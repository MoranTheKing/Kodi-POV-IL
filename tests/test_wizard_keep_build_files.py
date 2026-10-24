"""Wizard 0.4.82: a shortcut folder the user deleted stays deleted.

POV's remove_old_databases (modules/cache.py), run by its database maintenance
every three days, deletes every file in its data folder that is not one of
POV's own databases -- including the build's povil-shortcuts-defaults-v1.json
receipt. Without the receipt every start seeded the build's shortcut folders
again, so a folder the user had deleted came back (reproduced in the QA Kodi,
24 Oct 2026). A POV patch now keeps the build's files, and the receipt has a
second copy in the Wizard's own folder.
"""
import importlib.util
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

WIZ = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard'
ENGINE = WIZ / 'resources/libs/patch_engine.py'
CONFIG = WIZ / 'resources/libs/patches/patches_config.py'
PATCHES = WIZ / 'resources/libs/patches'

# POV 6.10.22 modules/cache.py, the function the patch goes into.
POV_CACHE = (
    "from modules import kodi_utils\n"
    "databases_path = kodi_utils.databases_path\n"
    "\n"
    "def remove_old_databases():\n"
    "\tcurrent_dbs = kodi_utils.current_dbs()\n"
    "\tfiles = kodi_utils.list_dirs(databases_path)[1]\n"
    "\tfor item in files:\n"
    "\t\tif item not in current_dbs:\n"
    "\t\t\ttry: kodi_utils.delete_file(databases_path + item)\n"
    "\t\t\texcept: pass\n")


def _load(name, path, modules=None):
    with patch.dict(sys.modules, modules or {}):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class KeepBuildFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addon = Path(self.tmp.name) / 'plugin.video.pov'
        (self.addon / 'resources/lib/modules').mkdir(parents=True)
        self.cache = self.addon / 'resources/lib/modules/cache.py'
        self.cache.write_text(POV_CACHE, encoding='utf-8')
        xbmc = types.ModuleType('xbmc')
        xbmc.LOGDEBUG, xbmc.LOGINFO, xbmc.LOGWARNING, xbmc.LOGERROR = range(4)
        xbmcaddon = types.ModuleType('xbmcaddon')
        xbmcaddon.Addon = lambda: types.SimpleNamespace(getSetting=lambda _key: '')
        xbmcvfs = types.ModuleType('xbmcvfs')
        home = 'special://home/addons/'

        def translate(value):
            if value.startswith(home + 'plugin.video.pov'):
                return str(self.addon) + value[len(home + 'plugin.video.pov'):]
            if value.startswith(home + 'plugin.program.kodipovilwizard/resources/libs/patches/'):
                return str(PATCHES) + '/'
            return value
        xbmcvfs.translatePath = translate
        common = types.ModuleType('resources.libs.common')
        logging = types.ModuleType('resources.libs.common.logging')
        logging.log = lambda *_a, **_k: None
        common.logging = logging
        self.modules = {'xbmc': xbmc, 'xbmcaddon': xbmcaddon, 'xbmcvfs': xbmcvfs,
                        'resources': types.ModuleType('resources'),
                        'resources.libs': types.ModuleType('resources.libs'),
                        'resources.libs.common': common,
                        'resources.libs.common.logging': logging}
        self.engine = _load('keep_engine', ENGINE, self.modules)
        config = _load('keep_config', CONFIG, self.modules).PATCH_CONFIG
        self.entry = next(e for e in config if e['id'] == 'pov_keep_build_files')

    def test_pov_cleanup_keeps_the_build_files_and_still_removes_strays(self):
        with patch.dict(sys.modules, self.modules):
            stats = self.engine.PatchEngine([self.entry]).run()
        self.assertEqual(1, stats['applied'])
        deleted = []
        files = ['watched.db', 'navigator.db', 'povil-shortcuts-defaults-v1.json',
                 'navigator.before-build-shortcuts-v1.db', 'navigator.before-catalogue-v2.db',
                 'povil_dropped_trakt.json',
                 'povil_dropped_trakt.json.lock.db', 'old.pov.db']
        kodi_utils = types.SimpleNamespace(
            databases_path='data/',
            current_dbs=lambda: {'settings.xml', 'watched.db', 'navigator.db'},
            list_dirs=lambda _p: ([], files),
            delete_file=deleted.append)
        modules = types.ModuleType('modules')
        modules.kodi_utils = kodi_utils
        with patch.dict(sys.modules, dict(self.modules, modules=modules,
                                          **{'modules.kodi_utils': kodi_utils})):
            sys.modules.pop('pov_keep_files', None)
            cache = _load('patched_cache', self.cache)
            cache.remove_old_databases()
        sys.modules.pop('pov_keep_files', None)
        self.assertEqual(['data/old.pov.db'], deleted)

    def menu(self, profile, folders=1):
        path = profile / 'addon_data/plugin.video.pov/navigator.db'
        conn = sqlite3.connect(path)
        try:
            conn.execute('CREATE TABLE IF NOT EXISTS navigator (list_name text, '
                         'list_type text, list_contents text)')
            conn.executemany('INSERT INTO navigator VALUES (?,?,?)',
                             [('f%d' % i, 'shortcut_folder', '[]') for i in range(folders)])
            conn.commit()
        finally:
            conn.close()

    def test_the_receipt_lives_in_the_wizard_folder_too(self):
        store = _load('keep_store', WIZ / 'resources/libs/profile_store.py')
        profile = Path(self.tmp.name) / 'profile'
        pov_copy = profile / 'addon_data/plugin.video.pov/povil-shortcuts-defaults-v1.json'
        wiz_copy = profile / 'addon_data/plugin.program.kodipovilwizard/povil-shortcuts-defaults-v1.json'
        self.assertFalse(store.shortcuts_seeded(str(profile)))
        pov_copy.parent.mkdir(parents=True)
        self.menu(profile)
        pov_copy.write_text(json.dumps({'version': 1}), encoding='utf-8')
        self.assertTrue(store.shortcuts_seeded(str(profile)))   # old receipt counts ...
        self.assertTrue(wiz_copy.is_file())                     # ... and is mirrored
        pov_copy.unlink()                                       # POV's clean-up
        self.assertTrue(store.shortcuts_seeded(str(profile)))   # still seeded
        self.assertTrue(pov_copy.is_file())                     # and put back

    def test_a_wiped_pov_folder_is_seeded_again(self):
        # Remove Addon Data / POV reinstalled: the Wizard's copy survives, POV's
        # menu is new and empty -- the build's folders must come back.
        store = _load('keep_store2', WIZ / 'resources/libs/profile_store.py')
        profile = Path(self.tmp.name) / 'profile'
        wiz_copy = profile / 'addon_data/plugin.program.kodipovilwizard/povil-shortcuts-defaults-v1.json'
        wiz_copy.parent.mkdir(parents=True)
        wiz_copy.write_text(json.dumps({'version': 1}), encoding='utf-8')
        self.assertFalse(store.shortcuts_seeded(str(profile)))  # no navigator.db
        (profile / 'addon_data/plugin.video.pov').mkdir(parents=True)
        self.menu(profile, folders=0)
        self.assertFalse(store.shortcuts_seeded(str(profile)))  # empty menu
        self.assertFalse((profile / 'addon_data/plugin.video.pov/'
                          'povil-shortcuts-defaults-v1.json').exists())


if __name__ == '__main__':
    unittest.main()
