# One-time restore of the NOX "series by networks" home row.
#
# The home screen's per-service SERIES tiles (Netflix / Disney+ /
# Apple TV+ / HBO / HBO Max / FOX / Amazon / Hulu / CW) are not baked
# into the skin -- the skin only carries a couple of them. The full
# nine-tile list lives in POV's navigator.db as a single
# shortcut_folder row named 'סדרות - לפי רשתות', which the home
# widget reads.
#
# When POV self-updated (5.12 -> 6.07) it re-extracted a fresh
# navigator.db on some devices, dropping this custom row -- so those
# users lost most of the series service tiles ("some just aren't
# showing like the rest"). The movies row uses a different mechanism
# and was unaffected; this patcher only touches the series row.
#
# We restore the row to its known-good contents exactly once per
# install (guarded by a hidden setting), then never touch it again --
# so a user who later curates the row keeps their edits. The write is
# defensive: missing DB / lock / unexpected schema all leave the DB
# alone and simply retry on a later startup (the marker is stamped
# only after a successful write).

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
        kodi_utils.log('pov_series_networks_reseed_patcher: ' + msg,
                       level=level)
    except Exception:
        pass


POV_ADDON_ID = 'plugin.video.pov'
DB_RELATIVE  = 'navigator.db'

# Hidden addon setting used as the one-time marker.
RESEED_FLAG = '_pov_series_networks_reseed'
RESEED_VERSION = 'v1'

# The row we restore. list_type must match the shipped build so we
# don't create a duplicate under the unique(list_name, list_type)
# constraint.
ROW_NAME = 'סדרות - לפי רשתות'
ROW_TYPE = 'shortcut_folder'

# Known-good contents, captured verbatim from a healthy build. Kept as
# a literal string (not rebuilt from a dict) so it round-trips exactly
# as POV wrote it.
ROW_CONTENTS = (
    "[{'action': 'tmdb_tv_networks', 'iconImage': 'special://home/media/build_icons/Twilight/Shows/Networks/Shows_Netflix.png', 'mode': 'build_tvshow_list', 'name': '[B]נטפליקס[/B]', 'network_id': '213'}, "
    "{'action': 'tmdb_tv_networks', 'iconImage': 'special://home/media/build_icons/Twilight/Shows/Networks/Shows_Disney_Plus.png', 'mode': 'build_tvshow_list', 'name': '[B]דיסני פלוס[/B]', 'network_id': '2739'}, "
    "{'action': 'tmdb_tv_networks', 'iconImage': 'special://home/media/build_icons/Twilight/Shows/Networks/Shows_AppleTV.png', 'mode': 'build_tvshow_list', 'name': '[B]Apple TV+[/B]', 'network_id': '2552'}, "
    "{'action': 'tmdb_tv_networks', 'iconImage': 'special://home/media/build_icons/Twilight/Shows/Networks/Shows_HBO.png', 'mode': 'build_tvshow_list', 'name': '[B]HBO[/B]', 'network_id': '49'}, "
    "{'action': 'tmdb_tv_networks', 'iconImage': 'special://home/media/build_icons/Twilight/Shows/Networks/Shows_HBO_Max.png', 'mode': 'build_tvshow_list', 'name': '[B]HBO Max[/B]', 'network_id': '3186'}, "
    "{'action': 'tmdb_tv_networks', 'iconImage': 'special://home/media/build_icons/Twilight/Shows/Networks/Shows_FOX.png', 'mode': 'build_tvshow_list', 'name': '[B]FOX[/B]', 'network_id': '19'}, "
    "{'action': 'tmdb_tv_networks', 'iconImage': 'special://home/media/build_icons/Twilight/Shows/Networks/Shows_Amazon.png', 'mode': 'build_tvshow_list', 'name': '[B]Amazon[/B]', 'network_id': '1024'}, "
    "{'action': 'tmdb_tv_networks', 'iconImage': 'special://home/media/build_icons/Twilight/Shows/Networks/Shows_Hulu.png', 'mode': 'build_tvshow_list', 'name': '[B]Hulu[/B]', 'network_id': '453'}, "
    "{'action': 'tmdb_tv_networks', 'iconImage': 'special://home/media/build_icons/Twilight/Shows/Networks/Shows_CW.png', 'mode': 'build_tvshow_list', 'name': '[B]CW[/B]', 'network_id': '71'}]"
)


def _db_path():
    """Resolve POV's navigator.db path, or '' if POV has never run."""
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://profile/addon_data/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    path = os.path.join(base, DB_RELATIVE)
    return path if os.path.isfile(path) else ''


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


def maybe_reseed_series_networks():
    """Restore the 'series by networks' row once per install.

    Returns:
      'done_before' -- marker already set, nothing to do
      'reseeded'    -- row written, marker stamped
      'unchanged'   -- row already matched target, marker stamped
      'no_db'       -- POV not installed / addon_data not created yet
                       (marker NOT stamped -- retry next startup)
      'failed'      -- any error path (marker NOT stamped)
    """
    if _already_done():
        return 'done_before'
    if sqlite3 is None:
        return 'failed'
    path = _db_path()
    if not path:
        return 'no_db'

    conn = None
    try:
        conn = sqlite3.connect(path, timeout=2.0, isolation_level=None)
        conn.execute('PRAGMA busy_timeout=2000')
        cur = conn.cursor()

        # Schema sanity -- bail (and retry later) on anything unexpected.
        try:
            cur.execute(
                "SELECT list_contents FROM navigator "
                "WHERE list_name=? AND list_type=?", (ROW_NAME, ROW_TYPE))
            row = cur.fetchone()
        except sqlite3.DatabaseError:
            return 'failed'

        if row is not None and (row[0] or '') == ROW_CONTENTS:
            _mark_done()
            return 'unchanged'

        cur.execute('BEGIN IMMEDIATE')
        try:
            cur.execute(
                "INSERT OR REPLACE INTO navigator "
                "(list_name, list_type, list_contents) VALUES (?, ?, ?)",
                (ROW_NAME, ROW_TYPE, ROW_CONTENTS))
            cur.execute('COMMIT')
        except Exception:
            try: cur.execute('ROLLBACK')
            except Exception: pass
            return 'failed'

        _mark_done()
        _log('series-by-networks row restored (9 tiles)', level='INFO')
        return 'reseeded'
    except sqlite3.OperationalError as e:
        _log('DB locked or unreadable: {0}'.format(e), level='WARNING')
        return 'failed'
    except Exception as e:
        _log('{0}'.format(e), level='WARNING')
        return 'failed'
    finally:
        if conn is not None:
            try: conn.close()
            except Exception: pass
