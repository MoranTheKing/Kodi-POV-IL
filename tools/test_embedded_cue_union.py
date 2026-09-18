"""The remote playing-file timing probe indexes every useful subtitle track."""
import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / 'addons/service.subtitles.kodipovilai/resources/lib/'
          'embedded_extract.py')
spec = importlib.util.spec_from_file_location('cue_union_under_test', MODULE)
ee = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ee)


class CueUnionTests(unittest.TestCase):
    def setUp(self):
        self.src = types.SimpleNamespace(
            total=100000, is_http=False, reqs=2, fetched=4096,
            _abort_cb=None)
        self.tracks = [
            {'type': ee._SUB_TRACK_TYPE, 'num': 2, 'codec': 'S_TEXT/UTF8',
             'lang': 'eng', 'forced': False, 'lang_explicit': True},
            {'type': ee._SUB_TRACK_TYPE, 'num': 3, 'codec': 'S_HDMV/PGS',
             'lang': 'heb', 'forced': False, 'lang_explicit': True},
            {'type': ee._SUB_TRACK_TYPE, 'num': 4, 'codec': 'S_TEXT/UTF8',
             'lang': 'eng', 'forced': True, 'lang_explicit': True},
        ]

    def test_no_selector_unions_text_and_bitmap_but_not_forced(self):
        seen = []
        with patch.object(ee, '_Source', return_value=self.src), \
             patch.object(ee, '_parse_head', return_value=(10, 1000000,
                                                           self.tracks, {})), \
             patch.object(ee, '_read_cue_times_multi',
                          side_effect=lambda src, seeks, seg, want, log: (
                              seen.append(set(want)) or
                              {2: [1000, 3000], 3: [1000, 2000]})), \
             patch.object(ee, '_read_cue_times',
                          side_effect=AssertionError('single-track read')), \
             patch.object(ee, '_timeline_origin', return_value=0):
            out = ee.cue_reference_times('movie.mkv')
        self.assertEqual(seen, [{2, 3}])
        self.assertEqual(out, [1000, 2000, 3000])

    def test_language_selector_keeps_old_single_text_track_semantics(self):
        with patch.object(ee, '_Source', return_value=self.src), \
             patch.object(ee, '_parse_head', return_value=(10, 1000000,
                                                           self.tracks, {})), \
             patch.object(ee, '_read_cue_times_multi',
                          side_effect=AssertionError('union read')), \
             patch.object(ee, '_read_cue_times', return_value=[500, 1500]) as one, \
             patch.object(ee, '_timeline_origin', return_value=0):
            out = ee.cue_reference_times('movie.mkv', lang='en')
        self.assertEqual(out, [500, 1500])
        self.assertEqual(one.call_args.args[3], 2)


if __name__ == '__main__':
    unittest.main()
