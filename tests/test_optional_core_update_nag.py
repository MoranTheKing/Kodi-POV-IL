"""Optional core reminders stay independent of build updates and preferences."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'service.subtitles.kodipovilai/resources/lib/update_nag_patcher.py'


class CoreUpdateNagTests(unittest.TestCase):
    def load(self, version='21.2 (21.2.0)', installed=True, enabled='true', fails=False):
        spec = importlib.util.spec_from_file_location('core_nag_fixture', SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        state = {'done': '', 'enabled': enabled}
        module.xbmc = SimpleNamespace(getInfoLabel=lambda _label: version)
        module.kodi_utils = SimpleNamespace(
            get_setting=lambda *_args: state['done'],
            set_setting=lambda _key, value: state.__setitem__('done', value),
            log=lambda *_args, **_kwargs: None)

        def addon(ident):
            if not installed or ident != 'service.xbmc.versioncheck':
                raise RuntimeError('Not installed')
            return SimpleNamespace(getSetting=lambda _key: state['enabled'])

        def apply(_ident, wanted, **_kwargs):
            if fails:
                return [], [], ['versioncheck_enable']
            state['enabled'] = dict(wanted)['versioncheck_enable']
            return ['versioncheck_enable'], [], []

        module.addon_settings_safe = SimpleNamespace(apply=Mock(side_effect=apply))
        return module, state, SimpleNamespace(Addon=addon)

    def run_quiet(self, module, sdk):
        from unittest.mock import patch
        with patch.dict('sys.modules', {'xbmcaddon': sdk}):
            return module.ensure_quiet()

    def test_212_reminder_is_disabled_once_without_touching_build_update_paths(self):
        module, state, sdk = self.load()
        self.assertEqual(self.run_quiet(module, sdk), 'patched')
        self.assertEqual(state['enabled'], 'false')
        self.assertEqual(module.addon_settings_safe.apply.call_args.args,
                         ('service.xbmc.versioncheck', (('versioncheck_enable', 'false'),)))
        self.assertEqual(self.run_quiet(module, sdk), 'unchanged')
        module.addon_settings_safe.apply.assert_called_once()

    def test_user_can_reenable_after_the_one_time_migration(self):
        module, state, sdk = self.load()
        self.run_quiet(module, sdk)
        state['enabled'] = 'true'
        self.assertEqual(self.run_quiet(module, sdk), 'unchanged')
        self.assertEqual(state['enabled'], 'true')

    def test_other_or_unknown_core_versions_are_not_changed(self):
        for version in ('21.1', '21.20', '21.3', '22.0', '', 'Unknown'):
            module, state, sdk = self.load(version=version)
            self.run_quiet(module, sdk)
            self.assertEqual(state['enabled'], 'true')
            module.addon_settings_safe.apply.assert_not_called()

    def test_absent_addon_does_not_consume_the_migration(self):
        module, state, sdk = self.load(installed=False)
        self.assertEqual(self.run_quiet(module, sdk), 'not_installed')
        self.assertEqual(state['done'], '')

    def test_failed_settings_write_can_retry_on_next_start(self):
        module, state, sdk = self.load(fails=True)
        self.assertEqual(self.run_quiet(module, sdk), 'write_failed')
        self.assertEqual(state['done'], '')

    def test_existing_disabled_preference_needs_no_settings_write(self):
        module, state, sdk = self.load(enabled='false')
        self.assertEqual(self.run_quiet(module, sdk), 'unchanged')
        self.assertIn('service.xbmc.versioncheck:versioncheck_enable', state['done'])
        module.addon_settings_safe.apply.assert_not_called()


if __name__ == '__main__':
    unittest.main()
