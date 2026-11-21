"""MoranSubs 0.3.110: a subtitle on screen whose timing agrees with an alternate the file proved stays.

Field log (21 Nov 2026, Friends S07E08 2160p UHD remux, "several episodes already"): the exact-release Ktuvit
copy from the pool (100%) was in sync, but its lines are cut differently from the file's tracks (vote 58%,
offset +275 ms), so it stayed unproven. The tournament then proved a Wizdom 49% row against the file's Chinese
PGS track at +1282 ms and put it on screen instead; the viewer picked his 100% row again by hand. Once shifted,
the Wizdom row runs 0.23-0.30 s from the exact copy (CONFIRMED): the proof was the exact copy's proof too.

tests/data/subsync_kept_friends.json holds both subtitles' cue timings (no text; 1 = a line the dialogue filter
drops). Runs on the legacy SubSync harness (tools/test_subsync_remote_playback_safety.py), pointed at the
current add-on tree."""
import importlib.util
import json
import sys
import types
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    'legacy_subsync_safety_for_kept', ROOT / 'tools/test_subsync_remote_playback_safety.py')
legacy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(legacy)
legacy.LIB = ROOT / 'service.subtitles.kodipovilai/resources/lib'
Base = legacy.RemotePlaybackSafety
DATA = json.load(open(ROOT / 'tests/data/subsync_kept_friends.json', encoding='utf-8'))
CUT = 'cut1:' + 'f' * 32


def srt(rows, shift=0):
    def at(ms):
        ms += shift
        return '%02d:%02d:%02d,%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)
    return '\n'.join('%d\n%s --> %s\n%s\n' % (i + 1, at(a), at(b), '-' if drop else 'שורה מספר %d' % (i + 1))
                     for i, (a, b, drop) in enumerate(rows))


def link(kind, release):
    return urllib.parse.quote(json.dumps({'type': 'pool', 'pool_kind': kind, 'hash': release[-16:].ljust(16, 'x'),
                                          'release': release}))


EXACT = link('ktuvit', DATA['video'])
WIZDOM = urllib.parse.quote(json.dumps({'type': 'engine', 'source': 'wizdom', 'language': 'Hebrew',
                                        'filename': 'Friends.S07E08.720p.BluRay.x264-PSYCHD',
                                        'download_data': {'id': 7}}))


