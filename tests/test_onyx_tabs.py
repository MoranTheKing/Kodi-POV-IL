"""Onyx 1.0.18 / Wizard 0.5.12: a "continue watching" screen, and the viewer chooses the screens of the top bar.

The owner, Nov 2026: "where is continue watching for whatever I am in the middle of? ... I want it as continue
watching for films and for series". A viewer: "I want to remove live TV and Israeli and put a screen of my own
choice there, say continue watching -- I see no way to change the screens at the top".
"""
import importlib.util
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
XML = ROOT / 'skin.povil.onyx/xml'
spec = importlib.util.spec_from_file_location('onyx_tabs_test', WIZARD / 'resources/libs/onyx_tabs.py')
tabs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tabs)


class BarTests(unittest.TestCase):
    def setUp(self):
        self.home = ET.parse(XML / 'Home.xml').getroot()
        self.bar = next(c for c in self.home.iter('control') if c.get('id') == '9000')

    def cells(self):
        return [c for c in self.bar if c.tag == 'control']

    def test_the_bar_is_a_list_of_buttons_that_can_leave_it(self):
        self.assertEqual(self.bar.get('type'), 'grouplist', 'a tab that is off the bar leaves no gap and the remote steps over it')
        self.assertEqual((self.bar.findtext('orientation'), self.bar.findtext('align')), ('horizontal', 'right'))
        # Kodi steps between a list's OWN children only (a button in a cell of its own did not move in the QA
        # Kodi): every child is a tab's button, and the line under the chosen tab is the button's texture
        # (a toggle button: its second pair of textures is the line, a texture named by a variable drew nothing)
        self.assertEqual({c.get('type') for c in self.cells()}, {'togglebutton'})
        names = [c.get('description').replace('tab ', '') for c in self.cells()]
        # the first on the right: the list is written from the left
        self.assertEqual(names[::-1], ['movies', 'tv', 'continue', 'israeli', 'live', 'kids', 'favourites', 'search', 'settings'])
        total = 0
        for button in self.cells():
            name = button.get('description').replace('tab ', '')
            self.assertIsNone(button.find('onleft'), "left and right are the list's")
            self.assertIsNone(button.find('onright'))
            if name in ('movies', 'settings'):
                self.assertIsNone(button.find('visible'), name + ' always stays: the home opens on films, settings is the way back')
            else:
                self.assertEqual(button.findtext('visible'), '!Skin.HasSetting(POVILHideTab_%s)' % name)
            # the line under the chosen tab is drawn at the button's own width: one file per width
            file_name = 'tab_line_%s.png' % button.findtext('width')
            for texture in ('alttexturefocus', 'alttexturenofocus'):
                self.assertEqual(button.findtext(texture), 'povil/' + file_name, name)
                self.assertFalse(button.findtext(texture.replace('alt', '')), 'nothing behind a tab that is not the chosen one')
            self.assertEqual(button.findtext('usealttexture'), 'String.IsEqual(Window(home).Property(povil.tab),%s)' % name)
            self.assertTrue((ROOT / 'skin.povil.onyx/media/povil' / file_name).is_file(), file_name)
            total += int(button.findtext('width'))
        self.assertEqual(int(self.bar.findtext('width')), total)
        power = next(c for c in self.home.iter('control') if c.get('id') == '9099')
        self.assertGreaterEqual(int(self.bar.findtext('left')), int(power.findtext('left')) + int(power.findtext('width')),
                                'nine tabs end right of the power button')
        self.assertEqual(self.home.findtext('defaultcontrol'), next(c.get('id') for c in self.cells() if c.get('description') == 'tab movies'),
                         'the home opens on the films tab: a list asked to take the focus gives it to its first button, at the left')

    def test_continue_watching_has_everything_the_viewer_is_in_the_middle_of(self):
        text = (XML / 'Home.xml').read_text('utf-8') + (XML / 'Includes_POVIL_Home.xml').read_text('utf-8')
        button = next(c for c in self.bar.iter('control') if c.get('description') == 'tab continue')
        self.assertEqual(button.findtext('label'), 'המשך צפייה')
        for route in ('mode=build_next_episode', 'action=in_progress_movies', 'mode=build_in_progress_episode'):
            self.assertIn(route, text, route)
        # the tabs that were there keep their rows of it, and their control ids (the service page's too)
        self.assertIn('id="5013"', text)
        self.assertIn('id="5023"', text)
        self.assertIn('id="5091"', text)

    def test_the_wizard_asks_which_screens_and_sets_exactly_those(self):
        self.assertEqual([tab for tab, _name in tabs.TABS], ['tv', 'continue', 'israeli', 'live', 'kids', 'favourites', 'search'])
        hidden = {'Skin.HasSetting(POVILHideTab_live)', 'Skin.HasSetting(POVILHideTab_israeli)'}
        self.assertEqual(tabs.shown(lambda cond: cond in hidden), [0, 1, 4, 5, 6])
        ran = []
        self.assertEqual(tabs.apply([0, 1, 4], ran.append), ['israeli', 'live', 'favourites', 'search'])
        self.assertEqual(ran, ['Skin.Reset(POVILHideTab_tv)', 'Skin.Reset(POVILHideTab_continue)', 'Skin.SetBool(POVILHideTab_israeli)',
                               'Skin.SetBool(POVILHideTab_live)', 'Skin.Reset(POVILHideTab_kids)', 'Skin.SetBool(POVILHideTab_favourites)',
                               'Skin.SetBool(POVILHideTab_search)'])
        # every id the Wizard names is a cell of the bar that can leave it
        cells = {c.get('description').replace('tab ', ''): c for c in self.cells()}
        for tab, name in tabs.TABS:
            self.assertIsNotNone(cells[tab].find('visible'), tab)
            self.assertEqual(cells[tab].findtext('label'), name)
        router = (WIZARD / 'resources/libs/common/router.py').read_text('utf-8')
        self.assertIn("elif mode == 'onyx_tabs':", router)
        home = (XML / 'Home.xml').read_text('utf-8') + (XML / 'Includes_POVIL_Home.xml').read_text('utf-8')
        self.assertIn('?mode=onyx_tabs)</onclick>', home, 'the tile "בחירת מסכים" in the settings screen')
        self.assertIn('בחירת מסכים', home)


if __name__ == '__main__':
    unittest.main()
