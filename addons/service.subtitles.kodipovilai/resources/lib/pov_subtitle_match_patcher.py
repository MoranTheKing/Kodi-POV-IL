# "Hebrew-subtitle match %" in POV's source-results window.
#
# Patches plugin.video.pov's windows/sources.py::make_items so each source row
# shows, before you pick it, how well an available Hebrew subtitle matches that
# source's release (see he_sub_match). Two gated edits:
#   1. SETUP: once per window, load the available Hebrew sub release names for
#      the media (community pool), via he_sub_match (self-contained import).
#   2. PER ROW: prepend a small coloured '<NN>% עברית | ' to tikiskins.size_label
#      -- that property is rendered first in the info line of EVERY layout
#      variant, so the badge shows on every skin with no skin-XML changes.
#
# The whole file is compile()-checked before writing (so it can never break
# POV / the source window), prior versions are reverted then re-applied, and
# POV already wraps each row build in try/except as a backstop.

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
MARKER = 'AI_SUBS_MATCH_v7'
END_MARKER = 'END ' + MARKER
# v6 -> v7: the badge call got its own try/except, and the SETUP block gained
# an END marker. See _setup_lines and _REVERT_SETUP_END_RE for why each.

# The for-loop that builds each source row (insert SETUP just before it).
_LOOP_RE = re.compile(
    r'^(?P<indent>[ \t]*)for count, item in enumerate\(self\.results, 1\):'
    r'[ \t]*(?P<cr>\r?)$',
    re.MULTILINE,
)
# The size_label property set (wrap it to prepend the match prefix).
_SIZE_RE = re.compile(
    r"^(?P<indent>[ \t]*)set_property\('tikiskins\.size_label', "
    r"get\('size_label', 'N/A'\)\)[ \t]*(?P<cr>\r?)$",
    re.MULTILINE,
)
# Revert, in two forms, because both exist in the field.
#
# NEW (v7+): START marker through END marker. It depends only on markers we
# control, so changing the block body can never break the revert -- which is
# what would leave an old block in place while _LOOP_RE happily inserts a
# second one in front of the untouched loop line. The middle is written so it
# cannot cross another marker of ours, so a block missing its END can never
# swallow the next block or the upstream code between them.
_REVERT_SETUP_END_RE = re.compile(
    r"[ \t]*#[ \t]*AI_SUBS_MATCH_v\d+[ \t]*\r?\n"
    r"(?:(?!#[ \t]*(?:END[ \t]+)?AI_SUBS_MATCH_v)[\s\S])*?"
    r"[ \t]*#[ \t]*END[ \t]+AI_SUBS_MATCH_v\d+[ \t]*\r?\n"
)
# LEGACY (v1-v6): every device in the field carries a v6 block, and a v6 block
# has NO end marker -- so it can only be found by the text of its own fallback
# line. Kept for exactly that reason, and bounded the same way so it cannot
# run past another marker. It is structurally unable to match a v7 block: v7's
# fallback line continues past `set()` with `; _sm_pfx = lambda ...`, so the
# `set\(\)[ \t]*\r?\n` tail below cannot match it.
_REVERT_SETUP_LEGACY_RE = re.compile(
    r"[ \t]*#[ \t]*AI_SUBS_MATCH_v\d+[ \t]*\r?\n"
    r"(?:(?!#[ \t]*(?:END[ \t]+)?AI_SUBS_MATCH_v)[\s\S])*?"
    r"_sm_m = None; _sm_names = \[\]"
    r"(?:; _sm_emb = \[\])?(?:; _sm_syncrel = set\(\))?[ \t]*\r?\n"
)
# Revert: wrapped size_label line -> plain.
_REVERT_SIZE_RE = re.compile(
    r"^(?P<indent>[ \t]*)set_property\('tikiskins\.size_label', "
    r"(?:\(_sm_m\.label_prefix|_sm_pfx\().*?\+ get\('size_label', 'N/A'\)\)"
    r"[ \t]*(?P<cr>\r?)$",
    re.MULTILINE,
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_subtitle_match_patcher: ' + msg, level=level)
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


def _setup_lines(indent, eol):
    """The once-per-window SETUP, plus `_sm_pfx` -- the per-row entry point.

    WHY THE BADGE GETS ITS OWN try/except. POV wraps each row build in
    try/except, and up to v6 this file treated that as a sufficient backstop.
    It is not: that backstop DROPS THE ROW. The badge call is identical for
    every row, so anything that makes it raise for one row makes it raise for
    all of them and the source list comes back EMPTY -- which reads as "the
    scrapers are broken", not "the badge is broken". Found while porting this
    to Umbrella, where it was reproduced: a `label_prefix` that gained a
    required argument turned two sources into zero rows. Same shape here, same
    fix.

    The realistic trigger is not exotic. `label_prefix` guards its own body,
    so it does not raise from inside -- but a call with the wrong arity raises
    before the body runs, and this add-on evolves he_sub_match.

    The fallback branch defines `_sm_pfx` too, so the per-row line calls it
    unconditionally. Note the fallback keeps going past `set()`: that is what
    makes a v7 block impossible for the LEGACY revert regex to match."""
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
        '\tdef _sm_pfx(_a, _b):',
        '\t\ttry:',
        '\t\t\treturn _sm_m.label_prefix(_a, _sm_names, _sm_emb, _b, _sm_syncrel)',
        '\t\texcept Exception:',
        "\t\t\treturn ''",
        'except Exception:',
        "\t_sm_m = None; _sm_names = []; _sm_emb = []; _sm_syncrel = set(); "
        "_sm_pfx = lambda _a, _b: ''",
        '# ' + END_MARKER,
    ]
    return ''.join(indent + ln + eol for ln in raw)


