# SRT parsing + chunking. Kept minimal -- we only need to split a
# file into translatable chunks of N entries and merge the model's
# response back into one document.
#
# An SRT entry block looks like:
#   1
#   00:01:22,082 --> 00:01:22,584
#   Hey, turtle.
#   <blank line>
#
# The model returns the same block shape with the text translated;
# we re-stitch the blocks back into a single SRT body.

import os
import re

BLOCK_SEPARATOR = re.compile(r'\r?\n\r?\n')

# Hearing-impaired annotations. Two flavours:
#  - whole-line annotations like "[breathing heavily]" or "(music
#    swells)" -- we want to drop the whole text line
#  - inline annotations like "Hello! [chuckles] How are you?" --
#    we want to drop just the bracketed part
# Brackets we recognise: [] {} () and unicode equivalents that
# show up in some sources.
_BRACKET_RE = re.compile(
    r'[\[\(\{][^\[\]\(\){}]*?[\]\)\}]'
)
# Also strip ALL-CAPS speaker prefixes like "MABEL: ..." that are
# common in HI subs but redundant for translation.
_SPEAKER_RE = re.compile(
    r'^[A-Z][A-Z0-9 \'\.\-]{1,30}:\s*'
)
# Same ALL-CAPS Latin speaker prefix, matched per-LINE (MULTILINE) with an
# optional leading dialogue dash preserved. Used to strip a prefix the model
# LEAKED into its Hebrew output. It can only ever match an English "NAME:" at a
# line start -- an index line (digits), a timecode line (digits), a Hebrew line,
# and a blank line can none of them match -- so it's applied to the whole text
# without classifying lines, preserving every newline exactly.
_LEAKED_SPEAKER_RE = re.compile(
    r'(?m)^(?P<pre>[ \t]*(?:-[ \t]+)?)[A-Z][A-Z0-9 \'\.\-]{1,30}:[ \t]*'
)
# Same ALL-CAPS speaker tag, but Hebrew-GATED: strip it only when the rest of
# that line contains a Hebrew character -- i.e. the model translated the line
# to Hebrew and merely LEAKED the tag. Used on the shipped Hebrew OUTPUT so a
# line the model deliberately left in English (an on-screen caption / news
# chyron / URL like "WARNING: ...", "PART 2: THE RETURN", "HTTP://...") is
# NEVER corrupted -- those have no Hebrew after the colon, so they don't match.
# An optional leading inline wrapper (<i>/<b>/<font ...>) the tag can hide
# behind is allowed and preserved (kept in the 'pre' group). The [^>\n]{1,40}
# tag body is bounded and '>'-free, so there is no catastrophic backtracking.
_LEAKED_SPEAKER_RE_HE = re.compile(
    r'(?m)^(?P<pre>[ \t]*(?:<[^>\n]{1,40}>[ \t]*)?(?:-[ \t]+)?)'
    r'[A-Z][A-Z0-9 \'\.\-]{1,30}:[ \t]*'
    r'(?=[^\n]*[֐-׿])'
)
# A line that is nothing but dialogue dashes / whitespace. What is left of
# "- (door creaking)" once the bracketed cue is gone.
_DASH_ONLY_RE = re.compile(r'^[-‐-―\s]+$')
# Hebrew combining points + cantillation. U+05BE (MAQAF), U+05C0 (PASEQ),
# U+05C3 (SOF PASUQ), U+05C6 (NUN HAFUKHA), U+05F3/U+05F4 (geresh, gershayim)
# are punctuation, not points, and are deliberately NOT in this class.
_NIQQUD_RE = re.compile('[' + ''.join(
    chr(c) for c in list(range(0x0591, 0x05BE))
    + [0x05BD, 0x05BF, 0x05C1, 0x05C2, 0x05C4, 0x05C5, 0x05C7]) + ']')
_INDEX_RE = re.compile(r'^\d+$')
_TIMECODE_RE = re.compile(
    r'^\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}\s*-->\s*'
    r'\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}'
)


# Hebrew letter range for RTL post-processing.
_HEB_LETTER = r'֐-׿'
# Punctuation that goes at the end of a Hebrew sentence but the AI
# sometimes outputs at the start.
_TRAILING_PUNCT_CHARS = '.,;:!?…'

# Match a Hebrew text line that has a misplaced punctuation prefix.
# Supports several common wrappers / decorations we need to ignore:
#   - leading dialogue dash: "- " (single dash + space)
#   - leading HTML tags (italic, bold, color, etc.): "<i>", "<b>"
#   - trailing HTML close tags: "</i>"
# The captured groups let us rebuild the line with the punct moved
# to its correct position while preserving the wrappers around it.
_LEADING_PUNCT_RE = re.compile(
    r'^(?P<dash>-\s+)?'                                 # optional "- " dialogue marker
    r'(?P<open_tags_a>(?:<[a-zA-Z!][^>]*>)*)'           # opening tags BEFORE the punct
    r'(?P<leading>[' + _TRAILING_PUNCT_CHARS + r']+)\s*'  # the misplaced punct
    r'(?P<open_tags_b>(?:<[a-zA-Z!][^>]*>)*)'           # opening tags AFTER the punct
                                                         # (covers ".<i>text</i>")
    r'(?P<rest>[' + _HEB_LETTER + r'][^\n]*?)'          # Hebrew body (non-greedy)
    r'(?P<close_tags>(?:</[a-zA-Z][^>]*>)*)\s*$'        # zero or more closing tags
)
# Detect a pure ellipsis (".." or "..." or more) -- legitimate
# continuation marker, don't move it.
_ELLIPSIS_RE = re.compile(r'^(?:\.{2,}|…+)$')


# Invisible BiDi / direction-control / BOM characters that Gemini
# (and other LLMs) sometimes insert at the START of a Hebrew line.
# When they're there, my leading-punct regex misses the punct that
# follows them, so the line never gets corrected. We strip these
# before checking, then drop them entirely from the output (they're
# noise for SRT rendering -- Kodi handles RTL via the text content
# alone).
_INVISIBLE_BIDI = (
    '‎'  # LRM
    '‏'  # RLM
    '‪'  # LRE
    '‫'  # RLE
    '‬'  # PDF
    '‭'  # LRO
    '‮'  # RLO
    '⁦'  # LRI
    '⁧'  # RLI
    '⁨'  # FSI
    '⁩'  # PDI
    '﻿'  # BOM / ZWNBSP
)

# Explicit RTL embedding controls used by the 'rtl_base' rtl_punct_mode (see
# fix_rtl_punctuation). RLE forces a right-to-left BASE direction for the wrapped
# run regardless of the renderer's paragraph base; PDF ends it. Both are in
# _INVISIBLE_BIDI above, so the wrap is idempotent (a re-run strips them first).
_RLE = '‫'   # RIGHT-TO-LEFT EMBEDDING
_PDF = '‬'   # POP DIRECTIONAL FORMATTING


def _fix_one_text_line(line, move_ellipsis=False):
    """Apply the RTL punctuation correction to a single text line
    (not an index or timecode line). Returns the corrected line."""
    stripped = line.strip()
    # Strip any leading invisible BiDi / BOM characters that would
    # otherwise hide the punct from our regex.
    while stripped and stripped[0] in _INVISIBLE_BIDI:
        stripped = stripped[1:]
    # Also strip from the end -- Gemini occasionally appends them too.
    while stripped and stripped[-1] in _INVISIBLE_BIDI:
        stripped = stripped[:-1]
    if not stripped:
        return line
    m = _LEADING_PUNCT_RE.match(stripped)
    if not m:
        # No leading punct -- but if we stripped invisible chars,
        # the rewritten stripped line is itself cleaner. Return it
        # so the invisible noise doesn't survive.
        if stripped != line.strip():
            return stripped
        return line
    dash       = m.group('dash')        or ''
    # Tags from EITHER side of the punct -- merge so the punct
    # ends up inside the tag wrap regardless of where Gemini put
    # the tag relative to the punct.
    open_tags  = (m.group('open_tags_a') or '') + \
                 (m.group('open_tags_b') or '')
    leading    = m.group('leading')
    rest       = m.group('rest')        or ''
    close_tags = m.group('close_tags')  or ''
    # Leave legitimate leading ellipses alone in normal text. A caller that
    # KNOWS this file was rewritten by the old built-in engine can opt into the
    # inverse operation: that engine moved a logical trailing ellipsis to this
    # physical leading position before rtl_base ever saw the line.
    if _ELLIPSIS_RE.match(leading) and not move_ellipsis:
        return stripped if stripped != line.strip() else line
    if not rest:
        return stripped if stripped != line.strip() else line
    # If the rest already ends with punctuation, the leading one is
    # redundant -- drop it instead of moving (which would double up).
    if rest[-1] in _TRAILING_PUNCT_CHARS:
        return dash + open_tags + rest + close_tags
    # Otherwise move leading punct to the end, INSIDE any closing
    # tag (so "<i>.לעזאזל</i>" becomes "<i>לעזאזל.</i>", not
    # "<i>לעזאזל</i>.").
    return dash + open_tags + rest + leading + close_tags


# --- encoding repair: SDH music glyphs mangled by a legacy cp1255 mis-decode ---
# A downloaded UTF-8 subtitle whose only non-ASCII char is a music note (e.g.
# U+266A, bytes E2 99 AA) was historically re-decoded as cp1255 by
# subs_engine.extract_sub.convert_to_utf (now fixed at the root), turning
# E2 99 AA into a 3-char garble ('gimel' + 'trademark' + 'multiplication').
# That garble was translated-through and cached/shared to the community pool,
# so we ALSO repair it on READ -- every cache/pool hit runs fix_rtl_punctuation
# -- which fixes entries already in the pool for everyone who downloads them,
# with no re-upload. An SDH music note is a standalone glyph at a line/word
# boundary, never a real word's final letter, so the replacement is anchored to
# a non-Hebrew-letter left boundary (below): it repairs the genuine garble but
# refuses to eat the trailing 'gimel' of a word that merely happens to be
# followed by stacked trademark-style symbols (e.g. "...gimel + TM + (R)").
_MOJIBAKE_MUSIC = {
    'ג™×': '♪',    # gimel ™ ×   -> eighth note
    'ג™«': '♫',    # gimel ™ «   -> beamed eighth notes
    'ג™¬': '♬',    # gimel ™ ¬   -> beamed sixteenth notes
    'ג™©': '♩',    # gimel ™ ©   -> quarter note
    'ג™­': '♭',    # gimel ™ soft-hyphen -> flat
    'ג™®': '♮',    # gimel ™ ®   -> natural
    'ג™¯': '♯',    # gimel ™ ¯   -> sharp
}
_MOJIBAKE_PREFIX = 'ג™'      # gimel + trademark: the shared 2-char signature
# Match a mojibake note ONLY when its leading gimel (U+05D2) is not glued to a
# real Hebrew word -- negative lookbehind on the Hebrew letter block
# U+05D0-U+05EA. The tail class is the exact 3rd char of each of the 7 keys:
# multiplication / << / not-sign / copyright / soft-hyphen / registered / macron.
_MOJIBAKE_RE = re.compile(
    '(?<![א-ת])ג™[×«¬©­®¯]')


def repair_music_mojibake(text):
    """Restore SDH music glyphs mangled to a 'gimel-trademark-x' style garble by
    a legacy cp1255 mis-decode of a UTF-8 source. Surgical: only the exact
    mojibake sequences are replaced, and only at a non-Hebrew-letter left
    boundary, so genuine Hebrew text (even a gimel-final word followed by a
    trademark sign) is never altered. Idempotent. Never raises."""
    try:
        if _MOJIBAKE_PREFIX not in text:   # cheap fast-out; every key has it
            return text
        return _MOJIBAKE_RE.sub(lambda m: _MOJIBAKE_MUSIC[m.group(0)], text)
    except Exception:
        return text


