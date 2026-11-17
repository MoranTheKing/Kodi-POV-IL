"""Arctic Fuse 3 3.5 moved search to SkinVariables' multisearch (MoranSubs 0.3.93)."""

import importlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MORANSUBS = ROOT / 'service.subtitles.kodipovilai'
AF3 = 'skin.arctic.fuse.3'
STOCK_TABLE = {
    'DefaultSearch-Movies': 'videodb://movies/titles/?xsp={query}',
    'DefaultSearch-TMDBMovies': 'plugin://plugin.video.themoviedb.helper?info=search&query={query_double}',
}
STOCK_1105 = ('<window type="window" id="1105">\n    <onload>Action(Back)</onload>\n'
              '    <onload>RunScript(script.skinvariables,run_multisearch,tmdbhelper_container)</onload>\n</window>\n')
STOCK_INCLUDES = ('<includes>\n    <label>$LOCALIZE[31851]: $VAR[MultiSearch_Sources_Label] ⌄</label>\n'
                  '    <label>$LOCALIZE[31852]: $VAR[MultiSearch_Decade_Label] ⌄</label>\n</includes>\n')


def host_audit():
    spec = importlib.util.spec_from_file_location('host_audit_for_af3', ROOT / '.github/scripts/moransubs_host_audit.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Af3MultisearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home, self.profile = Path(self.tmp.name) / 'home', Path(self.tmp.name) / 'profile'
        self.skin = self.home / 'addons' / AF3
        (self.skin / 'shortcuts').mkdir(parents=True)
        (self.skin / '1080i').mkdir()
        (self.profile / 'addon_data').mkdir(parents=True)
        (self.skin / 'addon.xml').write_text('<addon id="%s" version="3.5.4"/>' % AF3, 'utf-8')
        self.table = self.skin / 'shortcuts' / 'skinvariables-multisearch-paths.json'
        self.table.write_text(json.dumps(STOCK_TABLE, indent=4) + '\n', 'utf-8')
        (self.skin / '1080i' / 'Custom_1105_Search.xml').write_text(STOCK_1105, 'utf-8')
        self.includes = self.skin / '1080i' / 'Includes_Search.xml'
        self.includes.write_text(STOCK_INCLUDES, 'utf-8')
        saved = {name: sys.modules.get(name) for name in ('xbmc', 'xbmcvfs', 'xbmcaddon', 'xbmcgui')}
        self.addCleanup(lambda: [sys.modules.pop(n, None) if m is None else sys.modules.__setitem__(n, m)
                                 for n, m in saved.items()])
        host_audit().stub_kodi(self.home, self.profile, AF3)
        self.builtins = []
        sys.modules['xbmc'].executebuiltin = lambda *args, **kwargs: self.builtins.append(args[0])
        sys.path.insert(0, str(MORANSUBS))
        self.addCleanup(lambda: sys.path.remove(str(MORANSUBS)))
        # this test's own copies of the add-on's modules; what other tests imported goes back afterwards
        held = dict((n, m) for n, m in sys.modules.items() if n == 'resources' or n.startswith('resources.'))
        for name in held:
            del sys.modules[name]

        def restore():
            for name in [n for n in sys.modules if n == 'resources' or n.startswith('resources.')]:
                del sys.modules[name]
            sys.modules.update(held)
        self.addCleanup(restore)
        self.search = importlib.import_module('resources.lib.af3_search_pov_patcher')
        self.discover = importlib.import_module('resources.lib.af3_discover_pov_patcher')

    def test_the_build_tokens_join_the_multisearch_table_once(self):
        self.assertEqual(self.search.ensure_patched(), 'patched')
        table = json.loads(self.table.read_text('utf-8'))
        self.assertEqual(table['DefaultSearch-POVMovies'],
                         'plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_movies_search&query={query}')
        self.assertEqual(table['DefaultSearch-POVTv'],
                         'plugin://plugin.video.pov/?mode=build_tvshow_list&action=tmdb_tv_search&query={query}')
        self.assertIn('DefaultSearch-POVPeople', table)
        self.assertIn('DefaultSearch-POVCollections', table)
        for token, value in STOCK_TABLE.items():
            self.assertEqual(table[token], value, 'the skin\'s own entries are kept')
        self.assertNotIn('&amp;', self.table.read_text('utf-8'))
        self.assertEqual(self.search.ensure_patched(), 'already_patched')

    def test_another_search_add_on_rewrites_the_tokens(self):
        self.assertEqual(self.search.ensure_patched(), 'patched')
        umbrella = ('umbrella', {'Movies': 'plugin://plugin.video.umbrella/?action=movieSearchterm&amp;amp;name='})
        with patch.object(self.search, '_provider_and_prefixes', return_value=umbrella):
            self.assertEqual(self.search.ensure_patched(), 'patched')
            self.assertEqual(self.search.ensure_patched(), 'already_patched')
        self.assertEqual(json.loads(self.table.read_text('utf-8'))['DefaultSearch-POVMovies'],
                         'plugin://plugin.video.umbrella/?action=movieSearchterm&name={query}')

    def test_the_arrow_the_hebrew_font_lacks_leaves_the_labels(self):
        self.assertEqual(self.search.ensure_patched(), 'patched')
        text = self.includes.read_text('utf-8')
        self.assertNotIn('⌄', text)
        self.assertIn('$VAR[MultiSearch_Sources_Label]</label>', text)
        self.assertEqual(self.search.ensure_patched(), 'already_patched')

    def test_a_table_of_another_shape_is_left_alone(self):
        self.table.write_text('["not", "a", "table"]', 'utf-8')
        self.assertEqual(self.search.ensure_patched(), 'unmatched')
        self.assertEqual(self.table.read_text('utf-8'), '["not", "a", "table"]')

    def test_the_old_layout_still_goes_through_search_path_xml(self):
        # 3.4.x: search_path.xml exists; the multisearch branch must not take over
        setup = self.skin / 'shortcuts' / 'generator' / 'data' / 'setup'
        setup.mkdir(parents=True)
        (setup / 'search_path.xml').write_text('<rules/>', 'utf-8')
        self.assertEqual(self.search.ensure_patched(), 'unmatched')
        self.assertNotIn('DefaultSearch-POVMovies', self.table.read_text('utf-8'))

    def test_the_discover_grid_patcher_stands_down_and_turns_tmdb_discover_off_once(self):
        self.assertEqual(self.discover.ensure_patched(), 'upstream')
        self.assertEqual(self.builtins, ['Skin.SetBool(HomeSwitcher.Search.DisableDiscover)'])
        self.assertEqual(self.discover.ensure_patched(), 'upstream')
        self.assertEqual(len(self.builtins), 1, 'a user who turns discover back on keeps it')
        self.assertEqual((self.skin / '1080i' / 'Custom_1105_Search.xml').read_text('utf-8'), STOCK_1105)

    def test_another_running_skin_is_not_given_the_setting(self):
        sys.modules['xbmc'].getSkinDir = lambda: 'skin.estuary'
        self.assertEqual(self.discover.ensure_patched(), 'upstream')
        self.assertEqual(self.builtins, [])


if __name__ == '__main__':
    unittest.main()
