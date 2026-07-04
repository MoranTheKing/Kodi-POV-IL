# Restore POV's FENtastic genre shortcut-folder rows in navigator.db.
#
# The Arctic Fuse 3 (and FENtastic) home screen has "Movies by genre" /
# "Series by genre" widgets that read two navigator.db shortcut_folder rows:
#   'FENtastic - סרטים - זאנרים'  and  'FENtastic - סדרות - זאנרים'.
# These are the ONLY navigator.db-backed home widgets; every other POV home
# widget uses a direct action. When POV self-updates and re-extracts a fresh
# navigator.db it can drop these two rows -- so ONLY the genre widgets go empty
# ("genres stopped showing") while the rest keep working.
#
# We restore each row to its known-good build content, but ONLY when it is
# missing or empty -- a populated (possibly user-curated) row is left alone.
# One-time per install (hidden marker), then future edits are respected.
# Defensive: missing DB / lock / bad schema -> no-op, retry next boot.

import os

try:
    import sqlite3
except Exception:
    sqlite3 = None

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None

POV_ADDON_ID = 'plugin.video.pov'
DB_RELATIVE = 'navigator.db'
ROW_TYPE = 'shortcut_folder'
RESEED_FLAG = '_pov_genre_folders_reseed'
RESEED_VERSION = 'v1'

MOVIES_GENRES_NAME = 'FENtastic - סרטים - זאנרים'
TVSHOWS_GENRES_NAME = 'FENtastic - סדרות - זאנרים'
MOVIES_GENRES_CONTENTS = "[{'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_action.png', 'mode': 'build_movie_list', 'name': '[B]אקשן[/B]', 'genre_id': '28'}, {'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_adventure.png', 'mode': 'build_movie_list', 'name': '[B]הרפתקאות[/B]', 'genre_id': '12'}, {'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_animation.png', 'mode': 'build_movie_list', 'name': '[B]אנימציה[/B]', 'genre_id': '16'}, {'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_comedy.png', 'mode': 'build_movie_list', 'name': '[B]קומדיה[/B]', 'genre_id': '35'}, {'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_crime.png', 'mode': 'build_movie_list', 'name': '[B]פשע[/B]', 'genre_id': '80'}, {'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_documentary.png', 'mode': 'build_movie_list', 'name': '[B]דוקומנטרי[/B]', 'genre_id': '99'}, {'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_drama.png', 'mode': 'build_movie_list', 'name': '[B]דרמה[/B]', 'genre_id': '18'}, {'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_family.png', 'mode': 'build_movie_list', 'name': '[B]משפחה[/B]', 'genre_id': '10751'}, {'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_fantasy.png', 'mode': 'build_movie_list', 'name': '[B]פנטזיה[/B]', 'genre_id': '14'}, {'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_history.png', 'mode': 'build_movie_list', 'name': '[B]היסטוריה[/B]', 'genre_id': '36'}, {'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_horror.png', 'mode': 'build_movie_list', 'name': '[B]אימה[/B]', 'genre_id': '27'}, {'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_music.png', 'mode': 'build_movie_list', 'name': '[B]מוזיקה[/B]', 'genre_id': '10402'}, {'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_mystery.png', 'mode': 'build_movie_list', 'name': '[B]מסתורין[/B]', 'genre_id': '9648'}, {'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_romance.png', 'mode': 'build_movie_list', 'name': '[B]רומנטיקה[/B]', 'genre_id': '10749'}, {'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_scifi.png', 'mode': 'build_movie_list', 'name': '[B]מדע בדיוני[/B]', 'genre_id': '878'}, {'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_thriller.png', 'mode': 'build_movie_list', 'name': '[B]מתח[/B]', 'genre_id': '53'}, {'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_war.png', 'mode': 'build_movie_list', 'name': '[B]מלחמה[/B]', 'genre_id': '10752'}, {'action': 'tmdb_movies_genres', 'iconImage': 'genres/genre_western.png', 'mode': 'build_movie_list', 'name': '[B]מערבון[/B]', 'genre_id': '37'}]"
TVSHOWS_GENRES_CONTENTS = "[{'action': 'tmdb_tv_genres', 'iconImage': 'genres/genre_action_adventure.png', 'mode': 'build_tvshow_list', 'name': '[B]אקשן והרפתקאות[/B]', 'genre_id': '10759'}, {'action': 'tmdb_tv_genres', 'iconImage': 'genres/genre_animation.png', 'mode': 'build_tvshow_list', 'name': '[B]אנימציה[/B]', 'genre_id': '16'}, {'action': 'tmdb_tv_genres', 'iconImage': 'genres/genre_comedy.png', 'mode': 'build_tvshow_list', 'name': '[B]קומדיה[/B]', 'genre_id': '35'}, {'action': 'tmdb_tv_genres', 'iconImage': 'genres/genre_crime.png', 'mode': 'build_tvshow_list', 'name': '[B]פשע[/B]', 'genre_id': '80'}, {'action': 'tmdb_tv_genres', 'iconImage': 'genres/genre_documentary.png', 'mode': 'build_tvshow_list', 'name': '[B]דוקומנטרי[/B]', 'genre_id': '99'}, {'action': 'tmdb_tv_genres', 'iconImage': 'genres/genre_drama.png', 'mode': 'build_tvshow_list', 'name': '[B]דרמה[/B]', 'genre_id': '18'}, {'action': 'tmdb_tv_genres', 'iconImage': 'genres/genre_family.png', 'mode': 'build_tvshow_list', 'name': '[B]משפחה[/B]', 'genre_id': '10751'}, {'action': 'tmdb_tv_genres', 'iconImage': 'genres/genre_kids.png', 'mode': 'build_tvshow_list', 'name': '[B]ילדים[/B]', 'genre_id': '10762'}, {'action': 'tmdb_tv_genres', 'iconImage': 'genres/genre_mystery.png', 'mode': 'build_tvshow_list', 'name': '[B]מסתורין[/B]', 'genre_id': '9648'}, {'action': 'tmdb_tv_genres', 'iconImage': 'genres/genre_news.png', 'mode': 'build_tvshow_list', 'name': '[B]חדשות[/B]', 'genre_id': '10763'}, {'action': 'tmdb_tv_genres', 'iconImage': 'genres/genre_reality.png', 'mode': 'build_tvshow_list', 'name': '[B]ריאליטי[/B]', 'genre_id': '10764'}, {'action': 'tmdb_tv_genres', 'iconImage': 'genres/genre_scifi_fantasy.png', 'mode': 'build_tvshow_list', 'name': '[B]מדע בדיוני ופנטזיה[/B]', 'genre_id': '10765'}, {'action': 'tmdb_tv_genres', 'iconImage': 'genres/genre_soap.png', 'mode': 'build_tvshow_list', 'name': '[B]אופרת סבון[/B]', 'genre_id': '10766'}, {'action': 'tmdb_tv_genres', 'iconImage': 'genres/genre_talk.png', 'mode': 'build_tvshow_list', 'name': '[B]אירוח[/B]', 'genre_id': '10767'}, {'action': 'tmdb_tv_genres', 'iconImage': 'genres/genre_war_politics.png', 'mode': 'build_tvshow_list', 'name': '[B]מלחמה ופוליטיקה[/B]', 'genre_id': '10768'}, {'action': 'tmdb_tv_genres', 'iconImage': 'genres/genre_western.png', 'mode': 'build_tvshow_list', 'name': '[B]מערבון[/B]', 'genre_id': '37'}]"

