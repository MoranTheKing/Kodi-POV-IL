"""Safe platform probe tests: never send a real signal, including mutations."""
import ast
import builtins
from pathlib import Path
import types
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'addons/service.subtitles.kodipovilai/resources/lib/pov_reload.py'

class PidProbeTests(unittest.TestCase):
    def probe(self, platform, pid=123, error=None, mutate=False):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_pid_alive')
        if mutate:
            for n in ast.walk(node):
                if isinstance(n, ast.If) and isinstance(n.test, ast.Compare) and ast.unparse(n.test) == "os.name == 'nt'":
                    n.test = ast.Constant(False)
        calls = []
        def kill(*args):
            calls.append(args)
            if error:raise error
        fake = types.SimpleNamespace(name=platform, kill=kill)
        original = builtins.__import__
        def importer(name, *args, **kwargs):
            return fake if name == 'os' else original(name, *args, **kwargs)
        scope = {'__builtins__': dict(vars(builtins), __import__=importer)}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(SOURCE), 'exec'), scope)
        return scope['_pid_alive'](pid), calls

    def test_windows_never_sends_signal(self):
        self.assertEqual(self.probe('nt'), (True, []))

    def test_invalid_pid_never_sends_signal(self):
        for pid in (None, 0, -1):self.assertEqual(self.probe('nt', pid), (False, []))

    def test_posix_probe_retains_semantics(self):
        self.assertEqual(self.probe('posix'), (True, [(123, 0)]))
        self.assertFalse(self.probe('posix', error=ProcessLookupError())[0])
        self.assertTrue(self.probe('posix', error=PermissionError())[0])

    def test_guard_mutation_exposes_unsafe_call_without_real_signal(self):
        self.assertEqual(self.probe('nt', mutate=True)[1], [(123, 0)])

if __name__ == '__main__':unittest.main()
