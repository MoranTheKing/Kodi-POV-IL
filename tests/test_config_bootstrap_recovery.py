"""A fresh install can finish its verified config with its download unavailable."""
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch
from test_provisioning_gate import ROOT, _load_function

LIBS = ROOT / 'plugin.program.kodipovilwizard/resources/libs'
spec = importlib.util.spec_from_file_location('bootstrap_config_apply', LIBS/'config_apply.py')
config_apply = importlib.util.module_from_spec(spec); spec.loader.exec_module(config_apply)


class ConfigBootstrapRecoveryTests(unittest.TestCase):
    def test_shipped_pack_is_the_verified_public_config_and_stale_bytes_are_not_used(self):
        cfg = json.loads((ROOT/'manifest.json').read_text('utf8'))['config']
        # This seed is immutable; a future config can safely require a download.
        pack = ROOT/'plugin.program.kodipovilwizard/resources/bootstrap/config.zip'
        self.assertEqual(hashlib.sha256(pack.read_bytes()).hexdigest(),
                         '20f3f23b5571bc48be7313096e144fd01e903b346b050ca9a7a2899a92963f85')
        seed = dict(sha256=hashlib.sha256(pack.read_bytes()).hexdigest(),size=pack.stat().st_size)
        self.assertTrue(config_apply._bundled_config_zip(seed))
        self.assertIsNone(config_apply._bundled_config_zip(dict(seed,sha256='0'*64)))
        self.assertIsNone(config_apply._bundled_config_zip(dict(seed,size=1)))
        self.assertIsNone(config_apply._bundled_config_zip({}))
        with zipfile.ZipFile(pack) as z:
            self.assertIsNone(z.testzip())
            self.assertIn('config_policy.json', z.namelist())

    def test_actual_pack_applies_when_network_is_unavailable(self):
        with tempfile.TemporaryDirectory() as raw:
            home=Path(raw); userdata=home/'userdata'; userdata.mkdir()
            settings={}; cfg=json.loads((ROOT/'manifest.json').read_text('utf8'))['config']
            pack=ROOT/'plugin.program.kodipovilwizard/resources/bootstrap/config.zip'
            cfg=dict(cfg,config_version='seed-test',sha256=hashlib.sha256(pack.read_bytes()).hexdigest(),size=pack.stat().st_size)
            config=types.SimpleNamespace(HOME=str(home),USERDATA=str(userdata),PACKAGES=str(home/'packages'),
                get_setting=lambda k:settings.get(k,''),set_setting=lambda k,v:settings.__setitem__(k,v))
            logging=types.SimpleNamespace(log=lambda *a,**kw:None)
            tools=types.SimpleNamespace(ensure_folders=lambda p:os.makedirs(p,exist_ok=True),
                remove_file=lambda p:os.remove(p) if os.path.isfile(p) else None)
            common=types.ModuleType('resources.libs.common');common.logging=logging;common.tools=tools
            modules={'resources.libs.common':common,'resources.libs.common.config':types.SimpleNamespace(CONFIG=config),
                'xbmc':types.SimpleNamespace(LOGINFO=1,LOGERROR=4,LOGWARNING=3)}
            with patch.dict(sys.modules,modules),patch.object(config_apply,'_download_config_zip',side_effect=OSError('blocked')) as download:
                result=config_apply.apply_config_pack({'config':cfg},fresh=True)
            download.assert_not_called()
            self.assertTrue(result['applied'])
            self.assertEqual(settings['config_applied_version'],'seed-test')
            for file in ('guisettings.xml','favourites.xml','sources.xml','kodipovil.fresh_gui_defaults.xml'):
                self.assertTrue((userdata/file).is_file(),file)

    def test_https_uses_verified_portable_roots_and_a_bounded_timeout(self):
        with tempfile.TemporaryDirectory() as raw:
            context=Mock();opener=types.SimpleNamespace(open=Mock(return_value=io.BytesIO(b'ZIP')))
            with patch('ssl.create_default_context',return_value=context) as create, \
                    patch.dict(sys.modules,{'certifi':types.SimpleNamespace(where=lambda:'/qa/trusted.pem')}), \
                    patch('urllib.request.build_opener',return_value=opener) as build:
                config_apply._download_config_zip('https://example.test/config.zip',str(Path(raw)/'config.zip'))
            create.assert_called_once_with()
            context.load_verify_locations.assert_called_once_with(cafile='/qa/trusted.pem')
            self.assertIs(build.call_args.args[1]._context,context)
            self.assertEqual(opener.open.call_args.kwargs['timeout'],20)

    def run_config_phase(self,recover):
        state={'calls':0,'applied':False};waits=[];marks=[]
        def apply(*a,**kw):
            state['calls']+=1
            state['applied']=recover and state['calls']==2
            return {'applied':state['applied'],'skin_touched':state['applied']}
        manager=types.SimpleNamespace(append_to_queue=lambda _:None,wait_for_queue_empty=lambda:None,
            get_installed=lambda:[],pause_for_resolution=lambda:None,remove_resolution_pause=lambda:None,mark_all_jobs_added=lambda:None)
        def run_manager(orchestrator_func):orchestrator_func(manager);return []
        libs=types.ModuleType('resources.libs');libs.config_apply=types.SimpleNamespace(apply_config_pack=apply)
        libs.fentastic_widgets=types.SimpleNamespace(repair=lambda **kw:False)
        monitor=types.SimpleNamespace(abortRequested=lambda:False,waitForAbort=lambda t:waits.append(t) or False)
        config=types.SimpleNamespace(PACKAGES='unused')
        scope={'CONFIG':config,'os':os,'logging':types.SimpleNamespace(log=lambda *a,**kw:None),
            'tools':types.SimpleNamespace(ensure_folders=lambda _:None),
            'xbmc':types.SimpleNamespace(Monitor=lambda:monitor,LOGINFO=1,LOGWARNING=3,LOGERROR=4,getCondVisibility=lambda _:True)}
        fn=_load_function(LIBS/'modular_updater.py','execute_updates',scope,'ModularUpdater')
        self_mock=types.SimpleNamespace(fresh=True,background=False,_manifest={'config':{'config_version':'2.0.9'}},
            CORE_PROVISION_IDS=(),_resolve_phase_two_bounded=lambda:([],[]),
            _config_pending=lambda _:not state['applied'],_fresh_install_complete=lambda _:state['applied'],
            mark_provisioned=lambda _:marks.append(True),is_provisioned=lambda:bool(marks))
        with patch.dict(sys.modules,{'resources.libs':libs,'resources.libs.gui.install_manager':types.SimpleNamespace(run_install_manager=run_manager)}):
            result=fn(self_mock,[])
        return result,state,waits,marks

    def test_early_failure_is_retried_after_dependency_registration(self):
        result,state,waits,marks=self.run_config_phase(True)
        self.assertTrue(result);self.assertEqual(state['calls'],2)
        self.assertEqual(waits,[]);self.assertEqual(marks,[True])

    def test_persistent_config_failure_is_not_certified_or_waited_on_as_an_addon_scan(self):
        result,state,waits,marks=self.run_config_phase(False)
        self.assertFalse(result);self.assertEqual(state['calls'],2)
        self.assertEqual(waits,[]);self.assertEqual(marks,[])


if __name__=='__main__':unittest.main()
