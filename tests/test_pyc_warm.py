"""Kodi never writes bytecode (PYTHONDONTWRITEBYTECODE=1), so every POV click
recompiled its modules. pyc_warm writes the .pyc files Python will read anyway.
"""

import importlib.util
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


warm = _load('pyc_warm_test', LIBS / 'pyc_warm.py')


class PycWarmTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addons = Path(tmp.name)
        self.pov = self.addons / 'plugin.video.pov' / 'resources' / 'lib'
        self.pov.mkdir(parents=True)
        (self.pov / 'entry.py').write_text('X = 1\n')
        (self.addons / 'plugin.video.pov' / 'resources' / 'lib' / 'tests').mkdir()
        (self.pov / 'tests' / 'test_x.py').write_text('X = 2\n')
        other = self.addons / 'script.module.other' / 'lib'
        other.mkdir(parents=True)
        (other / 'py2.py').write_text('print "python 2"\n')
        (self.addons / 'packages').mkdir()
        (self.addons / 'packages' / 'ignored.py').write_text('X = 3\n')

    def run_warm(self, **kw):
        return warm.warm(str(self.addons), sleep=lambda s: None, **kw)

    def test_writes_a_pyc_the_import_system_accepts(self):
        self.assertEqual(self.run_warm(), (1, 0, 1))      # entry.py done, py2 file skipped
        cfile = importlib.util.cache_from_source(str(self.pov / 'entry.py'))
        self.assertTrue(os.path.isfile(cfile))
        self.assertFalse(os.path.exists(importlib.util.cache_from_source(str(self.pov / 'tests' / 'test_x.py'))))
        sys.path.insert(0, str(self.pov))
        self.addCleanup(sys.path.remove, str(self.pov))
        loader = importlib.machinery.SourceFileLoader('entry_pyc_check', str(self.pov / 'entry.py'))
        with mock.patch('builtins.compile', side_effect=AssertionError('recompiled')):
            code = loader.get_code('entry_pyc_check')        # served from the pyc
        ns = {}
        exec(code, ns)
        self.assertEqual(ns['X'], 1)

    def test_a_second_pass_only_checks(self):
        self.run_warm()
        self.assertEqual(self.run_warm(), (0, 1, 1))

    def test_an_edited_source_is_recompiled(self):
        self.run_warm()
        src = self.pov / 'entry.py'
        src.write_text('X = 10  # patched\n')
        st = src.stat()
        os.utime(src, (st.st_atime, st.st_mtime + 5))
        self.assertEqual(self.run_warm(), (1, 0, 1))

    def test_pov_comes_first_and_it_stops_on_request(self):
        names = [Path(p).parts[-4] if 'plugin.video.pov' in p else Path(p).parts[-3]
                 for p in warm.sources(str(self.addons))]
        self.assertEqual(names[0], 'plugin.video.pov')
        self.assertEqual(self.run_warm(should_stop=lambda: True), (0, 0, 0))

    def test_waits_while_a_video_plays(self):
        state = {'n': 0}

        def playing():
            state['n'] += 1
            return state['n'] < 3
        slept = []
        out = warm.warm(str(self.addons), should_pause=playing, sleep=slept.append)
        self.assertEqual(out, (1, 0, 1))
        self.assertIn(5, slept)


class ChildFlagCacheTests(unittest.TestCase):
    def test_the_gui_is_asked_once_per_invocation(self):
        calls = []
        xbmc = types.SimpleNamespace(getCondVisibility=lambda c: calls.append(c) or False)
        guard = _load('age_guard_test', LIBS / 'patches' / 'profile_age_guard.py')
        with mock.patch.dict(sys.modules, {'xbmc': xbmc}):
            for _ in range(5):
                self.assertFalse(guard._skin_child_flag())
            self.assertEqual(calls, ['Skin.HasSetting(POVILChild)'])
            guard._CHILD_FLAG[1] -= guard._CHILD_FLAG_TTL_S + 1     # expired
            guard._skin_child_flag()
            self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
