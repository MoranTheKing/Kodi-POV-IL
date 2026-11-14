"""The automatic pick's tournament and a FIXABLE map the subtitle cannot take.

Field log (14 Nov 2026, Dexter S03E05 '2160p.HDR.Ai.Upscale.Mesc'): the HDTV-0TV rows were proved FIXABLE by
a two-region map (+103,787 ms, -1,841 ms); applying it refused a negative cue ("retime would create
invalid/negative cue"), and the tournament stopped right there ("autosub tournament apply skipped"),
leaving an unsynced subtitle on screen. The BluRay SiNNERS row the viewer then picked by hand was CONFIRMED
at +0.1 s. Such a row is now passed over like an UNKNOWN one, and the next row is tried.

Runs on the legacy SubSync harness (tools/test_subsync_remote_playback_safety.py), pointed at the current
add-on tree."""
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
    'legacy_subsync_safety_for_map', ROOT / 'tools/test_subsync_remote_playback_safety.py')
legacy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(legacy)
legacy.LIB = ROOT / 'service.subtitles.kodipovilai/resources/lib'
Base = legacy.RemotePlaybackSafety


class TournamentMap(unittest.TestCase):
    setUp = Base.setUp
    _stream_hash = Base._stream_hash
    _selection_snapshot = Base._selection_snapshot
    _selection_matches = Base._selection_matches
    _bound_job = Base._bound_job

    def link(self, row_id):
        return urllib.parse.quote(json.dumps({
            'type': 'engine', 'source': 'opensubtitles', 'language': 'Hebrew',
            'filename': 'Candidate-%d' % row_id, 'download_data': {'id': row_id}}))

    def run_tournament(self, verdicts):
        first, second = self.link(1), self.link(2)
        job = self._bound_job(key='original', playing='Dexter.S03E05.2160p.HDR.Ai.Upscale-Mesc',
                              fallback_links=[first, second], info={})
        bundle = {'cues': [1], 'cut_signature': 'cut1:' + 'c' * 32}
        fake_translate = types.ModuleType('resources.lib.translate')
        fake_translate.resolve = Mock(return_value=str(self.subtitle))
        ku = sys.modules['resources.lib.kodi_utils']
        ku.get_current_subtitle = Mock(return_value='original-link')
        ku.set_current_subtitle = Mock()
        ku.current_subtitle_selection = Mock(return_value=self._selection_snapshot())
        ku.apply_subtitle_file = Mock(return_value=True)
        ku.notify = Mock()
        with patch.dict(sys.modules, {'resources.lib.translate': fake_translate}), \
                patch.object(self.sub, '_job_matches_current', return_value=True), \
                patch.object(self.sub, '_job_stream_is_current', return_value=True), \
                patch.object(self.sub, '_selection_matches', return_value=True), \
                patch.object(self.sub, '_cached_reference_bundle', return_value=bundle), \
                patch.object(self.sub, '_tournament_candidate_text',
                             side_effect=[('1\n00:00:01,000 --> 00:00:02,000\nHDTV line\n',
                                           self.sub._decode_link(first)),
                                          ('1\n00:00:04,000 --> 00:00:05,500\nBluRay line\n',
                                           self.sub._decode_link(second))]), \
                patch.object(self.sub, '_verify_file_bundle', side_effect=verdicts):
            applied = self.sub._apply_verified_human_fallback(job)
        return applied, ku, first, second, job

    def test_a_map_the_subtitle_cannot_take_passes_to_the_next_row(self):
        # +103,787 ms on a cue at 1 s maps it before zero: apply_verdict refuses it
        sa = self.sub.sync_align
        fixable = {'status': sa.STATUS_FIXABLE, 'scale': 1.0, 'offset_ms': 103787.0, 'mode': 'global',
                   'diag': 'piecewise 2 regions offsets=+103787,-1841'}
        confirmed = {'status': sa.STATUS_CONFIRMED, 'scale': 1.0, 'offset_ms': 100.0, 'diag': 'confirmed'}
        with self.assertRaises(ValueError):
            sa.apply_verdict('1\n00:00:01,000 --> 00:00:02,000\nHDTV line\n', fixable)
        applied, ku, first, second, job = self.run_tournament(
            [(fixable, 'FILE TRACK #3', 1448), (confirmed, 'FILE TRACK #3', 1448)])
        self.assertTrue(applied)
        ku.set_current_subtitle.assert_called_once_with(second, renew=True)   # never the HDTV row
        self.assertTrue(job.get('_rejected_timing'))                          # not checked again

    def test_a_map_that_applies_is_still_used(self):
        sa = self.sub.sync_align
        fixable = {'status': sa.STATUS_FIXABLE, 'scale': 1.0, 'offset_ms': -500.0, 'mode': 'global',
                   'diag': 'global -500 ms'}
        applied, ku, first, second, job = self.run_tournament(
            [(fixable, 'FILE TRACK #3', 1448), (fixable, 'FILE TRACK #3', 1448)])
        self.assertTrue(applied)
        ku.set_current_subtitle.assert_called_once_with(first, renew=True)


del Base     # unittest would otherwise collect (and run) the legacy suite from this module


if __name__ == '__main__':
    unittest.main()
