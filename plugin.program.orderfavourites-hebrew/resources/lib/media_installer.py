# -*- coding: utf-8 -*-
# Global media + favourites updater for the Kodi POV IL build.
#
# This addon is the CENTRAL home of the build's media assets.
# It recursively copies the entire contents of the 'resources/media' folder
# (including flat files, icons, fonts, and any nested subfolders) into the
# global media folder (special://home/media/).
#
# On startup we refresh changed assets and merge the skin's current defaults
# into favourites.xml. Users may have reordered or edited build shortcuts;
# favourites_generator compares against its last generated baseline and keeps
# those changes while adopting untouched new defaults.
#
# Fully guarded: every failure is swallowed so this can never break Kodi startup.

import os
import tempfile

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    import xbmcaddon
    _ADDON = xbmcaddon.Addon('plugin.program.orderfavourites-hebrew')
except Exception:
    xbmcaddon = None
    _ADDON = None

try:
    import xbmc
except Exception:
    xbmc = None


# (source path relative to the addon root, destination special:// folder).
# Deployed into the global media folder: Kodi reads the media from there rather 
# than reaching into this addon's own folder -- avoiding cross-addon containment breaches. 
# The canonical SOURCE copy lives in the addon (resources/media/) and is overwritten 
# recursively into the global folder on startup.
_COPY_JOBS = (
    (os.path.join('resources', 'media'), 'special://home/media/'),
)

def _log(msg):
    if xbmc is None:
        return
    try:
        xbmc.log('[orderfavourites media_installer] ' + msg, xbmc.LOGINFO)
    except Exception:
        pass


def _same_file(src, dst):
    """Compare content, not timestamps: packaged artwork can change in place."""
    try:
        if os.path.getsize(src) != os.path.getsize(dst):
            return False
        with open(src, 'rb') as left, open(dst, 'rb') as right:
            while True:
                chunk = left.read(256 * 1024)
                if chunk != right.read(256 * 1024):
                    return False
                if not chunk:
                    return True
    except (OSError, IOError):
        return False


def _install_assets(addon_path):
    """Copy changed bundled media to the global folder and return writes."""
    written = 0
    for src_rel, dst_special in _COPY_JOBS:
        try:
            src_root = os.path.join(addon_path, src_rel)
            if not os.path.isdir(src_root):
                continue
            
            dst_root = xbmcvfs.translatePath(dst_special)
            
            # Walk through all directories and files recursively
            for root, dirs, files in os.walk(src_root):
                for name in files:
                    src = os.path.join(root, name)
                    
                    # Calculate the relative path to maintain directory structure
                    rel_path = os.path.relpath(src, src_root)
                    dst = os.path.join(dst_root, rel_path)
                    
                    # Ensure the destination subdirectory exists
                    dst_dir = os.path.dirname(dst)
                    if not os.path.isdir(dst_dir):
                        try:
                            os.makedirs(dst_dir)
                        except Exception:
                            pass
                            
                    if _same_file(src, dst):
                        continue
                    tmp = None
                    try:
                        # Copy beside the destination, then replace it. A
                        # failed copy must leave the previously working icon.
                        fd, tmp = tempfile.mkstemp(prefix='.povil-media-', dir=dst_dir)
                        os.close(fd)
                        os.remove(tmp)  # Kodi's VFS copy may not overwrite.
                        if xbmcvfs.copy(src, tmp) is False or not _same_file(src, tmp):
                            raise IOError('incomplete media copy')
                        os.replace(tmp, dst)
                        tmp = None
                        written += 1
                    except Exception as exc:
                        _log('asset update failed for {0}: {1}'.format(rel_path, exc))
                    finally:
                        if tmp and os.path.exists(tmp):
                            try:
                                os.remove(tmp)
                            except OSError:
                                pass
        except Exception:
            pass
    return written


def _refresh_favourites(addon_path):
    """Merge active-skin defaults into favourites.xml, preserving user edits."""
    try:
        import importlib.util
        gen_file = os.path.join(addon_path, 'favourites_generator.py')
        if not os.path.isfile(gen_file):
            return False
        spec = importlib.util.spec_from_file_location(
            'povil_favourites_generator_startup', gen_file)
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)
        skin_id = ''
        if xbmc is not None:
            try:
                skin_id = xbmc.getSkinDir() or ''
            except Exception:
                skin_id = ''
        # merge=True keeps the user's own custom tiles; our canonical tiles are
        # refreshed (overwritten) so UI/shortcut/icon updates always land.
        if gen.generate_favourites_xml(skin_id, merge=True, write=True) is None:
            return False
        _log('favourites.xml refreshed for skin "{0}"'.format(skin_id or '?'))
        return True
    except Exception as e:
        _log('favourites refresh failed: {0}'.format(e))
        return False


def install_and_verify_global_media_assets():
    """Strict installer gate; zero writes alone does not prove completeness."""
    if xbmcvfs is None or _ADDON is None:
        return False
    addon_path = xbmcvfs.translatePath(_ADDON.getAddonInfo('path'))
    _install_assets(addon_path)
    found = False
    for src_rel, dst_special in _COPY_JOBS:
        src_root = os.path.join(addon_path, src_rel)
        if not os.path.isdir(src_root):
            return False
        dst_root = xbmcvfs.translatePath(dst_special)
        for root, _dirs, files in os.walk(src_root):
            for name in files:
                found = True
                src = os.path.join(root, name)
                if not _same_file(src, os.path.join(dst_root, os.path.relpath(src, src_root))):
                    return False
    return found and _refresh_favourites(addon_path)


def install_global_media_assets():
    """Refresh changed bundled assets and merge the skin's favourites.

    Safe to call repeatedly; every failure is swallowed.
    """
    if xbmcvfs is None or _ADDON is None:
        return 0
    try:
        addon_path = xbmcvfs.translatePath(_ADDON.getAddonInfo('path'))
    except Exception:
        return 0
    written = _install_assets(addon_path)
    if written:
        _log('installed/updated {0} global media asset(s)'.format(written))
    _refresh_favourites(addon_path)
    return written
