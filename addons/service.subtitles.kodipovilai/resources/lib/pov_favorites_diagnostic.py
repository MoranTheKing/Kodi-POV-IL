# One-shot diagnostic for the "Add to My List shows 0 results" bug.
#
# It does NOT change anything in POV. It only READS state and reports
# it, so we can see -- for the actual user, on the actual device --
# why "My Movies"/"My Shows" come back empty even though the add said
# success and the item is on themoviedb.org / trakt.tv.
#
# It captures the two competing hypotheses at once:
#   1. Auth/account mismatch: POV READS tmdb favorites via the v4
#      setting `tmdb.account_id`, but WRITES via the v3 setting
#      `tmdb.session_account_id`. If account_id is empty/wrong the
#      read URL breaks and POV returns [] forever, regardless of cache.
#   2. Store vs tile mismatch: maybe the items ARE saved (POV-local
#      favorites DB / trakt cache) but the tile reads a different
#      source, or the cache rows are stuck empty.
#
# Output goes three ways so it's easy to retrieve:
#   * kodi.log (tag pov_favorites_diagnostic)
#   * a text file: <pov profile>/POV_FAV_DIAGNOSTIC.txt
#   * a textviewer dialog popped once, so the user can just screenshot.
#
# Runs once per DIAG_VERSION (marker setting on OUR addon), so it
# won't nag on every startup.

import os
import sqlite3

try:
    import xbmc
    import xbmcgui
    import xbmcvfs
    import xbmcaddon
except Exception:
    xbmc = xbmcgui = xbmcvfs = xbmcaddon = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


DIAG_VERSION = '1'
OUR_ADDON_ID = 'service.subtitles.kodipovilai'
POV_ADDON_ID = 'plugin.video.pov'
POV_PROFILE = 'special://profile/addon_data/plugin.video.pov/'

WATCHED_DB = POV_PROFILE + 'watched.db'        # favorites table lives here
MAINCACHE_DB = POV_PROFILE + 'maincache.db'    # tmdblist_* cache
TRAKT_DB = POV_PROFILE + 'traktcache.db'       # trakt_* cache

TMDB_KEYS = ('tmdb.account_id', 'tmdb.session_account_id',
             'tmdb.token', 'tmdb.session_id', 'tmdb.username')
TRAKT_KEYS = ('trakt_user', 'trakt.token', 'trakt.expires', 'trakt.refresh')


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_favorites_diagnostic: ' + msg, level=level)
    except Exception:
        pass


def _tp(path):
    try:
        return xbmcvfs.translatePath(path)
    except Exception:
        return path


def _our_get(key, default=''):
    try:
        return xbmcaddon.Addon(OUR_ADDON_ID).getSetting(key) or default
    except Exception:
        return default


def _our_set(key, value):
    try:
        xbmcaddon.Addon(OUR_ADDON_ID).setSetting(key, value)
    except Exception:
        pass


def _pov_setting(key):
    """Read a POV setting value (auth tokens etc.). Returns '' if unset
    or unreadable. We never print full tokens -- only presence/length."""
    try:
        return xbmcaddon.Addon(POV_ADDON_ID).getSetting(key) or ''
    except Exception:
        return ''


def _mask(value):
    """Show a value safely: short ids in full, long secrets as len only."""
    if value == '':
        return "<EMPTY>"
    if len(value) <= 12:
        return repr(value)
    return "<set, len=%d, ...%s>" % (len(value), value[-4:])


def _q(db_path, sql, params=()):
    """Run a read query against a POV sqlite db. Returns rows or an
    error string. Never raises."""
    real = _tp(db_path)
    if not os.path.isfile(real):
        return "<db missing: %s>" % os.path.basename(real)
    try:
        con = sqlite3.connect(real)
        try:
            cur = con.cursor()
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            con.close()
    except Exception as e:
        return "<query error: %s>" % e


