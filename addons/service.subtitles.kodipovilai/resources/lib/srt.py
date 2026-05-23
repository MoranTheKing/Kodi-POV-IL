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
