# Self-healing injection of the Gemini AI service entry into the POV
# plugin's "My Services" menu
# (plugin.video.pov/resources/lib/modules/myservices.py).
#
# The POV plugin owns its own "Connect Services" UI that's separate
# from the wizard's login_menu. It iterates a hardcoded tuple of
# (name, AuthClass) pairs in modules.myservices.authorize() -- there
# is no public registration API for adding new services. To get our
# entries in there we patch the file on disk and re-inject on every
# Kodi startup, same pattern as darksubs_patcher and wizard_patcher.
#
# The injected service classes are dead simple: they read the
# matching key (api_key for Gemini, wyzie_api_key for Wyzie) from
# *our* addon's settings (service.subtitles.kodipovilai), prompt for
# input when unset, and clear it when set. They write back through
# xbmcaddon directly because POV's get_setting/set_setting operate
# on the POV addon's own settings, not ours.

import hashlib
import os
import re
import shutil

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import kodi_utils

POV_ADDON_ID = 'plugin.video.pov'
MYSERVICES_REL_PATH = 'resources/lib/modules/myservices.py'
POV_MEDIA_REL_PATH = 'resources/skins/Default/media'

# Source paths for the two icons we ship.
ICON_SRC_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'icons')
ICON_FILENAMES = ('gemini.png',)

INJECT_VERSION = 12
MARKER = '# AI_SUBS_MYSERVICES_INJECT_v{0}'.format(INJECT_VERSION)
END_MARKER = '# END AI_SUBS_MYSERVICES_INJECT_v{0}'.format(INJECT_VERSION)
TUPLE_MARKER = "# AI_SUBS_MYSERVICES_TUPLE_v{0}".format(INJECT_VERSION)
# Version log:
#   v1 (addon v0.1.8): placeholder tmdb.png / mdblist.png icons.
#   v2 (addon v0.1.9-v0.2.1): custom gemini.png / wyzie.png icons.
#   v3 (addon v0.2.2): Wyzie first-time setup dialog mentions that
#     the All_Subs addon makes Wyzie redundant.
#   v4 (addon v0.2.3): same dialog, but uses "DarkSubs" (the
#     display name the user actually sees) instead of "All_Subs"
#     (the addon-id / folder-name) which was confusing.
#   v5 (addon v0.2.11): Gemini auth dialog got a QR + inline
#     validation. The full flow lived in the injected code, which
#     meant every UX tweak required a patcher bump.
#   v6 (addon v0.2.12): Gemini class now just shells out to our
#     addon's action=connect_gemini handler. ALL the Gemini UI
#     (pair-from-phone vs type, key validation, retry, etc.)
#     lives in default.py going forward -- the patcher only
#     handles the "icon + click forwarder" pieces, which are
#     stable. Future Gemini UX changes won't touch this file.
#   v7 (addon v0.2.140): the replicated services tuple no longer
#     hardcodes POV's class names. POV 6.x renamed TMDbList to
#     TMDBList and dropped EasyDebrid, so after Kodi auto-updated
#     POV from its repo, the injected authorize() crashed with
#     NameError: name 'TMDbList' is not defined and the whole
#     "Connect Services" menu died. The wrapper now resolves each
#     candidate class through globals() at call time and silently
#     skips names the installed POV doesn't define.
#   v10 (addon v0.2.474): the debrid / Trakt rows now authorise through
#     Account Manager Lite (script.module.acctmgr) instead of POV
#     alone, so one click lands the account in EVERY add-on AM
#     supports -- POV and Umbrella among them -- not in POV only.
#     Same screen, same one-click feel, same number of rows: each
#     AM-backed row REPLACES the POV-native one it covers rather than
#     sitting beside it, because two rows both labelled "real-debrid"
#     is exactly the confusion this set out to avoid. POV's own class
#     stays as the fallback wherever AM is missing, and one clearly
#     marked row at the bottom still reaches the untouched POV-only
#     menu. Screen is in Hebrew from this version on.
#   v11 (addon v0.2.481): MDBList now subclasses POV's own native
#     MDBList instead of forwarding to our API-key pairing, so one
#     OAuth device authorisation covers POV and Umbrella both, and
#     the token is mirrored to Umbrella straight afterwards.
#   v12 (addon v0.2.483): the MDBList row reads POV's token before AND
#     after POV's own set(), so the mirror can be told a human really
#     authorised the service rather than declined a confirmation. It is
#     the only place with both sides of one click; every attempt to infer
#     it from outside reverted somebody's settings.
# Each bump triggers a one-time re-patch on the next Kodi startup;
# OLD_MARKERS lists every prior version's marker so the legacy
# blocks get stripped cleanly before the new one is injected.
OLD_MARKERS = [
    '# AI_SUBS_MYSERVICES_INJECT_v1',
    '# AI_SUBS_MYSERVICES_INJECT_v2',
    '# AI_SUBS_MYSERVICES_INJECT_v3',
    '# AI_SUBS_MYSERVICES_INJECT_v4',
    '# AI_SUBS_MYSERVICES_INJECT_v5',
    '# AI_SUBS_MYSERVICES_INJECT_v6',
    '# AI_SUBS_MYSERVICES_INJECT_v7',
    '# AI_SUBS_MYSERVICES_INJECT_v8',
    '# AI_SUBS_MYSERVICES_INJECT_v9',
    '# AI_SUBS_MYSERVICES_INJECT_v10',
    '# AI_SUBS_MYSERVICES_INJECT_v11',
]

