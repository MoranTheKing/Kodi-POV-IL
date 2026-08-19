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
# THE FIX, in three parts:
#   1. DO NOT ADVANCE THE CURSOR UNLESS THE FETCH ACTUALLY SUCCEEDED. This is
#      the root defect, and the only one of the three that makes the loss
#      IMPOSSIBLE rather than merely recoverable. The information needed to
#      tell success from failure is already there: get_request() returns None
#      on any error and {} on a 2xx whose body will not parse, while a
#      genuinely empty page still comes back as a dict carrying `pagination`
#      -- truthy. So `if not data: break` already separates them; it just
#      never told the tail of the function. A flag set on that path, and
#      checked before the three update_last_watched_at() writes, leaves the
#      cursor exactly where it was, so the next run asks for the same window
#      again and the rows finally land. The flag tests for a PAGE rather than
#      for emptiness -- see _NOT_A_PAGE -- because get_request hands back a
#      2xx body verbatim, and a body that is neither a page nor falsy would
#      otherwise sail through as a successful last page.
#   2. Overlap the window. The fetch starts 30 days before the stored cursor,
#      so a window missed for any reason is picked up on the next sync instead
#      of never. This is free: upsert_watched_episode() is INSERT OR REPLACE,
#      so re-ingesting the same rows changes nothing. Still needed after (1),
#      and not redundant with it: the cursor is written from the DEVICE's
#      clock (datetime.utcnow()) while the items are stamped by MDBList's, so
#      a device running a minute fast skips a minute of history on a run that
#      succeeded by every measure the code can take. No success flag can see
#      that; only an overlap can.
#   3. Repair the damage already done. An overlap only heals 30 days back, and
#      this user's table was missing far more, so applying the patch also
#      clears the stored cursor once -- the next scheduled sync then backfills
#      from 1970, which is what the force button does, without the user having
#      to know the button exists.
#
# Being too conservative in (1) is cheap and being too permissive is not. If
# the flag ever stays False when the sync really was fine, the cursor stands
# still and the next run re-fetches a window it already has -- INSERT OR
# REPLACE, so no damage, just work. The opposite mistake is the bug we are
# here for: the cursor only ever moves forward, so a window skipped once is
# skipped forever. When in doubt the patch does not advance.
#
# The guard above the fetch (`api_last - db_last < 60`) is deliberately left
# alone: it compares MDBList's newest activity against the last sync time to
# decide whether to bother, and that reasoning is sound. Only the WINDOW and
# the UNCONDITIONAL cursor write were wrong.

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

MARKER = '# AI_SUBS_UMB_MDBL_SINCE_v2'
# Prefix, never an enumerated list of predecessors: a hand-maintained tuple is
# only correct for the one bump it was written for.
#
# The name says SINCE because v1 only widened the `since` window and the field
# already carries it. It is FROZEN, not descriptive: _revert() finds a previous
# release's injection by this prefix, so renaming it would leave v1's line in
# place on every device that has one and then add v2's beside it.
_MARKER_ANY = '# AI_SUBS_UMB_MDBL_SINCE_v'

# The local we introduce into sync_watchedProgress. Deliberately not a name
# anybody would reach for: it has to be unique inside a function we do not own,
# and a collision would silently change Umbrella's own logic rather than fail.
_FLAG = '_ai_fetch_ok'

# The one-shot backfill is tracked SEPARATELY from the file patch. Tying it to
# the write meant a reset that lost a lock race to Umbrella's own sync thread
# -- both add-ons start around Kodi boot -- was never retried: the next run
# reads 'unchanged' and returns before reaching it. Its own flag makes it retry
# until it actually succeeds.
#
# The generation is the VALUE, not part of the key. A versioned key (_..._v1 ->
# _..._v2) asks for the next backfill correctly but abandons the old key in our
# settings on every bump; overwriting one value leaves nothing behind. Bump
# _RESET_GEN to request another full backfill.
_RESET_FLAG = '_umb_mdbl_cursor_reset'
# GEN 2, and the bump is a REPAIR, not a new idea. Generation 1 cleared three
# keys; two of them were activity signals, not fetch cursors, and clearing
# them told Umbrella "nothing new to sync" forever (see _reset_sync_cursor).
# Devices that took that release still have both at epoch and their episodes
# list still needs a manual refresh. Bumping the generation runs the corrected
# reset once more on exactly those devices; the sync it forces then writes all
# three keys back itself (modules/mdblist.py:983-985), so the signals it
# destroyed are restored by the same pass that backfills the table.
_RESET_GEN = '2'

# 30 days. Long enough to cover an outage or a clock that disagrees, short
# enough that the incremental sync stays incremental.
_OVERLAP_SECONDS = 2592000

# The line above the one we widen. Anchored on the GUARD rather than on the
# `from datetime import datetime as _dt` line, because that import appears
# four times in the file and only one of them belongs to this function.
_ANCHOR = ("\t\tif not forced and db_last and (api_last - db_last) < 60: "
           "return\n\t\tfrom datetime import datetime as _dt\n")

