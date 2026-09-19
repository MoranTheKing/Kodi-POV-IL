"""The remote playing-file timing probe indexes every useful subtitle track."""
import importlib.util
from pathlib import Path
import tempfile
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

    @staticmethod
    def _element(eid, payload):
        raw_id = eid.to_bytes((eid.bit_length() + 7) // 8, 'big')
        size = len(payload)
        for width in range(1, 9):
            if size < (1 << (7 * width)) - 1:
                raw_size = (size | (1 << (7 * width))).to_bytes(width, 'big')
                return raw_id + raw_size + payload
        raise ValueError(size)

    @classmethod
    def _uint(cls, eid, value):
        width = max(1, (value.bit_length() + 7) // 8)
        return cls._element(eid, value.to_bytes(width, 'big'))

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

    def test_profile_preserves_each_track_and_union_from_one_cues_read(self):
        sig = 'cut1:' + 'a' * 32
        with patch.object(ee, '_Source', return_value=self.src), \
             patch.object(ee, '_parse_head', return_value=(10, 1000000,
                                                           self.tracks, {})), \
             patch.object(ee, '_cut_signature_from_source', return_value=sig), \
             patch.object(ee, '_read_cue_times_multi', return_value={
                 2: [1000, 3000], 3: [1000, 2000]} ) as read, \
             patch.object(ee, '_timeline_origin', return_value=0):
            out = ee.cue_reference_profile('movie.mkv')
        self.assertEqual(read.call_count, 1)
        self.assertEqual(out['starts'], [1000, 2000, 3000])
        self.assertEqual([p['starts'] for p in out['track_starts']],
                         [[1000, 3000], [1000, 2000]])
        self.assertEqual(out['cut_signature'], sig)

    def test_non_matroska_profile_still_returns_content_cut_identity(self):
        sig = 'cut1:' + 'b' * 32
        with patch.object(ee, '_Source', return_value=self.src), \
             patch.object(ee, '_parse_head', side_effect=ValueError('not MKV')), \
             patch.object(ee, '_cut_signature_from_source', return_value=sig), \
             patch.object(ee, '_read_cue_times_multi') as read:
            out = ee.cue_reference_profile('movie.mp4')
        self.assertEqual(out['cut_signature'], sig)
        self.assertEqual(out['starts'], [])
        read.assert_not_called()

    def test_real_cues_parser_buckets_shared_points_by_track_in_one_read(self):
        points = []
        for when, tracks in ((100, (2, 3)), (200, (3,)), (300, (2,))):
            positions = b''.join(
                self._element(ee._CUE_TRACK_POS,
                              self._uint(ee._CUE_TRACK, track))
                for track in tracks)
            points.append(self._element(
                ee._CUE_POINT, self._uint(ee._CUE_TIME, when) + positions))
        cues = self._element(ee._CUES, b''.join(points))
        blob = b'\x00' * 64 + cues

        class Source:
            calls = 0

            def read(self, offset, size):
                self.calls += 1
                return blob[offset:offset + size]

        source = Source()
        out = ee._read_cue_times_multi(
            source, {ee._CUES: 64}, 0, {2, 3}, lambda _m: None)
        self.assertEqual(out, {2: [100, 300], 3: [100, 200]})
        self.assertEqual(source.calls, 1)

    def test_cut_signature_uses_content_not_path_and_detects_middle_change(self):
        with tempfile.TemporaryDirectory() as td:
            first = Path(td) / 'first.mkv'
            second = Path(td) / 'second.mkv'
            body = bytearray((i % 251 for i in range(300000)))
            first.write_bytes(body)
            second.write_bytes(body)
            sig1 = ee.media_cut_signature(str(first))
            sig2 = ee.media_cut_signature(str(second))
            self.assertRegex(sig1, r'^cut1:[0-9a-f]{32}$')
            self.assertEqual(sig1, sig2)  # paths never enter the identity
            changed = bytearray(body)
            changed[len(changed) // 2] ^= 0x7f
            second.write_bytes(changed)
            self.assertNotEqual(sig1, ee.media_cut_signature(str(second)))

    def test_cut_signature_refuses_a_short_or_partial_range(self):
        class ShortSource:
            total = 300000

            def read(self, offset, size):
                if offset:
                    return b'x' * (size - 1)
                return b'x' * size

        self.assertEqual(ee._cut_signature_from_source(ShortSource()), '')


if __name__ == '__main__':
    unittest.main()
