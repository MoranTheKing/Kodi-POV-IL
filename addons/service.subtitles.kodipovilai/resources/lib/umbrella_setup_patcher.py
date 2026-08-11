# Two independent, self-healing fixes for the opt-in Umbrella pilot.
#
# 1) EXTERNAL PROVIDER (settings only).
#    We ship CocoScrapers inside the Umbrella pack, but Umbrella starts with
#    "Enable External Providers" off and no provider chosen -- the user has to
#    find Providers -> External Providers and pick it by hand, and until they
#    do, Umbrella scrapes with far less than it could. Since the pack put
#    CocoScrapers on disk for exactly this purpose, we wire it up once:
#      provider.external.enabled = true
#      external_provider.module  = script.module.cocoscrapers
#      external_provider.name    = cocoscrapers        (Umbrella imports this)
#    Those are precisely the three values Umbrella's own picker writes (see
#    its tools.external_providers), so nothing here is a private arrangement.
#    Done ONCE, behind our own marker: a user who later turns it off or picks
#    a different provider keeps their choice, and Umbrella's own checkModules()
#    (which blanks the two names when the toggle is off) is never fought.
#
# 2) PICKED-SOURCE RELEASE NAME (code patch).
#    Our subtitle matcher scores a Hebrew subtitle against the release name of
#    the file being played. It reads that name from Window(10000), and POV
#    publishes it via pov_source_name_patcher. Umbrella publishes nothing, so
#    the matcher falls back to the URL basename: fine for AllDebrid/RD (the
#    release name is in the path) but useless for TorBox and other CDNs whose
#    URL is an opaque uuid -- every subtitle scores 0%.
#    Umbrella resolves a picked source in playItem(): the loop runs
#    sourcesResolve in a thread, then tests `if not self.url: continue`. At
#    that one line the resolved URL AND the picked source dict are both in
#    scope, which is exactly the pair POV publishes, so that is where we
#    publish. Same two property names the matcher already consumes -- no
#    change on the consumer side, and none is Umbrella-specific.
#
# 3) UMBRELLA DEFAULTS (settings only) -- two values that are worth having on
#    but that Umbrella ships off, applied once behind a marker like the rest.
#
# Both halves are defensive: settings writes are wrapped, the code patch is
# compile()-checked before it is written, prior versions are reverted then
# re-applied, and an Umbrella update that restructures the anchor makes us
# skip with a log line instead of guessing.
#
# EVERY settings write here goes through addon_settings_safe.apply(), never
# straight through xbmcaddon: a plain setSetting on somebody else's add-on
# makes Kodi re-serialise that add-on's WHOLE settings.xml, which can hand a
# setting we never named back its default. See addon_settings_safe.py.

import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None

try:
    from resources.lib import addon_settings_safe
except Exception:
    addon_settings_safe = None


UMBRELLA_ADDON_ID = 'plugin.video.umbrella'
SOURCES_REL_PATH = 'resources/lib/modules/sources.py'

COCO_MODULE = 'script.module.cocoscrapers'
COCO_NAME = 'cocoscrapers'
PROVIDER_DONE_SETTING = '_umbrella_coco_wired_v1'

# Umbrella mutes its own settings monitor with this home-window property
# while it writes settings itself (see its control.setSettingsDict). Driving
# it the same way keeps our writes from running its change handler once per
# key -- that handler clears its settings cache, re-parses the file and
# re-reads every context-menu property each time.
UMBRELLA_GUARD_PROPERTY = 'umbrella.updateSettings'

# CocoScrapers ships with 4 of its 16 providers on (torrentio, bitsearch,
# eztv, torrentdownload) -- the rest sit unused unless the user goes hunting
# through its settings. These five need no credential, no API key and no URL
# of their own, so they pay off with nothing to configure: comet and
# mediafusion are aggregators reaching indexers the shipped four do not, and
# knaben, torrentgalaxy and 1337x are plain indexers with their own catalogues.
# comet and mediafusion went out first, on their own, so the cost of adding
# them could be measured against nothing else in flight -- that came back at
# about 4-5 seconds a search, which is the budget the remaining three are
# joining. Everything left off needs a credential, a self-hosted URL or is
# anime-only, which is a per-user decision and not a default.
COCO_PROVIDERS = (
    'provider.comet',
    'provider.mediafusion',
    'provider.knaben',
    'provider.torrentgalaxy',
    'provider.1337x',
)
# Turned on ONCE EACH. The marker holds the keys we have already switched on
# rather than a plain "done", so a provider a user has since turned back off
# is never switched on again, while a provider added to the list later still
# reaches devices that took the earlier round.
COCO_PROVIDERS_DONE_SETTING = '_umbrella_coco_providers_v2'
# ...and the round that shipped as a plain 'done' flag covered exactly these.
COCO_PROVIDERS_LEGACY_SETTING = '_umbrella_coco_providers_v1'
COCO_PROVIDERS_LEGACY_KEYS = ('provider.comet', 'provider.mediafusion')

