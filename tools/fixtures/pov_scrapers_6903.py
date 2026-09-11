# GPL-3.0-or-later. Verbatim POV 6903 methods; surrounding class is a test fixture.
class Fixture:
	def activate_internal(self, prescrape=False):
		self.prepare_internal(prescrape)
		append = self.source.prescrape_scrapers.append if prescrape else self.source.providers.append
		source_path = kodi_utils.translate_path(kodi_utils.internal_path)
		for loader, module_name, is_pkg in pkgutil.iter_modules([source_path]):
			if is_pkg: continue
			if module_name not in self.source.active_internal_scrapers: continue
			if prescrape and not check_prescrape_sources(module_name, self.source.mediatype): continue
			try: module_source = importlib.import_module('.' + module_name, package='debrids').source
			except Exception as e: kodi_utils.logger('POV', 'Error: Loading module: "%s": %s' % (module_name, e))
			else: append(('internal', module_source, module_name))

	def get_provider_rank(self, account_type):
		return self.source.provider_sort_ranks[account_type] or 11

	def activate_external(self):
		pass
