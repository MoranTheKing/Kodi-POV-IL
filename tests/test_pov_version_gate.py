"""POV moves only to the version the build's hooks were verified on.

Field (21 Oct 2026): Kodi installed POV 6.10.16 from its developer's
repository the night it was published; ten hooks lost their anchors and
series lists failed for every user before anyone had checked it.
"""
import importlib.util
import os
import sqlite3
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'pov_version_gate', ROOT / 'plugin.program.kodipovilwizard/resources/libs/pov_version_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

PIN = {'id': 'plugin.video.pov', 'version': '6.10.17', 'size': 3,
       'sha256': 'a' * 64,
       'zip': 'https://github.com/MoranTheKing/Kodi-POV-IL/releases/download/addons-latest/x.zip'}


def addons_db(path):
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE update_rules (id integer primary key, addonID TEXT, updateRule INTEGER)')
    conn.execute("INSERT INTO update_rules (addonID, updateRule) VALUES ('skin.estuary', 1)")
    conn.commit()
    conn.close()


def rules(path):
    conn = sqlite3.connect(path)
    try:
        return sorted(conn.execute('SELECT addonID, updateRule FROM update_rules').fetchall())
    finally:
        conn.close()


class Decide(unittest.TestCase):
    def test_moves_up_never_down_except_fresh(self):
        self.assertEqual(gate.decide('6.10.06', '6.10.17', False), 'install')
        self.assertEqual(gate.decide('6.10.17', '6.10.17', False), 'keep')
        self.assertEqual(gate.decide('6.10.17', '6.10.06', False), 'keep')
        self.assertEqual(gate.decide('6.10.17', '6.10.06', True), 'install')
        self.assertEqual(gate.decide('', '6.10.17', True), 'keep')
        self.assertEqual(gate.decide('6.10.9', '6.10.16', False), 'install')   # numeric, not text


class Hold(unittest.TestCase):
    def test_rule_added_once_and_others_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, 'Addons33.db')
            addons_db(db)
            self.assertTrue(gate.ensure_hold(db))
            self.assertTrue(gate.ensure_hold(db))
            self.assertEqual(rules(db), [('plugin.video.pov', 1), ('skin.estuary', 1)])

    def test_missing_database_is_never_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, 'Addons33.db')
            self.assertFalse(gate.ensure_hold(db))
            self.assertFalse(os.path.exists(db))


class Sync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.config = types.SimpleNamespace(ADDONS=str(root / 'addons'),
                                            ADDON_DATA=str(root / 'addon_data'),
                                            ADDON_ID='plugin.program.kodipovilwizard')
        host = root / 'addons' / 'plugin.video.pov'
        host.mkdir(parents=True)
        (host / 'addon.xml').write_text('<addon id="plugin.video.pov" version="6.10.06"/>')
        self.db = str(root / 'Addons33.db')
        addons_db(self.db)
        self.calls = []

    def updater(self, installed):
        calls = self.calls

        class Updater:
            def get_local_version(self, addon_id):
                return installed

            def _download_background_zip(self, url, dest, entry):
                calls.append(('download', url))
                with open(dest, 'wb') as out:
                    out.write(b'zip')
        return Updater()

    def run_sync(self, installed, fresh=False, legacy=False, install_error=None,
                 install_allowed=True, stats=None):
        def install(path):
            self.calls.append(('install', os.path.basename(path)))
            if install_error:
                raise install_error
        return gate.sync(self.updater(installed), {'pov_host_migration': PIN}, fresh,
                         self.config, lambda msg: self.calls.append(('log', msg)), self.db,
                         legacy_host=lambda: legacy, install=install,
                         register=lambda: self.calls.append(('register',)),
                         repatch=lambda: self.calls.append(('repatch',)) or (stats or {'applied': 117}),
                         install_allowed=install_allowed,
                         recover=lambda: self.calls.append(('recover',)))

    def kinds(self):
        return [c[0] for c in self.calls if c[0] not in ('log', 'recover')]

    def test_older_pov_gets_the_verified_version_and_hooks(self):
        self.assertEqual(self.run_sync('6.10.06'), 'installed 6.10.17')
        self.assertEqual(self.kinds(), ['download', 'install', 'register', 'repatch'])
        self.assertIn(('plugin.video.pov', 1), rules(self.db))
        leftover = os.listdir(os.path.join(self.config.ADDON_DATA, self.config.ADDON_ID, 'ota-packages'))
        self.assertEqual(leftover, [])

    def test_current_or_newer_is_only_held(self):
        for installed in ('6.10.17', '6.10.18'):
            self.calls.clear()
            self.assertEqual(self.run_sync(installed), 'held')
            self.assertEqual(self.kinds(), [])
        self.assertIn(('plugin.video.pov', 1), rules(self.db))

    def test_fresh_install_replaces_an_unverified_newer_pov(self):
        self.assertEqual(self.run_sync('6.10.18', fresh=True), 'installed 6.10.17')

    def test_legacy_host_is_held_but_left_to_the_migration(self):
        self.assertEqual(self.run_sync('6.10.06', legacy=True), 'legacy')
        self.assertEqual(self.kinds(), [])
        self.assertIn(('plugin.video.pov', 1), rules(self.db))

    def test_failed_install_reports_and_keeps_going(self):
        result = self.run_sync('6.10.06', install_error=ValueError('add-on ZIP SHA-256 mismatch'))
        self.assertTrue(result.startswith('failed: '))
        self.assertNotIn('register', self.kinds())

    def test_a_wizard_update_in_the_same_run_defers_the_install(self):
        # the hooks in memory are the old Wizard's; the next start installs
        self.assertEqual(self.run_sync('6.10.06', install_allowed=False), 'deferred')
        self.assertEqual(self.kinds(), [])
        self.assertIn(('plugin.video.pov', 1), rules(self.db))

    def test_hook_problems_after_install_are_reported(self):
        result = self.run_sync('6.10.06', stats={'applied': 116, 'anchor_missing': 1})
        self.assertIn('hook problems', result)

    def test_an_interrupted_swap_is_recovered_first(self):
        self.run_sync('6.10.17')
        self.assertEqual(self.calls[0], ('recover',))

    def test_no_pin_or_no_pov(self):
        bad = dict(PIN, zip='http://insecure/x.zip')
        self.assertEqual(gate.sync(self.updater('6.10.06'), {'pov_host_migration': bad}, False,
                                   self.config, lambda m: None, self.db), 'no_pin')
        os.remove(os.path.join(self.config.ADDONS, 'plugin.video.pov', 'addon.xml'))
        self.assertEqual(self.run_sync('6.10.06'), 'no_pov')


if __name__ == '__main__':
    unittest.main()
