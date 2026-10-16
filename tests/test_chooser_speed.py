"""The subtitle chooser answers at once and does not search twice for nothing.

Measured in a user's video and log (Android streaming box): pressing
"בחירת כתוביות" showed 8 s of plain playback before the window, and 6.4 s of
that was a full provider search repeating the one that had found no subtitle
12 s earlier at the start of the episode.
"""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'service.subtitles.kodipovilai' / 'resources' / 'lib'


class _Window(object):
    props = {}

    def __init__(self, _id=10000):
        pass

    def setProperty(self, k, v):
        _Window.props[k] = v

    def getProperty(self, k):
        return _Window.props.get(k, '')


def _load_bridge():
    pkg = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    lib.__path__ = [str(LIB)]
    pkg.lib = lib
    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.log = lambda *a, **k: None
    ku.notify = lambda *a, **k: None
    ku.release_conflicts_with_episode = lambda *a, **k: False
    ku.addon = lambda: types.SimpleNamespace(getSetting=lambda s: 'false',
                                             getAddonInfo=lambda k: '')
    lib.kodi_utils = ku
    gui = types.ModuleType('xbmcgui')
    gui.Window = _Window
    mods = {'resources': pkg, 'resources.lib': lib, 'resources.lib.kodi_utils': ku,
            'xbmcgui': gui}
    with patch.dict(sys.modules, mods):
        spec = importlib.util.spec_from_file_location(
            'resources.lib.subs_engine_bridge', LIB / 'subs_engine_bridge.py')
        mod = importlib.util.module_from_spec(spec)
        sys.modules['resources.lib.subs_engine_bridge'] = mod
        spec.loader.exec_module(mod)
    return mod, mods


class EmptySearchTests(unittest.TestCase):
    INFO = {'imdb_id': 'tt35050741', 'season': '2', 'episode': '4',
            'picked_release': 'LOL.Last.One.Laughing.UK.S02E04.1080p.AMZN.WEB-DL-RAWR'}

    def setUp(self):
        _Window.props.clear()
        self.bridge, self.mods = _load_bridge()
        self.calls = []

    def _search(self, result):
        b = self.bridge

        def inner(info, modal_progress=True):
            self.calls.append(info)
            return list(result)
        with patch.dict(sys.modules, self.mods), \
                patch.object(b, 'enabled', return_value=True), \
                patch.object(b, '_search_inner', side_effect=inner), \
                patch.object(b, '_cache_get', return_value=None), \
                patch.object(b, '_cache_put'):
            return b.search(dict(self.INFO), modal_progress=False)

    def test_nothing_found_is_not_searched_again_right_away(self):
        self.assertEqual(self._search([]), [])
        self.assertEqual(self._search([]), [])
        self.assertEqual(len(self.calls), 1)

    def test_it_is_searched_again_after_a_few_minutes(self):
        self._search([])
        key = next(iter(_Window.props))
        _Window.props[key] = str(int(_Window.props[key]) - self.bridge._EMPTY_TTL - 1)
        self._search([])
        self.assertEqual(len(self.calls), 2)

    def test_a_search_that_found_subtitles_is_not_marked_empty(self):
        self._search([{'filename': 'x.srt'}])
        self.assertEqual(_Window.props, {})

    def test_without_a_release_name_nothing_is_remembered(self):
        self.INFO = {'imdb_id': 'tt35050741', 'season': '2', 'episode': '4',
                     'filepath': 'https://debrid.example/token'}
        self._search([])
        self._search([])
        self.assertEqual(len(self.calls), 2)


class ChooserFeedbackTests(unittest.TestCase):
    def test_the_press_pauses_and_shows_the_spinner_before_the_search(self):
        src = (LIB / 'subs_chooser.py').read_text(encoding='utf-8')
        show = src[src.index('def show():'):]
        self.assertLess(show.index('_pause_for_chooser()'), show.index('list_candidates('))
        self.assertLess(show.index('_busy(True)'), show.index('list_candidates('))
        # the spinner is closed in a finally, before any window or notice
        self.assertIn('finally:\n        _busy(False)', show.replace('\r\n', '\n'))


if __name__ == '__main__':
    unittest.main()
