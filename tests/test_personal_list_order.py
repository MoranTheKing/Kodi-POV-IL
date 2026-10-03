"""Addition order in real provider methods, including cache hits and page slices."""
import ast
import importlib.util
import runpy
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit, parse_qs, quote_plus, parse_qsl, urlencode, urlparse

ROOT = Path(__file__).resolve().parents[1]
WIZ = ROOT / 'plugin.program.kodipovilwizard/resources/libs/patches'
FIX = ROOT / 'tests/fixtures/list_order'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


logic = load('qa_personal_logic', WIZ / 'pov_mdblist_patch_logic.py')
setup = load('qa_umbrella_order', ROOT / 'service.subtitles.kodipovilai/resources/lib/umbrella_setup_patcher.py')


def rows(count=5):
    return [{'id': i, 'title': str(i), 'listed_at': '2026-10-%02dT08:00:00Z' % i,
             'added': '2026-10-%02dT08:00:00Z' % i} for i in range(1, count + 1)]


def umbrella_class(name, values):
    text = setup._personal_order_source((FIX / (name + '.py')).read_text('utf8'), name + '.py')
    tree = ast.parse(text)
    tree.body = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    ns = {'_povil_order': logic, 'getSetting': lambda key: values.get(key, ''),
          'parse_qsl': parse_qsl, 'urlsplit': urlsplit, 'urlencode': urlencode,
          'quote_plus': quote_plus, 'urlparse': urlparse, 're': __import__('re')}
    ns['control'] = types.SimpleNamespace(homeWindow=types.SimpleNamespace(getProperty=lambda _: '', clearProperty=lambda _: None))
    ns['log_utils'] = types.SimpleNamespace(log=lambda *a, **k: None, error=lambda *a, **k: None)
    ns['cache'] = types.SimpleNamespace(get=lambda fn, hours, *args: fn(*args))
    ns['trakt'] = types.SimpleNamespace(get_all_pages=lambda *a, **k: [], getWatchedMoviesLastWatchedDates=lambda: {})
    ns['traktsync'] = types.SimpleNamespace(cache_existing=lambda _: [], fetch_watch_list=lambda _: rows(), fetch_collection=lambda _: rows())
    ns['trakt'].syncTVShows = lambda: None
    ns['trakt'].watchedShows = lambda: []
    exec(compile(tree, '<real umbrella methods>', 'exec'), ns)
    cls = ns[next(n.name for n in tree.body if isinstance(n, ast.ClassDef))]
    owner = cls()
    owner.page_limit = 2
    owner.list = []
    owner.worker = lambda: None
    owner.movieDirectory = owner.tvshowDirectory = lambda *a, **k: None
    owner.traktuserlist_hours = 1
    return owner, ns, text