class KeptByAlternate(unittest.TestCase):
    setUp = Base.setUp
    _stream_hash = Base._stream_hash
    _selection_snapshot = Base._selection_snapshot
    _selection_matches = Base._selection_matches
    _bound_job = Base._bound_job
    _set_pending_for = Base._set_pending_for

    def proven(self):
        sa = self.sub.sync_align
        # as the viewer's log: Wizdom vs FILE TRACK #8 chi (676 cues), FIXABLE +1282 ms
        return ({'status': sa.STATUS_FIXABLE, 'scale': 1.0, 'offset_ms': 1282.0, 'mode': 'global',
                 'diag': 'scale=1.000000 offset=+1282ms vote=100% overlap=100%'}, 'FILE TRACK #8 chi', 676)

    def tournament(self, on_screen_link, on_screen_text):
        self.subtitle.write_text(on_screen_text, encoding='utf-8')
        job = self._bound_job(key='exact', path=str(self.subtitle), playing=DATA['video'], info={},
                              fallback_links=[WIZDOM])
        fake_translate = types.ModuleType('resources.lib.translate')
        delivered = self.root / 'wizdom.srt'
        delivered.write_text(srt(DATA['wizdom']), encoding='utf-8')
        fake_translate.resolve = Mock(return_value=str(delivered))
        ku = sys.modules['resources.lib.kodi_utils']
        ku.get_current_subtitle = Mock(return_value=on_screen_link)
        ku.set_current_subtitle = Mock()
        ku.current_subtitle_selection = Mock(return_value=self._selection_snapshot())
        ku.apply_subtitle_file = Mock(return_value=True)
        ku.notify = Mock()
        with patch.dict(sys.modules, {'resources.lib.translate': fake_translate}), \
                patch.object(self.sub, '_job_matches_current', return_value=True), \
                patch.object(self.sub, '_job_stream_is_current', return_value=True), \
                patch.object(self.sub, '_selection_matches', return_value=True), \
                patch.object(self.sub, '_cached_reference_bundle', return_value={'cues': [1], 'cut_signature': CUT}), \
                patch.object(self.sub, '_tournament_candidate_text',
                             return_value=(srt(DATA['wizdom']), self.sub._decode_link(WIZDOM))), \
                patch.object(self.sub, '_verify_file_bundle', return_value=self.proven()):
            applied = self.sub._apply_verified_human_fallback(job)
        return applied, ku, job

    def test_the_exact_copy_stays_when_the_proven_row_agrees_with_it(self):
        applied, ku, job = self.tournament(EXACT, srt(DATA['exact']))
        self.assertFalse(applied)
        ku.set_current_subtitle.assert_not_called()
        ku.apply_subtitle_file.assert_not_called()
        kept = job['_kept_by_alternate']
        self.assertEqual(kept['status'], self.sub.sync_align.STATUS_CONFIRMED)
        self.assertIn('PSYCHD', kept['proven_by'])
        self.assertAlmostEqual(kept['offset_ms'], 301, delta=40)   # the exact copy, against the proven timeline

    def test_a_row_on_screen_off_the_proven_timeline_is_still_replaced(self):
        applied, ku, job = self.tournament(EXACT, srt(DATA['exact'], shift=2000))
        self.assertTrue(applied)
        ku.set_current_subtitle.assert_called_once_with(WIZDOM, renew=True)
        self.assertNotIn('_kept_by_alternate', job)

    def test_an_ai_row_on_screen_is_still_replaced_by_the_proven_human_one(self):
        applied, ku, job = self.tournament(link('ai', DATA['video']), srt(DATA['exact']))
        self.assertTrue(applied)
        ku.set_current_subtitle.assert_called_once_with(WIZDOM, renew=True)

    def test_the_deep_job_ends_confirmed_without_a_swap_or_an_oracle(self):
        self.subtitle.write_text(srt(DATA['exact']), encoding='utf-8')
        job = self._bound_job(key='exact', path=str(self.subtitle), playing=DATA['video'], info={},
                              fallback_links=[WIZDOM])
        self._set_pending_for(job)
        bundle = {'cut_signature': CUT, 'cues': [{'start': 1000, 'end': 2000}]}
        sa = self.sub.sync_align
        unknown = {'status': sa.STATUS_UNKNOWN, 'diag': 'gate FAILED (scale=1.000000 offset=+275ms vote=58%)'}
        ku = sys.modules['resources.lib.kodi_utils']
        ku.get_current_subtitle = Mock(return_value=EXACT)
        ku.set_current_subtitle = Mock()
        ku.apply_subtitle_file = Mock(return_value=True)
        ku.notify = Mock()
        with patch.object(self.sub, '_probe_reference_bundle', return_value=bundle), \
                patch.object(self.sub, '_cached_reference_bundle', return_value=bundle), \
                patch.object(self.sub, '_community_verdict', return_value=None), \
                patch.object(self.sub, '_tournament_candidate_text',
                             return_value=(srt(DATA['wizdom']), self.sub._decode_link(WIZDOM))), \
                patch.object(self.sub, '_verify_file_bundle', side_effect=[(unknown, 'FILE TRACK #4 fre', 646),
                                                                           self.proven()]), \
                patch.object(self.sub, '_apply_proven_pool_fallback',
                             side_effect=AssertionError('a kept row is not replaced by a pool row')), \
                patch.object(self.sub, '_oracle_candidates',
                             side_effect=AssertionError('the proof is in: no oracle search')):
            self.sub.run_deep_job(job)
        ku.set_current_subtitle.assert_not_called()
        ku.apply_subtitle_file.assert_not_called()
        self.sub._swap_if_current.assert_not_called()
        self.assertIn(('confirmed', 'local'), self.successful_status)
        self.assertNotIn(('unverified', 'local'), self.successful_status)

    def test_the_kept_verdict_is_in_sync_as_it_is(self):
        job = {'_kept_by_alternate': {'proven_by': 'Friends.S07E08.720p.BluRay.x264-PSYCHD', 'diag': 'offset=+301ms'}}
        verdict = self.sub._kept_verdict(job, CUT, 'key')
        self.assertEqual(verdict['status'], self.sub.sync_align.STATUS_CONFIRMED)
        self.assertEqual((verdict['scale'], verdict['offset_ms']), (1.0, 0.0))
        self.assertTrue(verdict['kept_by_alternate'])


del Base     # unittest would otherwise collect (and run) the legacy suite from this module


if __name__ == '__main__':
    unittest.main()
