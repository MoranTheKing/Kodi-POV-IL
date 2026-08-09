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
# Both halves are defensive: settings writes are wrapped, the code patch is
# compile()-checked before it is written, prior versions are reverted then
# re-applied, and an Umbrella update that restructures the anchor makes us
# skip with a log line instead of guessing.

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


UMBRELLA_ADDON_ID = 'plugin.video.umbrella'
SOURCES_REL_PATH = 'resources/lib/modules/sources.py'

COCO_MODULE = 'script.module.cocoscrapers'
COCO_NAME = 'cocoscrapers'
PROVIDER_DONE_SETTING = '_umbrella_coco_wired_v1'

# CocoScrapers ships with 4 of its 14 providers on (torrentio, bitsearch,
# eztv, torrentdownload) -- the other ten sit unused unless the user goes
# hunting through its settings. These two are aggregators that pull from
# indexers the shipped four do not reach, and neither needs any credential
# or URL of its own, so they are the two that pay off with nothing to
# configure. Deliberately just these two for now: providers run in parallel,
# but adding them is still the one change in flight, so any change in how
# long a search takes can be attributed to them and to nothing else.
# Turned on ONCE, behind our own marker -- a user who switches either back
# off keeps that choice, and every other provider is left exactly as it is.
COCO_PROVIDERS = ('provider.comet', 'provider.mediafusion')
COCO_PROVIDERS_DONE_SETTING = '_umbrella_coco_providers_v1'

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
    try:
        addon.setSetting('external_provider.module', COCO_MODULE)
        addon.setSetting('external_provider.name', COCO_NAME)
        # enabled LAST: Umbrella's checkModules() blanks both names whenever it
        # sees the toggle off, so writing the toggle first could wipe them.
        addon.setSetting('provider.external.enabled', 'true')
    except Exception as e:
        _log('could not wire CocoScrapers: {0}'.format(e), 'WARNING')
        return 'write_failed'
    try:
        from resources.lib import kodi_utils as _ku
        _ku.set_setting(PROVIDER_DONE_SETTING, 'done')
    except Exception:
        pass
    _log('CocoScrapers wired as Umbrella\'s external provider')
    return 'patched'


def ensure_coco_providers():
    """Switch on the two extra CocoScrapers providers, once. Returns a short
    status string; never raises."""
    try:
        import xbmcaddon
        coco = xbmcaddon.Addon(COCO_MODULE)
    except Exception:
        return 'not_installed'
    try:
        from resources.lib import kodi_utils as _ku
        if (_ku.get_setting(COCO_PROVIDERS_DONE_SETTING, '') or '') == 'done':
            return 'unchanged'
    except Exception:
        pass
    turned_on = []
    for key in COCO_PROVIDERS:
        try:
            if (coco.getSetting(key) or '').strip().lower() != 'true':
                coco.setSetting(key, 'true')
                turned_on.append(key.split('.', 1)[-1])
        except Exception as e:
            _log('could not enable {0}: {1}'.format(key, e), 'WARNING')
    try:
        from resources.lib import kodi_utils as _ku
        _ku.set_setting(COCO_PROVIDERS_DONE_SETTING, 'done')
    except Exception:
        pass
    if turned_on:
        _log('CocoScrapers providers enabled: ' + ', '.join(turned_on))
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
        with open(path, 'r', encoding='utf-8') as f:
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
