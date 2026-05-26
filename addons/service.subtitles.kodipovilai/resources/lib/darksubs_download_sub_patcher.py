# Self-healing patch of DarkSubs's download_sub() so that when the
# user picks a non-Hebrew subtitle MANUALLY (with DarkSubs's
# auto_translate setting OFF), our AI hook still gets a chance to
# run.
#
# The problem:
#   DarkSubs's download_sub has this structure for non-Hebrew subs:
#
#     if 'Hebrew' in language:
#         ...apply RTL fixes, upload to Telegram...
#     elif Addon.getSetting("auto_translate")=='true':
#         ...call machine_translate_subs (where our hook lives)...
#
#   If auto_translate is OFF, the elif never fires -- and our hook
#   in machine_translate_subs never runs. The user sees the original
#   English subtitle on screen, not the AI-translated Hebrew.
#
#   Users who want "no Google Translate ever" turn auto_translate OFF
#   to prevent DarkSubs from auto-translating with Google. They still
#   want AI to translate when they manually pick a non-Hebrew sub.
#
# The fix:
#   Extend the elif's condition so it ALSO fires when our AI key is
#   set in service.subtitles.kodipovilai. machine_translate_subs gets
#   called, our existing hook (darksubs_patcher.py) inside it routes
#   to our AI. From the user's perspective:
#     - auto_translate=ON  + no AI key : Google (unchanged)
#     - auto_translate=OFF + no AI key : English (unchanged)
#     - auto_translate=ON  + AI key set: AI (via existing hook)
#     - auto_translate=OFF + AI key set: AI (NEW -- this patch enables it)
#
# Self-healing: re-applies on every Kodi startup. .pyc cache is
# invalidated alongside the file write so DarkSubs's interpreter
# picks up the new code on next import (reuselanguageinvoker pitfall
# -- see darksubs_patcher.py).

import os

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import kodi_utils


DARKSUBS_ADDON_ID = 'service.subtitles.All_Subs'
ENGINE_REL_PATH = 'resources/modules/engine.py'

MARKER = '# AI_DOWNLOAD_SUB_ELIF_v2'

# Markers from earlier versions of this patch -- we strip them
# before reinjecting v2 so a v0.2.33-shipped v1 doesn't shadow the
# v2 condition.
OLD_MARKERS = ['# AI_DOWNLOAD_SUB_ELIF_v1']

# Exact line we're rewriting in vanilla DarkSubs. 4-space indent
# (matches DarkSubs's style in download_sub) followed by a line
# terminator -- handled in ensure_patched() with both \r\n and \n
# variants so we work on whichever line-ending style the file is in.
OLD_LINE_BODY = (
    '    elif Addon.getSetting("auto_translate")==\'true\':'
)

# v2 NEW_LINE: gates the AI-key arm of the elif behind both
#   1. our api_key being set, AND
#   2. our explicit "force_ai_when_auto_translate_off" toggle being
#      enabled in service.subtitles.kodipovilai's settings.
# Without (2), users who deliberately keep auto_translate OFF
# *because they want subtitles in the source language* (e.g.
# language learners watching English with English subs) would get
# their subs surprise-translated to Hebrew -- which is the exact
# opposite of what they wanted from "auto_translate=off". The
# default for force_ai_when_auto_translate_off is false, so this
# is opt-in: users who want AI even with auto_translate off flip
# the toggle in our addon settings.
NEW_LINE_BODY = (
    '    elif Addon.getSetting("auto_translate")==\'true\' or ('
    '(__import__(\'xbmcaddon\').Addon(\'service.subtitles.kodipovilai\')'
    '.getSetting(\'api_key\') or \'\').strip() and '
    '__import__(\'xbmcaddon\').Addon(\'service.subtitles.kodipovilai\')'
    '.getSetting(\'force_ai_when_auto_translate_off\') == \'true\''
    '):  ' + MARKER
)


def _log(msg, level='INFO'):
    try:
        kodi_utils.log('darksubs_download_sub_patcher: ' + msg,
                       level=level)
    except Exception:
        pass


def _engine_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + DARKSUBS_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, ENGINE_REL_PATH)
    return p if os.path.isfile(p) else ''


def _invalidate_pyc_cache(py_path):
    """Wipe stale engine.cpython-*.pyc so DarkSubs re-compiles on
    next import. Same logic as darksubs_patcher; duplicated here
    (intentionally) so this module stays self-contained -- the
    function is tiny and a shared util would just add an indirection.
    """
    try:
        pkg_dir = os.path.dirname(py_path)
        base = os.path.splitext(os.path.basename(py_path))[0]
        cache_dir = os.path.join(pkg_dir, '__pycache__')
        if not os.path.isdir(cache_dir):
            return
        prefix = base + '.cpython-'
        for fname in os.listdir(cache_dir):
            if fname.startswith(prefix) and fname.endswith('.pyc'):
                try:
                    os.remove(os.path.join(cache_dir, fname))
                except OSError:
                    pass
    except Exception:
        pass


def ensure_patched():
    """Rewrite download_sub's auto_translate elif so it ALSO fires
    when our AI key is set AND the force_ai_when_auto_translate_off
    toggle is on. Idempotent. Self-migrates a v1-shipped variant
    that did not gate on the toggle.
    """
    path = _engine_path()
    if not path:
        return 'no_engine'
    try:
        with open(path, 'rb') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'
    if MARKER.encode('utf-8') in content:
        return 'already_patched'

    # Detect EOL style and rebuild patterns to match.
    eol = b'\r\n' if b'\r\n' in content[:8192] else b'\n'
    vanilla_line = OLD_LINE_BODY.encode('utf-8') + eol

    # Self-migration: if a previous version of this patch (gated on
    # AI key only, no toggle) is present, revert it back to the
    # vanilla line first so the v2 rewrite below can do the right
    # substitution. The previous lines we shipped all started with
    # OLD_LINE_BODY and ended with one of the OLD_MARKERS as a
    # trailing comment.
    import re as _re
    for old_marker in OLD_MARKERS:
        # Match: indent + the elif line body + anything ending with
        # the old marker + EOL.
        pat = (_re.escape(OLD_LINE_BODY.encode('utf-8'))
               + b'[^\r\n]*?' + _re.escape(old_marker.encode('utf-8'))
               + b'[^\r\n]*?' + _re.escape(eol))
        if _re.search(pat, content):
            content = _re.sub(pat, vanilla_line, content, count=1)
            _log('reverted older v1 inject before re-applying v2',
                 level='INFO')

    if vanilla_line not in content:
        _log('download_sub auto_translate elif not found -- '
             'DarkSubs upstream may have changed', level='WARNING')
        return 'unmatched'

    new_line = NEW_LINE_BODY.encode('utf-8') + eol
    new_content = content.replace(vanilla_line, new_line, 1)
    tmp_path = path + '.aitmp'
    try:
        with open(tmp_path, 'wb') as f:
            f.write(new_content)
        os.replace(tmp_path, path)
    except OSError as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'

    _invalidate_pyc_cache(path)
    _log('rewrote download_sub elif so AI key + force-toggle '
         'triggers translation with auto_translate=OFF',
         level='INFO')
    return 'patched'
