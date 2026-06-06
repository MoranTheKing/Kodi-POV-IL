# Self-healing fix for a typo in POV's bundled main-menu DB.
#
# The shipped userdata/addon_data/plugin.video.pov/navigator.db
# encodes the home-screen tile list (RootList) with the Favorites
# entry pointing at the URL
#
#     mode=navigator.favourites    (UK spelling, with 'u')
#
# but plugin.video.pov's resources/lib/menus/navigator.py defines
# the method as `def favorites(self):` (US spelling, no 'u'). POV's
# router uses getattr(cls, mode, None) and silently returns None
# when the method is missing, so endOfDirectory() is never called.
# Kodi waits, hits its 5-second script-didn't-finish timeout, kills
# the plugin, and bounces the user back to the previous screen --
# manifesting as Kodi "freezing" for about a minute on every
# Favorites click. (Long-press Favorites Manager / context-menu
# add-to-favorites work fine; only the home tile is broken.)
#
# We fix the row in place by replacing the bad substring. The
# update is idempotent (re-run is a no-op), defensive (open errors
# / lock errors / unexpected schemas leave the DB alone), and
# narrow (only the one substring is rewritten, the rest of the
# RootList is untouched).
#
# Future installs ship a pre-corrected navigator.db so this patcher
# is mostly belt-and-braces for users already on the broken DB.

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


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_navigator_patcher: ' + msg, level=level)
    except Exception:
        pass


POV_ADDON_ID = 'plugin.video.pov'
DB_RELATIVE  = 'navigator.db'
BAD_TOKEN    = "'navigator.favourites'"
GOOD_TOKEN   = "'navigator.favorites'"

# Personal-area lists -- the FENtastic widget on the movies/tvshows
# pages reads these two rows from POV's navigator.db. The shipped
# baseline only had a Trakt collection entry; the v0.2.18 patcher
# added a TMDB tile. v0.2.22 also appends a POV-local-favorites
# tile so users with no service connected still have a working
# personal area. Migration table:
#   V1 = baseline (Continue/Next + Trakt)
#   V2 = post-v0.2.18 (Continue/Next + TMDB + Trakt)
#   V3 = target (Continue/Next + TMDB + Trakt + POV)
# Each row is rewritten only if its current list_contents matches
# one of the known older versions exactly. User customizations
# don't match and are left alone.
MOVIES_PA_NAME = 'FENtastic - סרטים - איזור אישי'
MOVIES_PA_V1 = "[{'action': 'in_progress_movies', 'iconImage': 'player', 'mode': 'build_movie_list', 'name': '[B]המשך צפייה[/B]'}, {'action': 'trakt_collection', 'category_name': 'Movies Collection', 'iconImage': 'trakt', 'mode': 'build_movie_list', 'name': '[B]הסרטים שלי (Trakt)[/B]'}]"
MOVIES_PA_V2 = "[{'action': 'in_progress_movies', 'iconImage': 'player', 'mode': 'build_movie_list', 'name': '[B]המשך צפייה[/B]'}, {'action': 'tmdb_favorites', 'iconImage': 'tmdb', 'mode': 'build_movie_list', 'name': '[B]הסרטים שלי (TMDB)[/B]'}, {'action': 'trakt_collection', 'category_name': 'Movies Collection', 'iconImage': 'trakt', 'mode': 'build_movie_list', 'name': '[B]הסרטים שלי (Trakt)[/B]'}]"
MOVIES_PA_V3 = "[{'action': 'in_progress_movies', 'iconImage': 'player', 'mode': 'build_movie_list', 'name': '[B]המשך צפייה[/B]'}, {'action': 'tmdb_favorites', 'iconImage': 'tmdb', 'mode': 'build_movie_list', 'name': '[B]הסרטים שלי (TMDB)[/B]'}, {'action': 'trakt_collection', 'category_name': 'Movies Collection', 'iconImage': 'trakt', 'mode': 'build_movie_list', 'name': '[B]הסרטים שלי (Trakt)[/B]'}, {'action': 'favorites_movies', 'iconImage': 'favorites', 'mode': 'build_movie_list', 'name': '[B]הסרטים שלי (POV)[/B]'}]"
MOVIES_PA_V4 = MOVIES_PA_V3.replace("'tmdb_favorites'", "'tmdb_my_movies'").replace("'trakt_collection'", "'trakt_my_movies'")

