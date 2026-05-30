# Self-healing patch of DarkSubs's engine.py so that EMBEDDED
# ("[LOC]") subtitle entries sink to the BOTTOM of their language
# group in the results dialog instead of floating to the top.
#
# The problem:
#   DarkSubs (All_Subs/autosub.py) injects an embedded-stream entry
#   into the results with a hard-coded sync percent of 101 and
#   site_id '[LOC]'. The list builder in engine.py sorts each
#   language group by descending sync percent (-x[5]), so 101 always
#   wins -- the embedded English line lands FIRST in the English
#   group. On this POV/streaming build the embedded track is almost
#   always identical to (or worse than) an external English sub, and
#   crucially DarkSubs's download_sub() short-circuits embedded picks
#   with setSubtitleStream() + 'EmbeddedSubSelected' BEFORE
#   machine_translate_subs runs -- so picking it never reaches our AI
#   hook and the user is stuck with untranslated English. Users keep
#   landing on it by reflex because it's at the top.
#
# The fix:
#   Inject ONE statement immediately after engine.py's
#   `english_subtitles = custom_sort(english_subtitles, ...)` line that
#   stable-re-sorts ONLY the English group so '[LOC]' entries fall to its
#   bottom. External English subs (OpenSubtitles, YIFY, ...) keep their
#   relative order and now sit above the embedded English line, so the
#   AI-translatable source is the natural first pick. The embedded entry
#   is still present -- just last in its group.
#
# CRITICAL -- why we scope to English only (not the combined list):
#   DarkSubs stamps site_id '[LOC]' on BOTH embedded-English AND
#   embedded-Hebrew entries. A Hebrew embedded track is the BEST pick
#   (native Hebrew, perfectly synced, zero translation) and MUST stay at
#   the very top. engine.py's concat (`hebrew + telegram_mt + english +
#   other`) already guarantees the whole Hebrew group outranks English,
#   and the embedded Hebrew entry's 101% floats it to the top OF that
#   group. If we re-sorted the COMBINED list by '[LOC]' we'd sink the
#   Hebrew embedded entry below English -- the opposite of what we want.
#   Re-sorting english_subtitles alone leaves Hebrew completely untouched.
#
# Self-healing + safety:
#   * Idempotent via marker; re-applies every Kodi startup (DarkSubs
#     updates wipe our line).
#   * Regex match of the english_subtitles sort line is whitespace-
#     tolerant. EXACTLY ONE match required or we bail untouched.
#   * .pyc cache invalidated so DarkSubs's reuselanguageinvoker
#     interpreter recompiles from the new source (same pitfall the
#     other DarkSubs patchers handle).
#   * No-op (returns a status, writes nothing) when DarkSubs isn't
#     installed or its engine.py has been refactored beyond what we
#     recognise -- the dialog just keeps DarkSubs's native ordering.

import os
import re

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import kodi_utils


DARKSUBS_ADDON_ID = 'service.subtitles.All_Subs'
ENGINE_REL_PATH = 'resources/modules/engine.py'

MARKER = '# AI_EMBEDDED_DEMOTE_v1'

# The site_id DarkSubs stamps on embedded-stream entries
# (All_Subs/autosub.py: 'site_id':'[LOC]'). Index 9 in the result
# tuple the list builder assembles. We demote on this exact token so
# we never touch real online providers.
LOC_SITE_ID = '[LOC]'

