# Make POV's genre menu show a DISTINCT icon per genre (both skins).
#
# Root cause (found after the FENtastic screenshot showed every genre
# with the same default tile): POV's menus/navigator.py genres() and
# anime_genres() call
#     self._add_item({... 'genre_id': value[0], 'name': genre},
#                    'genres.png', list_name=list_name)
# i.e. they hard-code the single generic 'genres.png' for EVERY genre --
# even though POV's own genre dicts (modules/meta_lists.py) already store
# a per-genre icon filename in value[1] (e.g. ['28', 'genre_action.png'])
# and POV ships those PNGs in resources/skins/Default/media/genres/.
# The icon was right there; the menu just never used it.
#
# Both FENtastic and AF3 open genres via mode=navigator.genres, so fixing
# this one call fixes the icons on BOTH skins (FENtastic's
# favourites.xml -> navigator.genres; AF3's genre rows resolve the same
# live menu). The navigator.db-row repaint we added earlier only helped
# AF3's cached shortcut rows; this is the real, shared fix.
#
# What this patcher does:
#   1. Rewrites the two `..., 'genres.png', list_name=list_name)` calls in
#      genres() / anime_genres() to `..., 'genres/%s' % value[1],
#      list_name=list_name)` so each genre gets its own icon. (The
#      multiselect "all genres" entry at the top keeps 'genres.png'.)
#   2. Installs our nicer line-art genre PNGs into POV's
#      resources/skins/Default/media/genres/ (only filling gaps / the
#      ones we ship), so the icons look consistent and the one missing
#      stock icon (genre_tv.png) exists.
#
# Marker-gated, idempotent, atomic write, drops stale .pyc. Safe no-op if
# POV isn't installed or navigator.py was refactored.

import os
import re
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
NAVIGATOR_REL = 'resources/lib/menus/navigator.py'
POV_GENRE_MEDIA_REL = 'resources/skins/Default/media/genres'

MARKER = '# AI_SUBS_POV_GENRE_ICONS_v2'

# The exact per-genre _add_item call (in genres() AND anime_genres()):
#   self._add_item({...}, 'genres.png', list_name=list_name)
# We require it to carry 'genre_id': value[0] so we ONLY touch the genre
# loops, never the multiselect header (which has no list_name=...).
_GENRE_CALL_RE = re.compile(
    rb"(?P<head>self\._add_item\(\{[^}]*'genre_id': value\[0\][^}]*\}, )"
    rb"'genres\.png'(?P<tail>, list_name=list_name\))",
)

# build_shortcut_folder_list (the path AF3's genre WIDGETS use) blindly
# prepends media_path() to a non-network item's iconImage:
#   icon = item_get('iconImage') if item_get('network_id','') != '' \
#          else '%s%s' % (icon_path, item_get('iconImage'))
# So an ABSOLUTE special:// iconImage gets doubled into a broken path ->
# POV-logo fallback. Harden it to pass absolute paths through unchanged
# (and keep prepending media_path only for bare relative names). This
# makes genre icons robust no matter what value the navigator.db rows
# hold.
_SHORTCUT_ICON_OLD = (
    b"icon = item_get('iconImage') if item_get('network_id', '') != '' "
    b"else '%s%s' % (icon_path, item_get('iconImage'))")
_SHORTCUT_ICON_NEW = (
    b"icon = (item_get('iconImage') if (item_get('network_id', '') != '' "
    b"or str(item_get('iconImage') or '').startswith(('special://', "
    b"'http', 'resource://'))) else '%s%s' % (icon_path, "
    b"item_get('iconImage')))")


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_genre_icons_patcher: ' + msg, level=level)
    except Exception:
        pass


def _pov_base():
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''


def _install_genre_pngs(base):
    """Copy our bundled genre PNGs into POV's media/genres/, filling any
    that are missing (e.g. genre_tv.png) and refreshing to our cleaner
    set. Best-effort; never raises."""
    here = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.join(here, 'media_assets', 'pov_genres')
    if not os.path.isdir(src_dir):
        return 0
    dst_dir = os.path.join(base, *POV_GENRE_MEDIA_REL.split('/'))
    try:
        if not os.path.isdir(dst_dir):
            os.makedirs(dst_dir)
    except OSError:
        return 0
    n = 0
    for fn in os.listdir(src_dir):
        if not fn.lower().endswith('.png'):
            continue
        src = os.path.join(src_dir, fn)
        dst = os.path.join(dst_dir, fn)
        try:
            tmp = dst + '.aitmp'
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
            n += 1
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return n


def ensure_patched():
    """Returns 'patched' | 'already_patched' | 'no_pov' | 'no_file'
    | 'unmatched' | 'read_failed' | 'write_failed'."""
    base = _pov_base()
    if not base or not os.path.isdir(base):
        return 'no_pov'

    # Always (cheaply) make sure the per-genre PNGs are on disk -- the
    # rewrite is useless if the icon files are missing.
    installed = _install_genre_pngs(base)

    path = os.path.join(base, NAVIGATOR_REL)
    if not os.path.isfile(path):
        return 'no_file'
    try:
        with open(path, 'rb') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER.encode('utf-8') in content:
        return 'already_patched'

    matches = list(_GENRE_CALL_RE.finditer(content))
    if not matches:
        _log('per-genre _add_item call not found in navigator.py -- POV '
             'may have refactored; leaving icons as-is', level='WARNING')
        return 'unmatched'

    # Replace every per-genre call to use the genre's own icon (value[1]).
    def _repl(m):
        return (m.group('head')
                + b"'genres/%s' % value[1]"
                + m.group('tail'))
    new_content = _GENRE_CALL_RE.sub(_repl, content)
    # Harden build_shortcut_folder_list so an absolute special:// icon
    # isn't doubled into a broken path (best-effort; only if the exact
    # line is present).
    if _SHORTCUT_ICON_OLD in new_content:
        new_content = new_content.replace(
            _SHORTCUT_ICON_OLD, _SHORTCUT_ICON_NEW, 1)
    # Tag with the marker on its own line right after the genres() def so
    # re-runs are detected. (Append a comment near the top of the file.)
    new_content = new_content.replace(
        b'\n', b'\n' + MARKER.encode('utf-8') + b'\n', 1)

    tmp_path = path + '.aitmp'
    try:
        with open(tmp_path, 'wb') as f:
            f.write(new_content)
        os.replace(tmp_path, path)
    except OSError as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'

    pycache_dir = os.path.join(os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache_dir):
        for fn in os.listdir(pycache_dir):
            if fn.startswith('navigator.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache_dir, fn))
                except OSError:
                    pass

    _log('per-genre icons enabled in navigator.py ({0} genre call(s) '
         'rewritten, {1} png(s) installed)'.format(
             len(matches), installed), level='INFO')
    return 'patched'
