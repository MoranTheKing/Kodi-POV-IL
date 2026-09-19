"""An external Hebrew subtitle must never become a fake embedded 101% row.

The field failure is a real race: the play-start poll first completed with zero
embedded streams, MoranSubs appended an external Hebrew file, and a parallel
poller then saw ``['heb']`` and overwrote the empty baseline.  This executes the
real snapshot code with that exact ordering.  The pre-fix implementation either
rejects ``final=True`` or overwrites the baseline, so this cannot pass without
the production fix.
"""

import ast
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'addons/service.subtitles.kodipovilai/resources/lib'


class EmbeddedSnapshotSeal(unittest.TestCase):
    def setUp(self):
        self.props = {}
        self.streams = []
        self.reports = []
        self.url = 'https://media.invalid/shared.mkv?token=x'

        xbmc = types.ModuleType('xbmc')
        owner = self

        class Player:
            def isPlayingVideo(self):
                return True

            def getPlayingFile(self):
                return owner.url

            def getAvailableSubtitleStreams(self):
                return list(owner.streams)

        xbmc.Player = Player
        xbmc.sleep = lambda _ms: None
        xbmcgui = types.ModuleType('xbmcgui')
        props = self.props
        xbmcgui.Window = lambda _wid: types.SimpleNamespace(
            getProperty=lambda key: props.get(key, ''),
            setProperty=lambda key, value: props.__setitem__(key, value),
            clearProperty=lambda key: props.pop(key, None))

        resources = types.ModuleType('resources')
        resources.__path__ = [str(LIB.parent)]
        resources_lib = types.ModuleType('resources.lib')
        resources_lib.__path__ = [str(LIB)]
        ku = types.ModuleType('resources.lib.kodi_utils')
        ku.log = lambda *args, **kwargs: None
        ku.get_bool = lambda _key, _default=False: True
        resources.lib = resources_lib
        resources_lib.kodi_utils = ku

        self.mods = patch.dict(sys.modules, {
            'xbmc': xbmc, 'xbmcgui': xbmcgui,
            'resources': resources, 'resources.lib': resources_lib,
            'resources.lib.kodi_utils': ku,
        })
        self.mods.start()
        self.addCleanup(self.mods.stop)
        spec = importlib.util.spec_from_file_location(
            'resources.lib.subs_engine_bridge_snapshot_test',
            LIB / 'subs_engine_bridge.py')
        self.bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.bridge)

    def snapshot(self):
        return json.loads(self.props[self.bridge._SNAP_PROP])

    def test_completed_empty_baseline_cannot_be_overwritten_by_external_hebrew(self):
        info = {'title': 'The Flash'}
        self.bridge.note_playback_streams(info, [], final=True)
        first = self.snapshot()
        self.assertEqual(first['streams'], [])
        self.assertTrue(first['sealed'])
        self.assertTrue(self.bridge.have_playback_snapshot(info))

        # Kodi now appends MoranSubs's own external file.  A late onAVStarted
        # poller must not reinterpret it as media-container metadata.
        self.streams[:] = ['heb']
        self.bridge.note_playback_streams(info, ['heb'], final=True)
        self.assertEqual(self.snapshot()['streams'], [])
        self.assertEqual(self.bridge.embedded_candidates(info), [])

    def test_delivery_seal_freezes_the_pre_external_stream_list(self):
        info = {'title': 'The Flash'}
        self.assertTrue(self.bridge.seal_playback_streams(info))
        self.streams[:] = ['heb']
        self.bridge.note_playback_streams(info, ['heb'], final=True)
        self.assertEqual(self.snapshot()['streams'], [])
        self.assertTrue(self.snapshot()['sealed'])

    def test_recycled_endpoint_cannot_reuse_another_titles_snapshot(self):
        first = {'title': 'First', 'tmdb_id': '100'}
        second = {'title': 'Second', 'tmdb_id': '200'}
        self.bridge.note_playback_streams(first, ['eng'], final=True)
        first_snapshot = self.snapshot()
        self.assertTrue(self.bridge.have_playback_snapshot(first))
        self.assertFalse(self.bridge.have_playback_snapshot(second))

        # The transport URL is deliberately unchanged. A new media identity
        # must replace the old baseline instead of inheriting its stream index.
        self.bridge.note_playback_streams(second, ['heb'], final=True)
        second_snapshot = self.snapshot()
        self.assertNotEqual(first_snapshot['media'], second_snapshot['media'])
        self.assertEqual(second_snapshot['streams'], ['heb'])
        self.assertTrue(self.bridge.have_playback_snapshot(second))
        self.assertFalse(self.bridge.have_playback_snapshot(first))
        self.assertNotIn('token=x', second_snapshot['key'])

    def test_late_episode_metadata_enriches_the_same_snapshot(self):
        early = {'title': 'The Flash', 'tmdb_id': '60735'}
        settled = dict(early, season='1', episode='6')
        self.bridge.note_playback_streams(early, ['eng'], final=True)
        self.assertTrue(self.bridge.have_playback_snapshot(settled))
        self.bridge.note_playback_streams(settled, ['heb'], final=True)
        snap = self.snapshot()
        self.assertEqual(snap['streams'], ['eng'])
        self.assertEqual(snap['media']['season'], '1')
        self.assertEqual(snap['media']['episode'], '6')

    def test_unknown_new_metadata_never_consumes_a_recycled_snapshot(self):
        old = {'title': 'First', 'tmdb_id': '100',
               'filepath': self.url}
        new_early = {'filepath': self.url}
        self.bridge.note_playback_streams(old, ['eng'], final=True)
        self.assertFalse(self.bridge.have_playback_snapshot(new_early))
        self.assertEqual(self.bridge.embedded_candidates(new_early), [])

        # A writer keeps the sealed old baseline intact until the new title can
        # identify itself; crucially, no consumer is allowed to expose it.
        self.bridge.note_playback_streams(new_early, ['heb'], final=True)
        self.assertEqual(self.snapshot()['streams'], ['eng'])
        self.assertFalse(self.bridge.have_playback_snapshot(new_early))

    def test_auto_advance_waits_for_new_episode_numbers(self):
        old = {'title': 'The Flash', 'tvshow': 'The Flash',
               'tmdb_id': '60735', 'season': '1', 'episode': '6',
               'filepath': self.url}
        next_early = {'title': 'The Flash', 'tvshow': 'The Flash',
                      'tmdb_id': '60735', 'filepath': self.url}
        next_settled = dict(next_early, season='1', episode='7')
        self.bridge.note_playback_streams(old, ['eng'], final=True)

        # Same show/base plus temporarily missing S/E is not proof that the
        # old episode is still playing. Never expose E06's stream index here.
        self.assertFalse(self.bridge.have_playback_snapshot(next_early))
        self.assertEqual(self.bridge.embedded_candidates(next_early), [])
        self.assertFalse(self.bridge.have_playback_snapshot(next_settled))

    def test_timing_all_language_search_has_its_own_cache_and_override(self):
        rows = [{'language': 'ro', 'link': 'fixture'}]
        with patch.object(self.bridge, 'enabled', return_value=True), \
             patch.object(self.bridge, '_release_ready', return_value=True), \
             patch.object(self.bridge, '_cache_get', return_value=None) as get, \
             patch.object(self.bridge, '_cache_put') as put, \
             patch.object(self.bridge, '_search_inner',
                          return_value=rows) as search:
            result = self.bridge.search_all_languages_for_timing({})
        self.assertEqual(result, rows)
        get.assert_called_once_with({}, variant='timing_all')
        search.assert_called_once_with(
            {}, modal_progress=False, all_lang_override=True)
        put.assert_called_once_with({}, rows, variant='timing_all')

    def test_timing_all_language_cache_hit_avoids_provider_search(self):
        cached = [{'language': 'ro', 'link': 'cached'}]
        with patch.object(self.bridge, 'enabled', return_value=True), \
             patch.object(self.bridge, '_release_ready', return_value=True), \
             patch.object(self.bridge, '_cache_get', return_value=cached), \
             patch.object(self.bridge, '_search_inner') as search:
            result = self.bridge.search_all_languages_for_timing({})
        self.assertEqual(result, cached)
        search.assert_not_called()

    def test_timing_all_language_failure_is_transient_not_empty(self):
        with patch.object(self.bridge, 'enabled', return_value=True), \
             patch.object(self.bridge, '_release_ready', return_value=True), \
             patch.object(self.bridge, '_cache_get', return_value=None), \
             patch.object(self.bridge, '_cache_put') as put, \
             patch.object(self.bridge, '_search_inner',
                          side_effect=RuntimeError('provider busy')):
            result = self.bridge.search_all_languages_for_timing({})
        self.assertIsNone(result)
        put.assert_not_called()

    def test_timing_all_language_swallowed_provider_failure_is_retryable(self):
        with patch.object(self.bridge, 'enabled', return_value=True), \
             patch.object(self.bridge, '_release_ready', return_value=True), \
             patch.object(self.bridge, '_cache_get', return_value=None), \
             patch.object(self.bridge, '_cache_put') as put, \
             patch.object(self.bridge, '_search_inner', return_value=[]):
            result = self.bridge.search_all_languages_for_timing({})
        self.assertIsNone(result)
        put.assert_not_called()

    def test_timing_search_limits_engine_to_global_timing_sources(self):
        engine = types.ModuleType('resources.lib.subs_engine.engine')
        engine.c_get_subtitles = unittest.mock.Mock(return_value=[])
        engine.get_subtitles = unittest.mock.Mock(
            side_effect=AssertionError('visible-language search used'))
        engine.sort_subtitles = unittest.mock.Mock(return_value=[])
        general = types.ModuleType('resources.lib.subs_engine.general')
        general.break_all = False
        general.with_dp = False
        general.show_msg = ''
        package = types.ModuleType('resources.lib.subs_engine')
        package.engine = engine
        package.general = general
        package.__path__ = []
        with patch.dict(sys.modules, {
                'resources.lib.subs_engine': package,
                'resources.lib.subs_engine.engine': engine,
                'resources.lib.subs_engine.general': general}), \
             patch.object(self.bridge, 'ensure_engine_settings'), \
             patch.object(self.bridge, 'build_video_data', return_value={
                 'imdb': '123', 'title': 'Show', 'season': '1',
                 'episode': '6', 'media_type': 'tv'}):
            result = self.bridge._search_inner(
                {}, modal_progress=False, all_lang_override=True)
        self.assertEqual(result, [])
        engine.c_get_subtitles.assert_called_once_with(
            unittest.mock.ANY, all_lang_override=True, timing_only=True)
        engine.get_subtitles.assert_not_called()

    def test_engine_provider_globals_are_serialized_between_searches(self):
        entered = []
        first_entered = threading.Event()
        release_first = threading.Event()

        def provider_search(*_args, **_kwargs):
            entered.append(threading.current_thread().name)
            if len(entered) == 1:
                first_entered.set()
                release_first.wait(2.0)
            return []

        engine = types.ModuleType('resources.lib.subs_engine.engine')
        engine.c_get_subtitles = provider_search
        engine.get_subtitles = unittest.mock.Mock(
            side_effect=AssertionError('visible-language search used'))
        engine.sort_subtitles = unittest.mock.Mock(return_value=[])
        general = types.ModuleType('resources.lib.subs_engine.general')
        general.break_all = False
        general.with_dp = False
        general.show_msg = ''
        package = types.ModuleType('resources.lib.subs_engine')
        package.engine = engine
        package.general = general
        package.__path__ = []

        def run_search():
            self.bridge._search_inner(
                {}, modal_progress=False, all_lang_override=True)

        with patch.dict(sys.modules, {
                'resources.lib.subs_engine': package,
                'resources.lib.subs_engine.engine': engine,
                'resources.lib.subs_engine.general': general}), \
             patch.object(self.bridge, 'ensure_engine_settings'), \
             patch.object(self.bridge, 'build_video_data', return_value={
                 'imdb': '123', 'title': 'Show', 'season': '1',
                 'episode': '6', 'media_type': 'tv'}):
            first = threading.Thread(target=run_search, name='first')
            second = threading.Thread(target=run_search, name='second')
            first.start()
            self.assertTrue(first_entered.wait(1.0))
            second.start()
            time.sleep(0.05)
            self.assertEqual(entered, ['first'])
            release_first.set()
            first.join(2.0)
            second.join(2.0)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(entered, ['first', 'second'])

    def test_manual_progress_consumes_end_before_background_search_starts(self):
        modal_started = threading.Event()
        modal_observed = []
        general = types.ModuleType('resources.lib.subs_engine.general')
        general.break_all = False
        general.with_dp = False
        general.show_msg = ''

        def delayed_modal(_show):
            modal_started.set()
            time.sleep(0.12)
            modal_observed.append(general.show_msg)

        general.show_results = delayed_modal
        engine = types.ModuleType('resources.lib.subs_engine.engine')
        engine.get_subtitles = unittest.mock.Mock(return_value=[])

        def timing_search(*_args, **_kwargs):
            # Simulate the old engine behavior that reused the shared status.
            # A joined manual dialog must already be gone before this can run.
            general.show_msg = 'BACKGROUND_SEARCH'
            return []

        engine.c_get_subtitles = timing_search
        engine.sort_subtitles = unittest.mock.Mock(return_value=[])
        package = types.ModuleType('resources.lib.subs_engine')
        package.engine = engine
        package.general = general
        package.__path__ = []

        with patch.dict(sys.modules, {
                'resources.lib.subs_engine': package,
                'resources.lib.subs_engine.engine': engine,
                'resources.lib.subs_engine.general': general}), \
             patch.object(self.bridge, 'ensure_engine_settings'), \
             patch.object(self.bridge, 'build_video_data', return_value={
                 'imdb': '123', 'title': 'Show', 'season': '1',
                 'episode': '6', 'media_type': 'tv'}):
            self.bridge._search_inner(
                {}, modal_progress=True, all_lang_override=False)
            self.assertTrue(modal_started.is_set())
            self.bridge._search_inner(
                {}, modal_progress=False, all_lang_override=True)
        self.assertEqual(modal_observed, ['END'])

    def test_timed_out_provider_workers_quarantine_the_next_search(self):
        source = (LIB / 'subs_engine/engine.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        wanted = {'_join_provider_threads', '_provider_workers_ready',
                  '_quarantine_provider_threads', '_finish_timing_timeout'}
        nodes = [node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name in wanted]
        self.assertEqual({node.name for node in nodes}, wanted)
        class ProviderSearchBusy(RuntimeError):
            pass

        namespace = {'time': time, '_lingering_provider_threads': [],
                     'ProviderSearchBusy': ProviderSearchBusy}
        exec(compile(ast.Module(body=nodes, type_ignores=[]),
                     '<engine-worker-gate>', 'exec'), namespace)

        class Worker:
            def __init__(self, finish_on_join=False):
                self.alive = True
                self.finish_on_join = finish_on_join
                self.joins = 0

            def is_alive(self):
                return self.alive

            def join(self, _timeout):
                self.joins += 1
                if self.finish_on_join:
                    self.alive = False

        stuck = Worker()
        self.assertFalse(namespace['_quarantine_provider_threads'](
            [stuck], timeout_s=0.001))
        self.assertFalse(namespace['_provider_workers_ready'](
            timeout_s=0.001))
        self.assertEqual(namespace['_lingering_provider_threads'], [stuck])

        stuck.alive = False
        self.assertTrue(namespace['_provider_workers_ready'](
            timeout_s=0.001))
        self.assertEqual(namespace['_lingering_provider_threads'], [])

        finishing = Worker(finish_on_join=True)
        self.assertTrue(namespace['_quarantine_provider_threads'](
            [finishing], timeout_s=0.01))
        self.assertGreaterEqual(finishing.joins, 1)

        class Source:
            def __init__(self, rows):
                self.global_var = rows

        partial = Source(['FAST_EN'])
        late = Source([])
        stuck = Worker()
        with self.assertRaises(ProviderSearchBusy):
            namespace['_finish_timing_timeout'](
                [stuck], [('fast', partial), ('late', late)],
                timeout_s=0.001)

        class CompletingWorker(Worker):
            def join(self, _timeout):
                self.joins += 1
                late.global_var = ['LATE_RO']
                self.alive = False

        completed = namespace['_finish_timing_timeout'](
            [CompletingWorker()], [('fast', partial), ('late', late)],
            timeout_s=0.01)
        self.assertEqual(completed, ['FAST_EN', 'LATE_RO'])

        c_get = next(node for node in tree.body
                     if isinstance(node, ast.FunctionDef)
                     and node.name == 'c_get_subtitles')
        calls = {node.func.id for node in ast.walk(c_get)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name)}
        self.assertIn('_provider_workers_ready', calls)
        self.assertIn('_quarantine_provider_threads', calls)
        self.assertIn('_finish_timing_timeout', calls)


if __name__ == '__main__':
    unittest.main()
