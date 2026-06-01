# Self-healing patch of POV's myservices.py RepeatTimer.run() to
# wrap the polled-function call in try/except.
#
# Without this patch, a single failed poll (network blip, transient
# API error, malformed JSON response, KeyError on unexpected
# response structure) kills the entire polling thread silently --
# Python's threading.Timer.run() doesn't catch user-function
# exceptions, so any throw stops the loop dead. Result for the user:
# the auth dialog for Trakt / Real Debrid / TorBox / Premiumize /
# AllDebrid stays on screen with the same code/URL even after they
# authorize on the website, because the thread that was supposed
# to detect "authorization complete" died on its first poll.
#
# Fix is one try/except wrap. Successive polls keep retrying;
# eventually one returns a 200 with the token and the auth is
# captured. Symptom goes away across every device-flow service POV
# integrates with -- this isn't a per-service fix, it's a fix to
# the shared RepeatTimer.
#
# Self-healing: ensure_patched() runs every Kodi startup. If
# upstream POV updates myservices.py and wipes our marker, we
# re-apply. If they restructure RepeatTimer in a way the patch
# can't match anymore, we skip silently with a log -- auth
# dialogs go back to being fragile but POV itself keeps working.

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
MYSERVICES_REL_PATH = 'resources/lib/modules/myservices.py'

MARKER = '# AI_SUBS_REPEAT_TIMER_PATCH'

OLD_BODY = (
    'class RepeatTimer(Timer):\n'
    '\tdef run(self):\n'
    '\t\twhile not self.finished.wait(self.interval):\n'
    '\t\t\tself.function(*self.args, **self.kwargs)\n'
)

NEW_BODY = (
    'class RepeatTimer(Timer):\n'
    '\tdef run(self):\n'
    '\t\t' + MARKER + ": don't let a single failed poll\n"
    "\t\t# (network blip, transient API error, malformed JSON,\n"
    "\t\t# KeyError on unexpected structure) silently kill the\n"
    "\t\t# polling thread. Without this, auth dialogs for Trakt /\n"
    "\t\t# Real Debrid / TorBox / Premiumize / AllDebrid stay on\n"
    "\t\t# screen forever after the user authorizes on the website.\n"
    '\t\twhile not self.finished.wait(self.interval):\n'
    '\t\t\ttry:\n'
    '\t\t\t\tself.function(*self.args, **self.kwargs)\n'
    '\t\t\texcept Exception:\n'
    '\t\t\t\tpass\n'
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_repeat_timer_patcher: ' + msg, level=level)
    except Exception:
        pass


def _myservices_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, MYSERVICES_REL_PATH)
    return p if os.path.isfile(p) else ''


def ensure_patched():
    """Wrap RepeatTimer.run()'s self.function() call in try/except.
    Idempotent (skip if marker present), defensive (skip if upstream
    changed the shape, log and continue).
    """
    path = _myservices_path()
    if not path:
        _log('myservices.py not found', level='INFO')
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'
    if MARKER in content:
        return 'unchanged'
    if OLD_BODY not in content:
        _log('RepeatTimer body shape changed upstream -- skipping',
             level='WARNING')
        return 'unmatched'
    new_content = content.replace(OLD_BODY, NEW_BODY, 1)
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
        _log('wrapped RepeatTimer.run() in try/except for resilient '
             'device-flow auth polling', level='INFO')
        return 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
