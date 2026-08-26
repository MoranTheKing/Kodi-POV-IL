"""POV 6.08.14 subscripts a dict with [0] and every AllDebrid play fails.

Two field logs, 2026-08-26, dozens of lines each:

    >> resolve_external_sources exception <<: 0
       {'debrid': 'alldebrid', 'cache_provider': 'Unchecked alldebrid', ...}

An exception whose whole message is `0` is KeyError(0). The line:

    indexers/alldebrid_api.py  torrent_info()
      6.08.13   result = result['magnets']
      6.08.14   result = result['magnets'][0]

Same endpoint, same params. With an id AllDebrid returns one object; the
listing call returns a list. The `[0]` landed on the wrong one.

The checks below EXECUTE the method -- POV's own, before and after the patch --
against both response shapes, because the entire bug is a shape assumption and
a text comparison cannot see one.

Run: python3 tools/test_pov_alldebrid_status.py
"""
import glob
import importlib.util
import io
import os
import re
import shutil
import sys
import tempfile
import types
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
LIB = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
MODULE = os.path.join(LIB, 'pov_alldebrid_status_fix.py')
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
    spec = importlib.util.spec_from_file_location('ad_t', MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.kodi_utils = ku
    return m


def pov_home(rel, body):
    """A fake device carrying alldebrid_api.py at `rel` with `body`."""
    home = tempfile.mkdtemp(prefix='adfix-')
    _SCRATCH.append(home)
    p = os.path.join(home, 'addons', 'plugin.video.pov', *rel.split('/'))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(body)
    return home, p


def method_of(src, name='torrent_info'):
    i = src.index('\tdef %s(' % name)
    j = src.index('\n\n', i)
    return src[i:j]


def run_method(method_src, shape):
    """Execute POV's own torrent_info with a stubbed _get returning `shape`."""
    ns = {'SHAPE': shape}
    exec('class C:\n\tdef _get(self, u, p=None): return SHAPE\n' + method_src,
         ns)
    return ns['C']().torrent_info(1)


# --- 0. the bug is in the POV we ship, and it is where we say ------------
print('=== the defect, in real POV source ===')


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


mod0 = load(tempfile.mkdtemp(prefix='adfix-probe-'))
fb = newest_full_build()
check('a full build was found to inspect', fb is not None)
SHIPPED = None
if fb:
    with zipfile.ZipFile(fb) as z:
        for rel in mod0.CANDIDATE_RELS:
            n = 'addons/plugin.video.pov/' + rel
            if n in z.namelist():
                SHIPPED = z.read(n).decode('utf-8')
                print('     bundled POV keeps it at: %s' % rel)
                break
    check('the bundled POV has an alldebrid client', SHIPPED is not None)

# The anchor must be unique, and MUST NOT match create_transfer -- which has
# the identical `result['magnets'][0]` line and is CORRECT there, because
# v4/magnet/upload really does return a list.
POV14 = None
for cand in (os.path.join('/tmp/claude-0/-home-user-Kodi-POV-IL/'
                          '70968383-5f01-52a3-afe7-ced1aba28071/scratchpad',
                          'pov6814/plugin.video.pov/resources/lib/indexers/'
                          'alldebrid_api.py'),):
    if os.path.isfile(cand):
        POV14 = io.open(cand, encoding='utf-8', newline='').read()
if POV14:
    check('POV 6.08.14 really has the broken line',
          POV14.count("result = result['magnets'][0]") == 2,
          'expected it twice -- torrent_info (wrong) and create_transfer (right)')
    check('the anchor matches exactly once', POV14.count(mod0.ANCHOR) == 1,
          '%d matches' % POV14.count(mod0.ANCHOR))
    check('...and it is NOT inside create_transfer',
          'create_transfer' not in mod0.ANCHOR
          and "url = 'v4/magnet/upload'" not in mod0.ANCHOR)

def _raises_keyerror0(src):
    try:
        run_method(method_of(src), {'magnets': {'id': 7}})
        return False
    except KeyError as e:
        return str(e) == '0'
    except Exception:
        return False


if POV14:
    check('POV 6.08.14, unpatched, raises KeyError(0) -- the field message',
          _raises_keyerror0(POV14),
          'if this stops failing, POV fixed it and this patch should go')


# --- 1. the repair, executed ---------------------------------------------
print()
print('=== the repair, run against both API shapes ===')
if POV14:
    home, path = pov_home('resources/lib/indexers/alldebrid_api.py', POV14)
    mod = load(home)
    st = mod.ensure_patched()
    check('it patches a 6.08.14 client', st == 'patched', st)
    after = io.open(path, encoding='utf-8', newline='').read()
    check('the patched file still compiles',
          compile(after, path, 'exec') is not None)
    check('the marker is present', mod.MARKER in after)

    m = method_of(after)
    out_single = run_method(m, {'magnets': {'id': 7, 'completionDate': 1}})
    check('a SINGLE OBJECT response now returns that object',
          out_single == {'id': 7, 'completionDate': 1}, str(out_single))
    out_list = run_method(m, {'magnets': [{'id': 9}, {'id': 10}]})
    check('a LIST response still returns its first element',
          out_list == {'id': 9}, str(out_list))
    out_empty = run_method(m, {'magnets': []})
    check('an EMPTY list returns {} instead of raising IndexError',
          out_empty == {}, str(out_empty))

    # create_transfer must be untouched: its [0] is correct.
    ct_before = method_of(POV14, 'create_transfer')
    ct_after = method_of(after, 'create_transfer')
    check('create_transfer is byte-identical -- its [0] is right',
          ct_before == ct_after)
    check('...and the file still has exactly one [0] on magnets',
          after.count("result = result['magnets'][0]") == 1,
          'the one left must be create_transfer\'s')

    check('running again is a no-op', mod.ensure_patched() == 'unchanged')


    # THE COMPILE GUARD, exercised directly. It cannot be observed through a
    # correct replacement -- which is why a mutant that deleted it survived
    # every other check here -- so the replacement is deliberately broken for
    # one call. It exists so a future edit to REPLACEMENT can never leave POV
    # unable to import.
    home_c, path_c = pov_home('resources/lib/indexers/alldebrid_api.py', POV14)
    mod_c = load(home_c)
    before_c = io.open(path_c, encoding='utf-8', newline='').read()
    _good = mod_c.REPLACEMENT
    mod_c.REPLACEMENT = "\tdef torrent_info(self, transfer_id):\n\t\treturn ((("
    st_c = mod_c.ensure_patched()
    mod_c.REPLACEMENT = _good
    check('a replacement that would not compile is refused',
          st_c == 'compile_failed', st_c)
    check('...and POV is left byte-for-byte as it was',
          io.open(path_c, encoding='utf-8', newline='').read() == before_c)


# --- 2. it finds the client in either folder ----------------------------
print()
print('=== 6.08.13 kept the client somewhere else ===')
if POV14:
    home2, path2 = pov_home('resources/lib/debrids/alldebrid_api.py', POV14)
    check('the old debrids/ layout is found and patched',
          load(home2).ensure_patched() == 'patched')


# --- 3. POV's own fix, and files we must not touch ----------------------
print()
print('=== when POV repairs it, we stop ===')
POV13 = None
_p13 = ('/tmp/claude-0/-home-user-Kodi-POV-IL/'
        '70968383-5f01-52a3-afe7-ced1aba28071/scratchpad/'
        'pov6813/plugin.video.pov/resources/lib/debrids/alldebrid_api.py')
if os.path.isfile(_p13):
    POV13 = io.open(_p13, encoding='utf-8', newline='').read()
if POV13:
    home3, path3 = pov_home('resources/lib/debrids/alldebrid_api.py', POV13)
    before3 = io.open(path3, encoding='utf-8', newline='').read()
    st3 = load(home3).ensure_patched()
    check('a 6.08.13 client, which never had the bug, is left alone',
          st3 == 'unmatched', st3)
    check('...and untouched',
          io.open(path3, encoding='utf-8', newline='').read() == before3)
    check('...and it did not need us: it returns the object as-is',
          run_method(method_of(POV13), {'magnets': {'id': 3}}) == {'id': 3})

home4, path4 = pov_home('resources/lib/indexers/alldebrid_api.py',
                        'class C:\n\tpass\n')
before4 = io.open(path4, encoding='utf-8').read()
st4 = load(home4).ensure_patched()
check('a client we do not recognise is refused', st4 == 'unmatched', st4)
check('...and untouched', io.open(path4, encoding='utf-8').read() == before4)

empty = tempfile.mkdtemp(prefix='adfix-none-')
_SCRATCH.append(empty)
check('no POV installed is reported, not crashed',
      load(empty).ensure_patched() == 'no_pov')

# CRLF, because a device's copy has been through whatever wrote it.
if POV14:
    home5, path5 = pov_home('resources/lib/indexers/alldebrid_api.py',
                            POV14.replace('\n', '\r\n'))
    st5 = load(home5).ensure_patched()
    check('a CRLF copy patches too', st5 == 'patched', st5)
    after5 = io.open(path5, encoding='utf-8', newline='').read()
    check('...and stays CRLF', '\n' not in after5.replace('\r\n', ''))


# --- 4. it is wired in, and actually runs -------------------------------
print()
print('=== the service actually runs it ===')
svc = io.open(os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                           'service.py'), encoding='utf-8').read()
check('service.py defines the step',
      'def _maybe_fix_pov_alldebrid_status(' in svc)
tup = re.search(r'steps = \((.*?)\n    \)', svc, re.S)
check('...and the repair pass actually lists it',
      tup is not None and '_maybe_fix_pov_alldebrid_status,' in tup.group(1),
      'defined but never called is the failure this check exists for')


print()
if FAIL:
    print('FAILED: %d -> %s' % (len(FAIL), FAIL))
    raise SystemExit(1)
print('ALL PASS')
