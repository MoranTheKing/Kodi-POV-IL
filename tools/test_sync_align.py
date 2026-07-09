#!/usr/bin/env python3
"""Offline regression tests for resources/lib/sync_align.py (SubSync S2).

Run: python3 tools/test_sync_align.py
Builds synthetic SRT pairs with KNOWN ground truth (offset, FPS scale,
recuts) and asserts the verdicts + recovered parameters.
"""
import os
import sys
import random

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..',
    'addons', 'service.subtitles.kodipovilai', 'resources', 'lib'))

import sync_align as sa  # noqa: E402

FAILS = []


def check(desc, cond, extra=''):
    if cond:
        print('  ok  - ' + desc)
    else:
        FAILS.append(desc)
        print('  FAIL- ' + desc + (' [' + extra + ']' if extra else ''))


def _stamp(ms):
    ms = int(ms)
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return '%02d:%02d:%02d,%03d' % (h, m, s, ms)


def make_srt(cue_times, lang='en'):
    """SRT text from [(start_ms, dur_ms)] with plausible dialogue lines."""
    lines = {'en': 'Well, that is not what I expected to happen.',
             'he': 'ובכן, זה ממש לא מה שציפיתי שיקרה כאן.'}
    blocks = []
    for i, (start, dur) in enumerate(cue_times, 1):
        blocks.append('%d\n%s --> %s\n%s' % (
            i, _stamp(start), _stamp(start + dur), lines[lang]))
    return '\n\n'.join(blocks) + '\n'


def dialogue_times(n=220, seed=7, span_ms=40 * 60 * 1000):
    """Pseudo-random but deterministic dialogue cue pattern over ~40 min."""
    rng = random.Random(seed)
    t, out = 15000, []
    while len(out) < n and t < span_ms:
        dur = rng.randint(1200, 3800)
        out.append((t, dur))
        t += dur + rng.randint(400, 9000)   # speech + gap
    return out


BASE = dialogue_times()
REF = make_srt(BASE, 'en')


def transformed(scale=1.0, offset=0.0, drop_every=None):
    """Candidate Hebrew cues on the transformed timeline: t' = scale*t+offset.
    drop_every: drop 1 of every N cues (HI/non-HI style differences)."""
    out = []
    for i, (s, d) in enumerate(BASE):
        if drop_every and i % drop_every == 0:
            continue
        out.append((scale * s + offset, scale * d))
    return make_srt(out, 'he')


print('== identical -> CONFIRMED ==')
v = sa.verify(REF, transformed())
check('status CONFIRMED', v['status'] == sa.STATUS_CONFIRMED, v['diag'])

print('== constant offset +12.3s -> FIXABLE, offset recovered ==')
v = sa.verify(REF, transformed(offset=12300))
check('status FIXABLE', v['status'] == sa.STATUS_FIXABLE, v['diag'])
check('offset ~ +12300 (+/-500)', abs(v['offset_ms'] - 12300) <= 500, v['diag'])
check('scale == 1.0', v['scale'] == 1.0, v['diag'])

print('== negative offset -8s -> FIXABLE ==')
v = sa.verify(REF, transformed(offset=-8000))
check('status FIXABLE', v['status'] == sa.STATUS_FIXABLE, v['diag'])
check('offset ~ -8000 (+/-500)', abs(v['offset_ms'] + 8000) <= 500, v['diag'])

print('== FPS drift 25 -> 23.976 (+ offset) -> FIXABLE, scale recovered ==')
true_scale = (24000 / 1001) / 25.0
v = sa.verify(REF, transformed(scale=true_scale, offset=3000))
check('status FIXABLE', v['status'] == sa.STATUS_FIXABLE, v['diag'])
check('scale ~ %.4f' % true_scale, abs(v['scale'] - true_scale) < 0.002,
      v['diag'])

print('== HI-style cue-count mismatch (drop every 6th) still aligns ==')
v = sa.verify(REF, transformed(offset=5000, drop_every=6))
check('status FIXABLE', v['status'] == sa.STATUS_FIXABLE, v['diag'])

print('== recut (5 min removed mid-file) -> UNKNOWN (must refuse) ==')
cut_start, cut_len = 18 * 60 * 1000, 5 * 60 * 1000
recut = []
for s, d in BASE:
    if s < cut_start:
        recut.append((s, d))
    elif s >= cut_start + cut_len:
        recut.append((s - cut_len, d))
v = sa.verify(REF, make_srt(recut, 'he'))
check('status UNKNOWN', v['status'] == sa.STATUS_UNKNOWN, v['diag'])

print('== too few cues -> UNKNOWN ==')
v = sa.verify(REF, make_srt(BASE[:5], 'he'))
check('status UNKNOWN', v['status'] == sa.STATUS_UNKNOWN, v['diag'])

