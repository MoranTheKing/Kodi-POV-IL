"""The subtitle chooser answers at once and does not search twice.

Measured in two user logs and a video from an Android streaming box:
pressing "בחירת כתוביות" re-ran every subtitle provider each time (6.4 s,
then 4.5 s per press) right after the automatic search, and importing SubSync
for a rank that had nothing to reorder cost another 1.9 s. Pausing the video
with a busy spinner while waiting (0.3.33) was worse for the user: the video
stood still for the whole wait, and his "Unpause Jumpback" add-on rewinds 4 s
on every resume.
"""

import importlib.util
import json
import sys
import types
import unittest
import urllib.parse
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

    def clearProperty(self, k):
        _Window.props.pop(k, None)


def _load(name):
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
            'resources.lib.' + name, LIB / (name + '.py'))
        mod = importlib.util.module_from_spec(spec)
        sys.modules['resources.lib.' + name] = mod
        spec.loader.exec_module(mod)
    return mod, mods


class RecentSearchTests(unittest.TestCase):
    INFO = {'imdb_id': 'tt35050741', 'season': '2', 'episode': '5',
            'picked_release': 'LOL.Last.One.Laughing.UK.S02E05.1080p.AMZN.WEB-DL-RAWR'}

    def setUp(self):
        _Window.props.clear()
        self.bridge, self.mods = _load('subs_engine_bridge')
        self.calls = []

    def _search(self, result, finished=True, modal_progress=False, info=None):
        b = self.bridge

        def inner(info, modal_progress=True):
            self.calls.append(info)
            return list(result)
        with patch.dict(sys.modules, self.mods), \
                patch.object(b, 'enabled', return_value=True), \
                patch.object(b, '_search_inner', side_effect=inner), \
                patch.object(b, '_search_finished', return_value=finished), \
                patch.object(b, '_cache_get', return_value=None), \
                patch.object(b, '_cache_put'):
            return b.search(dict(info or self.INFO), modal_progress=modal_progress)

    def test_a_finished_empty_search_is_reused(self):
        self.assertEqual(self._search([]), [])
        self.assertEqual(self._search([]), [])
        self.assertEqual(len(self.calls), 1)

    def test_found_subtitles_are_reused_also_without_a_release_name(self):
        # a debrid URL is no release name: the 24 h disk cache is skipped
        info = {'imdb_id': 'tt35050741', 'season': '2', 'episode': '5',
                'filepath': 'https://debrid.example/token'}
        rows = [{'filename': 'x.srt', 'link': 'l'}]
        self.assertEqual(self._search(rows, info=info), rows)
        self.assertEqual(self._search([], info=info), rows)
        self.assertEqual(len(self.calls), 1)

    def test_a_search_cut_short_is_searched_again(self):
        self._search([], finished=False)
        self._search([])
        self.assertEqual(len(self.calls), 2)

    def test_kodis_own_dialog_always_searches(self):
        self._search([])
        self._search([], modal_progress=True)
        self.assertEqual(len(self.calls), 2)

    def test_it_is_searched_again_after_two_minutes(self):
        self._search([])
        rows = json.loads(_Window.props[self.bridge._RECENT_PROP])
        rows[-1]['t'] -= self.bridge._RECENT_TTL + 1
        _Window.props[self.bridge._RECENT_PROP] = json.dumps(rows)
        self._search([])
        self.assertEqual(len(self.calls), 2)

    def test_another_release_is_searched_again(self):
        self._search([])
        other = dict(self.INFO, picked_release='LOL.Last.One.Laughing.UK.S02E05.720p.WEB-OTHER')
        self._search([], info=other)
        self.assertEqual(len(self.calls), 2)

    def test_another_source_url_is_searched_again(self):
        a = {'imdb_id': 'tt35050741', 'season': '2', 'episode': '5',
             'filepath': 'https://debrid.example/AAA/LOL.S02E05.1080p.AMZN.WEB-DL-RAWR.mkv'}
        b = dict(a, filepath='https://debrid.example/BBB/LOL.S02E05.720p.HDTV-OTHER.mkv')
        self._search([], info=a)
        self._search([], info=a)
        self._search([], info=b)
        self.assertEqual(len(self.calls), 2)

    def test_one_property_keeps_only_the_last_few_titles(self):
        for ep in range(1, 7):
            self._search([], info=dict(self.INFO, episode=str(ep),
                                       picked_release='LOL.S02E0%d.1080p-RAWR' % ep))
        self.assertEqual(list(_Window.props), [self.bridge._RECENT_PROP])
        self.assertEqual(len(json.loads(_Window.props[self.bridge._RECENT_PROP])),
                         self.bridge._RECENT_KEEP)
        self.assertNotIn('debrid', _Window.props[self.bridge._RECENT_PROP])

    def test_finished_is_this_threads_last_engine_search(self):
        b = self.bridge
        b._SEARCH_STATE.finished = True
        self.assertTrue(b._search_finished())
        b._SEARCH_STATE.finished = False
        self.assertFalse(b._search_finished())
        src = (LIB / 'subs_engine_bridge.py').read_text(encoding='utf-8').replace('\r\n', '\n')
        inner = src[src.index('def _search_inner('):]
        locked = inner[inner.index('with _ENGINE_SEARCH_LOCK:'):]
        # reset and read under the lock, around the engine call
        self.assertLess(locked.index('engine.last_search_cut_short = False'),
                        locked.index('engine.get_subtitles(video_data)'))
        self.assertLess(locked.index('engine.get_subtitles(video_data)'),
                        locked.index('_SEARCH_STATE.finished = not ('))

    def test_the_engine_marks_a_timeout_and_a_refusal(self):
        src = (LIB / 'subs_engine' / 'engine.py').read_text(encoding='utf-8')
        body = src[src.index('def c_get_subtitles('):].replace('\r\n', '\n')
        self.assertIn('global last_search_cut_short', body)
        refuse = body[body.index('if not _provider_workers_ready():'):]
        self.assertLess(refuse.index('last_search_cut_short = True'), refuse.index('return []'))
        timeout = body[body.index('elapsed_time>ExcludeTime'):]
        self.assertLess(timeout.index('last_search_cut_short = True'), timeout.index('break\n'))


