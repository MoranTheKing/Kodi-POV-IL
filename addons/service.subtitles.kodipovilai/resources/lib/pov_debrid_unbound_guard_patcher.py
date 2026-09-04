# POV's debrid error handlers crash, and the crash DELETES the real error.
#
# THE REPORT: AllDebrid, "no results" for movies and series. The log
# (paste.kodi.tv/fagigocobe) says otherwise -- 70 sources were found and the
# scrape worked fine. What failed was every attempt to PLAY one:
#
#     38 AllDebrid sources, 38 failures, all identical:
#       resolve_external_sources exception: cannot access local variable
#       'torrent_id' where it is not associated with a value
#
# That is not a "no results" condition. It is an UnboundLocalError -- and the
# `resolve_external_sources` in the log line is only where it was CAUGHT. On a
# device carrying pov_debrid_resolve_patcher, that function's own copy of this
# defect is already guarded, so the name in the message comes from one level
# down: the provider's parse_magnet_pack, which nothing was guarding.
#
# WHERE IT COMES FROM. debrids/alldebrid_api.py:
#
#     try:
#         extensions = tuple(supported_video_extensions())
#         torrent_id = self.create_transfer(magnet_url)    # <-- raises
#         ...
#     except Exception as e:
#         if torrent_id: self.delete_torrent(torrent_id)   # <-- never assigned
#         if errors: raise
#
# create_transfer does `result['magnets'][0]`, so an error reply from AllDebrid
# -- expired key, lapsed subscription, rate limit, a changed endpoint -- is a
# KeyError. `torrent_id` was never bound, and the HANDLER then reads it.
#
# AND THAT IS THE PART WORTH FIXING. The handler does not merely fail; it
# REPLACES the exception that would have said what AllDebrid actually refused
# with a generic UnboundLocalError. The diagnosis is destroyed by the code
# written to report it. Nobody can tell an expired subscription from a broken
# endpoint, because the evidence is gone before it reaches the log.
#
# This is the same disease as the Umbrella sync cursor, one layer up: the
# record of what happened and what actually happened disagree.
#
# THE CHAIN WOULD NOT STOP THERE ON STOCK POV. When parse_magnet_pack raises,
# `files = api.parse_magnet_pack(*args)` never completes, so `files` is unbound
# and the caller's handler reads `if files and torrent_id`. On this build that
# second crash is already prevented -- see the note on the caller below -- so
# it is stock POV's problem, not ours, and it is recorded here so nobody
# rediscovers it as a live one.
#
# FOUR SITES, FOUND BY SCANNING RATHER THAN BY READING. An AST pass over every
# debrid API -- "which names does an except handler read that are only ever
# assigned inside its own try?" -- found the same shape in three of the six,
# plus the caller. AllDebrid is simply the one whose API is failing today; a
# Real-Debrid or TorBox user whose provider errs at the wrong moment gets the
# identical unreadable log.
#
#     debrids/alldebrid_api.py   parse_magnet_pack        torrent_id
#     debrids/real_debrid_api.py parse_magnet_pack        torrent_id
#     debrids/torbox_api.py      parse_magnet_pack        path, torrent_id
#
# THE CALLER IS ALREADY HANDLED, AND I NEARLY SHIPPED A SECOND COPY OF IT.
# modules/debrid.py's resolve_external_sources has the identical defect and
# `pov_debrid_resolve_patcher.py` -- in this same directory, months old --
# already binds `files` and `torrent_id` at the top of it. The first draft of
# this module patched it AGAIN. It could not even have worked: that patcher
# inserts its line BETWEEN the `def` and the import, which is the middle of the
# anchor here, so the site would have reported 'unmatched' on every real device
# forever while the log carried a WARNING about it every boot. Read the
# directory before adding a patcher; the bug you just diagnosed may already
# have a fix beside it.
#
# `api` is the one name that patcher does not bind, and it does not need to be:
# the handler reads `if files and torrent_id: self._delete(api, torrent_id)`,
# `api` is assigned BEFORE `files` in the body, and `and` short-circuits -- so
# any failure early enough to leave `api` unbound leaves `files` at the guarded
# None and `api` is never reached.
#
# WHAT THIS DOES AND DOES NOT FIX. It binds those names to None before the try,
# so the handler runs as written instead of crashing. It does not make
# AllDebrid work.
#
# AND IT DOES NOT DO THE SAME THING AT ALL THREE SITES. That sentence used to
# read "the ORIGINAL exception survives to the log", flatly, for all of them.
# A review executed all three rather than only the reported one and found it is
# true of two:
#
#   alldebrid, real_debrid -- their handlers end `if errors: raise`, and the
#     caller passes errors=True (modules/debrid.py:81). Once the handler stops
#     crashing it reaches that line, and the provider's real error is logged
#     verbatim. This is the reported case, and it is fixed as described.
#
#   torbox -- its parse_magnet_pack has NO `errors` parameter and its handler
#     never re-raises. With the crash gone it simply returns None, the caller
#     finds no files, and the log says `selected_files failed`. That is a
#     different generic message, not a diagnosis. What torbox gains is the
#     crash removed and its own cleanup running; what it does not gain is the
#     reason.
#
# TORBOX IS LEFT THAT WAY ON PURPOSE. Making it re-raise would change POV's
# control flow, not just stop a crash -- and two of the three call sites
# (modules/debrid.py:137 and :166) have no try of their own, so an exception
# there would propagate into code that never expected one. A patcher into
# somebody else's add-on gets to remove a crash; it does not get to invent an
# error path.
#
# One line per site, inserted between the existing import and `try:`. Pure
# insertions, never an edit to a line POV wrote, so _revert stays byte-exact.


