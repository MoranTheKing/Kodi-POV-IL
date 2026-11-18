"""The viewer's option: a title whose last source was remembered plays it at once, in POV and in Umbrella
(Wizard 0.5.5, MoranSubs 0.3.94). Asked for through the owner, Nov 2026: "as a choice, not on by itself".
"""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
LIB = ROOT / 'service.subtitles.kodipovilai/resources/lib'


def remember(settings, folder):
    """The Wizard's pov_source_remember over a Kodi whose Wizard settings are the given dict."""
    xbmc = types.SimpleNamespace(LOGINFO=1, LOGWARNING=2, LOGERROR=3, log=lambda *a, **k: None)
    properties = {}
    xbmcgui = types.SimpleNamespace(Window=lambda _id: types.SimpleNamespace(
        setProperty=lambda key, value: properties.__setitem__(key, value)))
    xbmcaddon = types.SimpleNamespace(Addon=lambda _id=None: types.SimpleNamespace(
        getSetting=lambda key: settings.get(key, '') if _id == 'plugin.program.kodipovilwizard' else ''))
    xbmcvfs = types.SimpleNamespace(translatePath=lambda path: str(folder))
    with mock.patch.dict(sys.modules, {'xbmc': xbmc, 'xbmcgui': xbmcgui, 'xbmcaddon': xbmcaddon, 'xbmcvfs': xbmcvfs}):
        spec = importlib.util.spec_from_file_location('pov_source_remember_option_test',
                                                      WIZARD / 'resources/libs/patches/pov_source_remember.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    module.properties = properties
    return module


ON = {'pov_remember_source': 'true', 'pov_play_remembered': 'true'}
TORRENT = {'name': 'Film.2026.2160p.WEB', 'hash': 'ABCDEF0123', 'quality': '4K', 'provider': 'torrentio', 'debrid': 'TorBox',
           'source': 'torrent', 'size': 19.4}


class PovTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def source(self, **params):
        # as run_reorder() leaves POV's object when the remembered torrent itself is in the results
        return types.SimpleNamespace(params=params, tmdb_id=27205, media_type='movie', season='', episode='', meta={},
                                     _povil_same_release=True)

    def test_only_the_very_release_that_was_played_plays_without_the_list(self):
        module = remember(ON, self.folder)
        played = {'name': 'Film.2026.2160p.WEB', 'hash': 'ABCDEF0123', 'quality': '4K', 'scrape_provider': 'external'}
        chooser = types.SimpleNamespace(params={}, tmdb_id=27205, season='', episode='', meta={})
        module.run_capture(chooser, played, 'link')
        # the same torrent in the next search: first, and played
        again = types.SimpleNamespace(params={}, tmdb_id=27205, season='', episode='', meta={})
        results = [{'hash': 'ffff', 'quality': '1080p', 'scrape_provider': 'external'}, dict(played, hash='abcdef0123')]
        self.assertTrue(module.run_reorder(again, results))
        self.assertEqual(results[0]['hash'], 'abcdef0123')
        self.assertTrue(module.should_play(again))
        # only a source like it (same quality, same scraper, another torrent): first, and the list shows
        like = types.SimpleNamespace(params={}, tmdb_id=27205, season='', episode='', meta={})
        results = [{'hash': 'ffff', 'quality': '1080p', 'scrape_provider': 'external'},
                   {'hash': '9999', 'quality': '4K', 'scrape_provider': 'external'}]
        self.assertTrue(module.run_reorder(like, results))
        self.assertEqual(results[0]['hash'], '9999')
        self.assertFalse(module.should_play(like), 'another cut, dub or encode must not start unasked')
        self.assertFalse(module.should_play(types.SimpleNamespace(params={})), 'nothing was matched at all')

    def test_off_unless_the_viewer_chose_it(self):
        self.assertFalse(remember({'pov_remember_source': 'true'}, self.folder).should_play(self.source()))
        self.assertFalse(remember({'pov_remember_source': 'true', 'pov_play_remembered': 'false'}, self.folder).should_play(self.source()))
        self.assertTrue(remember(ON, self.folder).should_play(self.source()))
        settings = ET.parse(WIZARD / 'resources/settings.xml').getroot()
        option = next(s for s in settings.iter('setting') if s.get('id') == 'pov_play_remembered')
        self.assertEqual(option.get('default'), 'false')
        self.assertEqual(option.get('enable'), 'eq(-1,true)', 'it needs the memory it plays from')
        memory = next(s for s in settings.iter('setting') if s.get('id') == 'pov_remember_source')
        self.assertFalse(memory.get('label').isdigit(), 'a label a viewer can find (it was a bare string id)')

    def test_it_needs_the_memory_and_never_overrides_a_list_asked_for_by_name(self):
        self.assertFalse(remember({'pov_remember_source': 'false', 'pov_play_remembered': 'true'}, self.folder).should_play(self.source()))
        module = remember(ON, self.folder)
        # "change source" in the player and POV's own "select source" pass autoplay=false
        self.assertFalse(module.should_play(self.source(autoplay='false')))
        self.assertFalse(module.should_play(self.source(autoplay='true')), 'POV\'s own autoplay decides for itself')
        self.assertFalse(module.should_play(object()) is None)

    def test_povs_hook_plays_the_remembered_source_which_run_reorder_put_first(self):
        spec = importlib.util.spec_from_file_location('patches_config_option_test', WIZARD / 'resources/libs/patches/patches_config.py')
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {'xbmc': types.SimpleNamespace(), 'xbmcvfs': types.SimpleNamespace()}):
            spec.loader.exec_module(module)
        patches = next(v for v in vars(module).values() if isinstance(v, list) and v and isinstance(v[0], dict) and 'hook' in v[0])
        patch = next(p for p in patches if p['id'] == 'pov_reorder_sources')
        self.assertEqual(patch['marker'], '# WIZARD_POV_REORDER_SOURCES_v4')
        self.assertIn("if pov_source_remember.run_reorder(self, results) and getattr(pov_source_remember, 'should_play', "
                      "lambda _s: False)(self): return self.play_file(results, results[0])", patch['hook'])
        # POV keeps the hook when the Wizard beside it is an older one: the list must still open (QA, Nov 2026)
        scope = {}
        exec('def display_results(self, results):' + chr(10) + patch['hook'] + chr(9) + 'return "list"' + chr(10), scope)
        old_wizard = types.ModuleType('pov_source_remember')
        old_wizard.run_reorder = lambda source, results: True
        with mock.patch.dict(sys.modules, {'pov_source_remember': old_wizard,
                                           'xbmcvfs': types.SimpleNamespace(translatePath=lambda path: path)}):
            self.assertEqual(scope['display_results'](object(), [1]), 'list')
            old_wizard.should_play = lambda source: True
            player = types.SimpleNamespace(play_file=lambda results, source: ('played', source))
            self.assertEqual(scope['display_results'](player, ['first', 'second']), ('played', 'first'))
        compile('def display_results(self, results):\n' + patch['hook'], 'hook', 'exec')


class UmbrellaTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def test_one_memory_serves_both_add_ons(self):
        module = remember(ON, self.folder)
        film = types.SimpleNamespace(tmdb_id=27205, media_type='movie', season='', episode='', meta={})
        episode = types.SimpleNamespace(tmdb_id=1399, season=1, episode=9, meta={})  # POV at capture: no media_type
        self.assertEqual(module._umbrella_key({'tmdb': '27205', 'season': None, 'episode': None}), module._key(film))
        self.assertEqual(module._umbrella_key({'tmdb': 1399, 'season': '1', 'episode': '9'}), module._key(episode))
        for ids in ({}, {'tmdb': ''}, {'tmdb': 'None'}, {'tmdb': '0'}, None):
            self.assertIsNone(module._umbrella_key(ids))

    def test_the_source_that_played_is_remembered_and_picked_next_time(self):
        module = remember(ON, self.folder)
        ids = {'tmdb': '27205', 'season': None, 'episode': None}
        self.assertTrue(module.umbrella_capture(ids, TORRENT))
        kept = json.loads((self.folder / 'movie_27205_s0_e0.json').read_text('utf-8'))
        self.assertEqual((kept['hash'], kept['quality'], kept['provider'], kept['debrid']), ('ABCDEF0123', '4K', 'torrentio', 'TorBox'))
        other = dict(TORRENT, name='Film.2026.1080p', hash='ffff', quality='1080p')
        same = dict(TORRENT, hash='abcdef0123')           # the same torrent, as the next scrape spells it
        self.assertEqual(module.umbrella_pick(ids, [other, same]), [same])
        # the same quality from the same scraper under another hash may be another cut, dub or encode:
        # nothing plays unasked, the list opens
        cousin = dict(TORRENT, hash='9999')
        self.assertIsNone(module.umbrella_pick(ids, [other, cousin]))
        self.assertIsNone(module.umbrella_pick(ids, [other]), 'not in this scrape: the list')
        self.assertIsNone(module.umbrella_pick({'tmdb': '1'}, [same]), 'another title')

    def test_an_uncached_source_is_neither_remembered_nor_picked(self):
        module = remember(ON, self.folder)
        ids = {'tmdb': '27205'}
        uncached = dict(TORRENT, source='uncached torrent')
        self.assertFalse(module.umbrella_capture(ids, uncached))
        module.umbrella_capture(ids, TORRENT)
        self.assertIsNone(module.umbrella_pick(ids, [uncached]))
        self.assertIsNone(module.umbrella_pick(ids, [dict(TORRENT, cloud_folder=True)]))

    def test_nothing_is_picked_while_the_option_is_off(self):
        remember(ON, self.folder).umbrella_capture({'tmdb': '27205'}, TORRENT)
        for settings in ({'pov_remember_source': 'true'}, {'pov_remember_source': 'false', 'pov_play_remembered': 'true'}):
            self.assertIsNone(remember(settings, self.folder).umbrella_pick({'tmdb': '27205'}, [TORRENT]))
        self.assertFalse(remember({'pov_remember_source': 'false'}, self.folder / 'x').umbrella_capture({'tmdb': '2'}, TORRENT))

    def test_what_plays_is_named_for_the_subtitle_matcher(self):
        module = remember(ON, self.folder)
        module.umbrella_published(TORRENT, 'https://example.invalid/file.mkv')
        self.assertEqual(module.properties['pov_picked_source_name'], 'Film.2026.2160p.WEB')
        self.assertEqual(module.properties['subs.player_filename'], 'Film.2026.2160p.WEB')


