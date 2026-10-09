"""Removal survives providers, failed reads, restarts and native SQL updates."""
from contextlib import closing
import http.server
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'plugin.program.kodipovilwizard/resources/libs/patches/pov_continue_watching.py'
spec = importlib.util.spec_from_file_location('continue_tests', SOURCE)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'watched.db'
        with closing(sqlite3.connect(self.db)) as c:
            c.executescript('CREATE TABLE dropped(db_type TEXT,tmdb_id TEXT,title TEXT,UNIQUE(db_type,tmdb_id));'
                            'CREATE TABLE watched_status(id TEXT); INSERT INTO watched_status VALUES("KEEP HISTORY");'
                            'CREATE TABLE progress(id TEXT); INSERT INTO progress VALUES("KEEP RESUME");')
            c.commit()
        self.settings = {'trakt.token': 'token-one', 'trakt_user': 'account-one',
                         'mdblist.token': 'token-two', 'mdblist_user': 'account-two'}
        self.utils = types.SimpleNamespace(get_setting=lambda key, fallback=None: self.settings.get(key, fallback),
            translate_path=lambda p:p, databases_path=str(self.root) + '/',
            notification=Mock(), logger=Mock(), notify_error=Mock(return_value=False),
            notify_success=Mock(), widget_refresh=Mock(), container_refresh=Mock(), external_browse=lambda:False)
        self.local = types.SimpleNamespace(local_droplist=self.local_rows,
            call_local=self.sql, add_to_sync=self.add, remove_from_sync=self.remove)
        self.trakt = types.SimpleNamespace(READ_TOKEN='client-id', base_url='', trakt_refresh=Mock())
        self.mdbl = types.SimpleNamespace(base_url='', mdbl_refresh=Mock())
        self.native_indexers = types.SimpleNamespace(trakt_api=self.trakt, mdblist_api=self.mdbl)
        mdbl_spec = importlib.util.spec_from_file_location('pov_mdblist_patch_logic',
            SOURCE.with_name('pov_mdblist_patch_logic.py'))
        mdbl_helper = importlib.util.module_from_spec(mdbl_spec);mdbl_spec.loader.exec_module(mdbl_helper)
        modules = {'modules': types.SimpleNamespace(kodi_utils=self.utils),
                   'indexers':self.native_indexers, 'indexers.local_api':self.local,
                   'pov_mdblist_patch_logic':mdbl_helper,
                   'caches':types.SimpleNamespace(
                       trakt_cache=types.SimpleNamespace(clear_trakt_hidden_data=Mock()),
                       mdbl_cache=types.SimpleNamespace(clear_mdbl_hidden_data=Mock()))}
        self.modules = patch.dict(sys.modules, modules)
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def sql(self, command, values=()):
        with closing(sqlite3.connect(self.db)) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(command, values)
            result = [dict(row) for row in rows] if command.startswith('SELECT') else None
            c.commit()
            return result

    def local_rows(self, _watched, mediatype, _page):
        return self.sql('SELECT tmdb_id,title FROM dropped WHERE db_type=?', (mediatype,))

    def add(self, _list, mediatype, tmdb_id, title):
        self.sql('INSERT OR IGNORE INTO dropped VALUES(?,?,?)', (mediatype,str(tmdb_id),title))
        return True

    def remove(self, _list, mediatype, tmdb_id, _title):
        self.sql('DELETE FROM dropped WHERE db_type=? AND tmdb_id=?', (mediatype,str(tmdb_id)))
        return True

    def check_history(self):
        self.assertEqual(self.sql('SELECT * FROM watched_status'), [{'id':'KEEP HISTORY'}])
        self.assertEqual(self.sql('SELECT * FROM progress'), [{'id':'KEEP RESUME'}])

    def test_local_removal_is_applied_with_all_three_providers_and_survives_reload(self):
        self.add('dropped','tvshow',1396,'Show')
        self.add('dropped','movie',456,'Other ID namespace')
        with patch.object(helper,'remote_hidden',return_value={82728}):
            for indicator, expected in ((0,{1396}),(1,{1396,82728}),(2,{1396,82728})):
                self.assertEqual(helper.dropped_info({},indicator),expected)
                # Re-read persistent SQL, not an interpreter's previous set.
                self.assertEqual(helper.dropped_info({},indicator),expected)
        self.check_history()

    def test_local_remove_restore_confirmation_and_widget_refresh(self):
        params=dict(mediatype='tvshow',tmdb_id='1396',title='Show')
        with patch.object(helper,'remote_hidden',return_value=set()):
            self.assertIsNone(helper.dropped_choice(params, {'confirm_dialog':lambda **kw:False}))
            self.assertNotIn(1396,helper.dropped_info({},2))
            self.assertTrue(helper.dropped_choice(params, {'confirm_dialog':lambda **kw:True}))
            self.assertIn(1396,helper.dropped_info({},2))
            self.assertTrue(helper.dropped_choice(params, {'confirm_dialog':lambda **kw:True}))
            self.assertNotIn(1396,helper.dropped_info({},2))
        self.assertEqual(self.utils.widget_refresh.call_count,2)
        self.check_history()

    def test_first_failed_cloud_read_does_not_restore_unknown_hidden_shows(self):
        self.add('dropped','tvshow',1396,'Show')
        with patch.object(helper,'remote_hidden',side_effect=helper.HiddenUnavailable(429)):
            hidden=helper.dropped_info({},1)
        self.assertIn(1396,hidden)
        self.assertIn(82728,hidden)
        self.check_history()

    def test_optional_watchlist_and_bookmark_sources_honor_same_removals(self):
        self.add('dropped','tvshow',1396,'Show')
        rows=[{'media_ids':{'tmdb':i}} for i in ('1396','456','82728')]
        with patch.object(helper,'remote_hidden',return_value={82728}):
            for list_type in ('next_episode_pov','in_progress'):
                menu=types.SimpleNamespace(list_type=list_type,watched_indicators=2,list=rows[:])
                helper.filter_episode_sources(menu)
                self.assertEqual(menu.list,[rows[1]])
            menu=types.SimpleNamespace(list_type='trakt_calendar',watched_indicators=2,list=rows[:])
            helper.filter_episode_sources(menu)
            self.assertEqual(menu.list,rows)

    def test_valid_empty_hidden_list_is_cached_without_repeated_http(self):
        path=str(self.root/'snapshot.json'); reader=Mock(return_value=set())
        for stamp in (1000,1001,1100):
            self.assertEqual(helper.snapshot(path,'A',reader,False,stamp),set())
        self.assertEqual(reader.call_count,1)
        state=helper._load(path,'A')
        self.assertTrue(state['complete'])
        self.assertNotIn('token',Path(path).read_text())

    def test_rate_limited_read_keeps_last_verified_ids_and_respects_cooldown(self):
        path=str(self.root/'snapshot.json')
        self.assertEqual(helper.snapshot(path,'A',lambda:{1396},False,1000),{1396})
        reader=Mock(side_effect=helper.HiddenUnavailable(429,120))
        self.assertEqual(helper.snapshot(path,'A',reader,False,1400),{1396})
        self.assertEqual(helper.snapshot(path,'A',reader,False,1401),{1396})
        self.assertEqual(reader.call_count,1)
        self.assertEqual(helper._load(path,'A')['retry_at'],1520)
        self.assertEqual(helper.snapshot(path,'A',lambda:{456},False,1521),{456})

    def test_no_initial_snapshot_failure_is_not_cached_as_empty_success(self):
        path=str(self.root/'snapshot.json');reader=Mock(side_effect=helper.HiddenUnavailable())
        for stamp in (1000,1001):
            with self.assertRaises(helper.HiddenUnavailable):helper.snapshot(path,'A',reader,False,stamp)
        self.assertEqual(reader.call_count,1)
        self.assertFalse(helper._load(path,'A')['complete'])
        self.assertEqual(helper.snapshot(path,'A',lambda:{1396},False,1061),{1396})

    def test_account_or_profile_change_never_reads_another_snapshot(self):
        path=str(self.root/'snapshot.json')
        helper.snapshot(path,'A',lambda:{1396},False,1000)
        self.assertEqual(helper.snapshot(path,'B',lambda:{456},False,1001),{456})
        other=str(self.root/'profile2'/'snapshot.json')
        self.assertEqual(helper.snapshot(other,'B',lambda:set(),False,1002),set())
        self.assertEqual(helper._load(path,'B')['items'],[456])
        self.settings['trakt_user']='different-account'
        self.assertNotEqual(helper._identity('trakt'),helper._identity('mdblist'))

    def test_stale_known_snapshot_returns_immediately_while_refresh_finishes(self):
        path=str(self.root/'snapshot.json');stamp=time.time()-1000
        helper.snapshot(path,'A',lambda:{1396},False,stamp)
        entered=threading.Event();release=threading.Event()
        def reader():
            entered.set();release.wait(3);return {456}
        start=time.monotonic()
        self.assertEqual(helper.snapshot(path,'A',reader),{1396})
        self.assertLess(time.monotonic()-start,.15)
        self.assertTrue(entered.wait(1))
        self.assertEqual(helper.snapshot(path,'A',lambda:self.fail('duplicate refresh')),{1396})
        release.set()
        deadline=time.monotonic()+3
        while helper._load(path,'A').get('items')!=[456] and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(helper._load(path,'A')['items'],[456])

    def test_failed_remote_toggle_preserves_local_and_remote_exclusions(self):
        self.add('dropped','tvshow',1396,'Show')
        with patch.object(helper,'remote_hidden',return_value={1396}):
            self.assertFalse(helper.remote_toggle({'call_trakt':lambda *a,**kw:None},
                'trakt','1396','shows','tt0903747','dropped'))
        self.assertEqual(self.local_rows(None,'tvshow','all'),[{'tmdb_id':'1396','title':'Show'}])
        self.utils.notify_success.assert_not_called()
        self.check_history()

    def test_verified_provider_toggle_updates_local_snapshot_and_uses_tmdb_id(self):
        for provider in ('trakt','mdblist'):
            request=Mock(return_value={'added':{'shows':1}})
            native={'call_trakt':request,'call_mdblist':request}
            with patch.object(helper,'remote_hidden',return_value=set()):
                self.assertTrue(helper.remote_toggle(native,provider,'1396','shows',None,'dropped'))
            payload=request.call_args.kwargs.get('data',request.call_args.kwargs.get('json'))
            self.assertEqual(payload,{'shows':[{'ids':{'tmdb':1396}}]})
            self.assertIn(1396,helper._load(helper._path(provider),helper._identity(provider))['items'])
            request.return_value={'deleted':{'shows':1}}
            with patch.object(helper,'remote_hidden',return_value={1396}):
                self.assertTrue(helper.remote_toggle(native,provider,'1396','shows',None,'dropped'))
            self.assertEqual(self.local_rows(None,'tvshow','all'),[])
            self.assertEqual(helper._load(helper._path(provider),helper._identity(provider))['items'],[])
        self.check_history()

    def test_unverified_remote_mutation_cannot_clear_exclusions(self):
        self.add('dropped','tvshow',1396,'Show')
        for result in ({'deleted':{'shows':1},'not_found':None},
                       {'deleted':{'shows':1},'not_found':{'shows':[1396]}},
                       {'deleted':{'shows':'1'}}, {'error':'failure'}):
            with self.subTest(result=result), patch.object(helper,'remote_hidden',return_value={1396}):
                self.assertFalse(helper.remote_toggle({'call_trakt':lambda *a,**kw:result},
                    'trakt','1396','shows','tt0903747','dropped'))
            self.assertEqual(self.local_rows(None,'tvshow','all'),[{'tmdb_id':'1396','title':'Show'}])
        self.utils.notify_success.assert_not_called()
        self.check_history()

    def test_episode_actions_use_real_season_and_native_handler(self):
        cm=[];scope=dict(self=types.SimpleNamespace(cm_sort={'mark':6},watched_title='MDBList',list_type='next_episode_pov'),
            cm_append=cm.append, season=5,unaired=False,year=2020,tmdb_id=1396,tvdb_id=81189,title='Show',
            build_url=lambda p:json.dumps(p,sort_keys=True),run_plugin='RunPlugin(%s)')
        helper.append_episode_actions(scope)
        self.assertEqual(len(cm),2)
        self.assertIn('mark_as_watched_unwatched_season',cm[0][2])
        self.assertIn('"season": 5',cm[0][2])
        self.assertIn('dropped_choice',cm[1][2])
        # The native hook passes locals(); URL helpers are module globals.
        build_url=scope.pop('build_url');run_plugin=scope.pop('run_plugin')
        cm.clear();helper.append_episode_actions(scope,build_url,run_plugin)
        self.assertEqual(len(cm),2)
        scope.update(build_url=build_url,run_plugin=run_plugin)
        scope['unaired']=True;cm.clear();helper.append_episode_actions(scope)
        self.assertEqual(len(cm),1)
        scope['self'].list_type='trakt_calendar';cm.clear();helper.append_episode_actions(scope)
        self.assertEqual(cm,[])

    def test_provider_hooks_preserve_native_actions_outside_show_dropped_lists(self):
        import runpy
        config=runpy.run_path(str(ROOT/'plugin.program.kodipovilwizard/resources/libs/patches/patches_config.py'))['PATCH_CONFIG']
        for prefix in ('trakt','mdbl'):
            entry=next(row for row in config if row['id']=='pov_'+prefix+'_verified_continue_toggle')
            namespace={};remote=Mock(return_value='verified')
            with patch.dict(sys.modules,{'xbmcvfs':types.SimpleNamespace(translatePath=lambda p:p),
                                         'pov_continue_watching':types.SimpleNamespace(remote_toggle=remote)}):
                exec('def native(action, mediatype, media_id, list_type):\n'+entry['hook']+'\n\treturn "native"\n',namespace)
                for media,list_type in (('movies','dropped'),('shows','watchlist')):
                    self.assertEqual(namespace['native']('hide',media,'1396',list_type),'native')
                remote.assert_not_called()
                self.assertEqual(namespace['native']('1396','shows',None,'dropped'),'verified')
                self.assertEqual(remote.call_count,1)

    def server(self, responses):
        requests=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                requests.append(dict(path=self.path,auth=self.headers.get('Authorization')))
                status,headers,body=responses[min(len(requests)-1,len(responses)-1)]
                raw=json.dumps(body).encode()
                self.send_response(status)
                for key,value in headers.items():self.send_header(key,str(value))
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(2)))
        self.trakt.base_url=self.mdbl.base_url='http://127.0.0.1:%s'%server.server_port
        fixture=ROOT/'tests/fixtures/http_session/session.py'
        spec=importlib.util.spec_from_file_location('session',fixture)
        native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
        self.modules2=patch.dict(sys.modules,{'session':native})
        self.modules2.start();self.addCleanup(self.modules2.stop)
        self.addCleanup(lambda:(native.session.close(),native.http.clear()))
        return requests

    def test_http_429_with_long_retry_after_returns_without_sleep_or_retry(self):
        requests=self.server([(429,{'Retry-After':120},{'error':'rate limit'})])
        start=time.monotonic()
        with self.assertRaises(helper.HiddenUnavailable) as caught:
            helper._read_remote('trakt',helper._identity('trakt'))
        self.assertEqual(caught.exception.retry_after,120)
        self.assertLess(time.monotonic()-start,1)
        self.assertEqual(len(requests),1)
        self.assertEqual(requests[0]['auth'],'Bearer token-one')

    def test_all_trakt_hidden_pages_must_be_verified_before_snapshot(self):
        row=lambda id:{'show':{'ids':{'tmdb':id}}}
        self.server([(200,{'X-Pagination-Page-Count':2},[row(1396)]),
                     (200,{'X-Pagination-Page-Count':2},[row(456)])])
        self.assertEqual(helper._read_remote('trakt',helper._identity('trakt')),{1396,456})

    def test_trakt_empty_collection_with_zero_pages_is_a_verified_empty_list(self):
        requests=self.server([(200,{'X-Pagination-Page-Count':0,'X-Pagination-Item-Count':0},[])])
        identity=helper._identity('trakt')
        for stamp in (1000,1001):
            self.assertEqual(helper.snapshot(helper._path('trakt'),identity,
                lambda:helper._read_remote('trakt',identity),False,stamp),set())
        self.assertEqual(len(requests),1)

    def test_partial_or_malformed_trakt_response_is_not_an_empty_list(self):
        for responses in ([(200,{},[])],[(200,{'X-Pagination-Page-Count':1},{'error':'invalid'})],
                          [(200,{'X-Pagination-Page-Count':2},[{'show':{'ids':{'tmdb':1396}}}]),
                           (503,{},[]) ]):
            with self.subTest(responses=responses):
                self.server(responses)
                with self.assertRaises(helper.HiddenUnavailable):
                    helper._read_remote('trakt',helper._identity('trakt'))

    def test_repeated_debrid_hashes_update_only_the_same_provider(self):
        import runpy
        config=runpy.run_path(str(ROOT/'plugin.program.kodipovilwizard/resources/libs/patches/patches_config.py'))['PATCH_CONFIG']
        entry=next(row for row in config if row['id']=='pov_debrid_cache_upsert')
        namespace={};exec(entry['hook'],namespace)
        with closing(sqlite3.connect(':memory:')) as c:
            c.execute('CREATE TABLE debrid_data(hash TEXT,debrid TEXT,cached INTEGER,expiry INTEGER,UNIQUE(hash,debrid))')
            c.execute('INSERT INTO debrid_data VALUES("hash","other",1,1)')
            c.executemany(namespace['SET_MANY'],[('hash','main',0,10),('hash','main',1,20)])
            self.assertEqual(c.execute('SELECT * FROM debrid_data ORDER BY debrid').fetchall(),
                             [('hash','main',1,20),('hash','other',1,1)])

    def test_mdblist_complete_pages_and_real_empty_lists(self):
        row=lambda id:{'show':{'ids':{'tmdb':id}}}
        requests=self.server([(200,{}, {'shows':[row(1396)],'pagination':{'next_cursor':'next'}}),
            (200,{}, {'shows':[row(456)],'pagination':{'next_cursor':None}})])
        self.assertEqual(helper._read_remote('mdblist',helper._identity('mdblist')),{1396,456})
        self.assertIn('cursor=next',requests[1]['path'])
        self.server([(200,{}, {'shows':[],'pagination':{'next_cursor':None}})])
        self.assertEqual(helper._read_remote('mdblist',helper._identity('mdblist')),set())

    def test_mdblist_repeated_cursor_failure_and_unknown_completion_are_rejected(self):
        row={'show':{'ids':{'tmdb':1396}}}
        for response in ({'shows':[row]}, {'shows':[row],'pagination':{'next_cursor':'same'}},
                         {'shows':[row],'pagination':{'has_more':False,'next_cursor':'inconsistent'}}):
            with self.subTest(response=response):
                self.server([(200,{},response)])
                with self.assertRaises(helper.HiddenUnavailable):
                    helper._read_remote('mdblist',helper._identity('mdblist'))

    def test_mdblist_uses_oauth_header_and_verifies_identity_after_read(self):
        self.settings['mdblist.refresh']='refresh-present'
        requests=self.server([(200,{}, {'shows':[],'pagination':{'next_cursor':None}})])
        self.assertEqual(helper._read_remote('mdblist',helper._identity('mdblist')),set())
        self.assertEqual(requests[0]['auth'],'Bearer token-two')
        self.assertNotIn('apikey',requests[0]['path'])
        with self.assertRaises(helper.HiddenUnavailable):
            helper._read_remote('mdblist','wrong identity')


if __name__=='__main__':unittest.main()
