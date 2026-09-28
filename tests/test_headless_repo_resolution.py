"""First-install repository lookup should only fetch what is needed."""

import ast
import types
import unittest
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1]
          / 'plugin.program.kodipovilwizard/resources/libs/headless_installer.py')


def method(name, scope):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    klass = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                 and node.name == 'HeadlessInstaller')
    function = next(node for node in klass.body if isinstance(node, ast.FunctionDef)
                    and node.name == name)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), 'exec'), scope)
    return scope[name]


class HeadlessRepoTests(unittest.TestCase):
    def test_requested_addon_and_dependencies_stop_unrelated_repo_scan(self):
        fetched = []
        scope = {
            '_log': lambda *_a, **_kw: None,
            '_parse_addons_xml': lambda body: {
                'script.module.acctmgr': {'version': '1.0', 'requires': ['dep.one']},
                'dep.one': {'version': '1.0', 'requires': []},
            } if body == 'canonical' else {},
            '_version_tuple': lambda version: tuple(int(x) for x in version.split('.')),
            'VIRTUAL_PREFIXES': ('xbmc.', 'kodi.'),
            'BINARY_PREFIXES': ('inputstream.',),
        }
        targets_indexed = method('_targets_indexed', scope)
        load_index = method('load_index', scope)
        resolver = types.SimpleNamespace(
            index={}, _loaded=False,
            _installed=lambda _aid: False,
            _targets_indexed=lambda wanted: targets_indexed(resolver, wanted),
            _iter_installed_repos=lambda: iter((
                ('repository.unrelated', [('unused', 'https://unused/')]),
                ('repository.709', [('canonical', 'https://canonical/')]),
            )),
            _fetch_text=lambda url: fetched.append(url) or url,
        )
        load_index(resolver, ['script.module.acctmgr'])
        self.assertEqual(fetched, ['canonical'])
        self.assertIn('dep.one', resolver.index)

    def test_missing_dependency_keeps_scanning(self):
        scope = {
            '_log': lambda *_a, **_kw: None,
            '_parse_addons_xml': lambda body: (
                {'script.module.acctmgr': {'version': '1.0', 'requires': ['dep.one']}}
                if body == 'canonical' else
                {'dep.one': {'version': '1.0', 'requires': []}}),
            '_version_tuple': lambda version: tuple(int(x) for x in version.split('.')),
            'VIRTUAL_PREFIXES': ('xbmc.', 'kodi.'),
            'BINARY_PREFIXES': ('inputstream.',),
        }
        targets_indexed = method('_targets_indexed', scope)
        load_index = method('load_index', scope)
        fetched = []
        resolver = types.SimpleNamespace(
            index={}, _loaded=False, _installed=lambda _aid: False,
            _targets_indexed=lambda wanted: targets_indexed(resolver, wanted),
            _iter_installed_repos=lambda: iter((
                ('repository.unrelated', [('dependency', 'https://dependency/')]),
                ('repository.709', [('canonical', 'https://canonical/')]),
            )),
            _fetch_text=lambda url: fetched.append(url) or url,
        )
        load_index(resolver, ['script.module.acctmgr'])
        self.assertEqual(fetched, ['canonical', 'dependency'])


if __name__ == '__main__':
    unittest.main()
