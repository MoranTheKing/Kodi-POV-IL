# "Hebrew-subtitle match %" in UMBRELLA's source-results window.
#
# The port of pov_subtitle_match_patcher to Umbrella. Same idea, same shared
# brain (he_sub_match): under every source row, BEFORE you pick it, show how
# well an available Hebrew subtitle's release name matches that source -- i.e.
# how likely a ready Hebrew sub will sync to it.
#
# WHY IT PORTS SO CLEANLY. Umbrella's window is structurally the same shape as
# POV's, down to the loop signature:
#
#   POV       windows/sources.py        for count, item in enumerate(self.results, 1):
#                                       set_property('tikiskins.size_label', ...)
#   Umbrella  windows/source_results.py for count, item in enumerate(self.results, 1):
#                                       listitem.setProperty('umbrella.size_label', ...)
#
# and `umbrella.size_label` is the FIRST token of the info line in all twelve
# layout variants of source_results.xml (checked: lines 342-626), exactly as
# `tikiskins.size_label` is in POV's. So prefixing that one property puts the
# badge on every layout with no skin-XML change at all -- and Umbrella ships
# only one skin, so there is no second place to keep in sync.
#
# Two gated edits, mirroring the POV patcher:
#   1. SETUP: once per window, load the available Hebrew release names for the
#      media via he_sub_match (self-contained import by path -- Umbrella runs
#      this in ITS interpreter, so no relative/package imports are possible).
#   2. PER ROW: prepend the coloured badge to the size_label property.
#
# THE ONE REAL DIFFERENCE: POV's row carries both `URLName` and `name`, and the
# POV injection scores against both and takes the max. An Umbrella row has only
# `name` (the release), so both arguments are the same value. label_prefix
# already takes the max of the two, so passing one value twice is a no-op, not
# a special case.
#
# The whole file is compile()-checked before writing (so it can never break
# Umbrella or its source window), prior versions are reverted then re-applied,
# and Umbrella already wraps each row build in its own try/except as a backstop.
# No-op when Umbrella is not installed -- which is most devices.

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


UMBRELLA_ADDON_ID = 'plugin.video.umbrella'
SOURCES_REL_PATH = 'resources/lib/windows/source_results.py'
MARKER = 'AI_SUBS_UMB_MATCH_v1'

# The for-loop that builds each source row (insert SETUP just before it).
#
# EVERY anchor here ends `[ \t]*\r?$`, not `[ \t]*$`. Umbrella's
# source_results.py ships with CRLF line endings where POV's sources.py is LF,
# so a `$` anchored after optional spaces/tabs lands on the `\r` and the match
# fails. The first run of this patcher against the real 6.7.81 file returned
# 'unmatched' for exactly that reason -- which in the field would have been a
# silent no-op plus a WARNING nobody reads.
_LOOP_RE = re.compile(
    r'^(?P<indent>[ \t]*)for count, item in enumerate\(self\.results, 1\):'
    r'[ \t]*\r?$',
    re.MULTILINE,
)
# The size_label property set (wrap it to prepend the match prefix). The
# trailing `\r` is captured here for the same reason it is in the revert: the
# match CONSUMES it, so a replacement that does not put it back leaves one LF
# line in a CRLF file.
_SIZE_RE = re.compile(
    r"^(?P<indent>[ \t]*)listitem\.setProperty\('umbrella\.size_label', "
    r"size_label\)[ \t]*(?P<cr>\r?)$",
    re.MULTILINE,
)
# Revert: SETUP block (marker comment .. its `except` fallback line).
_REVERT_SETUP_RE = re.compile(
    r"[ \t]*#[ \t]*AI_SUBS_UMB_MATCH_v\d+.*?"
    r"_sm_m = None; _sm_names = \[\]; _sm_emb = \[\]; _sm_syncrel = set\(\)"
    r"[ \t]*\r?\n",
    re.DOTALL,
)
# Revert: wrapped size_label line -> plain. The trailing `\r` is CAPTURED and
# re-emitted, not just matched: consuming it and writing the plain line back
# without it left exactly one LF line in an otherwise CRLF file. Python does
# not care, but silently changing a third-party file's line endings is not
# ours to do, and it makes "revert == upstream, byte for byte" untestable.
_REVERT_SIZE_RE = re.compile(
    r"^(?P<indent>[ \t]*)listitem\.setProperty\('umbrella\.size_label', "
    r"\(_sm_m\.label_prefix.*?\) \+ size_label\)[ \t]*(?P<cr>\r?)$",
    re.MULTILINE,
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('umbrella_subtitle_match_patcher: ' + msg, level=level)
    except Exception:
        pass


def _sources_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + UMBRELLA_ADDON_ID + '/')
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
        '\tif _sm_p not in _sm_s.path: _sm_s.path.append(_sm_p)',
        '\timport he_sub_match as _sm_m',
        '\t_sm_names = _sm_m.release_names(self.meta)',
        '\t_sm_emb = _sm_m.embedded_names(self.meta)',
        '\t_sm_syncrel = _sm_m.confirmed_releases(self.meta)',
        'except Exception:',
        '\t_sm_m = None; _sm_names = []; _sm_emb = []; _sm_syncrel = set()',
    ]
    return ''.join(indent + ln + eol for ln in raw)


