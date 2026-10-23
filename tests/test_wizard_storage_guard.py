"""Wizard 0.4.78: old add-on zips are pruned at start-up and a nearly full
device gets a Hebrew notice.

Field log, 24 Oct 2026 (LG webOS TV): "No space left on device" -- every
update failed and POV answered every search with no results. The QA Kodi held
820 MB of old zips in addons/packages (six Arctic Fuse 3 versions ~360 MB).
"""
import importlib.util
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard'
SOURCE = ROOT / 'resources/libs/storage_guard.py'


class StorageGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        self.addons = os.path.join(self.home, 'addons')
        self.packages = os.path.join(self.addons, 'packages')
        os.makedirs(self.packages)
        self.settings = {}
        self.notes = []
        config = types.SimpleNamespace(
            HOME=self.home, ADDONS=self.addons, PACKAGES=self.packages,
            ADDONTITLE='Kodi POV IL',
            get_setting=lambda key: self.settings.get(key, ''),
            set_setting=lambda key, value: self.settings.__setitem__(key, value))
        common = types.ModuleType('resources.libs.common')
        common.logging = types.SimpleNamespace(log=lambda *a, **k: None)
        common.config = types.SimpleNamespace(CONFIG=config)
        modules = {
            'xbmc': types.SimpleNamespace(LOGINFO=1, LOGWARNING=2),
            'xbmcgui': types.SimpleNamespace(Dialog=lambda: types.SimpleNamespace(
                notification=lambda heading, message, time=0: self.notes.append(('toast', message)),
                ok=lambda heading, message: self.notes.append(('dialog', message)))),
            'resources': types.ModuleType('resources'),
            'resources.libs': types.ModuleType('resources.libs'),
            'resources.libs.common': common,
            'resources.libs.common.logging': common.logging,
            'resources.libs.common.config': common.config,
        }
        patcher = mock.patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location('storage_guard_t', SOURCE)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def zip(self, name, size=1000, age=0):
        path = os.path.join(self.packages, name)
        with open(path, 'wb') as f:
            f.write(b'x' * size)
        if age:
            old = time.time() - age
            os.utime(path, (old, old))
        return path

    def installed(self, addon_id, version):
        os.makedirs(os.path.join(self.addons, addon_id))
        with open(os.path.join(self.addons, addon_id, 'addon.xml'), 'w', encoding='utf-8') as f:
            f.write('<addon id="{0}" name="x" version="{1}" provider-name="y">'.format(
                addon_id, version))

    def test_keeps_the_newest_and_the_installed_version_only(self):
        for v in ('3.3.12', '3.4.0', '3.4.6', '3.4.8', '3.4.10'):
            self.zip('skin.arctic.fuse.3-{0}.zip'.format(v), age=7200)
        self.installed('skin.arctic.fuse.3', '3.4.6')
        self.zip('script.module.acctmgr-1.2.0a.zip', age=7200)
        self.zip('script.module.acctmgr-1.2.1.zip', age=7200)
        self.zip('plugin.video.pov-6.10.21.zip', age=7200)
        removed, freed = self.mod.prune_packages(self.packages, self.addons)
        left = sorted(os.listdir(self.packages))
        self.assertEqual(left, ['plugin.video.pov-6.10.21.zip',
                                'script.module.acctmgr-1.2.1.zip',
                                'skin.arctic.fuse.3-3.4.10.zip',
                                'skin.arctic.fuse.3-3.4.6.zip'])
        self.assertEqual((removed, freed), (4, 4000))

    def test_our_stale_downloads_go_and_other_names_stay(self):
        self.zip('Kodi POV IL - FENtastic_quick_update.zip', age=7200)
        self.zip('plugin.video.pov_update.zip', age=60)     # may be in use
        self.zip('my-backup.zip')
        self.mod.prune_packages(self.packages, self.addons)
        self.assertEqual(sorted(os.listdir(self.packages)),
                         ['my-backup.zip', 'plugin.video.pov_update.zip'])

    def test_a_zip_written_in_the_last_hour_is_never_touched(self):
        # Kodi's own repository update may be writing it; and "~beta" sorts
        # above the release in our order, below it in Kodi's.
        self.zip('plugin.video.x-1.0.0.zip', age=60)
        self.zip('plugin.video.x-1.0.0~beta1.zip', age=7200)
        self.mod.prune_packages(self.packages, self.addons)
        self.assertEqual(sorted(os.listdir(self.packages)),
                         ['plugin.video.x-1.0.0.zip', 'plugin.video.x-1.0.0~beta1.zip'])

    def test_versions_compare_as_numbers(self):
        key = self.mod._version_key
        self.assertGreater(key('3.4.10'), key('3.4.8'))
        self.assertGreater(key('1.2.1'), key('1.2.0a'))
        self.assertGreater(key('1.2.0a'), key('1.2.0'))

    def test_low_space_notice_once_a_day(self):
        with mock.patch.object(self.mod, 'free_bytes', return_value=50 * 1024 * 1024):
            self.mod.run_at_startup()
            self.mod.run_at_startup()
        self.assertEqual(len(self.notes), 1)
        kind, text = self.notes[0]
        self.assertEqual(kind, 'dialog')      # a toast is one scrolling line
        self.assertIn('נשארו 50MB', text)
        self.assertIn('תחזוקה, Cleaning Tools ואז Clear Packages', text)
        self.assertEqual(3, len(text.split('\n')))   # a 4th line is cut off
        for line in text.split('\n'):        # RTL: every line opens in Hebrew
            self.assertRegex(line[0], '[א-ת]')

    def test_a_stamp_in_the_future_does_not_hide_the_notice(self):
        self.settings[self.mod._WARN_SETTING] = str(int(time.time()) + 30 * 86400)
        with mock.patch.object(self.mod, 'free_bytes', return_value=50 * 1024 * 1024):
            self.mod.run_at_startup()
        self.assertEqual([n[0] for n in self.notes], ['dialog'])

    def test_no_dialog_over_a_playing_video(self):
        player = types.SimpleNamespace(isPlaying=lambda: True)
        with mock.patch.object(self.mod.xbmc, 'Player', lambda: player, create=True), \
                mock.patch.object(self.mod, 'free_bytes', return_value=50 * 1024 * 1024):
            self.mod.run_at_startup()
        self.assertEqual(self.notes, [])
        self.assertNotIn(self.mod._WARN_SETTING, self.settings)   # shown next start

    def test_enough_space_says_nothing(self):
        with mock.patch.object(self.mod, 'free_bytes', return_value=5 * 1024 ** 3):
            self.mod.run_at_startup()
        self.assertEqual(self.notes, [])

    def test_an_update_failing_for_space_warns_at_once(self):
        self.settings[self.mod._WARN_SETTING] = str(int(time.time()))   # warned today
        err = OSError(28, 'No space left on device')
        with mock.patch.object(self.mod, 'free_bytes', return_value=1024 * 1024):
            self.assertTrue(self.mod.note_failure(err))
            self.mod.note_failure(err)                  # once per session
            self.assertFalse(self.mod.note_failure(ValueError('bad zip')))
        self.assertEqual(self.notes, [('toast', 'העדכון נכשל: אין מקום פנוי במכשיר')])

    def test_the_toast_does_not_postpone_the_daily_dialog(self):
        err = OSError(28, 'No space left on device')
        with mock.patch.object(self.mod, 'free_bytes', return_value=1024 * 1024):
            self.mod.note_failure(err)
        self.assertNotIn(self.mod._WARN_SETTING, self.settings)

    def test_startup_prunes_before_the_update_check(self):
        text = (ROOT / 'startup.py').read_text(encoding='utf-8')
        self.assertLess(text.index('storage_guard.run_at_startup()'),
                        text.index('_mu.run_update_check()'))
        updater = (ROOT / 'resources/libs/modular_updater.py').read_text(encoding='utf-8')
        # download, MoranSubs staging, unpacking
        self.assertEqual(updater.count('self._note_storage_failure('), 3)
        settings = (ROOT / 'resources/settings.xml').read_text(encoding='utf-8')
        self.assertIn('id="storage_low_warned"', settings)


if __name__ == '__main__':
    unittest.main()
