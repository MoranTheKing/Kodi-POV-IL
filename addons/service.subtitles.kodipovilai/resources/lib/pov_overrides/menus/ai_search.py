import sys

from indexers import tmdb_api
from modules import kodi_utils
from modules.utils import get_datetime

try:
	from indexers.metadata import (
		art_infodict, movie_meta, movie_show_infodict, tvshow_meta,
		tmdb_image_base
	)
	from modules import settings
except Exception:
	art_infodict = movie_meta = movie_show_infodict = tvshow_meta = None
	tmdb_image_base = 'https://image.tmdb.org/t/p/%s%s'
	settings = None


AI_SUBS_COMBINED_SEARCH_MARKER = 'ai_pov_combined_search_v2'


def _as_int(value, default=1):
	try:
		return int(value)
	except Exception:
		return default


def _fallback_art(item):
	poster_path = item.get('poster_path') or ''
	backdrop_path = item.get('backdrop_path') or ''
	poster = tmdb_image_base % ('w780', poster_path) if poster_path else kodi_utils.media_path('box_office.png')
	fanart = tmdb_image_base % ('w1280', backdrop_path) if backdrop_path else kodi_utils.get_addoninfo('fanart')
	return {
		'poster': poster,
		'thumb': poster,
		'icon': poster,
		'fanart': fanart,
		'tvshow.poster': poster,
		'landscape': fanart,
		'tvshow.landscape': fanart,
	}


def _meta_art(meta, mediatype):
	if not meta or art_infodict is None or settings is None:
		return None
	try:
		meta_user_info = settings.metadata_user_info()
		art_provider = (
			*settings.get_art_provider(),
			kodi_utils.media_path('box_office.png'),
			kodi_utils.get_addoninfo('fanart')
		)
		art = art_infodict(meta, art_provider, meta_user_info)
		poster = art.get('poster') or art.get('icon') or ''
		fanart = art.get('fanart') or ''
		if poster:
			art.setdefault('thumb', poster)
			art.setdefault('icon', poster)
			if mediatype == 'tvshow':
				art.setdefault('tvshow.poster', poster)
		if fanart:
			art.setdefault('landscape', fanart)
			if mediatype == 'tvshow':
				art.setdefault('tvshow.landscape', fanart)
		return art
	except Exception:
		return None


def _movie_meta(tmdb_id):
	if movie_meta is None or settings is None:
		return {}
	try:
		return movie_meta('tmdb_id', tmdb_id, settings.metadata_user_info(), get_datetime()) or {}
	except Exception:
		return {}


def _tv_meta(tmdb_id):
	if tvshow_meta is None or settings is None:
		return {}
	try:
		return tvshow_meta('tmdb_id', tmdb_id, settings.metadata_user_info(), get_datetime()) or {}
	except Exception:
		return {}


def _set_info(listitem, meta, item, mediatype, label):
	plot = meta.get('plot') or item.get('overview') or ''
	year_src = (
		meta.get('year') or
		(item.get('release_date') or item.get('first_air_date') or '')[:4]
	)
	try:
		year = int(year_src or 0)
	except Exception:
		year = 0
	info = {
		'title': label,
		'plot': plot,
		'mediatype': mediatype,
	}
	if year:
		info['year'] = year
	if meta and movie_show_infodict is not None:
		try:
			info.update(movie_show_infodict(meta))
		except Exception:
			pass
	try:
		listitem.setInfo('video', info)
	except Exception:
		pass


def _make_movie(item, position):
	tmdb_id = item.get('id')
	if not tmdb_id:
		return None
	meta = _movie_meta(tmdb_id)
	label = meta.get('rootname') or meta.get('title') or item.get('title') or item.get('original_title') or ''
	art = _meta_art(meta, 'movie') or _fallback_art(item)
	listitem = kodi_utils.make_listitem()
	listitem.setLabel(label)
	listitem.setArt(art)
	listitem.setProperties({
		AI_SUBS_COMBINED_SEARCH_MARKER: 'true',
		'mediatype': 'movie',
		'tmdb_type': 'movie',
		'tmdb_id': str(tmdb_id),
		'pov_sort_order': str(position),
	})
	try:
		listitem.setUniqueIDs({'tmdb': str(tmdb_id)})
	except Exception:
		pass
	_set_info(listitem, meta, item, 'movie', label)
	url = kodi_utils.build_url({
		'mode': 'play_media',
		'mediatype': 'movie',
		'tmdb_id': tmdb_id,
	})
	return (url, listitem, False)


