# Self-healing patch for DarkSubs's OpenSubtitles provider.
#
# Users can install this AI addon without installing the full POV IL build.
# In that path DarkSubs may already be present with the old OpenSubtitles
# URL/cache/key behaviour. Copy only the OpenSubtitles provider and its
# local key fallback into DarkSubs; do not touch menus, skins, lists, Trakt,
# TMDB, or any build-only state.

import os
import shutil

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import kodi_utils


DARKSUBS_ADDON_ID = 'service.subtitles.All_Subs'
TARGET_REL_DIR = os.path.join('resources', 'sources')
PATCH_REL_DIR = os.path.join('resources', 'patches', 'darksubs')
OPEN_SUBS_FILE = 'opensubtitles.py'
KEYS_FILE = 'darksubs_opensubtitles_api.json'
MARKER = 'OPENSUBTITLES_SEARCH_FALLBACK_VERSION = 4'


def _log(msg, level='INFO'):
    try:
        kodi_utils.log('darksubs_opensubtitles_patcher: ' + msg,
                       level=level)
    except Exception:
        pass


def _addon_path(addon_id):
    if xbmcvfs is None:
        return ''
    try:
        path = xbmcvfs.translatePath(
            'special://home/addons/{0}/'.format(addon_id))
    except Exception:
        return ''
    return path if os.path.isdir(path) else ''


def _source_patch_path(filename):
    base = _addon_path('service.subtitles.kodipovilai')
    if not base:
        return ''
    path = os.path.join(base, PATCH_REL_DIR, filename)
    return path if os.path.isfile(path) else ''


def _target_path(filename):
    base = _addon_path(DARKSUBS_ADDON_ID)
    if not base:
        return ''
    return os.path.join(base, TARGET_REL_DIR, filename)


def _invalidate_pyc_cache(py_path):
    try:
        pkg_dir = os.path.dirname(py_path)
        base = os.path.splitext(os.path.basename(py_path))[0]
        cache_dir = os.path.join(pkg_dir, '__pycache__')
        if not os.path.isdir(cache_dir):
            return
        prefix = base + '.cpython-'
        for fname in os.listdir(cache_dir):
            if fname.startswith(prefix) and fname.endswith('.pyc'):
                try:
                    os.remove(os.path.join(cache_dir, fname))
                except OSError:
                    pass
    except Exception:
        pass


def _clear_darksubs_subtitle_cache():
    if xbmcvfs is None:
        return
    try:
        profile_dir = xbmcvfs.translatePath(
            'special://home/userdata/addon_data/{0}/'.format(DARKSUBS_ADDON_ID))
        cache_db = os.path.join(profile_dir, 'cache_f', 'sources.db')
        if os.path.isfile(cache_db):
            try:
                os.remove(cache_db)
                _log('DarkSubs subtitle cache DB removed after OpenSubtitles patch')
            except OSError:
                pass
    except Exception as e:
        _log('failed to clear DarkSubs subtitle cache: {0}'.format(e),
             level='WARNING')


def _copy_if_needed(src, dst, marker=None):
    if not src or not os.path.isfile(src):
        return 'missing_source'
    if not dst:
        return 'missing_target'
    try:
        if marker and os.path.isfile(dst):
            with open(dst, 'r', encoding='utf-8', errors='replace') as f:
                if marker in f.read():
                    return 'already_patched'
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        return 'patched'
    except Exception as e:
        _log('copy failed for {0}: {1}'.format(dst, e), level='WARNING')
        return 'write_failed'


def ensure_patched():
    target_py = _target_path(OPEN_SUBS_FILE)
    if not target_py:
        return 'not_installed'

    py_status = _copy_if_needed(
        _source_patch_path(OPEN_SUBS_FILE), target_py, marker=MARKER)
    json_status = _copy_if_needed(
        _source_patch_path(KEYS_FILE), _target_path(KEYS_FILE))

    if py_status == 'patched':
        _invalidate_pyc_cache(target_py)
        _clear_darksubs_subtitle_cache()
        try:
            from . import darksubs_reload
            darksubs_reload.note_patched()
        except Exception:
            pass

    if py_status == 'patched' or json_status == 'patched':
        _log('OpenSubtitles provider/fallback updated')
        return 'patched'
    if py_status in ('missing_source', 'write_failed') or json_status in (
            'missing_source', 'write_failed'):
        return 'failed'
    return 'already_patched'
