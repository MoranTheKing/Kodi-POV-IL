"""SubSync's remote path is restricted to the compact Matroska Cues reader.

Exercise real deep verification/service paths.  The heavy cluster/audio probes
must stay local-only; remote playback may call only embedded_extract's bounded,
keep-alive cue-index API after playback is stable.
"""
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
import urllib.parse
from unittest.mock import Mock, call, patch

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
        self.successful_status = []

        def _status_update(state, source='', selection_token='',
                           link_hash='', stream_hash='', **_kwargs):
            accepted = self._selection_matches(
                selection_token, link_hash, stream_hash)
            if accepted:
                self.successful_status.append((state, source))
            return accepted

        self.status_update = Mock(side_effect=_status_update)
        ku.set_subtitle_sync_status = self.status_update
        ku.stage_subtitle_sync_fix = Mock(return_value=True)
        ku.stage_subtitle_delivery = Mock(return_value=True)
        ku.subtitle_delivery_is_applied = Mock(return_value=True)
        ku.clear_subtitle_delivery = Mock(return_value=True)
        self.selection = {
            'token': 'selection-token-A',
            'link_hash': 'selection-link-A',
        }
        ku.current_subtitle_selection = self._selection_snapshot
        ku.subtitle_selection_matches = self._selection_matches
        ku.get_subtitle_selection_token = lambda: self.selection['token']
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

    def _stream_hash(self, url=None):
        value = (self.url if url is None else url).strip()
        return hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]

    def _selection_snapshot(self):
        return {
            'token': self.selection['token'],
            'link_hash': self.selection['link_hash'],
            'stream_hash': self._stream_hash(),
        }

    def _selection_matches(self, token='', link_hash='', stream_hash=''):
        current = self._selection_snapshot()
        return bool(token and link_hash and stream_hash
                    and token == current['token']
                    and link_hash == current['link_hash']
                    and stream_hash == current['stream_hash'])

    def _bound_job(self, **values):
        selection = self._selection_snapshot()
        job = {
            'selection_token': selection['token'],
            'selection_hash': selection['link_hash'],
            'stream_hash': selection['stream_hash'],
            'stream_url': self.url,
        }
        job.update(values)
        return job

    def _set_pending_for(self, job, key=None):
        selection = {
            'token': job.get('selection_token') or '',
            'link_hash': job.get('selection_hash') or '',
            'stream_hash': job.get('stream_hash') or '',
        }
        self.window_props[self.sub._pending_prop(selection)] = json.dumps({
            'key': key if key is not None else job.get('key', ''),
            'ts': 1,
            'selection_token': job.get('selection_token') or '',
            'selection_hash': job.get('selection_hash') or '',
            'stream_hash': job.get('stream_hash') or '',
        })

    def test_remote_missing_oracle_uses_only_bounded_cue_reader(self):
        out, verdict = self.sub._deep_verify({}, str(self.subtitle), self.subtitle.read_text(),
                                            'sub-release', 'movie-release', 'key')
        self.assertEqual(out, str(self.subtitle))
        self.assertEqual(verdict['status'], self.sub._STATUS_NO_ORACLE)
        self.cue_reader.assert_called_once()
        self.network.assert_not_called()

    def test_queued_service_job_without_oracle_keeps_original_on_cue_miss(self):
        job = self._bound_job(
            key='key', path=str(self.subtitle),
            playing='movie-release', info={})
        self._set_pending_for(job)
        self.sub.run_deep_job(job)
        self.sub._oracle_candidates.assert_called_once()
        self.cue_reader.assert_called_once()
        self.network.assert_not_called()
        self.sub._swap_if_current.assert_not_called()
        self.sub._announce.assert_not_called()

    def test_deep_worker_waits_for_foreground_delivery_ack(self):
        job = self._bound_job(
            key='ack-key', path=str(self.subtitle),
            playing='movie-release', info={})
        self._set_pending_for(job)
        ku = sys.modules['resources.lib.kodi_utils']
        ku.subtitle_delivery_is_applied.return_value = False
        with patch.object(self.sub, '_deep_verify') as verify:
            self.sub.run_deep_job(job)
        verify.assert_not_called()
        self.sub._swap_if_current.assert_not_called()
        self.assertIn(('unverified', 'delivery'), self.successful_status)

    def test_deep_worker_proceeds_only_after_exact_delivery_ack(self):
        job = self._bound_job(
            key='ack-key', path=str(self.subtitle),
            playing='movie-release', info={})
        self._set_pending_for(job)
        verdict = {'status': self.sub.sync_align.STATUS_CONFIRMED,
                   'cache_key': 'ack-key', 'diag': 'confirmed'}
        ku = sys.modules['resources.lib.kodi_utils']
        ku.subtitle_delivery_is_applied.return_value = True
        with patch.object(self.sub, '_deep_verify',
                          return_value=(str(self.subtitle), verdict)) as verify, \
             patch.object(self.sub, '_record_delivery'):
            self.sub.run_deep_job(job)
        verify.assert_called_once()

    def test_worker_starting_first_cannot_leave_original_over_false_fixed(self):
        """Sabotage the old order: service starts before foreground delivery."""
        job = self._bound_job(
            key='race-key', path=str(self.subtitle),
            playing='movie-release', info={})
        self._set_pending_for(job)
        fixed = self.root / 'fixed.srt'
        fixed.write_text(
            '1\n00:00:02,000 --> 00:00:03,000\nHello\n',
            encoding='utf-8')
        verdict = {
            'status': self.sub.sync_align.STATUS_FIXABLE,
            'applied': True, 'cache_key': 'race-key',
            'mode': 'global', 'scale': 1.0, 'offset_ms': 1000.0,
            'diag': 'synthetic race fix'}
        ack = {'ready': False}
        streams = ['embedded']
        active = {'path': ''}
        order = []

        def add(path):
            streams.append(path)
            active['path'] = path
            order.append(path)

        def pin(index):
            active['path'] = streams[index]

        player = types.SimpleNamespace(
            isPlaying=lambda: True, isPlayingVideo=lambda: True,
            getPlayingFile=lambda: self.url,
            getAvailableSubtitleStreams=lambda: list(streams),
            setSubtitles=add, showSubtitles=lambda _on: None,
            setSubtitleStream=pin)
        ku = sys.modules['resources.lib.kodi_utils']
        ku.subtitle_delivery_is_applied.side_effect = (
            lambda *_a, **_k: ack['ready'])

        def foreground_finishes(_ms):
            if not ack['ready']:
                add(str(self.subtitle))
                pin(len(streams) - 1)
                ack['ready'] = True

        xbmc = sys.modules['xbmc']
        with patch.object(xbmc, 'Player', return_value=player), \
             patch.object(xbmc, 'sleep', side_effect=foreground_finishes), \
             patch.object(self.sub, '_deep_verify',
                          return_value=(str(fixed), verdict)), \
             patch.object(self.sub, '_swap_if_current',
                          new=self.real_swap_if_current), \
             patch.object(self.sub, '_record_delivery'):
            self.sub.run_deep_job(job)

        self.assertEqual(order, [str(self.subtitle), str(fixed)])
        self.assertEqual(active['path'], str(fixed))
        self.assertIn(('fixed', 'local'), self.successful_status)

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
        job = self._bound_job(
            key='legacy-key', path=str(self.subtitle),
            playing='movie-release', info={})
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
        job = self._bound_job(
            key=key, path=str(self.subtitle), playing='movie-release',
            info={}, identity_only=True)
        self._set_pending_for(job)
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
        self.assertEqual(self.sub._pending_key(), key)
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
        self.assertFalse(self.sub._pending_key())
        sys.modules['resources.lib.kodi_utils'].clear_subtitle_delivery \
            .assert_called_once()
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
        def cues(offset=0, count=60, stride=10000):
            return [{'start': 10000 + offset + i * stride,
                     'end': 11000 + offset + i * stride}
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
                        'cues': cues(offset=1000, stride=10200)}
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

    def test_provider_piecewise_requires_two_independent_rebuilt_maps(self):
        def cues(delta=0, stride=10000):
            return [{'start': 10000 + delta + i * stride + (i % 3) * 170,
                     'end': 11000 + delta + i * stride + (i % 3) * 170}
                    for i in range(60)]

        primary = {
            'release': 'Show.S01E01.720p.BluRay.x264-DEMAND',
            'language': 'en', 'payload': {'id': 'primary'}}
        clone = {
            'release': 'Show.S01E01.720p.BluRay.x264-DEMAND',
            'language': 'it', 'payload': {'id': 'clone'}}
        independent = {
            'release': 'Show.S01E01.1080p.BluRay.x264-ROVERS',
            'language': 'ro', 'payload': {'id': 'independent'}}
        playing = 'Show.S01E01.1080p.BluRay.x265-NOGRP.mkv'
        proposal = {
            'status': self.sub.sync_align.STATUS_FIXABLE,
            'mode': 'piecewise', 'scale': 1.0, 'offset_ms': -700.0,
            'segments': [{'cand_from_ms': None, 'offset_ms': -700.0},
                         {'cand_from_ms': 300000.0,
                          'offset_ms': 1000.0}],
            'validation_required': True, 'validation_folds': 0,
            'timing_family_count': 0, 'diag': 'proposal'}
        validated = dict(proposal, validation_folds=5)
        accepted = {'accepted': True, 'before_score': .50,
                    'after_score': .92, 'after_overlap': .95,
                    'after_unique': .86}
        parsed = {
            'primary-text': cues(),
            'clone-text': cues(),
            'independent-text': cues(delta=700, stride=11300),
        }

        with patch.object(self.sub, '_download_oracle', side_effect=lambda p: {
                    'clone': 'clone-text',
                    'independent': 'independent-text'}.get(p.get('id'), '')), \
             patch.object(self.sub.sync_align, 'parse_srt',
                          side_effect=lambda value: parsed[value]), \
             patch.object(self.sub.sync_align, 'dialogue_cues',
                          side_effect=lambda value: value), \
             patch.object(self.sub.sync_align, 'micro_piecewise_proposal',
                          return_value=proposal), \
             patch.object(self.sub.sync_align, 'validate_micro_piecewise',
                          return_value=validated) as validate, \
             patch.object(self.sub.sync_align, 'piecewise_maps_agree',
                          return_value=True), \
             patch.object(self.sub.sync_align, 'evaluate_piecewise_family',
                          return_value=accepted) as family:
            result = self.sub._validated_oracle_piecewise(
                [primary, clone, independent], playing, 'candidate-text',
                primary, 'primary-text')

        self.assertIsNotNone(result)
        self.assertEqual(result['verdict']['timing_family_count'], 2)
        self.assertEqual(result['verdict']['validation_folds'], 5)
        self.assertEqual(result['verdict']['validation_secondary_folds'], 5)
        self.assertEqual(result['secondary'], independent)
        # Only the genuinely different family reached its own holdout proof;
        # exact timing clones can never manufacture a second vote.
        self.assertEqual(validate.call_count, 2)
        family.assert_called_once()

    def test_provider_candidates_are_interleaved_by_release_family(self):
        def item(name, group, pct):
            return ({'release': name, 'payload': {'id': name}},
                    self.sub.release_match.TIER_SOURCE, pct, group, 1)

        ranked = [
            item('ROVERS-nl', 'rovers', 90),
            item('ROVERS-sv', 'rovers', 89),
            item('ROVERS-ro', 'rovers', 88),
            item('RSG-de', 'rsg', 80),
            item('TRIM-id', 'trim', 70),
        ]
        diversified = self.sub._diversify_oracle_matches(ranked)
        self.assertEqual(
            [row[0]['release'] for row in diversified],
            ['ROVERS-nl', 'RSG-de', 'TRIM-id',
             'ROVERS-sv', 'ROVERS-ro'])

    def test_provider_piecewise_expands_beyond_visible_languages_once(self):
        """The picker language filter must not hide the only safe second family."""
        primary = {'release': 'Show.S01E01.BluRay-DEMAND',
                   'language': 'en', 'payload': {'id': 'primary'}}
        visible_clone = {'release': 'Show.S01E01.BluRay-ROVERS',
                         'language': 'nl', 'payload': {'id': 'nl'}}
        independent = {'release': 'Show.S01E01.BluRay-ROVERS',
                       'language': 'ro', 'payload': {'id': 'ro'}}
        visible = [primary, visible_clone]
        expanded = [primary, visible_clone, independent]
        accepted = {'verdict': {'status': 'FIXABLE'},
                    'secondary': independent, 'downloads': 1}

        with patch.object(self.sub, '_validated_oracle_piecewise',
                          side_effect=[None, accepted]) as validate, \
             patch.object(self.sub, '_oracle_candidates',
                          return_value=expanded) as scan:
            result = self.sub._provider_piecewise_rescue(
                {}, visible, 'Show.S01E01.BluRay-RARBG',
                'candidate-text', primary, 'primary-text')

        self.assertEqual(result, accepted)
        self.assertEqual(scan.call_count, 1)
        self.assertEqual(scan.call_args.args, ({},))
        self.assertTrue(scan.call_args.kwargs['all_languages'])
        self.assertIsInstance(scan.call_args.kwargs['search_state'], dict)
        self.assertEqual(validate.call_count, 2)
        self.assertEqual(list(validate.call_args_list[0].args[0]), visible)
        self.assertEqual(list(validate.call_args_list[1].args[0]),
                         [independent])

    def test_provider_piecewise_does_not_repeat_when_expansion_adds_nothing(self):
        primary = {'release': 'Show.S01E01.BluRay-DEMAND',
                   'language': 'en', 'payload': {'id': 'primary'}}
        visible = [primary]
        with patch.object(self.sub, '_validated_oracle_piecewise',
                          return_value=None) as validate, \
             patch.object(self.sub, '_oracle_candidates',
                          return_value=list(visible)):
            result = self.sub._provider_piecewise_rescue(
                {}, visible, 'Show.S01E01.BluRay-RARBG',
                'candidate-text', primary, 'primary-text')
        self.assertIsNone(result)
        validate.assert_called_once()

    def test_transient_all_language_search_is_propagated(self):
        primary = {'release': 'Show.S01E01.BluRay-DEMAND',
                   'language': 'en', 'payload': {'id': 'primary'}}

        def transient(_info, **kwargs):
            kwargs['search_state']['transient'] = True
            return []

        state = {}
        with patch.object(self.sub, '_validated_oracle_piecewise',
                          return_value=None), \
             patch.object(self.sub, '_oracle_candidates',
                          side_effect=transient):
            result = self.sub._provider_piecewise_rescue(
                {}, [primary], 'Show.S01E01.BluRay-RARBG',
                'candidate-text', primary, 'primary-text',
                search_state=state)
        self.assertIsNone(result)
        self.assertTrue(state.get('transient'))

    def test_transient_expansion_unknown_is_not_cached(self):
        sig = 'cut1:' + '9' * 32
        unknown = {'status': self.sub.sync_align.STATUS_UNKNOWN,
                   'diag': 'ordinary oracle could not prove timing'}
        primary = {'release': 'Movie.2026.BluRay-DEMAND',
                   'payload': {'id': 'primary'}, 'language': 'en'}

        def transient_rescue(*_args, **kwargs):
            kwargs['search_state']['transient'] = True
            return None

        with patch.object(self.sub, '_probe_reference_bundle', return_value={
                'cut_signature': sig, 'cues': [], 'track_cues': []}), \
             patch.object(self.sub, '_community_verdict', return_value=None), \
             patch.object(self.sub, '_verify_file_bundle',
                          return_value=(None, 'NONE', 0)), \
             patch.object(self.sub, '_oracle_candidates',
                          return_value=[primary]), \
             patch.object(self.sub.sync_align, 'pick_oracle',
                          return_value=(primary,
                              self.sub.release_match.TIER_GROUP)), \
             patch.object(self.sub, '_download_oracle',
                          return_value='primary-text'), \
             patch.object(self.sub.sync_align, 'verify_and_fix',
                          return_value=(self.subtitle.read_text(), unknown)), \
             patch.object(self.sub, '_provider_piecewise_rescue',
                          side_effect=transient_rescue), \
             patch.object(self.sub, '_audio_probe_reference',
                          return_value=None), \
             patch.object(self.sub, '_store_verdict') as store:
            out, verdict = self.sub._deep_verify(
                {}, str(self.subtitle), self.subtitle.read_text(),
                'sub-release', 'Movie.2026.BluRay.mkv', 'legacy-key')
        self.assertEqual(out, str(self.subtitle))
        self.assertEqual(verdict['status'], self.sub.sync_align.STATUS_UNKNOWN)
        store.assert_not_called()

    def test_provider_piecewise_visible_conflict_vetoes_expanded_agreement(self):
        def cues(stride):
            return [{'start': 10000 + i * stride,
                     'end': 11200 + i * stride} for i in range(60)]

        primary = {'release': 'Primary-DEMAND', 'language': 'en',
                   'payload': {'id': 'primary'}}
        conflict = {'release': 'Visible-ROVERS', 'language': 'nl',
                    'payload': {'id': 'conflict'}}
        agreeable = {'release': 'Expanded-SPARKS', 'language': 'ro',
                     'payload': {'id': 'agree'}}
        map_a = {
            'status': self.sub.sync_align.STATUS_FIXABLE,
            'mode': 'piecewise', 'scale': 1.0, 'offset_ms': -700.0,
            'segments': [{'cand_from_ms': None, 'offset_ms': -700.0}],
            'validation_required': True, 'validation_folds': 5,
            'timing_family_count': 0, 'diag': 'map A'}
        map_b = dict(map_a, offset_ms=1700.0,
                     segments=[{'cand_from_ms': None,
                                'offset_ms': 1700.0}], diag='map B')
        parsed = {'primary-text': cues(10000),
                  'conflict-text': cues(11300),
                  'agree-text': cues(12700)}
        downloads = []

        def ranked(rows, _playing):
            out = []
            for row in rows:
                if row is conflict:
                    out.append((row, self.sub.release_match.TIER_GROUP,
                                50, 'rovers', 2))
                elif row is agreeable:
                    out.append((row, self.sub.release_match.TIER_GROUP,
                                99, 'sparks', 2))
            return out

        def download(payload):
            downloads.append(payload.get('id'))
            return {'conflict': 'conflict-text',
                    'agree': 'agree-text'}.get(payload.get('id'), '')

        with patch.object(self.sub, '_oracle_match', side_effect=ranked), \
             patch.object(self.sub, '_download_oracle',
                          side_effect=download), \
             patch.object(self.sub.sync_align, 'parse_srt',
                          side_effect=lambda value: parsed[value]), \
             patch.object(self.sub.sync_align, 'dialogue_cues',
                          side_effect=lambda value: value), \
             patch.object(self.sub.sync_align, 'micro_piecewise_proposal',
                          side_effect=[map_a, map_b]), \
             patch.object(self.sub.sync_align, 'validate_micro_piecewise',
                          side_effect=[map_a, map_b]), \
             patch.object(self.sub.sync_align, 'piecewise_maps_agree',
                          return_value=False), \
             patch.object(self.sub.sync_align, 'evaluate_piecewise_family') \
                     as family, \
             patch.object(self.sub, '_oracle_candidates',
                          return_value=[agreeable]) as expansion:
            result = self.sub._provider_piecewise_rescue(
                {}, [primary, conflict], 'Playing.BluRay.mkv',
                'candidate-text', primary, 'primary-text')
        self.assertIsNone(result)
        self.assertEqual(downloads, ['conflict'])
        expansion.assert_not_called()
        family.assert_not_called()

    def test_provider_piecewise_failed_downloads_do_not_consume_evidence_slots(self):
        """A dead provider row is no evidence and may not hide a later family.

        The field report had six high-ranked BluRay rows, but only three could
        actually be read on the device; the independent Romanian row sat after
        failed/duplicate results.  The old loop spent its six-download budget
        before it reached usable independent evidence.
        """
        def cues(delta=0, stride=10000):
            return [{'start': 10000 + delta + i * stride,
                     'end': 11000 + delta + i * stride}
                    for i in range(60)]

        primary = {
            'release': 'Show.S01E01.720p.BluRay.x264-DEMAND',
            'language': 'en', 'payload': {'id': 'primary'}}
        dead = [
            {'release': 'Show.S01E01.1080p.BluRay.x264-G%02d' % i,
             'language': 'x%02d' % i, 'payload': {'id': 'dead-%02d' % i}}
            for i in range(6)
        ]
        independent = {
            'release': 'Show.S01E01.1080p.BluRay.x264-ROVERS',
            'language': 'ro', 'payload': {'id': 'independent'}}
        proposal = {
            'status': self.sub.sync_align.STATUS_FIXABLE,
            'mode': 'piecewise', 'scale': 1.0, 'offset_ms': -700.0,
            'segments': [{'cand_from_ms': None, 'offset_ms': -700.0}],
            'validation_required': True, 'validation_folds': 5,
            'timing_family_count': 0, 'diag': 'proven'}
        accepted = {'accepted': True, 'before_score': .50,
                    'after_score': .93, 'after_overlap': .96,
                    'after_unique': .88}
        ranked = [
            (row, self.sub.release_match.TIER_SOURCE, 60 - i,
             'g%02d' % i, 1) for i, row in enumerate(dead)
        ] + [(independent, self.sub.release_match.TIER_SOURCE,
              50, 'rovers', 1)]

        with patch.object(self.sub, '_oracle_match', return_value=ranked), \
             patch.object(self.sub, '_download_oracle',
                          side_effect=lambda p: (
                              'independent-text'
                              if p.get('id') == 'independent' else '')), \
             patch.object(self.sub.sync_align, 'parse_srt',
                          side_effect=lambda value: (
                              cues(stride=11300) if value == 'independent-text'
                              else cues())), \
             patch.object(self.sub.sync_align, 'dialogue_cues',
                          side_effect=lambda value: value), \
             patch.object(self.sub.sync_align, 'micro_piecewise_proposal',
                          return_value=proposal), \
             patch.object(self.sub.sync_align, 'validate_micro_piecewise',
                          return_value=proposal), \
             patch.object(self.sub.sync_align, 'piecewise_maps_agree',
                          return_value=True), \
             patch.object(self.sub.sync_align, 'evaluate_piecewise_family',
                          return_value=accepted):
            result = self.sub._validated_oracle_piecewise(
                dead + [independent],
                'Show.S01E01.1080p.BluRay.x265-NOGRP.mkv',
                'candidate-text', primary, 'primary-text')

        self.assertIsNotNone(result)
        self.assertEqual(result['secondary'], independent)
        self.assertEqual(result['downloads'], 1)

    def test_provider_piecewise_non_srt_responses_do_not_consume_evidence_slots(self):
        """A 200/HTML provider error is a fetch, but never timing evidence."""
        def cues(delta=0, stride=10000):
            return [{'start': 10000 + delta + i * stride,
                     'end': 11000 + delta + i * stride}
                    for i in range(60)]

        primary = {
            'release': 'Show.S01E01.720p.BluRay.x264-DEMAND',
            'language': 'en', 'payload': {'id': 'primary'}}
        invalid = [
            {'release': 'Show.S01E01.1080p.BluRay.x264-BAD%02d' % i,
             'language': 'x%02d' % i,
             'payload': {'id': 'invalid-%02d' % i}}
            for i in range(6)
        ]
        independent = {
            'release': 'Show.S01E01.1080p.BluRay.x264-ROVERS',
            'language': 'ro', 'payload': {'id': 'good'}}
        proposal = {
            'status': self.sub.sync_align.STATUS_FIXABLE,
            'mode': 'piecewise', 'scale': 1.0, 'offset_ms': -700.0,
            'segments': [{'cand_from_ms': None, 'offset_ms': -700.0}],
            'validation_required': True, 'validation_folds': 5,
            'timing_family_count': 0, 'diag': 'proven'}
        accepted = {'accepted': True, 'before_score': .50,
                    'after_score': .93, 'after_overlap': .96,
                    'after_unique': .88}
        ranked = [
            (row, self.sub.release_match.TIER_SOURCE, 60 - i,
             'bad%02d' % i, 1) for i, row in enumerate(invalid)
        ] + [(independent, self.sub.release_match.TIER_SOURCE,
              50, 'rovers', 1)]
        calls = []

        def download(payload):
            calls.append(payload.get('id'))
            return ('good-srt' if payload.get('id') == 'good'
                    else '<html>rate limited</html>')

        def parse(value):
            if value == '<html>rate limited</html>':
                return []
            return cues(stride=11300) if value == 'good-srt' else cues()

        with patch.object(self.sub, '_oracle_match', return_value=ranked), \
             patch.object(self.sub, '_download_oracle', side_effect=download), \
             patch.object(self.sub.sync_align, 'parse_srt', side_effect=parse), \
             patch.object(self.sub.sync_align, 'dialogue_cues',
                          side_effect=lambda value: value), \
             patch.object(self.sub.sync_align, 'micro_piecewise_proposal',
                          return_value=proposal), \
             patch.object(self.sub.sync_align, 'validate_micro_piecewise',
                          return_value=proposal), \
             patch.object(self.sub.sync_align, 'piecewise_maps_agree',
                          return_value=True), \
             patch.object(self.sub.sync_align, 'evaluate_piecewise_family',
                          return_value=accepted):
            result = self.sub._validated_oracle_piecewise(
                invalid + [independent],
                'Show.S01E01.1080p.BluRay.x265-NOGRP.mkv',
                'candidate-text', primary, 'primary-text')

        self.assertIsNotNone(result)
        self.assertIn('good', calls)
        self.assertEqual(result['secondary'], independent)
        self.assertEqual(result['downloads'], 1)

    def test_provider_piecewise_timing_clones_do_not_hide_later_family(self):
        """Translated copies of one timeline are attempts, not six votes."""
        def cues(delta=0, stride=10000):
            return [{'start': 10000 + delta + i * stride,
                     'end': 11000 + delta + i * stride}
                    for i in range(60)]

        primary = {
            'release': 'Show.S01E01.720p.BluRay.x264-DEMAND',
            'language': 'en', 'payload': {'id': 'primary'}}
        clones = [
            {'release': 'Show.S01E01.1080p.BluRay.x264-C%02d' % i,
             'language': 'x%02d' % i,
             'payload': {'id': 'clone-%02d' % i}}
            for i in range(6)
        ]
        independent = {
            'release': 'Show.S01E01.1080p.BluRay.x264-ROVERS',
            'language': 'ro', 'payload': {'id': 'good'}}
        proposal = {
            'status': self.sub.sync_align.STATUS_FIXABLE,
            'mode': 'piecewise', 'scale': 1.0, 'offset_ms': -700.0,
            'segments': [{'cand_from_ms': None, 'offset_ms': -700.0}],
            'validation_required': True, 'validation_folds': 5,
            'timing_family_count': 0, 'diag': 'proven'}
        accepted = {'accepted': True, 'before_score': .50,
                    'after_score': .93, 'after_overlap': .96,
                    'after_unique': .88}
        ranked = [
            (row, self.sub.release_match.TIER_SOURCE, 60 - i,
             'clone%02d' % i, 1) for i, row in enumerate(clones)
        ] + [(independent, self.sub.release_match.TIER_SOURCE,
              50, 'rovers', 1)]
        calls = []

        def download(payload):
            calls.append(payload.get('id'))
            return ('independent-text' if payload.get('id') == 'good'
                    else 'clone-text')

        def parse(value):
            return (cues(delta=700, stride=11300)
                    if value == 'independent-text' else cues())

        with patch.object(self.sub, '_oracle_match', return_value=ranked), \
             patch.object(self.sub, '_download_oracle', side_effect=download), \
             patch.object(self.sub.sync_align, 'parse_srt', side_effect=parse), \
             patch.object(self.sub.sync_align, 'dialogue_cues',
                          side_effect=lambda value: value), \
             patch.object(self.sub.sync_align, 'micro_piecewise_proposal',
                          return_value=proposal), \
             patch.object(self.sub.sync_align, 'validate_micro_piecewise',
                          return_value=proposal), \
             patch.object(self.sub.sync_align, 'piecewise_maps_agree',
                          return_value=True), \
             patch.object(self.sub.sync_align, 'evaluate_piecewise_family',
                          return_value=accepted):
            result = self.sub._validated_oracle_piecewise(
                clones + [independent],
                'Show.S01E01.1080p.BluRay.x265-NOGRP.mkv',
                'candidate-text', primary, 'primary-text')

        self.assertIsNotNone(result)
        self.assertIn('good', calls)
        self.assertEqual(result['secondary'], independent)
        self.assertEqual(result['downloads'], 1)

    def test_provider_piecewise_abstains_when_every_secondary_is_a_clone(self):
        cues = [{'start': 10000 + i * 10000,
                 'end': 11000 + i * 10000} for i in range(60)]
        primary = {
            'release': 'Show.S01E01.720p.BluRay.x264-DEMAND',
            'language': 'en', 'payload': {'id': 'primary'}}
        clone = {
            'release': 'Show.S01E01.1080p.BluRay.x264-ROVERS',
            'language': 'it', 'payload': {'id': 'clone'}}
        proposal = {
            'status': self.sub.sync_align.STATUS_FIXABLE,
            'mode': 'piecewise', 'scale': 1.0, 'offset_ms': -700.0,
            'segments': [{'cand_from_ms': None, 'offset_ms': -700.0}],
            'validation_required': True, 'validation_folds': 0,
            'timing_family_count': 0, 'diag': 'proposal'}
        validated = dict(proposal, validation_folds=5)
        with patch.object(self.sub, '_download_oracle',
                          return_value='clone-text'), \
             patch.object(self.sub.sync_align, 'parse_srt',
                          return_value=cues), \
             patch.object(self.sub.sync_align, 'dialogue_cues',
                          side_effect=lambda value: value), \
             patch.object(self.sub.sync_align, 'micro_piecewise_proposal',
                          return_value=proposal), \
             patch.object(self.sub.sync_align, 'validate_micro_piecewise',
                          return_value=validated) as validate, \
             patch.object(self.sub.sync_align, 'evaluate_piecewise_family') \
                     as family:
            result = self.sub._validated_oracle_piecewise(
                [primary, clone],
                'Show.S01E01.1080p.BluRay.x265-NOGRP.mkv',
                'candidate-text', primary, 'primary-text')
        self.assertIsNone(result)
        self.assertEqual(validate.call_count, 1)
        family.assert_not_called()

    def test_provider_piecewise_rejects_shifted_superset_timing_clone(self):
        primary_cues = []
        derivative_cues = []
        for i in range(420):
            start = 10000 + i * 5000
            primary_cues.append({'start': start, 'end': start + 1200})
            derivative_cues.append({'start': start + 700,
                                    'end': start + 1900})
            if (i + 1) % 6 == 0:
                derivative_cues.append({'start': start + 2700,
                                        'end': start + 3600})
        self.assertEqual(len(derivative_cues), 490)
        self.assertFalse(self.sub._timing_profiles_distinct(
            {'cues': primary_cues}, {'cues': derivative_cues}))

        primary = {
            'release': 'Show.S01E01.720p.BluRay.x264-DEMAND',
            'language': 'en', 'payload': {'id': 'primary'}}
        derivative = {
            'release': 'Show.S01E01.1080p.BluRay.x264-ROVERS',
            'language': 'ro', 'payload': {'id': 'derivative'}}
        proposal = {
            'status': self.sub.sync_align.STATUS_FIXABLE,
            'mode': 'piecewise', 'scale': 1.0, 'offset_ms': -700.0,
            'segments': [{'cand_from_ms': None, 'offset_ms': -700.0}],
            'validation_required': True, 'validation_folds': 0,
            'timing_family_count': 0, 'diag': 'proposal'}
        validated = dict(proposal, validation_folds=5)
        parsed = {'primary-text': primary_cues,
                  'derivative-text': derivative_cues}
        with patch.object(self.sub, '_download_oracle',
                          return_value='derivative-text'), \
             patch.object(self.sub.sync_align, 'parse_srt',
                          side_effect=lambda value: parsed[value]), \
             patch.object(self.sub.sync_align, 'dialogue_cues',
                          side_effect=lambda value: value), \
             patch.object(self.sub.sync_align, 'micro_piecewise_proposal',
                          return_value=proposal), \
             patch.object(self.sub.sync_align, 'validate_micro_piecewise',
                          return_value=validated) as validate, \
             patch.object(self.sub.sync_align, 'evaluate_piecewise_family') \
                     as family:
            result = self.sub._validated_oracle_piecewise(
                [primary, derivative],
                'Show.S01E01.1080p.BluRay.x265-NOGRP.mkv',
                'candidate-text', primary, 'primary-text')
        self.assertIsNone(result)
        self.assertEqual(validate.call_count, 1)
        family.assert_not_called()

    def test_provider_piecewise_rejects_segment_jitter_timing_clone(self):
        primary_cues = []
        derivative_cues = []
        offsets = (251, -249, 251, -249, 251, -249)
        for i in range(420):
            start = 10000 + i * 5000
            offset = offsets[min(5, i // 70)]
            primary_cues.append({'start': start, 'end': start + 1200})
            derivative_cues.append({'start': start + offset,
                                    'end': start + offset + 1200})
        self.assertFalse(self.sub._timing_profiles_distinct(
            {'cues': primary_cues}, {'cues': derivative_cues}))

        primary = {
            'release': 'Show.S01E01.720p.BluRay.x264-DEMAND',
            'language': 'en', 'payload': {'id': 'primary'}}
        derivative = {
            'release': 'Show.S01E01.1080p.BluRay.x264-ROVERS',
            'language': 'ro', 'payload': {'id': 'derivative'}}
        proposal = {
            'status': self.sub.sync_align.STATUS_FIXABLE,
            'mode': 'piecewise', 'scale': 1.0, 'offset_ms': -700.0,
            'segments': [{'cand_from_ms': None, 'offset_ms': -700.0}],
            'validation_required': True, 'validation_folds': 0,
            'timing_family_count': 0, 'diag': 'proposal'}
        validated = dict(proposal, validation_folds=5)
        parsed = {'primary-text': primary_cues,
                  'derivative-text': derivative_cues}
        with patch.object(self.sub, '_download_oracle',
                          return_value='derivative-text'), \
             patch.object(self.sub.sync_align, 'parse_srt',
                          side_effect=lambda value: parsed[value]), \
             patch.object(self.sub.sync_align, 'dialogue_cues',
                          side_effect=lambda value: value), \
             patch.object(self.sub.sync_align, 'micro_piecewise_proposal',
                          return_value=proposal), \
             patch.object(self.sub.sync_align, 'validate_micro_piecewise',
                          return_value=validated) as validate, \
             patch.object(self.sub.sync_align, 'piecewise_maps_agree',
                          return_value=True), \
             patch.object(self.sub.sync_align, 'evaluate_piecewise_family') \
                     as family:
            result = self.sub._validated_oracle_piecewise(
                [primary, derivative],
                'Show.S01E01.1080p.BluRay.x265-NOGRP.mkv',
                'candidate-text', primary, 'primary-text')
        self.assertIsNone(result)
        self.assertEqual(validate.call_count, 1)
        family.assert_not_called()

    def test_provider_piecewise_rejects_one_in_eight_retimed_derivative(self):
        primary_cues = []
        derivative_cues = []
        for i in range(420):
            start = 10000 + i * 5000
            primary_cues.append({'start': start, 'end': start + 1200})
            # Replace, rather than add, one cue out of every eight. This keeps
            # equal cue counts and defeats a pure superset/containment check.
            moved = start + (1700 if (i + 1) % 8 == 0 else 0)
            derivative_cues.append({'start': moved, 'end': moved + 1200})
        left = {'cues': primary_cues}
        right = {'cues': derivative_cues}
        self.assertGreater(
            self.sub._shift_invariant_onset_coverage(
                primary_cues, derivative_cues, tolerance_ms=350.0), .87)
        self.assertFalse(self.sub._timing_profiles_distinct(left, right))

        primary = {
            'release': 'Show.S01E01.720p.BluRay.x264-DEMAND',
            'language': 'en', 'payload': {'id': 'primary'}}
        derivative = {
            'release': 'Show.S01E01.1080p.BluRay.x264-ROVERS',
            'language': 'ro', 'payload': {'id': 'derivative'}}
        proposal = {
            'status': self.sub.sync_align.STATUS_FIXABLE,
            'mode': 'piecewise', 'scale': 1.0, 'offset_ms': -700.0,
            'segments': [{'cand_from_ms': None, 'offset_ms': -700.0}],
            'validation_required': True, 'validation_folds': 0,
            'timing_family_count': 0, 'diag': 'proposal'}
        validated = dict(proposal, validation_folds=5)
        parsed = {'primary-text': primary_cues,
                  'derivative-text': derivative_cues}
        with patch.object(self.sub, '_download_oracle',
                          return_value='derivative-text'), \
             patch.object(self.sub.sync_align, 'parse_srt',
                          side_effect=lambda value: parsed[value]), \
             patch.object(self.sub.sync_align, 'dialogue_cues',
                          side_effect=lambda value: value), \
             patch.object(self.sub.sync_align, 'micro_piecewise_proposal',
                          return_value=proposal), \
             patch.object(self.sub.sync_align, 'validate_micro_piecewise',
                          return_value=validated) as validate, \
             patch.object(self.sub.sync_align, 'piecewise_maps_agree',
                          return_value=True), \
             patch.object(self.sub.sync_align, 'evaluate_piecewise_family') \
                     as family:
            result = self.sub._validated_oracle_piecewise(
                [primary, derivative],
                'Show.S01E01.1080p.BluRay.x265-NOGRP.mkv',
                'candidate-text', primary, 'primary-text')
        self.assertIsNone(result)
        self.assertEqual(validate.call_count, 1)
        family.assert_not_called()

    def test_timing_family_rejects_one_in_three_same_shape_derivative(self):
        primary_cues = []
        derivative_cues = []
        for i in range(420):
            start = 10000 + i * 5000
            primary_cues.append({'start': start, 'end': start + 1200})
            moved = start + (1700 if (i + 1) % 3 == 0 else 0)
            derivative_cues.append({'start': moved, 'end': moved + 1200})
        # Plain onset containment is intentionally below the 85% ceiling; the
        # duration/onset fingerprint is what proves this remains one lane.
        self.assertLess(
            self.sub._shift_invariant_onset_coverage(
                primary_cues, derivative_cues, tolerance_ms=350.0), .85)
        self.assertGreater(
            self.sub._shift_invariant_shape_coverage(
                primary_cues, derivative_cues), .65)
        self.assertFalse(self.sub._timing_profiles_distinct(
            {'cues': primary_cues}, {'cues': derivative_cues}))

    def test_provider_piecewise_conflicting_proven_map_is_a_veto(self):
        def cues(stride):
            return [{'start': 10000 + i * stride,
                     'end': 11200 + i * stride} for i in range(60)]

        primary = {'release': 'Primary-DEMAND', 'language': 'en',
                   'payload': {'id': 'primary'}}
        conflict = {'release': 'Conflict-ROVERS', 'language': 'ro',
                    'payload': {'id': 'conflict'}}
        agreeable = {'release': 'Agree-SPARKS', 'language': 'fr',
                     'payload': {'id': 'agree'}}
        map_a = {
            'status': self.sub.sync_align.STATUS_FIXABLE,
            'mode': 'piecewise', 'scale': 1.0, 'offset_ms': -700.0,
            'segments': [{'cand_from_ms': None, 'offset_ms': -700.0}],
            'validation_required': True, 'validation_folds': 5,
            'timing_family_count': 0, 'diag': 'map A'}
        map_b = dict(map_a, offset_ms=1700.0,
                     segments=[{'cand_from_ms': None,
                                'offset_ms': 1700.0}], diag='map B')
        parsed = {'primary-text': cues(10000),
                  'conflict-text': cues(11300),
                  'agree-text': cues(12700)}
        ranked = [
            (conflict, self.sub.release_match.TIER_GROUP, 99, 'rovers', 2),
            (agreeable, self.sub.release_match.TIER_GROUP, 98, 'sparks', 2),
        ]
        with patch.object(self.sub, '_oracle_match', return_value=ranked), \
             patch.object(self.sub, '_download_oracle', side_effect=lambda p: {
                 'conflict': 'conflict-text', 'agree': 'agree-text'
             }.get(p.get('id'), '')), \
             patch.object(self.sub.sync_align, 'parse_srt',
                          side_effect=lambda value: parsed[value]), \
             patch.object(self.sub.sync_align, 'dialogue_cues',
                          side_effect=lambda value: value), \
             patch.object(self.sub.sync_align, 'micro_piecewise_proposal',
                          side_effect=[map_a, map_b, map_a]), \
             patch.object(self.sub.sync_align, 'validate_micro_piecewise',
                          side_effect=[map_a, map_b, map_a]) as validate, \
             patch.object(self.sub.sync_align, 'piecewise_maps_agree',
                          side_effect=[False, True]) as agree, \
             patch.object(self.sub.sync_align, 'evaluate_piecewise_family') \
                     as family:
            result = self.sub._validated_oracle_piecewise(
                [conflict, agreeable], 'Playing.BluRay.mkv',
                'candidate-text', primary, 'primary-text')
        self.assertIsNone(result)
        self.assertEqual(validate.call_count, 2)
        agree.assert_called_once()
        family.assert_not_called()

    def test_provider_piecewise_strong_regression_is_a_veto(self):
        primary_cues = [{'start': 10000 + i * 10000,
                         'end': 11200 + i * 10000} for i in range(60)]
        secondary_cues = [{'start': 10000 + i * 11300,
                           'end': 12600 + i * 11300} for i in range(55)]
        primary = {'release': 'Primary-DEMAND', 'language': 'en',
                   'payload': {'id': 'primary'}}
        secondary = {'release': 'Secondary-ROVERS', 'language': 'ro',
                     'payload': {'id': 'secondary'}}
        proven = {
            'status': self.sub.sync_align.STATUS_FIXABLE,
            'mode': 'piecewise', 'scale': 1.0, 'offset_ms': -700.0,
            'segments': [{'cand_from_ms': None, 'offset_ms': -700.0}],
            'validation_required': True, 'validation_folds': 5,
            'timing_family_count': 0, 'diag': 'proven'}
        family_result = {'accepted': False, 'before_score': .90,
                         'after_score': .60, 'after_overlap': .65,
                         'after_unique': .61}
        parsed = {'primary-text': primary_cues,
                  'secondary-text': secondary_cues}
        ranked = [(secondary, self.sub.release_match.TIER_GROUP,
                   99, 'rovers', 2)]
        with patch.object(self.sub, '_oracle_match', return_value=ranked), \
             patch.object(self.sub, '_download_oracle',
                          return_value='secondary-text'), \
             patch.object(self.sub.sync_align, 'parse_srt',
                          side_effect=lambda value: parsed[value]), \
             patch.object(self.sub.sync_align, 'dialogue_cues',
                          side_effect=lambda value: value), \
             patch.object(self.sub.sync_align, 'micro_piecewise_proposal',
                          return_value=proven), \
             patch.object(self.sub.sync_align, 'validate_micro_piecewise',
                          return_value=proven), \
             patch.object(self.sub.sync_align, 'piecewise_maps_agree',
                          return_value=True), \
             patch.object(self.sub.sync_align, 'evaluate_piecewise_family',
                          return_value=family_result):
            result = self.sub._validated_oracle_piecewise(
                [secondary], 'Playing.BluRay.mkv', 'candidate-text',
                primary, 'primary-text')
        self.assertIsNone(result)

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
        old_job = self._bound_job(
            key=old_key, path=str(self.subtitle), playing='old-release',
            info={})
        self._set_pending_for(old_job)
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
        self.assertNotEqual(self.sub._pending_key(), old_key)
        expected = self._selection_snapshot()
        self.status_update.assert_not_called()
        ku = sys.modules['resources.lib.kodi_utils']
        ku.stage_subtitle_delivery.assert_called_with(
            str(self.subtitle), selection=expected,
            status='confirmed', source='release')

        xbmc = sys.modules['xbmc']
        setter = Mock()
        player = types.SimpleNamespace(
            isPlaying=lambda: True,
            getPlayingFile=lambda: self.url,
            setSubtitles=setter)
        with patch.object(xbmc, 'Player', return_value=player):
            self.assertFalse(self.real_swap_if_current(
                old_job,
                'old-fixed.srt', {}))
        setter.assert_not_called()

    def test_queued_verification_publishes_checking_before_job_is_visible(self):
        with patch.object(self.sub, 'enabled', return_value=True), \
             patch.object(self.sub, 'playing_release', return_value='movie'), \
             patch.object(self.sub, '_known_cut_signature', return_value=''), \
             patch.object(self.sub, '_community_verdict', return_value=None), \
             patch.object(self.sub, '_record_delivery'), \
             patch.object(self.sub, '_enqueue_deep', return_value=True) as enqueue:
            out, verdict = self.sub.process(
                {}, str(self.subtitle), 'different-sub-release')
        self.assertEqual(out, str(self.subtitle))
        self.assertEqual(verdict['status'], 'PENDING')
        expected = self._selection_snapshot()
        self.status_update.assert_any_call(
            'checking', source='local',
            selection_token=expected['token'],
            link_hash=expected['link_hash'],
            stream_hash=expected['stream_hash'])
        enqueue.assert_called_once()

    def test_missing_deep_job_file_finishes_checking_as_unverified(self):
        missing = self.root / 'removed-before-service.srt'
        job = self._bound_job(
            key='missing-key', path=str(missing),
            playing='movie-release', info={})
        self._set_pending_for(job)
        self.sub.run_deep_job(job)
        self.assertIn(('unverified', 'missing'), self.successful_status)

        self.successful_status[:] = []
        identity = dict(job, identity_only=True)
        self._set_pending_for(identity)
        self.sub.run_deep_job(identity)
        self.assertEqual(self.successful_status, [])

    def test_deep_result_updates_only_the_still_current_selection(self):
        job = self._bound_job(
            key='same-key', path=str(self.subtitle),
            playing='movie-release', info={})
        verdict = {'status': self.sub.sync_align.STATUS_CONFIRMED,
                   'cache_key': 'same-key', 'diag': 'confirmed'}
        self._set_pending_for(job)
        with patch.object(self.sub, '_deep_verify',
                          return_value=(str(self.subtitle), verdict)), \
             patch.object(self.sub, '_record_delivery'):
            self.sub.run_deep_job(job)
        expected = self._selection_snapshot()
        self.status_update.assert_called_with(
            'confirmed', source='local',
            selection_token=expected['token'],
            link_hash=expected['link_hash'],
            stream_hash=expected['stream_hash'])

        self.status_update.reset_mock()
        self._set_pending_for(job, key='newer-selection')
        with patch.object(self.sub, '_deep_verify',
                          return_value=(str(self.subtitle), verdict)), \
             patch.object(self.sub, '_record_delivery'):
            self.sub.run_deep_job(job)
        self.status_update.assert_not_called()

    def test_pool_correction_never_reuploads_a_second_subtitle_copy(self):
        fake_pool = types.ModuleType('resources.lib.pool')
        fake_pool.contribute = Mock()
        fake_pool.contribute_ktuvit = Mock()
        fake_pool.report_sync = Mock()
        fixable = {'status': self.sub.sync_align.STATUS_FIXABLE,
                   'scale': 1.0, 'offset_ms': 750.0,
                   'mode': 'global', 'diag': 'community exact-cut record'}
        with patch.dict(sys.modules, {'resources.lib.pool': fake_pool}), \
             patch.object(self.sub, 'enabled', return_value=True), \
             patch.object(self.sub, 'playing_release', return_value='movie'), \
             patch.object(self.sub, '_known_cut_signature',
                          return_value='cut1:' + 'a' * 32), \
             patch.object(self.sub, '_community_verdict',
                          return_value=fixable), \
             patch.object(self.sub, '_record_delivery'), \
             patch.object(self.sub, '_write_fixed',
                          return_value=str(self.root / 'fixed.srt')):
            _out, verdict = self.sub.process(
                {}, str(self.subtitle), 'different-sub-release')
        self.assertTrue(verdict['applied'])
        fake_pool.contribute.assert_not_called()
        fake_pool.contribute_ktuvit.assert_not_called()
        fake_pool.report_sync.assert_not_called()

    def test_process_never_rebinds_an_old_resolve_to_the_new_selection(self):
        selection_a = self._selection_snapshot()
        self.selection.update(token='selection-token-B',
                              link_hash='selection-link-B')
        pending_b = self._bound_job(key='new-selection-key', info={})
        self._set_pending_for(pending_b)
        with patch.object(self.sub, 'enabled') as enabled, \
             patch.object(self.sub, '_record_delivery') as record, \
             patch.object(self.sub, '_enqueue_deep') as enqueue:
            out, verdict = self.sub.process(
                {}, str(self.subtitle), 'old-release',
                selection=selection_a)
        self.assertEqual(out, str(self.subtitle))
        self.assertIsNone(verdict)
        enabled.assert_not_called()
        record.assert_not_called()
        enqueue.assert_not_called()
        self.assertEqual(self.sub._pending_key(), 'new-selection-key')
        self.assertEqual(self.successful_status, [])

    def test_deep_job_cannot_clear_or_label_a_selection_changed_mid_commit(self):
        job = self._bound_job(
            key='old-key', path=str(self.subtitle),
            playing='movie-release', info={})
        self._set_pending_for(job)
        verdict = {
            'status': self.sub.sync_align.STATUS_CONFIRMED,
            'cache_key': 'old-key', 'diag': 'confirmed'}

        def change_selection(*_args, **_kwargs):
            self.selection.update(token='selection-token-B',
                                  link_hash='selection-link-B')
            pending_b = self._bound_job(key='new-key', info={})
            self._set_pending_for(pending_b)
            return False

        with patch.object(self.sub, '_deep_verify',
                          return_value=(str(self.subtitle), verdict)), \
             patch.object(self.sub, '_record_delivery',
                          side_effect=change_selection):
            self.sub.run_deep_job(job)
        self.assertEqual(self.sub._pending_key(), 'new-key')
        self.assertNotIn(('confirmed', 'local'), self.successful_status)
        self.sub._announce.assert_not_called()

    def test_background_swap_requires_same_proven_stream(self):
        xbmc = sys.modules['xbmc']
        setter = Mock()
        current = {'url': ('https://media.invalid/stream?file=B&token=new'
                           '|Authorization=object-B')}
        streams = ['embedded']

        def registered_set(path):
            setter(path)
            streams.append(path)

        self.url = current['url']
        player = types.SimpleNamespace(
            isPlaying=lambda: True,
            getPlayingFile=lambda: current['url'],
            getAvailableSubtitleStreams=lambda: list(streams),
            setSubtitles=registered_set,
            showSubtitles=lambda _on: None,
            setSubtitleStream=lambda _index: None)
        base = self._bound_job(key='subtitle-key', info={})
        self._set_pending_for(base)
        missing_url = dict(base)
        missing_url.pop('stream_url', None)
        with patch.object(xbmc, 'Player', return_value=player):
            self.assertFalse(self.real_swap_if_current(
                missing_url, 'fixed.srt', {}))
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
            self.assertFalse(self.real_swap_if_current(
                dict(base, stream_url=
                     ('https://media.invalid/stream?file=B&token=new'
                      '|Authorization=object-A')),
                'fixed.srt', {}))
            self.assertTrue(self.real_swap_if_current(
                dict(base, stream_url=current['url']),
                'fixed.srt', {}))
        setter.assert_called_once_with('fixed.srt')

    def test_background_swap_does_not_claim_fixed_without_registration(self):
        xbmc = sys.modules['xbmc']
        job = self._bound_job(key='subtitle-key', info={})
        self._set_pending_for(job)
        player = types.SimpleNamespace(
            isPlaying=lambda: True,
            getPlayingFile=lambda: self.url,
            getAvailableSubtitleStreams=lambda: ['embedded'],
            setSubtitles=lambda _path: None,
            showSubtitles=lambda _on: None,
            setSubtitleStream=lambda _index: None)
        with patch.object(xbmc, 'Player', return_value=player):
            self.assertFalse(self.real_swap_if_current(job, 'fixed.srt', {}))

    def test_background_swap_accepts_kodi_external_slot_replacement(self):
        xbmc = sys.modules['xbmc']
        job = self._bound_job(key='subtitle-key', info={})
        self._set_pending_for(job)
        fixed = self.root / 'replacement-fixed.srt'
        fixed.write_text(
            '1\n00:00:01,000 --> 00:00:02,000\nשלום\n',
            encoding='utf-8')
        handed = []
        # Same count and same generic language label before/after, matching
        # Android's one-external-slot behavior in the field log.
        player = types.SimpleNamespace(
            isPlaying=lambda: True,
            getPlayingFile=lambda: self.url,
            getAvailableSubtitleStreams=lambda: ['embedded', 'he'],
            setSubtitles=lambda path: handed.append(path),
            showSubtitles=lambda _on: None,
            setSubtitleStream=lambda _index: None)
        with patch.object(xbmc, 'Player', return_value=player):
            self.assertTrue(self.real_swap_if_current(
                job, str(fixed), {}))
        self.assertEqual(handed, [str(fixed)])

    def test_background_swap_requires_new_stream_to_be_selected(self):
        xbmc = sys.modules['xbmc']
        job = self._bound_job(key='subtitle-key', info={})
        self._set_pending_for(job)
        streams = ['embedded']

        def add_stream(_path):
            streams.append('external')

        player = types.SimpleNamespace(
            isPlaying=lambda: True,
            getPlayingFile=lambda: self.url,
            getAvailableSubtitleStreams=lambda: list(streams),
            setSubtitles=add_stream, showSubtitles=lambda _on: None,
            setSubtitleStream=Mock(
                side_effect=RuntimeError('synthetic pin failure')))
        with patch.object(xbmc, 'Player', return_value=player):
            self.assertFalse(self.real_swap_if_current(job, 'fixed.srt', {}))

    def test_proven_ai_fallback_is_metadata_only_and_requires_trusted_release(self):
        def row(kind, release, digest):
            payload = {'type': 'pool', 'pool_kind': kind,
                       'release': release, 'hash': digest}
            return {'language': 'he',
                    'link': urllib.parse.quote(json.dumps(payload))}

        human = row('ktuvit', 'Movie.HDTV-GRP', 'a' * 16)
        bad_ai = row('ai', 'Movie.CAM-GRP', 'b' * 16)
        good_ai = row('ai', 'Movie.WEB-DL-GRP', 'c' * 16)
        trusted = next(iter(self.sub.release_match.AUTO_OK_TIERS))

        def score(_playing, release):
            return ((100, trusted, {}) if 'WEB-DL' in release
                    else (10, 'none', {}))

        with patch.object(self.sub, 'playing_release', return_value='playing'), \
             patch.object(self.sub.release_match, 'score', side_effect=score), \
             patch.object(self.sub, '_ready_candidate_text') as cache_read:
            picked = self.sub.proven_pool_ai_fallback(
                {}, [human, bad_ai, good_ai])
        self.assertEqual(picked, good_ai['link'])
        cache_read.assert_not_called()

    def test_first_play_release_rank_promotes_clear_human_winner_without_io(self):
        def human(release):
            payload = {'type': 'engine', 'language': 'Hebrew',
                       'filename': release, 'source': 'opensubtitles'}
            return {'language': 'he', 'filename': release,
                    'link': urllib.parse.quote(json.dumps(payload))}

        weak = human('the.flash.2014.106.hdtv-lol')
        better = human('The.Flash.2014.S01E06.HDTV.SubsIL')
        close = human('The.Flash.2014.S01E06.HDTV.XviD-FUM')
        rows = [weak, better, close]
        season_pack_info = {
            'picked_release': (
                'The.Flash.2014.S01.1080p.BluRay.x265-RARBG.mp4'),
            'season': '1', 'episode': '6', 'is_episode': True}
        self.assertEqual(
            self.sub.playing_release(season_pack_info),
            'The.Flash.2014.S01E06.1080p.BluRay.x265-RARBG.mp4')
        with patch.object(self.sub, '_cached_reference_bundle',
                          return_value={}):
            ranked = self.sub.rank_ready_candidates(season_pack_info, rows)
        self.assertIs(ranked[0], better)
        self.assertEqual(set(map(id, ranked)), set(map(id, rows)))

        existing_episode = dict(season_pack_info)
        existing_episode['picked_release'] = (
            'The.Flash.2014.S01E07.1080p.BluRay.x265-RARBG.mp4')
        self.assertIn('S01E07', self.sub.playing_release(existing_episode))
        wrong_season = dict(season_pack_info)
        wrong_season['picked_release'] = (
            'The.Flash.2014.S02.1080p.BluRay.x265-RARBG.mp4')
        self.assertIn('.S02.', self.sub.playing_release(wrong_season))
        movie_s01 = {
            'picked_release': 'Movie.S01.2024.1080p.WEB-DL-GRP',
            'season': '1', 'episode': '6', 'is_episode': False,
            'media_type': 'movie'}
        self.assertEqual(self.sub.playing_release(movie_s01),
                         movie_s01['picked_release'])
        contradictory = dict(season_pack_info, media_type='movie')
        self.assertIn('.S01.', self.sub.playing_release(contradictory))

        ai = {'language': 'he', 'filename': 'AI pool',
              'link': urllib.parse.quote(json.dumps(
                  {'type': 'pool', 'pool_kind': 'ai', 'language': 'Hebrew'}))}
        interleaved = [weak, ai, better]
        with patch.object(
                self.sub, 'playing_release', return_value=(
                    'The.Flash.2014.S01E06.1080p.BluRay.x265-RARBG.mp4')), \
             patch.object(self.sub, '_cached_reference_bundle',
                          return_value={}):
            ranked = self.sub.rank_ready_candidates({}, interleaved)
        self.assertIs(ranked[0], better)
        self.assertIs(ranked[1], ai)
        self.assertIs(ranked[2], weak)

        # A marginal metadata difference is not enough to disturb provider
        # order before timing evidence exists.
        with patch.object(self.sub, 'playing_release', return_value='playing'), \
             patch.object(self.sub, '_cached_reference_bundle',
                          return_value={}), \
             patch.object(self.sub.release_match, 'score',
                          side_effect=[(20, 'cross', {}),
                                       (23, 'cross', {}),
                                       (18, 'cross', {})]):
            unchanged = self.sub.rank_ready_candidates({}, rows)
        self.assertEqual(unchanged, rows)

    def test_exact_field_certificate_applies_and_near_maps_abstain(self):
        segments = [
            {'cand_from_ms': None, 'cand_to_ms': 619207.5,
             'offset_ms': -776.0},
            {'cand_from_ms': 619207.5, 'cand_to_ms': 1061546.0,
             'offset_ms': 945.5},
            {'cand_from_ms': 1061546.0, 'cand_to_ms': 1328859.5,
             'offset_ms': 2651.5},
            {'cand_from_ms': 1328859.5, 'cand_to_ms': 1764132.0,
             'offset_ms': 4379.0},
            {'cand_from_ms': 1764132.0, 'cand_to_ms': 2103903.5,
             'offset_ms': 6016.5},
            {'cand_from_ms': 2103903.5, 'cand_to_ms': None,
             'offset_ms': 7827.5},
        ]
        validated = {
            'status': self.sub.sync_align.STATUS_FIXABLE,
            'mode': 'piecewise', 'scale': 1.0, 'offset_ms': -776.0,
            'segments': segments, 'validation_required': True,
            'validation_folds': 4, 'timing_family_count': 0,
            'after_score': .928, 'unique': .88,
            'post_residual_ms': 107.0, 'diag': 'field proposal'}
        primary = {
            'release': 'The.Flash.2014.S01E06.720p.BluRay.x264-DEMAND'}
        playing = self.sub.playing_release({
            'picked_release': (
                'The.Flash.2014.S01.1080p.BluRay.x265-RARBG.mp4'),
            'season': '1', 'episode': '6', 'is_episode': True})
        self.assertEqual(
            playing, 'The.Flash.2014.S01E06.1080p.BluRay.x265-RARBG.mp4')
        verdict = self.sub._field_certified_piecewise(
            playing, primary, validated)
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict['validation_certificate'],
                         'flash-s01e06-rarbg-v1')

        candidate = ''.join(
            '%d\n00:%02d:%02d,000 --> 00:%02d:%02d,800\nline %d\n\n'
            % (i + 1, (i * 30) // 60, (i * 30) % 60,
               (i * 30) // 60, (i * 30) % 60, i + 1)
            for i in range(80))
        fixed = self.sub.sync_align.apply_verdict(candidate, verdict)
        self.assertNotEqual(fixed, candidate)
        self.assertEqual(
            [c['text'] for c in self.sub.sync_align.parse_srt(fixed)],
            [c['text'] for c in self.sub.sync_align.parse_srt(candidate)])

        wrong_target = self.sub._field_certified_piecewise(
            'Other.Show.S01E06.1080p.BluRay.x265-RARBG',
            primary, validated)
        self.assertIsNone(wrong_target)
        wrong_primary = self.sub._field_certified_piecewise(
            playing,
            {'release': 'Completely.Other.Movie.1999.720p.BluRay.x264-DEMAND'},
            validated)
        self.assertIsNone(wrong_primary)
        near = dict(validated)
        near['segments'] = [dict(x) for x in segments]
        near['segments'][3]['offset_ms'] += 351
        self.assertIsNone(self.sub._field_certified_piecewise(
            playing, primary, near))

        forged = dict(verdict)
        forged['segments'] = [dict(x) for x in segments]
        forged['segments'][1]['cand_to_ms'] += 5001
        with self.assertRaisesRegex(ValueError, 'family validation'):
            self.sub.sync_align.apply_verdict(candidate, forged)

        forged_from = dict(verdict)
        forged_from['segments'] = [dict(x) for x in segments]
        forged_from['segments'][1]['cand_from_ms'] = 100000
        with self.assertRaisesRegex(ValueError, 'family validation'):
            self.sub.sync_align.apply_verdict(candidate, forged_from)

        forged_scale = dict(verdict)
        forged_scale['scale'] = 1.01
        with self.assertRaisesRegex(ValueError, 'family validation'):
            self.sub.sync_align.apply_verdict(candidate, forged_scale)

        forged_target = dict(verdict)
        forged_target['validation_target'] = 'other.show.s01e06'
        with self.assertRaisesRegex(ValueError, 'family validation'):
            self.sub.sync_align.apply_verdict(candidate, forged_target)

    def test_matching_oracle_generalizes_piecewise_proof_to_other_titles(self):
        segments = [
            {'cand_from_ms': None, 'cand_to_ms': 600000.0,
             'offset_ms': -700.0},
            {'cand_from_ms': 600000.0, 'cand_to_ms': 1200000.0,
             'offset_ms': 900.0},
            {'cand_from_ms': 1200000.0, 'cand_to_ms': None,
             'offset_ms': 2600.0},
        ]
        proposal = {
            'status': self.sub.sync_align.STATUS_FIXABLE,
            'mode': 'piecewise', 'scale': 1.0, 'offset_ms': -700.0,
            'segments': segments, 'validation_required': True,
            'validation_folds': 5, 'timing_family_count': 0,
            'holdout_score_min': .86, 'holdout_gain_min': .18,
            'after_score': .94, 'unique': .90,
            'post_residual_ms': 180.0, 'cand_span_ms': 1800000.0,
            'diag': 'generic strict proposal'}
        primary = {
            'release': 'Other.Show.S02E03.720p.WEB-DL.x264-NTb',
            'language': 'en', 'payload': {'id': 'primary'}}
        playing = 'Other.Show.S02E03.1080p.WEB-DL.x265-NTb.mkv'
        cues = [{'start': 10000 + i * 10000,
                 'end': 11200 + i * 10000} for i in range(180)]
        with patch.object(self.sub.sync_align, 'parse_srt',
                          return_value=cues), \
             patch.object(self.sub.sync_align, 'dialogue_cues',
                          side_effect=lambda value: value), \
             patch.object(self.sub.sync_align, 'micro_piecewise_proposal',
                          return_value=proposal), \
             patch.object(self.sub.sync_align, 'validate_micro_piecewise',
                          return_value=proposal), \
             patch.object(self.sub, '_download_oracle') as download:
            result = self.sub._validated_oracle_piecewise(
                [primary], playing, 'candidate-text', primary, 'primary-text')
        self.assertIsNotNone(result)
        self.assertEqual(result['downloads'], 0)
        self.assertEqual(result['verdict']['validation_proof'],
                         'matched-oracle-holdouts-v1')
        download.assert_not_called()

        candidate = ''.join(
            '%d\n00:%02d:%02d,000 --> 00:%02d:%02d,800\nline %d\n\n'
            % (i + 1, (i * 30) // 60, (i * 30) % 60,
               (i * 30) // 60, (i * 30) % 60, i + 1)
            for i in range(80))
        fixed = self.sub.sync_align.apply_verdict(
            candidate, result['verdict'])
        self.assertNotEqual(fixed, candidate)

        wrong_title = dict(result['verdict'])
        wrong_title['validation_primary_oracle'] = (
            'Unrelated.Show.S02E03.720p.WEB-DL.x264-NTb')
        with self.assertRaisesRegex(ValueError, 'family validation'):
            self.sub.sync_align.apply_verdict(candidate, wrong_title)

        wrong_episode = dict(result['verdict'])
        wrong_episode['validation_primary_oracle'] = (
            'Other.Show.S02E04.720p.WEB-DL.x264-NTb')
        with self.assertRaisesRegex(ValueError, 'family validation'):
            self.sub.sync_align.apply_verdict(candidate, wrong_episode)

        forged_tier = dict(result['verdict'])
        forged_tier['validation_primary_tier'] = 'exact'
        with self.assertRaisesRegex(ValueError, 'family validation'):
            self.sub.sync_align.apply_verdict(candidate, forged_tier)

        weak_folds = dict(result['verdict'])
        weak_folds['validation_folds'] = 4
        with self.assertRaisesRegex(ValueError, 'family validation'):
            self.sub.sync_align.apply_verdict(candidate, weak_folds)

        weak_gain = dict(result['verdict'])
        weak_gain['holdout_gain_min'] = .149
        with self.assertRaisesRegex(ValueError, 'family validation'):
            self.sub.sync_align.apply_verdict(candidate, weak_gain)

        broken_chain = dict(result['verdict'])
        broken_chain['segments'] = [dict(item) for item in segments]
        broken_chain['segments'][1]['cand_from_ms'] += 2.0
        with self.assertRaisesRegex(ValueError, 'family validation'):
            self.sub.sync_align.apply_verdict(candidate, broken_chain)

        nonmonotonic = dict(result['verdict'])
        nonmonotonic['segments'] = [dict(item) for item in segments]
        nonmonotonic['segments'][2]['offset_ms'] = 100.0
        with self.assertRaisesRegex(ValueError, 'family validation'):
            self.sub.sync_align.apply_verdict(candidate, nonmonotonic)

        descending = dict(result['verdict'])
        descending['segments'] = [dict(item) for item in segments]
        descending['segments'][0]['cand_to_ms'] = 1200000.0
        descending['segments'][1]['cand_from_ms'] = 1200000.0
        descending['segments'][1]['cand_to_ms'] = 600000.0
        descending['segments'][2]['cand_from_ms'] = 600000.0
        with self.assertRaisesRegex(ValueError, 'family validation'):
            self.sub.sync_align.apply_verdict(candidate, descending)
        self.assertIsNone(self.sub._matched_oracle_piecewise(
            playing, primary, descending))

        outside_span = dict(result['verdict'])
        outside_span['segments'] = [dict(item) for item in segments]
        outside_span['segments'][1]['cand_to_ms'] = 1900000.0
        outside_span['segments'][2]['cand_from_ms'] = 1900000.0
        with self.assertRaisesRegex(ValueError, 'family validation'):
            self.sub.sync_align.apply_verdict(candidate, outside_span)
        self.assertIsNone(self.sub._matched_oracle_piecewise(
            playing, primary, outside_span))

        same_source_only = dict(primary)
        same_source_only['release'] = (
            'Other.Show.S02E03.1080p.WEB-DL.x265-FLUX')
        self.assertIsNone(self.sub._matched_oracle_piecewise(
            playing, same_source_only, proposal))

    def test_schema_25_retries_incomplete_release_decisions(self):
        self.assertEqual(self.sub._VERDICT_VERSION, 25)
        sig = 'cut1:' + '7' * 32
        text = self.subtitle.read_text(encoding='utf-8')
        final_key = self.sub._cache_key(text, 'movie-release', sig)
        stale = {'v': 24, 'status': self.sub.sync_align.STATUS_UNKNOWN,
                 'diag': 'release 655 used incomplete S01 identity'}
        with patch.object(self.sub, '_probe_reference_bundle', return_value={
                'cut_signature': sig, 'cues': [], 'track_cues': []}), \
             patch.object(self.sub, '_load_verdicts',
                          return_value={final_key: stale}), \
             patch.object(self.sub, '_community_verdict', return_value=None), \
             patch.object(self.sub, '_verify_file_bundle',
                          return_value=(None, 'NONE', 0)), \
             patch.object(self.sub, '_oracle_candidates',
                          return_value=[]) as search, \
             patch.object(self.sub, '_audio_probe_reference',
                          return_value=None):
            _out, verdict = self.sub._deep_verify(
                {}, str(self.subtitle), text, 'manual-pick',
                'movie-release', 'legacy-key')
        self.assertEqual(verdict['status'], self.sub._STATUS_NO_ORACLE)
        search.assert_called_once()

    def test_disc_piecewise_accepts_three_release_group_same_master_quorum(self):
        cues = [{'start': 10000 + i * 5000,
                 'end': 11200 + i * 5000} for i in range(420)]
        primary = {'release': 'Show.S01E01.720p.BluRay.x264-DEMAND',
                   'language': 'en', 'payload': {'id': 'primary'}}
        rovers = {'release': 'Show.S01E01.1080p.BluRay.x264-ROVERS',
                  'language': 'nl', 'payload': {'id': 'rovers'}}
        remux = {'release': 'Show.S01E01.BluRay.REMUX-EDITH',
                 'language': 'id', 'payload': {'id': 'edith'}}
        proposal = {
            'status': self.sub.sync_align.STATUS_FIXABLE,
            'mode': 'piecewise', 'scale': 1.0, 'offset_ms': -775.0,
            'segments': [{'cand_from_ms': None, 'offset_ms': -775.0}],
            'validation_required': True, 'validation_folds': 5,
            'timing_family_count': 0, 'diag': '4/5 field holdouts'}
        family = {'accepted': True, 'before_score': .61,
                  'after_score': .93, 'after_overlap': .98,
                  'after_unique': .88, 'post_residual_ms': 120.0}
        ranked = [
            (rovers, self.sub.release_match.TIER_SOURCE, 62, 'rovers', 1),
            (remux, self.sub.release_match.TIER_SOURCE, 58, 'edith', 1)]
        with patch.object(self.sub, '_oracle_match', return_value=ranked), \
             patch.object(self.sub, '_download_oracle',
                          side_effect=['rovers-text', 'edith-text']), \
             patch.object(self.sub.sync_align, 'parse_srt',
                          return_value=cues), \
             patch.object(self.sub.sync_align, 'dialogue_cues',
                          side_effect=lambda value: value), \
             patch.object(self.sub.sync_align, 'micro_piecewise_proposal',
                          return_value=proposal), \
             patch.object(self.sub.sync_align, 'validate_micro_piecewise',
                          return_value=proposal), \
             patch.object(self.sub.sync_align, 'evaluate_piecewise_family',
                          return_value=family):
            result = self.sub._validated_oracle_piecewise(
                [primary, rovers, remux],
                'Show.S01E01.1080p.BluRay.x265-RARBG',
                'candidate-text', primary, 'primary-text')
        self.assertIsNotNone(result)
        self.assertEqual(result['verdict']['same_master_group_count'], 3)
        self.assertEqual(result['verdict']['timing_family_count'], 1)
        self.assertEqual(
            result['verdict']['validation_proof'],
            'same-disc-release-group-quorum')
        self.assertIn('same-disc timing lane', result['verdict']['diag'])

        # Exercise the final production gate, not merely proposal creation.
        candidate = ''.join(
            '%d\n00:00:%02d,000 --> 00:00:%02d,900\nline %d\n\n'
            % (i + 1, 10 + i * 2, 10 + i * 2, i + 1)
            for i in range(10))
        fixed = self.sub.sync_align.apply_verdict(
            candidate, result['verdict'])
        before = self.sub.sync_align.parse_srt(candidate)
        after = self.sub.sync_align.parse_srt(fixed)
        self.assertNotEqual(fixed, candidate)
        self.assertEqual(len(after), len(before))
        self.assertEqual([cue['text'] for cue in after],
                         [cue['text'] for cue in before])

        # A declared count is not evidence: all three named groups must be
        # non-empty and distinct or the final application gate rejects it.
        spoofed = dict(result['verdict'])
        spoofed['same_master_groups'] = ['demand', 'rovers', 'rovers']
        with self.assertRaisesRegex(ValueError, 'family validation'):
            self.sub.sync_align.apply_verdict(candidate, spoofed)

    def test_disc_piecewise_refuses_quorum_when_primary_group_is_unknown(self):
        cues = [{'start': 10000 + i * 5000,
                 'end': 11200 + i * 5000} for i in range(420)]
        primary = {'release': 'Show.S01E01.720p.BluRay.x264',
                   'language': 'en', 'payload': {'id': 'primary'}}
        rovers = {'release': 'Show.S01E01.1080p.BluRay.x264-ROVERS',
                  'language': 'nl', 'payload': {'id': 'rovers'}}
        remux = {'release': 'Show.S01E01.BluRay.REMUX-EDITH',
                 'language': 'id', 'payload': {'id': 'edith'}}
        proposal = {
            'status': self.sub.sync_align.STATUS_FIXABLE,
            'mode': 'piecewise', 'scale': 1.0, 'offset_ms': -775.0,
            'segments': [{'cand_from_ms': None, 'offset_ms': -775.0}],
            'validation_required': True, 'validation_folds': 5,
            'timing_family_count': 0, 'diag': '4/5 field holdouts'}
        family = {'accepted': True, 'before_score': .61,
                  'after_score': .93, 'after_overlap': .98,
                  'after_unique': .88, 'post_residual_ms': 120.0}
        ranked = [
            (rovers, self.sub.release_match.TIER_SOURCE, 62, 'rovers', 1),
            (remux, self.sub.release_match.TIER_SOURCE, 58, 'edith', 1)]
        with patch.object(self.sub, '_oracle_match', return_value=ranked), \
             patch.object(self.sub, '_download_oracle',
                          side_effect=['rovers-text', 'edith-text']), \
             patch.object(self.sub.sync_align, 'parse_srt',
                          return_value=cues), \
             patch.object(self.sub.sync_align, 'dialogue_cues',
                          side_effect=lambda value: value), \
             patch.object(self.sub.sync_align, 'micro_piecewise_proposal',
                          return_value=proposal), \
             patch.object(self.sub.sync_align, 'validate_micro_piecewise',
                          return_value=proposal), \
             patch.object(self.sub.sync_align, 'evaluate_piecewise_family',
                          return_value=family):
            result = self.sub._validated_oracle_piecewise(
                [primary, rovers, remux],
                'Show.S01E01.1080p.BluRay.x265-RARBG',
                'candidate-text', primary, 'primary-text')
        self.assertIsNone(result)

    def test_unknown_human_can_switch_to_proven_pool_ai_only_while_current(self):
        ku = sys.modules['resources.lib.kodi_utils']
        human_link = 'human-link'
        fallback = urllib.parse.quote(json.dumps({
            'type': 'pool', 'pool_kind': 'ai',
            'release': 'Movie.WEB-DL-GRP', 'hash': 'd' * 16}))
        state = {'link': human_link}
        ku.get_current_subtitle = lambda: state['link']

        def select(link):
            state['link'] = link
            self.selection = {
                'token': 'fallback-token' if link == fallback else 'human-token',
                'link_hash': 'fallback-hash' if link == fallback else 'human-hash'}

        ku.set_current_subtitle = Mock(side_effect=select)

        def snapshot(expected_link=None):
            if expected_link is not None and expected_link != state['link']:
                return {'token': '', 'link_hash': '', 'stream_hash': ''}
            return self._selection_snapshot()

        ku.current_subtitle_selection = snapshot
        ku.apply_subtitle_file = Mock(return_value=True)
        ku.notify = Mock()
        self.selection = {'token': 'human-token', 'link_hash': 'human-hash'}
        job = self._bound_job(
            key='human-key', path=str(self.subtitle), playing='playing', info={},
            fallback_link=fallback)
        self._set_pending_for(job)
        fake_translate = types.ModuleType('resources.lib.translate')
        fake_translate.resolve = Mock(return_value=str(self.subtitle))
        trusted = next(iter(self.sub.release_match.AUTO_OK_TIERS))
        with patch.dict(sys.modules, {'resources.lib.translate': fake_translate}), \
             patch.object(self.sub.release_match, 'score',
                          return_value=(100, trusted, {})):
            self.assertTrue(self.sub._apply_proven_pool_fallback(job))
        ku.apply_subtitle_file.assert_called_once()
        self.assertEqual(state['link'], fallback)

        # A later manual selection invalidates the original human job before it
        # can claim or resolve the fallback.
        select('manual-link')
        ku.apply_subtitle_file.reset_mock()
        with patch.object(self.sub.release_match, 'score',
                          return_value=(100, trusted, {})):
            self.assertFalse(self.sub._apply_proven_pool_fallback(job))
        ku.apply_subtitle_file.assert_not_called()

    def test_failed_fallback_never_overwrites_manual_same_link_reselection(self):
        ku = sys.modules['resources.lib.kodi_utils']
        human_link = 'human-link'
        fallback = urllib.parse.quote(json.dumps({
            'type': 'pool', 'pool_kind': 'ai',
            'release': 'Movie.WEB-DL-GRP', 'hash': 'e' * 16}))
        state = {'link': human_link}
        ku.get_current_subtitle = lambda: state['link']

        def auto_select(link):
            state['link'] = link
            self.selection = {
                'token': ('auto-fallback-token' if link == fallback
                          else 'human-token'),
                'link_hash': ('fallback-hash' if link == fallback
                              else 'human-hash')}

        ku.set_current_subtitle = Mock(side_effect=auto_select)

        def snapshot(expected_link=None):
            if expected_link is not None and expected_link != state['link']:
                return {'token': '', 'link_hash': '', 'stream_hash': ''}
            return self._selection_snapshot()

        ku.current_subtitle_selection = snapshot
        ku.apply_subtitle_file = Mock(return_value=True)
        self.selection = {'token': 'human-token', 'link_hash': 'human-hash'}
        job = self._bound_job(
            key='human-key', path=str(self.subtitle), playing='playing', info={},
            fallback_link=fallback)
        self._set_pending_for(job)
        fake_translate = types.ModuleType('resources.lib.translate')

        def manual_same_row_then_fail(*_args, **_kwargs):
            # The explicit picker uses renew=True. The link stays identical,
            # while its fresh generation must make the automatic claim stale.
            self.selection = {
                'token': 'manual-same-row-token',
                'link_hash': 'fallback-hash'}
            return None

        fake_translate.resolve = Mock(side_effect=manual_same_row_then_fail)
        trusted = next(iter(self.sub.release_match.AUTO_OK_TIERS))
        with patch.dict(sys.modules, {'resources.lib.translate': fake_translate}), \
             patch.object(self.sub.release_match, 'score',
                          return_value=(100, trusted, {})):
            self.assertFalse(self.sub._apply_proven_pool_fallback(job))
        self.assertEqual(state['link'], fallback)
        self.assertEqual(self.selection['token'], 'manual-same-row-token')
        self.assertEqual(ku.set_current_subtitle.call_args_list,
                         [call(fallback)])
        ku.apply_subtitle_file.assert_not_called()


if __name__ == '__main__':
    unittest.main()
