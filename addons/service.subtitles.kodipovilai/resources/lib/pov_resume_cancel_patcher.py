# Fix POV's "stuck on BACK at the resume prompt" bug (all skins).
#
# When you pick a source for a title you're mid-watching, POV opens a modal
# resolving window (windows.sources.ProgressMedia) and then, inside
# POVPlayer.run(), shows the Resume/Restart prompt. If you press BACK instead of
# one of the two buttons, getResumeStatus() returns 'cancel' and run() does
#     if bookmark == 'cancel': return
# -- it returns IMMEDIATELY, WITHOUT the cleanup the success path runs a few
# lines later (progress_media() + close_all_dialog()). So the modal resolving
# window is never closed -> the UI is stuck and only a full Kodi restart clears
# it. This makes the cancel path close the dialog(s) before returning.
#
# Patches plugin.video.pov/resources/lib/modules/player.py. Marker-gated,
# compile()-checked before writing, revertible, EOL-preserving. player.py
# already imports kodi_utils, so close_all_dialog() is in scope.

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
PLAYER_REL_PATH = 'resources/lib/modules/player.py'
MARKER = 'AI_POV_RESUME_CANCEL_v1'

# The original single-line cancel-return (any indentation).
_TARGET_RE = re.compile(
    r"^(?P<indent>[ \t]*)if bookmark == 'cancel': return[ \t]*$",
    re.MULTILINE)
# Revert our patched line back to the original (so re-apply is idempotent).
_REVERT_RE = re.compile(
    r"^(?P<indent>[ \t]*)if bookmark == 'cancel':(?:(?!\r?\n).)*?"
    + MARKER + r"[ \t]*$",
    re.MULTILINE)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_resume_cancel_patcher: ' + msg, level=level)
    except Exception:
        pass


def _player_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, PLAYER_REL_PATH.replace('/', os.sep))
    return p if os.path.isfile(p) else ''


def _clear_pyc(path):
    try:
        cache = os.path.join(os.path.dirname(path), '__pycache__')
        if os.path.isdir(cache):
            for fn in os.listdir(cache):
                if fn.startswith('player.') and fn.endswith('.pyc'):
                    try:
                        os.remove(os.path.join(cache, fn))
                    except OSError:
                        pass
    except Exception:
        pass


def ensure_patched():
    """Returns 'no_file' | 'read_failed' | 'unmatched' | 'already_patched'
    | 'compile_failed' | 'write_failed' | 'patched'."""
    path = _player_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            original = f.read()
    except Exception as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    eol = '\r\n' if '\r\n' in original[:4096] else '\n'

    # Revert any prior version of our line so we re-apply cleanly (idempotent).
    content = _REVERT_RE.sub(
        lambda m: m.group('indent') + "if bookmark == 'cancel': return",
        original)

    m = _TARGET_RE.search(content)
    if not m:
        # Nothing to patch: either the marker's already there intact, or POV
        # changed this line. Report accordingly without touching the file.
        return 'already_patched' if MARKER in content else 'unmatched'

    indent = m.group('indent')
    # All three statements run under the `if` (single logical line). close first
    # so the modal window is guaranteed gone even if the callback raises.
    new_line = (
        indent + "if bookmark == 'cancel': kodi_utils.close_all_dialog(); "
        "(progress_media() if callable(progress_media) else None); return  # "
        + MARKER)
    content = content[:m.start()] + new_line + content[m.end():]

    if content == original:
        return 'already_patched'

    # SAFETY: never write a file that doesn't compile.
    try:
        compile(content, path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'

    try:
        tmp = path + '.aitmp'
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        os.replace(tmp, path)
    except OSError as e:
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'

    _clear_pyc(path)
    _log('patched player.py: resume-prompt BACK now closes the dialog', 'INFO')
    return 'patched'
