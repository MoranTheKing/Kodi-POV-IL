# Fix "a source whose NAME says 1080p is shown with an SD badge" in POV's
# source-results window.
#
# Why it happens (stock POV, verified): in POV the quality badge is derived from
# a scraper-supplied `name_info` field (or the stripped URL), NOT from the
# release name shown on the row. When a provider gives a display name containing
# "1080p"/"2160p"/"720p" but a name_info/URL without a resolution token,
# get_release_quality returns 'SD', so the row shows the 1080p name with an SD
# badge. Toggling scraper settings can't change this -- it's how POV classifies.
#
# Fix: patch windows/sources.py::make_items so, at the TOP of each row, when the
# stored quality is SD/empty we re-run POV's OWN get_release_quality against the
# visible name (URLName/name) and upgrade item['quality'] only to a real
# resolution (4K/1080p/720p). This is upgrade-only -- it can never downgrade a
# row or invent a quality the name doesn't contain -- and every downstream
# reader in make_items (badge icon, colour, quality text) picks up item.
#
# Anchored on the same row-loop line the subtitle-match patcher already uses, so
# it is proven to exist in the installed POV. Idempotent (reverts its own marker
# first), marker-gated, and compile()-checked before writing so it can never
# break POV. POV also wraps each row build in try/except as a backstop.

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
MARKER = 'AI_SUBS_QUALITY_FIX_v1'

# The for-loop that builds each source row (insert our block as its first body
# statements). Same anchor the subtitle-match patcher relies on.
_LOOP_RE = re.compile(
    r'^(?P<indent>[ \t]*)for count, item in enumerate\(self\.results, 1\):[ \t]*$',
    re.MULTILINE,
)
# Revert: our injected block (marker comment .. its trailing `except` line).
_REVERT_RE = re.compile(
    r"[ \t]*#[ \t]*AI_SUBS_QUALITY_FIX_v\d+.*?except Exception: pass[ \t]*\r?\n",
    re.DOTALL,
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_source_quality_patcher: ' + msg, level=level)
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


def _block(body_indent, eol):
    # body_indent = the loop body's indent (loop indent + one tab). Inner lines
    # nest with additional tabs, matching POV's tab-indented sources.
    t = '\t'
    raw = [
        '# ' + MARKER,
        'try:',
        t + "if (item.get('quality') or 'SD').upper() == 'SD':",
        t + t + 'from modules.source_utils import get_release_quality as _aq_grq',
        t + t + "_aq_nm = item.get('URLName') or item.get('name') or ''",
        t + t + "_aq_q = _aq_grq(_aq_nm) if _aq_nm else ''",
        t + t + "if _aq_q in ('4K', '1080p', '720p'): item['quality'] = _aq_q",
        'except Exception: pass',
    ]
    return ''.join(body_indent + ln + eol for ln in raw)


def ensure_patched():
    """Returns 'no_file' | 'read_failed' | 'unmatched' | 'compile_failed'
    | 'write_failed' | 'unchanged' | 'patched'."""
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
    content = _REVERT_RE.sub('', original)

    m = _LOOP_RE.search(content)
    if not m:
        _log('row loop not found -- skipping', level='WARNING')
        return 'unmatched'
    body_indent = m.group('indent') + '\t'
    # Insert right after the for-line's line ending, as the first body stmts.
    nl = content.find('\n', m.end())
    if nl == -1:
        return 'unmatched'
    insert_at = nl + 1
    content = content[:insert_at] + _block(body_indent, eol) + content[insert_at:]

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
        _log('upgraded SD rows whose name reveals real resolution', level='INFO')
        return 'unchanged' if already else 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
