"""Wizard 0.4.77: CONFIG reads its start-up settings through ONE Addon object.

Each xbmcaddon.Addon() loads the settings file again; with Kodi's debug log on,
every load writes a "requested setting (x) was not found" line for each stale
key left by old Wizard versions. 57 loads per Wizard call flooded field logs
(measured in the QA Kodi: 6,555 such lines for one menu listing before, 227
after).
"""
import ast
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard'
SOURCE = ROOT / 'resources/libs/common/config.py'


class InitSettingsLoadsOnce(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Config')
        self.init = next(n for n in cls.body
                         if isinstance(n, ast.FunctionDef) and n.name == 'init_settings')

    def test_no_per_key_addon_construction(self):
        text = ast.unparse(self.init)
        self.assertNotIn('self.get_setting(', text)
        self.assertNotIn('xbmcaddon.Addon(', text)
        self.assertIn('self.ADDON.getSetting(key)', text)

    def test_every_setting_is_still_read(self):
        reads = []

        class Addon(object):
            def getSetting(self, key):
                reads.append(key)
                return 'true' if key == 'oldlog' else ''

        fake = types.SimpleNamespace(ADDON=Addon(), USERDATA='', PLUGIN_DATA='',
                                     HOME='', ADDON_ID='plugin.program.kodipovilwizard')
        module = ast.Module(body=[self.init], type_ignores=[])
        scope = {'os': __import__('os'), 'xbmc': types.SimpleNamespace(translatePath=lambda p: p),
                 'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)}
        exec(compile(module, str(SOURCE), 'exec'), scope)
        scope['init_settings'](fake)
        self.assertEqual(len(reads), 57)            # as many as before 0.4.77
        self.assertEqual(len(set(reads)), 57)
        self.assertIn('buildname', reads)


if __name__ == '__main__':
    unittest.main()
