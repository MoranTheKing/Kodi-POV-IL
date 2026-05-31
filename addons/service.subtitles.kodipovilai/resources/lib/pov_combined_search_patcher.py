# Installs a small POV-side combined search route used by Arctic Fuse 3
# Discover. The route returns mixed movie + TV search results with stable
# poster/thumb/icon/fanart artwork and POV-native click actions.

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
HELPER_NAME = 'ai_search.py'
MARKER = 'ai_pov_combined_search_v2'
ENTRY_MARKER = '# AI_SUBS_POV_COMBINED_SEARCH_v1'

ENTRY_OLD = (
    "\t\t\telif mode == 'build_movie_list':\n"
    "\t\t\t\tfrom menus.movies import Menu\n"
    "\t\t\t\tMenu(params).run()\n"
)
ENTRY_NEW = (
    "\t\t\telif mode == 'ai_pov_combined_search':\n"
    "\t\t\t\tfrom menus.ai_search import run\n"
    "\t\t\t\trun(params)\n"
    "\t\t\t" + ENTRY_MARKER + "\n"
    + ENTRY_OLD
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_combined_search_patcher: ' + msg, level=level)
    except Exception:
        pass


def _pov_base():
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath('special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''


def _source_helper():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, 'pov_overrides', 'menus', HELPER_NAME)


def _drop_pyc(path, stem):
    pycache_dir = os.path.join(os.path.dirname(path), '__pycache__')
    if not os.path.isdir(pycache_dir):
        return
    prefix = stem + '.'
    for fn in os.listdir(pycache_dir):
        if fn.startswith(prefix) and fn.endswith('.pyc'):
            try:
                os.remove(os.path.join(pycache_dir, fn))
            except OSError:
                pass


def _install_helper(base):
    src = _source_helper()
    dst = os.path.join(base, 'resources', 'lib', 'menus', HELPER_NAME)
    if not os.path.isfile(src):
        return 'no_source'
    try:
        if os.path.isfile(dst):
            with open(dst, 'rb') as f:
                if MARKER.encode('utf-8') in f.read():
                    return 'unchanged'
        tmp = dst + '.aitmp'
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
        _drop_pyc(dst, 'ai_search')
        return 'patched'
    except OSError as e:
        _log('helper install failed: {0}'.format(e), level='WARNING')
        return 'failed'


def _patch_entry(base):
    path = os.path.join(base, 'resources', 'lib', 'entry.py')
    if not os.path.isfile(path):
        return 'no_entry'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except OSError as e:
        _log('entry read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'
    if ENTRY_MARKER in text:
        return 'unchanged'
    if ENTRY_OLD not in text:
        _log('entry anchor not found; POV may have changed entry.py', level='WARNING')
        return 'unmatched'
    new_text = text.replace(ENTRY_OLD, ENTRY_NEW, 1)
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_text)
        os.replace(tmp, path)
        _drop_pyc(path, 'entry')
        return 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('entry write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'


def ensure_patched():
    base = _pov_base()
    if not base or not os.path.isdir(base):
        return 'no_pov'
    helper_status = _install_helper(base)
    entry_status = _patch_entry(base)
    summary = 'helper={0}, entry={1}'.format(helper_status, entry_status)
    if 'patched' in summary:
        _log('installed combined search route ({0})'.format(summary), level='INFO')
    return summary
