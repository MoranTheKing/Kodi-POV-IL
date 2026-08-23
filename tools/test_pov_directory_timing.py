#!/usr/bin/env python3
"""Turning "the spinner feels long" into a number.

THE REPORT: a spinner on every category press, and a claim that a build from a
month earlier felt lighter. The log that came with it is the problem in
miniature. It is info level -- which is what a user can actually produce --
and it contains not one number about POV. The only trace of navigation in it
is Kodi's own

    Control 51 in window 10025 has been asked to focus, but it can't

sixteen times across three minutes, with gaps of 3 to 24 seconds. Those gaps
are the user's reading time and the directory build added together, and no
amount of staring separates them. Any diagnosis from that is a guess, and a
guess about performance is how a build acquires an optimisation that optimises
nothing.

So this ships the measurement first. Router.run in POV's entry.py is the one
door every plugin invocation goes through, so a single insertion times every
category, list and search, and writes one INFO line naming the seconds and the
route.

WHAT THIS PINS -- and the second group is the point:

  * the patch applies to real POV, once, idempotently, and refuses a shape it
    does not recognise;
  * EXECUTION. The line actually appears, it carries a plausible number, the
    route is named, and -- the one that matters -- `run` returns EXACTLY what
    it returned before. A measurement that changes the thing it measures is
    worse than no measurement.
  * and a call that ends in SystemExit is still timed. Router.__exit__ raises
    one by design, and a call that ends that way is exactly the sort worth a
    number; a trailing log line instead of a `finally` would miss every one.

Run: python3 tools/test_pov_directory_timing.py
"""
import atexit
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
LIB = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
PATCHER = os.path.join(LIB, 'pov_directory_timing_patcher.py')
STOCK = os.environ.get('POV_STOCK') or (
    '/tmp/claude-0/-home-user-Kodi-POV-IL/'
    '70968383-5f01-52a3-afe7-ced1aba28071/scratchpad/pov6813/plugin.video.pov')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


# The Router class, verbatim from POV 6.08.13. Section 0 asserts that against
# a stock tree when one is present -- a hand-written approximation would let
# the anchor drift while this still passed.
ROUTER = (
    "class Router:\n"
    "\tdef __enter__(self):\n"
    "\t\treturn self\n"
    "\n"
    "\tdef __exit__(self, exc_type, exc_value, traceback):\n"
    "\t\tif get_property('pov_rli_fix') != 'true' or not "
    "kodi_utils.external_browse(): return\n"
    "\t\tmessage = f\"pov not in "
    "'{kodi_utils.get_infolabel('Container.PluginName')}'\"\n"
    "\t\traise SystemExit(message)\n"
    "\n"
    "\tdef run(self, sys):\n"
    "\t\twith self: return routing(sys)\n"
)

# enough of a module around it to import and call. `routing`, `logger`,
# `get_property` and `kodi_utils` are module globals in the real entry.py too.
# routing() SLEEPS, so the logged number can be checked against real elapsed
# time rather than against "looks like a number". A version that hardcoded the
# value passed every other check in this file, which is why this exists.
_ROUTING_SECONDS = 0.35
PRELUDE = (
    "import time as _t\n"
    "def routing(sys):\n"
    "\t_t.sleep(%s)\n"
    "\treturn ('directory', sys.argv[2] if len(sys.argv) > 2 else '')\n"
    "\n"
) % _ROUTING_SECONDS

_SCRATCH = []


@atexit.register
def _clean():
    for d in _SCRATCH:
        shutil.rmtree(d, ignore_errors=True)


def fresh_pov(entry_src=None):
    home = tempfile.mkdtemp(prefix='povtiming-')
    _SCRATCH.append(home)
    root = os.path.join(home, 'addons', 'plugin.video.pov')
    dest = os.path.join(root, 'resources', 'lib', 'entry.py')
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if entry_src is None and os.path.isdir(STOCK):
        shutil.copy(os.path.join(STOCK, 'resources', 'lib', 'entry.py'), dest)
    else:
        with io.open(dest, 'w', encoding='utf-8', newline='') as f:
            f.write(entry_src if entry_src is not None
                    else PRELUDE + ROUTER)
    return home, dest


