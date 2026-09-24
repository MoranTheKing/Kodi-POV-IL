"""Bounded MP4 timing-index tests with video-payload-free fixtures."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest


LIB = (Path(__file__).resolve().parents[1] /
       'addons/service.subtitles.kodipovilai/resources/lib')
SPEC = importlib.util.spec_from_file_location('mp4_probe_test', LIB / 'mp4_probe.py')
MP4 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MP4)
SYNC_SPEC = importlib.util.spec_from_file_location('mp4_sync_test', LIB / 'sync_align.py')
SYNC = importlib.util.module_from_spec(SYNC_SPEC)
SYNC_SPEC.loader.exec_module(SYNC)


def box(kind, body=b''):
    return struct.pack('>I4s', 8 + len(body), kind) + body


def fullbox(kind, body=b'', version=0):
    return box(kind, bytes([version, 0, 0, 0]) + body)


def make_mp4(*, index_at_end=False, edited=False, fragmented=False,
             codec=b'tx3g', sample_count=80):
    sizes = [10 if i % 2 == 0 else 2 for i in range(sample_count)]
    mvhd = fullbox(b'mvhd', b'\0' * 8 + struct.pack('>I', 1000))
    mdhd = fullbox(b'mdhd', b'\0' * 8 + struct.pack('>I', 1000))
    hdlr = fullbox(b'hdlr', b'\0' * 4 + b'sbtl')
    stsd = fullbox(b'stsd', struct.pack('>I', 1) + box(codec, b'\0' * 8))
    stts = fullbox(b'stts', struct.pack('>III', 1, sample_count, 1000))
    stsz = fullbox(b'stsz', struct.pack('>II', 0, sample_count)
                    + struct.pack('>%dI' % sample_count, *sizes))
    stbl = box(b'stbl', stsd + stts + stsz)
    mdia = box(b'mdia', mdhd + hdlr + box(b'minf', stbl))
    edts = b''
    if edited:
        # Two seconds of empty movie timeline followed by media starting 1 s in.
        elst = fullbox(b'elst', struct.pack('>I', 2)
                       + struct.pack('>Ii hh', 2000, -1, 1, 0)
                       + struct.pack('>Ii hh', 100000, 1000, 1, 0))
        edts = box(b'edts', elst)
    moov = box(b'moov', mvhd + box(b'trak', edts + mdia)
               + (box(b'mvex') if fragmented else b''))
    ftyp = box(b'ftyp', b'isom\0\0\0\0isom')
    mdat = box(b'mdat', b'video' * 10000)
    return ftyp + (mdat + moov if index_at_end else moov + mdat)


class MP4ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'movie.mp4'

    def test_index_at_head_and_tail_recover_only_nonempty_cues(self):
        for at_end in (False, True):
            with self.subTest(at_end=at_end):
                self.path.write_bytes(make_mp4(index_at_end=at_end))
                result = MP4.subtitle_reference(self.path)
                self.assertEqual(len(result['cues']), 40)
                self.assertEqual([x['start'] for x in result['cues']],
                                 list(range(0, 80000, 2000)))
                self.assertLess(result['bytes'], 1000)

    def test_simple_edit_list_maps_to_playback_time(self):
        self.path.write_bytes(make_mp4(edited=True))
        starts = MP4.cue_onsets(self.path)[0]['cues']
        self.assertEqual(starts[:4], [1000, 3000, 5000, 7000])

    def test_quicktime_text_track_uses_same_timing_index(self):
        self.path.write_bytes(make_mp4(codec=b'text'))
        result = MP4.subtitle_reference(self.path)
        self.assertEqual(len(result['cues']), 40)
        self.assertEqual(result['track']['codec'], 'text')

    def test_quicktime_without_ftyp_can_still_find_moov(self):
        movie = make_mp4(codec=b'text')
        ftyp_len = struct.unpack_from('>I', movie, 0)[0]
        self.path.write_bytes(movie[ftyp_len:])
        result = MP4.subtitle_reference(self.path)
        self.assertEqual(len(result['cues']), 40)

    def test_mp4_index_drives_confirmed_and_shifted_verdicts(self):
        self.path.write_bytes(make_mp4(sample_count=240))
        reference = MP4.subtitle_reference(self.path)['cues']

        def stamp(ms):
            return '%02d:%02d:%02d,%03d' % (
                ms // 3600000, ms // 60000 % 60,
                ms // 1000 % 60, ms % 1000)

        def subtitle(shift):
            return '\n\n'.join(
                '%d\n%s --> %s\nCue %d' % (
                    i + 1, stamp(cue['start'] + shift),
                    stamp(cue['start'] + shift + 1000), i + 1)
                for i, cue in enumerate(reference))

        self.assertEqual(SYNC.verify_cues(reference, subtitle(0))['status'],
                         'CONFIRMED')
        self.assertEqual(SYNC.verify_cues(reference, subtitle(6000))['status'],
                         'FIXABLE')

    def test_fragmented_or_unsupported_text_codec_abstains(self):
        for options in ({'fragmented': True}, {'codec': b'wvtt'}):
            with self.subTest(options=options):
                self.path.write_bytes(make_mp4(**options))
                self.assertIsNone(MP4.subtitle_reference(self.path))

    def test_no_index_and_truncated_file_abstain(self):
        self.path.write_bytes(box(b'ftyp', b'isom') + box(b'mdat', b'abc'))
        self.assertIsNone(MP4.subtitle_reference(self.path))
        self.path.write_bytes(b'\0\0\0\x20moov')
        self.assertIsNone(MP4.subtitle_reference(self.path))


if __name__ == '__main__':
    unittest.main()
