# Add a UNIFIED movie+tv "discover/search" data source to POV, so AF3's
# Discover grid can show movies AND tv shows together, ranked by
# popularity (typed search -> /search/multi; empty -> /trending/all/week).
#
# WHY this approach (and not Codex's failed ai_pov_combined_search): POV
# ALREADY has a mixed-media list builder -- menus/tmdb.py build_tmdb_list()
# takes a list of {media_type,id} items, builds movies via Movies and tv
# via TVShows, MERGES them (items = movies.items + tvshows.items) and SORTS
# by pov_sort_order, rendering Hebrew posters that click straight into
# POV's source scraping. It only lacked a search/trending data source (it
# read a saved TMDB list). We add exactly that and reuse the proven
# merge+sort+render path -- a minimal, surgical change instead of a whole
# parallel builder.
#
# Three edits, all exact-string, marker-gated, idempotent, atomic, .pyc
# invalidated, re-applied each boot (so a POV self-update can't strip them):
#   1) resources/lib/indexers/tmdb_api.py: add tmdb_search_multi(query) and
#      tmdb_trending_all(), each returning the TMDB results filtered to
#      movie/tv (drops 'person'), mirroring the existing search functions'
#      caching exactly.
#   2) resources/lib/menus/tmdb.py TmdbListBuilder.fetch_results(): branch on
#      the params so action=search_multi&query=... uses tmdb_search_multi (or
#      trending when the query is empty); otherwise unchanged (list_details).
#      Everything downstream (merge/sort/render) is reused.
#   3) REMOVED (was harmful): this patcher used to also make
#      kodi_utils.py container_refresh() fire the widget-reload ping
#      (UpdateLibrary(video,special://skin/foo)) so AF3 home widgets re-query
#      after clear-progress / mark-watched. But container_refresh() is called
#      from ~30 sites (incl. every Trakt add), and that ping triggers a
#      RecentlyAdded home update that reloads ALL POV home widgets at once ->
#      concurrent router.py on POV's reuselanguageinvoker interpreter ->
#      CPython dict corruption (SystemError: dictobject.c:1756) -> native
#      crash. Confirmed from a field crash log. The ping is now REVERTED by
#      pov_container_refresh_crash_fix.py; FENtastic already reloads its
#      widgets on Container.Refresh alone, so nothing is lost there.
#   4) RETIRED in POV 6.07: the old dialogs.py trakt_manager_choice() redirect
#      is gone (managers are independent classes now), so there is nothing
#      to patch -- the Trakt context item already opens Trakt natively.
#
# Safe no-op if POV isn't installed or was refactored away from the anchors.

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


POV_ADDON_ID = 'plugin.video.pov'
TMDB_API_REL = 'resources/lib/indexers/tmdb_api.py'
TMDB_MENU_REL = 'resources/lib/menus/tmdb.py'

MARKER = '# AI_SUBS_POV_COMBINED_DISCOVER_v1'

# --- edit 1: tmdb_api.py -- add the two data functions after the existing
#     tmdb_movies_search. Both reuse base_url, get_tmdb, cache_object and
#     EXPIRES_4_HOURS, which are already present in the file.
#
#     This used to be an exact-string anchor pinning the whole of
#     tmdb_movies_search, including its url line. POV 6.08 moved the API
#     version out of base_url ('https://api.themoviedb.org/3' became
#     'https://api.themoviedb.org') and put the '/3' at every call site, so
#     the anchor stopped matching and the patcher quietly skipped -- while
#     the menus/tmdb.py half stayed patched and called a tmdb_search_multi
#     that no longer existed. So the anchor now pins only what we actually
#     depend on -- the def line and the shape of the body -- and the URL
#     PREFIX for our own two functions is read out of POV's own search line
#     rather than hard-coded. Whichever side of the '/3' move POV is on, we
#     build our URLs the same way it builds its own.
_API_ANCHOR_RE = re.compile(
    r"^def tmdb_movies_search\(query, page_no\):[ \t]*\n"
    r"(?:[ \t]+.*\n)+", re.MULTILINE)
# The path between base_url and the endpoint, as POV currently writes it:
# '' on POV <= 6.07, '/3' from 6.08 on.
_API_PREFIX_RE = re.compile(
    r"url = '%s(?P<pfx>[^']*)/search/movie\?language=en-US"
    r"&query=%s&page=%s' % \(base_url, query, page_no\)")
_API_ADDITION = (
    "\n"
    "def tmdb_search_multi(query, page_no=1):\n"
    "\tstring = 'tmdb_search_multi_%s_%s' % (query, page_no)\n"
    "\turl = '%s{pfx}/search/multi?language=en-US&query=%s&page=%s' % "
    "(base_url, query, page_no)\n"
    "\tdata = cache_object(get_tmdb, string, url, "
    "expiration=EXPIRES_4_HOURS)\n"
    "\ttry: results = data.get('results', [])\n"
    "\texcept Exception: results = []\n"
    "\treturn [i for i in results if i.get('media_type') in "
    "('movie', 'tv')]\n"
    "\n"
    "def tmdb_trending_all(page_no=1):\n"
    "\tstring = 'tmdb_trending_all_%s' % page_no\n"
    "\turl = '%s{pfx}/trending/all/week?language=en-US&page=%s' % "
    "(base_url, page_no)\n"
    "\tdata = cache_object(get_tmdb, string, url, "
    "expiration=EXPIRES_4_HOURS)\n"
    "\ttry: results = data.get('results', [])\n"
    "\texcept Exception: results = []\n"
    "\treturn [i for i in results if i.get('media_type') in "
    "('movie', 'tv')]\n")