def fix_rtl_punctuation(text, mode=None, legacy_engine=False):
    """Normalize RTL punctuation placement in a Hebrew SRT body.

    `mode` controls the direction of the correction. Pulled from
    the addon's `rtl_punct_mode` setting if not explicitly passed:
      'rtl_base' (default) -- wrap each Hebrew line in an explicit
                             RTL embedding (RLE..PDF) so the
                             renderer gives it a right-to-left BASE
                             direction. Its own BiDi then places
                             embedded LTR runs (numbers, English
                             names, quoted English), parentheses
                             AND end punctuation correctly -- the
                             root-cause fix for setups whose base
                             direction defaults to LTR. Became the
                             default in v0.2.416 after on-device
                             verification; falls back gracefully to
                             logical order if a renderer ignores the
                             marks.
      'reverse'           -- move END-of-sentence punct from line
                             END to line START only. The prior
                             default (through v0.2.415): a lighter
                             fix that corrects the sentence period
                             but not embedded numbers / English /
                             parentheses. Kept for renderers that do
                             not honour the RTL-base marks.
      'legacy'            -- the inverse: move leading punct to
                             the logical end. Was the default in
                             v0.2.0-v0.2.6 under the (wrong)
                             assumption that Kodi reorders. Kept
                             around in case any setup actually
                             does reorder correctly.
      'off'               -- no processing.

    `legacy_engine` is deliberately narrow compatibility metadata for Hebrew
    files previously passed through the vendored sources engine. That engine
    physically moved trailing ellipses to the start and leading dialogue dashes
    to the end. True reverses those shapes before applying rtl_base; 'auto'
    enables it only when another unambiguous legacy-engine signature exists in
    the same file. Normal AI/local text must leave it False, so a genuine
    authored leading ellipsis remains untouched.

    Idempotent. Skips index + timecode lines. Preserves trailing
    newline so a benign re-run doesn't flag the file as changed."""
    if not text:
        return text
    # Encoding repair runs first and independent of RTL mode (even 'off'): a
    # legacy cp1255 mis-decode turned SDH music notes into 'ג™×'-style garble
    # that reached the cache/pool; restore it on every read.
    text = repair_music_mojibake(text)
    if mode is None:
        try:
            from . import kodi_utils
            mode = (kodi_utils.get_setting('rtl_punct_mode', 'rtl_base')
                    or 'rtl_base').lower()
        except Exception:
            mode = 'rtl_base'
    # 'auto' was the v0.2.7 name for what is now 'legacy'. Map for
    # backwards compatibility with users who manually selected it.
    if mode == 'auto':
        mode = 'legacy'
    if mode == 'off':
        return text
    if legacy_engine == 'auto':
        legacy_engine = _looks_like_legacy_engine_text(text)
    else:
        legacy_engine = bool(legacy_engine)
    trailing_nl = '\n' if text.endswith(('\n', '\r')) else ''
    out_lines = []
    cue_hebrew = False   # did an earlier text line of THIS cue carry Hebrew?
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or _INDEX_RE.match(stripped) or \
                _TIMECODE_RE.match(stripped):
            out_lines.append(line)
            cue_hebrew = False   # blank / index / timecode = cue boundary
            continue
        if _HEB_LETTER_RE.search(stripped):
            cue_hebrew = True
        if mode == 'legacy':
            out_lines.append(_fix_one_text_line(line))
        elif mode == 'rtl_base':
            out_lines.append(_wrap_rtl_base_line(
                line, cue_hebrew=cue_hebrew,
                legacy_engine=legacy_engine))
        else:
            # 'reverse' (default) or anything unrecognised
            out_lines.append(_reverse_fix_one_text_line(line, cue_hebrew=cue_hebrew))
    return '\n'.join(out_lines) + trailing_nl


# Match a Hebrew text line that has punctuation at the END (the
# "normal" Hebrew sentence shape). Used by the reverse-mode fix to
# move that punct to the START of the line.
_TRAILING_PUNCT_RE = re.compile(
    r'^(?P<dash>-\s+)?'
    r'(?P<open_tags>(?:<[a-zA-Z!][^>]*>)*)'
    r'(?P<rest>(?=[^\n]*[' + _HEB_LETTER + r'])[^\n]*?[^'
    + _TRAILING_PUNCT_CHARS + r'\s])'
    r'(?P<trailing>[' + _TRAILING_PUNCT_CHARS + r']+)'
    r'(?P<close_tags>(?:</[a-zA-Z][^>]*>)*)\s*$'
)
_REVERSE_DASHED_LEADING_PUNCT_RE = re.compile(
    r'^(?P<dash>-\s+)'
    r'(?P<open_tags>(?:<[a-zA-Z!][^>]*>)*)'
    r'(?P<leading>[' + _TRAILING_PUNCT_CHARS + r']+)'
    r'(?P<rest>(?=[^\n]*[' + _HEB_LETTER + r'])[^\n]*?[^'
    + _TRAILING_PUNCT_CHARS + r'\s])'
    r'(?P<close_tags>(?:</[a-zA-Z][^>]*>)*)\s*$'
)


# A line that carries a Hebrew letter (used to tell a Hebrew-cue continuation
# line from a genuinely standalone Latin line).
_HEB_LETTER_RE = re.compile('[' + _HEB_LETTER + ']')
# End-of-line sentence punctuation with NO Hebrew-in-line requirement. Only used
# for the Latin-continuation case below (guarded by cue_hebrew), so it never
# touches a standalone Latin line. Mirrors _TRAILING_PUNCT_RE's dash + open/close
# tag groups (minus the Hebrew lookahead) so a dialogue dash is relocated to the
# line end and the moved punct stays INSIDE an italic/tag pair, exactly like the
# Hebrew-line path does -- not scrambled in front of the dash or tag.
_LATIN_TAIL_PUNCT_RE = re.compile(
    r'^(?P<dash>-\s+)?'
    r'(?P<open_tags>(?:<[a-zA-Z!][^>]*>)*)'
    r'(?P<pre>.*?[^' + _TRAILING_PUNCT_CHARS + r'\s])'
    r'(?P<trailing>[' + _TRAILING_PUNCT_CHARS + r']+)'
    r'(?P<close_tags>(?:</[a-zA-Z][^>]*>)*)\s*$'
)


def _reverse_dash_suffix(dash):
    return ' -' if dash else ''


def _reverse_fix_one_text_line(line, cue_hebrew=False):
    """Move END-of-line punctuation to the START. Used by the
    'reverse' rtl_punct_mode for Kodi setups whose subtitle
    renderer doesn't BiDi-reorder Hebrew lines and shows source
    text in physical L-to-R order.

    `cue_hebrew` is True when an EARLIER line of the same cue carried Hebrew.
    It only enables the Latin-continuation case below (a sentence-ending punct
    that wrapped onto a Latin-only line of a Hebrew cue, e.g. a username
    'Modelbehavior36.' on its own line); it never affects a standalone Latin
    line (cue_hebrew stays False there)."""
    stripped = line.strip()
    while stripped and stripped[0] in _INVISIBLE_BIDI:
        stripped = stripped[1:]
    while stripped and stripped[-1] in _INVISIBLE_BIDI:
        stripped = stripped[:-1]
    if not stripped:
        return line
    dashed_leading = _REVERSE_DASHED_LEADING_PUNCT_RE.match(stripped)
    if dashed_leading:
        open_tags = dashed_leading.group('open_tags') or ''
        leading = dashed_leading.group('leading')
        rest = dashed_leading.group('rest') or ''
        close_tags = dashed_leading.group('close_tags') or ''
        if rest:
            return open_tags + leading + rest + close_tags + ' -'
    m = _TRAILING_PUNCT_RE.match(stripped)
    if not m:
        # Latin-continuation: the Hebrew cue's sentence-ending punct wrapped
        # onto a line that is itself Latin-only, so the Hebrew-requiring match
        # above skipped it. Move that trailing punct to the line start the same
        # way -- ONLY inside a Hebrew cue (cue_hebrew) and only when the line has
        # no Hebrew of its own, so a genuinely standalone Latin line is untouched.
        if cue_hebrew and not _HEB_LETTER_RE.search(stripped):
            lm = _LATIN_TAIL_PUNCT_RE.match(stripped)
            if lm:
                lat_dash = lm.group('dash') or ''
                lat_open = lm.group('open_tags') or ''
                pre = lm.group('pre') or ''
                lat_trailing = lm.group('trailing')
                lat_close = lm.group('close_tags') or ''
                if pre and pre[0] not in _TRAILING_PUNCT_CHARS:
                    # Move the punct to the start, INSIDE any tag pair, and send a
                    # dialogue dash to the end -- same shape as the Hebrew path.
                    return lat_open + lat_trailing + pre + lat_close + \
                        _reverse_dash_suffix(lat_dash)
        if stripped != line.strip():
            return stripped
        return line
    dash       = m.group('dash')       or ''
    open_tags  = m.group('open_tags')  or ''
    rest       = m.group('rest')       or ''
    trailing   = m.group('trailing')
    close_tags = m.group('close_tags') or ''
    if not rest:
        return stripped if stripped != line.strip() else line
    # If a leading punct is already present too, don't double up:
    # the trailing one is redundant, drop it. Detection: rest
    # itself starts with punct (after the optional dash/tag prefix).
    if rest[0] in _TRAILING_PUNCT_CHARS:
        return open_tags + rest + close_tags + _reverse_dash_suffix(dash)
    return open_tags + trailing + rest + close_tags + \
        _reverse_dash_suffix(dash)


# A Latin-only line that is provably SAFE to wrap in RTL base: a single
# username / handle shaped token -- ASCII letter-first, alphanumeric runs joined
# by single hyphens, ending in exactly ONE sentence-punct char ('Modelbehavior36.',
# 'cutie-patotie87.', 'X-Ray.', 'john-doe99!'). Fuzzed at 50k tokens against a
# reference BiDi engine: wrapping this class reorders ONLY the trailing punct (to
# the RTL-correct left side) and NEVER the token body. Anything outside it -- a
# leading digit or symbol ('7-Eleven.' -> '.Eleven-7', '@handle.' -> '.handle@'),
# an internal symbol or dot, a multi-word line ('50 miles.' -> '.miles 50'), a
# double / edge hyphen, or a trailing symbol -- can have its segments swapped
# under the RTL embedding, so it is excluded and left LTR (unwrapped, unmodified).
# \Z (not $) so a stray trailing newline can never sneak a match, even if this
# helper is ever reused somewhere that doesn't pre-split lines.
_WRAPPABLE_LATIN_TAIL_RE = re.compile(
    r'^[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*[' + _TRAILING_PUNCT_CHARS + r']\Z')


def _is_wrappable_latin_tail(s):
    """True for a username/handle-shaped Latin token that is the TAIL of a Hebrew
    sentence wrapped onto its own line (see _WRAPPABLE_LATIN_TAIL_RE). Wrapping it
    in RTL base moves ONLY its trailing period to the RTL-correct (left) side; the
    body is provably never reordered. Non-mutating (marks only). Never raises."""
    return bool(_WRAPPABLE_LATIN_TAIL_RE.match(s))


def _looks_like_legacy_engine_text(text):
    """Detect a file rewritten by subs_engine.engine's old punctuation fixer.

    A pure leading ellipsis is ambiguous, so it is never evidence by itself.
    A trailing *bare* dialogue dash after leading sentence punctuation is the
    engine's unique ``- sentence?`` -> ``? sentence-`` shape. A displaced single
    sentence mark is also strong file-level evidence: normal logical Hebrew
    puts it at the end. This lets old pool rows self-identify without a network
    refetch or mass re-upload, while new logical files keep genuine leading
    ellipses intact.
    """
    try:
        for line in (text or '').splitlines():
            st = line.strip()
            while st and st[0] in _INVISIBLE_BIDI:
                st = st[1:]
            while st and st[-1] in _INVISIBLE_BIDI:
                st = st[:-1]
            if not st or not _HEB_LETTER_RE.search(st):
                continue
            bare_body = st[:-1].rstrip() if st.endswith('-') \
                and not st.endswith(' -') else ''
            if bare_body and _LEADING_PUNCT_RE.match(bare_body):
                return True
            m = _LEADING_PUNCT_RE.match(st)
            if m and not _ELLIPSIS_RE.match(m.group('leading') or ''):
                return True
    except Exception:
        return False
    return False


