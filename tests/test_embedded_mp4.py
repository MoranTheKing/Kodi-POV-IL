"""Embedded text subtitles from an MP4 (MoranSubs 0.3.83). The owner (14 Nov 2026): "make sure extraction
works on MP4 files too and does not fail" -- QA had met two 4K DV WEB-DLs that are MP4 (The Dark Knight,
The Matrix) and the pick ended in "could not extract".

Fixtures (tests/fixtures/embedded_mp4, made with ffmpeg 9 from three SRTs): faststart.mp4 (moov first; tx3g
tracks #3 English 40 lines, #4 French 40 lines starting 0.5 s later, #5 English 3 lines flagged forced) and
moovend.mp4 (moov after mdat; one English track)."""
import importlib.util
import struct
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'service.subtitles.kodipovilai/resources/lib'
FIX = ROOT / 'tests/fixtures/embedded_mp4'
URL = 'https://cdn.example/film.mp4'

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_embedded_gentle_read import Session  # noqa: E402  (the fake Range session)


def _load(name):
    spec = importlib.util.spec_from_file_location('mp4test_' + name, LIB / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {n: types.ModuleType(n) for n in ('xbmc', 'xbmcaddon', 'xbmcvfs', 'xbmcgui')}):
        spec.loader.exec_module(mod)
    return mod


def box(typ, payload=b''):
    return struct.pack('>I4s', 8 + len(payload), typ) + payload


def full(typ, payload, version=0, flags=0):
    return box(typ, struct.pack('>I', (version << 24) | flags) + payload)