# The other three anchors, as the exact adjacent line pairs we insert between.
_LIMIT = "\t\tlimit = 1000\n"
_WHILE = "\t\twhile True:\n"
_FETCH = "\t\t\tdata = get_request(url)\n"
_BREAK = "\t\t\tif not data: break\n"
_OFFSET = "\t\t\toffset += limit\n"
_FIRST_WRITE = "\t\tmdbsync.update_last_watched_at('last_watched_at')\n"

# What counts as "that was not a page of results".
#
# `not data` -- which is all this checked at first -- catches the two shapes
# get_request() is written to produce on failure: None on any error, and {} on
# a 2xx whose body will not parse (modules/mdblist.py:868-878). It does NOT
# catch a THIRD shape: get_request returns `response.json()` verbatim, so a 2xx
# carrying anything else -- a soft-fail envelope like {"error": "rate limited"}
# -- comes back TRUTHY. The loop then ingests nothing, reads
# `pagination = data.get('pagination', {})`, finds has_more falsy, and leaves
# as though it had reached the last page. The cursor advances over a window
# that was never fetched. Stock has the same blind spot; a review found it here
# before it found it in the field.
#
# So the test is positive: it has to LOOK like a page. Every real /sync/watched
# response carries `pagination` -- Umbrella's own loop steers on it, and POV's
# client indexes into it without a fallback -- so requiring it is requiring the
# documented shape, not guessing at one.
#
# And if that assumption is ever wrong, the cost is small and the direction is
# the safe one. A response with no `pagination` cannot paginate anyway: the
# loop reads one page and breaks, so a frozen cursor means ONE extra request
# per sync interval, re-upserting rows we already have through INSERT OR
# REPLACE. The opposite mistake is the bug this file exists for.
_NOT_A_PAGE = "not isinstance(data, dict) or 'pagination' not in data"


def _injections(fit):
    """The four lines we add, each as (anchor, anchor with our line inside it).

    All four are PURE INSERTIONS between two existing lines -- never an edit to
    a line Umbrella wrote. That is what keeps _revert() byte-exact: it deletes
    marked lines and everything indented under them, so everything it can
    delete has to be ours. The obvious alternative for part (1) -- wrap the
    three update_last_watched_at() calls in an `if` and re-indent them -- reads
    better and is wrong here, because the revert would then take Umbrella's
    three lines with it and the next version could not cleanly replace this
    one.

    An early `return` rather than a skip-and-continue, because everything below
    those three writes is cache invalidation and a widget refresh: on a run
    that failed there is nothing new worth showing, and re-priming those caches
    means going back to an API that just refused us.
    """
    return [
        (fit(_ANCHOR),
         fit(_ANCHOR + '\t\tdb_last = max(0, db_last - %d)  %s\n'
             % (_OVERLAP_SECONDS, MARKER))),
        (fit(_LIMIT + _WHILE),
         fit(_LIMIT + '\t\t%s = True  %s\n' % (_FLAG, MARKER) + _WHILE)),
        (fit(_FETCH + _BREAK),
         fit(_FETCH + '\t\t\tif %s: %s = False  %s\n'
             % (_NOT_A_PAGE, _FLAG, MARKER) + _BREAK)),
        (fit(_OFFSET + _FIRST_WRITE),
         fit(_OFFSET + '\t\tif not %s: return  %s\n' % (_FLAG, MARKER)
             + _FIRST_WRITE)),
    ]


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('umbrella_mdblist_sync_patcher: ' + msg, level=level)
    except Exception:
        pass


def _fitter(content):
    # Umbrella ships this file LF today, but parts of the pack this build
    # carries are CRLF, and an anchor that only matches LF is how the Hebrew
    # search fix shipped as a silent no-op. Same helper the token patcher on
    # this very file uses.
    eol = '\r\n' if '\r\n' in content else '\n'
    return (lambda t: t.replace('\n', eol)) if eol != '\n' else (lambda t: t), eol


