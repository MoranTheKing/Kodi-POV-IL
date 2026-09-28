"""Legacy Matroska ASS/SSA subtitles supply usable playing-file timing."""
import importlib.util
from pathlib import Path
import unittest


MODULE = (Path(__file__).resolve().parents[1] /
          'addons/service.subtitles.kodipovilai/resources/lib/embedded_extract.py')
spec = importlib.util.spec_from_file_location('embedded_legacy_ass_under_test', MODULE)
ee = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ee)


class LegacyAssTests(unittest.TestCase):
    def test_old_ass_ssa_tracks_are_selectable_but_bitmap_and_forced_are_not(self):
        tracks = [
            {'num': 1, 'codec': 'S_HDMV/PGS', 'lang': 'eng',
             'forced': False, 'lang_explicit': True},
            {'num': 2, 'codec': 'S_ASS', 'lang': 'eng',
             'forced': True, 'lang_explicit': True},
            {'num': 3, 'codec': 'S_SSA', 'lang': 'eng',
             'forced': False, 'lang_explicit': True},
        ]
        self.assertTrue(ee._is_text_codec('S_ASS'))
        self.assertTrue(ee._is_text_codec('S_SSA'))
        self.assertFalse(ee._is_text_codec('S_HDMV/PGS'))
        self.assertFalse(ee._is_text_codec('S_USF'))
        self.assertEqual(ee._pick_track(tracks, None, 'en')['num'], 3)

    def test_legacy_packet_decodes_dialogue_and_preserves_matroska_timing(self):
        packet = ('0,0,Default,,0,0,0,,{\\i1}שלום, עולם{\\i0}\\Nמה נשמע?'
                  ).encode('utf-8')
        for codec in ('S_ASS', 'S_SSA', 'S_TEXT/ASS', 'S_TEXT/SSA'):
            srt = ee._entries_to_srt([(1530, 2700, packet)], 1.0, 0, codec)
            self.assertIn('00:00:01,530 --> 00:00:04,230', srt)
            self.assertIn('שלום, עולם\nמה נשמע?', srt)
            self.assertNotIn('Default', srt)

    def test_malformed_ass_packet_never_becomes_a_subtitle(self):
        for codec in ('S_ASS', 'S_SSA', 'S_TEXT/ASS', 'S_TEXT/SSA'):
            self.assertEqual(ee._decode_frame(b'0,0,Default', codec), '')


if __name__ == '__main__':
    unittest.main()
