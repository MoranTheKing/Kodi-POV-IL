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


def _is_dialogue(c):
    t = (c.get('text') or '').strip()
    if not t or t.startswith(('♪', '♫', '#')):
        return False
    letters = re.sub(r'[^A-Za-z֐-׿؀-ۿÀ-ɏ'
                     r'Ѐ-ӿ぀-ヿ一-鿿가-힯]',
                     '', t)
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
    for a in sorted(scales or SCALES, key=lambda s: abs(s - 1.0)):
        b, v = _best_offset(ref_on, cand_on, a, max_off)
        if v > best[2]:
            best = (a, b, v)
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
           scales=None, max_offset_ms=None):
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
    return _gate(dialogue_cues(ref_srt_text), dialogue_cues(cand_srt_text),
                 min_vote=min_vote, min_overlap=min_overlap,
                 scales=scales, max_offset_ms=max_offset_ms)


def verify_cues(ref_cues, cand_srt_text, min_vote=None, min_overlap=None,
                scales=None, max_offset_ms=None):
    """verify() variant whose reference is a raw cue list (start/end ms) --
    e.g. embedded-track timestamps from the mkv_probe container probe, where
    there is no text to filter. Same gate, same verdict shape. min_vote /
    min_overlap override the gate thresholds; `scales` restricts the scale
    candidates and `max_offset_ms` the offset window (MANDATORY discipline
    for sparse audio-VAD references -- see _gate notes)."""
    ref = [c for c in (ref_cues or [])
           if isinstance(c, dict) and 'start' in c and 'end' in c]
    return _gate(ref, dialogue_cues(cand_srt_text),
                 min_vote=min_vote, min_overlap=min_overlap,
                 scales=scales, max_offset_ms=max_offset_ms)


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


def _gate(ref, cand, min_vote=None, min_overlap=None, scales=None,
          max_offset_ms=None):
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
    # Tight agreement is the REAL quality signal (a genuine offset lands almost
    # every ref cue within _TIGHT_MS; a spurious peak ~0.65-0.72). Compute it up
    # front for any real shift so it's visible in EVERY diagnostic -- including
    # gate-failed ones -- which is what tells us whether a vote-rejected match
    # was actually good (field: an oracle match at -926ms/61% vote).
    tight = None
    if abs(b) > CONFIRM_OFFSET_MS:
        tight = _tight_agreement(ref, cand, a, b)
    diag = 'scale=%.6f offset=%+dms vote=%.0f%% overlap=%.0f%%%s' % (
        a, int(b), vote * 100, ov * 100,
        '' if tight is None else ' tight=%.0f%%' % (tight * 100))
    if not (SCALE_MIN <= a <= SCALE_MAX) or vote < _mv or ov < _mo:
        return {'status': STATUS_UNKNOWN, 'scale': a, 'offset_ms': b,
                'vote': vote, 'overlap': ov, 'diag': 'gate FAILED (' + diag + ')'}
    if abs(b) > MAX_PLAUSIBLE_OFFSET_MS:
        return {'status': STATUS_UNKNOWN, 'scale': a, 'offset_ms': b,
                'vote': vote, 'overlap': ov,
                'diag': 'implausible offset (' + diag + ')'}
    # Tight-agreement gate for ANY real shift, scaled by its magnitude (see
    # _required_tight). Previously this ran only for sparse (<40) refs at a flat
    # 0.65 floor -- which let a 31-cue file-probe union apply a -20.3s jump at
    # 68% tight and de-sync an already-good sub. Now every non-trivial offset
    # must clear a bar that grows with the size of the jump, on dense refs too.
    if tight is not None:
        need = _required_tight(b, len(ref), vote, ov)
        diag += ' (need %.0f%%)' % (need * 100)
        if tight < need:
            return {'status': STATUS_UNKNOWN, 'scale': a, 'offset_ms': b,
                    'vote': vote, 'overlap': ov,
                    'diag': 'tight check FAILED (' + diag + ')'}
    if a == 1.0 and abs(b) <= CONFIRM_OFFSET_MS:
        return {'status': STATUS_CONFIRMED, 'scale': a, 'offset_ms': b,
                'vote': vote, 'overlap': ov, 'diag': diag}
    return {'status': STATUS_FIXABLE, 'scale': a, 'offset_ms': b,
            'vote': vote, 'overlap': ov, 'diag': diag}


def retime(cand_srt_text, scale, offset_ms):
    """Apply the INVERSE of the estimated map to the candidate so it lands on
    the reference timeline: t' = (t - offset_ms) / scale. Rewrites every
    timestamp, renumbers blocks, preserves text/formatting untouched."""
    if not cand_srt_text:
        return cand_srt_text
    scale = float(scale) or 1.0
    out_blocks = []
    idx = 0
    text = cand_srt_text.lstrip('﻿')
    for block in re.split(r'\r?\n\r?\n+', text):
        m = _TIME_RE.search(block)
        if not m:
            continue
        start = _to_ms(*m.group(1, 2, 3, 4))
        end = _to_ms(*m.group(5, 6, 7, 8))
        ns = (start - offset_ms) / scale
        ne = (end - offset_ms) / scale
        if ne < 0:
            continue   # cue mapped before t=0 (credit before the new start)
        body = block[m.end():].strip('\r\n')
        body = body.strip('\n')
        idx += 1
        out_blocks.append('{0}\n{1} --> {2}\n{3}'.format(
            idx, _ms_to_stamp(ns), _ms_to_stamp(ne), body.strip()))
    return '\n\n'.join(out_blocks) + '\n'


def verify_and_fix(ref_srt_text, cand_srt_text, min_vote=None, min_overlap=None,
                   scales=None, max_offset_ms=None):
    """One-call convenience: (fixed_or_original_text, verdict). The text is
    retimed ONLY on FIXABLE; CONFIRMED/UNKNOWN return the original. Gate
    overrides pass straight through to verify()."""
    verdict = verify(ref_srt_text, cand_srt_text, min_vote=min_vote,
                     min_overlap=min_overlap, scales=scales,
                     max_offset_ms=max_offset_ms)
    if verdict['status'] == STATUS_FIXABLE:
        try:
            fixed = retime(cand_srt_text, verdict['scale'],
                           verdict['offset_ms'])
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