def _wrap_rtl_base_line(line, cue_hebrew=False, legacy_engine=False):
    """Wrap a Hebrew text line in an explicit RTL embedding (RLE .. PDF) so the
    subtitle renderer treats it with a right-to-left BASE direction. Used by the
    'rtl_base' rtl_punct_mode.

    With a correct RTL base, the renderer's own BiDi places embedded LTR runs --
    numbers ('50'), usernames ('cutie-patotie87'), quoted English ('"Model
    behavior"') -- plus parentheses and end-of-sentence punctuation on the
    correct side, so NO manual surgery is needed. This is the root-cause fix for
    setups whose paragraph base defaults to LTR (which shoves that content to the
    wrong edge).

    A Hebrew line is wrapped. A Latin-only line is normally left LTR (an on-screen
    caption / URL stays as-is) -- EXCEPT a single-token username/handle that ends a
    Hebrew sentence on its own line (see _is_wrappable_latin_tail): when it sits
    inside a Hebrew cue (cue_hebrew) it is ALSO wrapped, so its trailing period
    lands on the RTL-correct side. The wrap is non-mutating (marks only), so a
    genuine '.NET' / '.exe' is never corrupted. Index / timecode / blank lines
    never reach here (the caller skips them).

    Crucially, the line is first NORMALIZED back to pristine LOGICAL order before
    wrapping. Cached and pool-shared SRT text was post-processed once already, by
    whatever rtl_punct_mode was active at WRITE time -- and 'reverse' (the
    long-standing default) MOVES end-of-sentence punct to the line START. RTL-base
    rendering needs that punct at its logical END, so we run the inverse
    ('legacy': move a leading sentence-punct back to the end, ellipsis-guarded)
    first. That makes the wrap correct for fresh, reverse-cached AND pool content
    alike -- pool items carry no mode metadata, so a puller must not assume the
    contributor used the same mode. Idempotent: edge BiDi marks (including a prior
    RLE/PDF) are stripped and the normalization converges, so a re-run is a no-op."""
    s = line
    while s and s[0] in _INVISIBLE_BIDI:
        s = s[1:]
    while s and s[-1] in _INVISIBLE_BIDI:
        s = s[:-1]
    if not s.strip():
        return line
    if not _HEB_LETTER_RE.search(s):
        # No Hebrew. A single-token username/handle ending a Hebrew sentence on its
        # own line ('Modelbehavior36.') is wrapped so BiDi moves its trailing period
        # to the RTL-correct side; everything else Latin stays LTR, UNMODIFIED. The
        # wrap is marks-only, so a genuine '.NET'/'.exe' can never be corrupted (and
        # is excluded anyway -- it starts with the punct). We do NOT try to "undo" a
        # possible reverse-mode move, because a leading '.' is indistinguishable
        # from a genuine one.
        if cue_hebrew and _is_wrappable_latin_tail(s):
            return _RLE + s + _PDF
        # Return the cleaned form only if we removed stray edge marks; else verbatim.
        return s if s != line else line
    # 'reverse' also relocates a leading dialogue dash "- " to a TRAILING " -"
    # suffix (and moves the sentence punct to the front) -- e.g. "- שלום?" was
    # cached as "?שלום -", and "- <i>שלום</i>." as "<i>.שלום</i> -". Move that dash
    # back to the front so the normalization below (which only recognizes a LEADING
    # dash) can restore the logical order, matching a fresh rtl_base render. The
    # gate uses _LEADING_PUNCT_RE (which skips a leading open-tag run before the
    # punct) so tag-wrapped cues match too; a genuine trailing interruption dash
    # ("שלום -", no leading punct) fails the match and is left untouched.
    st = s.strip()
    if st.endswith(' -') and _LEADING_PUNCT_RE.match(st[:-2].rstrip()):
        s = '- ' + st[:-2].rstrip()
    # The vendored engine used lstrip('-') and appended a BARE dash, producing
    # "? sentence-" (no separating space). Only undo it when the remaining line
    # starts with displaced punctuation; a genuine interruption "sentence-" has
    # no such prefix and is preserved.
    elif legacy_engine and st.endswith('-') and not st.endswith(' -') \
            and _LEADING_PUNCT_RE.match(st[:-1].rstrip()):
        s = '- ' + st[:-1].rstrip()
    # Undo any 'reverse'/'legacy' mutation baked into cached/pool text: move a
    # displaced leading sentence-punct back to the logical end. On pristine
    # (fresh AI) text this is a no-op -- Hebrew never authors a leading . , ; : ! ?
    normalized = _fix_one_text_line(s, move_ellipsis=legacy_engine)
    return _RLE + normalized + _PDF


# --- entries the model welded together -------------------------------------
# Field report (0.2.495): one cue rendered its own Hebrew line AND the raw
# "286" + "00:15:51,284 --> 00:15:54,054" of the cue that should have come
# after it, all on screen at once. The next cue was fine.
#
# A blank line is the ONLY thing that separates SRT entries, so when the model
# omits one while copying a chunk back, two entries arrive as a single block --
# and every stage after this one then treats the second entry's index and
# timecode as TEXT belonging to the first. restore_block_timings hands the
# merged block the first source block's header back and leaves the rest of it
# alone; the reply looks exactly one entry short, which the caller tolerates
# (it accepts up to 15% loss without retrying); and the player draws the lot.
#
# Splitting them back apart is unambiguous, which is what makes this safe to do
# on every parse rather than behind a heuristic:
#   * a digits-only line whose next non-empty line is a timecode is an entry
#     header. A bare number DOES occur in real dialogue -- a year, a score, a
#     countdown -- but never with "00:00:00,000 --> 00:00:00,000" under it.
#   * a timecode line anywhere but at the head of a block is impossible as
#     dialogue on its own.
# A well-formed block holds exactly one timecode line and leaves here untouched,
# so this costs one scan and changes nothing for input that was already correct.
def _has_text_line(lines, lo, hi):
    """True when lines[lo:hi] would still say something on screen.

    A digits-only line counts as TEXT unless it is itself an entry header --
    that is, unless a timecode follows it. The first version treated every
    digits-only line as a header, which meant a cue whose only dialogue IS a
    number could never satisfy this test: asked whether entry 41 (text: "42")
    still had something to say, it answered no, so the cut stayed at the
    timecode and the NEXT entry's index line ("50") was left behind as a second
    line of dialogue that nobody ever wrote. Same disambiguation as the split
    itself uses, and for the same reason -- digits alone are ambiguous, digits
    followed by a timecode are not.
    """
    for j in range(lo, min(hi, len(lines))):
        s = lines[j].strip()
        if not s or _TIMECODE_RE.match(s):
            continue
        if _INDEX_RE.match(s):
            k = j + 1
            while k < len(lines) and not lines[k].strip():
                k += 1
            if k < len(lines) and _TIMECODE_RE.match(lines[k].strip()):
                continue          # a header, not something the viewer reads
        return True
    return False


def _split_welded_block(block):
    """Split a block that carries a LATER entry's header inside its text."""
    lines = block.split('\n')
    tc_at = [i for i, ln in enumerate(lines) if _TIMECODE_RE.match(ln.strip())]
    if len(tc_at) < 2:
        return [block]
    cuts, prev = [], 0
    for i in tc_at[1:]:
        # The index line belongs to the entry its timecode opens, so cut BEFORE
        # the index -- cutting between the two would strand the number as the
        # last line of the previous cue, which is the same defect one line
        # smaller.
        start = i
        if i and _INDEX_RE.match(lines[i - 1].strip()):
            # ...UNLESS taking that line leaves the entry we are closing with
            # no text at all. Then the digits are not the next entry's index,
            # they are this entry's ONLY line of dialogue -- a score, a house
            # number, an answer shouted back -- and cutting in front of them
            # DELETES them: the cue above loses its text and the cue below
            # swallows the number as its index, so the number never reaches the
            # screen at all. Leaving it where it is costs nothing, because the
            # block below gets its index restored from the source either way.
            # Silent deletion is a worse outcome than the weld we came to fix.
            if _has_text_line(lines, prev, i - 1):
                start = i - 1
        if start > prev:
            cuts.append(start)
            prev = start
    if not cuts:
        return [block]
    out, prev = [], 0
    for cut in cuts + [len(lines)]:
        part = '\n'.join(lines[prev:cut])
        if part.strip():
            # rstrip the CR too. Splitting a CRLF block mid-way leaves the last
            # line's '\r' with no '\n' behind it, which a block that came
            # straight from BLOCK_SEPARATOR never carries (the separator eats
            # it), and a caller that rejoins blocks without stripping would
            # carry that artefact into the file.
            out.append(part.strip('\r\n'))
        prev = cut
    return out or [block]


def parse_blocks(text):
    """Return a list of raw entry blocks (still strings). We don't
    bother with a structured parse since the model handles the
    timecodes verbatim -- if we round-trip strings unchanged for
    those, we minimise damage from accidental edits.

    A block that holds more than one entry's header (the model dropped the
    blank line between them) is split back apart first -- see above."""
    if not text:
        return []
    # Some SRTs start with a BOM. Strip it once.
    if text.startswith('﻿'):
        text = text[1:]
    text = text.strip()
    blocks = []
    for b in BLOCK_SEPARATOR.split(text):
        if b.strip():
            blocks.extend(_split_welded_block(b))
    return blocks


# --- Cue-timing integrity ---------------------------------------------------
# The translator hands Gemini whole SRT blocks -- INCLUDING their timecode lines
# -- and stitches the reply back verbatim. The only validation on the reply is an
# ENTRY COUNT check, so a single mistyped digit in a timestamp the model was only
# supposed to copy ships straight to the player. Field reports: one Hebrew line
# frozen on screen while the rest of the dialogue came and went underneath it,
# a DIFFERENT line each re-translation, and clearing the add-on cache did not
# help (a fresh translation just mistypes a different entry). A single hour digit
# is enough: 00:41:22 --> 01:41:24 is a 60-minute cue.
#
# Two defences, deliberately layered:
#   restore_block_timings() -- the real fix. The model is never trusted with
#     timing: each translated block gets the SOURCE block's index + timecode back.
#   clamp_cue_durations()   -- a backstop for what the pairing cannot cover
#     (entry counts that legitimately differ, and a pathological SOURCE cue).
#
# The backstop is deliberately CONSERVATIVE. It is not the primary fix, so it is
# tuned to never damage a correctly-authored subtitle, at the price of leaving a
# corrupt cue a few seconds too long. Real subtitles legitimately contain long
# holds (a 90s ending-credits card, a title card over a silent scene) and
# intentional overlap (a location sign displayed across several dialogue lines,
# ASS-converted dual-speaker tracks) -- an aggressive clamp silently mangles all
# of those, which is a worse outcome than the bug it is guarding against.
_MAX_CUE_MS = 180000       # 3 min: longer than any authored hold, far under an
#                            hour-digit slip. Absolute sanity bound.
_OVERLAP_GRACE_MS = 10000  # how far a cue may outlive the NEXT cue's start before
#                            it is treated as runaway. Covers dual-speaker
#                            overlap and a sign held over roughly one dialogue
#                            turn -- NOT a sign held across many turns, which is
#                            still clipped. Raising it protects more authoring at
#                            the cost of leaving a corrupt cue on screen longer.
_MIN_CUE_MS = 400
_DEFAULT_CUE_MS = 2000
_NEXT_SCAN_MAX = 200           # bound the search for the next later-starting cue
# INVARIANT: _OVERLAP_GRACE_MS and _MAX_CUE_MS must both exceed _MIN_CUE_MS.
# The ceiling is always start+_MAX_CUE_MS or start+_OVERLAP_GRACE_MS(+gap), so
# this is what guarantees the minimum-duration floor can never be pushed past
# the ceiling and re-create the overlap the ceiling exists to prevent.

_TIME_PAIR_RE = re.compile(
    r'^(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*'
    r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})(.*)$')


