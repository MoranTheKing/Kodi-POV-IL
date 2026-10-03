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
               'mdblist_activity_failed_read'}
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

    def response(self, status, body):
        return types.SimpleNamespace(status_code=status, ok=status < 400, headers={'Content-Type': 'application/json'},
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


if __name__ == '__main__':
    unittest.main()
