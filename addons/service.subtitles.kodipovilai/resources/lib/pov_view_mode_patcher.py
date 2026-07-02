# Fix POV's intermittent "view resets to a plain list when paging forward".
#
# POV re-applies the user's chosen view (poster wall, etc.) on every directory
# by calling set_view_mode() in resources/lib/modules/kodi_utils.py. That
# function polls Container.Content for up to 3s (range(60) x 50ms) waiting for
# the new page's content type to settle, and -- crucially -- if it does NOT
# settle in time it hits `else: return` and NEVER calls Container.SetViewMode.
# The container is then left in the skin's default view, which on Estuary is
# the ugly no-poster list.
#
# On the first page the content settles quickly so the view is applied; on a
# deeper / slower page (big list, artwork still loading, slower device) the 3s
# poll times out and the view silently reverts -- exactly the intermittent
# "starts fine, then after a page or two becomes a plain list" report.
#
# Fix: widen the poll window (3s -> 6s) and remove the give-up `else: return`
# so Container.SetViewMode is always attempted after the wait (best-effort).
# The early `break` still applies the view the instant the content settles, so
# fast pages are unchanged; only the timed-out case now still gets the right
# view instead of falling back to the list.
#
# Marker-gated, compile()-checked, atomic, .pyc dropped. Safe no-op if POV
# isn't installed or the function changed upstream.

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
MARKER = '# AI_SUBS_POV_VIEWMODE_v1'

_OLD = (
    "\t\tfor _ in range(60):\n"
    "\t\t\tif container_content() == content: break\n"
    "\t\t\tsleep(50)\n"
    "\t\telse: return\n"
    "\t\texecute_builtin('Container.SetViewMode(%s)' % view_id)"
)
_NEW = (
    "\t\tfor _ in range(120):\n"
    "\t\t\tif container_content() == content: break\n"
    "\t\t\tsleep(50)\n"
    "\t\texecute_builtin('Container.SetViewMode(%s)' % view_id)"
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_view_mode_patcher: ' + msg, level=level)
    except Exception:
        pass


def _kodi_utils_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *KODI_UTILS_REL.split('/'))
    return p if os.path.isfile(p) else ''


def ensure_patched():
    """Returns 'patched' | 'already_patched' | 'no_pov' | 'no_file'
    | 'unmatched' | 'compile_failed' | 'read_failed' | 'write_failed'."""
    path = _kodi_utils_path()
    if not path:
        return 'no_pov' if xbmcvfs is None else 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'already_patched'
    if _OLD not in content:
        _log('set_view_mode body not found -- POV may have changed it; '
             'leaving alone', level='WARNING')
        return 'unmatched'

    new_content = content.replace(_OLD, _NEW, 1)
    # Stamp the marker on its own line right after the first newline.
    new_content = new_content.replace('\n', '\n' + MARKER + '\n', 1)

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
            if fn.startswith('kodi_utils.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache_dir, fn))
                except OSError:
                    pass

    _log('set_view_mode now always applies the view (no more list revert on '
         'paging)', level='INFO')
    return 'patched'
