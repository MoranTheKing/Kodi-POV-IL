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

    # A stale copy of POV's OWN module in the legacy folder must not shadow it.
    put_legacy(pov, 'rd_cloud.py', 'source = "SABOTAGE"\n')
    shadow = enumerate_like_pov(pov, home, internal)
    check('POV %s: a stale copy of its own module cannot shadow it' % label,
          shadow.count('rd_cloud') == 1, str(sorted(shadow)))
    if internal != 'scrapers':
        found = [m for m in pkgutil.iter_modules(
            [os.path.join(pov, 'resources', 'lib', internal),
             os.path.join(pov, 'resources', 'lib', 'scrapers')])
            if m.name == 'rd_cloud']
        check('POV %s: ...and the one it finds is POV\'s, not the stale one'
              % label,
              found and os.path.basename(
                  found[0].module_finder.path) == internal,
              found[0].module_finder.path if found else 'none')

    check('POV %s: running again is a no-op' % label,
          'scan=unchanged' in mod.ensure_patched())

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

# The compile guard, exercised directly -- it cannot be seen through a correct
# replacement, which is how a mutant that deleted it survived elsewhere.
home8, pov8 = real_pov('6814')
if pov8:
    mod8 = load(home8)
    p8 = os.path.join(pov8, 'resources', 'lib', 'modules', 'sources.py')
    before8 = io.open(p8, encoding='utf-8', newline='').read()
    mod8._REPLACEMENT_TMPL = '\t\tsource_path = ((( %s'
    st8 = mod8.ensure_patched()
    check('a replacement that would not compile is refused',
          'scan=compile_failed' in st8, st8)
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
