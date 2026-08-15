#!/usr/bin/env python3
"""Reproduce the field defect from the screenshot, then prove the fix.

The screenshot showed ONE cue rendering its own Hebrew line plus the raw
"286" and "00:15:51,284 --> 00:15:54,054" of the cue that should have come
next. So the test is not "does a helper split a string" -- it is: run the
model's reply through the SAME two calls translate.py makes (parse_blocks +
restore_block_timings) and look at what the player would be handed.

A test that only called _split_welded_block would pass even if parse_blocks
never called it, so the reproduction goes through the public path.

Run: python3 tools/test_welded_blocks.py
"""

import importlib.util
import re
import sys

import os

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(HERE, '..', 'addons', 'service.subtitles.kodipovilai')
LIB = os.path.join(ADDON, 'resources', 'lib')
spec = importlib.util.spec_from_file_location('srt', os.path.join(LIB, 'srt.py'))
srt = importlib.util.module_from_spec(spec)
sys.modules['srt'] = srt
spec.loader.exec_module(srt)

# The source chunk the model was given (3 entries, well-formed).
SRC = (
    '285\n'
    '00:15:48,100 --> 00:15:50,900\n'
    "You're not gonna believe this.\n"
    '\n'
    '286\n'
    '00:15:51,284 --> 00:15:54,054\n'
    'They found the car in the river.\n'
    '\n'
    '287\n'
    '00:15:54,900 --> 00:15:57,100\n'
    'Nobody was inside.\n'
)

# The model's reply, with the blank line before entry 286 dropped -- the
# defect. Everything else is a faithful translation.
REPLY_BAD = (
    '285\n'
    '00:15:48,100 --> 00:15:50,900\n'
    'אתה לא תאמין לזה.\n'
    '286\n'
    '00:15:51,284 --> 00:15:54,054\n'
    'הם מצאו את המכונית בנהר.\n'
    '\n'
    '287\n'
    '00:15:54,900 --> 00:15:57,100\n'
    'אף אחד לא היה בפנים.\n'
)

FAIL = []


def cue_text(block):
    """The lines the PLAYER would draw for this block."""
    lines = block.split('\n')
    out = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if i == 0 and srt._INDEX_RE.match(s):
            continue
        if i <= 1 and srt._TIMECODE_RE.match(s):
            continue
        out.append(ln)
    return '\n'.join(out).strip()


# srt._TIMECODE_RE is ^-anchored and compiled WITHOUT re.M, so .search() on a
# multi-line cue silently never matches -- the first version of this file used
# it as the leak detector and every leak check passed vacuously. The sabotage
# case below is what exposed that. Detect on our own multiline pattern instead.
_LEAK_TC = re.compile(r'(?m)^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->')
_LEAK_IDX = re.compile(r'(?m)^\s*\d+\s*$')


def leaks(text):
    """True when a cue's drawn text carries an entry header inside it."""
    return bool(_LEAK_TC.search(text) or _LEAK_IDX.search(text))


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


src_blocks = srt.parse_blocks(SRC)
out_blocks = srt.parse_blocks(REPLY_BAD)
fixed = srt.restore_block_timings(src_blocks, out_blocks)

print('source blocks : %d' % len(src_blocks))
print('reply blocks  : %d' % len(out_blocks))
print()
for i, b in enumerate(fixed):
    print('--- delivered cue %d ---' % (i + 1))
    print(cue_text(b))
print()

check('the welded reply parses back into 3 entries', len(out_blocks) == 3,
      'got %d' % len(out_blocks))
check('3 cues are delivered', len(fixed) == 3, 'got %d' % len(fixed))

leaked = [i + 1 for i, b in enumerate(fixed) if leaks(cue_text(b))]
check('no cue text contains an index or a timecode', not leaked,
      'leaked in cue(s) %s' % leaked)

if len(fixed) == 3:
    check('cue 285 shows only its own line',
          cue_text(fixed[0]) == 'אתה לא תאמין לזה.',
          repr(cue_text(fixed[0])))
    check('cue 286 survived as its own cue',
          cue_text(fixed[1]) == 'הם מצאו את המכונית בנהר.',
          repr(cue_text(fixed[1])))
    check("cue 286 kept the source's timecode",
          '00:15:51,284 --> 00:15:54,054' in fixed[1],
          repr(fixed[1]))

# --- the fix must not touch anything that was already correct --------------
REPLY_GOOD = (
    '285\n00:15:48,100 --> 00:15:50,900\nאתה לא תאמין לזה.\n\n'
    '286\n00:15:51,284 --> 00:15:54,054\nהם מצאו את המכונית בנהר.\n\n'
    '287\n00:15:54,900 --> 00:15:57,100\nאף אחד לא היה בפנים.\n'
)
good = srt.parse_blocks(REPLY_GOOD)
check('a well-formed reply still parses to 3 blocks', len(good) == 3,
      'got %d' % len(good))
check('a well-formed reply is returned byte-identical',
      good == [b for b in re.split(r'\r?\n\r?\n', REPLY_GOOD.strip())
               if b.strip()])

# A bare number in DIALOGUE must stay dialogue -- it is only an entry header
# when a timecode follows it.
DIALOGUE_NUM = (
    '12\n00:01:00,000 --> 00:01:02,000\nהוא ניצח\n1986\nוזה הכל.\n\n'
    '13\n00:01:03,000 --> 00:01:05,000\nכן.\n'
)
dn = srt.parse_blocks(DIALOGUE_NUM)
check('a year on its own line is not treated as an entry header',
      len(dn) == 2 and '1986' in dn[0], repr(dn))

