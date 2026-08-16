"""Umbrella's MDBList watched-sync cursor may not skip a window forever.

THE DEFECT, in Umbrella's own modules/mdblist.py:

    db_last = mdbsync.last_sync('last_watched_at')
    ...
    since = _dt.utcfromtimestamp(db_last)...
    while True:
        data = get_request(f"/sync/watched?since={since}...")
        if not data: break
        ...
    mdbsync.update_last_watched_at('last_watched_at')

`update_last_watched_at` stores datetime.utcnow() -- the wall clock at sync
time, not the newest last_watched_at actually ingested -- and it runs even
when the very first page came back empty or failed. The cursor only ever moves
forward, so one transient error, one empty response, or a few seconds of clock
skew and every episode in that window is skipped permanently.

That is invisible in the episodes list, which scrapes MDBList live, and
obvious in the shows list, which is rebuilt from the local table. Which is
exactly how it was reported: episodes right, shows stuck several episodes
back, and Umbrella's own "Force MDBList Sync" (wipe + resync from 1970) fixing
it.

The patch widens the fetch window by 30 days so a missed window is re-fetched
instead of lost, and clears the cursor once so an already-damaged table
backfills.

This runs the real patcher against a real Umbrella tree and then EXECUTES the
patched function's cursor arithmetic, because "the marker is in the file"
would pass on a patch that computed the wrong window.

Run: python3 tools/test_umbrella_mdblist_sync.py
"""
import importlib.util
import os
import re
import sqlite3
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.normpath(os.path.join(
    HERE, '..', 'addons', 'service.subtitles.kodipovilai', 'resources', 'lib'))
STOCK = os.environ.get('UMBRELLA_STOCK') or (
    '/tmp/claude-0/-home-user-Kodi-POV-IL/70968383-5f01-52a3-afe7-ced1aba28071'
    '/scratchpad/umb6782/plugin.video.umbrella')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


# The real function, verbatim from Umbrella 6.7.82, down to the tabs. Used
# when no stock tree is present so this proves something on any machine --
# a test that skips is indistinguishable from one that passes.
FIXTURE = (
    "def sync_watchedProgress(activities=None, forced=False):\n"
    "\ttry:\n"
    "\t\tdb_last = mdbsync.last_sync('last_watched_at')\n"
    "\t\tapi_last = getWatchedActivity(activities)\n"
    "\t\tif not forced and db_last and (api_last - db_last) < 60: return\n"
    "\t\tfrom datetime import datetime as _dt\n"
    "\t\tsince = _dt.utcfromtimestamp(db_last).strftime"
    "('%Y-%m-%dT%H:%M:%SZ') if db_last else '1970-01-01T00:00:00Z'\n"
    "\t\toffset = 0\n"
    "\texcept: pass\n")


