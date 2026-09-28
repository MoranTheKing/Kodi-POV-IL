"""Exercise the Wizard's one-time legacy favourites baseline hand-off."""

import importlib.util
import json
import shutil
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
CONFIG_APPLY = ROOT / 'plugin.program.kodipovilwizard/resources/libs/config_apply.py'
ORDER_ADDON = ROOT / 'plugin.program.orderfavourites-hebrew'
spec = importlib.util.spec_from_file_location('config_apply_test', CONFIG_APPLY)
config_apply = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_apply)


class LegacyFavouritesMigrationTests(unittest.TestCase):
    def test_upgrade_adds_missing_settings_without_resetting_user_choices(self):
        policy = json.loads((ROOT / 'userdata/config_policy.json').read_text('utf-8'))
        destinations = {'userdata/guisettings.xml',
                        'userdata/addon_data/skin.fentastic/settings.xml',
                        'userdata/addon_data/plugin.video.pov/settings.xml'}
        matched = [item for item in policy['files']
                   if item['dest'] in destinations]
        self.assertEqual({item['dest'] for item in matched}, destinations)
        modes = {item['dest']: item['update'] for item in matched}
        self.assertEqual(modes['userdata/guisettings.xml'], 'seed_if_absent')
        self.assertTrue(all(modes[dest] == 'merge_missing_id' for dest in
                            destinations - {'userdata/guisettings.xml'}))
        original = ('<settings><setting id="lookandfeel.skin">skin.povil.nox'
                    '</setting><setting id="custom">personal</setting></settings>')
        incoming = ('<settings><setting id="lookandfeel.skin">skin.fentastic'
                    '</setting><setting id="new_feature">on</setting></settings>')
        merged = config_apply.merge_settings_xml(
            original, incoming, overwrite_existing=False)
        self.assertIn('skin.povil.nox', merged)
        self.assertNotIn('skin.fentastic', merged)
        self.assertIn('personal', merged)
        self.assertIn('new_feature', merged)
        self.assertEqual(merged.count('id="lookandfeel.skin"'), 1)

    def test_upgrade_preserves_existing_navigation_views_widgets_and_cache_tuning(self):
        policy = json.loads((ROOT / 'userdata/config_policy.json').read_text('utf-8'))
        protected = {'advancedsettings.xml', 'navigator.db', 'views.db',
                     'cpath_cache.db'}
        specs = [item for item in policy['files']
                 if Path(item['src']).name in protected]
        self.assertEqual({Path(item['src']).name for item in specs}, protected)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            fake_xbmc = types.ModuleType('xbmc')
            fake_xbmc.LOGWARNING = 2
            fake_logs = types.ModuleType('resources.libs.common.logging')
            fake_logs.log = lambda *_a, **_kw: None
            fake_common = types.ModuleType('resources.libs.common')
            fake_common.logging = fake_logs
            fake_libs = types.ModuleType('resources.libs')
            fake_libs.common = fake_common
            fake_resources = types.ModuleType('resources')
            fake_resources.libs = fake_libs
            modules = {'xbmc': fake_xbmc, 'resources': fake_resources,
                       'resources.libs': fake_libs,
                       'resources.libs.common': fake_common,
                       'resources.libs.common.logging': fake_logs}
            with patch.dict(sys.modules, modules):
                for item in specs:
                    src = ROOT / 'userdata' / item['src']
                    dest = root / item['dest']
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    user_data = b'user changes must survive the upgrade'
                    dest.write_bytes(user_data)
                    with patch.object(config_apply, '_home_path',
                                      return_value=str(dest)):
                        self.assertIsNone(config_apply._apply_file(
                            item, str(ROOT / 'userdata'), fresh=False))
                        self.assertEqual(dest.read_bytes(), user_data)
                        dest.unlink()
                        self.assertEqual(config_apply._apply_file(
                            item, str(ROOT / 'userdata'), fresh=False), str(dest))
                        self.assertEqual(dest.read_bytes(), src.read_bytes())

    def test_old_skin_seed_is_stored_without_touching_user_favourites(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            userdata = home / 'userdata'
            seed = home / 'media/builds_favourites_xml/skin.fentastic/favourites.xml'
            seed.parent.mkdir(parents=True)
            seed.write_text('<favourites><favourite name="POV" thumb="old.png">'
                            'RunAddon("plugin.video.pov")</favourite></favourites>',
                            encoding='utf-8')
            userdata.mkdir()
            installed = userdata / 'favourites.xml'
            installed.write_text('<favourites><favourite name="My own" thumb="x.png">'
                                 'RunAddon("mine")</favourite></favourites>',
                                 encoding='utf-8')

            config = types.ModuleType('resources.libs.common.config')
            config.CONFIG = types.SimpleNamespace(HOME=str(home), USERDATA=str(userdata))
            logs = types.ModuleType('resources.libs.common.logging')
            logs.log = lambda *_a, **_kw: None
            common = types.ModuleType('resources.libs.common')
            common.logging = logs
            libs = types.ModuleType('resources.libs')
            libs.common = common
            resources = types.ModuleType('resources')
            resources.libs = libs
            addon = types.ModuleType('xbmcaddon')
            addon.Addon = lambda _id: types.SimpleNamespace(
                getAddonInfo=lambda _key: str(ORDER_ADDON))
            vfs = types.ModuleType('xbmcvfs')
            vfs.translatePath = lambda special: (
                str(home / 'profile' / special.rsplit('/', 1)[-1])
                if special.startswith('special://profile/') else special)
            modules = {'resources': resources, 'resources.libs': libs,
                       'resources.libs.common': common,
                       'resources.libs.common.config': config,
                       'resources.libs.common.logging': logs,
                       'xbmcaddon': addon, 'xbmcvfs': vfs}
            with patch.dict(sys.modules, modules):
                self.assertTrue(config_apply._seed_legacy_favourites_baseline(
                    'skin.fentastic'))
                self.assertFalse(config_apply._seed_legacy_favourites_baseline(
                    'skin.fentastic'))
            self.assertIn('My own', installed.read_text('utf-8'))
            state = home / 'profile/favourites_state.json'
            self.assertEqual(json.loads(state.read_text('utf-8'))['baseline'],
                             seed.read_text('utf-8'))

    def test_malformed_installed_settings_are_not_erased(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / 'settings.xml').write_text('<settings><broken', 'utf-8')
            incoming = root / 'pack'
            incoming.mkdir()
            (incoming / 'settings.xml').write_text(
                '<settings><setting id="new">yes</setting></settings>', 'utf-8')
            fake_xbmc = types.ModuleType('xbmc')
            fake_xbmc.LOGWARNING = 2
            fake_logs = types.ModuleType('resources.libs.common.logging')
            fake_logs.log = lambda *_a, **_kw: None
            fake_common = types.ModuleType('resources.libs.common')
            fake_common.logging = fake_logs
            fake_libs = types.ModuleType('resources.libs')
            fake_libs.common = fake_common
            fake_resources = types.ModuleType('resources')
            fake_resources.libs = fake_libs
            modules = {'xbmc': fake_xbmc, 'resources': fake_resources,
                       'resources.libs': fake_libs,
                       'resources.libs.common': fake_common,
                       'resources.libs.common.logging': fake_logs}
            with patch.dict(sys.modules, modules), patch.object(
                    config_apply, '_home_path', return_value=str(root / 'settings.xml')):
                with self.assertRaises(ValueError):
                    config_apply._apply_file(
                        {'src': 'settings.xml', 'dest': 'userdata/settings.xml',
                         'update': 'merge_id'}, str(incoming), False)
            self.assertEqual((root / 'settings.xml').read_text('utf-8'),
                             '<settings><broken')

    def test_interrupted_copy_preserves_previous_database(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            src = root / 'new.db'
            dest = root / 'installed.db'
            src.write_bytes(b'new database')
            dest.write_bytes(b'user database')
            with patch.object(config_apply.os, 'replace', side_effect=OSError('busy')):
                with self.assertRaises(OSError):
                    config_apply._atomic_copy(str(src), str(dest))
            self.assertEqual(dest.read_bytes(), b'user database')
            self.assertEqual(list(root.glob('.config-*')), [])

    def test_partial_config_pack_never_marks_version_applied(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            incoming_zip = root / 'input.zip'
            policy = {'files': [{'src': 'missing.db',
                                 'dest': 'userdata/missing.db',
                                 'update': 'replace'}]}
            with zipfile.ZipFile(incoming_zip, 'w') as bundle:
                bundle.writestr('config_policy.json', json.dumps(policy))
            settings = {}
            config = types.SimpleNamespace(
                PACKAGES=str(root / 'packages'), HOME=str(root),
                USERDATA=str(root / 'userdata'),
                get_setting=lambda key: settings.get(key),
                set_setting=lambda key, value: settings.__setitem__(key, value))
            fake_xbmc = types.ModuleType('xbmc')
            fake_xbmc.LOGINFO = 1
            fake_xbmc.LOGWARNING = 2
            fake_xbmc.LOGERROR = 3
            fake_xbmc.sleep = lambda _ms: None
            fake_xbmc.getSkinDir = lambda: 'skin.estuary'
            fake_logging = types.ModuleType('resources.libs.common.logging')
            fake_logging.log = lambda *_a, **_kw: None
            fake_config = types.ModuleType('resources.libs.common.config')
            fake_config.CONFIG = config
            fake_tools = types.ModuleType('resources.libs.common.tools')
            fake_tools.ensure_folders = lambda path: Path(path).mkdir(parents=True, exist_ok=True)
            fake_tools.remove_file = lambda path: Path(path).unlink(missing_ok=True)
            fake_downloader = types.ModuleType('resources.libs.downloader')
            fake_downloader.Downloader = lambda **_kw: types.SimpleNamespace(
                download=lambda _url, path: shutil.copyfile(incoming_zip, path))
            common = types.ModuleType('resources.libs.common')
            common.config, common.logging, common.tools = (
                fake_config, fake_logging, fake_tools)
            libs = types.ModuleType('resources.libs')
            libs.common, libs.downloader = common, fake_downloader
            resources = types.ModuleType('resources')
            resources.libs = libs
            modules = {'xbmc': fake_xbmc, 'resources': resources,
                       'resources.libs': libs, 'resources.libs.common': common,
                       'resources.libs.common.config': fake_config,
                       'resources.libs.common.logging': fake_logging,
                       'resources.libs.common.tools': fake_tools,
                       'resources.libs.downloader': fake_downloader}
            with patch.dict(sys.modules, modules), patch.object(
                    config_apply, '_seed_legacy_favourites_baseline', return_value=False), patch.object(
                    config_apply, '_download_config_zip',
                    side_effect=lambda _url, path: shutil.copyfile(incoming_zip, path)):
                outcome = config_apply.apply_config_pack(
                    {'config': {'config_version': 'test', 'zip': 'local'}},
                    fresh=False)
            self.assertFalse(outcome['applied'])
            self.assertEqual(outcome['failed_files'], ['userdata/missing.db'])
            self.assertNotIn('config_applied_version', settings)


if __name__ == '__main__':
    unittest.main()