# CRLF must survive: the cut rejoins the ORIGINAL lines, not stripped ones.
CRLF = ('285\r\n00:15:48,100 --> 00:15:50,900\r\nא.\r\n'
        '286\r\n00:15:51,284 --> 00:15:54,054\r\nב.\r\n')
cr = srt.parse_blocks(CRLF)
check('a CRLF welded block splits into 2', len(cr) == 2, repr(cr))
# Not "a \r appears somewhere" -- that passes even when the \r is in the WRONG
# place. Assert the exact blocks, and that neither carries a trailing CR with
# no LF behind it (an artefact a BLOCK_SEPARATOR-produced block never has).
check('the CRLF split produces exactly the right two blocks',
      cr == ['285\r\n00:15:48,100 --> 00:15:50,900\r\nא.',
             '286\r\n00:15:51,284 --> 00:15:54,054\r\nב.'], repr(cr))
check('no block ends in a stray CR', not any(b.endswith('\r') for b in cr),
      repr(cr))

# Three entries welded into one block, not just two.
TRIPLE = ('1\n00:00:01,000 --> 00:00:02,000\nא\n'
          '2\n00:00:03,000 --> 00:00:04,000\nב\n'
          '3\n00:00:05,000 --> 00:00:06,000\nג\n')
tr = srt.parse_blocks(TRIPLE)
check('three welded entries split into 3', len(tr) == 3, repr(tr))

# The model dropped the INDEX as well as the blank line: a timecode alone
# inside the text is still an entry boundary.
NO_INDEX = ('1\n00:00:01,000 --> 00:00:02,000\nא\n'
            '00:00:03,000 --> 00:00:04,000\nב\n')
ni = srt.parse_blocks(NO_INDEX)
check('a bare timecode inside the text also splits', len(ni) == 2, repr(ni))
check('and each half keeps its own dialogue',
      ni == ['1\n00:00:01,000 --> 00:00:02,000\nא',
             '00:00:03,000 --> 00:00:04,000\nב'], repr(ni))

# A cue whose ONLY dialogue is a bare number, welded to an entry that also
# lost its index. Cutting in front of the number would delete it outright --
# the cue above loses its text and the cue below eats the number as its index,
# so it never reaches the screen. Silent deletion is worse than the weld.
BARE_NUMBER = ('5\n00:01:00,000 --> 00:01:02,000\n42\n'
               '00:01:02,500 --> 00:01:04,000\nNext line\n')
bn = srt.parse_blocks(BARE_NUMBER)
check('a bare-number cue still splits into 2', len(bn) == 2, repr(bn))
check('the bare number survives as the first cue\'s text',
      len(bn) == 2 and bn[0].split('\n')[-1].strip() == '42', repr(bn))
check('the second cue did not swallow the number as its index',
      len(bn) == 2 and not bn[1].startswith('42'), repr(bn))

# ...but when the entry above DOES have text, the number is an index again.
NORMAL_IDX = ('5\n00:01:00,000 --> 00:01:02,000\nשלום\n'
              '6\n00:01:02,500 --> 00:01:04,000\nלהתראות\n')
ni2 = srt.parse_blocks(NORMAL_IDX)
check('with text above it, the digits ARE the next index',
      len(ni2) == 2 and ni2[1].startswith('6\n'), repr(ni2))

# The validator's case, reproduced by execution: entry 41's ONLY dialogue is
# "42", and the entry welded after it opens with index "50". The first version
# of _has_text_line called every digits-only line a header, so it answered "41
# has no text" and left the cut at the timecode -- stranding "50" inside 41 as
# a second line of dialogue nobody wrote.
VALIDATOR_CASE = ('41\n00:10:00,000 --> 00:10:02,000\n42\n'
                  '50\n00:10:05,000 --> 00:10:07,000\nForty-two, he confirmed.\n')
vc = srt.parse_blocks(VALIDATOR_CASE)
check('the validator case splits into 2', len(vc) == 2, repr(vc))
check('entry 41 shows ONLY its own "42"',
      len(vc) == 2 and vc[0].split('\n')[2:] == ['42'], repr(vc))
check('the next index is not left inside the cue above',
      len(vc) == 2 and '50' not in vc[0].split('\n')[2:], repr(vc))
check('the next entry keeps its own index',
      len(vc) == 2 and vc[1].startswith('50\n'), repr(vc))

# --- the guard the whole thing rests on: SABOTAGE ---------------------------
# If _split_welded_block is neutered, the reproduction must go RED again.
# Without this the suite could be green because the defect never reproduced.
_real = srt._split_welded_block
srt._split_welded_block = lambda b: [b]
sab = srt.parse_blocks(REPLY_BAD)
sab_fixed = srt.restore_block_timings(src_blocks, sab)
sab_leak = any(leaks(cue_text(b)) for b in sab_fixed)
srt._split_welded_block = _real
print()
check('SABOTAGE: with the split disabled the defect reproduces',
      len(sab) == 2 and sab_leak,
      'blocks=%d leak=%s -- the test cannot fail, so it proves nothing'
      % (len(sab), sab_leak))

print()
print('FAILED: %d' % len(FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
