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

MARKER = '# AI_SUBS_EMBED_ENG_LAST_v1'

# Match the UNIQUE index-calculation block in add_embedded_sub_if_exists,
# anchored on `index = 0` ... through the `if embedded_language=='eng':`
# Hebrew loop ... up to (not including) the `f_result.insert(` line:
#
#     index = 0
#     if embedded_language=='eng':
#         # Find the index where English subtitles should be inserted
#         for i, sub in enumerate(f_result):
#             if sub[0] == 'Hebrew':
#                 index = i + 1  # Insert after the last Hebrew subtitle
#     f_result.insert( ... )
#
# We require the `index = 0` start AND the `for ... enumerate(f_result)`
# inside, so it can't accidentally match the earlier
# `elif embedded_language=='eng':` settings block (which has no `index`).
# CRLF-tolerant; preserves the file's existing indentation style by
# reusing the captured indents (so we never mix tabs/spaces).
_BLOCK_RE = re.compile(
    rb"(?P<indent>[ \t]*)index[ \t]*=[ \t]*0[ \t]*\r?\n"
    rb"(?P<body>[ \t]*if[ \t]+embedded_language[ \t]*==[ \t]*"
    rb"['\"]eng['\"].*?for[ \t]+i,[ \t]*sub[ \t]+in[ \t]+"
    rb"enumerate\(f_result\).*?)"
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
    else:
        inner = indent + b'    '
    # Replacement (anchored from `index = 0`): set index unconditionally
    # for embedded English to the end of the list, dropping the
    # after-Hebrew loop entirely. Hebrew-embedded path is elsewhere and
    # untouched. Re-emit the `f_result.insert(` we matched up to.
    body = (
        indent + b'index = 0' + eol
        + indent + MARKER.encode('utf-8') + eol
        + indent + b"if embedded_language=='eng':" + eol
        + inner + b'index = len(f_result)  # embedded English LAST' + eol
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
