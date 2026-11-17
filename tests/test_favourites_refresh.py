"""A favourite that is added or removed shows at once (field report, 17 Nov 2026; Onyx 1.0.14, Wizard 0.5.4).

The saved-list side (a removed title stayed in the list) is tested in test_pov_list_snapshot.py. This is the
other half: the home's rows of the viewer's own saved titles are asked again the moment one changes.
"""
import importlib.util
import re
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PATCHES = ROOT / 'plugin.program.kodipovilwizard/resources/libs/patches'
TOKEN = 'povil_t=$INFO[Window(home).Property(povil.lists.t)]'


class HomeRowsTests(unittest.TestCase):
    def test_the_four_personal_rows_carry_the_token_and_no_other_row_does(self):
        text = (ROOT / 'skin.povil.onyx/xml/Includes_POVIL_Home.xml').read_text('utf-8')
        paths = re.findall(r'<value condition="[^"]*">(plugin://plugin\.video\.pov/[^<]*)</value>', text)
        with_token = sorted(re.search(r'action=([a-z_]+)', p).group(1) for p in paths if TOKEN in p)
        self.assertEqual(with_token, ['favorites_movies', 'favorites_tvshows', 'mdblist_my_movies', 'mdblist_my_tvshows'])
        self.assertGreaterEqual(len(paths), 16, 'the other rows are reloaded by nothing new')
        self.assertNotIn('UpdateLibrary', text, 'the ping that reloads every row once crashed Kodi beside Container.Refresh')

    def test_the_rows_are_still_built_ahead_under_the_address_asked_at_start(self):
        """The token is empty when Kodi starts: the prebuilder reads the rows' address with it removed."""
        spec = importlib.util.spec_from_file_location('snapshot_under_test', PATCHES / 'pov_list_snapshot.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIn(module.LISTS_TOKEN, TOKEN)
        targets = module.skin_targets(str(ROOT / 'skin.povil.onyx'))
        saved = [t for t in targets if 'action=favorites_movies' in t and 'povil_t=' in t]
        self.assertEqual(len(saved), 1, saved)
        self.assertIn('&povil_t=&', saved[0])
        self.assertFalse([t for t in targets if '$' in t])

    def test_the_chips_and_tiles_open_the_plain_list(self):
        """A full list is refreshed by Container.Refresh; a token in its address would save it under a new name each time."""
        home = (ROOT / 'skin.povil.onyx/xml/Home.xml').read_text('utf-8')
        self.assertNotIn('povil.lists.t', home)


class ToggleHooksTests(unittest.TestCase):
    def test_povs_own_favourites_toggle_changes_the_token(self):
        spec = importlib.util.spec_from_file_location('patches_config_under_test', PATCHES / 'patches_config.py')
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {'xbmc': types.SimpleNamespace(), 'xbmcvfs': types.SimpleNamespace()}):
            spec.loader.exec_module(module)
        patches = next(value for value in vars(module).values()
                       if isinstance(value, list) and value and isinstance(value[0], dict) and 'hook' in value[0])
        patch = next(p for p in patches if p['id'] == 'wizard_fav_refresh_dialog')
        self.assertEqual(patch['marker'], '# WIZARD_FAV_REFRESH_DIALOG_v4', 'a new marker: devices re-apply the hook')
        self.assertIn("Window(10000).setProperty('povil.lists.t'", patch['hook'])
        self.assertIn("refresh = 'search' not in", patch['hook'], 'the search guard stays')
        self.assertNotIn('UpdateLibrary', patch['hook'])
        compile(patch['hook'].replace('\t', ''), 'hook', 'exec')

    def test_the_list_manager_toggle_changes_it_too_and_still_returns_the_result(self):
        properties = {}
        window = types.SimpleNamespace(setProperty=lambda key, value: properties.__setitem__(key, value))
        refreshed = []
        kodi_utils = types.SimpleNamespace(container_refresh=lambda: refreshed.append(1), notify_failed=lambda: None)
        xbmc = types.SimpleNamespace(getInfoLabel=lambda label: 'plugin://plugin.video.pov/?mode=build_movie_list',
                                     log=lambda *a, **k: None, LOGERROR=4)
        stubs = {'xbmc': xbmc, 'xbmcgui': types.SimpleNamespace(Window=lambda _id: window),
                 'modules': types.SimpleNamespace(kodi_utils=kodi_utils), 'modules.kodi_utils': kodi_utils}
        with mock.patch.dict(sys.modules, stubs):
            spec = importlib.util.spec_from_file_location('pov_fav_refresh_manage_under_test', PATCHES / 'pov_fav_refresh_manage.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            manager = types.SimpleNamespace(execute_toggle=lambda choice, add: ('toggled', choice, add))
            result = module.run({'self': manager, 'choice': 'watchlist', 'action_add': False})
        self.assertEqual(result, ('toggled', 'watchlist', False))
        self.assertGreater(float(properties.get('povil.lists.t', '0')), 1e9, 'finer than a second: two changes in one differ')
        self.assertEqual(refreshed, [1])


if __name__ == '__main__':
    unittest.main()