def _revert(content, eol='\n'):
    """Delete a previous version's injected block.

    Every line of an injected block is indented strictly deeper than its
    marked line, so the marked line plus everything deeper below it is the
    block. Ours is a single marked line with nothing under it.
    """
    lines = content.split(eol)
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
            if nxt.strip():
                if (len(nxt) - len(nxt.lstrip())) <= base:
                    break
                i += 1
                continue
            # A blank line is only INSIDE the block if a deeper non-blank line
            # follows it. Swallowing every blank unconditionally would eat the
            # separator below the block -- and the file's trailing newline,
            # when the marked line is last -- so the revert stops being
            # byte-exact and the next version cannot cleanly replace this one.
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            if (j >= len(lines)
                    or (len(lines[j]) - len(lines[j].lstrip())) <= base):
                break
            i = j
    return eol.join(out)


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

    Returns True when there is nothing left to do -- which includes "no
    database yet", since a first sync is a full one anyway. False means the
    attempt FAILED and must be retried on a later start; Umbrella's own sync
    thread can hold the file, and giving up then would leave the damaged table
    damaged.
    """
    if xbmcvfs is None:
        return False
    try:
        db = xbmcvfs.translatePath(
            'special://profile/addon_data/' + UMBRELLA_ADDON_ID
            + '/mdbSync.db')
    except Exception:
        return False
    if not os.path.isfile(db):
        return True  # nothing synced yet; the first sync is a full one anyway
    conn = None
    try:
        import sqlite3
        conn = sqlite3.connect(db, timeout=10, isolation_level=None)
        cur = conn.cursor()
        row = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='service'").fetchone()
        if row:
            # ONLY last_watched_at. This was three keys and that was a
            # REGRESSION, reported from the field: the episodes list, which
            # had always been right, started needing a manual refresh too.
            #
            # sync_watchedProgress reads ONLY last_watched_at to compute
            # `since` (modules/mdblist.py:945), so it is the only one that
            # has to move for a backfill. The other two are read somewhere
            # else entirely -- getEpisodesWatchedActivity() and
            # getMoviesWatchedActivity() (mdblist.py:923-931) -- and
            # playcount.py:97 uses them as the "is there new watched activity"
            # signal for the indicator cache:
            #
            #     elif mdblist.getEpisodesWatchedActivity() < ...: timeout = 720
            #     else: timeout = 0
            #
            # last_sync() returns 0 for a row that is not there, so deleting
            # the key made that comparison permanently true: serve the 12-hour
            # cache instead of re-syncing. The refresh the user pressed then
            # did nothing. One stale list became two.
            cur.execute(
                "DELETE FROM service WHERE setting = 'last_watched_at'")
            _log('cleared the watched-sync cursor; the next MDBList sync '
                 'backfills the episodes the old one skipped')
        cur.close()
        return True
    except Exception as e:
        _log('could not clear the sync cursor, will retry on a later '
             'start: {0}'.format(e), level='WARNING')
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _ensure_cursor_reset():
    """Run the one-shot backfill, and keep trying until it actually runs.

    Deliberately NOT tied to the file write: the write succeeds on the first
    start and every later start returns 'unchanged' long before reaching here,
    so a reset that failed once would never be attempted again.
    """
    if kodi_utils is None:
        return
    try:
        if kodi_utils.get_setting(_RESET_FLAG, '') == _RESET_GEN:
            return
        if _reset_sync_cursor():
            kodi_utils.set_setting(_RESET_FLAG, _RESET_GEN)
    except Exception as e:
        _log('cursor reset bookkeeping failed: {0}'.format(e),
             level='WARNING')


def ensure_patched():
    """Idempotent. Returns 'no_umbrella' | 'no_file' | 'unchanged' | 'patched'
    | 'repatched' | 'unmatched' | 'read_failed' | 'write_failed' |
    'compile_failed' | 'revert_failed'. Never raises."""
    path = _umbrella_path(MDBLIST_REL)
    if not path:
        return 'no_umbrella' if xbmcvfs is None else 'no_file'

    # Before anything else, and on EVERY exit below. The one-shot backfill
    # repairs Umbrella's own database and does not depend on our line landing
    # in Umbrella's source: hanging it off the successful paths meant that a
    # user whose Umbrella had been refactored just enough to move the anchor
    # ('unmatched') kept a damaged table forever -- the one case where the
    # repair is needed MOST, since the forward fix cannot reach them either.
    # Self-gated and idempotent, so calling it first costs nothing.
    _ensure_cursor_reset()

    try:
        with open(path, encoding='utf-8', newline='') as f:
            content = f.read()
    except Exception as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    fit, eol = _fitter(content)

    if MARKER in content:
        return 'unchanged'

    repatch = False
    if _MARKER_ANY in content:
        content = _revert(content, eol)
        repatch = True
        if _MARKER_ANY in content:
            _log('could not remove an older injection', level='WARNING')
            return 'revert_failed'

    # ALL FOUR OR NONE. Three of the four lines only make sense together --
    # the flag has to be initialised, set and read -- so a partial application
    # would inject a NameError into somebody else's add-on, inside a bare
    # `except: log_utils.error()` that would swallow it and take the whole
    # sync down with it. `count != 1` rather than `not in`, so a refactor that
    # DUPLICATED one of these shapes is treated as unrecognised too, instead of
    # being patched at whichever copy happens to come first.
    injections = _injections(fit)
    if any(content.count(anchor) != 1 for anchor, _ in injections):
        _log('sync_watchedProgress does not have the expected shape -- '
             'Umbrella may have refactored it; leaving the file alone',
             level='WARNING')
        return 'unmatched'

    new_content = content
    for anchor, replacement in injections:
        new_content = new_content.replace(anchor, replacement, 1)

    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('compile check failed, not writing: {0}'.format(e),
             level='WARNING')
        return 'compile_failed'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
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

    _log('MDBList watched-sync: the cursor now advances only when the fetch '
         'succeeded, and the window overlaps by %d days, so a failed or '
         'skipped page is no longer lost forever'
         % (_OVERLAP_SECONDS // 86400))
    return 'repatched' if repatch else 'patched'
