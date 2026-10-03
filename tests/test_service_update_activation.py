"""An acknowledged service starts after one restart; a live one is untouched."""
import ast
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'plugin.program.kodipovilwizard/resources/libs/modular_updater.py'


def complete_method(namespace):
    tree = ast.parse(SOURCE.read_text('utf8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ModularUpdater')
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_complete_pending_service_handoff')
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(module, str(SOURCE), 'exec'), namespace)
    return namespace['_complete_pending_service_handoff']


class ServiceUpdateActivationTests(unittest.TestCase):
    def run_case(self, ack=True, playing=False, disable=True, enable=True, prepared=True):
        events = []
        staged = types.ModuleType('resources.libs.staged_addon_install')
        plan = {'version': '0.3.21', 'sha256': 'a'*64}
        staged.read_handoff = lambda *_a: (plan, {'token':'ack'} if ack else None)
        staged.prepared_matches = lambda *_a: prepared
        staged.activate_prepared = lambda *_a: events.append('swap') or 235
        staged.clear_handoff = lambda *_a: events.append('clear')
        db = types.ModuleType('resources.libs.db')
        db.addon_database = lambda *_a: events.append('db')
        libs = types.ModuleType('resources.libs'); libs.staged_addon_install=staged; libs.db=db
        notification = Mock()
        rpc = lambda text: (events.append('disable') or json.dumps(
            {'result':'OK'} if disable else {'error':{'message':'cannot disable'}}))
        namespace = {'json':json,
            'CONFIG':types.SimpleNamespace(USERDATA='userdata',ADDONS='addons',ADDONTITLE='QA'),
            'logging':types.SimpleNamespace(log=lambda *_a,**_k:None),
            'xbmcgui':types.SimpleNamespace(Dialog=lambda:types.SimpleNamespace(notification=notification)),
            'xbmc':types.SimpleNamespace(LOGINFO=1,LOGERROR=4,executeJSONRPC=rpc,
                getCondVisibility=lambda *_a:playing,executebuiltin=lambda *_a:events.append('scan'),
                Monitor=lambda:types.SimpleNamespace(waitForAbort=lambda *_a:False))}
        fn=complete_method(namespace)
        owner=types.SimpleNamespace(_service_handoff_ready=lambda:True,
            _runtime_addon_enabled=lambda *_a:not disable,
            _enable_addon=lambda *_a:events.append('enable') or enable)
        with patch.dict(sys.modules, {'resources':types.ModuleType('resources'),
            'resources.libs':libs,'resources.libs.staged_addon_install':staged,'resources.libs.db':db}):
            result=fn(owner)
        return result,events,notification

    def test_new_service_enabled_in_same_boot_without_second_restart_prompt(self):
        result,events,notice=self.run_case()
        self.assertTrue(result)
        self.assertEqual(events,['disable','swap','db','scan','clear','enable'])
        self.assertEqual(notice.call_args.args[1],'עדכון הכתוביות הושלם.')

    def test_live_unacknowledged_service_and_playback_are_untouched(self):
        for options in ({'ack':False},{'playing':True}):
            result,events,notice=self.run_case(**options)
            self.assertFalse(result); self.assertEqual(events,[]); notice.assert_not_called()

    def test_failed_disable_never_swaps_package(self):
        result,events,notice=self.run_case(disable=False)
        self.assertFalse(result); self.assertNotIn('swap',events); self.assertNotIn('enable',events)
        notice.assert_not_called()

    def test_missing_stage_clears_stale_request_without_restart_toast(self):
        result,events,notice=self.run_case(prepared=False)
        self.assertFalse(result); self.assertEqual(events,['clear']); notice.assert_not_called()

    def test_failed_enable_does_not_claim_success(self):
        result,events,notice=self.run_case(enable=False)
        self.assertFalse(result); self.assertIn('swap',events)
        self.assertIn('השירות לא התחיל',notice.call_args.args[1])
