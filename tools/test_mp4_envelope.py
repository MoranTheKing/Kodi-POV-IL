#!/usr/bin/env python3
"""Offline tests for the MP4 audio frame-size envelope (SubSync).

Run: python tools/test_mp4_envelope.py
Builds a synthetic movie index (no media files are stored), checks that the
frame-size envelope tells a synced subtitle from a sectionally shifted one in
both encoder polarities, and that weak or ambiguous envelopes decide nothing.
"""
import os
import random
import struct
import sys

LIB = os.path.join(os.path.dirname(__file__), '..',
                   'service.subtitles.kodipovilai', 'resources', 'lib')
sys.path.insert(0, LIB)

import mp4_probe  # noqa: E402
import sync_align as sa  # noqa: E402

FAILS = []


def check(desc, cond, extra=''):
    if cond:
        print('  ok  - ' + desc)
    else:
        FAILS.append(desc)
        print('  FAIL- ' + desc + (' [' + extra + ']' if extra else ''))


def box(kind, payload):
    return struct.pack('>I', 8 + len(payload)) + kind + payload


def full(kind, payload, version=0):
    return box(kind, struct.pack('>I', version << 24) + payload)


def movie_index(sizes, frame_ticks=1024, rate=48000, codec=b'mp4a'):
    mvhd = full(b'mvhd', struct.pack('>IIII', 0, 0, 1000, 0) + b'\0' * 80)
    mdhd = full(b'mdhd', struct.pack('>IIII', 0, 0, rate, 0) + b'\0' * 4)
    hdlr = full(b'hdlr', b'\0' * 4 + b'soun' + b'\0' * 12 + b'\0')
    entry = struct.pack('>I', 36) + codec + b'\0' * 28
    stsd = full(b'stsd', struct.pack('>I', 1) + entry)
    stts = full(b'stts', struct.pack('>III', 1, len(sizes), frame_ticks))
    stsz = full(b'stsz', struct.pack('>II', 0, len(sizes))
                + struct.pack('>%dI' % len(sizes), *sizes))
    stbl = box(b'stbl', stsd + stts + stsz)
    minf = box(b'minf', stbl)
    mdia = box(b'mdia', mdhd + hdlr + minf)
    trak = box(b'trak', mdia)
    return box(b'moov', mvhd + trak)


def speech(seed, minutes=44):
    rng = random.Random(seed)
    t, out = rng.uniform(20000, 60000), []
    while t < minutes * 60000:
        dur = rng.uniform(900, 4200)
        out.append((t, t + dur))
        r = rng.random()
        t += dur + (rng.uniform(80, 700) if r < 0.60 else
                    rng.uniform(700, 3000) if r < 0.95 else
                    rng.uniform(5000, 14000))
    return out


def frame_sizes(intervals, polarity, seed, minutes=44, noise=60):
    """AAC-like frame sizes: speech shifts the size by ``polarity``."""
    rng = random.Random(seed)
    frame_ms = 1024 * 1000.0 / 48000
    count = int(minutes * 60000 / frame_ms)
    starts = [a for a, _b in intervals]
    import bisect
    sizes = []
    for i in range(count):
        t = i * frame_ms
        j = bisect.bisect_right(starts, t) - 1
        talking = j >= 0 and t < intervals[j][1]
        base = 300 + (polarity * 45 if talking else 0)
        sizes.append(max(20, int(base + rng.gauss(0, noise))))
    return sizes


def srt(intervals, offsets=None, bounds=()):
    rows = []
    for n, (a, b) in enumerate(intervals, 1):
        shift = 0.0
        if offsets:
            shift = offsets[sum(a >= x for x in bounds)]
        rows.append('%d\n%s --> %s\nline\n' % (
            n, sa._ms_to_stamp(a + shift), sa._ms_to_stamp(b + shift)))
    return '\n'.join(rows)


