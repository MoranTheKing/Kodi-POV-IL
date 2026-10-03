"""Native schema limits, picker read-back, and expiry threshold semantics."""
import ast
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'plugin.program.kodipovilwizard/resources/libs/patch_engine.py'
PICKER = ROOT / 'service.subtitles.kodipovilai/default.py'
TOAST = ROOT / 'plugin.program.kodipovilwizard/resources/libs/patches/pov_custom_debrid_toasts.py'


def functions(path, names):
    nodes = ast.parse(path.read_text('utf8')).body
    selected = [node for node in nodes if isinstance(node, ast.FunctionDef) and node.name in names
                or isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names
                                                       for t in node.targets)]
    return compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec')


class DebridNoticeSettingsTests(unittest.TestCase):
    def setUp(self):
        namespace = {}
        import re
        import xml.etree.ElementTree as ET
        namespace.update(re=re, ET=ET)
        exec(functions(ENGINE, {'_EXPIRY_SETTINGS', 'expand_expiry_ranges'}), namespace)
        self.expand = namespace['expand_expiry_ranges']

    def test_precise_idempotent_edit_preserves_other_controls_and_defaults(self):
        rows = ['<setting id="{}" type="slider" option="int" range="0,1,7" default="7" visible="x" />'.format(key)
                for key in ('rd.expires', 'tb.expires', 'pm.expires', 'ad.expires', 'oc.expires')]
        source = '<settings>\r\n<!-- ' + rows[0] + ' -->\r\n' + '\r\n'.join(rows) + \
                 '\r\n<setting id="unrelated" type="slider" range="0,1,7" />\r\n</settings>'
        expected = source.replace('range="0,1,7"', 'range="0,1,365"', 6)
        expected = expected.replace('<!-- ' + rows[0].replace('0,1,7', '0,1,365') + ' -->', '<!-- ' + rows[0] + ' -->')
        repaired, count = self.expand(source)
        self.assertEqual(repaired, expected)
        self.assertEqual(count, 5)
        self.assertEqual(self.expand(repaired), (repaired, 0))

    def test_future_larger_range_is_not_reduced(self):
        source = "<settings><setting id='rd.expires' type='slider' option='int' range='0,1,730'/></settings>"
        self.assertEqual(self.expand(source), (source, 0))

    def test_unknown_or_malformed_schema_refuses_partial_change(self):
        for attributes in ('type="slider" option="int" range="0,7,90"',
                           'type="integer"', 'type="slider" option="int" range="broken"'):
            source = '<settings><setting id="rd.expires" ' + attributes + '/></settings>'
            with self.subTest(attributes=attributes), self.assertRaises(ValueError):
                self.expand(source)
        with self.assertRaises(Exception):
            self.expand('<settings>')

    def test_runtime_repair_reapplies_after_upstream_replacement(self):
        logger = types.SimpleNamespace(log=Mock())
        xbmc = types.SimpleNamespace(LOGDEBUG=0, LOGINFO=1, LOGWARNING=2, LOGERROR=3)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {
                'xbmc':xbmc, 'xbmcaddon':types.SimpleNamespace(),
                'xbmcvfs':types.SimpleNamespace(),
                'resources.libs.common':types.SimpleNamespace(logging=logger)}):
            spec = importlib.util.spec_from_file_location('expiry_engine_test', ENGINE)
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            root = Path(tmp)
            schema = root / 'resources/settings.xml'; schema.parent.mkdir()
            source = '<settings><setting id="tb.expires" type="slider" option="int" range="0,1,7" /></settings>'
            schema.write_text(source)
            preferences = root / 'saved-user-settings.xml'
            preferences.write_text('<settings><setting id="tb.expires">30</setting></settings>')
            before = preferences.read_bytes()
            code = root / 'entry.py'; code.write_text('original = 1\n')
            config = [dict(id='fixture', name='fixture', addon_id='plugin.video.pov',
                           target_file='entry.py', marker='fixture_v1', anchor='original = 1',
                           action='append_after', hook='added = 2')]
            class Engine(module.PatchEngine):
                @staticmethod
                def _resolve_paths(_aid, filename):
                    return str(root), str(root / filename)
                def _is_patch_enabled(self, entry):
                    return True
            for replaced in (False, True):
                if replaced:
                    schema.write_text(source)
                stats = Engine(config).run()
                self.assertEqual(stats.get('settings_expanded'), 1)
                self.assertEqual(stats['failed'], 0)
                self.assertIn('0,1,365', schema.read_text())
                self.assertEqual(preferences.read_bytes(), before)
                self.assertNotIn('settings_expanded', Engine(config).run())

    def picker(self, selections, reject=False):
        values = {}
        host = types.SimpleNamespace(getSetting=lambda key:values.get(key, '0'),
             setSetting=lambda key,value: None if reject else values.__setitem__(key,value))
        dialog = types.SimpleNamespace(select=Mock(side_effect=selections), ok=Mock(), notification=Mock())
        namespace = {'_pov_addon':lambda:host, 'xbmcgui':types.SimpleNamespace(Dialog=lambda:dialog)}
        exec(functions(PICKER, {'DEBRID_NOTICE_SERVICES','DEBRID_NOTICE_VALUES',
                               '_notice_value_label','_handle_debrid_notice_settings'}), namespace)
        # Force the fallback notification path, independent of installed Kodi libs.
        with patch.dict(sys.modules, {'resources.lib':None}):
            namespace['_handle_debrid_notice_settings']({})
        return namespace, values, dialog

    def test_every_picker_value_for_every_service_confirms_only_saved_values(self):
        for service in range(4):
            for option in range(10):
                with self.subTest(service=service, option=option):
                    namespace, values, dialog = self.picker([service, option])
                    key = namespace['DEBRID_NOTICE_SERVICES'][service][1]
                    value = namespace['DEBRID_NOTICE_VALUES'][option][1]
                    self.assertEqual(values[key], value)
                    dialog.ok.assert_not_called()
                    dialog.notification.assert_called_once()

    def test_rejected_value_does_not_claim_success_or_change_previous_choice(self):
        _namespace, values, dialog = self.picker([0,5], reject=True)
        self.assertEqual(values, {})
        dialog.ok.assert_called_once()
        dialog.notification.assert_not_called()

    def test_cancel_keeps_preferences(self):
        for selections in ([-1], [0,-1]):
            _namespace, values, dialog = self.picker(selections)
            self.assertEqual(values, {})
            dialog.notification.assert_not_called()
            dialog.ok.assert_not_called()

    def test_threshold_is_days_remaining_not_notification_frequency(self):
        namespace = {}
        exec(functions(TOAST, {'_get_setting','_get_threshold','_should_show'}), namespace)
        for days in (0,1,7,14,29,30):
            self.assertTrue(namespace['_should_show'](days,30))
        for days in (31,60,365,None):
            self.assertFalse(namespace['_should_show'](days,30))
        for threshold in (0,1,3,7,14,30,60,90,180,365):
            addon = types.SimpleNamespace(getSetting=lambda key:str(threshold))
            self.assertEqual(namespace['_get_threshold'](addon, {'expires':'tb.expires'}),threshold)
            self.assertTrue(namespace['_should_show'](threshold,threshold))
            self.assertEqual(namespace['_should_show'](threshold+1,threshold), threshold==0)


if __name__ == '__main__':
    unittest.main()
