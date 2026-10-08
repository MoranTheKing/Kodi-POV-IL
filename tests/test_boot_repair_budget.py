"""Changed files/settings require a real repair; adult onload skips layout work."""
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard'


def load(path, modules):
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location('budget_' + path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class RepairReceiptTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.addons = self.root / 'addons'
        self.addon = self.addons / 'plugin.video.pov'
        self.addon.mkdir(parents=True)
        self.target = self.addon / 'sample.py'
        self.target.write_text('ANCHOR\n', encoding='utf8')
        (self.addon / 'addon.xml').write_text('<addon/>')
        schema = self.addon / 'resources/settings.xml'
        schema.parent.mkdir(); schema.write_text('<settings/>')
        self.receipt = self.root / 'master/addon_data/plugin.program.kodipovilwizard/patch-receipt.json'
        self.overrides = {}; self.constructors = 0
        def constructor():
            self.constructors += 1
            return types.SimpleNamespace(getSetting=lambda key: self.overrides.get(key, ''))
        def translate(value):
            for prefix, directory in [('special://home/addons/', self.addons),
                                      ('special://masterprofile/', self.root / 'master')]:
                if value.startswith(prefix):return str(directory / value[len(prefix):])
            return value
        self.module = load(ROOT / 'resources/libs/patch_engine.py', {
            'xbmc':types.SimpleNamespace(LOGDEBUG=0,LOGINFO=1,LOGWARNING=2,LOGERROR=3),
            'xbmcaddon':types.SimpleNamespace(Addon=constructor),
            'xbmcvfs':types.SimpleNamespace(translatePath=translate),
            'resources.libs.common':types.SimpleNamespace(logging=types.SimpleNamespace(log=lambda *a,**k:None)),
        })
        self.config = [dict(id='sample',name='sample',addon_id='plugin.video.pov',
            target_file='sample.py',marker='HOOK_v1',anchor='ANCHOR',action='append_after',
            hook='pass',enabled=True)]

    def run_engine(self, fast=True):
        engine = self.module.PatchEngine(self.config)
        return engine.run_if_changed() if fast else engine.run()

    def certify(self):
        self.assertEqual(self.run_engine()['applied'], 1)
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.run_engine()['skipped_current'], 1)
        self.assertTrue(self.receipt.exists())

    def test_only_write_free_verified_pass_creates_receipt_then_skips_reads(self):
        self.certify()
        with patch.object(self.module.PatchEngine, '_process_target', side_effect=AssertionError('full pass')):
            result = self.run_engine()
        self.assertEqual(result['unchanged_targets'], 1)

    def test_explicit_repair_always_reads_the_target(self):
        self.certify()
        original = self.module.PatchEngine._process_target
        calls = []
        def process(engine,*args):calls.append(args);return original(engine,*args)
        with patch.object(self.module.PatchEngine,'_process_target',process):
            result = self.run_engine(fast=False)
        self.assertEqual(len(calls),1)
        self.assertEqual(result['skipped_current'],1)

    def test_clean_host_replacement_repairs_even_with_same_size_and_mtime(self):
        self.certify()
        stat = self.target.stat()
        replacement = self.target.with_suffix('.next')
        # An installed replacement is distinct even if the archive retains dates.
        replacement.write_bytes(b'ANCHOR\n' + b' ' * (stat.st_size - 7))
        os.utime(replacement, ns=(stat.st_atime_ns,stat.st_mtime_ns))
        os.replace(replacement,self.target)
        self.assertEqual(self.run_engine()['applied'],1)

    def test_override_removes_hook_and_does_not_trust_old_receipt(self):
        self.certify();self.overrides['patch_enabled_sample']='false'
        self.assertEqual(self.run_engine()['removed'],1)
        self.assertNotIn('HOOK_v1',self.target.read_text())
        self.assertNotIn('unchanged_targets',self.run_engine())
        self.assertEqual(self.run_engine()['unchanged_targets'],1)

    def test_config_upgrade_schema_change_and_new_optional_host_invalidate(self):
        self.certify();self.config[0]['marker']='HOOK_v2'
        self.assertEqual(self.run_engine()['upgraded'],1)
        self.run_engine();self.assertEqual(self.run_engine()['unchanged_targets'],1)
        (self.addon/'resources/settings.xml').write_text('<settings><!-- new --></settings>')
        self.assertNotIn('unchanged_targets',self.run_engine())
        (self.addon/'addon.xml').write_text('<addon version="2"/>')
        self.assertNotIn('unchanged_targets',self.run_engine())

    def test_legacy_edits_and_failed_targets_never_get_a_new_receipt(self):
        self.certify();self.receipt.unlink()
        self.target.write_text('ANCHOR\n# AI_SUBS_AUTOPICK_v7\n')
        self.assertEqual(self.run_engine()['legacy_host_deferred'],1)
        self.assertFalse(self.receipt.exists())
        self.target.unlink()
        self.assertEqual(self.run_engine()['missing'],1)
        self.assertFalse(self.receipt.exists())

    def test_corrupt_or_unwritable_receipt_keeps_full_repairs_available(self):
        self.certify();self.receipt.write_text('{ broken')
        self.assertEqual(self.run_engine()['skipped_current'],1)
        self.receipt.unlink();self.receipt.mkdir()
        self.assertEqual(self.run_engine()['skipped_current'],1)

    def test_one_sdk_settings_object_keeps_live_overrides_for_all_entries(self):
        self.config.append(dict(self.config[0],id='second',marker='SECOND_v1'))
        self.run_engine(fast=False)
        self.assertEqual(self.constructors,1)


class HomeBootstrapBudgetTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.master = Path(folder.name);self.active = self.master/'profiles/Adult'
        self.active.mkdir(parents=True);(self.master/'kodipovil.provisioned').write_text('1')
        (self.active/'kodipovil.profile_home_ready').write_text('1')
        self.skin = 'skin.estuary';self.child = False;self.ready = True;self.dialog = 0
        self.module = load(ROOT/'profile_bootstrap.py',{
            'xbmc':types.SimpleNamespace(getSkinDir=lambda:self.skin,
                getCondVisibility=lambda name:self.child if name.endswith('(POVILChild)') else self.ready),
            'xbmcgui':types.SimpleNamespace(Window=lambda _:types.SimpleNamespace(getProperty=lambda key:''),
                getCurrentWindowDialogId=lambda:self.dialog),
            'xbmcvfs':types.SimpleNamespace(translatePath=lambda value:str(
                self.master if value=='special://masterprofile/' else self.active)),
        })

    def policy(self, value):
        (self.master/'povil_profiles.json').write_text(json.dumps(value))

    def test_ready_adult_home_needs_no_layout_module_import(self):
        with patch.dict(sys.modules,{'resources.libs':None}):
            self.assertFalse(self.module.resume())

    def test_all_skins_keep_adult_fast_path(self):
        for self.skin in ('skin.estuary','skin.povil.nox','skin.fentastic','skin.arctic.fuse.3'):
            self.assertTrue(self.module._settled_adult(str(self.master),str(self.active)))

    def test_pending_profile_and_sidebar_migration_keep_full_path(self):
        (self.active/'kodipovil.profile_home_ready').unlink()
        self.assertFalse(self.module._settled_adult(str(self.master),str(self.active)))
        (self.active/'kodipovil.profile_home_ready').write_text('1');self.ready=False
        self.assertFalse(self.module._settled_adult(str(self.master),str(self.active)))

    def test_child_marker_live_skin_flag_and_fresh_policy_keep_full_path(self):
        self.child=True
        self.assertFalse(self.module._settled_adult(str(self.master),str(self.active)))
        self.child=False;(self.active/'povil.child-profile').write_text('1')
        self.assertFalse(self.module._settled_adult(str(self.master),str(self.active)))
        (self.active/'povil.child-profile').unlink()
        self.policy({'schema':1,'children':{'profiles/Adult':{'age':7,'approved':{}}}})
        self.assertFalse(self.module._settled_adult(str(self.master),str(self.active)))
        self.policy({'schema':1,'children':{}})
        self.assertTrue(self.module._settled_adult(str(self.master),str(self.active)))

    def test_broken_policy_and_outside_directory_cannot_take_fast_path(self):
        for data in ({'schema':2,'children':{}},{'schema':1,'children':[]},[]):
            self.policy(data)
            self.assertFalse(self.module._settled_adult(str(self.master),str(self.active)))
        (self.master/'povil_profiles.json').write_text('{ broken')
        self.assertFalse(self.module._settled_adult(str(self.master),str(self.active)))
        with tempfile.TemporaryDirectory() as outside:
            (Path(outside)/'kodipovil.profile_home_ready').write_text('1')
            self.assertFalse(self.module._settled_adult(str(self.master),outside))


