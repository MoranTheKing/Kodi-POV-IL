# Insert the embedded ENGLISH subtitle at the BOTTOM of the list, not
# right after the Hebrew subs.
#
# This is the REAL root cause of "תרגום מובנה אנגלית appears above the
# real English subs". In DarkSubs (service.subtitles.All_Subs)
# autosub.py, add_embedded_sub_if_exists() computes the insert index for
# an embedded English track as "right after the last Hebrew subtitle":
#
#     index = 0
#     if embedded_language=='eng':
#         for i, sub in enumerate(f_result):
#             if sub[0] == 'Hebrew':
#                 index = i + 1  # Insert after the last Hebrew subtitle
#     f_result.insert(index, (... '[LOC]' embedded entry ...))
#
# So the embedded English lands BETWEEN the Hebrew group and the real
# English subs -> it shows at the top of English. This happens AFTER
# engine.sort_subtitles ran, which is exactly why our engine-level and
# picker-level demotes didn't move it: the entry is positioned here, by
# index, at insert time.
#
# Fix: for embedded_language=='eng', set the insert index to len(f_result)
# (append at the very end) so the embedded English is always LAST. The
# Hebrew-embedded branch (embedded_language=='heb') is left untouched --
# it keeps index 0 and stays on top, which is what we want.
#
# We rewrite ONLY the English index calculation:
#   the `for i, sub in enumerate(f_result): if sub[0]=='Hebrew': index=i+1`
# loop becomes `index = len(f_result)`.
#
# Marker-gated, idempotent, atomic write, .pyc dropped, CRLF-safe.
# No-op if DarkSubs absent or the block was refactored.

import os
import re

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import kodi_utils


DARKSUBS_ADDON_ID = 'service.subtitles.All_Subs'
AUTOSUB_REL_PATH = 'autosub.py'

MARKER = '# AI_SUBS_EMBED_ENG_LAST_v2'

# Match the UNIQUE index-calculation block in add_embedded_sub_if_exists,
# from `index = 0` through the `if embedded_language=='eng':` body, up to
# (not including) the `f_result.insert(` line. The body may be EITHER the
# original Hebrew loop OR a prior v1 patch (`index = len(f_result)`), so
# we capture any body up to the insert -- this lets v2 re-patch a device
# that already has v1.
#
# v2 places the embedded English at the END OF THE ENGLISH GROUP (right
# after the last 'English' entry), not at the very end of the list, so it
# no longer sinks below other languages. f_result at insert time is
# ordered hebrew + telegram_mt + english + other (engine.sort_subtitles),
# so "after the last English row" == bottom of the English block, above
# 'other languages'. Falls back to end-of-list if there's no English row.
#
# We require BOTH `index = 0` AND `if embedded_language=='eng'` so we
# never touch the earlier `elif embedded_language=='eng':` settings block.
# CRLF-tolerant; reuses captured indents (never mixes tabs/spaces).
_BLOCK_RE = re.compile(
    rb"(?P<indent>[ \t]*)index[ \t]*=[ \t]*0[ \t]*\r?\n"
    # allow our own prior marker/comment lines between `index = 0` and the
    # `if` (a v1 patch left a '# AI_SUBS_EMBED_ENG_LAST_v1' line here),
    # so v2 can re-patch a device that already has v1 applied.
    rb"(?P<mid>(?:[ \t]*#[^\r\n]*\r?\n)*)"
    rb"(?P<body>[ \t]*if[ \t]+embedded_language[ \t]*==[ \t]*"
    rb"['\"]eng['\"].*?)"
    rb"(?P<insert_indent>[ \t]*)f_result\.insert\(",
    re.DOTALL,
)


def _log(msg, level='INFO'):
    try:
        kodi_utils.log('darksubs_embedded_insert_patcher: ' + msg,
                       level=level)
    except Exception:
        pass


def _autosub_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + DARKSUBS_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, AUTOSUB_REL_PATH)
    return p if os.path.isfile(p) else ''


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


def ensure_patched():
    """Returns 'patched' | 'already_patched' | 'no_darksubs' | 'no_file'
    | 'unmatched' | 'read_failed' | 'write_failed'."""
    path = _autosub_path()
    if not path:
        return 'no_darksubs'
    try:
        with open(path, 'rb') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER.encode('utf-8') in content:
        return 'already_patched'

    m = _BLOCK_RE.search(content)
    if not m:
        _log('embedded-eng index block not found in autosub.py -- '
             'DarkSubs may have refactored. Leaving as-is.',
             level='WARNING')
        return 'unmatched'

    indent = m.group('indent')              # indent of `index = 0`
    insert_indent = m.group('insert_indent')
    eol = b'\r\n' if b'\r\n' in content else b'\n'
    # Derive an inner indent from the file's own style: one extra level
    # past `indent`. Detect tabs vs spaces from `indent` itself; default
    # to 4 spaces (the file uses spaces). NEVER mix.
    if indent and b'\t' in indent:
        inner = indent + b'\t'
        inner2 = indent + b'\t\t'
    else:
        inner = indent + b'    '
        inner2 = indent + b'        '
    # Replacement (anchored from `index = 0`): for embedded English, set
    # index to the END OF THE ENGLISH GROUP -- right after the last row
    # whose language label (sub[0]) is 'English' -- so it sits at the
    # bottom of the English subs but ABOVE other languages. Default to
    # end-of-list only if no English row exists. Hebrew-embedded path is
    # untouched (handled elsewhere). Re-emit the matched `f_result.insert(`.
    body = (
        indent + b'index = 0' + eol
        + indent + MARKER.encode('utf-8') + eol
        + indent + b"if embedded_language=='eng':" + eol
        + inner + b'index = len(f_result)  # default: end of list' + eol
        + inner + b'for _i, _sub in enumerate(f_result):' + eol
        + inner2 + b"if _sub[0] == 'English':  # bottom of English group"
        + eol
        + inner2 + b'    index = _i + 1' + eol
        + insert_indent + b'f_result.insert('
    )
    new_content = content[:m.start()] + body + content[m.end():]

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
    _log('embedded English now inserted at the bottom of the list '
         '(was after the Hebrew group)', level='INFO')
    return 'patched'