# The two places MoranSubs' patcher touches in Umbrella's sources.py, as Umbrella 6.8.02 writes them
SOURCES = (
    "class Sources:\n"
    "\tdef play(self, title, year, imdb, tmdb, tvdb, season, episode, tvshowtitle, premiered, meta, select, rescrape=None):\n"
    "\t\ttry:\n"
    "\t\t\tforce_selection = select == '0' or rescrape == 'true'\n"
    "\t\t\titems = self.getSources()\n"
    "\t\t\tif len(items) > 0:\n"
    "\t\t\t\tpreference = None\n"
    "\t\t\t\turl = None\n"
    "\t\t\t\tif (preference and not url) or (not preference and select == '0'):\n"
    "\t\t\t\t\treturn self.sourceSelect(title, items, [], self.meta)\n"
    "\t\t\t\telif not preference: url = self.sourcesAutoPlay(items)\n"
    "\t\texcept: pass\n"
    "\n"
    "\tdef playItem(self, title, items, chosen_source, meta):\n"
    "\t\ttry:\n"
    "\t\t\tresolve_items = items\n"
    "\t\t\tfor i in range(len(resolve_items)):\n"
    "\t\t\t\ttry:\n"
    "\t\t\t\t\tself.url = self.resolve(resolve_items[i])\n"
    "\t\t\t\t\tif not self.url: continue\n"
    "\t\t\t\t\tbreak\n"
    "\t\t\t\texcept: pass\n"
    "\t\texcept: pass\n")