TVSHOWS_PA_NAME = 'FENtastic - סדרות - איזור אישי'
TVSHOWS_PA_V1 = "[{'iconImage': 'next_episodes', 'mode': 'build_next_episode', 'name': '[B]הפרק הבא[/B]'}, {'action': 'trakt_collection', 'category_name': 'TV Shows Collection', 'iconImage': 'trakt', 'mode': 'build_tvshow_list', 'name': '[B]הסדרות שלי (Trakt)[/B]'}]"
TVSHOWS_PA_V2 = "[{'iconImage': 'next_episodes', 'mode': 'build_next_episode', 'name': '[B]הפרק הבא[/B]'}, {'action': 'tmdb_favorites', 'iconImage': 'tmdb', 'mode': 'build_tvshow_list', 'name': '[B]הסדרות שלי (TMDB)[/B]'}, {'action': 'trakt_collection', 'category_name': 'TV Shows Collection', 'iconImage': 'trakt', 'mode': 'build_tvshow_list', 'name': '[B]הסדרות שלי (Trakt)[/B]'}]"
TVSHOWS_PA_V3 = "[{'iconImage': 'next_episodes', 'mode': 'build_next_episode', 'name': '[B]הפרק הבא[/B]'}, {'action': 'tmdb_favorites', 'iconImage': 'tmdb', 'mode': 'build_tvshow_list', 'name': '[B]הסדרות שלי (TMDB)[/B]'}, {'action': 'trakt_collection', 'category_name': 'TV Shows Collection', 'iconImage': 'trakt', 'mode': 'build_tvshow_list', 'name': '[B]הסדרות שלי (Trakt)[/B]'}, {'action': 'favorites_tvshows', 'iconImage': 'favorites', 'mode': 'build_tvshow_list', 'name': '[B]הסדרות שלי (POV)[/B]'}]"
TVSHOWS_PA_V4 = TVSHOWS_PA_V3.replace("'tmdb_favorites'", "'tmdb_my_tvshows'").replace("'trakt_collection'", "'trakt_my_tvshows'")


def _db_path():
    """Resolve the on-disk path to POV's navigator.db. Returns ''
    when Kodi APIs aren't available or POV has never run (no
    addon_data dir yet, so no DB)."""
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://profile/addon_data/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    path = os.path.join(base, DB_RELATIVE)
    return path if os.path.isfile(path) else ''


def maybe_fix_favourites_typo():
    """Open POV's navigator.db, rewrite the RootList row if it
    contains the bad UK-spelling token, leave it alone otherwise.

    Returns:
      'fixed'     -- token was present, rewrite committed
      'unchanged' -- token already correct (or row missing token)
      'no_db'     -- POV not installed / addon_data not yet created
      'failed'    -- any other error path; details swallowed
    """
    if sqlite3 is None:
        return 'failed'
    path = _db_path()
    if not path:
        return 'no_db'

    conn = None
    try:
        # isolation_level=None lets us drive transactions explicitly;
        # busy_timeout buys 2s for POV's own connection to release
        # the lock if it happens to be mid-write.
        conn = sqlite3.connect(path, timeout=2.0, isolation_level=None)
        conn.execute('PRAGMA busy_timeout=2000')
        cur = conn.cursor()

        # Schema sanity. If the table or columns aren't what we
        # expect, leave the DB alone -- POV may have re-shaped it.
        try:
            cur.execute(
                "SELECT list_contents FROM navigator "
                "WHERE list_name='RootList'")
            row = cur.fetchone()
        except sqlite3.DatabaseError:
            return 'unchanged'
        if not row:
            return 'unchanged'
        contents = row[0] or ''
        if BAD_TOKEN not in contents:
            return 'unchanged'

        new_contents = contents.replace(BAD_TOKEN, GOOD_TOKEN)

        cur.execute('BEGIN IMMEDIATE')
        try:
            cur.execute(
                "UPDATE navigator SET list_contents=? "
                "WHERE list_name='RootList'", (new_contents,))
            cur.execute('COMMIT')
        except Exception:
            try: cur.execute('ROLLBACK')
            except Exception: pass
            return 'failed'

        return 'fixed'
    except sqlite3.OperationalError:
        # DB locked or unreadable -- try again next startup.
        return 'failed'
    except Exception:
        return 'failed'
    finally:
        if conn is not None:
            try: conn.close()
            except Exception: pass


