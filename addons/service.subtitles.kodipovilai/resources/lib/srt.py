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
_TRAILING_PUNCT_CHARS = '.,;:!?'

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
_ELLIPSIS_RE = re.compile(r'^\.{2,}$')


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


def _fix_one_text_line(line):
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
    # Leave legitimate ellipsis alone.
    if _ELLIPSIS_RE.match(leading):
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


def fix_rtl_punctuation(text, mode=None):
    """Normalize RTL punctuation placement in a Hebrew SRT body.

    `mode` controls the direction of the correction. Pulled from
    the addon's `rtl_punct_mode` setting if not explicitly passed:
      'reverse' (default) -- move END-of-sentence punct from line
                             END to line START. Necessary because
                             Kodi's subtitle renderer (across the
                             observed setups -- Windows, Android,
                             FENtastic skin) does NOT BiDi-reorder
                             Hebrew lines, so a logical-START
                             punct visually lands at the end of
                             the Hebrew reader's reading flow.
      'legacy'            -- the inverse: move leading punct to
                             the logical end. Was the default in
                             v0.2.0-v0.2.6 under the (wrong)
                             assumption that Kodi reorders. Kept
                             around in case any setup actually
                             does reorder correctly.
      'rtl_base'          -- do NOT move anything. Instead wrap
                             each Hebrew line in an explicit RTL
                             embedding (RLE..PDF) so the renderer
                             gives it a right-to-left BASE
                             direction. Its own BiDi then places
                             embedded LTR runs (numbers, English
                             names, quoted English), parentheses
                             AND end punctuation correctly -- the
                             root-cause fix for setups whose base
                             direction defaults to LTR. Depends on
                             the renderer honouring the marks, so
                             it is opt-in (verify on-device).
      'off'               -- no processing.

    Idempotent. Skips index + timecode lines. Preserves trailing
    newline so a benign re-run doesn't flag the file as changed."""
    if not text:
        return text
    if mode is None:
        try:
            from . import kodi_utils
            mode = (kodi_utils.get_setting('rtl_punct_mode', 'reverse')
                    or 'reverse').lower()
        except Exception:
            mode = 'reverse'
    # 'auto' was the v0.2.7 name for what is now 'legacy'. Map for
    # backwards compatibility with users who manually selected it.
    if mode == 'auto':
        mode = 'legacy'
    if mode == 'off':
        return text
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
            out_lines.append(_wrap_rtl_base_line(line, cue_hebrew=cue_hebrew))
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
_WRAPPABLE_LATIN_TAIL_RE = re.compile(
    r'^[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*[' + _TRAILING_PUNCT_CHARS + r']$')


def _is_wrappable_latin_tail(s):
    """True for a username/handle-shaped Latin token that is the TAIL of a Hebrew
    sentence wrapped onto its own line (see _WRAPPABLE_LATIN_TAIL_RE). Wrapping it
    in RTL base moves ONLY its trailing period to the RTL-correct (left) side; the
    body is provably never reordered. Non-mutating (marks only). Never raises."""
    return bool(_WRAPPABLE_LATIN_TAIL_RE.match(s))


def _wrap_rtl_base_line(line, cue_hebrew=False):
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
    # Undo any 'reverse'/'legacy' mutation baked into cached/pool text: move a
    # displaced leading sentence-punct back to the logical end. On pristine
    # (fresh AI) text this is a no-op -- Hebrew never authors a leading . , ; : ! ?
    normalized = _fix_one_text_line(s)
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
