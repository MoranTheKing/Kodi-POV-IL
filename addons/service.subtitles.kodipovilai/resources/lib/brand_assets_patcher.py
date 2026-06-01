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


ASSETS = (
    (
        'media/splash.jpg',
        'special://home/media/splash.jpg',
    ),
    (
        'skin.fentastic/media/kodirdil/group_logo/kodirdil-logo.png',
        'special://home/addons/skin.fentastic/media/kodirdil/group_logo/'
        'kodirdil-logo.png',
    ),
    (
        'skin.fentastic/media/kodirdil/group_logo/kodirdil-vendor_logo.png',
        'special://home/addons/skin.fentastic/media/kodirdil/group_logo/'
        'kodirdil-vendor_logo.png',
    ),
    (
        'skin.estuary/media/kodirdil/group_logo/kodirdil-logo.png',
        'special://home/addons/skin.estuary/media/kodirdil/group_logo/'
        'kodirdil-logo.png',
    ),
    (
        'skin.estuary/media/kodirdil/group_logo/kodirdil-vendor_logo.png',
        'special://home/addons/skin.estuary/media/kodirdil/group_logo/'
        'kodirdil-vendor_logo.png',
    ),
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('brand_assets_patcher: ' + msg, level=level)
    except Exception:
        pass


def _translate(path):
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(path)
    except Exception:
        return ''


def _source_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, 'media_assets', 'brand')


def _same_file(src, dst):
    try:
        if not os.path.isfile(dst):
            return False
        if os.path.getsize(src) != os.path.getsize(dst):
            return False
        with open(src, 'rb') as a, open(dst, 'rb') as b:
            return a.read() == b.read()
    except Exception:
        return False


def _copy_if_changed(src, dst):
    if not os.path.isfile(src) or not dst:
        return 'missing'
    if _same_file(src, dst):
        return 'skipped'
    dst_dir = os.path.dirname(dst)
    try:
        if dst_dir and not os.path.isdir(dst_dir):
            os.makedirs(dst_dir)
        tmp = dst + '.aitmp'
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
        return 'updated'
    except OSError as e:
        _log('failed {0}: {1}'.format(dst, e), level='WARNING')
        try:
            os.remove(tmp)
        except Exception:
            pass
        return 'failed'


def ensure_patched():
    root = _source_root()
    if not os.path.isdir(root):
        return {'_status': 'no_brand_assets'}
    results = {}
    for rel, target in ASSETS:
        src = os.path.join(root, rel.replace('/', os.sep))
        dst = _translate(target)
        results[rel] = _copy_if_changed(src, dst)
    changed = [k for k, v in results.items() if v == 'updated']
    if changed:
        _log('updated {0}'.format(', '.join(changed)), level='INFO')
    return results
