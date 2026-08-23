# How long a category actually takes, in a log anybody can send.
#
# THE REPORT: a spinner on every category press, and "the July build felt
# lighter". The log that came with it is the problem in miniature -- it is
# info level, which is what a user can produce, and it contains not one number
# about POV. The only marker of navigation in it at all is Kodi's
#
#     Control 51 in window 10025 has been asked to focus, but it can't
#
# fired sixteen times over three minutes with gaps of 3 to 24 seconds. Those
# gaps are the user's reading time plus the directory build, mixed together
# and impossible to separate. A diagnosis from that would be a guess, and a
# guess about performance is how a build acquires an "optimisation" that
# optimises nothing.
#
# WHAT THIS ADDS: one line per plugin call, naming the elapsed seconds and the
# route. Router.run is the single door every POV plugin invocation goes
# through -- `with self: return routing(sys)`, one line, in entry.py -- so one
# insertion covers every category, every list, every search.
#
#     >> KODI_POV_IL timing <<: 11.42s ?action=tmdb_tv_networks&...
#
# At INFO, on purpose, because the whole point is that it appears in the log a
# user sends without being asked to enable anything. One line per press is not
# noise next to POV's own service chatter.
#
# IN A `finally`, also on purpose. Router.__exit__ can raise SystemExit (its
# reuse-language-invoker guard does), and a call that ends that way is exactly
# the kind worth timing. A `finally` reports it; an ordinary trailing line
# would not.
#
# WHAT IT IS NOT: it does not make anything faster, and it must never be
# mistaken for having done so. It turns "the spinner feels long" into a number
# that says which route and how long, which is the thing that has been missing.
#
# v2 ADDS `mods=A->B`, AND IT IS THERE TO SETTLE AN ARGUMENT v1 COULD NOT.
# v1 answered the first report: five unrelated routes with floors between
# 1.72s and 1.89s, and a revisit no faster than the first visit. That
# says "fixed per-invocation cost" but not WHICH cost, and the leading
# explanation -- POV re-importing itself because we turned
# `reuse_language_invoker` off -- stayed an inference, because no log in hand
# had a warm-interpreter sample to compare against.
#
# A and B are len(sys.modules) either side of the call, and between them they
# answer it outright:
#   * A is cold-or-warm. A fresh interpreter arrives with a few dozen modules;
#     a reused one arrives with hundreds. No arithmetic needed, just the size.
#   * B - A is what the ROUTE had to load. POV defers its weight into the route
#     (`_import('menus.tvshows', 'Menu')`), so on a cold interpreter this is
#     hundreds and on a warm one it is zero -- the same route, the same work,
#     the difference being only what was already in sys.modules.
# One log from a device with `pov_fast_navigation` on now proves or disproves
# the whole diagnosis, instead of arguing about it.
#
# `import sys as _kpi_sys` RATHER THAN THE ARGUMENT. Router.run takes a
# parameter named `sys`, and in the real add-on POV's router.py passes the sys
# module -- but nothing in the signature promises that, and a caller passing
# anything else turns len(sys.modules) into an AttributeError inside the
# finally block, whose own except would swallow it and take the timing line
# with it. A patch whose entire purpose is a line that always appears must not
# lose that line to an assumption about its caller. (Not hypothetical: this
# file's own test harness calls run() with a stand-in, and the first version
# of v2 silently logged nothing under it.)
#
# Modelled on pov_debrid_unbound_guard_patcher next door; read that first if
# this needs changing.

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
REL = 'resources/lib/entry.py'

MARKER = '# AI_SUBS_POV_DIRTIMING_v2'
_MARKER_ANY = '# AI_SUBS_POV_DIRTIMING_v'

# The tag every timing line carries, so a log can be grepped for it and so
# nobody mistakes these lines for something POV prints.
TAG = 'KODI_POV_IL timing'

# `def run(self, sys)` appears once in the file; the two other `run` methods
# take no argument. Carrying the body line as well makes the insertion point
# unambiguous and makes the patch self-documenting.
ANCHOR = (
    "\tdef run(self, sys):\n"
    "\t\twith self: return routing(sys)\n"
)

# The stand-in for the marker inside _SHAPES. Defined up here
# because _V1 below is written with it already substituted in.
_MARKER_SLOT = '<<<MARKER>>>'

REPLACEMENT = (
    "\tdef run(self, sys):\n"
    "\t\timport time as _kpi_time  " + MARKER + "\n"
    "\t\timport sys as _kpi_sys\n"
    "\t\t_kpi_t0 = _kpi_time.time()\n"
    "\t\ttry: _kpi_m0 = len(_kpi_sys.modules)\n"
    "\t\texcept Exception: _kpi_m0 = -1\n"
    "\t\ttry:\n"
    "\t\t\twith self: return routing(sys)\n"
    "\t\tfinally:\n"
    "\t\t\ttry: logger('" + TAG + "', '%.2fs mods=%s->%s %s' % "
    "(_kpi_time.time() - _kpi_t0, _kpi_m0, len(_kpi_sys.modules), "
    "(sys.argv[2] if len(sys.argv) > 2 else '')[:180]))\n"
    "\t\t\texcept Exception: pass\n"
)

