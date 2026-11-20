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
                        self.assertEqual(row[0], '$INFO[Skin.String(POVILRow_%s_%d_name)]' % (tab['id'], n))
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

    def test_the_settings_tile_opens_the_wizard_s_list(self):
        home = (SKIN / 'xml/Home.xml').read_text(encoding='utf-8')
        self.assertIn('RunPlugin(plugin://plugin.program.kodipovilwizard/?mode=custom_rows)', home)
        self.assertIn('שורות משלי', home)
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

        xbmc = types.SimpleNamespace(executebuiltin=builtin, sleep=lambda ms: None,
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
