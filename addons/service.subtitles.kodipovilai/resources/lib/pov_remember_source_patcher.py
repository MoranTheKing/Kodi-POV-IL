# PHASE 1 (capture only) of "remember the source the user picked".
#
# Injects a small, GATED block into plugin.video.pov's
# sources.py::play_file()._process(), right before it yields the resolved link
# of the source the user picked. Records that source's identifying attributes
# (name/hash/quality/provider/debrid) + media ids, one JSON file per media,
# under our addon_data/source_memory/. A later phase reads those to auto-pick.
#
# ROBUST ANCHOR: `yield link` is unique in POV's sources.py, but the line
# around it varies between POV versions / other patchers:
#   * `if not link is None: yield link`     (newer POV)
#   * `if link is not None: yield link`     (older POV)
#   * a standalone `yield link` at deeper indent (after the source-name patcher
#     already expanded the line)
# We match the single `yield link` with a tolerant regex (optional inline
# `if ...:` prefix, any indentation) and inject the capture right before it.
#
# SAFETY:
#   * Gated at runtime by our `remember_source` setting (OFF by default).
#   * Idempotent (marker) and matches only the unique yield site.
#   * The result is compiled with compile() BEFORE writing -- a malformed
#     injection is skipped, so this can never break POV playback.

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
MARKER = 'AI_SUBS_REMEMBER_SOURCE_v2'

# The single yield site, with optional inline `if ...:` prefix and any indent.
_YIELD_RE = re.compile(
    r'^(?P<indent>[ \t]*)'
    r'(?P<iff>if (?:not link is None|link is not None):[ \t]*)?'
    r'yield link[ \t]*$',
    re.MULTILINE,
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
    """The gated capture block, each line prefixed with body_indent."""
    raw = [
        '# ' + MARKER,
        'try:',
        '\timport xbmcaddon as _rs_a, xbmcvfs as _rs_v, json as _rs_j, os as _rs_o',
        "\tif (_rs_a.Addon('service.subtitles.kodipovilai').getSetting('remember_source') or '').lower() == 'true':",
        "\t\t_rs_id = str(self.tmdb_id or self.meta.get('imdb_id') or '')",
        '\t\tif _rs_id:',
        "\t\t\t_rs_key = '%s_%s_s%s_e%s' % (self.media_type, _rs_id, self.season or 0, self.episode or 0)",
        "\t\t\t_rs_rec = {'name': item.get('name', ''), 'hash': item.get('hash', ''), 'quality': item.get('quality', ''), 'provider': item.get('scrape_provider') or item.get('provider', ''), 'debrid': item.get('debrid', ''), 'release_title': item.get('release_title', '')}",
        "\t\t\t_rs_dir = _rs_v.translatePath('special://profile/addon_data/service.subtitles.kodipovilai/source_memory/')",
        '\t\t\tif not _rs_o.path.isdir(_rs_dir): _rs_o.makedirs(_rs_dir)',
        "\t\t\t_rs_tmp = _rs_o.path.join(_rs_dir, _rs_key + '.json.tmp')",
        "\t\t\twith open(_rs_tmp, 'w', encoding='utf-8') as _rs_f: _rs_f.write(_rs_j.dumps(_rs_rec))",
        "\t\t\t_rs_o.replace(_rs_tmp, _rs_o.path.join(_rs_dir, _rs_key + '.json'))",
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
    if MARKER in content:
        return 'unchanged'
    eol = '\r\n' if '\r\n' in content[:4096] else '\n'

    m = _YIELD_RE.search(content)
    if not m:
        _log('no `yield link` site found -- skipping', level='WARNING')
        return 'unmatched'

    indent = m.group('indent')
    if m.group('iff'):
        # Inline `if ...: yield link` -> expand; capture + yield in the body.
        body = indent + '\t'
        replacement = (indent + 'if not link is None:' + eol
                       + _capture_lines(body, eol)
                       + body + 'yield link')
    else:
        # Standalone `yield link` (already inside an if/block) -> inject the
        # capture right before it at the same indent.
        replacement = _capture_lines(indent, eol) + indent + 'yield link'

    new_content = content[:m.start()] + replacement + content[m.end():]

    # SAFETY: never write a file that doesn't compile.
    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
        _log('injected remember-source capture before yield link', level='INFO')
        return 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
