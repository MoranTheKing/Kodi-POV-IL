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
            _service_update_allowed=lambda:True,
            _runtime_addon_enabled=lambda *_a:not disable,
            _enable_addon=lambda *_a:events.append('enable') or enable,
            _mark_service_disabled=lambda flag:events.append('mark' if flag else 'unmark'),
            _addon_enabled_state=lambda *_a: not disable)
        with patch.dict(sys.modules, {'resources':types.ModuleType('resources'),
            'resources.libs':libs,'resources.libs.staged_addon_install':staged,'resources.libs.db':db}):
            result=fn(owner)
        return result,events,notification

    def test_new_service_enabled_in_same_boot_without_second_restart_prompt(self):
        result,events,notice=self.run_case()
        self.assertTrue(result)
        self.assertEqual(events,['mark','disable','swap','db','scan','clear','enable','unmark'])
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
        self.assertNotIn('unmark',events)          # still disabled: the next start heals it

    def test_failed_disable_leaves_no_marker(self):
        result,events,notice=self.run_case(disable=False)
        self.assertEqual(events[0],'mark'); self.assertEqual(events[-1],'unmark')


def method(name):
    tree = ast.parse(SOURCE.read_text('utf8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ModularUpdater')
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    return node


class InterruptedHandoffTests(unittest.TestCase):
    """QA (22 Oct 2026): Kodi closed between the handoff's disable and enable;
    MoranSubs stayed disabled for good."""

    def setUp(self):
        import os, tempfile
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.userdata = tmp.name
        self.events = []
        module = ast.fix_missing_locations(ast.Module(body=[
            method('_service_disabled_marker'), method('_mark_service_disabled'),
            method('_heal_service_left_disabled')], type_ignores=[]))
        ns = {'os': os, 'CONFIG': types.SimpleNamespace(USERDATA=self.userdata),
              'logging': types.SimpleNamespace(log=lambda *a, **k: self.events.append('log')),
              'xbmc': types.SimpleNamespace(LOGWARNING=2)}
        exec(compile(module, str(SOURCE), 'exec'), ns)
        self.ns = ns
        self.marker = os.path.join(self.userdata, 'kodipovil.moransubs_disabled_for_handoff')

    def owner(self, enabled, enable_ok=True):
        ns = self.ns
        owner = types.SimpleNamespace(
            _addon_enabled_state=lambda a: enabled,
            _enable_addon=lambda a: self.events.append('enable') or enable_ok)
        owner._service_disabled_marker = lambda: ns['_service_disabled_marker']()
        owner._mark_service_disabled = lambda flag: ns['_mark_service_disabled'](owner, flag)
        owner.heal = lambda: ns['_heal_service_left_disabled'](owner)
        return owner

    def test_disabled_by_an_interrupted_handoff_is_enabled_again(self):
        import os
        owner = self.owner(enabled=False)
        owner._mark_service_disabled(True)
        owner.heal()
        self.assertIn('enable', self.events)
        self.assertFalse(os.path.exists(self.marker))

    def test_a_failed_enable_keeps_the_marker_for_the_next_start(self):
        import os
        owner = self.owner(enabled=False, enable_ok=False)
        owner._mark_service_disabled(True)
        owner.heal()
        self.assertTrue(os.path.exists(self.marker))

    def test_kodi_unable_to_answer_keeps_the_marker(self):
        import os
        owner = self.owner(enabled=None)
        owner._mark_service_disabled(True)
        owner.heal()
        self.assertNotIn('enable', self.events)
        self.assertTrue(os.path.exists(self.marker))

    def test_heal_runs_after_the_pending_handoff(self):
        source = SOURCE.read_text('utf8')
        body = source[source.index('def run_update_check'):]
        self.assertLess(body.index('self._complete_pending_service_handoff()'),
                        body.index('self._heal_service_left_disabled()'))

    def test_no_marker_means_a_users_choice_is_left_alone(self):
        owner = self.owner(enabled=False)
        owner.heal()
        self.assertEqual(self.events, [])

    def test_enabled_already_just_clears_the_marker(self):
        import os
        owner = self.owner(enabled=True)
        owner._mark_service_disabled(True)
        owner.heal()
        self.assertNotIn('enable', self.events)
        self.assertFalse(os.path.exists(self.marker))
