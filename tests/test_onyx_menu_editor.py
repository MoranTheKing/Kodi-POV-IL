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
        # without the Wizard (Onyx 1.0.29): the same editor, inside the skin -- not the skin's rows-only windows
        self.assertIn('>RunScript(special://skin/scripts/povil_menu_editor.py)</onclick>', menus)
        self.assertNotIn('ActivateWindow(1162)', menus)
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


class WithoutTheWizardTests(unittest.TestCase):
    """Onyx 1.0.29. A viewer, via the owner, Nov 2026, with Onyx alone (no Wizard): "on yours there is only the row
    editing ... on mine I can edit all the menus" -- the full editor lived in the Wizard; the skin's own windows (1162,
    1163) edit the rows and shortcuts only. QA Kodi: RunScript of the skin's copy opened the editor, the shortcuts
    under "סרטים" and the order of the rows, nothing in the log."""

    def test_the_skin_carries_the_wizard_s_own_editor_unchanged(self):
        libs = SKIN / 'scripts/povil_menu/resources/libs'
        for name in ('menu_editor.py', 'custom_rows.py', 'home_rows.py'):
            self.assertEqual((libs / name).read_bytes(), (WIZARD / 'resources/libs' / name).read_bytes(),
                             '%s: the skin\'s copy is the Wizard\'s (tools/skin_onyx/build.py copies it)' % name)
        for package in (libs, libs.parent):
            self.assertTrue((package / '__init__.py').exists())
        # the copies need nothing of the Wizard's but each other (Kodi's own modules)
        for name in ('menu_editor.py', 'custom_rows.py', 'home_rows.py'):
            source = (libs / name).read_text(encoding='utf-8')
            imported = set(re.findall(r'from resources\.libs import (\w+)', source))
            self.assertLessEqual(imported, {'menu_editor', 'custom_rows', 'home_rows'}, name)
            self.assertNotIn('xbmcaddon', source, '%s: a script run from the skin has no add-on of its own' % name)

    def test_its_launcher_runs_each_part(self):
        launcher = (SKIN / 'scripts/povil_menu_editor.py').read_text(encoding='utf-8')
        self.assertIn("translatePath('special://skin/scripts/povil_menu')", launcher)
        calls = []
        libs = types.SimpleNamespace(menu_editor=types.SimpleNamespace(choose=lambda part=None: calls.append(('menu', part))),
                                     custom_rows=types.SimpleNamespace(choose=lambda: calls.append(('custom', None))),
                                     home_rows=types.SimpleNamespace(choose=lambda: calls.append(('order', None))))
        modules = {'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: '/skin/scripts/povil_menu'),
                   'resources': types.SimpleNamespace(libs=libs), 'resources.libs': libs,
                   'resources.libs.menu_editor': libs.menu_editor, 'resources.libs.custom_rows': libs.custom_rows,
                   'resources.libs.home_rows': libs.home_rows}
        for argv in (['x'], ['x', 'rows'], ['x', 'custom_rows'], ['x', 'home_rows']):
            with mock.patch.dict(sys.modules, modules), mock.patch.object(sys, 'argv', argv), \
                    mock.patch.object(sys, 'path', list(sys.path)):
                exec(compile(launcher, 'povil_menu_editor.py', 'exec'), {'__name__': '__main__'})
        self.assertEqual(calls, [('menu', None), ('menu', 'rows'), ('custom', None), ('order', None)])

    def test_without_the_wizard_every_way_in_opens_the_skin_s_copy(self):
        home = (SKIN / 'xml/Home.xml').read_text(encoding='utf-8')
        for label, mode, arg in (('עריכת התפריט', 'menu_editor', ''), ('שורות וכפתורים משלי', 'custom_chips', ',custom_rows'),
                                 ('סדר השורות', 'home_rows', ',home_rows')):
            tile = home.split('<label>%s</label>' % label)[1].split('</item>')[0]
            self.assertIn('<onclick condition="!String.Contains(Window(home).Property(povil.wizard.modes),%s)">'
                          'RunScript(special://skin/scripts/povil_menu_editor.py%s)</onclick>' % (mode, arg), tile)
        settings = (SKIN / 'xml/SkinSettings.xml').read_text(encoding='utf-8')
        shelves = settings.split('<control type="button" id="3401"')[1].split('</control>')[0]
        self.assertIn('>RunScript(special://skin/scripts/povil_menu_editor.py,rows)</onclick>', shelves)
        self.assertNotIn('ActivateWindow(1163)', shelves)


