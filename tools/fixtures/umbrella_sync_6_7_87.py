# Verbatim function fixtures from Umbrella 6.7.87 (GNU GPL version 3).
# Source: https://github.com/umbrellaplug/umbrellaplug.github.io
# Archive SHA256: c9862b1597ef418f580e898019bb3c9281def46e526115c4b98f0a9822b80252
# Executed with synthetic services by test_umbrella_server_cursor.py.

def get_request(url, post=None, method='GET', _retried=False):
	try:
		full_url = f"{mdblist_baseurl}{url}"
		import json as _json
		for _attempt in range(2):
			try:
				if method == 'DELETE':
					response = session.delete(full_url, headers=headers, timeout=20)
				elif post is not None:
					response = session.post(full_url, data=_json.dumps(post), headers=headers, timeout=20)
				else:
					response = session.get(full_url, timeout=20)
				break
			except requests.exceptions.ConnectionError:
				if _attempt == 0:
					log_utils.log('MDBList get_request: connection reset, retrying with fresh connection...', level=log_utils.LOGDEBUG)
					session.close()
				else:
					raise
		if response.status_code in (200, 201, 204):
			try: return response.json()
			except: return {}
		if response.status_code == 401 and not _retried:
			if _refresh_token():
				return get_request(url, post=post, method=method, _retried=True)
			control.notification(title='MDBList', message='MDBList session expired — please re-authenticate in settings')
		log_utils.log('MDBList get_request non-2xx: url=%s status=%s body=%r' % (url, response.status_code, response.text[:200]), level=log_utils.LOGDEBUG)
		return None
	except: log_utils.error()
	return None

def _activities_dict(activities=None):
	try:
		i = activities if activities else getActivities()
		if not i: return {}
		if isinstance(i, str):
			import json as _json
			i = _json.loads(i)
		return i if isinstance(i, dict) else {}
	except: log_utils.error()
	return {}

def getWatchedActivity(activities=None):
	try:
		i = _activities_dict(activities)
		return max(_activity_timestamp(i.get(key)) for key in
			('watched_at', 'season_watched_at', 'episode_watched_at', 'history_at'))
	except: log_utils.error()
	return 0

def getServerTime(activities=None):
	try: return _activity_timestamp(_activities_dict(activities).get('server_time'))
	except: log_utils.error()
	return 0

def sync_watchedProgress(activities=None, forced=False):
	try:
		# A new cursor key forces one complete snapshot on upgrade. Legacy builds
		# stored a device wall-clock value which could be ahead of MDBList forever.
		db_last = mdbsync.last_sync('last_watched_sync_at_v2')
		api_last = getWatchedActivity(activities)
		if not forced and db_last and api_last <= db_last: return
		from datetime import datetime as _dt
		since = _dt.utcfromtimestamp(db_last).strftime('%Y-%m-%dT%H:%M:%SZ') if db_last else '1970-01-01T00:00:00Z'
		offset = 0
		limit = 1000
		movie_count = 0
		episode_count = 0
		while True:
			url = f"/sync/watched?since={since}&limit={limit}&offset={offset}"
			data = get_request(url)
			# Do not advance the cursor when the request failed; the next service
			# pass must retry the same activity window.
			if data is None: return
			if not data: break
			for item in data.get('movies', []):
				ids = item.get('movie', {}).get('ids', {})
				imdb = str(ids.get('imdb', ''))
				if not imdb: continue
				mdbsync.upsert_watched_movie(
					imdb=imdb,
					tmdb=str(ids.get('tmdb', '')),
					title=item.get('movie', {}).get('title', ''),
					year=str(item.get('movie', {}).get('year', '')),
					last_watched_at=item.get('last_watched_at', '')
				)
				movie_count += 1
			for item in data.get('episodes', []):
				ep = item.get('episode', {})
				show_ids = ep.get('show', {}).get('ids', {})
				show_imdb = str(show_ids.get('imdb', ''))
				if not show_imdb: continue
				mdbsync.upsert_watched_episode(
					show_imdb=show_imdb,
					show_tmdb=str(show_ids.get('tmdb', '')),
					show_tvdb=str(show_ids.get('tvdb', '')),
					season=ep.get('season', 0),
					episode=ep.get('number', 0),
					last_watched_at=item.get('last_watched_at', '')
				)
				episode_count += 1
			pagination = data.get('pagination', {})
			if not pagination.get('has_more', False): break
			offset += limit
		# MDBList explicitly documents server_time as the safe sync cursor.
		checkpoint = getServerTime(activities) or api_last or None
		mdbsync.update_last_watched_at('last_watched_sync_at_v2', checkpoint)
		mdbsync.update_last_watched_at('last_watched_at', checkpoint)
		# invalidate indicator caches so next access fetches fresh data
		mdbsync.cache_delete(mdbsync._hash_function(syncMovies, ()))
		mdbsync.cache_delete(mdbsync._hash_function(syncTVShows, ()))
		_clr_episode_progress_cache()
		log_utils.log('MDBList watched sync applied %s movies and %s episodes (activity=%s, cursor=%s)' %
			(movie_count, episode_count, api_last, checkpoint), level=log_utils.LOGDEBUG)
		return True
	except: log_utils.error()
	return False
