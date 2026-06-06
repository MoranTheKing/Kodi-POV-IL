# Self-healing replacement of three plugin.video.pov menu source
# files (movies.py, tvshows.py, episodes.py) so the context-menu
# logic matches what PR #98 added: only show Trakt/MDBList/TMDB
# Manager entries that correspond to actually-connected services,
# with TMDB at the top when personally connected.
#
# Detection by marker substring (not byte-exact compare) so future
# inconsequential edits to upstream POV (whitespace, a comment
# tweak) don't trip the patcher into unnecessary rewrites. The
# marker is a phrase that only exists in the PR #98 version of
# these files:
#
#     tmdb_sort_key = min(self.cm_sort[
#
# If the marker is present, the file is already migrated. If not,
# we copy our bundled canonical version over.
#
# Defensive: if POV isn't installed, if the bundled overrides are
# missing (zip extraction edge case), or if the write fails
# (permission denied on Android), log and skip -- the patcher
# retries on the next Kodi startup.

import os
import shutil

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
MENU_FILES = ('movies.py', 'tvshows.py', 'episodes.py')

# Substring that ONLY the current canonical menu files contain, so we
# know whether the device's copy is up to date. Bumped to the
# `_flex_call` helper name in v0.2.80: that version-resilient call
# wrapper was added to movies.py/tvshows.py to fix the
# "tmdb_favorites() takes 2 positional arguments but 3 were given"
# TypeError that emptied every personal list when POV auto-updated its
# indexers/caches to a different arity than our synced movies.py
# expected. Earlier synced copies lack `_flex_call`, so this marker
# forces a one-time re-sync of the fixed files onto existing installs.
# (The previous marker, the Hebrew "ניהול רשימות (Trakt)" label, is
# still in the files but is no longer the freshness signal.)
MARKER = 'tmdb_my_movies'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_menus_patcher: ' + msg, level=level)
    except Exception:
        pass


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


def _has_marker(path):
    try:
        with open(path, 'rb') as f:
            return MARKER.encode('utf-8') in f.read()
    except OSError:
        return False


def _drop_pyc(dst, name):
    """Drop the matching __pycache__ entry so the next plugin
    invocation picks up the new code without waiting for Kodi
    to recompile."""
    pycache_dir = os.path.join(os.path.dirname(dst), '__pycache__')
    if not os.path.isdir(pycache_dir):
        return
    stem = name.replace('.py', '.')
    for fn in os.listdir(pycache_dir):
        if fn.startswith(stem) and fn.endswith('.pyc'):
            try:
                os.remove(os.path.join(pycache_dir, fn))
            except OSError:
                pass


def ensure_patched():
    """Copy each bundled menu file over to the user's POV addon
    when the destination lacks the PR #98 marker. Returns a
    {filename: status} dict where status is one of:
      'unchanged'    -- marker present, no write needed
      'patched'      -- file rewritten with canonical version
      'no_source'    -- bundled copy missing (shouldn't happen)
      'no_target'    -- POV addon file not present
      'failed'       -- write error; will retry next startup
    Plus a special key '_status' with values:
      'no_bundled'   -- our pov_overrides/menus dir missing
      'no_pov'       -- POV addon not installed
    """
    bdir = _bundled_dir()
    tdir = _target_dir()
    if not os.path.isdir(bdir):
        _log('bundled dir missing at {0}'.format(bdir),
             level='WARNING')
        return {'_status': 'no_bundled'}
    if not tdir or not os.path.isdir(tdir):
        _log('POV target dir missing at {0}'.format(tdir),
             level='INFO')
        return {'_status': 'no_pov'}

    results = {}
    for name in MENU_FILES:
        src = os.path.join(bdir, name)
        dst = os.path.join(tdir, name)
        if not os.path.isfile(src):
            results[name] = 'no_source'
            _log('{0}: bundled source missing at {1}'.format(name, src),
                 level='WARNING')
            continue
        if not os.path.isfile(dst):
            results[name] = 'no_target'
            _log('{0}: POV target missing at {1}'.format(name, dst),
                 level='INFO')
            continue
        if _has_marker(dst):
            results[name] = 'unchanged'
            _log('{0}: marker present, already migrated'.format(name),
                 level='DEBUG')
            continue
        # Marker missing -- copy our canonical version over.
        tmp = dst + '.aitmp'
        try:
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
            _drop_pyc(dst, name)
            results[name] = 'patched'
            _log('{0}: copied canonical PR #98 version over'.format(
                name), level='INFO')
        except OSError as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            results[name] = 'failed'
            _log('{0}: write failed: {1}'.format(name, e),
                 level='WARNING')
    return results
