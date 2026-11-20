"""Onyx 1.0.25 / Wizard 0.5.26: the viewer's own rows ("שורות משלי").

A viewer, via the owner, Nov 2026: "let me add a category, say the films on my hard drive; leave the menus open to
configure for those who tinker -- and keep it through every update". QA Kodi, on the screen: the settings tile opens
the Wizard's list (tab, row, source, name, delete); a POV row shows its 21 films right to left, a folder row its 7
files; a deleted row disappears. The rows are skin strings (addon_data/skin.povil.onyx/settings.xml), which neither
a skin update nor the build's settings pack touches.
"""
import importlib.util
import re
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'skin.povil.onyx'
TOOLS = ROOT / 'tools/skin_onyx'
WIZARD = ROOT / 'plugin.program.kodipovilwizard'


def includes():
    return (SKIN / 'xml/Includes_POVIL_Home.xml').read_text(encoding='utf-8')


def variable(name):
    return includes().split('<variable name="%s">' % name)[1].split('</variable>')[0]


def gen_home():
    sys.path.insert(0, str(TOOLS))
    try:
        import gen_home as H
    finally:
        sys.path.remove(str(TOOLS))
    return H


class SkinRowsTests(unittest.TestCase):
    def test_each_chosen_tab_ends_with_three_rows_of_the_viewer_s_own(self):
        H = gen_home()
        for ti, tab in enumerate(H.TABS):
            custom = [r for r in tab['rows'] if r[1].startswith('custom:')]
            if tab['id'] in ('movies', 'tv', 'kids', 'favourites'):
                with self.subTest(tab['id']):
                    self.assertEqual([r[1] for r in custom], ['custom:%s_%d' % (tab['id'], n) for n in (1, 2, 3)])
                    self.assertEqual(tab['rows'][-3:], custom, 'at the end, after the build\'s own rows')
                    for n, row in enumerate(custom, 1):
                        self.assertEqual(row[0], '$VAR[POVIL_RowName_%s_%d]' % (tab['id'], n))
                        name = variable('POVIL_RowName_%s_%d' % (tab['id'], n))
                        self.assertIn('$INFO[Skin.String(POVILRow_%s_%d_name)]' % (tab['id'], n), name)
                        self.assertIn('<value>השורה שלי</value>', name, 'a row with no name of its own')
            else:
                self.assertEqual(custom, [], tab['id'])

    def test_a_row_reads_its_address_only_when_opened_and_set(self):
        H = gen_home()
        ti = [t['id'] for t in H.TABS].index('movies')
        rows = H.TABS[ti]['rows']
        rid = H.row_id(ti, len(rows) - 3)
        block = variable('POVIL_Path_%d' % rid)
        values = re.findall(r'<value condition="([^"]*)">([^<]*)</value>', block)
        self.assertEqual(len(values), 3)
        self.assertNotIn('<value>', block, 'nothing set: no address, so no row')
        for cond, _value in values:
            self.assertIn('!String.IsEmpty(Skin.String(POVILRow_movies_1_path))', cond)
            self.assertRegex(cond, r'Window\(home\)\.Property\(povil\.(tab|deep)\.movies\)')
        self.assertEqual(values[2][1], '$INFO[Skin.String(POVILRow_movies_1_path)]', 'a folder is read as it is')
        self.assertTrue(values[0][1].endswith('&amp;povil_rtl=1') and values[1][1].endswith('?povil_rtl=1'))

    def test_only_the_add_ons_that_reverse_lists_get_the_right_to_left_mark(self):
        block = variable('POVIL_Path_5014')
        for cond, _v in re.findall(r'<value condition="([^"]*)">([^<]*)povil_rtl=1</value>', block):
            starts = re.findall(r'String\.StartsWith\(Skin\.String\(POVILRow_movies_1_path\),([^)]*)\)', cond)
            self.assertEqual(sorted(starts), ['plugin://plugin.video.idanplus/', 'plugin://plugin.video.pov/', 'plugin://plugin.video.umbrella/'])
        patched = (WIZARD / 'resources/libs/patches/patches_config.py').read_text(encoding='utf-8')
        for addon in gen_home().RTL_ADDONS:
            self.assertIn(addon, patched)

    def test_the_settings_tile_asks_the_wizard_only_when_it_says_it_can(self):
        # a viewer's CoreELEC box, Nov 2026: the skin updated first, the Wizard there did not know the mode -- nothing
        home = (SKIN / 'xml/Home.xml').read_text(encoding='utf-8')
        tile = home.split('<label>שורות משלי</label>')[1].split('</item>')[0]
        able = 'String.Contains(Window(home).Property(povil.wizard.modes),custom_rows)'
        self.assertIn('<onclick condition="%s">RunPlugin(plugin://plugin.program.kodipovilwizard/?mode=custom_rows)</onclick>' % able, tile)
        self.assertIn('<onclick condition="!%s">ActivateWindow(1162)</onclick>' % able, tile)
        startup = (WIZARD / 'startup.py').read_text(encoding='utf-8')
        self.assertIn("xbmcgui.Window(10000).setProperty('povil.wizard.modes', 'custom_rows')", startup)
        router = (WIZARD / 'resources/libs/common/router.py').read_text(encoding='utf-8')
        self.assertRegex(router, r"mode == 'custom_rows':\s*\n(\s*#[^\n]*\n)?\s*from resources\.libs import custom_rows\s*\n\s*custom_rows\.choose\(\)")

    def test_the_build_s_settings_pack_does_not_carry_the_skin_s_settings(self):
        pack = ROOT / 'userdata/addon_data'
        if pack.is_dir():
            self.assertFalse((pack / 'skin.povil.onyx').exists(), 'an update would wipe the viewer\'s rows')


