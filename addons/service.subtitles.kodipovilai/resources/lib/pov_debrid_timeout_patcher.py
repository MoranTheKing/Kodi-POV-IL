# "It found 300 sources and then said there were none."
#
# THE REPORT, twice over: the counters climb while POV searches, and then the
# list never opens -- "no results" on a title that certainly has sources.
# Intermittent: the same title works on the second try. Only on Premiumize;
# the same build on TorBox is fine.
#
# Every part of that is explained by ten lines of POV, and by two separate
# defects in them. Both are in the SECOND half of a source search, the part
# where POV asks the debrid which of the torrents it already holds.
#
#     self.thread_monitor(threads, ls(32579), True)
#     threads = [i for i in threads if i.done() and not i.exception()]
#     for name, hashes in ((fut.name, fut.result()) for fut in threads):
#         if name in ('realdebrid', 'alldebrid'): uncached = 'Unchecked %s' % name
#         else: uncached = 'Uncached %s' % name
#         self.final_sources.extend(
#             {**i, 'cache_provider': name if i['hash'] in hashes else uncached, ...}
#             for i in torrent_sources)
#
# DEFECT 1 -- THE LIST IS BUILT ONLY INSIDE THAT LOOP. final_sources starts
# empty and is filled exclusively from the debrid threads that came back in
# time. thread_monitor waits scrapers.timeout.1 + 1 seconds and then stops
# waiting; the unfinished futures are dropped by the line above. With ONE
# debrid configured -- the normal setup here -- that is one thread, and if it
# is a second late, every torrent phase 1 found is discarded unread. POV then
# reports "no results" while holding hundreds of them.
#
# DEFECT 2 -- A FAILED CHECK IS RECORDED AS AN AUTHORITATIVE "NOT CACHED".
# POV already knows its cache checks are not all equally trustworthy: for
# Real-Debrid and AllDebrid it asks third-party indexes, so a miss means "we
# could not confirm" and the source is labelled Unchecked; for Premiumize,
# TorBox and Offcloud it asks the provider itself, so a miss means "no", and
# the source is labelled Uncached. That distinction matters because it decides
# whether the user ever sees the source:
#
#     modules/sources.py:546
#     return [i for i in results if 'Uncached' not in i.get('cache_provider', '')]
#
# "Display Uncached Torrents" is off by default. Uncached rows are DELETED.
# Unchecked rows are kept and sorted to the bottom.
#
# And modules/debrid.py wraps the whole check in a bare `except: pass` and
# returns the empty cached list, so a check that TIMED OUT, was REFUSED, or
# came back malformed is indistinguishable from one that honestly found
# nothing cached. Every source is stamped Uncached, the filter deletes every
# one of them, and the user gets an empty screen.
#
# WHY ONLY PREMIUMIZE, AND WHY IT USED TO BE FINE. scrapers.timeout.1 is not
# only the monitor's budget: premiumize_api and torbox_api and offcloud_api
# each take it as the per-request HTTP timeout too. So the deadline the
# monitor enforces and the deadline the request obeys are THE SAME NUMBER,
# and a request that uses its whole allowance always finishes at or after the
# moment the monitor gave up. Raising the setting cannot fix that -- it raises
# both sides equally. (This build raised it from 10 to 20 on 1 August for
# exactly this symptom. It widened the window; it could not close it.)
#
# TorBox posts its hashes as one compact JSON array; Premiumize posts every
# hash as a separate items[] field in a form body, hundreds of them on a
# popular title. That is the shape difference, and it is the best available
# explanation of "why him and not me on the same build" -- but it is inference
# from the code plus the field reports (every reporter is on Premiumize, the
# maintainer runs TorBox on the same build and has never seen it), NOT a round
# trip anybody has timed. Do not repeat it as a measurement.
#
# And the intermittency is POV's own cache: DebridCheck consults a local
# DebridCache first and skips the network entirely when every hash is already
# known. A title scraped recently answers instantly and works; a fresh one
# pays the request and does not.
#
# WHAT THIS CHANGES. Two insertions, one in each file.
#
#   debrid.py: the direct provider check is given its own try/except, and a
#   FAILED check returns the cached list AS A TUPLE instead of as a list.
#   Nothing else about it changes -- a check that honestly returns nothing
#   still returns the empty cached LIST, and is still trusted. The container
#   type is the whole signal, and the contents are unchanged so that a POV
#   that has not been patched on the other side behaves exactly as it always
#   did.
#
#   sources.py: a debrid that did not answer in time is put back into the loop
#   with an empty tuple instead of being dropped -- it has no cached list to
#   carry, having never run -- and a reply that is not a list, from either
#   cause, labels its sources Unchecked rather than Uncached.
#
# The tuple is what lets those two ship independently; the long note above
# _SOURCES_SITE is the whole of why, and it is worth reading before changing
# either block.
#
# So: when the debrid answers, absolutely nothing is different. When it does
# not, the user sees the sources POV found, sorted to the bottom and honestly
# labelled "we could not check these", instead of an empty screen. That is the
# same treatment POV already gives Real-Debrid and AllDebrid every single time.
#
# THE ONE THING IT COSTS, and only when BOTH halves are applied. On a failed
# check the handful of hashes the local DebridCache already knew to be cached
# lose their cached badge, because the tuple says "could not check" about the
# whole reply rather than about part of it. They are still shown --
# it is a lost badge, not a lost source -- and paying it keeps the patch to a
# single return statement instead of a second signalling channel between two
# files. (POV throws the whole reply away on a failure today too; the change is
# only that the caller can now tell that is what happened.)
#
# Modelled on pov_debrid_error_log_patcher next door, down to the whole-block
# revert and the BOM note; read that file first if this one needs changing.

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

