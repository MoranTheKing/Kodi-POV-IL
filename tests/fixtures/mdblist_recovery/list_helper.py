"""Verbatim POV 6.10.01 fixtures; source SHA256 cb6e89b2e95a6521c86a570be9682c5f10e3c6f90879412df13ee4c5da99061b."""
class BaseListManager:
	setting_key = ''
	icon_file = ''
	heading_id = ''

	def __init__(self, params):
		self.params = params
		self.tmdb_id = params.get('tmdb_id')
		if self.tmdb_id: self.tmdb_id = int(self.tmdb_id)
		self.mediatype = params.get('mediatype')
		self.icon = media_path(self.icon_file)
		self.api = self._get_api()

	def _get_api(self):
		raise NotImplementedError

	def check_auth(self):
		return bool(get_setting(self.setting_key, ''))

	def get_custom_lists(self):
		return [], []

	def get_default_choices(self):
		return []

	def handle_special_action(self, choice_id, choice_name):
		return False

	def check_item_exists(self, choice_id):
		raise NotImplementedError

	def execute_toggle(self, choice, action_add):
		raise NotImplementedError

	def manage(self):
		if not self.check_auth(): return kodi_utils.no_results()
		heading = ls(self.heading_id).replace('[B]', '').replace('[/B]', '')
		list1, list2 = self.get_custom_lists()
		choices = list1 + self.get_default_choices() + list2
		if not choices: return
		list_items = [{'line1': item[1], 'line2': item[2], 'icon': item[3]} for item in choices]
		choice = kodi_utils.select_dialog([(i[0], i[1]) for i in choices], items=json.dumps(list_items), heading=heading)
		if choice is None: return
		special_result = self.handle_special_action(choice[0], choice[1])
		if special_result is not False: return special_result
		is_present = self.check_item_exists(choice[0])
		action_add = not is_present
		if not action_add:
			if not kodi_utils.confirm_dialog(text='Remove from %s?' % choice[1]): return
		return self.execute_toggle(choice, action_add)
