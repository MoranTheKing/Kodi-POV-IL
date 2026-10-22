"""A new Umbrella is pinned only when MoranSubs' Umbrella patchers fit it too.

Field (22 Oct 2026): the pin moved to Umbrella 6.7.95 on the Wizard's hooks
alone; 6.7.95 had moved its English strings, MoranSubs' Hebrew menu installer
skipped, and every device got English menus. QA: this audit, run with the
MoranSubs of that day on 6.7.95, reports exactly the two patchers that broke.
"""
import json
import runpy
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY = runpy.run_path(str(ROOT / '.github/scripts/verify_pov_patches.py'))
AUDIT_SCRIPT = ROOT / '.github/scripts/moransubs_umbrella_audit.py'
AUDIT = runpy.run_path(str(AUDIT_SCRIPT))


def runner_for(steps, good=('patched', 'unchanged', 'already_patched', 'upstream', 'repatched'),
               returncode=0, stderr=''):
    def run(args):
        return types.SimpleNamespace(returncode=returncode, stderr=stderr,
                                     stdout='noise\n' + json.dumps({'good': list(good), 'steps': steps}))
    return run


class Evaluation(unittest.TestCase):
    def audit(self, steps, **kw):
        return VERIFY['audit_moransubs_umbrella'](ROOT, Path('umbrella'), runner=runner_for(steps, **kw))

    def test_all_fit_and_settle(self):
        self.assertEqual(self.audit([['umbrella_hebrew_ui_patcher', 'ensure_patched', 'patched', 'unchanged'],
                                     ['umbrella_language_patcher', 'ensure_patched', 'upstream', 'upstream']]), [])

    def test_the_6_7_95_failure_is_named(self):
        problems = self.audit([['umbrella_hebrew_ui_patcher', 'ensure_patched', 'no_source', 'no_source']])
        self.assertEqual(problems, ['umbrella_hebrew_ui_patcher.ensure_patched: no_source'])

    def test_a_patcher_that_patches_every_time_is_reported(self):
        problems = self.audit([['umbrella_source_ux_patcher', 'ensure_patched', 'patched', 'patched']])
        self.assertIn('does not settle', problems[0])

    def test_an_exception_is_a_problem(self):
        problems = self.audit([['umbrella_x', 'ensure_patched', 'error: KeyError: 1', 'error: KeyError: 1']])
        self.assertEqual(len(problems), 1)

    def test_a_runner_that_cannot_work_stops_the_pin(self):
        with self.assertRaises(ValueError):
            self.audit([], returncode=1, stderr='Traceback ...')


class Contract(unittest.TestCase):
    def test_reads_the_list_devices_run(self):
        steps, good = AUDIT['repair_contract'](ROOT / 'service.subtitles.kodipovilai')
        self.assertIn(('umbrella_hebrew_ui_patcher', 'ensure_patched'), steps)
        self.assertIn(('umbrella_setup_patcher', 'ensure_personal_list_order'), steps)
        self.assertGreaterEqual(len(steps), 9)
        self.assertEqual(good, {'patched', 'repatched', 'already_patched', 'unchanged', 'upstream'})


class StrictContract(unittest.TestCase):
    def contract(self, source):
        with tempfile.TemporaryDirectory() as raw:
            (Path(raw) / 'repair_hosts.py').write_text(source)
            return AUDIT['repair_contract'](Path(raw))

    def test_an_entry_that_does_not_read_cleanly_is_an_error(self):
        for entries in ("('umbrella_a', 'ensure_patched'), ('umbrella_b', FN)",
                        "('umbrella_a', 'ensure_patched'), ('umbrella_b', 'x', 'y')"):
            with self.subTest(entries=entries):
                with self.assertRaises(ValueError):
                    self.contract("for name, function in (%s):\n    pass\ngood = {'patched'}\n" % entries)

    def test_two_lists_are_an_error(self):
        loop = "for name, function in (('umbrella_a', 'ensure_patched'),):\n    pass\n"
        with self.assertRaises(ValueError):
            self.contract(loop + loop + "good = {'patched'}\n")

    def test_other_loops_are_ignored(self):
        steps, good = self.contract("for x in (('a', 1), 2):\n    pass\n"
                                    "for name, function in (('umbrella_a', 'f'),):\n    pass\n"
                                    "good = {'patched'}\n")
        self.assertEqual(steps, [('umbrella_a', 'f')])


class Runner(unittest.TestCase):
    """The real script, on a tiny MoranSubs and Umbrella, in a subprocess."""

    def test_stubbed_kodi_copy_and_no_network(self):
        with tempfile.TemporaryDirectory() as raw:
            raw = Path(raw)
            ms = raw / 'moransubs'
            (ms / 'resources' / 'lib').mkdir(parents=True)
            (ms / 'resources' / '__init__.py').write_text('')
            (ms / 'resources' / 'lib' / '__init__.py').write_text('')
            (ms / 'repair_hosts.py').write_text(
                "def repair():\n"
                "    for name, function in (('umbrella_fake_patcher', 'ensure_patched'),\n"
                "                           ('umbrella_net_patcher', 'ensure_patched')):\n"
                "        pass\n"
                "good = {'patched', 'unchanged'}\n")
            (ms / 'resources' / 'lib' / 'umbrella_fake_patcher.py').write_text(
                "import os, xbmcvfs\n"
                "def ensure_patched():\n"
                "    path = xbmcvfs.translatePath('special://home/addons/plugin.video.umbrella/x.py')\n"
                "    text = open(path).read()\n"
                "    if 'PATCHED' in text:\n"
                "        return 'unchanged'\n"
                "    open(path, 'w').write(text + 'PATCHED')\n"
                "    return 'patched'\n")
            (ms / 'resources' / 'lib' / 'umbrella_net_patcher.py').write_text(
                "import socket\n"
                "def ensure_patched():\n"
                "    socket.create_connection(('example.org', 80))\n"
                "    return 'patched'\n")
            umbrella = raw / 'plugin.video.umbrella'
            umbrella.mkdir()
            (umbrella / 'x.py').write_text('x = 1\n')
            out = subprocess.run([sys.executable, '-I', str(AUDIT_SCRIPT), str(ms), str(umbrella)],
                                 capture_output=True, text=True, timeout=120)
            self.assertEqual(out.returncode, 0, out.stderr)
            data = json.loads(out.stdout.strip().splitlines()[-1])
            self.assertEqual(data['steps'][0], ['umbrella_fake_patcher', 'ensure_patched', 'patched', 'unchanged'])
            self.assertTrue(data['steps'][1][2].startswith('error: OSError: network access refused'))
            self.assertEqual((umbrella / 'x.py').read_text(), 'x = 1\n')     # the official tree is untouched


if __name__ == '__main__':
    unittest.main()