# Two service classes plus a hook that monkey-patches authorize()
# to include them. We do NOT edit the authorize() function source --
# instead we wrap it after definition. Cleaner + survives most
# refactors of the inline tuple.
CLASS_BLOCK = '''\

{marker}
# Injected by service.subtitles.kodipovilai. See pov_services_patcher.py.

import xbmcaddon as _ai_xbmcaddon

_AI_AM_ID = 'script.module.acctmgr'

# Screen strings. Short on purpose -- this is the one place in the build a
# newcomer has to understand without being told, so every row says what it is
# and what a click will do, and nothing else.
_AI_TITLE = 'חיבור שירותים'
_AI_ON_ALL = 'מחובר ✓ · מסונכרן לכל התוספים'
_AI_OFF_ALL = 'לא מחובר · לחץ לחיבור בכל התוספים'
_AI_ON_POV_ONLY = 'מחובר ל-POV בלבד · לחץ לחיבור בכל התוספים'
_AI_ON_POV = 'מחובר ✓ · לחץ לניהול'
_AI_OFF_POV = 'לא מחובר · לחץ לחיבור'
_AI_ADVANCED = 'חיבור ל-POV בלבד (מתקדם)'
_AI_ADVANCED2 = 'התפריט המקורי של POV, ללא סנכרון לשאר התוספים'


def _ai_get_addon():
    try:
        return _ai_xbmcaddon.Addon('service.subtitles.kodipovilai')
    except Exception:
        return None


def _ai_am_addon():
    """Account Manager Lite's handle, or None when it is not installed.
    Instantiating the Addon is the only honest test -- System.HasAddon stays
    true for an add-on that is present but disabled."""
    try:
        return _ai_xbmcaddon.Addon(_AI_AM_ID)
    except Exception:
        return None


def _ai_am_run(action):
    """Hand off to Account Manager. Its auth actions already run the sync
    themselves (auth -> push to every installed add-on -> enable the startup
    re-sync), so we deliberately do NOT chain a ReSync after an Auth: that
    would sync the same account twice and show the user two progress runs."""
    try:
        import xbmc as _aix
        _aix.executebuiltin('RunScript(%s,action=%s)' % (_AI_AM_ID, action))
        return True
    except Exception as e:
        notification('Account Manager failed to start: %s' % str(e)[:60])
        return False


class Gemini:
    """Forwarder. The actual UX (pair vs type, validation, retry,
    TMDB nudge) lives in the addon's default.py under the
    `connect_gemini` action -- a separate Python invocation we
    spawn via RunScript. Keeping the injected code this small
    means future Gemini-flow tweaks don't require a patcher
    bump (which would re-run on every Kodi launch for every
    user)."""
    icon = 'gemini.png'  # copied into POV's media dir by pov_services_patcher

    def __init__(self):
        self._ai = _ai_get_addon()
        try:
            v = self._ai.getSetting('api_key') if self._ai else ''
        except Exception:
            v = ''
        self.token = (v or '').strip()

    def set(self):
        if not self._ai:
            notification('Kodi POV IL AI subtitles addon not installed')
            return
        # Hand off to our addon. RunScript spawns a new Python
        # process; the dialog comes from our default.py so it
        # has access to the full gemini_pair / gemini modules
        # without sys.path tricks.
        try:
            import xbmc as _aix
            _aix.executebuiltin(
                'RunScript(service.subtitles.kodipovilai,'
                'action=connect_gemini)')
        except Exception as e:
            notification('Failed to launch Gemini setup: %s' % str(e)[:60])
        # Returning True so POV's authorize() treats the click as
        # handled (not as a failure). The actual save/notify
        # happens in our default.py process.
        return True


def _ai_make_mdblist():
    """Build the MDBList row on top of POV's OWN MDBList class, or return
    None if this POV has not got one.

    Resolved through globals() at call time rather than written as
    `class _AiMDBList(MDBList)` at module level. That spelling is evaluated
    the moment this block is imported, so a POV release that renames or drops
    MDBList would raise NameError while the module was still loading and take
    the WHOLE Connect Services screen down -- every row, not just this one.
    That is the failure v7 of this patcher was written to end, when POV
    renamed TMDbList to TMDBList and dropped EasyDebrid; re-introducing it
    for MDBList would undo that lesson.

    What the class adds to POV's own is a single step. MDBList used to need
    connecting twice -- an API key here, a device code inside Umbrella --
    because when this row was first written POV's MDBList service was a bare
    keyboard prompt with no QR. POV 6.08 replaced that with the OAuth device
    flow, which is the SAME flow Umbrella uses and yields the same kind of
    token, so the separate pairing had no reason left to exist. POV's QR,
    polling, watched-indicator wiring and revoke path are all its own code,
    untouched; we only hand the resulting token on to Umbrella afterwards.
    """
    _base = globals().get('MDBList')
    if _base is None:
        return None

    class _AiMDBList(_base):
        icon = 'mdblist.png'  # POV's own MDBList icon (native service)

        def set(self):
            # Read POV's token on BOTH sides of the call.
            #
            # This is the only place in the build that sees a before and an
            # after for the SAME click, and that is what turns "a human just
            # authorised this" from a guess into a measurement. Three
            # attempts to infer it from outside failed, each silently
            # reverting a setting somebody had chosen: an empty Umbrella
            # token (Umbrella empties its own), "POV is connected right now"
            # (this row fires whatever the outcome, so a declined
            # confirmation counted), and "POV's token changed" (POV rotates
            # it on its own timer). Here none of those apply: a declined
            # confirmation leaves the token identical, a revoke leaves it
            # empty, and only a real authorisation replaces it with a new
            # non-empty value inside the few seconds of the click.
            #
            # get_setting is taken from POV's own module globals through
            # globals(), not imported: if a POV release ever renames it we
            # simply cannot tell, `fresh` stays False, and the behaviour is
            # exactly what it was before this existed. Nothing here may raise
            # -- this runs inside the Connect Services screen, where an
            # exception takes every row down, not just this one.
            _ai_gs = globals().get('get_setting')

            def _ai_tok():
                if _ai_gs is None:
                    return None
                try:
                    return (_ai_gs('mdblist.token') or '').strip()
                except Exception:
                    return None

            _ai_before = _ai_tok()
            result = _base.set(self)
            _ai_after = _ai_tok()
            _ai_fresh = bool(_ai_after and _ai_before is not None
                             and _ai_after != _ai_before)
            # Fired whatever the outcome: the revoke path returns early too,
            # and after a revoke POV's token is empty -- which the mirror
            # reads as "nothing to hand over" and leaves Umbrella's own
            # authorisation alone rather than tearing it down for POV.
            try:
                import xbmc as _aix
                _aix.executebuiltin(
                    'RunScript(service.subtitles.kodipovilai,'
                    'action=mdblist_mirror_umbrella%s)'
                    % (',connected=1' if _ai_fresh else ''))
            except Exception:
                pass
            return result

    # POV's watch_indicators decorator puts instance.__class__.__name__ into
    # the dialog it shows ("watched status will be set to <name>"), so without
    # this the user is told about "_AiMDBList". It is the same service; it
    # should say so.
    try:
        _AiMDBList.__name__ = _base.__name__
        _AiMDBList.__qualname__ = _base.__name__
    except Exception:
        pass
    return _AiMDBList


def _ai_am_service(prefix, icon_name, keys, title, pov_names):
    """Build a POV-shaped service class (class attribute `icon`, instance
    attribute `token`, method `set()`) that authorises through Account
    Manager instead of through POV alone.

    Why the indirection: POV's own classes write POV's settings and nothing
    else, so a user who connects Real-Debrid here still has to connect it
    again inside Umbrella, Fen, and every other add-on. AM writes all of them
    -- POV included -- from one authorisation. The row looks and behaves the
    same; only its reach changes.

    `pov_names` is used for DISPLAY only: when AM has no token but POV does,
    the row says so, instead of claiming "not connected" at somebody who
    connected POV natively last month."""
    class _AiAmService(object):
        icon = icon_name
        _prefix = prefix
        _keys = keys
        _title = title
        _pov_names = pov_names

        def __init__(self):
            self.token = ''
            self.pov_token = ''
            am = _ai_am_addon()
            if am is not None:
                try:
                    vals = [(am.getSetting(k) or '').strip()
                            for k in self._keys]
                except Exception:
                    vals = []
                # EVERY key must be set: Easynews needs user AND password,
                # and a half-filled pair is not a working account.
                if vals and all(vals):
                    self.token = ''.join(vals)
            if not self.token:
                self.pov_token = _ai_pov_token(self._pov_names)

        def label2(self):
            if self.token:
                return _AI_ON_ALL
            if self.pov_token:
                return _AI_ON_POV_ONLY
            return _AI_OFF_ALL

        def set(self):
            if _ai_am_addon() is None:
                notification('Account Manager is not installed')
                return
            if not self.token:
                return _ai_am_run(self._prefix + 'Auth')
            choice = kodi_utils.dialog.select(self._title, [
                'סנכרון החשבון לכל התוספים',
                'ניתוק החשבון מכל התוספים'])
            if choice < 0:
                return
            return _ai_am_run(
                self._prefix + ('ReSync' if choice == 0 else 'Revoke'))
    return _AiAmService


def _ai_pov_cls(names):
    """POV's own service class by name, newest spelling first, or None.
    Never name POV's classes directly: upstream renames and removes them
    between releases (5.x TMDbList + EasyDebrid, 6.x TMDBList and no
    EasyDebrid) and a hardcoded name used to take the whole menu down with
    NameError the moment Kodi auto-updated POV."""
    g = globals()
    for n in (names or ()):
        if n in g:
            return g[n]
    return None


def _ai_pov_token(names):
    cls = _ai_pov_cls(names)
    if cls is None:
        return ''
    try:
        return cls().token or ''
    except Exception:
        return ''


class _AiPovOnly:
    """Bottom row: POV's untouched original menu. It exists so that a failure
    anywhere in the Account Manager flow can never leave somebody unable to
    connect POV at all -- which, for this build, would be the worst outcome
    of the whole change. One clearly marked row is the price."""
    icon = 'settings.png'

    def __init__(self):
        self.token = ''

    def set(self):
        return _ai_orig_authorize()


# Replace authorize() with a wrapper that routes the debrid / Trakt rows
# through Account Manager and adds our own two services. We can't reliably
# regex-edit the inline tuple because the formatting might shift in upstream
# updates, so we wrap the function instead.
_ai_orig_authorize = authorize
def authorize():
    # One row per service, in the order they appear on screen. Columns:
    #   name        the label, upper-cased by the builder
    #   kind        'am'   -- Account Manager when installed, POV as fallback
    #               'pov'  -- POV's own class only (AM has no usable one)
    #               'ours' -- one of the two forwarders injected above
    #   icon        filename inside POV's own media folder
    #   prefix      AM's action prefix: <prefix>Auth / ReSync / Revoke
    #   keys        AM settings that hold the account; ALL must be non-empty
    #   pov         POV class names, newest spelling first
    #
    # THREE rows stay POV-only on purpose, each for its own reason:
    #
    #   trakt      -- AM 1.1.5a's traktAuth AND traktReSync both end in
    #                 os._exit(1): they FORCE-CLOSE KODI, after a 3-second
    #                 "Force Closing Kodi!" toast. That alone is why this row
    #                 stays POV-only -- POV's native Trakt connect does none
    #                 of it, and a build's main connect screen cannot kill
    #                 Kodi. Trakt-everywhere is still available to anyone who
    #                 wants it, from inside Account Manager, where the
    #                 force-close is at least in the add-on that causes it.
    #
    #                 The other two objections raised with AM's author were
    #                 answered, and the answers check out against 1.1.5a:
    #                   * the force-close is deliberate. AM rewrites the Trakt
    #                     handling inside the add-ons it supports and bypasses
    #                     their own authorisation, so they have to be restarted
    #                     to rebuild their Trakt databases, and a dialog could
    #                     be dismissed or stolen while a hard exit cannot.
    #                   * control.updates_off() is NOT permanent, which is what
    #                     an earlier version of this comment claimed. It parks
    #                     Kodi's add-on updates only until AM's own startup
    #                     work is done: startup.py run_addon_updates() calls
    #                     autoupdate_on() and then UpdateAddonRepos(), so the
    #                     setting comes back on the next start. Verified in the
    #                     shipped code, not taken on trust.
    #                 Answering "no" to its "create your sync list now?"
    #                 question falling off the end of the branch is a real bug
    #                 and its author has fixed it for the next release.
    #   easydebrid -- AM writes `easydebrid.token` but never DECLARES it in
    #                 its settings.xml, so the write is a silent no-op and its
    #                 EasyDebrid rows are absent from its own settings screen.
    #                 Routing it through AM would connect nothing.
    #   tmdblist   -- AM has no TMDb service at all.
    _ai_table = (
        ('trakt',        'pov',  'trakt.png',      None, (), ('Trakt',)),
        ('mdblist',      'ours', 'mdblist.png',    None, (), None),
        ('tmdblist',     'pov',  'tmdb.png',       None, (),
         ('TMDBList', 'TMDbList')),
        ('real-debrid',  'am',   'realdebrid.png', 'realdebrid',
         ('realdebrid.token',),                       ('RealDebrid',)),
        ('premiumize.me', 'am',  'premiumize.png', 'premiumize',
         ('premiumize.token',),                       ('Premiumize',)),
        ('alldebrid',    'am',   'alldebrid.png',  'alldebrid',
         ('alldebrid.token',),                        ('AllDebrid',)),
        ('torbox',       'am',   'torbox.png',     'torbox',
         ('torbox.token',),                           ('TorBox',)),
        ('offcloud',     'am',   'offcloud.png',   'offcloud',
         ('offcloud.token',),                         ('Offcloud',)),
        ('easydebrid',   'pov',  'easydebrid.png', None, (), ('EasyDebrid',)),
        ('easynews',     'am',   'easynews.png',   'easynews',
         ('easynews.username', 'easynews.password'),  ('EasyNews',)),
        ('gemini-ai',    'ours', 'gemini.png',     None, (), None),
    )
    # Built at call time; None when this POV has no MDBList class, in which
    # case the row is simply left out rather than crashing the screen.
    _ai_mdblist_cls = _ai_make_mdblist()
    _ai_ours = {'gemini-ai': Gemini}
    if _ai_mdblist_cls is not None:
        _ai_ours['mdblist'] = _ai_mdblist_cls
    _ai_am_ok = _ai_am_addon() is not None

    _ai_services = []
    for _ai_name, _ai_kind, _ai_icon, _ai_pfx, _ai_keys, _ai_pov in _ai_table:
        if _ai_kind == 'ours':
            _ai_cls_ours = _ai_ours.get(_ai_name)
            if _ai_cls_ours is not None:
                _ai_services.append((_ai_name, _ai_cls_ours))
            continue
        if _ai_kind == 'am' and _ai_am_ok:
            _ai_services.append((_ai_name, _ai_am_service(
                _ai_pfx, _ai_icon, _ai_keys, _ai_name.upper(), _ai_pov)))
            continue
        # 'pov', or 'am' with no Account Manager installed
        _ai_cls = _ai_pov_cls(_ai_pov)
        if _ai_cls is not None:
            _ai_services.append((_ai_name, _ai_cls))
    if _ai_am_ok:
        _ai_services.append((_AI_ADVANCED, _AiPovOnly))

    def _builder():
        for name, api in services:
            item = kodi_utils.make_listitem()
            # No [B]..[/B] of our own. The select dialog's focused row is
            # already emphasised by the skin, which wraps the label in its
            # own bold tag -- and a bold tag inside a bold tag came back
            # from the field rendering the leftover "[/B]" as literal text
            # on whichever row happened to be focused.
            item.setLabel(name.upper())
            try:
                inst = api()
            except Exception:
                inst = None
            if inst is None:
                sub = ''
            elif api is _AiPovOnly:
                sub = _AI_ADVANCED2
            elif hasattr(inst, 'label2'):
                sub = inst.label2()
            else:
                sub = _AI_ON_POV if inst.token else _AI_OFF_POV
            item.setLabel2(sub)
            item.setArt({'icon': '%s%s' % (icon_path, api.icon)})
            yield(item)

    icon_path = kodi_utils.media_path()
    services = tuple(_ai_services)
    service = kodi_utils.dialog.select(
        _AI_TITLE, list(_builder()), useDetails=True)
    if service < 0: return
    try: success = services[service][1]().set()
    except Exception as e: kodi_utils.logger('myservices error', str(e))
    else: return success
    return notification(32574)
{end_marker}
'''
# Replace the marker placeholders without using .format() -- the
# injected code body itself uses '{0}'-style placeholders inside
# its own .format() calls, and a single outer .format() would try
# to interpret those too and crash with IndexError.
CLASS_BLOCK = CLASS_BLOCK.replace('{marker}', MARKER) \
                         .replace('{end_marker}', END_MARKER)


