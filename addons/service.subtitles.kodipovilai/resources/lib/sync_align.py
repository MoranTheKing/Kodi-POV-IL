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
import math
import statistics

# ---- gate thresholds (mirroring arabic_gender's production values) --------
_FPS = [24000 / 1001, 24.0, 25.0, 30000 / 1001, 30.0]
SCALES = sorted({1.0} | {round(p / q, 6) for p in _FPS for q in _FPS
                         if 0.9 <= p / q <= 1.11})
_TOL = 500            # offset histogram bin (ms)
_MAXOFF = 600000      # search window: +/-10 minutes
_SAMPLE = 500         # cap sampled reference cues
MIN_CUES = 8          # min dialogue cues on each side
MIN_VOTE = 0.65       # histogram peak must carry >=65% of sampled cues
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

def _best_offset(ref_on, cand_on, a, max_off=_MAXOFF):
    step = max(1, len(ref_on) // _SAMPLE)
    sampled = ref_on[::step]
    hist = {}
    for e in sampled:
        pe = a * e
        lo = bisect.bisect_left(cand_on, pe - max_off)
        hi = bisect.bisect_right(cand_on, pe + max_off)
        # ONE vote per reference cue per bin. Without the dedupe, a DENSE
        # candidate (600 cues) inflated bins with multiple hits per ref cue,
        # so a sparse 10-cue reference could report vote=120% on a spurious
        # alignment (seen in the field: offset=-350s applied, subs vanished).
        bins = set()
        for j in range(lo, hi):
            bins.add(int(round((cand_on[j] - pe) / _TOL)))
        for b in bins:
            hist[b] = hist.get(b, 0) + 1
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
        return _preflight_unknown('reference: ' + ref_error)
    cand_all, cand_error = _preflight_srt(cand_srt_text)
    if cand_error:
        return _preflight_unknown('candidate: ' + cand_error)
    return _gate(dialogue_cues(ref_all), dialogue_cues(cand_all),
                 min_vote=min_vote, min_overlap=min_overlap,
                 scales=scales, max_offset_ms=max_offset_ms,
                 allow_piecewise=allow_piecewise,
                 require_tight=require_tight)


def verify_cues(ref_cues, cand_srt_text, min_vote=None, min_overlap=None,
                scales=None, max_offset_ms=None, allow_piecewise=True,
                require_tight=True):
    """verify() variant whose reference is a raw cue list (start/end ms) --
    e.g. embedded-track timestamps from the mkv_probe container probe, where
    there is no text to filter. Same gate, same verdict shape. min_vote /
    min_overlap override the gate thresholds; `scales` restricts the scale
    candidates and `max_offset_ms` the offset window (MANDATORY discipline
    for sparse audio-VAD references -- see _gate notes)."""
    ref, ref_error = _preflight_cues(ref_cues)
    if ref_error:
        return _preflight_unknown('reference: ' + ref_error)
    cand_all, cand_error = _preflight_srt(cand_srt_text)
    if cand_error:
        return _preflight_unknown('candidate: ' + cand_error)
    return _gate(ref, dialogue_cues(cand_all),
                 min_vote=min_vote, min_overlap=min_overlap,
                 scales=scales, max_offset_ms=max_offset_ms,
                 allow_piecewise=allow_piecewise,
                 require_tight=require_tight)


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
        allowed.append(range(lo_i, hi_i + 1))

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
    if tight is not None and require_tight:
        need = _required_tight(b, len(ref), vote, ov)
        diag += ' (need %.0f%%)' % (need * 100)
        if tight < need:
            return {'status': STATUS_UNKNOWN, 'scale': a, 'offset_ms': b,
                    'vote': vote, 'overlap': ov,
                    'diag': 'tight check FAILED (' + diag + ')'}
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
    return {'status': STATUS_FIXABLE, 'scale': a, 'offset_ms': b,
            'vote': vote, 'overlap': ov, 'unique': unique,
            'unique_median_ms': unique_median,
            'unique_p95_ms': unique_p95,
            'before_score': before_score, 'after_score': after_score,
            'mode': 'global', 'diag': diag}


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


def apply_verdict(cand_srt_text, verdict):
    """Apply a FIXABLE verdict only if all structural invariants survive.

    Cue count/order/text are immutable.  Negative/non-positive timestamps,
    reordered starts and new adjacent overlaps refuse the candidate rather than
    silently clamping, dropping or bunching cues at zero.
    """
    if not verdict or verdict.get('status') != STATUS_FIXABLE:
        return cand_srt_text
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