# POV 6.08.14 MOVED THESE FILES AND THE DEFECTS CAME WITH THEM. The debrid API
# clients were relocated from resources/lib/debrids/ to resources/lib/indexers/
# (the debrids/ name was reused for the cloud scrapers that used to live in
# scrapers/). The anchors below still match, byte for byte, in the new
# location -- so this patch did not become unnecessary, it silently stopped
# being applied, on a device where the thing it prevents still happens.
#
# `_pov_path` therefore tries the recorded folder first and then the other one,
# rather than pinning either. Both layouts are live in the field right now.

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

MARKER = '# AI_SUBS_POV_DEBRID_UNBOUND_v1'
# Prefix, never an enumerated list of predecessors.
_MARKER_ANY = '# AI_SUBS_POV_DEBRID_UNBOUND_v'

# (relative path, anchor, the names the handler reads)
#
# Each anchor carries the `def` line as well as the import and the `try:`.
# The import line alone repeats across methods in these files; the def line
# makes each anchor unique and makes the patch self-documenting -- the anchor
# names the function it is protecting.
_SITES = (
    ('resources/lib/debrids/alldebrid_api.py',
     "\tdef parse_magnet_pack(self, magnet_url, info_hash, errors=False):\n"
     "\t\tfrom modules.source_utils import supported_video_extensions\n"
     "\t\ttry:\n",
     ('torrent_id',)),
    ('resources/lib/debrids/real_debrid_api.py',
     "\tdef parse_magnet_pack(self, magnet_url, info_hash, errors=False):\n"
     "\t\tfrom modules.source_utils import supported_video_extensions\n"
     "\t\ttry:\n",
     ('torrent_id',)),
    ('resources/lib/debrids/torbox_api.py',
     "\tdef parse_magnet_pack(self, magnet_url, info_hash):\n"
     "\t\tfrom modules.source_utils import supported_video_extensions\n"
     "\t\ttry:\n",
     ('path', 'torrent_id')),
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_debrid_unbound_guard_patcher: ' + msg, level=level)
    except Exception:
        pass


def _fitter(content):
    eol = '\r\n' if '\r\n' in content else '\n'
    return (lambda t: t.replace('\n', eol)) if eol != '\n' else (lambda t: t), eol


def _revert(content, eol='\n'):
    """Delete a previous version's injected block.

    A marked line plus everything indented strictly deeper below it. Ours is a
    single marked line with nothing under it -- the line after it is `try:` at
    the same depth, so the walk stops immediately.
    """
    lines = content.split(eol)
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if _MARKER_ANY not in line:
            out.append(line)
            i += 1
            continue
        base = len(line) - len(line.lstrip())
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if nxt.strip():
                if (len(nxt) - len(nxt.lstrip())) <= base:
                    break
                i += 1
                continue
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            if (j >= len(lines)
                    or (len(lines[j]) - len(lines[j].lstrip())) <= base):
                break
            i = j
    return eol.join(out)


def _pov_path(rel):
    """POV's file, wherever this version of POV keeps it.

    6.08.14 moved the debrid API clients from debrids/ to indexers/ without
    changing them, so a path recorded against one layout has to be tried
    against the other. Returns '' when neither exists, which every caller
    already treats as "not this device's POV".
    """
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    for candidate in _relocations(rel, base):
        p = os.path.join(base, *candidate.split('/'))
        if os.path.isfile(p):
            return p
    return ''


# The folder move, and its inverse. A list rather than a string swap so a path
# that mentions neither folder is returned untouched and exactly once.
_MOVED = (('resources/lib/debrids/', 'resources/lib/indexers/'),
          ('resources/lib/indexers/', 'resources/lib/debrids/'))

# POV also renames FILES, not just folders. 6.09.01 renamed the Real-Debrid
# client `real_debrid_api.py` -> `realdebrid_api.py` (its import line in
# modules/debrid.py moved with it), and the guard reported `realdebrid=no_file`
# -- a repair silently not applying, on the client that carries the very
# unbound-name crash this exists to stop.
#
# Basenames are tried in order and the first file that EXISTS wins, so this is
# safe in both directions: a device still on 6.08.15 finds the old name, a
# device on 6.09.01 finds the new one, and neither has to know which POV it is
# running. Each rename is listed with its inverse for the same reason _MOVED is.
_RENAMED = (('real_debrid_api.py', 'realdebrid_api.py'),
            ('realdebrid_api.py', 'real_debrid_api.py'))


def _live_pkg(base):
    """Which package POV ITSELF imports these clients from, or ''.

    ORDER MATTERS AND EXISTENCE IS NOT ENOUGH, which the first version of this
    got wrong. Both folders ship in 6.08.14 -- debrids/ holds the cloud
    scrapers now -- so "try the recorded path, then the other" happily patches
    a stale debrids/torbox_api.py left behind by an earlier layout while the
    file POV actually imports, indexers/torbox_api.py, is never touched. The
    patch then reports `patched` having fixed nothing, which is worse than
    reporting `no_file`.

    POV states the answer in one line of modules/debrid.py:
        6.08.13   from debrids  import alldebrid_api, ... torbox_api, ...
        6.08.14   from indexers import alldebrid_api, ... torbox_api, ...
    """
    p = os.path.join(base, 'resources', 'lib', 'modules', 'debrid.py')
    try:
        with open(p, encoding='utf-8', errors='replace') as fh:
            text = fh.read()
    except Exception:
        return ''
    for line in text.splitlines():
        s = line.strip()
        for pkg in ('indexers', 'debrids'):
            if s.startswith('from %s import ' % pkg) and '_api' in s:
                return pkg
    return ''


def _relocations(rel, base=''):
    out = [rel]
    for a, b in _MOVED:
        if rel.startswith(a):
            alt = b + rel[len(a):]
            if alt not in out:
                out.append(alt)
    # Renamed FILES, applied to every folder candidate above -- POV has moved
    # the folder and renamed the file in separate releases, so a device can
    # need either, or both at once.
    for cand in list(out):
        head, _, tail = cand.rpartition('/')
        for a, b in _RENAMED:
            if tail == a:
                alt = '%s/%s' % (head, b) if head else b
                if alt not in out:
                    out.append(alt)
    pkg = _live_pkg(base) if base else ''
    if pkg:
        # Put the folder POV imports from first, whatever we recorded.
        out.sort(key=lambda c: 0 if '/%s/' % pkg in c else 1)
    return out


def _drop_pycache(path):
    stem = os.path.basename(path).split('.')[0] + '.'
    pycache = os.path.join(os.path.dirname(path), '__pycache__')
    if not os.path.isdir(pycache):
        return
    for fn in os.listdir(pycache):
        if fn.startswith(stem) and fn.endswith('.pyc'):
            try:
                os.remove(os.path.join(pycache, fn))
            except OSError:
                pass


def _patch_one(rel, anchor, names):
    """Returns 'no_file' | 'unchanged' | 'patched' | 'repatched' | 'unmatched'
    | 'read_failed' | 'write_failed' | 'compile_failed' | 'revert_failed'."""
    path = _pov_path(rel)
    if not path:
        return 'no_file'
    try:
        with open(path, encoding='utf-8', newline='') as f:
            content = f.read()
    except Exception as e:
        _log('{0}: read failed: {1}'.format(rel, e), level='WARNING')
        return 'read_failed'

    fit, eol = _fitter(content)

    if MARKER in content:
        return 'unchanged'

    repatch = False
    if _MARKER_ANY in content:
        content = _revert(content, eol)
        repatch = True
        if _MARKER_ANY in content:
            _log('{0}: could not remove an older injection'.format(rel),
                 level='WARNING')
            return 'revert_failed'

    # count, not `in`: a refactor that DUPLICATED this shape is unrecognised
    # rather than patched at whichever copy happens to come first.
    if content.count(fit(anchor)) != 1:
        _log('{0}: the expected shape is not there exactly once -- POV may '
             'have refactored it; leaving the file alone'.format(rel),
             level='WARNING')
        return 'unmatched'

    # `a = b = None` rather than a tuple: one name or three, the line reads the
    # same and there is no comma to get wrong.
    init = '\t\t' + ' = '.join(names) + ' = None  ' + MARKER + '\n'
    head, _, tail = anchor.rpartition('\t\ttry:\n')
    new_content = content.replace(
        fit(anchor), fit(head + init + '\t\ttry:\n' + tail), 1)

    try:
        # lstrip the BOM for the CHECK only. Reading with plain utf-8 leaves a
        # leading BOM in the string as U+FEFF, and compile() rejects it as a
        # non-printable character -- so a POV file carrying one would report
        # compile_failed forever and log a WARNING every boot, while importing
        # perfectly well in Kodi. Stripping it on the way IN would be worse: we
        # would then write the file back without its BOM, which is a byte
        # change we did not intend and would break the byte-exact revert.
        # Stock POV 6.08.13 has no BOM on any of the three; this is about the
        # file we have not seen.
        compile(new_content.lstrip('\ufeff'), path, 'exec')
    except SyntaxError as e:
        _log('{0}: compile check failed, not writing: {1}'.format(rel, e),
             level='WARNING')
        return 'compile_failed'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(new_content)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('{0}: write failed: {1}'.format(rel, e), level='WARNING')
        return 'write_failed'

    _drop_pycache(path)
    return 'repatched' if repatch else 'patched'


def ensure_patched():
    """Idempotent. Never raises. Returns a comma-joined per-file status, e.g.
    'alldebrid=patched, realdebrid=patched, torbox=patched'.

    Per FILE, not all-or-none across files: three independent handlers in three
    independent files, and a POV refactor that moves one is no reason to leave
    the other two crashing.
    """
    if xbmcvfs is None:
        return 'no_pov'
    labels = ('alldebrid', 'realdebrid', 'torbox')
    out = []
    for label, (rel, anchor, names) in zip(labels, _SITES):
        try:
            st = _patch_one(rel, anchor, names)
        except Exception as e:
            _log('{0}: unexpected failure: {1}'.format(rel, e),
                 level='WARNING')
            st = 'read_failed'
        out.append('%s=%s' % (label, st))
    if any(s.endswith('=patched') or s.endswith('=repatched') for s in out):
        _log('debrid error handlers can no longer crash on an unbound name; '
             'the real provider error now reaches the log')
    return ', '.join(out)