def _tc_ms(h, m, sec, ms):
    return h * 3600000 + m * 60000 + sec * 1000 + ms


def _fmt_tc(ms):
    if ms < 0:
        ms = 0
    h, rem = divmod(int(ms), 3600000)
    m, rem = divmod(rem, 60000)
    s, msec = divmod(rem, 1000)
    return '{0:02d}:{1:02d}:{2:02d},{3:03d}'.format(h, m, s, msec)


def _block_timecode_index(lines):
    """Index of the timecode line inside a block's lines, or -1."""
    for i, ln in enumerate(lines[:3]):
        if _TIMECODE_RE.match(ln.strip()):
            return i
    return -1


def _block_times(block):
    """(start_ms, end_ms, trailing) for a block, or None when it has no
    parsable timecode line."""
    for ln in block.split('\n')[:3]:
        m = _TIME_PAIR_RE.match(ln.strip())
        if m:
            g = [int(x) for x in m.groups()[:8]]
            return (_tc_ms(*g[:4]), _tc_ms(*g[4:]), m.group(9) or '')
    return None


def _block_start(block):
    t = _block_times(block)
    return None if t is None else t[0]


def _rebuild_block(src_block, out_block):
    """out_block's text under src_block's index + timecode. None if either
    block isn't SRT-shaped (caller keeps the original)."""
    src_lines = src_block.split('\n')
    out_lines = out_block.split('\n')
    si = _block_timecode_index(src_lines)
    oi = _block_timecode_index(out_lines)
    if si < 0 or oi < 0:
        return None
    return '\n'.join(src_lines[:si + 1] + out_lines[oi + 1:])


def missing_blocks(src_blocks, out_blocks):
    """Source blocks the model's reply does NOT account for.

    Identity is the START TIMESTAMP, matched as a MULTISET, because that is the
    only field the model is asked to copy verbatim and the only one that
    survives a renumbered reply. Genuinely simultaneous dialogue (two entries at
    the same start) is handled by the multiset: two wanted and one returned
    leaves one missing.

    Counting alone -- "did we get back roughly as many entries as we asked
    for?" -- cannot see this. A reply that drops ten lines and invents ten
    others has the right count and the wrong content, and at an 85% yield
    threshold a chunk of 50 may quietly lose 7 lines and still be accepted.
    Fully fail-open: anything unparseable returns [] (caller keeps the reply)."""
    try:
        if not src_blocks:
            return []
        have = {}
        for b in out_blocks or ():
            st = _block_start(b)
            if st is not None:
                have[st] = have.get(st, 0) + 1
        out = []
        for b in src_blocks:
            st = _block_start(b)
            if st is None:
                continue
            if have.get(st, 0) > 0:
                have[st] -= 1
            else:
                out.append(b)
        return out
    except Exception:
        return []


def align_blocks(src_blocks, *candidate_lists):
    """Blocks drawn from `candidate_lists` to match `src_blocks` exactly: the
    same start timestamps, with the same MULTIPLICITY, in timeline order.
    Earlier lists win; a start is filled from later lists only while the source
    still calls for more at that start.

    Both halves of that rule are load-bearing, and getting either wrong loses
    subtitle content:

      * Multiplicity, not presence. Two source entries may legitimately share a
        start -- simultaneous dialogue -- and de-duplicating on start alone
        drops the second one PERMANENTLY. Not "left untranslated": gone from the
        subtitle. (Reproduced: a 3-entry chunk with two entries at one start
        came back with 2, while the caller's own bookkeeping reported success.)

      * Only what was asked for. A block whose start the model corrupted --
        a documented, already-observed failure of this model -- answers nothing
        that was requested. Adding it inserts a line at a fabricated time while
        the real slot is ALSO filled from the source, shipping the same dialogue
        twice. (Reproduced: 20 entries in, 21 out, one line at two timestamps.)

    Ordering matters downstream too: restore_block_timings pairs POSITIONALLY
    when the counts match, which only holds if the result is back in timeline
    order. The sort is stable, so entries sharing a start keep the order the
    candidates supplied them in. Fail-open: returns the first list on any
    problem."""
    try:
        wanted = {}
        for b in src_blocks or ():
            st = _block_start(b)
            if st is not None:
                wanted[st] = wanted.get(st, 0) + 1
        taken = {}
        keyed = []
        for lst in candidate_lists:
            for b in lst or ():
                st = _block_start(b)
                if st is None or taken.get(st, 0) >= wanted.get(st, 0):
                    continue
                taken[st] = taken.get(st, 0) + 1
                keyed.append((st, b))
        keyed.sort(key=lambda p: p[0])
        return [b for _st, b in keyed]
    except Exception:
        return list(candidate_lists[0]) if candidate_lists else []


def _repair_pinned_starts(src_blocks, out_blocks, fixed, ambiguous):
    """Give back the source timecode to a block whose START the model corrupted,
    but ONLY where its position is pinned by agreeing neighbours on both sides.

    `fixed` is the by-start repair pass's result (same length as out_blocks);
    blocks it already repaired are left exactly as they are. Fail-open: any
    surprise returns `fixed` untouched.

    The safety argument, in full, because the strictness is the whole point:
      * counts are equal, so index i in the reply corresponds to index i in the
        source UNLESS something shifted;
      * a shift (dropped or inserted entry) misaligns every block from the shift
        point onward, so a shifted block can never have an agreeing successor;
      * an adjacent transposition makes both members disagree, so neither has an
        agreeing neighbour on the swapped side;
      * therefore a block that disagrees while BOTH neighbours agree can only be
        an isolated mistyped timestamp, and src_blocks[i] is its source.
    A block at either end is pinned by its single existing neighbour, since there
    is no room on the other side for a block to have come from.
    """
    try:
        n = len(out_blocks)
        if n != len(src_blocks) or len(fixed) != n:
            return fixed
        agrees = []
        for i in range(n):
            ss, os_ = _block_start(src_blocks[i]), _block_start(out_blocks[i])
            agrees.append(ss is not None and os_ is not None and ss == os_)
        out = list(fixed)
        for i in range(n):
            if agrees[i]:
                continue
            if fixed[i] is not out_blocks[i]:
                continue          # the by-start pass already identified it
            src_start = _block_start(src_blocks[i])
            if src_start is None or src_start in ambiguous:
                continue
            # None means "no neighbour on that side", which happens only at the
            # ends -- and an end has no room on the far side for a block to have
            # come from, so it is pinned by its one existing neighbour. (Both
            # None means n == 1, where equal counts pin the single block on
            # their own.)
            left = agrees[i - 1] if i > 0 else None
            right = agrees[i + 1] if i + 1 < n else None
            if left is False or right is False:
                continue          # a neighbour disagrees -> a shift or a swap
            rebuilt = _rebuild_block(src_blocks[i], out_blocks[i])
            if rebuilt:
                out[i] = rebuilt
        return out
    except Exception:
        return fixed


def restore_block_timings(src_blocks, out_blocks):
    """Give every translated block its SOURCE index + timecode line back.

    The model is asked to copy timings verbatim; it usually does, and when it
    does this is a no-op. When it does not, this is the difference between a
    correct subtitle and one with a line welded to the screen.

    Pairing is positional, but positional pairing is VERIFIED before it is
    trusted: equal block counts are necessary and not sufficient (a stray blank
    line inside the model's reply can split one cue into two while another is
    dropped, keeping the count intact but shifting everything after it). Every
    pair's start timestamps must agree -- not most of them, ALL of them. A
    tolerance is tempting, since a corrupted START would then also be repairable,
    but any tolerance is a window a shift can hide in: transposing the last two
    entries of a 30-entry chunk disagrees on only 6.7% of blocks and would sail
    through a 10% gate, silently swapping two lines' text. A wrong line at the
    right time is a worse defect than a right line at a wrong time, so the strict
    rule wins and a corrupted start is left to the clamp instead.

    When the counts differ, or any pair disagrees, each output block is instead
    matched to the source block with the SAME START. That covers the common
    "Gemini silently dropped an entry" case, which the caller accepts without
    retrying at up to 15% loss, and which a positional pass would otherwise
    mis-pair into corrupting every following cue.

    Blocks whose source start is AMBIGUOUS -- the same start appears more than
    once in the source, as genuinely simultaneous dialogue does -- are left
    untouched on both paths. Neither position nor start can tell such a pair
    apart, so repairing them means guessing, and a wrong guess swaps two lines
    while doing nothing beats leaving the model's own self-consistent timing.

    Fully fail-open: any surprise returns the input unchanged.
    """
    try:
        if not out_blocks or not src_blocks:
            return out_blocks
        by_start = {}
        for i, src in enumerate(src_blocks):
            st = _block_start(src)
            if st is not None:
                by_start.setdefault(st, []).append(i)
        ambiguous = set(st for st, idxs in by_start.items() if len(idxs) > 1)
        if len(src_blocks) == len(out_blocks):
            pairs = list(zip(src_blocks, out_blocks))
            comparable = agree = 0
            for src, out in pairs:
                ss, os_ = _block_start(src), _block_start(out)
                if ss is None or os_ is None:
                    continue
                comparable += 1
                if ss == os_:
                    agree += 1
            if comparable and agree == comparable:
                return [out if _block_start(src) in ambiguous
                        else (_rebuild_block(src, out) or out)
                        for src, out in pairs]
        # Counts differ, or a pair disagreed: repair only what can be identified
        # positively.
        used = set()
        fixed = []
        for out in out_blocks:
            st = _block_start(out)
            idxs = by_start.get(st) if st is not None and st not in ambiguous else None
            pick = None
            if idxs:
                for i in idxs:
                    if i not in used:
                        pick = i
                        break
            if pick is None:
                fixed.append(out)
                continue
            used.add(pick)
            fixed.append(_rebuild_block(src_blocks[pick], out) or out)
        # A block whose START the model corrupted matches nothing above, so it
        # kept the corrupted start -- and the clamp deliberately never moves a
        # start, so nothing downstream fixes it either. That is the "line appears
        # several cues early, then vanishes exactly when it is spoken" defect
        # (field report, 0.2.445): the END was repaired, the START never was.
        #
        # It IS recoverable, in the one case where position cannot be in doubt:
        # equal counts, and the block's IMMEDIATE NEIGHBOURS both agree with the
        # source positionally. A shift cannot hide there -- a shift misaligns
        # every block after it, so no shifted block has two agreeing neighbours.
        # Nor can an adjacent transposition, which makes BOTH members disagree.
        # Only an isolated mistyped timestamp fits, and for that one src_blocks[i]
        # is pinned on both sides. Anything less certain is still left alone.
        # (The equal-counts precondition is enforced inside, in one place.)
        return _repair_pinned_starts(src_blocks, out_blocks, fixed, ambiguous)
    except Exception:
        return out_blocks


