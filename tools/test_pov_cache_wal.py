"""POV's cache lock contention, and whether WAL actually removes it.

THE FIRST VERSION OF THE PATCH THIS GUARDS WAS WRONG, and the reason is worth
keeping at the top of the file. It claimed "readers block on a writer" and
proposed WAL for that. Reads never block. What blocks is a WRITE arriving while
another invocation is part-way through a READ -- and that one WAL does fix. The
difference is not cosmetic: the wrong version would have shipped a real change
to POV's data layer on every device to fix a case that does not occur.

So the block matrix is executed here, not asserted from memory, in both journal
modes, against real sqlite. If a future sqlite changes any cell, this fails and
the reason for the patch has to be re-argued rather than assumed.

Run: python3 tools/test_pov_cache_wal.py
"""
import ast
import glob
import importlib.util
import io
import os
import re
import sqlite3
import sys
import tempfile
import time
import types
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
LIB = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
MODULE = os.path.join(LIB, 'pov_cache_wal_patcher.py')
DIST = os.path.join(ROOT, 'dist')

OFF = 'PRAGMA synchronous=OFF; PRAGMA journal_mode=OFF;'
WAL = 'PRAGMA synchronous=NORMAL; PRAGMA journal_mode=WAL;'

FAIL = []
_SCRATCH = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def load(home):
    """The real module, with xbmcvfs pointed at a fake special://home."""
    for name in ('xbmcvfs', 'resources', 'resources.lib',
                 'resources.lib.kodi_utils'):
        sys.modules.pop(name, None)
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
    ku.log = lambda msg, level='INFO': ku.logged.append((level, msg))
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku
    spec = importlib.util.spec_from_file_location('pcw_t', MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.kodi_utils = ku
    return m


def pov_home(files):
    """A fake special://home carrying plugin.video.pov source files."""
    home = tempfile.mkdtemp(prefix='pcw-')
    _SCRATCH.append(home)
    for rel, text in files.items():
        full = os.path.join(home, 'addons', 'plugin.video.pov',
                            *rel.split('/'))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with io.open(full, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
    return home


def read_pov(home, rel):
    with io.open(os.path.join(home, 'addons', 'plugin.video.pov',
                              *rel.split('/')), encoding='utf-8',
                 newline='') as f:
        return f.read()


# --- 0. the block matrix, executed --------------------------------------
print('=== which direction actually blocks, in each journal mode ===')


def block_probe(pragmas, holder, arriver):
    """Returns (effective journal_mode, seconds, blocked?).

    `holder` is 'writer' (an open write transaction) or 'reader' (a cursor
    part-way through a large result set -- the lazy fetch is what holds the
    SHARED lock, which is why this uses fetchone() and not fetchall()).
    """
    d = tempfile.mkdtemp(prefix='pcw-db-')
    _SCRATCH.append(d)
    db = os.path.join(d, 'metacache.db')
    c = sqlite3.connect(db, isolation_level=None)
    c.executescript(pragmas)
    c.execute('CREATE TABLE metadata (db_type TEXT, tmdb_id TEXT, meta TEXT, '
              'expires INT)')
    c.executemany('INSERT INTO metadata VALUES (?,?,?,?)',
                  [('movie', str(i), '{"x":"%s"}' % ('y' * 3000), 9999999999)
                   for i in range(3000)])
    mode = c.execute('PRAGMA journal_mode').fetchone()[0]
    c.close()

    h = sqlite3.connect(db, isolation_level=None)
    h.executescript(pragmas)
    if holder == 'writer':
        h.execute('BEGIN IMMEDIATE')
        h.execute("INSERT OR REPLACE INTO metadata VALUES ('tv','1','{}',1)")
    else:
        cur = h.execute('SELECT db_type, tmdb_id, meta, expires FROM metadata '
                        'ORDER BY expires DESC')
        cur.fetchone()

    a = sqlite3.connect(db, isolation_level=None)   # POV's exact connect call
    a.executescript(pragmas)
    t0 = time.time()
    blocked = False
    try:
        if arriver == 'read':
            a.execute("SELECT meta FROM metadata WHERE tmdb_id='7'").fetchone()
        else:
            a.execute("INSERT OR REPLACE INTO metadata "
                      "VALUES ('tv','9','{}',1)")
    except sqlite3.OperationalError:
        blocked = True
    took = time.time() - t0
    for conn in (a, h):
        try:
            conn.close()
        except Exception:
            pass
    return mode, took, blocked


MATRIX = {}
for pragmas, name in ((OFF, 'off'), (WAL, 'wal')):
    for holder in ('writer', 'reader'):
        for arriver in ('read', 'write'):
            mode, took, blocked = block_probe(pragmas, holder, arriver)
            MATRIX[(name, holder, arriver)] = (mode, took, blocked)
            print('   %-3s holder=%-6s arriver=%-5s -> %s %.2fs'
                  % (mode, holder, arriver,
                     'BLOCKED' if blocked else 'ok     ', took))

check('journal_mode=OFF really is what POV asks for',
      MATRIX[('off', 'writer', 'read')][0] == 'off')
check('journal_mode=WAL really takes effect',
      MATRIX[('wal', 'writer', 'read')][0] == 'wal')

# THE CASE THE PATCH EXISTS FOR.
check('OFF: a reader mid-scan BLOCKS a writer',
      MATRIX[('off', 'reader', 'write')][2],
      'if this stops blocking, the patch has no reason to exist')
check('WAL: the same writer is not blocked',
      not MATRIX[('wal', 'reader', 'write')][2],
      'WAL no longer fixes the case it was chosen for')
check('...and it is fast, not merely eventually successful',
      MATRIX[('wal', 'reader', 'write')][1] < 1.0,
      '%.2fs' % MATRIX[('wal', 'reader', 'write')][1])
check('...and the block it replaces was the full 5s default busy timeout',
      4.5 <= MATRIX[('off', 'reader', 'write')][1] <= 6.5,
      '%.2fs -- the field log\'s +5.38s and +10.00s excesses were read as one '
      'and two of these' % MATRIX[('off', 'reader', 'write')][1])

# THE CASES IT DOES NOT FIX, asserted so nobody claims it does.
check('reads never block, in either mode',
      not MATRIX[('off', 'writer', 'read')][2]
      and not MATRIX[('wal', 'writer', 'read')][2],
      'the first version of the patch was written for a case that does not '
      'occur')
check('writer-vs-writer blocks in BOTH modes -- WAL does not help there',
      MATRIX[('off', 'writer', 'write')][2]
      and MATRIX[('wal', 'writer', 'write')][2])


# --- 1. the anchors match POV as shipped ---------------------------------
print()
print('=== the anchors match the POV in the released build ===')


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
check('a full build was found to inspect', fb is not None)
POV = {}
if fb:
    probe = load(pov_home({}))
    with zipfile.ZipFile(fb) as z:
        for _label, rel, _old, _new in probe.SITES:
            POV[rel] = z.read(
                'addons/plugin.video.pov/' + rel).decode('utf-8')
    for label, rel, old, new in probe.SITES:
        check('%s: shipped POV has the block exactly once' % label,
              POV[rel].count(old) == 1,
              'found %d -- if POV changed this upstream, re-derive the patch '
              'rather than keeping one that matches nothing' % POV[rel].count(old))
        check('%s: ...and is not already patched' % label,
              new not in POV[rel])


# --- 2. the repair -------------------------------------------------------
print()
print('=== the repair ===')
if POV:
    home = pov_home(POV)
    mod = load(home)
    st = mod.ensure_patched()
    print('   status: %s' % st)
    check('every site patches', st.count('=patched') == len(mod.SITES), st)

    for label, rel, old, new in mod.SITES:
        after = read_pov(home, rel)
        check('%s: patched source is still valid python' % label,
              ast.parse(after) is not None)
        check('%s: the marker is present' % label, mod.MARK in after)

    # THE PRAGMAS SAY WHAT WE THINK, and the SQL is executable. Checking the
    # text alone would accept `journal_mode = WAL` inside a string nothing runs.
    for rel in ('resources/lib/caches/__init__.py',
                'resources/lib/caches/meta_cache.py'):
        after = read_pov(home, rel)
        body = re.search(r'executescript\("""(.*?)"""\)', after, re.S).group(1)
        check('%s: journal_mode is WAL' % rel.split('/')[-1],
              re.search(r'journal_mode\s*=\s*WAL', body) is not None, body)
        check('%s: synchronous is NORMAL, not OFF' % rel.split('/')[-1],
              re.search(r'synchronous\s*=\s*NORMAL', body) is not None, body)
        d = tempfile.mkdtemp(prefix='pcw-sql-')
        _SCRATCH.append(d)
        con = sqlite3.connect(os.path.join(d, 'x.db'), isolation_level=None)
        con.executescript(body)          # must be valid SQL, not just text
        check('%s: ...and the block really puts sqlite in WAL'
              % rel.split('/')[-1],
              con.execute('PRAGMA journal_mode').fetchone()[0] == 'wal')
        con.close()

    # mmap_size was in meta_cache's block and must survive.
    meta = read_pov(home, 'resources/lib/caches/meta_cache.py')
    check('meta_cache keeps its mmap_size pragma', 'mmap_size = 268435456' in meta)

    # THE KEEP-LIST, executed. This is the site that stops POV's own 3-day
    # maintenance deleting a live write-ahead log.
    ku_after = read_pov(home, 'resources/lib/modules/kodi_utils.py')
    fn = re.search(r'def current_dbs\(\):\n(?:\t.*\n)+', ku_after).group(0)
    ns = {}
    exec(fn, ns)
    dbs = ns['current_dbs']()
    for name in ('settings.xml', 'maincache.db', 'metacache.db', 'watched.db',
                 'navigator.db', 'views.db', 'debridcache.db',
                 'providerscache.db', 'traktcache.db', 'mdblcache.db',
                 'fenomcache.db'):
        if name not in dbs:
            check('keep-list still keeps %s' % name, False)
    check('keep-list still keeps every original name', True)
    check('keep-list now spares maincache.db-wal',
          'maincache.db-wal' in dbs,
          'without this, remove_old_databases() deletes the live log')
    check('keep-list now spares metacache.db-shm', 'metacache.db-shm' in dbs)
    check('...for every database, not just the two patched ones',
          all(n + s in dbs for n in dbs if n.endswith('.db')
              for s in ('-wal', '-shm')))
    check('...and settings.xml did not sprout a -wal name',
          'settings.xml-wal' not in dbs)

    check('running it again changes nothing',
          mod.ensure_patched().count('=unchanged') == len(mod.SITES))


# --- 3. the safety rule: keep-list first, or nothing ---------------------
print()
print('=== the keep-list is written first, or no database moves to WAL ===')
if POV:
    # kodi_utils.py in a shape the patch does not recognise: the keep-list
    # cannot be written, so neither pragma site may be touched. Otherwise a
    # device runs WAL while POV's cleanup still deletes -wal files.
    broken = dict(POV)
    broken['resources/lib/modules/kodi_utils.py'] = 'def current_dbs():\n\treturn set()\n'
    home2 = pov_home(broken)
    mod2 = load(home2)
    st2 = mod2.ensure_patched()
    check('an unrecognised keep-list is reported, not forced',
          'cleanup_keeps_wal_files=unmatched' in st2, st2)
    check('...and it says WHY nothing else ran',
          'wal_not_enabled=keep_list_first' in st2, st2)
    for rel in ('resources/lib/caches/__init__.py',
                'resources/lib/caches/meta_cache.py'):
        check('...and %s was NOT moved to WAL' % rel.split('/')[-1],
              'journal_mode = WAL' not in read_pov(home2, rel),
              'a database in WAL mode with a cleanup that deletes its log')

    # The keep-list site is index 0 in SITES, and that is load-bearing.
    check('the keep-list really is the first site',
          mod2.SITES[0][1].endswith('kodi_utils.py')
          and mod2._KEEP_SITE == 0)


# --- 4. what it must not touch -------------------------------------------
print()
print('=== files it does not recognise are left alone ===')
home3 = pov_home({'resources/lib/modules/kodi_utils.py': 'x = 1\n',
                  'resources/lib/caches/__init__.py': 'y = 2\n',
                  'resources/lib/caches/meta_cache.py': 'z = 3\n'})
mod3 = load(home3)
before3 = read_pov(home3, 'resources/lib/caches/__init__.py')
st3 = mod3.ensure_patched()
check('an unrecognised keep-list stops the pass', '=unmatched' in st3, st3)
check('...and nothing was written',
      read_pov(home3, 'resources/lib/caches/__init__.py') == before3)

if POV:
    # Two copies of a pragma block means a POV somebody has edited. Refuse.
    twice = dict(POV)
    _b = None
    for label, rel, old, new in load(pov_home({})).SITES:
        if rel.endswith('caches/__init__.py'):
            _b = old
    twice['resources/lib/caches/__init__.py'] = \
        POV['resources/lib/caches/__init__.py'].replace(_b, _b + '\n' + _b, 1)
    home4 = pov_home(twice)
    mod4 = load(home4)
    st4 = mod4.ensure_patched()
    check('two copies of a block are refused, not half-patched',
          'base_cache_wal=unmatched' in st4, st4)
    check('...and both copies are left exactly as they were',
          read_pov(home4, 'resources/lib/caches/__init__.py').count(_b) == 2)

home5 = tempfile.mkdtemp(prefix='pcw-none-')
_SCRATCH.append(home5)
mod5 = load(home5)
st5 = mod5.ensure_patched()
check('no POV installed is reported, not crashed', 'no_pov' in st5, st5)


# --- 5. it is wired in, and actually runs --------------------------------
print()
print('=== the service actually runs it ===')
svc = io.open(os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                           'service.py'), encoding='utf-8').read()
check('service.py defines the step',
      'def _maybe_patch_pov_cache_wal(' in svc)
tup = re.search(r'steps = \((.*?)\n    \)', svc, re.S)
check('...and the repair pass actually lists it',
      tup is not None and '_maybe_patch_pov_cache_wal,' in tup.group(1),
      'defined but never called is the failure this check exists for')


print()
if FAIL:
    print('FAILED: %d -> %s' % (len(FAIL), FAIL))
    raise SystemExit(1)
print('ALL PASS')
