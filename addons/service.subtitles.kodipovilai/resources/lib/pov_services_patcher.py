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

INJECT_VERSION = 8
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
]

# Two service classes plus a hook that monkey-patches authorize()
# to include them. We do NOT edit the authorize() function source --
# instead we wrap it after definition. Cleaner + survives most
# refactors of the inline tuple.
CLASS_BLOCK = '''\

{marker}
# Injected by service.subtitles.kodipovilai. See pov_services_patcher.py.

import xbmcaddon as _ai_xbmcaddon


def _ai_get_addon():
    try:
        return _ai_xbmcaddon.Addon('service.subtitles.kodipovilai')
    except Exception:
        return None


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



# Replace authorize() with a wrapper that adds our two services to
# the menu. We can't reliably regex-edit the inline tuple because
# the formatting might shift in upstream updates, so we wrap the
# function instead.
_ai_orig_authorize = authorize
def authorize():
    _ai_extra = (('gemini-ai', Gemini),)
    # Monkey-patch the module's `_builder` indirectly by replicating
    # authorize()'s logic exactly, but with our extras appended to
    # the services list. (We can't just call _orig_authorize and
    # then patch -- the dialog gets built INSIDE the function and
    # we'd have already shown the original.)
    def _builder():
        for name, api in services:
            item = kodi_utils.make_listitem()
            item.setLabel('[B]%s[/B]' % name.upper())
            item.setLabel2(auth_str if api().token else noauth_str)
            item.setArt({'icon': '%s%s' % (icon_path, api.icon)})
            yield(item)
    icon_path = kodi_utils.media_path()
    # Resolve POV's own service classes dynamically instead of naming
    # them directly. Upstream renames/removes classes between releases
    # (POV 5.x: TMDbList + EasyDebrid, POV 6.x: TMDBList, no
    # EasyDebrid) and a hardcoded name crashes the whole menu with
    # NameError after Kodi auto-updates POV. Each entry lists the
    # known spellings, newest first; entries the installed POV does
    # not define are skipped.
    _ai_candidates = (
        ('trakt', ('Trakt',)),
        ('mdblist', ('MDBList',)),
        ('tmdblist', ('TMDBList', 'TMDbList')),
        ('real-debrid', ('RealDebrid',)),
        ('premiumize.me', ('Premiumize',)),
        ('alldebrid', ('AllDebrid',)),
        ('torbox', ('TorBox',)),
        ('offcloud', ('Offcloud',)),
        ('easydebrid', ('EasyDebrid',)),
        ('easynews', ('EasyNews',)),
    )
    _ai_g = globals()
    _ai_services = []
    for _ai_name, _ai_classes in _ai_candidates:
        for _ai_cls in _ai_classes:
            if _ai_cls in _ai_g:
                _ai_services.append((_ai_name, _ai_g[_ai_cls]))
                break
    services = tuple(_ai_services) + _ai_extra
    service = kodi_utils.dialog.select('My Services', list(_builder()), useDetails=True)
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
