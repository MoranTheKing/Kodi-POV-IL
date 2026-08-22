#!/usr/bin/env python3
"""A debrid that answers late must not delete the sources POV already found.

THE REPORT, from two users on the same build: the counters climb while POV
searches -- 40, 120, 300 -- and then the list never opens. "No results" on a
title that certainly has sources. Intermittent; the same title works on the
second try. Only on Premiumize. TorBox on the identical build is fine.

TWO DEFECTS, both in the second half of the search:

  1. final_sources is built EXCLUSIVELY inside the loop over the debrid
     cache-check threads that finished in time. One debrid configured, one
     thread; a second late and every torrent phase 1 found is discarded.

  2. a check that FAILED -- timed out, refused, malformed -- is swallowed by
     modules/debrid.py's bare `except: pass` and comes back as an empty cached
     list, indistinguishable from an honest "none of these are cached". Every
     source is then stamped 'Uncached <name>', and

         return [i for i in results if 'Uncached' not in i.get(...)]

     with "Display Uncached Torrents" off by default deletes all of them.

Both end at an empty screen. POV already draws the distinction that fixes
this -- Real-Debrid and AllDebrid checks are labelled 'Unchecked', which that
filter keeps -- it just never applies it to a check that did not happen.

WHAT THIS PINS, and section 2 is the point: the block is lifted OUT of a file
on disk and EXECUTED. Stock must demonstrate the bug first -- a late thread in,
an empty list out -- before the patched build is allowed to claim it fixes it.
And every case where the debrid DID answer must come out byte-identical to
stock, because this is a fix for the failure path and nothing else.

HOW REAL "REAL" IS, said plainly. The PATCHED side is always the true file the
patcher just wrote. The STOCK side is the real tree when POV_STOCK is set or the
session's stock copy exists, and the transcribed FIXTURES otherwise -- and
section 0 only proves those are verbatim when a real tree IS present. So on a
machine with no stock POV this suite still executes real code, but its
guarantee against future POV drift is the weaker one. The banner printed at the
top says which of the two ran.

Run: python3 tools/test_pov_debrid_timeout.py
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
PATCHER = os.path.join(LIB, 'pov_debrid_timeout_patcher.py')
STOCK = os.environ.get('POV_STOCK') or (
    '/tmp/claude-0/-home-user-Kodi-POV-IL/'
    '70968383-5f01-52a3-afe7-ced1aba28071/scratchpad/pov6813/plugin.video.pov')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


# --- fixtures: real POV, byte for byte -------------------------------------
# Verbatim from POV 6.08.13. Section 0 asserts that against a stock tree when
# one is present; a hand-written approximation would let the anchor drift and
# the test would still pass.
SOURCES_PHASE = (
    "\t\t\tself.thread_monitor(threads, ls(32579), True)\n"
    "\t\t\tthreads = [i for i in threads if i.done() and not i.exception()]\n"
    "\t\t\tfor name, hashes in ((fut.name, fut.result()) for fut in threads):\n"
    "\t\t\t\tif name in ('realdebrid', 'alldebrid'): uncached = '%s %s' % ('Unchecked', name)\n"
    "\t\t\t\telse: uncached = '%s %s' % ('Uncached', name)\n"
    "\t\t\t\tself.final_sources.extend(\n"
    "\t\t\t\t\t{**i, 'cache_provider': name if i['hash'] in hashes else uncached, 'debrid': name}\n"
    "\t\t\t\t\tfor i in torrent_sources\n"
    "\t\t\t\t)\n"
)
# The filter that decides whether any of it is ever seen. Not patched by this
# module -- lifted so the test can prove the END of the road, not the middle.
SORT_UNCACHED = (
    "\tdef sort_uncached_torrents(self, results):\n"
    "\t\tresults.sort(key=lambda k: 'Unchecked' in k.get('cache_provider', ''), reverse=False)\n"
    "\t\tif self.source.background or self.source.autoplay:\n"
    "\t\t\treturn [i for i in results if 'Uncached' not in i.get('cache_provider', '')]\n"
    "\t\tif self.source.display_uncached_torrents or get_property('fs_filterless_search') == 'true':\n"
    "\t\t\treturn sorted(results, key=lambda k: 'Uncached' in k.get('cache_provider', ''), reverse=False)\n"
    "\t\treturn [i for i in results if 'Uncached' not in i.get('cache_provider', '')]\n"
)
DEBRID_CACHE_CHECK = (
    "\tdef cache_check(self):\n"
    "\t\ttry:\n"
    "\t\t\tself.cached_list.extend(i[0] for i in self.cached_hashes if i[1] == self.debrid and i[2] == 'True')\n"
    "\t\t\tunchecked_filter = {h[0] for h in self.cached_hashes if h[1] == self.debrid}\n"
    "\t\t\tunchecked_hashes = [i for i in self.hash_list if i not in unchecked_filter]\n"
    "\t\t\tif not unchecked_hashes: return self.cached_list\n"
    "\t\t\tif self.debrid in ('rd', 'ad'): checked_hashes = self.external_check_cache(unchecked_hashes)\n"
    "\t\t\telse: checked_hashes = self.function().check_cache(unchecked_hashes)\n"
    "\t\t\tif not checked_hashes: return self.cached_list\n"
    "\t\t\tchecked_hashes = set(checked_hashes)\n"
    "\t\t\thashes_to_cache = []\n"
    "\t\t\tprocess_append = hashes_to_cache.append\n"
    "\t\t\tcached_append = self.cached_list.append\n"
    "\t\t\tfor h in unchecked_hashes:\n"
    "\t\t\t\tif h in checked_hashes:\n"
    "\t\t\t\t\tcached_append(h)\n"
    "\t\t\t\t\tprocess_append((h, 'True'))\n"
    "\t\t\t\telse: process_append((h, 'False'))\n"
    "\t\t\tif hashes_to_cache: Thread(target=self.cache_write, args=(hashes_to_cache,)).start()\n"
    "\t\texcept: pass\n"
    "\t\treturn self.cached_list\n"
)

FIXTURES = {
    'resources/lib/modules/sources.py':
        'class ExternalManager:\n\tdef results(self, info):\n\t\ttry:\n'
        + SOURCES_PHASE
        + "\t\texcept: notification(32574)\n"
        + "\t\treturn self.final_sources\n\n"
        + 'class ResultsProcessor:\n' + SORT_UNCACHED,
    'resources/lib/modules/debrid.py':
        'from threading import Thread\nfrom modules import kodi_utils\n'
        'class DebridCheck:\n' + DEBRID_CACHE_CHECK,
}

_SCRATCH = []


@atexit.register
def _clean():
    for d in _SCRATCH:
        shutil.rmtree(d, ignore_errors=True)


def fresh_pov(fixtures=None):
    """A POV tree the patcher can work on: the real one where it exists, the
    byte-slice fixtures where it does not."""
    home = tempfile.mkdtemp(prefix='povdbgto-')
    _SCRATCH.append(home)
    root = os.path.join(home, 'addons', 'plugin.video.pov')
    if fixtures is None and os.path.isdir(STOCK):
        shutil.copytree(STOCK, root)
        return home, root
    for rel, body in (fixtures or FIXTURES).items():
        p = os.path.join(root, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with io.open(p, 'w', encoding='utf-8', newline='') as f:
            f.write(body)
    return home, root


LOG = []


def load(home):
    """The patcher, pointed at `home` as if it were special://home."""
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
    ku.log = lambda *a, **k: LOG.append(a[0] if a else '')
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku
    spec = importlib.util.spec_from_file_location('pdto_t', PATCHER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _read(root, rel):
    with io.open(os.path.join(root, *rel.split('/')),
                 encoding='utf-8', newline='') as f:
        return f.read()


# --- 0. the fixtures really are POV ----------------------------------------
print('fixture: %s' % ('real stock POV' if os.path.isdir(STOCK)
                       else 'byte-slices of real POV (no stock tree here)'))
if os.path.isdir(STOCK):
    for rel, slice_ in (('resources/lib/modules/sources.py', SOURCES_PHASE),
                        ('resources/lib/modules/sources.py', SORT_UNCACHED),
                        ('resources/lib/modules/debrid.py',
                         DEBRID_CACHE_CHECK)):
        real = _read(STOCK, rel)
        check('FIXTURE slice of %s is verbatim POV' % rel.split('/')[-1],
              real.count(slice_) == 1,
              'found %d times -- the anchor has drifted' % real.count(slice_))
    # THE NEAR MISS, pinned. The first line of the anchor is not unique --
    # POV runs the same filter over the PROVIDER threads a dozen lines above.
    # An anchor of that line alone would patch the wrong phase and every test
    # here would still pass, so the anchor is the whole four-line block.
    _s = _read(STOCK, 'resources/lib/modules/sources.py')
    _one = "\t\t\tthreads = [i for i in threads if i.done() and not i.exception()]\n"
    check('the first anchor line appears more than once in POV',
          _s.count(_one) == 2, 'found %d' % _s.count(_one))
    check('...and the whole block appears exactly once',
          _s.count(SOURCES_PHASE) == 1)
else:
    print('---- fixtures NOT checked against a real tree here')


# --- 1. it applies ----------------------------------------------------------
print()
print('=== the patch applies to real POV ===')
home, root = fresh_pov()
mod = load(home)
status = mod.ensure_patched()
print('   status: %s' % status)
check('both halves patch on a stock tree',
      status == 'sources=patched, debrid=patched', status)

for rel in ('resources/lib/modules/sources.py',
            'resources/lib/modules/debrid.py'):
    src = _read(root, rel)
    n = src.count(mod.MARKER)
    want = {'sources.py': 8, 'debrid.py': 6}[rel.split('/')[-1]]
    check('%s carries exactly the markers its block has' % rel.split('/')[-1],
          n == want, 'found %d, expected %d' % (n, want))
    try:
        compile(src.lstrip('﻿'), rel, 'exec')
    except SyntaxError as e:
        check('%s still compiles' % rel.split('/')[-1], False, str(e))
    else:
        check('%s still compiles' % rel.split('/')[-1], True)

check('running it again changes nothing',
      mod.ensure_patched() == 'sources=unchanged, debrid=unchanged')


# --- 2. EXECUTION: the block is lifted out of the file and run -------------
# Not a paraphrase. The debrid phase is cut out of sources.py -- stock from the
# stock tree, patched from the tree the patcher just wrote -- and exec'd. A
# `def` at column 0 with a body already indented three tabs is valid Python, so
# the bytes go in untouched.
print()
print('=== the block, executed: stock loses the list, patched keeps it ===')


def lift_phase(text):
    """POV's debrid phase, verbatim, as a callable."""
    lines = text.splitlines(True)
    a = next(i for i, l in enumerate(lines)
             if 'self.thread_monitor(threads, ls(32579), True)' in l)
    b = next(i for i, l in enumerate(lines) if i > a and l.strip() == ')')
    body = ''.join(lines[a:b + 1])
    ns = {}
    exec('def run(self, threads, torrent_sources, ls):\n' + body, ns)
    return ns['run']


def lift_filter(text):
    """POV's uncached filter, verbatim, as a callable."""
    lines = text.splitlines(True)
    a = next(i for i, l in enumerate(lines)
             if l.startswith('\tdef sort_uncached_torrents'))
    b = next(i for i, l in enumerate(lines)
             if i > a and l.strip() and not l.startswith('\t\t'))
    body = ''.join(lines[a + 1:b])
    ns = {'get_property': lambda *a, **k: ''}
    exec('def run(self, results):\n' + body, ns)
    return ns['run']


class Fut(object):
    """A concurrent.futures future, as far as this block can tell."""

    def __init__(self, name, result=None, done=True, exc=None):
        self.name, self._r, self._d, self._e = name, result, done, exc

    def done(self):
        return self._d

    def exception(self):
        return self._e

    def result(self):
        if self._e:
            raise self._e
        return self._r


class Manager(object):
    def __init__(self, debrid_torrents):
        self.debrid_torrents = debrid_torrents
        self.final_sources = []

    def thread_monitor(self, threads, status_line='', debrid=False):
        # The real one waits and then gives up; by the time it returns the
        # done() answers are whatever they are. Nothing to simulate.
        pass


class Src(object):
    background = autoplay = False
    display_uncached_torrents = False


class Proc(object):
    source = Src()


TORRENTS = [{'source': 'torrent', 'hash': 'h%d' % n, 'url': 'u%d' % n}
            for n in range(5)]

stock_run = lift_phase(_read(STOCK, 'resources/lib/modules/sources.py')
                       if os.path.isdir(STOCK)
                       else FIXTURES['resources/lib/modules/sources.py'])
patched_run = lift_phase(_read(root, 'resources/lib/modules/sources.py'))
seen = lift_filter(_read(STOCK, 'resources/lib/modules/sources.py')
                   if os.path.isdir(STOCK)
                   else FIXTURES['resources/lib/modules/sources.py'])


def play(run, futs, names=None):
    """Run the phase, then POV's own filter. Returns (built, shown)."""
    mgr = Manager(names if names is not None else [f.name for f in futs])
    run(mgr, set(futs), list(TORRENTS), lambda n: '')
    return mgr.final_sources, seen(Proc(), list(mgr.final_sources))


def marks(rows):
    return sorted({r['cache_provider'] for r in rows})


# THE REPORTED FAILURE. One debrid, still running when the monitor gave up.
late = [Fut('premiumize', done=False)]
s_built, s_shown = play(stock_run, late)
p_built, p_shown = play(patched_run, late)
check('STOCK: a late debrid discards every source it found',
      s_built == [] and s_shown == [],
      'stock built %d' % len(s_built))
check('PATCHED: the sources survive', len(p_built) == len(TORRENTS))
check('...labelled as not checked, not as not cached',
      marks(p_built) == ['Unchecked premiumize'], str(marks(p_built)))
check('...and POV\'s own filter shows every one of them',
      len(p_shown) == len(TORRENTS), '%d shown' % len(p_shown))

# THE SECOND ROAD TO THE SAME SCREEN. The thread finished -- because the HTTP
# request timed out INSIDE it and modules/debrid.py swallowed the error -- and
# said "nothing cached". Stock believes it.
failed = [Fut('premiumize', result=())]
s_built, s_shown = play(stock_run, [Fut('premiumize', result=[])])
p_built, p_shown = play(patched_run, failed)
check('STOCK: a failed check is read as "none of these are cached"',
      marks(s_built) == ['Uncached premiumize'], str(marks(s_built)))
check('...and the default filter then deletes all of them',
      s_shown == [], '%d shown' % len(s_shown))
check('PATCHED: a failed check (the sentinel) is "we could not check"',
      marks(p_built) == ['Unchecked premiumize'], str(marks(p_built)))
check('...and they are shown', len(p_shown) == len(TORRENTS))

# AND THE HALF THAT MUST NOT CHANGE. An honest empty answer is still believed.
honest = [Fut('premiumize', result=[])]
s_built, s_shown = play(stock_run, honest)
p_built, p_shown = play(patched_run, honest)
check('an honest "nothing cached" is still an authoritative no',
      marks(p_built) == ['Uncached premiumize'] and p_shown == [],
      str(marks(p_built)))
check('...byte-identical to stock', p_built == s_built and p_shown == s_shown)

# A NORMAL, SUCCESSFUL SEARCH. Nothing whatsoever may differ.
ok = [Fut('premiumize', result=['h1', 'h3'])]
s_built, s_shown = play(stock_run, ok)
p_built, p_shown = play(patched_run, ok)
check('a debrid that answers is handled exactly as before',
      p_built == s_built and p_shown == s_shown,
      '%s vs %s' % (marks(p_built), marks(s_built)))
check('...the cached ones are marked cached and shown',
      len(p_shown) == 2 and marks(p_shown) == ['premiumize'],
      str(marks(p_shown)))

# RD/AD ALREADY GOT THIS TREATMENT AND MUST KEEP IT.
for name in ('realdebrid', 'alldebrid'):
    s_built, _ = play(stock_run, [Fut(name, result=[])])
    p_built, p_shown = play(patched_run, [Fut(name, result=[])])
    check('%s is untouched -- Unchecked, and shown' % name,
          p_built == s_built and marks(p_built) == ['Unchecked ' + name]
          and len(p_shown) == len(TORRENTS), str(marks(p_built)))

# TWO DEBRIDS, ONE LATE. The one that answered must not be disturbed, and the
# one that did not must still contribute.
mixed = [Fut('torbox', result=['h0']), Fut('premiumize', done=False)]
s_built, s_shown = play(stock_run, mixed)
p_built, p_shown = play(patched_run, mixed)
check('STOCK: the late debrid contributes nothing at all',
      marks(s_built) == ['Uncached torbox', 'torbox'], str(marks(s_built)))
check('PATCHED: the debrid that answered is unchanged',
      [r for r in p_built if r['debrid'] == 'torbox']
      == [r for r in s_built if r['debrid'] == 'torbox'])
check('...and the late one contributes its sources, unchecked',
      marks([r for r in p_built if r['debrid'] == 'premiumize'])
      == ['Unchecked premiumize'])

# A FUTURE THAT RAISED is the same case as one that never finished.
s_built, _ = play(stock_run, [Fut('premiumize', exc=RuntimeError('boom'))])
p_built, p_shown = play(patched_run, [Fut('premiumize',
                                          exc=RuntimeError('boom'))])
check('a debrid thread that died is treated as late, not as absent',
      s_built == [] and marks(p_built) == ['Unchecked premiumize']
      and len(p_shown) == len(TORRENTS))

# ORDER IS STABLE. The late rows are walked in debrid_torrents order, so two
# identical searches produce identical lists.
two_late = [Fut('premiumize', done=False), Fut('torbox', done=False)]
first, _ = play(patched_run, two_late, names=['premiumize', 'torbox'])
second, _ = play(patched_run, list(reversed(two_late)),
                 names=['premiumize', 'torbox'])
check('the same search twice gives the same order',
      [r['debrid'] for r in first] == [r['debrid'] for r in second])

# AND A DEBRID THAT WAS NEVER ASKED must not appear. debrid_torrents is the
# list POV submitted; anything outside it has no thread and no rows.
built, _ = play(patched_run, [Fut('premiumize', done=False)],
                names=['premiumize'])
check('only the debrids POV actually asked appear',
      {r['debrid'] for r in built} == {'premiumize'})


# --- 3. the other half, executed: a failed check now says so ---------------
print()
print('=== cache_check, executed: failure is told apart from emptiness ===')

LOGGED = []


def lift_cache_check(text):
    lines = text.splitlines(True)
    a = next(i for i, l in enumerate(lines)
             if l.startswith('\tdef cache_check(self):'))
    b = next(i for i, l in enumerate(lines)
             if i > a and l.strip() and not l.startswith('\t\t'))
    body = ''.join(lines[a + 1:b])

    class _T(object):
        def __init__(self, target=None, args=()):
            self._t, self._a = target, args

        def start(self):
            self._t(*self._a)

    ku = types.SimpleNamespace(
        logger=lambda *a, **k: LOGGED.append(a[-1] if a else ''))
    ns = {'Thread': _T, 'kodi_utils': ku}
    exec('def run(self):\n' + body, ns)
    return ns['run']


class Chk(object):
    """A DebridCheck, as far as cache_check can tell."""

    def __init__(self, debrid='pm', hashes=('h0', 'h1'), known=(), reply=None):
        self.debrid, self.hash_list = debrid, list(hashes)
        self.cached_hashes, self.cached_list = list(known), []
        self.written, self._reply = [], reply

    def function(self):
        outer = self

        class _Api(object):
            def check_cache(self, unchecked):
                if isinstance(outer._reply, BaseException):
                    raise outer._reply
                return outer._reply
        return _Api()

    def external_check_cache(self, unchecked):
        if isinstance(self._reply, BaseException):
            raise self._reply
        return self._reply

    def cache_write(self, pairs):
        self.written.extend(pairs)


stock_cc = lift_cache_check(_read(STOCK, 'resources/lib/modules/debrid.py')
                            if os.path.isdir(STOCK)
                            else FIXTURES['resources/lib/modules/debrid.py'])
patched_cc = lift_cache_check(_read(root, 'resources/lib/modules/debrid.py'))

# The two shapes a Premiumize failure actually takes, both observed in POV's
# own code: `result['response']` on a refusal envelope is a KeyError, and on
# the None its _request returns after catching its own Timeout it is a
# TypeError. Neither escapes cache_check today.
for label, boom in (('a refusal envelope (KeyError)', KeyError('response')),
                    ('its own timeout (TypeError on None)',
                     TypeError("'NoneType' object is not subscriptable"))):
    s = stock_cc(Chk(reply=boom))
    LOGGED[:] = []
    p = patched_cc(Chk(reply=boom))
    check('STOCK: %s comes back as an empty cached list' % label, s == [],
          repr(s))
    check('PATCHED: %s comes back as the empty-tuple sentinel' % label,
          p == () and isinstance(p, tuple), repr(p))
    check('...and says so in the log, naming the provider',
          len(LOGGED) == 1 and 'pm' in LOGGED[0] and 'KODI_POV_IL' in LOGGED[0],
          str(LOGGED))

# NOTHING ELSE MOVES.
for label, kw in (
        ('an honest empty answer', {'reply': []}),
        ('a normal answer', {'reply': ['h1']}),
        ('everything already in the local cache',
         {'known': [('h0', 'pm', 'True'), ('h1', 'pm', 'True')]}),
        ('a local cache that says not-cached',
         {'known': [('h0', 'pm', 'False'), ('h1', 'pm', 'False')]})):
    a, b = Chk(**kw), Chk(**kw)
    check('%s is unchanged' % label,
          stock_cc(a) == patched_cc(b) and a.written == b.written,
          '%r vs %r' % (stock_cc(Chk(**kw)), patched_cc(Chk(**kw))))

# The rd/ad branch is deliberately NOT wrapped: a failure there already ends
# as 'Unchecked', which is what this whole change is trying to produce.
boom = KeyError('response')
check('the rd/ad branch keeps stock behaviour exactly',
      stock_cc(Chk(debrid='rd', reply=boom))
      == patched_cc(Chk(debrid='rd', reply=boom)) == [])

# AND THE JOIN: a None from cache_check must survive the trip into sources.py.
built, shown = play(patched_run, [Fut('premiumize',
                                      result=patched_cc(Chk(reply=boom)))])
check('the sentinel reaches sources.py and becomes a visible list',
      marks(built) == ['Unchecked premiumize'] and len(shown) == len(TORRENTS))


# --- 4. the two halves are independent, and that is the point --------------
# THE FIRST DRAFT WAS NOT. It had cache_check `return None`, which unpatched
# sources.py evaluates as `i['hash'] in None` -- TypeError, into
# `except: notification(32574)`: an error toast AND an empty list, worse than
# the bug. A review reached that state without any bug in the module at all:
# POV updates, rewriting sources.py's block but not debrid.py's six lines; the
# next pass gets `unmatched` and is killed before it can revert debrid.py.
#
# The sentinel is an empty TUPLE instead, so the half-applied state is not a
# failure mode at all. This section runs the real patched debrid.py against the
# real UNPATCHED sources.py and asserts it is byte-identical to stock.
print()
print('=== a half-applied pair behaves exactly like no patch at all ===')

STOCK_TEXT = {rel: _read(STOCK, rel) if os.path.isdir(STOCK)
              else FIXTURES[rel]
              for rel in ('resources/lib/modules/sources.py',
                          'resources/lib/modules/debrid.py')}
SRC_REL = 'resources/lib/modules/sources.py'
DBR_REL = 'resources/lib/modules/debrid.py'


def write(root, rel, text):
    with io.open(os.path.join(root, *rel.split('/')), 'w',
                 encoding='utf-8', newline='') as f:
        f.write(text)


# THE CASE THAT BROKE THE FIRST TUPLE, and the reason the sentinel carries the
# cached list instead of being bare. A hash the local DebridCache already
# confirmed, plus a DIFFERENT newly-seen hash whose live check then fails:
# stock still returns the known one and shows it as cached. A bare `()` threw
# it away, so unpatched sources.py marked it Uncached and the default filter
# DELETED it -- worse than doing nothing, in exactly the half-applied state
# the tuple exists to make safe. Every case below is run with this shape, not
# with an empty local cache.
KNOWN = [('h1', 'pm', 'True')]


def chk(**kw):
    kw.setdefault('known', KNOWN)
    kw.setdefault('hashes', ('h0', 'h1', 'h2'))
    return Chk(**kw)


boom = KeyError('response')
sentinel = patched_cc(chk(reply=boom))          # what patched debrid.py returns
legacy = stock_cc(chk(reply=boom))              # what stock debrid.py returns
check('(setup) stock keeps the locally-known hash on a failed check',
      list(legacy) == ['h1'], repr(legacy))
check('the sentinel carries the same contents, only as a tuple',
      tuple(sentinel) == tuple(legacy) and isinstance(sentinel, tuple),
      repr(sentinel))
try:
    half_built, half_shown = play(stock_run, [Fut('premiumize', result=sentinel)])
    raised = None
except BaseException as e:                       # noqa: BLE001 - that is the test
    raised = e
check('the sentinel through UNPATCHED sources.py does not raise',
      raised is None, repr(raised))
if raised is None:
    was_built, was_shown = play(stock_run, [Fut('premiumize', result=legacy)])
    check('...and gives byte-identical output to no patch at all',
          half_built == was_built and half_shown == was_shown)
    check('...INCLUDING the hash the local cache already knew about',
          marks(half_built) == ['Uncached premiumize', 'premiumize']
          and len(half_shown) == 1,
          '%s / %d shown' % (marks(half_built), len(half_shown)))
    # and the bare tuple the first draft used would have lost it
    bare_built, bare_shown = play(stock_run, [Fut('premiumize', result=())])
    check('...which a BARE tuple would have deleted -- hence the contents',
          bare_shown == [] and half_shown != bare_shown)

# AND THE VALUE THAT WOULD HAVE BROKEN IT. Pinned so nobody "simplifies" the
# sentinel back to None, or to a string (where `'' in "SENTINEL"` is True and a
# source with an empty hash would be reported as cached).
try:
    play(stock_run, [Fut('premiumize', result=None)])
    none_raised = False
except TypeError:
    none_raised = True
check('None WOULD have raised there -- hence the tuple', none_raised)
check('an empty hash is not "in" the sentinel', '' not in ())

# NOT-A-LIST IS THE GUARD, so anything a future POV returns is Unchecked rather
# than a TypeError. Stock crashes on all of these; patched does not.
for odd in (0, False, 5, 'x', None, ()):
    try:
        built, shown = play(patched_run, [Fut('premiumize', result=odd)])
        ok = marks(built) == ['Unchecked premiumize'] and len(shown) == len(TORRENTS)
        err = ''
    except BaseException as e:                   # noqa: BLE001
        ok, err = False, repr(e)
    check('a reply of %r is treated as unchecked, not as a crash' % (odd,),
          ok, err)

# ...and a real list is still trusted, in both directions.
built, _ = play(patched_run, [Fut('premiumize', result=[])])
check('an empty LIST is still an authoritative "not cached"',
      marks(built) == ['Uncached premiumize'])

# EMPTY INPUTS. Neither half may invent rows out of nothing.
built, shown = play(patched_run, [], names=[])
check('no debrids configured builds nothing', built == [] and shown == [])
_saved, TORRENTS[:] = list(TORRENTS), []
built, _ = play(patched_run, [Fut('premiumize', done=False)])
check('no torrents found builds nothing', built == [])
TORRENTS[:] = _saved

# --- 5. the things that break patchers ------------------------------------
print()
print('=== CRLF, an older marker, a missing file, a duplicated shape ===')

# CRLF. Kodi ships LF, but a file that has been through a Windows editor is a
# real thing and a patcher that writes LF into it corrupts every line it owns.
home4, root4 = fresh_pov()
mod4 = load(home4)
for rel in (SRC_REL, DBR_REL):
    write(root4, rel, STOCK_TEXT[rel].replace('\n', '\r\n'))
st = mod4.ensure_patched()
check('a CRLF tree patches', st == 'sources=patched, debrid=patched', st)
for rel in (SRC_REL, DBR_REL):
    body = _read(root4, rel)
    check('%s keeps CRLF throughout' % rel.split('/')[-1],
          '\n' not in body.replace('\r\n', ''))
    try:
        compile(body.lstrip('﻿'), rel, 'exec')
    except SyntaxError as e:
        check('%s still compiles as CRLF' % rel.split('/')[-1], False, str(e))
    else:
        check('%s still compiles as CRLF' % rel.split('/')[-1], True)
check('and it is idempotent on CRLF too',
      mod4.ensure_patched() == 'sources=unchanged, debrid=unchanged')

# An older version's block must be replaced, not stacked on.
home5, root5 = fresh_pov()
mod5 = load(home5)
mod5.ensure_patched()
for rel in (SRC_REL, DBR_REL):
    write(root5, rel, _read(root5, rel).replace(mod5.MARKER,
                                                mod5._MARKER_ANY + '0'))
st = mod5.ensure_patched()
check('an older marker is reverted and replaced, not doubled',
      st == 'sources=repatched, debrid=repatched', st)
for rel in (SRC_REL, DBR_REL):
    body = _read(root5, rel)
    check('%s has no stale marker left' % rel.split('/')[-1],
          mod5._MARKER_ANY + '0' not in body)
check('and the result is what a clean patch produces',
      (_read(root5, SRC_REL), _read(root5, DBR_REL))
      == (_read(root, SRC_REL), _read(root, DBR_REL)))

# A tree without the files at all.
home6 = tempfile.mkdtemp(prefix='povdbgto-')
_SCRATCH.append(home6)
mod6 = load(home6)
check('no POV installed is not an error, and not a skip',
      mod6.ensure_patched() == 'sources=no_file, debrid=no_file',
      mod6.ensure_patched())

# A shape that appears twice is not patched at whichever copy comes first.
home7, root7 = fresh_pov()
mod7 = load(home7)
write(root7, SRC_REL, STOCK_TEXT[SRC_REL] + '\n' + SOURCES_PHASE)
st = mod7.ensure_patched()
check('a duplicated shape is refused, and the other half still applies',
      st == 'sources=unmatched, debrid=patched', st)

# A BOM-prefixed file. Kodi ships none, but a file that has been through a
# Windows editor has one, and stripping it on the way in would change bytes
# this module does not own. The compile CHECK strips it; the write must not.
home9, root9 = fresh_pov()
mod9 = load(home9)
for rel in (SRC_REL, DBR_REL):
    write(root9, rel, '\ufeff' + STOCK_TEXT[rel])
st = mod9.ensure_patched()
check('a BOM tree patches', st == 'sources=patched, debrid=patched', st)
for rel in (SRC_REL, DBR_REL):
    body = _read(root9, rel)
    check('%s keeps its BOM' % rel.split('/')[-1], body.startswith('\ufeff'))
    check('%s has exactly one BOM' % rel.split('/')[-1],
          body.count('\ufeff') == 1)
check('and it is idempotent with a BOM too',
      mod9.ensure_patched() == 'sources=unchanged, debrid=unchanged')

# A file carrying our current block AND a stray marker is left alone rather
# than guessed at.
home8, root8 = fresh_pov()
mod8 = load(home8)
mod8.ensure_patched()
write(root8, DBR_REL, _read(root8, DBR_REL) + '\n' + mod8.MARKER + '\n')
st = mod8.ensure_patched()
check('a stray marker beside a good block is reported, not repaired',
      st == 'sources=unchanged, debrid=revert_failed', st)

# --- 6. the service actually runs it --------------------------------------
print()
print('=== the service runs it, in the right place ===')
_svc = io.open(os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                            'service.py'), encoding='utf-8').read()
import ast as _ast
_tree = _ast.parse(_svc)
_fns = [f for f in _ast.walk(_tree) if isinstance(f, _ast.FunctionDef)
        and f.name == '_maybe_keep_sources_when_debrid_is_late']
check('the startup step exists', len(_fns) == 1)
if _fns:
    _names = {n.attr for n in _ast.walk(_fns[0])
              if isinstance(n, _ast.Attribute)}
    check('it calls the patcher', 'ensure_patched' in _names)
    check('...and arms the POV reload, or the fix waits a boot',
          'note_patched' in _names)
    check('...and is skipped where the other POV patchers are',
          any(isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
              and n.func.id == '_skip_pov_patchers'
              for n in _ast.walk(_fns[0])))
# the step list is a tuple of bare names, so find it by its neighbours
_steps = [n for n in _ast.walk(_tree) if isinstance(n, _ast.Tuple)
          and any(isinstance(e, _ast.Name)
                  and e.id == '_maybe_keep_sources_when_debrid_is_late'
                  for e in n.elts)]
check('it is registered as a startup step', len(_steps) == 1)

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