class FakeDialog:
    def __init__(self, selects, inputs=(), browse=''):
        self.selects, self.inputs, self.browsed = list(selects), list(inputs), browse

    def select(self, heading, items):
        return self.selects.pop(0) if self.selects else -1

    def input(self, heading, default=''):
        return self.inputs.pop(0) if self.inputs else default

    def browse(self, *args):
        return self.browsed

    def ok(self, *args):
        return True


class WizardDialogTests(unittest.TestCase):
    def run_choose(self, dialog, strings=None):
        strings = dict(strings or {})
        done = []

        def builtin(cmd):
            done.append(cmd)
            m = re.match(r'Skin\.SetString\(([^,]+),(.*)\)$', cmd)
            if m:
                strings[m.group(1)] = m.group(2).strip('"')
            m = re.match(r'Skin\.Reset\(([^)]+)\)$', cmd)
            if m:
                strings.pop(m.group(1), None)

        library = self.library if hasattr(self, 'library') else {}

        def rpc(request):
            import json
            method = json.loads(request)['method']
            return json.dumps({'result': {'limits': {'total': library.get(method, 0)}}})
        xbmc = types.SimpleNamespace(executebuiltin=builtin, sleep=lambda ms: None, executeJSONRPC=rpc,
                                     getInfoLabel=lambda l: strings.get(l[len('Skin.String('):-1], ''))
        xbmcgui = types.SimpleNamespace(Dialog=lambda: dialog)
        # by its file: in the full suite another add-on's "resources" package may already be imported
        spec = importlib.util.spec_from_file_location('povil_custom_rows_under_test', WIZARD / 'resources/libs/custom_rows.py')
        custom_rows = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(custom_rows)
        with mock.patch.dict(sys.modules, {'xbmc': xbmc, 'xbmcgui': xbmcgui}):
            custom_rows.choose()
        return strings, done

    def test_a_hard_drive_folder_becomes_a_named_row(self):
        # tab 0 (movies), row 1, source, folder entry (after the 3 library nodes), then the list is left
        strings, done = self.run_choose(FakeDialog([0, 0, 0, 3], inputs=['סרטים מהדיסק'], browse='D:\\Films\\'))
        self.assertEqual(strings['POVILRow_movies_1_path'], 'D:\\Films\\')
        self.assertIn('Skin.SetString(POVILRow_movies_1_path,D:\\Films\\)', done, 'bare: Kodi drops a trailing \\ inside quotes')
        self.assertEqual(strings['POVILRow_movies_1_name'], 'סרטים מהדיסק')

    def test_a_folder_whose_films_are_in_the_library_shows_the_films(self):
        # a viewer, Nov 2026: his films' folder added to Kodi as films and scanned; the row showed file names
        from urllib.parse import unquote
        import json
        self.library = {'VideoLibrary.GetMovies': 12}
        strings, done = self.run_choose(FakeDialog([0, 0, 0, 3], inputs=['הסרטים שלי'], browse='smb://nas/Films, 4K/'))
        path = strings['POVILRow_movies_1_path']
        self.assertTrue(path.startswith('videodb://movies/titles/?xsp='), path)
        self.assertNotIn(',', path)
        self.assertNotIn('"', path)
        xsp = json.loads(unquote(path.split('?xsp=')[1]))
        self.assertEqual(xsp['rules'], {'and': [{'field': 'path', 'operator': 'startswith', 'value': ['smb://nas/Films, 4K/']}]})
        self.assertEqual((xsp['type'], xsp['order']['method'], xsp['order']['direction']), ('movies', 'dateadded', 'descending'))
        # series in the library: the library's series; nothing there: the folder as it is
        self.library = {'VideoLibrary.GetTVShows': 3}
        strings, _ = self.run_choose(FakeDialog([1, 0, 0, 3], browse='/storage/Series/'))
        self.assertTrue(strings['POVILRow_tv_1_path'].startswith('videodb://tvshows/titles/?xsp='))
        self.library = {}
        strings, _ = self.run_choose(FakeDialog([1, 0, 0, 3], browse='/storage/Clips/'))
        self.assertEqual(strings['POVILRow_tv_1_path'], '/storage/Clips/')

    def test_a_comma_in_the_name_cannot_break_the_command(self):
        strings, _ = self.run_choose(FakeDialog([1, 2, 0, 0], inputs=['אקשן, מתח (HD "חדש"']))
        self.assertEqual(strings['POVILRow_tv_3_path'], 'videodb://movies/titles/')
        self.assertEqual(strings['POVILRow_tv_3_name'], 'אקשן מתח HD חדש')

    def test_deleting_a_row_resets_both_strings(self):
        strings, done = self.run_choose(FakeDialog([0, 1, 2]), {'POVILRow_movies_2_path': 'D:\\x\\', 'POVILRow_movies_2_name': 'x'})
        self.assertNotIn('POVILRow_movies_2_path', strings)
        self.assertNotIn('POVILRow_movies_2_name', strings)
        self.assertIn('Skin.Reset(POVILRow_movies_2_path)', done)

    def test_an_empty_row_offers_only_a_source_and_cancel_changes_nothing(self):
        strings, done = self.run_choose(FakeDialog([0, 0, -1]))
        self.assertEqual(strings, {})
        self.assertEqual(done, [])


