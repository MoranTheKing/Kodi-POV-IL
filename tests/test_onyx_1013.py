"""Onyx 1.0.13: the info panel's plot under the pills, POV's own lists among the favourites chips, and a skin
that is dark rather than black (field reports of 17 Nov 2026)."""
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'skin.povil.onyx'
XML = SKIN / 'xml'


def number(control, tag):
    return int(control.findtext(tag))


class InfoPanelTests(unittest.TestCase):
    def test_the_plot_starts_under_what_is_over_it(self):
        """1.0.12 drew the pills at 298-340 and left the plot at 300: one written over the other.
        Since 1.0.15 the pills are over the timeline and the ratings row is what the plot follows."""
        root = ET.parse(XML / 'VideoFullScreen.xml').getroot()
        plot = next(c for c in root.iter('control') if c.get('type') == 'textbox' and
                    'VideoPlayer.Plot' in (c.findtext('label') or ''))
        ratings = next(c for c in root.iter('control') if c.get('description') == 'ratings')
        self.assertGreaterEqual(number(plot, 'top'), number(ratings, 'top') + number(ratings, 'height'))
        details = next(c for c in root.iter('control') if c.get('type') == 'label' and
                       'VideoPlayer.Genre' in (c.findtext('label') or ''))
        self.assertLessEqual(number(details, 'top') + number(details, 'height'), number(ratings, 'top'))
        pills = next(c for c in root.iter('control') if c.get('description') == 'what is playing')
        self.assertGreater(number(pills, 'top'), number(plot, 'top') + number(plot, 'height'))
        # a film has no episode line: the details, the ratings and the plot move up together
        block = next(c for c in root.iter('control') if c.get('description') == 'under the episode line')
        self.assertIn('String.IsEmpty(Control.GetLabel(7902))', block.find('animation').get('condition'))
        for part in (details, ratings, plot):
            self.assertIn(part, list(block.iter('control')))

    def test_the_raw_formats_line_is_gone(self):
        """It read "4Kp - HEVC - DOLBYVISION - EAC3 5.1" on the left while the pills said it on the right."""
        for name in ('VideoFullScreen.xml', 'Includes_POVIL_Home.xml'):
            text = (XML / name).read_text('utf-8')
            self.assertNotIn('POVIL_OSD_File', text)
            self.assertNotIn('POVIL_OSD_Channels', text)


class FavouritesChipsTests(unittest.TestCase):
    def test_povs_own_saved_lists_have_chips_and_come_first(self):
        text = (XML / 'Home.xml').read_text('utf-8') + (XML / 'Includes_POVIL_Home.xml').read_text('utf-8')
        movies = text.index('סרטים ב-POV')
        shows = text.index('סדרות ב-POV')
        trakt = text.index('סרטים ב-Trakt')
        # the chips are written last to first: the row is laid out from the right, where reading starts
        self.assertGreater(movies, shows)
        self.assertGreater(shows, trakt, 'the lists that need no account come first')
        for action in ('mode=build_movie_list&amp;action=favorites_movies', 'mode=build_tvshow_list&amp;action=favorites_tvshows'):
            self.assertTrue(re.search(r'ActivateWindow\(Videos,[^)]*' + re.escape(action), text), action)


class DarkNotBlackTests(unittest.TestCase):
    def test_a_full_page_gets_a_faint_veil_over_its_background(self):
        text = (XML / 'Includes.xml').read_text('utf-8')
        start = text.index('<include name="FullBackground">')
        block = text[start:text.index('</include>\n\t<include name="MiniBackground">', start)]
        veil = block.rindex('POVIL: a page is dark, not black')
        self.assertGreater(veil, block.rindex('<include>DiffuseBG</include>'), 'over the art and its shade')
        alpha = int(re.search(r'colordiffuse="([0-9A-F]{2})F5F2EC">povil/white.png', block[veil:]).group(1), 16)
        self.assertTrue(0x10 <= alpha <= 0x24, 'a lift, not a grey screen')
        self.assertIn('<visible>!$EXP[BGvideoPlaying]</visible>', block[veil:], 'never over a video playing behind a page')

    def test_the_setting_rows_stand_out_and_the_secondary_text_is_readable(self):
        rows = (XML / 'SettingsCategory.xml').read_text('utf-8')
        self.assertNotIn('colordiffuse="0DFFFFFF">povil/rounded_fill.png', rows, 'five percent over black was one surface')
        colors = {c.get('name'): c.text for c in ET.parse(SKIN / 'colors/defaults.xml').getroot()}
        self.assertGreaterEqual(int(colors['povil_dim'][:2], 16), 0xD0)
        self.assertGreaterEqual(int(colors['povil_faint'][:2], 16), 0xA0)
        self.assertLess(int(colors['povil_faint'][:2], 16), int(colors['povil_dim'][:2], 16))
        self.assertGreaterEqual(int(colors['White'][2:4], 16), 0xE0)


if __name__ == '__main__':
    unittest.main()
