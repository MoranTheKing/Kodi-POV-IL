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
# TorBox posts its hashes as a compact JSON array and answers in well under a
# second, so it never comes near the deadline. Premiumize posts every hash as
# a separate items[] field in a form body -- hundreds of them on a popular
# title -- and is slow enough, often enough, to sit right on it. That is the
# whole of "why him and not me on the same build".
#
# And the intermittency is POV's own cache: DebridCheck consults a local
# DebridCache first and skips the network entirely when every hash is already
# known. A title scraped recently answers instantly and works; a fresh one
# pays the request and does not.
#
# WHAT THIS CHANGES. Two insertions, one in each file.
#
#   debrid.py: the direct provider check is given its own try/except, and a
#   FAILED check returns None instead of an empty list. Nothing else about it
#   changes -- a check that honestly returns nothing still returns the empty
#   cached list, and is still trusted.
#
#   sources.py: a debrid that did not answer in time is put back into the loop
#   with a None reply instead of being dropped, and a None reply -- from either
#   cause -- labels its sources Unchecked rather than Uncached.
#
# So: when the debrid answers, absolutely nothing is different. When it does
# not, the user sees the sources POV found, sorted to the bottom and honestly
# labelled "we could not check these", instead of an empty screen. That is the
# same treatment POV already gives Real-Debrid and AllDebrid every single time.
#
# THE ONE THING IT COSTS. On a failed check the handful of hashes the local
# DebridCache already knew to be cached lose their cached badge along with the
# rest, because the failure discards the whole reply. They are still shown --
# it is a lost badge, not a lost source -- and paying it keeps the patch to a
# single return statement instead of a second signalling channel between two
# files.
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


# (label, relative path, the block POV ships, the block that replaces it)
#
# Whole blocks, not anchors-plus-insertion, because both fixes REWRITE a line
# POV wrote rather than adding one beside it. That rules out the pure-insertion
# revert its sibling uses, so the revert here matches the entire injected block
# byte for byte and refuses to touch a file that is not exactly what a version
# of this module wrote. See _revert.
# ORDER MATTERS, AND THE TWO HALVES ARE NOT INDEPENDENT.
#
# The sources.py half is safe on its own: against an unpatched debrid.py the
# `hashes is None` branch simply never fires, and the fix reduces to "a debrid
# that did not answer still contributes its sources, marked Unchecked".
#
# The debrid.py half is NOT safe on its own. It makes cache_check return None,
# and POV's shipped line then evaluates `i['hash'] in None`, which raises
# TypeError inside the generator, which lands in `except: notification(32574)`
# -- an error toast and an empty list, which is worse than the bug. So
# ensure_patched applies sources.py first, applies debrid.py only if sources.py
# is in the shape this module expects, and REVERTS debrid.py if it is not.
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
    "\t\t\treplies.extend((i, None) for i in self.debrid_torrents if i not in _answered)  <<<MARKER>>>\n"
    "\t\t\tfor name, hashes in replies:  <<<MARKER>>>\n"
    "\t\t\t\tif hashes is None: hashes, unconfirmed = (), True  <<<MARKER>>>\n"
    "\t\t\t\telse: unconfirmed = name in ('realdebrid', 'alldebrid')  <<<MARKER>>>\n"
    "\t\t\t\tif unconfirmed: uncached = '%s %s' % ('Unchecked', name)  <<<MARKER>>>\n"
    "\t\t\t\telse: uncached = '%s %s' % ('Uncached', name)\n",
)

# 2. Tell a failed check apart from an empty one.
#
#    `except BaseException`, not `except Exception`: the line this sits inside
#    is POV's own bare `except:`, which catches BaseException, and narrowing it
#    here would let a KeyboardInterrupt out of a frame that used to hold it.
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
    "\t\t\t\t\treturn None  <<<MARKER>>>\n",
)

# In application order. Anything walking this must keep that order.
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


