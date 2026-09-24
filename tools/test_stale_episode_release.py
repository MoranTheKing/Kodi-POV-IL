"""A remembered source from episode 7 must not identify episodes 8 or 4."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


LIB = (Path(__file__).resolve().parents[1] /
       'addons/service.subtitles.kodipovilai/resources/lib')


class StaleEpisodeReleaseTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            'incident_kodi_utils', LIB / 'kodi_utils.py')
        self.ku = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ku)

    def test_explicit_other_episode_is_stale(self):
        name = 'The.Shards.S01E07.1080p.WEB-DL.mkv'
        for episode in ('4', '8'):
            self.assertTrue(self.ku.release_conflicts_with_episode(
                name, '1', episode))
        self.assertFalse(self.ku.release_conflicts_with_episode(name, '1', '7'))
        self.assertFalse(self.ku.release_conflicts_with_episode(
            'The.Shards.S01.1080p.WEB-DL.mkv', '1', '8'))
        self.assertFalse(self.ku.release_conflicts_with_episode(
            name, '', '8'))

    def test_player_snapshot_discards_stale_window_property(self):
        labels = {
            'VideoPlayer.TVshowtitle': 'The Shards',
            'VideoPlayer.Season': '1',
            'VideoPlayer.Episode': '8',
            'Window(10000).Property(subs.player_filename)':
                'The.Shards.S01E07.1080p.WEB-DL.mkv',
        }
        self.ku.KODI_AVAILABLE = True
        self.ku.xbmc = types.SimpleNamespace(
            getInfoLabel=lambda key: labels.get(key, ''))
        info = self.ku.current_video_info()
        self.assertTrue(info['is_episode'])
        self.assertEqual(info['picked_release'], '')
        labels['Window(10000).Property(subs.player_filename)'] = (
            'The.Shards.S01E08.1080p.WEB-DL.mkv')
        self.assertIn('S01E08', self.ku.current_video_info()['picked_release'])

    def test_bridge_ignores_stale_episode_for_ranking_and_cache(self):
        pkg = types.ModuleType('resources')
        lib = types.ModuleType('resources.lib')
        pkg.__path__ = [str(LIB.parent)]
        lib.__path__ = [str(LIB)]
        lib.kodi_utils = self.ku
        with patch.dict(sys.modules, {
                'resources': pkg, 'resources.lib': lib,
                'resources.lib.kodi_utils': self.ku}):
            spec = importlib.util.spec_from_file_location(
                'resources.lib.incident_bridge', LIB / 'subs_engine_bridge.py')
            bridge = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(bridge)
            info = {
                'picked_release': 'The.Shards.S01E07.1080p.WEB-DL.mkv',
                'season': '1', 'episode': '8',
                'title': 'The Shards',
            }
            self.assertFalse(bridge._release_ready(info))
            self.assertNotIn('S01E07', bridge._detect_release_name(info))
            info['tagline'] = 'The.Shards.S01E08.1080p.WEB-DL.mkv'
            self.assertTrue(bridge._release_ready(info))
            self.assertIn('S01E08', bridge._detect_release_name(info))

    def test_publisher_never_erases_fresh_pick_when_labels_lag_and_url_changes(self):
        props = {
            'pov_picked_source_name': 'The.Shards.S01E07.1080p.WEB-DL',
            'pov_picked_source_url': 'https://media.invalid/e07',
            'subs.player_filename': 'The.Shards.S01E07.1080p.WEB-DL',
        }
        labels = {
            'VideoPlayer.Title': 'The Shards',
            'VideoPlayer.Season': '1',
            'VideoPlayer.Episode': '8',
            'VideoPlayer.VideoResolution': '1080',
        }
        current_url = ['https://media.invalid/e08']

        class Player:
            def __init__(self):
                pass

            def getPlayingFile(self):
                return current_url[0]

        xbmc = types.ModuleType('xbmc')
        xbmc.Player = Player
        xbmc.getInfoLabel = lambda key: labels.get(key, '')
        xbmcgui = types.ModuleType('xbmcgui')
        window = types.SimpleNamespace(
            getProperty=lambda key: props.get(key, ''),
            setProperty=lambda key, value: props.__setitem__(key, value),
            clearProperty=lambda key: props.pop(key, None))
        xbmcgui.Window = lambda _wid: window
        pkg = types.ModuleType('resources')
        lib = types.ModuleType('resources.lib')
        pkg.__path__ = [str(LIB.parent)]
        lib.__path__ = [str(LIB)]
        lib.kodi_utils = self.ku
        with patch.dict(sys.modules, {
                'resources': pkg, 'resources.lib': lib,
                'resources.lib.kodi_utils': self.ku,
                'xbmc': xbmc, 'xbmcgui': xbmcgui}):
            spec = importlib.util.spec_from_file_location(
                'resources.lib.incident_publisher',
                LIB / 'subs_filename_publisher.py')
            publisher = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(publisher)
            # The publisher only mirrors source properties. Episode validation
            # belongs to the readers above, because player labels can lag AV
            # start and a resolved URL need not equal the pre-player URL.
            publisher.SubsFilenamePublisher().onPlayBackStarted()
            self.assertIn('S01E07', props['subs.player_filename'])
            publisher.SubsFilenamePublisher().onAVStarted()
            self.assertIn('S01E07', props['subs.player_filename'])
            self.assertEqual(props['pov_picked_source_url'],
                             'https://media.invalid/e07')

            # A *fresh* E08 pick must survive the lagging E07 label even when
            # Kodi presents a redirected/normalized playback URL.
            props['pov_picked_source_name'] = 'The.Shards.S01E08.WEB-DL'
            props['subs.player_filename'] = props['pov_picked_source_name']
            props['pov_picked_source_url'] = 'https://media.invalid/e08?pre=1'
            labels['VideoPlayer.Episode'] = '7'
            current_url[0] = 'https://media.invalid/e08?resolved=1'
            publisher.SubsFilenamePublisher().onAVStarted()
            self.assertIn('S01E08', props['subs.player_filename'])
            self.assertIn('S01E08', props['pov_picked_source_name'])
            self.assertEqual(props['pov_picked_source_url'],
                             'https://media.invalid/e08?pre=1')

    def test_installed_darksubs_v2_upgrades_without_clearing_fresh_source(self):
        pkg = types.ModuleType('resources')
        lib = types.ModuleType('resources.lib')
        pkg.__path__ = [str(LIB.parent)]
        lib.__path__ = [str(LIB)]
        lib.kodi_utils = self.ku
        with patch.dict(sys.modules, {
                'resources': pkg, 'resources.lib': lib,
                'resources.lib.kodi_utils': self.ku}):
            spec = importlib.util.spec_from_file_location(
                'resources.lib.incident_darksubs',
                LIB / 'darksubs_filename_fallback_patcher.py')
            patcher = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(patcher)
            with tempfile.TemporaryDirectory() as folder:
                host = Path(folder) / 'general.py'
                host.write_bytes((
                    'import os\r\ndef get_playing_filename(file_original_path):\r\n'
                    + patcher.V2_NEW_BLOCK + patcher.HELPER_BLOCK
                ).encode('utf-8'))
                with patch.object(patcher, '_general_path',
                                  return_value=str(host)):
                    self.assertEqual(patcher.ensure_patched(), 'patched')
                    self.assertEqual(patcher.ensure_patched(), 'unchanged')
                upgraded_bytes = host.read_bytes()
                upgraded = upgraded_bytes.decode('utf-8')
                self.assertIn(patcher.MARKER, upgraded)
                self.assertNotIn('clearProperty(', upgraded)
                self.assertNotIn(patcher.V2_NEW_BLOCK.encode('utf-8'),
                                 upgraded_bytes)

                props = {
                    'pov_picked_source_name': 'The.Shards.S01E08.WEB-DL',
                    'pov_picked_source_url':
                        'https://media.invalid/e08?pre=1',
                    'subs.player_filename': 'The.Shards.S01E08.WEB-DL',
                }
                labels = {
                    'VideoPlayer.Title': 'The Shards',
                    'VideoPlayer.Season': '1',
                    'VideoPlayer.Episode': '7',
                    'VideoPlayer.VideoResolution': '1080',
                }
                xbmc = types.ModuleType('xbmc')
                xbmc.getInfoLabel = lambda key: labels.get(key, '')
                xbmc.Player = lambda: types.SimpleNamespace(
                    getPlayingFile=lambda: 'https://media.invalid/e08?resolved=1')
                xbmcgui = types.ModuleType('xbmcgui')
                xbmcgui.Window = lambda _wid: types.SimpleNamespace(
                    getProperty=lambda key: props.get(key, ''),
                    clearProperty=lambda key: props.pop(key, None))
                with patch.dict(sys.modules, {'xbmcgui': xbmcgui}):
                    scope = {'xbmc': xbmc}
                    exec(compile(host.read_bytes(), str(host), 'exec'), scope)
                    scope['get_playing_filename'](
                        'https://media.invalid/0123456789abcdef0123456789abcdef')
                    self.assertIn('S01E08', props['pov_picked_source_name'])
                    self.assertIn('S01E08', props['subs.player_filename'])
                    labels['VideoPlayer.Episode'] = '8'
                    self.assertIn('S01E08', scope['get_playing_filename'](
                        'https://media.invalid/0123456789abcdef0123456789abcdef'))

                # A partly damaged v2 host has the call but lost its helper.
                # The upgrader must restore the definition, not mistake the
                # call site for proof that the helper already exists.
                host.write_bytes((
                    'import os\r\ndef get_playing_filename(file_original_path):\r\n'
                    + patcher.V2_NEW_BLOCK
                ).encode('utf-8'))
                with patch.object(patcher, '_general_path',
                                  return_value=str(host)):
                    self.assertEqual(patcher.ensure_patched(), 'patched')
                self.assertIn('def _ai_subs_filename_looks_like_hash(',
                              host.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