def _row(lang, payload, filename='x.srt'):
    return {'language': lang, 'filename': filename,
            'link': urllib.parse.quote(json.dumps(payload))}


class ChooserTests(unittest.TestCase):
    def setUp(self):
        self.ch, _mods = _load('subs_chooser')

    def test_no_pause_before_the_list_and_a_pause_at_the_window(self):
        src = (LIB / 'subs_chooser.py').read_text(encoding='utf-8').replace('\r\n', '\n')
        show = src[src.index('def show():'):]
        listed = show.index('list_candidates(')
        self.assertLess(show.index('_searching_notice()'), listed)
        self.assertNotIn('_pause_for_chooser()', show[:listed])
        self.assertLess(show.index('_paused = _pause_for_chooser()'), show.index('w.doModal()'))
        self.assertIn('finally:\n        _close_notice(_notice)', show)

    def test_a_second_press_while_one_is_open_is_ignored(self):
        import time as _t
        calls = []
        _Window.props[self.ch._BUSY_PROP] = str(_t.time())
        with patch.object(self.ch, '_show', side_effect=lambda: calls.append(1) or True), \
                patch.object(self.ch, 'xbmcgui', types.SimpleNamespace(Window=_Window)), \
                patch.object(self.ch, 'xbmc', types.SimpleNamespace()):
            self.assertTrue(self.ch.show())
            self.assertEqual(calls, [])
            _Window.props[self.ch._BUSY_PROP] = str(_t.time() - 120)   # a dead process
            self.assertTrue(self.ch.show())
            self.assertEqual(calls, [1])
            self.assertEqual(_Window.props.get(self.ch._BUSY_PROP, ''), '')

    def test_the_rank_gate_counts_human_hebrew_rows(self):
        ai = _row('he', {'type': 'embedded_ai'})
        emb = _row('en', {'type': 'engine', 'embedded': True, 'language': 'English'})
        human = _row('he', {'type': 'engine', 'language': 'Hebrew'})
        mt = _row('he', {'type': 'engine', 'language': 'HebrewMachineTranslated'})
        ktuvit = _row('he', {'type': 'pool', 'pool_kind': 'ktuvit'})
        self.assertEqual(self.ch._human_hebrew_rows([ai, ai, emb, mt]), 0)
        self.assertEqual(self.ch._human_hebrew_rows([human, ktuvit, ai]), 2)

    def test_the_current_row_stays_first_without_the_rank(self):
        a = {'filename': 'a.srt'}
        cur = {'filename': '» נוכחית · b.srt'}
        self.assertEqual(self.ch._current_first([a, cur]), [cur, a])
        self.assertEqual(self.ch._current_first([a]), [a])


if __name__ == '__main__':
    unittest.main()