def _collect():
    lines = []
    lines.append("=== POV FAVORITES DIAGNOSTIC v%s ===" % DIAG_VERSION)

    pov_installed = os.path.isdir(_tp('special://home/addons/' + POV_ADDON_ID))
    lines.append("POV installed: %s" % pov_installed)

    # --- TMDB auth state (the account_id read/write mismatch) ---
    lines.append("")
    lines.append("[TMDB auth]")
    for k in TMDB_KEYS:
        lines.append("  %s = %s" % (k, _mask(_pov_setting(k))))
    acc = _pov_setting('tmdb.account_id')
    sess = _pov_setting('tmdb.session_account_id')
    if acc == '' and sess != '':
        lines.append("  >> NOTE: account_id (v4 READ id) is EMPTY but "
                     "session_account_id (v3 WRITE id) is set -> the "
                     "favorites READ url breaks -> always 0 results. "
                     "This matches 'adds to the site but list is empty'.")

    # --- Trakt auth state ---
    lines.append("")
    lines.append("[Trakt auth]")
    for k in TRAKT_KEYS:
        lines.append("  %s = %s" % (k, _mask(_pov_setting(k))))

    # --- POV-local favorites DB (no cache, no account; ground truth) ---
    lines.append("")
    lines.append("[POV-local favorites DB] (watched.db -> favorites)")
    rows = _q(WATCHED_DB,
              "SELECT db_type, COUNT(*) FROM favorites GROUP BY db_type")
    if isinstance(rows, str):
        lines.append("  %s" % rows)
    elif not rows:
        lines.append("  favorites table empty (0 rows for every type)")
    else:
        for r in rows:
            lines.append("  db_type=%s -> %s rows" % (r[0], r[1]))
    # a small sample so we can see if ids look sane (or empty/null)
    sample = _q(WATCHED_DB,
                "SELECT db_type, tmdb_id, title FROM favorites LIMIT 5")
    if isinstance(sample, list) and sample:
        lines.append("  sample:")
        for r in sample:
            lines.append("    %r" % (r,))

    # --- TMDB list cache (maincache.db) ---
    lines.append("")
    lines.append("[TMDB list cache] (maincache.db -> id LIKE 'tmdblist_%')")
    rows = _q(MAINCACHE_DB,
              "SELECT id, LENGTH(data), expires FROM maincache "
              "WHERE id LIKE 'tmdblist_%'")
    if isinstance(rows, str):
        lines.append("  %s" % rows)
    elif not rows:
        lines.append("  no tmdblist_* rows cached (will re-fetch on open)")
    else:
        for r in rows:
            empty = " <EMPTY/near-empty>" if (r[1] or 0) <= 2 else ""
            lines.append("  %s: data_len=%s expires=%s%s"
                         % (r[0], r[1], r[2], empty))

    # --- Trakt cache (traktcache.db -> trakt_data table) ---
    lines.append("")
    lines.append("[Trakt cache] (traktcache.db -> trakt_data)")
    rows = _q(TRAKT_DB,
              "SELECT id, LENGTH(data) FROM trakt_data "
              "WHERE id LIKE 'trakt_collection%' "
              "OR id LIKE 'trakt_watchlist%' "
              "OR id LIKE 'trakt_favorites%' "
              "OR id LIKE 'trakt_user_lists%' "
              "OR id LIKE 'trakt_lists%'")
    if isinstance(rows, str):
        lines.append("  %s" % rows)
    elif not rows:
        lines.append("  no trakt collection/watchlist/favorites rows cached")
    else:
        for r in rows:
            empty = " <EMPTY/near-empty>" if (r[1] or 0) <= 4 else ""
            lines.append("  %s: data_len=%s%s" % (r[0], r[1], empty))

    lines.append("")
    lines.append("=== END DIAGNOSTIC ===")
    return "\n".join(lines)


def run(force=False):
    """Collect + log + write file + popup. One-shot per DIAG_VERSION
    unless force=True. Never raises."""
    if xbmcaddon is None:
        return 'no_kodi'
    try:
        if not force and _our_get('_fav_diag_done') == DIAG_VERSION:
            return 'already_done'
        report = _collect()

        # log every line
        for ln in report.splitlines():
            _log(ln)

        # write file
        try:
            out = _tp(POV_PROFILE + 'POV_FAV_DIAGNOSTIC.txt')
            d = os.path.dirname(out)
            if d and not os.path.isdir(d):
                os.makedirs(d)
            with open(out, 'w', encoding='utf-8') as f:
                f.write(report)
        except Exception as e:
            _log('file write failed: %s' % e, level='WARNING')

        # popup so the user can just screenshot it
        try:
            xbmcgui.Dialog().textviewer(
                'אבחון מועדפים — צלם מסך ושלח', report)
        except Exception:
            pass

        _our_set('_fav_diag_done', DIAG_VERSION)
        return 'done'
    except Exception as e:
        _log('run failed: %s' % e, level='WARNING')
        return 'error'
