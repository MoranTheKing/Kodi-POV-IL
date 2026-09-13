"""SubSync must never compete with Kodi for a remote playing stream.

Exercise real deep verification/service paths; network spies are counted even
when production fail-open handlers swallow exceptions. No external traffic.
"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

LIB = Path(__file__).resolve().parents[1] / 'addons/service.subtitles.kodipovilai/resources/lib'


class RemotePlaybackSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.media = self.root / 'movie.mkv'
        self.media.write_bytes(b'local fixture')
        self.subtitle = self.root / 'subtitle.srt'
        self.subtitle.write_text('1\n00:00:01,000 --> 00:00:02,000\nHello\n', encoding='utf-8')
        self.url = 'https://media.invalid/movie.mkv?token=synthetic'
        self.cache = self.root / 'probe.json'
        pkg = types.ModuleType('resources')
        lib = types.ModuleType('resources.lib')
        pkg.__path__ = []
        lib.__path__ = [str(LIB)]
        ku = types.ModuleType('resources.lib.kodi_utils')
        ku.log = Mock()
        ku.get_setting = lambda key, default='': 'test-only' if key == 'api_key' else default
        xbmc = types.ModuleType('xbmc')
        xbmc.Player = lambda: types.SimpleNamespace(getPlayingFile=lambda: self.url)
        self.mods = patch.dict(sys.modules, {'resources': pkg, 'resources.lib': lib,
                     'resources.lib.kodi_utils': ku, 'xbmc': xbmc})
        self.mods.start()
        self.addCleanup(self.mods.stop)
        spec = importlib.util.spec_from_file_location('subsync_remote_test', LIB / 'subsync.py')
        self.sub = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.sub)
        self.sub._probe_cache_path = lambda: str(self.cache)
        self.sub._oracle_candidates = Mock(return_value=[])
        self.sub._load_verdicts = Mock(return_value={})
        self.sub._store_verdict = Mock()
        self.sub._swap_if_current = Mock()
        self.sub._announce = Mock()
        self.network = Mock(side_effect=AssertionError('unexpected media network request'))
        self.netpatch = patch('urllib.request.urlopen', self.network)
        self.netpatch.start()
        self.addCleanup(self.netpatch.stop)
        gemini = types.ModuleType('resources.lib.gemini')
        gemini.generate_media = Mock(side_effect=AssertionError('unexpected Gemini request'))
        sys.modules['resources.lib.gemini'] = gemini

    def test_remote_missing_oracle_deep_path_keeps_subtitle_without_network(self):
        out, verdict = self.sub._deep_verify({}, str(self.subtitle), self.subtitle.read_text(),
                                            'sub-release', 'movie-release', 'key')
        self.assertEqual(out, str(self.subtitle))
        self.assertEqual(verdict['status'], self.sub._STATUS_NO_ORACLE)
        self.network.assert_not_called()

    def test_queued_service_job_without_oracle_does_not_touch_remote_media(self):
        self.sub.run_deep_job({'key': 'key', 'path': str(self.subtitle),
                               'playing': 'movie-release', 'info': {}})
        self.sub._oracle_candidates.assert_called_once()
        self.network.assert_not_called()
        self.sub._swap_if_current.assert_not_called()
        self.sub._announce.assert_not_called()

    def test_remote_variants_and_stale_filepath_are_rejected(self):
        for url in ('http://media.invalid/movie.mkv', self.url,
                    'HTTPS://media.invalid/movie.mkv|Authorization=synthetic'):
            self.url = url
            with self.subTest(url=url):
                self.assertEqual(self.sub._playing_url({}), '')
        self.url = ''
        self.assertEqual(self.sub._playing_url({'filepath': 'https://media.invalid/stale.mkv'}), '')
        self.network.assert_not_called()

    def test_remote_audio_second_pass_keeps_cached_cues_without_network(self):
        cues = [{'start': 1000, 'end': 2000}]
        key = self.sub.release_match.normalize('movie-release') + '|audio'
        self.cache.write_text(json.dumps({key: {'pv': self.sub._PROBE_CACHE_VERSION,
                                               'cues': cues}}))
        self.assertEqual(self.sub._audio_probe_reference({}, 'movie-release', second_pass=True), cues)
        self.network.assert_not_called()

    def test_remote_cached_container_reference_still_available(self):
        cues = [{'start': 1000, 'end': 2000}]
        key = self.sub.release_match.normalize('movie-release')
        self.cache.write_text(json.dumps({key: {'pv': self.sub._PROBE_CACHE_VERSION,
                                               'cues': cues}}))
        self.assertEqual(self.sub._probe_reference_cues({}, 'movie-release'), cues)
        self.network.assert_not_called()

    def test_local_file_still_reaches_container_probe(self):
        self.url = str(self.media)
        self.assertEqual(self.sub._playing_url({}), str(self.media))
        from resources.lib import mkv_probe
        cues = [{'start': 1000, 'end': 2000}]
        with patch.object(mkv_probe, 'subtitle_reference', return_value={'cues': cues}) as probe:
            self.assertEqual(self.sub._probe_reference_cues({}, 'movie-release'), cues)
            self.assertEqual(probe.call_args.args[0], str(self.media))
        self.network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
