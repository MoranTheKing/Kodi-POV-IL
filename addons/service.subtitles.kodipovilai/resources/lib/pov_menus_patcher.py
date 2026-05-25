# Self-healing replacement of three plugin.video.pov menu source
# files (movies.py, tvshows.py, episodes.py) so the context-menu
# logic matches what PR #98 added: only show Trakt/MDBList/TMDB
# Manager entries that correspond to actually-connected services,
# with TMDB at the top when personally connected.
#
# These files don't fit the marker-inject pattern used by
# pov_services_patcher.py because PR #98 *replaces* an existing
# block rather than appending one. The safest delivery for code
# we already control is to ship the canonical version inside our
# own addon and copy it over POV's copy whenever the bytes differ
# (idempotent: noop when already up to date).
#
# Trade-off: any future upstream POV update to these specific
# files would be clobbered. Acceptable because the Kodi POV IL
# build ships a frozen POV version we maintain ourselves; users
# don't get POV updates from POV upstream, they get whatever the
# FENtastic build zip carries.
#
# Defensive: if POV isn't installed at all, or the target dir
# doesn't exist, skip. If the write fails (permissions, disk
# full, file locked), log and continue -- the patcher will
# retry on the next Kodi startup.

import os
import shutil

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None


POV_ADDON_ID = 'plugin.video.pov'
MENU_FILES = ('movies.py', 'tvshows.py', 'episodes.py')


def _bundled_dir():
    """Where our canonical POV menu files live inside this addon."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, 'pov_overrides', 'menus')


def _target_dir():
    """Where to install them in the user's POV addon."""
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID
            + '/resources/lib/menus/')
    except Exception:
        return ''


def _files_identical(a, b):
    try:
        with open(a, 'rb') as fa, open(b, 'rb') as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def ensure_patched():
    """Copy each bundled menu file over to the user's POV addon if
    the bytes differ. Returns a {filename: status} dict where status
    is one of:
      'unchanged'    -- already identical, no write needed
      'patched'      -- file rewritten
      'no_source'    -- bundled copy missing (shouldn't happen)
      'no_target'    -- POV addon file not present (POV not installed?)
      'failed'       -- write error; will retry next startup
    """
    bdir = _bundled_dir()
    tdir = _target_dir()
    results = {}
    if not os.path.isdir(bdir):
        return {'_status': 'no_bundled'}
    if not tdir or not os.path.isdir(tdir):
        return {'_status': 'no_pov'}

    for name in MENU_FILES:
        src = os.path.join(bdir, name)
        dst = os.path.join(tdir, name)
        if not os.path.isfile(src):
            results[name] = 'no_source'
            continue
        if not os.path.isfile(dst):
            results[name] = 'no_target'
            continue
        if _files_identical(src, dst):
            results[name] = 'unchanged'
            continue
        # Drop pycache for this file if present, otherwise Kodi may
        # keep executing the old compiled bytecode until next launch.
        pycache_dir = os.path.join(os.path.dirname(dst), '__pycache__')
        if os.path.isdir(pycache_dir):
            for f in os.listdir(pycache_dir):
                if f.startswith(name.replace('.py', '.')) and \
                        f.endswith('.pyc'):
                    try:
                        os.remove(os.path.join(pycache_dir, f))
                    except OSError:
                        pass
        tmp = dst + '.aitmp'
        try:
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
            results[name] = 'patched'
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            results[name] = 'failed'
    return results
