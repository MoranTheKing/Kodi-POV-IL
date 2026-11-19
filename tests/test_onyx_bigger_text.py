"""Onyx 1.0.23: the home a size up where it is read from the sofa, and the watched mark's colour as the viewer likes.

Viewers, via the owner, Nov 2026: "bigger, to see from afar -- the top bar, the chips, the film's details like the
rating; done with care" and "how do I make the V green, where I now see it gold". QA Kodi, on the screen: the bar's
names a size up and evenly apart, the chips and the hero's details and ratings larger; the colour list names its
four choices and a choice turns every mark that colour.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'skin.povil.onyx'
TOOLS = ROOT / 'tools/skin_onyx'


def fonts():
    text = (SKIN / 'xml/Font.xml').read_text(encoding='utf-8')
    default = text.split('<fontset id="Arial"')[0]
    return {name: int(size) for name, size in re.findall(r'<name>([^<]+)</name>\s*<filename>[^<]+</filename>\s*<size>(\d+)</size>', default)}


class BiggerTextTests(unittest.TestCase):
    def test_the_home_s_own_fonts_are_a_size_up_and_the_others_keep_theirs(self):
        sizes = fonts()
        self.assertGreater(sizes['povil_tab'], sizes['povil_menu'])
        self.assertGreater(sizes['povil_chip_home'], sizes['povil_chip'])
        self.assertGreater(sizes['povil_hero_meta'], sizes['povil_meta'])
        self.assertEqual((sizes['povil_menu'], sizes['povil_chip'], sizes['povil_meta']), (31, 23, 26), 'the player and dialogs keep theirs')
        both = (SKIN / 'xml/Font.xml').read_text(encoding='utf-8')
        for name in ('povil_tab', 'povil_chip_home', 'povil_hero_meta', 'povil_hero_meta_bold'):
            self.assertEqual(both.count('<name>%s</name>' % name), 2, 'in both fontsets: %s' % name)
        home = (SKIN / 'xml/Home.xml').read_text(encoding='utf-8') + (SKIN / 'xml/Includes_POVIL_Home.xml').read_text(encoding='utf-8')
        for name in ('povil_tab', 'povil_chip_home', 'povil_hero_meta', 'povil_hero_meta_bold'):
            self.assertIn('<font>%s</font>' % name, home)

    def test_every_tab_name_fits_its_button_and_the_bar_is_as_wide_as_before(self):
        sys.path.insert(0, str(TOOLS))
        try:
            import gen_home as H
        finally:
            sys.path.remove(str(TOOLS))
        self.assertEqual(H.BAR_W, 1420, 'it still ends right of the power button')
        try:
            from PIL import ImageFont
        except ImportError:
            self.skipTest('Pillow')
        font = ImageFont.truetype(str(SKIN / 'fonts/Heebo-Medium.ttf'), fonts()['povil_tab'])
        for tab in H.TABS:
            if tab['id'] in H.BAR:
                with self.subTest(tab['id']):
                    self.assertLessEqual(font.getlength(tab['label']) + 30, H.tab_width(tab['id']))
        for width in set(H.tab_width(t) for t in H.BAR):
            self.assertTrue((SKIN / ('media/povil/tab_line_%d.png' % width)).is_file(), width)


class WatchedColourTests(unittest.TestCase):
    def test_the_choice_names_its_colours_by_the_skin_s_own_strings(self):
        home = (SKIN / 'xml/Home.xml').read_text(encoding='utf-8')
        choice = re.search(r'Skin\.SelectBool\(([^)]*)\)', home).group(1).split(',')
        self.assertEqual(choice[0], '31900')
        self.assertEqual([c.split('|')[1] for c in choice[1:]], ['POVILWatchedGold', 'POVILWatchedGreen', 'POVILWatchedWhite', 'POVILWatchedBlue'])
        he = (SKIN / 'language/resource.language.he_il/strings.po').read_text(encoding='utf-8')
        for sid, word in (('31900', 'צבע סימן הנצפה'), ('31901', 'זהב'), ('31902', 'ירוק'), ('31903', 'לבן'), ('31904', 'תכלת')):
            self.assertIn('msgctxt "#%s"' % sid, he)
            self.assertIn('msgstr "%s"' % word, he)

    def test_every_mark_takes_the_chosen_colour_gold_by_default(self):
        includes = (SKIN / 'xml/Includes_POVIL_Home.xml').read_text(encoding='utf-8')
        self.assertNotIn('colordiffuse="povil_gold">povil/check.png', includes)
        self.assertIn('colordiffuse="$VAR[POVIL_WatchedColour]">povil/check.png', includes)
        block = includes.split('<variable name="POVIL_WatchedColour">')[1].split('</variable>')[0]
        self.assertIn('<value condition="Skin.HasSetting(POVILWatchedGreen)">FF34C759</value>', block)
        self.assertTrue(block.strip().endswith('<value>povil_gold</value>'), 'none chosen (or gold): gold, as until now')


if __name__ == '__main__':
    unittest.main()