class CatalogueLatencyTests(unittest.TestCase):
    def setUp(self):
        self.logs=[];self.clock=0.;self.params={'mode':'build_movie_list','action':'tmdb_movies_popular'}
        self.module=load(ROOT/'resources/libs/patches/pov_directory_latency.py',{
            'xbmc':types.SimpleNamespace(log=lambda *a:self.logs.append(a),getSkinDir=lambda:'skin.estuary',LOGINFO=1)})
        self.module.time=types.SimpleNamespace(perf_counter=lambda:self.clock)
        self.native={'kodi_utils':types.SimpleNamespace(parsed_query=lambda _:self.params),
                     '_povil_entry_started':-0.1}
        self.args=types.SimpleNamespace(argv=['plugin://plugin.video.pov/',1,'?private=SECRET'])

    def wrap(self,function):
        self.native['routing']=function;self.module.install(self.native)
        return self.native['routing']

    def test_native_return_identity_and_slow_route_measurement(self):
        sentinel=object()
        def original(_):self.clock=.4;return sentinel
        routed=self.wrap(original)
        self.assertIs(routed(self.args),sentinel)
        self.assertIn('route_ms=400 entry_ms=500',self.logs[0][0])
        self.assertIn('action=tmdb_movies_popular',self.logs[0][0])
        self.assertNotIn('SECRET',self.logs[0][0])
        self.module.install(self.native);self.assertIs(self.native['routing'],routed)

    def test_reused_interpreter_does_not_count_idle_time_as_loading(self):
        def original(_):self.clock+=.4
        routed=self.wrap(original);routed(self.args)
        self.clock=1000;routed(self.args)
        self.assertIn('entry_ms=500',self.logs[0][0])
        self.assertIn('entry_ms=400',self.logs[1][0])

    def test_error_and_system_exit_survive_diagnostics(self):
        for error in (ValueError('private error'),SystemExit('native exit')):
            self.clock=0
            def original(_):self.clock=.4;raise error
            with self.assertRaises(type(error)) as caught:self.wrap(original)(self.args)
            self.assertIs(caught.exception,error)
        self.assertEqual(len(self.logs),2)

    def test_fast_routes_do_no_extra_parsing_or_logging(self):
        self.native['kodi_utils'].parsed_query=lambda _:self.fail('fast route parsed')
        self.assertEqual(self.wrap(lambda _:17)(self.args),17)
        self.assertEqual(self.logs,[])

    def test_unknown_action_is_redacted_and_only_directory_modes_are_logged(self):
        self.params.update(action='account-token-SECRET',widget_limit='7')
        def original(_):self.clock+=.4
        routed=self.wrap(original);routed(self.args)
        self.assertIn('kind=widget',self.logs[0][0]);self.assertIn('action=other',self.logs[0][0])
        self.assertNotIn('SECRET',self.logs[0][0])
        self.params['mode']='open_settings';routed(self.args)
        self.assertEqual(len(self.logs),1)

    def test_diagnostic_failure_does_not_change_native_result(self):
        self.native['kodi_utils'].parsed_query=lambda _: (_ for _ in ()).throw(ValueError())
        def original(_):self.clock=.4;return 23
        self.assertEqual(self.wrap(original)(self.args),23)


if __name__=='__main__':unittest.main()
