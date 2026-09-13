"""Integrated evening prototype: real pure modules, SQLite, persistence and action boundary."""
import copy,hashlib,importlib.util,json,os,sqlite3,sys,tempfile,unittest
from unittest.mock import patch
from urllib.parse import urlparse,parse_qs
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'addons/service.subtitles.kodipovilai'))
from resources.lib.tonight import engine,history,storage,entrypoints,catalog,ui,providers


def item(n=1,genres=('Mystery',),runtime=5400):
    return engine.normalize(dict(file='plugin://plugin.video.pov/?mode=play_media&mediatype=movie&tmdb_id='+str(n),title='Title '+str(n),genre=list(genres),runtime=runtime,rating=8))


class Tonight(unittest.TestCase):
    def test_refinement_refreshes_shared_action_path(self):
        state=engine.initial_state()
        changed=engine.refine(state,item(),'similar')
        with patch.object(ui,'_actions',return_value=(changed,False)), patch.object(ui,'_refresh',return_value=changed) as refresh, patch.object(providers,'current',return_value='umbrella'):
            result,playing=ui._act_and_refresh(None,None,None,item(),[],state,'folder')
            refresh.assert_called_once_with(changed,None,None,'folder','umbrella',None)
            self.assertFalse(playing)

    def test_provider_catalog_routes_are_distinct(self):
        for p,mode in [('pov','mode'),('umbrella','action')]:
            for kind in ('movie','tvshow'):
                url=providers.catalog_route(p,kind)
                self.assertEqual(urlparse(url).netloc,'plugin.video.'+p)
                self.assertIn(mode,parse_qs(urlparse(url).query))

    def test_umbrella_anchor_key_stays_internal(self):
        url=providers.catalog_route('umbrella','movie',item(7))
        inner=parse_qs(urlparse(url).query)['url'][0]
        self.assertEqual(inner,'https://api.themoviedb.org/3/movie/7/recommendations?api_key=%s&language=en-US&page=1')

    def test_same_movie_identity_survives_provider_change(self):
        a=item(9)
        b=engine.normalize(dict(file='plugin://plugin.video.umbrella/?action=play_Item&tmdb=9&imdb=tt1234567&title=Original',title='Translated',playcount=1))
        self.assertEqual(a['key'],b['key']);self.assertEqual(b['provider'],'umbrella');self.assertTrue(b['watched'])
        self.assertEqual(b['originaltitle'],'Original')

    def test_umbrella_episode_not_mistaken_for_movie(self):
        self.assertIsNone(engine.normalize(dict(file='plugin://plugin.video.umbrella/?action=play_Item&tmdb=9&season=1&episode=2',title='Episode')))

    def test_umbrella_playback_reconstructed_with_metadata(self):
        x=item();x.update(originaltitle='A, "title" & more',imdb='tt1234567',year=2020)
        parsed=parse_qs(urlparse(providers.playback_route('umbrella',x)).query)
        self.assertEqual(parsed['action'],['play_Item']);self.assertEqual(parsed['title'],[x['originaltitle']])
        self.assertEqual(json.loads(parsed['meta'][0])['tmdb'],'1')
        self.assertNotIn('mode',parsed)
        self.assertEqual((50/100)*json.loads(parsed['meta'][0])['duration'],45)

    def test_umbrella_seasons_and_trailer_native_types(self):
        x=item();x.update(kind='tvshow',key='tvshow:1',tvdb='99')
        parsed=parse_qs(urlparse(providers.playback_route('umbrella',x)).query)
        self.assertEqual(parsed['action'],['seasons']);self.assertEqual(parsed['tvdb'],['99'])
        self.assertEqual(parse_qs(urlparse(providers.trailer_route('umbrella',x)).query)['type'],['show'])

    def test_provider_rechecked_at_play_click(self):
        class D:
            def select(self,*a):return 0
        class X:
            def __init__(self):self.calls=[]
            def executebuiltin(self,v):self.calls.append(v)
        x=X()
        with patch.object(providers,'current',side_effect=['pov','umbrella']):ui._actions(D(),x,None,item(),[],engine.initial_state())
        self.assertIn('plugin.video.umbrella',x.calls[0]);self.assertNotIn('play_media',x.calls[0])

    def test_catalog_rejects_wrong_provider_rows(self):
        def rpc(_):return json.dumps(dict(result=dict(files=[dict(file=engine.provider_route('movie',1),title='POV')])))
        self.assertEqual(catalog.fetch(rpc,provider='umbrella'),[])

    def test_umbrella_remote_history_never_uses_local_cache(self):
        for value in ('1','2','3','5','6','99',''):
            self.assertFalse(history.umbrella_local_selected({'indicators.alt':value}))
        self.assertFalse(history.umbrella_local_selected({'indicators.alt':'4','dev.enable.custom':'true'}))
        self.assertTrue(history.umbrella_local_selected({'indicators.alt':'4','dev.enable.custom':'false'}))

    def test_umbrella_watched_readonly_and_overlay(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'watched.db';db=sqlite3.connect(p)
            db.execute('CREATE TABLE watched (media_type TEXT,tmdb_id TEXT,overlay INTEGER)')
            db.executemany('INSERT INTO watched VALUES (?,?,?)',[('movie','1',5),('movie','2',4),('episode','3',5)])
            db.commit();db.close();before=p.read_bytes()
            self.assertEqual(history.read_umbrella_local(p)['keys'],['movie:1']);self.assertEqual(p.read_bytes(),before)

    def test_shorter_is_strict_and_temporary(self):
        old=engine.initial_state();state=engine.refine(old,item(),'shorter')
        rows=engine.rank([item(2,runtime=5399),item(3,runtime=5400)],[state['profiles']['household']],state['session'])
        self.assertEqual([r['item']['key'] for r in rows],['movie:2'])
        self.assertEqual(state['profiles'],old['profiles']);storage.validate(state)

    def test_similar_tonight_does_not_invent_permanent_like(self):
        state=engine.refine(engine.initial_state(),item(),'similar');x=item(2);x['recommended_from']=['movie:1']
        ranked=engine.rank([x],[state['profiles']['household']],state['session'])
        self.assertTrue(any('בחרת לדייק' in r for r in ranked[0]['reasons']))
        self.assertFalse(state['profiles']['household']['feedback'])

    def test_different_direction_is_session_only(self):
        before=engine.initial_state();state=engine.refine(before,item(),'different')
        self.assertEqual(state['profiles'],before['profiles'])
        self.assertEqual(state['session']['avoid_genres'],item()['genres'])
    def test_ids_and_routes(self):
        for malicious in ('1,Quit()', '../2', '-1', '0', 'NaN', '1&mode=delete'):
            with self.assertRaises(ValueError):engine.provider_route('movie',malicious)
        self.assertIn('mode=play_media',engine.provider_route('movie',1))
        self.assertIn('mode=build_season_list',engine.provider_route('tvshow',1))

    def test_untrusted_catalog_urls(self):
        for value in (None,123,[],{}):
            self.assertIsNone(engine.normalize(dict(file=value,title='bad')))
        for route in ('http://example.org','plugin://other/?tmdb_id=1','plugin://plugin.video.pov/?mode=delete&tmdb_id=1','plugin://plugin.video.pov/?mode=play_media&mediatype=movie&tmdb_id=1&tmdb_id=2'):
            self.assertIsNone(engine.normalize(dict(file=route,title='bad')))

    def test_nonfinite_rating(self):
        x=engine.normalize(dict(file=engine.provider_route('movie',1),title='one',rating=float('nan')))
        self.assertEqual(x['rating'],0)

    def test_normalized_catalog_satisfies_storage_contract(self):
        state=engine.initial_state()
        state['catalog']=[engine.normalize(dict(file=engine.provider_route('movie',1),title='One',genre=['','  ',None,' Mystery ']))]
        storage.validate(state)
        self.assertEqual(state['catalog'][0]['genres'],['Mystery'])
        self.assertIsNone(engine.normalize(dict(file='plugin://[',title='bad')))

    def test_seen_does_not_mean_liked(self):
        state=engine.feedback(engine.initial_state(),'household',item(),'seen')
        self.assertFalse(state['profiles']['household']['feedback'])
        self.assertEqual(engine.rank([item()],[state['profiles']['household']],state['session']),[])

    def test_session_rejection_is_not_permanent(self):
        original=engine.initial_state();state=engine.feedback(original,'household',item(),'not_tonight')
        self.assertFalse(original['session']['excluded'])
        self.assertFalse(state['profiles']['household']['feedback'])
        self.assertFalse(engine.rank([item()],[state['profiles']['household']],state['session']))
        self.assertTrue(engine.rank([item()],[state['profiles']['household']],original['session']))

    def test_group_veto_not_average(self):
        a=engine.initial_state()['profiles']['household'];b=engine.feedback(engine.initial_state(),'household',item(),'dislike')['profiles']['household']
        self.assertFalse(engine.rank([item()],[a,b],dict(minutes=0)))

    def test_time_unknown_and_tv(self):
        tv=item(3);tv['kind']='tvshow';tv['key']='tvshow:3'
        rows=engine.rank([item(1,runtime=5400),item(2,runtime=0),tv],[engine.initial_state()['profiles']['household']],dict(minutes=90))
        self.assertEqual([r['item']['key'] for r in rows],['movie:1'])

    def test_time_hard_under_diversity(self):
        rows=engine.choose_three(engine.rank([item(i,runtime=i*3600) for i in range(1,12)],[engine.initial_state()['profiles']['household']],dict(minutes=60)))
        self.assertEqual(len(rows),1)

    def test_stable_no_duplicate_picks(self):
        c=[item(i) for i in range(1,9)]+[item(1)]
        p=[engine.initial_state()['profiles']['household']]
        a=engine.choose_three(engine.rank(c,p,{}));b=engine.choose_three(engine.rank(list(reversed(c)),p,{}))
        self.assertEqual(a,b);self.assertEqual(len({r['item']['key'] for r in a}),3)

    def test_no_invented_personal_reason(self):
        r=engine.rank([item()],[engine.initial_state()['profiles']['household']],{})[0]
        self.assertIn('עדיין לומדים',r['reasons'][0])

    def test_cancel_and_details_never_play(self):
        class D:
            def __init__(self):self.values=iter([1,-1])
            def select(self,*a,**kw):return next(self.values)
            def textviewer(self,*a):pass
        class X:
            def executebuiltin(self,*a):raise AssertionError('Playback before explicit request')
        state,playing=ui._actions(D(),X(),None,item(),[],engine.initial_state())
        self.assertFalse(playing)

    def test_play_exact_allowlist_route(self):
        class D:
            def select(self,*a):return 0
        class X:
            def __init__(self):self.calls=[]
            def executebuiltin(self,x):self.calls.append(x)
        x=X();_,playing=ui._actions(D(),x,None,item(),[],engine.initial_state())
        self.assertTrue(playing);self.assertEqual(x.calls,['RunPlugin("'+engine.provider_route('movie',1)+'")'])

    def test_catalog_rpc_read_only(self):
        requests=[]
        def rpc(raw):
            requests.append(json.loads(raw));return json.dumps(dict(result=dict(files=[dict(file=engine.provider_route('movie',1),title='One')])))
        rows=catalog.fetch(rpc)
        self.assertEqual(len(rows),1)
        self.assertEqual(requests[0]['method'],'Files.GetDirectory')
        self.assertNotIn('play_media',requests[0]['params']['directory'])

    def test_recommendation_provenance_requires_explicit_like(self):
        candidate=item(2,genres=('Comedy',));candidate['recommended_from']=['movie:1']
        plain=engine.initial_state();liked=engine.feedback(plain,'household',item(1),'like')
        base=engine.rank([candidate],[plain['profiles']['household']],{})[0]
        ranked=engine.rank([candidate],[liked['profiles']['household']],{})[0]
        self.assertGreater(ranked['score'],base['score'])
        self.assertIn('בעקבות',ranked['reasons'][0]);self.assertNotIn('בעקבות',base['reasons'][0])

    def test_duplicate_merging_preserves_recommendation_origin(self):
        a=item(1);b=item(1);b['recommended_from']=['movie:2']
        self.assertEqual(catalog.merge([a,b])[0]['recommended_from'],['movie:2'])

    def test_anchor_is_catalog_not_playback(self):
        calls=[]
        def rpc(raw):calls.append(json.loads(raw));return json.dumps(dict(result=dict(files=[])))
        catalog.fetch(rpc,anchor=item(15))
        self.assertIn('tmdb_movies_recommendations',calls[0]['params']['directory'])
        self.assertIn('tmdb_id=15',calls[0]['params']['directory'])
        self.assertNotIn('play_media',calls[0]['params']['directory'])

    def test_history_missing_never_created(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'missing.db';self.assertEqual(history.read_watched(p)['status'],'unknown');self.assertFalse(p.exists())

    def test_history_readonly_no_episode_to_movie(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'watched.db';db=sqlite3.connect(p)
            db.execute('CREATE TABLE watched_status (db_type TEXT, media_id TEXT)');db.executemany('INSERT INTO watched_status VALUES (?,?)',[('movie','1'),('episode','2')]);db.commit();db.close()
            before=p.read_bytes();self.assertEqual(history.read_watched(p)['keys'],['movie:1']);self.assertEqual(before,p.read_bytes())

    def test_active_provider_not_silent_local_fallback(self):
        self.assertEqual(history.selected_database(dict(trakt_user='connected',watched_indicators='1')),'traktcache.db')
        self.assertIsNone(history.selected_database(dict(trakt_user='connected',watched_indicators='99')))

    def test_storage_and_crash_safe_lock(self):
        with tempfile.TemporaryDirectory() as t:
            p=os.path.join(t,'preferences.json');storage.save(p,engine.initial_state());self.assertEqual(storage.load(p)['version'],1)
            with ui.exclusive(os.path.join(t,'lock')) as first:
                self.assertTrue(first)
                with ui.exclusive(os.path.join(t,'lock')) as second:self.assertFalse(second)
            with ui.exclusive(os.path.join(t,'lock')) as third:self.assertTrue(third)

    def test_corrupt_state_preserved(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'preferences.json';p.write_text('{broken')
            with self.assertRaises(storage.StateError):storage.load(p)
            self.assertEqual(p.read_text(),'{broken')

    def test_valid_json_but_invalid_state_preserved(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'preferences.json'
            for mutation in ('name','catalog','session','feedback'):
                value=engine.initial_state()
                if mutation=='name':del value['profiles']['household']['name']
                elif mutation=='catalog':value['catalog']=[{}]
                elif mutation=='session':value['session']['started']='tomorrow'
                else:value['profiles']['household']['feedback']={'movie:1':{'value':True}}
                before=json.dumps(value);p.write_text(before)
                with self.assertRaises(storage.StateError):storage.load(p)
                self.assertEqual(p.read_text(),before)

    def test_home_preserves_and_honors_deletion(self):
        raw='<favourites>\r\n  <favourite name="mine">Custom()</favourite>\r\n</favourites>\r\n'
        added=entrypoints.insert(raw);self.assertIn('Custom()',added);self.assertEqual(added,entrypoints.insert(added))
        deleted=added.replace('  <favourite name="הערב שלי — התנסות" thumb="special://home/addons/service.subtitles.kodipovilai/icon.png">'+entrypoints.ACTION+'</favourite>\n','')
        self.assertEqual(deleted,entrypoints.insert(deleted))
        self.assertEqual(entrypoints.insert('<broken'),'<broken')
        self.assertIn(entrypoints.ACTION,entrypoints.insert('<favourites />'))

    def test_standalone_excludes_feature(self):
        spec=importlib.util.spec_from_file_location('pack',ROOT/'tools/build_ai_subtitles_packages.py');pack=importlib.util.module_from_spec(spec);spec.loader.exec_module(pack)
        self.assertFalse(pack.include_standalone(Path('resources/lib/tonight/ui.py')))
        default=(ROOT/'addons/service.subtitles.kodipovilai/default.py').read_text(encoding='utf-8')
        slim=pack.slim_default_text(default);self.assertNotIn('resources.lib.tonight',slim);compile(slim,'slim','exec')


if __name__=='__main__':unittest.main()
