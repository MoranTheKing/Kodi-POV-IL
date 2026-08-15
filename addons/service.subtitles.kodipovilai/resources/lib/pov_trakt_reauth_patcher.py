# Let POV recover from a Trakt 401 instead of going quiet for half an hour.
#
# The same defect as pov_mdblist_reauth_patcher, in the same shape, in the
# file next door -- found because the MDBList fix landed on a real device and
# the log showed Trakt still failing beside it:
#
#   >> POV <<: SyncMonitor Service Update POV TraktMonitor - Failed.
#      Error from Trakt - Next Update in 30 minutes...
#   >> mdblist error <<: 401 ... (fixed, and two lines later)
#   >> POV <<: SyncMonitor Service Update POV MDBListMonitor - Success
#
# POV refreshes its Trakt token on a CLOCK CHECK only:
#
#     def trakt_expires():
#         if not get_setting('trakt.refresh', ''): return
#         ...
#         if interval + current >= expires: trakt_refresh()
#
# and call_trakt() treats a 401 as just another RequestException -- it logs
# and returns None. So once the stored token stops being accepted while
# `trakt.expires` still looks comfortably in the future there is no way back:
# every call fails, the sync monitor backs off half an hour, and the account
# has to be authorised again by hand.
#
# TWO THINGS ARE DIFFERENT FROM THE MDBLIST ONE, and both are handled:
#
#   * call_trakt recurses. Its first line turns a dict argument into a call to
#     itself -- by POPPING 'path' out of the caller's dict. After the rename
#     that inner call lands on the WRAPPER, and leaving it there was a real
#     bug, not the harmless one first written here: the pop happens once, the
#     outer retry re-enters with the same now-EMPTY dict, and KeyError: 'path'
#     comes out of a background sync thread -- on exactly the revoked account
#     this exists to rescue. The wrapper therefore resolves the dict form
#     itself, on a copy, before any retry logic runs.
#   * call_trakt is handed to a ThreadPoolExecutor (executor.map(call_trakt,
#     args)). The status flag is thread-local for exactly that reason: a
#     shared one would have one worker's 401 answer another worker's question.
#
# WHAT THIS DOES NOT DO. Nothing when `trakt.refresh` is empty -- there is
# nothing to refresh, and posting an empty refresh token would turn one clear
# failure into two.
#
# Anchors are exact and each must appear exactly once. POV self-updates: the
# device this was written for is already on 6.08.08 while the copy checked
# here is 6.08.06. If POV has changed any of the four, this reports
# 'unmatched' and leaves the file alone rather than half-patching it.

import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
TARGET_REL = 'resources/lib/indexers/trakt_api.py'
MARKER = '# AI_SUBS_POV_TRAKT_REAUTH_v1'

_OLD_DEF = ('def call_trakt(path, params=None, data=None, with_auth=True, method=None, pagination=False, page=1):')
_NEW_DEF = ('def _ai_call_trakt_once(path, params=None, data=None, with_auth=True, method=None, pagination=False, page=1):')

# Anchored on the `except` LINE alone, never on the logger call under it --
# the same lesson the MDBList patcher learned when another of ours rewrote
# that logger line and the two silently depended on running order. Inserting
# after the `except` line is independent of what the handler body says.
_OLD_EXCEPT = "\texcept requests.RequestException as e:\n"
_NEW_EXCEPT = (
    "\texcept requests.RequestException as e:\n"
    "\t\t_ai_trakt_tls.status = getattr(getattr(e, 'response', None), 'status_code', 0) or 0\n"
)

_OLD_EXPIRES = '\tif interval + current >= expires: trakt_refresh()'
_NEW_EXPIRES = '\tif interval + current >= expires: _ai_trakt_refresh_once()'

# The injected code CALLS this, so its existence is an anchor too. Without
# it a POV release that renamed the refresher would still be patched, and
# the first 401 would raise NameError inside somebody's sync instead of
# quietly declining to help. Caught by a harness that renamed it.
_OLD_REFRESH_DEF = 'def trakt_refresh():'

_INSERT_BEFORE = 'def _get_trakt_paginated_list(url):'