OLD_BLOCK = (
    "\t\t\t\t\t# AI_SUBS_UMBRELLA_SOURCE_NAME_v1 -- publish the picked release name for the subtitle matcher\n"
    "\t\t\t\t\ttry:\n"
    "\t\t\t\t\t\timport xbmcgui as _ai_g\n"
    "\t\t\t\t\texcept Exception: pass\n")


class UmbrellaPatcherTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'sources.py'
        ku = types.SimpleNamespace(log=lambda *a, **k: None, get_setting=lambda key, default='': default,
                                   set_setting=lambda key, value: None)
        package = types.ModuleType('resources.lib')
        package.kodi_utils = ku
        stubs = {'resources': types.ModuleType('resources'), 'resources.lib': package, 'resources.lib.kodi_utils': ku,
                 'resources.lib.addon_settings_safe': types.SimpleNamespace(), 'resources.lib.addon_presence': types.SimpleNamespace(),
                 'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)}
        package.addon_settings_safe, package.addon_presence = stubs['resources.lib.addon_settings_safe'], stubs['resources.lib.addon_presence']
        patcher = mock.patch.dict(sys.modules, stubs)
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location('umbrella_setup_patcher_option_test', LIB / 'umbrella_setup_patcher.py')
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.mod._sources_path = lambda: str(self.path)

    def write(self, text):
        with open(self.path, 'w', encoding='utf-8', newline='') as target:
            target.write(text)

    def read(self):
        with open(self.path, 'r', encoding='utf-8', newline='') as source:
            return source.read()

    def test_a_device_with_the_old_block_gets_the_capture_and_the_option(self):
        self.write(SOURCES.replace("\t\t\t\t\tif not self.url: continue\n", "\t\t\t\t\tif not self.url: continue\n" + OLD_BLOCK))
        self.assertEqual(self.mod.ensure_source_name_published(), 'patched')
        text = self.read()
        self.assertNotIn('AI_SUBS_UMBRELLA_SOURCE_NAME_v1', text)
        self.assertEqual(text.count(self.mod.MARKER), 1)
        self.assertEqual(text.count(self.mod.PICK_MARKER), 1)
        self.assertIn('_ai_m.umbrella_capture(meta, resolve_items[i])', text)
        # the option's block stands right before the line that chooses between the list and autoplay
        self.assertLess(text.index(self.mod.PICK_MARKER), text.index("if (preference and not url) or (not preference and select == '0'):"))
        self.assertIn("if not preference and not force_selection and select == '0':", text)
        self.assertIn("url, preference = _ai_u, {'povil_remembered': True}", text)
        compile(text, 'sources.py', 'exec')
        self.assertEqual(self.mod.ensure_source_name_published(), 'unchanged')
        self.assertEqual(self.read(), text)

    def test_line_endings_are_kept(self):
        self.write(SOURCES.replace('\n', '\r\n'))
        self.assertEqual(self.mod.ensure_source_name_published(), 'patched')
        text = self.read()
        self.assertEqual(text.count('\n'), text.count('\r\n'))
        self.assertEqual(text.count(self.mod.PICK_MARKER), 1)

    def test_an_umbrella_without_the_deciding_line_keeps_the_name_block_and_is_not_rewritten_at_every_start(self):
        self.write(SOURCES.replace("if (preference and not url) or (not preference and select == '0'):", 'if choose_list(preference, url, select):'))
        self.assertEqual(self.mod.ensure_source_name_published(), 'patched')
        text = self.read()
        self.assertEqual(text.count(self.mod.MARKER), 1)
        self.assertNotIn(self.mod.PICK_MARKER, text)
        compile(text, 'sources.py', 'exec')
        self.assertEqual(self.mod.ensure_source_name_published(), 'unchanged')
        self.assertEqual(self.read(), text)


if __name__ == '__main__':
    unittest.main()
