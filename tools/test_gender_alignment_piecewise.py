#!/usr/bin/env python3
"""Gender-helper alignment uses the same safe local/piecewise timing engine."""

import os
import random
import sys

ROOT = os.path.join(os.path.dirname(__file__), '..')
ADDON = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai')
sys.path.insert(0, ADDON)

from resources.lib import arabic_gender as ag  # noqa: E402


def stamp(ms):
    ms = int(round(ms))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return '%02d:%02d:%02d,%03d' % (h, m, s, ms)


def srt(cues, prefix):
    return '\n\n'.join(
        '%d\n%s --> %s\n%s %d' %
        (i, stamp(start), stamp(end), prefix, i)
        for i, (start, end) in enumerate(cues, 1)) + '\n'


rng = random.Random(8917)
clock = 12000
base = []
for _ in range(220):
    clock += rng.randint(1700, 5600)
    duration = rng.randint(900, 3100)
    base.append((clock, clock + duration))


def transformed(boundaries, scale=1.0):
    out = []
    for start, end in base:
        offset = boundaries[0][1]
        for boundary, value in boundaries:
            if start >= boundary:
                offset = value
        out.append((scale * start + offset, scale * end + offset))
    return out


source = srt(base, 'Source line')
blocks = source.strip().split('\n\n')
mid = base[len(base) // 2][0]

# This exact shape passed the legacy single-map gate while half the helper was
# 60 seconds wrong.  It must now produce a validated two-region map.
helper = srt(transformed([(0, 0), (mid, 60000)]), 'Arabic line')
mapping, diag = ag.align_one(source, blocks, helper)
assert mapping is not None, diag
assert 'piecewise 2 regions' in diag, diag
assert len(mapping) == len(base), (len(mapping), diag)
for index in range(1, len(base) + 1):
    assert mapping[index] == 'Arabic line %d' % index, (index, mapping[index], diag)

# Several adjacent steps below the automatic 5-second evidence threshold are
# detected as inconsistent but deliberately refused rather than guessed.
third = base[len(base) // 3][0]
two_thirds = base[2 * len(base) // 3][0]
ambiguous = srt(transformed([
    (0, 0), (third, 3000), (mid, 8000), (two_thirds, 12000),
]), 'Arabic line')
mapping, diag = ag.align_one(source, blocks, ambiguous)
assert mapping is None, diag
assert 'local consistency FAILED' in diag, diag

# A crash in the mandatory hardened engine must not revive the legacy global
# vote.  That vote accepts this exact half-file +60s shape and links the second
# half's gender evidence to unrelated dialogue.
from resources.lib import sync_align as _sync_align  # noqa: E402
_original_verify = _sync_align.verify_cue_lists
try:
    def _crash(*_args, **_kwargs):
        raise RuntimeError('sabotage')
    _sync_align.verify_cue_lists = _crash
    mapping, diag = ag.align_one(source, blocks, helper)
finally:
    _sync_align.verify_cue_lists = _original_verify
assert mapping is None, diag
assert 'reference declined' in diag, diag

print('PASS gender helper local-consistency + safe piecewise alignment')
