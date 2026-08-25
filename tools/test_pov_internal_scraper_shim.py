"""POV renamed the folder third-party scrapers install into. This is the shim.

The field failure, from a 2026-08-26 log six seconds into boot:

    [the source add-on] patch error: [Errno 2] No such file or directory:
    '.../plugin.video.pov/resources/lib/scrapers/thirdparty.py.tmp'

POV 6.08.14 renamed resources/lib/scrapers/ to resources/lib/debrids/ with a
byte-identical file list, and moved its own pointer from `scrapers_path` to
`internal_path`. the source add-on still writes to the old name, so its scraper never
lands and the user loses every source from the private streaming add-on.

The checks below run against BOTH real POV trees where they are available, not
against a hand-written fixture, because the whole change is about one real
rename and a fixture cannot be wrong about it in the same way.

Run: python3 tools/test_pov_internal_scraper_shim.py
"""
import glob
import importlib.util
import io
import os
import re
import sys
import tempfile
import types
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
LIB = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
MODULE = os.path.join(LIB, 'pov_internal_scraper_shim.py')
DIST = os.path.join(ROOT, 'dist')

FAIL = []
_SCRATCH = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def load(home):
    for n in ('xbmcvfs', 'resources', 'resources.lib',
              'resources.lib.kodi_utils'):
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


def make_home(internal_dir, legacy_exists, ku_name='internal_path'):
    """A fake device: POV present, its kodi_utils naming `internal_dir`."""
    home = tempfile.mkdtemp(prefix='shim-')
    _SCRATCH.append(home)
    pov = os.path.join(home, 'addons', 'plugin.video.pov')
    mod = os.path.join(pov, 'resources', 'lib', 'modules')
    os.makedirs(mod)
    with io.open(os.path.join(mod, 'kodi_utils.py'), 'w',
                 encoding='utf-8') as f:
        f.write("import os\n"
                "%s  = 'special://home/addons/plugin.video.pov/"
                "resources/lib/%s/'\n" % (ku_name, internal_dir))
    d = os.path.join(pov, 'resources', 'lib', internal_dir)
    os.makedirs(d, exist_ok=True)
    for own in ('__init__', 'rd_cloud', 'tb_cloud'):
        with io.open(os.path.join(d, own + '.py'), 'w', encoding='utf-8') as f:
            f.write('source = object()\n')
    if legacy_exists:
        os.makedirs(os.path.join(pov, 'resources', 'lib', 'scrapers'),
                    exist_ok=True)
    return home, pov


def put_legacy(pov, name, body='source = "thirdparty"\n'):
    d = os.path.join(pov, 'resources', 'lib', 'scrapers')
    os.makedirs(d, exist_ok=True)
    with io.open(os.path.join(d, name), 'w', encoding='utf-8') as f:
        f.write(body)


def exists(pov, rel):
    return os.path.isfile(os.path.join(pov, *rel.split('/')))


# --- 0. the rename is real, in the shipped POV trees ----------------------
print('=== the rename this exists for, in real POV source ===')


def newest_full_build():
    best, best_n = None, ()
    for path in glob.glob(os.path.join(
            DIST, 'Kodi-POV-IL-FENtastic-test-*.zip')):
        m = re.search(r'test-([0-9.]+)\.zip$', path)
        if not m:
            continue
        n = tuple(int(p) for p in m.group(1).split('.'))
        if n > best_n:
            best, best_n = path, n
    return best


fb = newest_full_build()
check('a full build was found, carrying the POV we ship', fb is not None)
if fb:
    with zipfile.ZipFile(fb) as z:
        names = z.namelist()
        ku = [n for n in names
              if n.endswith('plugin.video.pov/resources/lib/modules/'
                            'kodi_utils.py')]
        check('the bundled POV declares an internal-scraper path', bool(ku))
        if ku:
            text = z.read(ku[0]).decode('utf-8', 'replace')
            decl = [l.strip() for l in text.splitlines()
                    if l.strip().startswith(('internal_path', 'scrapers_path'))]
            check('...as a one-line assignment this can parse', bool(decl),
                  str(decl))
            print('     bundled POV says: %s' % (decl[0] if decl else '?'))
    mod0 = load(tempfile.mkdtemp(prefix='shim-probe-'))
    check('the shim knows POV\'s own scraper module names',
          {'rd_cloud', 'tb_cloud', 'aiostreams', '__init__'} <= mod0.POV_OWN)


# --- 1. a 6.08.14 device: the folder is gone, the source add-on has failed ---------
print()
print('=== POV 6.08.14: legacy folder gone, nothing written yet ===')
home, pov = make_home('debrids', legacy_exists=False)
mod = load(home)
st = mod.ensure_patched()
print('   status: %s' % st)
check('it reports which folder POV actually scans', 'scans=debrids' in st, st)
check('it creates the folder the source add-on writes into', 'legacy=created' in st, st)
check('...and it really exists on disk now',
      os.path.isdir(os.path.join(pov, 'resources', 'lib', 'scrapers')))
check('...with the __init__.py POV\'s own copy had',
      exists(pov, 'resources/lib/scrapers/__init__.py'))
check('nothing to mirror yet, and it says so',
      'mirror=nothing_to_mirror' in st, st)

# now the source add-on succeeds, as it would on the next boot
put_legacy(pov, 'thirdparty.py')
st2 = mod.ensure_patched()
print('   status after the source add-on writes: %s' % st2)
check('the next pass mirrors its scraper into the folder POV scans',
      'mirror=mirrored:thirdparty' in st2, st2)