print('== credit lines are ignored ==')
cred = ('0\n00:00:01,000 --> 00:00:05,000\nתורגם על ידי צוות האתר www.example.com\n\n'
        + transformed(offset=12300))
v = sa.verify(REF, cred)
check('credits do not break alignment', v['status'] == sa.STATUS_FIXABLE,
      v['diag'])

print('== verify_and_fix round-trip: fixed candidate re-verifies CONFIRMED ==')
fixed, verdict = sa.verify_and_fix(REF, transformed(scale=true_scale,
                                                    offset=9000))
check('first pass FIXABLE', verdict['status'] == sa.STATUS_FIXABLE,
      verdict['diag'])
v2 = sa.verify(REF, fixed)
check('after retime CONFIRMED', v2['status'] == sa.STATUS_CONFIRMED,
      v2['diag'])
check('fixed text is valid SRT with all cues',
      len(sa.parse_srt(fixed)) == len(BASE))

print('== retime preserves text ==')
fixed = sa.retime(transformed(offset=4000), 1.0, 4000)
cues = sa.parse_srt(fixed)
check('hebrew text intact', 'ציפיתי' in cues[0]['text'], cues[0]['text'])
check('timestamps shifted back', abs(cues[0]['start'] - BASE[0][0]) <= 1)

print('== pick_oracle ==')
cands = [
    {'release': 'Show.S01E05.1080p.WEB-DL.H.264-NTb', 'id': 1},
    {'release': 'Show.S01E05.720p.HDTV.x264-KILLERS', 'id': 2},
    {'release': 'Show.S01E05.2160p.WEB-DL.H.265-NTb', 'id': 3},
]
c, tier = sa.pick_oracle(cands, 'Show.S01E05.1080p.WEB-DL.H.264-NTb.mkv')
check('exact-release oracle picked', c is not None and c['id'] == 1, str(tier))
c, tier = sa.pick_oracle(cands, 'Show.S01E05.1080p.BluRay.x264-SPARKS')
check('no oracle for unmatched release', c is None)
c, tier = sa.pick_oracle(cands, 'Some Show.S01E05.1080p.mkv')
check('synthetic name never anchors', c is None)

print('== FIELD REGRESSION: sparse audio ref vs UNRELATED dense candidate ==')
# The exact failure mode seen live: 10 sparse VAD cues x dense (600-cue)
# unrelated subtitle -> a spurious histogram peak passed the old gate with
# vote=120% and applied offset=-350s (subs vanished). With vote dedupe +
# identity-scale-only + narrow window + the tight check, this MUST refuse.
rng_f = random.Random(42)
sparse_ref = []
for base_pos in (0.22, 0.5, 0.78):
    t0 = int(40 * 60 * 1000 * base_pos)
    t = t0
    while t < t0 + 20000:
        d = rng_f.randint(900, 2500)
        sparse_ref.append({'start': t, 'end': t + d})
        t += d + rng_f.randint(500, 4000)
sparse_ref = sparse_ref[:10]
unrelated = dialogue_times(n=600, seed=99, span_ms=45 * 60 * 1000)
cand_unrelated = make_srt(unrelated, 'he')
v = sa.verify_cues(sparse_ref, cand_unrelated,
                   min_vote=0.55, min_overlap=0.65,
                   scales=(1.0,), max_offset_ms=180000)
check('spurious alignment REFUSED', v['status'] == sa.STATUS_UNKNOWN,
      v['diag'])

print('== sparse audio ref vs TRUE shifted candidate still FIXABLE ==')
# Same sparse-ref conditions, but the candidate genuinely matches (+7s).
true_cand_times = []
for c in sparse_ref:
    true_cand_times.append((c['start'] + 7000, c['end'] - c['start']))
# pad with plausible other dialogue OUTSIDE the ref windows (dense candidate)
for s, d in dialogue_times(n=500, seed=7, span_ms=45 * 60 * 1000):
    if all(abs(s - (c['start'] + 7000)) > 4000 for c in sparse_ref):
        true_cand_times.append((s, d))
v = sa.verify_cues(sparse_ref, make_srt(sorted(true_cand_times), 'he'),
                   min_vote=0.55, min_overlap=0.65,
                   scales=(1.0,), max_offset_ms=180000)
check('true sparse alignment FIXABLE', v['status'] == sa.STATUS_FIXABLE,
      v['diag'])
check('offset ~ +7000', abs(v['offset_ms'] - 7000) <= 500, v['diag'])

print('== implausible-offset cap ==')
v = sa.verify(REF, transformed(offset=300000))
check('offset 300s refused as implausible',
      v['status'] == sa.STATUS_UNKNOWN, v['diag'])

print()
if FAILS:
    print('FAILED (%d):' % len(FAILS))
    for f in FAILS:
        print('  - ' + f)
    sys.exit(1)
print('ALL TESTS PASSED')
