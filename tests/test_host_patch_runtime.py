"""Exercise runtime contracts rather than just searching for injected markers."""
import importlib.util
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / 'plugin.program.kodipovilwizard/resources/libs'
PATCHES = LIBS / 'patches'

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class HostPatchRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.xbmc = types.SimpleNamespace(LOGDEBUG=0, LOGINFO=1, LOGWARNING=2,
                                         LOGERROR=3, log=Mock(),
                                         getInfoLabel=lambda key:'plugin://plugin.video.pov/movies')
        self.vfs = types.SimpleNamespace(translatePath=lambda value:value)
        self.modules = patch.dict(sys.modules, {'xbmc':self.xbmc, 'xbmcvfs':self.vfs,
            'xbmcgui':types.ModuleType('xbmcgui'),
            'xbmcaddon':types.SimpleNamespace(Addon=lambda *a:types.SimpleNamespace(getSetting=lambda key:''))})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def helper(self, name):
        return load('host_test_' + name, PATCHES / (name + '.py'))

    def test_update_watch_retries_failure_before_accepting_signature(self):
        watch = load('watch_test', LIBS / 'host_patch_watch.py')
        props = {}
        window = types.SimpleNamespace(getProperty=lambda key:props.get(key, ''),
            setProperty=lambda key,value:props.__setitem__(key,value),
            clearProperty=lambda key:props.pop(key,None))
        monitor = types.SimpleNamespace(waitForAbort=Mock(side_effect=[False]*6+[True]),
                                        abortRequested=lambda:False)
        old = (('plugin.video.pov',1,1),('plugin.video.umbrella',None,None))
        new = (('plugin.video.pov',2,1),('plugin.video.umbrella',None,None))
        self.xbmc.Monitor=lambda:monitor
        self.xbmc.Player=lambda:types.SimpleNamespace(isPlayingVideo=lambda:False)
        with patch.dict(sys.modules, {'xbmcgui':types.SimpleNamespace(Window=lambda n:window)}), \
             patch.object(watch,'signature',side_effect=[old]+[new]*10), \
             patch.object(watch,'repair_changed',side_effect=[False,True]) as repair, \
             patch.object(watch.time,'monotonic',side_effect=[0,0,20,40,60,80]):
            watch.run()
        self.assertEqual(repair.call_count,2)
        self.assertEqual(props,{})

    def test_profile_watch_unload_never_reads_gui_lock_and_cannot_block_another_profile(self):
        watch = load('watch_unload_test', LIBS / 'host_patch_watch.py')
        props={};state={'aborted':False};queued=[]
        def read(key):
            self.assertFalse(state['aborted'],'GUI getter reached during native interpreter unload')
            return props.get(key,'')
        window=types.SimpleNamespace(getProperty=read,
            setProperty=lambda key,value:props.__setitem__(key,value),
            clearProperty=lambda key:self.fail('Synchronous GUI cleanup'))
        def wait(delay):
            state['aborted']=True
            return True
        self.xbmc.Monitor=lambda:types.SimpleNamespace(waitForAbort=wait,abortRequested=lambda:state['aborted'])
        self.xbmc.executebuiltin=lambda action:queued.append(action)
        with patch.dict(sys.modules,{'xbmcgui':types.SimpleNamespace(Window=lambda n:window)}), \
             patch.object(watch,'signature',return_value=()):
            for profile in ('master','secondary'):
                state['aborted']=False
                self.vfs.translatePath=lambda path:profile if path=='special://profile/' else 'addons'
                watch.run()
        self.assertEqual(len(props),2)  # queued cleanup has not run; neither profile is blocked
        self.assertEqual(len(queued),2)
        self.assertNotEqual(queued[0],queued[1])
        self.assertTrue(all(a.startswith('ClearProperty(kodipovil.host_patch_watch.v2.') for a in queued))

    def test_update_watch_requires_umbrella_ack_and_rejects_timeout(self):
        watch = load('watch_ack_test', LIBS / 'host_patch_watch.py')
        old = (('plugin.video.pov',None,None),('plugin.video.umbrella',1,1))
        new = (('plugin.video.pov',None,None),('plugin.video.umbrella',2,1))
        window=types.SimpleNamespace(getProperty=lambda key:'',clearProperty=Mock())
        self.xbmc.executebuiltin=Mock()
        monitor=types.SimpleNamespace(waitForAbort=lambda delay:False)
        with patch.dict(sys.modules, {'resources.libs.patch_engine':types.SimpleNamespace(PatchEngine=Mock())}), \
             patch.object(watch.os.path,'isfile',return_value=True):
            self.assertFalse(watch.repair_changed('addons',old,new,window,monitor))
            window.getProperty=lambda key:'{"ok":true}'
            self.assertTrue(watch.repair_changed('addons',old,new,window,monitor))
        self.assertEqual(window.clearProperty.call_count,2)

    def test_timeout_keeps_confirmed_hashes_and_marks_only_unknown(self):
        helper = self.helper('pov_debrid_timeout')
        future = types.SimpleNamespace(name='torbox',done=lambda:True,
            exception=lambda:None,result=lambda:('confirmed',))
        manager = types.SimpleNamespace(debrid_torrents=['torbox'],final_sources=[])
        # Actual code accepts a set of Future objects. Use a list with clear
        # so the fixture's SimpleNamespace needn't manufacture hash semantics.
        futures = [future]
        helper.run(manager, futures, [{'hash':'confirmed'},{'hash':'unknown'}])
        self.assertEqual([r['cache_provider'] for r in manager.final_sources],
                         ['torbox','Unchecked torbox'])
        self.assertEqual(futures, [])

    def test_favourite_toggle_once_and_search_does_not_refresh(self):
        utils = types.SimpleNamespace(container_refresh=Mock())
        with patch.dict(sys.modules, {'modules':types.SimpleNamespace(kodi_utils=utils)}):
            helper = self.helper('pov_fav_refresh_manage')
            owner = types.SimpleNamespace(execute_toggle=Mock(return_value=7))
            local = {'self':owner,'choice':'x','action_add':True}
            self.assertEqual(helper.run(local),7)
            owner.execute_toggle.assert_called_once_with('x',True)
            utils.container_refresh.assert_called_once()
            self.xbmc.getInfoLabel = lambda key:'plugin://plugin.video.pov/search'
            utils.container_refresh.reset_mock()
            helper.run(local)
            utils.container_refresh.assert_not_called()

    def test_discover_old_and_new_url_contract_and_query_encoding(self):
        for old in (False, True):
            tmdb = types.ModuleType('indexers.tmdb_api')
            tmdb.base_url='https://api.themoviedb.org'
            tmdb.EXPIRES_4_HOURS=4
            tmdb.get_tmdb=Mock()
            if old:tmdb.requests=object()
            caches = types.SimpleNamespace(cache_object=Mock(return_value={'results':[]}))
            package=types.ModuleType('indexers');package.tmdb_api=tmdb
            with patch.dict(sys.modules, {'indexers':package,'indexers.tmdb_api':tmdb,
                                         'caches.main_cache':caches}):
                helper = self.helper('pov_combined_discover')
                helper.tmdb_search_multi('a & b#c')
                url = caches.cache_object.call_args.args[2]
                self.assertEqual(url.startswith('https://'),old)
                self.assertIn('/3/search/multi?',url)
                self.assertIn('query=a+%26+b%23c',url)

    def test_mdblist_like_and_retry_use_correct_namespace_and_host_contract(self):
        helper = self.helper('pov_mdblist_patch_logic')
        for base in ('https://api.mdblist.com','https://api.mdblist.com/%s'):
            response=types.SimpleNamespace(headers={'Content-Type':'application/json'},
                ok=True,json=lambda:{'ok':True})
            api=types.SimpleNamespace(base_url=base,timeout=10,
                call_mdblist=Mock(return_value={'ok':True}),
                session=types.SimpleNamespace(request=Mock(return_value=response)))
            utils=types.SimpleNamespace(get_setting=lambda key,*a:'fixture')
            with patch.dict(sys.modules, {'indexers.mdblist_api':api,
                                         'modules':types.SimpleNamespace(kodi_utils=utils)}):
                helper._call_mdblist('lists/12/like',method='put')
                expected='/lists/12/like' if '%s' not in base else 'lists/12/like'
                api.call_mdblist.assert_called_once_with(expected,method='put')
                self.assertEqual(helper._retry_call('lists/12/like',None,None,'put'),{'ok':True})
                self.assertEqual(api.session.request.call_args.args[1],
                                 'https://api.mdblist.com/lists/12/like')

    def test_enabled_local_providers_native_precedence_and_disabled_provider(self):
        helper=self.helper('pov_legacy_scrapers')
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw); native=root/'debrids'; legacy=root/'scrapers'
            native.mkdir();legacy.mkdir()
            for folder,name in ((native,'collision'),(legacy,'collision'),
                                (legacy,'fixture'),(legacy,'disabled')):
                (folder/(name+'.py')).write_text('source = object()\n')
            utils=types.SimpleNamespace(translate_path=lambda value:
                str(legacy) if '/scrapers/' in value else str(root),
                get_setting=lambda key:'false' if key=='provider.disabled' else 'true',logger=Mock())
            with patch.dict(sys.modules, {'modules':types.SimpleNamespace(kodi_utils=utils)}):
                settings=helper.enabled_settings(['provider.external'])
                self.assertEqual(settings.count('provider.collision'),1)
                self.assertNotIn('provider.disabled',settings)
                self.assertEqual(helper.enabled_settings(['provider.aiostreams']),['provider.aiostreams'])
                processor=types.SimpleNamespace(source=types.SimpleNamespace(
                    active_internal_scrapers=['collision','fixture'],mediatype='movie'))
                providers=[]
                helper.run(processor,str(native),providers.append,False)
                self.assertEqual([r[2] for r in providers],['fixture'])

    def test_late_badge_cache_updates_without_second_network_lookup(self):
        helper=self.helper('pov_sub_match_v2')
        entry={}
        sm=types.SimpleNamespace(release_names=Mock(return_value=[]),embedded_names=lambda m:[],
            confirmed_releases=lambda m:set(),_media_params=lambda m:m,
            _media_key=lambda m:'fixture',_cache_entry=lambda key:entry,
            label_prefix=lambda name,names,*a:'HEB 95% | ' if names else '')
        owner=types.SimpleNamespace(meta={'tmdb_id':1})
        props={}
        row={'name':'release','size_label':'2 GB'}
        with patch.dict(sys.modules, {'he_sub_match':sm}), \
                patch.object(helper.time,'monotonic',side_effect=[0,2,3]):
            args={'self':owner,'get':row.get,'set_property':props.__setitem__}
            helper.run(args)
            self.assertEqual(props,{})
            entry.update(warm=True,names=['release'])
            helper.run(args)
            self.assertEqual(props['tikiskins.size_label'],'HEB 95% | 2 GB')
            helper.run(args)
            sm.release_names.assert_called_once()

    def test_debrid_client_names_match_real_modules(self):
        helper=self.helper('pov_custom_debrid_toasts')
        services={s['prefix']:s for s in helper.SERVICES}
        self.assertEqual(services['rd']['module'],'realdebrid_api')
        self.assertIn('oc',services)
        api=types.ModuleType('indexers.realdebrid_api')
        with patch.dict(sys.modules, {'indexers.realdebrid_api':api}):
            self.assertIs(helper._import_client(services['rd']),api)

if __name__ == '__main__':
    unittest.main()