def _api_patch(text):
    """Insert the two data functions straight after tmdb_movies_search,
    using the same base_url/version convention that function uses. Returns
    the new text, or the text unchanged if anything does not line up."""
    m = _API_ANCHOR_RE.search(text)
    if not m:
        return text
    p = _API_PREFIX_RE.search(m.group(0))
    if not p:
        return text
    addition = _API_ADDITION.replace('{pfx}', p.group('pfx'))
    return text[:m.end()] + addition + text[m.end():]

# --- edit 2: menus/tmdb.py TmdbListBuilder.fetch_results -- branch on the
#     params (exact-string anchor). POV 6.07 refactored build_tmdb_list()
#     into the class TmdbListBuilder whose fetch_results() returns
#     tmdb_api.list_details(self.list_id); we wrap that with the unified
#     Discover branch. For the unified Discover the skin passes
#     action=search_multi with the typed query; when the query is empty
#     (nothing typed) we fall back to trending so Discover shows a unified
#     popular grid, otherwise a unified movie+tv search. One skin binding
#     covers both cases; the else path is byte-identical to stock POV.
_MENU_ANCHOR = "\t\treturn tmdb_api.list_details(self.list_id)\n"
_MENU_REPLACEMENT = (
    "\t\t_action = self.params.get('action')\n"
    "\t\t_query = (self.params.get('query') or '').strip()\n"
    "\t\tif _action == 'search_multi':\n"
    "\t\t\treturn tmdb_api.tmdb_search_multi(_query) if _query "
    "else tmdb_api.tmdb_trending_all()\n"
    "\t\telif _action == 'trending_all':\n"
    "\t\t\treturn tmdb_api.tmdb_trending_all()\n"
    "\t\treturn tmdb_api.list_details(self.list_id)\n")

# --- edit 3 REMOVED (was harmful): the container_refresh() widget-reload
#     ping is now reverted by pov_container_refresh_crash_fix.py. See the
#     module docstring above for the crash it caused.

# --- edit 4 (RETIRED in POV 6.07): the old trakt_manager_choice() redirect
#     in modules/dialogs.py no longer exists. POV 6.07 split the managers
#     into independent classes (menus/trakt.py TraktManager,
#     menus/tmdb.py TmdbManager) with NO cross-redirect, so the Trakt
#     context item already opens Trakt on its own. Nothing to patch.


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_combined_discover_patcher: ' + msg, level=level)
    except Exception:
        pass


def _pov_base():
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''


def _invalidate_pyc(py_path):
    d = os.path.join(os.path.dirname(py_path), '__pycache__')
    if not os.path.isdir(d):
        return
    stem = os.path.basename(py_path)[:-3]  # strip .py
    for fn in os.listdir(d):
        if fn.startswith(stem + '.') and fn.endswith('.pyc'):
            try:
                os.remove(os.path.join(d, fn))
            except OSError:
                pass


def _patch_one(path, anchor, make_new, label, marker=MARKER):
    """Apply one edit. make_new(text)->new_text, returning the text
    unchanged when it cannot find its anchor. `anchor` is an optional
    exact-string pre-check; pass None when make_new does its own matching.
    Returns 'patched' | 'already_patched' | 'unmatched' | 'read_failed' |
    'write_failed'."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except OSError as e:
        _log('{0}: read failed: {1}'.format(label, e), level='WARNING')
        return 'read_failed'

    if marker in text:
        return 'already_patched'
    if anchor is not None and anchor not in text:
        _log('{0}: anchor not found -- POV may have changed; skipping'
             .format(label), level='WARNING')
        return 'unmatched'

    new_text = make_new(text)
    if new_text == text:
        _log('{0}: anchor not found -- POV may have changed; skipping'
             .format(label), level='WARNING')
        return 'unmatched'
    # stamp marker on its own line at the very top (after any shebang/coding
    # is unnecessary here; these files start with imports).
    new_text = marker + '\n' + new_text

    try:
        compile(new_text, path, 'exec')
    except SyntaxError as e:
        _log('{0}: patched content would not compile -- skipping ({1})'
             .format(label, e), level='WARNING')
        return 'compile_failed'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_text)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('{0}: write failed: {1}'.format(label, e), level='WARNING')
        return 'write_failed'
    _invalidate_pyc(path)
    return 'patched'


def ensure_patched():
    """Returns a short summary. Never raises."""
    base = _pov_base()
    if not base or not os.path.isdir(base):
        return 'no_pov'

    api_path = os.path.join(base, *TMDB_API_REL.split('/'))
    menu_path = os.path.join(base, *TMDB_MENU_REL.split('/'))
    results = []

    if os.path.isfile(api_path):
        st = _patch_one(api_path, None, _api_patch, 'tmdb_api.py')
        results.append('api=' + st)
    else:
        results.append('api=no_file')

    if os.path.isfile(menu_path):
        st = _patch_one(
            menu_path, _MENU_ANCHOR,
            lambda t: t.replace(_MENU_ANCHOR, _MENU_REPLACEMENT, 1),
            'menus/tmdb.py')
        results.append('menu=' + st)
    else:
        results.append('menu=no_file')

    # edit 3 removed: the container_refresh() widget-reload ping caused a
    # native crash (see docstring); it is reverted by
    # pov_container_refresh_crash_fix.py instead.

    # edit 4 retired in POV 6.07 (no trakt_manager_choice redirect to drop).

    summary = ', '.join(results)
    if any('=patched' in r for r in results):
        _log('unified discover data source added to POV (' + summary + ')',
             'INFO')
    return summary
