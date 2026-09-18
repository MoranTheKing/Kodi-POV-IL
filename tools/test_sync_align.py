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

print('== constant offset +12.3s -> FIXABLE, offset recovered PRECISELY ==')
v = sa.verify(REF, transformed(offset=12300))
check('status FIXABLE', v['status'] == sa.STATUS_FIXABLE, v['diag'])
# Refinement (median of raw deltas) must beat the 500ms histogram bin.
check('offset ~ +12300 (+/-100 after refine)',
      abs(v['offset_ms'] - 12300) <= 100, v['diag'])
check('scale == 1.0', v['scale'] == 1.0, v['diag'])

print('== NON-bin-aligned offset +1180ms recovered to sub-100ms ==')
# The field bug: a true ~+1000-1200ms offset landed on a +1500ms bin and
# over-shifted subs ~0.5s early. Refinement must recover it precisely.
v = sa.verify(REF, transformed(offset=1180))
check('status FIXABLE', v['status'] == sa.STATUS_FIXABLE, v['diag'])
check('offset ~ +1180 (+/-120), not a 500ms-bin value',
      abs(v['offset_ms'] - 1180) <= 120, v['diag'])

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

print('== arbitrary smooth 1.03 clock drift is measured, not segmented ==')
fixed, v = sa.verify_and_fix(REF, transformed(scale=1.03, offset=1500))
check('arbitrary drift is FIXABLE/global',
      v['status'] == sa.STATUS_FIXABLE and v.get('mode') == 'global',
      v['diag'])
check('arbitrary scale recovered within 0.001',
      abs(v['scale'] - 1.03) <= 0.001, v['diag'])
check('arbitrary drift round-trips to CONFIRMED',
      sa.verify(REF, fixed)['status'] == sa.STATUS_CONFIRMED, v['diag'])

print('== arbitrary drift survives irregular missing and extra cues ==')
# The two cheap quantile proposals are deliberately defeated here: irregular
# deletions and insertions shift cue indices even though the underlying clock is
# one clean 1.025004 line. The bounded adaptive sweep must propose that line;
# all ordinary acceptance gates still decide whether it is safe to apply.
_rng = random.Random(10005)
_ref_irregular = dialogue_times(n=120, seed=5, span_ms=20 * 60 * 1000)
_scale_irregular, _offset_irregular = 1.0250044611, 1168.5115
_cand_irregular = []
for _i, (_s, _d) in enumerate(_ref_irregular):
    if _rng.random() < 0.08:
        continue
    _j = _rng.uniform(-100, 100)
    _cand_irregular.append((_scale_irregular * _s + _offset_irregular + _j,
                            _scale_irregular * _d))
for _ in range(int(len(_ref_irregular) * 0.05)):
    _t = _rng.uniform(_cand_irregular[0][0], _cand_irregular[-1][0])
    _cand_irregular.append((_t, _rng.randint(600, 2200)))
_cand_irregular.sort()
v = sa.verify(make_srt(_ref_irregular, 'en'),
              make_srt(_cand_irregular, 'he'))
check('irregular arbitrary drift is FIXABLE/global',
      v['status'] == sa.STATUS_FIXABLE and v.get('mode') == 'global', v['diag'])
check('irregular scale recovered within 0.001',
      abs(v['scale'] - _scale_irregular) <= 0.001, v['diag'])
check('irregular offset recovered within 0.6s',
      abs(v['offset_ms'] - _offset_irregular) <= 600, v['diag'])
_adaptive_real = sa._adaptive_scale_candidates
try:
    sa._adaptive_scale_candidates = lambda *args, **kwargs: []
    _sabotaged = sa.verify(make_srt(_ref_irregular, 'en'),
                           make_srt(_cand_irregular, 'he'))
finally:
    sa._adaptive_scale_candidates = _adaptive_real
check('SABOTAGE: removing the NG-derived search loses this valid fix',
      _sabotaged['status'] == sa.STATUS_UNKNOWN, _sabotaged['diag'])

print('== a small hard cut cannot masquerade as arbitrary smooth drift ==')
# This exact fixture used to be accepted as scale~1.0045/offset~1.5s: the
# global line improved the average score by smearing a 2.5s step across both
# halves, although neither half then had its real timing. Non-standard clocks
# now have to prove a flat local residual after the fit.
_step_clock = random.Random(5005)
_step_ref = []
_step_t = 30000
for _ in range(150):
    _step_d = _step_clock.randint(700, 3500)
    _step_ref.append((_step_t, _step_d))
    _step_t += _step_d + _step_clock.randint(300, 7000)
