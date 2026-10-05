"""Regressions for native profile setup and build navigation after skin changes."""
import importlib.util
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from test_provisioning_gate import _load_function, ROOT
from test_build_profiles import store, ARCHIVE

LIBS = ROOT / 'plugin.program.kodipovilwizard/resources/libs'


class SkinProfileCompletionTests(unittest.TestCase):
    def test_live_settings_save_uses_native_path_and_verifies_profile_skin(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'guisettings.xml'
            path.write_text('<settings><setting id="lookandfeel.skin">skin.estuary</setting></settings>')
            calls = []
            fn = _load_function(LIBS / 'build_skin.py', 'persist_live_settings',
                dict(ET=ET, xbmcvfs=types.SimpleNamespace(translatePath=lambda _: str(path)),
                     xbmc=types.SimpleNamespace(getSkinDir=lambda: 'skin.estuary',
                         executebuiltin=lambda *args: calls.append(args))))
            self.assertTrue(fn())
            self.assertEqual(calls, [('Skin.SetBool(POVIL.SettingsCommitted,true)', True)])
            path.write_text('<settings><setting id="lookandfeel.skin">skin.povil.nox</setting></settings>')
            self.assertFalse(fn())

    def test_estuary_build_pages_never_open_the_empty_native_library(self):
        root = ET.parse(ROOT / 'skin.estuary/xml/Home.xml').getroot()
        items = root.findall('.//control[@id="9000"]/content/item')
        self.assertEqual(items[0].findtext('label'), 'מסך הבית')
        for kind, action in (('movies', 'MovieList'), ('tvshows', 'TVShowList')):
            item = next(v for v in items if v.findtext("property[@name='id']") == kind)
            self.assertIn('plugin.video.pov', item.findtext('onclick'))
            self.assertIn(action, item.findtext('onclick'))
        power = (ROOT / 'skin.estuary/xml/DialogButtonMenu.xml').read_text('utf8')
        for route in ('mode=profiles', 'action=build_switch_skin', 'mode=myservices'):
            self.assertIn(route, power)

    def test_layout_defaults_restore_missing_helper_db_without_overwriting_custom_skin(self):
        with tempfile.TemporaryDirectory() as raw:
            profile = Path(raw)
            custom = profile / 'addon_data/skin.fentastic/settings.xml'
            custom.parent.mkdir(parents=True)
            custom.write_text('<settings><setting id="custom">KEEP</setting></settings>')
            calls = []
            libs = types.SimpleNamespace(profile_store=store,
                fentastic_widgets=types.SimpleNamespace(repair=lambda **kwargs: calls.append(kwargs)))
            def translate(path):
                return str(ARCHIVE if 'bootstrap' in path else profile)
            import hashlib, zipfile
            fn = _load_function(LIBS / 'build_skin.py', 'prepare_layout',
                dict(hashlib=hashlib, zipfile=zipfile,
                    xbmcvfs=types.SimpleNamespace(translatePath=translate),
                    xbmc=types.SimpleNamespace(getSkinDir=lambda: 'skin.fentastic')))
            with patch.dict('sys.modules', {'resources.libs': libs}):
                self.assertTrue(fn())
                self.assertTrue(fn())
            self.assertIn('KEEP', custom.read_text())
            self.assertTrue((profile / 'addon_data/script.fentastic.helper/cpath_cache.db').exists())
            self.assertFalse((profile / 'Database').exists())
            self.assertEqual(calls, [{'reload_skin': False}] * 2)

    def test_bootstrap_does_not_reenable_established_users_disabled_wizard(self):
        with tempfile.TemporaryDirectory() as raw:
            master = Path(raw); active = master / 'profiles/Guest'; active.mkdir(parents=True)
            (master / 'kodipovil.provisioned').write_text('1')
            (active / 'kodipovil.profile_home_ready').write_text('1')
            def translate(path):
                return str(master if 'masterprofile' in path else active)
            fn = _load_function(ROOT / 'plugin.program.kodipovilwizard/profile_bootstrap.py', 'resume',
                dict(os=__import__('os'), xbmcvfs=types.SimpleNamespace(translatePath=translate),
                     xbmc=types.SimpleNamespace(executeJSONRPC=lambda _q: self.fail('Must not modify established choices'))))
            self.assertFalse(fn())


if __name__ == '__main__':
    unittest.main()
