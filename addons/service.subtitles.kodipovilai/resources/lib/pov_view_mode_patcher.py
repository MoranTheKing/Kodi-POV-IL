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
MARKER = '# AI_SUBS_POV_VIEWMODE_v2'

# v2 widens the settle window a lot (60->300 = up to 15s) AND drops the
# give-up `else: return`. The loop still breaks the instant the content
# settles, so fast pages are unaffected (milliseconds); only a genuinely slow
# page now waits long enough for the container content to catch up before the
# view is applied -- v1's 6s wasn't enough on slow devices (the view fired
# mid-load and didn't stick, so it fell back to the list around page 9).
_NEW = (
    "\t\tfor _ in range(300):\n"
    "\t\t\tif container_content() == content: break\n"
    "\t\t\tsleep(50)\n"
    "\t\texecute_builtin('Container.SetViewMode(%s)' % view_id)"
)

# Anchors we know how to upgrade to _NEW: POV stock, and our own v1 output.
_OLD_STOCK = (
    "\t\tfor _ in range(60):\n"
    "\t\t\tif container_content() == content: break\n"
    "\t\t\tsleep(50)\n"
    "\t\telse: return\n"
    "\t\texecute_builtin('Container.SetViewMode(%s)' % view_id)"
)
_OLD_V1 = (
    "\t\tfor _ in range(120):\n"
    "\t\t\tif container_content() == content: break\n"
    "\t\t\tsleep(50)\n"
    "\t\texecute_builtin('Container.SetViewMode(%s)' % view_id)"
)
_OLDS = (_OLD_STOCK, _OLD_V1)


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
    anchor = next((a for a in _OLDS if a in content), None)
    if anchor is None:
        _log('set_view_mode body not found -- POV may have changed it; '
             'leaving alone', level='WARNING')
        return 'unmatched'

    new_content = content.replace(anchor, _NEW, 1)
    # Drop the superseded v1 marker line if this is a v1 -> v2 upgrade.
    new_content = new_content.replace('# AI_SUBS_POV_VIEWMODE_v1\n', '')
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