def clamp_cue_durations(text, max_ms=None):
    """Bound every cue's END so one bad timestamp cannot pin a line on screen.

    Conservative by design (see the note above): a cue is shortened only when it
    outlives the next cue's start by more than _OVERLAP_GRACE_MS, or exceeds the
    absolute _MAX_CUE_MS sanity bound, or does not end after it starts. That
    leaves authored long holds and intentional overlap alone, while an hour-long
    cue -- the failure this exists for -- is still cut back to a few seconds.

    Starts are never touched: a line that appears early is a far smaller defect
    than a permanent one, and moving starts would desynchronise content that is
    otherwise fine.
    """
    try:
        if not text or '-->' not in text:
            return text
        limit = _MAX_CUE_MS if max_ms is None else max_ms
        blocks = parse_blocks(text)
        times = [_block_times(b) for b in blocks]
        # The next start strictly LATER than this cue's own start. A suffix
        # minimum cannot express that (the smallest following start may be
        # EARLIER than ours in an out-of-order file), so this is a forward scan
        # -- but a HARD-BOUNDED one. In a well-formed subtitle the answer is the
        # very next cue; the bound only matters for a degenerate file, which is
        # exactly where an unbounded rescan-per-cue would go quadratic. Past the
        # bound we simply decline to bound that cue by a neighbour and let the
        # absolute ceiling stand.
        n = len(blocks)
        next_later = [None] * n
        for i in range(n):
            ti = times[i]
            if ti is None:
                continue
            for j in range(i + 1, min(n, i + 1 + _NEXT_SCAN_MAX)):
                tj = times[j]
                if tj is not None and tj[0] > ti[0]:
                    next_later[i] = tj[0]
                    break
        out = []
        changed = 0
        for i, block in enumerate(blocks):
            t = times[i]
            if t is None:
                out.append(block)
                continue
            start, end, trail = t
            ceiling = start + limit
            nxt = next_later[i]
            if nxt is not None and nxt > start:
                ceiling = min(ceiling, nxt + _OVERLAP_GRACE_MS)
            new_end = end
            if new_end <= start:
                new_end = start + _DEFAULT_CUE_MS
            # Order matters: the minimum duration must never push the end back
            # past the ceiling, or the "cannot outlive the next cue" guarantee
            # is silently broken for rapid exchanges.
            new_end = min(max(new_end, start + _MIN_CUE_MS), ceiling)
            if new_end <= start:
                new_end = start + 1
            if new_end == end:
                out.append(block)
                continue
            changed += 1
            lines = block.split('\n')
            ti = _block_timecode_index(lines)
            if ti < 0:
                out.append(block)
                continue
            # Preserve the line's own EOL so a CRLF file stays a CRLF file.
            cr = '\r' if lines[ti].endswith('\r') else ''
            lines[ti] = '{0} --> {1}{2}{3}'.format(
                _fmt_tc(start), _fmt_tc(new_end), trail.rstrip('\r'), cr)
            out.append('\n'.join(lines))
        if not changed:
            return text
        return stitch_blocks(out)
    except Exception:
        return text


def chunk_blocks(blocks, per_chunk=250):
    """Yield groups of `per_chunk` blocks. Last group may be smaller."""
    if per_chunk < 1:
        per_chunk = 1
    for i in range(0, len(blocks), per_chunk):
        yield blocks[i:i + per_chunk]


def block_text_only(block):
    """Return just the dialogue text from a single SRT entry block,
    stripping the entry number and the timecode line. Returns ''
    if the block isn't shaped like SRT.

    Used by the cross-chunk context feature in translate.py: we
    feed the last N source-text lines of the previous chunk to the
    AI as "PREVIOUS DIALOGUE CONTEXT" so the model has the same
    conversational thread it would have had if everything ran in
    one giant chunk -- which catches the cross-chunk gender drift
    that the per-chunk-cast block alone can't prevent.
    """
    if not block:
        return ''
    lines = block.strip().split('\n')
    # First line: entry number. Second line: timecode arrow.
    # Everything from line 3 onward is the dialogue text.
    # We're tolerant: if the entry number is missing (some scrapers
    # emit unnumbered SRT) we accept and start at the timecode.
    start = 0
    if lines and lines[0].strip().isdigit():
        start = 1
    if start < len(lines) and '-->' in lines[start]:
        start += 1
    return '\n'.join(lines[start:]).strip()


def stitch_blocks(blocks):
    """Join blocks back into a single SRT body using CRLF blank lines
    between entries (standard SRT delimiter). Trailing newline so
    Kodi's parser is happy."""
    return '\r\n\r\n'.join(b.strip() for b in blocks) + '\r\n'


def count_entries(text):
    return len(parse_blocks(text))


def looks_hebrew(text, min_alpha=120, min_ratio=0.5):
    """Rough sanity check that `text` is genuinely a Hebrew translation and not
    a failed / mostly-untranslated one. Among the alphabetic characters, Hebrew
    must dominate. If there's too little text to judge, returns True (never
    block on thin evidence). Used as a pool-upload quality gate."""
    heb = lat = 0
    for c in text or '':
        o = ord(c)
        if 0x0590 <= o <= 0x05FF:
            heb += 1
        elif ('a' <= c <= 'z') or ('A' <= c <= 'Z'):
            lat += 1
    alpha = heb + lat
    if alpha < min_alpha:
        return True
    return heb >= alpha * min_ratio


def untranslated_line_ratio(text, min_cues=10, min_len=8):
    """Fraction of substantial cues that look UNTRANSLATED -- i.e. they carry
    Latin letters but contain no Hebrew at all. Used as a pool-upload quality
    gate to catch a PARTIALLY-failed translation (whole chunks left in English)
    that `looks_hebrew` misses because the document is Hebrew overall.

    A cue with ANY Hebrew counts as translated (mixed Hebrew+English lines are
    fine). Only cues with real text (>= min_len letters) are weighed, so blank
    lines, '♪', numbers and short interjections don't skew it. Returns 0.0 when
    there are too few substantial cues to judge (never block on thin evidence)
    -- so a handful of legitimately-English lines (song lyrics, on-screen
    signs, 'FBI') can't trip the gate; only a large proportion does."""
    substantial = 0
    untranslated = 0
    for block in parse_blocks(text or ''):
        line = block_text_only(block)
        if not line:
            continue
        heb = lat = 0
        for c in line:
            o = ord(c)
            if 0x0590 <= o <= 0x05FF:
                heb += 1
            elif ('a' <= c <= 'z') or ('A' <= c <= 'Z'):
                lat += 1
        if (heb + lat) < min_len:
            continue  # too little text to judge this cue
        substantial += 1
        if heb == 0 and lat > 0:
            untranslated += 1
    if substantial < min_cues:
        return 0.0
    return untranslated / float(substantial)


def strip_hi_annotations(text, keep_speaker_prefixes=False):
    """Remove hearing-impaired noise from an SRT body.

    Drops bracketed sound cues like [breathing], (music playing),
    {chuckles}. If an entry's text was nothing but annotations, the
    whole entry is dropped (its timecode goes too -- there's literally
    no speech in that span, so an empty subtitle would be a visual gap
    with nothing useful).

    ALL-CAPS speaker prefixes like 'MABEL: ' are dropped by default, BUT
    kept when keep_speaker_prefixes=True. The AI translation path keeps
    them on purpose: the model matches the name against the TMDB cast
    block to pick the correct Hebrew gender per line (see prompt.py's
    SPEAKER-PREFIX HINT), then drops the tag from its own Hebrew output
    -- so stripping them here would throw away the best per-line gender
    signal. Any prefix the model fails to drop is removed from the OUTPUT
    by strip_leaked_speaker_prefix().

    Returns the cleaned SRT body. Block order and numbering are
    preserved for surviving entries (we keep the original index
    numbers so the model sees stable references).
    """
    if not text:
        return text
    out_blocks = []
    for block in parse_blocks(text):
        lines = block.split('\n')
        kept_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if _INDEX_RE.match(stripped):
                kept_lines.append(line)
                continue
            if _TIMECODE_RE.match(stripped):
                kept_lines.append(line)
                continue
            # text line -- strip bracketed sound cues. Speaker prefixes are
            # KEPT when keep_speaker_prefixes (the AI uses them for gender and
            # drops them from its output; see the docstring).
            cleaned = _BRACKET_RE.sub('', line)
            if not keep_speaker_prefixes:
                cleaned = _SPEAKER_RE.sub('', cleaned)
            # collapse whitespace runs that the strips may have
            # left behind
            cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
            # A line that was ONLY a sound cue behind a dialogue dash
            # ("- (door creaking)") reduces to a bare "-". That dash belongs
            # to the line we just removed, so keeping it ships a visible "-"
            # cue -- 76 of them in one reported file, and the model dutifully
            # copies each one into the Hebrew. Drop the residue, but ONLY when
            # the strip is what emptied the line, so a dash a source
            # deliberately wrote on its own is left exactly as it was.
            if cleaned != line.strip() and _DASH_ONLY_RE.match(cleaned):
                cleaned = ''
            if cleaned:
                kept_lines.append(cleaned)
        # only keep the block if there's actual dialogue text left
        # (more than just the index + timecode)
        text_lines = [ln for ln in kept_lines
                      if ln.strip() and not _INDEX_RE.match(ln.strip())
                      and not _TIMECODE_RE.match(ln.strip())]
        if text_lines and len(kept_lines) >= 3:
            out_blocks.append('\n'.join(kept_lines))
    return '\r\n\r\n'.join(out_blocks) + '\r\n' if out_blocks else ''


def strip_leaked_speaker_prefix(text, hebrew_only=False):
    """Remove any ALL-CAPS Latin speaker prefix (e.g. 'MABEL: ', '- DR. SMITH: ')
    that LEAKED into a line. The prompt tells the model to use such a prefix for
    gender then drop it, but model compliance isn't perfect. Index/timecode/blank
    lines can never match (the pattern needs a leading A-Z Latin run), and the
    exact line/newline structure is preserved (no entries dropped, cue timing
    intact). A leading dialogue dash is kept. Never raises into the caller.

    hebrew_only=True (use on the shipped Hebrew OUTPUT) strips the tag ONLY when
    the rest of that line contains a Hebrew character, so a line the model
    deliberately left in English -- a caption/chyron/URL like 'WARNING: ...' or
    'HTTP://...' -- is never corrupted. The default (un-gated) strips any leading
    ALL-CAPS 'NAME:' and is used on transient ENGLISH placeholders (the interim
    first-chunk fallback, the progressive stitch) and on the pre-Google source,
    matching the historical source-side speaker-prefix stripping."""
    if not text:
        return text
    try:
        rx = _LEAKED_SPEAKER_RE_HE if hebrew_only else _LEAKED_SPEAKER_RE
        return rx.sub(lambda m: m.group('pre'), text)
    except Exception:
        return text


# --- the speaker tag the model TRANSLATED instead of dropping ----------------
# strip_leaked_speaker_prefix covers the tag the model COPIED ("IAN: לא, לא.").
# It cannot see the far more common outcome, because that pattern needs an
# ALL-CAPS LATIN name: the model translates the tag along with the line, and
# "IAN: No, no." comes back as "איאן: לא, לא.". Measured on a file a user
# reported: 60 leaked tags, every one of them Hebrew, zero Latin -- the Latin
# stripper works, the model just rarely gives it anything to do.
#
# Stripping a "word:" prefix from Hebrew on its own evidence would be reckless:
# real dialogue says "תראה: אני לא יודע" and "האמת: לא אכפת לי". So this is
# ANCHORED TO THE SOURCE. An entry's Hebrew may lose a prefix only when the
# SAME entry's source carried an ALL-CAPS speaker tag, and never more of them
# than the source had. Genuine dialogue has no ALL-CAPS tag in the source, so
# it can never match, whatever it does with colons.
# The leading run allows the invisible bidi controls fix_rtl_punctuation adds
# (RLE ... PDF), so this still works on a file that has already been through
# the RTL pass -- the live path runs before it, the repair paths do not.
_HE_TAG_RE = re.compile(
    u'^(?P<pre>[ \t' + _INVISIBLE_BIDI + u']*'
    u'(?:<[^>\n]{1,40}>[ \t]*)?(?:-[ \t]*)?)'
    u'[\u05d0-\u05ea][\u0590-\u05f4 \t\'"]{0,20}?'
    u'[ \t]*:[ \t]*(?=\\S)')
_HE_TAG_WORDS = 2


