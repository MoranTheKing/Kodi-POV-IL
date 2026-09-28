"""The visible POV MDBList row must still reach phone pairing after migration."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


FILE = (Path(__file__).resolve().parents[1] /
        'plugin.program.kodipovilwizard/resources/libs/patches/pov_myservices.py')


class _Item:
    def __init__(self):
        self.label = ''
        self.label2 = ''

    def setLabel(self, value):
        self.label = value

    def setLabel2(self, value):
        self.label2 = value

    def setArt(self, _value):
        pass


class MDBListMyServicesTests(unittest.TestCase):
    def test_myservices_row_opens_verified_pairing_action(self):
        calls = []
        addon = types.ModuleType('xbmcaddon')

        def get_addon(addon_id):
            if addon_id == 'script.module.acctmgr':
                raise RuntimeError('not installed')
            if addon_id == 'plugin.video.pov':
                return types.SimpleNamespace(getSetting=lambda _key: '')
            if addon_id == 'service.subtitles.kodipovilai':
                return object()
            raise AssertionError(addon_id)

        addon.Addon = get_addon
        xbmc = types.ModuleType('xbmc')
        xbmc.executebuiltin = calls.append
        gui = types.ModuleType('modules.kodi_utils')
        gui.media_path = lambda: ''
        gui.make_listitem = _Item
        gui.notification = Mock()
        gui.logger = Mock()
        items_seen = []

        def select(_title, items, useDetails=False):
            items_seen.extend(items)
            self.assertTrue(useDetails)
            return next(i for i, item in enumerate(items)
                        if item.label == 'MDBLIST')

        gui.dialog = types.SimpleNamespace(select=select)
        modules = types.ModuleType('modules')
        modules.kodi_utils = gui
        myservices = types.ModuleType('modules.myservices')
        stubs = {'xbmc': xbmc, 'xbmcaddon': addon, 'modules': modules,
                 'modules.kodi_utils': gui, 'modules.myservices': myservices}
        with patch.dict(sys.modules, stubs):
            spec = importlib.util.spec_from_file_location('wizard_myservices_test', FILE)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self.assertTrue(mod.get_authorize_override(Mock())())
        self.assertTrue(any(item.label == 'MDBLIST' for item in items_seen))
        self.assertEqual(calls, [
            'RunScript(service.subtitles.kodipovilai,action=connect_mdblist)'])


if __name__ == '__main__':
    unittest.main()
