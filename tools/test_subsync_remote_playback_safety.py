"""SubSync's remote path is restricted to the compact Matroska Cues reader.

Exercise real deep verification/service paths.  The heavy cluster/audio probes
must stay local-only; remote playback may call only embedded_extract's bounded,
keep-alive cue-index API after playback is stable.
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
        ku.cache_dir = lambda: str(self.root)
        xbmc = types.ModuleType('xbmc')
        xbmc.Player = lambda: types.SimpleNamespace(
            getPlayingFile=lambda: self.url,
            isPlayingVideo=lambda: True,
            getTime=lambda: 12.0)
        xbmc.getCondVisibility = lambda _name: False
        xbmc.sleep = lambda _ms: None
        ee = types.ModuleType('resources.lib.embedded_extract')
        self.cue_reader = Mock(return_value=[])
        ee.cue_reference_times = self.cue_reader
        self.mods = patch.dict(sys.modules, {'resources': pkg, 'resources.lib': lib,
                     'resources.lib.kodi_utils': ku, 'resources.lib.embedded_extract': ee,
                     'xbmc': xbmc})
        self.mods.start()
        self.addCleanup(self.mods.stop)
        spec = importlib.util.spec_from_file_location('subsync_remote_test', LIB / 'subsync.py')
        self.sub = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.sub)
        self.sub._probe_cache_path = lambda: str(self.cache)
        self.sub._oracle_candidates = Mock(return_value=[])
        self.sub._load_verdicts = Mock(return_value={})
        self.sub._store_verdict = Mock()
        self.real_swap_if_current = self.sub._swap_if_current
        self.sub._swap_if_current = Mock()
        self.sub._announce = Mock()
        self.network = Mock(side_effect=AssertionError('unexpected media network request'))
        self.netpatch = patch('urllib.request.urlopen', self.network)
        self.netpatch.start()
        self.addCleanup(self.netpatch.stop)
        gemini = types.ModuleType('resources.lib.gemini')
        gemini.generate_media = Mock(side_effect=AssertionError('unexpected Gemini request'))
        sys.modules['resources.lib.gemini'] = gemini

    def test_remote_missing_oracle_uses_only_bounded_cue_reader(self):
        out, verdict = self.sub._deep_verify({}, str(self.subtitle), self.subtitle.read_text(),
                                            'sub-release', 'movie-release', 'key')
        self.assertEqual(out, str(self.subtitle))
        self.assertEqual(verdict['status'], self.sub._STATUS_NO_ORACLE)
        self.cue_reader.assert_called_once()
        self.network.assert_not_called()

    def test_queued_service_job_without_oracle_keeps_original_on_cue_miss(self):
        self.sub.run_deep_job({'key': 'key', 'path': str(self.subtitle),
                               'playing': 'movie-release', 'info': {}})
        self.sub._oracle_candidates.assert_called_once()
        self.cue_reader.assert_called_once()
        self.network.assert_not_called()
        self.sub._swap_if_current.assert_not_called()
        self.sub._announce.assert_not_called()

    def test_inconclusive_oracle_falls_through_to_actual_playing_file(self):
        candidate = {'release': 'movie-release', 'payload': 'opaque'}
        self.sub._oracle_candidates = Mock(return_value=[candidate])
        starts = [1000 + i * 2500 for i in range(12)]
        self.cue_reader.return_value = starts
        unknown = {'status': self.sub.sync_align.STATUS_UNKNOWN,
                   'diag': 'controlled oracle miss'}
        confirmed = {'status': self.sub.sync_align.STATUS_CONFIRMED,
                     'diag': 'actual playing file matched'}
        with patch.object(self.sub.sync_align, 'pick_oracle',
                          return_value=(candidate, 'exact')), \
             patch.object(self.sub, '_download_oracle',
                          return_value=self.subtitle.read_text()), \
             patch.object(self.sub.sync_align, 'verify_and_fix',
                          return_value=(self.subtitle.read_text(), unknown)), \
             patch.object(self.sub.sync_align, 'verify_cues',
                          return_value=confirmed) as actual_verify:
            out, verdict = self.sub._deep_verify(
                {}, str(self.subtitle), self.subtitle.read_text(),
                'sub-release', 'movie-release', 'key')
        self.assertEqual(out, str(self.subtitle))
        self.assertEqual(verdict['status'], self.sub.sync_align.STATUS_CONFIRMED)
        self.cue_reader.assert_called_once()
        actual_verify.assert_called_once()
        self.network.assert_not_called()

    def test_remote_variants_and_stale_filepath_are_rejected(self):
        for url in ('http://media.invalid/movie.mkv', self.url,
                    'HTTPS://media.invalid/movie.mkv|Authorization=synthetic'):
            self.url = url
            with self.subTest(url=url):
                self.assertEqual(self.sub._playing_url({}), '')
                self.assertEqual(self.sub._remote_playing_url({}),
                                 url.split('|')[0])
        self.url = ''
        self.assertEqual(self.sub._playing_url({'filepath': 'https://media.invalid/stale.mkv'}), '')
        self.assertEqual(self.sub._remote_playing_url(
            {'filepath': 'https://media.invalid/stale.mkv'}),
            'https://media.invalid/stale.mkv')
        self.network.assert_not_called()

    def test_remote_cues_are_adapted_and_cached_without_heavy_probe(self):
        starts = [1000 + i * 2500 for i in range(12)]
        self.cue_reader.return_value = starts
        from resources.lib import mkv_probe
        with patch.object(mkv_probe, 'subtitle_reference') as heavy:
            cues = self.sub._probe_reference_cues({}, 'movie-release')
        self.assertEqual(len(cues), len(starts))
        self.assertEqual(cues[0]['start'], starts[0])
        self.assertGreater(cues[0]['end'], cues[0]['start'])
        self.cue_reader.assert_called_once()
        self.assertTrue(self.cue_reader.call_args.kwargs['allow_http'])
        heavy.assert_not_called()
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

    def test_cached_piecewise_verdict_is_applied_without_flat_delay_record(self):
        blocks = []
        for i in range(10):
            start = 11000 + i * 10000
            end = start + 1200
            stamp = lambda ms: '00:%02d:%02d,%03d' % (
                ms // 60000, (ms // 1000) % 60, ms % 1000)
            blocks.append('%d\n%s --> %s\nLine %d' % (
                i + 1, stamp(start), stamp(end), i + 1))
        text = '\n\n'.join(blocks) + '\n'
        self.subtitle.write_text(text, encoding='utf-8')
        playing = 'Movie.2026.1080p.WEB-DL'
        key = self.sub._cache_key(text, playing)
        verdict = {
            'v': self.sub._VERDICT_VERSION,
            'status': self.sub.sync_align.STATUS_FIXABLE,
            'scale': 1.0,
            'offset_ms': 1000.0,
            'mode': 'piecewise',
            'segments': [
                {'cand_from_ms': None, 'cand_to_ms': 60000.0,
                 'ref_from_ms': None, 'ref_to_ms': 57500.0,
                 'offset_ms': 1000.0},
                {'cand_from_ms': 60000.0, 'cand_to_ms': None,
                 'ref_from_ms': 57500.0, 'ref_to_ms': None,
                 'offset_ms': 6000.0},
            ],
            'diag': 'test piecewise cache',
        }
        record = Mock()
        with patch.object(self.sub, 'enabled', return_value=True), \
             patch.object(self.sub, 'playing_release', return_value=playing), \
             patch.object(self.sub, '_load_verdicts', return_value={key: verdict}), \
             patch.object(self.sub, '_record_delivery', record):
            out, result = self.sub.process({}, str(self.subtitle), '')

        self.assertNotEqual(out, str(self.subtitle))
        fixed = Path(out).read_text(encoding='utf-8')
        self.assertIn('00:00:10,000 --> 00:00:11,200', fixed)
        self.assertIn('00:00:55,000 --> 00:00:56,200', fixed)
        self.assertEqual(result['mode'], 'piecewise')
        self.assertTrue(result['cached'])
        record.assert_not_called()
        self.network.assert_not_called()

    def test_enqueue_captures_actual_stream_identity(self):
        queue = self.root / 'queue'
        with patch.object(self.sub, '_queue_dir', return_value=str(queue)):
            self.assertTrue(self.sub._enqueue_deep(
                {'filepath': ''}, str(self.subtitle), '', 'movie-release',
                'subtitle-key'))
        jobs = list(queue.glob('*.json'))
        self.assertEqual(len(jobs), 1)
        job = json.loads(jobs[0].read_text(encoding='utf-8'))
        self.assertEqual(job['stream_url'], self.url)

    def test_background_swap_requires_same_proven_stream(self):
        xbmc = sys.modules['xbmc']
        setter = Mock()
        current = {'url': 'https://media.invalid/stream?file=B&token=new'}
        player = types.SimpleNamespace(
            isPlaying=lambda: True,
            getPlayingFile=lambda: current['url'],
            setSubtitles=setter)
        base = {'key': 'subtitle-key', 'info': {}}
        with patch.object(self.sub, '_pending_key',
                          return_value='subtitle-key'), \
             patch.object(xbmc, 'Player', return_value=player):
            self.assertFalse(self.real_swap_if_current(
                dict(base), 'fixed.srt', {}))
            self.assertFalse(self.real_swap_if_current(
                dict(base, stream_url='https://media.invalid/old.mkv'),
                'fixed.srt', {}))
            self.assertFalse(self.real_swap_if_current(
                dict(base, stream_url=
                     'https://media.invalid/stream?file=A&token=new'),
                'fixed.srt', {}))
            self.assertFalse(self.real_swap_if_current(
                dict(base, stream_url=
                     'https://media.invalid/stream?file=B&token=old'),
                'fixed.srt', {}))
            self.assertTrue(self.real_swap_if_current(
                dict(base, stream_url=current['url']),
                'fixed.srt', {}))
        setter.assert_called_once_with('fixed.srt')


if __name__ == '__main__':
    unittest.main()
