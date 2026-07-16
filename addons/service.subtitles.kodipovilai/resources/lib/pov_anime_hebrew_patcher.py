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
    import sqlite3
except Exception:
    sqlite3 = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None

# POV stores the RENDERED main menus in navigator.db (seeded ONCE from
# menu_lists.py) and caches them as Window(10000) properties. Patching the .py
# only affects a FRESH seed, so existing installs keep the English anime menu
# forever. We therefore ALSO rewrite the stored rows + clear the memory cache.
NAV_DB_REL = 'navigator.db'
# Rows carrying anime labels: AnimeList = the 13 submenu names; RootList = the
# top-level 'Anime' entry. Both stored per list_type.
_DB_ROWS = ('AnimeList', 'RootList')
_DB_TYPES = ('default', 'edited', 'shortcut_folder')


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


def _nav_db_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://profile/addon_data/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, NAV_DB_REL)
    return p if os.path.isfile(p) else ''


def _apply_menu_map(text):
    """Apply the anime-name English->Hebrew replacements to a stored
    list_contents string (a repr()'d list of dicts, so the same
    "'name': 'English'" tokens match). Returns (new_text, hit_count)."""
    hits = 0
    for old, new in MENU_LISTS_MAP:
        if old in text:
            text = text.replace(old, new)
            hits += 1
    return text, hits


def _clear_menu_memory_cache():
    """Clear POV's in-memory menu cache (Window(10000) properties named
    pov_<list>_<type>) so the rewritten DB rows are read fresh THIS session
    instead of only after POV's process restarts."""
    try:
        import xbmcgui
        w = xbmcgui.Window(10000)
        for name in _DB_ROWS:
            for ltype in _DB_TYPES:
                try:
                    w.clearProperty('pov_{0}_{1}'.format(name, ltype))
                except Exception:
                    pass
    except Exception:
        pass


def _patch_navigator_db():
    """Rewrite the anime labels in POV's navigator.db (the ACTUAL source the
    main menu renders from -- menu_lists.py only seeds it once). Only the
    AnimeList/RootList rows are touched, only the anime name tokens are
    replaced, and only when present -- everything else (user edits, other
    lists) is left byte-identical. Returns 'no_sqlite' | 'no_db' | 'unchanged'
    | 'patched' | 'failed'. Never raises."""
    if sqlite3 is None:
        return 'no_sqlite'
    path = _nav_db_path()
    if not path:
        return 'no_db'
    changed = False
    errored = False
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=2.0, isolation_level=None)
        conn.execute('PRAGMA busy_timeout=2000')
        cur = conn.cursor()
        for name in _DB_ROWS:
            if errored:
                break
            for ltype in _DB_TYPES:
                try:
                    cur.execute(
                        'SELECT list_contents FROM navigator '
                        'WHERE list_name=? AND list_type=?', (name, ltype))
                    row = cur.fetchone()
                except sqlite3.DatabaseError:
                    # Locked / corrupt / unexpected schema -> stop touching the
                    # DB. Fall through to the shared exit so a partial rewrite
                    # still clears the in-memory cache for the rows we DID
                    # change (otherwise POV keeps serving the stale English
                    # props this session).
                    errored = True
                    break
                if not row:
                    continue
                cur_contents = row[0] or ''
                new_contents, hits = _apply_menu_map(cur_contents)
                if not hits or new_contents == cur_contents:
                    continue
                try:
                    cur.execute('BEGIN IMMEDIATE')
                    cur.execute(
                        'UPDATE navigator SET list_contents=? '
                        'WHERE list_name=? AND list_type=?',
                        (new_contents, name, ltype))
                    cur.execute('COMMIT')
                    changed = True
                except Exception:
                    try:
                        cur.execute('ROLLBACK')
                    except Exception:
                        pass
    except sqlite3.OperationalError:
        return 'failed'  # DB locked/unreadable -- retry next startup
    except Exception:
        return 'failed'
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    if changed:
        # Always clear the in-memory cache when we committed ANY row -- even if
        # a later row hit a DB error -- so POV serves the Hebrew rows this
        # session instead of the stale English Window props.
        _clear_menu_memory_cache()
        _log('navigator.db anime rows translated to Hebrew')
        return 'patched'
    return 'failed' if errored else 'unchanged'


def ensure_patched():
    """Translate POV's Anime section to Hebrew. Idempotent, defensive,
    never raises. Returns a short combined status string.

    Three surfaces: menu_lists.py (fresh-install seed), navigator.py (anime
    breadcrumb titles), and navigator.db (the stored menu existing installs
    actually render -- the real fix for a device that already seeded English)."""
    a = _patch_file(MENU_LISTS_REL, MENU_LISTS_MAP)
    # Patch whichever navigator.py this POV release ships (only one exists).
    b = 'no_file'
    for rel in NAVIGATOR_RELS:
        if _pov_path(rel):
            b = _patch_file(rel, NAVIGATOR_MAP)
            break
    c = _patch_navigator_db()
    return 'menu_lists={0}, navigator={1}, db={2}'.format(a, b, c)
