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
import re
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
# The detail string is built from llog[0] BEFORE check() decides whether it
# is needed, so an empty llog used to raise TypeError here and take the whole
# run down instead of reporting a failure. Found when a change to the injected
# block stopped it logging at all -- the test could not say so.
check('a huge query is truncated rather than dumped into the log',
      bool(llog) and len(llog[0]) < 400,
      'line is %d chars' % len(llog[0]) if llog else 'nothing was logged')


# --- 1b. the shape v1 actually wrote, taken from history --------------------
# _revert matches a WHOLE BLOCK, so upgrading a device from v1 to v2 works only
# if _SHAPES carries v1 byte for byte. Nothing else here can check that: the
# "an older injection is replaced" case above fakes an old version by RENAMING
# the current shape's marker, so it would pass with a _SHAPES entry that bore
# no resemblance to what v1 shipped -- and the device would be left on v1
# forever, still logging the old line, with ensure_patched returning
# 'revert_failed' into a log nobody reads.
#
# The only non-circular source for "what v1 wrote" is git. If git is not there
# (a packaged checkout), say so rather than pretending the check ran.
def _shipped_shapes():
    """{marker: REPLACEMENT} for every version of this patcher in history."""
    import subprocess
    rel = ('addons/service.subtitles.kodipovilai/resources/lib/'
           'pov_directory_timing_patcher.py')
    root = os.path.normpath(os.path.join(HERE, '..'))
    try:
        revs = subprocess.run(
            ['git', '-C', root, 'log', '--format=%H', '--', rel],
            capture_output=True, text=True, timeout=60)
    except Exception:
        return None
    if revs.returncode:
        return None
    out = {}
    for rev in revs.stdout.split():
        blob = subprocess.run(['git', '-C', root, 'show', '%s:%s' % (rev, rel)],
                              capture_output=True, text=True, timeout=60)
        if blob.returncode:
            continue
        ns = {'__file__': rel}
        try:
            exec(compile(blob.stdout, rel, 'exec'), ns)
        except Exception:
            continue
        if 'MARKER' in ns and 'REPLACEMENT' in ns:
            out.setdefault(ns['MARKER'], ns['REPLACEMENT'])
    return out


_hist = _shipped_shapes()
if _hist is None:
    print('SKIP git is unavailable -- cannot check the recorded old shapes')
else:
    _slot = mod5._MARKER_SLOT
    _checked = 0
    for _marker, _shape in sorted(_hist.items()):
        if _marker == mod5.MARKER:
            continue
        _checked += 1
        check('%s is recorded byte-for-byte in _SHAPES' % _marker.strip('# '),
              _shape.replace(_marker, _slot) in mod5._SHAPES,
              'a device on this version cannot be upgraded')

        # and prove it end to end: inject the OLD block, then upgrade for real
        _homeh, _entryh = fresh_pov(PRELUDE + ROUTER)
        with open(_entryh, encoding='utf-8', newline='') as _f:
            _stock = _f.read()
        with open(_entryh, 'w', encoding='utf-8', newline='') as _f:
            _f.write(_stock.replace(mod5.ANCHOR, _shape, 1))
        _st = load(_homeh).ensure_patched()
        _after = read(_entryh)
        check('...and a device carrying it upgrades cleanly',
              _st == 'repatched', _st)
        check('...leaving only the current marker',
              mod5.MARKER in _after and _marker not in _after,
              'markers left: %s' % re.findall(r'# AI_SUBS_POV_DIRTIMING_v\d+',
                                              _after))
        check('...and the result still compiles',
              compile(_after, 'entry.py', 'exec') is not None)

    # The loop must have had something to do. Only COMMITTED versions are in
    # history, so while a bump is still uncommitted the current marker is
    # absent from _hist and every entry is an old one -- which is the case
    # this guards: an empty loop would report four silent passes.
    check('at least one superseded version was actually checked', _checked,
          'history held %s and the loop did nothing' % sorted(_hist))


# --- 2a. the module counters say cold or warm ------------------------------
# v2 of the wrapper adds `mods=A->B`, the size of sys.modules before and after
# the call. It exists to settle a question the seconds alone cannot: whether
# the ~1.75s floor measured in the field is POV re-importing itself on a fresh
# interpreter, or real work. A is the discriminator (a reused interpreter
# arrives with hundreds of modules already loaded, a fresh one with a fraction
# of that) and B - A is how many the route itself had to load.
#
# So the field has to actually track imports, not be a decorative constant.
_MODS_RE = re.compile(r'mods=(-?\d+)->(-?\d+)')

check('the timing line carries the module counts',
      _MODS_RE.search(joined) is not None, joined)

_m = _MODS_RE.search(joined)
if _m:
    _a, _b = int(_m.group(1)), int(_m.group(2))
    check('...as two real counts, not the -1 fallback', _a > 0 and _b > 0,
          '%s->%s' % (_a, _b))
    check('...and a route that imports nothing does not move them', _a == _b,
          '%s->%s -- this route only sleeps' % (_a, _b))

# and now a route that DOES import something, to prove the field moves at all
_VICTIM = 'colorsys'
check('the module used to prove this is genuinely not loaded yet',
      _VICTIM not in sys.modules,
      'pick a different stdlib module or the next check proves nothing')

_IMPORTING = (
    "import time as _t\n"
    "def routing(sys):\n"
    "\timport %s\n"
    "\t_t.sleep(%s)\n"
    "\treturn ('directory', '')\n"
    "\n"
) % (_VICTIM, _ROUTING_SECONDS)

_home7, _entry7 = fresh_pov(_IMPORTING + ROUTER)
load(_home7).ensure_patched()
_, _, _ilog = run_router(read(_entry7), ARGV)
_im = _MODS_RE.search(' | '.join(_ilog))
check('a route that imports one module reports one more module',
      _im is not None and int(_im.group(2)) - int(_im.group(1)) == 1,
      ' | '.join(_ilog) or 'nothing was logged')


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
