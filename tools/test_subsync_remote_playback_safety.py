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
import urllib.parse
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
            isPlaying=lambda: True,
            isPlayingVideo=lambda: True,
            getTime=lambda: 12.0)
        xbmc.getCondVisibility = lambda _name: False
        xbmc.sleep = lambda _ms: None
        self.window_props = {}
        xbmcgui = types.ModuleType('xbmcgui')
        props = self.window_props
        xbmcgui.Window = lambda _wid: types.SimpleNamespace(
            getProperty=lambda key: props.get(key, ''),
            setProperty=lambda key, value: props.__setitem__(key, value),
            clearProperty=lambda key: props.pop(key, None))
        ee = types.ModuleType('resources.lib.embedded_extract')
        self.cue_reader = Mock(return_value=[])
        self.signature_reader = Mock(return_value='')
        ee.cue_reference_times = self.cue_reader
        ee.media_cut_signature = self.signature_reader
        self.mods = patch.dict(sys.modules, {'resources': pkg, 'resources.lib': lib,
                     'resources.lib.kodi_utils': ku, 'resources.lib.embedded_extract': ee,
                     'xbmc': xbmc, 'xbmcgui': xbmcgui})
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
                               'playing': 'movie-release', 'info': {},
                               'stream_url': self.url})
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
        # Actual-media CONFIRMED is stronger and now saves the provider request.
        self.sub._oracle_candidates.assert_not_called()
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
        key = self.sub._transport_cache_key({})
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
        self.window_props[self.sub._DELIVERED_PROP] = 'stale-global-record'
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
        self.assertNotIn(self.sub._DELIVERED_PROP, self.window_props)
        self.network.assert_not_called()

    def test_background_piecewise_swap_clears_foreground_scalar_record(self):
        verdict = {'status': self.sub.sync_align.STATUS_FIXABLE,
                   'mode': 'piecewise', 'scale': 1.0,
                   'offset_ms': 1000.0, 'applied': True,
                   'cache_key': 'exact-key',
                   'cut_signature': 'cut1:' + 'a' * 32,
                   'segments': [{'cand_from_ms': None,
                                 'offset_ms': 1000.0}]}
        job = {'key': 'legacy-key', 'path': str(self.subtitle),
               'playing': 'movie-release', 'info': {},
               'stream_url': self.url}
        self.window_props[self.sub._DELIVERED_PROP] = json.dumps(
            {'key': 'legacy-key', 'mode': 'global', 'offset': 0})
        with patch.object(self.sub, '_job_stream_is_current',
                          return_value=True), \
             patch.object(self.sub, '_job_matches_current',
                          return_value=True), \
             patch.object(self.sub, '_deep_verify',
                          return_value=(str(self.media), verdict)), \
             patch.object(self.sub, '_swap_if_current',
                          return_value=True), \
             patch.object(self.sub, '_record_delivery') as record:
            self.sub.run_deep_job(job)
        record.assert_not_called()
        self.assertNotIn(self.sub._DELIVERED_PROP, self.window_props)

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
        self.assertFalse(job['identity_only'])

    def test_queue_names_do_not_collide_after_long_common_prefix_or_by_mode(self):
        queue = self.root / 'queue'
        common = 'subtitle|' + ('same-release-prefix-' * 8)
        with patch.object(self.sub, '_queue_dir', return_value=str(queue)):
            self.assertTrue(self.sub._enqueue_deep(
                {}, str(self.subtitle), '', 'release', common + 'A'))
            self.assertTrue(self.sub._enqueue_deep(
                {}, str(self.subtitle), '', 'release', common + 'B'))
            self.assertTrue(self.sub._enqueue_deep(
                {}, str(self.subtitle), '', 'release', common + 'A',
                identity_only=True))
        self.assertEqual(len(list(queue.glob('*.json'))), 3)

    def test_trusted_remote_delivery_queues_only_cut_identity_work(self):
        playing = 'Movie.2026.1080p.WEB-DL'
        tier = next(iter(self.sub.release_match.AUTO_OK_TIERS))
        enqueue = Mock(return_value=True)
        with patch.object(self.sub, 'enabled', return_value=True), \
             patch.object(self.sub, 'playing_release', return_value=playing), \
             patch.object(self.sub, '_known_cut_signature', return_value=''), \
             patch.object(self.sub.release_match, 'score',
                          return_value=(100, tier, {})), \
             patch.object(self.sub, '_record_delivery'), \
             patch.object(self.sub, '_enqueue_deep', enqueue):
            out, verdict = self.sub.process(
                {}, str(self.subtitle), playing)
        self.assertEqual(out, str(self.subtitle))
        self.assertEqual(verdict['status'], self.sub._STATUS_TRUSTED)
        self.assertTrue(enqueue.call_args.kwargs['identity_only'])
        self.assertEqual(self.sub._pending_key(), enqueue.call_args.args[4])
        self.sub._oracle_candidates.assert_not_called()

    def test_identity_probe_reads_only_tiny_content_signature_not_cues(self):
        sig = 'cut1:' + 'e' * 32
        self.signature_reader.return_value = sig
        with patch.object(self.sub, '_remote_probe_ready', return_value=True):
            self.assertEqual(self.sub._learn_cut_signature({}), sig)
        self.signature_reader.assert_called_once()
        self.assertTrue(self.signature_reader.call_args.kwargs['allow_http'])
        self.cue_reader.assert_not_called()
        saved = json.loads(self.cache.read_text(encoding='utf-8'))
        ent = saved[self.sub._transport_cache_key({})]
        self.assertEqual(ent['cut_signature'], sig)
        self.assertEqual(ent['cues'], [])
        self.assertFalse(ent['timing_attempted'])
        self.network.assert_not_called()

    def test_identity_only_cache_never_suppresses_later_timing_probe(self):
        sig = 'cut1:' + 'e' * 32
        self.signature_reader.return_value = sig
        with patch.object(self.sub, '_remote_probe_ready', return_value=True):
            self.assertEqual(self.sub._learn_cut_signature({}), sig)
        full = {'cues': [{'start': 1000, 'end': 1800}] * 10,
                'track_cues': [], 'cut_signature': sig, 'bytes': 123}
        with patch.object(self.sub, '_remote_reference_bundle',
                          return_value=full) as probe:
            out = self.sub._probe_reference_bundle({}, 'release')
        probe.assert_called_once()
        self.assertEqual(out['cues'], full['cues'])
        self.assertTrue(out['timing_attempted'])

    def test_identity_job_records_exact_cut_without_timing_or_provider_work(self):
        sig = 'cut1:' + 'd' * 32
        key = 'legacy-sub-hash|movie-release'
        record = Mock()
        deep = Mock(side_effect=AssertionError('timing verification ran'))
        job = {'key': key, 'path': str(self.subtitle),
               'playing': 'movie-release', 'info': {},
               'identity_only': True, 'stream_url': self.url}
        self.window_props[self.sub._PENDING_PROP] = json.dumps(
            {'key': key, 'ts': 1})
        xbmc = sys.modules['xbmc']
        player = types.SimpleNamespace(isPlaying=lambda: True,
                                       getPlayingFile=lambda: self.url)
        with patch.object(self.sub, '_learn_cut_signature', return_value=sig), \
             patch.object(self.sub, '_record_delivery', record), \
             patch.object(self.sub, '_deep_verify', deep), \
             patch.object(xbmc, 'Player', return_value=player):
            self.sub.run_deep_job(job)
        exact_key = self.sub._cache_key(
            self.subtitle.read_text(encoding='utf-8'), 'movie-release', sig)
        self.assertEqual(record.call_args.args[2], exact_key)
        self.assertEqual(record.call_args.kwargs['cut_signature'], sig)
        self.assertEqual(self.sub._pending_key(), '')
        self.sub._oracle_candidates.assert_not_called()
        self.network.assert_not_called()

    def test_stale_job_does_no_media_or_provider_work(self):
        old = self.url
        self.url = 'https://media.invalid/next.mkv?token=next'
        deep = Mock(side_effect=AssertionError('stale job was executed'))
        with patch.object(self.sub, '_deep_verify', deep):
            self.sub.run_deep_job({
                'key': 'old-key', 'path': str(self.subtitle),
                'playing': 'old-release', 'info': {}, 'stream_url': old})
        deep.assert_not_called()
        self.sub._oracle_candidates.assert_not_called()
        self.cue_reader.assert_not_called()
        self.network.assert_not_called()

    def test_stream_change_during_probe_discards_before_cache_or_share(self):
        old = self.url

        def changed(_info, _playing):
            self.url = 'https://media.invalid/next.mkv?token=next'
            return {'cut_signature': 'cut1:' + 'f' * 32,
                    'cues': [], 'track_cues': []}

        with patch.object(self.sub, '_probe_reference_bundle',
                          side_effect=changed), \
             patch.object(self.sub, '_store_verdict') as store:
            out, verdict = self.sub._deep_verify(
                {'_subsync_stream_url': old}, str(self.subtitle),
                self.subtitle.read_text(encoding='utf-8'), '', 'release', 'key')
        self.assertEqual(out, str(self.subtitle))
        self.assertIsNone(verdict)
        store.assert_not_called()
        self.sub._oracle_candidates.assert_not_called()

    def test_exact_community_verdict_short_circuits_oracle_and_file_judge(self):
        sig = 'cut1:' + '1' * 32
        confirmed = {'status': self.sub.sync_align.STATUS_CONFIRMED,
                     'scale': 1.0, 'offset_ms': 0.0,
                     'diag': 'human exact-cut record'}
        with patch.object(self.sub, '_probe_reference_bundle', return_value={
                'cut_signature': sig, 'cues': [], 'track_cues': []}), \
             patch.object(self.sub, '_community_verdict',
                          return_value=confirmed), \
             patch.object(self.sub, '_verify_file_bundle') as judge:
            out, verdict = self.sub._deep_verify(
                {}, str(self.subtitle), self.subtitle.read_text(encoding='utf-8'),
                '', 'release', 'legacy-key')
        self.assertEqual(out, str(self.subtitle))
        self.assertEqual(verdict['status'], self.sub.sync_align.STATUS_CONFIRMED)
        self.assertTrue(verdict['community'])
        judge.assert_not_called()
        self.sub._oracle_candidates.assert_not_called()

    def test_cached_cues_with_missing_identity_retry_only_tiny_signature(self):
        sig = 'cut1:' + '2' * 32
        confirmed = {'status': self.sub.sync_align.STATUS_CONFIRMED,
                     'scale': 1.0, 'offset_ms': 0.0, 'diag': 'confirmed'}
        store = Mock()
        with patch.object(self.sub, '_probe_reference_bundle', return_value={
                'cut_signature': '', 'cues': [1], 'track_cues': []}), \
             patch.object(self.sub, '_learn_cut_signature',
                          return_value=sig) as learn, \
             patch.object(self.sub, '_community_verdict', return_value=None), \
             patch.object(self.sub, '_verify_file_bundle',
                          return_value=(confirmed, 'FILE', 20)), \
             patch.object(self.sub, '_store_verdict', store):
            _out, verdict = self.sub._deep_verify(
                {}, str(self.subtitle), self.subtitle.read_text(encoding='utf-8'),
                '', 'release', 'legacy-key')
        learn.assert_called_once()
        exact_key = self.sub._cache_key(
            self.subtitle.read_text(encoding='utf-8'), 'release', sig)
        self.assertEqual(verdict['cache_key'], exact_key)
        self.assertEqual(store.call_args.args[0], exact_key)
        self.sub._oracle_candidates.assert_not_called()

    def test_unwritable_queue_never_runs_deep_verify_in_picker_thread(self):
        deep = Mock(side_effect=AssertionError('blocking foreground verify ran'))
        with patch.object(self.sub, 'enabled', return_value=True), \
             patch.object(self.sub, 'playing_release', return_value='release'), \
             patch.object(self.sub, '_known_cut_signature', return_value=''), \
             patch.object(self.sub, '_community_verdict', return_value=None), \
             patch.object(self.sub, '_record_delivery'), \
             patch.object(self.sub, '_enqueue_deep', return_value=False), \
             patch.object(self.sub, '_deep_verify', deep):
            out, verdict = self.sub.process({}, str(self.subtitle), '')
        self.assertEqual(out, str(self.subtitle))
        self.assertEqual(verdict['status'], 'DEFERRED')
        self.assertEqual(self.sub._pending_key(), '')
        deep.assert_not_called()

    def test_fixed_delivery_names_cannot_collide_on_reused_temp_basename(self):
        first = self.sub._write_fixed(str(self.subtitle), 'first fixed text')
        second = self.sub._write_fixed(str(self.subtitle), 'second fixed text')
        self.assertNotEqual(first, second)
        self.assertEqual(Path(first).read_text(encoding='utf-8'),
                         'first fixed text')
        self.assertEqual(Path(second).read_text(encoding='utf-8'),
                         'second fixed text')
        self.assertEqual(self.subtitle.read_text(encoding='utf-8'),
                         '1\n00:00:01,000 --> 00:00:02,000\nHello\n')

    def test_soft_file_probe_nudge_is_refused_but_real_shift_survives(self):
        base = {'status': self.sub.sync_align.STATUS_FIXABLE,
                'mode': 'global', 'scale': 1.0, 'offset_ms': -699.0,
                'diag': 'three-track union synthetic majority'}
        guarded = self.sub._guard_soft_probe_shift(base, 'FILE PROBE')
        self.assertEqual(guarded['status'], self.sub.sync_align.STATUS_UNKNOWN)
        self.assertEqual(guarded['reason'], 'soft_probe_shift')
        # A release-matched oracle still corrects the measured ~1s field case.
        self.assertIs(self.sub._guard_soft_probe_shift(base, 'ORACLE'), base)
        large = dict(base, offset_ms=1800.0)
        self.assertIs(self.sub._guard_soft_probe_shift(
            large, 'FILE PROBE'), large)
        drift = dict(base, scale=1.0173, offset_ms=500.0)
        self.assertIs(self.sub._guard_soft_probe_shift(
            drift, 'FILE PROBE'), drift)

    def test_independent_exact_track_beats_shifted_track_majority(self):
        bundle = {'cues': [{'start': 1500, 'end': 2200}], 'track_cues': [
            {'track': {'num': 2, 'lang': 'eng'},
             'cues': [{'start': 1000, 'end': 1800}] * 10},
            {'track': {'num': 3, 'lang': 'spa'},
             'cues': [{'start': 2000, 'end': 2800}] * 10},
            {'track': {'num': 4, 'lang': 'fra'},
             'cues': [{'start': 3000, 'end': 3800}] * 10},
        ]}

        def judge(cues, _text, **_kw):
            start = cues[0]['start']
            if start == 1000:
                return {'status': self.sub.sync_align.STATUS_CONFIRMED,
                        'scale': 1.0, 'offset_ms': 0.0,
                        'vote': .9, 'overlap': .95, 'diag': 'exact'}
            return {'status': self.sub.sync_align.STATUS_FIXABLE,
                    'mode': 'global', 'scale': 1.0,
                    'offset_ms': float(start), 'vote': .95,
                    'overlap': .95, 'diag': 'shifted'}

        with patch.object(self.sub.sync_align, 'verify_cues', side_effect=judge):
            verdict, label, count = self.sub._verify_file_bundle(bundle, 'srt')
        self.assertEqual(verdict['status'], self.sub.sync_align.STATUS_CONFIRMED)
        self.assertIn('#2', label)
        self.assertEqual(count, 10)

    def test_conflicting_accepted_tracks_abstain_instead_of_union_vote(self):
        profiles = []
        for num, start in ((2, 1000), (3, 3000)):
            profiles.append({'track': {'num': num, 'lang': 'eng'},
                             'cues': [{'start': start, 'end': start + 700}] * 10})
        bundle = {'cues': [{'start': 2000, 'end': 2700}] * 20,
                  'track_cues': profiles}

        def judge(cues, _text, **_kw):
            return {'status': self.sub.sync_align.STATUS_FIXABLE,
                    'mode': 'global', 'scale': 1.0,
                    'offset_ms': float(cues[0]['start']),
                    'vote': .95, 'overlap': .95, 'diag': 'accepted'}

        with patch.object(self.sub.sync_align, 'verify_cues', side_effect=judge) as call:
            verdict, label, count = self.sub._verify_file_bundle(bundle, 'srt')
        self.assertEqual(verdict['status'], self.sub.sync_align.STATUS_UNKNOWN)
        self.assertEqual(verdict['reason'], 'embedded_track_conflict')
        self.assertEqual(call.call_count, 2)  # union was never allowed to decide
        self.assertEqual(count, 0)

    def test_union_of_individually_sparse_tracks_cannot_fabricate_a_fix(self):
        profiles = []
        union = []
        for num, base in ((2, 1000), (3, 2000), (4, 3000)):
            cues = [{'start': base + i * 5000,
                     'end': base + i * 5000 + 700} for i in range(5)]
            profiles.append({'track': {'num': num, 'lang': 'eng'},
                             'cues': cues})
            union.extend(cues)
        bundle = {'cues': union, 'track_cues': profiles}
        with patch.object(self.sub.sync_align, 'verify_cues') as judge:
            verdict, label, count = self.sub._verify_file_bundle(bundle, 'srt')
        self.assertIsNone(verdict)
        self.assertEqual(label, 'FILE TRACKS TOO SPARSE')
        self.assertEqual(count, 0)
        judge.assert_not_called()

    def test_micro_piecewise_requires_a_complete_distinct_codec_family(self):
        def cues(offset=0, count=60):
            return [{'start': 10000 + offset + i * 10000,
                     'end': 11000 + offset + i * 10000}
                    for i in range(count)]

        proposal = {'status': self.sub.sync_align.STATUS_FIXABLE,
                    'mode': 'piecewise', 'scale': 1.0,
                    'offset_ms': 1000.0, 'segments': [
                        {'cand_from_ms': None, 'offset_ms': 1000.0},
                        {'cand_from_ms': 300000.0, 'offset_ms': 2700.0}],
                    'validation_required': True,
                    'validation_folds': 0, 'timing_family_count': 0,
                    'diag': 'synthetic proposal'}
        validated = dict(proposal, validation_folds=5)
        accepted = {'accepted': True, 'before_score': .50,
                    'after_score': .90, 'after_overlap': .90,
                    'after_unique': .80}
        text_profile = {'track': {'num': 3, 'lang': 'eng',
                                  'codec': 'S_TEXT/UTF8',
                                  'name': 'English'},
                        'cues': cues()}
        duplicate_pgs = {'track': {'num': 5, 'lang': 'eng',
                                   'codec': 'S_HDMV/PGS',
                                   'name': 'English'},
                         'cues': cues()}
        distinct_pgs = {'track': {'num': 6, 'lang': 'eng',
                                  'codec': 'S_HDMV/PGS',
                                  'name': 'English'},
                        'cues': cues(offset=1000)}
        short_text = {'track': {'num': 2, 'lang': 'eng',
                                'codec': 'S_TEXT/UTF8',
                                'name': 'English'},
                      'cues': cues(count=20)}

        with patch.object(self.sub.sync_align, 'micro_piecewise_proposal',
                          return_value=proposal), \
             patch.object(self.sub.sync_align, 'validate_micro_piecewise',
                          return_value=validated), \
             patch.object(self.sub.sync_align, 'evaluate_piecewise_family',
                          return_value=accepted) as family:
            self.assertIsNone(self.sub._validated_micro_piecewise(
                [text_profile, duplicate_pgs], self.subtitle.read_text()))
            family.assert_not_called()
            result = self.sub._validated_micro_piecewise(
                [short_text, text_profile, distinct_pgs],
                self.subtitle.read_text())

        self.assertIsNotNone(result)
        self.assertEqual(result['verdict']['validation_folds'], 5)
        self.assertEqual(result['verdict']['timing_family_count'], 2)
        self.assertEqual(result['track']['num'], 3)

    def test_file_bundle_uses_validated_micro_path_and_exact_track_veto(self):
        cues = [{'start': 10000 + i * 10000,
                 'end': 11000 + i * 10000} for i in range(12)]
        bundle = {'track_cues': [
            {'track': {'num': 3, 'lang': 'eng',
                       'codec': 'S_TEXT/UTF8'}, 'cues': cues},
            {'track': {'num': 5, 'lang': 'eng',
                       'codec': 'S_HDMV/PGS'}, 'cues': cues},
        ]}
        piecewise = {'status': self.sub.sync_align.STATUS_FIXABLE,
                     'mode': 'piecewise', 'scale': 1.0,
                     'offset_ms': 1000.0, 'validation_required': True,
                     'validation_folds': 5, 'timing_family_count': 2,
                     'segments': [{'cand_from_ms': None,
                                   'offset_ms': 1000.0}],
                     'diag': 'validated path'}
        validated = {'track': bundle['track_cues'][0]['track'],
                     'cues': cues, 'verdict': piecewise}
        unknown = {'status': self.sub.sync_align.STATUS_UNKNOWN,
                   'diag': 'no flat map'}
        with patch.object(self.sub, '_validated_micro_piecewise',
                          return_value=validated), \
             patch.object(self.sub.sync_align, 'verify_cues',
                          return_value=unknown):
            verdict, label, count = self.sub._verify_file_bundle(bundle, 'srt')
        self.assertIs(verdict, piecewise)
        self.assertIn('VALIDATED', label)
        self.assertEqual(count, len(cues))

        exact = {'status': self.sub.sync_align.STATUS_CONFIRMED,
                 'scale': 1.0, 'offset_ms': 0.0,
                 'vote': .9, 'overlap': .95, 'diag': 'exact track'}
        with patch.object(self.sub, '_validated_micro_piecewise',
                          return_value=validated), \
             patch.object(self.sub.sync_align, 'verify_cues',
                          side_effect=[unknown, exact]):
            verdict, label, _count = self.sub._verify_file_bundle(bundle, 'srt')
        self.assertEqual(verdict['status'], self.sub.sync_align.STATUS_CONFIRMED)
        self.assertIn('#5', label)

    def test_exact_cut_scopes_cache_and_existing_worker_release_key(self):
        text = self.subtitle.read_text(encoding='utf-8')
        sig_a = 'cut1:' + 'a' * 32
        sig_b = 'cut1:' + 'b' * 32
        key_a = self.sub._cache_key(text, 'same release', sig_a)
        key_b = self.sub._cache_key(text, 'same release', sig_b)
        self.assertNotEqual(key_a, key_b)
        self.assertTrue(key_a.endswith('|' + sig_a))
        reg_a = self.sub._sync_registry_release('same release', sig_a)
        reg_b = self.sub._sync_registry_release('same release', sig_b)
        self.assertNotEqual(reg_a, reg_b)
        self.assertIn('POVILCUT', reg_a)

    def test_same_subtitle_keeps_independent_fixes_for_two_video_cuts(self):
        """A correction learned for one stream must never overwrite another.

        This is the real user flow: the same subtitle is selected against two
        encodes with different timing and then the first encode is opened
        again.  Each delivery must resolve through its content-scoped verdict.
        """
        text = '1\n00:00:10,000 --> 00:00:11,000\nHello\n'
        self.subtitle.write_text(text, encoding='utf-8')
        sig_a = 'cut1:' + 'a' * 32
        sig_b = 'cut1:' + 'b' * 32
        key_a = self.sub._cache_key(text, 'same visible release', sig_a)
        key_b = self.sub._cache_key(text, 'same visible release', sig_b)
        verdicts = {
            key_a: {'v': self.sub._VERDICT_VERSION,
                    'status': self.sub.sync_align.STATUS_FIXABLE,
                    'scale': 1.0, 'offset_ms': -1000.0,
                    'mode': 'global', 'diag': 'cut A'},
            key_b: {'v': self.sub._VERDICT_VERSION,
                    'status': self.sub.sync_align.STATUS_FIXABLE,
                    'scale': 1.0, 'offset_ms': 2000.0,
                    'mode': 'global', 'diag': 'cut B'},
        }
        with patch.object(self.sub, 'enabled', return_value=True), \
             patch.object(self.sub, 'playing_release',
                          return_value='same visible release'), \
             patch.object(self.sub, '_known_cut_signature',
                          side_effect=[sig_a, sig_b, sig_a]), \
             patch.object(self.sub, '_load_verdicts', return_value=verdicts):
            out_a1, result_a1 = self.sub.process({}, str(self.subtitle), '')
            out_b, result_b = self.sub.process({}, str(self.subtitle), '')
            out_a2, result_a2 = self.sub.process({}, str(self.subtitle), '')

        self.assertNotEqual(key_a, key_b)
        self.assertEqual(Path(out_a1).read_text(encoding='utf-8'),
                         '1\n00:00:11,000 --> 00:00:12,000\nHello\n')
        self.assertEqual(Path(out_b).read_text(encoding='utf-8'),
                         '1\n00:00:08,000 --> 00:00:09,000\nHello\n')
        self.assertEqual(Path(out_a2).read_text(encoding='utf-8'),
                         Path(out_a1).read_text(encoding='utf-8'))
        self.assertEqual(out_a2, out_a1)
        self.assertNotEqual(out_b, out_a1)
        self.assertTrue(result_a1['cached'] and result_a1['applied'])
        self.assertTrue(result_b['cached'] and result_b['applied'])
        self.assertTrue(result_a2['cached'] and result_a2['applied'])

    def test_human_fix_is_stored_only_for_a_matching_exact_cut_key(self):
        sig = 'cut1:' + 'c' * 32
        key = '0123456789abcdef|' + sig
        report = {'cache_key': key, 'cut_signature': sig,
                  'status': self.sub.sync_align.STATUS_FIXABLE,
                  'scale': 1.0, 'offset_ms': 1250.0,
                  'mode': 'global'}
        with patch.object(self.sub, '_store_verdict') as store:
            self.assertTrue(self.sub.store_human_verdict(report))
        self.assertEqual(store.call_args.args[0], key)
        with patch.object(self.sub, '_store_verdict') as store:
            self.assertFalse(self.sub.store_human_verdict(
                dict(report, cache_key='0123456789abcdef|other')))
        store.assert_not_called()

    def test_manual_delay_learning_requires_and_preserves_exact_cut(self):
        sig = 'cut1:' + '9' * 32
        record = {'key': 'subtitlehash|' + sig, 'playing': 'release',
                  'scale': 1.0, 'offset': 500.0,
                  'mode': 'global',
                  'cut_signature': sig, 'info': {'tmdb_id': '1'}}
        report = self.sub.finalize_delay_session(record, 1.0, 300)
        self.assertEqual(report['status'], self.sub.sync_align.STATUS_FIXABLE)
        self.assertEqual(report['offset_ms'], -500.0)
        self.assertEqual(report['cut_signature'], sig)
        self.assertEqual(report['cache_key'], record['key'])
        self.assertIsNone(self.sub.finalize_delay_session(
            dict(record, cut_signature=''), 1.0, 300))
        self.assertIsNone(self.sub.finalize_delay_session(
            dict(record, key='subtitlehash|different'), 1.0, 300))
        self.assertIsNone(self.sub.finalize_delay_session(
            dict(record, mode='piecewise'), 1.0, 300))
        self.assertIsNone(self.sub.finalize_delay_session(
            dict(record, mode=None), 1.0, 300))

    def test_unfingerprinted_auto_verdict_is_not_persisted_or_shared(self):
        confirmed = {'status': self.sub.sync_align.STATUS_CONFIRMED,
                     'scale': 1.0, 'offset_ms': 0.0, 'diag': 'file exact'}
        fake_pool = types.ModuleType('resources.lib.pool')
        fake_pool.report_sync = Mock()
        with patch.dict(sys.modules, {'resources.lib.pool': fake_pool}), \
             patch.object(self.sub, '_probe_reference_bundle', return_value={
                 'cut_signature': '', 'cues': [1], 'track_cues': []}), \
             patch.object(self.sub, '_verify_file_bundle',
                          return_value=(confirmed, 'FILE', 20)), \
             patch.object(self.sub, '_store_verdict') as store:
            out, verdict = self.sub._deep_verify(
                {}, str(self.subtitle), self.subtitle.read_text(encoding='utf-8'),
                '', 'release', 'legacy-key')
        self.assertEqual(out, str(self.subtitle))
        self.assertEqual(verdict['status'], self.sub.sync_align.STATUS_CONFIRMED)
        store.assert_not_called()
        fake_pool.report_sync.assert_not_called()

    def test_autosub_promotes_only_a_cached_human_candidate_proven_synced(self):
        def candidate(name):
            payload = {'type': 'engine', 'source': 'Ktuvit',
                       'language': 'Hebrew', 'filename': name}
            return {'filename': name, 'language': 'he',
                    'link': urllib.parse.quote(json.dumps(payload))}

        first, second = candidate('first'), candidate('second')
        ready = [(self.subtitle.read_text(), self.sub._decode_link(first['link'])),
                 (self.subtitle.read_text(), self.sub._decode_link(second['link']))]
        fixable = {'status': self.sub.sync_align.STATUS_FIXABLE,
                   'mode': 'global', 'scale': 1.0, 'offset_ms': 2200.0,
                   'vote': .9, 'overlap': .9, 'diag': 'fixable'}
        confirmed = {'status': self.sub.sync_align.STATUS_CONFIRMED,
                     'scale': 1.0, 'offset_ms': 0.0,
                     'vote': .9, 'overlap': .95, 'diag': 'confirmed'}
        with patch.object(self.sub, '_cached_reference_bundle',
                          return_value={'cues': [1]}), \
             patch.object(self.sub, 'playing_release', return_value='movie'), \
             patch.object(self.sub, '_ready_candidate_text', side_effect=ready), \
             patch.object(self.sub, '_verify_file_bundle', side_effect=[
                 (fixable, 'track 2', 20),
                 (confirmed, 'track 3', 20)]):
            out = self.sub.rank_ready_candidates({}, [first, second])
        self.assertEqual([x['filename'] for x in out], ['second', 'first'])

    def test_candidate_timing_rank_reads_cache_only_and_never_downloads(self):
        from resources.lib import subs_engine_bridge as bridge
        from resources.lib import translate
        engine_payload = {'type': 'engine', 'source': 'Ktuvit',
                          'language': 'Hebrew', 'filename': 'cached.srt'}
        engine = {'language': 'he', 'filename': 'cached.srt',
                  'link': urllib.parse.quote(json.dumps(engine_payload))}
        with patch.object(bridge, 'cached_source',
                          return_value=str(self.subtitle)) as cached, \
             patch.object(bridge, 'download') as download:
            text, payload = self.sub._ready_candidate_text({}, engine)
        self.assertIn('Hello', text)
        self.assertEqual(payload['source'], 'Ktuvit')
        cached.assert_called_once()
        download.assert_not_called()

        pool_payload = {'type': 'pool', 'pool_kind': 'ktuvit',
                        'hash': 'a' * 16, 'filename': 'pool.srt'}
        pool_candidate = {
            'language': 'he', 'filename': 'pool.srt',
            'link': urllib.parse.quote(json.dumps(pool_payload))}
        with patch.object(translate, '_pool_source_text',
                          return_value=(self.subtitle.read_text(), 'id')) as read:
            text, payload = self.sub._ready_candidate_text({}, pool_candidate)
        self.assertIn('Hello', text)
        self.assertTrue(read.call_args.kwargs['cache_only'])

    def test_new_trusted_delivery_invalidates_old_background_swap(self):
        old_key = 'old-subtitle-key'
        self.window_props[self.sub._PENDING_PROP] = json.dumps(
            {'key': old_key, 'ts': 1})
        playing = 'Movie.2026.1080p.WEB-DL'
        tier = next(iter(self.sub.release_match.AUTO_OK_TIERS))
        with patch.object(self.sub, 'enabled', return_value=True), \
             patch.object(self.sub, 'playing_release', return_value=playing), \
             patch.object(self.sub.release_match, 'score',
                          return_value=(100, tier, {})), \
             patch.object(self.sub, '_record_delivery'):
            out, verdict = self.sub.process(
                {}, str(self.subtitle), playing)
        self.assertEqual(out, str(self.subtitle))
        self.assertEqual(verdict['status'], self.sub._STATUS_TRUSTED)
        self.assertEqual(self.sub._pending_key(), '')

        xbmc = sys.modules['xbmc']
        setter = Mock()
        player = types.SimpleNamespace(
            isPlaying=lambda: True,
            getPlayingFile=lambda: self.url,
            setSubtitles=setter)
        with patch.object(xbmc, 'Player', return_value=player):
            self.assertFalse(self.real_swap_if_current(
                {'key': old_key, 'stream_url': self.url},
                'old-fixed.srt', {}))
        setter.assert_not_called()

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
