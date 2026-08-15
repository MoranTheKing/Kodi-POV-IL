# Let POV recover from an MDBList 401 instead of waiting to be reconnected.
#
# THE REPORT. "MDBList session expired -- please re-authenticate in settings"
# keeps coming back, and reconnecting the account by hand is the only thing
# that clears it. The log says it plainly:
#
#   >> mdblist error <<: 401 Client Error: Unauthorized for url:
#      https://api.mdblist.com/sync/last_activities
#   >> POV <<: SyncMonitor Service Update POV MDBListMonitor - Failed.
#      Error from MDBList - Next Update in 30 minutes...
#
# twice inside eight seconds of startup, from two different POV sync threads.
#
# WHY IT NEVER HEALS. POV refreshes its MDBList token on a CLOCK CHECK only:
#
#     def mdbl_expires():
#         if not get_setting('mdblist.refresh', ''): return
#         ...
#         if interval + current >= expires: mdbl_refresh()
#
# and call_mdblist() treats a 401 as just another RequestException -- it logs
# and returns None. So the moment the stored access token stops being accepted
# while `mdblist.expires` still looks comfortably in the future, there is no
# path back: every call fails, the sync monitor backs off half an hour, and
# the account has to be authorised again by hand. Umbrella has had the
# reactive retry from the beginning (modules/mdblist.py get_request refreshes
# and retries once on a 401); POV has not.
#
# HOW THE TOKEN GETS THERE. MDBList rotates: a refresh returns a NEW refresh
# token and retires the old one. POV starts two `mdbl_sync_activities` passes
# seconds apart at every startup and each calls mdbl_expires() -- so two
# refreshes with the same rotating token is the normal case here, not an
# exotic one, and the loser can leave a token stored that the server has
# already replaced. Whether that is what happened on this device is not
# provable from a log, which is exactly why the fix is to recover from a
# rejected token rather than to explain it: it heals the same either way. The
# lock closes the race as well, so both halves are covered.
#
# WHAT THIS DOES NOT DO. It does not touch the API-KEY path. A POV
# `mdblist.token` with no `mdblist.refresh` beside it is an API key, and there
# is nothing to refresh -- the retry would post an empty refresh token and
# turn one clear failure into two.

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
TARGET_REL = 'resources/lib/indexers/mdblist_api.py'
MARKER = '# AI_SUBS_POV_MDBL_REAUTH_v1'

_OLD_DEF = 'def call_mdblist(path, params=None, json=None, method=None):'
_NEW_DEF = 'def _ai_call_mdblist_once(path, params=None, json=None, method=None):'

# Anchored on the `except` LINE alone, never on the logger call under it.
# pov_mdblist_patcher rewrites that logger line to redact the api key from the
# message, and both patchers run at every startup from the same steps tuple.
# Matching the logger text meant this patcher applied only while it happened to
# run first -- reorder the tuple, or edit either anchor, and the whole 401
# recovery would go quietly missing behind one WARNING. Inserting after the
# `except` line is independent of what the handler body looks like.
_OLD_EXCEPT = "\texcept requests.RequestException as e:\n"
_NEW_EXCEPT = (
    "\texcept requests.RequestException as e:\n"
    "\t\t_ai_mdbl_tls.status = getattr(getattr(e, 'response', None), 'status_code', 0) or 0\n"
)

_OLD_EXPIRES = '\tif interval + current >= expires: mdbl_refresh()'
_NEW_EXPIRES = '\tif interval + current >= expires: _ai_mdbl_refresh_once()'

# The injected code CALLS this, so its existence is an anchor too. Without
# it a POV release that renamed the refresher would still be patched, and
# the first 401 would raise NameError inside somebody's sync instead of
# quietly declining to help. Caught by a harness that renamed it.
_OLD_REFRESH_DEF = 'def mdbl_refresh():'

_INSERT_BEFORE = 'def _get_mdbl_paginated_list(url):'

# Thread-local, not a module global: POV runs several sync threads at once and
# a shared "last status" would have one thread's 401 answer another thread's
# question.
_INJECT = '''_ai_mdbl_tls = __import__('threading').local()
_AI_MDBL_REFRESH_LOCK = 'pov_ai_mdbl_refreshing'

def _ai_mdbl_refresh_once():
\t# One refresh at a time, across POV's own threads and across processes.
\t# MDBList rotates the refresh token, so two refreshes racing means the
\t# loser stores an access token the server has already replaced -- and POV,
\t# which otherwise only refreshes on a clock check, never notices.
\ttry:
\t\timport xbmcgui
\t\twindow = xbmcgui.Window(10000)
\texcept Exception:
\t\twindow = None
\tbefore = get_setting('mdblist.token')
\tif window is not None:
\t\tfor _ in range(60):
\t\t\tif window.getProperty(_AI_MDBL_REFRESH_LOCK) != 'true': break
\t\t\tkodi_utils.sleep(250)
\t\tif get_setting('mdblist.token') != before: return True
\t\twindow.setProperty(_AI_MDBL_REFRESH_LOCK, 'true')
\t\t# Check-then-set is not atomic on a window property, so two threads
\t\t# arriving together can both get past the poll. Reading the token again
\t\t# AFTER claiming catches that: if the other one already refreshed, its
\t\t# token is on disk and there is nothing left to do. The poll ceiling
\t\t# above is deliberate too -- a process that died holding the property
\t\t# must not deadlock every caller after it.
\t\tif get_setting('mdblist.token') != before:
\t\t\twindow.clearProperty(_AI_MDBL_REFRESH_LOCK)
\t\t\treturn True
\ttry:
\t\tmdbl_refresh()
\tfinally:
\t\tif window is not None: window.clearProperty(_AI_MDBL_REFRESH_LOCK)
\treturn get_setting('mdblist.token') != before

def call_mdblist(path, params=None, json=None, method=None):
\t# Refresh and retry once on a 401, the way Umbrella's own MDBList client
\t# does. Without this a rejected token is permanent until the account is
\t# authorised again by hand.
\t_ai_mdbl_tls.status = 0
\tresult = _ai_call_mdblist_once(path, params=params, json=json, method=method)
\tif result is not None or getattr(_ai_mdbl_tls, 'status', 0) != 401: return result
\tif not get_setting('mdblist.refresh', ''): return result
\tif not _ai_mdbl_refresh_once(): return result
\t_ai_mdbl_tls.status = 0
\treturn _ai_call_mdblist_once(path, params=params, json=json, method=method)

'''


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_mdblist_reauth_patcher: ' + msg, level=level)
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
    # leaves call_mdblist renamed with nothing calling it, which is every
    # MDBList feature in POV gone.
    for name, anchor in (('call_mdblist def', old_def),
                         ('RequestException handler', old_except),
                         ('mdbl_expires clock check', old_expires),
                         ('insertion point', insert_before),
                         ('mdbl_refresh def', _fit(_OLD_REFRESH_DEF))):
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
            if fn.startswith('mdblist_api.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache, fn))
                except OSError:
                    pass

    _log('POV now refreshes and retries once on an MDBList 401 instead of '
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
