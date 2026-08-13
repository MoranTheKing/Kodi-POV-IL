# Make POV survive the seconds in which Kodi says it does not exist.
#
# Kodi's enabled flag flips the moment Addons.SetAddonEnabled returns, but its
# add-on manager catches up a couple of seconds later -- and in between,
# xbmcaddon.Addon('plugin.video.pov') raises "Unknown addon id". Kodi starts
# the add-on's own service script at the FIRST of those two moments, so POV's
# service runs head-first into a window in which POV cannot read its own
# settings. From a field log (2026-08-13 21:40):
#
#   Error Type: <class 'RuntimeError'>
#   Error Contents: Unknown addon id 'plugin.video.pov'.
#     service.py line 7      POVMonitor().run()
#     entry.py line 313      from indexers.trakt_api import trakt_sync_activities
#     tmdb_api.py line 14    READ_TOKEN = kodi_utils.addon().getSetting(...)
#     kodi_utils.py line 60  return Addon(id=addon_id)
#
# tmdb_api reads that setting at IMPORT time, so the failure is not one call
# that returns nothing -- the import chain dies, POVMonitor never starts, and
# POV's Trakt sync monitor and premium-account notification are gone for the
# rest of the session. The user sees a red error and, later, silently stale
# Trakt data.
#
# WE OPEN THAT WINDOW OURSELVES. pov_reload cycles POV off and on to make it
# re-import after we patch its files, and the log shows the crash landing
# three tenths of a second before our own "cycled POV" line. But the window is
# Kodi's, not ours: anyone toggling POV by hand hits it too, and so does any
# add-on that reads its own settings while importing. Waiting longer before we
# re-enable would not help either, because the wait has to happen INSIDE the
# add-on Kodi has just started.
#
# So the fix goes where the failure is. addon() retries for up to four seconds
# -- the observed window is about 2.7 -- and only after Addon() has already
# raised once, so nothing is slower on the path everybody takes. If POV really
# is gone, the last attempt raises exactly as before.

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


POV_ADDON_ID = 'plugin.video.pov'
KODI_UTILS_REL = 'resources/lib/modules/kodi_utils.py'
MARKER = '# AI_SUBS_POV_ADDON_WINDOW_v1'

# POV indents with tabs. This must match byte for byte.
_STOCK = ("def addon(addon_id='plugin.video.pov'):\n"
          "\treturn Addon(id=addon_id)\n")

_PATCHED = (
    "def addon(addon_id='plugin.video.pov'):\n"
    "\t" + MARKER + "\n"
    "\ttry:\n"
    "\t\treturn Addon(id=addon_id)\n"
    "\texcept Exception:\n"
    "\t\tpass\n"
    "\t# Kodi calls an add-on unknown for a couple of seconds after it is\n"
    "\t# re-enabled -- the enabled flag flips at once, the add-on manager\n"
    "\t# catches up later -- and it starts this add-on's service inside that\n"
    "\t# window. Reading a setting there used to kill the import chain and\n"
    "\t# with it the whole background service, for the rest of the session.\n"
    "\tfor _ in range(40):\n"
    "\t\txbmc.sleep(100)\n"
    "\t\ttry:\n"
    "\t\t\treturn Addon(id=addon_id)\n"
    "\t\texcept Exception:\n"
    "\t\t\tcontinue\n"
    "\t# Out of patience: this is not the window, the add-on is really gone.\n"
    "\t# Raise the way stock does, so nothing downstream has to change.\n"
    "\treturn Addon(id=addon_id)\n"
)

# Any earlier version of our own block, so a re-patch replaces rather than
# stacks. Anchored on the def line and running to the end of the indented
# body -- indented lines ONLY. Letting it eat blank lines too would swallow
# the separator before the next function, so a re-patched file would differ
# from a freshly patched one by a missing blank line, forever.
_OURS_RE = re.compile(
    r"def addon\(addon_id='plugin\.video\.pov'\):\n"
    r"\t# AI_SUBS_POV_ADDON_WINDOW_v\d+\n"
    r"(?:[ \t].*\n)*",
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_addon_window_patcher: ' + msg, level=level)
    except Exception:
        pass


def _pov_path(rel):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *rel.split('/'))
    return p if os.path.isfile(p) else ''


def _drop_pyc(path):
    try:
        d = os.path.join(os.path.dirname(path), '__pycache__')
        base = os.path.splitext(os.path.basename(path))[0] + '.'
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.startswith(base):
                    try:
                        os.remove(os.path.join(d, fn))
                    except OSError:
                        pass
    except Exception:
        pass


def ensure_patched():
    """'no_file' | 'clean' | 'patched' | 'unmatched' | 'read_failed'
    | 'compile_failed' | 'write_failed'. Never raises."""
    path = _pov_path(KODI_UTILS_REL)
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'clean'

    new_content = content
    if _OURS_RE.search(new_content):
        # An older version of ours. Back to stock first, then forward -- so
        # this never leaves two retry loops wrapped around each other.
        new_content = _OURS_RE.sub(_STOCK, new_content, count=1)
    if _STOCK not in new_content:
        # POV rewrote addon(). Guessing at a replacement for a function this
        # central is how a build breaks everything at once.
        _log('addon() is not the function we know; leaving it alone',
             level='WARNING')
        return 'unmatched'
    new_content = new_content.replace(_STOCK, _PATCHED, 1)

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
    _drop_pyc(path)
    _log("addon() now waits out Kodi's unknown-addon window instead of "
         'killing the service')
    return 'patched'
