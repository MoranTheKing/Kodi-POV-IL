"""Bound home work while retaining complete native directory/history semantics."""
import builtins
import importlib.util
import json
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PATCHES = ROOT/'plugin.program.kodipovilwizard/resources/libs/patches'


def load(name):
    spec = importlib.util.spec_from_file_location('test_'+name, PATCHES/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WidgetWorkTests(unittest.TestCase):
    def setUp(self):
        self.module = load('pov_widget_budget')
        self.instance = types.SimpleNamespace(
            is_widget=True, widget_hide_watched=False,
            params={'widget_limit':'7'}, list=list(range(20)), items=[])
        self.instance.append = self.instance.items.append
        self.source = self.instance.list
        self.scopes = []

    def worker(self):
        self.scopes.append(tuple(self.instance.list))
        for item in self.instance.list:
            if item not in getattr(self, 'omitted', ()):
                self.instance.append(item)
        return self.instance.items

    def wrap(self, policy=None):
        guard = types.SimpleNamespace(active_policy=lambda:policy)
        with patch.dict(sys.modules, {'profile_age_guard':guard,
                'xbmc':types.SimpleNamespace(getSkinDir=lambda:'skin.povil.nox')}):
            return self.module.wrap_worker(self.instance, self.worker)

    def test_visible_watched_titles_also_avoid_metadata_outside_the_row(self):
        result = self.wrap()()
        self.assertEqual(result,list(range(7)))
        self.assertEqual(self.scopes,[tuple(range(7))])
        self.assertIs(self.instance.list,self.source)

    def test_missing_metadata_or_hidden_watched_titles_backfill_in_native_order(self):
        for hidden in (False, True):
            self.instance.widget_hide_watched=hidden
            self.omitted={0,1,2,3,4,5,6,7,8}
            self.scopes.clear()
            self.assertEqual(self.wrap()(),list(range(9,16)))
            self.assertEqual(len(self.scopes[-1]),20)
            self.assertIs(self.instance.list,self.source)

    def test_short_source_keeps_all_available_results(self):
        self.omitted=set(range(18))
        self.assertEqual(self.wrap()(),[18,19])
        self.assertIs(self.instance.list,self.source)

    def test_directories_and_unlimited_or_invalid_home_rows_keep_native_worker(self):
        self.instance.is_widget=False
        self.assertEqual(self.wrap(),self.worker)
        self.instance.is_widget=True
        for raw in ('','0','-1','all','not-an-int'):
            self.instance.params['widget_limit']=raw
            self.assertEqual(self.wrap(),self.worker)

    def test_child_and_broken_child_policy_retain_full_classification_candidates(self):
        for policy in ({'age':7,'approved':{}},{'blocked':True}):
            self.assertEqual(self.wrap(policy),self.worker)
        with patch.dict(sys.modules,{'profile_age_guard':types.SimpleNamespace(
                active_policy=lambda:(_ for _ in ()).throw(ValueError('broken policy'))),
                'xbmc':types.SimpleNamespace(getSkinDir=lambda:'skin.povil.nox')}):
            self.assertEqual(self.module.wrap_worker(self.instance,self.worker),self.worker)

    def test_native_failure_restores_complete_source(self):
        def failure(): raise RuntimeError('native worker failure')
        with patch.dict(sys.modules, {'profile_age_guard':types.SimpleNamespace(active_policy=lambda:None),
                'xbmc':types.SimpleNamespace(getSkinDir=lambda:'skin.povil.nox')}):
            worker=self.module.wrap_worker(self.instance,failure)
        with self.assertRaises(RuntimeError): worker()
        self.assertIs(self.instance.list,self.source)


class WidgetSortingTests(unittest.TestCase):
    def test_custom_af3_sort_reverse_duplicate_and_unknown_rows_keep_full_candidates(self):
        module=load('pov_widget_budget')
        params={'mode':'build_movie_list','action':'tmdb_movies_popular','widget_limit':'7'}
        row={'path':'plugin://plugin.video.pov/?action=tmdb_movies_popular&mode=build_movie_list&widget_limit=7'}
        with tempfile.TemporaryDirectory() as raw:
            path=Path(raw)/'homewidgets.json'
            with patch.dict(sys.modules,{'xbmc':types.SimpleNamespace(getSkinDir=lambda:'skin.arctic.fuse.3'),
                    'xbmcvfs':types.SimpleNamespace(translatePath=lambda _:str(path))}):
                path.write_text(json.dumps([row]),'utf8')
                self.assertTrue(module._native_order(params))
                for change in ({'widget_sortby':'rating'},{'widget_sortby':'random'},
                               {'widget_sortby':'userpreference'},{'widget_sortorder':True}):
                    path.write_text(json.dumps([dict(row,**change)]),'utf8')
                    self.assertFalse(module._native_order(params))
                path.write_text(json.dumps([row,dict(row,widget_sortby='title')]),'utf8')
                self.assertFalse(module._native_order(params))
                path.write_text('[]','utf8')
                self.assertFalse(module._native_order(params))
                path.write_text('invalid','utf8')
                self.assertFalse(module._native_order(params))
        self.assertFalse(module._native_order(dict(params,sortby='rating')))


class TVHistoryTests(unittest.TestCase):
    def setUp(self):
        self.module=load('pov_watch_history')
        self.rows=[('42','A','2026-10-08',2,3),('99','B','2026-10-07',0,1),
                   ('42','A','2026-10-06',2,2),('42','A','2026-10-05',1,1)]
        self.closed=[];self.calls=[]
        class Cursor:
            def execute(inner,command,args):
                self.calls.append((command,args))
                return inner
            def fetchall(inner): return self.rows
        self.cursor=Cursor()
        self.native={'GET_MOVIE_SHOW':'SELECT %s FROM watched_status WHERE db_type = ? ORDER BY last_played DESC',
            '_database_connect':lambda source: self.calls.append(source) or types.SimpleNamespace(
                close=lambda:self.closed.append(True)),
            'set_PRAGMAS':lambda connection:self.cursor,'MappingProxyType':types.MappingProxyType}

    def test_preserves_complete_group_order_types_specials_and_source(self):
        result=self.module.tv_history(self.native,2)
        self.assertEqual(result,{'42':tuple(row for row in self.rows if row[0]=='42'), '99':(self.rows[1],)})
        self.assertIsInstance(result,types.MappingProxyType)
        self.assertIsInstance(result['42'],tuple)
        self.assertEqual(self.calls[0],2)
        self.assertEqual(self.calls[1][1],('episode',))
        self.assertIn('ORDER BY last_played DESC',self.calls[1][0])
        self.assertEqual(self.closed,[True])
        with self.assertRaises(TypeError): result['42']=()

    def test_next_read_observes_new_episode_and_changed_account_database(self):
        first=self.module.tv_history(self.native,0)
        self.rows.insert(0,('42','A','2026-10-09',2,4))
        second=self.module.tv_history(self.native,1)
        self.assertEqual(len(first['42']),3)
        self.assertEqual(len(second['42']),4)
        self.assertEqual(second['42'][0][4],4)
        self.assertEqual([value for value in self.calls if isinstance(value,int)],[0,1])

    def test_unavailable_database_keeps_empty_native_result(self):
        self.native['_database_connect']=lambda source:(_ for _ in ()).throw(OSError('unavailable'))
        self.assertEqual(self.module.tv_history(self.native,1),{})

    def test_published_hook_delegates_the_native_context(self):
        rules=runpy.run_path(str(PATCHES/'patches_config.py'))['PATCH_CONFIG']
        hook=next(row for row in rules if row['id']=='pov_linear_tv_history')
        stub=types.SimpleNamespace(translatePath=lambda value:str(PATCHES))
        with patch.dict(sys.modules,{'xbmcvfs':stub,'pov_watch_history':self.module}):
            namespace=dict(self.native)
            exec('def get_watched_info_tv(watched_indicators):\n'+hook['hook'],namespace)
            self.assertEqual(namespace['get_watched_info_tv'](0)['42'][0],self.rows[0])


class CandidatePolicyTests(unittest.TestCase):
    def setUp(self):
        self.guard=load('profile_age_guard')
        self.path='adult'
        self.vfs=types.SimpleNamespace(translatePath=lambda _:self.path)
        self.modules=patch.dict(sys.modules, {'xbmcvfs':self.vfs})
        self.modules.start();self.addCleanup(self.modules.stop)

    def test_same_route_uses_work_snapshot_but_another_route_or_profile_reads_again(self):
        route={'mode':'build_movie_list','widget_limit':'7'}
        child={'age':7,'approved':{}}
        with patch.object(self.guard,'active_policy',side_effect=[None,child,child]) as policy:
            self.assertTrue(self.guard.route_allowed(route,'pov'))
            self.assertIsNone(self.guard.work_policy(route))
            self.assertEqual(policy.call_count,1)
            self.assertEqual(self.guard.work_policy(dict(route)),child)
            self.path='child'
            self.assertEqual(self.guard.work_policy(route),child)
            self.assertEqual(policy.call_count,3)

    def test_candidate_snapshot_cannot_authorize_publication_after_policy_changes(self):
        api=types.SimpleNamespace(addDirectoryItem=lambda *a:True,
                                 addDirectoryItems=lambda h,rows,n:rows)
        route={'mode':'build_movie_list','widget_limit':'7'}
        with patch.dict(sys.modules,{'xbmcplugin':api}):
            self.guard.install_directory_guard()
            with patch.object(self.guard,'active_policy',side_effect=[None,{'blocked':True}]):
                self.assertTrue(self.guard.route_allowed(route,'pov'))
                self.assertIsNone(self.guard.work_policy(route))
                self.assertEqual(api.addDirectoryItems(1,[('url',object(),False)],1),[])

    def test_new_invocation_replaces_previous_route_and_child_policy(self):
        first={'mode':'build_movie_list'};second={'mode':'build_movie_list'}
        child={'age':7,'approved':{}}
        with patch.object(self.guard,'active_policy',side_effect=[child,None]) as policy:
            self.assertTrue(self.guard.route_allowed(first,'pov'))
            self.assertEqual(self.guard.work_policy(first),child)
            self.assertTrue(self.guard.route_allowed(second,'pov'))
            self.assertIsNone(self.guard.work_policy(second))
            self.assertEqual(policy.call_count,2)


class CacheImportTests(unittest.TestCase):
    def test_json_paths_do_not_load_literal_parser_and_legacy_literals_still_work(self):
        real_import=builtins.__import__
        def import_without_ast(name,*args,**kwargs):
            if name=='ast':raise AssertionError('JSON path imported literal parser')
            return real_import(name,*args,**kwargs)
        raw=json.dumps({'connected':True,'empty':None,'rows':[1,2]})
        for name,method in (('pov_cache_read','loads'),('pov_visibility_mgr','_loads')):
            with patch('builtins.__import__',side_effect=import_without_ast):
                module=load(name)
                self.assertEqual(getattr(module,method)(raw),json.loads(raw))
            self.assertEqual(getattr(module,method)("{'connected': True, 'empty': None, 'rows': (1, 2)}"),
                             {'connected':True,'empty':None,'rows':(1,2)})


if __name__=='__main__':unittest.main()
