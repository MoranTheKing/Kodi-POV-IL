#!/usr/bin/env python3
"""Overlapping helper cues cannot disappear from the gender-reference lookup."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addons' /
                       'service.subtitles.kodipovilai'))
from resources.lib import arabic_gender as gender  # noqa: E402


def block(number, start, end, text):
    def stamp(ms):
        seconds, milli = divmod(ms, 1000)
        return '00:%02d:%02d,%03d' % (seconds // 60, seconds % 60, milli)
    return '%d\n%s --> %s\n%s' % (
        number, stamp(start), stamp(end), text)


# Starts are ordered, but ends are 5000, 1700, 2300. The first, long helper
# line is the largest true overlap for the source cue at 1800-2500 ms.
helper = [
    {'start': 1000, 'end': 5000, 'text': 'Long feminine dialogue'},
    {'start': 1500, 'end': 1700, 'text': 'Short earlier dialogue'},
    {'start': 2000, 'end': 2300, 'text': 'Short masculine dialogue'},
]
source = block(1, 1800, 2500, 'You are ready.')
mapped = gender._arabic_for_blocks([source], helper, 1.0, 0.0)
assert mapped == {1: 'Long feminine dialogue'}, mapped

# A source line entirely after the long cue must not inherit it.
later = block(2, 5100, 5500, 'You should go.')
assert gender._arabic_for_blocks([later], helper, 1.0, 0.0) == {}

# The overlap-rate calculation uses the same reference structure. A monotone
# start order does not imply monotone ends, so this should still count.
source_cues = [{'start': 1800, 'end': 2500}]
assert gender._overlap_rate(source_cues, helper, 1.0, 0.0) == 1.0

# Exercise the real align_one gate too, not only the lookup helper. The long
# overlapping Hebrew cue carries the translation of source entry 6; the short
# cue is unrelated dialogue. Most other entries establish the identity clock.
source_blocks = []
reference_blocks = []
for number in range(1, 31):
    start = number * 3000
    source_blocks.append(block(number, start, start + 700,
                               'You are ready.' if number == 6
                               else 'Source dialogue %d' % number))
    if number == 5:
        start, end, text = 15000, 19000, 'את מוכנה.'
    elif number == 6:
        start, end, text = 17500, 17700, 'לא עכשיו.'
    elif number == 7:
        start, end, text = 18000, 18300, 'אין בעיה.'
    else:
        end, text = start + 700, 'משפט מספר %d' % number
    reference_blocks.append(block(number, start, end, text))
aligned, diagnostic = gender.align_one(
    '\n\n'.join(source_blocks), source_blocks,
    '\n\n'.join(reference_blocks))
assert aligned is not None, diagnostic
assert aligned[6] == 'את מוכנה.', (aligned[6], diagnostic)
print('PASS overlapping gender-reference cues remain visible')
