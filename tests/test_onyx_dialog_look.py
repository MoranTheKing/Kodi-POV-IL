"""Onyx 1.0.15: the skin's dialogs in the build's look (tools/skin_onyx/patch_onyx.py dialog_look,
gen_dialog_textures.py). Every dialog sat on a black square with a white hairline and marked the focused
row with a flat grey rectangle; both textures are replaced wherever they were used, in their own geometry.
"""
import importlib.util
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'skin.povil.onyx'
XML = SKIN / 'xml'


class DialogLookTests(unittest.TestCase):
    def texts(self):
        return {path.name: path.read_text('utf-8') for path in sorted(XML.glob('*.xml'))}

    def test_no_dialog_sits_on_the_black_square_any_more(self):
        texts = self.texts()
        self.assertEqual([name for name, text in texts.items() if 'img/DialogCE.png' in text], [])
        panels = re.findall(r'<texture[^>]*>povil/panel\.png', ''.join(texts.values()))
        self.assertGreaterEqual(len(panels), 30)
        # the original's own geometry: the same 9-slice border, so no dialog's layout moves
        self.assertTrue(all('border="128"' in use for use in panels), [u for u in panels if 'border="128"' not in u][:3])
        self.assertIn('povil/panel.png', texts['DialogContextMenu.xml'])
        self.assertIn('povil/panel.png', texts['DialogConfirm.xml'])

    def test_the_focused_row_gets_the_rounded_box_with_a_border_that_fits_it(self):
        texts = ''.join(self.texts().values())
        uses = re.findall(r'<(?:alt)?texture(?:focus|nofocus)?[^>]*>povil/focus_box\.png', texts)
        self.assertGreaterEqual(len(uses), 90)
        self.assertTrue(all('border="14"' in use for use in uses), [u for u in uses if 'border="14"' not in u][:3])
        left = re.findall(r'<[a-z]+[^>]*>img/MediaButton2\.png', texts)
        self.assertTrue(all(use.startswith('<bordertexture') for use in left), left)

    def test_the_textures_exist_in_the_originals_sizes(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Pillow is not installed')
        panel = Image.open(SKIN / 'media/povil/panel.png')
        self.assertEqual(panel.size, (320, 320))
        self.assertEqual(panel.getpixel((4, 160))[3] < 80, True, 'the margin holds only the shadow')
        self.assertGreater(panel.getpixel((160, 160))[3], 240, 'the body is all but opaque')
        box = Image.open(SKIN / 'media/povil/focus_box.png')
        self.assertGreaterEqual(min(box.size), 2 * 14 + 4, 'room for a 9-slice border of 14')

    def test_the_panel_is_all_but_opaque_unless_the_viewer_chose_otherwise(self):
        # QA, Nov 2026: at Onyx's default transparency the home's plot was read through a yes/no question
        variables = (XML / 'Includes_Variables.xml').read_text('utf-8')
        block = re.search(r'<variable name="MenuTransperancy">(.*?)</variable>', variables, re.S).group(1)
        values = re.findall(r'<value[^>]*>([^<]+)</value>', block)
        self.assertEqual(values[-1], 'povil_panel')
        self.assertEqual(len(re.findall(r'<value condition="Skin\.HasSetting\(Menu\w+\)">', block)), len(values) - 1)
        colours = (SKIN / 'colors/defaults.xml').read_text('utf-8')
        colour = re.search(r'<color name="povil_panel">([0-9A-Fa-f]{8})</color>', colours).group(1)
        self.assertGreaterEqual(int(colour[:2], 16), 0xF0)
        self.assertEqual(colour[2:].upper(), 'FFFFFF', 'the panel keeps its own colour')

    def test_the_pass_changes_nothing_the_second_time(self):
        spec = importlib.util.spec_from_file_location('patch_onyx_look_test', ROOT / 'tools/skin_onyx/patch_onyx.py')
        sys.path.insert(0, str(ROOT / 'tools/skin_onyx'))
        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(ROOT / 'tools/skin_onyx'))
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            (folder / 'A.xml').write_text(
                '<window><texture colordiffuse="$VAR[MenuTransperancy]" border="128">img/DialogCE.png</texture>\n'
                '<texturefocus border="9" colordiffuse="$VAR[FocusBoxColor]">img/MediaButton2.png</texturefocus>\n'
                '<texture>img/MediaButton2.png</texture><alttexturefocus  border="5">img/MediaButton2.png</alttexturefocus>\n'
                '<bordertexture border="5">img/MediaButton2.png</bordertexture></window>\n', encoding='utf-8')
            shutil.copy(folder / 'A.xml', folder / 'notes.txt')
            self.assertEqual(module.dialog_look(str(folder)), 1)
            text = (folder / 'A.xml').read_text('utf-8')
            self.assertIn('<texture colordiffuse="$VAR[MenuTransperancy]" border="128">povil/panel.png', text)
            self.assertIn('<texturefocus border="14" colordiffuse="$VAR[FocusBoxColor]">povil/focus_box.png', text)
            self.assertIn('<texture border="14">povil/focus_box.png', text)
            self.assertIn('border="14">povil/focus_box.png</alttexturefocus>', text)
            self.assertIn('<bordertexture border="5">img/MediaButton2.png', text, 'a border texture is another thing')
            self.assertEqual(module.dialog_look(str(folder)), 0)
            self.assertIn('img/DialogCE.png', (folder / 'notes.txt').read_text('utf-8'), 'only the skin\'s XML')


if __name__ == '__main__':
    unittest.main()