class Local(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ee = _load('embedded_extract')

    def test_english_from_a_faststart_file(self):
        srt = self.ee.extract_srt(str(FIX / 'faststart.mp4'), lang='en')
        self.assertEqual(srt.count('-->'), 40)
        self.assertIn('00:00:03,000 --> 00:00:04,500\nEnglish line 2\n', srt)
        self.assertNotIn('Sign', srt)                                   # the forced track is not read

    def test_moov_after_the_media(self):
        srt = self.ee.extract_srt(str(FIX / 'moovend.mp4'), lang='en')
        self.assertEqual(srt.count('-->'), 40)
        self.assertIn('00:01:57,000 --> 00:01:58,500\nEnglish line 40', srt)

    def test_french_track_keeps_its_own_timing(self):
        srt = self.ee.extract_srt(str(FIX / 'faststart.mp4'), lang='fr')
        self.assertEqual(srt.count('-->'), 40)
        self.assertIn('00:00:00,500 --> 00:00:02,000\nFrançais ligne é line 1\n', srt)

    def test_a_language_not_in_the_file(self):
        stats = {}
        self.assertIsNone(self.ee.extract_srt(str(FIX / 'faststart.mp4'), lang='de', stats=stats))
        self.assertEqual(stats.get('why'), 'not_mkv')                   # the caller offers the external one


class OverHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ee = _load('embedded_extract')

    def run_http(self, name, many, pad=0, **kw):
        blob = (FIX / name).read_bytes() + bytes(pad)
        sessions = []

        def new_session():
            s = Session(blob, None, many)
            sessions.append(s)
            return s
        with patch.object(self.ee, '_new_session', new_session), patch.object(self.ee, '_HTTP_REQ_PACE_S', 0.0):
            got = self.ee.extract_srt(URL, lang='en', allow_http=True, **kw)
        return got, sessions

    def test_batched_like_a_matroska_track(self):
        local = self.ee.extract_srt(str(FIX / 'faststart.mp4'), lang='en')
        got, sessions = self.run_http('faststart.mp4', 'multipart', pad=4 * 1024 * 1024)
        self.assertEqual(got, local)
        multi = [m for s in sessions for m in s.multi]
        self.assertEqual(len(multi), 1)                                 # the 40 lines in one request
        asked = [a for s in sessions for a in s.asked if a[1] > 1]
        self.assertLessEqual(len(asked), 4)                            # a head piece, the box headers, moov

    def test_a_node_that_answers_one_range_still_reads_it(self):
        local = self.ee.extract_srt(str(FIX / 'moovend.mp4'), lang='en')
        got, _sessions = self.run_http('moovend.mp4', 'first')
        self.assertEqual(got, local)

    def test_the_lines_near_the_viewer_come_first(self):
        shown, windows = [], [(30000, 45000), None]
        steps = (lambda: windows.pop(0), shown.append, lambda starts: None)
        got, _s = self.run_http('faststart.mp4', 'multipart', steps=steps, resume_path='unused')
        self.assertEqual(got.count('-->'), 40)
        self.assertEqual(len(shown), 1)
        self.assertEqual(shown[0].count('-->'), 6)                      # 30.0 .. 45.0 s: lines 11-16
        self.assertIn('English line 11', shown[0])

    def test_the_head_serves_the_box_headers_and_a_small_moov(self):
        _got, sessions = self.run_http('faststart.mp4', 'multipart', pad=4 * 1024 * 1024)
        asked = [a for s in sessions for a in s.asked if a[1] > 1]
        self.assertEqual(len(asked), 1)                                 # the first head piece only

    def test_a_reading_cut_part_way_is_not_called_unreadable(self):
        # review: the buffer gate's stop, a dropped answer or the budget is not the file's fault -- no
        # external subtitle instead, and no "progress saved" (nothing is)
        calls = []
        stats = {}
        got, _s = self.run_http('faststart.mp4', 'multipart', pad=4 * 1024 * 1024, stats=stats,
                                abort_cb=lambda: calls.append(1) or len(calls) > 1)
        self.assertIsNone(got)
        self.assertEqual(stats.get('why'), 'mp4_cut')
        self.assertEqual(stats.get('done'), 0)

    def test_a_box_the_parser_cannot_read_falls_back(self):
        stats = {}
        mp4 = self.ee._mp4()
        with patch.object(mp4, 'tracks', side_effect=struct.error('bad box')):
            got, _s = self.run_http('faststart.mp4', 'multipart', stats=stats)
        self.assertIsNone(got)
        self.assertEqual(stats.get('why'), 'not_mkv')

    def test_http_not_allowed(self):
        blob = (FIX / 'faststart.mp4').read_bytes()
        with patch.object(self.ee, '_new_session', lambda: Session(blob, None, 'multipart')):
            self.assertIsNone(self.ee.extract_srt(URL, lang='en', allow_http=False))


class Tables(unittest.TestCase):
    """embedded_mp4 on hand-built boxes: the forms ffmpeg's fixtures do not use."""

    @classmethod
    def setUpClass(cls):
        cls.mp4 = _load('embedded_mp4')

    def moov(self, stbl_extra, handler=b'text', entry=b'tx3g', elst=None, lang=b'\x15\xc7', name=b''):
        tx3g = box(entry, bytes(6) + struct.pack('>H', 1) + struct.pack('>I', 0) + bytes(34))
        stsd = full(b'stsd', struct.pack('>I', 1) + tx3g)
        stbl = box(b'stbl', stsd + stbl_extra)
        mdhd = full(b'mdhd', struct.pack('>IIII', 0, 0, 1000, 0) + lang + b'\x00\x00')
        hdlr = full(b'hdlr', struct.pack('>I', 0) + handler + bytes(12) + b'\x00')
        mdia = box(b'mdia', mdhd + hdlr + box(b'minf', stbl))
        tkhd = full(b'tkhd', struct.pack('>III', 0, 0, 7) + bytes(68))
        edts = box(b'edts', full(b'elst', struct.pack('>I', len(elst)) + b''.join(
            struct.pack('>IiI', d, m, 0x10000) for d, m in elst))) if elst else b''
        udta = box(b'udta', box(b'name', name)) if name else b''
        mvhd = full(b'mvhd', struct.pack('>III', 0, 0, 600) + bytes(84))
        return box(b'moov', mvhd + box(b'trak', tkhd + edts + mdia + udta))

    def test_co64_stz2_and_a_leading_empty_edit(self):
        stz2 = full(b'stz2', bytes(3) + bytes([16]) + struct.pack('>I', 3) + struct.pack('>3H', 2, 12, 9))
        co64 = full(b'co64', struct.pack('>I', 2) + struct.pack('>2Q', 5 * 10 ** 9, 6 * 10 ** 9))
        stsc = full(b'stsc', struct.pack('>I', 2) + struct.pack('>III', 1, 2, 1) + struct.pack('>III', 2, 1, 1))
        stts = full(b'stts', struct.pack('>I', 1) + struct.pack('>II', 3, 2000))
        d = self.moov(stz2 + co64 + stsc + stts, elst=[(600, -1), (0, 0)])   # 1 s of nothing first
        tr = self.mp4.tracks(d)[0]
        self.assertEqual((tr['num'], tr['lang'], tr['codec']), (7, 'eng', 'S_TEXT/MP4_TX3G'))
        got = self.mp4.samples(d, tr)
        self.assertEqual(got, [(5 * 10 ** 9, 2, 1000, 3000), (5 * 10 ** 9 + 2, 12, 3000, 5000),
                               (6 * 10 ** 9, 9, 5000, 7000)])

    def test_a_table_count_the_file_cannot_back_is_capped(self):
        stsz = full(b'stsz', struct.pack('>II', 4, 2 * 10 ** 9))          # fixed size, 2e9 "samples"
        stco = full(b'stco', struct.pack('>I', 1) + struct.pack('>I', 1000))
        stsc = full(b'stsc', struct.pack('>I', 1) + struct.pack('>III', 1, 3, 1))
        d = self.moov(stsz + stco + stsc)
        got = self.mp4.samples(d, self.mp4.tracks(d)[0])
        self.assertEqual([s[:2] for s in got], [(1000, 4), (1004, 4), (1008, 4)])   # what the chunks hold

    def test_a_picture_track_and_a_forced_name(self):
        stsz = full(b'stsz', struct.pack('>II', 4, 1))
        d = self.moov(stsz, handler=b'subp', entry=b'mp4s')
        self.assertEqual(self.mp4.tracks(d)[0]['codec'], 'S_VOBSUB')
        d = self.moov(stsz, name=b'English Forced')
        self.assertTrue(self.mp4.tracks(d)[0]['forced'])

    def test_sample_text_forms(self):
        t = self.mp4.sample_text
        self.assertEqual(t(struct.pack('>H', 5) + b'Hello' + box(b'styl', bytes(4)), b'tx3g'), 'Hello')
        u16 = '﻿שלום'.encode('utf-16-be')
        self.assertEqual(t(struct.pack('>H', len(u16)) + u16, b'tx3g'), 'שלום')
        self.assertEqual(t(struct.pack('>H', 0), b'tx3g'), '')
        vtt = box(b'vttc', box(b'payl', 'one\r\ntwo'.encode()))
        self.assertEqual(t(vtt + box(b'vttc', box(b'payl', b'three')), b'wvtt'), 'one\ntwo\nthree')
        self.assertEqual(t(box(b'vtte'), b'wvtt'), '')

    def test_find_moov_walks_past_a_large_mdat(self):
        head = box(b'ftyp', b'isom' + bytes(4)) + struct.pack('>I4sQ', 1, b'mdat', 16 + 10 ** 10)
        moov = box(b'moov', bytes(8))
        blob = {0: head}
        at = len(head) - 16 + 16 + 10 ** 10 - 16 + 16           # ftyp + the 64-bit mdat

        def read(off, n):
            if off == 0:
                return head[:n]
            if off == len(box(b'ftyp', b'isom' + bytes(4))):
                return head[off:off + n]
            if off == at:
                return moov[:n]
            return b''
        self.assertEqual(self.mp4.find_moov(read, 0), (at, len(moov)))


if __name__ == '__main__':
    unittest.main()
