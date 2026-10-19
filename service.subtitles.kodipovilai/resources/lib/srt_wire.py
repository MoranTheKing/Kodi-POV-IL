# -*- coding: utf-8 -*-
"""Numbered entries without timecodes, for the translation request.

Gemini used to be handed every cue WITH its timecode line and asked to copy
it back verbatim. The reply's timecodes were never used -- translate.py puts
the source timecode back on every block -- so they were output tokens spent
for nothing (and a typo in one was a failure to repair). Ported from SRT AI
Translator NG's index/text request (MIT, Akila3): the request carries only

    17
    the text of entry 17

and the reply comes back in the same shape. from_wire() rebuilds full SRT
blocks from the reply, taking every timecode from the source block of the
same number, so everything downstream (integrity gates, top-ups, the
progressive preview) sees the SRT it always saw.
"""
import re

_TIMECODE = re.compile(
    r'^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}')
_FENCE = re.compile(r'^```[a-zA-Z]*[ \t]*\n?|\n?```\s*$')


def _split(block):
    lines = (block or '').replace('\r\n', '\n').replace('\r', '\n').strip('\n').split('\n')
    return lines


def to_wire(blocks):
    """'N\\ntext' for every SRT block whose first line is its number and whose
    second line is a timecode; any other block is passed through as is."""
    out = []
    for block in blocks:
        lines = _split(block)
        if len(lines) >= 2 and lines[0].strip().isdigit() and _TIMECODE.match(lines[1]):
            out.append('\n'.join([lines[0].strip()] + lines[2:]))
        else:
            out.append(block)
    return out


def from_wire(source_blocks, reply):
    """The reply as SRT text: every entry the reply holds for a number of
    `source_blocks`, with that source block's timecode, in reply order.

    An entry is a number line of a requested entry followed by text lines.
    A timecode line the model added anyway is dropped (the source one wins).
    A requested number on its own line inside an entry starts the next entry
    when it is a later number not seen yet (two entries welded together).
    Text before the first number (a preface) is dropped. A reply that already
    carries timecodes on every entry is returned unchanged.
    """
    timecode = {}
    order = []
    for block in source_blocks:
        lines = _split(block)
        if len(lines) >= 2 and lines[0].strip().isdigit() and _TIMECODE.match(lines[1]):
            n = int(lines[0].strip())
            if n not in timecode:
                timecode[n] = lines[1].strip()
                order.append(n)
    text = (reply or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if text.startswith('```'):
        text = _FENCE.sub('', text).strip()
    if not timecode or not text:
        return reply or ''
    # Already SRT (the model ignored the format, or an older caller): keep it.
    raw_blocks = [b for b in re.split(r'\n\s*\n', text) if b.strip()]
    if raw_blocks and all(len(_split(b)) >= 2 and _TIMECODE.match(_split(b)[1])
                          for b in raw_blocks):
        return reply

    position = dict((n, i) for i, n in enumerate(order))
    entries = []          # [number, [text lines]]
    seen = set()
    prev_blank = True
    for line in text.split('\n'):
        s = line.strip()
        num = int(s) if s.isdigit() else None
        starts = False
        if num is not None and num in timecode and num not in seen:
            if not entries:
                starts = True
            elif entries[-1][0] is None:
                starts = prev_blank
            else:
                cur = position[entries[-1][0]]
                # After a blank line: any requested entry not seen yet (even
                # out of order). Welded (no blank line): only the very next
                # entry, and only once the current one has text -- so a cue
                # whose whole text is "18" is not read as entry 18.
                starts = prev_blank or bool(
                    entries[-1][1] and position[num] == cur + 1)
        if not starts and num is not None and prev_blank and entries:
            # A header nobody asked for, or a repeat of one already taken
            # (the first wins): its lines belong to no requested entry.
            entries.append([None, []])
            prev_blank = False
            continue
        prev_blank = not s
        if starts:
            entries.append([num, []])
            seen.add(num)
            continue
        if not entries:
            continue      # a preface before the first entry
        if not s:
            continue
        if _TIMECODE.match(s) and not entries[-1][1]:
            continue      # the model echoed a timecode anyway
        entries[-1][1].append(line.rstrip())
    out = []
    for num, lines in entries:
        if num is not None and lines:
            out.append('\n'.join(['%d' % num, timecode[num]] + lines))
    return '\n\n'.join(out)