MARKER = '# AI_SUBS_POV_DEBRID_TIMEOUT_v1'
# Prefix, never an enumerated list of predecessors.
_MARKER_ANY = '# AI_SUBS_POV_DEBRID_TIMEOUT_v'

# The text the injected log line carries, so a user's log can be grepped for
# it and so nobody mistakes it for something POV itself prints.
_TAG = 'KODI_POV_IL'

# A literal placeholder and str.replace, not str.format: these blocks contain
# percent formatting and braces of their own.
_MARKER_SLOT = '<<<MARKER>>>'
_TAG_SLOT = '<<<TAG>>>'


# TWO INDEPENDENT SITES, AND THE SENTINEL THAT MAKES THEM INDEPENDENT.
#
# The first draft had debrid.py `return None` on a failed check, which made the
# two halves COUPLED: against an unpatched sources.py that None reaches
# `i['hash'] in hashes` and raises TypeError into `except: notification(32574)`
# -- an error toast AND an empty list, worse than the bug. That draft applied
# sources.py first and reverted debrid.py if sources.py was not carrying the
# fix. A review broke it in one move: POV updates, rewriting the block
# sources.py targets but not the six lines debrid.py targets; the next pass
# gets `unmatched` for sources.py and is killed (reboot, OOM, abort) in the
# window before the revert runs. It built that exact on-disk state, ran the
# real lifted blocks against a real Premiumize refusal, and got the toast and
# the empty list. Self-healing on the next successful pass, but wrong until
# then, for exactly the user this fix is for.
#
# So the signal is not None. **A failed check returns an empty TUPLE.**
#
#   * unpatched sources.py: `i['hash'] in tuple(self.cached_list)` gives the
#     SAME answer for every hash that stock's `in self.cached_list` gave, so
#     the half-applied state is byte for byte what POV did before this module
#     existed. No crash, no toast, no behaviour change at all.
#
#     A bare `()` was the first attempt and it was WRONG, which a second
#     review proved by construction: when the local DebridCache already knows
#     a hash is cached and a DIFFERENT, newly-seen hash then fails its live
#     check, stock still returns the known one and shows it as cached. `()`
#     threw it away, so unpatched sources.py marked it Uncached and the
#     default filter deleted it -- worse than doing nothing, in exactly the
#     half-applied state the tuple existed to make safe. Carrying the list
#     THROUGH the tuple costs nothing and closes it.
#   * patched sources.py: `cache_check` returns a LIST on every success path
#     (self.cached_list, built in __init__ and only ever extended/appended), so
#     "not a list" means "we could not check". That covers the tuple, and it
#     also covers anything a future POV might return that stock would have
#     crashed on -- the guard is strictly safer than the line it replaces.
#
# An empty tuple and not a sentinel string, deliberately: `'' in 'SENTINEL'` is
# True, so a source with an empty hash would be reported as cached. `'' in ()`
# is False. The container has no such edge.
#
# The two sites are therefore applied independently, in any order, and neither
# needs the other to be safe. Nothing reverts anything.
#
# (label, relative path, the block POV ships, the block that replaces it)
#
# Whole blocks, not anchors-plus-insertion, because both fixes REWRITE a line
# POV wrote rather than adding one beside it. That rules out the pure-insertion
# revert its sibling uses, so the revert here matches the entire injected block
# byte for byte and refuses to touch a file that is not exactly what a version
# of this module wrote.