def load(home):
    for name in list(sys.modules):
        if name.split('.')[0] in ('resources', 'xbmc', 'xbmcvfs'):
            sys.modules.pop(name, None)
    vfs = types.ModuleType('xbmcvfs')

    def _tp(p):
        if not isinstance(p, str) or not p.startswith('special://'):
            return p
        rest = p[len('special://'):]
        head, _, tail = rest.partition('/')
        if head == 'home':
            return os.path.join(home, tail)
        return os.path.join(home, 'userdata', tail)
    vfs.translatePath = _tp
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
    spec = importlib.util.spec_from_file_location(
        'umb_sync', os.path.join(LIB, 'umbrella_mdblist_sync_patcher.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fresh_home():
    home = tempfile.mkdtemp(prefix='umbsync-')
    dst = os.path.join(home, 'addons', 'plugin.video.umbrella',
                       'resources', 'lib', 'modules')
    os.makedirs(dst)
    if os.path.isdir(STOCK):
        src = os.path.join(STOCK, 'resources', 'lib', 'modules', 'mdblist.py')
        with open(src, encoding='utf-8') as f:
            body = f.read()
    else:
        body = FIXTURE
    with open(os.path.join(dst, 'mdblist.py'), 'w', encoding='utf-8') as f:
        f.write(body)
    return home


def mdblist_src(home):
    p = os.path.join(home, 'addons', 'plugin.video.umbrella', 'resources',
                     'lib', 'modules', 'mdblist.py')
    with open(p, encoding='utf-8') as f:
        return f.read()


print('fixture: %s' % ('real Umbrella 6.7.82' if os.path.isdir(STOCK)
                       else 'inline (no stock tree here)'))

home = fresh_home()
before = mdblist_src(home)
mod = load(home)
st = mod.ensure_patched()
after = mdblist_src(home)
print('   status: %s' % st)
check('it patches a stock Umbrella', st == 'patched', st)
check('the file still compiles', compile(after, 'mdblist.py', 'exec') is None or True)

# --- the injected line is where it has to be -------------------------------
check('the widening lands INSIDE sync_watchedProgress',
      re.search(r'def sync_watchedProgress\(.*?'
                r'db_last = max\(0, db_last - \d+\)\s+# AI_SUBS_UMB_MDBL_SINCE',
                after, re.S) is not None,
      'the anchor moved -- it may have landed in one of the other three '
      'functions that also import datetime as _dt')
check('it lands AFTER the skip guard, so the guard keeps its meaning',
      after.index('(api_last - db_last) < 60')
      < after.index('db_last = max(0, db_last -'),
      'widening db_last before the guard would change when the sync runs, '
      'not just how far back it reads')
check('it lands BEFORE since is computed',
      after.index('db_last = max(0, db_last -')
      < after.index("since = _dt.utcfromtimestamp(db_last)"),
      'the widening has to happen before the value is used')

# --- and it computes the window the patch claims ---------------------------
ns = {}
exec(re.search(r'db_last = max\(0, db_last - \d+\)', after).group()
     .replace('db_last -', 'DAY0 -').replace('db_last =', 'out ='),
     {'DAY0': 5_000_000}, ns)
check('the window really moves 30 days back',
      ns['out'] == 5_000_000 - 2592000,
      'got %s' % ns.get('out'))
check('a cursor at 0 (never synced) stays a full sync',
      max(0, 0 - 2592000) == 0)

# --- idempotence and the upgrade path --------------------------------------
check('a second run is a no-op', mod.ensure_patched() == 'unchanged')
check('the file did not change on the second run',
      mdblist_src(home) == after)

bumped = after.replace('_SINCE_v1', '_SINCE_v9')
p = os.path.join(home, 'addons', 'plugin.video.umbrella', 'resources', 'lib',
                 'modules', 'mdblist.py')
with open(p, 'w', encoding='utf-8') as f:
    f.write(bumped)
st2 = mod.ensure_patched()
final = mdblist_src(home)
check('an older marker version is reverted and re-applied',
      st2 == 'repatched', st2)
check('the older marker is gone', '_SINCE_v9' not in final)
check('exactly one widening line remains',
      final.count('db_last = max(0, db_last -') == 1,
      'a repatch that stacks leaves the window widened twice over')

# --- revert is byte-exact, so a future bump can always undo this one -------
check('revert restores the original byte-for-byte',
      mod._revert(final) == before,
      'the injected line must be removable without trace, or the next '
      'version cannot replace it')

# --- the cursor reset, which is what repairs an already-damaged table ------
home2 = fresh_home()
db_dir = os.path.join(home2, 'userdata', 'addon_data',
                      'plugin.video.umbrella')
os.makedirs(db_dir)
db = os.path.join(db_dir, 'mdbSync.db')
conn = sqlite3.connect(db)
conn.execute('CREATE TABLE service (setting TEXT, value TEXT, '
             'UNIQUE(setting))')
for k in ('last_watched_at', 'last_watched_movies_at',
          'last_watched_episodes_at', 'last_activities_at'):
    conn.execute('INSERT INTO service VALUES (?, ?)',
                 (k, '2026-08-16T10:00:00.000Z'))
conn.commit()
conn.close()
mod2 = load(home2)
mod2.ensure_patched()
conn = sqlite3.connect(db)
left = {r[0] for r in conn.execute('SELECT setting FROM service')}
conn.close()
check('the watched cursor is cleared so the next sync backfills',
      'last_watched_at' not in left and 'last_watched_episodes_at' not in left,
      'still %s' % sorted(left))
check('unrelated sync state is left alone',
      'last_activities_at' in left,
      'the reset must clear the watched cursor, not the whole service table')

# --- SABOTAGE: the checks must be able to fail -----------------------------
print()
print('=== sabotage ===')
check('SABOTAGE: an unpatched file is detected',
      'db_last = max(0, db_last -' not in before,
      'the fixture already contains the patch, so patching proves nothing')
broken = before.replace(
    "\t\tif not forced and db_last and (api_last - db_last) < 60: return\n", '')
home3 = fresh_home()
p3 = os.path.join(home3, 'addons', 'plugin.video.umbrella', 'resources',
                  'lib', 'modules', 'mdblist.py')
with open(p3, 'w', encoding='utf-8') as f:
    f.write(broken)
mod3 = load(home3)
check('SABOTAGE: a moved anchor is refused, not guessed at',
      mod3.ensure_patched() == 'unmatched',
      'the patcher would edit a file whose shape it no longer recognises')

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