def _revert_one(rel, shipped, injected):
    """Put POV's own block back. 'clean' when there was nothing to undo.

    Returns 'clean' | 'reverted' | 'no_file' | 'read_failed' | 'write_failed'
    | 'compile_failed' | 'revert_failed'.

    This exists for one case: debrid.py patched by an earlier pass, and
    sources.py no longer patchable (POV refactored it, or the write failed).
    Leaving the pair half-applied turns a late debrid into an error toast, so
    the half that cannot stand alone comes back out.
    """
    path = _pov_path(rel)
    if not path:
        return 'no_file'
    try:
        with open(path, encoding='utf-8', newline='') as f:
            content = f.read()
    except Exception as e:
        _log('{0}: read failed: {1}'.format(rel, e), level='WARNING')
        return 'read_failed'
    marker = _found_marker(content)
    if not marker:
        return 'clean'
    fit = _fitter(content)
    aged = fit(_shape(injected, marker))
    if aged not in content:
        _log('{0}: an injection is not the shape this file wrote; leaving it '
             'alone'.format(rel), level='WARNING')
        return 'revert_failed'
    content = content.replace(aged, fit(shipped), 1)
    if _MARKER_ANY in content:
        _log('{0}: more than one injection; leaving it alone'.format(rel),
             level='WARNING')
        return 'revert_failed'
    try:
        compile(content.lstrip('\ufeff'), path, 'exec')
    except SyntaxError as e:
        _log('{0}: compile check failed, not writing: {1}'.format(rel, e),
             level='WARNING')
        return 'compile_failed'
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('{0}: write failed: {1}'.format(rel, e), level='WARNING')
        return 'write_failed'
    _drop_pycache(path)
    return 'reverted'


# The states that mean "sources.py is carrying the fix right now". no_file is
# not one of them: it means POV is not installed, and then debrid.py is not
# there either and its own _patch_one answers no_file anyway.
_GOOD = ('patched', 'repatched', 'unchanged')


def ensure_patched():
    """Idempotent. Never raises. Returns a comma-joined per-file status,
    e.g. 'sources=patched, debrid=patched'.

    ORDERED, NOT PER-FILE INDEPENDENT -- see the note above _SOURCES_SITE.
    sources.py goes first because it is the half that stands alone; debrid.py
    is applied only behind it, and is reverted if sources.py is not carrying
    the fix.
    """
    if xbmcvfs is None:
        return 'no_pov'
    label, rel, shipped, injected = _SOURCES_SITE
    try:
        first = _patch_one(rel, shipped, injected)
    except Exception as e:
        _log('{0}: unexpected failure: {1}'.format(rel, e), level='WARNING')
        first = 'read_failed'
    out = ['%s=%s' % (label, first)]

    label, rel, shipped, injected = _DEBRID_SITE
    if first in _GOOD:
        try:
            second = _patch_one(rel, shipped, injected)
        except Exception as e:
            _log('{0}: unexpected failure: {1}'.format(rel, e),
                 level='WARNING')
            second = 'read_failed'
    elif first == 'no_file':
        # POV is not installed. Not a skip and not a warning -- there is
        # nothing to apply, nothing to revert, and nothing worth a line in
        # the log of every device that does not have POV.
        second = 'no_file'
    else:
        try:
            second = 'skipped:' + _revert_one(rel, shipped, injected)
        except Exception as e:
            _log('{0}: unexpected failure: {1}'.format(rel, e),
                 level='WARNING')
            second = 'skipped:read_failed'
        _log('sources.py is not carrying the fix ({0}), so the debrid.py half '
             'is not applied -- on its own it would turn a late debrid into an '
             'error toast'.format(first), level='WARNING')
    out.append('%s=%s' % (label, second))

    if any(s.endswith('=patched') or s.endswith('=repatched') for s in out):
        _log('a debrid that answers late or not at all no longer erases the '
             'source list')
    return ', '.join(out)
