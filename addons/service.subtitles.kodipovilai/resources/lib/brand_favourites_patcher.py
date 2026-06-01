import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


FAVOURITES_REL = 'favourites.xml'

REPLACEMENTS = (
    (
        'special://home/media/build_icons/POV/Logo_POV.png',
        'special://home/media/build_icons/POV/Logo_POV_IL.png',
    ),
    (
        'special://home/media/build_icons/Wizard/wizard.png',
        'special://home/media/build_icons/Wizard/wizard_pov_il.png',
    ),
    (
        'special://home/media/build_icons/Wizard/fast_update.png',
        'special://home/media/build_icons/Wizard/fast_update_pov_il.png',
    ),
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('brand_favourites_patcher: ' + msg, level=level)
    except Exception:
        pass


def _favourites_path():
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath('special://userdata/' + FAVOURITES_REL)
    except Exception:
        return ''


def ensure_patched():
    path = _favourites_path()
    if not path or not os.path.isfile(path):
        return 'no_favourites'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    new_content = content
    changed = []
    for old, new in REPLACEMENTS:
        if old in new_content:
            new_content = new_content.replace(old, new)
            changed.append(old)

    if not changed:
        return 'already_patched'

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

    _log('migrated cached icon paths to POV IL filenames', level='INFO')
    return 'patched'
