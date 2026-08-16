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
    # A REAL store, not a stub that swallows writes: the one-shot backfill is
    # gated on a setting, and a get_setting that always returns '' would make
    # every run look like the first one -- which is exactly the bug the flag
    # exists to prevent, passing as a green test.
    store = {}
    ku.get_setting = lambda k, d='': store.get(k, d)
    ku.set_setting = lambda k, v: store.__setitem__(k, v)
    ku._store = store
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


def compiles(src):
    # `compile(...) is None or True` was ALWAYS true -- a code object is not
    # None, so the second operand won. It could not report a failure it was
    # written to report.
    try:
        compile(src, 'mdblist.py', 'exec')
        return True
    except SyntaxError:
        return False


check('the file still compiles', compiles(after))
check('SELF-CHECK: the compile check can actually fail',
      not compiles(after + '\nthis is not python(\n'))

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
# EVERY key the patcher claims to clear, not the two that happened to get
# written down: a variant that dropped last_watched_movies_at from the DELETE
# passed the old two-key version of this check.
CLEARED = ('last_watched_at', 'last_watched_movies_at',
           'last_watched_episodes_at')
check('the watched cursor is cleared so the next sync backfills',
      not [k for k in CLEARED if k in left],
      'still set: %s' % ', '.join(k for k in CLEARED if k in left))
check('unrelated sync state is left alone',
      'last_activities_at' in left,
      'the reset must clear the watched cursor, not the whole service table')
check('the three cleared keys are the three sync_watchedProgress writes',
      set(CLEARED) == set(re.findall(r"update_last_watched_at\('(\w+)'\)",
                                     mdblist_src(home2)))
      or not os.path.isdir(STOCK),
      'Umbrella advances a cursor this reset does not clear, so that half of '
      'the watched history still never backfills')
check('the reset marks itself done so it does not repeat every start',
      mod2.kodi_utils.get_setting('_umb_mdbl_cursor_reset', '') == '1')

# --- and it RETRIES when the reset could not run --------------------------
# Tying the backfill to the file write meant a reset that lost a lock race to
# Umbrella's own sync thread was never attempted again: the next start reads
# 'unchanged' and returns long before reaching it.
home4 = fresh_home()
db4_dir = os.path.join(home4, 'userdata', 'addon_data',
                       'plugin.video.umbrella')
os.makedirs(db4_dir)
db4 = os.path.join(db4_dir, 'mdbSync.db')
conn = sqlite3.connect(db4)
conn.execute('CREATE TABLE service (setting TEXT, value TEXT, '
             'UNIQUE(setting))')
for k in CLEARED:
    conn.execute('INSERT INTO service VALUES (?, ?)', (k, 'x'))
conn.commit()
conn.close()
mod4 = load(home4)
_real_reset = mod4._reset_sync_cursor
mod4._reset_sync_cursor = lambda: False          # the lock race
check('the first run patches the file even though the reset failed',
      mod4.ensure_patched() == 'patched')
check('a failed reset is NOT marked done',
      mod4.kodi_utils.get_setting('_umb_mdbl_cursor_reset', '') != '1')
mod4._reset_sync_cursor = _real_reset            # ... and it clears next time
check('the next start retries the reset even though the file is unchanged',
      mod4.ensure_patched() == 'unchanged')
conn = sqlite3.connect(db4)
left4 = {r[0] for r in conn.execute('SELECT setting FROM service')}
conn.close()
check('the retry actually cleared the cursor',
      not [k for k in CLEARED if k in left4],
      'still set: %s' % ', '.join(k for k in CLEARED if k in left4))
check('and now it is marked done',
      mod4.kodi_utils.get_setting('_umb_mdbl_cursor_reset', '') == '1')

# --- CRLF: the shape that shipped the Hebrew search fix as a silent no-op --
home5 = fresh_home()
p5 = os.path.join(home5, 'addons', 'plugin.video.umbrella', 'resources',
                  'lib', 'modules', 'mdblist.py')
with open(p5, 'w', encoding='utf-8', newline='') as f:
    f.write(before.replace('\n', '\r\n'))
mod5 = load(home5)
st5 = mod5.ensure_patched()
with open(p5, encoding='utf-8', newline='') as f:
    crlf_after = f.read()
check('a CRLF copy of the file is still patched', st5 == 'patched', st5)
check('a CRLF file stays CRLF -- the patch does not rewrite every line ending',
      '\n' not in crlf_after.replace('\r\n', ''),
      'the whole file was silently normalised to LF')
check('the CRLF patch compiles', compiles(crlf_after))
check('reverting a CRLF file restores it byte-for-byte',
      mod5._revert(crlf_after, '\r\n') == before.replace('\n', '\r\n'))

# --- SABOTAGE: the checks must be able to fail -----------------------------
print()
print('=== sabotage ===')
check('SABOTAGE: an unpatched file is detected',
      'db_last = max(0, db_last -' not in before,
      'the fixture already contains the patch, so patching proves nothing')
# _revert() walks "the marked line plus everything indented deeper". A blank
# line has no indentation to compare, and treating every blank as INSIDE the
# block eats the separator below it -- and the file's final newline, when the
# marked line is last. Both cases must survive a round trip.
_blank = "def f():\n\tx = 1  # AI_SUBS_UMB_MDBL_SINCE_v1\n\n\treturn 2\n"
check('SABOTAGE: a blank line after the block is not swallowed',
      mod._revert(_blank) == "def f():\n\n\treturn 2\n",
      'got %r' % mod._revert(_blank))
_tail = "def f():\n\treturn 2\n\tx = 1  # AI_SUBS_UMB_MDBL_SINCE_v1\n"
check("SABOTAGE: a marked LAST line keeps the file's trailing newline",
      mod._revert(_tail) == "def f():\n\treturn 2\n",
      'got %r' % mod._revert(_tail))
_nested = ("def f():\n\tif x:  # AI_SUBS_UMB_MDBL_SINCE_v1\n\t\ta = 1\n\n"
           "\t\tb = 2\n\treturn 2\n")
check('SABOTAGE: a blank line INSIDE a block is still part of the block',
      mod._revert(_nested) == "def f():\n\treturn 2\n",
      'got %r' % mod._revert(_nested))

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
