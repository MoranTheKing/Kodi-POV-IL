# Self-healing patch: after stopping an episode/movie mid-way, refresh the
# open container ONCE, AFTER the Trakt/MDBList progress write -- not before.
#
# Symptom users hit (field report, SHIELD + Estuary): stopping a series
# episode part-way and going back takes many seconds staring at a spinner,
# sometimes lands on a bare files screen showing only ".." instead of the
# episode list, and the view type flips (thumbnails appear where they were
# not) once the list comes back.
#
# Root cause: POV 6's watched_cache.set_bookmark() fires container_refresh()
# IMMEDIATELY after the local bookmark write, and only then runs
# trakt_progress()/mdbl_progress() -- whose 'scrobble/pause' call triggers
# trakt_sync_activities(), which INVALIDATES the Trakt caches (watched,
# progress, playback) and re-downloads them. So the container rebuild races
# the sync it just scheduled: the episode list rebuilds against caches that
# are being cleared under it, waits out the whole network round-trip behind
# a spinner, and when a call fails mid-race the plugin directory comes back
# empty -- Kodi's ".." fallback screen, plus the view-type flip that comes
# with a momentary 'files' content type.
#
# POV 5 refreshed LAST (progress write first, one container_refresh at the
# end); v6 flipped the order. This patch restores the v5 ordering inside
# the v6 structure, byte-preserving every other behavior: same single
# refresh, same 'refresh' gate, same widget-vs-container choice, same
# progress-write condition. The user keeps a live, navigable list while
# the sync runs, and the one refresh lands when the data is ready.
#
# POV 5.x installs (bundled full-build copy before POV self-updates) do not
# carry the v6 anchor and already refresh last -- the patcher no-ops there
# by design. Self-healing: ensure_patched() runs every Kodi startup, is
# idempotent (marker), atomic, compile-checked, and skips loudly if the
# upstream shape changes.

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
WATCHED_CACHE_REL_PATH = 'resources/lib/caches/watched_cache.py'

MARKER = '# AI_SUBS_BOOKMARK_REFRESH_LAST_v1'

# POV 6.x set_bookmark tail (tabs, exactly as shipped in 6.08.x).
_OLD = (
    "\t\tdbcur.execute(SET_BM, (mediatype, tmdb_id, season, episode, "
    "str(resume_point), str(curr_time), last_played, 0, title))\n"
    "\t\tif refresh == 'true': kodi_utils.widget_refresh() if "
    "kodi_utils.external_browse() else kodi_utils.container_refresh()\n"
    "\t\tif watched_indicators not in (1, 2): return\n"
    "\t\tfunction = mdbl_progress if watched_indicators == 2 else trakt_progress\n"
    "\t\tfunction('set_progress', mediatype, tmdb_id, resume_point, season, "
    "episode, refresh=True)\n"
)

# Same statements, refresh moved to the end (v5 ordering, v6 semantics).
_NEW = (
    "\t\tdbcur.execute(SET_BM, (mediatype, tmdb_id, season, episode, "
    "str(resume_point), str(curr_time), last_played, 0, title))\n"
    "\t\t" + MARKER + " -- one refresh, AFTER the progress write.\n"
    "\t\t# Refreshing first sent the rebuilding container racing into the\n"
    "\t\t# Trakt cache invalidation that follows: a spinner for the whole\n"
    "\t\t# round-trip, and an empty '..' listing when a call failed\n"
    "\t\t# mid-race. POV 5 refreshed last; this restores that order.\n"
    "\t\tif watched_indicators in (1, 2):\n"
    "\t\t\tfunction = mdbl_progress if watched_indicators == 2 else trakt_progress\n"
    "\t\t\tfunction('set_progress', mediatype, tmdb_id, resume_point, season, "
    "episode, refresh=True)\n"
    "\t\tif refresh == 'true': kodi_utils.widget_refresh() if "
    "kodi_utils.external_browse() else kodi_utils.container_refresh()\n"
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_bookmark_refresh_patcher: ' + msg, level=level)
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


def _write(path, new_content):
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
        return True
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed for {0}: {1}'.format(path, e), level='WARNING')
        return False


def ensure_patched():
    """Move set_bookmark's container refresh AFTER the progress write.
    Idempotent, defensive, never raises. Returns a short status string."""
    path = _pov_path(WATCHED_CACHE_REL_PATH)
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'
    if MARKER in content:
        return 'unchanged'
    n = content.count(_OLD)
    if n != 1:
        # POV 5.x (already refreshes last) or a future rewrite: no-op.
        _log('set_bookmark anchor found {0} times (need 1) -- shape '
             'differs (POV 5.x or upstream change), skipping'.format(n),
             level='INFO' if n == 0 else 'WARNING')
        return 'unmatched'
    new_content = content.replace(_OLD, _NEW, 1)
    # SAFETY: never write a file that doesn't compile.
    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'
    return 'patched' if _write(path, new_content) else 'write_failed'
