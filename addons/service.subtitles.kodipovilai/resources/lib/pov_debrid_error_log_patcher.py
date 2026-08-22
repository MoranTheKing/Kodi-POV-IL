# A debrid that says "no" with HTTP 200, and a log that keeps none of it.
#
# THE REPORT: AllDebrid stopped working. The follow-up log said nothing about
# why -- no HTTP error, no exception, just sources that would not play.
#
# WHY THE LOG WAS EMPTY. AllDebrid does not signal refusals with status codes.
# Every answer is 200 OK, and the refusal is in the body:
#
#     {"status": "error",
#      "error": {"code": "AUTH_BAD_APIKEY", "message": "The auth apikey is invalid"}}
#
# POV's _request logs only `if not response.ok`. A 200 is ok, so nothing is
# logged; the body is then handed on, `if 'data' in response and status ==
# 'success'` is false, and the raw envelope travels up to a caller that wanted
# a list. The caller reports "no sources". The reason -- which AllDebrid spelt
# out in words -- is discarded one line after it arrives.
#
# Checked against the live API with no credentials, so the shapes below are
# observed rather than assumed: v4/user and v4/magnet/upload both answer 200
# with AUTH_MISSING_APIKEY; v4/magnet/instant answers 404. The endpoints are
# fine. AllDebrid is refusing the account and naming the refusal in a field
# nobody reads.
#
# TORBOX HAS THE SAME DISEASE with a different envelope -- {"success": false,
# "error": "...", "detail": "..."} at 200 -- and its unwrap line is worse: it
# tests `'success' in response`, which is true when success is FALSE, so on an
# error it returns response['data'] (null) and the error string never leaves
# the function.
#
# WHAT THIS DOES: one log line, at the moment the envelope is decoded, naming
# the endpoint and the provider's own code and message. It changes no control
# flow whatsoever -- POV goes on to do exactly what it did before, and the user
# sees exactly what they saw before. The difference is that the NEXT log
# somebody sends says which of "not connected", "key rejected", "banned" and
# "not premium" it was, instead of leaving four possibilities open.
#
# TWO SITES, NOT FOUR. Premiumize (`{"status":"error","message":...}` at 200)
# and Real-Debrid (proper status codes, but its log line prints the HTTP reason
# phrase -- "Forbidden" -- and drops RD's own error string) have the same
# defect. Both end _request with `return response.json() if ... else response`,
# a single expression: reporting the error there means REWRITING a line POV
# wrote, not inserting one. Every patcher here is pure insertion so that the
# revert is byte-exact, and that is worth more than two more log lines. They
# are recorded here so nobody has to rediscover them.
#
# Modelled on pov_debrid_unbound_guard_patcher next door, down to the revert
# walk and the BOM note; read that file first if this one needs changing.

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

MARKER = '# AI_SUBS_POV_DEBRID_ERRLOG_v1'
# Prefix, never an enumerated list of predecessors.
_MARKER_ANY = '# AI_SUBS_POV_DEBRID_ERRLOG_v'

# The text every injected line carries, so a user's log can be grepped for it
# and so nobody mistakes these lines for something POV itself prints.
_TAG = 'KODI_POV_IL'

