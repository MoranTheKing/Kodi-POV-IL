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
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or _INDEX_RE.match(stripped) or \
                _TIMECODE_RE.match(stripped):
            out_lines.append(line)
            continue
        if mode == 'legacy':
            out_lines.append(_fix_one_text_line(line))
        else:
            # 'reverse' (default) or anything unrecognised
            out_lines.append(_reverse_fix_one_text_line(line))
    return '\n'.join(out_lines) + trailing_nl


# Match a Hebrew text line that has punctuation at the END (the
# "normal" Hebrew sentence shape). Used by the reverse-mode fix to
# move that punct to the START of the line.
_TRAILING_PUNCT_RE = re.compile(
    r'^(?P<dash>-\s+)?'
    r'(?P<open_tags>(?:<[a-zA-Z!][^>]*>)*)'
    r'(?P<rest>[' + _HEB_LETTER + r'][^\n]*?[' + _HEB_LETTER + r'])'
    r'(?P<trailing>[' + _TRAILING_PUNCT_CHARS + r']+)'
    r'(?P<close_tags>(?:</[a-zA-Z][^>]*>)*)\s*$'
)


def _reverse_fix_one_text_line(line):
    """Move END-of-line punctuation to the START. Used by the
    'reverse' rtl_punct_mode for Kodi setups whose subtitle
    renderer doesn't BiDi-reorder Hebrew lines and shows source
    text in physical L-to-R order."""
    stripped = line.strip()
    while stripped and stripped[0] in _INVISIBLE_BIDI:
        stripped = stripped[1:]
    while stripped and stripped[-1] in _INVISIBLE_BIDI:
        stripped = stripped[:-1]
    if not stripped:
        return line
    m = _TRAILING_PUNCT_RE.match(stripped)
    if not m:
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
        return dash + open_tags + rest + close_tags
    return dash + open_tags + trailing + rest + close_tags


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


def strip_hi_annotations(text):
    """Remove hearing-impaired noise from an SRT body.

    Drops bracketed sound cues like [breathing], (music playing),
    {chuckles}, and ALL-CAPS speaker prefixes like 'MABEL: '. If an
    entry's text was nothing but annotations, the whole entry is
    dropped (its timecode goes too -- there's literally no speech
    in that span, so an empty subtitle would be a visual gap with
    nothing useful).

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
            # text line -- strip annotations
            cleaned = _BRACKET_RE.sub('', line)
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