def load(home):
    for n in list(sys.modules):
        if n.split('.')[0] in ('resources', 'xbmcvfs'):
            sys.modules.pop(n, None)
    vfs = types.ModuleType('xbmcvfs')
    vfs.translatePath = lambda p: p.replace('special://home/', home + os.sep)
    sys.modules['xbmcvfs'] = vfs
    pkg = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    lib.__path__ = [LIB]
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = lib
    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.log = lambda *a, **k: None
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku
    spec = importlib.util.spec_from_file_location('pdt_t', PATCHER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def read(path):
    with io.open(path, encoding='utf-8', newline='') as f:
        return f.read()


# --- 0. the anchor is really POV -------------------------------------------
print('fixture: %s' % ('real stock POV' if os.path.isdir(STOCK)
                       else 'a byte-slice of real POV (no stock tree here)'))
if os.path.isdir(STOCK):
    real = read(os.path.join(STOCK, 'resources', 'lib', 'entry.py'))
    check('the Router fixture is verbatim POV', real.count(ROUTER) == 1,
          'found %d times -- the anchor has drifted' % real.count(ROUTER))


# --- 1. it applies ---------------------------------------------------------
print()
print('=== the patch applies ===')
home, entry = fresh_pov()
mod = load(home)
st = mod.ensure_patched()
check('it patches a stock entry.py', st == 'patched', st)
src = read(entry)
check('the marker is there exactly once', src.count(mod.MARKER) == 1,
      'found %d' % src.count(mod.MARKER))
try:
    compile(src, entry, 'exec')
    ok = True
except SyntaxError as e:
    ok, err = False, str(e)
check('...and the file still compiles', ok, locals().get('err', ''))
check('running it again changes nothing', mod.ensure_patched() == 'unchanged')

# a shape POV changed: leave it completely alone rather than guess
home2, entry2 = fresh_pov(PRELUDE + "class Router:\n"
                          "\tdef run(self, sys, extra=None):\n"
                          "\t\treturn routing(sys)\n")
mod2 = load(home2)
before2 = read(entry2)
check('a refactored Router is left untouched',
      mod2.ensure_patched() == 'unmatched')
check('...byte for byte', read(entry2) == before2)

home3, entry3 = fresh_pov(PRELUDE + ROUTER + '\n' + ROUTER.replace(
    'class Router:', 'class Router2:'))
mod3 = load(home3)
before3 = read(entry3)
check('a duplicated shape is refused, not patched at the first copy',
      mod3.ensure_patched() == 'unmatched')
check('...and that file is untouched too', read(entry3) == before3)

# CRLF
home4, entry4 = fresh_pov((PRELUDE + ROUTER).replace('\n', '\r\n'))
mod4 = load(home4)
check('a CRLF file patches', mod4.ensure_patched() == 'patched')
check('...without introducing a bare LF',
      '\n' not in read(entry4).replace('\r\n', ''))

# an older marker: the revert has to put POV's own two lines back, not walk
# indents -- the line to keep is nested INSIDE the block to remove.
home5, entry5 = fresh_pov(PRELUDE + ROUTER)
mod5 = load(home5)
mod5.ensure_patched()
with io.open(entry5, encoding='utf-8', newline='') as f:
    aged = f.read().replace(mod5.MARKER, '# AI_SUBS_POV_DIRTIMING_v0')
with io.open(entry5, 'w', encoding='utf-8', newline='') as f:
    f.write(aged)
mod5b = load(home5)
mod5b.MARKER = mod5.MARKER
# re-point the module's REPLACEMENT at the aged marker so the revert can
# recognise the block it is meant to remove, exactly as a real version bump
# would have to.
st5 = mod5b.ensure_patched()
check('an older injection is replaced, not stacked',
      st5 in ('repatched', 'patched'), st5)
check('...leaving exactly one marker',
      read(entry5).count('DIRTIMING_v') == 1,
      'found %d' % read(entry5).count('DIRTIMING_v'))


# --- 2. IT ACTUALLY MEASURES, AND CHANGES NOTHING --------------------------
print()
print('=== the line appears, and run still does what it did ===')


def run_router(source, argv, exit_raises=None):
    """exec the patched (or stock) module and call Router().run(sys).

    Returns (returned value, raised exception or None, [log lines]).
    """
    logged = []
    fake_sys = types.SimpleNamespace(argv=argv)
    ns = {
        'logger': lambda tag, msg: logged.append('%s: %s' % (tag, msg)),
        'get_property': lambda k: 'true' if exit_raises else 'false',
        'kodi_utils': types.SimpleNamespace(
            external_browse=lambda: bool(exit_raises),
            get_infolabel=lambda k: 'somewhere-else'),
    }
    exec(compile(source, 'entry.py', 'exec'), ns)
    router = ns['Router']()
    try:
        return router.run(fake_sys), None, logged
    except BaseException as e:      # SystemExit is not an Exception
        return None, e, logged


STOCK_SRC = PRELUDE + ROUTER
home6, entry6 = fresh_pov(STOCK_SRC)
mod6 = load(home6)
mod6.ensure_patched()
PATCHED_SRC = read(entry6)

ARGV = ['plugin://plugin.video.pov/', '7',
        '?action=tmdb_tv_networks&name=Disney%2b&network_id=2739']

sval, serr, slog = run_router(STOCK_SRC, ARGV)
check('STOCK logs nothing about how long it took', not slog,
      'it logged %s -- then this patch has no reason to exist' % slog)

pval, perr, plog = run_router(PATCHED_SRC, ARGV)
joined = ' | '.join(plog)
check('PATCHED writes exactly one timing line', len(plog) == 1, joined)
check('...tagged so a user log can be grepped for it', mod6.TAG in joined,
      joined)
check('...naming the route that was slow', 'tmdb_tv_networks' in joined,
      joined)
_secs = [float(part[:-1]) for part in joined.split()
         if part.endswith('s') and part[:-1].replace('.', '', 1).isdigit()]
check('...with a number of seconds in it', len(_secs) == 1, joined)
# AND THE NUMBER IS THE REAL ONE. routing() sleeps a known amount above; a
# timer that reported a constant, or measured the wrong span, would satisfy
# every other check in this file. Verified by building exactly that mutant.
check('...that actually measured the work',
      _secs and _ROUTING_SECONDS <= _secs[0] < _ROUTING_SECONDS + 5,
      'logged %s for %ss of work' % (_secs, _ROUTING_SECONDS))
check('AND THE RETURN IS UNCHANGED -- a measurement that changes what it '
      'measures is worse than none', pval == sval and pval is not None,
      '%r vs %r' % (pval, sval))
check('...and it raised nothing new', perr is None and serr is None,
      '%r vs %r' % (perr, serr))

# A CALL THAT ENDS IN SystemExit IS STILL TIMED. Router.__exit__ raises one on
# purpose (its reuse-language-invoker guard), and those calls are exactly the
# ones worth a number. A trailing log line rather than a `finally` would miss
# every single one.
sval2, serr2, slog2 = run_router(STOCK_SRC, ARGV, exit_raises=True)
pval2, perr2, plog2 = run_router(PATCHED_SRC, ARGV, exit_raises=True)
check('stock still raises SystemExit from __exit__',
      isinstance(serr2, SystemExit), repr(serr2))
check('patched raises the SAME thing', isinstance(perr2, SystemExit)
      and str(perr2) == str(serr2), '%r vs %r' % (perr2, serr2))
check('...and times it anyway', len(plog2) == 1, str(plog2))

# an argv shorter than Kodi's usual three (some entry points pass two)
short = run_router(PATCHED_SRC, ['plugin://plugin.video.pov/', '7'])
check('a short argv does not break the line', len(short[2]) == 1
      and short[1] is None, '%r' % (short,))

# a route long enough to bloat every line it appears on
longq = '?action=x&' + 'y' * 4000
lval, lerr, llog = run_router(PATCHED_SRC,
                              ['plugin://plugin.video.pov/', '7', longq])
check('a huge query is truncated rather than dumped into the log',
      llog and len(llog[0]) < 400, 'line is %d chars' % len(llog[0] if llog
                                                           else 0))


# --- 2b. it never raises, whatever the filesystem does ---------------------
# The docstring has always said "Never raises". It was not true: _drop_pycache
# ends the happy path with a bare os.listdir, and a __pycache__ it cannot read
# threw straight out of ensure_patched -- AFTER the file had been written. The
# caller then logged a failure for a patch that had landed and skipped the
# note_patched() that makes POV re-import it, so the change sat on disk doing
# nothing.
print()
print('=== it never raises, even when the last step does ===')
home8, entry8 = fresh_pov(STOCK_SRC)
mod8 = load(home8)
_pycache = os.path.join(os.path.dirname(entry8), '__pycache__')
os.makedirs(_pycache, exist_ok=True)
_real_listdir = os.listdir


def _hostile_listdir(path):
    if path.endswith('__pycache__'):
        raise PermissionError('this directory cannot be read')
    return _real_listdir(path)


os.listdir = _hostile_listdir
try:
    st8, raised8 = None, None
    try:
        st8 = mod8.ensure_patched()
    except BaseException as e:
        raised8 = e
finally:
    os.listdir = _real_listdir
check('a failing last step does not escape ensure_patched', raised8 is None,
      'it raised %r -- the caller cannot tell a landed patch from a failed '
      'one' % raised8)
check('...and it still reports a status string', isinstance(st8, str), repr(st8))


# --- 3. it is wired in -----------------------------------------------------
print()
print('=== the service actually runs it ===')
svc = read(os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                        'service.py'))
check('service.py imports the patcher',
      'pov_directory_timing_patcher' in svc,
      'a patcher nobody calls measures nothing')

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
