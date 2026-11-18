"""Wizard 0.5.6: POV's own favourites newest first, or by name (patches/pov_favorites_order.py).

A viewer, Nov 2026: "the ascending / descending order does nothing -- I sort them by hand; it needs an A-to-Z
setting". POV hands its lists to Kodi with no sort order, so Kodi's switch has nothing to reverse; the order of
POV's favourites is the order of its own query.
"""
import importlib.util
import sqlite3
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
spec = importlib.util.spec_from_file_location('pov_favorites_order_test', WIZARD / 'resources/libs/patches/pov_favorites_order.py')
order = importlib.util.module_from_spec(spec)
spec.loader.exec_module(order)


def hook():
    spec_c = importlib.util.spec_from_file_location('patches_config_fav_test', WIZARD / 'resources/libs/patches/patches_config.py')
    config = importlib.util.module_from_spec(spec_c)
    with mock.patch.dict(sys.modules, {'xbmc': types.SimpleNamespace(), 'xbmcvfs': types.SimpleNamespace()}):
        spec_c.loader.exec_module(config)
    patches = next(v for v in vars(config).values() if isinstance(v, list) and v and isinstance(v[0], dict) and 'hook' in v[0])
    return next(p for p in patches if p['id'] == 'pov_local_favorites_recent')


class OrderTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.file = str(Path(folder.name) / 'pov' / order.FILE)

    def test_newest_first_until_the_viewer_chooses_by_name_and_back(self):
        self.assertEqual(order.current(self.file), order.NEWEST, 'no file: as it was')
        self.assertEqual(order.clause(self.file), 'rowid DESC')
        self.assertEqual(order.switch(self.file), order.BY_NAME)
        self.assertEqual(order.clause(self.file), 'title COLLATE NOCASE ASC, rowid DESC')
        self.assertEqual(order.switch(self.file), order.NEWEST)
        Path(self.file).write_text('something else', encoding='utf-8')
        self.assertEqual(order.current(self.file), order.NEWEST, 'anything but "az" is newest first')

    def test_povs_query_follows_it(self):
        patch = hook()
        self.assertEqual(patch['marker'], '# WIZARD_POV_LOCAL_FAVORITES_RECENT_v2', 'a new marker: devices take the new block')
        con = sqlite3.connect(':memory:')
        con.execute('create table favorites (db_type, tmdb_id, title)')
        for row in (('movie', 1, 'Zulu'), ('movie', 2, 'alpha'), ('movie', 3, 'בלב הפרא'), ('movie', 4, 'Beta'), ('tvshow', 5, 'Aaa')):
            con.execute('insert into favorites values (?, ?, ?)', row)

        def call_local(sql, args):
            return [{'tmdb_id': r[0], 'title': r[1]} for r in con.execute(sql, args)]
        scope = {'call_local': call_local}
        exec('def favorites(mediatype, page_no):\n' + patch['hook'], scope)
        fake = types.ModuleType('pov_favorites_order')
        fake.clause = lambda: order.CLAUSES[order.NEWEST]
        with mock.patch.dict(sys.modules, {'pov_favorites_order': fake, 'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)}):
            self.assertEqual([i['title'] for i in scope['favorites']('movie', 'all')], ['Beta', 'בלב הפרא', 'alpha', 'Zulu'])
            fake.clause = lambda: order.CLAUSES[order.BY_NAME]
            names = [i['title'] for i in scope['favorites']('movie', 'all')]
            self.assertEqual(names, ['alpha', 'Beta', 'Zulu', 'בלב הפרא'], 'capitals do not matter; Latin names before Hebrew ones')
            items, pages = scope['favorites']('movie', 1)
            self.assertEqual(([i['media_id'] for i in items], pages), (['2', '4', '1', '3'], 1))
        # the Wizard's module missing (POV beside an older Wizard): newest first, as before
        broken = types.ModuleType('pov_favorites_order')
        with mock.patch.dict(sys.modules, {'pov_favorites_order': broken, 'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)}):
            self.assertEqual([i['title'] for i in scope['favorites']('movie', 'all')][0], 'Beta')

    def test_the_switch_shows_at_once_and_says_which(self):
        done, said, props = [], [], {}
        xbmc = types.SimpleNamespace(getInfoLabel=lambda label: 'plugin.video.pov', executebuiltin=done.append)
        window = types.SimpleNamespace(setProperty=lambda key, value: props.update({key: value}))
        xbmcgui = types.SimpleNamespace(Window=lambda _id: window, NOTIFICATION_INFO='info',
                                        Dialog=lambda: types.SimpleNamespace(notification=lambda *a: said.append(a)))
        with mock.patch.dict(sys.modules, {'xbmc': xbmc, 'xbmcgui': xbmcgui}), mock.patch.object(order, '_path', lambda: self.file):
            self.assertEqual(order.toggle(), order.BY_NAME)
        self.assertEqual(done, ['Container.Refresh'], 'the open list is asked again')
        self.assertIn('povil.lists.t', props, 'and the home\'s rows of saved titles, by their address')
        self.assertIn('לפי א-ב', said[0][1])

    def test_it_is_within_reach_and_a_saved_list_never_shows_the_other_order(self):
        settings = ET.parse(WIZARD / 'resources/settings.xml').getroot()
        line = next(s for s in settings.iter('setting') if s.get('id') == 'pov_favorites_order')
        self.assertEqual(line.get('type'), 'action')
        self.assertIn('?mode=pov_favorites_order', line.get('action'))
        router = (WIZARD / 'resources/libs/common/router.py').read_text('utf-8')
        self.assertIn("elif mode == 'pov_favorites_order':", router)
        home = (ROOT / 'skin.povil.onyx/xml/Home.xml').read_text('utf-8')
        self.assertIn('?mode=pov_favorites_order)</onclick>', home, 'a chip in Onyx\'s favourites tab')
        with mock.patch.dict(sys.modules, {'xbmc': types.SimpleNamespace(log=lambda *a: None, LOGINFO=1, LOGWARNING=2)}):
            spec_s = importlib.util.spec_from_file_location('snap_fav_test', WIZARD / 'resources/libs/patches/pov_list_snapshot.py')
            snap = importlib.util.module_from_spec(spec_s)
            spec_s.loader.exec_module(snap)
        self.assertIn(order.FILE, snap.HASHED_FILES)
        self.assertIn(order.FILE, snap.STAT_FILES)


if __name__ == '__main__':
    unittest.main()