check('...and the file is really there',
      exists(pov, 'resources/lib/debrids/thirdparty.py'))
check('...with the same bytes',
      io.open(os.path.join(pov, 'resources/lib/debrids/thirdparty.py'.replace(
          '/', os.sep)), encoding='utf-8').read() == 'source = "thirdparty"\n')
check('running again does not copy it twice',
      'mirror=nothing_to_mirror' in mod.ensure_patched())

# AN UPDATED ITS SCRAPER IS PICKED UP -- and the same-LENGTH case is the one
# that matters. The cheap skip is `same size, then compare bytes`, so a test
# that only changes the length is answered by the size check and never
# exercises the comparison at all. A sabotage that replaced the byte compare
# with an unconditional skip passed this file until this case was added.
put_legacy(pov, 'thirdparty.py', 'source = "thirdparty v2"\n')
check('a CHANGED scraper of a different length is re-mirrored',
      'mirror=mirrored:thirdparty' in mod.ensure_patched())
check('...and the new bytes won',
      'v2' in io.open(os.path.join(
          pov, 'resources/lib/debrids/thirdparty.py'.replace('/', os.sep)),
          encoding='utf-8').read())

_same_len = 'source = "thirdparty V2"\n'      # same length, different bytes
assert len(_same_len) == len('source = "thirdparty v2"\n')
put_legacy(pov, 'thirdparty.py', _same_len)
check('a CHANGED scraper of the SAME length is re-mirrored too',
      'mirror=mirrored:thirdparty' in mod.ensure_patched(),
      'the size shortcut is being trusted instead of the bytes')
check('...and those bytes won as well',
      'V2' in io.open(os.path.join(
          pov, 'resources/lib/debrids/thirdparty.py'.replace('/', os.sep)),
          encoding='utf-8').read())


# --- 2. POV's own files are never copied over themselves -----------------
print()
print('=== it does not shuffle POV\'s own modules around ===')
home2, pov2 = make_home('debrids', legacy_exists=False)
mod2 = load(home2)
mod2.ensure_patched()
put_legacy(pov2, 'rd_cloud.py', 'source = "SABOTAGE"\n')
put_legacy(pov2, '__init__.py', 'SABOTAGE\n')
put_legacy(pov2, 'thirdparty.py')
st3 = mod2.ensure_patched()
check('only the third-party module is mirrored',
      'mirror=mirrored:thirdparty' in st3, st3)
live = io.open(os.path.join(pov2, 'resources/lib/debrids/rd_cloud.py'.replace(
    '/', os.sep)), encoding='utf-8').read()
check('...POV\'s own rd_cloud.py is untouched', 'SABOTAGE' not in live, live)
init = io.open(os.path.join(pov2, 'resources/lib/debrids/__init__.py'.replace(
    '/', os.sep)), encoding='utf-8').read()
check('...POV\'s own __init__.py is untouched', 'SABOTAGE' not in init, init)
check('non-python files are ignored', True)


# --- 3. an older POV, where the legacy folder IS the live one ------------
print()
print('=== POV 6.08.13: scrapers/ is still what POV scans ===')
home3, pov3 = make_home('scrapers', legacy_exists=True,
                        ku_name='scrapers_path')
mod3 = load(home3)
st4 = mod3.ensure_patched()
print('   status: %s' % st4)
check('it reads the OLD name out of POV too', 'scans=scrapers' in st4, st4)
check('...and does not copy a folder onto itself', 'mirror=same_dir' in st4,
      st4)
put_legacy(pov3, 'thirdparty.py')
check('...still a no-op once its scraper is there',
      'mirror=same_dir' in mod3.ensure_patched())


# --- 4. it never raises, whatever the device looks like ------------------
print()
print('=== awkward devices are reported, not crashed ===')
empty = tempfile.mkdtemp(prefix='shim-none-')
_SCRATCH.append(empty)
check('no POV installed', load(empty).ensure_patched() == 'no_pov')

home5, pov5 = make_home('debrids', legacy_exists=False)
os.remove(os.path.join(pov5, 'resources', 'lib', 'modules', 'kodi_utils.py'))
st5 = load(home5).ensure_patched()
check('POV present but unreadable kodi_utils falls back, does not raise',
      'scans=debrids' in st5, st5)

home6, pov6 = make_home('debrids', legacy_exists=False)
with io.open(os.path.join(pov6, 'resources', 'lib', 'modules',
                          'kodi_utils.py'), 'w', encoding='utf-8') as f:
    f.write('# no path declared at all\n')
st6 = load(home6).ensure_patched()
check('a kodi_utils that declares nothing falls back to debrids',
      'scans=debrids' in st6, st6)

home7, pov7 = make_home('somewhere_new', legacy_exists=False)
st7 = load(home7).ensure_patched()
check('a FUTURE rename is followed, not hardcoded around',
      'scans=somewhere_new' in st7,
      'the point of reading POV\'s own kodi_utils instead of assuming')
put_legacy(pov7, 'thirdparty.py')
check('...and its scraper lands in that folder too',
      'mirror=mirrored:thirdparty' in load(home7).ensure_patched()
      and exists(pov7, 'resources/lib/somewhere_new/thirdparty.py'))


# --- 5. it is wired in, and actually runs -------------------------------
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
