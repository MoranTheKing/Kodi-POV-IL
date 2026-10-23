"""The repo-channel MoranSubs is packaged from the build's tree (Oct 2026).

tools/build_standalone_moransubs.py ships the subtitle modules only. These
check that nothing it ships reaches a module it leaves out except inside a
`try` (so a build-only path fails quietly instead of breaking the add-on), and
that default.py loses exactly the build-only actions.
"""
import ast
import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_standalone_moransubs',
                                              ROOT / 'tools' / 'build_standalone_moransubs.py')
bsm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bsm)
SRC = bsm.SRC
BUILDISH = re.compile(r'(pov_|af3_|umbrella_|mdblist_|nox_|estuary_|fentastic_|idanplus_|'
                      r'subs_chooser|search_provider|he_sub_match|wizard|tonight|brand_|favourites_)')


def shipped():
    return sorted(p.relative_to(SRC) for p in SRC.rglob('*') if p.is_file()
                  and '__pycache__' not in p.parts and bsm.include(p.relative_to(SRC)))


CATCHES_IMPORT_ERROR = {'Exception', 'BaseException', 'ImportError', 'ModuleNotFoundError'}


def catches_import_error(handler):
    kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return handler.type is None or any(
        isinstance(k, ast.Name) and k.id in CATCHES_IMPORT_ERROR for k in kinds)


def guarded(node, parents):
    """The import runs inside the body of a try, in the same function, that
    catches ImportError. A try around a def doesn't count: the import runs
    when the function is called, not when it is defined."""
    child = node
    while child in parents:
        parent = parents[child]
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return False
        if (isinstance(parent, ast.Try) and child in parent.body
                and any(catches_import_error(h) for h in parent.handlers)):
            return True
        child = parent
    return False


def import_targets(node, pkg):
    if isinstance(node, ast.ImportFrom):
        if node.level:
            base = pkg.split('.')
            mod = '.'.join(base[:len(base) - node.level + 1] + ([node.module] if node.module else []))
        else:
            mod = node.module or ''
        if not mod.startswith('resources.lib'):
            return []
        out = []
        for alias in node.names:
            cand = mod + '.' + alias.name
            exists = (SRC / (cand.replace('.', '/') + '.py')).exists() or (SRC / cand.replace('.', '/')).is_dir()
            out.append(cand if exists else mod)
        return out
    if isinstance(node, ast.Import):
        return [a.name for a in node.names if a.name.startswith('resources.lib')]
    return []


class StandalonePackage(unittest.TestCase):
    def test_only_subtitle_modules(self):
        lib = [r for r in shipped() if r.parts[:2] == ('resources', 'lib') and len(r.parts) == 3]
        self.assertEqual([r.name for r in lib if BUILDISH.search(r.name)], [])
        for name in bsm.STANDALONE_LIB_FILES:
            self.assertTrue((SRC / 'resources' / 'lib' / name).is_file(), name)
        names = {r.as_posix() for r in shipped()}
        for required in ('addon.xml', 'default.py', 'service.py', 'resources/settings.xml',
                         'resources/lib/translate.py', 'resources/lib/subs_engine_bridge.py',
                         'resources/lib/gender_guard.py', 'resources/lib/srt_wire.py'):
            self.assertIn(required, names)

    def test_left_out_modules_are_reached_only_inside_try(self):
        files = [r for r in shipped() if r.suffix == '.py' and r.parts[:3] != ('resources', 'patches', 'darksubs')]
        mods = {'.'.join(r.with_suffix('').parts) for r in files}
        bad = []
        for rel in files:
            text = (SRC / rel).read_text(encoding='utf-8', errors='replace')
            if rel.as_posix() == 'default.py':
                text = bsm.slim_default(text)
            tree = ast.parse(text)
            parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
            pkg = '.'.join(rel.with_suffix('').parts[:-1])
            for node in ast.walk(tree):
                for target in import_targets(node, pkg):
                    if target in mods or target in ('resources.lib',) or target + '.__init__' in mods:
                        continue
                    if not guarded(node, parents):
                        bad.append('%s:%d -> %s' % (rel.as_posix(), node.lineno, target))
        self.assertEqual(bad, [])

    def test_default_py_loses_the_build_actions_only(self):
        source = (SRC / 'default.py').read_text(encoding='utf-8')
        slim = bsm.slim_default(source)
        compile(slim, 'default.py', 'exec')
        actions = re.findall(r"action == '([a-z_]+)'", slim)
        for action in bsm.BUILD_ACTIONS:
            self.assertNotIn(action, actions)
        for action in ('search', 'manualsearch', 'download', 'translate_file',
                       'bg_translate_picker', 'connect_gemini', 'connect_telegram', 'engine_test'):
            self.assertIn(action, actions)
        # The chain opened with the two removed build actions; it now opens
        # with `if action == 'search'` (compile() above rejects a dangling elif).
        self.assertEqual(actions[0], 'search')
        self.assertIn("        if action == 'search':", slim)
        for token in ('torbox_status', 'debrid_notice_settings', 'open_pov_settings',
                      'plugin.video.pov not found', 'user/stats', 'פתח את ה-Wizard'):
            self.assertNotIn(token, slim)


if __name__ == '__main__':
    unittest.main()
