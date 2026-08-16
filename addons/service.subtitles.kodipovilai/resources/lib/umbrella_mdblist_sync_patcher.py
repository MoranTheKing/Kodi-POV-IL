# Umbrella's MDBList watched-history sync loses episodes permanently.
#
# THE REPORT: POV shows the right progress. In Umbrella, "פרקים בהמשך צפייה"
# (episodes) shows the correct next episode, but "סדרות בהמשך צפייה" (shows)
# is stuck several episodes back. Pressing Umbrella's own "Force MDBList Sync
# to local database" fixes it.
#
# WHY THE TWO LISTS DISAGREE. They do not read the same thing:
#   * the EPISODES list scrapes MDBList live (mdblist_directProgressScrape),
#     and menus/episodes.py re-fetches whenever MDBList's watched-activity
#     stamp is newer than its cache. It is always right.
#   * the SHOWS list is reconstructed locally, in menus/tvshows.py's
#     mdblist_tvshow_progress(), out of the mdb_watched_episodes TABLE. It
#     shows whatever the table last managed to ingest.
# So "shows is stuck" means the table is missing rows, and the force button
# fixes it because it wipes the tables and re-syncs from 1970.
#
# WHY THE TABLE GOES MISSING ROWS. modules/mdblist.py sync_watchedProgress()
# pages through /sync/watched?since=<db_last>, and then, at the end, calls
# update_last_watched_at(), which stores datetime.utcnow() -- the WALL CLOCK
# AT SYNC TIME, not the newest last_watched_at it actually ingested. The next
# run asks only for items after that moment.
#
# That write is unconditional. `if not data: break` leaves the loop on an
# empty page or a failed request, and the cursor advances anyway. So one
# transient MDBList error, one empty response, or a few seconds of clock skew
# between the device and MDBList's server, and everything in that window is
# skipped FOREVER -- the cursor only ever moves forward. Exactly the shape of
# our own enrich bug, where a failure still wrote progress.
#
# THE FIX, in two halves:
#   1. Overlap the window. The fetch starts 30 days before the stored cursor,
#      so a window missed for any reason is picked up on the next sync instead
#      of never. This is free: upsert_watched_episode() is INSERT OR REPLACE,
#      so re-ingesting the same rows changes nothing.
#   2. Repair the damage already done. An overlap only heals 30 days back, and
#      this user's table was missing far more, so applying the patch also
#      clears the stored cursor once -- the next scheduled sync then backfills
#      from 1970, which is what the force button does, without the user having
#      to know the button exists.
#
# The guard above the fetch (`api_last - db_last < 60`) is deliberately left
# alone: it compares MDBList's newest activity against the last sync time to
# decide whether to bother, and that reasoning is sound. Only the WINDOW was
# wrong.

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


UMBRELLA_ADDON_ID = 'plugin.video.umbrella'
MDBLIST_REL = 'resources/lib/modules/mdblist.py'

MARKER = '# AI_SUBS_UMB_MDBL_SINCE_v1'
# Prefix, never an enumerated list of predecessors: a hand-maintained tuple is
# only correct for the one bump it was written for.
_MARKER_ANY = '# AI_SUBS_UMB_MDBL_SINCE_v'

# 30 days. Long enough to cover an outage or a clock that disagrees, short
# enough that the incremental sync stays incremental.
_OVERLAP_SECONDS = 2592000

# The line above the one we widen. Anchored on the GUARD rather than on the
# `from datetime import datetime as _dt` line, because that import appears
# four times in the file and only one of them belongs to this function.
_ANCHOR = ("\t\tif not forced and db_last and (api_last - db_last) < 60: "
           "return\n\t\tfrom datetime import datetime as _dt\n")


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('umbrella_mdblist_sync_patcher: ' + msg, level=level)
    except Exception:
        pass


def _revert(content):
    """Delete a previous version's injected block.

    Every line of an injected block is indented strictly deeper than its
    marked line, so the marked line plus everything deeper below it is the
    block. Ours is a single marked line with nothing under it.
    """
    lines = content.split('\n')
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if _MARKER_ANY not in line:
            out.append(line)
            i += 1
            continue
        base = len(line) - len(line.lstrip())
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= base:
                break
            i += 1
    return '\n'.join(out)


def _umbrella_path(rel):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + UMBRELLA_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *rel.split('/'))
    return p if os.path.isfile(p) else ''


def _reset_sync_cursor():
    """Clear the stored watched cursor so the next sync backfills from 1970.

    The overlap alone only heals 30 days; a table that has been dropping rows
    for months needs one full pass. Umbrella's own force button does this by
    wiping every table -- we only clear the CURSOR, so nothing already
    ingested is lost and the next scheduled sync repopulates the gaps.
    """
    if xbmcvfs is None:
        return
    try:
        db = xbmcvfs.translatePath(
            'special://profile/addon_data/' + UMBRELLA_ADDON_ID
            + '/mdbSync.db')
    except Exception:
        return
    if not os.path.isfile(db):
        return  # nothing synced yet; the first sync is a full one anyway
    try:
        import sqlite3
        conn = sqlite3.connect(db, timeout=10, isolation_level=None)
        cur = conn.cursor()
        row = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='service'").fetchone()
        if row:
            cur.execute(
                "DELETE FROM service WHERE setting IN "
                "('last_watched_at', 'last_watched_movies_at', "
                "'last_watched_episodes_at')")
            _log('cleared the watched-sync cursor; the next MDBList sync '
                 'backfills the episodes the old one skipped')
        cur.close()
        conn.close()
    except Exception as e:
        _log('could not clear the sync cursor: {0}'.format(e),
             level='WARNING')


def ensure_patched():
    """Idempotent. Returns 'no_umbrella' | 'no_file' | 'unchanged' | 'patched'
    | 'repatched' | 'unmatched' | 'read_failed' | 'write_failed' |
    'compile_failed' | 'revert_failed'. Never raises."""
    path = _umbrella_path(MDBLIST_REL)
    if not path:
        return 'no_umbrella' if xbmcvfs is None else 'no_file'
    try:
        with open(path, encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'unchanged'

    repatch = False
    if _MARKER_ANY in content:
        content = _revert(content)
        repatch = True
        if _MARKER_ANY in content:
            _log('could not remove an older injection', level='WARNING')
            return 'revert_failed'

    if _ANCHOR not in content:
        _log('sync_watchedProgress does not have the expected shape -- '
             'Umbrella may have refactored it; leaving the file alone',
             level='WARNING')
        return 'unmatched'

    new_content = content.replace(
        _ANCHOR,
        _ANCHOR + '\t\tdb_last = max(0, db_last - %d)  %s\n'
        % (_OVERLAP_SECONDS, MARKER), 1)

    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('compile check failed, not writing: {0}'.format(e),
             level='WARNING')
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
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'

    pycache = os.path.join(os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache):
        for fn in os.listdir(pycache):
            if fn.startswith('mdblist.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache, fn))
                except OSError:
                    pass

    _reset_sync_cursor()
    _log('widened the MDBList watched-sync window by %d days so a missed '
         'or failed page is no longer skipped forever'
         % (_OVERLAP_SECONDS // 86400))
    return 'repatched' if repatch else 'patched'
