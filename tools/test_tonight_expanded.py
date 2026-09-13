"""Expanded Tonight integration: staged UI, persisted cursors and honest taste."""
import copy
from pathlib import Path
import queue
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'addons/service.subtitles.kodipovilai'))
from resources.lib.tonight import ui,engine,catalog,discovery,storage,taste,providers

def item(n,genres=('Mystery',),director=None):
    row=dict(file='plugin://plugin.video.pov/?mode=play_media&mediatype=movie&tmdb_id='+str(n),title='Synthetic '+str(n),genre=list(genres),runtime=5400,rating=8)
    if director:row['director']=[director]
    return engine.normalize(row)

class Expanded(unittest.TestCase):
    def test_joined_provider_genres_work_with_existing_cached_feedback(self):
        state=engine.feedback(engine.initial_state(),'household',item(1,('Comedy / Adventure / Family',)),'like')
        comedy=item(2,('Comedy',));other=item(3,('Drama',))
        ranked=engine.rank([other,comedy],[state['profiles']['household']],state['session'])
        self.assertEqual(ranked[0]['item']['key'],comedy['key'])
        refined=engine.refine(state,other,'lighter')
        self.assertGreater(taste.refinement(item(4,('Comedy / Family',)),refined['session'])[0],0)
        self.assertLess(taste.refinement(item(5,('Thriller / Horror',)),refined['session'])[0],0)

    def test_actual_refinement_menu_dispatch_and_switching(self):
        candidate=item(1,director='Known Creator')
        for index,mode in enumerate(('shorter','similar','different','lighter','less_familiar')):
            state=engine.initial_state();before=copy.deepcopy(state)
            selections=iter((4,index))
            dialog=types.SimpleNamespace(select=lambda *args:next(selections))
            with patch.object(providers,'current',return_value='pov'):
                changed,playing=ui._actions(dialog,None,None,candidate,[],state)
            self.assertFalse(playing);self.assertEqual(state,before)
            self.assertIn(candidate['key'],changed['session']['excluded'])
            storage.validate(changed)
            if mode in ('lighter','less_familiar'):
                self.assertEqual(changed['session']['discovery_mode'],mode)
                if mode=='less_familiar':
                    self.assertEqual(changed['session']['avoid_creators'],['Known Creator'])
                switched=engine.refine(changed,candidate,'similar')
                self.assertNotIn('discovery_mode',switched['session'])
                self.assertNotIn('avoid_creators',switched['session'])
                self.assertEqual(switched['profiles'],before['profiles'])

    def test_actual_ui_timeout_retains_partial_and_signals_worker_stop(self):
        ready=threading.Event();release=threading.Event();done=threading.Event();observed=[]
        partial={'items':[item(9)],'discovery':{'anchors':[],'cursor':0,'popular':['movie']},'completed':1,'errors':0,'timed_out':False,'provider':'pov'}
        def collect(execute,planned,existing,cancelled,progress):
            progress(copy.deepcopy(partial));ready.set();release.wait(2)
            observed.append(cancelled());done.set();return {'items':[item(10)]}
        class Q(queue.Queue):
            def get(self,timeout=None):
                self.assert_ready=ready.wait(2)
                if not self.assert_ready:raise AssertionError('worker did not stage result')
                raise queue.Empty
        closed=[]
        dialog=types.SimpleNamespace(create=lambda *a:None,iscanceled=lambda:False,close=lambda:closed.append(True))
        xbmc=types.SimpleNamespace(executeJSONRPC=lambda p:'{}',Monitor=lambda:types.SimpleNamespace(abortRequested=lambda:False))
        with tempfile.TemporaryDirectory() as root:
            with patch.object(catalog,'collect',collect),patch.object(providers,'current',return_value='pov'),patch.object(ui.queue,'Queue',Q),patch.object(ui.time,'monotonic',side_effect=[0,0,21]):
                result=ui._load_catalog(xbmc,types.SimpleNamespace(DialogProgress=lambda:dialog),root,planned={'provider':'pov'})
            frozen=copy.deepcopy(result);release.set();self.assertTrue(done.wait(2))
            self.assertEqual(result,frozen);self.assertEqual(result['items'],partial['items'])
            self.assertTrue(result['timed_out']);self.assertEqual(observed,[True]);self.assertEqual(closed,[True])
    def test_actual_ui_cancel_does_not_publish_staged_result(self):
        ready=threading.Event();release=threading.Event();done=threading.Event();observed=[]
        def collect(execute,planned,existing,cancelled,progress):
            progress({'items':[item(9)]});ready.set();release.wait(2)
            observed.append(cancelled());done.set();return {'items':[item(10)]}
        dialog=types.SimpleNamespace(create=lambda *a:None,iscanceled=lambda:ready.wait(2),close=lambda:None)
        xbmc=types.SimpleNamespace(executeJSONRPC=lambda p:'{}',Monitor=lambda:types.SimpleNamespace(abortRequested=lambda:False))
        with tempfile.TemporaryDirectory() as root:
            with patch.object(catalog,'collect',collect),patch.object(providers,'current',return_value='pov'):
                result=ui._load_catalog(xbmc,types.SimpleNamespace(DialogProgress=lambda:dialog),root,planned={'provider':'pov'})
                release.set();self.assertTrue(done.wait(2))
            self.assertIs(result,ui._CANCELLED);self.assertEqual(observed,[True])

    def test_cursor_persists_and_invalid_provider_state_rejected(self):
        state=engine.initial_state();planned=discovery.plan(state,['movie:1','tvshow:2'],'pov')
        state['discovery']={'pov':discovery.advance(planned,[0,1,2,3])}
        with tempfile.TemporaryDirectory() as root:
            path=str(Path(root)/'state.json');storage.save(path,state);loaded=storage.load(path)
        self.assertEqual(loaded['discovery'],state['discovery'])
        self.assertFalse(discovery.plan(loaded,['movie:1','tvshow:2'],'pov')['initial'])
        self.assertTrue(discovery.plan(loaded,['movie:1','tvshow:2'],'umbrella')['initial'])
        loaded['discovery']['foreign']={'cursor':0,'anchors':[],'popular':[]}
        with self.assertRaises(storage.StateError):storage.validate(loaded)
    def test_creator_affinity_uses_actual_metadata_not_genre_alone(self):
        liked=item(1,director='Known Creator');match=item(2,director='Known Creator');other=item(3,director='Other Creator')
        state=engine.feedback(engine.initial_state(),'household',liked,'like')
        rows=engine.rank([other,match],[state['profiles']['household']],state['session'])
        self.assertEqual(rows[0]['item']['key'],match['key'])
        self.assertTrue(any('Known Creator' in r for r in rows[0]['reasons']))
        self.assertEqual(taste.affinity(item(4),state['profiles']['household']['feedback'])[0],0)
    def test_three_lanes_unique_saved_and_all_hard_filters_retained(self):
        state=engine.initial_state();a,b,c,d=item(1),item(2,('Comedy',)),item(3),item(4)
        state=engine.feedback(state,'household',c,'save');state=engine.feedback(state,'household',d,'dislike')
        rows=engine.choose_three(engine.rank([a,b,c,d],[state['profiles']['household']],state['session']))
        self.assertEqual(len(rows),3);self.assertEqual(len({r['item']['key'] for r in rows}),3)
        self.assertNotIn(d['key'],[r['item']['key'] for r in rows]);self.assertTrue(any(r['lane']=='מהשמורים שלך' for r in rows))
    def test_mood_preference_reversible_without_erasing_taste_or_catalog(self):
        state=engine.feedback(engine.initial_state(),'household',item(1),'like');state['catalog']=[item(2)]
        before=engine.checkpoint(state);state['session']['discovery_mode']='lighter'
        self.assertGreater(taste.refinement(item(3,('Comedy',)),state['session'])[0],0)
        restored=engine.restore_checkpoint(state,before)
        self.assertEqual(restored['profiles'],before['profiles']);self.assertNotIn('discovery_mode',restored['session'])
        self.assertEqual(restored['catalog'],state['catalog'])
    def test_active_provider_playback_uses_trusted_identity(self):
        original=item(1)
        route=providers.playback_route('umbrella',original)
        self.assertTrue(route.startswith('plugin://plugin.video.umbrella/'))
        self.assertNotIn('plugin.video.pov',route)
    def test_quick_pair_private_history_dedup_and_immutability(self):
        state=engine.initial_state();a,b,c=item(1),item(2),item(3)
        duplicate=dict(a,provider='umbrella');state['catalog']=[a,duplicate,b,c]
        before=copy.deepcopy(state)
        self.assertEqual([x['key'] for x in engine.quick_pair(state,'household',[a['key'],b['key']])],[a['key'],b['key']])
        self.assertEqual(state,before)
        state['profiles']['person']={'name':'Person','feedback':{},'seen':[c['key']],'saved':[]}
        self.assertEqual([x['key'] for x in engine.quick_pair(state,'person',[a['key'],b['key']])],[c['key']])
        state=engine.feedback(state,'household',a,'like')
        self.assertEqual([x['key'] for x in engine.quick_pair(state,'household',[a['key'],b['key']])],[b['key']])

    def test_actual_quick_pair_ui_never_dislikes_unselected_loser(self):
        import ast
        tree=ast.parse(Path(ui.__file__).read_text(encoding='utf-8'))
        branch=next(n for n in ast.walk(tree) if isinstance(n,ast.If)
                    and ast.unparse(n.test)=='action == 11')
        for choice in (0,1,2,3,4,-1):
            state=engine.initial_state();a,b=item(1),item(2);state['catalog']=[a,b]
            dialog=types.SimpleNamespace(select=lambda *args:choice,ok=lambda *a:None)
            env=dict(state=state,dialog=dialog,engine=engine,seeds=[a['key'],b['key']],
                     _viewer=lambda *a:'household',TITLE='test',xbmc=None,xbmcgui=None,folder='unused',
                     providers=types.SimpleNamespace(current=lambda:'pov'),_refresh=lambda state,*args:state)
            exec(compile(ast.Module(body=branch.body,type_ignores=[]),'quickpair-ui','exec'),env)
            feedback=env['state']['profiles']['household']['feedback']
            expected=({a['key']:1} if choice==0 else {b['key']:1} if choice==1 else
                      {a['key']:1,b['key']:1} if choice==2 else
                      {a['key']:-1,b['key']:-1} if choice==3 else {})
            self.assertEqual({k:v['value'] for k,v in feedback.items()},expected)

    def test_all_saved_candidates_still_make_unique_lanes(self):
        state=engine.initial_state();items=[item(i) for i in (1,2,3)]
        for candidate in items:state=engine.feedback(state,'household',candidate,'save')
        rows=engine.choose_three(engine.rank(items,[state['profiles']['household']],state['session']))
        self.assertEqual(len(rows),3);self.assertEqual(len({r['item']['key'] for r in rows}),3)
        self.assertTrue(any(r['lane']=='מהשמורים שלך' for r in rows))

    def test_ui_retained_other_provider_metadata_cannot_enter_ranking(self):
        import ast
        tree=ast.parse(Path(ui.__file__).read_text(encoding='utf-8'))
        assign=next(n for n in ast.walk(tree) if isinstance(n,ast.Assign)
                    and any(isinstance(t,ast.Name) and t.id=='current_catalog' for t in n.targets))
        state=engine.initial_state();state['catalog']=[item(1),dict(item(2),provider='umbrella')]
        env=dict(state=state,provider='pov')
        exec(compile(ast.Module(body=[assign],type_ignores=[]),'provider-ui','exec'),env)
        ranked=engine.rank(env['current_catalog'],[state['profiles']['household']],state['session'])
        self.assertEqual([r['item']['key'] for r in ranked],['movie:1'])
        self.assertEqual(len(state['catalog']),2)

if __name__=='__main__':unittest.main()
