"""Manual and startup install share bounded, verified resumption."""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from test_provisioning_gate import ROOT, _load_function

SOURCE = ROOT / 'plugin.program.kodipovilwizard/resources/libs/fresh_install.py'


class FreshInstallRetryTests(unittest.TestCase):
    def run_flow(self, results, *, marker=True, abort=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        calls, notices, waits = [], [], []
        outcomes = iter(results)
        def factory(**kwargs):
            outcome = next(outcomes)
            calls.append(kwargs)
            def run():
                if isinstance(outcome, Exception): raise outcome
                return outcome
            return types.SimpleNamespace(run_fresh_install=run,
                is_provisioned=lambda: marker, last_install_issues=['plugin.video.pov (missing)'])
        monitor = types.SimpleNamespace(abortRequested=lambda: abort,
            waitForAbort=lambda secs: waits.append(secs) or False)
        scope = {'CONFIG': types.SimpleNamespace(USERDATA=directory.name, ADDONTITLE='QA'),
            'xbmc': types.SimpleNamespace(Monitor=lambda: monitor, LOGERROR=4),
            'xbmcgui': types.SimpleNamespace(Dialog=lambda: types.SimpleNamespace(
                notification=lambda *a, **kw: notices.append(a))),
            'logging': types.SimpleNamespace(log=lambda *_a, **_kw: None),
            'os': os, 'json': json}
        fn = _load_function(SOURCE, 'provision', scope)
        receipt = Path(directory.name) / 'kodipovil.install_failure.json'
        receipt.write_text('{}')
        with patch.dict(sys.modules, {'resources.libs.modular_updater': types.SimpleNamespace(ModularUpdater=factory)}):
            result = fn()
        return result, calls, notices, waits, receipt

    def test_transient_failure_recovers_in_same_invocation_and_clears_diagnostic(self):
        result, calls, notices, waits, receipt = self.run_flow([False, True])
        self.assertEqual(result, (True, []))
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(notices), 1)
        self.assertEqual(waits, [3])
        self.assertFalse(receipt.exists())

    def test_persistent_failure_is_bounded_and_reported_without_marking_success(self):
        result, calls, notices, waits, receipt = self.run_flow([False] * 3)
        self.assertFalse(result[0])
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(notices), 2)
        self.assertEqual(json.loads(receipt.read_text()), {'issues': result[1], 'attempts': 3})

    def test_ui_success_without_verified_marker_is_not_completion(self):
        result, calls, *_ = self.run_flow([True] * 3, marker=False)
        self.assertFalse(result[0]); self.assertEqual(len(calls), 3)

    def test_exception_recovers_and_shutdown_does_not_start_work(self):
        result, calls, *_ = self.run_flow([OSError('offline'), True])
        self.assertTrue(result[0]); self.assertEqual(len(calls), 2)
        result, calls, *_ = self.run_flow([], abort=True)
        self.assertFalse(result[0]); self.assertEqual(calls, [])

    def test_failure_message_explains_network_or_missing_items_and_preserves_profile(self):
        fn = _load_function(SOURCE, 'failure_message', {})
        self.assertIn('חיבור לרשת', fn(['manifest unavailable']))
        text = fn(['plugin.video.pov (missing)'])
        self.assertIn('plugin.video.pov', text)
        self.assertIn('בלי למחוק', text)
        self.assertNotIn('הפעל מחדש', text)

    def test_manual_and_startup_both_call_the_same_provisioning_flow(self):
        wizard = (ROOT / 'plugin.program.kodipovilwizard/resources/libs/wizard.py').read_text('utf8')
        startup = (ROOT / 'plugin.program.kodipovilwizard/startup.py').read_text('utf8')
        for source in (wizard, startup):
            self.assertIn('= fresh_install.provision()', source)
            self.assertIn('fresh_install.failure_message(issues)', source)


if __name__ == '__main__': unittest.main()