# 1. Keep the sources, and label them honestly.
#
#    `threads` is left alone rather than rebound, so anything POV adds below
#    that reads it still sees what it saw before.
#
#    The late list is walked in debrid_torrents order -- the order POV
#    submitted them in -- rather than in set order, so the rows come out the
#    same way twice running.
_SOURCES_SITE = (
    'sources', 'resources/lib/modules/sources.py',
    "\t\t\tthreads = [i for i in threads if i.done() and not i.exception()]\n"
    "\t\t\tfor name, hashes in ((fut.name, fut.result()) for fut in threads):\n"
    "\t\t\t\tif name in ('realdebrid', 'alldebrid'): uncached = '%s %s' % ('Unchecked', name)\n"
    "\t\t\t\telse: uncached = '%s %s' % ('Uncached', name)\n",
    "\t\t\tanswered = [i for i in threads if i.done() and not i.exception()]  <<<MARKER>>>\n"
    "\t\t\treplies = [(fut.name, fut.result()) for fut in answered]  <<<MARKER>>>\n"
    "\t\t\t_answered = {fut.name for fut in answered}  <<<MARKER>>>\n"
    "\t\t\treplies.extend((i, ()) for i in self.debrid_torrents if i not in _answered)  <<<MARKER>>>\n"
    "\t\t\tfor name, hashes in replies:  <<<MARKER>>>\n"
    "\t\t\t\tif not isinstance(hashes, list): hashes, unconfirmed = (), True  <<<MARKER>>>\n"
    "\t\t\t\telse: unconfirmed = name in ('realdebrid', 'alldebrid')  <<<MARKER>>>\n"
    "\t\t\t\tif unconfirmed: uncached = '%s %s' % ('Unchecked', name)  <<<MARKER>>>\n"
    "\t\t\t\telse: uncached = '%s %s' % ('Uncached', name)\n",
)

# 2. Tell a failed check apart from an empty one.
#
#    `except BaseException`, not `except Exception`: the line this sits inside
#    is POV's own bare `except:`, which catches BaseException. Narrowing it
#    would change which exceptions reach that outer handler; keeping it means
#    the only difference is that a failure now returns the sentinel instead of
#    an empty cached list.
#
#    The log line is wrapped again because a diagnostic is not worth a new way
#    for cache_check to raise -- and self.debrid, not self.name, since the
#    two-letter code is what the settings and the rest of the log use.
_DEBRID_SITE = (
    'debrid', 'resources/lib/modules/debrid.py',
    "\t\t\telse: checked_hashes = self.function().check_cache(unchecked_hashes)\n",
    "\t\t\telse:  <<<MARKER>>>\n"
    "\t\t\t\ttry: checked_hashes = self.function().check_cache(unchecked_hashes)  <<<MARKER>>>\n"
    "\t\t\t\texcept BaseException as e:  <<<MARKER>>>\n"
    "\t\t\t\t\ttry: kodi_utils.logger(__name__, '<<<TAG>>> %s cache check failed,"
    " reporting unchecked -- %s' % (self.debrid, e))  <<<MARKER>>>\n"
    "\t\t\t\t\texcept Exception: pass  <<<MARKER>>>\n"
    "\t\t\t\t\treturn tuple(self.cached_list)  <<<MARKER>>>\n",
)

