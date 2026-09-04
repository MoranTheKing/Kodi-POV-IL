"""POV scans ONE folder for internal scrapers, and 6.08.14 renamed it.

Field symptom: "it does not show the internal sources any more, only the
external ones." A third-party add-on installs a scraper by writing a module
into POV's internal-scraper folder. 6.08.14 renamed that folder --
resources/lib/scrapers/ -> resources/lib/debrids/ -- and moved its own pointer
(scrapers_path -> internal_path) with it. The installer still writes to the old
name, so its write fails with ENOENT and POV would not have looked there anyway.

The shim creates the old folder so the write succeeds, and edits the one line in
modules/sources.py so POV scans BOTH. The checks below run POV's own patched
line through pkgutil, against both real POV trees, because "would POV find it"
is the only question that matters and text cannot answer it.

Run: python3 tools/test_pov_internal_scraper_shim.py
"""
import importlib.util
import io
import os
import pkgutil
import re
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
LIB = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
MODULE = os.path.join(LIB, 'pov_internal_scraper_shim.py')
SC = ('/tmp/claude-0/-home-user-Kodi-POV-IL/'
      '70968383-5f01-52a3-afe7-ced1aba28071/scratchpad')

FAIL = []
_SCRATCH = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def load(home):
    for n in list(sys.modules):
        if n.startswith(('xbmcvfs', 'resources')):
            sys.modules.pop(n, None)
    xv = types.ModuleType('xbmcvfs')
    xv.translatePath = lambda p: p.replace('special://home/', home + os.sep)
    sys.modules['xbmcvfs'] = xv
    pkg = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    pkg.lib = lib
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = lib
    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.logged = []
    ku.log = lambda m, level='INFO': ku.logged.append((level, m))
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku
    spec = importlib.util.spec_from_file_location('shim_t', MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.kodi_utils = ku
    return m


def real_pov(ver):
    """A throwaway copy of a real POV tree, or None if it is not on disk."""
    src = os.path.join(SC, 'pov%s' % ver, 'plugin.video.pov')
    if not os.path.isdir(src):
        return None, None
    home = tempfile.mkdtemp(prefix='shim-')
    _SCRATCH.append(home)
    pov = os.path.join(home, 'addons', 'plugin.video.pov')
    shutil.copytree(src, pov)
    return home, pov


def enumerate_like_pov(pov, home, internal_dir):
    """Run POV's OWN patched line and return what it would load."""
    src = io.open(os.path.join(pov, 'resources', 'lib', 'modules',
                               'sources.py'), encoding='utf-8').read()
    i = src.index('_ai_dirs = [source_path]')
    j = src.index('iter_modules(_ai_dirs)', i)
    start = src.rfind('\n', 0, i) + 1
    block = '\n'.join(l[2:] for l in src[start:src.index('\n', j)].split('\n'))
    ns = {'source_path': os.path.join(pov, 'resources', 'lib', internal_dir),
          'kodi_utils': types.SimpleNamespace(
              translate_path=lambda p: p.replace('special://home/',
                                                 home + os.sep)),
          'pkgutil': pkgutil}
    exec(block.replace('for loader, module_name, is_pkg in', '_found=[m.name for m in')
              .replace('):', ')]'), ns)
    return ns['_found']


def ai_dirs_from_patched(pov, home, internal_dir):
    """The directory list the SHIM injected, obtained by running it.

    Not rebuilt here. The point of this helper is that the order under test is
    the order the patch wrote, so a patch that reverses it fails.
    """
    src = io.open(os.path.join(pov, 'resources', 'lib', 'modules',
                               'sources.py'), encoding='utf-8').read()
    i = src.index('_ai_dirs = [source_path]')
    j = src.index('iter_modules(_ai_dirs)', i)
    start = src.rfind('\n', 0, i) + 1
    block = '\n'.join(l[2:] for l in src[start:src.rindex('\n', 0, j)].split('\n'))
    ns = {'source_path': os.path.join(pov, 'resources', 'lib', internal_dir),
          'kodi_utils': types.SimpleNamespace(
              translate_path=lambda p: p.replace('special://home/',
                                                 home + os.sep))}
    exec(block, ns)
    return ns['_ai_dirs']


def rank_of(pov, account_type, ranks):
    """Run POV's OWN get_provider_rank and return its answer -- or, when it
    blows up, the exception itself, because that is the whole finding.

    Extracted from the file rather than reimplemented, so it reads whatever is
    on disk at the moment it is called: the stock bare subscript before the
    shim runs, the guarded lookup after.
    """
    src = io.open(os.path.join(pov, 'resources', 'lib', 'modules',
                               'sources.py'), encoding='utf-8').read()
    i = src.index('\tdef get_provider_rank(self, account_type):')
    j = src.index('\n', src.index('provider_sort_ranks', i))
    body = '\n'.join(l[1:] for l in src[i:j].split('\n'))
    ns = {}
    exec(body, ns)
    me = types.SimpleNamespace(
        source=types.SimpleNamespace(provider_sort_ranks=ranks))
    try:
        return ns['get_provider_rank'](me, account_type)
    except Exception as exc:
        return exc


def put_legacy(pov, name, body='source = 1\n'):
    d = os.path.join(pov, 'resources', 'lib', 'scrapers')
    os.makedirs(d, exist_ok=True)
    with io.open(os.path.join(d, name), 'w', encoding='utf-8') as f:
        f.write(body)


# --- 0. the rename is real, and both shapes are handled ------------------
print('=== against both real POV trees ===')
seen_any = False
for ver, label, internal in (('6813', '6.08.13', 'scrapers'),
                             ('6814', '6.08.14', 'debrids')):
    home, pov = real_pov(ver)
    if not pov:
        print('   (POV %s not on disk -- skipped)' % label)
        continue
    seen_any = True
    # Plant a stale .pyc BEFORE patching, or the check below is vacuous: a
    # freshly extracted POV has no __pycache__ and a mutant that deleted
    # _drop_pyc passed. On a real device the .pyc is always there -- Kodi
    # writes one the first time it imports the module.
    _cache = os.path.join(pov, 'resources', 'lib', 'modules', '__pycache__')
    os.makedirs(_cache, exist_ok=True)
    with io.open(os.path.join(_cache, 'sources.cpython-311.pyc'), 'wb') as f:
        f.write(b'stale')

    # THE STOCK TREE REALLY HAS THE BUG. Asserted before patching, or the
    # checks after it would pass against a POV that never had the problem.
    _RANKS = {'rd_cloud': 2, 'external': 4}
    _stock = rank_of(pov, 'thirdparty', _RANKS)
    check('POV %s: an unknown provider raises out of STOCK POV' % label,
          isinstance(_stock, KeyError), repr(_stock))

    mod = load(home)
    st = mod.ensure_patched()
    print('   POV %s -> %s' % (label, st))
    check('POV %s: sources.py is patched' % label, 'scan=patched' in st, st)
    check('POV %s: the legacy folder exists afterwards' % label,
          os.path.isdir(os.path.join(pov, 'resources', 'lib', 'scrapers')))
    check('POV %s: patched sources.py still compiles' % label,
          compile(io.open(os.path.join(pov, 'resources', 'lib', 'modules',
                                       'sources.py'),
                          encoding='utf-8').read(), 'x', 'exec') is not None)

    # THE RANK GUARD -- the edit that makes scanning a second folder safe
    # instead of dangerous. One provider name POV does not know took the whole
    # result list down with it, POV's own sources included.
    check('POV %s: the provider-rank lookup is guarded' % label,
          'rank=patched' in st, st)
    _miss = rank_of(pov, 'thirdparty', _RANKS)
    check('POV %s: ...so an unknown provider no longer raises' % label,
          _miss == 11, repr(_miss))
    check('POV %s: a registered provider still gets its own rank' % label,
          rank_of(pov, 'rd_cloud', _RANKS) == 2,
          repr(rank_of(pov, 'rd_cloud', _RANKS)))
    # POV's `or 11` treats a rank of 0 as unset and the guard must not change
    # that -- a patcher shipped elsewhere in this repo depends on it.
    check('POV %s: a rank of 0 still falls through to 11' % label,
          rank_of(pov, 'zero', {'zero': 0}) == 11,
          repr(rank_of(pov, 'zero', {'zero': 0})))

    before = enumerate_like_pov(pov, home, internal)
    check('POV %s: its own scrapers are still all found' % label,
          {'rd_cloud', 'tb_cloud', 'aiostreams', 'easynews'} <= set(before),
          str(sorted(before)))

    # A third-party module appears in the legacy folder AFTER we patched.
    put_legacy(pov, 'thirdparty.py')
    after = enumerate_like_pov(pov, home, internal)
    check('POV %s: a third-party scraper in the legacy folder IS found'
          % label, 'thirdparty' in after, str(sorted(after)))
    check('POV %s: ...and POV\'s own modules are not duplicated' % label,
          all(after.count(n) == 1 for n in after), str(sorted(after)))

    # A stale copy of POV's OWN module in the legacy folder must not shadow
    # it. ONLY MEANINGFUL WHEN THE TWO FOLDERS DIFFER: on 6.08.13 the legacy
    # folder IS POV's folder, so planting there overwrites the real module and
    # the question does not arise. Writing this check without that guard made
    # it fail on 6.08.13 for a reason that was purely the fixture's.
    if internal == 'scrapers':
        print('   (6.08.13 keeps both in one folder -- no shadowing to test)')
        _again = mod.ensure_patched()
        check('POV %s: running again is a no-op' % label,
              'scan=unchanged' in _again and 'rank=unchanged' in _again, _again)
        continue
    put_legacy(pov, 'rd_cloud.py', 'source = "SABOTAGE"\n')
    shadow = enumerate_like_pov(pov, home, internal)
    check('POV %s: a stale copy of its own module cannot shadow it' % label,
          shadow.count('rd_cloud') == 1, str(sorted(shadow)))
    # THE ORDER GUARANTEE, READ OUT OF THE PATCHED FILE. The first version of
    # this check built its own directory list, in the correct order, and asked
    # pkgutil about that -- so it could not fail no matter what the shim wrote.
    # A review proved it: flipping `append` to `insert(0, ...)` in the shim
    # left this file printing ALL PASS while POV loaded the sabotaged copy.
    # It now executes the block the shim actually injected and asks which
    # finder answers.
    dirs = ai_dirs_from_patched(pov, home, internal)
    check('POV %s: POV\'s own folder is FIRST in the list it wrote' % label,
          dirs and os.path.basename(dirs[0].rstrip(os.sep)) == internal,
          str(dirs))
    found = [m for m in pkgutil.iter_modules(dirs) if m.name == 'rd_cloud']
    check('POV %s: ...so the module it loads is POV\'s, not the stale one'
          % label,
          found and os.path.basename(
              found[0].module_finder.path.rstrip(os.sep)) == internal,
          found[0].module_finder.path if found else 'none')
    # Deliberately NOT exec'ing the module to read its .source: POV's own
    # rd_cloud imports caches.main_cache and needs POV's package context, so
    # loading it here proves nothing about the patch and only breaks the test.
    # Which finder answers is the question, and it is answered above.

    # A STALE .pyc WOULD KEEP THE ONE-FOLDER SCAN ALIVE after the rewrite --
    # exactly what _drop_pyc's docstring says it prevents, and a mutant that
    # deleted the call passed everything else here.
    _cache = os.path.join(pov, 'resources', 'lib', 'modules', '__pycache__')
    _left = [n for n in (os.listdir(_cache) if os.path.isdir(_cache) else [])
             if n.startswith('sources.') and n.endswith('.pyc')]
    check('POV %s: no stale sources .pyc survives the rewrite' % label,
          not _left, str(_left))

    _again = mod.ensure_patched()
    check('POV %s: running again is a no-op' % label,
          'scan=unchanged' in _again and 'rank=unchanged' in _again, _again)

check('at least one real POV tree was available to test against', seen_any,
      'this file proves nothing without one')


# --- 1. what it refuses ---------------------------------------------------
print()
print('=== files it does not recognise are left alone ===')
home2 = tempfile.mkdtemp(prefix='shim-x-')
_SCRATCH.append(home2)
pov2 = os.path.join(home2, 'addons', 'plugin.video.pov')
os.makedirs(os.path.join(pov2, 'resources', 'lib', 'modules'))
p2 = os.path.join(pov2, 'resources', 'lib', 'modules', 'sources.py')
with io.open(p2, 'w', encoding='utf-8') as f:
    f.write('x = 1\n')
st2 = load(home2).ensure_patched()
check('an unrecognised sources.py is reported, not forced',
      'scan=unmatched' in st2, st2)
check('...and untouched', io.open(p2, encoding='utf-8').read() == 'x = 1\n')
check('...but the legacy folder is still created, which is the half that '
      'unblocks the installer', 'legacy=created' in st2, st2)
check('a sources.py with no rank lookup is reported, not forced',
      'rank=unmatched' in st2, st2)

# TWO matches must be refused, not half-patched. A POV somebody has edited, or
# a future POV with the scan in two places, is one we must not guess at -- and
# loosening the count from `!= 1` to `< 1` passed every other check here.
home2b, pov2b = real_pov('6814')
if pov2b:
    _p = os.path.join(pov2b, 'resources', 'lib', 'modules', 'sources.py')
    _t = io.open(_p, encoding='utf-8', newline='').read()
    _blk = ("\t\tsource_path = kodi_utils.translate_path("
            "kodi_utils.internal_path)\n\t\tfor loader, module_name, is_pkg "
            "in __import__('pkgutil').iter_modules([source_path]):")
    check('the fixture really has the block once', _t.count(_blk) == 1)
    with io.open(_p, 'w', encoding='utf-8', newline='') as f:
        f.write(_t.replace(_blk, _blk + '\n\t\tpass\n' + _blk, 1))
    st2b = load(home2b).ensure_patched()
    check('two copies of the scan line are refused, not half-patched',
          'scan=unmatched' in st2b, st2b)
    check('...and the file still has both, untouched',
          io.open(_p, encoding='utf-8', newline='').read().count(_blk) == 2)

# The same refusal for the rank lookup, on its own fixture. Two of them means a
# POV somebody has edited or a shape we do not understand, and guessing which
# one to rewrite is how a patcher silently half-applies.
home2c, pov2c = real_pov('6814')
if pov2c:
    _pc = os.path.join(pov2c, 'resources', 'lib', 'modules', 'sources.py')
    _tc = io.open(_pc, encoding='utf-8', newline='').read()
    _rank = "\t\treturn self.source.provider_sort_ranks[account_type] or 11"
    check('the fixture really has the rank lookup once', _tc.count(_rank) == 1)
    with io.open(_pc, 'w', encoding='utf-8', newline='') as f:
        f.write(_tc.replace(
            _rank, _rank + '\n\tdef _x(self, account_type):\n' + _rank, 1))
    st2c = load(home2c).ensure_patched()
    check('two copies of the rank lookup are refused, not half-guarded',
          'rank=unmatched' in st2c, st2c)
    check('...and the file still has both, untouched',
          io.open(_pc, encoding='utf-8', newline='').read().count(_rank) == 2)

# A LATER VERSION OF EITHER EDIT finds its own older marker in place and the
# anchor already consumed. Both must report 'unchanged' -- the quiet, correct
# answer for a module pinned NEVER-UPGRADES -- and not 'unmatched', which reads
# as "POV refactored" and sends the next maintainer hunting a change POV never
# made. The rank guard reported exactly that before it grew the same check the
# scan edit already had.
home2d, pov2d = real_pov('6814')
if pov2d:
    mod2d = load(home2d)
    st_first = mod2d.ensure_patched()
    check('the fixture is patched before the bump is simulated',
          'scan=patched' in st_first and 'rank=patched' in st_first, st_first)
    mod2d = load(home2d)
    mod2d.MARKER = mod2d.MARKER[:-1] + '2'
    mod2d._RANK_MARKER = mod2d._RANK_MARKER[:-1] + '2'
    st2d = mod2d.ensure_patched()
    check('a bumped scan marker leaves the old one alone, quietly',
          'scan=unchanged' in st2d, st2d)
    check('a bumped rank marker leaves the old one alone, quietly',
          'rank=unchanged' in st2d, st2d)

home3 = tempfile.mkdtemp(prefix='shim-none-')
_SCRATCH.append(home3)
check('no POV installed is reported, not crashed',
      load(home3).ensure_patched() == 'no_pov')

home4, pov4 = real_pov('6814')
if pov4:
    os.remove(os.path.join(pov4, 'resources', 'lib', 'modules', 'sources.py'))
    st4 = load(home4).ensure_patched()
    check('a missing sources.py is reported, not crashed',
          'scan=no_file' in st4, st4)

# A legacy path that is a FILE.
home5, pov5 = real_pov('6814')
if pov5:
    with io.open(os.path.join(pov5, 'resources', 'lib', 'scrapers'), 'w',
                 encoding='utf-8') as f:
        f.write('not a directory\n')
    st5 = load(home5).ensure_patched()
    check('a legacy path that is a FILE is reported, not crashed',
          'legacy=failed' in st5, st5)
    check('...and the scan edit still applies', 'scan=patched' in st5, st5)

# An existing legacy folder without __init__.py gets one.
home6, pov6 = real_pov('6814')
if pov6:
    os.makedirs(os.path.join(pov6, 'resources', 'lib', 'scrapers'),
                exist_ok=True)
    init6 = os.path.join(pov6, 'resources', 'lib', 'scrapers', '__init__.py')
    check('the fixture really has no __init__.py yet',
          not os.path.isfile(init6))
    st6 = load(home6).ensure_patched()
    check('an existing legacy folder without __init__.py gets one',
          os.path.isfile(init6), st6)

# CRLF, because a device's copy has been through whatever wrote it.
home7, pov7 = real_pov('6814')
if pov7:
    p7 = os.path.join(pov7, 'resources', 'lib', 'modules', 'sources.py')
    t7 = io.open(p7, encoding='utf-8', newline='').read().replace('\n', '\r\n')
    with io.open(p7, 'w', encoding='utf-8', newline='') as f:
        f.write(t7)
    st7 = load(home7).ensure_patched()
    check('a CRLF sources.py patches too', 'scan=patched' in st7, st7)
    a7 = io.open(p7, encoding='utf-8', newline='').read()
    check('...and stays CRLF', '\n' not in a7.replace('\r\n', ''))

# The compile guards, exercised directly -- they cannot be seen through a
# correct replacement, which is how a mutant that deleted one survived
# elsewhere. BOTH edits are sabotaged in the same run, because they write to
# the same file: sabotaging only one leaves the other free to rewrite it, and
# the byte-for-byte assertion below would then be measuring the wrong edit.
home8, pov8 = real_pov('6814')
if pov8:
    mod8 = load(home8)
    p8 = os.path.join(pov8, 'resources', 'lib', 'modules', 'sources.py')
    before8 = io.open(p8, encoding='utf-8', newline='').read()
    # Sabotage the SHAPE TABLE, not a name that no longer exists. When this
    # read `mod8._REPLACEMENT_TMPL = ...` it was setting an attribute the
    # module had stopped having, so the real replacement still applied, the
    # scan reported `patched`, and the check "a replacement that would not
    # compile is refused" was passing against an edit that compiled fine.
    # A sabotage that misses its target is worse than no sabotage: it reports
    # a guard as proven while proving nothing.
    assert mod8._SHAPES, 'the shape table is what carries the replacements'
    mod8._SHAPES = tuple((anchor, '\t\tsource_path = ((( %s')
                         for anchor, _repl in mod8._SHAPES)
    mod8._RANK_REPLACEMENT = '\t\treturn ((('
    st8 = mod8.ensure_patched()
    check('a scan replacement that would not compile is refused',
          'scan=compile_failed' in st8, st8)
    check('a rank replacement that would not compile is refused',
          'rank=compile_failed' in st8, st8)
    check('...and POV is left byte-for-byte as it was',
          io.open(p8, encoding='utf-8', newline='').read() == before8)


# --- 2. it is wired in, and actually runs --------------------------------
print()
print('=== the service actually runs it ===')
svc = io.open(os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                           'service.py'), encoding='utf-8').read()
check('service.py defines the step',
      'def _maybe_shim_pov_internal_scrapers(' in svc)
tup = re.search(r'steps = \((.*?)\n    \)', svc, re.S)
check('...and the repair pass actually lists it',
      tup is not None and '_maybe_shim_pov_internal_scrapers,' in tup.group(1),
      'defined but never called is the failure this check exists for')


print()
if FAIL:
    print('FAILED: %d -> %s' % (len(FAIL), FAIL))
    raise SystemExit(1)
print('ALL PASS')