class ChipRowTests(unittest.TestCase):
    """Onyx 1.0.29. The owner, Nov 2026, a photo of his TV: the films' first chip stood cut at the margin, in the middle
    of the picture ("even though the picture covers the whole TV") -- the viewer's shortcuts made the row longer than
    the screen, and Kodi shows a grouplist longer than itself from its left end. QA Kodi, with five long shortcuts of
    the viewer's: the first chip at the margin as before, the rest cut at the screen's left edge; Left to the far end
    shows the last one whole at the margin; another screen and back, the row at its first chip again."""

    def test_the_row_spans_the_screen_with_a_margin_of_nothing_at_either_end(self):
        H = gen_home()
        home = (SKIN / 'xml/Home.xml').read_text(encoding='utf-8')
        row = home.split('<control type="grouplist" id="9100" description="chips">')[1]
        row = row[:row.index('<control type="group" description="rows movies">')]
        self.assertIn('<left>0</left><top>538</top><width>1920</width>', row)
        edge = '<control type="label" description="edge"><width>%d</width>' % (H.MARGIN - H.CHIP_GAP)
        self.assertEqual(row.count(edge), 2)
        self.assertLess(row.index(edge), row.index('<control type="button"'), 'one before the first chip')
        self.assertLess(row.rindex('<control type="button"'), row.rindex(edge), 'one after the last')
        self.assertIn('<itemgap>%d</itemgap>' % H.CHIP_GAP, row)

    def test_each_screen_s_row_is_brought_to_its_first_chip_once_and_the_focus_put_back(self):
        H = gen_home()
        timers = (SKIN / 'xml/Timers.xml').read_text(encoding='utf-8')
        tabs = [t['id'] for t in H.TABS if t['chips'] and not t.get('hidden')]
        self.assertIn('movies', tabs)
        for tab in tabs:
            timer = timers.split('<name>povil_chips_%s</name>' % tab)[1].split('</timer>')[0]
            start = timer.split('<start reset="true">')[1].split('</start>')[0]
            for cond in ('Window.IsActive(home)', '!System.HasActiveModalDialog', '!String.IsEmpty(System.CurrentControlId)',
                         'String.IsEqual(Window(home).Property(povil.tab),%s)' % tab,
                         '!String.IsEqual(Window(home).Property(povil.chips.at),%s)' % tab,
                         'String.IsEmpty(Window(home).Property(povil.%s.enter))' % H.HUB):
                self.assertIn(cond, start, tab)
            steps = re.findall(r'<onstart>(.*?)</onstart>', timer)
            self.assertEqual(steps, ['SetProperty(povil.chips.at,%s,home)' % tab,
                                     'SetProperty(povil.chips.back,$INFO[System.CurrentControlId],home)',
                                     'SetProperty(povil.chips.focus,$INFO[Window(home).Property(povil.focus)],home)',
                                     'SetFocus($VAR[POVIL_FirstChip_%s])' % tab,
                                     'SetFocus($INFO[Window(home).Property(povil.chips.back)])',
                                     'SetProperty(povil.focus,$INFO[Window(home).Property(povil.chips.focus)],home)'], tab)
            self.assertIn('<variable name="POVIL_FirstChip_%s">' % tab,
                          (SKIN / 'xml/Includes_POVIL_Home.xml').read_text(encoding='utf-8'))
        # every time the home opens
        home = (SKIN / 'xml/Home.xml').read_text(encoding='utf-8')
        self.assertIn('<onload>ClearProperty(povil.chips.at,home)</onload>', home)


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
