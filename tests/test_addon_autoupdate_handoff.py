"""Preserve the build-owned Kodi update-rule repair in the modular service."""

import ast
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / 'service.subtitles.kodipovilai/service.py'


class AddonAutoupdateHandoffTests(unittest.TestCase):
    def test_startup_pass_calls_update_rule_repair(self):
        tree = ast.parse(SERVICE.read_text(encoding='utf-8'))
        wrapper = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                       and node.name == '_maybe_repair_addon_autoupdate')
        repairs = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                       and node.name == '_run_build_startup_repairs')
        self.assertIn(wrapper.name, [node.id for node in ast.walk(repairs)
                                     if isinstance(node, ast.Name)])
        called = []
        resources = types.ModuleType('resources')
        lib = types.ModuleType('resources.lib')
        repair = types.ModuleType('resources.lib.addon_autoupdate_repair')
        repair.ensure_repaired = lambda: called.append('repair') or 'ok'
        kodi_utils = types.ModuleType('resources.lib.kodi_utils')
        kodi_utils.log = lambda *_a, **_k: None
        lib.addon_autoupdate_repair = repair
        lib.kodi_utils = kodi_utils
        namespace = {}
        exec(compile(ast.Module(body=[wrapper], type_ignores=[]), str(SERVICE), 'exec'),
             namespace)
        with patch.dict(sys.modules, {'resources': resources, 'resources.lib': lib,
                                      'resources.lib.addon_autoupdate_repair': repair,
                                      'resources.lib.kodi_utils': kodi_utils}):
            namespace[wrapper.name]()
        self.assertEqual(called, ['repair'])


if __name__ == '__main__':
    unittest.main()