TARGETS = (
    (MOVIES_GENRES_NAME, MOVIES_GENRES_CONTENTS),
    (TVSHOWS_GENRES_NAME, TVSHOWS_GENRES_CONTENTS),
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_genre_folders_reseed_patcher: ' + msg, level=level)
    except Exception:
        pass


def _db_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://profile/addon_data/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, DB_RELATIVE)
    return p if os.path.isfile(p) else ''


def _already_done():
    if kodi_utils is None:
        return False
    try:
        return kodi_utils.get_setting(RESEED_FLAG, '') == RESEED_VERSION
    except Exception:
        return False


def _mark_done():
    if kodi_utils is None:
        return
    try:
        kodi_utils.set_setting(RESEED_FLAG, RESEED_VERSION)
    except Exception:
        pass


def _is_empty(contents):
    s = (contents or '').strip()
    return s in ('', '[]', '()', 'None')


def maybe_reseed_genre_folders():
    """Restore the two genre shortcut-folder rows once, only where missing/empty.
    Returns 'done_before' | 'reseeded' | 'unchanged' | 'no_db' | 'failed'."""
    if _already_done():
        return 'done_before'
    if sqlite3 is None:
        return 'failed'
    path = _db_path()
    if not path:
        return 'no_db'
    conn = None
    restored = []
    try:
        conn = sqlite3.connect(path, timeout=2.0, isolation_level=None)
        conn.execute('PRAGMA busy_timeout=2000')
        cur = conn.cursor()
        for name, canonical in TARGETS:
            try:
                row = cur.execute(
                    "SELECT list_contents FROM navigator "
                    "WHERE list_name=? AND list_type=?", (name, ROW_TYPE)).fetchone()
            except sqlite3.DatabaseError:
                return 'failed'
            if row is not None and not _is_empty(row[0]):
                continue  # populated -> leave alone
            try:
                cur.execute('BEGIN IMMEDIATE')
                cur.execute(
                    "INSERT OR REPLACE INTO navigator "
                    "(list_name, list_type, list_contents) VALUES (?, ?, ?)",
                    (name, ROW_TYPE, canonical))
                cur.execute('COMMIT')
                restored.append(name)
            except Exception:
                try: cur.execute('ROLLBACK')
                except Exception: pass
                return 'failed'
        _mark_done()
        if restored:
            _log('restored genre folders: {0}'.format(
                ', '.join(n.split(' - ')[1] for n in restored)), level='INFO')
            return 'reseeded'
        return 'unchanged'
    except sqlite3.OperationalError as e:
        _log('DB locked/unreadable: {0}'.format(e), level='WARNING')
        return 'failed'
    except Exception as e:
        _log('{0}'.format(e), level='WARNING')
        return 'failed'
    finally:
        if conn is not None:
            try: conn.close()
            except Exception: pass
