# POV's caches block each other, and the blocked write is silently discarded.
#
# MEASURED, 2026-08-23, the first field log after fast navigation shipped.
# Thirty-two navigations on one device, split by whether another POV call was
# running at the same moment:
#
#     ran alone         n=17   max    1.78s
#     overlapped one    n=15   median 4.22s   max 11.19s
#
# Every one of the eight calls over three seconds was overlapping another.
# Zero exceptions. The excess over the 1.19s solo median is bounded by
# multiples of five seconds, and one of them is +10.00s to the hundredth.
#
# FIVE SECONDS IS NOT A COINCIDENCE, it is the Python sqlite3 default busy
# timeout, and POV never overrides it for these databases:
#
#     caches/__init__.py   database_connect(self.db_file, isolation_level=None)
#
# (mdbl_cache, trakt_cache and watched_cache DO pass timeout=20; BaseCache,
# which is what main_cache and meta_cache are built on, does not.) Reproduced
# here with POV's exact call: a second connection waits 5.09s and then raises
# `database is locked`.
#
# AND POV SWALLOWS THAT, which is why the slowness outlives the moment:
#
#     def set(self, string, data, expiration):
#         try:  ...  except: pass
#
# Nothing surfaces. The five seconds are spent, the exception is discarded, and
# the entry is simply never written -- so the next visit to that category has
# to fetch it from the network all over again, and can collide all over again.
# That is the "it went back to being slow" the reporter described, and it is
# also why the problem does not settle down on its own: contention is what
# stops the cache being populated, so contention keeps having something to
# collide with.
#
# WHY TWO CALLS OVERLAP AT ALL, since one person has one remote: the home
# screen's widget rows repopulate when home regains focus, and each row is its
# own POV invocation. Browse in and back out and you get the user's press
# racing two or three widget refreshes. In the log, `tmdb_tv_premieres` and
# `tmdb_movies_latest_releases` are widgets; `tmdb_tv_networks` is the person.
#
# WHICH DIRECTION BLOCKS, MEASURED, BECAUSE THE OBVIOUS GUESS IS WRONG. The
# first version of this file said "readers block on a writer" and proposed WAL
# to fix it. Both halves of that were wrong, and a scripted reproduction caught
# it before release. sqlite 3.45.1, POV's exact connect call:
#
#   holder                    arriver   journal_mode=OFF   journal_mode=WAL
#   writer (BEGIN IMMEDIATE)  read      ok 0.00s           ok 0.00s
#   writer (BEGIN IMMEDIATE)  write     BLOCKED 5.01s      BLOCKED 5.01s
#   READER mid-scan           WRITE     BLOCKED 5.01s      ok 0.00s
#
# Readers never block. Writer-versus-writer blocks in BOTH modes, so WAL does
# nothing for it. The case WAL fixes is the third one, and it is the one POV
# spends its time in: with journal_mode=OFF a reader holds SHARED, a writer
# needs EXCLUSIVE, and EXCLUSIVE cannot be taken while anyone holds SHARED. So
# any call part-way through reading the metadata table -- every directory
# build, and MetaCache.prefetch(500) at service start -- freezes every other
# invocation's cache WRITES for five seconds. WAL is the one journal mode where
# a reader and a writer do not exclude each other at all.
#
# `synchronous = NORMAL` rather than OFF because WAL with synchronous OFF can
# lose the tail of a transaction on power loss. NORMAL is the documented
# pairing for WAL and still fsyncs only at checkpoints, not per commit.
#
# THIS IS NOT ABOUT THE FAST-NAVIGATION SWITCH and is not gated on it. The
# contention is between separate POV processes hitting the same files, which
# happens whether or not they share an interpreter. It applies to everyone.
#
# THE THIRD SITE IS THE ONE THAT MAKES THIS SAFE, and it is not an optimisation
# -- without it the other two destroy data. WAL keeps each database's log in a
# sibling `<name>-wal` file, and POV's own maintenance does this:
#
#     def remove_old_databases():
#         current_dbs = kodi_utils.current_dbs()
#         files = kodi_utils.list_dirs(databases_path)[1]
#         for item in files:
#             if item not in current_dbs:
#                 try: kodi_utils.delete_file(databases_path + item)
#
# A whitelist of filenames, and everything else in the directory is deleted.
# `maincache.db-wal` is not on it. That runs from POV's tools menu and on a
# THREE-DAY timer out of entry.py's maintenance service, so a device left alone
# would have had its live write-ahead logs deleted underneath open connections
# within three days of this patch landing. current_dbs() is taught the -wal and
# -shm names here.
#
# BECAUSE OF THAT, SITE ORDER IS FIXED AND THE THIRD SITE IS NEVER REVERTED.
# The keep-list is written FIRST, so there is no window in which a database is
# in WAL mode while the cleanup does not know to spare its log. And reverting
# it is not symmetric with the others: switching a database back out of WAL
# needs an exclusive lock POV may not be able to take, so a revert can leave
# real WAL files on disk with a keep-list that no longer protects them. Adding
# names to a keep-list costs nothing when they do not exist, so it stays.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'

# Bumped when a site's replacement text changes, so a device carrying an older
# injection is upgraded rather than reported already-patched. The marker is a
# SQL comment inside the pragma block and a Python comment in the keep-list,
# both of which the interpreter and SQLite ignore.
MARK = 'KODI_POV_IL wal v1'

