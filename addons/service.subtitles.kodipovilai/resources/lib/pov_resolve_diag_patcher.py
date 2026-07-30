# Make POV say WHY a source refused to resolve.
#
# When a debrid source fails, POV logs one opaque line:
#
#     >> resolve_external_sources exception <<: selected_files failed
#
# That single message covers two completely different failures, which need
# opposite fixes:
#
#   A. the debrid returned NO files -- the source is advertised as cached by an
#      external scraper (comet, torz, ...) but the provider does not actually
#      hold it. Nothing about the file list is wrong; the source is a phantom.
#   B. the debrid returned files and POV's own season/episode filter rejected
#      every one of them -- e.g. a season pack whose members are named in a
#      shape seas_ep_filter() does not recognise, or a pack that genuinely does
#      not contain the episode.
#
# From outside, the two are indistinguishable, and a field report of "I clicked
# a source, it ran through twenty and played nothing" cannot be diagnosed
# without knowing which one happened. Guessing between them has already cost a
# wrong fix once.
#
# So this patcher rewrites that one raise to carry the evidence:
#
#     selected_files failed (0 files from torbox)
#     selected_files failed (14 files from torbox, filtered out: Rick...E01.mkv | ...E02.mkv | ...)
#
# It changes NO behaviour -- the same exception is raised at the same point with
# the same effect on POV's fallback loop; only the message grows. Everything the
# message touches is already bound at that line (`files` from the line above,
# `self.debrid` from the instance), so it cannot introduce an unbound name.
#
# Marker-gated, idempotent, compile()-checked before writing, atomic.

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
DEBRID_REL_PATH = 'resources/lib/modules/debrid.py'
MARKER = 'AI_SUBS_RESOLVE_DIAG_v1'

# POV 6.07.9x, tab-indented:
#     \t\t\tif not selected_files: raise Exception('selected_files failed')
# Matched by shape rather than by an exact literal, because the last patcher
# that pinned an exact line went stale the moment POV reformatted it.
_ANCHOR_RE = re.compile(
    r"^([ \t]*)if not selected_files:\s*raise Exception\(\s*'selected_files"
    r" failed'\s*\)[ \t]*$", re.M)

# Deliberately ONE line, so the replacement inherits the anchor's indentation
# without having to reason about continuation lines. `_n` / `_names` are local
# to the expression; nothing leaks into POV's namespace.
_DIAG = (
    "if not selected_files: "
    "raise Exception('selected_files failed (%s file(s) from %s%s)' % ("
    "len(files or []), getattr(self, 'debrid', '?'), "
    "(', filtered out: ' + ' | '.join("
    "str((_f or {}).get('filename'))[-70:] for _f in (files or [])[:6])"
    ") if files else ''))  # " + MARKER)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_resolve_diag_patcher: ' + msg, level=level)
    except Exception:
        pass


def _debrid_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/{0}/'.format(POV_ADDON_ID))
        p = os.path.join(base, *DEBRID_REL_PATH.split('/'))
        return p if os.path.isfile(p) else ''
    except Exception:
        return ''


def ensure_patched():
    """Returns 'no_file' | 'read_failed' | 'already' | 'unmatched'
    | 'compile_failed' | 'write_failed' | 'patched'."""
    path = _debrid_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except (OSError, UnicodeDecodeError) as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'already'
    m = _ANCHOR_RE.search(content)
    if m is None:
        _log('selected_files raise not found -- leaving alone', level='WARNING')
        return 'unmatched'

    patched = content[:m.start()] + m.group(1) + _DIAG + content[m.end():]
    try:
        compile(patched, path, 'exec')
    except SyntaxError as e:
        _log('compile check failed, not writing: {0}'.format(e),
             level='WARNING')
        return 'compile_failed'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(patched)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'

    _log('resolve failures will now say how many files the debrid returned',
         level='INFO')
    return 'patched'
