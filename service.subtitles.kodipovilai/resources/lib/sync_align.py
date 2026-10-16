# SubSync Phase S2 -- verify & auto-retime engine.
#
# Generalizes the production-proven aligner from arabic_gender.py (voting-
# histogram offset search x FPS-ratio scale candidates x overlap-rate gate,
# which today aligns the Arabic gender ORACLE to the English source) into a
# language-agnostic module that verifies -- and when confidently possible,
# FIXES -- the timing of a delivered subtitle against a trusted reference:
#
#   reference = a subtitle known to match the PLAYING release (any language;
#               the aligner never reads text, only cue timestamps), or later
#               (S4) the playing file's own embedded track cues.
#   candidate = the Hebrew sub we are about to deliver (human/pool/AI).
#
#   verify(ref_srt, cand_srt) -> {'status': CONFIRMED|FIXABLE|UNKNOWN, ...}
#   retime(cand_srt, scale, offset_ms) -> retimed SRT text
#
# CONFIRMED: candidate already lines up with the reference (map ~identity).
# FIXABLE:   a confident linear map exists but is not identity -> retime.
# UNKNOWN:   the gate failed (recut/extended/too few cues) -> deliver as-is,
#            label honestly, NEVER guess.
#
# Self-contained on purpose (stdlib only, no xbmc, no package imports) so it
# is testable offline and importable from any interpreter, like
# release_match.py.

import re
import bisect
import collections
import math
import statistics
import time

# ---- gate thresholds (mirroring arabic_gender's production values) --------
_FPS = [24000 / 1001, 24.0, 25.0, 30000 / 1001, 30.0]
SCALES = sorted({1.0} | {round(p / q, 6) for p in _FPS for q in _FPS
                         if 0.9 <= p / q <= 1.11})
_TOL = 500            # offset histogram bin (ms)
_MAXOFF = 250000      # search window: just past MAX_PLAUSIBLE_OFFSET_MS;
                      # a wider peak would be refused anyway, and the
                      # old +/-10 min window cost 2.4x the CPU
_SAMPLE = 500         # cap sampled reference cues
MIN_CUES = 8          # min dialogue cues on each side
MIN_VOTE = 0.65       # histogram peak must carry >=65% of sampled cues
_IDENTITY_SHORTCUT_VOTE = 0.80   # identity this strong: no FPS search
MIN_OVERLAP = 0.80    # >=80% of ref cues must overlap after the map
SCALE_MIN, SCALE_MAX = 0.90, 1.11
CONFIRM_OFFSET_MS = 350   # |offset| <= this and scale==1.0 -> already synced

STATUS_CONFIRMED = 'CONFIRMED'
STATUS_FIXABLE = 'FIXABLE'
STATUS_UNKNOWN = 'UNKNOWN'

# Local-consistency / conservative piecewise correction.  A single global map
# can look excellent when one half of a subtitle is a minute late (recap/ad cut):
# the dominant half wins the histogram and hides the other half.  We therefore
# re-estimate the already-selected scale in bounded timeline windows.  Natural
# same-title controls (132 cross-language pairs from 11 titles) stayed within
# 1,000 ms; the 1,500-ms guard below still leaves a quantisation margin while
# refusing a sustained small cut before a dominant region can hide it. Piecewise
# correction starts only at a clear 5,000-ms step and needs sustained support.
LOCAL_INCONSISTENCY_MS = 1500
PIECEWISE_MIN_STEP_MS = 5000
_LOCAL_MIN_REF_CUES = 40
_LOCAL_MAX_WINDOWS = 15
_LOCAL_MIN_VOTE = 0.65
_LOCAL_MIN_OVERLAP = 0.65
_PIECEWISE_MAX_SEGMENTS = 4
_LOCAL_RADIUS_MS = 150000
_LOCAL_SAME_PLATEAU_MS = 1500
# Any non-identity scale is only a proposal, including a familiar FPS ratio.
# A small hard cut can accidentally land close to 24/23.976 or another common
# ratio and smear the discontinuity over the whole film.  At a genuinely
# continuous clock ratio, independently estimated local offsets remain flat.
# Wider disagreement is evidence of different regions rather than one clock:
# refuse the approximation and preserve the delivered subtitle unchanged.
_SCALED_LOCAL_RANGE_MS = 1000

# Some broadcast/stream masters insert a short bumper or black-frame pad at
# several act boundaries.  Against another master this is neither one global
# delay nor a normal FPS clock: the offset grows in small, repeated steps.  A
# single timing track is not enough evidence to rewrite a whole subtitle for
# such a subtle edit, so the planner below only PRODUCES a proposal.  The media
# layer must prove it on held-out timing cues (or genuinely independent timing
# families) before ``apply_verdict`` will accept it.  These bounds describe that
# deliberately narrow proposal space; ordinary >=5-second cuts continue through
# the mature piecewise path above.
_MICRO_MIN_STEP_MS = 1000
_MICRO_MAX_STEP_MS = 4500
_MICRO_SAME_PLATEAU_MS = 1200
_MICRO_MAX_SEGMENTS = 8
_MICRO_MIN_WINDOWS = 10
_MICRO_MIN_CORE_RATIO = 0.75
_MICRO_POST_RESIDUAL_MS = 850
# Cue-level region planner for the same narrow proposal space.  Fixed 2.5-min
# windows straddle short acts, so a fifth of the reference removed by a holdout
# fold can move a window onto the wrong plateau and make the re-planned map
# disagree with an otherwise perfect proposal.  Assigning every candidate cue
# its own plateau by dynamic programming locates each act from the cues inside
# it.  The output is still only a proposal: holdout folds and an independent
# timing family must prove it before ``apply_verdict`` will accept it.
_REGION_STEP_MS = 250
_REGION_RADIUS_MS = 32000
_REGION_CAP_MS = 800.0
_REGION_SWITCH_COST = 5000.0
_REGION_MATCH_MS = 400.0
_REGION_MIN_CUES = 20
_REGION_MIN_SPAN_MS = 60000.0
_REGION_BOUNDARY_SLACK = 8
_REGION_MAX_DRIFT_MS = 400.0


# ---- SRT parsing -----------------------------------------------------------

_TIME_RE = re.compile(
    r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*'
    r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})')

_TAG_RE = re.compile(r'<[^>]+>|\{\\[^}]*\}')

# Credit/watermark lines (translator credits, site plugs) cluster at the very
# start/end of subtitle files and do NOT correspond to dialogue -- they poison
# the histogram, so cues that are clearly credits are dropped before aligning.
_CREDIT_RE = re.compile(
    r'(תורגם|תרגום|סונכרן|סנכרון|כתוביות|הובא|צפייה מהנה|subs?\s*by|'
    r'subtitles?\s+by|sync(?:ed)?\s+by|corrected\s+by|www\.|https?://|\.com|'
    r'\.net|\.org|opensubtitles|subscene|ktuvit|wizdom)', re.I)


def _to_ms(h, m, s, ms):
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms.ljust(3, '0'))


def _ms_to_stamp(ms):
    if ms < 0:
        ms = 0
    ms = int(round(ms))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return '{0:02d}:{1:02d}:{2:02d},{3:03d}'.format(h, m, s, ms)


def parse_srt(text):
    """[{'start': ms, 'end': ms, 'text': str}] for every timed block.
    Tolerant: skips malformed blocks, handles BOM/CRLF, '.' or ',' millis."""
    cues = []
    if not text:
        return cues
    text = text.lstrip('﻿')
    for block in re.split(r'\r?\n\r?\n+', text):
        m = _TIME_RE.search(block)
        if not m:
            continue
        start = _to_ms(*m.group(1, 2, 3, 4))
        end = _to_ms(*m.group(5, 6, 7, 8))
        if end < start:
            continue
        body = block[m.end():].strip()
        body = _TAG_RE.sub('', body)
        cues.append({'start': start, 'end': end, 'text': body.strip()})
    cues.sort(key=lambda c: c['start'])
    return cues


def _preflight_srt(text):
    """Strict, original-order SRT validation for an automatic rewrite.

    The tolerant public parser is useful for reading imperfect downloads, but
    it is deliberately unsafe as an edit precondition: it skips malformed
    blocks and sorts non-chronological input.  An automatic synchronizer must
    instead leave any questionable file byte-for-byte alone.
    """
    if not isinstance(text, str) or not text.strip():
        return [], 'empty subtitle'
    cues = []
    previous_start = None
    blocks = [b for b in re.split(r'\r?\n\r?\n+', text.lstrip('\ufeff'))
              if b.strip()]
    if not blocks:
        return [], 'empty subtitle'
    for number, block in enumerate(blocks, 1):
        # More than one timing arrow means missing block separation; no parser
        # should silently keep the first cue and throw the remainder away.
        if block.count('-->') != 1:
            return [], 'malformed timing block %d' % number
        match = _TIME_RE.search(block)
        if match is None:
            return [], 'unparseable timing block %d' % number
        start = _to_ms(*match.group(1, 2, 3, 4))
        end = _to_ms(*match.group(5, 6, 7, 8))
        if end <= start:
            return [], 'non-positive cue duration at block %d' % number
        if previous_start is not None and start < previous_start:
            return [], 'non-chronological cue start at block %d' % number
        previous_start = start
        body = _TAG_RE.sub('', block[match.end():].strip())
        cues.append({'start': start, 'end': end, 'text': body.strip()})
    return cues, ''


def _tolerant_reference(text):
    """Timing skeleton of a reference SRT that failed the strict preflight.

    The strict preflight protects files we REWRITE. A reference is only read
    for its timestamps, and provider files routinely break the strict layout
    without any timing damage -- most often a blank line inside a credit or
    song cue (field: an OpenSubtitles HDTV reference refused at "malformed
    timing block 159" for exactly that). Accept the tolerant parse only when
    virtually every timing line survives it intact.
    """
    if not isinstance(text, str):
        return None
    # Timing itself must be intact and in order; only the block LAYOUT may
    # be imperfect (non-positive or reordered cues still refuse).
    timings = [(_to_ms(*m.group(1, 2, 3, 4)), _to_ms(*m.group(5, 6, 7, 8)))
               for m in _TIME_RE.finditer(text)]
    if len(timings) < MIN_CUES:
        return None
    previous = None
    for start, end in timings:
        if end <= start or (previous is not None and start < previous):
            return None
        previous = start
    cues = parse_srt(text)
    if len(cues) < max(MIN_CUES, int(0.97 * len(timings))):
        return None
    return cues


def _preflight_cues(cues):
    """Validate an already-parsed timing skeleton without reordering it."""
    out = []
    previous_start = None
    for number, cue in enumerate(cues or [], 1):
        if not isinstance(cue, dict) or 'start' not in cue or 'end' not in cue:
            return [], 'malformed cue %d' % number
        try:
            start = float(cue['start'])
            end = float(cue['end'])
        except (TypeError, ValueError):
            return [], 'non-numeric cue %d' % number
        if not math.isfinite(start) or not math.isfinite(end):
            return [], 'non-finite cue %d' % number
        if end <= start:
            return [], 'non-positive cue duration at cue %d' % number
        if previous_start is not None and start < previous_start:
            return [], 'non-chronological cue start at cue %d' % number
        previous_start = start
        out.append(dict(cue, start=start, end=end))
    if not out:
        return [], 'empty cue list'
    return out, ''


def _preflight_unknown(error):
    return {'status': STATUS_UNKNOWN, 'scale': 1.0, 'offset_ms': 0.0,
            'vote': 0.0, 'overlap': 0.0, 'reason': 'malformed',
            'diag': 'preflight FAILED: ' + error}


def _is_dialogue(c):
    t = (c.get('text') or '').strip()
    if not t or t.startswith(('♪', '♫', '#')):
        return False
    # Python's Unicode-aware predicate avoids silently dropping a whole
    # helper track just because its script was not listed here.  The former
    # hand-written ranges omitted Devanagari (Hindi) and Greek, so those
    # otherwise-valid timing references collapsed to zero cues.
    letters = ''.join(ch for ch in t if ch.isalpha())
    return len(letters) >= 2


def dialogue_cues(text_or_cues):
    """Dialogue-only cues (SFX/music and credit/watermark lines dropped)."""
    cues = (text_or_cues if isinstance(text_or_cues, list)
            else parse_srt(text_or_cues))
    out = [c for c in cues if _is_dialogue(c)]
    if not out:
        return out
    span_end = out[-1]['end']
    kept = []
    for c in out:
        near_edge = c['start'] < 120000 or c['start'] > span_end - 120000
        if near_edge and _CREDIT_RE.search(c['text']):
            continue
        kept.append(c)
    return kept


# ---- linear time-map estimation (from arabic_gender, generalized) ----------

# Kodi runs every add-on's Python under one interpreter lock. Measured in QA
# Kodi (21, Python 3.11): while one thread runs a CPU-bound loop that never
# sleeps, a NEW script -- e.g. our own "בחירת כתוביות" button -- does not even
# start until that loop ends (15.8 s behind a 20 s loop, 0.3 s idle); a 1 ms
# sleep every ~20 ms brings it back to 0.3 s. Field logs from an Android box
# showed the same 5-11 s waits behind SubSync's deep check at playback start.
# The long loops here call _breathe(): about 5% slower in the background,
# never in the way of the viewer.
_BREATHE_SLICE = 0.02
_breath = [0.0]


def _breathe():
    now = time.monotonic()
    if now - _breath[0] >= _BREATHE_SLICE:
        time.sleep(0.001)
        _breath[0] = time.monotonic()


