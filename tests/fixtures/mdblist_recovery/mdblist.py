"""Verbatim POV 6.10.01 fixtures; source SHA256 17dc60b1aff372a2a34d7c5b18ddf5fbb4515c1e783d6f853a3fca4f9b6896e9."""
class MdbListManager(list_helper.BaseListManager):
	setting_key = 'mdblist_user'
	icon_file = 'mdblist.png'
	heading_id = 32200

	def _get_api(self):
		return mdblist_api

	def get_custom_lists(self):
		list1 = [
			(str(item['id']), item['name'], '%s items' % item['items'], self.icon)
			for item in self.api.mdbl_get_lists('my_lists') if not item['dynamic']
		]
		list2 = [('new', 'Create a new list', '', self.icon)]
		return list1, list2

	def get_default_choices(self):
		choices = [(i.lower(), i, '', self.icon) for i in (watchl_str, coll_str)]
		if self.mediatype == 'tvshow': choices.append(('dropped', 'Toggle Dropped', '', self.icon))
		return choices

	def handle_special_action(self, choice_id, choice_name):
		if 'new' in choice_id:
			kodi_utils.show_busy_dialog()
			try: self.api.make_new_mdbl_list(None)
			except: return kodi_utils.notify_error()
			finally: kodi_utils.hide_busy_dialog()
			return self.manage()
		if 'dropped' in choice_id:
			args = self.params['tmdb_id'], 'shows', self.params['imdb_id']
			return self.api.hide_unhide_mdbl_items(*args, 'dropped')
		return False

	def check_item_exists(self, choice_id):
		if any(x in choice_id for x in ('watchlist', 'collection')):
			list_items = self.api.mdbl_collection_watchlist_items(choice_id, self.mediatype)
		else: list_items = self.api.get_mdbl_list_contents('my_lists', choice_id)
		return self.tmdb_id in {i['id'] for i in list_items}

	def execute_toggle(self, choice, action_add):
		content = 'shows' if self.mediatype == 'tvshow' else 'movies'
		if 'collection' in choice[0]:
			data = {content: [{'ids': {'tmdb': self.tmdb_id}}]}
			return self.api.add_to_collection(data) if action_add else self.api.remove_from_collection(data)
		data = {content: [{'tmdb': self.tmdb_id}]}
		return self.api.add_to_list(choice[0], data) if action_add else self.api.remove_from_list(choice[0], data)