# Thread-local, not a module global: POV runs several sync threads at once and
# a shared "last status" would have one thread's 401 answer another thread's
# question.
_INJECT = '''_ai_trakt_tls = __import__('threading').local()
_AI_TRAKT_REFRESH_LOCK = 'pov_ai_trakt_refreshing'

def _ai_trakt_refresh_once():
\t# One refresh at a time, across POV's own threads and across processes.
\t# Trakt rotates the refresh token, so two refreshes racing means the loser
\t# stores an access token the server has already replaced -- and POV, which
\t# otherwise only refreshes on a clock check, never notices.
\ttry:
\t\timport xbmcgui
\t\twindow = xbmcgui.Window(10000)
\texcept Exception:
\t\twindow = None
\tbefore = get_setting('trakt.token')
\tif window is not None:
\t\tfor _ in range(60):
\t\t\tif window.getProperty(_AI_TRAKT_REFRESH_LOCK) != 'true': break
\t\t\tkodi_utils.sleep(250)
\t\tif get_setting('trakt.token') != before: return True
\t\twindow.setProperty(_AI_TRAKT_REFRESH_LOCK, 'true')
\t\t# Check-then-set is not atomic on a window property, so two threads
\t\t# arriving together can both get past the poll. Reading the token again
\t\t# AFTER claiming catches that: if the other one already refreshed, its
\t\t# token is on disk and there is nothing left to do. The poll ceiling
\t\t# above is deliberate too -- a process that died holding the property
\t\t# must not deadlock every caller after it.
\t\tif get_setting('trakt.token') != before:
\t\t\twindow.clearProperty(_AI_TRAKT_REFRESH_LOCK)
\t\t\treturn True
\ttry:
\t\ttrakt_refresh()
\tfinally:
\t\tif window is not None: window.clearProperty(_AI_TRAKT_REFRESH_LOCK)
\treturn get_setting('trakt.token') != before

def call_trakt(path, params=None, data=None, with_auth=True, method=None, pagination=False, page=1):
\t# Refresh and retry once on a 401. Without this a rejected token is
\t# permanent until the account is authorised again by hand.
\t#
\t# The dict form is resolved HERE, on a COPY, before anything else. POV's
\t# own first line does `path.pop('path')`, which empties the caller's dict;
\t# left to the inner function that pop happened once, then the retry below
\t# re-entered with the same now-empty dict and raised KeyError out of a
\t# background sync thread -- on exactly the revoked account this exists to
\t# rescue. Resolving first means the retry only ever sees a string, and the
\t# copy means a caller's dict survives the call.
\tif isinstance(path, dict):
\t\t_ai_p = dict(path)
\t\treturn call_trakt(str(_ai_p.pop('path')), **_ai_p)
\t_ai_trakt_tls.status = 0
\tresult = _ai_call_trakt_once(path, params=params, data=data, with_auth=with_auth, method=method, pagination=pagination, page=page)
\tif result is not None or getattr(_ai_trakt_tls, 'status', 0) != 401: return result
\tif not get_setting('trakt.refresh', ''): return result
\tif not _ai_trakt_refresh_once(): return result
\t_ai_trakt_tls.status = 0
\treturn _ai_call_trakt_once(path, params=params, data=data, with_auth=with_auth, method=method, pagination=pagination, page=page)

'''


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_trakt_reauth_patcher: ' + msg, level=level)
    except Exception:
        pass


def _target_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *TARGET_REL.split('/'))
    return p if os.path.isfile(p) else ''


def _eol(content):
    # POV ships this file LF-only today, but a pack that has been through a
    # Windows checkout does not, and an anchor that only matches LF is how an
    # earlier patcher in this build shipped as a silent no-op for weeks.
    return '\r\n' if '\r\n' in content else '\n'


def ensure_patched():
    """Returns 'patched' | 'already_patched' | 'no_pov' | 'no_file'
    | 'unmatched' | 'compile_failed' | 'read_failed' | 'write_failed'."""
    path = _target_path()
    if not path:
        return 'no_pov' if xbmcvfs is None else 'no_file'
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            content = f.read()
    except Exception as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'already_patched'

    eol = _eol(content)

    def _fit(text):
        return text.replace('\n', eol) if eol != '\n' else text

    old_def, old_except = _fit(_OLD_DEF), _fit(_OLD_EXCEPT)
    old_expires, insert_before = _fit(_OLD_EXPIRES), _fit(_INSERT_BEFORE)
    # Every anchor must be present AND unique. A partial application here
    # leaves call_trakt renamed with nothing calling it, which is every Trakt
    # feature in POV gone.
    for name, anchor in (('call_trakt def', old_def),
                         ('RequestException handler', old_except),
                         ('trakt_expires clock check', old_expires),
                         ('insertion point', insert_before),
                         ('trakt_refresh def', _fit(_OLD_REFRESH_DEF))):
        if content.count(anchor) != 1:
            _log('{0} not found exactly once -- POV may have changed it; '
                 'leaving alone'.format(name), level='WARNING')
            return 'unmatched'

    new_content = content.replace(old_def, _fit(_NEW_DEF), 1)
    new_content = new_content.replace(old_except, _fit(_NEW_EXCEPT), 1)
    new_content = new_content.replace(old_expires, _fit(_NEW_EXPIRES), 1)
    new_content = new_content.replace(
        insert_before, _fit(_INJECT) + insert_before, 1)
    new_content = new_content.replace(eol, eol + MARKER + eol, 1)

    try:
        compile(new_content.replace('\r\n', '\n'), path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
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

    pycache = os.path.join(os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache):
        for fn in os.listdir(pycache):
            if fn.startswith('trakt_api.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache, fn))
                except OSError:
                    pass

    _log('POV now refreshes and retries once on a Trakt 401 instead of '
         'waiting to be reconnected by hand', level='INFO')
    return 'patched'


def revert():
    """Undo, for a device that needs POV exactly as shipped. Returns
    'reverted' | 'not_patched' | 'no_file' | 'failed'."""
    path = _target_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            content = f.read()
    except Exception:
        return 'failed'
    if MARKER not in content:
        return 'not_patched'
    eol = _eol(content)

    def _fit(text):
        return text.replace('\n', eol) if eol != '\n' else text

    # Every replacement has to actually land. Checking only that the marker
    # went would let a file somebody had edited near the injected text lose
    # its marker while keeping the injection -- a revert that reports success
    # and leaves the patch in place is worse than one that refuses.
    out = content
    for new, old in ((_INJECT, ''), (_NEW_EXPIRES, _OLD_EXPIRES),
                     (_NEW_EXCEPT, _OLD_EXCEPT), (_NEW_DEF, _OLD_DEF)):
        before = out
        out = out.replace(_fit(new), _fit(old) if old else '', 1)
        if out == before:
            _log('revert found the file no longer as we left it -- refusing',
                 level='WARNING')
            return 'failed'
    out = re.sub(r'[ \t]*' + re.escape(MARKER) + r'(?:\r?\n)', '', out, count=1)
    if MARKER in out:
        return 'failed'
    try:
        compile(out.replace('\r\n', '\n'), path, 'exec')
    except SyntaxError:
        return 'failed'
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(out)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return 'failed'
    return 'reverted'
