"""A failed config update must leave the existing Kodi profile intact."""

import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


PATH = (Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard'
        / 'resources/libs/config_apply.py')
module_spec = importlib.util.spec_from_file_location('transaction_config_apply', PATH)
config_apply = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(config_apply)


class ConfigTransactionTests(unittest.TestCase):
    def test_saved_active_skin_needs_no_kodi_gui_call(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'guisettings.xml'
            for skin in ('skin.estuary', 'skin.fentastic',
                         'skin.povil.nox', 'skin.arctic.fuse.3'):
                path.write_text('<settings><setting id="lookandfeel.skin">'
                                + skin + '</setting></settings>', encoding='utf-8')
                self.assertEqual(config_apply._saved_active_skin(raw), skin)
            path.write_text('<settings><setting', encoding='utf-8')
            self.assertIsNone(config_apply._saved_active_skin(raw))

    def test_config_zip_streams_binary_bytes(self):
        with tempfile.TemporaryDirectory() as raw:
            expected = b'PK\x03\x04\x00\xff\x80' * 1024
            dest = Path(raw) / 'config.zip'
            calls = []
            def respond(request, timeout):
                calls.append((request.full_url, timeout))
                return io.BytesIO(expected)
            opener = types.SimpleNamespace(open=respond)
            with patch('urllib.request.build_opener', return_value=opener) as make_opener:
                config_apply._download_config_zip('http://local/config.zip',
                                                   str(dest))
            self.assertEqual(make_opener.call_args.args[0].proxies, {})
            self.assertEqual(dest.read_bytes(), expected)
            self.assertEqual(calls, [('http://local/config.zip', 8)])

    def test_policy_paths_cannot_escape_kodi_home(self):
        for value in ('../outside', 'userdata/../../outside', '/absolute',
                      'C:/outside', 'userdata//settings.xml'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                config_apply._safe_relative_path(value)

    def test_later_write_failure_rolls_back_earlier_write(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / 'home'
            userdata = home / 'userdata'
            packages = root / 'packages'
            userdata.mkdir(parents=True)
            packages.mkdir()
            (userdata / 'a.txt').write_text('user A', encoding='utf-8')
            (userdata / 'b.txt').write_text('user B', encoding='utf-8')
            archive = root / 'pack.zip'
            policy = {'files': [
                {'src': 'a.txt', 'dest': 'userdata/a.txt', 'update': 'replace'},
                {'src': 'b.txt', 'dest': 'userdata/b.txt', 'update': 'replace'}]}
            with zipfile.ZipFile(archive, 'w') as zf:
                zf.writestr('config_policy.json', json.dumps(policy))
                zf.writestr('a.txt', 'build A')
                zf.writestr('b.txt', 'build B')

            settings = {}
            config = types.SimpleNamespace(
                HOME=str(home), USERDATA=str(userdata), PACKAGES=str(packages),
                get_setting=lambda key: settings.get(key, ''),
                set_setting=lambda key, value: settings.__setitem__(key, value))
            log = types.ModuleType('resources.libs.common.logging')
            log.log = lambda *_a, **_kw: None
            common = types.ModuleType('resources.libs.common')
            common.config = types.ModuleType('resources.libs.common.config')
            common.config.CONFIG = config
            common.logging = log
            common.tools = types.SimpleNamespace(
                ensure_folders=lambda path: os.makedirs(path, exist_ok=True),
                remove_file=lambda path: os.remove(path) if os.path.isfile(path) else None)
            downloader = types.ModuleType('resources.libs.downloader')
            downloader.Downloader = lambda **_kw: types.SimpleNamespace(
                download=lambda _url, dest: shutil.copyfile(archive, dest))
            libs = types.ModuleType('resources.libs')
            libs.common = common
            libs.downloader = downloader
            resources = types.ModuleType('resources')
            resources.libs = libs
            xbmc = types.ModuleType('xbmc')
            xbmc.LOGINFO = 1
            xbmc.LOGERROR = 4
            xbmc.sleep = lambda *_a: None
            xbmc.getSkinDir = lambda: 'skin.fentastic'
            modules = {
                'resources': resources, 'resources.libs': libs,
                'resources.libs.common': common,
                'resources.libs.common.config': common.config,
                'resources.libs.common.logging': log,
                'resources.libs.downloader': downloader,
                'xbmc': xbmc,
            }
            original_apply = config_apply._apply_file

            def fail_second(spec, src_dir, fresh):
                if spec['src'] == 'b.txt':
                    raise OSError('injected write failure')
                return original_apply(spec, src_dir, fresh)

            manifest = {'config': {'config_version': '2.0.7',
                                   'zip': 'file:///test/pack.zip'}}
            with patch.dict(sys.modules, modules), patch.object(
                    config_apply, '_seed_legacy_favourites_baseline', return_value=False), patch.object(
                    config_apply, '_apply_file', side_effect=fail_second), patch.object(
                    config_apply, '_download_config_zip',
                    side_effect=lambda _url, dest: shutil.copyfile(archive, dest)):
                result = config_apply.apply_config_pack(manifest, fresh=False)
            self.assertFalse(result['applied'])
            self.assertEqual((userdata / 'a.txt').read_text('utf-8'), 'user A')
            self.assertEqual((userdata / 'b.txt').read_text('utf-8'), 'user B')
            self.assertNotIn('config_applied_version', settings)
            self.assertFalse(list(packages.glob('config-rollback-*')))


if __name__ == '__main__':
    unittest.main()