# (label, relative path, anchor, the condition that means "this is a refusal")
#
# The anchor is the decode line plus the unwrap line beneath it. The decode
# line alone is not unique across POV's debrid modules; the pair is unique
# inside each file, and carrying both makes the insertion point unambiguous --
# the block goes between them, after the body is a dict and before POV throws
# the envelope away.
# (label, relative path, anchor, the condition that means "this is a refusal",
#  the expression naming WHAT was refused)
#
# ONE EXPRESSION, AND NO CHAINED .get. This carried a separate code and message
# expression, and AllDebrid's read `(response.get('error') or {}).get('code')`.
# That is a bet that `error` is a dict -- `or {}` only rescues a FALSY value,
# so an `error` that is a string, a list or a number sails through and .get
# raises AttributeError. The guard around the line then swallows it and NOTHING
# is logged, for exactly the case a diagnostic is worth most: an answer whose
# shape we did not expect. Logging the whole value instead cannot raise on a
# shape, and reads no worse -- a dict prints its own code and message.
_SITES = (
    ('alldebrid', 'resources/lib/debrids/alldebrid_api.py',
     "\t\tresponse = response.json() if 'json' in response.headers.get('Content-Type', '') else response\n"
     "\t\tif 'data' in response and response.get('status') == 'success': response = response['data']\n",
     "response.get('status') == 'error'",
     "response.get('error')"),
    ('torbox', 'resources/lib/debrids/torbox_api.py',
     "\t\tresponse = response.json() if 'json' in response.headers.get('Content-Type', '') else response\n"
     "\t\tif not self._is_control(path) and 'data' in response and 'success' in response: response = response['data']\n",
     "response.get('success') is False",
     "(response.get('error'), response.get('detail'))"),
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_debrid_error_log_patcher: ' + msg, level=level)
    except Exception:
        pass


def _fitter(content):
    eol = '\r\n' if '\r\n' in content else '\n'
    return (lambda t: t.replace('\n', eol)) if eol != '\n' else (lambda t: t)


# The marker inside a shape, so a block written by an older version can be
# recognised whatever its version number was. A literal placeholder and
# str.replace, not str.format: the block contains percent formatting.
_MARKER_SLOT = '<<<MARKER>>>'


def _found_marker(content):
    """The marker actually present -- the prefix plus its version digits."""
    at = content.find(_MARKER_ANY)
    if at < 0:
        return ''
    end = at + len(_MARKER_ANY)
    while end < len(content) and content[end].isdigit():
        end += 1
    return content[at:end]


def _revert(content, is_error, error_expr, eol='\n'):
    """Delete a previous version's injected block, by matching the WHOLE of it.

    NOT the indent walk its sibling patcher uses. That walk removes "the
    marked line and everything indented deeper", which is right until
    something else is sitting there: a review built a file with an unrelated,
    deeper-indented line straight after an old marker and watched the walk
    swallow it, report success, and leave a file that still compiled. Deleting
    somebody else's line out of somebody else's add-on is worse than any
    failure to upgrade.

    Matching the whole block cannot do that. A block that is not exactly what
    a version of this file wrote matches nothing, and the caller then reports
    revert_failed and leaves the file alone -- which is the right answer for a
    file we no longer recognise.
    """
    marker = _found_marker(content)
    if not marker:
        return content
    fit = _fitter(content)
    shape = _block(is_error, error_expr).replace(MARKER, _MARKER_SLOT)
    injected = fit(shape.replace(_MARKER_SLOT, marker))
    if injected in content:
        return content.replace(injected, '', 1)
    return content


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


def _block(is_error, error_expr):
    """The three lines that go in. Tabs, because these files use tabs.

    Wrapped in its own try/except and reading only through `.get`, because a
    log line is not worth a single new way for _request to raise. `isinstance`
    first: on a non-JSON reply `response` is still the requests object, which
    has no .get at all.
    """
    return (
        "\t\tif isinstance(response, dict) and {0}:  {1}\n"
        "\t\t\ttry: kodi_utils.logger(__name__, '{2} refused %s -- %s'"
        " % (path, {3}))\n"
        "\t\t\texcept Exception: pass\n"
    ).format(is_error, MARKER, _TAG, error_expr)


def _patch_one(rel, anchor, is_error, error_expr):
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
    eol = '\r\n' if '\r\n' in content else '\n'

    if MARKER in content:
        return 'unchanged'

    repatch = False
    if _MARKER_ANY in content:
        content = _revert(content, is_error, error_expr, eol)
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

    decode, _, unwrap = anchor.partition('\n')
    new_content = content.replace(
        fit(anchor),
        fit(decode + '\n' + _block(is_error, error_expr) + unwrap),
        1)

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
    e.g. 'alldebrid=patched, torbox=patched'.

    Per FILE, not all-or-none: two independent providers, and a POV refactor
    that moves one is no reason to leave the other silent.
    """
    if xbmcvfs is None:
        return 'no_pov'
    out = []
    for label, rel, anchor, is_error, error_expr in _SITES:
        try:
            st = _patch_one(rel, anchor, is_error, error_expr)
        except Exception as e:
            _log('{0}: unexpected failure: {1}'.format(rel, e),
                 level='WARNING')
            st = 'read_failed'
        out.append('%s=%s' % (label, st))
    if any(s.endswith('=patched') or s.endswith('=repatched') for s in out):
        _log('a debrid that refuses the account now says so in the log '
             'instead of turning into "no sources"')
    return ', '.join(out)
