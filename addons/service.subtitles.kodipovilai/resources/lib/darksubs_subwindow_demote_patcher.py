# Sink the EMBEDDED ENGLISH ("תרגום מובנה אנגלית", site_id '[LOC]')
# subtitle to the bottom of DarkSubs's picker -- patched at the LAST
# possible point, the picker dialog itself, so it works regardless of how
# engine.sort_subtitles ordered things.
#
# Why the engine-level demote (darksubs_embedded_demote_patcher) wasn't
# enough on the user's device: the picker window
# (service.subtitles.All_Subs/resources/modules/sub_window.py) renders
# self.list_o in the exact order it receives, and the embedded English
# row still showed up ABOVE the real English subs. Rather than depend on
# engine.sort_subtitles' classification/order (which varies), we reorder
# right before the list is drawn -- guaranteed last word on order.
#
# CRITICAL correctness: sub_window keeps TWO parallel arrays indexed by
# display position -- self.list_o (what's shown) and self.full_list (the
# download payload used by click_list via self.full_list[list_index]).
# They MUST stay in lockstep, so we permute BOTH with the SAME stable
# sort. We sink an entry only when it is embedded ([LOC] at tuple index
# 9) AND its language label (index 0) is English (ASCII 'english'/'eng'
# or Hebrew 'אנגלית'); a genuine embedded HEBREW track is left on top.
#
# We inject one block immediately after `self.list.reset()` inside
# set_active_controls(). Marker-gated, idempotent, atomic write, .pyc
# dropped. No-op if DarkSubs absent or the anchor isn't found.

import os
import re

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import kodi_utils


DARKSUBS_ADDON_ID = 'service.subtitles.All_Subs'
SUB_WINDOW_REL_PATH = 'resources/modules/sub_window.py'

MARKER = '# AI_SUBS_SUBWINDOW_DEMOTE_v1'

# Anchor on `self.list.reset()` inside set_active_controls and inject our
# reorder right AFTER it. Whitespace/indent tolerant; the indent captured
# is reused for the injected lines so they sit at the same block level.
_RESET_RE = re.compile(
    rb'^(?P<indent>[ \t]+)self\.list\.reset\(\)[ \t]*(?P<eol>\r?\n)',
    re.MULTILINE,
)


def _log(msg, level='INFO'):
    try:
        kodi_utils.log('darksubs_subwindow_demote_patcher: ' + msg,
                       level=level)
    except Exception:
        pass


def _sub_window_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + DARKSUBS_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, SUB_WINDOW_REL_PATH)
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


def _build_inject(indent):
    """Lines (each ending in \\n) that stable-sink embedded-English in
    BOTH parallel arrays. Uses the captured `indent` for block level."""
    i = indent.decode('utf-8')
    lines = [
        MARKER,
        'try:',
        '\t_aix_pairs = list(zip(self.list_o, self.full_list))',
        '\tdef _aix_isengemb(_p):',
        '\t\t_t = _p[0]',
        ('\t\tif not (len(_t) > 9 and _t[9] == "[LOC]"): return 0'),
        '\t\t_lbl = str(_t[0]).lower()',
        ('\t\treturn 1 if ("english" in _lbl or "eng" in _lbl '
         'or "\\u05d0\\u05e0\\u05d2\\u05dc\\u05d9\\u05ea" in str(_t[0])) '
         'else 0'),
        '\t_aix_pairs = sorted(_aix_pairs, key=_aix_isengemb)',
        ('\tself.list_o = [_a for _a, _b in _aix_pairs]'),
        ('\tself.full_list = [_b for _a, _b in _aix_pairs]'),
        'except Exception:',
        '\tpass',
    ]
    return ''.join(i + ln + '\n' for ln in lines).encode('utf-8')


def ensure_patched():
    """Returns 'patched' | 'already_patched' | 'no_darksubs' | 'no_file'
    | 'unmatched' | 'read_failed' | 'write_failed'."""
    path = _sub_window_path()
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

    matches = list(_RESET_RE.finditer(content))
    if len(matches) == 0:
        _log('self.list.reset() not found in sub_window.py -- DarkSubs '
             'may have refactored. Leaving order as-is.', level='WARNING')
        return 'unmatched'
    if len(matches) > 1:
        _log('self.list.reset() matched {0} times -- refusing to inject '
             'ambiguously'.format(len(matches)), level='WARNING')
        return 'unmatched'

    m = matches[0]
    indent = m.group('indent')
    inject = _build_inject(indent)
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
    _log('injected embedded-English demote into sub_window picker '
         '(reorders list_o + full_list in lockstep)', level='INFO')
    return 'patched'
