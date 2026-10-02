"""Fresh setup must certify the live home, not just extracted files."""
import json
import os
import threading
import re
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch
from test_provisioning_gate import _load_function, ROOT

FRESH = ROOT / 'plugin.program.kodipovilwizard/resources/libs/fresh_install.py'


class FreshHomeReadinessTests(unittest.TestCase):
    def test_late_first_install_tiles_get_one_bounded_extra_profile_refresh(self):
        with tempfile.TemporaryDirectory() as raw:
            Path(raw, 'favourites.xml').write_text(
                '<favourites><favourite name="Tonight">RunScript(tonight)</favourite></favourites>')
            calls = []
            cached = []
            fn = _load_function(FRESH, 'live_favourites_ready', {
                'CONFIG': types.SimpleNamespace(USERDATA=raw), 'ET': ET, 'os': os,
                '_rpc': lambda *_a: {'favourites': cached},
                'xbmc': types.SimpleNamespace(getInfoLabel=lambda _k: 'Master user',
                                              executebuiltin=calls.append)})
            self.assertFalse(fn()); self.assertFalse(fn()); self.assertFalse(fn())
            self.assertEqual(calls, ['LoadProfile("Master user")'] * 2)
            cached.append({'title': 'Tonight'})
            self.assertTrue(fn()); self.assertEqual(len(calls), 2)

    def test_exact_skin_question_uses_native_heading(self):
        sent = []
        # Native controls expose no heading through the Python wrapper's label.
        xbmc = types.SimpleNamespace(getSkinDir=lambda: 'skin.povil.nox',
            getCondVisibility=lambda _c: True, getInfoLabel=lambda _c: 'Skin',
            getLocalizedString=lambda i: {13123: 'Skin', 13111: 'Keep this skin?'}[i],
            executebuiltin=sent.append)
        textbox = types.SimpleNamespace(getText=lambda: 'Keep this skin?', getLabel=lambda: '')
        gui = types.SimpleNamespace(Window=lambda _id: types.SimpleNamespace(getControl=lambda _id: textbox))
        fn = _load_function(FRESH, '_accept_initial_skin_confirmation', {'xbmc': xbmc, 'xbmcgui': gui})
        self.assertTrue(fn()); self.assertEqual(sent, ['SendClick(10100,11)'])
        xbmc.getInfoLabel = lambda _c: 'Security warning'
        self.assertFalse(fn()); self.assertEqual(len(sent), 1)

    def test_live_defaults_are_typed_and_skin_is_last(self):
        with tempfile.TemporaryDirectory() as raw:
            Path(raw, 'kodipovil.fresh_gui_defaults.xml').write_text('''<settings>
                <setting id="lookandfeel.skin">skin.povil.nox</setting>
                <setting id="locale.language">resource.language.he_il</setting>
                <setting id="test.bool">false</setting>
                <setting id="test.list">English|Hebrew</setting>
                <setting id="test.default" default="true">ignored</setting>
                </settings>''', encoding='utf8')
            current = {'locale.language': 'en', 'test.bool': True, 'test.list': []}
            calls, waits = [], []
            skin = ['skin.estuary']
            def rpc(method, params):
                if method.endswith('GetSettingValue'):
                    return {'value': current[params['setting']]}
                calls.append(params)
                if params['setting'] == 'lookandfeel.skin':
                    skin[0] = params['value']
                return True
            xbmc = types.SimpleNamespace(
                Monitor=lambda: types.SimpleNamespace(abortRequested=lambda: False,
                    waitForAbort=lambda seconds: waits.append(seconds) or False),
                getSkinDir=lambda: skin[0], getCondVisibility=lambda _cond: True)
            fn = _load_function(FRESH, 'apply_live_defaults', {
                'ET': ET, 'os': os, 're': re, 'threading': threading, 'CONFIG': types.SimpleNamespace(USERDATA=raw),
                'xbmc': xbmc, '_rpc': rpc, '_accept_initial_skin_confirmation': lambda: False})
            self.assertTrue(fn())
            self.assertEqual(calls[-1], {'setting': 'lookandfeel.skin', 'value': 'skin.povil.nox'})
            self.assertIs(calls[1]['value'], False)
            self.assertEqual(calls[2]['value'], ['English', 'Hebrew'])
            self.assertGreater(sum(waits), 10)
            xbmc.getSkinDir = lambda: 'skin.estuary'
            self.assertFalse(fn(), 'RPC success cannot certify a reverted skin')

    def test_missing_core_retains_first_boot_retry_marker(self):
        with tempfile.TemporaryDirectory() as raw:
            marker = Path(raw, 'retry'); marker.write_text('1')
            reloads = []
            xbmc = types.SimpleNamespace(LOGINFO=1, LOGWARNING=2, LOGERROR=4,
                Monitor=lambda: types.SimpleNamespace(abortRequested=lambda: False,
                                                      waitForAbort=lambda _n: False),
                getCondVisibility=lambda _condition: False,
                executebuiltin=reloads.append)
            banner = types.SimpleNamespace(create=lambda *_a: None,
                update=lambda *_a: None, close=lambda: None)
            fn = _load_function(ROOT / 'plugin.program.kodipovilwizard/startup.py',
                'first_boot_stabilize_if_needed', {'os': os, 'xbmc': xbmc,
                 'xbmcgui': types.SimpleNamespace(DialogProgressBG=lambda: banner),
                 'CONFIG': types.SimpleNamespace(ADDONTITLE='QA'),
                 'logging': types.SimpleNamespace(log=lambda *_a, **_k: None),
                 '_first_boot_marker_path': lambda: str(marker),
                 '_first_boot_warmup_seconds': lambda: 5})
            self.assertFalse(fn())
            self.assertTrue(marker.exists())
            self.assertEqual(reloads, [])

    def test_partial_media_or_patch_failure_never_marks_installed(self):
        import importlib.util
        calls = []
        media = types.SimpleNamespace(install_and_verify_global_media_assets=lambda: False)
        spec = types.SimpleNamespace(loader=types.SimpleNamespace(exec_module=lambda _m: None))
        fake_importlib = types.SimpleNamespace(util=types.SimpleNamespace(
            spec_from_file_location=lambda *_a: spec, module_from_spec=lambda _s: media))
        config = types.SimpleNamespace(USERDATA='unused', ADDONS='unused',
                                      set_setting=lambda *args: calls.append(args))
        fn = _load_function(FRESH, 'finalize', {'CONFIG': config, 'os': os,
            'importlib': fake_importlib, 'apply_live_defaults': lambda: True,
            'xbmc': types.SimpleNamespace(executebuiltin=lambda _b: None,
                Monitor=lambda: None, getCondVisibility=lambda _c: True)})
        modules = {key: types.ModuleType(key) for key in (
            'resources', 'resources.libs', 'resources.libs.modular_updater',
            'resources.libs.patch_engine')}
        modules['resources.libs'].db = types.SimpleNamespace(fix_metas=lambda: None, addon_database=lambda *_a: None)
        modules['resources.libs.modular_updater'].ModularUpdater = types.SimpleNamespace(
            is_provisioned=lambda: True, CORE_PROVISION_IDS=())
        modules['resources.libs.patch_engine'].PatchEngine = lambda: types.SimpleNamespace(
            run=lambda: {'failed': 1})
        with patch.dict('sys.modules', modules):
            with self.assertRaisesRegex(RuntimeError, 'media'):
                fn()
            media.install_and_verify_global_media_assets = lambda: True
            with self.assertRaisesRegex(RuntimeError, 'patches'):
                fn()
        self.assertEqual(calls, [])

    def test_existing_skin_is_preserved_by_update_policy(self):
        policy = json.loads((ROOT / 'userdata/config_policy.json').read_text('utf8'))
        gui = next(row for row in policy['files'] if row['src'] == 'guisettings.xml')
        self.assertEqual(gui['update'], 'seed_if_absent')
        self.assertEqual(ET.parse(ROOT / 'userdata/guisettings.xml').find(
            "setting[@id='lookandfeel.skin']").text, 'skin.povil.nox')


if __name__ == '__main__':
    unittest.main()
