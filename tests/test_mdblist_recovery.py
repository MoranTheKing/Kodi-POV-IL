"""Real POV request, cache, pagination and manager paths with a scripted API.

No live credentials or list mutations. Fixture responses cover the Android
incident (401 -> cached null/empty -> context-manager crash).
"""
import importlib.util
import json
import runpy
import sqlite3
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
WIZ = ROOT / 'plugin.program.kodipovilwizard/resources/libs'
FIX = ROOT / 'tests/fixtures/mdblist_recovery'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MDBListRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.props = {}
        self.values = {'mdblist.token': 'expired-fixture', 'mdblist.refresh': 'refresh-fixture',
                       'mdblist.client_id': 'fixture-client', 'mdblist_user': 'fixture-user'}
        self.notifications = []
        self.kodi = types.SimpleNamespace(
            get_setting=lambda k, *a: self.values.get(k, ''),
            set_setting=lambda k, v: self.values.__setitem__(k, v),
            sleep=lambda _: None, logger=Mock(), notification=self.notifications.append,
            select_dialog=Mock(return_value=None), no_results=Mock())
        self.window = types.SimpleNamespace(getProperty=lambda k: self.props.get(k, ''),
            setProperty=self.props.__setitem__, clearProperty=lambda k: self.props.pop(k, None))
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE mdbl_data(id TEXT PRIMARY KEY,data TEXT)')
        self.cache = types.ModuleType('caches.mdbl_cache')
        self.cache.MDBLCache = lambda: types.SimpleNamespace(dbcur=self.db.cursor())
        self.cache.MC_BASE_GET = 'SELECT data FROM mdbl_data WHERE id=?'
        self.cache.MC_BASE_SET = 'INSERT OR REPLACE INTO mdbl_data VALUES(?,?)'
        self.api = types.ModuleType('indexers.mdblist_api')
        self.api.session = types.SimpleNamespace(request=Mock())
        self.api.base_url, self.api.timeout = 'https://api.mdblist.com', 10
        self.api.MAX_LIST_ITEMS = 250000
        self.api.kodi_utils = self.kodi
        self.api.get_setting, self.api.set_setting, self.api.logger = self.kodi.get_setting, self.kodi.set_setting, self.kodi.logger
        self.api.mdbl_cache = self.cache
        self.logic = load('qa_mdbl_recovery', WIZ / 'patches/pov_mdblist_patch_logic.py')
        self.modules = {'xbmc': types.SimpleNamespace(LOGERROR=3), 'xbmcaddon': types.SimpleNamespace(),
            'xbmcvfs': types.SimpleNamespace(translatePath=lambda _: str(WIZ / 'patches')),
            'xbmcgui': types.SimpleNamespace(Window=lambda _: self.window),
            'resources.libs.common': types.SimpleNamespace(logging=types.SimpleNamespace(log=Mock())),
            'modules': types.SimpleNamespace(kodi_utils=self.kodi), 'modules.kodi_utils': self.kodi,
            'indexers': types.SimpleNamespace(mdblist_api=self.api), 'indexers.mdblist_api': self.api,
            'caches': types.SimpleNamespace(mdbl_cache=self.cache), 'caches.mdbl_cache': self.cache,
            'pov_mdblist_patch_logic': self.logic}
        self.patcher = patch.dict(sys.modules, self.modules)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        engine = load('qa_mdbl_engine', WIZ / 'patch_engine.py').PatchEngine([])
        config = runpy.run_path(str(WIZ / 'patches/patches_config.py'))['PATCH_CONFIG']
        ids = {'mdblist_api_redact_and_reauth_prep', 'mdblist_api_reauth_retry',
               'mdblist_cache_verified_reads', 'mdblist_complete_pagination', 'mdblist_manager_read_failure',
               'mdblist_activity_failed_read', 'mdblist_response_pagination'}
        def patched(filename, target):
            source = (FIX / filename).read_text('utf8')
            for entry in config:
                if entry['id'] in ids and entry['target_file'].endswith('/' + filename):
                    source, _, status = engine._apply_single_patch(source, entry, '\n')
                    self.assertEqual(status, 'applied')
            exec(compile(source, filename, 'exec'), target)
        patched('mdblist_api.py', vars(self.api))
        patched('mdbl_cache.py', vars(self.cache))
        base = {'kodi_utils': self.kodi, 'get_setting': self.kodi.get_setting,
                'media_path': lambda _: '', 'ls': lambda _: 'MDBList', 'json': json}
        exec((FIX / 'list_helper.py').read_text('utf8'), base)
        menu = {'list_helper': types.SimpleNamespace(BaseListManager=base['BaseListManager']),
                'mdblist_api': self.api, 'kodi_utils': self.kodi, 'watchl_str': 'Watchlist', 'coll_str': 'Collection'}
        patched('mdblist.py', menu)
        self.Manager = menu['MdbListManager']

    def response(self, status, body, headers=None):
        return types.SimpleNamespace(status_code=status, ok=status < 400, headers=dict({'Content-Type': 'application/json'}, **(headers or {})),
            reason='Unauthorized' if status == 401 else 'API error', url='https://api.mdblist.com/lists/user',
            json=lambda: body, text='')

    def test_real_generic_exception_401_refreshes_once_then_reads_lists(self):
        self.api.session.request.side_effect = [self.response(401, {}),
            self.response(200, {'expires_in': 3600, 'access_token': 'new-fixture', 'refresh_token': 'new-refresh'}),
            self.response(200, [{'id': 7, 'name': 'Mine', 'items': 3, 'dynamic': False}])]
        result = self.api.mdbl_get_lists('my_lists')
        self.assertEqual(result[0]['id'], 7)
        self.assertEqual(self.values['mdblist.token'], 'new-fixture')
        self.assertEqual(self.api.session.request.call_count, 3)
        self.assertEqual(self.api.session.request.call_args.kwargs['headers'], {'Authorization': 'Bearer new-fixture'})
        self.assertEqual(self.api.mdbl_get_lists('my_lists'), result)
        self.assertEqual(self.api.session.request.call_count, 3)

    def test_invalid_api_key_manager_not_crashed_no_write_or_empty_cache(self):
        self.values['mdblist.refresh'] = ''
        self.api.session.request.return_value = self.response(401, {})
        self.Manager({'tmdb_id': 7, 'mediatype': 'movie'}).manage()
        self.kodi.select_dialog.assert_not_called()
        self.assertIn('MDBList', self.notifications[0])
        self.assertEqual(self.api.session.request.call_count, 1)
        self.assertIsNone(self.db.execute("SELECT data FROM mdbl_data WHERE id='mdbl_my_lists'").fetchone())
        self.assertEqual(self.values['mdblist.token'], 'expired-fixture')

    def test_old_empty_cache_recovered_and_valid_empty_response_cached(self):
        for name, value in [('mdbl_watchlist', {'movies': [], 'shows': []}), ('mdbl_my_lists', None)]:
            self.db.execute('INSERT INTO mdbl_data VALUES(?,?)', (name, json.dumps(value)))
        body = {'movies': [{'id': 42}], 'shows': [{'id': 43}], 'pagination': {'has_more': False}}
        self.api.session.request.return_value = self.response(200, body)
        self.assertEqual(self.api.mdbl_collection_watchlist_items('watchlist', 'movies'), [{'id': 42}])
        self.assertEqual(self.api.mdbl_collection_watchlist_items('watchlist', 'shows'), [{'id': 43}])
        self.assertEqual(self.api.session.request.call_count, 1)
        self.api.session.request.return_value = self.response(200, [])
        self.assertEqual(self.api.mdbl_get_lists('my_lists'), [])
        self.assertEqual(self.api.mdbl_get_lists('my_lists'), [])
        self.assertEqual(self.api.session.request.call_count, 2)

    def test_partial_page_failure_not_cached_and_recovers_next_attempt(self):
        self.api.session.request.side_effect = [self.response(200, {'items': [{'id': 1}], 'pagination': {'has_more': True, 'next_cursor': 'next'}}),
                                               self.response(503, {})]
        with self.assertRaises(self.logic.MDBListUnavailable):
            self.cache.cache_mdbl_object(self.api._get_mdbl_paginated_list, 'fixture', '/lists/7/items')
        self.assertIsNone(self.db.execute("SELECT data FROM mdbl_data WHERE id='fixture'").fetchone())
        self.api.session.request.side_effect = None
        self.api.session.request.return_value = self.response(200, [])
        self.assertEqual(self.cache.cache_mdbl_object(self.api._get_mdbl_paginated_list, 'fixture', '/lists/7/items')['items'], [])

    def test_revoked_refresh_bounded_and_cooldown_no_automatic_writes(self):
        self.api.session.request.return_value = self.response(401, {})
        for _ in range(2):
            with self.assertRaises(self.logic.MDBListUnavailable): self.api.mdbl_get_lists('my_lists')
        methods = [c.args[0] for c in self.api.session.request.call_args_list]
        self.assertEqual(methods, ['get', 'post', 'get'])
        self.assertEqual(self.values['mdblist.refresh'], 'refresh-fixture')

    def test_busy_refresh_lock_not_stolen(self):
        self.props['pov_ai_mdbl_refreshing'] = 'true'
        self.api.session.request.return_value = self.response(401, {})
        self.assertIsNone(self.api.call_mdblist('/lists/user'))
        self.assertEqual(self.api.session.request.call_count, 1)
        self.assertEqual(self.props['pov_ai_mdbl_refreshing'], 'true')

    def test_failed_reads_do_not_erase_watched_tables_or_other_account_settings(self):
        self.db.execute('CREATE TABLE watched_status(id INTEGER)')
        self.db.execute('INSERT INTO watched_status VALUES(9)')
        self.api.session.request.return_value = self.response(403, {})
        with self.assertRaises(self.logic.MDBListUnavailable): self.api.mdbl_get_lists('my_lists')
        self.assertEqual(self.db.execute('SELECT id FROM watched_status').fetchall(), [(9,)])
        self.assertEqual(self.api.session.request.call_count, 1)

    def test_username_heal_uses_oauth_header_and_no_apikey(self):
        self.values['mdblist_user'] = ''
        self.api.session.request.return_value = self.response(200, {'username': 'recovered'})
        self.logic.heal_mdblist_account_if_needed()
        self.assertEqual(self.values['mdblist_user'], 'recovered')
        self.assertEqual(self.api.session.request.call_args.kwargs['headers'], {'Authorization': 'Bearer expired-fixture'})
        self.assertNotIn('apikey', self.api.session.request.call_args.kwargs['params'])

    def test_malformed_success_is_not_cached_or_used_as_empty_manager_choices(self):
        self.api.session.request.return_value = self.response(200, {'detail': 'not a list'})
        self.Manager({'tmdb_id': 7, 'mediatype': 'movie'}).manage()
        self.kodi.select_dialog.assert_not_called()
        self.assertIsNone(self.db.execute("SELECT data FROM mdbl_data WHERE id='mdbl_my_lists'").fetchone())

    def test_native_failed_activity_sync_does_not_clear_watched_and_progress(self):
        self.values['mdblist.refresh'] = ''
        self.api.session.request.return_value = self.response(401, {})
        self.cache.clear_mdbl_calendar = Mock()
        self.cache.clear_all_mdbl_cache_data = Mock()
        self.api.mdbl_get_activity = lambda: self.api.call_mdblist('/sync/last_activities')
        self.assertEqual(self.api.mdbl_sync_activities(), 'failed')
        self.cache.clear_all_mdbl_cache_data.assert_not_called()

    def collection_row(self, media, id, date):
        return {'collected_at': date, media: {'title': str(id), 'year': 2020,
                'ids': {'tmdb': id, 'imdb': 'tt%s' % id}}}

    def test_documented_collection_cursor_without_has_more_recovers_both_media(self):
        body = {'movies': [self.collection_row('movie', 42, '2026-10-04T08:00:00Z')],
                'shows': [self.collection_row('show', 43, '2026-10-04T09:00:00Z')],
                'pagination': {'total': 2, 'limit': 1000, 'offset': 0, 'next_cursor': None}}
        self.api.session.request.return_value = self.response(200, body)
        for media, id in (('movies', 42), ('shows', 43)):
            self.assertEqual(self.api.mdbl_collection_watchlist_items('collection', media)[0]['id'], id)
        self.assertEqual(self.api.session.request.call_count, 1)
        self.assertNotIn('has_more', body['pagination'])  # Provider object remains unchanged.

    def test_collection_cursor_pages_and_empty_final_page_keep_all_items(self):
        self.api.session.request.side_effect = [
            self.response(200, {'movies': [self.collection_row('movie', 42, '2026-10-04T08:00:00Z')],
                'pagination': {'total': 2, 'offset': 0, 'next_cursor': 'opaque+a'}}),
            self.response(200, {'shows': [self.collection_row('show', 43, '2026-10-04T09:00:00Z')],
                'pagination': {'total': 2, 'offset': 1, 'next_cursor': 'opaque+b'}}),
            self.response(200, {'movies': [], 'shows': [],
                'pagination': {'total': 2, 'offset': 2, 'next_cursor': None}})]
        self.assertEqual(self.api.mdbl_collection_watchlist_items('collection', 'shows')[0]['id'], 43)
        self.assertEqual(self.api.mdbl_collection_watchlist_items('collection', 'movies')[0]['id'], 42)
        params = [c.kwargs['params'] for c in self.api.session.request.call_args_list]
        self.assertEqual([p.get('cursor') for p in params], [None, 'opaque+a', 'opaque+b'])
        self.assertEqual(self.api.session.request.call_count, 3)

    def test_bucketed_watchlist_header_pagination_is_preserved(self):
        self.api.session.request.side_effect = [
            self.response(200, {'movies': [{'id': 1}], 'shows': []},
                {'X-Has-More': 'true', 'X-Next-Cursor': 'header+a'}),
            self.response(200, {'movies': [], 'shows': [{'id': 2}]}, {'X-Has-More': 'false'})]
        self.assertEqual(self.api.mdbl_collection_watchlist_items('watchlist', 'movies'), [{'id': 1}])
        self.assertEqual(self.api.mdbl_collection_watchlist_items('watchlist', 'shows'), [{'id': 2}])
        self.assertEqual(self.api.session.request.call_count, 2)

    def test_refreshed_oauth_preserves_bucketed_response_headers(self):
        self.api.session.request.side_effect = [self.response(401, {}),
            self.response(200, {'expires_in': 3600, 'access_token': 'new-fixture', 'refresh_token': 'new-refresh'}),
            self.response(200, {'movies': [{'id': 42}]}, {'X-Has-More': 'false'})]
        self.assertEqual(self.api.mdbl_collection_watchlist_items('watchlist', 'movies'), [{'id': 42}])
        self.assertEqual(self.api.session.request.call_count, 3)

    def test_empty_collection_cursor_is_valid_and_cached(self):
        self.api.session.request.return_value = self.response(200, {'movies': [], 'shows': [],
            'pagination': {'total': 0, 'next_cursor': None}})
        for media in ('movies', 'shows'):
            self.assertEqual(self.api.mdbl_collection_watchlist_items('collection', media), [])
        self.assertEqual(self.api.session.request.call_count, 1)

    def test_terminal_collection_counts_prove_completion_without_cursor_field(self):
        self.api.session.request.return_value = self.response(200, {'movies': [
            self.collection_row('movie', 42, '2026-10-04T08:00:00Z')], 'shows': [],
            'pagination': {'total': 1, 'offset': 0, 'limit': 1000}})
        self.assertEqual(self.api.mdbl_collection_watchlist_items('collection', 'movies')[0]['id'], 42)
        self.assertEqual(self.api.mdbl_collection_watchlist_items('collection', 'shows'), [])
        self.assertEqual(self.api.session.request.call_count, 1)

    def test_unknown_or_inconsistent_pagination_never_caches_partial_data(self):
        for pagination in ({}, {'has_more': 'false'}, {'has_more': False, 'next_cursor': 'more'},
                {'next_cursor': 42}, {'next_cursor': None, 'total': 100}, {'has_more': True}):
            with self.subTest(pagination=pagination):
                self.api.session.request.return_value = self.response(200, {'items': [{'id': 1}], 'pagination': pagination})
                with self.assertRaises(self.logic.MDBListUnavailable):
                    self.cache.cache_mdbl_object(self.api._get_mdbl_paginated_list, 'fixture', '/lists/7/items')
                self.assertIsNone(self.db.execute("SELECT data FROM mdbl_data WHERE id='fixture'").fetchone())

    def test_repeated_cursor_or_later_failure_does_not_cache_collection(self):
        page = {'movies': [self.collection_row('movie', 42, '2026-10-04T08:00:00Z')],
                'pagination': {'next_cursor': 'repeated'}}
        for last in (self.response(200, page), self.response(503, {})):
            self.api.session.request.side_effect = [self.response(200, page), last]
            with self.assertRaises(self.logic.MDBListUnavailable):
                self.api.mdbl_collection_watchlist_items('collection', 'movies')
            self.assertIsNone(self.db.execute("SELECT data FROM mdbl_data WHERE id='mdbl_collection'").fetchone())

    def test_conflicting_header_or_unknown_completion_is_rejected(self):
        for body, headers in (({'items': [], 'pagination': {'has_more': False}}, {'X-Has-More': 'true'}),
                ({'items': []}, {'X-Has-More': 'invalid'}), ({'movies': [], 'shows': []}, {})):
            self.api.session.request.return_value = self.response(200, body, headers)
            with self.assertRaises(self.logic.MDBListUnavailable): self.api._get_mdbl_paginated_list('/watchlist/items')

    def test_collection_and_watchlist_merged_newest_before_slice_for_movies_and_shows(self):
        settings = types.SimpleNamespace(lists_sort_order=lambda *a: 1, paginate=lambda: True,
            page_limit=lambda: 2, show_unaired_watchlist=lambda: True)
        paginate = {'chunks': lambda rows, limit: [rows[i:i+limit] for i in range(0, len(rows), limit)]}
        source = (ROOT / 'tests/fixtures/list_order/paginate.py').read_text('utf8')
        entry = next(e for e in runpy.run_path(str(WIZ / 'patches/patches_config.py'))['PATCH_CONFIG']
                     if e['id'] == 'pov_merged_personal_pagination')
        exec(source.replace(entry['anchor'], entry['hook'] + entry['anchor']), paginate)
        self.modules['modules'].settings = settings
        self.modules['modules'].utils = types.SimpleNamespace(paginate_list=paginate['paginate_list'])
        self.api.settings, self.api.paginate_list = settings, paginate['paginate_list']
        exec((ROOT / 'tests/fixtures/list_order/merged_mdblist.py').read_text('utf8'), vars(self.api))
        merged = load('qa_my_lists', WIZ / 'patches/pov_my_lists.py')
        visibility = load('qa_personal_routes', WIZ / 'patches/pov_visibility_mgr.py')
        for media, singular in (('movies', 'movie'), ('shows', 'show')):
            self.db.execute('DELETE FROM mdbl_data')
            collection = {media: [self.collection_row(singular, i, '2026-10-0%dT08:00:00Z' % i)
                                 for i in (1, 2, 3)], 'pagination': {'total': 3, 'next_cursor': None}}
            watchlist = {media: [{'id': i, 'watchlist_at': '2026-10-0%dT09:00:00Z' % i}
                                for i in (3, 4)]}
            self.api.session.request.side_effect = [self.response(200, collection),
                self.response(200, watchlist, {'X-Has-More': 'false'})]
            sources = ((self.api.mdblist_collection, 'mdblist_collection'),
                       (self.api.mdblist_watchlist, 'mdblist_watchlist'))
            self.assertEqual(merged._merge_tmdb_or_mdblist(sources, media, 1), ([4, 3], 2))
            self.assertEqual(merged._merge_tmdb_or_mdblist(sources, media, 2), ([2, 1], 2))
            name, canonical = next((name, row) for name, row in visibility._MDBLIST_ROWS.items()
                                   if row['action'].endswith('movies' if media == 'movies' else 'tvshows'))
            with patch.object(visibility, '_snapshot', return_value={'svc': {'mdblist': True}}), \
                    patch.object(visibility, 'is_service_active', return_value=True), \
                    patch.dict(sys.modules, {'pov_visibility_mgr': visibility}):
                route = visibility.filter_navigator_list(
                    [dict(canonical, action='mdblist_watchlist')], name)[0]
                entry_point = merged.maybe_populate_movies if media == 'movies' else merged.maybe_populate_tvshows
                for page, expected in ((1, [4, 3]), (2, [2, 1])):
                    instance = types.SimpleNamespace(action=route['action'], list=[])
                    entry_point(instance, page)
                    self.assertEqual(instance.list, expected)
            self.assertEqual(self.api.session.request.call_count, 2 if media == 'movies' else 4)


if __name__ == '__main__':
    unittest.main()
