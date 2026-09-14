#!/usr/bin/env python3
"""Behavior tests for the crash-safe Umbrella/Coco settings reload."""

import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / 'addons' / 'service.subtitles.kodipovilai' /
          'resources' / 'lib' / 'source_settings_reload.py')


def load_module():
    spec = importlib.util.spec_from_file_location(
        'test_source_settings_reload_module', str(MODULE))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReloadTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.record = Path(self.temp.name) / 'cycle.json'
        self.path_patch = mock.patch.object(
            self.mod, '_record_path', return_value=str(self.record))
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        self.temp.cleanup()

    def test_user_disabled_addon_is_never_cycled(self):
        states = {self.mod.UMBRELLA_ID: False, self.mod.COCO_ID: True}
        calls = []

        def set_enabled(addon_id, enabled):
            calls.append((addon_id, enabled))
            states[addon_id] = enabled
            return True

        with mock.patch.object(self.mod, 'heal_interrupted_cycle',
                               return_value=True), \
                mock.patch.object(self.mod, '_safe_to_cycle',
                                  return_value=True), \
                mock.patch.object(self.mod, '_is_enabled',
                                  side_effect=lambda addon_id: states[addon_id]), \
                mock.patch.object(self.mod, '_set_enabled',
                                  side_effect=set_enabled), \
                mock.patch.object(self.mod, '_sleep'):
            self.assertTrue(self.mod._run_cycle(set(states)))
        self.assertNotIn((self.mod.UMBRELLA_ID, False), calls)
        self.assertEqual([
            (self.mod.COCO_ID, False), (self.mod.COCO_ID, True)], calls)
        self.assertFalse(self.record.exists())

    def test_record_failure_disables_nothing(self):
        calls = []
        with mock.patch.object(self.mod, 'heal_interrupted_cycle',
                               return_value=True), \
                mock.patch.object(self.mod, '_safe_to_cycle',
                                  return_value=True), \
                mock.patch.object(self.mod, '_is_enabled', return_value=True), \
                mock.patch.object(self.mod, '_write_record',
                                  return_value=False), \
                mock.patch.object(self.mod, '_set_enabled',
                                  side_effect=lambda *args: calls.append(args)):
            self.assertFalse(self.mod._run_cycle({self.mod.UMBRELLA_ID}))
        self.assertEqual([], calls)

    def test_rpc_result_without_observed_disable_is_not_a_reload(self):
        calls = []
        with mock.patch.object(self.mod, 'heal_interrupted_cycle',
                               return_value=True), \
                mock.patch.object(self.mod, '_safe_to_cycle',
                                  return_value=True), \
                mock.patch.object(self.mod, '_is_enabled', return_value=True), \
                mock.patch.object(self.mod, '_set_enabled',
                                  side_effect=lambda addon_id, enabled:
                                  calls.append((addon_id, enabled)) or True), \
                mock.patch.object(self.mod, '_sleep'):
            self.assertFalse(self.mod._run_cycle({self.mod.UMBRELLA_ID}))
        self.assertIn((self.mod.UMBRELLA_ID, False), calls)
        self.assertFalse(self.record.exists())

    def test_successful_cycle_uses_dependency_safe_order_and_clears_record(self):
        states = {self.mod.UMBRELLA_ID: True, self.mod.COCO_ID: True}
        calls = []

        def set_enabled(addon_id, enabled):
            calls.append((addon_id, enabled))
            states[addon_id] = enabled
            return True

        with mock.patch.object(self.mod, 'heal_interrupted_cycle',
                               return_value=True), \
                mock.patch.object(self.mod, '_safe_to_cycle',
                                  return_value=True), \
                mock.patch.object(self.mod, '_is_enabled',
                                  side_effect=lambda addon_id: states[addon_id]), \
                mock.patch.object(self.mod, '_set_enabled',
                                  side_effect=set_enabled), \
                mock.patch.object(self.mod, '_sleep'):
            self.assertTrue(self.mod._run_cycle(set(states)))
        self.assertEqual([
            (self.mod.UMBRELLA_ID, False),
            (self.mod.COCO_ID, False),
            (self.mod.COCO_ID, True),
            (self.mod.UMBRELLA_ID, True),
        ], calls)
        self.assertFalse(self.record.exists())

    def test_interrupted_record_enables_only_allowlisted_recorded_ids(self):
        self.record.write_text(json.dumps({
            'addon_ids': [self.mod.UMBRELLA_ID, 'plugin.video.unrelated']}),
            encoding='utf-8')
        states = {self.mod.UMBRELLA_ID: False}
        calls = []

        def set_enabled(addon_id, enabled):
            calls.append((addon_id, enabled))
            states[addon_id] = enabled
            return True

        with mock.patch.object(self.mod, '_is_enabled',
                               side_effect=lambda addon_id: states[addon_id]), \
                mock.patch.object(self.mod, '_set_enabled',
                                  side_effect=set_enabled), \
                mock.patch.object(self.mod, '_sleep'):
            self.assertTrue(self.mod.heal_interrupted_cycle())
        self.assertEqual([(self.mod.UMBRELLA_ID, True)], calls)
        self.assertFalse(self.record.exists())

    def test_failed_reenable_keeps_record_for_next_start(self):
        states = {self.mod.UMBRELLA_ID: True}

        def set_enabled(addon_id, enabled):
            if not enabled:
                states[addon_id] = False
                return True
            return False

        with mock.patch.object(self.mod, 'heal_interrupted_cycle',
                               return_value=True), \
                mock.patch.object(self.mod, '_safe_to_cycle',
                                  return_value=True), \
                mock.patch.object(self.mod, '_is_enabled',
                                  side_effect=lambda addon_id: states[addon_id]), \
                mock.patch.object(self.mod, '_set_enabled',
                                  side_effect=set_enabled), \
                mock.patch.object(self.mod, '_sleep'):
            self.assertFalse(self.mod._run_cycle({self.mod.UMBRELLA_ID}))
        self.assertTrue(self.record.exists())
        self.assertEqual([self.mod.UMBRELLA_ID],
                         self.mod._read_record())

    def test_coco_repair_also_schedules_umbrella_consumer(self):
        self.mod.note_repaired([self.mod.COCO_ID])
        self.assertEqual({self.mod.COCO_ID, self.mod.UMBRELLA_ID},
                         self.mod._pending)

    def test_final_gate_refuses_media_dialog_or_container_update(self):
        class Xbmc(object):
            @staticmethod
            def getCondVisibility(condition):
                return condition == 'Player.HasMedia'

        pov = types.SimpleNamespace(
            wait_until_settled=lambda timeout=0: True,
            _wait_until_idle=lambda timeout=0: True,
            _dialog_up=lambda: False)
        self.mod.xbmc = Xbmc()
        self.mod.pov_reload = pov
        self.assertFalse(self.mod._safe_to_cycle())


if __name__ == '__main__':
    unittest.main(verbosity=2)
