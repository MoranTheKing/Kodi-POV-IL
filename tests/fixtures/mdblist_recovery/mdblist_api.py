"""Verbatim POV 6.10.01 fixtures; source SHA256 355a8930167d1614485256197e1f41e06decbfd23f0c3d09b2c73a0e700abab8."""
def call_mdblist(path, params=None, json=None, method=None):
	headers = None
	params = params or {}
	if not bool(get_setting('mdblist.refresh')): params.setdefault('apikey', get_setting('mdblist.token'))
	else: headers = {'Authorization': 'Bearer %s' % get_setting('mdblist.token')}
	try:
		response = session.request(
			method or 'get',
			base_url + path,
			params=params,
			json=json,
			headers=headers,
			timeout=timeout
		)
		if 'json' in response.headers.get('Content-Type', ''):
			result = response.json()
		else: result = response.text
		if not response.ok: raise Exception(f"{response.reason}, {response.url}")
		if isinstance(result, list):
			result = {'items': result, 'pagination': {'has_more': response.headers.get('X-Has-More') == 'true'}}
			if (next := response.headers.get('X-Next-Cursor')): result['pagination']['next_cursor'] = next
		return result
	except Exception as e:
		logger('mdblist error', str(e))

def _get_mdbl_paginated_list(url):
	params = {'limit': 1000}
	items = {'movies': [], 'shows': [], 'episodes': [], 'items': []}
	try:
		for _ in range(MAX_LIST_ITEMS // params['limit']):
			result = call_mdblist(url, params=params)
			if not isinstance(result, dict): break
			for k in items:
				if k in result and isinstance(result[k], list):
					items[k].extend(result[k])
			if not result['pagination']['has_more']: break
			params['cursor'] = result['pagination']['next_cursor']
	except: pass
	return items

def mdbl_refresh():
	try:
		created_at = __import__('time').time()
		data = {'grant_type': 'refresh_token'}
		data['refresh_token'] = get_setting('mdblist.refresh')
		data['client_id'] = get_setting('mdblist.client_id')
		url = 'https://api.mdblist.com/oauth/token/'
		response = session.request('post', url, data=data, timeout=timeout).json()
		expires = int(created_at) + int(response['expires_in'])
		token, refresh = response['access_token'], response['refresh_token']
		set_setting('mdblist.token', token)
		set_setting('mdblist.refresh', refresh)
		set_setting('mdblist.expires', str(expires))
		kodi_utils.sleep(500)
	except Exception as e: logger('mdbl_refresh error', str(e))

# Additional verbatim expiry function from the pinned official POV 6.10.05.
def mdbl_expires():
	if not get_setting('mdblist.refresh', ''): return
	from datetime import datetime, timezone
	interval = settings.trakt_sync_interval()[1]
	current = int(datetime.now(timezone.utc).timestamp())
	expires = int(get_setting('mdblist.expires', '0'))
	if interval + current >= expires: mdbl_refresh()

def mdbl_collection_watchlist_items(list_type, mediatype):
	if list_type == 'collection': string, url = 'mdbl_collection', '/sync/collection'
	else: string, url = 'mdbl_watchlist', '/watchlist/items'
	results = mdbl_cache.cache_mdbl_object(_get_mdbl_paginated_list, string, url)
	results = results['movies' if mediatype in ('movie', 'movies') else 'shows']
	if list_type == 'collection':
		def _year(item):
			if isinstance(item.get('year'), int): return str(item['year'])
			return item.get('year')
		key = 'movie' if mediatype in ('movie', 'movies') else 'show'
		results = [
			{'collected_at': i['collected_at'],
			 'year': _year(i[key]),
			 'title': i[key]['title'],
			 'id': i[key]['ids']['tmdb'],
			 'imdb_id': i[key]['ids']['imdb']}
			for i in results
		] # only endpoint with nested media. no response to feature req to flatten.
	return results

def mdbl_get_lists(list_type):
	if list_type == 'external': key, string, url = 'items', 'mdbl_external', '/external/lists/user'
	elif list_type == 'liked_lists': key, string, url = 'lists', 'mdbl_liked_lists', '/lists/liked'
	else: key, string, url = 'items', 'mdbl_my_lists', '/lists/user'
	return mdbl_cache.cache_mdbl_object(call_mdblist, string, url)[key]

def mdbl_sync_activities(force_update=False, init_callback=None, monitor=None):
	def _compare(latest, cached):
		try: return (latest or '') > (cached or '')
		except: return True
	if not get_setting('mdblist_user', ''): return 'no account'
	if monitor and monitor.abortRequested(): return
	if callable(init_callback): init_callback()
	elif init_callback is True: mdbl_expires()
	else: pass
	if force_update:
		check_databases()
		mdbl_cache.clear_all_mdbl_cache_data(refresh=False)
	mdbl_cache.clear_mdbl_calendar()
	latest = mdbl_get_activity()
	if not (isinstance(latest, dict) and 'journal_at' in latest):
		logger('mdblist error', str(latest))
		mdbl_cache.clear_all_mdbl_cache_data(refresh=False)
		return 'failed'
	cached = mdbl_cache.reset_activity(latest)
	success = 'not needed'
	# format: (timestamp_key, callback_args, callback_func)
	for key, args, func in (
		('collected_at',   ('collection',), mdbl_cache.clear_mdbl_collection_watchlist_data),
		('watchlisted_at', ('watchlist',),  mdbl_cache.clear_mdbl_collection_watchlist_data),
		('dropped_at',     ('dropped',),    mdbl_cache.clear_mdbl_hidden_data)
	):
		if _compare(latest[key], cached[key]):
			success = 'success'
			func(*args)
	if _compare(latest['list_updated_at'], cached['list_updated_at']):
		success = 'success'
		for i in ('external', 'liked_lists', 'my_lists'):
			mdbl_cache.clear_mdbl_list_data(i)
			mdbl_cache.clear_mdbl_list_contents_data(i)
	refresh_movies_watched = _compare(latest['watched_at'], cached['watched_at'])
	refresh_episodes_watched = _compare(latest['episode_watched_at'], cached['episode_watched_at'])
	if refresh_movies_watched or refresh_episodes_watched:
		success = 'success'
		watched_info = _get_mdbl_paginated_list('/sync/watched')
		if refresh_movies_watched: mdbl_indicators_movies(watched_info)
		if refresh_episodes_watched: mdbl_indicators_tv(watched_info)
	refresh_movies_progress = _compare(latest['paused_at'], cached['paused_at'])
	refresh_episodes_progress = _compare(latest['episode_paused_at'], cached['episode_paused_at'])
	if refresh_movies_progress or refresh_episodes_progress:
		success = 'success'
		progress_info = mdbl_playback_progress()['items']
		if refresh_movies_progress: mdbl_progress_movies(progress_info)
		if refresh_episodes_progress: mdbl_progress_tv(progress_info)
	return success
