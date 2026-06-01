# Self-healing installer for the bundled TMDB build_icons.
#
# The FENtastic build's home-screen tiles (in userdata/favourites.xml)
# reference icons by absolute special:// paths -- e.g.
#   special://home/media/build_icons/Twilight/Shows/My_Shows.png
# When we migrate the Trakt-collection home tiles to TMDB favourites,
# the existing icons are Trakt-branded (red TRAKT badge in the
# upper-right of the folder graphic). Pointing the TMDB tiles at
# those icons would visually mislead users.
#
# This patcher ships TMDB-branded variants of those icons inside
# the AI subs addon's resources/lib/media_assets/build_icons/
# subtree, and on every Kodi startup it copies any that are
# missing from the live media/ directory.
#
# Defensive by default: only writes files that don't exist on disk.
# A tiny allow-list is force-synced for build branding assets that
# must replace the legacy Real-Debrid/KODI artwork on existing installs.

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

FORCE_SYNC = set([
    'POV/Logo_POV.png',
    'Wizard/fast_update.png',
    'Wizard/wizard.png',
])


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('build_icons_patcher: ' + msg, level=level)
    except Exception:
        pass


def _bundled_root():
    """Directory holding the bundled build_icons subtree."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, 'media_assets', 'build_icons')


def _target_root():
    """The live media/build_icons/ directory under the user's Kodi
    home. Returns '' when Kodi APIs aren't available."""
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(
            'special://home/media/build_icons/')
    except Exception:
        return ''


def _walk_pngs(root):
    """Yield (full_path, relative_path) for every .png under root."""
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.lower().endswith('.png'):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            yield full, rel


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


def ensure_installed():
    """Copy each bundled PNG into the live media/build_icons/
    subtree, skipping files that already exist there. Returns
    {'installed': [...], 'skipped': [...]} or {'_status': '...'}.
    """
    src_root = _bundled_root()
    dst_root = _target_root()
    if not os.path.isdir(src_root):
        _log('bundled icons dir missing', level='WARNING')
        return {'_status': 'no_bundled'}
    if not dst_root:
        return {'_status': 'no_kodi'}

    installed, updated, skipped = [], [], []
    for src, rel in _walk_pngs(src_root):
        rel_key = rel.replace(os.sep, '/')
        dst = os.path.join(dst_root, rel)
        force = rel_key in FORCE_SYNC
        existed = os.path.isfile(dst)
        if existed and (not force or _same_file(src, dst)):
            skipped.append(rel)
            continue
        dst_dir = os.path.dirname(dst)
        try:
            if not os.path.isdir(dst_dir):
                os.makedirs(dst_dir)
            tmp = dst + '.aitmp'
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
            if force and existed:
                updated.append(rel)
                _log('updated {0}'.format(rel), level='INFO')
            else:
                installed.append(rel)
                _log('installed {0}'.format(rel), level='INFO')
        except OSError as e:
            _log('failed {0}: {1}'.format(rel, e), level='WARNING')
            try:
                os.remove(tmp)
            except (OSError, UnboundLocalError):
                pass

    if not installed and not updated:
        _log('all bundled icons already on disk', level='DEBUG')
    return {'installed': installed, 'updated': updated, 'skipped': skipped}
