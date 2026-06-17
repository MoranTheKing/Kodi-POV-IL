# "Remember the source the user picked" -- patches plugin.video.pov's
# sources.py with TWO gated hooks (both no-ops unless our `remember_source`
# setting is on, both reverted-then-reapplied so versions don't stack, and the
# whole file is compile()-checked before writing so it can never break POV):
#
#   1. CAPTURE  -- right before POV yields the resolved link, record the chosen
#      source (name/hash/quality/provider) per media. (source_capture.capture)
#   2. AUTO-PICK -- at the top of display_results(), if the user already picked
#      a source for this media, play the same/similar one and skip the source
#      dialog. (source_capture.autopick) First watch -> no record -> dialog;
#      later watches -> auto-play.

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
CAP_MARKER = 'AI_SUBS_REMEMBER_SOURCE_v5'
PICK_MARKER = 'AI_SUBS_AUTOPICK_v5'

# Unique yield site (optional inline `if ...:` prefix, any indent).
_YIELD_RE = re.compile(
    r'^(?P<indent>[ \t]*)'
    r'(?P<iff>if (?:not link is None|link is not None):[ \t]*)?'
    r'yield link[ \t]*$',
    re.MULTILINE,
)
# display_results method definition (any indent).
_DISPLAY_RE = re.compile(
    r'^(?P<indent>[ \t]*)def display_results\(self, results\):[ \t]*$',
    re.MULTILINE,
)
# Revert: capture block (marker comment .. yield link) -> plain yield.
_REVERT_CAP_RE = re.compile(
    r'[ \t]*#[ \t]*AI_SUBS_REMEMBER_SOURCE_v\d+.*?\n(?P<yi>[ \t]*)yield link[ \t]*$',
    re.DOTALL | re.MULTILINE,
)
# Revert: autopick block (marker comment .. its closing `except Exception: pass`).
_REVERT_PICK_RE = re.compile(
    r'[ \t]*#[ \t]*AI_SUBS_AUTOPICK_v\d+.*?except Exception: pass[ \t]*\n',
    re.DOTALL,
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


def _capture_lines(body_indent, eol):
    raw = [
        '# ' + CAP_MARKER,
        'try:',
        '\timport xbmcaddon as _rs_a',
        "\tif (_rs_a.Addon('service.subtitles.kodipovilai').getSetting('remember_source') or '').strip().lower() == 'true':",
        '\t\timport sys as _rs_s, xbmcvfs as _rs_v',
        "\t\t_rs_p = _rs_v.translatePath('special://home/addons/service.subtitles.kodipovilai/resources/lib')",
        '\t\tif _rs_p not in _rs_s.path: _rs_s.path.insert(0, _rs_p)',
        '\t\timport source_capture as _rs_c',
        '\t\t_rs_c.capture(self, item)',
        'except Exception: pass',
    ]
    return ''.join(body_indent + ln + eol for ln in raw)


def _autopick_lines(body_indent, eol):
    raw = [
        '# ' + PICK_MARKER,
        'try:',
        '\timport xbmcaddon as _ap_a',
        "\tif (_ap_a.Addon('service.subtitles.kodipovilai').getSetting('remember_source') or '').strip().lower() == 'true':",
        '\t\timport sys as _ap_s, xbmcvfs as _ap_v',
        "\t\t_ap_p = _ap_v.translatePath('special://home/addons/service.subtitles.kodipovilai/resources/lib')",
        '\t\tif _ap_p not in _ap_s.path: _ap_s.path.insert(0, _ap_p)',
        '\t\timport source_capture as _ap_c',
        '\t\t_ap_pick = _ap_c.autopick(self, results)',
        '\t\tif _ap_pick is not None:',
        '\t\t\tself._kill_progress_dialog()',
        '\t\t\treturn self.play_file(results, _ap_pick)',
        'except Exception: pass',
    ]
    return ''.join(body_indent + ln + eol for ln in raw)


def ensure_patched():
    path = _sources_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            original = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    eol = '\r\n' if '\r\n' in original[:4096] else '\n'
    already = CAP_MARKER in original and PICK_MARKER in original

    # Revert any prior versions of either hook so we re-apply cleanly.
    content = _REVERT_CAP_RE.sub(lambda m: m.group('yi') + 'yield link', original)
    content = _REVERT_PICK_RE.sub('', content)

    # 1) capture hook at the yield site.
    m = _YIELD_RE.search(content)
    if not m:
        _log('yield site not found -- skipping', level='WARNING')
        return 'unmatched'
    indent = m.group('indent')
    if m.group('iff'):
        body = indent + '\t'
        cap = (indent + 'if not link is None:' + eol
               + _capture_lines(body, eol) + body + 'yield link')
    else:
        cap = _capture_lines(indent, eol) + indent + 'yield link'
    content = content[:m.start()] + cap + content[m.end():]

    # 2) autopick hook at the top of display_results().
    d = _DISPLAY_RE.search(content)
    if not d:
        _log('display_results not found -- skipping', level='WARNING')
        return 'unmatched'
    body = d.group('indent') + '\t'
    after = content[d.end():]
    if after.startswith(eol):
        # insert the block right after the def line's newline (idempotent: the
        # revert removes exactly the block, restoring the original).
        content = (content[:d.end()] + eol + _autopick_lines(body, eol)
                   + after[len(eol):])
    else:
        content = (content[:d.end()] + eol + _autopick_lines(body, eol) + after)

    # SAFETY: never write a file that doesn't compile.
    try:
        compile(content, path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'

    if content == original:
        return 'unchanged'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(content)
        os.replace(tmp, path)
        _log('injected capture + autopick hooks (v4)', level='INFO')
        return 'unchanged' if already else 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
