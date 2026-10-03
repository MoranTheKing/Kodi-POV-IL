"""Safety gates for migrating an installed build and certifying a fresh one."""

import ast
import json
import io
import os
import tempfile
import types
import unittest
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _load_function(path, name, globals_dict, class_name=None):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    nodes = tree.body
    if class_name:
        nodes = next(n for n in nodes if isinstance(n, ast.ClassDef)
                     and n.name == class_name).body
    fn = next(n for n in nodes if isinstance(n, ast.FunctionDef) and n.name == name)
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    namespace = dict(globals_dict)
    exec(compile(module, str(path), 'exec'), namespace)
    return namespace[name]


class ProvisioningGateTests(unittest.TestCase):
    def test_background_zip_download_is_atomic_and_size_bounded(self):
        path = (ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs'
                / 'modular_updater.py')
        fn = _load_function(path, '_download_background_zip', {
            'CONFIG': types.SimpleNamespace(USER_AGENT='Kodi POV IL QA'),
            'xbmc': types.SimpleNamespace(Monitor=lambda: types.SimpleNamespace(
                abortRequested=lambda: False)), 'os': os},
            class_name='ModularUpdater')

        def response(data):
            stream = io.BytesIO(data)
            stream.status = 200
            return stream

        with tempfile.TemporaryDirectory() as directory:
            target = str(Path(directory) / 'addon.zip')
            Path(target).write_bytes(b'previous')
            opener = types.SimpleNamespace(open=lambda *_a, **_kw: response(b'new'))
            with patch('urllib.request.build_opener', return_value=opener):
                with self.assertRaisesRegex(IOError, 'size mismatch'):
                    fn('https://example.invalid/addon.zip', target, {'size': 4})
                self.assertEqual(Path(target).read_bytes(), b'previous')
                self.assertFalse(Path(target + '.part').exists())
                fn('https://example.invalid/addon.zip', target, {'size': 3})
            self.assertEqual(Path(target).read_bytes(), b'new')

    def test_legacy_build_does_not_need_new_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for addon_id in ('service.subtitles.kodipovilai', 'plugin.video.pov'):
                addon_xml = root / addon_id / 'addon.xml'
                addon_xml.parent.mkdir()
                addon_xml.write_text('<addon/>', encoding='utf-8')
            state = {'buildname': 'Kodi POV IL', 'installed': 'true'}
            config = types.SimpleNamespace(
                ADDONS=str(root), USERDATA=str(root),
                get_setting=lambda key: state.get(key, ''))
            fn = _load_function(ROOT / 'plugin.program.kodipovilwizard' / 'startup.py',
                                '_is_existing_pre_modular_build',
                                {'CONFIG': config, 'os': os})
            self.assertTrue(fn())
            (root / 'plugin.video.pov' / 'addon.xml').unlink()
            self.assertFalse(fn())
            (root / 'plugin.video.pov' / 'addon.xml').write_text('<addon/>')
            state['installed'] = ''
            self.assertFalse(fn())
            (root / 'kodipovil.legacy_migration').write_text('bridge')
            self.assertTrue(fn())
            (root / 'service.subtitles.kodipovilai' / 'addon.xml').unlink()
            self.assertFalse(fn())

    def test_fresh_marker_requires_every_addon_and_config(self):
        versions = {'plugin.video.pov': '6.09.05',
                    'service.subtitles.kodipovilai': '0.3.15'}
        state = {'config_applied_version': '2.0.7'}
        messages = []
        config = types.SimpleNamespace(get_setting=lambda key: state.get(key, ''))
        logging = types.SimpleNamespace(log=lambda message, **kw: messages.append(message))
        native_present = {'plugin.video.pov': True, 'plugin.video.idanplus': True,
                          'skin.povil.nox': True, 'script.fentastic.helper': True}
        xbmc = types.SimpleNamespace(
            LOGERROR=4, LOGINFO=1,
            getCondVisibility=lambda condition: native_present.get(
                condition.removeprefix('System.HasAddon(').removesuffix(')'), False))
        fn = _load_function(
            ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs'
            / 'modular_updater.py', '_fresh_install_complete',
            {'CONFIG': config, 'logging': logging, 'xbmc': xbmc},
            class_name='ModularUpdater')
        updater = types.SimpleNamespace(
            get_local_version=lambda aid: versions.get(aid),
            _version_tuple=lambda ver: tuple(int(part) for part in ver.split('.')),
            ON_DEMAND_SKINS=frozenset(('skin.povil.nox',)),
            _pending_addon_receipt=lambda _aid: False,
            CORE_PROVISION_IDS=('plugin.video.pov', 'plugin.video.idanplus'))
        manifest = {'addons': {aid: {'version': ver} for aid, ver in versions.items()},
                    'config': {'config_version': '2.0.7'}}
        manifest['addons']['skin.povil.nox'] = {'version': '1.0.11'}
        self.assertFalse(fn(updater, manifest), 'missing default skin must block completion')
        versions['skin.povil.nox'] = '1.0.11'
        self.assertTrue(fn(updater, manifest))
        native_present['plugin.video.idanplus'] = False
        self.assertFalse(fn(updater, manifest), 'missing native core must block completion')
        native_present['plugin.video.idanplus'] = True
        versions['plugin.video.pov'] = '6.09.04'
        self.assertFalse(fn(updater, manifest))
        versions['plugin.video.pov'] = '6.09.05'
        state['config_applied_version'] = ''
        self.assertFalse(fn(updater, manifest))
        self.assertTrue(any('incomplete' in message for message in messages))

    def test_fresh_queue_installs_default_nox_skin(self):
        config = types.SimpleNamespace(USER_AGENT='Kodi POV IL QA')
        logs = types.SimpleNamespace(log=lambda *_a, **_kw: None)
        xbmc = types.SimpleNamespace(LOGINFO=1)
        fn = _load_function(
            ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs'
            / 'modular_updater.py', 'run_update_check',
            {'CONFIG': config, 'logging': logs, 'xbmc': xbmc},
            class_name='ModularUpdater')
        manifest = {'addons': {
            'plugin.program.kodipovilwizard': {'id': 'plugin.program.kodipovilwizard',
                                                'version': '0.4.3'},
            'service.subtitles.kodipovilai': {'id': 'service.subtitles.kodipovilai',
                                              'version': '0.3.18'},
            'skin.povil.nox': {'id': 'skin.povil.nox', 'version': '1.0.11'}},
            'config': {'config_version': '2.0.7'}}
        seen = []
        updater = types.SimpleNamespace(
            _load_manifest=lambda: manifest,
            get_local_version=lambda _id: None,
            _on_disk=lambda _id: False,
            ON_DEMAND_SKINS=frozenset(('skin.povil.nox',)),
            _pending_addon_receipt=lambda _aid: False,
            install_missing=True, fresh=True,
            _record_build_identity=lambda _manifest: True,
            _config_pending=lambda _manifest: True,
            execute_updates=lambda queue: seen.extend(queue) or True)
        self.assertTrue(fn(updater))
        self.assertEqual([item['id'] for item in seen],
                         ['plugin.program.kodipovilwizard',
                          'service.subtitles.kodipovilai', 'skin.povil.nox'])
        # No old service exists. The conservative unknown-addon probe must
        # never prevent an initial installation (real Kodi returns an error).
        updater._runtime_addon_enabled = lambda _aid: True
        updater._service_handoff_ready = lambda: False
        seen.clear()
        self.assertTrue(fn(updater))
        self.assertIn('service.subtitles.kodipovilai', [item['id'] for item in seen])
        # A manually requested fresh provisioning on an existing profile still
        # protects its live service, regardless of the fresh flag.
        updater.get_local_version = lambda aid: ('0.2.566' if aid.startswith('service.') else None)
        updater._on_disk = lambda aid: aid == 'service.subtitles.kodipovilai'
        updater._version_tuple = lambda ver: tuple(map(int, ver.split('.')))
        xbmc.LOGWARNING = 2
        seen.clear()
        self.assertTrue(fn(updater))
        self.assertNotIn('service.subtitles.kodipovilai', [item['id'] for item in seen])
        # Broken/versionless existing metadata is still an existing tree;
        # inability to parse its version cannot waive live-service protection.
        updater.get_local_version = lambda _aid: None
        seen.clear()
        self.assertTrue(fn(updater))
        self.assertNotIn('service.subtitles.kodipovilai', [item['id'] for item in seen])

    def test_legacy_pov_host_keeps_its_old_repair_service(self):
        fn = _load_function(
            ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs'
            / 'modular_updater.py', 'run_update_check',
            {'logging': types.SimpleNamespace(log=lambda *_a, **_k: None),
             'xbmc': types.SimpleNamespace(LOGINFO=1, LOGWARNING=2),
             'CONFIG': types.SimpleNamespace(ADDON_DATA='/tmp/qa', ADDON_ID='wizard'),
             'os': os},
            class_name='ModularUpdater')
        manifest = {'addons': {
            'service.subtitles.kodipovilai': {
                'id': 'service.subtitles.kodipovilai', 'version': '0.3.15'},
            'plugin.program.orderfavourites-hebrew': {
                'id': 'plugin.program.orderfavourites-hebrew', 'version': '1.4.5'}}}
        queued = []
        updater = types.SimpleNamespace(
            _load_manifest=lambda: manifest,
            get_local_version=lambda aid: ('0.2.566' if aid.startswith('service.')
                                           else '1.2.1'),
            _service_handoff_ready=lambda: False,
            _runtime_addon_enabled=lambda _aid: True,
            _complete_pending_service_handoff=lambda: False,
            _version_tuple=lambda version: tuple(int(x) for x in version.split('.')),
            ON_DEMAND_SKINS=frozenset(), background=True,
            _record_build_identity=lambda _manifest: False,
            _config_pending=lambda _manifest: False,
            execute_updates=lambda items: queued.extend(items) or True)
        resources = types.ModuleType('resources')
        libs = types.ModuleType('resources.libs')
        patch_engine = types.ModuleType('resources.libs.patch_engine')
        patch_engine.PatchEngine = lambda: types.SimpleNamespace(
            legacy_pov_host_present=lambda: True)
        receipt = types.ModuleType('resources.libs.addon_install_receipt')
        receipt.needs_retry = lambda *_args: False
        libs.addon_install_receipt = receipt
        with patch.dict(sys.modules, {
                'resources': resources, 'resources.libs': libs,
                'resources.libs.patch_engine': patch_engine,
                'resources.libs.addon_install_receipt': receipt}):
            self.assertTrue(fn(updater))
            self.assertEqual([item['id'] for item in queued],
                             ['plugin.program.orderfavourites-hebrew'])
            queued.clear()
            updater.get_local_version = lambda aid: manifest['addons'][aid]['version']
            receipt.needs_retry = lambda _data, aid: (
                aid == 'plugin.program.orderfavourites-hebrew')
            self.assertTrue(fn(updater))
            self.assertEqual([item['id'] for item in queued],
                             ['plugin.program.orderfavourites-hebrew'],
                             'same-version interrupted extraction must retry')
            queued.clear()
            updater.get_local_version = lambda aid: (
                None if aid == 'plugin.program.orderfavourites-hebrew'
                else manifest['addons'][aid]['version'])
            self.assertTrue(fn(updater))
            self.assertEqual([item['id'] for item in queued],
                             ['plugin.program.orderfavourites-hebrew'],
                             'missing addon.xml during interrupted extraction must retry')

    def test_service_handoff_requires_all_active_patches(self):
        path = (ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs'
                / 'modular_updater.py')
        fn = _load_function(path, '_service_handoff_ready', {
            'logging': types.SimpleNamespace(log=lambda *_a, **_k: None),
            'xbmc': types.SimpleNamespace(LOGWARNING=2)},
            class_name='ModularUpdater')
        resources = types.ModuleType('resources')
        libs = types.ModuleType('resources.libs')
        patch_engine = types.ModuleType('resources.libs.patch_engine')
        state = {'stats': {
            'skipped_current': 70, 'anchor_missing': 0, 'failed': 0,
            'missing': 0, 'malformed': 0}}
        patch_engine.PatchEngine = lambda: types.SimpleNamespace(
            run=lambda: state['stats'])
        with patch.dict(sys.modules, {
                'resources': resources, 'resources.libs': libs,
                'resources.libs.patch_engine': patch_engine}):
            self.assertTrue(fn())
            state['stats'] = dict(state['stats'], anchor_missing=1)
            self.assertFalse(fn())
            state['stats'] = dict(state['stats'], anchor_missing=0,
                                  legacy_host_deferred=1)
            self.assertFalse(fn())

    def test_live_service_must_be_proven_disabled_before_swap(self):
        path = (ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs'
                / 'modular_updater.py')
        replies = [
            '{"result":{"addon":{"addonid":"service.subtitles.kodipovilai",'
            '"enabled":false}}}',
            '{"result":{"addon":{"addonid":"service.subtitles.kodipovilai",'
            '"enabled":true}}}',
            '{"error":{"code":-32602}}',
        ]
        xbmc = types.SimpleNamespace(executeJSONRPC=lambda _body: replies.pop(0))
        fn = _load_function(path, '_runtime_addon_enabled',
                            {'json': json, 'xbmc': xbmc}, class_name='ModularUpdater')
        self.assertFalse(fn('service.subtitles.kodipovilai'))
        self.assertTrue(fn('service.subtitles.kodipovilai'))
        self.assertTrue(fn('service.subtitles.kodipovilai'))

    def test_manual_update_never_sends_existing_service_to_in_place_installer(self):
        path = (ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs'
                / 'modular_updater.py')
        fn = _load_function(path, 'execute_updates', {
            'CONFIG': types.SimpleNamespace(PACKAGES='unused', ADDONTITLE='QA'),
            'tools': types.SimpleNamespace(ensure_folders=lambda _path: None),
            'logging': types.SimpleNamespace(log=lambda *_a, **_k: None),
            'xbmc': types.SimpleNamespace(LOGINFO=1, LOGWARNING=2,
                                           executebuiltin=lambda *_a: None),
        }, class_name='ModularUpdater')
        seen = []
        modules = {name: types.ModuleType(name) for name in (
            'resources', 'resources.libs', 'resources.libs.config_apply')}
        modules['resources.libs.config_apply'].apply_config_pack = (
            lambda *_a, **_k: seen.append('config') or {'skin_touched': False})
        modules['resources.libs'].config_apply = modules['resources.libs.config_apply']
        updater = types.SimpleNamespace(
            background=False, fresh=False, _manifest={'config': {}},
            _missing_native=[],
            _runtime_addon_enabled=lambda _aid: seen.append('runtime') or True,
            _service_handoff_ready=lambda: seen.append('patches') or True)
        with patch.dict(sys.modules, modules):
            self.assertTrue(fn(updater, [
                {'id': 'service.subtitles.kodipovilai', 'version': '0.3.15'}]))
        self.assertEqual(seen, ['config'])

    def test_offline_boot_does_not_fetch_manifest_twice(self):
        path = (ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs'
                / 'modular_updater.py')
        logs = types.SimpleNamespace(log=lambda *_a, **_kw: None)
        xbmc = types.SimpleNamespace(LOGINFO=1)
        globals_dict = {'logging': logs, 'xbmc': xbmc}
        check = _load_function(path, 'run_update_check', globals_dict,
                               class_name='ModularUpdater')
        heal = _load_function(path, 'heal_missing_addons', globals_dict,
                              class_name='ModularUpdater')
        calls = []
        updater = types.SimpleNamespace(
            background=True,
            _complete_pending_service_handoff=lambda: False,
            _load_manifest=lambda: calls.append('fetch') or None)
        self.assertFalse(check(updater))
        heal(updater)
        self.assertEqual(calls, ['fetch'])

    def test_manifest_fetch_is_bounded_and_single_request(self):
        calls = []
        logs = types.SimpleNamespace(log=lambda *_a, **_kw: None)
        xbmc = types.SimpleNamespace(LOGERROR=4, LOGINFO=1)
        config = types.SimpleNamespace(USER_AGENT='Kodi POV IL QA')
        fn = _load_function(
            ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs'
            / 'modular_updater.py', '_load_manifest',
            {'CONFIG': config, 'logging': logs, 'xbmc': xbmc, 'json': json},
            class_name='ModularUpdater')
        updater = types.SimpleNamespace(manifest_url='http://127.0.0.1/test')
        def respond(request, timeout):
            calls.append((request.full_url, timeout))
            return io.BytesIO(b'{"addons":{},"config":{}}')
        opener = types.SimpleNamespace(open=respond)
        with patch('urllib.request.build_opener', return_value=opener) as make_opener:
            self.assertEqual(fn(updater), {'addons': {}, 'config': {}})
        self.assertEqual(len(make_opener.call_args.args), 1)
        self.assertEqual(make_opener.call_args.args[0].proxies, {})
        self.assertEqual(calls, [('http://127.0.0.1/test', 8)])

    def test_phase_two_resolver_failure_still_reaches_native_fallback(self):
        path = (ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs'
                / 'modular_updater.py')
        attempted = []
        present = {'core.one': True, 'core.two': False}
        xbmc = types.SimpleNamespace(
            LOGINFO=1, LOGERROR=4, LOGWARNING=2,
            Monitor=lambda: types.SimpleNamespace(abortRequested=lambda: False, waitForAbort=lambda _n: False),
            getCondVisibility=lambda condition: present.get(
                condition.removeprefix('System.HasAddon(').removesuffix(')'), False))
        xbmcgui = types.SimpleNamespace(DialogProgressBG=lambda: types.SimpleNamespace(
            create=lambda *_a: None, close=lambda: None))
        logs = types.SimpleNamespace(log=lambda *_a, **_kw: None)
        config = types.SimpleNamespace(PACKAGES='unused', ADDONTITLE='test')
        tools = types.SimpleNamespace(ensure_folders=lambda _path: None)

        class Dialog:
            def append_to_queue(self, _jobs): pass
            def wait_for_queue_empty(self): pass
            def pause_for_resolution(self): pass
            def remove_resolution_pause(self): pass
            def mark_all_jobs_added(self): pass
            def get_installed(self): return []

        def run_install_manager(orchestrator_func):
            orchestrator_func(Dialog())
            return []

        modules = {name: types.ModuleType(name) for name in (
            'resources', 'resources.libs', 'resources.libs.gui',
            'resources.libs.gui.install_manager',
            'resources.libs.config_apply')}
        modules['resources.libs.gui.install_manager'].run_install_manager = run_install_manager
        modules['resources.libs.config_apply'].apply_config_pack = (
            lambda *_a, **_kw: {'skin_touched': False})
        modules['resources.libs'].config_apply = modules['resources.libs.config_apply']
        fn = _load_function(path, 'execute_updates',
                            {'CONFIG': config, 'tools': tools, 'logging': logs,
                             'xbmc': xbmc, 'xbmcgui': xbmcgui},
                            class_name='ModularUpdater')
        updater = types.SimpleNamespace(
            fresh=True, background=False, PROVISION_IDS=('core.one', 'core.two'),
            _manifest={'addons': {}, 'config': {}},
            _resolve_phase_two_bounded=lambda: (_ for _ in ()).throw(
                RuntimeError('repository unavailable')),
            _native_install_fallback=lambda ids, per_addon_timeout:
                attempted.append((ids, per_addon_timeout)),
            _fresh_install_complete=lambda _manifest: False,
            CORE_PROVISION_IDS=(), _enable_addon=lambda _aid: None)
        with patch.dict(sys.modules, modules):
            self.assertFalse(fn(updater, []))
        self.assertEqual(attempted, [(['core.two'], 60)])

    def test_phase_two_resolver_has_a_hard_deadline(self):
        path = (ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs'
                / 'modular_updater.py')
        fn = _load_function(path, '_resolve_phase_two_bounded', {},
                            class_name='ModularUpdater')
        module = types.ModuleType('resources.libs.headless_installer')

        class SlowResolver:
            def resolve_and_prepare(self, _ids):
                import time
                time.sleep(0.1)
                return [], []

        module.HeadlessInstaller = SlowResolver
        with patch.dict(sys.modules, {'resources': types.ModuleType('resources'),
                                      'resources.libs': types.ModuleType('resources.libs'),
                                      'resources.libs.headless_installer': module}):
            with self.assertRaises(TimeoutError):
                fn(types.SimpleNamespace(PROVISION_IDS=('core.one',)), timeout=0.01)


if __name__ == '__main__':
    unittest.main()
