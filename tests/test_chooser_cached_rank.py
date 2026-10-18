"""The subtitle chooser ranks with stored timing verdicts only.

A new comparison against the playing file's cue profile took 7.7 s each on a
Shield and kept the chooser closed for 16 s (field log, Oct 2026). The
chooser passes cached_only=True: no comparison runs, verdicts the sync
already stored for this file still order the list.
"""
import importlib.util
import json
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    'subsync_harness', ROOT / 'tools' / 'test_subsync_remote_playback_safety.py')
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)
harness.LIB = ROOT / 'service.subtitles.kodipovilai' / 'resources' / 'lib'


def _candidate(name):
    payload = {'type': 'engine', 'source': 'Ktuvit', 'language': 'Hebrew', 'filename': name}
    return {'filename': name, 'language': 'he', 'link': urllib.parse.quote(json.dumps(payload))}


class ChooserCachedRank(unittest.TestCase):
    # The playback-safety harness's fixtures only, not its tests.
    setUp = harness.RemotePlaybackSafety.setUp
    _selection_snapshot = harness.RemotePlaybackSafety._selection_snapshot
    _selection_matches = harness.RemotePlaybackSafety._selection_matches

    def _rank(self, stored, texts):
        rows = [_candidate('Show.S01E03.1080p.WEB.H264-CAKES'),
                _candidate('Show.S01E03.1080p.WEB.H264-OTHER')]
        bundle = {'cues': [1], 'cut_signature': 'cut1:' + 'a' * 32}
        ready = [(text, self.sub._decode_link(row['link'])) for text, row in zip(texts, rows)]
        self.sub._load_verdicts.return_value = stored
        with patch.object(self.sub, 'playing_release',
                          return_value='Show.S01E03.1080p.WEB.H264-CAKES'), \
                patch.object(self.sub, '_cached_reference_bundle', return_value=bundle), \
                patch.object(self.sub, '_ready_candidate_text', side_effect=ready), \
                patch.object(self.sub, '_verify_file_bundle') as verify:
            out = self.sub.rank_picker_candidates({}, rows, cached_only=True)
        verify.assert_not_called()
        return rows, out

    def test_no_comparison_runs_and_a_stored_proof_still_ranks(self):
        key = self.sub._cache_key('second text', 'Show.S01E03.1080p.WEB.H264-CAKES',
                                  'cut1:' + 'a' * 32)
        confirmed = {'status': self.sub.sync_align.STATUS_CONFIRMED, 'scale': 1.0,
                     'offset_ms': 0.0, 'vote': .95, 'overlap': .95, 'diag': 'confirmed',
                     'v': self.sub._VERDICT_VERSION}
        rows, out = self._rank({key: confirmed}, ['first text', 'second text'])
        self.assertIs(out[0], rows[1])

    def test_nothing_stored_keeps_the_order(self):
        rows, out = self._rank({}, ['first text', 'second text'])
        self.assertEqual([r['filename'] for r in out], [r['filename'] for r in rows])



if __name__ == '__main__':
    unittest.main()
