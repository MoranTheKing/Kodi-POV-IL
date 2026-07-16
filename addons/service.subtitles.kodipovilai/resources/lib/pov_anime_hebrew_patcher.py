# Hebrew-ise POV's ANIME section (all skins).
#
# Unlike the Movies/TV menus (numeric string-ids, translated by
# pov_hebrew_ui_patcher via strings.po), the Anime area ships HARDCODED
# English in two places:
#   * modules/menu_lists.py -- the root 'Anime' entry + all 13 anime_list
#     menu names ('Series Trending', 'Movies Popular', ...).
#   * indexers/navigator.py -- the my-lists 'Anime Calendar' / 'Dropped TV
#     Shows' labels, and the 'ANIME %s: %s %s' breadcrumb titles that
#     anime_years()/anime_genres() build.
# Genre ITEM names inside those menus are already Hebrew via
# pov_hebrew_genres_patcher (shared meta_lists dicts), and the content
# itself is TMDB metadata -- so translating these two files completes the
# Anime area.
#
# Replacements are exact-token, so they can only ever touch the intended
# labels. Idempotent by construction (once Hebrew, the English tokens are
# gone -> no-op), compile()-checked before writing (never break POV), atomic
# write, stale .pyc dropped, and self-healing: a POV self-update that
# restores the English files is re-patched on the next Kodi start.
# Replacement strings use DOUBLE quotes where the Hebrew contains an
# apostrophe (ז'אנר) so the patched source stays valid Python.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
MENU_LISTS_REL = 'resources/lib/modules/menu_lists.py'
# navigator.py moved between POV releases: indexers/ in 5.12, menus/ in 6.07.
# Try both; whichever exists gets patched (the other is a clean no_file).
NAVIGATOR_RELS = (
    'resources/lib/menus/navigator.py',
    'resources/lib/indexers/navigator.py',
)

# modules/menu_lists.py -- exact source tokens (single-quoted English) -> the
# replacement Python expression (note double quotes around Hebrew with ').
MENU_LISTS_MAP = (
    ("{'name': 'Anime', 'iconImage': ''", "{'name': 'אנימה', 'iconImage': ''"),
    ("'name': 'Series Calendar'", "'name': 'לוח שידורים — סדרות'"),
    ("'name': 'Series Trending'", "'name': 'סדרות חמות עכשיו'"),
    ("'name': 'Series Most Watched'", "'name': 'הסדרות הנצפות ביותר'"),
    ("'name': 'Series Popular'", "'name': 'סדרות פופולריות'"),
    ("'name': 'Series Recent Released'", "'name': 'סדרות שיצאו לאחרונה'"),
    ("'name': 'Series Genres'", "'name': \"סדרות לפי ז'אנר\""),
    ("'name': 'Series Years'", "'name': 'סדרות לפי שנה'"),
    ("'name': 'Movies Trending'", "'name': 'סרטים חמים עכשיו'"),
    ("'name': 'Movies Most Watched'", "'name': 'הסרטים הנצפים ביותר'"),
    ("'name': 'Movies Popular'", "'name': 'סרטים פופולריים'"),
    ("'name': 'Movies Recent Released'", "'name': 'סרטים שיצאו לאחרונה'"),
    ("'name': 'Movies Genres'", "'name': \"סרטים לפי ז'אנר\""),
    ("'name': 'Movies Years'", "'name': 'סרטים לפי שנה'"),
)

# indexers/navigator.py -- the my-lists labels line + the two anime
# breadcrumb-title builders. menu_type is in scope at both builder sites.
NAVIGATOR_MAP = (
    ("cal_str, ani_str, drp_str = ls(32081), 'Anime Calendar', "
     "'Dropped TV Shows'",
     "cal_str, ani_str, drp_str = ls(32081), 'לוח שידורי אנימה', "
     "'סדרות שנזנחו'"),
    ("list_name = 'ANIME %s: %s %s' % (lst_ins.upper(), str(i), ls(32460))",
     "list_name = '%s: %s' % (('סרטי אנימה' if menu_type == 'movie' "
     "else 'סדרות אנימה'), str(i))"),
    ("list_name = 'ANIME %s: %s %s' % (lst_ins.upper(), genre, ls(32470))",
     "list_name = '%s: %s' % (('סרטי אנימה' if menu_type == 'movie' "
     "else 'סדרות אנימה'), genre)"),
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_anime_hebrew_patcher: ' + msg, level=level)
    except Exception:
        pass


def _pov_path(rel):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *rel.split('/'))
    return p if os.path.isfile(p) else ''


def _drop_pyc(path):
    try:
        d = os.path.join(os.path.dirname(path), '__pycache__')
        base = os.path.splitext(os.path.basename(path))[0] + '.'
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.startswith(base):
                    try:
                        os.remove(os.path.join(d, fn))
                    except OSError:
                        pass
    except Exception:
        pass


def _patch_file(rel, pairs):
    """Apply exact-token replacements to one POV file. Returns
    'no_file' | 'unchanged' | 'patched' | 'compile_failed' | 'write_failed'
    | 'read_failed'. 'unchanged' covers both already-Hebrew and
    shape-changed-upstream (each pair is optional; we log the misses)."""
    path = _pov_path(rel)
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed for {0}: {1}'.format(rel, e), level='WARNING')
        return 'read_failed'
    new_content = content
    hits = 0
    for old, new in pairs:
        if old in new_content:
            new_content = new_content.replace(old, new, 1)
            hits += 1
        elif new not in new_content:
            # neither the English token nor our Hebrew is present -> POV
            # reshaped this line upstream; skip it but say so once.
            _log('{0}: anchor not found: {1!r}'.format(rel, old[:60]),
                 level='DEBUG')
    if new_content == content:
        return 'unchanged'
    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('{0}: patched content would not compile -- skipping ({1})'
             .format(rel, e), level='WARNING')
        return 'compile_failed'
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
        _log('write failed for {0}: {1}'.format(rel, e), level='WARNING')
        return 'write_failed'
    _drop_pyc(path)
    _log('{0}: {1} label(s) set to Hebrew'.format(rel, hits))
    return 'patched'


def ensure_patched():
    """Translate POV's Anime section to Hebrew. Idempotent, defensive,
    never raises. Returns a short combined status string."""
    a = _patch_file(MENU_LISTS_REL, MENU_LISTS_MAP)
    # Patch whichever navigator.py this POV release ships (only one exists).
    b = 'no_file'
    for rel in NAVIGATOR_RELS:
        if _pov_path(rel):
            b = _patch_file(rel, NAVIGATOR_MAP)
            break
    return 'menu_lists={0}, navigator={1}'.format(a, b)
