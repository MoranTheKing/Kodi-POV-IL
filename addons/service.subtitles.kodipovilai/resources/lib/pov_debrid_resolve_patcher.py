# Self-healing fix for a crash in plugin.video.pov's debrid.py
# resolve_external_sources(): its `except` handler references `torrent_id`
# (and `files`) which are only bound INSIDE the try -- so when resolution
# fails EARLY (parse_magnet_pack returns nothing, or a file dict has no
# 'filename'), the handler itself raises
#     "cannot access local variable 'torrent_id' where it is not associated
#      with a value"
# That UnboundLocalError propagates out of resolve_sources -> play_file's
# generator and ABORTS the whole "try the next sources" fallback loop (it's
# swallowed by play_file's bare except), so the user is left with NO playable
# source and no source dialog -- "no results" even though sources were found.
#
# Fix: initialise `files = None` and `torrent_id = None` at the very top of the
# function (before the try), so the except handler degrades gracefully (returns
# None) instead of crashing. POV's play_file then simply moves on to the next
# source, exactly as it does for any other failed resolve. This fixes both the
# remember-source auto-pick path and ordinary manual source selection.
#
# Idempotent + marker-gated + compile()-checked before writing, so it can never
# break POV. If POV ever ships a fixed resolve_external_sources we detect the
# guard is unneeded (signature not found / already guarded) and skip.

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
MARKER = 'AI_SUBS_DEBRID_RESOLVE_GUARD_v1'

# The signature line of the function we harden.
#
# This used to be one exact string, matching the free function POV had when the
# guard was written:
#     def resolve_external_sources(source, store_to_cloud, title, season, episode):
# POV has since made it a METHOD -- 6.07.9x reads
#     def resolve_external_sources(self, title, season, episode):
# -- so the literal stopped matching and this patcher has been quietly reporting
# 'unmatched' on every recent POV, taking its guard with it. A field log
# (2026-07-30, POV 6.07.93) shows exactly that line, which is how it surfaced.
#
# So match the NAME and take the parameters as they come, and derive the body
# indentation from the signature's own instead of assuming one tab: a method is
# one level deeper than a free function, and a guard at the wrong depth either
# fails to compile or lands outside the function.
_SIG_RE = re.compile(
    r'^([ \t]*)def\s+resolve_external_sources\s*\([^)]*\)\s*:[ \t]*$', re.M)
_GUARD_BODY = ('files = None; torrent_id = None  # ' + MARKER
               + ' -- guard except handler against unbound locals')


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_debrid_resolve_patcher: ' + msg, level=level)
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
    """Returns 'no_file' | 'unmatched' | 'already' | 'compile_failed'
    | 'write_failed' | 'read_failed' | 'patched'."""
    path = _debrid_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'already'
    m = _SIG_RE.search(content)
    if m is None:
        _log('resolve_external_sources signature not found -- skipping',
             level='WARNING')
        return 'unmatched'

    # Insert the guard immediately after the signature, one level deeper than
    # the signature itself, matching whatever POV indents with (tabs today).
    outer = m.group(1)
    unit = '\t' if '\t' in outer or not outer else outer[:1] * 4
    guard = outer + unit + _GUARD_BODY
    patched = content[:m.end()] + '\n' + guard + content[m.end():]
    if patched == content:
        return 'unmatched'

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

    _log('hardened resolve_external_sources (guard v1)', level='INFO')
    return 'patched'
