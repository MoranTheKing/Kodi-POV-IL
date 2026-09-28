"""Verify the built-in subtitle engine and DarkSubs do not compete at startup."""

import ast
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


SERVICE = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai/service.py'
SOURCE = SERVICE.read_text(encoding='utf-8-sig')
TREE = ast.parse(SOURCE)
NODE = next(node for node in TREE.body
            if isinstance(node, ast.FunctionDef)
            and node.name == '_ensure_darksubs_enabled')


def _exercise(engine_on, keep, initial):
    states = dict(initial)
    writes = []

    def rpc(raw):
        req = json.loads(raw)
        addon_id = req['params']['addonid']
        if req['method'] == 'Addons.GetAddonDetails':
            return json.dumps({'result': {'addon': (
                {'enabled': states[addon_id]} if addon_id in states else {})}})
        if req['method'] == 'Addons.SetAddonEnabled':
            states[addon_id] = req['params']['enabled']
            writes.append((addon_id, states[addon_id]))
            return '{}'
        raise AssertionError(req['method'])

    xbmc = types.SimpleNamespace(executeJSONRPC=rpc, log=lambda *_a, **_kw: None,
                                 LOGINFO=1)
    kodi_utils = types.SimpleNamespace(get_bool=lambda key, _default: (
        engine_on if key == 'use_builtin_engine' else keep))
    resources = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    lib.kodi_utils = kodi_utils
    resources.lib = lib
    namespace = {'xbmc': xbmc, 'ADDON_ID': 'service.subtitles.kodipovilai'}
    exec(compile(ast.Module(body=[NODE], type_ignores=[]), str(SERVICE), 'exec'), namespace)
    with patch.dict(sys.modules, {'resources': resources,
                                  'resources.lib': lib}):
        namespace['_ensure_darksubs_enabled']()
    return writes


class DarkSubsEnableTests(unittest.TestCase):
    def test_builtin_engine_disables_competing_addons(self):
        self.assertEqual(_exercise(True, False, {
            'service.subtitles.All_Subs': True,
            'service.subtitles.all_subs_plus': True}), [
                ('service.subtitles.All_Subs', False),
                ('service.subtitles.all_subs_plus', False)])

    def test_keep_setting_preserves_darksubs_even_with_builtin_engine(self):
        self.assertEqual(_exercise(True, True, {
            'service.subtitles.All_Subs': True,
            'service.subtitles.all_subs_plus': True}), [])

    def test_manual_builtin_opt_out_reenables_darksubs(self):
        self.assertEqual(_exercise(False, False, {
            'service.subtitles.All_Subs': False}), [
                ('service.subtitles.All_Subs', True)])

    def test_missing_addon_is_never_installed_or_modified(self):
        self.assertEqual(_exercise(True, False, {}), [])

    def test_reconciliation_runs_after_engine_rollout(self):
        main = next(node for node in TREE.body
                    if isinstance(node, ast.FunctionDef) and node.name == 'main')
        calls = [(node.lineno, node.func.id) for node in ast.walk(main)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        line = {name: number for number, name in calls}
        self.assertLess(line['_maybe_default_builtin_engine'],
                        line['_ensure_darksubs_enabled'])
        self.assertLess(line['_ensure_darksubs_enabled'],
                        line['_maybe_set_default_subtitle_service'])


if __name__ == '__main__':
    unittest.main()
