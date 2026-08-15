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
MARKER = '# AI_SUBS_POV_VIEWMODE_v4'

# v3: waiting-then-setting-once (v1/v2) still lost a race -- POV applies the
# view right after the directory loads, but Kodi re-applies the path's DEFAULT
# view a moment later as the items finish rendering, clobbering it. Waiting
# longer only shifts which page loses the race (hence "reverts after a few
# pages", variably). v3 instead RE-APPLIES the view every 50ms for ~1s after
# the content settles, so any late default-application is immediately
# overridden. Fast pages still get the view on the first tick; the loop stops
# ~1s after the content matched. If the content never settles (e.g. a genuinely
# empty/failed list) it just times out without forcing a view, as before.
# The `else: settled = -1` is load-bearing. Without it the window is anchored
# to the FIRST match ever seen, and this loop checks BEFORE its first sleep --
# so on a page-forward, where the outgoing and incoming containers share the
# same content type, a match on tick 0 (before Kodi has begun the transition)
# pins `settled` there. The counter then runs out against the old page and the
# loop breaks around the moment the new one settles, collapsing "re-apply for a
# second" into a single apply -- in exactly the scenario the re-applying exists
# for. Resetting whenever the content stops matching means the window always
# measures from the last real settle.
_NEW = (
    "\t\tsettled = -1\n"
    "\t\tfor _n in range(200):\n"
    "\t\t\tif container_content() == content:\n"
    "\t\t\t\tif settled < 0: settled = _n\n"
    "\t\t\t\texecute_builtin('Container.SetViewMode(%s)' % view_id)\n"
    "\t\t\t\tif _n - settled >= 20: break\n"
    "\t\t\telse: settled = -1\n"
    "\t\t\tsleep(50)"
)

# Anchors we know how to upgrade to _NEW: POV stock, and our own v1/v2 output.
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
_OLD_V2 = (
    "\t\tfor _ in range(300):\n"
    "\t\t\tif container_content() == content: break\n"
    "\t\t\tsleep(50)\n"
    "\t\texecute_builtin('Container.SetViewMode(%s)' % view_id)"
)
# POV 6.08.01 rewrote the loop: it sleeps FIRST, skips the tick with `continue`
# while the content has not settled, and returns the moment it applies the view.
# The old `else: return` give-up is gone, so the specific bug the first version
# of this patcher chased no longer exists upstream.
#
# What DOES survive is the reason for v3, and it is the one that actually
# matches the field report: POV still applies the view exactly once and returns
# immediately, so a default view that Kodi applies a moment later -- as the
# items finish rendering -- still wins. Re-applying for ~1s after the content
# settles is still the fix.
#
# This shape has to be listed explicitly rather than matched loosely. An earlier
# patcher in this build pinned an exact line, POV reformatted it, and the
# patcher went quiet for months without anyone noticing; the lesson taken there
# was to match by shape. Here the whole body is the thing being replaced, so
# there is nothing looser to key on -- instead ensure_patched() reports
# 'unmatched' loudly, and run_patchers.py in the scratchpad re-checks every
# patcher against a fresh POV whenever POV ships a new version.
_OLD_STOCK_608 = (
    "\t\tfor _ in range(60):\n"
    "\t\t\tsleep(50)\n"
    "\t\t\tif container_content() != content: continue\n"
    "\t\t\treturn execute_builtin('Container.SetViewMode(%s)' % view_id)"
)

# Our own v3 output. It is listed so a device already carrying it upgrades to
# v4 (which adds the `else: settled = -1` reset) instead of stopping at the
# marker check. Without this the fix would only ever reach devices that had not
# been patched yet -- i.e. nobody who already had the feature.
_OLD_V3 = (
    "\t\tsettled = -1\n"
    "\t\tfor _n in range(200):\n"
    "\t\t\tif container_content() == content:\n"
    "\t\t\t\tif settled < 0: settled = _n\n"
    "\t\t\t\texecute_builtin('Container.SetViewMode(%s)' % view_id)\n"
    "\t\t\t\tif _n - settled >= 20: break\n"
    "\t\t\tsleep(50)"
)

_OLDS = (_OLD_STOCK, _OLD_V1, _OLD_V2, _OLD_STOCK_608, _OLD_V3)


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
    except Exception as e:
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
    # Drop any superseded version marker line, so an upgraded file carries
    # exactly one. Listing them individually has already been forgotten once --
    # v3 was added without its predecessor being retired here -- so this is
    # derived from the marker's own prefix instead of enumerated by hand.
    _prefix = MARKER.rsplit('_v', 1)[0]
    new_content = re.sub(r'[ \t]*' + re.escape(_prefix) + r'_v\d+\n', '',
                         new_content)
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
