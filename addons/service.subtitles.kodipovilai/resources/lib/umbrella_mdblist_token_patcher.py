# Stop Umbrella nagging about an MDBList session it cannot renew.
#
# Umbrella captures its Authorization header once, when modules/mdblist.py is
# imported, and never looks at the setting again except through its own
# refresher. In this build that refresher can never run: we hand Umbrella
# POV's access token and deliberately leave `mdblist.refresh.token` EMPTY,
# because a refresh token belongs to the client it was issued to and Umbrella
# posts its OWN client id -- so its refresh would be rejected and, on
# rejection, Umbrella clears the authorisation outright. See
# mdblist_umbrella_mirror for the whole arrangement.
#
# The consequence is what the field reported. POV rotates its token; our
# mirror writes the new one into Umbrella's settings within the minute; but
# Umbrella is still sending the token it read at import, gets a 401, finds no
# refresh token, and shows:
#
#     MDBList session expired — please re-authenticate in settings
#
# which is wrong twice over: nothing has expired that reconnecting Umbrella
# would fix, and in this build MDBList is not connected from Umbrella's
# settings at all -- it is connected once, in POV, for both.
#
# So two changes, both inside Umbrella's own refresher:
#
#   1. Before giving up, re-read `mdblist.token`. If it is not the one the
#      session is holding, adopt it and report success -- the caller then
#      retries the request, which is exactly what it does after a real
#      refresh. This is the whole fix for the common case, and it needs no
#      refresh token because somebody else has already done the refreshing.
#   2. Drop the dialog. Since POV was taught to refresh and retry on its own
#      401 (pov_mdblist_reauth_patcher), a genuinely dead token now heals at
#      the source within a sync cycle; and until it does, a popup telling the
#      user to go and fix it in the wrong add-on's settings is worse than
#      silence. The failure is still logged where Umbrella logs everything
#      else.

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


UMBRELLA_ADDON_ID = 'plugin.video.umbrella'
TARGET_REL = 'resources/lib/modules/mdblist.py'
MARKER = '# AI_SUBS_UMB_MDBL_TOKEN_v1'

_OLD_REFRESH = (
    "def _refresh_token():\n"
    "\ttry:\n"
    "\t\trefresh_token = getSetting('mdblist.refresh.token')\n"
    "\t\tif not refresh_token:\n"
    "\t\t\treturn False"
)
_NEW_REFRESH = (
    "def _refresh_token():\n"
    "\ttry:\n"
    "\t\t# Somebody else may already have refreshed this account -- in this\n"
    "\t\t# build POV owns the refreshing, with the client id the refresh\n"
    "\t\t# token was issued to. The header here was read at import, so a\n"
    "\t\t# newer token in settings is the ordinary reason for a 401.\n"
    "\t\t_ai_token = getSetting('mdblist.token')\n"
    "\t\tif _ai_token and session.headers.get('Authorization') != 'Bearer %s' % _ai_token:\n"
    "\t\t\tsession.headers.update({'Authorization': 'Bearer %s' % _ai_token})\n"
    "\t\t\treturn True\n"
    "\t\trefresh_token = getSetting('mdblist.refresh.token')\n"
    "\t\tif not refresh_token:\n"
    "\t\t\treturn False"
)

_OLD_NOTIFY = (
    "\t\t\tcontrol.notification(title='MDBList', "
    "message='MDBList session expired — please re-authenticate in settings')"
)
_NEW_NOTIFY = (
    "\t\t\t# No dialog: MDBList is connected in POV in this build, not here,\n"
    "\t\t\t# so 'authenticate in settings' points at the wrong screen -- and\n"
    "\t\t\t# POV refreshes and retries on its own 401, so this heals itself.\n"
    "\t\t\tlog_utils.log('MDBList 401 and no usable token here; POV owns the "
    "refresh', level=log_utils.LOGDEBUG)"
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('umbrella_mdblist_token_patcher: ' + msg, level=level)
    except Exception:
        pass


def _target_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + UMBRELLA_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *TARGET_REL.split('/'))
    return p if os.path.isfile(p) else ''


def _fitter(content):
    # Umbrella ships this file LF today, but parts of the pack this build
    # carries are CRLF, and an anchor that only matches LF is how the Hebrew
    # search fix shipped as a silent no-op.
    eol = '\r\n' if '\r\n' in content else '\n'
    return (lambda t: t.replace('\n', eol)) if eol != '\n' else (lambda t: t), eol


def ensure_patched():
    """Returns 'patched' | 'already_patched' | 'no_umbrella' | 'no_file'
    | 'unmatched' | 'compile_failed' | 'read_failed' | 'write_failed'."""
    path = _target_path()
    if not path:
        return 'no_umbrella' if xbmcvfs is None else 'no_file'
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'already_patched'

    fit, eol = _fitter(content)
    old_refresh, old_notify = fit(_OLD_REFRESH), fit(_OLD_NOTIFY)
    for name, anchor in (('_refresh_token head', old_refresh),
                         ('session-expired dialog', old_notify)):
        if content.count(anchor) != 1:
            _log('{0} not found exactly once -- Umbrella may have changed it; '
                 'leaving alone'.format(name), level='WARNING')
            return 'unmatched'

    out = content.replace(old_refresh, fit(_NEW_REFRESH), 1)
    out = out.replace(old_notify, fit(_NEW_NOTIFY), 1)
    out = out.replace(eol, eol + MARKER + eol, 1)

    try:
        compile(out.replace('\r\n', '\n'), path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(out)
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
            if fn.startswith('mdblist.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache, fn))
                except OSError:
                    pass

    _log('Umbrella now picks up a refreshed MDBList token instead of asking '
         'to be re-authorised', level='INFO')
    return 'patched'


def revert():
    """Returns 'reverted' | 'not_patched' | 'no_file' | 'failed'."""
    path = _target_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            content = f.read()
    except OSError:
        return 'failed'
    if MARKER not in content:
        return 'not_patched'
    fit, _eol = _fitter(content)
    out = content.replace(fit(_NEW_REFRESH), fit(_OLD_REFRESH), 1)
    out = out.replace(fit(_NEW_NOTIFY), fit(_OLD_NOTIFY), 1)
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