# Two Umbrella values that are worth having on but that Umbrella ships off.
#   sources.retryall -- when a picked source fails to play, try the next one
#     instead of dropping the user back to an empty screen. A dead link is
#     the single most common thing that goes wrong at play time and this is
#     the difference between "it just played" and "it did nothing".
#   scrapers.timeout -- the ceiling on a source search, not its length:
#     Umbrella stops the moment every provider has answered, and a full
#     search measures about 4-5 seconds. The shipped 60 is only ever reached
#     by a provider that has stopped answering, so it is 60 seconds of
#     watching a progress bar for nothing. 45 keeps roughly nine times the
#     headroom a real search needs while cutting a hung one short sooner.
# Applied once each, and the timeout only while it still reads exactly what
# Umbrella shipped -- a user who has already moved that slider has said what
# they want and we do not argue.
UMBRELLA_DEFAULTS = (
    ('sources.retryall', 'true', None),
    ('scrapers.timeout', '45', '60'),
)
UMBRELLA_DEFAULTS_DONE_SETTING = '_umbrella_defaults_v1'


MARKER = '# AI_SUBS_UMBRELLA_SOURCE_NAME_v1'

# The single line in playItem() that means "this picked source resolved".
_ANCHOR = "\t\t\t\t\tif not self.url: continue\n"

_REVERT_RE = re.compile(
    r"[ \t]*#[ \t]*AI_SUBS_UMBRELLA_SOURCE_NAME_v\d+.*?except Exception: pass[ \t]*\r?\n",
    re.DOTALL,
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('umbrella_setup_patcher: ' + msg, level=level)
    except Exception:
        pass


def _addon():
    try:
        import xbmcaddon
        return xbmcaddon.Addon(UMBRELLA_ADDON_ID)
    except Exception:
        return None


def ensure_external_provider():
    """Point Umbrella at the CocoScrapers we ship with it, once. Returns a
    short status string; never raises."""
    addon = _addon()
    if addon is None:
        return 'not_installed'
    try:
        from resources.lib import kodi_utils as _ku
        if (_ku.get_setting(PROVIDER_DONE_SETTING, '') or '') == 'done':
            return 'unchanged'
    except Exception:
        pass
    # Only wire it if CocoScrapers is really on disk -- pointing Umbrella at a
    # missing module would make it warn on every source search.
    if xbmcvfs is not None:
        try:
            p = xbmcvfs.translatePath(
                'special://home/addons/' + COCO_MODULE + '/addon.xml')
            if not os.path.isfile(p):
                return 'no_cocoscrapers'
        except Exception:
            return 'no_cocoscrapers'
    if addon_settings_safe is None:
        return 'write_failed'
    # enabled LAST: Umbrella's checkModules() blanks both names whenever it
    # sees the toggle off, so writing the toggle first could wipe them.
    changed, _, failed = addon_settings_safe.apply(
        UMBRELLA_ADDON_ID,
        (('external_provider.module', COCO_MODULE),
         ('external_provider.name', COCO_NAME),
         ('provider.external.enabled', 'true')),
        guard_property=UMBRELLA_GUARD_PROPERTY)
    if failed:
        # Half-wired is worse than unwired, and marking it done would make
        # that permanent. Leave the marker off so the next startup retries.
        _log('CocoScrapers not fully wired ({0}) -- will retry next startup'
             .format(', '.join(failed)), 'WARNING')
        return 'write_failed'
    # Marker goes down even when there was nothing to change: having looked
    # once is the point. Without it, a user who later turns External Providers
    # back off would find us turning it on again at the next startup.
    try:
        from resources.lib import kodi_utils as _ku
        _ku.set_setting(PROVIDER_DONE_SETTING, 'done')
    except Exception:
        pass
    if not changed:
        return 'unchanged'
    _log('CocoScrapers wired as Umbrella\'s external provider')
    return 'patched'


def _already_done(marker_setting):
    """The keys this marker says we have already applied once."""
    try:
        from resources.lib import kodi_utils as _ku
        raw = _ku.get_setting(marker_setting, '') or ''
    except Exception:
        return set()
    return set(k for k in (p.strip() for p in raw.split(',')) if k)


def _record_done(marker_setting, keys):
    try:
        from resources.lib import kodi_utils as _ku
        _ku.set_setting(marker_setting, ','.join(sorted(keys)))
    except Exception:
        pass


def ensure_coco_providers():
    """Switch on the extra CocoScrapers providers, once each. Returns a short
    status string; never raises."""
    try:
        import xbmcaddon
        xbmcaddon.Addon(COCO_MODULE)
    except Exception:
        return 'not_installed'
    if addon_settings_safe is None:
        return 'write_failed'
    done = _already_done(COCO_PROVIDERS_DONE_SETTING)
    if not done:
        # First run under the per-key marker. Devices that took the earlier
        # round carry a plain 'done' flag, and it stood for exactly the two
        # providers that round shipped -- inherit that, so those two are not
        # switched back on for anyone who has since switched them off.
        try:
            from resources.lib import kodi_utils as _ku
            if (_ku.get_setting(COCO_PROVIDERS_LEGACY_SETTING, '')
                    or '') == 'done':
                done = set(COCO_PROVIDERS_LEGACY_KEYS)
        except Exception:
            pass
    todo = [k for k in COCO_PROVIDERS if k not in done]
    if not todo:
        return 'unchanged'
    changed, _, failed = addon_settings_safe.apply(
        COCO_MODULE, tuple((k, 'true') for k in todo))
    # Only what really landed is recorded as done -- a provider whose write
    # failed stays on the list and is tried again at the next startup, instead
    # of being written off forever on one bad boot.
    _record_done(COCO_PROVIDERS_DONE_SETTING,
                 done | set(k for k in todo if k not in failed))
    if changed:
        _log('CocoScrapers providers enabled: '
             + ', '.join(k.split('.', 1)[-1] for k in changed))
        return 'patched'
    return 'unchanged'


def ensure_umbrella_defaults():
    """Apply the handful of Umbrella values worth having on, once each.
    Returns a short status string; never raises."""
    addon = _addon()
    if addon is None:
        return 'not_installed'
    if addon_settings_safe is None:
        return 'write_failed'
    done = _already_done(UMBRELLA_DEFAULTS_DONE_SETTING)
    wanted = []
    seen = set()
    for key, value, only_if in UMBRELLA_DEFAULTS:
        seen.add(key)
        if key in done:
            continue
        if only_if is not None:
            # Guarded value: touch it only while it still reads exactly what
            # Umbrella shipped. Anything else is a choice somebody made.
            try:
                if (addon.getSetting(key) or '').strip() != only_if:
                    continue
            except Exception:
                continue
        wanted.append((key, value))
    if not wanted:
        # Nothing to write, but we did look -- and a key whose guard said
        # "the user has moved this, leave it" is settled for good. Recording
        # it is what stops us revisiting the decision if they later happen to
        # put the slider back where Umbrella shipped it.
        _record_done(UMBRELLA_DEFAULTS_DONE_SETTING, done | seen)
        return 'unchanged'
    changed, _, failed = addon_settings_safe.apply(
        UMBRELLA_ADDON_ID, tuple(wanted),
        guard_property=UMBRELLA_GUARD_PROPERTY)
    # Everything we settled is marked -- what we wrote, and what the guard
    # told us to leave alone. Not what we tried and failed to write.
    _record_done(UMBRELLA_DEFAULTS_DONE_SETTING,
                 done | set(k for k in seen if k not in failed))
    if changed:
        _log('Umbrella defaults applied: ' + ', '.join(changed))
        return 'patched'
    return 'unchanged'


def _sources_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + UMBRELLA_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *SOURCES_REL_PATH.split('/'))
    return p if os.path.isfile(p) else ''