def strip_hebrew_speaker_prefix(text, source_text):
    """Remove a speaker tag the model rendered in Hebrew ("איאן: לא, לא.").

    `source_text` is the SRT the translation was made from, and it is what
    licenses each removal (see the note above) -- without it nothing is
    touched. Line and newline structure is preserved exactly: only characters
    inside a line are removed, so no cue, line or timing can change. Never
    raises into the caller.
    """
    if not text or not source_text:
        return text
    try:
        # Per source entry: which TEXT-LINE POSITIONS carried an ALL-CAPS
        # speaker tag, and how many text lines that entry had. The positions
        # are what make this precise -- with them, a source entry whose first
        # line is "IAN: No." and whose second is "Look: I don't know." can
        # only ever license a removal on the FIRST Hebrew line.
        #
        # An index number that appears TWICE is dropped rather than merged.
        # The number is the only key there is, so two blocks sharing one would
        # share a licence, and the untagged one would spend the tagged one's.
        src_tags, seen = {}, set()
        for blk in parse_blocks(source_text):
            lines = blk.split('\n')
            if (len(lines) < 3 or not _INDEX_RE.match(lines[0].strip())
                    or not _TIMECODE_RE.match(lines[1].strip())):
                continue
            n = int(lines[0].strip())
            if n in seen:
                src_tags.pop(n, None)
                continue
            seen.add(n)
            at = set()
            for i, ln in enumerate(lines[2:]):
                s = ln.strip()
                if s.startswith('-'):
                    s = s[1:].lstrip()
                if _SPEAKER_RE.match(s):
                    at.add(i)
            if at:
                src_tags[n] = (at, len(lines) - 2)
        if not src_tags:
            return text

        # Which lines of the TRANSLATION are really entry indices: a
        # digits-only line whose next non-empty line is a timecode. Without
        # that second condition a digits-only line of DIALOGUE -- a year, a
        # score, a countdown, and there are plenty in a 2,000-cue file --
        # reads as an entry boundary, and hands the rest of its cue the tag
        # licence belonging to whichever entry happens to share the number.
        lines_all = text.split('\n')
        idx_at, dup = {}, set()
        for i, line in enumerate(lines_all):
            s = line.strip()
            if not _INDEX_RE.match(s):
                continue
            j = i + 1
            while j < len(lines_all) and not lines_all[j].strip():
                j += 1
            if j < len(lines_all) and _TIMECODE_RE.match(lines_all[j].strip()):
                n = int(s)
                if n in idx_at.values():
                    dup.add(n)
                idx_at[i] = n

        # How many text lines each entry of the TRANSLATION has. Positions
        # only mean the same thing on both sides when these agree.
        he_count = {}
        cur, expect_tc = None, False
        for i, line in enumerate(lines_all):
            if i in idx_at:
                cur = idx_at[i]
                he_count[cur] = 0
                expect_tc = True
            elif not line.strip():
                continue
            elif expect_tc:
                expect_tc = False
            elif cur is not None:
                he_count[cur] += 1

        out = []
        tags_at, pos, licensed, expect_tc = set(), -1, False, False
        for i, line in enumerate(lines_all):
            cr = '\r' if line.endswith('\r') else ''
            body = line[:-1] if cr else line
            if i in idx_at:
                n = idx_at[i]
                tags_at, span = src_tags.get(n, (set(), 0))
                # POSITIONAL ONLY. When the two sides split the entry
                # differently -- the model merges two source lines into one
                # often enough -- position 0 of the Hebrew is not position 0
                # of the source, so nothing about the source's positions
                # applies and NOTHING is licensed. Counting instead ("at most
                # this many tags somewhere in the entry") is what would let a
                # merged cue's genuine "תראה:" be read as the tag the source
                # carried on its other line.
                licensed = (bool(tags_at) and n not in dup
                            and he_count.get(n) == span)
                pos = -1
                expect_tc = True
            elif not body.strip():
                pass
            elif expect_tc:
                expect_tc = False
            else:
                pos += 1
                if licensed and pos in tags_at and _HAS_HEBREW_RE.search(body):
                    m = _HE_TAG_RE.match(body)
                    # a tag is a NAME, not a sentence: at most two words, and
                    # the line must still have Hebrew left once it is gone
                    # (otherwise the "tag" was the whole line, and removing it
                    # would empty a cue -- never allowed). Counted on the tag
                    # ALONE, with the dash and any bidi control excluded, so
                    # the limit means the same thing on every line shape.
                    tag = m.group(0)[len(m.group('pre')):] if m else ''
                    if m and len(tag.split(':')[0].split()) <= _HE_TAG_WORDS:
                        rest = body[m.end():]
                        if _HAS_HEBREW_RE.search(rest):
                            body = m.group('pre') + rest
            out.append(body + cr)
        return '\n'.join(out)
    except Exception:
        return text


def strip_niqqud(text):
    """Remove Hebrew points and cantillation marks.

    Hebrew subtitles are written unpointed; the model sometimes vocalises a
    word anyway ("בְּסֵדֶר", "מַה?", "דוֹב."), which a user reported as "a lot of
    niqqud that isn't really needed". Every occurrence measured in real output
    was an ordinary word carrying no information the consonants don't already
    have -- no gendered form depended on a point -- so this is a pure display
    cleanup.

    Combining marks ONLY: MAQAF, PASEQ, SOF PASUQ, geresh and gershayim are
    real punctuation and are deliberately outside the class, so a word like
    צה"ל and a hyphenated בֵּית-הַסֵּפֶר keep their spelling. Never raises.
    """
    if not text:
        return text
    try:
        return _NIQQUD_RE.sub('', text)
    except Exception:
        return text


# --- leaked Arabic gender-reference text -------------------------------------
# When the Arabic gender reference is on (forced on for everyone), the prompt
# carries REAL Arabic lines from a human translation of the same scene, as a
# gender oracle. prompt.py tells the model in capitals to take "the gender and
# NOTHING else", but a prompt is an instruction, not a guarantee: field report
# of "Arabic word completions / half words" turning up inside otherwise-correct
# Hebrew lines. The speaker-prefix leak already has a post-processor; this one
# had none, so a leak shipped straight to the player.
#
# Deliberately narrow. It strips Arabic ONLY from a line that also carries
# Hebrew -- i.e. a contaminated translation, which is the reported shape. A line
# that is entirely Arabic is left alone: that is what an on-screen sign or a
# deliberately untranslated line looks like, and destroying it would be worse
# than the leak. Same reasoning as strip_leaked_speaker_prefix(hebrew_only=True).
# Arabic script, EXCLUDING two things that live inside the same Unicode blocks
# and are not leaks: Arabic-Indic DIGITS (U+0660-0669 -- "השעה ١٢:٣٠" is a time,
# not a leaked word) and U+FEFF, the byte-order mark, which is the last
# codepoint of Presentation Forms-B and would otherwise make a stray BOM between
# two Hebrew words look like Arabic. Both were found by review.
_ARABIC_CH = (u'\u0600-\u065f\u066a-\u06ff'      # Arabic (no Arabic-Indic digits)
              u'\u0750-\u077f'                    # Arabic Supplement
              u'\u0870-\u089f'                    # Arabic Extended-B
              u'\u08a0-\u08ff'                    # Arabic Extended-A
              u'\ufb50-\ufdff'                    # Presentation Forms-A
              u'\ufe70-\ufefc')                   # Presentation Forms-B (no BOM)
# Deliberately NOT included: U+1EE00-1EEFF (Arabic Mathematical Alphabetic
# Symbols) -- notation, not text, and outside the BMP; and U+206C/206D, two
# deprecated formatting controls. Everything else Unicode names ARABIC is
# covered; a field report of a stray letter INSIDE a Hebrew word is what turned
# up the Extended-B hole, so this list is now verified against the full
# character database rather than assembled by hand.
_HEBREW_CH = u'\u0590-\u05ff\ufb1d-\ufb4f'
# INVARIANT, and the thing that actually makes strip_leaked_arabic safe:
# these two classes are DISJOINT, and _ARABIC_RUN_RE's continuation class is
# built only from _ARABIC_CH plus blanks/tatweel/Arabic diacritics/Arabic
# punctuation. The regex therefore CANNOT consume a Hebrew character, whatever
# surrounds it -- so a line can never lose part of its Hebrew sentence. The
# 'did the Hebrew survive' check in strip_leaked_arabic is a net under that,
# not the guarantee itself, and it only notices the loss of the LAST Hebrew
# character. Anyone widening either class must keep them disjoint.
# A run of Arabic plus ONLY what belongs to it: surrounding blanks, Arabic
# diacritics/tatweel, and ARABIC punctuation. Latin/Hebrew punctuation is
# deliberately excluded -- the '.' in "קארל מת. ـكِ" and the '?' in
# "מה קורה? ماذا" end the HEBREW sentence, and an earlier version that swallowed
# them turned a leak into a second defect.
_ARABIC_RUN_RE = re.compile(
    u'[ \t]*[' + _ARABIC_CH + u'][' + _ARABIC_CH + u' \t\u0640\u064b-\u0652\u060c\u061b\u061f]*')
_HAS_HEBREW_RE = re.compile(u'[' + _HEBREW_CH + u']')
_HAS_ARABIC_RE = re.compile(u'[' + _ARABIC_CH + u']')


# --- the leak that is a SCRIPT SWAP, not a foreign word ----------------------
# Deleting the Arabic is right when the model pasted a foreign WORD in. It is
# wrong for the commonest shape by far, which measurement on a reported file
# turned up: the model typed the correct HEBREW WORD but rendered part of it in
# Arabic letters. Deletion then mutilates the word --
#     לעצمي     -> לעצ         (wanted: לעצמי)
#     רוمانטיקה -> רוטיקה      (wanted: רומאנטיקה)
#     קريستل    -> ק           (wanted: קריסתל)
# -- which is how a "letters in the middle of a Hebrew word" report becomes a
# "half a word is missing" one. Hebrew and Arabic are cognate alphabets, so the
# fragment can simply be spelled back into Hebrew letters instead.
#
# Restricted to exactly the swap shape, because that is the only shape where
# transliteration is meaningful:
#   * the run must TOUCH a Hebrew letter with no space in between (a run behind
#     a space is a separate token -- a real Arabic word -- and is deleted as
#     before),
#   * and it must be a short, punctuation-free, space-free letter run. A phrase
#     ("وه، لا، يا لقد...") is a genuine pasted sentence; spelling it in Hebrew
#     letters would produce gibberish, so it stays on the deletion path.
# Nothing here can remove Hebrew -- it only ever ADDS Hebrew letters -- so the
# module-level guarantee that a line never loses its Hebrew holds a fortiori.
_AR2HE = {
    u'ا': u'א', u'أ': u'א', u'إ': u'א',
    u'آ': u'א', u'ء': u'א',
    u'ب': u'ב', u'ت': u'ת', u'ث': u'ת',
    u'ة': u'ה',
    u'ج': u'ג', u'ح': u'ח', u'خ': u'ח',
    u'د': u'ד', u'ذ': u'ד',
    u'ر': u'ר', u'ز': u'ז',
    u'س': u'ס', u'ش': u'ש',
    u'ص': u'צ', u'ض': u'צ',
    u'ط': u'ט', u'ظ': u'ט',
    u'ع': u'ע', u'غ': u'ע',
    u'ف': u'פ', u'ق': u'ק', u'ك': u'כ',
    u'ل': u'ל', u'م': u'מ', u'ن': u'נ',
    u'ه': u'ה', u'و': u'ו',
    u'ي': u'י', u'ى': u'י', u'ئ': u'י',
    u'ؤ': u'ו',
}
# Harakat / tatweel carry no consonant, so they simply drop. Built from the
# codepoints _ARABIC_RUN_RE itself allows inside a run (U+064B-U+0652 plus
# tatweel), plus the Quranic marks, so the two cannot drift apart.
_AR_MARKS = frozenset([chr(0x0640)]
                      + [chr(c) for c in range(0x064B, 0x0653)]
                      + [chr(c) for c in range(0x0610, 0x061B)]
                      + [chr(c) for c in range(0x0653, 0x0656)]
                      + [chr(0x0670)])
# Hebrew letters that take a different shape at the end of a word.
_HE_FINAL = {u'כ': u'ך', u'מ': u'ם', u'נ': u'ן',
             u'פ': u'ף', u'צ': u'ץ'}
_MAX_GLUED_RUN = 8


