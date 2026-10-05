"""Reproduce the FENtastic empty personal folders and interrupted OTA handoff."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bootstrap = load('legacy_recovery_bootstrap', 'tools/legacy_bridge/modular_legacy_bootstrap.py')
reader = load('legacy_recovery_reader', 'tools/legacy_bridge/pov_navigator_read_patcher.py')
builder = load('legacy_recovery_builder', 'tools/refresh_legacy_bridge.py')


def wizard_zip(path):
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in {
            'addon.xml': '<addon id="plugin.program.kodipovilwizard" version="0.4.31"/>',
            'startup.py': 'pass\n', 'resources/libs/wizard.py': 'pass\n',
            'resources/libs/modular_updater.py': 'pass\n',
            'resources/libs/patches/pov_nav_read_fix.py': 'pass\n',
        }.items():
            z.writestr('plugin.program.kodipovilwizard/' + name, data)
    return bootstrap._sha256(path)


class FentasticLegacyRecoveryTests(unittest.TestCase):
    def _old_install(self, root):
        addons = root / 'addons'
        for name, value in ((bootstrap.WIZARD_ID, 'live old'), (bootstrap.ROLLBACK, 'previous backup')):
            tree = addons / name
            tree.mkdir(parents=True)
            (tree / 'addon.xml').write_text('<addon id="plugin.program.kodipovilwizard" version="0.1.48"/>')
            (tree / 'retain.txt').write_text(value)
        profile = root / 'userdata/addon_data/plugin.video.pov/settings.xml'
        profile.parent.mkdir(parents=True)
        profile.write_bytes(b'<settings>keep-services-and-user-settings</settings>')
        archive = root / 'wizard.zip'
        digest = wizard_zip(archive)
        return addons, archive, digest, profile

    def test_live_old_wizard_and_stale_rollback_do_not_block_ota(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            addons, archive, digest, profile = self._old_install(root)
            result, backup = bootstrap.install_staged_wizard(archive, digest, '0.4.31', addons)
            self.assertEqual(result, 'installed')
            self.assertIn('0.4.31', (addons / bootstrap.WIZARD_ID / 'addon.xml').read_text())
            self.assertEqual((Path(backup) / 'retain.txt').read_text(), 'live old')
            histories = list(addons.glob(bootstrap.ROLLBACK + '.history-*'))
            self.assertEqual(len(histories), 1)
            self.assertEqual((histories[0] / 'retain.txt').read_text(), 'previous backup')
            self.assertEqual(profile.read_bytes(), b'<settings>keep-services-and-user-settings</settings>')
            self.assertEqual(bootstrap.install_staged_wizard(archive, digest, '0.4.31', addons)[0], 'already_installed')
            self.assertEqual(len(list(addons.glob(bootstrap.ROLLBACK + '.history-*'))), 1)

    def test_failed_activation_restores_live_and_retains_previous_backup(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            addons, archive, digest, _ = self._old_install(root)
            original = bootstrap.os.replace

            def fail_activation(source, target):
                if '.kodipovil-wizard-stage-' in str(source):
                    raise OSError('activation interrupted')
                return original(source, target)

            with patch.object(bootstrap.os, 'replace', side_effect=fail_activation):
                with self.assertRaisesRegex(OSError, 'interrupted'):
                    bootstrap.install_staged_wizard(archive, digest, '0.4.31', addons)
            self.assertEqual((addons / bootstrap.WIZARD_ID / 'retain.txt').read_text(), 'live old')
            self.assertEqual(len(list(addons.glob(bootstrap.ROLLBACK + '.history-*'))), 1)
            self.assertEqual(bootstrap.install_staged_wizard(archive, digest, '0.4.31', addons)[0], 'installed')

    def test_bad_archive_never_moves_live_or_previous_backup(self):
        with tempfile.TemporaryDirectory() as raw:
            addons, archive, _, _ = self._old_install(Path(raw))
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                bootstrap.install_staged_wizard(archive, '0' * 64, '0.4.31', addons)
            self.assertEqual((addons / bootstrap.ROLLBACK / 'retain.txt').read_text(), 'previous backup')
            self.assertEqual((addons / bootstrap.WIZARD_ID / 'retain.txt').read_text(), 'live old')

    def test_repeated_legacy_note_never_downgrades_a_newer_modular_wizard(self):
        with tempfile.TemporaryDirectory() as raw:
            addons, archive, digest, _ = self._old_install(Path(raw))
            live = addons / bootstrap.WIZARD_ID
            (live / 'addon.xml').write_text('<addon id="plugin.program.kodipovilwizard" version="0.4.32"/>')
            self.assertEqual(bootstrap.install_staged_wizard(archive, digest, '0.4.31', addons)[0], 'already_newer')
            self.assertIn('0.4.32', (live / 'addon.xml').read_text())
            self.assertEqual(list(addons.glob(bootstrap.ROLLBACK + '.history-*')), [])

    def test_service_completes_requested_ota_after_real_restart_with_stale_backup(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            addons, archive, digest, _ = self._old_install(root)
            service = addons / bootstrap.SERVICE_ID / 'resources'
            service.mkdir(parents=True)
            (service / 'modular_wizard_stage1.zip').write_bytes(archive.read_bytes())
            userdata = root / 'userdata'
            (userdata / bootstrap.REQUEST).write_text(json.dumps({'version': '0.4.31', 'sha256': digest}))
            pid = [100]
            vfs = types.SimpleNamespace(translatePath=lambda p: str(root / p.removeprefix('special://home/')))
            kodi = types.SimpleNamespace(getCondVisibility=lambda _: False, log=lambda *_: None, LOGERROR=3)
            addons_api = types.SimpleNamespace(Addon=lambda _: object())
            with patch.object(bootstrap, 'xbmcvfs', vfs), patch.object(bootstrap, 'xbmc', kodi), \
                    patch.object(bootstrap, 'xbmcaddon', addons_api), patch.object(bootstrap, 'xbmcgui', None), \
                    patch.object(bootstrap.os, 'getpid', side_effect=lambda: pid[0]):
                self.assertEqual(bootstrap.ensure_bootstrapped(), 'deferred_restart')
                self.assertEqual(bootstrap.ensure_bootstrapped(), 'deferred_restart')
                pid[0] = 200
                self.assertEqual(bootstrap.ensure_bootstrapped(), 'installed')
                self.assertEqual(bootstrap.ensure_bootstrapped(), 'ready')
            self.assertFalse((userdata / bootstrap.REQUEST).exists())
            self.assertEqual(json.loads((userdata / bootstrap.READY).read_text())['version'], '0.4.31')
            self.assertIn('0.4.31', (addons / bootstrap.WIZARD_ID / 'addon.xml').read_text())

    def test_unrelated_backup_is_never_moved(self):
        with tempfile.TemporaryDirectory() as raw:
            addons, archive, digest, _ = self._old_install(Path(raw))
            (addons / bootstrap.ROLLBACK / 'addon.xml').write_text('<addon id="unrelated"/>')
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                bootstrap.install_staged_wizard(archive, digest, '0.4.31', addons)
            self.assertEqual((addons / bootstrap.WIZARD_ID / 'retain.txt').read_text(), 'live old')
            self.assertEqual(list(addons.glob(bootstrap.ROLLBACK + '.history-*')), [])

    def test_upstream_context_readers_recover_shipped_personal_and_genre_rows(self):
        source = ('class NavigatorCache(BaseCache):\n' + reader._OLD_GET_LIST_CONTEXT + '\n\n' + reader._OLD_FOLDER_CONTEXT + '\n')
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'navigator_cache.py'
            path.write_text(source)
            with patch.object(reader, '_nav_cache_path', return_value=str(path)):
                self.assertEqual(reader.ensure_patched(), 'patched')
                self.assertEqual(reader.ensure_patched(), 'already_patched')
            ns = {'BaseCache': object, 'GET_LIST': 'SELECT list_contents FROM navigator WHERE list_name=? AND list_type=?',
                  'GET_FOLDER_CONTENTS': 'SELECT list_contents FROM navigator WHERE list_name=? AND list_type=?'}
            exec(compile(path.read_text(), str(path), 'exec'), ns)
            cls = ns['NavigatorCache']
            cls.__enter__ = lambda self: self
            cls.__exit__ = lambda *_: None
            db = ROOT / 'userdata/addon_data/plugin.video.pov/navigator.db'
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            with sqlite3.connect('file:' + db.as_posix() + '?mode=ro', uri=True) as con:
                cache = cls()
                cache.dbcur, cache.jsloads = con.cursor(), json.loads
                rows = con.execute("SELECT list_name FROM navigator WHERE list_name LIKE 'FENtastic%' AND list_type='shortcut_folder'").fetchall()
                self.assertEqual(len(rows), 4)
                for (name,) in rows:
                    contents = cache.get_shortcut_folder_contents(name)
                    self.assertGreater(len(contents), 0, name)
                    self.assertEqual(contents, cache.get_list(name, 'shortcut_folder'))
                    if 'אישי' in name:
                        self.assertEqual(len(contents), 5)
                        self.assertTrue(any('(Trakt)' in row['name'] for row in contents))
                self.assertEqual(cache.get_shortcut_folder_contents('missing'), [])
                self.assertIsNone(cache.get_list('missing', 'default'))
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before)

    def test_modular_reader_handles_same_legacy_rows_without_account_manager(self):
        xbmc = types.SimpleNamespace(log=lambda *_: None, LOGINFO=1, LOGERROR=3)
        with patch.dict(sys.modules, {'xbmc': xbmc}):
            modern = load('modern_nav_recovery', 'plugin.program.kodipovilwizard/resources/libs/patches/pov_nav_read_fix.py')
        cache = types.SimpleNamespace(jsloads=json.loads)
        modern.run(cache)
        for rows in ([{'name': 'הסרטים שלי', 'connected': True}], [{'name': 'הסדרות שלי', 'connected': False}]):
            self.assertEqual(cache.jsloads(repr(rows)), rows)
            self.assertEqual(cache.jsloads(json.dumps(rows)), rows)
        with self.assertRaises(Exception):
            cache.jsloads('__import__("os").getcwd()')

    def test_bridge_refresh_preserves_all_other_members_and_credentials(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            wizard = root / 'wizard.zip'
            sha = wizard_zip(wizard)
            previous = root / 'previous.zip'
            entries = {builder.STAGED: b'old archive', builder.REQUEST: b'old request',
                       builder.SERVICE + 'resources/lib/pool.py': b'unchanged fixture credential',
                       'userdata/favourites.xml': b'old favourites', 'addons/skin.fentastic/addon.xml': b'old skin'}
            for name in builder.REPAIRS:
                entries[builder.SERVICE + 'resources/lib/' + name] = b'old repair'
            with zipfile.ZipFile(previous, 'w') as z:
                for name, data in entries.items():
                    z.writestr(name, data)
            output = root / 'new.zip'
            report = builder.build(previous, wizard, output, bootstrap._sha256(previous), sha)
            self.assertEqual(len(report['changed']), 4)
            with zipfile.ZipFile(output) as z:
                self.assertEqual(z.namelist(), list(entries))
                self.assertEqual(z.read(builder.STAGED), wizard.read_bytes())
                self.assertEqual(json.loads(z.read(builder.REQUEST))['version'], '0.4.31')
                for name, data in entries.items():
                    if name not in report['changed']:
                        self.assertEqual(z.read(name), data)


if __name__ == '__main__':
    unittest.main()
