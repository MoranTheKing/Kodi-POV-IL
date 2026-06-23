# "Hebrew-subtitle match %" in POV's source-results window.
#
# Patches plugin.video.pov's windows/sources.py::make_items so each source row
# shows, before you pick it, how well an available Hebrew subtitle matches that
# source's release (see he_sub_match). Two gated edits:
#   1. SETUP: once per window, load the available Hebrew sub release names for
#      the media (community pool), via he_sub_match (self-contained import).
#   2. PER ROW: prepend a small coloured '<NN>% עברית | ' to tikiskins.size_label
#      -- that property is rendered first in the info line of EVERY layout
#      variant, so the badge shows on every skin with no skin-XML changes.
#
# The whole file is compile()-checked before writing (so it can never break
# POV / the source window), prior versions are reverted then re-applied, and
# POV already wraps each row build in try/except as a backstop.

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
SOURCES_REL_PATH = 'resources/lib/windows/sources.py'
MARKER = 'AI_SUBS_MATCH_v3'

# The for-loop that builds each source row (insert SETUP just before it).
_LOOP_RE = re.compile(
    r'^(?P<indent>[ \t]*)for count, item in enumerate\(self\.results, 1\):[ \t]*$',
    re.MULTILINE,
)
# The size_label property set (wrap it to prepend the match prefix).
_SIZE_RE = re.compile(
    r"^(?P<indent>[ \t]*)set_property\('tikiskins\.size_label', "
    r"get\('size_label', 'N/A'\)\)[ \t]*$",
    re.MULTILINE,
)
# Revert: SETUP block (marker comment .. its `except` fallback line).
_REVERT_SETUP_RE = re.compile(
    r"[ \t]*#[ \t]*AI_SUBS_MATCH_v\d+.*?_sm_m = None; _sm_names = \[\]"
    r"(?:; _sm_emb = \[\])?[ \t]*\r?\n",
    re.DOTALL,
)
# Revert: wrapped size_label line -> plain.
_REVERT_SIZE_RE = re.compile(
    r"^(?P<indent>[ \t]*)set_property\('tikiskins\.size_label', "
    r"\(_sm_m\.label_prefix.*?\) \+ get\('size_label', 'N/A'\)\)[ \t]*$",
    re.MULTILINE,
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_subtitle_match_patcher: ' + msg, level=level)
    except Exception:
        pass


def _sources_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, SOURCES_REL_PATH.replace('/', os.sep))
    return p if os.path.isfile(p) else ''


def _setup_lines(indent, eol):
    raw = [
        '# ' + MARKER,
        'try:',
        '\timport sys as _sm_s, xbmcvfs as _sm_v',
        "\t_sm_p = _sm_v.translatePath('special://home/addons/service.subtitles.kodipovilai/resources/lib')",
        '\tif _sm_p not in _sm_s.path: _sm_s.path.insert(0, _sm_p)',
        '\timport he_sub_match as _sm_m',
        '\t_sm_names = _sm_m.release_names(self.meta)',
        '\t_sm_emb = _sm_m.embedded_names(self.meta)',
        'except Exception:',
        '\t_sm_m = None; _sm_names = []; _sm_emb = []',
    ]
    return ''.join(indent + ln + eol for ln in raw)


def ensure_patched():
    path = _sources_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            original = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    eol = '\r\n' if '\r\n' in original[:4096] else '\n'
    already = MARKER in original

    # Revert any prior version so we re-apply cleanly (idempotent).
    content = _REVERT_SETUP_RE.sub('', original)
    content = _REVERT_SIZE_RE.sub(
        lambda m: m.group('indent')
        + "set_property('tikiskins.size_label', get('size_label', 'N/A'))",
        content)

    # 1) SETUP block right before the row-building loop.
    m = _LOOP_RE.search(content)
    if not m:
        _log('row loop not found -- skipping', level='WARNING')
        return 'unmatched'
    indent = m.group('indent')
    content = content[:m.start()] + _setup_lines(indent, eol) + content[m.start():]

    # 2) wrap the size_label set to prepend the match prefix.
    s = _SIZE_RE.search(content)
    if not s:
        _log('size_label set not found -- skipping', level='WARNING')
        return 'unmatched'
    si = s.group('indent')
    wrapped = (si + "set_property('tikiskins.size_label', "
               "(_sm_m.label_prefix((get('URLName') or get('name') or ''), "
               "_sm_names, _sm_emb) if _sm_m else '') + get('size_label', 'N/A'))")
    content = content[:s.start()] + wrapped + content[s.end():]

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
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        os.replace(tmp, path)
        _log('injected Hebrew-subtitle match into source results', level='INFO')
        return 'unchanged' if already else 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
