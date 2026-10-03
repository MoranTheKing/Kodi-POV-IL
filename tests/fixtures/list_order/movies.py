"""Verbatim official Umbrella 6.7.90 method fixtures; source SHA256 65f08892b8645d6ad45298a3328be364c9266f7e36b90ad079b9cb71dd9b661b."""
import re
class Movies:
	def mbd_user_lists(self, addremove):
		try:
			listType = 'movie'
			items = mdblist.getMDBUserList(self, listType, addremove)
			next = ''
		except:
			from resources.lib.modules import log_utils
			log_utils.error()
		for item in items:
			try:
				list_name = item.get('params', {}).get('list_name', '')
				list_id = item.get('params', {}).get('list_id', '')
				list_owner = item.get('unique_ids', {}).get('user', '')
				list_count = item.get('params', {}).get('list_count', '')
				list_url = self.mbdlist_list_items % (list_id)
				label = '%s - (%s)' % (list_name, list_count)
				self.list.append({'name': label, 'url': list_url, 'list_owner': list_owner, 'list_name': list_name, 'list_id': list_id, 'context': list_url, 'next': next, 'image': 'mdblist.png', 'icon': 'mdblist.png', 'action': 'movies&folderName=%s' % quote_plus(list_name)})
			except:
				from resources.lib.modules import log_utils
				log_utils.error()
		return self.list

	def get_mdbuser_watchlist(self, url=None, create_directory=True, folderName=''):
		self.list = []
		try:
			try:
				if not url or '?' not in url:
					url = 'mdbwatchlist?limit=%s&page=1' % self.page_limit
				q = dict(parse_qsl(urlsplit(url).query))
				index = int(q.get('page', 1)) - 1
			except:
				index = 0
			listType = 'movie'
			self.list = cache.get(mdblist.get_user_watchlist, 0, listType)
			if self.list is None: self.list = []
			self.worker()
			self.sort(type='movies.watchlist')
			next = ''
			if getSetting('mdblist.paginate.lists') == 'true' and self.list:
				paginated_ids = [self.list[x:x + int(self.page_limit)] for x in range(0, len(self.list), int(self.page_limit))]
				total_pages = len(paginated_ids)
				self.list = paginated_ids[index] if index < total_pages else []
				try:
					if index + 1 >= total_pages: raise Exception()
					next_page = index + 2
					next = 'plugin://plugin.video.umbrella/?action=mdbUserWatchListMovies&url=%s&page=%s&folderName=%s' % (
						quote_plus('mdbwatchlist?limit=%s&page=%s' % (self.page_limit, next_page)),
						str(next_page), quote_plus(folderName))
				except: pass
			for i in range(len(self.list)): self.list[i]['next'] = next
			hasNext = bool(next)
			return self.movieDirectory(self.list, next=hasNext, folderName=folderName)
		except:
			from resources.lib.modules import log_utils
			log_utils.error()

	def get_mdbuser_collection(self, url=None, create_directory=True, folderName=''):
		self.list = []
		try:
			try:
				if not url or '?' not in url:
					url = 'mdbcollection?limit=%s&page=1' % self.page_limit
				q = dict(parse_qsl(urlsplit(url).query))
				index = int(q.get('page', 1)) - 1
			except:
				index = 0
			listType = 'movie'
			self.list = cache.get(mdblist.get_user_collection, 0, listType)
			if self.list is None: self.list = []
			self.worker()
			self.sort(type='movies.watchlist')
			next = ''
			if getSetting('mdblist.paginate.lists') == 'true' and self.list:
				paginated_ids = [self.list[x:x + int(self.page_limit)] for x in range(0, len(self.list), int(self.page_limit))]
				total_pages = len(paginated_ids)
				self.list = paginated_ids[index] if index < total_pages else []
				try:
					if index + 1 >= total_pages: raise Exception()
					next_page = index + 2
					next = 'plugin://plugin.video.umbrella/?action=mdbUserCollectionMovies&url=%s&page=%s&folderName=%s' % (
						quote_plus('mdbcollection?limit=%s&page=%s' % (self.page_limit, next_page)),
						str(next_page), quote_plus(folderName))
				except: pass
			for i in range(len(self.list)): self.list[i]['next'] = next
			hasNext = bool(next)
			return self.movieDirectory(self.list, next=hasNext, folderName=folderName)
		except:
			from resources.lib.modules import log_utils
			log_utils.error()

	def mdb_list_items(self, url, create_directory=True, folderName=''):
		self.list = []
		q = dict(parse_qsl(urlsplit(url).query))
		index = int(q['page']) - 1
		def mbdList_totalItems(url):
			items = mdblist.getMDBItems(url)
			if not items: return
			for item in items:
				try:
					values = {}
					values['title'] = item.get('title', '')
					values['originaltitle'] = item.get('title', '')
					try: values['premiered'] = item['release_year']
					except: values['premiered'] = ''
					values['year'] = str(item.get('release_year', '')) if item.get('release_year') else ''
					values['imdb'] = str(item.get('imdb', '')) if item.get('imdb') else ''
					values['rank'] = item.get('rank')
					self.list.append(values)
				except:
					from resources.lib.modules import log_utils
					log_utils.error()
			return self.list
		self.list = mbdList_totalItems(url)
		if not self.list: return
		self.sort() # sort before local pagination
		next = ''
		if getSetting('mdblist.paginate.lists') == 'true':
			total_pages = 1
			if len(self.list) == int(self.page_limit):
				useNext = False
			else:
				useNext = True
			paginated_ids = [self.list[x:x + int(self.page_limit)] for x in range(0, len(self.list), int(self.page_limit))]
			total_pages = len(paginated_ids)
			self.list = paginated_ids[index]
			try:
				if useNext == False: raise Exception()
				if int(self.page_limit) != len(self.list): raise Exception()
				if int(q['page']) == total_pages: raise Exception()
				q.update({'page': str(int(q['page']) + 1)})
				q = (urlencode(q)).replace('%2C', ',')
				next = url.replace('?' + urlparse(url).query, '') + '?' + q
				next = next + '&folderName=%s' % quote_plus(folderName)
			except: next = ''
		for i in range(len(self.list)): self.list[i]['next'] = next
		self.worker()
		if self.list is None: self.list = []
		if create_directory: self.movieDirectory(self.list, folderName=folderName)
		return self.list

	def sort(self, type='movies'):
		try:
			if not self.list: return
			attribute = int(getSetting('sort.%s.type' % type) or '0')
			reverse = int(getSetting('sort.%s.order' % type) or '0') == 1
			if attribute == 0: reverse = False # Sorting Order is not enabled when sort method is "Default"
			if attribute > 0:
				if attribute == 1:
					try: self.list = sorted(self.list, key=lambda k: re.sub(r'(^the |^a |^an )', '', k['title'].lower()), reverse=reverse)
					except: self.list = sorted(self.list, key=lambda k: k['title'].lower(), reverse=reverse)
				elif attribute == 2: self.list = sorted(self.list, key=lambda k: float(k['rating']), reverse=reverse)
				elif attribute == 3: self.list = sorted(self.list, key=lambda k: int(str(k['votes']).replace(',', '')), reverse=reverse)
				elif attribute == 4:
					for i in range(len(self.list)):
						if 'premiered' not in self.list[i]: self.list[i]['premiered'] = ''
					self.list = sorted(self.list, key=lambda k: k['premiered'], reverse=reverse)
				elif attribute == 5:
					for i in range(len(self.list)):
						if 'added' not in self.list[i]: self.list[i]['added'] = ''
					self.list = sorted(self.list, key=lambda k: k['added'], reverse=reverse)
				elif attribute == 6:
					for i in range(len(self.list)):
						if 'lastplayed' not in self.list[i]: self.list[i]['lastplayed'] = ''
					self.list = sorted(self.list, key=lambda k: k['lastplayed'], reverse=reverse)
			elif reverse:
				self.list = list(reversed(self.list))
		except:
			from resources.lib.modules import log_utils
			log_utils.error()

	def traktCollection(self, url, create_directory=True, folderName=''):
		self.list = []
		try:
			try:
				q = dict(parse_qsl(urlsplit(url).query))
				index = int(q['page']) - 1
			except:
				q = dict(parse_qsl(urlsplit(url).query))
			self.list = traktsync.fetch_collection('movies_collection')
			useNext = True
			if create_directory:
				self.sort() # sort before local pagination
				if getSetting('trakt.paginate.lists') == 'true' and self.list:
					if len(self.list) == int(self.page_limit):
						useNext = False
					paginated_ids = [self.list[x:x + int(self.page_limit)] for x in range(0, len(self.list), int(self.page_limit))]
					self.list = paginated_ids[index]
			try:
				if useNext == False: raise Exception()
				if int(q['limit']) != len(self.list): raise Exception()
				q.update({'page': str(int(q['page']) + 1)})
				q = (urlencode(q)).replace('%2C', ',')
				next = url.replace('?' + urlparse(url).query, '') + '?' + q
				next = next + '&folderName=%s' % quote_plus(folderName)
			except: next = ''
			for i in range(len(self.list)): self.list[i]['next'] = next
			self.worker()
			if self.list is None: self.list = []
			if create_directory: self.movieDirectory(self.list, isCollection=True, folderName=folderName)
			return self.list
		except:
			from resources.lib.modules import log_utils
			log_utils.error()

	def traktWatchlist(self, url, create_directory=True, folderName=''):
		self.list = []
		try:
			try:
				q = dict(parse_qsl(urlsplit(url).query))
				index = int(q['page']) - 1
			except:
				q = dict(parse_qsl(urlsplit(url).query))
			self.list = traktsync.fetch_watch_list('movies_watchlist')
			useNext = True
			if create_directory:
				self.sort(type='movies.watchlist') # sort before local pagination
				if getSetting('trakt.paginate.lists') == 'true' and self.list:
					if len(self.list) == int(self.page_limit):
						useNext = False
					paginated_ids = [self.list[x:x + int(self.page_limit)] for x in range(0, len(self.list), int(self.page_limit))]
					self.list = paginated_ids[index]
			try:
				if useNext == False: raise Exception()
				if int(q['limit']) != len(self.list): raise Exception()
				q.update({'page': str(int(q['page']) + 1)})
				q = (urlencode(q)).replace('%2C', ',')
				next = url.replace('?' + urlparse(url).query, '') + '?' + q
				next = next + '&folderName=%s' % quote_plus(folderName)
			except: next = ''
			for i in range(len(self.list)): self.list[i]['next'] = next
			self.worker()
			if self.list is None: self.list = []
			if create_directory: self.movieDirectory(self.list, folderName=folderName)
			return self.list
		except:
			from resources.lib.modules import log_utils
			log_utils.error()

	def trakt_userList(self, url, create_directory=True, folderName=''):
		self.list = []
		q = dict(parse_qsl(urlsplit(url).query))
		index = int(q['page']) - 1
		def userList_totalItems(url):
			items = trakt.get_all_pages(url)
			if not items: return
			for item in items:
				try:
					values = {}
					values['added'] = item.get('listed_at', '')
					movie = item['movie']
					values['title'] = movie.get('title')
					values['originaltitle'] = values['title']
					try: values['premiered'] = movie.get('released', '')[:10]
					except: values['premiered'] = ''
					values['year'] = str(movie.get('year', '')) if movie.get('year') else ''
					if not values['year']:
						try: values['year'] = str(values['premiered'][:4])
						except: values['year'] = ''
					ids = movie.get('ids', {})
					values['imdb'] = str(ids.get('imdb', '')) if ids.get('imdb') else ''
					values['tmdb'] = str(ids.get('tmdb', '')) if ids.get('tmdb') else ''
					values['rating'] = movie.get('rating')
					values['votes'] = movie.get('votes')
					values['mediatype'] = 'movies'
					self.list.append(values)
				except:
					from resources.lib.modules import log_utils
					log_utils.error()
			return self.list
		_force_fresh = control.homeWindow.getProperty('umbrella.trakt.userlist.modified') == 'true'
		if _force_fresh:
			control.homeWindow.clearProperty('umbrella.trakt.userlist.modified')
		self.list = cache.get(userList_totalItems, 0 if _force_fresh else self.traktuserlist_hours, url.split('?')[0] + '?extended=full')
		if not self.list: return
		if int(getSetting('sort.movies.type') or '0') == 6:
			watched_dates = trakt.getWatchedMoviesLastWatchedDates()
			if watched_dates:
				for item in self.list:
					if not item.get('lastplayed'):
						item['lastplayed'] = watched_dates.get(item.get('imdb', ''), '')
		self.sort() # sort before local pagination
		total_pages = 1
		useNext = True
		if getSetting('trakt.paginate.lists') == 'true':
			if len(self.list) == int(self.page_limit):
				useNext = False
			paginated_ids = [self.list[x:x + int(self.page_limit)] for x in range(0, len(self.list), int(self.page_limit))]
			total_pages = len(paginated_ids)
			self.list = paginated_ids[index]
		try:
			if useNext == False: raise Exception()
			if int(q['limit']) != len(self.list): raise Exception()
			if int(q['page']) == total_pages: raise Exception()
			q.update({'page': str(int(q['page']) + 1)})
			q = (urlencode(q)).replace('%2C', ',')
			next = url.replace('?' + urlparse(url).query, '') + '?' + q
			next = next + '&folderName=%s' % quote_plus(folderName)
		except: next = ''
		for i in range(len(self.list)): self.list[i]['next'] = next
		self.worker()
		if self.list is None: self.list = []
		if create_directory: self.movieDirectory(self.list, folderName=folderName)
		return self.list