_step_rng = random.Random(6005)
_step_at = _step_rng.randrange(40, 110)
_step_ms = _step_rng.uniform(1800, 4200)
_step_cand = [
    (_s + 2200 + (_step_ms if _i >= _step_at else 0)
     + _step_rng.uniform(-70, 70), _d)
    for _i, (_s, _d) in enumerate(_step_ref)]
v = sa.verify(make_srt(_step_ref, 'en'), make_srt(_step_cand, 'he'))
check('2.5s step is UNKNOWN, never flattened into one scale',
      v['status'] == sa.STATUS_UNKNOWN,
      v['diag'])
_range_real = sa._SCALED_LOCAL_RANGE_MS
try:
    sa._SCALED_LOCAL_RANGE_MS = 10 ** 9
    _step_sabotaged = sa.verify(
        make_srt(_step_ref, 'en'), make_srt(_step_cand, 'he'))
finally:
    sa._SCALED_LOCAL_RANGE_MS = _range_real
check('SABOTAGE: removing scaled-clock continuity revives the false fix',
      _step_sabotaged['status'] == sa.STATUS_FIXABLE
      and _step_sabotaged.get('mode') == 'global',
      _step_sabotaged['diag'])

print('== hard cuts cannot masquerade as standard or near-identity scales ==')
def _hard_step_fixture(seed):
    _r = random.Random(8000 + seed)
    _xs = sorted(_r.uniform(0, 5000000) for _ in range(160))
    _ref = [(_x, _r.uniform(800, 3200)) for _x in _xs]
    _step = random.Random(9000 + seed).uniform(2000, 3000)
    _cand = [(_x + 1000 + (_step if _x > 2500000 else 0), _d)
             for _x, _d in _ref]
    return _ref, _cand


for _seed in (26, 68):
    _boundary_ref, _boundary_cand = _hard_step_fixture(_seed)
    v = sa.verify(make_srt(_boundary_ref, 'en'),
                  make_srt(_boundary_cand, 'he'), allow_piecewise=False)
    check('hard-step seed %d is safely UNKNOWN' % _seed,
          v['status'] == sa.STATUS_UNKNOWN, v['diag'])

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

print('== exact 7/8 cue boundary ==')
v7 = sa.verify(make_srt(BASE[:7], 'en'),
               make_srt([(s + 5000, d) for s, d in BASE[:7]], 'he'))
v8 = sa.verify(make_srt(BASE[:8], 'en'),
               make_srt([(s + 5000, d) for s, d in BASE[:8]], 'he'))
check('7 cues safely refused', v7['status'] == sa.STATUS_UNKNOWN, v7['diag'])
check('8 cues can prove a global fix', v8['status'] == sa.STATUS_FIXABLE,
      v8['diag'])

print('== malformed/non-chronological inputs fail before filtering ==')
zero = REF.replace('--> 00:00:17,526', '--> 00:00:15,000', 1)
v = sa.verify(zero, transformed())
check('zero-duration cue refuses',
      v['status'] == sa.STATUS_UNKNOWN and v.get('reason') == 'malformed',
      v['diag'])
blocks = transformed(offset=5000).strip().split('\n\n')
blocks[0], blocks[1] = blocks[1], blocks[0]
v = sa.verify(REF, '\n\n'.join(blocks) + '\n')
check('non-chronological input refuses before parser sort',
      v['status'] == sa.STATUS_UNKNOWN and v.get('reason') == 'malformed',
      v['diag'])

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


def stepped_candidate(scale, boundaries):
    """Apply [(reference_ms, offset_ms)] as piecewise timing ground truth."""
    out = []
    for s, d in BASE:
        off = boundaries[0][1]
        for boundary, value in boundaries:
            if s >= boundary:
                off = value
        out.append((scale * s + off, scale * d))
    return make_srt(out, 'he')


