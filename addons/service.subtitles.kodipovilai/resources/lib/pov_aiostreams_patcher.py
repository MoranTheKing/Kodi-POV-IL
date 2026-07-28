# Stop a switched-on-but-unusable AIOStreams from swallowing every scrape.
#
# THE BUG THIS FIXES (POV 6.07.92, "No Results" on every movie and episode):
#
#   modules/settings.py:
#       def active_internal_scrapers():
#           if get_setting('provider.aiostreams') == 'true': return ['aiostreams']
#           ...everything else...
#
# That first line is not a filter, it is a takeover: when provider.aiostreams
# is on, aiostreams becomes the ONLY scraper POV will consider. External
# (torrentio/comet/...), the debrid cloud scrapers and easynews are all dropped
# -- modules/sources.py keys three separate decisions off the same list
# (activate_external() returns immediately, ResultsProcessor.process() skips
# every filter, and collect_results() never reaches the external manager).
#
# And the aiostreams scraper itself opens with:
#       if not all(self.auth): return internal_results(...)   # auth = (aio.username, aio.password)
# i.e. with no credentials it returns nothing, instantly, silently, without a
# single network request. The visible result is POV's progress window flashing
# open and shut in ~20ms followed by "No Results" -- for every title, forever.
#
# WHY IT SUDDENLY STARTED: POV removed aiostreams in 6.04 and brought it back
# in 6.07. Kodi keeps a setting's stored value in the profile even while the
# add-on stops declaring it, so a profile that had provider.aiostreams=true
# back in the 6.03 era carried that 'true' silently through every version in
# between -- and 6.07 handed it back its meaning. Nothing the user did.
#
# THE FIX, two independent halves so either one alone is enough:
#   1. settings.py's takeover line gains an "...and we actually have
#      credentials" test. Credentials present -> POV behaves exactly as its
#      author wrote it. Absent -> the scraper that cannot return anything no
#      longer gets to be the only one asked.
#   2. The stored setting is turned back off, so POV's own settings screen
#      agrees with what is happening and the takeover cannot come back on the
#      next POV update that resets our file edits.
#
# Both halves are strictly conditional on the credentials being EMPTY, so a
# user who genuinely uses AIOStreams is never touched.
#
# Marker-gated, compile()-checked, atomic, .pyc dropped. No-op if POV isn't
# installed or the anchor changed upstream.

import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    import xbmcaddon
except Exception:
    xbmcaddon = None

try:
    import xbmcgui
except Exception:
    xbmcgui = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
SETTINGS_REL = 'resources/lib/modules/settings.py'
MARKER = '# AI_SUBS_POV_AIOSTREAMS_v1'

ENABLE_SETTING = 'provider.aiostreams'
CRED_SETTINGS = ('aio.username', 'aio.password')

# POV's takeover line, verbatim (one tab of indent, inside
# active_internal_scrapers()).
_ANCHOR = (
    "\tif get_setting('provider.aiostreams') == 'true': return ['aiostreams']"
)
_INJECT = (
    "\tif get_setting('provider.aiostreams') == 'true' and all("
    "(get_setting('aio.username'), get_setting('aio.password'))): "
    "return ['aiostreams']  " + MARKER
)

# Put ANY earlier version of our line back to POV's own before injecting the
# current one, so bumping the marker replaces the edit instead of leaving a
# stale form of it behind.
_REVERT_RE = re.compile(
    r"[ \t]*if get_setting\('provider\.aiostreams'\)[^\r\n]*"
    r"#[ \t]*AI_SUBS_POV_AIOSTREAMS_v\d+[^\r\n]*"
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_aiostreams_patcher: ' + msg, level=level)
    except Exception:
        pass


def _settings_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *SETTINGS_REL.split('/'))
    return p if os.path.isfile(p) else ''


def _pov_addon():
    if xbmcaddon is None:
        return None
    try:
        return xbmcaddon.Addon(POV_ADDON_ID)
    except Exception:
        return None


def _has_credentials(addon):
    """True only when BOTH aiostreams credentials are set -- the same test the
    scraper itself makes before it will do anything at all."""
    for key in CRED_SETTINGS:
        try:
            value = (addon.getSetting(key) or '').strip()
        except Exception:
            return True  # can't tell -- assume configured and keep hands off
        if not value:
            return False
    return True


def disarm_setting():
    """Half 2: turn provider.aiostreams back off when it is on with no
    credentials. Returns 'off' | 'configured' | 'no_pov' | 'disarmed'
    | 'failed'."""
    addon = _pov_addon()
    if addon is None:
        return 'no_pov'
    try:
        enabled = (addon.getSetting(ENABLE_SETTING) or '').strip().lower()
    except Exception:
        return 'failed'
    if enabled != 'true':
        return 'off'
    if _has_credentials(addon):
        return 'configured'
    try:
        addon.setSetting(ENABLE_SETTING, 'false')
    except Exception as e:
        _log('could not turn provider.aiostreams off: {0}'.format(e),
             level='WARNING')
        return 'failed'
    # POV reads its settings from a JSON snapshot cached in a window property
    # (modules.kodi_utils.SettingsManager). Dropping the property makes the
    # next read rebuild it, so this takes effect without a Kodi restart.
    if xbmcgui is not None:
        try:
            xbmcgui.Window(10000).clearProperty('pov_settings')
        except Exception:
            pass
    _log('provider.aiostreams was ON with no aio.username/aio.password -- '
         'that makes aiostreams the ONLY scraper POV asks, and it answers '
         'nothing without credentials ("No Results" on every title). '
         'Turned it off.', level='INFO')
    return 'disarmed'


def ensure_patched():
    """Half 1: the source edit. Returns 'patched' | 'already_patched'
    | 'no_pov' | 'no_file' | 'unmatched' | 'compile_failed' | 'read_failed'
    | 'write_failed'."""
    path = _settings_path()
    if not path:
        return 'no_pov' if xbmcvfs is None else 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except (OSError, UnicodeDecodeError) as e:
        # Not only OSError: a settings.py that is not valid UTF-8 (a truncated
        # or half-written POV update) would otherwise raise straight out of a
        # function whose whole contract is that every outcome is a status
        # string.
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'already_patched'

    # Both the anchor and the replacement are a SINGLE line with no line
    # terminator of their own, so this works unchanged on CRLF files -- there
    # is no newline in either string to translate.
    anchor = _ANCHOR
    inject = _INJECT

    # Replace via a function, not a template: a plain string replacement would
    # have re interpret any backslash escape in it. There is none today, but a
    # later edit to the anchor should not be able to introduce one silently.
    content = _REVERT_RE.sub(lambda _m: anchor, content)
    if anchor not in content:
        _log('active_internal_scrapers aiostreams line not found -- leaving '
             'alone', level='WARNING')
        return 'unmatched'

    new_content = content.replace(anchor, inject, 1)
    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'

    pycache_dir = os.path.join(os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache_dir):
        for fn in os.listdir(pycache_dir):
            if fn.startswith('settings.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache_dir, fn))
                except OSError:
                    pass

    _log('an AIOStreams with no credentials can no longer take over the '
         'scraper list', level='INFO')
    return 'patched'
