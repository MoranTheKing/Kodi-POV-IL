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


POV_ADDON_ID = 'plugin.video.pov'
DB_RELATIVE  = 'navigator.db'
BAD_TOKEN    = "'navigator.favourites'"
GOOD_TOKEN   = "'navigator.favorites'"


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