def revert(content):
    """`content` with any version of our two edits removed. The END-marker form
    runs first so a v7 block is gone before the legacy pattern is tried; a v6
    block, which has no END marker, is then caught by the legacy one.

    A function rather than lines inlined in ensure_patched because "the revert
    restores upstream exactly" is the property that keeps a version bump from
    stacking blocks -- and a test that re-implements the substitution proves
    nothing about the shipped one."""
    out = _REVERT_SETUP_END_RE.sub('', content)
    out = _REVERT_SETUP_LEGACY_RE.sub('', out)
    return _REVERT_SIZE_RE.sub(
        lambda m: m.group('indent')
        + "set_property('tikiskins.size_label', get('size_label', 'N/A'))"
        + m.group('cr'),
        out)


def ensure_patched():
    path = _sources_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            original = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    already = MARKER in original

    # Revert any prior version so we re-apply cleanly (idempotent).
    content = revert(original)

    # 1) SETUP block right before the row-building loop.
    m = _LOOP_RE.search(content)
    if not m:
        _log('row loop not found -- skipping', level='WARNING')
        return 'unmatched'
    indent = m.group('indent')
    # The line ending comes from the line we insert in FRONT of, not from a
    # sample of the file's first 4 KB: a file whose head disagrees with its
    # body would otherwise get the wrong ending at the one place it matters.
    eol = '\r\n' if m.group('cr') else '\n'
    content = content[:m.start()] + _setup_lines(indent, eol) + content[m.start():]

    # 2) wrap the size_label set to prepend the match prefix.
    s = _SIZE_RE.search(content)
    if not s:
        _log('size_label set not found -- skipping', level='WARNING')
        return 'unmatched'
    si = s.group('indent')
    wrapped = (si + "set_property('tikiskins.size_label', "
               "_sm_pfx((get('URLName') or get('name') or ''), "
               "(get('name') or '')) + get('size_label', 'N/A'))"
               + s.group('cr'))
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
        _log('injected Hebrew-subtitle match into source results', level='INFO')
        return 'unchanged' if already else 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
