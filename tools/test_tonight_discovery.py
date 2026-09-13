"""Discovery rotates evidence while retaining active-provider partial results."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]/'addons/service.subtitles.kodipovilai/resources/lib/tonight'
spec=importlib.util.spec_from_file_location('tonight_discovery_test',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
pkg=importlib.util.module_from_spec(spec);sys.modules[spec.name]=pkg;spec.loader.exec_module(pkg)
from tonight_discovery_test import discovery,catalog,engine
class Discovery(unittest.TestCase):
    def state(self):
        state=engine.initial_state()
        for i in range(1,5):state['profiles']['household']['feedback']['movie:'+str(i)]={'value':1}
        return state
    def test_initial_popular_then_rotated_anchors_and_no_input_mutation(self):
        state=self.state();seeds=['tvshow:'+str(i) for i in range(10,16)]
        p=discovery.plan(state,seeds,'pov')
        self.assertEqual(len(p['anchors']),8);self.assertEqual(len(p['queries']),4)
        self.assertEqual([q['kind'] for q in p['queries'][2:]],['movie','tvshow'])
        self.assertNotIn('discovery',state)
        state['discovery']={'pov':discovery.advance(p,[0,1,2,3])}
        q=discovery.plan(state,seeds,'pov');self.assertFalse(q['initial'])
        self.assertTrue(all(x['anchor'] for x in q['queries']))
        self.assertNotEqual(p['queries'][0]['anchor'],q['queries'][0]['anchor'])
        self.assertTrue(discovery.plan(state,seeds,'umbrella')['initial'])
    def test_dislikes_and_private_profiles_exclude_household_history(self):
        state=self.state();state['profiles']['household']['feedback']['tvshow:10']={'value':-1}
        p=discovery.plan(state,['tvshow:10','tvshow:11'],'pov');self.assertNotIn('tvshow:10',p['anchors'])
        state['profiles']['person']={'feedback':{}};state['viewers']=['person']
        self.assertEqual(discovery.plan(state,['tvshow:11'],'pov')['anchors'],[])
    def test_preferred_like_is_first_even_if_tv(self):
        p=discovery.plan(self.state(),['tvshow:11'],'pov',preferred='tvshow:99')
        self.assertEqual(p['queries'][0]['anchor']['key'],'tvshow:99')
    def test_partial_cancel_preserves_first_result_and_provider_scope(self):
        planned=discovery.plan(self.state(),[],'pov');calls=[];snapshots=[]
        def fetch(execute,kind,anchor,provider):
            calls.append(kind)
            return [{'key':'movie:99','provider':'pov','recommended_from':[anchor['key']] if anchor else []}]
        existing=[{'key':'movie:12','provider':'umbrella'},{'key':'movie:13','provider':'pov'}]
        with patch.object(catalog,'fetch',fetch):
            out=catalog.collect(None,planned,existing,cancelled=lambda:len(calls)>=2,progress=snapshots.append)
        self.assertEqual(len(calls),2);self.assertEqual(out['completed'],1);self.assertTrue(out['cancelled'])
        self.assertEqual({x['key'] for x in out['items']},{'movie:99','movie:13'})
        self.assertEqual(len(snapshots),1)
    def test_deadline_drops_late_result_and_keeps_prior_partial(self):
        planned=discovery.plan(self.state(),[],'pov');now=[0];calls=[]
        def fetch(*args):
            calls.append(1);now[0]+=11
            return [{'key':'movie:'+str(len(calls)),'provider':'pov'}]
        with patch.object(catalog,'fetch',fetch):out=catalog.collect(None,planned,clock=lambda:now[0])
        self.assertTrue(out['timed_out']);self.assertEqual(out['completed'],1);self.assertEqual(len(calls),2)
        self.assertEqual([x['key'] for x in out['items']],['movie:1'])
    def test_four_query_cap_and_errors_keep_cache(self):
        planned=discovery.plan(self.state(),[],'pov');calls=[]
        def fetch(*args):calls.append(1);raise ValueError('InvalidParams')
        existing=[{'key':'movie:13','provider':'pov'}]
        with patch.object(catalog,'fetch',fetch):out=catalog.collect(None,planned,existing)
        self.assertEqual(len(calls),4);self.assertEqual(out['items'],existing);self.assertEqual(out['completed'],0)
    def test_same_provider_merge_preserves_all_anchor_provenance(self):
        planned=discovery.plan(self.state(),[],'pov')
        def fetch(execute,kind,anchor,provider):return [{'key':'movie:99','provider':'pov','recommended_from':[anchor['key']] if anchor else []}]
        with patch.object(catalog,'fetch',fetch):out=catalog.collect(None,planned)
        self.assertEqual(out['completed'],4);self.assertEqual(out['items'][0]['recommended_from'],['movie:1','movie:2'])
if __name__=='__main__':unittest.main()