# We anchor on the per-group sort of the ENGLISH list specifically:
#   english_subtitles = custom_sort(english_subtitles, site_id_order)
# and inject our re-sort right AFTER it. This is deliberately scoped to
# the English group ONLY -- we must NOT touch the Hebrew group.
#
# Why Hebrew must be left alone: DarkSubs stamps site_id '[LOC]' on BOTH
# the embedded-English AND the embedded-Hebrew entries (All_Subs/
# autosub.py). A Hebrew embedded track is the BEST possible pick -- native
# Hebrew, perfectly synced, no translation needed -- and its hard-coded
# 101% sync correctly floats it to the top of the Hebrew group, which the
# concat (`hebrew + telegram_mt + english + other`) already puts first in
# the whole list. Re-sorting the COMBINED list by '[LOC]' would have sunk
# the Hebrew embedded entry below the English ones -- exactly wrong. By
# only re-sorting english_subtitles we leave Hebrew (embedded or not)
# untouched. '[LOC]' only ever appears in the Hebrew or English groups
# (autosub builds embedded entries for 'heb'/'eng' only), so the English
# group is the only place we need to act.
#
# Whitespace/indent tolerant. Require EXACTLY ONE match or we bail.
_ENGLISH_SORT_RE = re.compile(
    rb'^(?P<indent>[ \t]*)english_subtitles[ \t]*=[ \t]*'
    rb'custom_sort[ \t]*\([^\r\n]*\)[ \t]*(?P<eol>\r?\n)',
    re.MULTILINE,
)


def _log(msg, level='INFO'):
    try:
        kodi_utils.log('darksubs_embedded_demote_patcher: ' + msg,
                       level=level)
    except Exception:
        pass


def _engine_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + DARKSUBS_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, ENGINE_REL_PATH)
    return p if os.path.isfile(p) else ''


def _invalidate_pyc_cache(py_path):
    """Wipe stale engine.cpython-*.pyc so DarkSubs re-compiles on next
    import (reuselanguageinvoker pitfall -- see darksubs_patcher)."""
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


def _build_inject_line(indent, eol):
    """One self-contained statement that stable-sorts sorted_subtitles
    so [LOC] (embedded) entries sink to the bottom. site_id is the
    last element of each result tuple. Guarded with a try/except via a
    list comprehension fallback isn't needed -- sorted() with a tuple
    index can only fail if the tuples are malformed, which would have
    crashed DarkSubs's own custom_sort already. Kept as a single line
    so the injection stays trivially reversible by an upstream update.
    """
    return (
        indent
        + b'english_subtitles = sorted(english_subtitles, '
        b'key=lambda _s: 1 if (len(_s) > 9 and _s[9] == '
        + repr(LOC_SITE_ID).encode('utf-8')
        + b') else 0)  ' + MARKER.encode('utf-8') + eol
    )


def ensure_patched():
    """Inject the embedded-demote re-sort right after engine.py's
    `english_subtitles = custom_sort(...)` line, scoped to the English
    group only so the Hebrew group (incl. a Hebrew embedded track, which
    SHOULD stay first) is never touched.

    Returns one of:
      'patched'          -- injected the re-sort line
      'already_patched'  -- marker present, no change
      'no_engine'        -- DarkSubs not installed / path unreachable
      'unmatched'        -- english_subtitles sort not found or ambiguous
      'read_failed' / 'write_failed'
    """
    path = _engine_path()
    if not path:
        return 'no_engine'
    try:
        with open(path, 'rb') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER.encode('utf-8') in content:
        return 'already_patched'

    matches = list(_ENGLISH_SORT_RE.finditer(content))
    if len(matches) == 0:
        _log('english_subtitles custom_sort line not found -- DarkSubs '
             'upstream may have changed. Leaving native ordering.',
             level='WARNING')
        return 'unmatched'
    if len(matches) > 1:
        _log('english_subtitles custom_sort matched {0} times -- '
             'refusing to inject ambiguously'.format(len(matches)),
             level='WARNING')
        return 'unmatched'

    m = matches[0]
    indent = m.group('indent')
    eol = m.group('eol')
    inject = _build_inject_line(indent, eol)
    # Insert immediately AFTER the matched concat line so we re-sort
    # the list it just built.
    insert_at = m.end()
    new_content = content[:insert_at] + inject + content[insert_at:]

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
    _log('injected embedded-demote re-sort so [LOC] entries sink to '
         'the bottom of their language group', level='INFO')
    return 'patched'