def _myservices_path():
    if xbmcvfs is None:
        return None
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/{0}/{1}'.format(
                POV_ADDON_ID, MYSERVICES_REL_PATH))
    except Exception:
        return None


def _pov_media_dir():
    if xbmcvfs is None:
        return None
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/{0}/{1}'.format(
                POV_ADDON_ID, POV_MEDIA_REL_PATH))
    except Exception:
        return None


def _sha1(path):
    try:
        h = hashlib.sha1()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _ensure_icons_copied():
    """Copy gemini.png + wyzie.png from our addon's icons dir into
    POV's media folder if missing or different. Idempotent.

    Returns the number of icons newly written (0 = no change needed).
    """
    media_dir = _pov_media_dir()
    if not media_dir or not os.path.isdir(media_dir):
        return 0
    written = 0
    for name in ICON_FILENAMES:
        src = os.path.join(ICON_SRC_DIR, name)
        if not os.path.isfile(src):
            kodi_utils.log(
                'pov_services_patcher: icon source missing: {0}'.format(
                    src), level='WARNING')
            continue
        dst = os.path.join(media_dir, name)
        if os.path.isfile(dst) and _sha1(src) == _sha1(dst):
            continue  # already up to date
        try:
            tmp = dst + '.aitmp'
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
            written += 1
            kodi_utils.log(
                'pov_services_patcher: installed icon {0}'.format(name),
                level='INFO')
        except OSError as e:
            kodi_utils.log(
                'pov_services_patcher: icon copy failed {0}: {1}'
                .format(name, e), level='WARNING')
    return written


