# Revert the crash-inducing widget-reload ping from POV's container_refresh().
#
# A previous build (pov_combined_discover_patcher edit 3) rewrote POV's
# resources/lib/modules/kodi_utils.py container_refresh() to ALSO run
# UpdateLibrary(video,special://skin/foo) after Container.Refresh, so AF3's
# home widgets would re-query after mark-watched / clear-progress.
#
# That was confirmed (field crash log, 2026-07-16) to crash Kodi: container_
# refresh() is called from ~30 sites, INCLUDING the Trakt add path
# (indexers/trakt_api.py). The UpdateLibrary ping fires a RecentlyAdded home
# update that reloads EVERY POV home widget at once, spawning many
# plugin.video.pov/router.py invocations concurrently. POV ships
# reuselanguageinvoker=true, so those share one interpreter and corrupt
# CPython dict internals:
#   SystemError: Objects/dictobject.c:1756: bad argument to internal function
# -> the whole Kodi app dies. (The symptom looked like POV's Trakt widget-
# refresh SETTING, but that path never ran -- the log had zero "Widget Refresh
# Performed" lines. The ping was ours.)
#
# This patcher restores container_refresh() to stock (Container.Refresh only)
# and strips the old marker. FENtastic reloads its widgets on Container.Refresh
# alone, so nothing is lost there. Exact-string, idempotent, compile-checked,
# atomic, .pyc invalidated, self-healing every boot. Because POV runs with
# reuselanguageinvoker, the caller should cycle POV (pov_reload.note_patched)
# after a revert so it applies THIS session, not only after a restart.

import os

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
OLD_MARKER = '# AI_SUBS_POV_WIDGET_REFRESH_v1\n'

# The exact harmful block the old patcher wrote (tabs + comment wrapping must
# match byte-for-byte).
_BAD_BLOCK = (
    "def container_refresh():\n"
    "\texecute_builtin('Container.Refresh')\n"
    "\t# AF3/TMDbHelper home widgets don't reload on Container.Refresh alone;\n"
    "\t# this ping makes them re-query (no-op for the library).\n"
    "\treturn execute_builtin('UpdateLibrary(video,special://skin/foo)')\n")
_STOCK_BLOCK = (
    "def container_refresh():\n"
    "\treturn execute_builtin('Container.Refresh')\n")


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_container_refresh_crash_fix: ' + msg, level=level)
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
    """Revert the container_refresh() widget-reload ping if present. Returns
    'no_file' | 'clean' | 'reverted' | 'read_failed' | 'compile_failed' |
    'write_failed'. Never raises."""
    path = _pov_path(KODI_UTILS_REL)
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    new_content = content
    if _BAD_BLOCK in new_content:
        new_content = new_content.replace(_BAD_BLOCK, _STOCK_BLOCK, 1)
    # Strip the old top-of-file marker line if it lingers (either alone or
    # after the block was already hand-reverted).
    if OLD_MARKER in new_content:
        new_content = new_content.replace(OLD_MARKER, '', 1)

    if new_content == content:
        return 'clean'

    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('reverted content would not compile -- skipping ({0})'.format(e),
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
    _log('container_refresh() ping reverted to stock (prevents Trakt-add '
         'native crash)')
    return 'reverted'
