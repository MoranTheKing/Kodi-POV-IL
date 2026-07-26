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


def parse_blocks(text):
    """Return a list of raw entry blocks (still strings). We don't
    bother with a structured parse since the model handles the
    timecodes verbatim -- if we round-trip strings unchanged for
    those, we minimise damage from accidental edits."""
    if not text:
        return []
    # Some SRTs start with a BOM. Strip it once.
    if text.startswith('﻿'):
        text = text[1:]
    text = text.strip()
    return [b for b in BLOCK_SEPARATOR.split(text) if b.strip()]


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
_OVERLAP_GRACE_MS = 10000  # how far a cue may legitimately outlive the next cue's
#                            start (signs over dialogue, dual-speaker overlap)
_MIN_CUE_MS = 400
_DEFAULT_CUE_MS = 2000
_START_MATCH_MIN_RATIO = 0.9   # positional pairing must look this right to trust
_NEXT_SCAN_MAX = 200           # bound the search for the next later-starting cue

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


def restore_block_timings(src_blocks, out_blocks):
    """Give every translated block its SOURCE index + timecode line back.

    The model is asked to copy timings verbatim; it usually does, and when it
    does this is a no-op. When it does not, this is the difference between a
    correct subtitle and one with a line welded to the screen.

    Pairing is positional, but positional pairing is VERIFIED before it is
    trusted: equal block counts are necessary and not sufficient (a stray blank
    line inside the model's reply can split one cue into two while another is
    dropped, keeping the count intact but shifting everything after it). So the
    start timestamps of each pair are compared, and positional pairing is used
    only when they agree for nearly every block -- the remaining disagreements
    are exactly the corrupted timestamps we are here to repair.

    When the counts differ, or positional pairing does not look right, each
    output block is instead matched to the source block with the SAME START
    (forward-scanning, so duplicate starts still consume in order). That covers
    the common "Gemini silently dropped an entry" case, which the caller accepts
    without retrying at up to 15% loss, and which a positional pass would
    otherwise mis-pair into corrupting every following cue.

    Fully fail-open: any surprise returns the input unchanged.
    """
    try:
        if not out_blocks or not src_blocks:
            return out_blocks
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
            if comparable and (agree / float(comparable)) >= _START_MATCH_MIN_RATIO:
                return [(_rebuild_block(src, out) or out) for src, out in pairs]
        # Counts differ, or the positional alignment looked wrong: repair only
        # what can be identified positively, and leave the rest to the clamp.
        by_start = {}
        for i, src in enumerate(src_blocks):
            st = _block_start(src)
            if st is not None:
                by_start.setdefault(st, []).append(i)
        used = set()
        fixed = []
        for out in out_blocks:
            st = _block_start(out)
            idxs = by_start.get(st) if st is not None else None
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
        return fixed
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
