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
# Two edits, both exact-string, marker-gated, idempotent, atomic, .pyc
# invalidated, re-applied each boot (so a POV self-update can't strip it):
#   1) resources/lib/indexers/tmdb_api.py: add tmdb_search_multi(query) and
#      tmdb_trending_all(), each returning the TMDB results filtered to
#      movie/tv (drops 'person'), mirroring the existing search functions'
#      caching exactly.
#   2) resources/lib/menus/tmdb.py build_tmdb_list(): branch on the params
#      so action=search_multi&query=... uses tmdb_search_multi, and
#      action=trending_all uses tmdb_trending_all; otherwise unchanged
#      (list_details). Everything downstream (merge/sort/render) is reused.
#
# Safe no-op if POV isn't installed or was refactored away from the anchors.

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
TMDB_API_REL = 'resources/lib/indexers/tmdb_api.py'
TMDB_MENU_REL = 'resources/lib/menus/tmdb.py'

MARKER = '# AI_SUBS_POV_COMBINED_DISCOVER_v1'

# --- edit 1: tmdb_api.py -- add the two data functions after the existing
#     tmdb_movies_search (exact-string anchor; both funcs reuse base_url,
#     get_tmdb, cache_object, EXPIRES_4_HOURS already present in the file).
_API_ANCHOR = (
    "def tmdb_movies_search(query, page_no):\n"
    "\tstring = 'tmdb_movies_search_%s_%s' % (query, page_no)\n"
    "\turl = '%s/search/movie?language=en-US&query=%s&page=%s' % "
    "(base_url, query, page_no)\n"
    "\treturn cache_object(get_tmdb, string, url, "
    "expiration=EXPIRES_4_HOURS)\n")
_API_ADDITION = (
    "\n"
    "def tmdb_search_multi(query, page_no=1):\n"
    "\tstring = 'tmdb_search_multi_%s_%s' % (query, page_no)\n"
    "\turl = '%s/search/multi?language=en-US&query=%s&page=%s' % "
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
    "\turl = '%s/trending/all/week?language=en-US&page=%s' % "
    "(base_url, page_no)\n"
    "\tdata = cache_object(get_tmdb, string, url, "
    "expiration=EXPIRES_4_HOURS)\n"
    "\ttry: results = data.get('results', [])\n"
    "\texcept Exception: results = []\n"
    "\treturn [i for i in results if i.get('media_type') in "
    "('movie', 'tv')]\n")

# --- edit 2: menus/tmdb.py build_tmdb_list -- swap the single data line
#     for a branch on the params (exact-string anchor). For the unified
#     Discover the skin always passes action=search_multi with the typed
#     query; when the query is empty (nothing typed) we fall back to
#     trending so Discover shows a unified popular grid, otherwise a
#     unified movie+tv search. One skin binding covers both cases.
_MENU_ANCHOR = "\tresults = tmdb_api.list_details(list_id)\n"
_MENU_REPLACEMENT = (
    "\t_action = params.get('action')\n"
    "\t_query = (params.get('query') or '').strip()\n"
    "\tif _action == 'search_multi':\n"
    "\t\tresults = tmdb_api.tmdb_search_multi(_query, page) if _query "
    "else tmdb_api.tmdb_trending_all(page)\n"
    "\telif _action == 'trending_all':\n"
    "\t\tresults = tmdb_api.tmdb_trending_all(page)\n"
    "\telse:\n"
    "\t\tresults = tmdb_api.list_details(list_id)\n")


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


def _patch_one(path, anchor, make_new, label):
    """Apply one exact-string edit. make_new(text)->new_text. Returns
    'patched' | 'already_patched' | 'unmatched' | 'read_failed' |
    'write_failed'."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except OSError as e:
        _log('{0}: read failed: {1}'.format(label, e), level='WARNING')
        return 'read_failed'

    if MARKER in text:
        return 'already_patched'
    if anchor not in text:
        _log('{0}: anchor not found -- POV may have changed; skipping'
             .format(label), level='WARNING')
        return 'unmatched'

    new_text = make_new(text)
    if new_text == text:
        return 'unmatched'
    # stamp marker on its own line at the very top (after any shebang/coding
    # is unnecessary here; these files start with imports).
    new_text = MARKER + '\n' + new_text

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
        st = _patch_one(
            api_path, _API_ANCHOR,
            lambda t: t.replace(_API_ANCHOR, _API_ANCHOR + _API_ADDITION, 1),
            'tmdb_api.py')
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

    summary = ', '.join(results)
    if any('=patched' in r for r in results):
        _log('unified discover data source added to POV (' + summary + ')',
             'INFO')
    return summary
