"""Independent behavioral checks for weak household watched recommendation seeds."""
import copy
import os
import sys
from pathlib import Path
import unittest
import types
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'addons/service.subtitles.kodipovilai'))
from resources.lib.tonight import engine,ui

def item(n, recommended=(), provider='pov', kind='movie', rating=8):
    return dict(key=kind+':'+str(n),kind=kind,tmdb=str(n),title='Title '+str(n),
                provider=provider,genres=['Drama'],runtime=5400,rating=rating,
                recommended_from=list(recommended))

class HistoryPersonalization(unittest.TestCase):
    def test_seed_balancing_dedup_bounds_and_no_feedback_write(self):
        state=engine.initial_state();before=copy.deepcopy(state)
        seeds=['movie:3','movie:2','tvshow:9','movie:2','invalid','movie:0']
        result=engine.history_anchors(state,seeds,limit=2)
        self.assertEqual(len(result),2)
        self.assertEqual({a['kind'] for a in result},{'movie','tvshow'})
        self.assertEqual(len({a['key'] for a in result}),2)
        self.assertTrue(all(set(a)=={'key','kind','tmdb'} for a in result))
        self.assertEqual(result,engine.history_anchors(state,seeds,limit=2))
        self.assertEqual(state,before)
        self.assertEqual(engine.history_anchors(state,seeds,limit=0),[])

    def test_named_only_does_not_inherit_shared_history(self):
        state=engine.initial_state()
        state['profiles']['alice']=dict(name='Alice',feedback={},seen=[],saved=[])
        state['viewers']=['alice'];before=copy.deepcopy(state)
        self.assertEqual(engine.history_anchors(state,['movie:1','tvshow:2']),[])
        self.assertEqual(state,before)

    def test_any_selected_dislike_excludes_anchor(self):
        state=engine.initial_state()
        state['profiles']['alice']=dict(name='Alice',feedback={'movie:1':dict(value=-1,genres=['Drama'],title='No')},seen=[],saved=[])
        state['viewers']=['household','alice']
        anchors=engine.history_anchors(state,['movie:1','movie:2','tvshow:3'])
        self.assertNotIn('movie:1',[a['key'] for a in anchors])
        self.assertEqual({a['kind'] for a in anchors},{'movie','tvshow'})

    def test_watched_recommendation_is_weak_not_explicit_like(self):
        state=engine.initial_state();profile=state['profiles']['household']
        candidates=[item(1),item(2,['movie:99'])]
        before=copy.deepcopy(profile)
        baseline=engine.rank(candidates,[profile],state['session'])
        boosted=engine.rank(candidates,[profile],state['session'],history_seeds=['movie:99'])
        self.assertEqual(boosted[0]['item']['key'],'movie:2')
        base={r['item']['key']:r['score'] for r in baseline}
        delta=boosted[0]['score']-base['movie:2']
        self.assertGreater(delta,0);self.assertLessEqual(delta,1)
        self.assertEqual(profile,before)
        reasons=' '.join(boosted[0]['reasons'])
        self.assertNotIn('סימנת באהבתי',reasons)
        state=engine.feedback(state,'household',item(99),'like')
        liked=engine.rank(candidates,[state['profiles']['household']],state['session'])
        self.assertGreater(liked[0]['score']-base['movie:2'],delta)

    def test_disliked_candidate_remains_excluded_despite_history_and_rating(self):
        state=engine.initial_state();bad=item(2,['movie:99'],rating=10)
        state=engine.feedback(state,'household',bad,'dislike')
        result=engine.rank([item(1,rating=1),bad],[state['profiles']['household']],state['session'],history_seeds=['movie:99'])
        self.assertEqual([r['item']['key'] for r in result],['movie:1'])

    def test_series_seed_is_not_equivalent_to_completed_series(self):
        state=engine.initial_state();series=item(99,kind='tvshow')
        result=engine.rank([series],[state['profiles']['household']],state['session'],watched=[],history_seeds=['tvshow:99'])
        self.assertEqual([r['item']['key'] for r in result],['tvshow:99'])

    def test_unrelated_seed_does_not_boost_by_genre(self):
        state=engine.initial_state();items=[item(1),item(2,['movie:98'])];profiles=[state['profiles']['household']]
        self.assertEqual(engine.rank(items,profiles,state['session']),engine.rank(items,profiles,state['session'],history_seeds=['movie:99']))


    def test_refresh_uses_fresh_active_provider_history_routes(self):
        state=engine.initial_state();dialog=types.SimpleNamespace(ok=lambda *a:None)
        snapshots=[dict(keys=['movie:91'],seed_keys=['movie:91','tvshow:92']),
                   dict(keys=['movie:71'],seed_keys=['movie:71','tvshow:72'])]
        with patch.dict(sys.modules,{'xbmcaddon':types.SimpleNamespace(),'xbmcvfs':types.SimpleNamespace()}), patch.object(ui,'_history',side_effect=snapshots) as hist, patch.object(ui,'_load_catalog',return_value=[]) as load:
            ui._refresh(state,None,None,'unused','pov',dialog)
            ui._refresh(state,None,None,'unused','umbrella',dialog)
        self.assertEqual([c.args[2] for c in hist.call_args_list],['pov','umbrella'])
        self.assertEqual([a['key'] for a in load.call_args_list[0].args[3]],['movie:91','tvshow:92'])
        self.assertEqual([a['key'] for a in load.call_args_list[1].args[3]],['movie:71','tvshow:72'])
        self.assertEqual([c.args[4] for c in load.call_args_list],['pov','umbrella'])

    def test_refresh_unknown_history_still_loads_and_named_profile_has_no_shared_anchors(self):
        dialog=types.SimpleNamespace(ok=lambda *a:None)
        for named in (False,True):
            state=engine.initial_state()
            if named:
                state['profiles']['alice']=dict(name='Alice',feedback={},seen=[],saved=[])
                state['viewers']=['alice']
            snapshot=dict(status='unknown',keys=[]) if not named else dict(keys=['movie:91'],seed_keys=['movie:91'])
            with patch.dict(sys.modules,{'xbmcaddon':types.SimpleNamespace(),'xbmcvfs':types.SimpleNamespace()}), patch.object(ui,'_history',return_value=snapshot), patch.object(ui,'_load_catalog',return_value=[]) as load:
                ui._refresh(state,None,None,'unused','pov',dialog)
                self.assertEqual(load.call_args.args[3],[])

    def test_explicit_preferred_anchor_takes_priority_without_duplicate_requests(self):
        state=engine.initial_state();state['catalog']=[item(91)]
        dialog=types.SimpleNamespace(ok=lambda *a:None)
        with patch.dict(sys.modules,{'xbmcaddon':types.SimpleNamespace(),'xbmcvfs':types.SimpleNamespace()}), patch.object(ui,'_history',return_value=dict(keys=[],seed_keys=['movie:91','tvshow:92'])), patch.object(ui,'_load_catalog',return_value=[]) as load:
            ui._refresh(state,None,None,'unused','pov',dialog,preferred='movie:91')
        self.assertEqual([a['key'] for a in load.call_args.args[3]],['movie:91','tvshow:92'])


    def _aggregated_snapshot(self, settings, snapshots):
        from resources.lib import addon_presence
        queried=[]
        addon=types.SimpleNamespace(getSetting=lambda k:settings.get(k,''),getAddonInfo=lambda k:'special://pov-profile')
        def read(path):
            name=os.path.basename(path) if path else None
            queried.append((name,path))
            return copy.deepcopy(snapshots.get(name,dict(status='unknown',keys=[])))
        with patch.object(addon_presence,'addon',return_value=addon), patch.object(ui.history,'read_watched',side_effect=read):
            out=ui._history(None,types.SimpleNamespace(translatePath=lambda p:os.path.join('isolated','pov-profile')),'pov')
        return out,queried

    def test_connected_snapshots_seed_union_dedup_without_exclusion_union(self):
        config=dict(watched_indicators='2',mdblist_user='connected',trakt_user='connected')
        snapshots={'mdblcache.db':dict(status='available',keys=['movie:1'],seed_keys=['movie:1','tvshow:2']),
                   'traktcache.db':dict(status='available',keys=['movie:3'],seed_keys=['tvshow:2','movie:3'])}
        out,queries=self._aggregated_snapshot(config,snapshots)
        self.assertEqual(out['keys'],['movie:1'])
        self.assertEqual(out['seed_keys'],['movie:1','tvshow:2','movie:3'])
        self.assertEqual(out['signal_sources'],['MDBList','Trakt'])
        self.assertEqual([n for n,path in queries],['mdblcache.db','traktcache.db'])
        self.assertTrue(all(path==os.path.join('isolated','pov-profile',n) for n,path in queries))

    def test_disconnected_accounts_never_read_their_snapshots(self):
        config=dict(watched_indicators='0',mdblist_user='',trakt_user='')
        out,queries=self._aggregated_snapshot(config,{'watched.db':dict(status='available',keys=['movie:8'])})
        self.assertEqual([n for n,path in queries],['watched.db'])
        self.assertEqual(out['seed_keys'],['movie:8'])
        self.assertEqual(out['signal_sources'],['POV'])

    def test_missing_selected_snapshot_keeps_other_connected_seed_without_false_watched(self):
        config=dict(watched_indicators='2',mdblist_user='connected',trakt_user='connected')
        out,queries=self._aggregated_snapshot(config,{'traktcache.db':dict(status='available',keys=['movie:7'],seed_keys=['movie:7','tvshow:9'])})
        self.assertEqual(out['status'],'unknown')
        self.assertEqual(out['keys'],[])
        self.assertEqual(out['seed_keys'],['movie:7','tvshow:9'])
        self.assertEqual(out['signal_sources'],['Trakt'])

    def test_selected_trakt_order_precedes_connected_mdblist(self):
        config=dict(watched_indicators='1',trakt_user='connected',mdblist_user='connected')
        out,queries=self._aggregated_snapshot(config,{'traktcache.db':dict(status='available',keys=['movie:7']),
                                                     'mdblcache.db':dict(status='available',keys=['movie:2'])})
        self.assertEqual(out['keys'],['movie:7'])
        self.assertEqual(out['seed_keys'],['movie:7','movie:2'])
        self.assertEqual([n for n,path in queries],['traktcache.db','mdblcache.db'])

    def test_nullable_snapshot_strength_is_kept_as_one_safe_view(self):
        config=dict(watched_indicators='2',mdblist_user='connected',trakt_user='connected')
        snapshots={
            'mdblcache.db':dict(status='available',keys=['movie:1'],
                seed_keys=['movie:1','tvshow:2'],seed_strengths={'movie:1':None,'tvshow:2':None}),
            'traktcache.db':dict(status='available',keys=['movie:3'],
                seed_keys=['tvshow:2','movie:3'],seed_strengths={'tvshow:2':7,'movie:3':'bad'}),
        }
        out,_=self._aggregated_snapshot(config,snapshots)
        self.assertEqual(out['seed_strengths'],{'movie:1':1,'tvshow:2':7,'movie:3':1})

if __name__=='__main__':unittest.main()
