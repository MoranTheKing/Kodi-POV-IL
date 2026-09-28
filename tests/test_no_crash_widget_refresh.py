"""Do not restore the widget-refresh ping that crashed field Kodi playback."""

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'plugin.program.kodipovilwizard/resources/libs/patches'
          / 'patches_config.py')


class NoCrashWidgetRefreshTests(unittest.TestCase):
    def test_no_active_hook_runs_update_library_from_container_refresh(self):
        tree = ast.parse(CONFIG.read_text(encoding='utf-8'))
        assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name)
                                  and target.id == 'PATCH_CONFIG'
                                  for target in node.targets))
        patches = ast.literal_eval(assignment.value)
        retired = next(p for p in patches if p['id'] == 'wizard_pov_widget_refresh')
        self.assertFalse(retired['enabled'])
        self.assertFalse(any('kodi_widget_refresh.ping()' in p.get('hook', '')
                             for p in patches if p.get('enabled', True)))


if __name__ == '__main__':
    unittest.main()