def _transliterate_glued_run(run, before, after, ate_space):
    """Hebrew spelling of an Arabic run that is part of a Hebrew word, or None
    when this run is not that shape and the caller should fall through to the
    existing deletion path. Never raises."""
    try:
        if ate_space:
            return None          # behind a space: a separate token, not a swap
        # _ARABIC_RUN_RE's continuation class includes blanks, so a run can
        # carry the space that FOLLOWS it ("זוכرة כשהיית" matches "رة "). That
        # space belongs to the Hebrew sentence -- keep it, or the two words
        # weld together, which is how one defect used to become another.
        core = run.rstrip(' \t')
        tail = run[len(core):]
        if not core or len(core) > _MAX_GLUED_RUN:
            return None
        # must be glued to Hebrew on at least one side
        ends_word = bool(tail) or not (after and _HAS_HEBREW_RE.match(after))
        touches = ((before and _HAS_HEBREW_RE.match(before))
                   or (not tail and after and _HAS_HEBREW_RE.match(after)))
        if not touches:
            return None
        out = []
        for ch in core:
            if ch in _AR_MARKS:
                continue
            he = _AR2HE.get(ch)
            if he is None:
                return None          # punctuation / anything unmapped: not a swap
            out.append(he)
        if not out:
            return None
        # word-final letters take their sofit form, but only when the word
        # really ends here (the next character is not more of the same word).
        if ends_word:
            out[-1] = _HE_FINAL.get(out[-1], out[-1])
        return u''.join(out) + tail
    except Exception:
        return None


def _clean_arabic_from_line(body):
    """Arabic runs removed from one text line, tidied."""
    # Replace a run with a SPACE when it stood between words, but with NOTHING
    # when it sat INSIDE one. A field report showed a single Arabic letter glued
    # into the middle of a Hebrew word ("להא<lam>ל"); substituting a space there
    # splits the word in two, which is a second defect rather than a repair.
    def _sub(m):
        start, end = m.start(), m.end()
        ate_space = m.group(0)[:1] in (' ', '\t')
        after = body[end:end + 1]
        before = body[start - 1:start] if start else ''
        glued = _transliterate_glued_run(m.group(0), before, after, ate_space)
        if glued is not None:
            return glued
        tight = (not ate_space and after and not after.isspace()
                 and before and not before.isspace())
        return '' if tight else ' '

    cleaned = _ARABIC_RUN_RE.sub(_sub, body)
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
    cleaned = re.sub(r'[ \t]+(</)', r'\1', cleaned)   # no gap before a closing tag
    # A file that already went through fix_rtl_punctuation is wrapped in RLE/PDF,
    # which are not whitespace -- so .strip() cannot reach a space stranded
    # between the text and the closing control. That is exactly the shape of a
    # CACHED subtitle being repaired after the fact, so handle it explicitly.
    #
    # ANCHORED to the two ends, and to RLE/PDF only -- the controls WE insert.
    # An unanchored version of this collapsed blanks around ANY invisible
    # control anywhere in the line, which glued words together across a
    # legitimate space-padded RLM or BOM ("יש 50<RLM> דולר" -> "יש 50<RLM>דולר").
    # Those are zero-width, so the damage is visible in the rendered subtitle.
    _wrap = _RLE + _PDF
    cleaned = re.sub(r'^([' + _wrap + r']*)[ \t]+', r'\1', cleaned)
    cleaned = re.sub(r'[ \t]+([' + _wrap + r']*)$', r'\1', cleaned)
    cleaned = cleaned.strip()
    if body.lstrip().startswith('-') and cleaned and not cleaned.startswith('-'):
        cleaned = '- ' + cleaned
    return cleaned


# --- the same swap, in a script with no reference block behind it -----------
# The Arabic leak has an obvious source (the gender-reference block in the
# prompt). This one does not: the model simply reaches for a letter from
# another alphabet mid-word -- "\u05d0\u05de\u043c" for \u05d0\u05de\u05de, "\u05de\u057a\u0430\u05e6\u05d7\u05ea". It is the same defect the
# user described as "English letters in the middle of a Hebrew word", and the
# same repair applies: the letter stands for a sound, so spell it in Hebrew.
#
# Narrower than the Arabic path in two deliberate ways. Only a run GLUED to a
# Hebrew letter is touched, and a standalone foreign word is NEVER touched --
# there is no reference block here that could have leaked one, so a Cyrillic or
# Greek word standing on its own is far more likely to be a deliberate quote
# than a mistake. And the run is capped at 3 characters: this defect is a
# letter or two, and a longer run is a word, not a slip.
_FOREIGN2HE = {}
for _s, _d in (
        (u'\u0430\u0431\u0432\u0433\u0434\u0435\u0436\u0437\u0438\u0439\u043a\u043b\u043c\u043d\u043e\u043f\u0440\u0441\u0442\u0443\u0444\u0445\u0446\u0447\u0448\u0449\u044b\u044d\u044e\u044f',
         u'\u05d0\u05d1\u05d5\u05d2\u05d3\u05d0\u05d6\u05d6\u05d9\u05d9\u05e7\u05dc\u05de\u05e0\u05d5\u05e4\u05e8\u05e1\u05ea\u05d5\u05e4\u05d7\u05e6\u05e6\u05e9\u05e9\u05d9\u05d0\u05d5\u05d0'),
        (u'\u03b1\u03b2\u03b3\u03b4\u03b5\u03b6\u03b7\u03b8\u03b9\u03ba\u03bb\u03bc\u03bd\u03be\u03bf\u03c0\u03c1\u03c2\u03c3\u03c4\u03c5\u03c6\u03c7\u03c8\u03c9',
         u'\u05d0\u05d1\u05d2\u05d3\u05d0\u05d6\u05d0\u05ea\u05d9\u05e7\u05dc\u05de\u05e0\u05e1\u05d5\u05e4\u05e8\u05e1\u05e1\u05ea\u05d5\u05e4\u05d7\u05e4\u05d5'),
        (u'\u0561\u0562\u0563\u0564\u0565\u0566\u0567\u0568\u0569\u056a\u056b\u056c\u056d\u056e\u056f\u0570\u0571\u0572\u0573\u0574\u0575\u0576\u0577\u0578\u0579\u057a\u057b\u057c\u057d\u057e\u057f\u0580\u0581\u0582\u0583\u0584\u0585\u0586',
         u'\u05d0\u05d1\u05d2\u05d3\u05d0\u05d6\u05d0\u05d0\u05ea\u05d6\u05d9\u05dc\u05d7\u05e6\u05e7\u05d4\u05d6\u05e2\u05e6\u05de\u05d9\u05e0\u05e9\u05d5\u05e6\u05e4\u05d2\u05e8\u05e1\u05d5\u05ea\u05e8\u05e6\u05d5\u05e4\u05e7\u05d5\u05e4')):
    for _a, _b in zip(_s, _d):
        _FOREIGN2HE[_a] = _b
        _FOREIGN2HE[_a.upper()] = _b
# UNBOUNDED, like _ARABIC_RUN_RE, and the length check lives inside the
# substitution. A '{1,3}' regex does not cap the run -- it caps each MATCH,
# so a six-letter Cyrillic word glued to Hebrew came back as two matches and
# was transliterated in pieces, half in each script. Matching the whole run
# and rejecting it by length is what actually enforces the cap.
_FOREIGN_RUN_RE = re.compile(u'[' + u''.join(sorted(_FOREIGN2HE)) + u']+')
_MAX_FOREIGN_RUN = 3


def fold_foreign_in_hebrew_word(text):
    """Spell a foreign-alphabet run that sits INSIDE a Hebrew word back into
    Hebrew letters (Cyrillic, Greek, Armenian).

    Only ever touches a run with a Hebrew letter directly against it on at
    least one side, so a foreign word standing on its own -- a quote, a name,
    a title -- is left exactly as written. Adds Hebrew and removes nothing
    else, so no cue, line or Hebrew character can be lost. Never raises.
    """
    if not text:
        return text
    try:
        if not _FOREIGN_RUN_RE.search(text):
            return text
        out = []
        for line in text.split('\n'):
            cr = '\r' if line.endswith('\r') else ''
            body = line[:-1] if cr else line
            if _HAS_HEBREW_RE.search(body):
                def _sub(m, _b=body):
                    run = m.group(0)
                    if len(run) > _MAX_FOREIGN_RUN:
                        return run
                    before = _b[m.start() - 1:m.start()] if m.start() else ''
                    after = _b[m.end():m.end() + 1]
                    if not ((before and _HAS_HEBREW_RE.match(before))
                            or (after and _HAS_HEBREW_RE.match(after))):
                        return run
                    he = [_FOREIGN2HE[c] for c in run]
                    if not (after and _HAS_HEBREW_RE.match(after)):
                        he[-1] = _HE_FINAL.get(he[-1], he[-1])
                    return u''.join(he)
                body = _FOREIGN_RUN_RE.sub(_sub, body)
            out.append(body + cr)
        return '\n'.join(out)
    except Exception:
        return text


def may_carry_arabic_leak(path=None, pool_kind=None):
    """Whether these bytes could contain a leak from the AI's gender reference.

    The ONE place that rule lives. strip_leaked_arabic() repairs a defect only
    the gender-reference prompt can produce, so it must not run on anything that
    prompt never touched -- and there turned out to be three such sources, each
    found separately, each after the previous fix had been declared complete:

      * a Ktuvit row mirrored into the community pool -- a HUMAN Hebrew subtitle
        (identified by pool_kind, which is why that argument exists);
      * a Google Translate fallback -- no cast/gender mechanism at all, and it
        writes into cache/translated/ alongside real AI output, so only the
        '.google' sidecar tells them apart;
      * a file of unknown origin sitting next to the video, which is exempted at
        its call site because nothing here can identify it.

    Any of them may legitimately quote Arabic ('הוא אמר "אינשאללה" (إن شاء الله)')
    and would come back with the quote deleted and empty brackets left behind.

    It is a shared function rather than a check at each call site because the
    check WAS at each call site, and the fourth, fifth and sixth repair paths
    silently did not get it. A rule with more than one home has no home.
    """
    try:
        if pool_kind is not None and str(pool_kind).strip().lower() == 'ktuvit':
            return False
        if is_google_translated(path):
            return False
    except Exception:
        # Provenance UNKNOWN. Answer no: stripping deletes text, and this
        # module's stated preference throughout is a visible defect over a
        # silent one. Leaving a stray Arabic word on screen is reportable;
        # deleting a quote out of someone's subtitle is not.
        return False
    return True


def is_google_translated(path):
    """True when a '<path>.google' sidecar marks this file as a Google Translate
    fallback. Lives here, next to the rule that consumes it, so there is exactly
    ONE implementation -- translate.py calls this rather than keeping its own
    copy. A signal with two readers drifts the same way a rule with two homes.

    Deliberately does NOT swallow errors, because its two callers want OPPOSITE
    answers when the signal cannot be read: refusing to strip is the safe
    failure for a repair that deletes text, while refusing to SHARE is the safe
    failure for pool contribution. A single fail direction here would be wrong
    for one of them, so each catches and decides. (os.path.exists already
    absorbs ordinary filesystem errors; this is about a malformed path.)
    """
    return bool(path) and os.path.exists(path + '.google')


