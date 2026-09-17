#!/usr/bin/env python3
"""Slow diagnostics and speculative subtitle imports stay off the home path.

The performance regression is architecture-specific in size, so this test pins
the scheduling properties instead of a desktop wall-clock number. It also runs
the warm-queue function with a real queued JSON job: a title the viewer actually
opened must bypass the speculative delay and reach run_warm immediately.
"""
import ast
import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
SERVICE = os.path.normpath(os.path.join(
    HERE, '..', 'addons', 'service.subtitles.kodipovilai', 'service.py'))
SRC = open(SERVICE, encoding='utf-8').read()
TREE = ast.parse(SRC)
FAIL = []


def check(label, condition, detail=''):
    print('%-4s %s%s' % ('ok' if condition else 'FAIL', label,
                         (' -- ' + detail) if detail and not condition else ''))
    if not condition:
        FAIL.append(label)


def function(name):
    return next(node for node in TREE.body
                if isinstance(node, ast.FunctionDef) and node.name == name)


def load_function(name, namespace):
    node = function(name)
    code = compile(ast.Module(body=[node], type_ignores=[]), SERVICE, 'exec')
    exec(code, namespace)
    return namespace[name]


print('=== architecture-aware startup budget ===')
check('ARM/x86 32-bit gets at least 45 seconds to settle',
      '_BACKGROUND_SETTLE_32 = 45.0' in SRC)
check('other architectures also avoid the first 15 seconds',
      '_BACKGROUND_SETTLE_OTHER = 15.0' in SRC)
settle = function('_background_settle_seconds')
check('the architecture test uses the Python pointer-size boundary',
      any(isinstance(n, ast.Attribute) and n.attr == 'maxsize'
          for n in ast.walk(settle)))


print('\n=== patch-health is scheduled, not executed by the repair pass ===')
started = []


class FakeThread:
    def __init__(self, target, daemon=False):
        self.target = target
        self.daemon = daemon

    def start(self):
        started.append(self)


report = load_function('_report_patcher_health', {
    'threading': types.SimpleNamespace(Thread=FakeThread),
})
report()
check('the repair step starts exactly one worker', len(started) == 1)
check('the worker is a daemon and cannot hold Kodi shutdown open',
      len(started) == 1 and started[0].daemon is True)

# If Kodi shuts down during the settle window, the worker must return before it
# imports patcher_health. No resources package is installed in this test, so an
# accidental early import also makes the check fail loudly.
waits = []


class AbortMonitor:
    def waitForAbort(self, seconds):
        waits.append(seconds)
        return True


started[0].target.__globals__.update({
    'xbmc': types.SimpleNamespace(Monitor=lambda: AbortMonitor()),
    '_background_settle_seconds': lambda: 45.0,
    '_background_ui_busy': lambda: False,
})
try:
    started[0].target()
    cancelled_cleanly = True
except Exception:
    cancelled_cleanly = False
check('the full tree scan waits for the settle window',
      cancelled_cleanly and waits == [45.0], repr(waits))


print('\n=== a real HEB warm request bypasses that delay ===')
queue_dir = tempfile.mkdtemp(prefix='he-warm-budget-')
job_path = os.path.join(queue_dir, 'one.json')
with open(job_path, 'w', encoding='utf-8') as handle:
    json.dump({'mk': 'movie:123', 'title': 'Probe'}, handle)

events = []
warm_waits = []


class WarmMonitor:
    def __init__(self):
        self.done = False

    def abortRequested(self):
        return False

    def waitForAbort(self, seconds):
        warm_waits.append(seconds)
        if seconds == 0.2:
            self.done = True
            return True
        return False


class CaptureThread(FakeThread):
    def start(self):
        events.append(('thread', self.target))


hsm = types.ModuleType('resources.lib.he_sub_match')
hsm._warm_queue_dir = lambda: queue_dir
hsm._dbg = lambda message: events.append(('log', message))
hsm.run_warm = lambda info: events.append(('warm', info.get('mk')))
pkg = types.ModuleType('resources')
lib = types.ModuleType('resources.lib')
lib.he_sub_match = hsm
pkg.lib = lib
saved = {name: sys.modules.get(name) for name in
         ('resources', 'resources.lib', 'resources.lib.he_sub_match')}
sys.modules.update({
    'resources': pkg,
    'resources.lib': lib,
    'resources.lib.he_sub_match': hsm,
})
try:
    ns = {
        'os': os,
        'time': __import__('time'),
        'threading': types.SimpleNamespace(Thread=CaptureThread),
        '_background_settle_seconds': lambda: 45.0,
        '_background_ui_busy': lambda: False,
    }
    start = load_function('_start_he_warm_drainer', ns)
    monitor = WarmMonitor()
    start(monitor)
    worker = [value for kind, value in events if kind == 'thread'][0]
    worker()
finally:
    for name, value in saved.items():
        if value is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = value

check('the queued title reached run_warm on the first poll',
      ('warm', 'movie:123') in events, repr(events))
check('the real request did not wait for the 45-second idle preload',
      warm_waits[:2] == [0.5, 0.2], repr(warm_waits))
check('the claimed queue job was removed before running it',
      not os.path.exists(job_path))


# Mutation proof: removing the time gate would put the expensive speculative
# import straight back into the first loop. The assertion must notice it.
warm_node = function('_start_he_warm_drainer')
compare = [n for n in ast.walk(warm_node)
           if isinstance(n, ast.Compare)
           and any(isinstance(x, ast.Name) and x.id == 'preload_at'
                   for x in [n.left] + list(n.comparators))]
check('the idle preload remains behind its explicit time gate', len(compare) == 1)

print('\nFAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
