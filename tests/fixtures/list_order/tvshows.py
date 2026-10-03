"""Verbatim official Umbrella 6.7.90 method fixtures; source SHA256 c121efe64effbf1a07fe2b43d5a2706e1d89077df84782afbac29219e6ef7988."""
import re
class TVshows:
	def sort(self, type='shows'):
		try:
			if not self.list: return
			attribute = int(getSetting('sort.%s.type' % type) or '0')
			reverse = int(getSetting('sort.%s.order' % type) or '0') == 1
			if attribute == 0:
				if type == 'progress':
					reverse = True
					attribute = 6
				else:
					reverse = False # Sorting Order is not enabled when sort method is "Default"
			if attribute > 0:
				if attribute == 1:
					try: self.list = sorted(self.list, key=lambda k: re.sub(r'(^the |^a |^an )', '', k['tvshowtitle'].lower()), reverse=reverse)
					except: self.list = sorted(self.list, key=lambda k: re.sub(r'(^the |^a |^an )', '', k['title'].lower()), reverse=reverse)
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
					nolastPlayed = []
					for i in range(len(self.list)):
						if 'lastplayed' not in self.list[i]:
							self.list[i]['lastplayed'] = ''
							log_utils.log('TVShow Last Played Blank Title: %s' % self.list[i].get('title', ''), 1)
					#self.list = sorted(self.list, key=lambda k: k['lastplayed'], reverse=reverse)
					if self.list:
						def _parse_lastplayed(k):
							lp = k.get('lastplayed')
							if not lp:
								return time.gmtime(0)
							# Some providers' raw timestamps don't match either expected
							# format (e.g. an unexpected double-fraction like
							# "...25.000.000Z") — never let one bad value crash sorting
							# for the whole list. Scrob's own /history timestamps come
							# through with no trailing "Z" at all (Python's raw
							# datetime.isoformat() shape, e.g. "...21:35:47.759746"),
							# which silently fell back to epoch for every Scrob show and
							# made its progress list sort in essentially arbitrary order.
							for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
								try: return time.strptime(lp, fmt)
								except ValueError: continue
							return time.gmtime(0)
						self.list = sorted(self.list, key=_parse_lastplayed, reverse=reverse)
			elif reverse:
				self.list = list(reversed(self.list))
		except:

			log_utils.error()

	def traktCollection(self, url, create_directory=True, folderName=''):
		log_utils.log('traktCollection url: %s' % url, 1)
		self.list = []
		try:
			try:
				q = dict(parse_qsl(urlsplit(url).query))
				index = int(q['page']) - 1
			except:
				q = dict(parse_qsl(urlsplit(url).query))
			self.list = traktsync.fetch_collection('shows_collection')
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
				log_utils.log('traktCollection next url: %s' % next, 1)
			except: next = ''
			for i in range(len(self.list)): self.list[i]['next'] = next
			self.worker()
			if self.list is None: self.list = []
			if create_directory: self.tvshowDirectory(self.list, folderName=folderName, isCollection=True)
			return self.list
		except:

			log_utils.error()

	def traktWatchlist(self, url, create_directory=True, folderName=''):
		log_utils.log('traktWatchlist url: %s' % url, 1)
		self.list = []
		try:
			try:
				q = dict(parse_qsl(urlsplit(url).query))
				index = int(q['page']) - 1
			except:
				q = dict(parse_qsl(urlsplit(url).query))
			self.list = traktsync.fetch_watch_list('shows_watchlist')
			useNext = True
			if create_directory:
				self.sort(type='shows.watchlist') # sort before local pagination
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
				log_utils.log('traktWatchlist next url: %s' % next, 1)
			except: next = ''
			for i in range(len(self.list)): self.list[i]['next'] = next
			self.worker()
			if self.list is None: self.list = []
			if create_directory: self.tvshowDirectory(self.list, folderName=folderName)
			return self.list
		except:

			log_utils.error()

	def trakt_userList(self, url, create_directory=True, folderName=''):
		self.list = []
		q = dict(parse_qsl(urlsplit(url).query))
		index = int(q['page']) - 1
		def userList_totalItems(url):
			items = trakt.get_all_pages(url)
			if not items: return
			_cached = traktsync.cache_existing(trakt.syncTVShows)
			if _cached:
				watchedItems = [{'show': {'ids': e[0]}, 'seasons': []} for e in _cached]
			else:
				watchedItems = trakt.watchedShows()
			for item in items:
				try:
					values = {}
					values['added'] = item.get('listed_at', '')
					show = item['show']
					values['title'] = show.get('title')
					values['originaltitle'] = values['title']
					values['tvshowtitle'] = values['title']
					try: values['premiered'] = show.get('first_aired', '')[:10]
					except: values['premiered'] = ''
					values['year'] = str(show.get('year', '')) if show.get('year') else ''
					if not values['year']:
						try: values['year'] = str(values['premiered'][:4])
						except: values['year'] = ''
					ids = show.get('ids', {})
					values['imdb'] = str(ids.get('imdb', '')) if ids.get('imdb') else ''
					values['tmdb'] = str(ids.get('tmdb', '')) if ids.get('tmdb') else ''
					values['tvdb'] = str(ids.get('tvdb')) if ids.get('tvdb', '') else ''
					values['rating'] = show.get('rating')
					values['votes'] = show.get('votes')
					airs = show.get('airs', {})
					values['airday'] = airs['day']
					values['airtime'] = airs['time']
					values['airzone'] = airs['timezone']
					values['mediatype'] = 'tvshows'
					try:
						item_list = [item for item in watchedItems if item.get('show').get('title') == show.get('title')]
					except:
						item_list = None
					if item_list:
						try: values['lastplayed'] = item_list[0].get('last_watched_at') # for by date sorting
						except: values['lastplayed'] = ''
					self.list.append(values)
				except:

					log_utils.error()
			return self.list
		_force_fresh = control.homeWindow.getProperty('umbrella.trakt.userlist.modified') == 'true'
		if _force_fresh:
			control.homeWindow.clearProperty('umbrella.trakt.userlist.modified')
		self.list = cache.get(userList_totalItems, 0 if _force_fresh else self.traktuserlist_hours, url.split('?')[0] + '?extended=full')
		if not self.list: return
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
		if create_directory: self.tvshowDirectory(self.list, folderName=folderName)
		return self.list

	def mdb_list_items(self, url, create_directory=True, folderName=''):
		self.list = []
		q = dict(parse_qsl(urlsplit(url).query))
		index = int(q['page']) - 1
		def userList_totalItems(url):
			items = mdblist.getMDBItems(url)
			if not items: return
			for item in items:
				try:
					values = {}
					values['title'] = item.get('title', '')
					values['originaltitle'] = item.get('title', '')
					values['tvshowtitle'] = item.get('title', '')
					try: values['premiered'] = item['release_year']
					except: values['premiered'] = ''
					values['year'] = str(item.get('release_year', '')) if item.get('release_year') else ''
					values['imdb'] = str(item.get('imdb', '')) if item.get('imdb') else ''
					values['rank'] = item.get('rank')
					self.list.append(values)
				except:

					log_utils.error()
			return self.list
		self.list = userList_totalItems(url)
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
		if create_directory: self.tvshowDirectory(self.list, folderName=folderName)
		return self.list

	def mbd_user_lists(self, addremove):
		try:
			listType = 'show'
			items = mdblist.getMDBUserList(self, listType, addremove=addremove)
			next = ''
		except:

			log_utils.error()
		for item in items:
			try:
				list_name = item.get('params', {}).get('list_name', '')
				list_id = item.get('params', {}).get('list_id', '')
				list_owner = item.get('unique_ids', {}).get('user', '')
				list_count = item.get('params', {}).get('list_count', '')
				list_url = self.mbdlist_list_items % (list_id)
				label = '%s - (%s)' % (list_name, list_count)
				folderN = quote_plus(list_name)
				self.list.append({'name': label, 'url': list_url, 'list_owner': list_owner, 'list_name': list_name, 'list_id': list_id, 'context': list_url, 'next': next, 'image': 'mdblist.png', 'icon': 'mdblist.png','folderName': folderN, 'action': 'tvshows'})
			except:

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
			listType = 'tvshow'
			self.list = cache.get(mdblist.get_user_watchlist, 0, listType)
			if self.list is None: self.list = []
			self.worker()
			self.sort(type='shows.watchlist')
			next = ''
			if getSetting('mdblist.paginate.lists') == 'true' and self.list:
				paginated_ids = [self.list[x:x + int(self.page_limit)] for x in range(0, len(self.list), int(self.page_limit))]
				total_pages = len(paginated_ids)
				self.list = paginated_ids[index] if index < total_pages else []
				try:
					if index + 1 >= total_pages: raise Exception()
					next_page = index + 2
					next = 'plugin://plugin.video.umbrella/?action=mdbUserWatchListTVShows&url=%s&page=%s&folderName=%s' % (
						quote_plus('mdbwatchlist?limit=%s&page=%s' % (self.page_limit, next_page)),
						str(next_page), quote_plus(folderName))
				except: pass
			for i in range(len(self.list)): self.list[i]['next'] = next
			hasNext = bool(next)
			return self.tvshowDirectory(self.list, next=hasNext, folderName=folderName)
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
			listType = 'tvshow'
			self.list = cache.get(mdblist.get_user_collection, 0, listType)
			if self.list is None: self.list = []
			self.worker()
			self.sort(type='shows.watchlist')
			next = ''
			if getSetting('mdblist.paginate.lists') == 'true' and self.list:
				paginated_ids = [self.list[x:x + int(self.page_limit)] for x in range(0, len(self.list), int(self.page_limit))]
				total_pages = len(paginated_ids)
				self.list = paginated_ids[index] if index < total_pages else []
				try:
					if index + 1 >= total_pages: raise Exception()
					next_page = index + 2
					next = 'plugin://plugin.video.umbrella/?action=mdbUserCollectionTVShows&url=%s&page=%s&folderName=%s' % (
						quote_plus('mdbcollection?limit=%s&page=%s' % (self.page_limit, next_page)),
						str(next_page), quote_plus(folderName))
				except: pass
			for i in range(len(self.list)): self.list[i]['next'] = next
			hasNext = bool(next)
			return self.tvshowDirectory(self.list, next=hasNext, folderName=folderName)
		except:
			from resources.lib.modules import log_utils
			log_utils.error()
