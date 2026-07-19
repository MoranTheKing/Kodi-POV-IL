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
    import xbmc
except Exception:
    xbmc = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None

FORCE_SYNC = set([
    'POV/Logo_POV_IL.png',
    'POV/Logo_POV.png',
    'Wizard/fast_update_pov_il.png',
    'Wizard/fast_update.png',
    'Wizard/wizard_pov_il.png',
    'Wizard/wizard.png',
    'Wizard/switch_skin_pov_il.png',   # AF3 "switch skin" tile (distinct baked text)
])

# Bump this whenever the shipped branding tiles CHANGE. On a bump, every install
# drops its (now stale) texture-cache entries for the FORCE_SYNC tiles exactly
# ONCE, even when the new bytes are already on disk from a prior release -- that
# is the case that bit us: 0.2.386 synced the new baked-text tiles to disk, but
# Kodi kept showing the OLD cached bitmap, and 0.2.387 wouldn't re-trigger because
# the files already matched. The gen marker forces the one-time cache drop.
TILE_REFRESH_GEN = '2'
SETTING_REFRESH_GEN = '_tiles_refresh_gen'


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


def _invalidate_texture_cache(rel_keys):
    """Drop Kodi's cached copy of the given build_icons tiles so a freshly
    written PNG is re-read from disk instead of served from the stale texture
    cache. Without this, replacing a tile at the same path leaves the home
    showing the OLD image until the user happens to navigate away and back
    (the texture is already cached under its special:// url). Best-effort:
    JSON-RPC only, wrapped so a failure can never break startup."""
    if not rel_keys or xbmc is None:
        return
    try:
        import json
    except Exception:
        return
    for rel_key in rel_keys:
        try:
            # Match on the distinctive tail of the path (build_icons/<rel>) so
            # we never collide with an unrelated texture that merely shares a
            # bare filename. The stored url is the special:// path the skin
            # referenced, which ends with this.
            needle = 'build_icons/' + rel_key
            q = {'jsonrpc': '2.0', 'id': 1, 'method': 'Textures.GetTextures',
                 'params': {'filter': {'field': 'url', 'operator': 'contains',
                                       'value': needle}}}
            res = json.loads(xbmc.executeJSONRPC(json.dumps(q))) or {}
            textures = ((res.get('result') or {}).get('textures') or [])
            for tex in textures:
                tid = tex.get('textureid')
                if tid is None:
                    continue
                rq = {'jsonrpc': '2.0', 'id': 1,
                      'method': 'Textures.RemoveTexture',
                      'params': {'textureid': tid}}
                xbmc.executeJSONRPC(json.dumps(rq))
        except Exception:
            pass


def ensure_installed():
    """Copy each bundled PNG into the live media/build_icons/
    subtree, skipping files that already exist there. Returns
    {'installed': [...], 'skipped': [...]} or {'_status': '...'}.
    Any FORCE_SYNC tile whose bytes actually changed also has its
    stale texture-cache entry dropped so the tile is correct the NEXT
    time it is rendered. (A frame the home already painted this session,
    before this ran, may still need one navigation away-and-back to
    refresh; the next Kodi start is always correct.)
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

    # Drop stale texture-cache entries so the fresh art actually shows. Two
    # triggers: (a) `updated` -- a FORCE_SYNC tile's bytes changed THIS boot;
    # (b) a TILE_REFRESH_GEN bump -- the tiles are already correct on disk (a
    # prior release synced them) but Kodi still shows the OLD cached bitmap, so
    # we drop ALL branding tiles' cache once. Kodi re-caches from disk on the
    # next render; service.py triggers one focus-preserving reload after startup
    # so it shows THIS boot instead of the next restart.
    gen_stale = False
    try:
        if kodi_utils is not None:
            gen_stale = (kodi_utils.get_setting(SETTING_REFRESH_GEN, '') or '') \
                != TILE_REFRESH_GEN
    except Exception:
        gen_stale = False
    # Persist the marker FIRST and CONFIRM it stuck before doing the one-time full
    # refresh. kodi_utils.set_setting read-backs and returns False when the write
    # silently no-ops (a documented Kodi/Android failure mode); if the marker
    # can't persist we must NOT do the gen refresh, else gen_stale stays True and
    # we'd ReloadSkin on EVERY boot forever. The per-`updated` path below is
    # unaffected -- it's bounded by real byte changes, not a marker.
    gen_committed = False
    if gen_stale and kodi_utils is not None:
        try:
            gen_committed = bool(kodi_utils.set_setting(
                SETTING_REFRESH_GEN, TILE_REFRESH_GEN))
        except Exception:
            gen_committed = False
        if not gen_committed:
            _log('tile-refresh gen marker did not persist -- skipping the '
                 'one-time reload so it cannot repeat every boot', level='WARNING')
    refresh_keys = set(r.replace(os.sep, '/') for r in updated)
    if gen_stale and gen_committed:
        refresh_keys |= set(FORCE_SYNC)
    refresh_needed = bool(refresh_keys)
    if refresh_needed:
        _invalidate_texture_cache(sorted(refresh_keys))
    return {'installed': installed, 'updated': updated, 'skipped': skipped,
            'refresh_needed': refresh_needed}
