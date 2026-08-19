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

The patch does three things: it stops the cursor advancing when the fetch did
not succeed (the root defect), widens the fetch window by 30 days so a window
missed for a reason no flag can see -- device clock skew -- is re-fetched
instead of lost, and clears the cursor once so an already-damaged table
backfills.

This runs the real patcher against a real Umbrella tree and then EXECUTES the
patched function, driving a scripted MDBList through success, a first-page
failure, a mid-run failure and a genuinely empty account, because "the marker
is in the file" would pass on a patch that guards the wrong line -- or that
guards so eagerly the cursor can never advance at all. The same scenarios are
run against the STOCK function too, so the suite has to demonstrate the bug it
claims to fix before it is allowed to claim the fix works.

Run: python3 tools/test_umbrella_mdblist_sync.py
"""
import datetime as _dtmod
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
    '/scratchpad/umb/plugin.video.umbrella')


def stock_version():
    """Read it, never print a hardcoded one. The banner said '6.7.82' while
    running against 6.7.85, which is exactly the kind of small lie that makes
    a later reader trust the wrong thing."""
    try:
        with open(os.path.join(STOCK, 'addon.xml'), encoding='utf-8') as f:
            m = re.search(r'<addon[^>]*?version="([0-9.]+)"', f.read(), re.S)
        return m.group(1) if m else 'unknown version'
    except Exception:
        return 'unknown version'

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


# The real function, verbatim from Umbrella 6.7.85, down to the tabs. Used
# when no stock tree is present so this proves something on any machine --
# a test that skips is indistinguishable from one that passes. It is the WHOLE
# function now, not the first few lines: three of the four injected lines live
# below the fetch loop, and a truncated fixture would report 'unmatched' on a
# machine without a stock tree and look like a broken patcher instead of a
# short fixture.
FIXTURE = (
    'def sync_watchedProgress(activities=None, forced=False):\n'
    '\ttry:\n'
    "\t\tdb_last = mdbsync.last_sync('last_watched_at')\n"
    '\t\tapi_last = getWatchedActivity(activities)\n'
    '\t\tif not forced and db_last and (api_last - db_last) < 60: return\n'
    '\t\tfrom datetime import datetime as _dt\n'
    "\t\tsince = _dt.utcfromtimestamp(db_last).strftime('%Y-%m-%dT%H:%M:%SZ') if db_last else '1970-01-01T00:00:00Z'\n"
    '\t\toffset = 0\n'
    '\t\tlimit = 1000\n'
    '\t\twhile True:\n'
    '\t\t\turl = f"/sync/watched?since={since}&limit={limit}&offset={offset}"\n'
    '\t\t\tdata = get_request(url)\n'
    '\t\t\tif not data: break\n'
    "\t\t\tfor item in data.get('movies', []):\n"
    "\t\t\t\tids = item.get('movie', {}).get('ids', {})\n"
    "\t\t\t\timdb = str(ids.get('imdb', ''))\n"
    '\t\t\t\tif not imdb: continue\n'
    '\t\t\t\tmdbsync.upsert_watched_movie(\n'
    '\t\t\t\t\timdb=imdb,\n'
    "\t\t\t\t\ttmdb=str(ids.get('tmdb', '')),\n"
    "\t\t\t\t\ttitle=item.get('movie', {}).get('title', ''),\n"
    "\t\t\t\t\tyear=str(item.get('movie', {}).get('year', '')),\n"
    "\t\t\t\t\tlast_watched_at=item.get('last_watched_at', '')\n"
    '\t\t\t\t)\n'
    "\t\t\tfor item in data.get('episodes', []):\n"
    "\t\t\t\tep = item.get('episode', {})\n"
    "\t\t\t\tshow_ids = ep.get('show', {}).get('ids', {})\n"
    "\t\t\t\tshow_imdb = str(show_ids.get('imdb', ''))\n"
    '\t\t\t\tif not show_imdb: continue\n'
    '\t\t\t\tmdbsync.upsert_watched_episode(\n'
    '\t\t\t\t\tshow_imdb=show_imdb,\n'
    "\t\t\t\t\tshow_tmdb=str(show_ids.get('tmdb', '')),\n"
    "\t\t\t\t\tshow_tvdb=str(show_ids.get('tvdb', '')),\n"
    "\t\t\t\t\tseason=ep.get('season', 0),\n"
    "\t\t\t\t\tepisode=ep.get('number', 0),\n"
    "\t\t\t\t\tlast_watched_at=item.get('last_watched_at', '')\n"
    '\t\t\t\t)\n'
    "\t\t\tpagination = data.get('pagination', {})\n"
    "\t\t\tif not pagination.get('has_more', False): break\n"
    '\t\t\toffset += limit\n'
    "\t\tmdbsync.update_last_watched_at('last_watched_at')\n"
    "\t\tmdbsync.update_last_watched_at('last_watched_movies_at')\n"
    "\t\tmdbsync.update_last_watched_at('last_watched_episodes_at')\n"
    '\t\t# invalidate indicator caches so next access fetches fresh data\n'
    '\t\tmdbsync.cache_delete(mdbsync._hash_function(syncMovies, ()))\n'
    '\t\tmdbsync.cache_delete(mdbsync._hash_function(syncTVShows, ()))\n'
    '\t\tcontrol.trigger_widget_refresh()\n'
    '\texcept: log_utils.error()\n'
)


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


print('fixture: %s' % ('real Umbrella ' + stock_version()
                       if os.path.isdir(STOCK)
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

# --- the four lines are all there, and they are all ours -------------------
check('all four injected lines are present',
      after.count(mod.MARKER) == 4,
      'found %d marked lines; three of them (init, set, check) only work as a '
      'set -- a partial application injects a NameError into somebody else\'s '
      'add-on' % after.count(mod.MARKER))
check('the flag name does not collide with anything Umbrella uses',
      before.count(mod._FLAG) == 0,
      'a collision would silently change Umbrella\'s own logic instead of '
      'failing')
check('the guard is read BEFORE the first cursor write',
      after.index('if not %s: return' % mod._FLAG)
      < after.index("mdbsync.update_last_watched_at('last_watched_at')"))
check('the flag is initialised before the loop that clears it',
      after.index('%s = True' % mod._FLAG)
      < after.index('if %s: %s = False' % (mod._NOT_A_PAGE, mod._FLAG)))
check('the failure test asks whether it LOOKS LIKE A PAGE, not whether it is '
      'empty',
      "'pagination' not in data" in mod._NOT_A_PAGE,
      'get_request hands back a 2xx body verbatim, so a soft-fail envelope '
      'that is neither a page nor falsy sails through as a last page')

# --- and the patched function BEHAVES --------------------------------------
# The window arithmetic above is one line of a three-part fix. The other two
# lines exist only to hold the cursor still on a run that failed, and nothing
# short of running the function proves that they do. So: extract
# sync_watchedProgress from both the stock and the patched file, drive each
# through the same four scripted MDBList conversations, and compare.
#
# The stock runs are not decoration. If they ever stop showing the bug, either
# Umbrella fixed it upstream -- in which case this patch should be retired --
# or the harness stopped exercising the real path, in which case the patched
# runs prove nothing either.


def extract_func(text, name='sync_watchedProgress'):
    lines = text.split('\n')
    start = next((i for i, l in enumerate(lines)
                  if l.startswith('def %s(' % name)), None)
    if start is None:
        return ''
    end = start + 1
    while end < len(lines) and (not lines[end].strip()
                                or lines[end][:1] in ('\t', ' ')):
        end += 1
    return '\n'.join(lines[start:end]) + '\n'


class FakeSync(object):
    """Just enough of resources/lib/database/mdbsync to run the loop."""

    def __init__(self, cursor):
        self.service = {'last_watched_at': cursor}
        self.movies, self.episodes = [], []
        self.cursor_writes, self.cache_deleted = [], []

    def last_sync(self, key):
        return self.service.get(key, 0)

    def update_last_watched_at(self, key='last_watched_at'):
        self.cursor_writes.append(key)
        self.service[key] = 9999999999

    def upsert_watched_movie(self, **kw):
        self.movies.append(kw)

    def upsert_watched_episode(self, **kw):
        self.episodes.append(kw)

    def cache_delete(self, h):
        self.cache_deleted.append(h)

    def _hash_function(self, fn, args):
        return getattr(fn, '__name__', str(fn))


CURSOR = 1700000000
ALL_THREE = ['last_watched_at', 'last_watched_movies_at',
             'last_watched_episodes_at']


def page(movies=0, episodes=0, has_more=False):
    """A well-formed MDBList page. Note that an EMPTY one is still truthy --
    it carries `pagination` -- which is the whole reason `not data` is a
    usable failure signal."""
    return {
        'movies': [{'movie': {'ids': {'imdb': 'tt%07d' % i, 'tmdb': str(i)},
                              'title': 'm%d' % i, 'year': '2020'},
                    'last_watched_at': '2026-08-01T00:00:00.000Z'}
                   for i in range(movies)],
        'episodes': [{'episode': {'show': {'ids': {'imdb': 'tt900%04d' % i,
                                                   'tmdb': str(i),
                                                   'tvdb': str(i)}},
                                  'season': 1, 'number': i + 1},
                      'last_watched_at': '2026-08-01T00:00:00.000Z'}
                     for i in range(episodes)],
        'pagination': {'has_more': has_more},
    }


def run(text, pages):
    fake = FakeSync(CURSOR)
    seen = {'refresh': 0, 'urls': []}
    served = list(pages)

    def get_request(url):
        seen['urls'].append(url)
        return served.pop(0) if served else None

    class _Ctl(object):
        def trigger_widget_refresh(self):
            seen['refresh'] += 1

    class _Log(object):
        def error(self):
            # Umbrella's own `except: log_utils.error()` swallows everything.
            # Here it must not: a NameError from a half-applied patch would
            # otherwise surface as "the cursor did not advance" -- and read as
            # a pass.
            raise

    g = {'mdbsync': fake, 'get_request': get_request,
         'getWatchedActivity': lambda a=None: CURSOR + 10000,
         'control': _Ctl(), 'log_utils': _Log(),
         'syncMovies': lambda: None, 'syncTVShows': lambda: None}
    body = extract_func(text)
    if not body:
        raise RuntimeError('sync_watchedProgress not found')
    exec(compile(body, 'mdblist.py', 'exec'), g)
    g['sync_watchedProgress']()
    return fake, seen


OK_PAGES = [page(1, 2, True), page(1, 2, False)]
SCENARIOS = [
    ('both pages came back', OK_PAGES, True),
    ('the first page failed outright (get_request -> None)', [None], False),
    ('page two failed after page one had landed',
     [page(1, 2, True), None], False),
    ('a 2xx whose body would not parse (get_request -> {})', [{}], False),
    # The third shape, and the one `not data` alone cannot see. get_request
    # returns response.json() verbatim on any 2xx, so a soft-fail envelope is
    # a TRUTHY dict: the loop ingests nothing, finds no `pagination`, and
    # leaves as though that had been the final page.
    ('a 2xx soft-fail envelope that is not a page at all',
     [{'error': 'rate limited'}], False),
    ('a soft-fail envelope that also carries empty lists',
     [{'error': 'rate limited', 'movies': [], 'episodes': []}], False),
    ('an account with genuinely nothing new', [page(0, 0, False)], True),
    # ... and an empty page is NOT mistaken for a failure just because it is
    # empty. Freezing the cursor on a quiet account would be the other bug.
    ('a quiet account across two pages',
     [page(0, 0, True), page(0, 0, False)], True),
]

print()
print('=== executing the patched function ===')
for label, pages, should_advance in SCENARIOS:
    fake, seen = run(after, pages)
    moved = fake.service['last_watched_at'] != CURSOR
    if should_advance:
        check('%s -> the cursor advances' % label,
              fake.cursor_writes == ALL_THREE and moved,
              'wrote %s' % fake.cursor_writes)
        check('%s -> the indicator caches are invalidated and the widgets '
              'refresh' % label,
              len(fake.cache_deleted) == 2 and seen['refresh'] == 1,
              'cache_delete x%d, refresh x%d'
              % (len(fake.cache_deleted), seen['refresh']))
    else:
        check('%s -> the cursor DOES NOT MOVE' % label,
              fake.cursor_writes == [] and not moved,
              'wrote %s -- the window just fetched is now behind the cursor '
              'and can never be asked for again' % fake.cursor_writes)
        check('%s -> nothing is re-primed off an API that just refused us'
              % label,
              fake.cache_deleted == [] and seen['refresh'] == 0)

# rows that DID arrive before the failure are still ingested: holding the
# cursor is about what we ask for next time, not about throwing away work.
fake, _ = run(after, [page(1, 2, True), None])
check('a page that landed before the failure is still ingested',
      len(fake.movies) == 1 and len(fake.episodes) == 2,
      '%d movies, %d episodes' % (len(fake.movies), len(fake.episodes)))

fake, seen = run(after, OK_PAGES)
check('a full success ingests every row from every page',
      len(fake.movies) == 2 and len(fake.episodes) == 4,
      '%d movies, %d episodes' % (len(fake.movies), len(fake.episodes)))
check('the request really asks from 30 days before the stored cursor',
      seen['urls'] and 'since=%s' % _dtmod.datetime.utcfromtimestamp(
          CURSOR - 2592000).strftime('%Y-%m-%dT%H:%M:%SZ') in seen['urls'][0],
      'first url was %r' % (seen['urls'][0] if seen['urls'] else None))

# --- the same scenarios against STOCK, which must show the bug -------------
print()
print('=== the same scenarios against stock Umbrella (the bug) ===')
for label, pages in (('first page failed', [None]),
                     ('page two failed', [page(1, 2, True), None]),
                     ('body would not parse', [{}]),
                     ('a soft-fail envelope', [{'error': 'rate limited'}]),
                     ('an envelope with empty lists',
                      [{'error': 'rate limited', 'movies': [],
                        'episodes': []}])):
    fake, seen = run(before, pages)
    check('STOCK: %s -> the cursor advances anyway (this is the defect)'
          % label,
          fake.cursor_writes == ALL_THREE,
          'stock no longer loses the window -- either Umbrella fixed this '
          'upstream and the patch should be retired, or the harness is no '
          'longer running the real path')
fake, _ = run(before, OK_PAGES)
check('STOCK: a successful run advances the cursor too, so the patch is '
      'only removing the WRONG advances',
      fake.cursor_writes == ALL_THREE)

# --- SABOTAGE: each of the three new lines is load-bearing -----------------
print()
print('=== sabotage: the behavioural checks must be able to fail ===')
no_set = '\n'.join(l for l in after.split('\n')
                   if '%s = False' % mod._FLAG not in l)
check('SABOTAGE: dropping the line that CLEARS the flag changes the source',
      no_set != after)
fake, _ = run(no_set, [page(1, 2, True), None])
check('SABOTAGE: without it the cursor advances past a failed page again',
      fake.cursor_writes == ALL_THREE,
      'the behavioural test is insensitive to the line it exists to check')

no_check = '\n'.join(l for l in after.split('\n')
                     if 'if not %s: return' % mod._FLAG not in l)
fake, _ = run(no_check, [None])
check('SABOTAGE: dropping the line that READS the flag advances again',
      fake.cursor_writes == ALL_THREE)

# A 2xx whose body is a JSON ARRAY. `data.get(...)` cannot work on a list, so
# both versions die on it -- the point is that NEITHER writes the cursor,
# because the exception unwinds past those three lines. Recorded so that a
# future change which starts swallowing it has to decide what the cursor does.
for _which, _text in (('stock', before), ('patched', after)):
    try:
        run(_text, [[1, 2, 3]])
        _raised = None
    except Exception as _e:
        _raised = type(_e).__name__
    check('%s: a JSON array body raises rather than advancing the cursor'
          % _which, _raised == 'AttributeError', 'got %s' % _raised)

no_init = '\n'.join(l for l in after.split('\n')
                    if '%s = True' % mod._FLAG not in l)
try:
    run(no_init, OK_PAGES)
    raised = False
except NameError:
    raised = True
check('SABOTAGE: dropping the INIT is a NameError, not a silent no-op',
      raised,
      'this is why the patcher applies all four lines or none -- Umbrella '
      'wraps the whole function in a bare except that would hide it')

# --- idempotence and the upgrade path --------------------------------------
check('a second run is a no-op', mod.ensure_patched() == 'unchanged')
check('the file did not change on the second run',
      mdblist_src(home) == after)

# Never the literal previous version: this line silently stopped testing
# anything the moment MARKER was bumped, because the string it looked for
# was no longer in the file and `bumped` was just a copy of `after`.
bumped = after.replace(mod.MARKER, '# AI_SUBS_UMB_MDBL_SINCE_v9')
check('SELF-CHECK: the downgrade fixture really differs',
      bumped != after, 'MARKER no longer appears in the patched file')
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
# EXACTLY ONE key. This check used to demand all three, and that demand WAS
# THE BUG -- it encoded a regression as the passing condition, which is the
# failure mode this project keeps finding in other people's tests and then
# committed itself. Reported from the field: after clearing three keys, the
# EPISODES list -- the one that had always been right -- started needing a
# manual refresh too.
#
# Only last_watched_at is the fetch cursor (modules/mdblist.py:945 reads it to
# build `since`). The other two are read by getEpisodesWatchedActivity() and
# getMoviesWatchedActivity() (mdblist.py:923-931), which playcount.py:97 uses
# as the "is there new watched activity" signal:
#
#     elif mdblist.getEpisodesWatchedActivity() < ...: timeout = 720
#     else: timeout = 0
#
# last_sync() returns 0 for a missing row, so clearing them pinned that
# comparison true forever: serve the 12-hour cache, never re-sync.
CLEARED = ('last_watched_at',)
KEPT = ('last_watched_movies_at', 'last_watched_episodes_at')
check('the fetch cursor is cleared so the next sync backfills',
      not [k for k in CLEARED if k in left],
      'still set: %s' % ', '.join(k for k in CLEARED if k in left))
check('the ACTIVITY signals are left alone -- clearing them broke the '
      'episodes list',
      all(k in left for k in KEPT),
      'cleared %s; playcount.py reads these to decide whether to re-sync, '
      'and last_sync() returns 0 for a missing row, so zeroing them means '
      '"serve the stale cache" forever'
      % ', '.join(k for k in KEPT if k not in left))
check('unrelated sync state is left alone',
      'last_activities_at' in left,
      'the reset must clear the fetch cursor, not the whole service table')
check('the cleared key is the one sync_watchedProgress reads for `since`',
      set(CLEARED) == set(re.findall(r"db_last = mdbsync\.last_sync\('(\w+)'\)",
                                     mdblist_src(home2)))
      or not os.path.isdir(STOCK),
      'the reset clears a key the fetch does not read, so the backfill will '
      'not happen')
check('the reset marks itself done so it does not repeat every start',
      mod2.kodi_utils.get_setting(mod2._RESET_FLAG, '') == mod2._RESET_GEN)

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
      mod4.kodi_utils.get_setting(mod4._RESET_FLAG, '') != mod4._RESET_GEN)
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
      mod4.kodi_utils.get_setting(mod4._RESET_FLAG, '') == mod4._RESET_GEN)

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
# A damaged table on this same install. The repair must not depend on our
# line landing in Umbrella's source -- it clears three keys in Umbrella's own
# database and is independent of the patch.
db3_dir = os.path.join(home3, 'userdata', 'addon_data',
                       'plugin.video.umbrella')
os.makedirs(db3_dir)
conn = sqlite3.connect(os.path.join(db3_dir, 'mdbSync.db'))
conn.execute('CREATE TABLE service (setting TEXT, value TEXT, '
             'UNIQUE(setting))')
for k in CLEARED:
    conn.execute('INSERT INTO service VALUES (?, ?)', (k, 'stale'))
conn.commit()
conn.close()
mod3 = load(home3)
check('SABOTAGE: a moved anchor is refused, not guessed at',
      mod3.ensure_patched() == 'unmatched',
      'the patcher would edit a file whose shape it no longer recognises')
conn = sqlite3.connect(os.path.join(db3_dir, 'mdbSync.db'))
left3 = {r[0] for r in conn.execute('SELECT setting FROM service')}
conn.close()
check('a damaged table is still repaired when the anchor no longer matches',
      not [k for k in CLEARED if k in left3],
      'this is the user who needs the repair MOST -- the forward fix cannot '
      'reach them either -- and hanging it off the success path left them '
      'with a broken table forever')

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
