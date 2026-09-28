"""The modular transition preserves a user's source-memory opt-out."""

import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'plugin.program.kodipovilwizard/resources/libs/patches/pov_source_remember.py'
STARTUP = ROOT / 'plugin.program.kodipovilwizard/startup.py'


def migration_function(addons, legacy_settings_xml=None):
    tree = ast.parse(MODULE.read_text(encoding='utf-8'))
    func = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef)
                and node.name == 'migrate_legacy_preference')
    code = compile(ast.Module(body=[func], type_ignores=[]), str(MODULE), 'exec')
    ns = {'xbmcaddon': SimpleNamespace(Addon=lambda name: addons[name]),
          'xbmc': SimpleNamespace(LOGWARNING=1), '_log': lambda *_args: None,
          'xbmcvfs': SimpleNamespace(translatePath=lambda _path: legacy_settings_xml)}
    exec(code, ns)
    return ns['migrate_legacy_preference']


class Addon:
    def __init__(self, values):
        self.values = dict(values)

    def getSetting(self, key):
        return self.values.get(key, '')

    def setSetting(self, key, value):
        self.values[key] = value


class SourceRememberMigrationTests(unittest.TestCase):
    def test_opt_out_survives_once_and_later_user_change_sticks(self):
        wizard = Addon({'pov_remember_source': 'true'})
        legacy = Addon({'remember_source': 'false'})
        migrate = migration_function({
            'plugin.program.kodipovilwizard': wizard,
            'service.subtitles.kodipovilai': legacy})
        self.assertEqual(migrate(), 'migrated')
        self.assertEqual(wizard.getSetting('pov_remember_source'), 'false')
        wizard.setSetting('pov_remember_source', 'true')
        self.assertEqual(migrate(), 'already_migrated')
        self.assertEqual(wizard.getSetting('pov_remember_source'), 'true')

    def test_fresh_install_keeps_default_until_real_legacy_choice_exists(self):
        wizard = Addon({'pov_remember_source': 'true'})
        migrate = migration_function({'plugin.program.kodipovilwizard': wizard})
        self.assertEqual(migrate(), 'no_legacy_choice')
        self.assertEqual(wizard.getSetting('pov_remember_source'), 'true')
        self.assertEqual(wizard.getSetting('_pov_remember_migrated_v1'), '')

    def test_disabled_old_service_uses_its_saved_profile_setting(self):
        wizard = Addon({'pov_remember_source': 'true'})
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'settings.xml'
            path.write_text('<settings><setting id="remember_source">false</setting>'
                            '</settings>', encoding='utf-8')
            migrate = migration_function({'plugin.program.kodipovilwizard': wizard},
                                         str(path))
            self.assertEqual(migrate(), 'migrated')
        self.assertEqual(wizard.getSetting('pov_remember_source'), 'false')
        self.assertEqual(wizard.getSetting('_pov_remember_migrated_v1'), 'true')

    def test_migration_runs_before_modular_service_replacement(self):
        source = STARTUP.read_text(encoding='utf-8')
        self.assertLess(source.index('migrate_legacy_preference()'),
                        source.index('_mu.run_update_check()'))


if __name__ == '__main__':
    unittest.main()
