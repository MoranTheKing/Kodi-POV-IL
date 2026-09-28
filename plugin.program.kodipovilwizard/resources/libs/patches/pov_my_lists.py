"""
pov_my_lists.py
Engine V2 decoupled patch module -- "My Movies" / "My Series" feature.

Populates self.list for the four merged personal-list actions the
home-screen tiles point at:
    tmdb_my_movies / trakt_my_movies / mdblist_my_movies (movies.py)
    tmdb_my_tvshows / trakt_my_tvshows / mdblist_my_tvshows (tvshows.py)

POV has no native action by these names, so without this module the
tiles build an empty directory.

FIXES vs. the legacy in-memory patcher this replaces
------------------------------------------------------
1. No blanket `except Exception: pass` around the whole fetch. Each
   source is fetched independently and a failure there is logged via
   xbmc.log (source, media type, page, exception) and treated as "zero
   items from this source" rather than aborting the merge entirely --
   e.g. if Trakt watchlist times out but favorites succeeds, the user
   still sees favorites instead of a blank tile with no signal at all.
   This logging is self-contained (doesn't import pov_content_logger),
   so it still works even if that module's patch didn't apply this
   boot. The functions below are also on pov_content_logger's
   TRACE_TARGETS list, so anything NOT caught here (e.g. a bug in the
   merge/dedup logic itself) is still caught by that settrace hook
   before POV's own untouched `except: pass` in run() swallows it.
2. Real pagination: total_pages is the max across the merged sources,
   and self.new_page is only set following the same
   `isinstance(page_no, int)` guard POV's own trakt_personal branch
   uses (page_no can be a raw string in POV's own ValueError fallback
   path), so the native "next page" nav item and alphabet-jump logic
   already in run() keep working unmodified across multiple pages
   instead of always stopping after page 1.

Dedup is per-page, matching POV's own pagination model: each run() is
a fresh process with no cross-page state, so this is parity with how
every native personal-list branch already behaves, not a regression.
"""
try:
	import xbmc
except Exception:
	xbmc = None

MOVIE_ACTIONS = ('tmdb_my_movies', 'trakt_my_movies', 'mdblist_my_movies')
TVSHOW_ACTIONS = ('tmdb_my_tvshows', 'trakt_my_tvshows', 'mdblist_my_tvshows')

_LOG_PREFIX = '[POV Wizard][MyLists]'


def _log(msg):
	if xbmc is None:
		return
	try:
		xbmc.log('%s %s' % (_LOG_PREFIX, msg), xbmc.LOGWARNING)
	except Exception:
		pass


def _safe_fetch(fn, media_type, page_no, source_label):
	"""Call fn(media_type, page_no) -> (data, total_pages). On failure,
	log with enough context to act on and return an empty contribution
	instead of aborting the whole merge."""
	try:
		data, total_pages = fn(media_type, page_no)
		return data or [], total_pages or 0
	except Exception as e:
		_log('%s fetch failed (media_type=%r, page=%r): %r' % (
			source_label, media_type, page_no, e))
		return [], 0


def _merge_tmdb_or_mdblist(fns_and_labels, media_type, page_no):
	"""Used for both TMDB and MDBList as both expect native TMDB IDs in the final list."""
	seen, merged, total_pages = set(), [], 0
	for fn, label in fns_and_labels:
		data, pages = _safe_fetch(fn, media_type, page_no, label)
		total_pages = max(total_pages, pages)
		for item in data:
			item_id = item.get('id') if isinstance(item, dict) else item
			if item_id is not None and item_id not in seen:
				seen.add(item_id)
				merged.append(item_id)
	return merged, total_pages


def _merge_trakt(fns_and_labels, media_type, page_no):
	seen, merged, total_pages = set(), [], 0
	for fn, label in fns_and_labels:
		data, pages = _safe_fetch(fn, media_type, page_no, label)
		total_pages = max(total_pages, pages)
		for item in data:
			if isinstance(item, dict):
				ids = item.get('media_ids') or {}
				key = ids.get('tmdb') or ids.get('imdb') or ids.get('trakt')
				if key is not None and key not in seen:
					seen.add(key)
					merged.append(ids)
	return merged, total_pages


def _populate(instance, page_no, actions, tmdb_media_type, trakt_mdblist_media_type):
	if instance.action not in actions:
		return

	# Check service status early to prevent redundant API calls / timeouts
	try:
		import pov_visibility_mgr
		if instance.action.startswith('tmdb_'):
			service = 'tmdb'
		elif instance.action.startswith('mdblist_'):
			service = 'mdblist'
		else:
			service = 'trakt'

		if not pov_visibility_mgr.is_service_active(service):
			instance.list = []
			return
	except Exception:
		if xbmc:
			xbmc.log('[POV Wizard][MyLists] pov_visibility_mgr unavailable, skipping service status check', xbmc.LOGWARNING)

	total_pages = 0
	if instance.action.startswith('tmdb_'):
		from indexers.tmdb_api import tmdb_favorites, tmdb_watchlist
		merged, total_pages = _merge_tmdb_or_mdblist(
			((tmdb_favorites, 'tmdb_favorites'), (tmdb_watchlist, 'tmdb_watchlist')),
			tmdb_media_type, page_no
		)
		instance.list = merged

	elif instance.action.startswith('mdblist_'):
		from indexers.mdblist_api import mdblist_watchlist, mdblist_collection
		# MDBList uses 'movies'/'shows' like Trakt, and returns dicts where 'id' is TMDB
		merged, total_pages = _merge_tmdb_or_mdblist(
			((mdblist_collection, 'mdblist_collection'), (mdblist_watchlist, 'mdblist_watchlist')),
			trakt_mdblist_media_type, page_no
		)
		instance.list = merged

	elif instance.action.startswith('trakt_'):
		instance.id_type = 'trakt_dict'
		from indexers.trakt_api import trakt_collection, trakt_watchlist, trakt_favorites
		merged, total_pages = _merge_trakt(
			((trakt_collection, 'trakt_collection'),
			 (trakt_watchlist, 'trakt_watchlist'),
			 (trakt_favorites, 'trakt_favorites')),
			trakt_mdblist_media_type, page_no
		)
		instance.list = merged

	if total_pages > 2:
		instance.total_pages = total_pages
	if isinstance(page_no, int) and total_pages > page_no:
		instance.new_page = {'new_page': str(page_no + 1)}


def maybe_populate_movies(instance, page_no):
	if instance.action not in MOVIE_ACTIONS:
		return
	_populate(instance, page_no, MOVIE_ACTIONS, 'movie', 'movies')


def maybe_populate_tvshows(instance, page_no):
	if instance.action not in TVSHOW_ACTIONS:
		return
	_populate(instance, page_no, TVSHOW_ACTIONS, 'tv', 'shows')