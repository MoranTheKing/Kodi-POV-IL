# PHASE 1 (capture only) of "remember the source the user picked".
#
# Injects a tiny, STABLE block into plugin.video.pov's sources.py right before
# it yields the resolved link of the picked source. The block is intentionally
# minimal: it checks our `remember_source` setting (OFF by default), logs that
# the hook fired, and -- only when on -- imports our source_capture module (by
# path, since POV is a separate add-on) and hands it the source. All real logic
# + logging lives in source_capture.py, so it can be iterated without
# re-patching POV.
#
# ANCHOR: `yield link` is unique in POV's sources.py. We match it with a
# tolerant regex (optional inline `if ...:` prefix, any indent) so it works on
# every POV variant. Any previously-injected version of our block is reverted
# first, so upgrades don't stack.
#
# SAFETY: the patched file is compile()-checked BEFORE writing; if anything is
# off we skip and leave POV untouched -- it can never break playback.

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
SOURCES_REL_PATH = 'resources/lib/modules/sources.py'
MARKER = 'AI_SUBS_REMEMBER_SOURCE_v3'

# The unique yield site, with optional inline `if ...:` prefix, any indent.
_YIELD_RE = re.compile(
    r'^(?P<indent>[ \t]*)'
    r'(?P<iff>if (?:not link is None|link is not None):[ \t]*)?'
    r'yield link[ \t]*$',
    re.MULTILINE,
)

# Any previously-injected block: from our marker comment through the next
# `yield link` line. Used to revert before re-applying (so upgrades don't stack).
_REVERT_RE = re.compile(
    r'[ \t]*#[ \t]*AI_SUBS_REMEMBER_SOURCE_v\d+.*?\n(?P<yi>[ \t]*)yield link[ \t]*$',
    re.DOTALL | re.MULTILINE,
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_remember_source_patcher: ' + msg, level=level)
    except Exception:
        pass


def _sources_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, SOURCES_REL_PATH)
    return p if os.path.isfile(p) else ''


def _hook_lines(body_indent, eol):
    raw = [
        '# ' + MARKER,
        'try:',
        '\timport xbmc as _rs_x, xbmcaddon as _rs_a',
        "\t_rs_on = (_rs_a.Addon('service.subtitles.kodipovilai').getSetting('remember_source') or '')",
        "\t_rs_x.log('[remember_source] yield hook; setting=' + repr(_rs_on), 1)",
        "\tif _rs_on.strip().lower() == 'true':",
        '\t\timport sys as _rs_s, xbmcvfs as _rs_v',
        "\t\t_rs_p = _rs_v.translatePath('special://home/addons/service.subtitles.kodipovilai/resources/lib')",
        '\t\tif _rs_p not in _rs_s.path: _rs_s.path.insert(0, _rs_p)',
        '\t\timport source_capture as _rs_c',
        '\t\t_rs_c.capture(self, item)',
        'except Exception: pass',
    ]
    return ''.join(body_indent + ln + eol for ln in raw)


def ensure_patched():
    path = _sources_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    eol = '\r\n' if '\r\n' in content[:4096] else '\n'

    already = MARKER in content

    # Revert any previously-injected version (v1/v2/v3...) back to a plain
    # `yield link`, so we can (re)apply the current version cleanly.
    def _revert(m):
        return m.group('yi') + 'yield link'
    reverted = _REVERT_RE.sub(_revert, content)
    if reverted != content:
        content = reverted
        # If the only marker present was the current one and revert changed
        # nothing else, we'll re-apply identical content (harmless).

    m = _YIELD_RE.search(content)
    if not m:
        _log('no `yield link` site found -- skipping', level='WARNING')
        return 'unmatched'

    indent = m.group('indent')
    if m.group('iff'):
        body = indent + '\t'
        replacement = (indent + 'if not link is None:' + eol
                       + _hook_lines(body, eol)
                       + body + 'yield link')
    else:
        replacement = _hook_lines(indent, eol) + indent + 'yield link'

    new_content = content[:m.start()] + replacement + content[m.end():]

    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'

    # If the file already had exactly this version and revert produced the same
    # bytes, avoid a redundant write.
    try:
        with open(path, 'r', encoding='utf-8') as f:
            if f.read() == new_content:
                return 'unchanged'
    except OSError:
        pass

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
        _log('injected remember-source capture hook (v3)', level='INFO')
        return 'unchanged' if already else 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
