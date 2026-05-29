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
import re

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
# Kept for the v1 self-migration path below (which matched on it).
OLD_LINE_BODY = (
    '    elif Addon.getSetting("auto_translate")==\'true\':'
)

# Flexible matcher for the auto_translate elif. Different DarkSubs
# builds vary on:
#   * indentation (kept verbatim via group 'indent')
#   * the addon-handle variable name (Addon / _Addon / addon ...),
#     captured via group 'addon' so the rewrite reuses it
#   * quote style around 'auto_translate' and 'true' (" vs ')
#   * spacing around == and inside getSetting(...)
# User report (v0.2.49): a wizard-on-existing-Kodi install had a
# DarkSubs whose elif line didn't byte-match OLD_LINE_BODY, so the
# patch returned 'unmatched', the hook never fired on manual picks,
# and English stayed on screen. The regex below matches the
# semantically-equivalent line regardless of those cosmetic
# differences. Anchored per-line; we require EXACTLY ONE match or
# we bail (so we never rewrite the wrong line).
_ELIF_RE = re.compile(
    rb'^(?P<indent>[ \t]*)elif[ \t]+'
    rb'(?P<addon>[A-Za-z_][A-Za-z0-9_.]*)\.getSetting\([ \t]*'
    rb'["\']auto_translate["\'][ \t]*\)[ \t]*==[ \t]*'
    rb'["\']true["\'][ \t]*:[ \t]*(?:\r?\n|$)',
    re.MULTILINE,
)


def _build_new_line(indent, addon, eol):
    """Reconstruct the elif preserving the file's own indentation and
    addon-handle variable name, appending the AI-key OR-arm + marker.
    Operates on bytes."""
    return (
        indent + b'elif ' + addon
        + b'.getSetting("auto_translate")==\'true\' or ('
        b'(__import__(\'xbmcaddon\').Addon('
        b'\'service.subtitles.kodipovilai\')'
        b'.getSetting(\'api_key\') or \'\').strip() and '
        b'__import__(\'xbmcaddon\').Addon('
        b'\'service.subtitles.kodipovilai\')'
        b'.getSetting(\'force_ai_when_auto_translate_off\') == \'true\''
        b'):  ' + MARKER.encode('utf-8') + eol
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
    that did not gate on the toggle. Matching is regex-based so it
    tolerates cosmetic differences across DarkSubs builds (quote
    style, spacing, indentation, addon-handle variable name).
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

    # Detect EOL style.
    eol = b'\r\n' if b'\r\n' in content[:8192] else b'\n'

    # Self-migration: if a previous version of this patch (gated on
    # AI key only, no toggle) is present, revert it back to the
    # vanilla line first so the v2 rewrite below can do the right
    # substitution. The v1 line we shipped started with the exact
    # OLD_LINE_BODY and ended with the old marker as a trailing
    # comment, so an exact-style revert is correct here.
    vanilla_line_exact = OLD_LINE_BODY.encode('utf-8') + eol
    for old_marker in OLD_MARKERS:
        pat = (re.escape(OLD_LINE_BODY.encode('utf-8'))
               + b'[^\r\n]*?' + re.escape(old_marker.encode('utf-8'))
               + b'[^\r\n]*?' + re.escape(eol))
        if re.search(pat, content):
            content = re.sub(pat, vanilla_line_exact, content, count=1)
            _log('reverted older v1 inject before re-applying v2',
                 level='INFO')

    # Flexible match of the (now-vanilla) elif line. Require EXACTLY
    # ONE match -- 0 means DarkSubs upstream changed beyond what we
    # recognise (leave it alone; auto_translate=ON still routes
    # through the main hook), >1 means an ambiguous file we refuse
    # to rewrite blind.
    matches = list(_ELIF_RE.finditer(content))
    if len(matches) == 0:
        _log('download_sub auto_translate elif not found -- '
             'DarkSubs upstream may have changed. auto_translate=ON '
             'still works via the main hook.', level='WARNING')
        return 'unmatched'
    if len(matches) > 1:
        _log('download_sub auto_translate elif matched {0} times -- '
             'refusing to rewrite ambiguously'.format(len(matches)),
             level='WARNING')
        return 'unmatched'

    m = matches[0]
    new_line = _build_new_line(m.group('indent'), m.group('addon'), eol)
    new_content = content[:m.start()] + new_line + content[m.end():]

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
    _log('rewrote download_sub elif (flexible match) so AI key + '
         'force-toggle triggers translation with auto_translate=OFF',
         level='INFO')
    return 'patched'