def _make_tvshow(item, position):
	tmdb_id = item.get('id')
	if not tmdb_id:
		return None
	meta = _tv_meta(tmdb_id)
	label = meta.get('rootname') or meta.get('title') or item.get('name') or item.get('original_name') or ''
	art = _meta_art(meta, 'tvshow') or _fallback_art(item)
	listitem = kodi_utils.make_listitem()
	listitem.setLabel(label)
	listitem.setArt(art)
	listitem.setProperties({
		AI_SUBS_COMBINED_SEARCH_MARKER: 'true',
		'mediatype': 'tvshow',
		'tmdb_type': 'tv',
		'tmdb_id': str(tmdb_id),
		'pov_sort_order': str(position),
	})
	try:
		listitem.setUniqueIDs({'tmdb': str(tmdb_id)})
	except Exception:
		pass
	_set_info(listitem, meta, item, 'tvshow', label)
	url = kodi_utils.build_url({
		'mode': 'build_season_list',
		'tmdb_id': tmdb_id,
	})
	return (url, listitem, True)


def _interleave(movie_results, tv_results):
	out = []
	max_len = max(len(movie_results), len(tv_results))
	for idx in range(max_len):
		if idx < len(movie_results):
			out.append(('movie', movie_results[idx]))
		if idx < len(tv_results):
			out.append(('tvshow', tv_results[idx]))
	return out


def _media_type(params):
	value = (params.get('media_type') or params.get('type') or 'all').lower()
	if value in ('movie', 'movies'):
		return 'movie'
	if value in ('tv', 'show', 'shows', 'tvshow', 'tvshows'):
		return 'tvshow'
	return 'all'


def run(params):
	handle = int(sys.argv[1])
	query = (params.get('query') or '').strip()
	media_type = _media_type(params)
	page_no = _as_int(params.get('new_page') or params.get('page'), 1)
	if query and media_type in ('all', 'movie'):
		movie_data = tmdb_api.tmdb_movies_search(query, page_no) or {}
	elif not query and media_type in ('all', 'movie'):
		movie_data = tmdb_api.tmdb_movies_popular(page_no) or {}
	else:
		movie_data = {}

	if query and media_type in ('all', 'tvshow'):
		tv_data = tmdb_api.tmdb_tv_search(query, page_no) or {}
	elif not query and media_type in ('all', 'tvshow'):
		tv_data = tmdb_api.tmdb_tv_popular(page_no) or {}
	else:
		tv_data = {}
	movie_results = movie_data.get('results') or []
	tv_results = tv_data.get('results') or []

	items = []
	if media_type == 'movie':
		iterable = [('movie', item) for item in movie_results]
	elif media_type == 'tvshow':
		iterable = [('tvshow', item) for item in tv_results]
	else:
		iterable = _interleave(movie_results, tv_results)
	for pos, (mediatype, item) in enumerate(iterable, 1):
		try:
			built = _make_movie(item, pos) if mediatype == 'movie' else _make_tvshow(item, pos)
			if built:
				items.append(built)
		except Exception as exc:
			try:
				kodi_utils.logger('AI_POV_COMBINED_SEARCH_ITEM_ERROR', repr(exc))
			except Exception:
				pass

	kodi_utils.add_items(handle, items)
	max_pages = max(
		_as_int(movie_data.get('total_pages'), 1),
		_as_int(tv_data.get('total_pages'), 1)
	)
	if max_pages > page_no:
		kodi_utils.add_dir(
			handle,
			{
				'mode': 'ai_pov_combined_search',
				'query': query,
				'media_type': media_type,
				'new_page': str(page_no + 1),
				'name': params.get('name') or 'Search Results',
			},
			'Next Page',
			kodi_utils.media_path('item_next.png'),
			isFolder=True
		)
	kodi_utils.set_category(handle, params.get('name') or 'Search Results')
	kodi_utils.set_sort_method(handle, 'unsorted')
	content_type = 'tvshows' if media_type == 'tvshow' else 'movies'
	kodi_utils.set_content(handle, content_type)
	kodi_utils.end_directory(handle, False)