def revert(content):
    """`content` with any version of our two edits removed, restoring the file
    to upstream byte for byte -- CRLF included.

    A function rather than two lines inside ensure_patched because it is the
    half that has to be PROVEN: "the revert restores upstream exactly" is the
    property that keeps a version bump from stacking blocks, and a test that
    re-implements the substitution proves nothing about the shipped one."""
    out = _REVERT_SETUP_RE.sub('', content)
    return _REVERT_SIZE_RE.sub(
        lambda m: m.group('indent')
        + "listitem.setProperty('umbrella.size_label', size_label)"
        + m.group('cr'),
        out)


def _drop_pyc(path):
    """A stale __pycache__ entry for the file we just rewrote. os.replace moves
    the mtime so Python would re-compile anyway; this is belt and braces for
    filesystems with coarse timestamps."""
    try:
        stem = os.path.basename(path)[:-3]
        pycache = os.path.join(os.path.dirname(path), '__pycache__')
        if not os.path.isdir(pycache):
            return
        for fn in os.listdir(pycache):
            if fn.startswith(stem + '.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache, fn))
                except OSError:
                    pass
    except Exception:
        pass


def ensure_patched():
    """Returns 'no_file' | 'read_failed' | 'unmatched' | 'compile_failed'
    | 'unchanged' | 'patched' | 'write_failed'."""
    path = _sources_path()
    if not path:
        return 'no_file'          # Umbrella not installed -- the common case
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            original = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    eol = '\r\n' if '\r\n' in original[:4096] else '\n'
    already = MARKER in original

    # Revert any prior version so we re-apply cleanly (idempotent).
    content = revert(original)

    # 1) SETUP block right before the row-building loop.
    m = _LOOP_RE.search(content)
    if not m:
        _log('row loop not found -- skipping', level='WARNING')
        return 'unmatched'
    indent = m.group('indent')
    content = content[:m.start()] + _setup_lines(indent, eol) + content[m.start():]

    # 2) wrap the size_label set to prepend the match prefix. Umbrella's row has
    #    only `name`, so it is passed as both the primary and the alternate
    #    release; label_prefix maxes the two scores, so that is a no-op.
    s = _SIZE_RE.search(content)
    if not s:
        _log('size_label set not found -- skipping', level='WARNING')
        return 'unmatched'
    si = s.group('indent')
    wrapped = (si + "listitem.setProperty('umbrella.size_label', "
               "(_sm_m.label_prefix((item.get('name') or ''), "
               "_sm_names, _sm_emb, (item.get('name') or ''), _sm_syncrel) "
               "if _sm_m else '') + size_label)" + s.group('cr'))
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
        _drop_pyc(path)
        _log('injected Hebrew-subtitle match into Umbrella source results',
             level='INFO')
        return 'unchanged' if already else 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
