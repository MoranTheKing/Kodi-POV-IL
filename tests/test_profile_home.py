"""Inactive home preparation must stay inside the target and use its accounts."""
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from test_build_profiles import ROOT, LIBS, ARCHIVE, store
from test_provisioning_gate import _load_function


class ProfileHomeTests(unittest.TestCase):
    def test_prepared_home_is_current_and_does_not_touch_master(self):
        with tempfile.TemporaryDirectory() as raw:
            master = Path(raw)
            target = dict(id=1, directory='profiles/Viewer')
            (master / 'kodipovil.provisioned').write_text('2.0.9')
            (master / 'favourites.xml').write_text('MASTER SENTINEL')
            store.seed_profile(str(master), target, str(ARCHIVE), prepare_login=True)
            dest = Path(store.profile_path(str(master), target))

            def translate(path):
                if path.startswith('special://profile/'):
                    return str(master / path[len('special://profile/'):])
                if path == 'special://home/addons/':
                    return str(ROOT)
                return path

            vfs = types.SimpleNamespace(translatePath=translate,
                exists=lambda p: Path(translate(p)).exists(),
                File=lambda p, mode='r': open(translate(p), mode, encoding='utf8'))
            sdk = types.SimpleNamespace(getCondVisibility=lambda _p: True,
                log=lambda *_a: None, LOGINFO=1, LOGWARNING=2, LOGERROR=3)
            libs = types.ModuleType('resources.libs')
            libs.profile_store = store
            patches = types.ModuleType('resources.libs.patches')
            # Use the production source IDs without loading Kodi's active cache.
            import ast
            tree = ast.parse((LIBS / 'patches/pov_visibility_mgr.py').read_text('utf8'))
            sources = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                           and any(isinstance(t, ast.Name) and t.id == '_SOURCES' for t in n.targets))
            patches.pov_visibility_mgr = types.SimpleNamespace(_SOURCES=ast.literal_eval(sources))
            atomic = _load_function(LIBS / 'parental_profiles.py', 'atomic_write',
                dict(os=os, tempfile=tempfile))
            modules = {'xbmc': sdk, 'xbmcvfs': vfs,
                'xbmcaddon': types.SimpleNamespace(Addon=lambda _id:
                    types.SimpleNamespace(getAddonInfo=lambda _key: '0.4.29')),
                'resources': types.ModuleType('resources'), 'resources.libs': libs,
                'resources.libs.patches': patches,
                'resources.libs.parental_profiles': types.SimpleNamespace(atomic_write=atomic)}
            spec = importlib.util.spec_from_file_location('profile_home_test', LIBS / 'profile_home.py')
            home = importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules, modules):
                spec.loader.exec_module(home)
                home.prepare(str(master), target)
                first = (dest / 'favourites.xml').read_text('utf8')
                self.assertIn('mode=profiles', first)
                self.assertIn('action=tonight', first)
                self.assertIn('mode=recentupdates', first)
                self.assertNotIn('mdblist_my_tvshows', first)
                settings = dest / 'addon_data/plugin.video.pov/settings.xml'
                settings.parent.mkdir(parents=True, exist_ok=True)
                settings.write_text('<settings><setting id="mdblist.token">QA</setting></settings>')
                home.prepare(str(master), target)
                self.assertIn('mdblist_my_tvshows', (dest / 'favourites.xml').read_text('utf8'))
                self.assertEqual((master / 'favourites.xml').read_text(), 'MASTER SENTINEL')
                self.assertFalse((master / 'addon_data/plugin.program.orderfavourites-hebrew').exists())
                with self.assertRaises(ValueError):
                    home.prepare(str(master), dict(id=0))
                (dest / 'kodipovil.profile_home_ready').write_text('1')
                (dest / 'favourites.xml').write_text('USER CHOICE')
                home.prepare(str(master), target)
                self.assertEqual((dest / 'favourites.xml').read_text(), 'USER CHOICE')
