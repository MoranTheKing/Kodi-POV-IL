"""An external Hebrew subtitle must never become a fake embedded 101% row.

The field failure is a real race: the play-start poll first completed with zero
embedded streams, MoranSubs appended an external Hebrew file, and a parallel
poller then saw ``['heb']`` and overwrote the empty baseline.  This executes the
real snapshot code with that exact ordering.  The pre-fix implementation either
rejects ``final=True`` or overwrites the baseline, so this cannot pass without
the production fix.
"""

import importlib.util
import json
from pathlib import Path
import sys
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


if __name__ == '__main__':
    unittest.main()