def strip_leaked_arabic(text):
    """Remove Arabic that leaked from the gender reference into a Hebrew line.

    HARD GUARANTEE, and the reason this is written the narrow way it is: no cue
    is ever removed, no LINE is ever removed, and no line ever loses its Hebrew.
    All this does is rewrite Arabic characters on a line that ALSO contains
    Hebrew -- i.e. a contaminated translation, which is the shape that was
    actually reported ("Arabic word completions / half words" inside otherwise
    correct lines). The Hebrew on that line always survives, so a cue can never
    turn into silence while people are talking.

    Two different rewrites, because there are two different leaks. A run GLUED
    to a Hebrew letter is the model spelling a Hebrew word in the wrong script,
    and is transliterated back into Hebrew letters (see _transliterate_glued_run
    -- that path only adds Hebrew, so it cannot touch the guarantee above). A
    run standing on its own is a pasted Arabic word and is deleted, as before.

    A line that is ENTIRELY Arabic is deliberately left alone. Structurally it
    is indistinguishable from a leaked reference line that happened to land on
    its own wrapped line, and there is no way to tell the two apart from the
    text: one is an on-screen sign or a deliberately untranslated line, the
    other is a leak. Dropping it would fix the leak at the cost of silently
    deleting real content -- and a stray visible line is a defect a user can see
    and report, whereas missing dialogue is one they cannot. An earlier revision
    dropped such lines; review found it destroying a genuine Arabic sign that
    shared a cue with a contaminated line, and it was reverted for this reason.
    That residual is accepted, and it is the ONLY case this does not cover.

    Index and timecode lines have no Hebrew, so they can never match. Never
    raises into the caller.
    """
    if not text:
        return text
    try:
        if not _HAS_ARABIC_RE.search(text):
            return text            # overwhelmingly the common case: no-op
        out = []
        for line in text.split('\n'):
            cr = '\r' if line.endswith('\r') else ''
            body = line[:-1] if cr else line
            if (_HAS_ARABIC_RE.search(body)
                    and _HAS_HEBREW_RE.search(body)):
                cleaned = _clean_arabic_from_line(body)
                # Only accept the rewrite if the Hebrew came through it. Any
                # other outcome means the cleanup misread the line, and the
                # original is always the safer answer.
                if cleaned and _HAS_HEBREW_RE.search(cleaned):
                    body = cleaned
            out.append(body + cr)
        return '\n'.join(out)
    except Exception:
        return text


# --- content-based SDH detection (Phase 3) -----------------------------------
# Music glyphs an SDH sub uses to mark lyrics.
_SDH_MUSIC_GLYPHS = '♪♫♬♩'
# A bracketed cue that carries a real sound/action description -- REQUIRES two
# consecutive letters inside, so a bare "[2020]" / "(?)" / "(!)" never counts
# (those are not SDH markers). Classes are bracket-free so there is no
# catastrophic backtracking on cue-sized text.
_SDH_BRACKET_RE = re.compile(
    r'[\[\(\{][^\[\]\(\){}]*[A-Za-z]{2,}[^\[\]\(\){}]*[\]\)\}]')


def sdh_content_stats(text):
    """Scan cue entries for hearing-impaired / SDH content markers: a bracketed
    sound/action cue ("[door creaks]"), a leading ALL-CAPS speaker label
    ("MABEL:"), or a music glyph. Returns (total_entries, annotated_entries,
    ratio). A plain sub scores ~0; an SDH sub is heavily annotated. Only counts
    entries that actually have dialogue text. Never raises."""
    try:
        blocks = parse_blocks(text)
    except Exception:
        return (0, 0, 0.0)
    total = 0
    annotated = 0
    for b in blocks:
        try:
            t = block_text_only(b)
        except Exception:
            continue
        if not t:
            continue
        total += 1
        if (any(g in t for g in _SDH_MUSIC_GLYPHS)
                or _SDH_BRACKET_RE.search(t)
                or any(_SPEAKER_RE.match(ln.strip()) for ln in t.split('\n'))):
            annotated += 1
    ratio = (annotated / float(total)) if total else 0.0
    return (total, annotated, ratio)


def is_sdh_content(text, min_entries=20, min_annotated=12, min_ratio=0.12):
    """Conservative content-based SDH classifier. HIGH precision is the explicit
    design goal (zero false positives): it returns True ONLY when a substantial,
    DENSE fraction of entries carry SDH markers -- a regular subtitle (whose
    marker ratio sits well under a couple of percent) can never cross all three
    thresholds, while a genuinely hearing-impaired sub clears them with margin.
    Used AFTER download (the text isn't available when the list is built) to
    learn a release's SDH-ness for future ranking. Never raises."""
    try:
        total, annotated, ratio = sdh_content_stats(text)
    except Exception:
        return False
    return total >= min_entries and annotated >= min_annotated and ratio >= min_ratio


# --- AI output hygiene ------------------------------------------------------
# Two defects reported from the field, both from the same gap: nothing cleans
# the text the model returns before it is written and handed to the player.

# Written with \u escapes ONLY, never with the characters themselves. A
# literal U+FB1D pasted into source is one editor-normalisation away from
# becoming the yod+hiriq PAIR it decomposes to, which silently turns the
# class into a range STARTING AT U+05B4 -- one that swallows Arabic, CJK and
# the Latin ligatures. That exact mistake was made in this file and caught by
# a test. Do not replace these with the characters they stand for.
_HEB_RE = re.compile('[\u0590-\u05FF\uFB1D-\uFB4F]')
# Zero-width and bidi controls. They are invisible, they survive every existing
# repair, and a player that lacks a glyph draws them as a box.
#
# Built from _INVISIBLE_BIDI rather than from a second hand-rolled range. That
# list is this module's existing answer to the same question, _fix_one_text_line
# already strips exactly it, and two character lists that are meant to agree
# will eventually stop agreeing. The zero-width three are the only additions:
# they are not direction controls, so _INVISIBLE_BIDI never needed them, but
# they are invisible and a font without them draws a box just the same.
_ZERO_WIDTH = '\u200B\u200C\u200D'   # ZWSP, ZWNJ, ZWJ
# The Hebrew presentation-form block. NFC handles most of it; the compatibility
# forms in it need NFKC, which is why this range is picked out by itself.
_HEB_PRESENTATION_RE = re.compile('[\uFB1D-\uFB4F]')
# SRT styling tags ('<i>', '</font>') and ASS-style overrides ('{\\an8}'), used
# only to ask whether a line carries any real text of its own.
_MARKUP_RE = re.compile(r'<[^>]*>|\{[^}]*\}')
_INVISIBLE_RE = re.compile('[' + re.escape(_INVISIBLE_BIDI + _ZERO_WIDTH) + ']')


def normalize_glyphs(text):
    """Fold the text to characters the build's fonts can actually draw.

    Reported as "a square instead of one letter, mid-word" -- a box is the
    player saying it has no glyph for that codepoint. The usual culprit is a
    Hebrew PRESENTATION FORM: U+FB1D-U+FB4F holds precomposed letter+niqqud and
    ligature variants (U+FB1D is yod-with-hiriq, which looks like a plain yod
    and is not one), and the fonts shipped here do not cover that block. NFC
    normalisation decomposes those back to ordinary letters, so the same word
    renders with the ordinary glyph the font does have.

    NFC alone is not enough for all of them. It leaves the WIDE letters
    (U+FB21-FB28), ALTERNATIVE AYIN (U+FB20), ALTERNATIVE PLUS (U+FB29) and
    LIGATURE ALEF LAMED (U+FB4F) exactly as they are -- those are compatibility
    forms, not canonical ones, so only NFKC folds them. NFKC is applied to that
    block ALONE and nothing else: run over the whole text it would also rewrite
    unrelated characters a subtitle may legitimately contain (the fi ligature,
    fullwidth forms, superscripts, '½' into '1/2'), which is a different and
    unwanted change. Per-character on U+FB1D-FB4F it can only ever turn a
    Hebrew presentation form into the ordinary Hebrew letters it stands for.

    Also drops zero-width and bidi-control characters. They are invisible by
    definition, so removing them cannot change what a correct line looks like,
    and they are the other thing that shows up as a box.

    Applies to ANY subtitle, whatever produced it: it only ever replaces a
    character with the canonical spelling of that same character. Never raises.

    ORDER MATTERS. The invisible set includes RLE/PDF, which is deliberate --
    _fix_one_text_line strips them too, and that is what makes the rtl_base wrap
    idempotent. But it means this must run BEFORE fix_rtl_punctuation, never
    after: run it after and it removes the very wrap that call just added,
    silently undoing the RTL fix for every line. Both callers order it that way
    and test_wiring pins it.
    """
    if not text:
        return text
    try:
        import unicodedata
        out = unicodedata.normalize('NFC', text)
        if _HEB_PRESENTATION_RE.search(out):
            out = _HEB_PRESENTATION_RE.sub(
                lambda m: unicodedata.normalize('NFKC', m.group(0)), out)
        out = _INVISIBLE_RE.sub('', out)
        return out
    except Exception:
        return text


def strip_source_echo(text):
    """Drop source-language lines the model emitted above its own translation.

    Reported as three English lines followed by three Hebrew ones inside a
    single cue. The model occasionally answers with the original AND the
    translation stacked; it is not deterministic, which is why the same title
    can come back clean on a second run and why a copy fetched from the pool
    (a different run, by a different user) can be clean while a local one is
    not. Nothing on either side removed it.

    Narrow on purpose, in the same spirit as strip_leaked_arabic: a cue is only
    touched when its leading lines carry NO Hebrew at all and a later line
    DOES. That is the echo shape and nothing else -- the Hebrew is always the
    part that survives, so a cue can never become empty, and a subtitle with no
    Hebrew in it (a foreign cue, a sign, a song credit, a line the model
    declined to translate) is never altered, because there is no Hebrew line
    for the non-Hebrew ones to be an echo OF. A line with any Hebrew in it
    counts as Hebrew, so 'נולדתי בChina' is never a candidate either.

    WHAT THIS CAN COST, stated plainly rather than left to be discovered. The
    shape is a heuristic, and these are indistinguishable from an echo:

      * a cue the model translated only PARTLY -- one line rendered, one left
        in the source language;
      * a leading line that is legitimately not Hebrew and not a duplicate --
        a brand name ('STARBUCKS'), an on-screen clock ('12:00 PM'), a chyron.

    In those the leading line is deleted and only the Hebrew is kept. The bet
    is that inside OUR OWN model's output -- which is all this ever sees, via
    the ai_output gate -- a non-Hebrew line sitting directly above a Hebrew one
    is overwhelmingly the echo defect rather than any of the above. Cues with
    no Hebrew, the far more common way untranslated text survives, are exempt
    entirely. Two things are refused outright because the damage would exceed
    the defect: emptying a cue, and orphaning a styling tag.

    Never raises into the caller.

    Cues are separated by scanning for blank lines rather than by splitting on
    '\\n\\n', because SRT is conventionally a CRLF format and in a CRLF file the
    cue separator is '\\r\\n\\r\\n' -- which contains no '\\n\\n' at all. Splitting
    on the literal would hand the whole file back as ONE cue, and the fix would
    then apply to the first cue only and silently skip every echo after it. The
    only caller today reads in text mode, so it never sees a '\\r'; this does not
    depend on that staying true. A line keeps whatever '\\r' it arrived with, so
    the file's line endings come back exactly as they went in.
    """
    if not text:
        return text
    try:
        if not _HEB_RE.search(text):
            return text
        lines = text.split('\n')
        out, cue, changed = [], [], False

        def _flush(cue):
            # Keep the index + timecode lines exactly as they are; the cue body
            # is whatever follows the '-->' line.
            head = 0
            for i, ln in enumerate(cue):
                if '-->' in ln:
                    head = i + 1
                    break
            body = cue[head:]
            if len(body) < 2 or not any(_HEB_RE.search(l) for l in body):
                return cue, False
            first_heb = next(i for i, l in enumerate(body)
                             if _HEB_RE.search(l))
            # Only a LEADING run of non-Hebrew lines counts as an echo. There is
            # no blank-line check here because a blank line cannot reach this
            # point: blanks delimit cues in the loop below, so every line in
            # `cue` is real text. Layout is preserved by never entering a cue
            # that a blank line already ended.
            #
            # A lead line that is PURE MARKUP is not an echo and must not go.
            # '<i>' on its own line above a Hebrew line is formatting, and
            # dropping it strands the matching '</i>' below -- which does not
            # merely lose a line, it corrupts the styling of everything after
            # it. Anything with real text left after tags are removed is still
            # a candidate; only the empty ones veto the cue.
            lead = body[:first_heb]
            if lead and all(_MARKUP_RE.sub('', l).strip() for l in lead):
                return cue[:head] + body[first_heb:], True
            return cue, False

        for ln in lines:
            if ln.strip():
                cue.append(ln)
                continue
            kept, hit = _flush(cue)
            out.extend(kept)
            out.append(ln)          # the separator, '\r' and all
            cue, changed = [], changed or hit
        kept, hit = _flush(cue)
        out.extend(kept)
        changed = changed or hit
        return '\n'.join(out) if changed else text
    except Exception:
        return text