def maybe_fix_personal_area_lists():
    """Replace the FENtastic personal-area rows in POV's navigator.db
    so the widget on movies/shows pages leads with TMDB Favorites
    instead of Trakt Collection. Each row is rewritten only if its
    current list_contents matches the shipped baseline byte-for-byte;
    if the user (or some other patcher) has touched the row, leave it
    alone.

    Returns a {row_name: status} dict, with status one of:
      'fixed'     -- row matched baseline, rewrite committed
      'unchanged' -- row already migrated (or already different)
      'no_row'    -- row missing from DB (POV schema changed?)
      'failed'    -- any error path
    Or {'_status': 'no_db'} if POV isn't installed yet.
    """
    if sqlite3 is None:
        return {'_status': 'failed'}
    path = _db_path()
    if not path:
        return {'_status': 'no_db'}

    # (row_name, known_old_versions, target_version) -- the patcher
    # rewrites the row to `target` if its current content matches
    # any of the known_old_versions exactly. Anything else is treated
    # as user customization and left alone.
    targets = (
        (MOVIES_PA_NAME, (MOVIES_PA_V1, MOVIES_PA_V2, MOVIES_PA_V3), MOVIES_PA_V4),
        (TVSHOWS_PA_NAME, (TVSHOWS_PA_V1, TVSHOWS_PA_V2, TVSHOWS_PA_V3), TVSHOWS_PA_V4),
    )
    out = {}
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=2.0, isolation_level=None)
        conn.execute('PRAGMA busy_timeout=2000')
        cur = conn.cursor()
        for row_name, known_old_versions, target in targets:
            try:
                cur.execute(
                    "SELECT list_contents FROM navigator "
                    "WHERE list_name=?", (row_name,))
                row = cur.fetchone()
            except sqlite3.DatabaseError:
                out[row_name] = 'failed'
                continue
            if not row:
                out[row_name] = 'no_row'
                continue
            current = row[0] or ''
            if current == target:
                out[row_name] = 'unchanged'
                continue
            if current not in known_old_versions:
                # User customized or in an unknown state -- don't touch.
                out[row_name] = 'unchanged'
                continue
            try:
                cur.execute('BEGIN IMMEDIATE')
                cur.execute(
                    "UPDATE navigator SET list_contents=? "
                    "WHERE list_name=?", (target, row_name))
                cur.execute('COMMIT')
                out[row_name] = 'fixed'
            except Exception:
                try: cur.execute('ROLLBACK')
                except Exception: pass
                out[row_name] = 'failed'
    except sqlite3.OperationalError as e:
        _log('personal-area: DB locked or unreadable: {0}'.format(e),
             level='WARNING')
        return {'_status': 'failed'}
    except Exception as e:
        _log('personal-area: {0}'.format(e), level='WARNING')
        return {'_status': 'failed'}
    finally:
        if conn is not None:
            try: conn.close()
            except Exception: pass
    _log('personal-area: {0}'.format(
        ', '.join('{0}={1}'.format(k.split(' - ')[1], v)
                  for k, v in out.items())), level='INFO')
    return out
