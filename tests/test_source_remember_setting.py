"""A user's Wizard opt-out must beat the old subtitle-addon rollout value."""

import ast
import types
import unittest
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] /
          'plugin.program.kodipovilwizard/resources/libs/patches/pov_source_remember.py')


def load_enabled(wizard_value, legacy_value):
    tree = ast.parse(SOURCE.read_text('utf-8'))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == '_enabled')
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    values = {'plugin.program.kodipovilwizard': wizard_value,
              'service.subtitles.kodipovilai': legacy_value}
    addon = lambda addon_id: types.SimpleNamespace(
        getSetting=lambda key: values[addon_id])
    scope = {'xbmcaddon': types.SimpleNamespace(Addon=addon)}
    exec(compile(module, str(SOURCE), 'exec'), scope)
    return scope['_enabled']()


class SourceRememberSettingTests(unittest.TestCase):
    def test_explicit_wizard_choice_wins_over_legacy_value(self):
        self.assertFalse(load_enabled('false', 'true'))
        self.assertTrue(load_enabled('true', 'false'))

    def test_only_missing_wizard_choice_falls_back(self):
        self.assertTrue(load_enabled('', 'true'))
        self.assertFalse(load_enabled('', 'false'))


if __name__ == '__main__':
    unittest.main()