_PRAGMA_OLD = (
    '\tdef _set_PRAGMAS(self):\n'
    '\t\tself.dbcur.executescript("""\n'
    '\t\t\tPRAGMA synchronous = OFF;\n'
    '\t\t\tPRAGMA journal_mode = OFF;\n'
    '%s'
    '\t\t""")')
_PRAGMA_NEW = (
    '\tdef _set_PRAGMAS(self):\n'
    '\t\tself.dbcur.executescript("""\n'
    '\t\t\t-- ' + MARK + '\n'
    '\t\t\tPRAGMA synchronous = NORMAL;\n'
    '\t\t\tPRAGMA journal_mode = WAL;\n'
    '%s'
    '\t\t""")')

_KEEP_OLD = (
    "def current_dbs():\n"
    "\treturn {'settings.xml', 'fenomcache.db', 'traktcache.db', "
    "'mdblcache.db', 'watched.db',\n"
    "\t\t\t'maincache.db', 'metacache.db', 'navigator.db', 'views.db', "
    "'debridcache.db', 'providerscache.db'}")
_KEEP_NEW = (
    "def current_dbs():\n"
    "\t_dbs = {'settings.xml', 'fenomcache.db', 'traktcache.db', "
    "'mdblcache.db', 'watched.db',\n"
    "\t\t\t'maincache.db', 'metacache.db', 'navigator.db', 'views.db', "
    "'debridcache.db', 'providerscache.db'}\n"
    "\t# " + MARK + ": WAL keeps each database's log in a sibling <name>-wal\n"
    "\t# and <name>-shm file. remove_old_databases() deletes every file in\n"
    "\t# this directory that is not named here, so without these the 3-day\n"
    "\t# maintenance pass would delete a live write-ahead log out from under\n"
    "\t# an open connection. Harmless when the files do not exist.\n"
    "\treturn _dbs | set(n + s for n in _dbs if n.endswith('.db')\n"
    "\t\t\t\t\t   for s in ('-wal', '-shm'))")

# (label, file relative to the add-on, old block, new block)
#
# ORDER IS LOAD-BEARING: the keep-list first. See the header.
SITES = (
    ('cleanup keeps wal files', 'resources/lib/modules/kodi_utils.py',
     _KEEP_OLD, _KEEP_NEW),
    ('base cache wal', 'resources/lib/caches/__init__.py',
     _PRAGMA_OLD % '', _PRAGMA_NEW % ''),
    ('meta cache wal', 'resources/lib/caches/meta_cache.py',
     _PRAGMA_OLD % '\t\t\tPRAGMA mmap_size = 268435456;\n',
     _PRAGMA_NEW % '\t\t\tPRAGMA mmap_size = 268435456;\n'),
)

# The keep-list, by index, for the rule that it is never reverted.
_KEEP_SITE = 0


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_cache_wal_patcher: ' + msg, level=level)
    except Exception:
        pass


def _path(rel):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    full = os.path.join(base, *rel.split('/'))
    return full if os.path.isfile(full) else ''


def _read(path):
    with open(path, encoding='utf-8', newline='') as fh:
        return fh.read()


def _write(path, text):
    """Replace in one step, so a torn write cannot leave POV half-edited."""
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _patch_one(rel, old, new):
    """'no_pov' | 'unchanged' | 'patched' | 'unmatched' | 'read_failed'
    | 'write_failed'."""
    path = _path(rel)
    if not path:
        return 'no_pov'
    try:
        text = _read(path)
    except Exception as exc:
        _log('{0}: read failed: {1}'.format(rel, exc), level='WARNING')
        return 'read_failed'

    if new in text:
        return 'unchanged'
    # A marker present without this exact replacement means an OLDER injection
    # of ours: strip nothing, just report it, because guessing at the shape of
    # a version we no longer carry is how a file gets corrupted.
    if MARK not in text and text.count(old) != 1:
        _log('{0}: not the shape this patches ({1} match(es)); leaving it '
             'alone'.format(rel, text.count(old)), level='WARNING')
        return 'unmatched'
    if MARK in text and old not in text:
        _log('{0}: carries a different version of this patch; leaving it '
             'alone'.format(rel), level='WARNING')
        return 'unmatched'

    try:
        _write(path, text.replace(old, new, 1))
    except Exception as exc:
        _log('{0}: write failed: {1}'.format(rel, exc), level='WARNING')
        return 'write_failed'
    return 'patched'


def ensure_patched():
    """Idempotent. Never raises. A comma-joined per-site status.

    STOPS AT THE FIRST SITE THAT DOES NOT END UP IN PLACE, and that is the
    whole safety argument. The keep-list is site 0; if it cannot be written,
    no database is switched to WAL, so POV's three-day cleanup is never given
    the chance to delete a log file it does not know about. Sites 1 and 2 are
    independent of each other and either order is fine, but neither may run
    before site 0 has succeeded.
    """
    out = []
    for i, (label, rel, old, new) in enumerate(SITES):
        try:
            st = _patch_one(rel, old, new)
        except Exception as exc:
            _log('{0}: unexpected failure: {1}'.format(rel, exc),
                 level='WARNING')
            st = 'read_failed'
        out.append('%s=%s' % (label.replace(' ', '_'), st))
        if st not in ('patched', 'unchanged'):
            if i == _KEEP_SITE:
                out.append('wal_not_enabled=keep_list_first')
            break
    if any(o.endswith('=patched') for o in out):
        _log('POV cache databases moved to WAL; readers no longer wait on a '
             'writer. Takes effect on the next POV invocation')
    return ', '.join(out)
