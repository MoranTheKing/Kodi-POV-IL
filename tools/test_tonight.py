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
    def test_cancelled_load_closes_progress_and_preserves_catalog_silently(self):
        import types
        closed=[]
        progress=types.SimpleNamespace(create=lambda *a:None,iscanceled=lambda:True,close=lambda:closed.append(True))
        xbmc=types.SimpleNamespace(Monitor=lambda:types.SimpleNamespace(abortRequested=lambda:False))
        gui=types.SimpleNamespace(DialogProgress=lambda:progress)
        with patch.object(ui.threading,'Thread',return_value=types.SimpleNamespace(start=lambda:None)):
            self.assertIs(ui._load_catalog(xbmc,gui,'unused'),ui._CANCELLED)
        self.assertEqual(closed,[True])
        state=engine.initial_state();state['catalog']=[item()]
        notices=[];dialog=types.SimpleNamespace(ok=lambda *a:notices.append(a))
        with patch.object(ui,'_load_catalog',return_value=ui._CANCELLED):
            self.assertIs(ui._refresh(state,None,None,'unused','pov',dialog),state)
        self.assertFalse(notices);self.assertEqual(state['catalog'],[item()])
        with patch.object(ui,'_load_catalog',return_value=None):
            self.assertIs(ui._refresh(state,None,None,'unused','pov',dialog),state)
        self.assertEqual(len(notices),1);self.assertEqual(state['catalog'],[item()])

    def test_visible_filter_summary_includes_shorter_cap_and_type(self):
        self.assertIn('סדרות',ui._session_summary(dict(kind='tvshow',minutes=0)))
        self.assertIn('ללא מגבלת זמן',ui._session_summary(dict(minutes=0)))
        self.assertIn('90',ui._session_summary(dict(kind='movie',minutes=90)))
        summary=ui._session_summary(dict(kind='movie',minutes=120,max_runtime=5399))
        self.assertIn('סרטים',summary);self.assertIn('90',summary);self.assertNotIn('120',summary)

    def test_first_load_explained_profile_limit_and_search_cancel_silent(self):
        import types
        state=engine.initial_state()
        for i in range(7):state['profiles'][str(i)]=dict(name=str(i),feedback={},seen=[],saved=[])
        notices=[];menus=[];profile_rows=[];steps=iter(['מי צופה','היכרות —',0,-1])
        class ListItem:
            def __init__(self,label='',label2='',**kw):self.label=label;self.label2=label2
            def setArt(self,*a):pass
            def setInfo(self,*a):pass
        class Dialog:
            def select(self,title,rows,**kw):
                menus.append(rows);choice=next(steps)
                if isinstance(choice,str):return next(i for i,row in enumerate(rows) if choice in (row if isinstance(row,str) else row.label))
                return choice
            def multiselect(self,title,rows,**kw):profile_rows.extend(rows);return None
            def input(self,*a):return 'query'
            def ok(self,*a):notices.append(a)
        with tempfile.TemporaryDirectory() as folder:
            fake=dict(xbmc=types.SimpleNamespace(Monitor=lambda:types.SimpleNamespace(abortRequested=lambda:False)),
                      xbmcaddon=types.SimpleNamespace(Addon=lambda *a:types.SimpleNamespace(getAddonInfo=lambda *a:folder)),
                      xbmcgui=types.SimpleNamespace(Dialog=Dialog,ListItem=ListItem),xbmcvfs=types.SimpleNamespace(translatePath=lambda p:p))
            with patch.dict(sys.modules,fake),patch.object(storage,'load',return_value=state),patch.object(storage,'save'),patch.object(providers,'current',return_value='pov'),patch.object(providers,'fallback_notice',return_value=''),patch.object(ui,'_history',return_value=dict(keys=[])),patch.object(ui,'_load_catalog',return_value=ui._CANCELLED):
                ui.run()
        self.assertEqual(len(profile_rows),8);self.assertNotIn('הוסף צופה',profile_rows)
        self.assertIn('שלוש הצעות',menus[0][0].label2)
        self.assertIn('ללא מגבלת זמן',menus[0][2].label)
        self.assertFalse(notices)

    def test_new_like_fetches_its_recommendations_before_old_likes(self):
        import types
        old,new,found=item(1),item(2),item(3)
        state=engine.initial_state();state['catalog']=[old,new]
        state=engine.feedback(state,'household',old,'like')
        dialog=types.SimpleNamespace(select=lambda title,labels:labels.index('אהבתי את הכותר הזה'),ok=lambda *a:None,notification=lambda *a,**k:None)
        calls=[]
        def fetch(xbmc,gui,folder,anchors,provider,**kwargs):
            self.assertEqual(kwargs['planned']['queries'][0]['anchor']['key'],new['key'])
            calls.append([a['key'] for a in anchors]);return [found]
        with patch.object(ui,'_load_catalog',side_effect=fetch),patch.object(providers,'current',return_value='pov'):
            changed,playing=ui._act_and_refresh(dialog,None,None,new,[],state,'unused')
        self.assertFalse(playing)
        self.assertEqual(calls,[[new['key'],old['key']]])
        self.assertIn(found['key'],[x['key'] for x in changed['catalog']])
        self.assertNotIn('anchor',changed['session'])
        with patch.object(ui,'_load_catalog',side_effect=AssertionError('Repeated like fetched again')):
            ui._act_and_refresh(dialog,None,None,new,[],changed,'unused')

    def test_visible_label_disambiguates_year_and_media_type(self):
        import types
        class LI:
            def __init__(self,**kwargs):self.label=kwargs['label']
            def setArt(self,*a):pass
            def setInfo(self,*a):pass
        movie=item();movie['year']=1999
        label=ui._item(types.SimpleNamespace(ListItem=LI),movie).label
        self.assertIn('1999',label);self.assertIn('סרט',label)
        movie['kind']='tvshow'
        self.assertIn('סדרה',ui._item(types.SimpleNamespace(ListItem=LI),movie).label)

    def test_empty_recovery_preserves_preferences_and_restores_candidates(self):
        import types
        state=engine.initial_state();state['catalog']=[item()]
        state['session'].update(kind='tvshow',max_runtime=1200)
        saved=[];notices=[];steps=iter(['פתח מחדש',-1])
        class ListItem:
            def __init__(self,label='',**kwargs):self.label=label
            def setArt(self,*args):pass
            def setInfo(self,*args):pass
        class Dialog:
            def select(self,title,rows,**kwargs):
                choice=next(steps)
                if isinstance(choice,str):return next(i for i,row in enumerate(rows) if choice in (row if isinstance(row,str) else row.label))
                return choice
            def ok(self,*args):notices.append(args)
        class Monitor:
            def abortRequested(self):return False
        with tempfile.TemporaryDirectory() as folder:
            class Addon:
                def __init__(self,*args):pass
                def getAddonInfo(self,*args):return folder
            def no_play(*args):raise AssertionError('Unexpected playback')
            fake=dict(xbmc=types.SimpleNamespace(Monitor=Monitor,executebuiltin=no_play),
                      xbmcaddon=types.SimpleNamespace(Addon=Addon),
                      xbmcgui=types.SimpleNamespace(Dialog=Dialog,ListItem=ListItem),
                      xbmcvfs=types.SimpleNamespace(translatePath=lambda path:path))
            with patch.dict(sys.modules,fake), patch.object(storage,'load',return_value=copy.deepcopy(state)), patch.object(storage,'save',side_effect=lambda path,value:saved.append(copy.deepcopy(value))), patch.object(providers,'current',return_value='pov'), patch.object(providers,'fallback_notice',return_value=''), patch.object(ui,'_history',return_value=dict(keys=[])):
                ui.run()
        self.assertNotIn('kind',saved[-1]['session'])
        self.assertNotIn('max_runtime',saved[-1]['session'])
        self.assertEqual(saved[-1]['profiles'],state['profiles'])
        self.assertEqual(len(engine.rank(saved[-1]['catalog'],[saved[-1]['profiles']['household']],saved[-1]['session'])),1)

    def test_run_tv_then_time_switches_to_movies_and_clears_shorter_cap(self):
        import types
        state=engine.initial_state();state['catalog']=[item()]
        state['session'].update(kind='tvshow',max_runtime=1200)
        saved=[];notices=[];steps=iter(['מה מתאים',0,3,-1])
        class ListItem:
            def __init__(self,label='',**kwargs):self.label=label
            def setArt(self,*args):pass
            def setInfo(self,*args):pass
        class Dialog:
            def select(self,title,rows,**kwargs):
                choice=next(steps)
                if isinstance(choice,str):return next(i for i,row in enumerate(rows) if choice in (row if isinstance(row,str) else row.label))
                return choice
            def ok(self,*args):notices.append(args)
        class Monitor:
            def abortRequested(self):return False
        with tempfile.TemporaryDirectory() as folder:
            class Addon:
                def __init__(self,*args):pass
                def getAddonInfo(self,*args):return folder
            def no_play(*args):raise AssertionError('Unexpected playback')
            fake=dict(xbmc=types.SimpleNamespace(Monitor=Monitor,executebuiltin=no_play),
                      xbmcaddon=types.SimpleNamespace(Addon=Addon),
                      xbmcgui=types.SimpleNamespace(Dialog=Dialog,ListItem=ListItem),
                      xbmcvfs=types.SimpleNamespace(translatePath=lambda path:path))
            with patch.dict(sys.modules,fake), patch.object(storage,'load',return_value=copy.deepcopy(state)), patch.object(storage,'save',side_effect=lambda path,value:saved.append(copy.deepcopy(value))), patch.object(providers,'current',return_value='pov'), patch.object(providers,'fallback_notice',return_value=''), patch.object(ui,'_history',return_value=dict(keys=[])):
                ui.run()
        self.assertEqual(saved[-1]['session']['kind'],'movie')
        self.assertEqual(saved[-1]['session']['minutes'],90)
        self.assertNotIn('max_runtime',saved[-1]['session'])
        self.assertTrue(notices)
        self.assertEqual(len(engine.rank(saved[-1]['catalog'],[saved[-1]['profiles']['household']],saved[-1]['session'])),1)

    def test_run_search_like_refresh_undo_preserves_refreshed_catalog(self):
        import types
        state=engine.initial_state();found=item(77);refreshed=item(88);refresh_calls=[]
        saved=[];notices=[];steps=iter(['היכרות —',0,'Query',0,'אהבתי את','עוד אפשרויות',0,-1])
        class ListItem:
            def __init__(self,label='',**kwargs):self.label=label
            def setArt(self,*args):pass
            def setInfo(self,*args):pass
        class Dialog:
            def input(self,*args):return next(steps)
            def notification(self,*args,**kwargs):notices.append(args)
            def select(self,title,rows,**kwargs):
                choice=next(steps)
                if isinstance(choice,str):return next(i for i,row in enumerate(rows) if choice in (row if isinstance(row,str) else row.label))
                return choice
            def ok(self,*args):notices.append(args)
        class Monitor:
            def abortRequested(self):return False
        with tempfile.TemporaryDirectory() as folder:
            class Addon:
                def __init__(self,*args):pass
                def getAddonInfo(self,*args):return folder
            def no_play(*args):raise AssertionError('Unexpected playback')
            fake=dict(xbmc=types.SimpleNamespace(Monitor=Monitor,executebuiltin=no_play),
                      xbmcaddon=types.SimpleNamespace(Addon=Addon),
                      xbmcgui=types.SimpleNamespace(Dialog=Dialog,ListItem=ListItem),
                      xbmcvfs=types.SimpleNamespace(translatePath=lambda path:path))
            def refresh(value,*args):
                refresh_calls.append(args[-2]);value['catalog']=[refreshed];return value
            with patch.object(ui,'_load_catalog',return_value=[found]), patch.object(ui,'_refresh',side_effect=refresh), patch.dict(sys.modules,fake), patch.object(storage,'load',return_value=copy.deepcopy(state)), patch.object(storage,'save',side_effect=lambda path,value:saved.append(copy.deepcopy(value))), patch.object(providers,'current',return_value='pov'), patch.object(providers,'fallback_notice',return_value=''), patch.object(ui,'_history',return_value=dict(keys=[])):
                ui.run()
        self.assertEqual(saved[-1]['profiles'],state['profiles'])
        self.assertEqual(saved[-1]['catalog'],[refreshed])
        self.assertEqual(refresh_calls,['pov'])
        self.assertTrue(any(value['profiles']['household']['feedback'].get('movie:77',{}).get('value')==1 for value in saved))

    def test_refinement_refreshes_shared_action_path(self):
        state=engine.initial_state()
        changed=engine.refine(state,item(),'similar')
        with patch.object(ui,'_actions',return_value=(changed,False)), patch.object(ui,'_refresh',return_value=changed) as refresh, patch.object(providers,'current',return_value='umbrella'):
            result,playing=ui._act_and_refresh(None,None,None,item(),[],state,'folder')
            refresh.assert_called_once_with(changed,None,None,'folder','umbrella',None)
            self.assertFalse(playing)

    def test_clear_feedback_restores_eligibility_without_erasing_seen(self):
        state=engine.feedback(engine.initial_state(),'household',item(),'dislike')
        self.assertFalse(engine.rank([item()],[state['profiles']['household']],state['session']))
        changed=engine.feedback(state,'household',item(),'clear_feedback')
        self.assertTrue(engine.rank([item()],[changed['profiles']['household']],changed['session']))
        self.assertIn(item()['key'],state['profiles']['household']['feedback'])
        changed=engine.feedback(changed,'household',item(),'seen')
        changed=engine.feedback(changed,'household',item(),'clear_feedback')
        self.assertFalse(engine.rank([item()],[changed['profiles']['household']],changed['session']))

    def test_unsave_and_unseen_do_not_edit_other_viewers(self):
        state=engine.initial_state();state['profiles']['other']=copy.deepcopy(state['profiles']['household'])
        for viewer in state['profiles']:
            for action in ('save','seen'):state=engine.feedback(state,viewer,item(),action)
        for action in ('unsave','unseen'):state=engine.feedback(state,'household',item(),action)
        self.assertEqual(state['profiles']['household']['saved'],[])
        self.assertEqual(state['profiles']['household']['seen'],[])
        self.assertEqual(state['profiles']['other']['saved'],['movie:1'])
        self.assertEqual(state['profiles']['other']['seen'],['movie:1'])

    def test_undo_restores_decisions_not_provider_catalog(self):
        state=engine.initial_state();snap=engine.checkpoint(state)
        changed=engine.feedback(state,'household',item(),'like')
        changed['catalog']=[item(2)];changed['catalog_fetched']=123
        restored=engine.restore_checkpoint(changed,snap)
        self.assertEqual(restored['profiles'],state['profiles'])
        self.assertEqual(restored['catalog'],changed['catalog'])
        self.assertEqual(restored['catalog_fetched'],123)
        restored['profiles']['household']['name']='new'
        self.assertNotEqual(snap['profiles']['household']['name'],'new')

    def test_format_filter_preserves_seen_and_time_boundaries(self):
        tv=item(2);tv.update(kind='tvshow',key='tvshow:2')
        state=engine.initial_state();profiles=[state['profiles']['household']]
        self.assertEqual([r['item']['key'] for r in engine.rank([item(),tv],profiles,dict(kind='movie'))],['movie:1'])
        self.assertEqual([r['item']['key'] for r in engine.rank([item(),tv],profiles,dict(kind='tvshow'))],['tvshow:2'])
        self.assertFalse(engine.rank([tv],profiles,dict(kind='tvshow',minutes=90)))
        self.assertFalse(engine.rank([tv],profiles,dict(kind='tvshow'),['tvshow:2']))
        state['session']['kind']='invalid'
        with self.assertRaises(storage.StateError):storage.validate(state)

    def test_remove_saved_action_uses_regular_select(self):
        state=engine.feedback(engine.initial_state(),'household',item(),'save')
        class D:
            def __init__(self):self.choices=iter([9,0])
            def select(self,*a):return next(self.choices)
            def notification(self,*a,**kw):pass
        class X:
            def executebuiltin(self,*a):raise AssertionError('Unexpected playback')
        changed,playing=ui._actions(D(),X(),None,item(),[],state)
        self.assertFalse(playing);self.assertEqual(changed['profiles']['household']['saved'],[])

    def test_trailer_is_third_and_rechecks_current_provider(self):
        import types
        calls=[]
        class D:
            def select(self,title,labels):
                self.asserted=labels
                return 2
        dialog=D()
        with patch.object(providers,'current',side_effect=['pov','umbrella']):
            changed,playing=ui._actions(dialog,types.SimpleNamespace(executebuiltin=calls.append),None,item(),[],engine.initial_state())
        self.assertIn('טריילר',dialog.asserted[2])
        self.assertTrue(playing)
        self.assertEqual(len(calls),1)
        self.assertIn('plugin.video.umbrella',calls[0])
        self.assertIn('play_Trailer_Select',calls[0])
        self.assertNotIn('play_Item',calls[0])

    def test_reordered_feedback_changes_correct_state_and_confirms_viewer(self):
        import types
        for label,action in [('שמור לערב אחר','save'),('אהבתי את הכותר הזה','like'),('לא מתאים לטעם שלי','dislike'),('כבר ראיתי','seen'),('לא הערב — הצעה אחרת','not_tonight')]:
            with self.subTest(action=action):
                notices=[];state=engine.initial_state()
                state['profiles']['household']['name']='נועה'
                dialog=types.SimpleNamespace(select=lambda title,labels:labels.index(label),notification=lambda *a,**kw:notices.append((a,kw)))
                def no_play(*a):raise AssertionError('Feedback triggered playback')
                changed,playing=ui._actions(dialog,types.SimpleNamespace(executebuiltin=no_play),None,item(),[],state)
                self.assertFalse(playing)
                self.assertEqual(changed,engine.feedback(state,'household',item(),action))
                self.assertEqual(len(notices),1)
                self.assertEqual(notices[0][1],dict(time=2500,sound=False))
                if action!='not_tonight':self.assertIn('נועה',notices[0][0][1])

    def test_cancel_before_feedback_has_no_notice_or_mutation(self):
        import types
        state=engine.initial_state()
        def unexpected(*a,**kw):raise AssertionError('Cancel caused side effect')
        dialog=types.SimpleNamespace(select=lambda *a:-1,notification=unexpected)
        changed,playing=ui._actions(dialog,types.SimpleNamespace(executebuiltin=unexpected),None,item(),[],state)
        self.assertIs(changed,state);self.assertFalse(playing)

    def test_group_save_acknowledges_only_selected_viewer(self):
        import types
        state=engine.initial_state();state['profiles']['other']=copy.deepcopy(state['profiles']['household'])
        state['profiles']['other']['name']='דנה';state['viewers'].append('other')
        notices=[]
        def select(title,labels):return 1 if title=='למי לשמור את המשוב?' else labels.index('שמור לערב אחר')
        dialog=types.SimpleNamespace(select=select,notification=lambda *a,**kw:notices.append(a))
        changed,playing=ui._actions(dialog,None,None,item(),[],state)
        self.assertFalse(playing)
        self.assertEqual(changed['profiles']['household']['saved'],[])
        self.assertEqual(changed['profiles']['other']['saved'],['movie:1'])
        self.assertIn('דנה',notices[0][1]);self.assertNotIn('הבית',notices[0][1])

    def test_search_term_is_encoded_and_provider_native(self):
        query='שם & action=play_Item / "hello"'
        for provider,kind,action,parameter in [('pov','movie','tmdb_movies_search','query'),('pov','tvshow','tmdb_tv_search','query'),('umbrella','movie','movieSearchterm','name'),('umbrella','tvshow','tvSearchterm','name')]:
            parsed=urlparse(providers.search_route(provider,kind,query));params=parse_qs(parsed.query)
            self.assertEqual(parsed.netloc,'plugin.video.'+provider)
            self.assertEqual(params['action'],[action]);self.assertEqual(params[parameter],[query])
        for query in ('',None,'x'*201):
            with self.assertRaises(ValueError):providers.search_route('pov','movie',query)

    def test_search_results_do_not_claim_recommendation_provenance(self):
        calls=[]
        def rpc(raw):
            calls.append(json.loads(raw));return json.dumps(dict(result=dict(files=[dict(file=engine.provider_route('movie',1),title='Found')])) )
        found=catalog.fetch(rpc,query='Found')
        self.assertNotIn('recommended_from',found[0])
        self.assertIn('tmdb_movies_search',calls[0]['params']['directory'])
        with self.assertRaises(ValueError):catalog.fetch(rpc,anchor=item(),query='Found')

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

    def test_umbrella_season_consumer_keeps_rows_with_partial_catalog_art(self):
        # Consumer-shaped excerpt of Umbrella 6.7.87 Seasons.tmdb_list:
        # a missing mandatory artwork field raises inside the per-season try
        # and causes that season to be discarded, rather than surfacing an error.
        def consume(raw):
            art=json.loads(raw);rows=[]
            for season in (1,2):
                try:
                    values=dict(season=season)
                    if art:
                        for name in ('fanart','icon','thumb','banner','clearart','tvshow.poster'):
                            values[name]=art[name]
                    rows.append(values)
                except KeyError:pass
            return rows
        self.assertEqual(consume(json.dumps(dict(poster='poster'))),[])
        for supplied in ({},{'poster':'poster'},{'fanart':'fanart'},{'poster':'poster','fanart':'fanart','thumb':'thumb'}):
            with self.subTest(art=supplied):
                x=item();x.update(kind='tvshow',key='tvshow:1',art=supplied)
                raw=parse_qs(urlparse(providers.playback_route('umbrella',x)).query)['art'][0]
                rows=consume(raw)
                self.assertEqual([r['season'] for r in rows],[1,2])
                for key,value in supplied.items():self.assertEqual(json.loads(raw)[key],value)

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
        self.assertIn('name="הערב שלי"',added);self.assertNotIn('התנסות',added)
        self.assertIn('thumb="'+entrypoints.ICON+'"',added)
        deleted=added.replace('  <favourite name="הערב שלי" thumb="'+entrypoints.ICON+'">'+entrypoints.ACTION+'</favourite>\n','')
        self.assertEqual(deleted,entrypoints.insert(deleted))
        self.assertEqual(entrypoints.insert('<broken'),'<broken')
        self.assertIn(entrypoints.ACTION,entrypoints.insert('<favourites />'))

    def test_home_renames_only_our_exact_old_generated_entry(self):
        old='<favourites>\n  <favourite name="הערב שלי — התנסות" thumb="special://home/addons/service.subtitles.kodipovilai/icon.png">'+entrypoints.ACTION+'</favourite>\n'+entrypoints.MARKER+'\n</favourites>'
        changed=entrypoints.insert(old)
        self.assertIn('name="הערב שלי"',changed);self.assertNotIn('— התנסות',changed)
        self.assertIn('thumb="'+entrypoints.ICON+'"',changed)

    def test_home_upgrades_generated_icon_but_keeps_custom_thumb(self):
        current='<favourites>\n  <favourite name="הערב שלי" thumb="'+entrypoints.LEGACY_ICON+'">'+entrypoints.ACTION+'</favourite>\n'+entrypoints.MARKER+'\n</favourites>'
        self.assertIn('thumb="'+entrypoints.ICON+'"',entrypoints.insert(current))
        custom=current.replace(entrypoints.LEGACY_ICON,'special://profile/my-art.png')
        self.assertEqual(custom,entrypoints.insert(custom))

    def test_standalone_excludes_feature(self):
        spec=importlib.util.spec_from_file_location('pack',ROOT/'tools/build_ai_subtitles_packages.py');pack=importlib.util.module_from_spec(spec);spec.loader.exec_module(pack)
        self.assertFalse(pack.include_standalone(Path('resources/lib/tonight/ui.py')))
        default=(ROOT/'addons/service.subtitles.kodipovilai/default.py').read_text(encoding='utf-8')
        slim=pack.slim_default_text(default);self.assertNotIn('resources.lib.tonight',slim);compile(slim,'slim','exec')


if __name__=='__main__':unittest.main()
