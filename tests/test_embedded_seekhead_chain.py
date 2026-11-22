"""The Cues index listed by a further SeekHead (QA, 17 Nov 2026: a 2.2 GB HDTV
episode whose head's SeekHead lists only a SeekHead and the Tags at the end of
the file; the Cues are two SeekHeads further). Read from the head alone it was
"no index" and its English text track was never translated."""

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'service.subtitles.kodipovilai/resources/lib/embedded_extract.py'


def load():
    spec = importlib.util.spec_from_file_location('embedded_seekhead_chain_test', MODULE)
    module = importlib.util.module_from_spec(spec)
    stubs = {n: types.ModuleType(n) for n in ('xbmc', 'xbmcaddon', 'xbmcvfs', 'xbmcgui')}
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


def vsize(n):
    """An 8-byte EBML size, so a placeholder never changes an element's length."""
    return bytes([0x01]) + n.to_bytes(7, 'big')


def el(eid, payload):
    return eid.to_bytes((eid.bit_length() + 7) // 8, 'big') + vsize(len(payload)) + payload


def uint(eid, value, width=8):
    return el(eid, value.to_bytes(width, 'big'))


SEEKHEAD, SEEK, SEEKID, SEEKPOS = 0x114D9B74, 0x4DBB, 0x53AB, 0x53AC
INFO, TRACKS, CLUSTER, CUES, TAGS = 0x1549A966, 0x1654AE6B, 0x1F43B675, 0x1C53BB6B, 0x1254C367


def seekhead(entries):
    return el(SEEKHEAD, b''.join(
        el(SEEK, el(SEEKID, eid.to_bytes(4, 'big')) + uint(SEEKPOS, pos)) for eid, pos in entries))


def block(ms, text, dur):
    raw = bytes([0x81]) + ms.to_bytes(2, 'big', signed=True) + b'\x00' + text.encode('utf-8')
    return el(0xA0, el(0xA1, raw) + uint(0x9B, dur, 2))


LINES = [(1000, 'Hello there.', 1500), (4000, 'Where are we going?', 2000), (8000, 'To the Alps.', 1800)]


def build(chain=True):
    """An MKV whose Cues are listed by a SeekHead two hops from the head's (chain=True), or by the head's."""
    info = el(INFO, uint(0x2AD7B1, 1000000, 4))
    tracks = el(TRACKS, el(0xAE, uint(0xD7, 1, 1) + uint(0x83, 17, 1) + el(0x86, b'S_TEXT/UTF8')
                           + el(0x22B59C, b'eng')))
    cluster = el(CLUSTER, uint(0xE7, 0, 2) + b''.join(block(*l) for l in LINES))
    pos = {}
    for _ in range(2):          # positions are fixed-width: the second pass is exact
        sh1 = seekhead([(SEEKHEAD, pos.get('sh2', 0)), (INFO, pos.get('info', 0))] if chain
                       else [(CUES, pos.get('cues', 0)), (INFO, pos.get('info', 0))])
        body = sh1
        pos['info'] = len(body)
        body += info + tracks
        pos['cluster'] = len(body)
        body += cluster
        cues = el(CUES, b''.join(
            el(0xBB, uint(0xB3, ms) + el(0xB7, uint(0xF7, 1, 1) + uint(0xF1, pos['cluster'])))
            for ms, _t, _d in LINES))
        pos['cues'] = len(body)
        body += cues
        pos['sh3'] = len(body)
        body += seekhead([(CUES, pos['cues'])])
        pos['tags'] = len(body)
        body += el(TAGS, b'')
        pos['sh2'] = len(body)
        body += seekhead([(SEEKHEAD, pos['sh3']), (TAGS, pos['tags'])])
    ebml = el(0x1A45DFA3, el(0x4282, b'matroska'))
    return ebml + el(0x18538067, body), len(ebml) + 12, pos


class FakeSource(object):
    is_http = True

    def __init__(self, data):
        self.data = data
        self.reads = []

    def read(self, offset, length):
        self.reads.append((offset, length))
        return self.data[offset:offset + length]


class SeekHeadChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ee = load()

    def head(self, data):
        src = FakeSource(data)
        seg_start, _ts, tracks, seeks = self.ee._parse_head(src, len(data), lambda m: None)
        return src, seg_start, tracks, seeks

    def test_the_head_alone_does_not_list_the_cues(self):
        data, seg, pos = build()
        _src, seg_start, tracks, seeks = self.head(data)
        self.assertEqual(seg_start, seg)
        self.assertNotIn(self.ee._CUES, seeks)
        self.assertEqual(seeks[self.ee._SEEKHEAD], seg + pos['sh2'])
        self.assertEqual([t['codec'] for t in tracks], ['S_TEXT/UTF8'])

    def test_the_cues_are_found_two_seekheads_further(self):
        data, seg, pos = build()
        src, seg_start, _tracks, seeks = self.head(data)
        said = []
        self.assertEqual(self.ee._cues_pos(src, seeks, seg_start, said.append), seg + pos['cues'])
        self.assertEqual(seeks[TAGS], seg + pos['tags'])     # what the further SeekHeads list joins `seeks`
        self.assertTrue(any('further SeekHead (2 read(s))' in m for m in said), said)
        # the chain is read once: a second caller asks for nothing
        before = len(src.reads)
        self.assertEqual(self.ee._cues_pos(src, seeks, seg_start), seg + pos['cues'])
        self.assertEqual(len(src.reads), before)

    def test_the_index_points_at_the_subtitle_cluster(self):
        data, seg, pos = build()
        src, seg_start, _tracks, seeks = self.head(data)
        positions, is_sub = self.ee._read_cues(src, seeks, seg_start, 1, lambda m: None)
        self.assertTrue(is_sub)
        self.assertEqual({p[0] for p in positions}, {seg + pos['cluster']})
        times = self.ee._read_cue_times_multi(src, seeks, seg_start, [1], lambda m: None)
        self.assertEqual(sorted(times[1]), [ms for ms, _t, _d in LINES])

    def test_a_head_that_lists_the_cues_reads_nothing_more(self):
        data, seg, pos = build(chain=False)
        src, seg_start, _tracks, seeks = self.head(data)
        before = len(src.reads)
        self.assertEqual(self.ee._cues_pos(src, seeks, seg_start), seg + pos['cues'])
        self.assertEqual(len(src.reads), before)

    def test_a_loop_or_a_wrong_element_ends_the_search(self):
        data, seg, pos = build()
        src, seg_start, _tracks, seeks = self.head(data)
        seeks[self.ee._SEEKHEAD] = seg + pos['info']      # not a SeekHead there
        self.assertIsNone(self.ee._cues_pos(src, dict(seeks), seg_start))
        loop = seekhead([(SEEKHEAD, 0)])                  # a SeekHead that lists itself
        src2 = FakeSource(b'\x00' * seg + loop)
        self.assertIsNone(self.ee._cues_pos(src2, {self.ee._SEEKHEAD: seg}, seg))
        self.assertEqual(len(src2.reads), 1)
        self.assertIsNone(self.ee._cues_pos(FakeSource(b''), {}, 0))

    def test_a_failed_read_on_the_way_is_not_called_no_index(self):
        data, seg, pos = build()
        src, seg_start, _tracks, seeks = self.head(data)
        real = src.read

        def dropped(offset, length):
            return b'' if offset == seg + pos['sh3'] else real(offset, length)
        src.read = dropped
        src.tripped = False
        src._stats = {}
        self.assertIsNone(self.ee._cues_pos(src, seeks, seg_start))
        self.assertTrue(getattr(src, '_cues_unsure', False))
        ok = self.ee._extract_cues(src, seeks, seg_start, 1, [], 0, 90.0, 0.0, None, lambda m: None)
        self.assertFalse(ok)
        # not 'no_index': since 0.3.111 an index that did not answer is said so
        self.assertEqual(src._stats.get('why'), 'index_unread')
        # a chain that simply ends -- a further SeekHead with no Cues and no
        # SeekHead in it -- is a file with no index, as before
        src2 = FakeSource(b'\x00' * seg + seekhead([(TAGS, 0)]))
        self.assertIsNone(self.ee._cues_pos(src2, {self.ee._SEEKHEAD: seg}, seg))
        self.assertFalse(getattr(src2, '_cues_unsure', False))

    def test_the_whole_track_is_read_through_the_index(self):
        data, _seg, _pos = build()
        fd, path = tempfile.mkstemp(suffix='.mkv')
        os.close(fd)
        try:
            with open(path, 'wb') as f:
                f.write(data)
            said = []
            srt = self.ee.extract_srt(path, lang='en', log=said.append)
        finally:
            os.remove(path)
        self.assertTrue(any('further SeekHead' in m for m in said), said)
        self.assertIsNotNone(srt, said)
        for _ms, text, _d in LINES:
            self.assertIn(text, srt)
        self.assertIn('00:00:01,000 --> 00:00:02,500', srt)


if __name__ == '__main__':
    unittest.main()