# v1: the same wrapper without the two module counts. Kept here because
# _SHAPES is the ONLY description of a block this file no longer writes, and
# a device carrying v1 has to be reverted forward rather than ending up with
# both wrappers nested.
_V1 = (
    "\tdef run(self, sys):\n"
    "\t\timport time as _kpi_time  " + _MARKER_SLOT + "\n"
    "\t\t_kpi_t0 = _kpi_time.time()\n"
    "\t\ttry:\n"
    "\t\t\twith self: return routing(sys)\n"
    "\t\tfinally:\n"
    "\t\t\ttry: logger('" + TAG + "', '%.2fs %s' % "
    "(_kpi_time.time() - _kpi_t0, (sys.argv[2] if len(sys.argv) > 2 "
    "else '')[:180]))\n"
    "\t\t\texcept Exception: pass\n"
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_directory_timing_patcher: ' + msg, level=level)
    except Exception:
        pass


def _fitter(content):
    eol = '\r\n' if '\r\n' in content else '\n'
    return ((lambda t: t.replace('\n', eol)) if eol != '\n'
            else (lambda t: t)), eol


# Every shape this module has EVER written, newest first, with its marker
# left as the placeholder below. _revert walks it so a device carrying an
# older injection can be brought forward. Adding a version means appending the
# shape it replaces here -- there is no way to reconstruct a block this file
# no longer describes, and guessing at one would corrupt somebody else's
# add-on.
#
# A literal placeholder and str.replace, NOT str.format: the block contains
# percent formatting and could one day contain a brace, and a revert that
# raises on its own template is a revert that never runs.
_SHAPES = (
    REPLACEMENT.replace(MARKER, _MARKER_SLOT),
    _V1,
)


def _revert(content, eol='\n'):
    """Put the file back the way POV wrote it.

    NOT the indent walk the sibling patchers use. Those insert a line and
    delete "the marked line plus everything deeper"; this one WRAPS an
    existing line in a try/finally, so the line to keep is nested INSIDE the
    block to remove. The only correct revert is to put POV's original two
    lines back.

    Matched as a WHOLE BLOCK, with the version number of the marker as the
    only wildcard. A partial or hand-edited copy therefore matches nothing and
    is left alone and reported, rather than half-removed -- which on somebody
    else's add-on is the difference between "we did not touch it" and "we
    broke it".
    """
    fit, _ = _fitter(content)
    marker = _found_marker(content)
    if not marker:
        return content
    for shape in _SHAPES:
        injected = fit(shape.replace(_MARKER_SLOT, marker))
        if injected in content:
            return content.replace(injected, fit(ANCHOR), 1)
    return content


def _found_marker(content):
    """The marker actually present -- the _MARKER_ANY prefix plus whatever
    version digits follow it in the file.

    Deliberately without an example: a marker literal spelled out here, even
    inside a docstring, is indistinguishable from a real one to the scanner
    that audits this tree's markers, and it read a made-up version number as a
    shipped one.
    """
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


def ensure_patched():
    """Idempotent. Never raises. Returns 'no_pov' | 'no_file' | 'unchanged'
    | 'patched' | 'repatched' | 'unmatched' | 'read_failed' | 'write_failed'
    | 'compile_failed' | 'revert_failed'.

    "Never raises" IS THE CONTRACT, and it needs the outer guard to be true.
    Both siblings have one; this file inlined everything behind narrow excepts
    instead, and _drop_pycache's bare os.listdir walked straight out of it on
    a directory it could not read. The caller then logged "failed" for a patch
    that had already landed, and -- the part that matters -- never reached the
    note_patched() that makes POV re-import it, so the change sat on disk
    doing nothing until some unrelated release happened to arm a cycle.
    """
    try:
        return _ensure_patched()
    except Exception as exc:
        _log('unexpected failure: {0}'.format(exc), level='WARNING')
        return 'read_failed'


def _ensure_patched():
    if xbmcvfs is None:
        return 'no_pov'
    path = _pov_path(REL)
    if not path:
        return 'no_file'
    try:
        with open(path, encoding='utf-8', newline='') as f:
            content = f.read()
    except Exception as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    fit, eol = _fitter(content)

    if MARKER in content:
        return 'unchanged'

    repatch = False
    if _MARKER_ANY in content:
        content = _revert(content, eol)
        repatch = True
        if _MARKER_ANY in content:
            _log('could not remove an older injection; leaving the file alone',
                 level='WARNING')
            return 'revert_failed'

    # count, not `in`: a refactor that duplicated this shape is unrecognised
    # rather than patched at whichever copy comes first.
    if content.count(fit(ANCHOR)) != 1:
        _log('Router.run is not the expected shape -- POV may have '
             'refactored it; leaving the file alone', level='WARNING')
        return 'unmatched'

    new_content = content.replace(fit(ANCHOR), fit(REPLACEMENT), 1)

    try:
        # lstrip the BOM for the CHECK only -- see the long note on the same
        # line in pov_debrid_unbound_guard_patcher.
        compile(new_content.lstrip('﻿'), path, 'exec')
    except SyntaxError as e:
        _log('compile check failed, not writing: {0}'.format(e),
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
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'

    _drop_pycache(path)
    _log('every POV navigation now logs how long it took')
    return 'repatched' if repatch else 'patched'