def ensure_patched():
    # Always make sure the icons are in place, even when myservices.py
    # is already patched -- handles the case where the icons got
    # blown away by a POV update but the marker block in the .py is
    # still there.
    _ensure_icons_copied()

    p = _myservices_path()
    if not p or not os.path.isfile(p):
        return 'no_pov'
    try:
        with open(p, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        kodi_utils.log(
            'pov_services_patcher: read failed: {0}'.format(e),
            level='WARNING')
        return 'read_failed'
    if MARKER in content:
        return 'already_patched'

    # Sanity: confirm authorize() and the expected service classes
    # are present in the file. If POV refactored the menu away from
    # this pattern, bail without touching it.
    if 'def authorize():' not in content:
        return 'unmatched'
    for cls in ('class Trakt', 'class RealDebrid', 'class Premiumize'):
        if cls not in content:
            kodi_utils.log(
                'pov_services_patcher: {0} not found, skipping'.format(
                    cls), level='WARNING')
            return 'unmatched'

    # Strip old-version markers if we ever bump.
    for old in OLD_MARKERS:
        old_end = old.replace('AI_SUBS_MYSERVICES_INJECT',
                              'END AI_SUBS_MYSERVICES_INJECT', 1)
        pattern = re.compile(
            r'^[ \t]*' + re.escape(old) + r'\b.*?^[ \t]*'
            + re.escape(old_end) + r'\b[^\n]*\n',
            re.MULTILINE | re.DOTALL,
        )
        content = pattern.sub('', content)

    if not content.endswith('\n'):
        content += '\n'
    new_content = content + CLASS_BLOCK

    tmp_path = p + '.aitmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp_path, p)
    except OSError as e:
        kodi_utils.log(
            'pov_services_patcher: write failed: {0}'.format(e),
            level='WARNING')
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return 'write_failed'
    kodi_utils.log(
        'pov_services_patcher: injected v{0} into POV myservices'.format(
            INJECT_VERSION),
        level='INFO')
    return 'patched'
