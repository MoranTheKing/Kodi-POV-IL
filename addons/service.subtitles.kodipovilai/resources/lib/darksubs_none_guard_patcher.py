# Best-effort hotfix for existing DarkSubs AI hook installs.
#
# Older hook versions assumed DarkSubs always passes real file paths to
# machine_translate_subs(input_file, output_file). In the wild DarkSubs can
# call it with input_file=None while resolving a selected English subtitle.
# That made the hook crash on input_file.encode('utf-8') before our addon even
# received the request. This tiny patch adds a guard to the already-injected
# hook without needing to rewrite the entire hook body.

import os
import re

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import kodi_utils

DARKSUBS_ADDON_ID = 'service.subtitles.All_Subs'
ENGINE_REL_PATH = 'resources/modules/engine.py'
MARKER = '# AI_TRANSLATE_NONE_GUARD_v1'
HOOK_MARKERS = (
    '# AI_TRANSLATE_HOOK_v4',
    '# AI_TRANSLATE_HOOK_v5',
)


def _engine_path():
    if xbmcvfs is None:
        return None
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/{0}/{1}'.format(
                DARKSUBS_ADDON_ID, ENGINE_REL_PATH))
    except Exception:
        return None


def _invalidate_pyc_cache(py_path):
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


def _build_guard(eol):
    lines = [
        '            ' + MARKER,
        "            if input_file is None or not _aix_os.path.isfile(str(input_file)):",
        "                _aix_x.log('[AI hook] missing input_file; returning empty subtitle instead of crashing', level=3)",
        "                _aix_g.Window(10000).setProperty('ai_subs.hook_last_outcome', 'invalid_input')",
        "                try:",
        "                    _aix_ad.setSetting('_darksubs_hook_last_outcome', 'invalid_input')",
        "                except Exception:",
        "                    pass",
        "                try:",
        "                    _aix_x.executebuiltin('Notification(Kodi POV IL - AI Subtitles,Subtitle file was not ready -- choose another subtitle if needed,8000)')",
        "                except Exception:",
        "                    pass",
        "                return ''",
        "            if output_file is None:",
        "                try:",
        "                    import xbmcvfs as _aix_vfs",
        "                    output_file = _aix_os.path.join(_aix_vfs.translatePath('special://temp/'), 'kodipovilai_' + _aix_now + '.srt')",
        "                except Exception:",
        "                    output_file = _aix_os.path.join(_aix_os.path.dirname(str(input_file)) or '.', 'kodipovilai_' + _aix_now + '.srt')",
    ]
    return eol.join(lines) + eol


def ensure_patched():
    engine = _engine_path()
    if not engine or not os.path.isfile(engine):
        return 'no_engine'

    try:
        with open(engine, 'rb') as f:
            raw = f.read()
        content = raw.decode('utf-8', errors='replace')
    except OSError as e:
        kodi_utils.log(
            'darksubs_none_guard: read failed for {0}: {1}'.format(
                engine, e), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'already_patched'
    if not any(marker in content for marker in HOOK_MARKERS):
        return 'no_hook'

    eol = '\r\n' if '\r\n' in content[:8192] else '\n'
    needle = eol.join((
        '        if _aix_key:',
        '            _aix_tried_ai = True',
    ))
    replacement = eol.join((
        '        if _aix_key:',
        _build_guard(eol).rstrip(eol),
        '            _aix_tried_ai = True',
    ))

    if needle not in content:
        # Fallback for spacing changes: insert immediately after the if line.
        pattern = re.compile(r'^(?P<indent>[ \t]*)if _aix_key:\s*$',
                             re.MULTILINE)
        match = pattern.search(content)
        if not match:
            return 'unmatched'
        insert_at = match.end()
        content = content[:insert_at] + eol + _build_guard(eol) + content[insert_at:]
    else:
        content = content.replace(needle, replacement, 1)

    tmp_path = engine + '.noneguardtmp'
    try:
        with open(tmp_path, 'wb') as f:
            f.write(content.encode('utf-8'))
        os.replace(tmp_path, engine)
    except OSError as e:
        kodi_utils.log(
            'darksubs_none_guard: write failed for {0}: {1}'.format(
                engine, e), level='WARNING')
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return 'write_failed'

    _invalidate_pyc_cache(engine)
    kodi_utils.log('darksubs_none_guard: installed None input guard',
                   level='INFO')
    return 'patched'
