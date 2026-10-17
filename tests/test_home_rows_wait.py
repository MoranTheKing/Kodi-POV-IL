"""The build's services hold their start-up work until the home rows load."""

import ast
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (ROOT / 'plugin.program.kodipovilwizard' / 'startup.py',
           ROOT / 'service.subtitles.kodipovilai' / 'service.py')


def _load(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    body = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name == 'wait_for_home_rows')
            or (isinstance(n, ast.Assign) and any(getattr(t, 'id', '') == 'ROWS_PROPERTY' for t in n.targets))]
    ns = {}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), 'exec'), ns)
    return ns['wait_for_home_rows']


class Clock(object):
    def __init__(self):
        self.now = 1000.0
        self.events = []        # (time, property value)
        self.home_at = 1001.0

    def time(self):
        return self.now


class WaitTests(unittest.TestCase):
    def run_wait(self, fn, clock, rows):
        props = {}
        win = types.SimpleNamespace(getProperty=lambda k: props.get(k, ''))

        def wait(seconds):
            clock.now += seconds
            for t in [t for t in rows if t <= clock.now]:
                props['povil.rows.last'] = '%.3f' % t
            return False
        xbmc = types.SimpleNamespace(getCondVisibility=lambda c: clock.now >= clock.home_at)
        xbmcgui = types.SimpleNamespace(Window=lambda wid: win)
        monitor = types.SimpleNamespace(waitForAbort=wait)
        with mock.patch.dict(sys.modules, {'xbmc': xbmc, 'xbmcgui': xbmcgui}), \
                mock.patch('time.time', clock.time):
            fn(monitor)
        return clock.now

    def test_waits_for_rows_to_settle(self):
        for path in SOURCES:
            fn = _load(path)
            clock = Clock()
            done = self.run_wait(fn, clock, rows=[1001.5, 1002.0, 1003.2])
            self.assertGreaterEqual(done, 1003.2 + 1.5, path.name)
            self.assertLess(done, 1003.2 + 2.0, path.name)

    def test_no_rows_means_a_short_wait_and_the_cap_holds(self):
        for path in SOURCES:
            fn = _load(path)
            clock = Clock()
            self.assertLess(self.run_wait(fn, clock, rows=[]) - 1001.0, 5.5, path.name)
            clock = Clock()
            rows = [1001.0 + i for i in range(40)]                         # rows forever
            self.assertLessEqual(self.run_wait(fn, clock, rows=rows) - 1000.0, 15.5, path.name)


if __name__ == '__main__':
    unittest.main()