print('== local consistency catches old half-file false pass ==')
mid = BASE[len(BASE) // 2][0]
piece = stepped_candidate(1.0, [(0, 0), (mid, 60000)])
v = sa.verify(REF, piece, allow_piecewise=False)
check('global-only path REFUSES the deceptive map',
      v['status'] == sa.STATUS_UNKNOWN and 'local consistency FAILED' in v['diag'],
      v['diag'])

print('== conservative piecewise: one cut is recovered and round-trips ==')
fixed, v = sa.verify_and_fix(REF, piece)
check('one-cut verdict is FIXABLE/piecewise',
      v['status'] == sa.STATUS_FIXABLE and v.get('mode') == 'piecewise',
      v['diag'])
after = sa.parse_srt(fixed)
check('one-cut result keeps every cue', len(after) == len(BASE), v['diag'])
check('one-cut start error <= 50ms',
      max(abs(c['start'] - BASE[i][0]) for i, c in enumerate(after)) <= 50,
      v['diag'])
check('one-cut fixed file re-verifies CONFIRMED',
      sa.verify(REF, fixed)['status'] == sa.STATUS_CONFIRMED, v['diag'])

print('== conservative piecewise: FPS drift + cut ==')
fps_piece = stepped_candidate(25.0 / (24000 / 1001),
                              [(0, 0), (mid, 60000)])
fixed, v = sa.verify_and_fix(REF, fps_piece)
check('FPS+cut is FIXABLE/piecewise',
      v['status'] == sa.STATUS_FIXABLE and v.get('mode') == 'piecewise',
      v['diag'])
after = sa.parse_srt(fixed)
check('FPS+cut p95 start error <= 50ms',
      sorted(abs(c['start'] - BASE[i][0]) for i, c in enumerate(after))[
          int(0.95 * (len(after) - 1))] <= 50, v['diag'])

print('== conservative piecewise: two cuts ==')
one_third = BASE[len(BASE) // 3][0]
two_thirds = BASE[2 * len(BASE) // 3][0]
two_cuts = stepped_candidate(
    1.0, [(0, 0), (one_third, 30000), (two_thirds, 90000)])
fixed, v = sa.verify_and_fix(REF, two_cuts)
check('two-cut verdict is FIXABLE/piecewise',
      v['status'] == sa.STATUS_FIXABLE and len(v.get('segments') or []) == 3,
      v['diag'])
after = sa.parse_srt(fixed)
check('two-cut result exact to <=50ms',
      max(abs(c['start'] - BASE[i][0]) for i, c in enumerate(after)) <= 50,
      v['diag'])

print('== ambiguous small multi-step pattern is refused, never guessed ==')
ambiguous = stepped_candidate(
    1.0, [(0, 0), (one_third, 3000), (mid, 8000),
          (two_thirds, 12000)])
v = sa.verify(REF, ambiguous)
check('sub-5s adjacent steps stay UNKNOWN', v['status'] == sa.STATUS_UNKNOWN,
      v['diag'])

print('== dominant region cannot hide a sustained 2.5s tail cut ==')
tail_cut = stepped_candidate(
    1.0, [(0, 0), (BASE[int(len(BASE) * 0.80)][0], 2500)])
v = sa.verify(REF, tail_cut)
check('small unsupported tail cut is refused, not globally accepted',
      v['status'] == sa.STATUS_UNKNOWN
      and 'local consistency FAILED' in v['diag'], v['diag'])

print('== post-transform invariants reject cue loss/clamping ==')
early = make_srt([(500, 1200)] + [(s + 10000, d) for s, d in BASE], 'he')
try:
    sa.apply_verdict(early, {'status': sa.STATUS_FIXABLE, 'scale': 1.0,
                             'offset_ms': 5000})
    invariant_refused = False
except ValueError:
    invariant_refused = True
check('negative first cue refuses whole transform', invariant_refused)

# Counting overlaps is insufficient: a piecewise map can remove one old
# overlap and create a different one, leaving the count unchanged.  The exact
# cue-pair set must be preserved or reduced.
overlap_move = make_srt([(10000, 3000), (12000, 2000), (16000, 2000)], 'he')
overlap_move_verdict = {
    'status': sa.STATUS_FIXABLE, 'scale': 1.0, 'offset_ms': 0.0,
    'mode': 'piecewise',
    'segments': [
        {'cand_from_ms': None, 'offset_ms': 0.0},
        {'cand_from_ms': 11000.0, 'offset_ms': -2000.0},
        {'cand_from_ms': 15000.0, 'offset_ms': 500.0},
    ],
}
try:
    sa.apply_verdict(overlap_move, overlap_move_verdict)
    moved_overlap_refused = False
except ValueError:
    moved_overlap_refused = True
check('an overlap cannot migrate to a different cue pair',
      moved_overlap_refused)

print('== dialogue detection is Unicode-complete ==')
for label, sample in (
        ('Hindi', 'तुम यहाँ क्यों आई हो?'),
        ('Greek', 'Γιατί ήρθες εδώ;'),
        ('Arabic', 'لماذا أتيت إلى هنا؟'),
        ('Hebrew', 'למה באת לכאן?')):
    check(label + ' dialogue survives',
          bool(sa.dialogue_cues([{'start': 1000, 'end': 2000,
                                  'text': sample}])))

print()
if FAILS:
    print('FAILED (%d):' % len(FAILS))
    for f in FAILS:
        print('  - ' + f)
    sys.exit(1)
print('ALL TESTS PASSED')