class PersonalListOrderTests(unittest.TestCase):
    def test_times_offsets_missing_stability_and_cached_data_are_safe(self):
        items = [{'id': 'later', 'listed_at': '2026-10-03T10:01:00+03:00'},
                 {'id': 'earlier', 'listed_at': '2026-10-03T08:00:00+01:00'},
                 {'id': 'missing', 'listed_at': None}, {'id': 'invalid', 'added': 'invalid'}]
        original = list(items)
        self.assertEqual([i['id'] for i in logic.newest_personal_items(items)], ['later', 'earlier', 'missing', 'invalid'])
        self.assertEqual(items, original)
        self.assertEqual(logic.newest_personal_items(None), None)

    def test_mdbl_documented_sort_preserves_cursor_and_removes_ui_flag(self):
        url = 'https://api.mdblist.com/lists/7/items?unified=true&cursor=a%2Bb&sort=rank&povil_personal=1'
        result = logic.personal_mdbl_url(url)
        q = parse_qs(urlsplit(result).query)
        self.assertEqual(q, {'unified': ['true'], 'cursor': ['a+b'], 'sort': ['added'], 'order': ['desc']})
        self.assertNotIn('povil_personal', logic.personal_mdbl_url(url, False))
        public = url.replace('&povil_personal=1', '')
        self.assertEqual(logic.personal_mdbl_url(public), public)

    def test_pov_real_cached_trakt_items_order_before_pagination(self):
        config = runpy.run_path(str(WIZ / 'patches_config.py'))['PATCH_CONFIG']
        entry = next(e for e in config if e['id'] == 'pov_trakt_personal_newest')
        source = (FIX / 'trakt_api.py').read_text('utf8').replace(entry['anchor'], entry['hook'] + entry['anchor'])
        cached = rows(7)
        cache = Mock(return_value=cached)
        ns = {'trakt_cache': types.SimpleNamespace(cache_trakt_object=cache), '_get_trakt_paginated_list': object()}
        with patch.dict(sys.modules, {'xbmcvfs': types.SimpleNamespace(translatePath=lambda _: str(WIZ)), 'pov_mdblist_patch_logic': logic}):
            exec(source, ns)
            result = ns['get_trakt_list_contents']('my_lists', 1, 'me', 'test')
            self.assertEqual([i['id'] for i in result[:2]], [7, 6])
            self.assertEqual([i['id'] for i in result[2:4]], [5, 4])
            self.assertEqual([i['id'] for i in cached], list(range(1, 8)))
            self.assertIs(ns['get_trakt_list_contents']('liked_lists', 1, 'other', 'test'), cached)
        self.assertEqual(cache.call_count, 2)

    def test_pov_mdbl_uses_sorted_cursor_fetch_and_new_cache_namespace_once(self):
        config = runpy.run_path(str(WIZ / 'patches_config.py'))['PATCH_CONFIG']
        entry = next(e for e in config if e['id'] == 'pov_mdblist_personal_newest')
        source = (FIX / 'mdblist_api.py').read_text('utf8').replace(entry['anchor'], entry['hook'] + entry['anchor'])
        cache = Mock(return_value={'items': rows()})
        ns = {'mdbl_cache': types.SimpleNamespace(cache_mdbl_object=cache), '_get_mdbl_paginated_list': object()}
        with patch.dict(sys.modules, {'xbmcvfs': types.SimpleNamespace(translatePath=lambda _: str(WIZ)), 'pov_mdblist_patch_logic': logic}):
            exec(source, ns)
            ns['get_mdbl_list_contents']('my_lists', 7)
            args = cache.call_args.args
            self.assertTrue(args[1].endswith('_newest_v1'))
            self.assertEqual(parse_qs(urlsplit(args[2]).query), {'unified': ['true'], 'sort': ['added'], 'order': ['desc']})
            ns['get_mdbl_list_contents']('liked_lists', 7)
            self.assertNotIn('sort=', cache.call_args.args[2])
        self.assertEqual(cache.call_count, 2)

    def test_umbrella_watchlist_widgets_and_directory_pages_all_media(self):
        for media in ('movies', 'tvshows'):
            values = {'trakt.paginate.lists': 'true'}
            owner, ns, _ = umbrella_class(media, values)
            result = owner.traktWatchlist('https://api.trakt.tv/users/me/watchlist?limit=2&page=1', create_directory=False)
            self.assertEqual([i['id'] for i in result], [5, 4, 3, 2, 1])
            result = owner.traktWatchlist('https://api.trakt.tv/users/me/watchlist?limit=2&page=2')
            self.assertEqual([i['id'] for i in result], [3, 2])
            result = owner.traktCollection('https://api.trakt.tv/users/me/collection?limit=2&page=1', create_directory=False)
            self.assertEqual([i['id'] for i in result], [5, 4, 3, 2, 1])

    def test_umbrella_custom_trakt_global_pages_and_public_order(self):
        for media in ('movies', 'tvshows'):
            owner, ns, _ = umbrella_class(media, {'trakt.user.name': 'tester', 'trakt.paginate.lists': 'true'})
            data = [{'listed_at': i['listed_at'], 'movie': {'title': str(i['id']), 'ids': {}, 'year': 2020}, 'show': {'title': str(i['id']), 'ids': {}, 'year': 2020, 'airs': {'day': '', 'time': '', 'timezone': ''}}} for i in rows()]
            ns['trakt'].get_all_pages = lambda *a, **k: data
            result = owner.trakt_userList('https://api.trakt.tv/users/tester/lists/7/items?limit=2&page=1', create_directory=False)
            self.assertEqual([i['title'] for i in result], ['5', '4'])
            result = owner.trakt_userList('https://api.trakt.tv/users/tester/lists/7/items?limit=2&page=2', create_directory=False)
            self.assertEqual([i['title'] for i in result], ['3', '2'])
            result = owner.trakt_userList('https://api.trakt.tv/users/other/lists/7/items?limit=2&page=1', create_directory=False)
            self.assertEqual([i['title'] for i in result], ['1', '2'])

    def test_umbrella_explicit_sort_and_progress_are_untouched(self):
        owner = types.SimpleNamespace(list=rows())
        self.assertFalse(logic.umbrella_personal_sort(owner, 'movies.watchlist', lambda _: '4'))
        self.assertEqual([i['id'] for i in owner.list], [1, 2, 3, 4, 5])
        self.assertFalse(logic.umbrella_personal_sort(owner, 'progress', lambda _: '0'))

    def test_umbrella_mdbl_own_menu_and_request_order_before_page_slice(self):
        for media in ('movies', 'tvshows'):
            owner, ns, _ = umbrella_class(media, {'mdblist.paginate.lists': 'true'})
            calls = []
            def get_items(url):
                calls.append(url)
                q = parse_qs(urlsplit(url).query)
                values = rows()
                if q.get('sort') == ['added'] and q.get('order') == ['desc']: values.reverse()
                return [{'title': str(i['id']), 'rank': i['id']} for i in values]
            ns['mdblist'] = types.SimpleNamespace(getMDBItems=get_items,
                getMDBUserList=lambda *a, **k: [{'params': {'list_id': 7, 'list_name': 'test'}, 'unique_ids': {}}],
                get_user_watchlist=lambda _: rows(), get_user_collection=lambda _: rows())
            owner.mbdlist_list_items = 'https://api.mdblist.com/lists/%s/items?page=1'
            owned = owner.mbd_user_lists(False)[0]['url']
            self.assertIn('povil_personal=1', owned)
            result = owner.mdb_list_items(owned, create_directory=False)
            self.assertEqual([i['title'] for i in result], ['5', '4'])
            self.assertEqual(len(calls), 1)
            self.assertNotIn('povil_personal', calls[0])
            result = owner.mdb_list_items(owned.replace('page=1', 'page=2'), create_directory=False)
            self.assertEqual([i['title'] for i in result], ['3', '2'])
            # Watchlists/collections use their actual dates, even without API sorting.
            result = owner.get_mdbuser_watchlist(create_directory=False)
            self.assertEqual([i['id'] for i in owner.list], [5, 4])
            ns['_povil_order'] = None
            owner.list = []
            self.assertNotIn('povil_personal', owner.mbd_user_lists(False)[0]['url'])

    def test_local_umbrella_sqlite_remove_readd_and_media_isolation(self):
        source = setup._personal_order_source((FIX / 'favourites.py').read_text('utf8'), 'favourites.py')
        tree = ast.parse(source)
        tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        with tempfile.TemporaryDirectory() as raw:
            db = Path(raw) / 'favourites.db'
            con = sqlite3.connect(db)
            con.execute('create table movies(id text, items text)')
            con.execute('create table tvshows(id text, items text)')
            con.executemany('insert into movies values(?,?)', [('old', "{'title':'old'}"), ('new', "{'title':'new'}")])
            con.execute('insert into tvshows values(?,?)', ('series', "{'title':'series'}"))
            con.commit()
            ns = {'database': sqlite3, 'favouritesFile': str(db)}
            exec(compile(tree, '<real getFavourites>', 'exec'), ns)
            self.assertEqual([i[0] for i in ns['getFavourites']('movies')], ['new', 'old'])
            con.execute("delete from movies where id='old'")
            con.execute('insert into movies values(?,?)', ('old', "{'title':'old'}"))
            con.commit()
            self.assertEqual([i[0] for i in ns['getFavourites']('movies')], ['old', 'new'])
            self.assertEqual(ns['getFavourites']('tvshows')[0][0], 'series')
            con.close()

    def test_patcher_repeat_and_changed_upstream_fail_without_writes(self):
        for name in ('movies', 'tvshows', 'favourites'):
            source = (FIX / (name + '.py')).read_text('utf8')
            result = setup._personal_order_source(source, name + '.py')
            self.assertEqual(setup._personal_order_source(result, name + '.py'), result)
            compile(result, name, 'exec')
            crlf = source.replace('\n', '\r\n')
            patched = setup._personal_order_source(crlf, name + '.py')
            self.assertNotIn('\n', patched.replace('\r\n', ''))
        with self.assertRaises(ValueError):
            setup._personal_order_source('import re\nclass Movies: pass\n', 'movies.py')
        source = setup._personal_order_source((FIX / 'movies.py').read_text('utf8'), 'movies.py')
        with patch.dict(sys.modules, {'xbmcvfs': types.SimpleNamespace(translatePath=lambda _: str(WIZ)),
                                    'pov_mdblist_patch_logic': types.SimpleNamespace()}):
            ns = {}
            exec(source, ns)
            self.assertIsNone(ns['_povil_order'])


if __name__ == '__main__': unittest.main()
