"""Wizard 0.4.79: Maintenance > Cleaning Tools > "Auto Clean Up On Startup"
runs. The toggles were in the menu all along and nothing ever ran them.

Packages only. "Clear Cache on Startup" would delete every add-on's *cache*
folder at each start (MoranSubs keeps its AI translations in such folders),
and old_thumbs() finds nothing but VACUUMs the live Textures DB: both toggles
are hidden.
"""
import importlib.util
import os
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard'
SOURCE = ROOT / 'resources/libs/clear.py'


class AutoCleanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.packages = os.path.join(self.tmp.name, 'packages')
        os.makedirs(self.packages)
        self.settings = {}
        self.toasts = []
        self.config = types.SimpleNamespace(
            PACKAGES=self.packages, ADDONTITLE='Kodi POV IL', COLOR2='white',
            AUTOCLEANUP='true', AUTOPACKAGES='true', AUTOTHUMBS='false',
            AUTOCACHE='true', AUTOFREQ=3, AUTONEXTRUN='2019-01-01 00:00:00',   # int, as config.py
            set_setting=lambda key, value: self.settings.__setitem__(key, value))
        logging = types.SimpleNamespace(
            log=lambda *a, **k: None,
            log_notify=lambda title, msg, **k: self.toasts.append(msg))
        tools = types.SimpleNamespace(
            convert_size=lambda n: '{0} B'.format(n), get_size=lambda p: 0,
            clean_house=lambda p: (0, 0))
        common = types.ModuleType('resources.libs.common')
        common.logging = logging
        common.tools = tools
        common.config = types.SimpleNamespace(CONFIG=self.config)
        modules = {
            'xbmc': types.SimpleNamespace(LOGINFO=1, LOGWARNING=2, LOGERROR=4),
            'xbmcgui': types.SimpleNamespace(),
            'resources': types.ModuleType('resources'),
            'resources.libs': types.ModuleType('resources.libs'),
            'resources.libs.common': common,
            'resources.libs.common.config': common.config,
            'resources.libs.common.logging': logging,
            'resources.libs.common.tools': tools,
        }
        patcher = mock.patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location('clear_t', SOURCE)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.thumbs = []
        self.mod.old_thumbs = lambda *a, **k: self.thumbs.append(True)
        self.mod.clear_cache = lambda *a, **k: self.fail('cache must not be cleared')

    def zip(self, name, age):
        path = os.path.join(self.packages, name)
        with open(path, 'wb') as f:
            f.write(b'x' * 10)
        old = time.time() - age
        os.utime(path, (old, old))

    def test_switched_on_and_due_clears_old_packages_only(self):
        self.config.AUTOTHUMBS = 'true'         # hidden; must not run
        self.zip('skin.x-1.0.zip', age=7200)
        self.zip('skin.x-1.1.zip', age=1800)    # Kodi may still be unpacking it
        self.assertTrue(self.mod.auto_clean_startup())
        self.assertEqual(os.listdir(self.packages), ['skin.x-1.1.zip'])
        self.assertEqual(self.thumbs, [])
        nxt = datetime.strptime(self.settings['nextautocleanup'], '%Y-%m-%d %H:%M:%S')
        self.assertAlmostEqual((nxt - datetime.now()).days, 6, delta=1)   # weekly

    def test_off_does_nothing(self):
        self.config.AUTOCLEANUP = 'false'
        self.zip('skin.x-1.0.zip', age=7200)
        self.assertFalse(self.mod.auto_clean_startup())
        self.assertEqual(len(os.listdir(self.packages)), 1)

    def test_not_due_waits(self):
        self.config.AUTONEXTRUN = (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')
        self.zip('skin.x-1.0.zip', age=7200)
        self.assertFalse(self.mod.auto_clean_startup())
        self.assertEqual(len(os.listdir(self.packages)), 1)

    def test_every_startup_ignores_the_date(self):
        self.config.AUTOFREQ = 0                # was read as weekly ("0 or 3")
        self.config.AUTONEXTRUN = (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')
        self.assertTrue(self.mod.auto_clean_startup())
        nxt = datetime.strptime(self.settings['nextautocleanup'], '%Y-%m-%d %H:%M:%S')
        self.assertLess(abs((nxt - datetime.now()).total_seconds()), 60)

    def test_a_date_beyond_the_frequency_is_a_wrong_clock(self):
        self.config.AUTONEXTRUN = '2031-01-01 00:00:00'
        self.assertTrue(self.mod.auto_clean_startup())

    def test_nothing_to_remove_is_silent_and_one_bad_file_does_not_stop_the_rest(self):
        self.assertTrue(self.mod.auto_clean_startup())
        self.assertEqual(self.toasts, [])          # no "None Found!" at start-up
        self.zip('a-1.0.zip', age=7200)
        self.zip('b-1.0.zip', age=7200)
        real_unlink = os.unlink

        def unlink(path):
            if path.endswith('a-1.0.zip'):
                raise PermissionError(13, 'locked')
            real_unlink(path)
        with mock.patch.object(self.mod.os, 'unlink', unlink):
            self.mod.clear_packages_startup()
        self.assertEqual(os.listdir(self.packages), ['a-1.0.zip'])
        self.assertEqual(len(self.toasts), 1)

    def test_wired_at_startup_and_cache_toggle_hidden(self):
        startup = (ROOT / 'startup.py').read_text(encoding='utf-8')
        self.assertLess(startup.index('_clear.auto_clean_startup()'),
                        startup.index('storage_guard.run_at_startup()'))
        menu = (ROOT / 'resources/libs/gui/maintenance_menu.py').read_text(encoding='utf-8')
        self.assertNotIn("'name': 'clearcache'", menu)
        self.assertNotIn("'name': 'clearthumbs'", menu)
        self.assertIn("'name': 'clearpackages'", menu)
        settings = (ROOT / 'resources/settings.xml').read_text(encoding='utf-8')
        self.assertRegex(settings, r'id="clearcache"[^>]*visible="false"')
        self.assertRegex(settings, r'id="clearthumbs"[^>]*visible="false"')


if __name__ == '__main__':
    unittest.main()