def _block(eol):
    t = '\t' * 5
    raw = [
        MARKER + ' -- publish the picked release name for the subtitle matcher',
        'try:',
        '\timport xbmcgui as _ai_g',
        '\t_ai_w = _ai_g.Window(10000)',
        "\t_ai_n = (resolve_items[i].get('name') or '') if isinstance(resolve_items[i], dict) else ''",
        '\tif _ai_n:',
        "\t\t_ai_w.setProperty('subs.player_filename', _ai_n)",
        "\t\t_ai_w.setProperty('pov_picked_source_name', _ai_n)",
        "\t\t_ai_w.setProperty('pov_picked_source_url', self.url or '')",
        'except Exception: pass',
    ]
    return ''.join(t + ln + eol for ln in raw)


def ensure_source_name_published():
    """Make Umbrella publish the picked source's release name + URL, the way
    POV does, so subtitle matching works for opaque CDN links too. Returns a
    short status string; never raises."""
    path = _sources_path()
    if not path:
        return 'not_installed'
    try:
        # newline='' or Python's universal-newline translation strips every
        # \r on the way in, while the write below is raw -- so patching a
        # CRLF copy of this file would rewrite the WHOLE file as LF, not just
        # the inserted lines. sources.py ships LF today, but the Umbrella pack
        # this build installs already ships two of its siblings as CRLF, and
        # an Umbrella self-update can flip it either way.
        with open(path, 'r', encoding='utf-8', newline='') as f:
            original = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), 'WARNING')
        return 'read_failed'
    if MARKER in original:
        return 'unchanged'
    eol = '\r\n' if '\r\n' in original[:4096] else '\n'
    content = _REVERT_RE.sub('', original)
    anchor = _ANCHOR if eol == '\n' else _ANCHOR.replace('\n', eol)
    n = content.count(anchor)
    if n != 1:
        _log('playItem resolved-source anchor found {0} time(s), need 1 -- '
             'Umbrella restructured; leaving the file alone'.format(n),
             'WARNING')
        return 'unmatched'
    new_content = content.replace(anchor, anchor + _block(eol), 1)
    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
             'WARNING')
        return 'compile_failed'
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(new_content)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), 'WARNING')
        return 'write_failed'
    _log('Umbrella now publishes the picked release name for subtitle matching')
    return 'patched'
