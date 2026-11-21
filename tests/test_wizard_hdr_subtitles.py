"""Wizard 0.5.45: subtitles on HDR video at full white.

A viewer (21 Nov 2026, a photo of his TV): "why are the subtitles such an ugly colour and not bright white -- it
wasn't like this before; the black around them is fine, but the letters are dark". In HDR (PQ) mode Kodi draws
subtitles at "GUI peak luminance in HDR PQ mode", default 40 % -- on Android (0.7 x 40 + 30) % = 58 % of white.
The box behind the subtitles hid it until 15 Nov. Kodi's own 40 goes to 100 once per profile; any other value
is someone's choice and stays. Kodi's JSON-RPC answers for the setting only while it is visible, i.e. on a
display that can show HDR (Kodi 21, SettingsOperations.cpp: setting->IsVisible()).
"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('povil_subtitle_style_tests_for_hdr',
                                               REPO / 'tests/test_wizard_subtitle_style.py')
_style_tests = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_style_tests)
Base = _style_tests.SubtitleStyleTests
KEY = 'videoscreen.guipeakluminance'


class HdrSubtitlesWhite(unittest.TestCase):
    _base_setUp = Base.setUp

    def setUp(self):
        self._base_setUp()
        self.kodi[KEY] = 40
        self.hdr_display = True
        xbmc = sys.modules['xbmc']
        inner = xbmc.executeJSONRPC

        def rpc(text):
            req = json.loads(text)
            if req['params']['setting'] == KEY and not self.hdr_display:
                return json.dumps({'error': {'code': -32602}})      # not visible: InvalidParams, both ways
            return inner(text)
        xbmc.executeJSONRPC = rpc

    def test_kodis_40_becomes_100_and_is_saved(self):
        self.assertTrue(self.style.brighten_hdr())
        self.assertEqual(self.writes, [(KEY, 100)])
        self.assertEqual(self.kodi[KEY], 100)
        self.assertEqual(len(self.saves), 1)                    # Kodi 21 changes memory only
        self.assertEqual(self.saves[0][KEY], 100)
        self.assertEqual(self.settings['hdr_subtitles_white_v1'], 'applied')
        self.assertTrue(any('full white' in line and '40 -> 100' in line for line in self.logged))

    def test_once(self):
        self.style.brighten_hdr()
        self.kodi[KEY] = 40                                     # set back by hand, later
        del self.writes[:]
        self.assertFalse(self.style.brighten_hdr())
        self.assertEqual(self.writes, [])

    def test_a_value_someone_chose_is_kept(self):
        for value in (0, 55, 70, 99):
            with self.subTest(value):
                self.settings.clear()
                self.kodi[KEY] = value
                del self.writes[:]
                self.assertFalse(self.style.brighten_hdr())
                self.assertEqual(self.writes, [])
                self.assertEqual(self.settings['hdr_subtitles_white_v1'], 'kept')

    def test_already_white_is_marked_without_a_write(self):
        self.kodi[KEY] = 100
        self.assertFalse(self.style.brighten_hdr())
        self.assertEqual(self.writes, [])
        self.assertEqual(self.settings['hdr_subtitles_white_v1'], 'applied')

    def test_no_hdr_display_changes_and_marks_nothing_until_one_is_there(self):
        self.hdr_display = False
        self.assertFalse(self.style.brighten_hdr())
        self.assertEqual((self.writes, self.settings), ([], {}))
        self.hdr_display = True                                 # the box on a TV that can show HDR, later
        self.assertTrue(self.style.brighten_hdr())
        self.assertEqual(self.kodi[KEY], 100)

    def test_refused_or_unsaved_is_tried_again_at_the_next_start(self):
        self.refuse.add(KEY)
        self.assertFalse(self.style.brighten_hdr())
        self.assertNotIn('hdr_subtitles_white_v1', self.settings)
        self.refuse.clear()
        self.saved = False
        self.assertTrue(self.style.brighten_hdr())
        self.assertNotIn('hdr_subtitles_white_v1', self.settings)
        self.saved = True
        self.assertFalse(self.style.brighten_hdr())             # 100 now, saved by Kodi's next save
        self.assertEqual(self.settings['hdr_subtitles_white_v1'], 'applied')

    def test_the_subtitle_look_is_untouched(self):
        before = {k: v for k, v in self.kodi.items() if k.startswith('subtitles.')}
        self.style.brighten_hdr()
        self.assertEqual({k: v for k, v in self.kodi.items() if k.startswith('subtitles.')}, before)

    def test_the_start_up_runs_it_after_the_outline(self):
        startup = (REPO / 'plugin.program.kodipovilwizard/startup.py').read_text(encoding='utf-8')
        self.assertEqual(startup.count('subtitle_style.brighten_hdr()'), 1)
        self.assertLess(startup.index('subtitle_style.migrate()'), startup.index('subtitle_style.brighten_hdr()'))
        self.assertLess(startup.index('subtitle_style.brighten_hdr()'), startup.index('_subtitle_style_err'))


del Base     # unittest would otherwise collect (and run) the subtitle-style suite from this module


if __name__ == '__main__':
    unittest.main()