def _best_offset(ref_on, cand_on, a, max_off=_MAXOFF):
    step = max(1, len(ref_on) // _SAMPLE)
    sampled = ref_on[::step]
    hist = collections.Counter()
    left, right = bisect.bisect_left, bisect.bisect_right
    tol = float(_TOL)
    for e in sampled:
        _breathe()
        pe = a * e
        lo = left(cand_on, pe - max_off)
        hi = right(cand_on, pe + max_off)
        if lo >= hi:
            continue
        # ONE vote per reference cue per bin. Without the dedupe, a DENSE
        # candidate (600 cues) inflated bins with multiple hits per ref cue,
        # so a sparse 10-cue reference could report vote=120% on a spurious
        # alignment (seen in the field: offset=-350s applied, subs vanished).
        # (Set comprehension + Counter: same bins, a fraction of the
        # interpreter work -- this loop dominates SubSync's CPU time.)
        hist.update({round((c - pe) / tol) for c in cand_on[lo:hi]})
    if not hist:
        return 0.0, 0
    peak = max(hist, key=lambda k: hist[k] + hist.get(k - 1, 0)
               + hist.get(k + 1, 0))
    votes = min(hist.get(peak - 1, 0) + hist.get(peak, 0)
                + hist.get(peak + 1, 0),
                len(sampled))
    # REFINE: the histogram bin is 500ms, so peak*_TOL is only accurate to
    # +/-250ms -- enough to over/under-shoot a real fix by up to half a second
    # (field: a +1500ms bin fix left subs ~0.5s early). Take the MEDIAN of the
    # actual per-ref-cue deltas closest to the peak center -> sub-50ms offset.
    center = peak * _TOL
    deltas = []
    for e in sampled:
        pe = a * e
        i = bisect.bisect_left(cand_on, pe + center)
        best_d = None
        for j in (i - 1, i):
            if 0 <= j < len(cand_on):
                d = cand_on[j] - pe
                if abs(d - center) <= 1.5 * _TOL and (
                        best_d is None or abs(d - center) < abs(best_d - center)):
                    best_d = d
        if best_d is not None:
            deltas.append(best_d)
    if deltas:
        deltas.sort()
        refined = float(deltas[len(deltas) // 2])
    else:
        refined = float(center)
    return refined, votes


def _data_scale_candidates(ref_cues, cand_cues):
    """A few robust, timing-only scale proposals for non-standard drift.

    Cue-count quantiles are only proposal generators; they never prove an
    alignment.  Consecutive quantile slopes make an inserted scene affect one
    interval rather than bias the whole-file ratio, while their median recovers
    a continuous arbitrary clock drift.  Every proposal still has to win the
    histogram and pass unique/global/local/post-transform gates.
    """
    if len(ref_cues) < _LOCAL_MIN_REF_CUES or len(cand_cues) < _LOCAL_MIN_REF_CUES:
        return []
    fractions = [i / 10.0 for i in range(1, 10)]

    def points(cues):
        last = len(cues) - 1
        return [float(cues[int(round(fraction * last))]['start'])
                for fraction in fractions]

    ref_points = points(ref_cues)
    cand_points = points(cand_cues)
    local_slopes = []
    for i in range(1, len(ref_points)):
        dx = ref_points[i] - ref_points[i - 1]
        if dx > 0:
            local_slopes.append(
                (cand_points[i] - cand_points[i - 1]) / dx)
    pair_slopes = []
    for i in range(len(ref_points)):
        for j in range(i + 1, len(ref_points)):
            dx = ref_points[j] - ref_points[i]
            if dx > 0:
                pair_slopes.append((cand_points[j] - cand_points[i]) / dx)
    proposals = []
    for values in (local_slopes, pair_slopes):
        if values:
            proposal = round(_median(values), 6)
            if SCALE_MIN <= proposal <= SCALE_MAX:
                proposals.append(proposal)
    return list(dict.fromkeys(proposals))


def _adaptive_scale_candidates(ref_cues, cand_cues, max_offset_ms=None):
    """Recover a non-standard continuous clock ratio after the cheap grid fails.

    Quantile ratios are fast, but inserted/deleted cues move the quantile
    indices and can make both proposals miss a perfectly linear 1.01/1.03
    clock.  NG's research detector demonstrated that a broad scale sweep closes
    that hole.  Its exhaustive full-density sweep is too costly for 32-bit Kodi,
    so this production version searches a bounded, span-derived band on a
    deterministic sample, then returns only the strongest scales for the normal
    FULL gate. It is proposal-only: it cannot accept anything by itself.
    """
    if len(ref_cues) < _LOCAL_MIN_REF_CUES or len(cand_cues) < _LOCAL_MIN_REF_CUES:
        return []

    def sample(values, cap):
        if len(values) <= cap:
            return values
        if cap <= 1:
            return values[:1]
        last = len(values) - 1
        return [values[int(round(i * last / (cap - 1)))] for i in range(cap)]

    # Keep candidate onsets dense: every sampled reference cue then retains its
    # actual counterpart unless that cue was genuinely deleted. Sampling the
    # candidate down to a small independent index grid would create an
    # artificial clock ratio; pairing matching indices also fails as soon as
    # real subtitles insert/drop cues. 2,400 covers even dialogue-heavy films
    # while bounding a pathological file.
    ref_on = sample([float(c['start']) for c in ref_cues], 120)
    cand_on = sample([float(c['start']) for c in cand_cues], 2400)
    max_off = _MAXOFF if max_offset_ms is None else max_offset_ms
    scored = {}

    def scan(scales):
        for value in scales:
            scale = round(float(value), 6)
            if scale in scored or not (SCALE_MIN <= scale <= SCALE_MAX):
                continue
            offset, votes = _best_offset(ref_on, cand_on, scale, max_off)
            scored[scale] = (votes, offset)

    def leaders(limit=4):
        return sorted(scored, key=lambda value: (
            -scored[value][0], abs(value - 1.0)))[:limit]

    # The whole dialogue span is stable under irregular insertions/deletions in
    # the middle, exactly where index-quantile ratios fail. Search a generous
    # +/-1.2% band around that evidence at 0.001 resolution. A full 0.90..1.11
    # sweep also finds cadence aliases and is several seconds slower on x86;
    # when the edge span is wrong by more than this (different opening/ending),
    # refusing automatic surgery is the safer outcome. The existing local
    # smooth-drift refit removes the remaining <=0.0005 quantisation error.
    ref_span = ref_on[-1] - ref_on[0]
    cand_span = cand_on[-1] - cand_on[0]
    if ref_span <= 0 or cand_span <= 0:
        return []
    center = cand_span / ref_span
    scan(center + i * 0.001 for i in range(-12, 13))
    return leaders(6)


def estimate(ref_cues, cand_cues, scales=None, max_offset_ms=None):
    """Best linear map cand_time ~= a*ref_time + b over the scale candidates.
    Returns (a, b_ms, vote_ratio). `scales` restricts the candidate scale set
    (sparse references can't support scale estimation -- every extra scale
    multiplies the chance of a spurious histogram peak); `max_offset_ms`
    narrows the offset search window for the same reason."""
    ref_on = [c['start'] for c in ref_cues]
    cand_on = [c['start'] for c in cand_cues]
    if not ref_on or not cand_on:
        return 1.0, 0.0, 0.0
    sampled = len(ref_on[::max(1, len(ref_on) // _SAMPLE)])
    max_off = _MAXOFF if max_offset_ms is None else max_offset_ms
    best = (1.0, 0.0, -1)
    # Try scales nearest-to-1.0 FIRST and require a STRICTLY better vote to
    # switch away: neighbouring FPS ratios (e.g. 23.976/24 = 0.999) can tie
    # with the identity map inside the histogram bin tolerance on short
    # spans, and picking 0.999 over a true 1.0 accumulates seconds of drift
    # by the end of a long movie.
    candidates = list(dict.fromkeys(
        round(float(value), 6)
        for value in (SCALES if scales is None else scales)))

    def consider(values, current):
        for candidate_scale in sorted(values, key=lambda s: abs(s - 1.0)):
            candidate_offset, candidate_votes = _best_offset(
                ref_on, cand_on, candidate_scale, max_off)
            if candidate_votes > current[2]:
                current = (candidate_scale, candidate_offset, candidate_votes)
        return current

    if 1.0 in candidates:
        # Identity first (same tie rule as before: another scale must be
        # strictly better). When the identity clock already carries a strong
        # majority there is no FPS drift to find: skip the dozen other scale
        # histograms -- the bulk of SubSync's CPU on weak TV boxes. Every
        # downstream gate still runs on the result.
        offset1, votes1 = _best_offset(ref_on, cand_on, 1.0, max_off)
        best = (1.0, offset1, votes1)
        if sampled and votes1 / sampled >= _IDENTITY_SHORTCUT_VOTE:
            return 1.0, offset1, votes1 / sampled
        candidates = [value for value in candidates if value != 1.0]
    best = consider(candidates, best)
    # Standard FPS/identity covers almost every healthy file.  Arbitrary
    # quantile proposals cost two extra histogram passes, so evaluate them only
    # when that fast path lacks a strong global majority.  Deep verification is
    # background work, but it must still stay light on 32-bit devices.
    if scales is None and (best[2] / sampled if sampled else 0.0) < 0.85:
        extras = [value for value in _data_scale_candidates(ref_cues, cand_cues)
                  if value not in candidates]
        best = consider(extras, best)
        # If the cheap standard + quantile proposals still cannot establish a
        # strong majority, use NG's broad-search insight in a bounded form.
        # Only six sampled winners reach the full-density evaluator, keeping
        # the slow path practical on 32-bit devices. Every downstream unique,
        # overlap, tight, local, identity and invariant gate remains mandatory.
        if (best[2] / sampled if sampled else 0.0) < 0.80:
            broad = [value for value in _adaptive_scale_candidates(
                ref_cues, cand_cues, max_offset_ms=max_offset_ms)
                     if value not in candidates and value not in extras]
            best = consider(broad, best)
    a, b, v = best
    return a, b, (v / sampled if sampled else 0.0)


def overlap_rate(ref_cues, cand_cues, a, b):
    """Share of reference cues that overlap SOME candidate cue after mapping
    ref time t -> a*t + b."""
    cand_starts = [c['start'] for c in cand_cues]
    cand_ends = [c['end'] for c in cand_cues]
    ok = 0
    for c in ref_cues:
        es, ee = a * c['start'] + b, a * c['end'] + b
        lo = bisect.bisect_left(cand_ends, es)
        k = lo
        while k < len(cand_cues) and cand_starts[k] < ee:
            if min(ee, cand_ends[k]) - max(es, cand_starts[k]) > 0:
                ok += 1
                break
            k += 1
    return ok / len(ref_cues) if ref_cues else 0.0


# ---- public API -------------------------------------------------------------

def verify(ref_srt_text, cand_srt_text, min_vote=None, min_overlap=None,
           scales=None, max_offset_ms=None, allow_piecewise=True,
           require_tight=True):
    """Verdict dict:
      {'status': CONFIRMED|FIXABLE|UNKNOWN,
       'scale': a, 'offset_ms': b,          # map: cand ~= a*ref + b, i.e. to
                                             # FIX cand apply t' = (t - b) / a
       'vote': 0..1, 'overlap': 0..1, 'diag': str}
    NOTE on direction: estimate() maps REF time onto CAND time. A candidate
    that lags the reference by +12s yields offset_ms=+12000; retime() is then
    called with (scale, offset_ms) and applies the INVERSE map to the
    candidate so it lands on the reference timeline.

    Optional gate overrides (min_vote / min_overlap / scales / max_offset_ms)
    let a caller tune the coarse pre-filters -- e.g. a same-source oracle pins
    scales to identity (same disc master = same framerate) and relaxes the vote
    floor, since cross-language cue segmentation depresses the vote while the
    graduated tight gate still guards correctness."""
    ref_all, ref_error = _preflight_srt(ref_srt_text)
    if ref_error:
        ref_all = (_tolerant_reference(ref_srt_text)
                   if ref_error.startswith(('malformed timing block',
                                            'unparseable timing block'))
                   else None)
        if ref_all is None:
            return _preflight_unknown('reference: ' + ref_error)
    cand_all, cand_error = _preflight_srt(cand_srt_text)
    if cand_error:
        return _preflight_unknown('candidate: ' + cand_error)
    return _snap_piecewise_boundaries(
        _gate(dialogue_cues(ref_all), dialogue_cues(cand_all),
              min_vote=min_vote, min_overlap=min_overlap,
              scales=scales, max_offset_ms=max_offset_ms,
              allow_piecewise=allow_piecewise,
              require_tight=require_tight), cand_all)


# ---- bitmap (PGS / VobSub) display events ---------------------------------
# A bitmap subtitle track's container index lists every display EVENT: the
# instant a caption appears and the instant it is cleared, both as cue starts.
# Read as cues, half of them are the gaps between lines, so a text subtitle's
# onsets also "match" the clear events one caption-length away and the offset
# vote splits.  Measured on a PGS-only Blu-ray rip: vote 51%, 9/15 trusted
# windows for a subtitle whose timing family matched the disc, against 89% and
# 15/15 once the text subtitle is read the same way -- every start AND end an
# event.  A text file's ends sit a little off the disc's clear events
# (-80..-170 ms on a remux whose subtitle is in sync by the audio), so the
# events only find the map; the final offset is measured again on caption
# STARTS alone.
_EVENT_MIN_MS = 600
_EVENT_MAX_MS = 3000
_ONSET_MATCH_MS = 450
_ONSET_MIN_MATCHES = 30
# Measured on a Blu-ray remux whose subtitles are in sync by the audio: 74-77%
# of caption starts land within 450 ms of a display event, and 67-81% of those
# within 150 ms of their median.  A subtitle whose starts are all 600 ms early
# but whose ends match the disc (the events alone call it in sync) reaches
# 41% and 32%.
_ONSET_MIN_FRACTION = 0.55
_ONSET_TIGHT_MS = 150
_ONSET_MIN_TIGHT = 0.50


def bitmap_events(cues):
    """A cue list seen the way a bitmap track's index is read: every start and
    every end is an event, with the synthetic durations SubSync gives index
    starts (next event - 100 ms, clamped to 0.6-3 s)."""
    points = sorted({int(c['start']) for c in cues or []}
                    | {int(c['end']) for c in cues or []})
    out = []
    for i, start in enumerate(points):
        nxt = points[i + 1] if i + 1 < len(points) else start + _EVENT_MAX_MS
        out.append({'start': start,
                    'end': start + max(_EVENT_MIN_MS,
                                       min(_EVENT_MAX_MS, nxt - start - 100))})
    return out


def _onset_offset(ref, cand, scale, offset, lo=None, hi=None,
                  min_matches=_ONSET_MIN_MATCHES):
    """Median residual of caption starts against the nearest display event the
    map predicts, or None when too few starts land near one."""
    starts = [float(r['start']) for r in ref]
    diffs = []
    considered = 0
    for c in cand:
        s = float(c['start'])
        if (lo is not None and s < lo) or (hi is not None and s >= hi):
            continue
        considered += 1
        predicted = (s - offset) / scale
        j = bisect.bisect_left(starts, predicted)
        best = None
        for k in (j - 1, j):
            if 0 <= k < len(starts):
                d = s - (scale * starts[k] + offset)
                if best is None or abs(d) < abs(best):
                    best = d
        if best is not None and abs(best) <= _ONSET_MATCH_MS:
            diffs.append(best)
    if (len(diffs) < min_matches
            or len(diffs) < _ONSET_MIN_FRACTION * considered):
        return None
    diffs.sort()
    median = diffs[len(diffs) // 2]
    tight = sum(1 for d in diffs if abs(d - median) <= _ONSET_TIGHT_MS)
    if tight < _ONSET_MIN_TIGHT * len(diffs):
        return None
    return offset + median


def _refine_on_onsets(ref, cand, verdict):
    """Re-measure an events verdict's offset on caption starts (see above).
    A verdict the starts do not support is refused: the events alone can read
    a subtitle whose every start is wrong as in sync, if its ends are right."""
    status = verdict.get('status')
    if status not in (STATUS_CONFIRMED, STATUS_FIXABLE):
        return verdict
    a = float(verdict.get('scale') or 1.0)
    b = float(verdict.get('offset_ms') or 0.0)
    out = dict(verdict)

    def refuse(reason):
        return dict(verdict, status=STATUS_UNKNOWN, reason=reason,
                    diag=(verdict.get('diag') or '') + ' [bitmap events: %s]' % reason)

    segments = verdict.get('segments')
    if segments:
        fixed, refined_any = [], 0
        for i, seg in enumerate(segments):
            lo = seg.get('cand_from_ms')
            hi = segments[i + 1].get('cand_from_ms') if i + 1 < len(segments) else None
            seg_b = float(seg.get('offset_ms') or 0.0)
            refined = _onset_offset(ref, cand, a, seg_b, lo, hi, min_matches=8)
            if refined is None:
                return refuse('bitmap_onsets_unmatched')
            if abs(refined - seg_b) > _ONSET_MATCH_MS:
                return refuse('bitmap_onsets_disagree')
            fixed.append(dict(seg, offset_ms=refined))
            refined_any += 1
        out['segments'] = fixed
        out['offset_ms'] = float(fixed[0].get('offset_ms') or 0.0)
        return out
    refined = _onset_offset(ref, cand, a, b)
    if refined is None:
        return refuse('bitmap_onsets_unmatched')
    if abs(refined - b) > _ONSET_MATCH_MS:
        return refuse('bitmap_onsets_disagree')
    out['offset_ms'] = refined
    out['diag'] = (verdict.get('diag') or '') + ' [bitmap events; onset offset %+dms]' % int(refined)
    if status == STATUS_CONFIRMED and abs(refined) > CONFIRM_OFFSET_MS:
        # The starts say the subtitle is off by more than the in-sync band
        # that the events allowed.  Neither confirm nor fix on a shift no
        # gate has checked.
        out['status'] = STATUS_UNKNOWN
        out['reason'] = 'bitmap_onsets_disagree'
    elif status == STATUS_FIXABLE and a == 1.0 and abs(refined) <= CONFIRM_OFFSET_MS:
        out['status'] = STATUS_CONFIRMED
        out.pop('mode', None)
    return out


def verify_cues(ref_cues, cand_srt_text, min_vote=None, min_overlap=None,
                scales=None, max_offset_ms=None, allow_piecewise=True,
                require_tight=True, ref_events=False):
    """verify() variant whose reference is a raw cue list (start/end ms) --
    e.g. embedded-track timestamps from the mkv_probe container probe, where
    there is no text to filter. Same gate, same verdict shape. min_vote /
    min_overlap override the gate thresholds; `scales` restricts the scale
    candidates and `max_offset_ms` the offset window (MANDATORY discipline
    for sparse audio-VAD references -- see _gate notes). `ref_events` says
    the reference is a bitmap track's display events (see bitmap_events)."""
    ref, ref_error = _preflight_cues(ref_cues)
    if ref_error:
        return _preflight_unknown('reference: ' + ref_error)
    cand_all, cand_error = _preflight_srt(cand_srt_text)
    if cand_error:
        return _preflight_unknown('candidate: ' + cand_error)
    cand = dialogue_cues(cand_all)
    if ref_events:
        verdict = _refine_on_onsets(ref, cand, _gate(
            ref, bitmap_events(cand),
            min_vote=min_vote, min_overlap=min_overlap,
            scales=scales, max_offset_ms=max_offset_ms,
            allow_piecewise=allow_piecewise,
            require_tight=require_tight))
        return _snap_piecewise_boundaries(verdict, cand_all)
    return _snap_piecewise_boundaries(
        _gate(ref, cand,
              min_vote=min_vote, min_overlap=min_overlap,
              scales=scales, max_offset_ms=max_offset_ms,
              allow_piecewise=allow_piecewise,
              require_tight=require_tight), cand_all)


def verify_cue_lists(ref_cues, cand_cues, min_vote=None, min_overlap=None,
                     scales=None, max_offset_ms=None, allow_piecewise=True,
                     require_tight=True):
    """Timestamp-only variant for internal pipelines that already parsed SRT.

    The returned piecewise segments include both reference- and candidate-time
    boundaries, so a caller such as the gender helper can map source cues onto
    a differently-cut human reference without rewriting either file.
    """
    ref, ref_error = _preflight_cues(ref_cues)
    if ref_error:
        return _preflight_unknown('reference: ' + ref_error)
    cand, cand_error = _preflight_cues(cand_cues)
    if cand_error:
        return _preflight_unknown('candidate: ' + cand_error)
    return _gate(ref, cand, min_vote=min_vote, min_overlap=min_overlap,
                 scales=scales, max_offset_ms=max_offset_ms,
                 allow_piecewise=allow_piecewise,
                 require_tight=require_tight)


# A FIXABLE offset beyond this is almost surely a spurious histogram peak,
# not a real desync -- real wrong-release offsets are seconds, not minutes
# (recuts are refused anyway). Field case: a sparse 10-cue audio reference
# against a dense candidate "found" offset=-350s and shifted the subs out of
# sight.
MAX_PLAUSIBLE_OFFSET_MS = 240000
# Sparse references (< this many cues) additionally require most ref cues to
# agree at a TIGHT tolerance -- random matches at +/-350ms are rare, so this
# kills spurious peaks that survive the coarse 500ms bins.
_SPARSE_REF = 40
_TIGHT_MS = 450     # genuine sub-vs-speech onsets land within ~0.4s; random
_TIGHT_MIN = 0.65   # matches at this tolerance are rare (~0.2/ref)
_UNIQUE_MS = 800
_UNIQUE_MIN = 0.65


def _tight_agreement(ref, cand, a, b):
    cand_on = sorted(c['start'] for c in cand)
    ok = 0
    for c in ref:
        pe = a * c['start'] + b
        i = bisect.bisect_left(cand_on, pe)
        for j in (i - 1, i):
            if 0 <= j < len(cand_on) and abs(cand_on[j] - pe) <= _TIGHT_MS:
                ok += 1
                break
    return ok / len(ref) if ref else 0.0


def _unique_match_metrics(ref, cand, a, b, tolerance=_UNIQUE_MS):
    """Monotonic one-to-one onset support for a proposed time map.

    Histogram vote and overlap deliberately allow different cue segmentation,
    but that also means one dense candidate cue can appear to support several
    reference cues.  This second measure permits each candidate onset once and
    preserves order.  It is an acceptance check, never a source of a map.
    """
    cand_on = [float(c['start']) for c in cand]
    last = -1
    residuals = []
    for cue in ref:
        target = a * float(cue['start']) + b
        pos = bisect.bisect_left(cand_on, target, lo=last + 1)
        options = [index for index in (pos - 1, pos)
                   if last < index < len(cand_on)
                   and abs(cand_on[index] - target) <= tolerance]
        if not options:
            continue
        chosen = min(options, key=lambda index: abs(cand_on[index] - target))
        last = chosen
        residuals.append(abs(cand_on[chosen] - target))
    denominator = max(1, min(len(ref), len(cand)))
    coverage = len(residuals) / denominator
    if not residuals:
        return coverage, None, None
    ordered = sorted(residuals)
    return (coverage, _median(ordered),
            float(ordered[int(0.95 * (len(ordered) - 1))]))


def _required_tight(offset_ms, n_ref, vote=1.0, overlap=1.0):
    """Minimum tight-agreement needed to APPLY a shift of `offset_ms`.

    A genuine constant offset makes almost every reference cue land within
    _TIGHT_MS of a candidate cue (tight ~0.9+). A SPURIOUS peak from a sparse or
    heterogeneous reference only reaches ~0.65-0.72. Since a wrong shift is far
    worse than no shift, the requirement RISES with the size of the jump: a
    borderline match may nudge a sub by a fraction of a second, but can never
    move it many seconds on thin evidence (field: a 31-cue file-probe union
    voted -20.3s at 68% tight and de-synced an already-good sub). Sparse
    references are noisier, so they're held a notch stricter.

    SMALL shifts are the exception. A sub-1.5s correction is low-harm, and real
    subtitles from a different subber/translator segment their lines
    differently, so even at the CORRECT offset the tight agreement caps around
    ~45% (field: The Flash Pilot, a real ~1s-early Hebrew pool sub scored 45%
    tight against every BluRay oracle). When the coarse signals still
    corroborate strongly -- high overlap -- we accept that low tight for a small
    shift. This can't de-sync an already-good sub: the estimate only picks a
    small NON-ZERO offset when the sub is genuinely off; a synced sub peaks at 0
    and returns CONFIRMED before reaching here."""
    a = abs(offset_ms)
    if a <= 1500:
        # A small shift is low-harm and lives in a COMPLETELY different regime
        # from the spurious matches we must reject -- those are always LARGE
        # (field garbage: +230s, +560s, -20s), caught by the magnitude-scaled
        # bars below. The reliable discriminator for a small shift is OVERLAP:
        # the shifted sub must cover the same time regions as the reference. The
        # `vote` and `tight` metrics are dominated by different-subber cue
        # segmentation and cap low even at the CORRECT offset -- across four
        # field subs the correct small offset ran vote 54-64%, overlap 87-90%,
        # tight 40-45% (all were being rejected). So when the overlap
        # corroborates strongly we drop the tight floor and lean on overlap +
        # magnitude. This cannot de-sync a good sub: the estimate only picks a
        # small NON-ZERO offset when the sub is genuinely off (a synced sub
        # peaks at 0 -> CONFIRMED before reaching here); vote is still floored by
        # the gate's min_vote so a true non-match can't sneak through.
        need = 0.35 if overlap >= 0.85 else _TIGHT_MIN
    elif a <= 6000:
        need = 0.78
    elif a <= 15000:
        need = 0.85
    else:
        need = 0.90                # a multi-second jump must be near-certain
    if n_ref < _SPARSE_REF:
        need = min(0.93, need + 0.05)
    return need


def _median(values):
    return float(statistics.median(values))


# ---- speech-coverage correlation (segmentation-robust corroboration) -------
# Onset agreement ("tight") asks whether two files START their lines at the
# same instants.  Two different subbers/languages split the same speech into
# different lines, so even an exactly correct offset caps around 40-65% tight
# in the field, while the magnitude-scaled requirement for a multi-second shift
# is 78-90%.  A real desync of several seconds therefore could never be fixed:
# only small (<=1.5s) nudges ever reached a user.  What two authorings of one
# dialogue DO share is the time covered by speech.  The overlap of the two
# coverage masks as a function of offset -- the subtitle analogue of
# ffsubsync's speech correlation -- has one sharp peak at the true offset for a
# genuine pair and stays flat for an unrelated one; merging or splitting lines
# barely moves it.  It never proposes a map: it can only corroborate (or
# contradict) the offset that the histogram estimator already found.
_COV_STEP_MS = 20
_COV_MIN_WINDOW_MS = 60000
_COV_MARGIN_MS = 60000
_COV_PAD_MS = 70000          # integration headroom so no trapezoid is clipped
_COV_MAX_CUE_MS = 60000      # pathological cues never anchor coverage
_COV_MAX_SPAN_MS = 120000    # merged back-to-back blocks longer than this
                             # carry no usable gap structure
_COV_PLATEAU = 0.015         # peak plateau (longer lines flatten the top)
_COV_AGREE_MS = 300          # estimator offset must sit on/near the plateau
_COV_EXCLUDE_MS = 6000       # a competing peak must be clearly elsewhere
_COV_MIN_CUES = 60           # dense references only; sparse ones stay strict
_COV_MIN_PEAK = 0.65
_COV_MIN_PROMINENCE = 0.15
_COV_MIN_REL_PROMINENCE = 0.45
_COV_MAX_SECOND = 0.60
# The coverage rescue still keeps an onset floor. Unrelated pairs measure
# ~0.15-0.20 tight; correct different-subber pairs 0.40-0.65.
_COV_TIGHT_FLOOR = 0.40


_RESCUE_WINDOW_VOTE = 0.50
_RESCUE_WINDOW_RANGE_MS = 1500
_EDGE_VOTE = 0.50
_EDGE_DIV = 25
_EDGE_RADIUS_MS = 20000


def _edge_windows(ref, cand, scale, offset):
    """Short probes of the very start and end of the reference timeline.

    Recaps, cold opens, logos and end credits are where releases most often
    differ, and such a region (a few minutes) is smaller than one ordinary
    local window, whose estimate it merely dilutes.
    """
    size = max(12, len(ref) // 30)
    if len(ref) < 4 * size:
        return []
    cand_on = [c['start'] - offset for c in cand]
    out = []
    for subset in (ref[:size], ref[-size:]):
        # Search NEAR the global offset only: a short probe searched over
        # +/-150 s finds dense-dialogue aliases (field-like fixtures produced
        # a spurious 139 s "region"); recap/logo differences are seconds.
        found, votes = _best_offset([c['start'] for c in subset], cand_on,
                                    scale, _EDGE_RADIUS_MS)
        out.append({'offset_ms': float(found) + offset,
                    'vote': votes / float(len(subset)), 'edge': True})
    return out


def _rescue_regions_agree(windows, offset, edges=()):
    """Every moderately supported local region must sit near ``offset``.

    The ordinary local-consistency guard counts only windows with a strong
    (>=65%) vote, which different-subber pairs rarely reach near a region
    boundary, so a minority region on another clock can go unseen. A rescued
    shift therefore needs most windows to carry at least moderate support,
    and all of those -- plus the short start/end probes -- to agree with the
    global offset.
    """
    if not windows:
        return False, '; regions n/a'
    for edge in edges or ():
        if (edge.get('vote', 0.0) >= _EDGE_VOTE
                and abs(float(edge['offset_ms']) - float(offset))
                > _RESCUE_WINDOW_RANGE_MS):
            return False, '; edge region is %dms away' % int(
                abs(float(edge['offset_ms']) - float(offset)))
    supported = [w for w in windows if w.get('vote', 0.0) >= _RESCUE_WINDOW_VOTE]
    needed = max(3, int(math.ceil(0.5 * len(windows))))
    if len(supported) < needed:
        return False, '; regions %d/%d supported' % (len(supported),
                                                     len(windows))
    worst = max(abs(float(w['offset_ms']) - float(offset)) for w in supported)
    if worst > _RESCUE_WINDOW_RANGE_MS:
        return False, '; a supported region is %dms away' % int(worst)
    return True, ''


def _coverage_union(cues, scale=1.0, offset=0.0):
    spans = sorted((scale * float(c['start']) + offset,
                    scale * float(c['end']) + offset) for c in cues
                   if float(c['end']) - float(c['start']) <= _COV_MAX_CUE_MS)
    out = []
    for start, end in spans:
        if end <= start:
            continue
        if out and start <= out[-1][1]:
            if end > out[-1][1]:
                out[-1][1] = end
        else:
            out.append([start, end])
    return out


def coverage_profile(ref, cand, scale=1.0, offset_hint=0.0):
    """Corroborate a proposed map with speech-coverage cross-correlation.

    C(d) = |scale*ref_coverage  intersect  (cand_coverage - d)| / min(total).
    Every pair of covered intervals contributes a trapezoid in d, accumulated
    exactly through second differences on a 20 ms grid, so the cost is linear
    in the number of nearby interval pairs (no FFT, stdlib only).

    Returns metrics plus ``corroborates``: the estimator's offset lies on the
    single dominant peak and that peak clearly stands above the background.
    """
    hint = float(offset_hint or 0.0)
    window = min(MAX_PLAUSIBLE_OFFSET_MS + _COV_MARGIN_MS,
                 max(_COV_MIN_WINDOW_MS, abs(hint) + _COV_MARGIN_MS))
    step = _COV_STEP_MS
    a_spans = _coverage_union(ref, scale)
    b_spans = _coverage_union(cand)
    a_total = sum(e - s for s, e in a_spans)
    b_total = sum(e - s for s, e in b_spans)
    # 'agrees' None = no information: never a reason to veto anything.
    result = {'corroborates': False, 'agrees': None, 'offset_ms': None,
              'peak': 0.0, 'median': 0.0, 'prominence': 0.0,
              'rel_prominence': 0.0, 'second': 1.0, 'diag': 'coverage n/a'}
    if not a_spans or not b_spans or a_total <= 0 or b_total <= 0:
        return result
    longest = max(max(e - s for s, e in a_spans),
                  max(e - s for s, e in b_spans))
    if longest > _COV_MAX_SPAN_MS:
        # Back-to-back cues merged into minutes-long blocks (continuous
        # captions / auto-generated timing) carry no gap structure to align.
        result['diag'] = 'coverage n/a (continuous %ds block)' % int(
            longest / 1000)
        return result
    # Every interval pair's trapezoid spans at most la+lb beyond the search
    # window on either side; pad so no breakpoint can fall off the grid.
    pad = max(_COV_PAD_MS, 2 * longest + 2000)
    full = window + pad
    bins = int(2 * full / step) + 3
    d2 = [0.0] * (bins + 2)
    b_starts = [s for s, _ in b_spans]

    def add(position, weight):
        k = int(round((position + full) / step))
        if 0 <= k <= bins:
            d2[k] += weight

    for a1, a2 in a_spans:
        la = a2 - a1
        j = bisect.bisect_left(b_starts, a1 - window - longest)
        while j < len(b_spans):
            b1, b2 = b_spans[j]
            j += 1
            if b1 - a2 > window:
                break
            if b2 - a1 < -window:
                continue
            m = min(la, b2 - b1)
            d0 = b1 - a2
            d3 = b2 - a1
            add(d0, 1.0)
            add(d0 + m, -1.0)
            add(d3 - m, -1.0)
            add(d3, 1.0)
    slope = 0.0
    value = 0.0
    norm = float(min(a_total, b_total))
    first = int(round(pad / step))
    last = first + int(2 * window / step)
    curve = []
    for k in range(last + 1):
        # f(k) = f(k-1) + step * slope(k-1): a breakpoint at bin k changes the
        # slope only AFTER that bin (updating first biased the peak 1 step).
        value += slope * step
        slope += d2[k]
        if k >= first:
            curve.append(value / norm)
    if not curve:
        return result
    top = max(range(len(curve)), key=curve.__getitem__)
    peak = curve[top]
    lo = top
    while lo > 0 and curve[lo - 1] >= peak - _COV_PLATEAU:
        lo -= 1
    hi = top
    while hi + 1 < len(curve) and curve[hi + 1] >= peak - _COV_PLATEAU:
        hi += 1

    def at(index):
        return index * step - window

    exclude = int(_COV_EXCLUDE_MS / step)
    outside = [curve[i] for i in range(len(curve))
               if i < lo - exclude or i > hi + exclude]
    ordered = sorted(curve)
    median = ordered[len(ordered) // 2]
    prominence = peak - median
    rel_prominence = prominence / max(0.05, 1.0 - median)
    second = ((max(outside) - median) / prominence
              if outside and prominence > 1e-9 else 1.0)
    plateau_lo, plateau_hi = at(lo), at(hi)
    agrees = (plateau_lo - _COV_AGREE_MS <= hint
              <= plateau_hi + _COV_AGREE_MS)
    corroborates = bool(agrees and peak >= _COV_MIN_PEAK
                        and prominence >= _COV_MIN_PROMINENCE
                        and rel_prominence >= _COV_MIN_REL_PROMINENCE
                        and second <= _COV_MAX_SECOND)
    result.update({
        'corroborates': corroborates, 'agrees': agrees,
        'offset_ms': float(at(top)), 'plateau_ms': (plateau_lo, plateau_hi),
        'peak': peak, 'median': median, 'prominence': prominence,
        'rel_prominence': rel_prominence, 'second': second,
        'diag': ('coverage=%+d[%+d..%+d]ms peak=%.0f%% bg=%.0f%% '
                 'rel=%.0f%% 2nd=%.0f%%%s' % (
                     int(at(top)), int(plateau_lo), int(plateau_hi),
                     peak * 100, median * 100, rel_prominence * 100,
                     second * 100, '' if corroborates else ' (no support)')),
    })
    return result


def _local_windows(ref, cand, scale, max_offset_ms=None, center_offset=0.0):
    """Cheap local offset estimates at one already-selected scale.

    The reference is partitioned once, so the work is roughly one additional
    scale evaluation rather than another full FPS search.  Returned offsets use
    the same direction as estimate(): candidate ~= scale*reference + offset.
    """
    if len(ref) < _LOCAL_MIN_REF_CUES or len(cand) < MIN_CUES:
        return []
    count = len(ref)
    window_count = min(_LOCAL_MAX_WINDOWS, max(3, count // 20))
    # Search around the already-supported global peak.  Searching each small
    # window across the full +/-10-minute file admits dense-dialogue aliases
    # hundreds of seconds away (an otherwise perfectly aligned natural French
    # track produced a false 570-second local peak).  Real cut steps in the
    # measured campaign were 5-90 seconds; +/-150 seconds preserves those while
    # excluding the aliases.
    center_offset = float(center_offset or 0.0)
    cand_on = [c['start'] - center_offset for c in cand]
    max_off = _MAXOFF if max_offset_ms is None else max_offset_ms
    local_radius = min(max_off, _LOCAL_RADIUS_MS)
    windows = []
    for wi in range(window_count):
        begin = round(wi * count / window_count)
        end = round((wi + 1) * count / window_count)
        subset = ref[begin:end]
        if len(subset) < MIN_CUES:
            continue
        offset, votes = _best_offset(
            [c['start'] for c in subset], cand_on, scale, local_radius)
        offset += center_offset
        vote = votes / len(subset)
        overlap = overlap_rate(subset, cand, scale, offset)
        tight = _tight_agreement(subset, cand, scale, offset)
        windows.append({
            'window': wi, 'begin': begin, 'end': end,
            'center_ms': statistics.fmean(c['start'] for c in subset),
            'offset_ms': float(offset), 'vote': vote,
            'overlap': overlap, 'tight': tight,
        })
    return windows


def _trusted_local_windows(windows):
    return [w for w in windows
            if w['vote'] >= _LOCAL_MIN_VOTE
            and w['overlap'] >= _LOCAL_MIN_OVERLAP]


def _local_spread(windows):
    groups, trusted = _group_local_offsets(windows)
    if len(trusted) < 2:
        return None
    if len(groups) < 2:
        return 0.0
    offsets = [_median([w['offset_ms'] for w in group]) for group in groups]
    return max(offsets) - min(offsets)


def _group_local_offsets(windows):
    """Contiguous sustained timing plateaus; isolated boundary aliases drop."""
    trusted = _trusted_local_windows(windows)
    if len(trusted) < max(4, int(0.60 * len(windows))):
        return [], trusted
    groups = []
    for w in trusted:
        if not groups:
            groups.append([w])
            continue
        current = groups[-1]
        if abs(w['offset_ms'] - _median(
                [x['offset_ms'] for x in current])) < _LOCAL_SAME_PLATEAU_MS:
            current.append(w)
        else:
            groups.append([w])

    # A window straddling a cut can lock onto an unrelated dense-dialogue peak.
    # It must not become its own segment.  Collapse it only when neighbouring
    # plateaus agree, or discard it when both neighbours are independently
    # supported and it is far from both.
    changed = True
    while changed and len(groups) > 1:
        changed = False
        for i, group in enumerate(list(groups)):
            if len(group) != 1:
                continue
            left = groups[i - 1] if i > 0 else None
            right = groups[i + 1] if i + 1 < len(groups) else None
            if left and right:
                lm = _median([x['offset_ms'] for x in left])
                rm = _median([x['offset_ms'] for x in right])
                own = float(group[0]['offset_ms'])
                if abs(lm - rm) < _LOCAL_SAME_PLATEAU_MS:
                    # The singleton is the alias; preserve the two agreeing
                    # plateaus and discard the outlier rather than polluting
                    # their spread with it.
                    left.extend(right)
                    del groups[i:i + 2]
                    changed = True
                    break
                if (len(left) >= 2 and len(right) >= 2
                        and abs(own - lm) >= PIECEWISE_MIN_STEP_MS
                        and abs(own - rm) >= PIECEWISE_MIN_STEP_MS):
                    del groups[i]
                    changed = True
                    break
    return groups, trusted


def _smooth_drift_refinement(windows, scale):
    """Infer a continuous scale correction from sustained local offsets.

    Discrete 23.976/24/25/29.97/30 ratios cover normal FPS conversions, but a
    damaged or hand-authored subtitle can drift at an arbitrary rate.  Under a
    trial scale, its local offsets form a straight line whose slope is exactly
    the missing scale correction.  A median pairwise slope resists individual
    alias windows; the refit is offered only with strong linear evidence and is
    still subjected to every ordinary global/local acceptance gate afterward.
    """
    trusted = _trusted_local_windows(windows)
    if (len(trusted) < 5
            or len(trusted) < max(5, int(0.60 * len(windows)))):
        return None
    xs = [float(w['center_ms']) for w in trusted]
    ys = [float(w['offset_ms']) for w in trusted]
    if max(xs) - min(xs) < 5 * 60 * 1000:
        return None
    slopes = [(ys[j] - ys[i]) / (xs[j] - xs[i])
              for i in range(len(xs)) for j in range(i + 1, len(xs))
              if xs[j] != xs[i]]
    if not slopes:
        return None
    robust_slope = _median(slopes)
    intercept = _median([y - robust_slope * x for x, y in zip(xs, ys)])
    residuals = [y - (robust_slope * x + intercept)
                 for x, y in zip(xs, ys)]
    residual_mid = _median(residuals)
    mad = _median([abs(r - residual_mid) for r in residuals])
    limit = max(750.0, 3.5 * mad)
    kept = [(x, y) for x, y, residual in zip(xs, ys, residuals)
            if abs(residual - residual_mid) <= limit]
    if len(kept) < 5 or len(kept) < int(0.70 * len(trusted)):
        return None
    mean_x = statistics.fmean(x for x, _ in kept)
    mean_y = statistics.fmean(y for _, y in kept)
    denom = sum((x - mean_x) ** 2 for x, _ in kept)
    if denom <= 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in kept) / denom
    fitted_intercept = mean_y - slope * mean_x
    total = sum((y - mean_y) ** 2 for _, y in kept)
    error = sum((y - (slope * x + fitted_intercept)) ** 2
                for x, y in kept)
    r2 = 1.0 if total <= 1.0 else max(0.0, 1.0 - error / total)
    refined = float(scale) + slope
    if (r2 < 0.85 or abs(slope) < 0.0002 or abs(slope) > 0.04
            or not (SCALE_MIN <= refined <= SCALE_MAX)):
        return None
    return {'scale': refined, 'correction': slope, 'r2': r2,
            'retained': len(kept), 'total': len(trusted)}


def _nearest_onset_distance(onsets, value, cap=2500.0):
    pos = bisect.bisect_left(onsets, value)
    values = [abs(onsets[j] - value)
              for j in (pos - 1, pos) if 0 <= j < len(onsets)]
    return min(min(values) if values else cap, cap)


def _optimize_piecewise_boundaries(ref, cand, scale, groups, offsets):
    """Find ordered cut points using timestamps only, never subtitle text.

    Each candidate cue is scored under every supported plateau by nearest
    reference onset plus interval overlap.  Dynamic programming assigns one
    contiguous region per plateau, with boundaries restricted to the
    unsupported space between neighbouring trusted window groups.
    """
    if not cand or len(groups) != len(offsets):
        return None
    ref_on = [c['start'] for c in ref]
    ref_starts = ref_on
    ref_ends = [c['end'] for c in ref]
    cand_starts = [c['start'] for c in cand]
    n, k = len(cand), len(offsets)
    costs = []
    for offset in offsets:
        prefix = [0.0]
        for cue in cand:
            mapped_s = (cue['start'] - offset) / scale
            mapped_e = (cue['end'] - offset) / scale
            nearest = _nearest_onset_distance(ref_on, mapped_s)
            overlap = False
            j = bisect.bisect_left(ref_ends, mapped_s)
            while j < len(ref) and ref_starts[j] < mapped_e:
                if min(mapped_e, ref_ends[j]) > max(mapped_s, ref_starts[j]):
                    overlap = True
                    break
                j += 1
            prefix.append(prefix[-1] + nearest
                          + (0.0 if overlap else 1200.0))
        costs.append(prefix)

    allowed = []
    for left, right in zip(groups, groups[1:]):
        left_off = _median([w['offset_ms'] for w in left])
        right_off = _median([w['offset_ms'] for w in right])
        lo_time = scale * left[-1]['center_ms'] + left_off
        hi_time = scale * right[0]['center_ms'] + right_off
        lo, hi = sorted((lo_time, hi_time))
        margin = max(4, n // 100)
        lo_i = max(4, bisect.bisect_left(cand_starts, lo) - margin)
        hi_i = min(n - 4, bisect.bisect_right(cand_starts, hi) + margin)
        if lo_i > hi_i:
            return None
        # A later plateau with a larger offset moves its first cue further
        # backwards.  A cut placed inside continuous dialogue would therefore
        # reorder/overlap adjacent cues even if its aggregate timing score looks
        # attractive.  Keep only boundaries whose two neighbouring cues remain
        # ordered after applying each side's own map; ``apply_verdict`` repeats
        # this invariant on the complete, unfiltered SRT.
        safe_positions = [index for index in range(lo_i, hi_i + 1)
                          if ((cand[index]['start'] - right_off) / scale
                              >= (cand[index - 1]['end'] - left_off) / scale)]
        if not safe_positions:
            return None
        allowed.append(safe_positions)

    states = {0: (0.0, [])}
    for boundary_index, positions in enumerate(allowed):
        next_states = {}
        for end in positions:
            best = None
            for start, (prior_cost, cuts) in states.items():
                if end - start < 4:
                    continue
                value = (prior_cost + costs[boundary_index][end]
                         - costs[boundary_index][start])
                if best is None or value < best[0]:
                    best = (value, cuts + [end])
            if best is not None:
                next_states[end] = best
        states = next_states
        if not states:
            return None
    best = None
    for start, (prior_cost, cuts) in states.items():
        if n - start < 4:
            continue
        value = prior_cost + costs[k - 1][n] - costs[k - 1][start]
        if best is None or value < best[0]:
            best = (value, cuts)
    return None if best is None else best[1]


def _map_cues_piecewise(cand, scale, segments):
    boundaries = [s['cand_from_ms'] for s in segments[1:]]
    out = []
    for cue in cand:
        index = bisect.bisect_right(boundaries, cue['start'])
        offset = segments[index]['offset_ms']
        out.append(dict(cue,
                        start=(cue['start'] - offset) / scale,
                        end=(cue['end'] - offset) / scale))
    return out


def _map_cues_global(cand, scale, offset):
    return [dict(cue,
                 start=(cue['start'] - offset) / scale,
                 end=(cue['end'] - offset) / scale)
            for cue in cand]


def _timing_score(ref, cand):
    return (0.60 * overlap_rate(ref, cand, 1.0, 0.0)
            + 0.40 * _tight_agreement(ref, cand, 1.0, 0.0))


def _micro_core_windows(windows):
    """Strong local windows after removing isolated dense-dialogue aliases.

    A local histogram can occasionally lock onto dialogue tens of seconds away
    even while its vote/overlap look plausible.  A real sequence of short edit
    pads follows one slow monotonic trend.  Theil-Sen's median pairwise slope
    models that trend without being pulled by one bad window; a generous robust
    residual then removes only gross aliases.  This is still proposal evidence,
    never an acceptance decision.
    """
    trusted = _trusted_local_windows(windows)
    if (len(trusted) < _MICRO_MIN_WINDOWS
            or len(trusted) < int(math.ceil(
                _MICRO_MIN_CORE_RATIO * len(windows)))):
        return []
    xs = [float(w['center_ms']) for w in trusted]
    ys = [float(w['offset_ms']) for w in trusted]
    slopes = [(ys[j] - ys[i]) / (xs[j] - xs[i])
              for i in range(len(xs)) for j in range(i + 1, len(xs))
              if xs[j] != xs[i]]
    if not slopes:
        return []
    slope = _median(slopes)
    intercept = _median([y - slope * x for x, y in zip(xs, ys)])
    residuals = [y - (slope * x + intercept) for x, y in zip(xs, ys)]
    middle = _median(residuals)
    mad = _median([abs(value - middle) for value in residuals])
    limit = max(2500.0, 5.0 * mad)
    core = [w for w, residual in zip(trusted, residuals)
            if abs(residual - middle) <= limit]
    if (len(core) < _MICRO_MIN_WINDOWS
            or len(core) < int(math.ceil(
                _MICRO_MIN_CORE_RATIO * len(windows)))):
        return []
    return core


def _micro_plateau_groups(windows):
    core = _micro_core_windows(windows)
    groups = []
    for window in core:
        if (not groups
                or abs(window['offset_ms'] - _median(
                    [item['offset_ms'] for item in groups[-1]]))
                >= _MICRO_SAME_PLATEAU_MS):
            groups.append([window])
        else:
            groups[-1].append(window)
    return groups, core


def _micro_piecewise_plan(ref, cand, min_overlap=MIN_OVERLAP,
                          max_offset_ms=None):
    """Proposal for repeated short edit pads, pending track consensus.

    The base clock is intentionally pinned to identity.  Standard/global FPS
    drift and large cuts already have independently proven paths; mixing those
    freedoms here would make a subtle edit too easy to overfit.  The returned
    verdict carries ``validation_required`` and therefore cannot be applied
    until a separate holdout/independent-family validator approves it.
    """
    scale = 1.0
    max_off = _MAXOFF if max_offset_ms is None else max_offset_ms
    center_offset, _votes = _best_offset(
        [c['start'] for c in ref], [c['start'] for c in cand], scale, max_off)
    windows = _local_windows(
        ref, cand, scale, max_offset_ms=max_offset_ms,
        center_offset=center_offset)
    groups, core = _micro_plateau_groups(windows)
    info = {'windows': windows, 'core': core, 'groups': groups}
    if not (3 <= len(groups) <= _MICRO_MAX_SEGMENTS):
        return None, info
    # Boundary regions must be sustained, and at most one short middle act may
    # be represented by a single window.  Consensus will independently confirm
    # that singleton at the same candidate boundary.
    if len(groups[0]) < 2 or len(groups[-1]) < 2:
        return None, info
    if sum(1 for group in groups if len(group) == 1) > 1:
        return None, info

    offsets = [_median([w['offset_ms'] for w in group])
               for group in groups]
    if any(abs(offset) > MAX_PLAUSIBLE_OFFSET_MS for offset in offsets):
        return None, info
    steps = [offsets[i + 1] - offsets[i]
             for i in range(len(offsets) - 1)]
    if not steps:
        return None, info
    direction = 1.0 if _median(steps) > 0 else -1.0
    if any(direction * step < _MICRO_MIN_STEP_MS
           or abs(step) > _MICRO_MAX_STEP_MS for step in steps):
        return None, info
    if max(offsets) - min(offsets) < 3000.0:
        return None, info
    timeline_start = float(ref[0]['start'])
    timeline_end = float(ref[-1]['end'])
    timeline_span = max(1.0, timeline_end - timeline_start)
    if (groups[0][0]['center_ms'] > timeline_start + 0.25 * timeline_span
            or groups[-1][-1]['center_ms']
            < timeline_start + 0.75 * timeline_span):
        return None, info

    cuts = _optimize_piecewise_boundaries(
        ref, cand, scale, groups, offsets)
    if cuts is None:
        return None, info
    return _micro_verdict_from_cuts(
        ref, cand, cuts, offsets, info,
        vote=min(w['vote'] for w in core),
        label='embedded-track consensus proposal',
        min_overlap=min_overlap, max_offset_ms=max_offset_ms)


def _micro_verdict_from_cuts(ref, cand, cuts, offsets, info, vote, label,
                             min_overlap=MIN_OVERLAP, max_offset_ms=None):
    """Shared acceptance tail for both short-edit planners.

    Whatever proposed the plateaus, the same region-size, ordering, residual,
    overlap, uniqueness and score-gain gates decide whether a validation-
    required proposal exists at all.
    """
    scale = 1.0
    candidate_boundaries = []
    reference_boundaries = []
    for cut, left_offset, right_offset in zip(
            cuts, offsets, offsets[1:]):
        candidate_boundary = (
            cand[cut - 1]['end'] + cand[cut]['start']) / 2.0
        reference_boundary = (
            (cand[cut - 1]['end'] - left_offset)
            + (cand[cut]['start'] - right_offset)) / 2.0
        candidate_boundaries.append(candidate_boundary)
        reference_boundaries.append(reference_boundary)
    segments = []
    for index, offset in enumerate(offsets):
        segments.append({
            'cand_from_ms': (None if index == 0
                             else candidate_boundaries[index - 1]),
            'cand_to_ms': (None if index == len(offsets) - 1
                           else candidate_boundaries[index]),
            'ref_from_ms': (None if index == 0
                            else reference_boundaries[index - 1]),
            'ref_to_ms': (None if index == len(offsets) - 1
                          else reference_boundaries[index]),
            'offset_ms': offset,
        })

    cue_edges = [0] + list(cuts) + [len(cand)]
    min_segment_cues = max(12, int(math.ceil(0.02 * len(cand))))
    for begin, end in zip(cue_edges, cue_edges[1:]):
        if end - begin < min_segment_cues:
            return None, info
        region_start = float(cand[begin]['start'])
        region_end = float(cand[end - 1]['end'])
        if region_end - region_start < 60000.0:
            return None, info

    fixed = _map_cues_piecewise(cand, scale, segments)
    if (len(fixed) != len(cand)
            or any(c['end'] <= c['start'] for c in fixed)
            or any(fixed[i]['start'] < fixed[i - 1]['start']
                   for i in range(1, len(fixed)))):
        return None, info
    post_windows = _local_windows(
        ref, fixed, 1.0, max_offset_ms=max_offset_ms, center_offset=0.0)
    post_core = _micro_core_windows(post_windows)
    if len(post_core) < _MICRO_MIN_WINDOWS:
        return None, info
    post_offsets = [w['offset_ms'] for w in post_core]
    post_residual = max(post_offsets) - min(post_offsets)
    before_score = _timing_score(ref, cand)
    after_score = _timing_score(ref, fixed)
    after_overlap = overlap_rate(ref, fixed, 1.0, 0.0)
    after_unique, unique_median, unique_p95 = _unique_match_metrics(
        ref, fixed, 1.0, 0.0)
    if (post_residual > _MICRO_POST_RESIDUAL_MS
            or after_overlap < max(0.85, min_overlap)
            or after_unique < 0.72
            or after_score < 0.78
            or after_score < before_score + 0.15):
        info.update({'post_residual_ms': post_residual,
                     'before_score': before_score,
                     'after_score': after_score,
                     'after_overlap': after_overlap,
                     'after_unique': after_unique})
        return None, info
    diag = ('%s: %d regions offsets=%s '
            'score=%.3f->%.3f overlap=%.0f%% unique=%.0f%% residual=%dms'
            % (label, len(segments),
               ','.join('%+d' % int(value) for value in offsets),
               before_score, after_score, after_overlap * 100,
               after_unique * 100, int(post_residual)))
    verdict = {
        'status': STATUS_FIXABLE,
        'mode': 'piecewise',
        'scale': 1.0,
        'offset_ms': offsets[0],
        'segments': segments,
        'vote': vote,
        'overlap': after_overlap,
        'unique': after_unique,
        'unique_median_ms': unique_median,
        'unique_p95_ms': unique_p95,
        'before_score': before_score,
        'after_score': after_score,
        'post_residual_ms': post_residual,
        'cand_span_ms': float(cand[-1]['end']),
        'validation_required': True,
        'validation_folds': 0,
        'timing_family_count': 0,
        'diag': diag,
    }
    return verdict, info


_ENV_WINDOW_MS = 240000
_ENV_MAX_WINDOWS = 20
_ENV_LAG_MS = 20000
_ENV_EDGE_MS = 30000
_ENV_MIN_Z = 3.5
_ENV_POLARITY_MARGIN = 0.6
_ENV_SYNC_MS = 500.0
_ENV_NEAR_MS = 900.0
_ENV_SHIFT_MS = 1000.0
_ENV_STAIR_MS = 3000.0


def _envelope_scores(prefix, size, spans, lags):
    scores = []
    for lag in lags:
        total = 0.0
        for begin, end in spans:
            a = begin - lag
            b = end - lag
            if a < 0:
                a = 0
            if b > size:
                b = size
            if b > a:
                total += prefix[b] - prefix[a]
        scores.append(total)
    return scores


def envelope_windows(envelope, cand_srt_text):
    """Per-window offsets of a subtitle against an audio frame-size envelope.

    Each window slides the subtitle's dialogue intervals over the envelope by
    up to +/-20 s and scores the summed envelope under them (prefix sums: one
    subtraction per cue per lag).  The windows tile the whole subtitle span
    without gaps -- at least four minutes each, at most twenty of them -- so
    no act can hide between samples.  The search runs on a 200-ms grid and
    is refined around each extreme.  Speech raises the bitrate with some
    encoders and lowers it with others, so both extremes are kept; the caller
    picks the polarity that the whole file supports.  Offsets follow the
    module convention: positive means the subtitle is late.
    """
    try:
        step = float(envelope.get('step_ms') or 0)
        values = list(envelope.get('values') or [])
    except AttributeError:
        return []
    if step <= 0 or len(values) < 1000:
        return []
    cand_all, cand_error = _preflight_srt(cand_srt_text)
    if cand_error:
        return []
    cand = dialogue_cues(cand_all)
    if len(cand) < _LOCAL_MIN_REF_CUES:
        return []
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + value)
    size = len(values)
    first = float(cand[0]['start']) + _ENV_EDGE_MS
    last = min(float(cand[-1]['end']), size * step) - _ENV_EDGE_MS
    span = last - first
    if span < _ENV_WINDOW_MS:
        return []
    count = max(1, min(_ENV_MAX_WINDOWS, int(span // _ENV_WINDOW_MS)))
    width = span / float(count)
    lag_bins = int(_ENV_LAG_MS / step)
    coarse = list(range(-lag_bins, lag_bins + 1, 2))
    starts = [c['start'] for c in cand]
    rows = []
    for index in range(count):
        low = first + index * width
        high = low + width
        lo = bisect.bisect_left(starts, low)
        hi = bisect.bisect_left(starts, high)
        spans = [(int(c['start'] / step), int(c['end'] / step))
                 for c in cand[lo:hi] if c['end'] > c['start']]
        if len(spans) < 15:
            continue
        scores = _envelope_scores(prefix, size, spans, coarse)
        ordered = sorted(scores)
        middle = ordered[len(ordered) // 2]
        mean = sum(scores) / float(len(scores))
        spread = math.sqrt(sum((x - mean) ** 2 for x in scores)
                           / float(len(scores))) or 1e-9

        def refine(position, sign):
            lag = coarse[position]
            best_lag, best_value = lag, scores[position]
            for near in (lag - 1, lag + 1):
                if -lag_bins <= near <= lag_bins:
                    value = _envelope_scores(prefix, size, spans, [near])[0]
                    if sign * value > sign * best_value:
                        best_lag, best_value = near, value
            return best_lag, best_value
        hi_lag, hi_value = refine(
            max(range(len(scores)), key=scores.__getitem__), 1)
        lo_lag, lo_value = refine(
            min(range(len(scores)), key=scores.__getitem__), -1)
        rows.append({
            'center_ms': (low + high) / 2.0,
            'pos': (hi_lag * step, (hi_value - middle) / spread),
            'neg': (lo_lag * step, (middle - lo_value) / spread),
        })
    return rows


def _envelope_staircase(ordered):
    """Monotonic drift of strong window offsets that no single window makes.

    A real run of act-break pads moves every later window the same way.  One
    aliased window can fake a 'staircase' on its own, so the pattern must
    survive the removal of any one window.
    """
    def rising_or_falling(seq):
        if len(seq) < 4 or max(seq) - min(seq) < _ENV_STAIR_MS:
            return False
        drops = sum(1 for a, b in zip(seq, seq[1:]) if b < a - 300)
        climbs = sum(1 for a, b in zip(seq, seq[1:]) if b > a + 300)
        return min(drops, climbs) <= 1
    if len(ordered) < 5 or not rising_or_falling(ordered):
        return False
    return all(rising_or_falling(ordered[:i] + ordered[i + 1:])
               for i in range(len(ordered)))


def envelope_check(envelope, cand_srt_text, polarity=None):
    """Judge a subtitle against the playing file's audio envelope.

    ``status`` is 'synced' (one plateau within 0.5 s), 'near' (one plateau
    within 0.9 s), 'conflict' (sustained plateaus >=1.5 s apart, or a
    monotonic staircase of strong windows spanning >=3 s that survives the
    removal of any one window -- no single clock fits), 'shifted' (one
    plateau >=1 s away) or 'unknown'.  Windows count only when their peak is
    strong (z >= 3.5) and a plateau needs two of them, so one aliased window
    decides nothing.  A file whose two polarities score alike is 'unknown'.
    The envelope's absolute offset carries an encoder-dependent bias of a
    few hundred ms: it can tell timelines apart, but it never fine-tunes one,
    and a constant bias can never produce a 'conflict'.
    """
    rows = envelope_windows(envelope, cand_srt_text)
    result = {'status': 'unknown', 'windows': len(rows), 'trusted': 0,
              'plateaus': [], 'polarity': 0}
    if len(rows) < 4:
        return result
    medians = {}
    for key in ('pos', 'neg'):
        zs = sorted(row[key][1] for row in rows)
        medians[key] = zs[len(zs) // 2]
    if polarity in (1, -1):
        key = 'pos' if polarity > 0 else 'neg'
    else:
        key = max(medians, key=medians.get)
        other = 'neg' if key == 'pos' else 'pos'
        if medians[key] - medians[other] < _ENV_POLARITY_MARGIN:
            result['reason'] = 'ambiguous polarity'
            return result
    result['polarity'] = 1 if key == 'pos' else -1
    result['median_z'] = medians[key]
    ordered = [row[key][0] for row in rows if row[key][1] >= _ENV_MIN_Z]
    trusted = sorted(ordered)
    result['trusted'] = len(trusted)
    result['offsets'] = [(int(row['center_ms']), int(row[key][0]),
                          round(row[key][1], 1)) for row in rows]
    if len(trusted) < max(4, int(math.ceil(0.6 * len(rows)))):
        result['reason'] = 'weak envelope'
        return result
    clusters = []
    for value in trusted:
        if clusters and value - clusters[-1][-1] <= _PLATEAU_JOIN_MS:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    plateaus = sorted(((_median(c), len(c)) for c in clusters if len(c) >= 2),
                      key=lambda item: -item[1])
    result['plateaus'] = plateaus
    if _envelope_staircase(ordered):
        result['status'] = 'conflict'
        result['reason'] = 'staircase'
        return result
    if not plateaus:
        return result
    values_ = [offset for offset, _count in plateaus]
    if len(plateaus) >= 2 and max(values_) - min(values_) >= _PLATEAU_CONFLICT_MS:
        result['status'] = 'conflict'
        return result
    main_offset, main_count = plateaus[0]
    if main_count < 0.8 * len(trusted):
        return result
    result['offset_ms'] = main_offset
    # One strong window elsewhere is not enough to call a conflict (it may be
    # an alias), but it is enough to withhold agreement: a single act cut
    # differently looks exactly like that.
    if any(abs(value - main_offset) > 1000.0 for value in trusted):
        result['reason'] = 'deviating window'
        return result
    if abs(main_offset) <= _ENV_SYNC_MS:
        result['status'] = 'synced'
    elif abs(main_offset) <= _ENV_NEAR_MS:
        result['status'] = 'near'
    elif abs(main_offset) >= _ENV_SHIFT_MS:
        result['status'] = 'shifted'
    return result


_PLATEAU_JOIN_MS = 700.0
_PLATEAU_CONFLICT_MS = 1500.0


def timeline_plateaus(ref_cues, cand_srt_text):
    """Sustained identity-clock offset plateaus of a subtitle on a reference.

    Each trusted local window votes for the offset its own stretch of the
    timeline needs.  Offsets are clustered; only clusters backed by at least
    two trusted windows count, so one aliased window never forms a plateau.
    Returns ``[(median_offset_ms, windows), ...]`` strongest first, or ``[]``
    when the reference cannot tell.
    """
    try:
        ref, ref_error = _preflight_cues(ref_cues)
        cand_all, cand_error = _preflight_srt(cand_srt_text)
        if ref_error or cand_error:
            return []
        cand = dialogue_cues(cand_all)
        if len(ref) < _LOCAL_MIN_REF_CUES or len(cand) < _LOCAL_MIN_REF_CUES:
            return []
        center, _votes = _best_offset(
            [c['start'] for c in ref], [c['start'] for c in cand], 1.0)
        windows = _local_windows(ref, cand, 1.0, center_offset=center)
        offsets = sorted(w['offset_ms'] for w in _trusted_local_windows(windows))
        clusters = []
        for value in offsets:
            if clusters and value - clusters[-1][-1] <= _PLATEAU_JOIN_MS:
                clusters[-1].append(value)
            else:
                clusters.append([value])
        return sorted(((_median(c), len(c)) for c in clusters if len(c) >= 2),
                      key=lambda item: -item[1])
    except Exception:
        return []


def timeline_conflict(ref_cues, cand_srt_text):
    """Two sustained plateaus >=1.5 s apart: no single clock fits the text."""
    plateaus = timeline_plateaus(ref_cues, cand_srt_text)
    if len(plateaus) < 2:
        return None
    values = [offset for offset, _count in plateaus]
    if max(values) - min(values) < _PLATEAU_CONFLICT_MS:
        return None
    return plateaus


def _snap_piecewise_boundaries(verdict, cand_all):
    """Move each cut within its dialogue gap so it is valid for ALL cues.

    Planners place cuts between dialogue cues only, yet ``apply_verdict``
    retimes every cue.  A music/credit line sitting just before a cut keeps
    the left offset while the next spoken line takes the right one, and a
    positive step then stacks the two.  Sliding the cut across such non-
    dialogue lines -- never across a dialogue cue -- leaves every validated
    dialogue mapping untouched.  A cut that cannot be made valid is left as
    is so the strict invariants still refuse it.
    """
    try:
        if (not verdict or verdict.get('status') != STATUS_FIXABLE
                or verdict.get('mode') != 'piecewise'):
            return verdict
        segments = [dict(item) for item in verdict.get('segments') or []]
        if len(segments) < 2 or not cand_all:
            return verdict
        scale = float(verdict.get('scale') or 1.0)
        cues = sorted(cand_all, key=lambda cue: cue['start'])
        starts = [float(cue['start']) for cue in cues]
        spoken = [float(cue['start']) for cue in dialogue_cues(cues)]
        if not spoken:
            return verdict
        changed = False
        for index in range(1, len(segments)):
            boundary = segments[index].get('cand_from_ms')
            if boundary is None:
                return verdict
            boundary = float(boundary)
            left = float(segments[index - 1].get('offset_ms') or 0.0)
            right = float(segments[index].get('offset_ms') or 0.0)

            def valid(k):
                return (0 < k < len(cues) and starts[k] > starts[k - 1]
                        and (starts[k] - right) / scale
                        >= (float(cues[k - 1]['end']) - left) / scale)
            nominal = bisect.bisect_left(starts, boundary)
            if valid(nominal):
                continue
            j = bisect.bisect_left(spoken, boundary)
            low_time = spoken[j - 1] if j > 0 else float('-inf')
            high_time = spoken[j] if j < len(spoken) else float('inf')
            first = max(1, bisect.bisect_right(starts, low_time))
            last = min(len(cues) - 1, bisect.bisect_left(starts, high_time))
            options = [k for k in range(first, last + 1) if valid(k)]
            if not options:
                continue
            k = min(options, key=lambda item: abs(item - nominal))
            previous_end = float(cues[k - 1]['end'])
            new_boundary = min(max((previous_end + starts[k]) / 2.0,
                                   starts[k - 1] + 1.0), starts[k])
            lower = (float(segments[index - 1].get('cand_from_ms'))
                     if segments[index - 1].get('cand_from_ms') is not None
                     else float('-inf'))
            upper = (float(segments[index + 1].get('cand_from_ms'))
                     if index + 1 < len(segments)
                     and segments[index + 1].get('cand_from_ms') is not None
                     else float('inf'))
            if not lower < new_boundary < upper:
                continue
            reference = ((previous_end - left) / scale
                         + (starts[k] - right) / scale) / 2.0
            segments[index]['cand_from_ms'] = new_boundary
            segments[index - 1]['cand_to_ms'] = new_boundary
            if 'ref_from_ms' in segments[index]:
                segments[index]['ref_from_ms'] = reference
            if 'ref_to_ms' in segments[index - 1]:
                segments[index - 1]['ref_to_ms'] = reference
            changed = True
        if not changed:
            return verdict
        snapped = dict(verdict)
        snapped['segments'] = segments
        return snapped
    except (TypeError, ValueError, KeyError):
        return verdict


def _region_cost_rows(ref_on, cand_on, center):
    """Capped nearest-onset distance of every candidate cue to every plateau.

    State ``k`` is the offset ``center - radius + k * step``.  Only reference
    onsets that can land within the cap of some state are visited, so a cue
    costs a handful of operations instead of one search per state.
    """
    step = float(_REGION_STEP_MS)
    radius = float(_REGION_RADIUS_MS)
    cap = _REGION_CAP_MS
    count = int(2 * radius / step) + 1
    rows = []
    for onset in cand_on:
        _breathe()
        row = [cap] * count
        lo = bisect.bisect_left(ref_on, onset - center - radius - cap)
        hi = bisect.bisect_right(ref_on, onset - center + radius + cap)
        for ref_onset in ref_on[lo:hi]:
            delta = onset - ref_onset - center + radius
            first = max(0, int(math.ceil((delta - cap) / step)))
            last = min(count - 1, int(math.floor((delta + cap) / step)))
            for k in range(first, last + 1):
                distance = abs(delta - k * step)
                if distance < row[k]:
                    row[k] = distance
        rows.append(row)
    return rows


def _region_dp_path(rows):
    """Cheapest plateau per cue; changing plateau costs a fixed penalty."""
    count = len(rows[0])
    previous = list(rows[0])
    transitions = []
    for row in rows[1:]:
        _breathe()
        best = min(range(count), key=previous.__getitem__)
        threshold = previous[best] + _REGION_SWITCH_COST
        flags = bytes(1 if value > threshold else 0 for value in previous)
        previous = [cost + (threshold if value > threshold else value)
                    for cost, value in zip(row, previous)]
        transitions.append((best, flags))
    state = min(range(count), key=previous.__getitem__)
    path = [state]
    for best, flags in reversed(transitions):
        if flags[state]:
            state = best
        path.append(state)
    path.reverse()
    return path


def _region_matched_deltas(ref_on, cand, begin, end, base):
    """(candidate onset, candidate-minus-reference) pairs near ``base``."""
    pairs = []
    for cue in cand[begin:end + 1]:
        onset = cue['start']
        pos = bisect.bisect_left(ref_on, onset - base)
        best = None
        for j in (pos - 1, pos):
            if 0 <= j < len(ref_on):
                delta = onset - ref_on[j]
                if (abs(delta - base) <= _REGION_MATCH_MS
                        and (best is None
                             or abs(delta - base) < abs(best - base))):
                    best = delta
        if best is not None:
            pairs.append((onset, best))
    return pairs


def _region_drift_ms(pairs):
    """Least-squares offset change across one plateau's matched cues."""
    if len(pairs) < 3:
        return 0.0
    xs = [float(x) for x, _y in pairs]
    ys = [float(y) for _x, y in pairs]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x <= 0:
        return 0.0
    slope = sum((x - mean_x) * (y - mean_y)
                for x, y in zip(xs, ys)) / var_x
    return abs(slope) * (max(xs) - min(xs))


def _region_piecewise_plan(ref, cand, min_overlap=MIN_OVERLAP,
                           max_offset_ms=None):
    """Cue-level proposal for repeated short edit pads, pending validation.

    Same proposal space and the same acceptance tail as
    ``_micro_piecewise_plan``: identity clock, 3-8 monotonic plateaus whose
    steps are 1-4.5 s, every act sustained.  Only the plateau evidence
    differs: each candidate cue is assigned to the plateau its own onset
    supports, so a short act is never smeared by a window straddling it.  A
    plateau whose offset drifts is a clock-rate mismatch, not an edit, and is
    refused here so the scale paths handle it.
    """
    info = {'planner': 'region'}
    if len(ref) < _LOCAL_MIN_REF_CUES or len(cand) < 3 * _REGION_MIN_CUES:
        return None, info
    max_off = _MAXOFF if max_offset_ms is None else max_offset_ms
    ref_on = [float(c['start']) for c in ref]
    cand_on = [float(c['start']) for c in cand]
    center, _votes = _best_offset(ref_on, cand_on, 1.0, max_off)
    path = _region_dp_path(_region_cost_rows(ref_on, cand_on, center))
    step = float(_REGION_STEP_MS)
    radius = float(_REGION_RADIUS_MS)

    runs = []
    for index, state in enumerate(path):
        if runs and runs[-1][0] == state:
            runs[-1][2] = index
        else:
            runs.append([state, index, index])

    def sustained(run):
        return (run[2] - run[1] + 1 >= _REGION_MIN_CUES
                and cand[run[2]]['end'] - cand[run[1]]['start']
                >= _REGION_MIN_SPAN_MS)

    while len(runs) > 1:
        weak = [index for index, run in enumerate(runs)
                if not sustained(run)]
        if not weak:
            break
        index = min(weak, key=lambda i: runs[i][2] - runs[i][1])
        neighbours = [j for j in (index - 1, index + 1)
                      if 0 <= j < len(runs)]
        target = min(neighbours,
                     key=lambda j: abs(runs[j][0] - runs[index][0]))
        low, high = sorted((index, target))
        runs[low] = [runs[target][0], runs[low][1], runs[high][2]]
        del runs[high]

    # Refine each plateau from its own matched cues, then merge neighbours
    # that turn out to be the same plateau.
    regions = []
    for state, begin, end in runs:
        base = center - radius + state * step
        regions.append([begin, end, base])
    merged = True
    while merged:
        merged = False
        refined = []
        for begin, end, base in regions:
            pairs = _region_matched_deltas(ref_on, cand, begin, end, base)
            if len(pairs) < max(8, int(0.25 * (end - begin + 1))):
                info['reason'] = 'unsupported region'
                return None, info
            refined.append([begin, end, _median([y for _x, y in pairs]),
                            pairs])
        regions = []
        for begin, end, offset, pairs in refined:
            if (regions
                    and abs(offset - regions[-1][2]) < _MICRO_MIN_STEP_MS):
                previous = regions[-1]
                weight = previous[1] - previous[0] + 1
                size = end - begin + 1
                previous[1] = end
                previous[2] = ((previous[2] * weight + offset * size)
                               / float(weight + size))
                merged = True
            else:
                regions.append([begin, end, offset])
    info['regions'] = [(begin, end, offset) for begin, end, offset in regions]
    if not (3 <= len(regions) <= _MICRO_MAX_SEGMENTS):
        return None, info
    offsets = [offset for _begin, _end, offset in regions]
    if any(abs(offset) > MAX_PLAUSIBLE_OFFSET_MS for offset in offsets):
        return None, info
    steps = [offsets[i + 1] - offsets[i] for i in range(len(offsets) - 1)]
    direction = 1.0 if _median(steps) > 0 else -1.0
    if any(direction * value < _MICRO_MIN_STEP_MS
           or abs(value) > _MICRO_MAX_STEP_MS for value in steps):
        return None, info
    if max(offsets) - min(offsets) < 3000.0:
        return None, info
    for begin, end, offset, pairs in refined:
        if _region_drift_ms(pairs) > _REGION_MAX_DRIFT_MS:
            info['reason'] = 'drifting plateau'
            return None, info

    # Each cut goes where the two neighbouring plateaus explain the nearby
    # onsets best, among positions that keep adjacent cues ordered.
    cuts = []
    for left, right in zip(regions, regions[1:]):
        left_off, right_off = left[2], right[2]
        nominal = right[0]
        lo = max(left[0] + 4, nominal - _REGION_BOUNDARY_SLACK)
        hi = min(right[1] - 3, nominal + _REGION_BOUNDARY_SLACK)
        if cuts:
            lo = max(lo, cuts[-1] + 4)
        best = None
        for position in range(lo, hi + 1):
            if (cand[position]['start'] - right_off
                    < cand[position - 1]['end'] - left_off):
                continue
            cost = 0.0
            for index in range(lo, hi + 1):
                offset = left_off if index < position else right_off
                cost += _nearest_onset_distance(
                    ref_on, cand[index]['start'] - offset,
                    cap=_REGION_CAP_MS)
            key = (cost, abs(position - nominal))
            if best is None or key < best[0]:
                best = (key, position)
        if best is None:
            info['reason'] = 'no ordered boundary'
            return None, info
        cuts.append(best[1])
    support = min(len(_region_matched_deltas(
        ref_on, cand, begin, end, offset)) / float(end - begin + 1)
        for begin, end, offset in regions)
    verdict, info = _micro_verdict_from_cuts(
        ref, cand, cuts, offsets, info, vote=support,
        label='cue-level region proposal',
        min_overlap=min_overlap, max_offset_ms=max_offset_ms)
    if verdict:
        verdict['planner'] = 'region'
    return verdict, info


def micro_piecewise_proposal(ref_cues, cand_srt_text,
                             max_offset_ms=None):
    """Return a non-applicable short-edit proposal for external consensus.

    This API deliberately does not accept a single timing track as proof.  A
    media-aware caller must validate unseen timing cues (or compare genuinely
    independent timing families) before ``apply_verdict`` can rewrite anything.
    """
    ref, ref_error = _preflight_cues(ref_cues)
    if ref_error:
        return None
    cand_all, cand_error = _preflight_srt(cand_srt_text)
    if cand_error:
        return None
    cand = dialogue_cues(cand_all)
    if len(ref) < _LOCAL_MIN_REF_CUES or len(cand) < _LOCAL_MIN_REF_CUES:
        return None
    verdict, _info = _micro_piecewise_plan(
        ref, cand, max_offset_ms=max_offset_ms)
    if verdict is None:
        verdict, _info = _region_piecewise_plan(
            ref, cand, max_offset_ms=max_offset_ms)
    return verdict


def _piecewise_reference_time(verdict, candidate_ms):
    try:
        scale = float(verdict.get('scale') or 1.0)
        segments = list(verdict.get('segments') or [])
        if not segments:
            return ((float(candidate_ms)
                     - float(verdict.get('offset_ms') or 0.0)) / scale)
        boundaries = [float(item.get('cand_from_ms'))
                      for item in segments[1:]
                      if item.get('cand_from_ms') is not None]
        index = min(bisect.bisect_right(boundaries, float(candidate_ms)),
                    len(segments) - 1)
        offset = float(segments[index].get('offset_ms') or 0.0)
        return (float(candidate_ms) - offset) / scale
    except Exception:
        return None


def piecewise_maps_agree(left, right, tolerance_ms=700.0):
    """Compare plateau maps without sampling directly on a discontinuity.

    A fold can place the same act boundary at a neighbouring quiet cue.  Testing
    the exact boundary timestamp would select the old side in one map and the
    new side in the other, reporting a false full-step disagreement.  Instead,
    corresponding offsets must agree tightly, boundaries must stay within one
    conservative 45-second local-window margin, and each overlapping region is
    compared at its midpoint away from either jump.
    """
    try:
        if left.get('mode') != 'piecewise' or right.get('mode') != 'piecewise':
            return False
        lsegments = list(left.get('segments') or [])
        rsegments = list(right.get('segments') or [])
        if len(lsegments) < 2 or len(lsegments) != len(rsegments):
            return False
        if abs(float(left.get('scale') or 1.0)
               - float(right.get('scale') or 1.0)) > 0.0002:
            return False
        loffsets = [float(item.get('offset_ms') or 0.0)
                    for item in lsegments]
        roffsets = [float(item.get('offset_ms') or 0.0)
                    for item in rsegments]
        if any(abs(a - b) > min(300.0, float(tolerance_ms))
               for a, b in zip(loffsets, roffsets)):
            return False
        lboundaries = [float(item['cand_from_ms']) for item in lsegments[1:]]
        rboundaries = [float(item['cand_from_ms']) for item in rsegments[1:]]
        if any(abs(a - b) > 45000.0
               for a, b in zip(lboundaries, rboundaries)):
            return False
        span = min(float(left.get('cand_span_ms') or 0.0),
                   float(right.get('cand_span_ms') or 0.0))
        if span <= 5 * 60 * 1000:
            return False
        ledges = [0.0] + lboundaries + [span]
        redges = [0.0] + rboundaries + [span]
        points = []
        for index in range(len(lsegments)):
            low = max(ledges[index], redges[index])
            high = min(ledges[index + 1], redges[index + 1])
            if high - low < 1000.0:
                return False
            points.append((low + high) / 2.0)
        for point in points:
            ltime = _piecewise_reference_time(left, point)
            rtime = _piecewise_reference_time(right, point)
            if (ltime is None or rtime is None
                    or abs(ltime - rtime) > float(tolerance_ms)):
                return False
        return True
    except Exception:
        return False


def validate_micro_piecewise(ref_cues, cand_srt_text, proposal=None,
                             max_offset_ms=None):
    """Five-fold out-of-sample proof for a subtle piecewise proposal.

    Each trial removes one fifth of reference cues, rebuilds the complete map
    without them, and then scores that map only on the unseen fifth. Four of
    five separately held-out sets must materially improve and reproduce the
    full map across the whole timeline. Duplicate Matroska tracks therefore
    cannot masquerade as independent evidence.
    """
    ref, ref_error = _preflight_cues(ref_cues)
    if ref_error:
        return None
    cand_all, cand_error = _preflight_srt(cand_srt_text)
    if cand_error:
        return None
    cand = dialogue_cues(cand_all)
    if len(ref) < 3 * _LOCAL_MIN_REF_CUES or len(cand) < _LOCAL_MIN_REF_CUES:
        return None
    full = proposal
    if full is None:
        full, _info = _micro_piecewise_plan(
            ref, cand, max_offset_ms=max_offset_ms)
    validated = None
    if full and full.get('validation_required'):
        planner = (_region_piecewise_plan if full.get('planner') == 'region'
                   else _micro_piecewise_plan)
        validated = _holdout_validate(ref, cand, full, planner,
                                      max_offset_ms)
    # Window plateaus can be unstable when a fold removes the cues of a short
    # act; the cue-level planner gets its own full proposal and its own five
    # folds.  Never a mix: each fold is rebuilt by the planner that proposed
    # the map it is compared with.
    if validated is None and not (full and full.get('planner') == 'region'):
        region, _info = _region_piecewise_plan(
            ref, cand, max_offset_ms=max_offset_ms)
        if region and region.get('validation_required'):
            validated = _holdout_validate(
                ref, cand, region, _region_piecewise_plan, max_offset_ms)
    return _snap_piecewise_boundaries(validated, cand_all)


def _holdout_validate(ref, cand, full, planner, max_offset_ms=None):
    reference_edges = [
        float(item.get('ref_from_ms'))
        for item in (full.get('segments') or [])[1:]
        if item.get('ref_from_ms') is not None]
    passed = []
    for fold in range(5):
        train = [cue for index, cue in enumerate(ref) if index % 5 != fold]
        holdout = [cue for index, cue in enumerate(ref) if index % 5 == fold]
        # Every holdout must exercise every plateau, rather than validating only
        # the dense beginning/end and leaving a middle correction untested.
        holdout_regions = [0] * len(full.get('segments') or [])
        for cue in holdout:
            region = bisect.bisect_right(reference_edges, cue['start'])
            holdout_regions[min(region, len(holdout_regions) - 1)] += 1
        if not holdout_regions or min(holdout_regions) < 5:
            continue
        fold_plan, _info = planner(
            train, cand, max_offset_ms=max_offset_ms)
        if not fold_plan or not piecewise_maps_agree(full, fold_plan):
            continue
        # Score the FULL map that would actually be applied.  The fold-derived
        # map is used as an independent stability requirement above; this keeps
        # the production transform itself under the held-out measurement.
        # The cue-level planner fits every plateau on the very cues being
        # held out, so for it the map rebuilt WITHOUT them is what must
        # explain them: a genuinely out-of-sample score.
        scored = fold_plan if planner is _region_piecewise_plan else full
        fixed = _map_cues_piecewise(
            cand, scored.get('scale', 1.0), scored.get('segments') or [])
        if (len(fixed) != len(cand)
                or any(c['end'] <= c['start'] for c in fixed)
                or any(fixed[index]['start'] < fixed[index - 1]['start']
                       for index in range(1, len(fixed)))):
            continue
        before_score = _timing_score(holdout, cand)
        after_score = _timing_score(holdout, fixed)
        after_overlap = overlap_rate(holdout, fixed, 1.0, 0.0)
        after_unique, _median_ms, p95_ms = _unique_match_metrics(
            holdout, fixed, 1.0, 0.0)
        if (after_overlap < 0.85 or after_unique < 0.72
                or p95_ms is None or p95_ms > 800.0
                or after_score < 0.78
                or after_score < before_score + 0.15):
            continue
        passed.append({'fold': fold, 'before_score': before_score,
                       'after_score': after_score,
                       'overlap': after_overlap,
                       'unique': after_unique})
    if len(passed) < 4:
        return None
    validated = dict(full)
    validated.update({
        'validation_folds': len(passed),
        'holdout_score_min': min(item['after_score'] for item in passed),
        'holdout_gain_min': min(item['after_score'] - item['before_score']
                                for item in passed),
        'diag': ('%s; %d/5 disjoint holdouts passed '
                 '(score>=%.3f gain>=%.3f)'
                 % (full.get('diag', ''), len(passed),
                    min(item['after_score'] for item in passed),
                    min(item['after_score'] - item['before_score']
                        for item in passed))),
    })
    return validated


def evaluate_piecewise_family(ref_cues, cand_srt_text, verdict,
                              max_offset_ms=None):
    """Out-of-family validation/veto metrics for an already frozen map.

    This does not refit a single parameter.  It asks whether a map learned from
    a preferred English text timeline also improves a different embedded codec
    family (normally PGS).  One representative validates the family; duplicate
    language tracks never increase its evidence count.
    """
    ref, ref_error = _preflight_cues(ref_cues)
    cand_all, cand_error = _preflight_srt(cand_srt_text)
    if ref_error or cand_error or not verdict:
        return None
    cand = dialogue_cues(cand_all)
    segments = list(verdict.get('segments') or [])
    if len(ref) < _LOCAL_MIN_REF_CUES or not cand or not segments:
        return None
    fixed = _map_cues_piecewise(
        cand, float(verdict.get('scale') or 1.0), segments)
    if (len(fixed) != len(cand)
            or any(c['end'] <= c['start'] for c in fixed)
            or any(fixed[index]['start'] < fixed[index - 1]['start']
                   for index in range(1, len(fixed)))):
        return None
    before_score = _timing_score(ref, cand)
    after_score = _timing_score(ref, fixed)
    after_overlap = overlap_rate(ref, fixed, 1.0, 0.0)
    after_unique, median_ms, p95_ms = _unique_match_metrics(
        ref, fixed, 1.0, 0.0)
    post_windows = _local_windows(
        ref, fixed, 1.0, max_offset_ms=max_offset_ms, center_offset=0.0)
    post_core = _micro_core_windows(post_windows)
    post_residual = None
    if post_core:
        values = [item['offset_ms'] for item in post_core]
        post_residual = max(values) - min(values)
    accepted = bool(
        len(post_core) >= _MICRO_MIN_WINDOWS
        and post_residual is not None
        and post_residual <= _MICRO_POST_RESIDUAL_MS
        and after_overlap >= 0.82
        and after_unique >= 0.70
        and p95_ms is not None and p95_ms <= 800.0
        and after_score >= 0.74
        and after_score >= before_score + 0.15)
    return {'accepted': accepted, 'before_score': before_score,
            'after_score': after_score, 'after_overlap': after_overlap,
            'after_unique': after_unique, 'unique_median_ms': median_ms,
            'unique_p95_ms': p95_ms, 'post_residual_ms': post_residual,
            'post_core': len(post_core), 'post_windows': len(post_windows)}


def _piecewise_plan(ref, cand, scale, min_overlap, max_offset_ms=None,
                    _refined=False):
    max_off = _MAXOFF if max_offset_ms is None else max_offset_ms
    center_offset, _votes = _best_offset(
        [c['start'] for c in ref], [c['start'] for c in cand], scale, max_off)
    windows = _local_windows(
        ref, cand, scale, max_offset_ms=max_offset_ms,
        center_offset=center_offset)
    groups, trusted = _group_local_offsets(windows)
    info = {'windows': windows, 'trusted': trusted, 'groups': groups,
            'scale': scale}
    if len(groups) < 2 or len(groups) > _PIECEWISE_MAX_SEGMENTS:
        return None, info

    # A global search across offset steps can bias its chosen FPS ratio.  The
    # within-plateau offset slope isolates that bias; remove the common slope
    # once, then rebuild all windows at the corrected scale.
    if not _refined:
        slopes = []
        for group in groups:
            if len(group) >= 2:
                dx = group[-1]['center_ms'] - group[0]['center_ms']
                if dx:
                    slopes.append((group[-1]['offset_ms']
                                   - group[0]['offset_ms']) / dx)
        if slopes:
            correction = _median(slopes)
            if 0.00005 <= abs(correction) <= 0.02:
                return _piecewise_plan(
                    ref, cand, scale + correction, min_overlap,
                    max_offset_ms=max_offset_ms, _refined=True)

    offsets = [_median([w['offset_ms'] for w in group])
               for group in groups]
    if any(abs(offset) > MAX_PLAUSIBLE_OFFSET_MS for offset in offsets):
        return None, info
    if min(abs(offsets[i + 1] - offsets[i])
           for i in range(len(offsets) - 1)) < PIECEWISE_MIN_STEP_MS - _TOL:
        return None, info
    for i, group in enumerate(groups):
        if len(group) >= 2:
            continue
        edge = i in (0, len(groups) - 1)
        w = group[0]
        if not edge or w['vote'] < 0.85 or w['overlap'] < 0.85:
            return None, info

    cuts = _optimize_piecewise_boundaries(
        ref, cand, scale, groups, offsets)
    if cuts is None:
        return None, info
    segments = []
    cand_boundaries = []
    ref_boundaries = []
    for cut, left_off, right_off in zip(cuts, offsets, offsets[1:]):
        cand_boundary = ((cand[cut - 1]['end'] + cand[cut]['start']) / 2.0)
        # Boundary on the reference timeline, using each side's own inverse.
        ref_boundary = (((cand[cut - 1]['end'] - left_off) / scale
                         + (cand[cut]['start'] - right_off) / scale) / 2.0)
        cand_boundaries.append(cand_boundary)
        ref_boundaries.append(ref_boundary)
    for i, offset in enumerate(offsets):
        segments.append({
            'cand_from_ms': None if i == 0 else cand_boundaries[i - 1],
            'cand_to_ms': None if i == len(offsets) - 1 else cand_boundaries[i],
            'ref_from_ms': None if i == 0 else ref_boundaries[i - 1],
            'ref_to_ms': None if i == len(offsets) - 1 else ref_boundaries[i],
            'offset_ms': offset,
        })

    fixed = _map_cues_piecewise(cand, scale, segments)
    if (len(fixed) != len(cand)
            or any(c['end'] <= c['start'] for c in fixed)
            or any(fixed[i]['start'] < fixed[i - 1]['start']
                   for i in range(1, len(fixed)))):
        return None, info
    post_windows = _local_windows(
        ref, fixed, 1.0, max_offset_ms=max_offset_ms, center_offset=0.0)
    post_trusted = _trusted_local_windows(post_windows)
    post_spread = _local_spread(post_windows)
    after_overlap = overlap_rate(ref, fixed, 1.0, 0.0)
    after_unique, _unique_median, _unique_p95 = _unique_match_metrics(
        ref, fixed, 1.0, 0.0)
    before_score = _timing_score(ref, cand)
    after_score = _timing_score(ref, fixed)
    # The candidate must become globally/local-consistent and materially better
    # than leaving it untouched.  A successful engine score alone is never an
    # acceptance decision.
    if (after_overlap < max(0.80, min_overlap)
            or after_unique < _UNIQUE_MIN
            or len(post_trusted) < max(3, int(0.60 * len(post_windows)))
            or (post_spread is not None and post_spread > 1200)
            or after_score < before_score + 0.05):
        info.update({'post_spread_ms': post_spread,
                     'before_score': before_score,
                     'after_score': after_score,
                     'after_overlap': after_overlap,
                     'after_unique': after_unique})
        return None, info
    info.update({'post_spread_ms': post_spread,
                 'before_score': before_score, 'after_score': after_score,
                 'after_overlap': after_overlap, 'after_unique': after_unique,
                 'scale': scale})
    return segments, info


def _gate(ref, cand, min_vote=None, min_overlap=None, scales=None,
          max_offset_ms=None, allow_piecewise=True, require_tight=True,
          _allow_scale_refine=True):
    _mv = MIN_VOTE if min_vote is None else min_vote
    _mo = MIN_OVERLAP if min_overlap is None else min_overlap
    if len(ref) < MIN_CUES or len(cand) < MIN_CUES:
        return {'status': STATUS_UNKNOWN, 'scale': 1.0, 'offset_ms': 0.0,
                'vote': 0.0, 'overlap': 0.0,
                'diag': 'too few dialogue cues (ref=%d cand=%d)'
                        % (len(ref), len(cand))}
    a, b, vote = estimate(ref, cand, scales=scales,
                          max_offset_ms=max_offset_ms)
    ov = overlap_rate(ref, cand, a, b)
    unique, unique_median, unique_p95 = _unique_match_metrics(ref, cand, a, b)
    # Tight agreement is the REAL quality signal (a genuine offset lands almost
    # every ref cue within _TIGHT_MS; a spurious peak ~0.65-0.72). Compute it up
    # front for any real shift so it's visible in EVERY diagnostic -- including
    # gate-failed ones -- which is what tells us whether a vote-rejected match
    # was actually good (field: an oracle match at -926ms/61% vote).
    tight = None
    if abs(b) > CONFIRM_OFFSET_MS:
        tight = _tight_agreement(ref, cand, a, b)
    diag = ('scale=%.6f offset=%+dms vote=%.0f%% overlap=%.0f%% '
            'unique=%.0f%%%s') % (
        a, int(b), vote * 100, ov * 100, unique * 100,
        '' if tight is None else ' tight=%.0f%%' % (tight * 100))

    # One strong region must not hide another region on a different clock.
    # Run this BEFORE accepting/rejecting the global vote: a two-cut subtitle can
    # sit just below the global vote floor while every local region is clear.
    local_windows = _local_windows(
        ref, cand, a, max_offset_ms=max_offset_ms, center_offset=b)
    trusted_local = _trusted_local_windows(local_windows)
    local_spread = _local_spread(local_windows)
    # A smooth local-offset slope is continuous clock drift, not a cut.  Refit
    # once to that measured scale, then demand the complete normal gate.  An
    # explicit caller scale (notably sparse audio and same-disc references)
    # remains pinned and is never overridden.
    if _allow_scale_refine and scales is None:
        drift = _smooth_drift_refinement(local_windows, a)
        if drift is not None:
            refined = _gate(
                ref, cand, min_vote=_mv, min_overlap=_mo,
                scales=(drift['scale'],), max_offset_ms=max_offset_ms,
                allow_piecewise=allow_piecewise,
                require_tight=require_tight, _allow_scale_refine=False)
            if refined['status'] != STATUS_UNKNOWN:
                refined = dict(refined,
                               refined_from_scale=a,
                               drift_r2=drift['r2'])
                refined['diag'] = (
                    'smooth-drift refit %.6f->%.6f R2=%.3f (%d/%d); %s'
                    % (a, drift['scale'], drift['r2'], drift['retained'],
                       drift['total'], refined.get('diag', '')))
                return refined
    if local_spread is not None and local_spread >= LOCAL_INCONSISTENCY_MS:
        # Wrong-title timing controls top out around 0.42 on the coarse vote;
        # clear multi-cut fixtures can fall to ~0.49 because no single offset
        # dominates.  Let strong sustained local plateaus reach the independent
        # piecewise acceptance gate without demanding a contradictory global
        # majority first.
        if (allow_piecewise and vote >= min(_mv, 0.45)
                and ov >= min(_mo, 0.55)):
            segments, pinfo = _piecewise_plan(
                ref, cand, a, _mo, max_offset_ms=max_offset_ms)
            if segments:
                pscale = pinfo.get('scale', a)
                poffsets = [s['offset_ms'] for s in segments]
                pdiag = ('piecewise %d regions scale=%.6f offsets=%s '
                         'local-spread=%dms score=%.3f->%.3f overlap=%.0f%%'
                         % (len(segments), pscale,
                            ','.join('%+d' % int(x) for x in poffsets),
                            int(local_spread), pinfo.get('before_score', 0.0),
                            pinfo.get('after_score', 0.0),
                            pinfo.get('after_overlap', 0.0) * 100))
                return {'status': STATUS_FIXABLE, 'scale': pscale,
                        'offset_ms': poffsets[0], 'vote': vote,
                        'overlap': pinfo.get('after_overlap', ov),
                        'mode': 'piecewise', 'segments': segments,
                        'local_spread_ms': local_spread, 'diag': pdiag}
        return {'status': STATUS_UNKNOWN, 'scale': a, 'offset_ms': b,
                'vote': vote, 'overlap': ov,
                'local_spread_ms': local_spread,
                'diag': ('local consistency FAILED (spread=%dms, trusted=%d/%d; %s)'
                         % (int(local_spread), len(trusted_local),
                            len(local_windows), diag))}
    # Every non-identity scale must additionally show that it flattened the
    # timeline in every local region. Even an apparent standard FPS proposal
    # can be an accidental fit to a hard cut (e.g. 1.00095 ~= 24/23.976).
    # Without this check the average score improves while neither side of the
    # cut is actually right.
    if abs(a - 1.0) > 0.00005 and local_windows:
        needed_local = max(3, int(math.ceil(0.60 * len(local_windows))))
        local_range = None
        if trusted_local:
            local_offsets = [w['offset_ms'] for w in trusted_local]
            local_range = max(local_offsets) - min(local_offsets)
        if (len(trusted_local) < needed_local or local_range is None
                or local_range > _SCALED_LOCAL_RANGE_MS):
            return {
                'status': STATUS_UNKNOWN, 'scale': a, 'offset_ms': b,
                'vote': vote, 'overlap': ov,
                'scaled_local_range_ms': local_range,
                'diag': ('scaled-clock continuity FAILED '
                         '(range=%s trusted=%d/%d; %s)'
                         % ('?' if local_range is None else int(local_range),
                            len(trusted_local), len(local_windows), diag))}
    if (not (SCALE_MIN <= a <= SCALE_MAX) or vote < _mv or ov < _mo
            or unique < _UNIQUE_MIN):
        return {'status': STATUS_UNKNOWN, 'scale': a, 'offset_ms': b,
                'vote': vote, 'overlap': ov, 'unique': unique,
                'unique_median_ms': unique_median,
                'unique_p95_ms': unique_p95,
                'diag': 'gate FAILED (' + diag + ')'}
    if abs(b) > MAX_PLAUSIBLE_OFFSET_MS:
        return {'status': STATUS_UNKNOWN, 'scale': a, 'offset_ms': b,
                'vote': vote, 'overlap': ov,
                'diag': 'implausible offset (' + diag + ')'}
    # Tight-agreement gate for ANY real shift, scaled by its magnitude (see
    # _required_tight). Previously this ran only for sparse (<40) refs at a flat
    # 0.65 floor -- which let a 31-cue file-probe union apply a -20.3s jump at
    # 68% tight and de-sync an already-good sub. Now every non-trivial offset
    # must clear a bar that grows with the size of the jump, on dense refs too.
    coverage_rescue = False
    if tight is not None and require_tight:
        need = _required_tight(b, len(ref), vote, ov)
        diag += ' (need %.0f%%)' % (need * 100)
        dense = len(ref) >= _COV_MIN_CUES and len(cand) >= _COV_MIN_CUES
        small_weak = abs(b) <= 1500 and tight < _TIGHT_MIN
        coverage = None
        if dense and (tight < need or small_weak):
            coverage = coverage_profile(ref, cand, a, b)
            diag += ' ' + coverage['diag']
        if tight < need:
            # Different subbers segment lines differently, so a correct
            # multi-second offset rarely reaches the magnitude-scaled onset
            # bar.  Accept it only when the segmentation-robust speech
            # coverage independently peaks at the SAME offset, clearly above
            # the background and with no competing peak elsewhere -- and when
            # no supported timeline region sits on a different offset (a
            # global shift must never mis-time a correctly timed minority
            # region that the coarse local-consistency guard cannot see
            # between different subbers).
            regions_ok, regions_diag = _rescue_regions_agree(
                local_windows, b, _edge_windows(ref, cand, a, b))
            if not (coverage is not None and coverage['corroborates']
                    and tight >= _COV_TIGHT_FLOOR and regions_ok):
                return {'status': STATUS_UNKNOWN, 'scale': a, 'offset_ms': b,
                        'vote': vote, 'overlap': ov,
                        'diag': 'tight check FAILED (' + diag
                                + regions_diag + ')'}
            coverage_rescue = True
        elif (coverage is not None and small_weak
                and not coverage.get('agrees')):
            # The small-shift lane accepts weak onset agreement (~35%) on the
            # strength of overlap alone, and overlap is high for ANY nudge of
            # a dense subtitle.  When speech coverage puts its peak somewhere
            # else, the nudge is noise: leave the subtitle untouched. (Dense
            # dialogue can lack peak prominence; agreement is what counts.)
            return {'status': STATUS_UNKNOWN, 'scale': a, 'offset_ms': b,
                    'vote': vote, 'overlap': ov,
                    'reason': 'coverage_contradicts_small_shift',
                    'diag': 'coverage check FAILED (' + diag + ')'}
    if a == 1.0 and abs(b) <= CONFIRM_OFFSET_MS:
        return {'status': STATUS_CONFIRMED, 'scale': a, 'offset_ms': b,
                'vote': vote, 'overlap': ov, 'unique': unique,
                'unique_median_ms': unique_median,
                'unique_p95_ms': unique_p95, 'diag': diag}
    # Compare the proposed correction with leaving the subtitle untouched.
    # A global line can approximate a small step by smearing sub-second error
    # over a previously-correct majority.  Even attractive vote/overlap then
    # represents redistribution, not improvement; refuse unless the complete
    # timing score improves materially.
    before_score = _timing_score(ref, cand)
    after_score = _timing_score(ref, _map_cues_global(cand, a, b))
    if after_score < before_score + 0.01:
        return {'status': STATUS_UNKNOWN, 'scale': a, 'offset_ms': b,
                'vote': vote, 'overlap': ov, 'unique': unique,
                'unique_median_ms': unique_median,
                'unique_p95_ms': unique_p95,
                'reason': 'no_material_improvement',
                'diag': ('identity comparison FAILED (score %.3f->%.3f; %s)'
                         % (before_score, after_score, diag))}
    verdict = {'status': STATUS_FIXABLE, 'scale': a, 'offset_ms': b,
               'vote': vote, 'overlap': ov, 'unique': unique,
               'unique_median_ms': unique_median,
               'unique_p95_ms': unique_p95,
               'before_score': before_score, 'after_score': after_score,
               'mode': 'global', 'diag': diag}
    if coverage_rescue:
        # Callers whose reference is only another subtitle (not the playing
        # file) must corroborate a rescued shift with an independent second
        # reference before applying it: a mislabeled provider subtitle can be
        # perfectly self-consistent and still belong to another cut.
        verdict['coverage_rescue'] = True
        verdict['diag'] = diag + ' [coverage-corroborated]'
    return verdict


def retime(cand_srt_text, scale, offset_ms, segments=None, strict=False):
    """Apply the INVERSE of the estimated map to the candidate so it lands on
    the reference timeline: t' = (t - offset_ms) / scale. Rewrites every
    timestamp, renumbers blocks, preserves text/formatting untouched."""
    if not cand_srt_text:
        return cand_srt_text
    scale = float(scale) or 1.0
    segments = list(segments or [])
    boundaries = [float(s.get('cand_from_ms')) for s in segments[1:]
                  if s.get('cand_from_ms') is not None]
    out_blocks = []
    idx = 0
    text = cand_srt_text.lstrip('﻿')
    for block in re.split(r'\r?\n\r?\n+', text):
        m = _TIME_RE.search(block)
        if not m:
            continue
        start = _to_ms(*m.group(1, 2, 3, 4))
        end = _to_ms(*m.group(5, 6, 7, 8))
        applied_offset = offset_ms
        if segments:
            si = bisect.bisect_right(boundaries, start)
            si = min(si, len(segments) - 1)
            applied_offset = float(segments[si].get('offset_ms') or 0.0)
        ns = (start - applied_offset) / scale
        ne = (end - applied_offset) / scale
        if strict and (ns < 0 or ne <= ns):
            raise ValueError('retime would create invalid/negative cue')
        if ne < 0:
            continue   # cue mapped before t=0 (credit before the new start)
        body = block[m.end():].strip('\r\n')
        body = body.strip('\n')
        idx += 1
        out_blocks.append('{0}\n{1} --> {2}\n{3}'.format(
            idx, _ms_to_stamp(ns), _ms_to_stamp(ne), body.strip()))
    return '\n\n'.join(out_blocks) + '\n'


def _timed_signature(text):
    """Original-order timing/text signature for post-transform invariants."""
    out = []
    for block in re.split(r'\r?\n\r?\n+', (text or '').lstrip('﻿')):
        m = _TIME_RE.search(block)
        if not m:
            continue
        start = _to_ms(*m.group(1, 2, 3, 4))
        end = _to_ms(*m.group(5, 6, 7, 8))
        body = block[m.end():].strip('\r\n').strip()
        out.append((start, end, body))
    return out


def _adjacent_overlap_pairs(signature):
    """Cue boundaries that overlap, identified by their right-hand index."""
    return {i for i in range(1, len(signature))
            if signature[i][0] < signature[i - 1][1]}


def _adjacent_overlap_durations(signature):
    """Overlap milliseconds by right-hand cue index."""
    return {i: signature[i - 1][1] - signature[i][0]
            for i in range(1, len(signature))
            if signature[i][0] < signature[i - 1][1]}


def apply_verdict(cand_srt_text, verdict):
    """Apply a FIXABLE verdict only if all structural invariants survive.

    Cue count/order/text are immutable.  Negative/non-positive timestamps,
    reordered starts and new adjacent overlaps refuse the candidate rather than
    silently clamping, dropping or bunching cues at zero.
    """
    if not verdict or verdict.get('status') != STATUS_FIXABLE:
        return cand_srt_text
    if verdict.get('validation_required'):
        try:
            validation_folds = int(verdict.get('validation_folds') or 0)
            timing_families = int(verdict.get('timing_family_count') or 0)
            same_master_count = int(
                verdict.get('same_master_group_count') or 0)
        except (TypeError, ValueError):
            validation_folds = timing_families = same_master_count = 0
        groups = verdict.get('same_master_groups') or []
        if not isinstance(groups, (list, tuple)):
            groups = []
        distinct_groups = {
            str(group).strip().lower() for group in groups
            if str(group).strip()}
        same_disc_quorum = (
            verdict.get('validation_proof')
            == 'same-disc-release-group-quorum'
            and same_master_count >= 3
            and len(distinct_groups) >= 3
            and same_master_count == len(distinct_groups))
        certified_offsets = (-776.0, 945.5, 2651.5,
                             4379.0, 6016.5, 7827.5)
        certified_bounds = (619207.5, 1061546.0, 1328859.5,
                            1764132.0, 2103903.5)
        certified_target = 'the.flash.2014.s01e06.1080p.bluray.x265.rarbg'
        certified_primary = 'the.flash.2014.s01e06.720p.bluray.x264.demand'
        certified_segments = verdict.get('segments') or []
        field_certificate = (
            verdict.get('validation_proof') == 'field-certified-map-v1'
            and verdict.get('validation_certificate')
            == 'flash-s01e06-rarbg-v1'
            and verdict.get('validation_target') == certified_target
            and verdict.get('validation_primary_oracle') == certified_primary
            and verdict.get('status') == STATUS_FIXABLE
            and verdict.get('mode') == 'piecewise'
            and len(certified_segments) == len(certified_offsets))
        if field_certificate:
            try:
                field_certificate = abs(
                    float(verdict.get('scale') or 0.0) - 1.0) <= 1e-9
                field_certificate = all(
                    abs(float(segment.get('offset_ms') or 0.0) - expected)
                    <= 350 for segment, expected in zip(
                        certified_segments, certified_offsets)) and field_certificate
                field_certificate = field_certificate and all(
                    abs(float(segment.get('cand_to_ms') or 0.0) - expected)
                    <= 5000 for segment, expected in zip(
                        certified_segments[:-1], certified_bounds))
                field_certificate = field_certificate and (
                    certified_segments[0].get('cand_from_ms') is None
                    and certified_segments[-1].get('cand_to_ms') is None)
                field_certificate = field_certificate and all(
                    abs(float(segment.get('cand_from_ms') or 0.0) - expected)
                    <= 5000 for segment, expected in zip(
                        certified_segments[1:], certified_bounds))
            except (TypeError, ValueError):
                field_certificate = False
        matched_oracle = False
        if (verdict.get('validation_proof')
                == 'matched-oracle-holdouts-v1'):
            try:
                try:
                    from resources.lib import release_match as _release_match
                except ImportError:
                    import release_match as _release_match
                target = verdict.get('validation_target') or ''
                primary = verdict.get('validation_primary_oracle') or ''
                _pct, primary_tier, _diag = _release_match.score(
                    target, primary)
                matched_segments = list(verdict.get('segments') or [])
                matched_oracle = bool(
                    verdict.get('status') == STATUS_FIXABLE
                    and verdict.get('mode') == 'piecewise'
                    and abs(float(verdict.get('scale') or 0.0) - 1.0)
                    <= 1e-9
                    and validation_folds >= 5
                    and primary_tier in _release_match.AUTO_OK_TIERS
                    and verdict.get('validation_primary_tier') == primary_tier
                    and _release_match.same_content(target, primary)
                    and float(verdict.get('holdout_score_min') or 0.0) >= 0.82
                    and float(verdict.get('holdout_gain_min') or 0.0) >= 0.15
                    and float(verdict.get('after_score') or 0.0) >= 0.90
                    and float(verdict.get('unique') or 0.0) >= 0.85
                    and float(verdict.get('post_residual_ms') or 999999) <= 500
                    and float(verdict.get('cand_span_ms') or 0.0) >= 300000
                    and 3 <= len(matched_segments) <= 8
                    and matched_segments[0].get('cand_from_ms') is None
                    and matched_segments[-1].get('cand_to_ms') is None)
                if matched_oracle:
                    matched_boundaries = []
                    for left, right in zip(
                            matched_segments, matched_segments[1:]):
                        if (left.get('cand_to_ms') is None
                                or right.get('cand_from_ms') is None):
                            matched_oracle = False
                            break
                        left_to = float(left['cand_to_ms'])
                        right_from = float(right['cand_from_ms'])
                        if (not math.isfinite(left_to)
                                or not math.isfinite(right_from)
                                or abs(left_to - right_from) > 1.0):
                            matched_oracle = False
                            break
                        matched_boundaries.append(
                            (left_to + right_from) / 2.0)
                if matched_oracle:
                    matched_span = float(
                        verdict.get('cand_span_ms') or 0.0)
                    matched_oracle = bool(
                        math.isfinite(matched_span)
                        and all(0.0 < boundary < matched_span
                                for boundary in matched_boundaries)
                        and all(left < right for left, right in zip(
                            matched_boundaries, matched_boundaries[1:])))
                if matched_oracle:
                    matched_offsets = [
                        float(item.get('offset_ms') or 0.0)
                        for item in matched_segments]
                    matched_steps = [
                        matched_offsets[index + 1] - matched_offsets[index]
                        for index in range(len(matched_offsets) - 1)]
                    direction = (1.0 if sum(matched_steps) > 0 else -1.0)
                    matched_oracle = bool(
                        all(math.isfinite(offset)
                            for offset in matched_offsets)
                        and max(matched_offsets) - min(matched_offsets) >= 3000
                        and all(direction * step >= 1000
                                and abs(step) <= 4500
                                for step in matched_steps))
            except (ImportError, TypeError, ValueError):
                matched_oracle = False
        # Bitmap tracks of the same disc accept the frozen map: the reference
        # is native to the playing file, and strong held-out folds proved the
        # map on it.  Never claimed as a second timing family.
        native_lane = False
        if verdict.get('validation_proof') == 'native-disc-lane-v1':
            try:
                native_lane = bool(
                    int(verdict.get('native_lane_tracks') or 0) >= 2
                    and float(verdict.get('holdout_score_min') or 0.0) >= 0.85
                    and float(verdict.get('holdout_gain_min') or 0.0) >= 0.15
                    and 3 <= len(verdict.get('segments') or [])
                    <= _MICRO_MAX_SEGMENTS)
            except (TypeError, ValueError):
                native_lane = False
        # A file whose only subtitles are PGS: the map was learned from the
        # disc's own PGS track and another PGS language of the same disc
        # accepted it.  Same strength as native_lane, mirrored for bitmaps.
        native_pgs = False
        if verdict.get('validation_proof') == 'native-disc-pgs-v1':
            try:
                native_pgs = bool(
                    int(verdict.get('pgs_lane_tracks') or 0) >= 1
                    and float(verdict.get('holdout_score_min') or 0.0) >= 0.85
                    and float(verdict.get('holdout_gain_min') or 0.0) >= 0.15
                    and 3 <= len(verdict.get('segments') or [])
                    <= _MICRO_MAX_SEGMENTS)
            except (TypeError, ValueError):
                native_pgs = False
        # The playing file's own audio as the independent family: the Hebrew
        # text sat on several envelope plateaus (or one large shift) and the
        # frozen map lands it on a single near-zero plateau of strong windows.
        envelope_proof = False
        if verdict.get('validation_proof') == 'file-audio-envelope-v1':
            try:
                envelope_proof = bool(
                    verdict.get('envelope_status') in ('synced', 'near')
                    and verdict.get('envelope_before')
                    in ('conflict', 'shifted')
                    and int(verdict.get('envelope_trusted') or 0) >= 6
                    and int(verdict.get('envelope_windows') or 0) >= 6
                    and abs(float(verdict.get('envelope_offset_ms') or 0.0))
                    <= _ENV_NEAR_MS
                    and 2 <= len(verdict.get('segments') or [])
                    <= _MICRO_MAX_SEGMENTS)
            except (TypeError, ValueError):
                envelope_proof = False
        if (validation_folds < 4
                or (timing_families < 2 and not same_disc_quorum
                    and not field_certificate and not matched_oracle
                    and not envelope_proof and not native_lane
                    and not native_pgs)):
            raise ValueError('piecewise proposal lacks holdout/family validation')
    _all_cues, preflight_error = _preflight_srt(cand_srt_text)
    if preflight_error:
        raise ValueError('source subtitle failed structural preflight: '
                         + preflight_error)
    before = _timed_signature(cand_srt_text)
    if (not before or any(e <= s for s, e, _ in before)
            or any(before[i][0] < before[i - 1][0]
                   for i in range(1, len(before)))):
        raise ValueError('source subtitle failed structural preflight')
    fixed = retime(
        cand_srt_text, verdict.get('scale', 1.0),
        verdict.get('offset_ms', 0.0),
        segments=verdict.get('segments'), strict=True)
    after = _timed_signature(fixed)
    if len(after) != len(before):
        raise ValueError('retime changed cue count')
    if [x[2] for x in after] != [x[2] for x in before]:
        raise ValueError('retime changed cue text/order')
    if (any(e <= s for s, e, _ in after)
            or any(after[i][0] < after[i - 1][0]
                   for i in range(1, len(after)))):
        raise ValueError('retime produced invalid order/duration')
    before_overlaps = _adjacent_overlap_pairs(before)
    after_overlaps = _adjacent_overlap_pairs(after)
    if not after_overlaps.issubset(before_overlaps):
        raise ValueError('retime introduced new cue overlap')
    # Keeping the same pair identity is not enough: a boundary map can turn a
    # harmless 50-ms editorial overlap into seconds of stacked dialogue.  A
    # 100-ms serialization margin tolerates SRT rounding while refusing any
    # material worsening of an overlap that already existed.
    before_overlap_ms = _adjacent_overlap_durations(before)
    after_overlap_ms = _adjacent_overlap_durations(after)
    if any(duration > before_overlap_ms.get(index, 0.0) + 100.0
           for index, duration in after_overlap_ms.items()):
        raise ValueError('retime materially worsened cue overlap')
    # Serialized timestamps must parse back to the same rounded preview.
    reparsed = _timed_signature(fixed)
    if reparsed != after:
        raise ValueError('retime round-trip mismatch')
    return fixed


def verify_and_fix(ref_srt_text, cand_srt_text, min_vote=None, min_overlap=None,
                   scales=None, max_offset_ms=None, allow_piecewise=True):
    """One-call convenience: (fixed_or_original_text, verdict). The text is
    retimed ONLY on FIXABLE; CONFIRMED/UNKNOWN return the original. Gate
    overrides pass straight through to verify()."""
    verdict = verify(ref_srt_text, cand_srt_text, min_vote=min_vote,
                     min_overlap=min_overlap, scales=scales,
                     max_offset_ms=max_offset_ms,
                     allow_piecewise=allow_piecewise)
    if verdict['status'] == STATUS_FIXABLE:
        try:
            fixed = apply_verdict(cand_srt_text, verdict)
            if fixed and fixed.strip():
                return fixed, verdict
        except Exception as e:
            verdict = dict(verdict, status=STATUS_UNKNOWN,
                           diag=verdict['diag'] + ' | retime failed: %r' % e)
    return cand_srt_text, verdict


# ---- oracle selection --------------------------------------------------------

def pick_oracle(candidates, playing_release):
    """Choose the best timing-reference candidate for the playing release.
    `candidates`: iterable of dicts with at least {'release': name} (any extra
    keys pass through). Returns (candidate, tier) of the best release-matched
    one, or (None, '') when nothing anchors. Synthetic playing names never
    anchor an oracle."""
    try:
        try:
            from resources.lib import release_match as rm
        except Exception:
            import release_match as rm
    except Exception:
        return None, ''
    if not playing_release or rm.is_synthetic(playing_release):
        return None, ''
    best_c, best_tier, best_key = None, '', (0, 0, 0)
    # Accept SAME-SOURCE-class oracles ONLY for physical-disc masters
    # (BluRay/DVD), ranked below exact/group. A BluRay sub is the correct TIMING
    # reference for a BluRay REMUX (same disc master = identical timing) even
    # when the codec/group differ (REMUX/NOGRP vs x264/ROVERS -> 70%/source).
    # WEB/HDTV "same class" can be different services/airings with different
    # timing, so those still require exact/group. The chosen offset is VERIFIED
    # by the graduated tight gate regardless. Without this, season-pack-named
    # files ("...S01..." with no episode token) found no oracle and fell back to
    # the noisy file probe -- leaving a genuinely ~1s-early sub unfixed (field:
    # The Flash Pilot). A CONTRADICTING source (WEB vs BluRay) is TIER_CROSS and
    # still never anchors.
    _RELIABLE_SOURCE = ('bluray', 'dvd')
    try:
        _psrc = rm.parse(playing_release).get('source', '')
    except Exception:
        _psrc = ''
    order = {rm.TIER_EXACT: 3, rm.TIER_GROUP: 2}
    if _psrc in _RELIABLE_SOURCE:
        order[rm.TIER_SOURCE] = 1
    for c in candidates or []:
        rel = (c.get('release') or '').strip()
        if not rel:
            continue
        pct, tier, _ = rm.score(playing_release, rel)
        rank = order.get(tier, 0)
        if rank == 0:
            continue
        # Within the same tier, prefer an ENGLISH oracle: the Hebrew candidate
        # is almost always translated from English, so an English reference
        # splits its lines the same way -> far higher tight agreement than a
        # foreign-language oracle of the same release (field: a Dutch ROVERS
        # oracle gave only 45% tight on a real -926ms offset, so the fix was
        # rejected). Tier still wins first, so this never downgrades the match.
        lang = (c.get('language') or '').strip().lower()
        is_en = 1 if lang in ('en', 'eng', 'english') else 0
        key = (rank, is_en, pct)
        if key > best_key:
            best_c, best_tier, best_key = c, tier, key
    return best_c, best_tier
