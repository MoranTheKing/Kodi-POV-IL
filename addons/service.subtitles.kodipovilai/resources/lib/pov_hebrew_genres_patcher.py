# Show POV's genre menu names in HEBREW (all skins).
#
# POV's genre menu (menus/navigator.py genres()/anime_genres()/
# multiselect_genres) and the genre picker (modules/dialogs.py genres_choice)
# take their DISPLAY names straight from the dict KEYS of
# modules/meta_lists.py: movie_genres / tvshow_genres, e.g.
#     'Action': ['28', 'genre_action.png'], ...
# Upstream POV ships those keys in English, so after a POV self-update the
# whole build's genres reverted to English on every skin. This patcher
# rewrites each genre KEY to Hebrew IN PLACE, keeping the [tmdb_id, icon]
# value untouched -- so the id (and therefore the content each genre loads)
# is unchanged; only the label becomes Hebrew.
#
# Each line is matched by its TMDB genre id AND the trailing 'genre_*.png'
# icon, so the substitution can only ever touch genre-dict lines. Idempotent
# (re-running finds the keys already Hebrew -> no change), compile()-checked
# before writing, atomic, .pyc dropped. Safe no-op if POV isn't installed or
# meta_lists.py was refactored.

import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
META_LISTS_REL = 'resources/lib/modules/meta_lists.py'
MARKER = '# AI_SUBS_POV_HEBREW_GENRES_v1'

# TMDB genre id -> Hebrew name (covers POV's movie AND tv genre dicts; ids
# shared by both dicts map to the same Hebrew, so replacing by id is safe).
GENRE_HE = {
    '28': 'אקשן',
    '12': 'הרפתקאות',
    '16': 'אנימציה',
    '35': 'קומדיה',
    '80': 'פשע',
    '99': 'דוקומנטרי',
    '18': 'דרמה',
    '10751': 'משפחה',
    '14': 'פנטזיה',
    '36': 'היסטוריה',
    '27': 'אימה',
    '10402': 'מוזיקה',
    '9648': 'מסתורין',
    '10749': 'רומנטיקה',
    '878': 'מדע בדיוני',
    '10770': 'סרט טלוויזיה',
    '53': 'מתח',
    '10752': 'מלחמה',
    '37': 'מערבון',
    '10759': 'אקשן והרפתקאות',
    '10762': 'ילדים',
    '10763': 'חדשות',
    '10764': 'ריאליטי',
    '10765': 'מדע בדיוני ופנטזיה',
    '10766': 'אופרת סבון',
    '10767': 'אירוח',
    '10768': 'מלחמה ופוליטיקה',
}


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_hebrew_genres_patcher: ' + msg, level=level)
    except Exception:
        pass


def _meta_lists_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *META_LISTS_REL.split('/'))
    return p if os.path.isfile(p) else ''


def ensure_patched():
    """Returns 'patched' | 'already_patched' | 'no_pov' | 'no_file'
    | 'unmatched' | 'compile_failed' | 'read_failed' | 'write_failed'."""
    path = _meta_lists_path()
    if not path:
        return 'no_pov' if xbmcvfs is None else 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'already_patched'

    new_content = content
    changed = 0
    for gid, he in GENRE_HE.items():
        # Match:  '<any key>' : ['<id>', 'genre_*.png']  -> replace key only.
        # The id + genre_*.png anchor guarantees we only touch genre lines.
        pat = re.compile(
            r"'[^']*'(\s*:\s*\[\s*'" + re.escape(gid)
            + r"'\s*,\s*'genre_[^']*\.png'\s*\])")
        new_content, n = pat.subn(r"'" + he + r"'\1", new_content)
        changed += n

    if changed == 0:
        _log('no genre-dict lines matched -- POV may have refactored '
             'meta_lists.py; leaving it alone', level='WARNING')
        return 'unmatched'

    # Stamp the marker on its own line right after the first newline.
    new_content = new_content.replace('\n', '\n' + MARKER + '\n', 1)

    # SAFETY: never write a file that doesn't compile.
    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'

    if new_content == content:
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

    pycache_dir = os.path.join(os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache_dir):
        for fn in os.listdir(pycache_dir):
            if fn.startswith('meta_lists.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache_dir, fn))
                except OSError:
                    pass

    _log('translated {0} genre label(s) to Hebrew in meta_lists.py'.format(
        changed), level='INFO')
    return 'patched'