_SITES = (_SOURCES_SITE, _DEBRID_SITE)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_debrid_timeout_patcher: ' + msg, level=level)
    except Exception:
        pass


def _fitter(content):
    eol = '\r\n' if '\r\n' in content else '\n'
    return (lambda t: t.replace('\n', eol)) if eol != '\n' else (lambda t: t)


def _shape(text, marker):
    return text.replace(_MARKER_SLOT, marker).replace(_TAG_SLOT, _TAG)


def _found_marker(content):
    """The marker actually present -- the prefix plus its version digits."""
    at = content.find(_MARKER_ANY)
    if at < 0:
        return ''
    end = at + len(_MARKER_ANY)
    while end < len(content) and content[end].isdigit():
        end += 1
    return content[at:end]


def _pov_path(rel):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *rel.split('/'))
    return p if os.path.isfile(p) else ''


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


def _patch_one(rel, shipped, injected):
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

    fit = _fitter(content)
    want = fit(_shape(injected, MARKER))
    n_markers = content.count(_MARKER_ANY)

    # `want in content` alone used to answer this, and it short-circuits: a
    # file carrying the current block AND an orphan from some other version
    # would be called unchanged and the orphan would stay for good. Each
    # injected block here carries a known number of markers, so counting is
    # exact rather than a guess.
    expected = want.count(MARKER)
    if want in content and n_markers == expected:
        return 'unchanged'
    if want in content:
        _log('{0}: carries the current block plus {1} stray marker(s); '
             'leaving it alone rather than guessing which to remove'.format(
                 rel, n_markers - expected), level='WARNING')
        return 'revert_failed'

    marker = _found_marker(content)
    repatch = False
    if marker:
        aged = fit(_shape(injected, marker))
        if aged not in content:
            _log('{0}: an older injection is not the shape this file wrote; '
                 'leaving it alone'.format(rel), level='WARNING')
            return 'revert_failed'
        content = content.replace(aged, fit(shipped), 1)
        repatch = True
        if _MARKER_ANY in content:
            _log('{0}: could not remove an older injection'.format(rel),
                 level='WARNING')
            return 'revert_failed'

    # count, not `in`: a refactor that DUPLICATED this shape is left
    # unrecognised rather than patched at whichever copy comes first.
    if content.count(fit(shipped)) != 1:
        _log('{0}: the expected shape is not there exactly once -- POV may '
             'have refactored it; leaving the file alone'.format(rel),
             level='WARNING')
        return 'unmatched'

    new_content = content.replace(fit(shipped), want, 1)

    try:
        # lstrip the BOM for the CHECK only -- see the long note on the same
        # line in pov_debrid_unbound_guard_patcher for why stripping it on the
        # way in would be worse.
        compile(new_content.lstrip('﻿'), path, 'exec')
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
    """Idempotent. Never raises. Returns a comma-joined per-file status,
    e.g. 'sources=patched, debrid=patched'.

    PER FILE, AND IN ANY ORDER. See the note above _SOURCES_SITE for why that
    is true here and was not true of the first draft: a failed check returns an
    empty tuple, which unpatched sources.py handles as "nothing cached" exactly
    as it always did. Neither half can hurt anybody without the other, so a POV
    refactor that moves one is no reason to skip -- or undo -- the other.
    """
    if xbmcvfs is None:
        return 'no_pov'
    out = []
    for label, rel, shipped, injected in _SITES:
        try:
            st = _patch_one(rel, shipped, injected)
        except Exception as e:
            _log('{0}: unexpected failure: {1}'.format(rel, e),
                 level='WARNING')
            st = 'read_failed'
        out.append('%s=%s' % (label, st))
    if any(s.endswith('=patched') or s.endswith('=repatched') for s in out):
        _log('a debrid that answers late or not at all no longer erases the '
             'source list')
    return ', '.join(out)
