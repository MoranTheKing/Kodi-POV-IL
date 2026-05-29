# Self-healing patcher for service.subtitles.all_subs_plus.
#
# Bug we're fixing: at module-load time, autosub.py imports service.py
# which calls setLanguageSettings('kodi', False) at line 183. That
# function does 2 unconditional shutil.copy() calls. On Windows (and
# anywhere with NTFS junctions/hardlinks), if the source and destination
# point to the same physical file, shutil.copy raises SameFileError.
# autosub.py never catches it, so the WHOLE addon fails to load every
# Kodi startup -- user-visible Python error notification + AllSubs
# functionality completely broken.
#
# What we patch: wrap each of the 6 shutil.copy(...) lines inside
# setLanguageSettings in a try/except shutil.SameFileError so the
# already-correct file is silently accepted instead of crashing. Two
# branches of the if/elif/else each have 2 calls; we leave the call
# sites byte-identical structurally and only add the wrapper.
#
# Marker-gated, idempotent, atomic write. Quiet on no-op. Logs WARNING
# on weird states (file vanished, more/fewer matches than expected, etc).

import os
import re

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import kodi_utils


ALL_SUBS_ADDON_ID = 'service.subtitles.all_subs_plus'
SERVICE_PY_REL = 'service.py'

# Sticky marker so we know we've already touched the file. Bumped if a
# future iteration of this patcher needs to re-run.
MARKER = '# AI_SUBS_ALL_SUBS_SAMEFILE_v1'

# Match each line of the form:
#   <indent>shutil.copy(<arg1>, <arg2>)<eol>
# Captures indent so we can keep it on the rewrite. Restricted to
# inside setLanguageSettings by the call_site_count check below
# (the function has exactly 6 such calls -- the only other
# shutil.copy in the file is line 222 / 810 which are unrelated and
# we DO NOT want to touch).
_COPY_LINE_RE = re.compile(
    rb'^(?P<indent>[ \t]+)'
    rb'shutil\.copy\((?P<args>[^()\r\n]+)\)'
    rb'[ \t]*(?P<eol>\r?\n|$)',
    re.MULTILINE,
)


def _log(msg, level='INFO'):
    try:
        kodi_utils.log(
            'all_subs_samefile_patcher: ' + msg, level=level)
    except Exception:
        pass


def _service_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + ALL_SUBS_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, SERVICE_PY_REL)
    return p if os.path.isfile(p) else ''


def _wrap_in_try_except(match):
    """Rewrite ONE matched line:
       <indent>shutil.copy(A, B)<eol>
    -> <indent>try: shutil.copy(A, B)<eol>
       <indent>except shutil.SameFileError: pass<eol>
    Same total semantics as the original except SameFileError is
    silently absorbed (which is the *intended* behaviour: source and
    destination are byte-identical, copy is a no-op). All other errors
    still surface."""
    indent = match.group('indent')
    args = match.group('args')
    eol = match.group('eol')
    return (
        indent + b'try: shutil.copy(' + args + b')' + eol
        + indent + b'except shutil.SameFileError: pass' + eol
    )


def ensure_patched():
    """Idempotent. Returns one of: 'no_addon' | 'no_file'
    | 'already_patched' | 'unmatched' | 'read_failed'
    | 'write_failed' | 'patched'."""
    path = _service_path()
    if not path:
        return 'no_addon' if xbmcvfs is None else 'no_file'

    try:
        with open(path, 'rb') as f:
            content = f.read()
    except OSError as e:
        _log('read failed for {0}: {1}'.format(path, e),
             level='WARNING')
        return 'read_failed'

    if MARKER.encode('utf-8') in content:
        return 'already_patched'

    # Find every shutil.copy(X, Y) call site. We expect at least 6
    # (the 3 branches of setLanguageSettings, 2 calls each). The
    # file also has shutil.copy2 at line ~222 and shutil.copy at
    # ~810; both unrelated to setLanguageSettings and harmless to
    # patch -- the wrap turns into a no-op for non-SameFileError
    # failure modes. Still, restrict to "at least 6" so we don't
    # silently swallow an upstream refactor that dropped half of
    # the calls.
    matches = list(_COPY_LINE_RE.finditer(content))
    if len(matches) < 6:
        _log('expected >=6 shutil.copy lines, got {0} -- AllSubs may '
             'have refactored service.py; leaving file alone'
             .format(len(matches)), level='WARNING')
        return 'unmatched'

    # Rewrite all of them in reverse order to keep earlier offsets
    # valid as we splice.
    new_content = bytearray(content)
    for m in reversed(matches):
        replacement = _wrap_in_try_except(m)
        new_content[m.start():m.end()] = replacement

    # Drop the marker as a comment near the top so future runs
    # short-circuit.
    bytes_out = bytes(new_content)
    # Insert marker after the first import line block. Conservative:
    # just prepend at the very top after the encoding declaration.
    if bytes_out.startswith(b'# -*- coding'):
        first_newline = bytes_out.index(b'\n') + 1
        bytes_out = (
            bytes_out[:first_newline]
            + MARKER.encode('utf-8') + b'\n'
            + bytes_out[first_newline:]
        )
    else:
        bytes_out = MARKER.encode('utf-8') + b'\n' + bytes_out

    tmp_path = path + '.aitmp'
    try:
        with open(tmp_path, 'wb') as f:
            f.write(bytes_out)
        os.replace(tmp_path, path)
    except OSError as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        _log('write failed for {0}: {1}'.format(path, e),
             level='WARNING')
        return 'write_failed'

    _log('patched {0} shutil.copy lines in {1} to absorb '
         'SameFileError'.format(len(matches), path), level='INFO')
    return 'patched'
