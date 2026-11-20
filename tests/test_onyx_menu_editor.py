"""Onyx 1.0.28 / Wizard 0.5.29: the menu editor ("עריכת התפריט").

A viewer, via the owner, Nov 2026, with a mod of Onyx 1.0.26 his own Claude made (the original Onyx's Homepage
category back: the bar's order, names, hiding, buttons of one's own, shortcuts under each button): "I'd be glad if
you put it in yours -- I want to work only with your skin, updates included". QA Kodi (21 and 22), on the screen.
"""
import importlib.util
import json
import pathlib
import re
import sys
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKIN = ROOT / 'skin.povil.onyx'
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
sys.path.insert(0, str(ROOT / 'tools' / 'skin_onyx'))


def gen_home():
    import gen_home as H
    return H


def load(name):
    spec = importlib.util.spec_from_file_location('povil_%s_under_test' % name, WIZARD / ('resources/libs/%s.py' % name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def variable(name):
    text = (SKIN / 'xml/Includes_POVIL_Home.xml').read_text(encoding='utf-8')
    return text.split('<variable name="%s">' % name)[1].split('</variable>')[0]


class BarTests(unittest.TestCase):
    def test_every_place_holds_a_button_of_every_tab_shown_only_while_it_holds_it(self):
        H = gen_home()
        home = (SKIN / 'xml/Home.xml').read_text(encoding='utf-8')
        bar = home.split('<control type="grouplist" id="9000" description="tabs">')[1].split('</control>')[0]
        places = re.findall(r'<include content="POVIL_Tab_(\w+)"><param name="id" value="(\d+)" />', bar)
        self.assertEqual(len(places), H.BAR_PLACES * len(H.BAR_IDS))
        # XML order is left to right: the last place first -- place 0 (the films, unordered) the rightmost
        self.assertEqual(places[-len(H.BAR_IDS):][0], ('movies', str(H.bar_button(0, 'movies'))))
        self.assertEqual(H.bar_shows(0, 'movies'), '[!Skin.HasSetting(POVILBarOrdered) | String.IsEqual(Skin.String(POVILBar_0),movies)]')
        self.assertEqual(H.bar_shows(0, 'tv'), '[Skin.HasSetting(POVILBarOrdered) + String.IsEqual(Skin.String(POVILBar_0),tv)]')
        ids = [int(i) for _t, i in places]
        self.assertEqual(len(ids), len(set(ids)))
        # a button of the viewer's own: shown only with something to do, and never if he took it off
        own = [line for line in bar.split('\n') if 'POVIL_Tab_own1' in line][0]
        self.assertIn('!Skin.HasSetting(POVILHideTab_own1)', own)
        self.assertIn('!String.IsEmpty(Skin.String(POVILTabOwn_1_path))', own)

    def test_the_focus_finds_a_tab_wherever_it_stands(self):
        H = gen_home()
        button = variable('POVIL_TabButton_movies')
        for p in range(H.BAR_PLACES):
            self.assertIn('<value condition="%s">%d</value>' % (H.bar_shows(p, 'movies'), H.bar_button(p, 'movies')), button)
        # a chip goes up to its tab's button ($VAR in an action: QA Kodi 21, a probe on the power button)
        home = (SKIN / 'xml/Home.xml').read_text(encoding='utf-8')
        chip = home.split('<control type="button" id="9112">')[1].split('</control>')[0]
        self.assertIn('<onup>SetFocus($VAR[POVIL_TabButton_movies])</onup>', chip)
        # Kodi's start with the films elsewhere: the first place's button
        self.assertIn('SetFocus($VAR[POVIL_BarFirst])</onload>', home)
        self.assertIn('<onright>SetFocus($VAR[POVIL_BarLast])</onright>', home)

    def test_a_tab_s_name_is_the_viewer_s_and_its_button_comes_from_one_include(self):
        label = variable('POVIL_TabLabel_tv')
        self.assertIn('<value condition="!String.IsEmpty(Skin.String(POVILTabName_tv))">$INFO[Skin.String(POVILTabName_tv)]</value>', label)
        self.assertTrue(label.rstrip().endswith('<value>סדרות</value>'))
        includes = (SKIN / 'xml/Includes_POVIL_Home.xml').read_text(encoding='utf-8')
        tv = includes.split('<include name="POVIL_Tab_tv">')[1].split('</include>')[0]
        self.assertIn('<control type="togglebutton" id="$PARAM[id]" description="tab tv">', tv)
        self.assertIn('<visible>$PARAM[visible]</visible>', tv)
        self.assertIn('<label>$VAR[POVIL_TabLabel_tv]</label>', tv)
        self.assertIn('<ondown>SetFocus($VAR[POVIL_FirstChip_tv])</ondown>', tv)
        own = includes.split('<include name="POVIL_Tab_own1">')[1].split('</include>')[0]
        self.assertIn('<onclick condition="!String.IsEmpty(Skin.String(POVILTabOwn_1_cmd))">$INFO[Skin.String(POVILTabOwn_1_cmd)]</onclick>', own)

    def test_the_first_chip_on_the_screen_is_the_first_shown(self):
        H = gen_home()
        ti = [t['id'] for t in H.TABS].index('movies')
        first = variable('POVIL_FirstChip_movies')
        values = re.findall(r'<value(?: condition="([^"]*)")?>(\d+)</value>', first)
        # the viewer's at the start first, then Netflix (unless he hid it) ...
        self.assertEqual(int(values[0][1]), H.custom_chip_id(ti, 1, 'start'))
        netflix = [v for v in values if int(v[1]) == H.chip_ids(ti, H.TABS[ti])[0]][0]
        self.assertIn('!Skin.HasSetting(POVILHideChip_movies_0)', netflix[0])

    def test_the_skin_settings_homepage_opens_the_editor(self):
        settings = (SKIN / 'xml/SkinSettings.xml').read_text(encoding='utf-8')
        item = settings.split('<item id="3104" description="Homepage">')[1].split('</item>')[0]
        self.assertNotIn('<visible>false</visible>', item)
        menus = settings.split('<control type="button" id="3400"')[1].split('</control>')[0]
        self.assertIn('RunPlugin(plugin://plugin.program.kodipovilwizard/?mode=menu_editor)</onclick>', menus)
        self.assertIn('>ActivateWindow(1162)</onclick>', menus)
        shelves = settings.split('<control type="button" id="3401"')[1].split('</control>')[0]
        self.assertIn('?mode=menu_editor&amp;part=rows)</onclick>', shelves)
        for cid in ('3413', '3410', '3402', '3405'):
            self.assertIn('<visible>false</visible>', settings.split('id="%s"' % cid)[1].split('</control>')[0])
        home = (SKIN / 'xml/Home.xml').read_text(encoding='utf-8')
        tile = home.split('<label>עריכת התפריט</label>')[1].split('</item>')[0]
        self.assertIn('RunPlugin(plugin://plugin.program.kodipovilwizard/?mode=menu_editor)', tile)
        router = (WIZARD / 'resources/libs/common/router.py').read_text(encoding='utf-8')
        self.assertIn("menu_editor.choose(self.params.get('part'))", router)
        data = json.loads((SKIN / 'extras/povil_menu.json').read_text(encoding='utf-8'))
        self.assertEqual(data['bar'][0], 'movies')
        self.assertEqual(data['places'], gen_home().BAR_PLACES)
        self.assertEqual(data['chips']['movies']['build'][0], 'נטפליקס')

    def test_any_live_tv_client_shows_the_iptv_chip(self):
        # a viewer, Nov 2026: "I moved to Onyx and my IPTV is not found"
        H = gen_home()
        live = [t for t in H.TABS if t['id'] == 'live'][0]
        chip = [c for c in live['chips'] if c[0] == 'IPTV שלי'][0]
        self.assertIn('System.HasPVRAddon', chip[2])


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.me = load('menu_editor')
        self.strings, self.bools, self.done = {}, set(), []

    def read(self, label):
        m = re.match(r'Skin\.String\((.+)\)$', label)
        return self.strings.get(m.group(1), '') if m else ''

    def visible(self, cond):
        m = re.match(r'Skin\.HasSetting\((.+)\)$', cond)
        return bool(m and m.group(1) in self.bools)

    def builtin(self, cmd):
        self.done.append(cmd)
        m = re.match(r'Skin\.SetString\(([^,]+),(.*)\)$', cmd)
        if m:
            value = m.group(2)
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1].replace('\\"', '"')
            self.strings[m.group(1)] = value
        m = re.match(r'Skin\.Reset\(([^)]+)\)$', cmd)
        if m:
            self.strings.pop(m.group(1), None)
            self.bools.discard(m.group(1))
        m = re.match(r'Skin\.SetBool\(([^)]+)\)$', cmd)
        if m:
            self.bools.add(m.group(1))

    def bar(self):
        return self.me.Bar(self.me.FALLBACK, self.read, self.visible, self.builtin)

    def test_the_order_is_the_build_s_until_written_and_keeps_every_tab(self):
        bar = self.bar()
        self.assertEqual(bar.order(), self.me.FALLBACK['bar'])
        order = self.me.move(bar.order(), 1, -1)            # series to the right of the films
        self.assertEqual(order[:2], ['tv', 'movies'])
        bar.write(order)
        self.assertIn('POVILBarOrdered', self.bools)
        self.assertEqual(self.strings['POVILBar_0'], 'tv')
        self.assertEqual(bar.order(), order)
        # a place that names nothing known, or a tab twice: still every tab, once
        self.strings['POVILBar_3'] = 'nonsense'
        self.strings['POVILBar_4'] = 'tv'
        self.assertEqual(sorted(bar.order()), sorted(self.me.FALLBACK['bar']))
        self.assertEqual(self.me.move(order, 0, -1), order, 'at the edge: unchanged')

    def test_a_button_of_his_own_takes_a_hidden_tab_s_place_and_stands_before_the_settings(self):
        bar = self.bar()
        dialog = types.SimpleNamespace(ok=lambda *a: self.done.append('ok'), select=None, input=None)
        self.me.add_own_tab(dialog, bar, None)
        self.assertEqual(self.done, ['ok'], 'nine on the bar: hide one first')
        self.bools.add('POVILHideTab_live')
        self.done.clear()
        picks = iter([4, 0])      # live TV and radio -> the TV channels
        dialog = types.SimpleNamespace(ok=lambda *a: None, select=lambda *a, **k: next(picks), input=lambda *a, **k: 'טלוויזיה')
        self.me.add_own_tab(dialog, bar, None)
        self.assertEqual(self.strings['POVILTabOwn_1_cmd'], 'ActivateWindow(TVChannels)')
        self.assertEqual(self.strings['POVILTabOwn_1_name'], 'טלוויזיה'[:bar.longest('own1')])
        order = bar.order()
        self.assertEqual(order[-2:], ['own1', 'settings'])

    def test_a_favourite_becomes_its_own_command_kept_whole(self):
        favs = {'result': {'favourites': [
            {'title': 'IPTV', 'type': 'window', 'window': '10025', 'windowparameter': 'plugin://plugin.video.iptv/?a=1,b=2'},
            {'title': 'Clip', 'type': 'media', 'path': 'D:\\clip.mp4'},
            {'title': 'Weird', 'type': 'unknown', 'path': 'nothing'}]}}
        got = self.me.favourites(lambda request: json.dumps(favs))
        self.assertEqual(got, [('IPTV', 'ActivateWindow(10025,"plugin://plugin.video.iptv/?a=1,b=2",return)'),
                               ('Clip', 'PlayMedia("D:\\clip.mp4")')])
        # written quoted, its inner quotes escaped: Kodi keeps it whole (QA Kodi)
        sys.modules.setdefault('resources', types.SimpleNamespace())
        self.me.write_target('POVILChip_movies_1', {'cmd': got[0][1]}, self.builtin)
        self.assertEqual(self.done[0], 'Skin.SetString(POVILChip_movies_1_cmd,"ActivateWindow(10025,\\"plugin://plugin.video.iptv/?a=1,b=2\\",return)")')
        self.assertEqual(self.strings['POVILChip_movies_1_cmd'], got[0][1])

    def test_a_windows_folder_s_last_backslash_never_cuts_the_command(self):
        # the reviewer: before an escaped quote Kodi would read \\" as an escaped backslash -- QA Kodi 22: stored whole
        # without it, and the folder opened (5 films)
        quoted = self.me.skin_quote('ActivateWindow(Videos,"D:\\Films\\",return)')
        self.assertEqual(quoted, '"ActivateWindow(Videos,\\"D:\\Films\\",return)"')

    def test_the_build_s_chips_hidden_but_never_all_of_them(self):
        info = {'build': ['נטפליקס', 'דיסני+', 'אקשן'], 'mid': True}
        oks = []
        dialog = types.SimpleNamespace(multiselect=lambda *a, **k: [0, 1, 2], ok=lambda *a: oks.append(1))
        self.me.build_chips(dialog, 'movies', 'סרטים', info, self.visible, self.builtin, mine=[])
        self.assertEqual(oks, [1])
        self.assertFalse(self.bools)
        dialog = types.SimpleNamespace(multiselect=lambda *a, **k: [0], ok=lambda *a: oks.append(1))
        self.me.build_chips(dialog, 'movies', 'סרטים', info, self.visible, self.builtin, mine=[])
        self.assertEqual(self.bools, {'POVILHideChip_movies_0'})

    def test_reset_puts_the_bar_back(self):
        bar = self.bar()
        bar.write(self.me.move(bar.order(), 1, -1))
        self.strings.update({'POVILTabName_tv': 'שלי', 'POVILTabOwn_1_cmd': 'X', 'POVILTabOwn_1_name': 'Y'})
        self.bools.add('POVILHideTab_kids')
        bar.reset()
        self.assertFalse(self.bools)
        self.assertFalse([k for k in self.strings if k.startswith(('POVILBar_', 'POVILTabName_', 'POVILTabOwn_'))])


if __name__ == '__main__':
    unittest.main()


class ButtonIdTests(unittest.TestCase):
    def test_the_wizard_finds_a_tab_s_button_as_the_skin_numbers_it(self):
        # a builtin from Python has no $VAR (QA Kodi): the Wizard counts the id itself, as gen_home.py does
        H = gen_home()
        me = load('menu_editor')
        data = json.loads((SKIN / 'extras/povil_menu.json').read_text(encoding='utf-8'))
        strings = {'POVILBar_0': 'tv', 'POVILBar_1': 'movies', 'POVILBar_4': 'own1'}
        read = lambda label: strings.get(label[len('Skin.String('):-1], '')
        ordered = lambda cond: cond == 'Skin.HasSetting(POVILBarOrdered)'
        self.assertEqual(me.button_id('movies', read, ordered, data), H.bar_button(1, 'movies'))
        self.assertEqual(me.button_id('own1', read, ordered, data), H.bar_button(4, 'own1'))
        self.assertEqual(me.button_id('movies', read, lambda cond: False, data), H.bar_button(0, 'movies'))
        self.assertEqual(me.button_id('movies', read, lambda cond: cond == 'Control.IsVisible(9010)', data), 9010)
