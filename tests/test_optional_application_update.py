"""Run the legacy Android/Windows update checks and observe actual dialogs."""

import ast
import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'wizard/source/plugin.program.kodipovilwizard'


def load_checks(source):
    spec = importlib.util.spec_from_file_location(
        'release_parser', WIZARD / 'resources/libs/common/release_version.py')
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    user_tree = ast.parse((WIZARD / 'uservar.py').read_text(encoding='utf-8'))
    policy = next(ast.literal_eval(node.value) for node in user_tree.body
                  if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name)
                          and target.id == 'NO_AUTO_APP_PROMPT_TARGETS'
                          for target in node.targets))
    dialog = Mock()
    dialog.yesno.return_value = False
    namespace = {
        'release_version': parser,
        'CONFIG': types.SimpleNamespace(
            NO_AUTO_APP_PROMPT_TARGETS=policy, ADDONTITLE='Kodi POV IL Wizard',
            LATEST_APK_VERSION_TEXT_FILE='android-pointer',
            LATEST_WINDOWS_VERSION_TEXT_FILE='windows-pointer'),
        'xbmc': types.SimpleNamespace(LOGINFO=1),
        'xbmcgui': types.SimpleNamespace(Dialog=Mock(return_value=dialog)),
        'logging': types.SimpleNamespace(log=Mock()),
        '_latest_platform_release': Mock(return_value='21.3-povil.49\n'),
        '_installed_platform_release': Mock(return_value='21.3-povil.47'),
    }
    tree = ast.parse(source)
    names = {'_app_update_not_required', '_auto_prompt_suppressed',
             'kodi_apk_update_check', 'kodi_windows_update_check'}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and node.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'wizard-check', 'exec'),
         namespace)
    return namespace, dialog


class OptionalApplicationUpdateTests(unittest.TestCase):
    def setUp(self):
        self.source = (WIZARD / 'resources/libs/wizard.py').read_text(
            encoding='utf-8')

    def test_build_only_package_never_offers_a_reinstall(self):
        for platform in ('apk', 'windows'):
            for installed in ('21.3-povil.1', '21.3-povil.25', '21.3-povil.35',
                              '21.3-povil.46', '21.3-povil.47', '21.3-povil.48'):
                for manual in (False, True):
                    with self.subTest(platform=platform, installed=installed,
                                      manual=manual):
                        namespace, dialog = load_checks(self.source)
                        namespace['_installed_platform_release'].return_value = installed
                        namespace['kodi_' + platform + '_update_check'](
                            manual, platform.capitalize())
                        dialog.yesno.assert_not_called()
                        if manual:
                            dialog.ok.assert_called_once()
                            self.assertIn('אין צורך לעדכן', dialog.ok.call_args.args[1])
                        else:
                            dialog.ok.assert_not_called()

    def test_genuine_future_application_update_remains_available(self):
        for platform in ('apk', 'windows'):
            for manual in (False, True):
                with self.subTest(platform=platform, manual=manual):
                    namespace, dialog = load_checks(self.source)
                    namespace['_latest_platform_release'].return_value = '21.3-povil.50'
                    namespace['kodi_' + platform + '_update_check'](
                        manual, platform.capitalize())
                    dialog.yesno.assert_called_once()

    def test_current_application_is_not_offered_again(self):
        for platform in ('apk', 'windows'):
            for manual in (False, True):
                with self.subTest(platform=platform, manual=manual):
                    namespace, dialog = load_checks(self.source)
                    namespace['_installed_platform_release'].return_value = '21.3-povil.49'
                    namespace['kodi_' + platform + '_update_check'](
                        manual, platform.capitalize())
                    dialog.yesno.assert_not_called()
                    self.assertEqual(dialog.ok.call_count, int(manual))

    def test_logging_failure_does_not_restore_the_unnecessary_offer(self):
        namespace, dialog = load_checks(self.source)
        namespace['logging'].log.side_effect = OSError('log unavailable')
        namespace['kodi_apk_update_check'](True, 'Android')
        dialog.yesno.assert_not_called()
        dialog.ok.assert_called_once()


if __name__ == '__main__':
    unittest.main()