if __name__ == '__main__':
    unittest.main()


class StandaloneTests(unittest.TestCase):
    """Onyx alone, without the Wizard (a viewer's CoreELEC box, Nov 2026): the skin's own dialogs."""

    def test_the_rows_dialog_offers_the_library_the_viewer_s_sources_and_any_folder(self):
        rows = (SKIN / 'xml/Custom_POVILRows.xml').read_text(encoding='utf-8')
        self.assertIn('<window type="dialog" id="1162">', rows)
        self.assertEqual(rows.count('SetProperty(povil.rows.slot,'), 12, 'four tabs, three rows each')
        key = 'POVILRow_$INFO[Window(home).Property(povil.rows.slot)]'
        for path in ('videodb://movies/titles/', 'videodb://tvshows/titles/', 'videodb://recentlyaddedmovies/'):
            self.assertIn('Skin.SetString(%s_path,%s)' % (key, path), rows)
        self.assertIn('<content>sources://video/</content>', rows)
        self.assertIn('Skin.SetString(%s_path,$ESCINFO[ListItem.FolderPath])' % key, rows)
        self.assertIn('Skin.SetString(%s_name,$ESCINFO[ListItem.Label])' % key, rows, 'a comma in a source name cannot split it')
        self.assertIn('Skin.SetPath(%s_path)' % key, rows)
        self.assertIn('Skin.Reset(%s_path)' % key, rows)
        self.assertIn('Skin.SetString(%s_name)' % key, rows, 'the name, in Kodi\'s keyboard')
        self.assertIn('allowhiddenfocus="true"', rows, 'the source list takes the focus as it appears')

    def test_the_choice_dialog_sets_what_the_wizard_would(self):
        choice = (SKIN / 'xml/Custom_POVILChoice.xml').read_text(encoding='utf-8')
        self.assertIn('<window type="dialog" id="1161">', choice)
        for value in ('netflix', 'advanced', 'simple', 'pretty'):
            self.assertIn('Skin.SetString(POVILPlayer,%s)' % value, choice)
        self.assertIn('Skin.Reset(POVILPlayer)', choice)
        for tab in ('tv', 'continue', 'israeli', 'live', 'kids', 'favourites', 'search'):
            self.assertIn('Skin.ToggleSetting(POVILHideTab_%s)' % tab, choice)
        self.assertNotIn('POVILHideTab_movies', choice)
        self.assertNotIn('POVILHideTab_settings', choice)

    def test_tiles_without_the_wizard(self):
        home = (SKIN / 'xml/Home.xml').read_text(encoding='utf-8')
        wiz = 'System.HasAddon(plugin.program.kodipovilwizard)'

        def tile(label):
            return home.split('<label>%s</label>' % label)[1].split('</item>')[0]
        # the log: the Wizard's uploader, else Kodi's own (installed when first asked for)
        log = tile('שליחת לוג')
        self.assertIn('<onclick condition="%s">RunPlugin(plugin://plugin.program.kodipovilwizard/?mode=uploadlog)</onclick>' % wiz, log)
        self.assertIn('<onclick condition="!%s + System.HasAddon(script.kodi.loguploader)">RunScript(script.kodi.loguploader)</onclick>' % wiz, log)
        self.assertIn('<onclick condition="!%s + !System.HasAddon(script.kodi.loguploader)">InstallAddon(script.kodi.loguploader)</onclick>' % wiz, log)
        self.assertNotIn('<visible>', log, 'always there')
        # the player and the screens: the skin's own dialog without the Wizard
        for label, mode in (('בחירת מסכים', 'tabs'), ('$VAR[POVIL_PlayerTile]', 'player')):
            with self.subTest(label):
                part = tile(label)
                self.assertIn('<onclick condition="!%s">SetProperty(povil.choice,%s,home)</onclick>' % (wiz, mode), part)
                self.assertIn('<onclick condition="!%s">ActivateWindow(1161)</onclick>' % wiz, part)
        # what only the Wizard does shows only with it
        for label in ('הוויזארד', 'החלפת סקין', 'סנכרון בין מכשירים', 'פרופילים', '$VAR[POVIL_TrailersTile]', 'תזמון טריילרים'):
            with self.subTest(label):
                self.assertRegex(tile(label), r'<visible>[^<]*%s' % re.escape(wiz))