print('== envelope from a synthetic movie index ==')
SPEECH = speech(31)
for polarity in (1, -1):
    index = movie_index(frame_sizes(SPEECH, polarity, 32))
    env = mp4_probe.audio_envelope(index)
    check('polarity %+d: AAC envelope extracted' % polarity,
          env is not None and len(env['values']) > 20000,
          '' if env is None else str(len(env['values'])))
    synced = sa.envelope_check(env, srt(SPEECH))
    check('polarity %+d: synced subtitle -> synced' % polarity,
          synced['status'] == 'synced' and synced['polarity'] == polarity,
          str(synced))
    span = SPEECH[-1][1] - SPEECH[0][0]
    bounds = [SPEECH[0][0] + span * f for f in (0.26, 0.45, 0.6, 0.75)]
    steps = sa.envelope_check(env, srt(SPEECH, [0, 1900, 3800, 5900, 7900],
                                        bounds))
    check('polarity %+d: act-pad staircase -> conflict' % polarity,
          steps['status'] == 'conflict', str(steps))
    shifted = sa.envelope_check(env, srt(SPEECH, [4000], ()))
    check('polarity %+d: one 4 s shift -> shifted, never synced' % polarity,
          shifted['status'] == 'shifted', str(shifted))
    other = sa.envelope_check(env, srt(speech(77)))
    check('polarity %+d: unrelated rhythm is never synced' % polarity,
          other['status'] != 'synced', str(other))

print('== nothing is decided from a signal-free envelope ==')
flat = mp4_probe.audio_envelope(movie_index([256] * 120000))
check('constant-size (CBR/AC-3 like) audio yields no envelope', flat is None)
noise_only = mp4_probe.audio_envelope(
    movie_index(frame_sizes(SPEECH, 0, 33)))
quiet = sa.envelope_check(noise_only, srt(SPEECH))
check('speech-blind envelope stays unknown', quiet['status'] == 'unknown',
      str(quiet))
_t0 = __import__('time').time()
check('a corrupt multi-day duration yields no envelope (and no huge buffers)',
      mp4_probe.audio_envelope(movie_index(frame_sizes(SPEECH, 1, 35)[:3000],
                                           frame_ticks=48000 * 600)) is None
      and __import__('time').time() - _t0 < 5.0)
check('a non-AAC track is ignored',
      mp4_probe.audio_envelope(movie_index(frame_sizes(SPEECH, 1, 34),
                                           codec=b'ac-3')) is None)

print('== apply_verdict: the audio-envelope proof ==')
REF = srt(SPEECH)
# Cut inside a real pause, as an act break is: the later act moves 1.9 s
# earlier without touching the line before it.
_gap = min(((b[0] - a[1], (a[1] + b[0]) / 2.0)
            for a, b in zip(SPEECH, SPEECH[1:]) if b[0] - a[1] > 2500),
           key=lambda item: abs(item[1] - 900000.0))[1]
segments = [{'cand_from_ms': None, 'cand_to_ms': _gap, 'offset_ms': 0.0},
            {'cand_from_ms': _gap, 'cand_to_ms': None, 'offset_ms': 1900.0}]
base = {'status': sa.STATUS_FIXABLE, 'mode': 'piecewise', 'scale': 1.0,
        'offset_ms': 0.0, 'segments': segments,
        'validation_required': True, 'validation_folds': 5,
        'timing_family_count': 1}
proof = dict(base, validation_proof='file-audio-envelope-v1',
             envelope_status='synced', envelope_before='conflict',
             envelope_trusted=8, envelope_windows=9, envelope_offset_ms=-300)


def applies(verdict):
    try:
        return bool(sa.apply_verdict(REF, verdict))
    except ValueError:
        return False


check('holdouts + audio envelope proof applies', applies(proof))
check('holdouts alone still cannot apply', not applies(base))
check('an envelope that was already synced proves nothing',
      not applies(dict(proof, envelope_before='synced')))
check('too few strong windows prove nothing',
      not applies(dict(proof, envelope_trusted=4)))
check('a residual beyond 0.9 s proves nothing',
      not applies(dict(proof, envelope_offset_ms=1400)))
check('fewer than four holdout folds prove nothing',
      not applies(dict(proof, validation_folds=3)))

print()
if FAILS:
    print('FAILED (%d):' % len(FAILS))
    for f in FAILS:
        print('  - ' + f)
    sys.exit(1)
print('ALL TESTS PASSED')
