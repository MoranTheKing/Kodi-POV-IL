"""Upgrade real build MDBList entry points without rewriting user lists."""
import ast
import importlib.util
import json
import sqlite3
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


visibility = load('qa_mdbl_personal_visibility',
                  'plugin.program.kodipovilwizard/resources/libs/patches/pov_visibility_mgr.py')
af3 = load('qa_mdbl_personal_af3',
           'service.subtitles.kodipovilai/resources/lib/af3_home_patcher.py')


class MDBListPersonalRoutesTests(unittest.TestCase):
    def test_large_tiles_submenu_and_continue_use_identical_directory_urls(self):
        generator = load('qa_fav_routes', 'plugin.program.orderfavourites-hebrew/favourites_generator.py')
        with patch.object(generator, '_check_condition', return_value=True):
            for skin in ('skin.povil.nox', 'skin.fentastic', 'skin.estuary'):
                rows = ET.fromstring(generator.generate_favourites_xml(skin, merge=False, write=False))
                for action in ('mdblist_my_movies', 'mdblist_my_tvshows'):
                    tile = next(i.text for i in rows if 'action=' + action + '&' in i.text)
                    for filename in ('Custom_nox_main_menu.xml', 'Custom_2115_next_watch.xml'):
                        menu = ET.parse(ROOT / 'skin.povil.nox/xml' / filename)
                        self.assertIn(tile, [i.text for i in menu.iter('onclick')])

    def test_nox_favourites_submenu_and_continue_dialog_include_combined_library_routes(self):
        for filename in ('Custom_nox_main_menu.xml', 'Custom_2115_next_watch.xml'):
            root = ET.parse(ROOT / 'skin.povil.nox/xml' / filename).getroot()
            for action, mode in (('mdblist_my_movies', 'build_movie_list'),
                                 ('mdblist_my_tvshows', 'build_tvshow_list')):
                rows = [item for item in root.iter('item')
                        if any('action=' + action + '&' in (onclick.text or '')
                               for onclick in item.findall('onclick'))]
                self.assertEqual(len(rows), 1, (filename, action))
                self.assertIn('MDBList', rows[0].findtext('label'))
                self.assertTrue(any('mode=' + mode + '&' in onclick.text
                                    for onclick in rows[0].findall('onclick')))
                if filename == 'Custom_nox_main_menu.xml':
                    self.assertEqual(rows[0].findtext('visible'),
                                     'String.IsEqual(Container(9000).ListItem.Property(id),favorites)')
                else:
                    self.assertEqual(rows[0].findtext('onclick'), 'Close')
            if filename == 'Custom_2115_next_watch.xml':
                group = root.find('controls/control')
                self.assertEqual(group.findtext('centertop'), '50%')
                self.assertEqual(group.findtext('height'), '980')
                self.assertEqual(group.find('include/param[@name="height"]').get('value'), '980')
        home = ET.parse(ROOT / 'skin.povil.nox/xml/Home_nox.xml').getroot()
        self.assertTrue(any(item.text == 'MainMenu' for item in home.iter('include')))
        self.assertTrue(any('ActivateWindow(2115)' in (param.get('value') or '')
                            for param in home.iter('param')))

    def test_shipped_personal_folders_repaired_in_memory_only(self):
        path = ROOT / 'userdata/addon_data/plugin.video.pov/navigator.db'
        before = path.read_bytes()
        with sqlite3.connect('file:' + path.as_posix() + '?mode=ro', uri=True) as db:
            for name, canonical in visibility._MDBLIST_ROWS.items():
                rows = ast.literal_eval(db.execute(
                    'SELECT list_contents FROM navigator WHERE list_name=?', (name,)).fetchone()[0])
                saved = [dict(row) for row in rows]
                with patch.object(visibility, '_snapshot', return_value={
                        'svc': {'mdblist': True, 'trakt': True, 'tmdb': True}}):
                    result = visibility.filter_navigator_list(rows, name)
                    self.assertEqual(result, visibility.filter_navigator_list(result, name))
                original = next(row for row in saved if row.get('action') == 'mdblist_watchlist')
                self.assertIn(dict(original, action=canonical['action']), result)
                self.assertEqual(rows, saved)
                self.assertEqual(len(result), len(saved))
        self.assertEqual(path.read_bytes(), before)

    def test_custom_watchlist_and_deleted_rows_not_replaced_or_restored(self):
        name, canonical = next(iter(visibility._MDBLIST_ROWS.items()))
        custom = dict(canonical, action='mdblist_watchlist', name='My Watchlist', iconImage='mine.png')
        original = dict(canonical, action='mdblist_watchlist', iconImage='my-custom-icon.png')
        with patch.object(visibility, '_snapshot', return_value={'svc': {'mdblist': True}}):
            self.assertEqual(visibility.filter_navigator_list([custom], name), [custom])
            self.assertEqual(visibility.filter_navigator_list([], name), [])
            self.assertEqual(visibility.filter_navigator_list([original], 'Custom Folder'), [original])
            self.assertEqual(visibility.filter_navigator_list([original], name),
                             [dict(original, action=canonical['action'])])
        with patch.object(visibility, '_snapshot', return_value={'svc': {}}):
            self.assertEqual(visibility.filter_navigator_list([original], name), [])
        with patch.object(visibility, '_snapshot', side_effect=RuntimeError('fixture')):
            self.assertEqual(visibility.filter_navigator_list([original], name), [original])

    def merge(self, current, baseline, canonical):
        filename = 'fixture.json'
        data = {af3.AF3_NODES + filename: json.dumps(current)}
        if baseline is not None:
            data[af3.POV_BASELINE_DIR + filename] = json.dumps(baseline)
        with patch.object(af3, '_exists', side_effect=lambda p: p in data), \
                patch.object(af3, '_read', side_effect=data.__getitem__), \
                patch.object(af3, '_write', side_effect=lambda p, v: data.__setitem__(p, v)), \
                patch.object(af3, '_mkdir'):
            changed = af3._merge_widget_nodes(filename, canonical)
            self.assertFalse(af3._merge_widget_nodes(filename, canonical))
        return changed, json.loads(data[af3.AF3_NODES + filename])

    def defaults(self):
        current = [dict(row) for row in af3.HOME_WIDGETS if 'MDBList' in row.get('label', '')]
        legacy = [dict(row, path=row['path'].replace('action=mdblist_my_movies',
                  'action=mdblist_watchlist').replace('action=mdblist_my_tvshows',
                  'action=mdblist_watchlist')) for row in current]
        return current, legacy

    def test_af3_old_routes_upgrade_in_place_without_duplicate_widgets(self):
        canonical, old = self.defaults()
        custom = {'label': 'Mine', 'path': 'plugin://plugin.video.pov/?action=mdblist_watchlist&mode=custom'}
        changed, rows = self.merge([old[1], custom, old[0]], old, canonical)
        self.assertTrue(changed)
        self.assertEqual(rows, [canonical[1], custom, canonical[0]])

    def test_af3_removed_movie_widget_stays_removed(self):
        canonical, old = self.defaults()
        changed, rows = self.merge([old[1]], old, canonical)
        self.assertTrue(changed)
        self.assertEqual(rows, [canonical[1]])

    def test_af3_lost_baseline_does_not_duplicate_legacy_defaults(self):
        canonical, old = self.defaults()
        changed, rows = self.merge(old, None, canonical)
        self.assertTrue(changed)
        self.assertEqual(rows, canonical)


if __name__ == '__main__':
    unittest.main()
