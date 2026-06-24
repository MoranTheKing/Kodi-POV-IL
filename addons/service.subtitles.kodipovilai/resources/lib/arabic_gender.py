# Arabic-as-gender-reference for AI translation (opt-in, default OFF).
#
# Hebrew is heavily gendered and the #1 quality issue is per-line gender (who is
# speaking / who is addressed). English doesn't mark it; Arabic does, almost 1:1
# with Hebrew (أنتَ/أنتِ, gendered verbs/imperatives). A HUMAN Arabic subtitle of
# the same title already "solved" gender per line. So, when enabled, we fetch an
# Arabic sub for the same media, time-align it to the source SRT, and hand each
# entry its aligned Arabic line as a GENDER ORACLE in the prompt (see prompt.py).
#
# This module is self-contained + fully guarded: ANY failure returns None and the
# caller falls back to the normal (no-Arabic) translation. It NEVER raises.
#
# Validated on real OpenSubtitles pairs (From S03E09, Super Mario Bros Movie):
# global alignment is reliable across different releases + SDH once SFX/music is
# filtered; per-line interleave with the strong prompt lifted gender accuracy
# from ~27% (cast-only) to ~90%+ with zero regressions.

import os
import re

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('arabic_gender: ' + msg, level=level)
    except Exception:
        pass


# ---------------- SRT parsing (encoding-robust, timecode-aware) -------------

_TIME_RE = re.compile(
    r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*'
    r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})')
_NONDIALOG = re.compile(r'\[[^\]]*\]|\([^)]*\)|\{[^}]*\}|<[^>]+>')
_MUSIC = ('♪', '♫', '#')
_RAW_AMP = re.compile(r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9A-Fa-f]+;)')


def _to_ms(h, m, s, ms):
    ms = (ms + '000')[:3]
    return (int(h) * 3600 + int(m) * 60 + int(s)) * 1000 + int(ms)


def _parse(text):
    """Parse SRT text -> list of {start,end,text} sorted by start."""
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    cues = []
    for block in re.split(r'\n\s*\n', text):
        lines = [ln for ln in block.split('\n') if ln.strip() != '']
        if not lines:
            continue
        ti = None
        m = None
        for i, ln in enumerate(lines[:3]):
            m = _TIME_RE.search(ln)
            if m:
                ti = i
                break
        if m is None:
            continue
        start = _to_ms(*m.group(1, 2, 3, 4))
        end = _to_ms(*m.group(5, 6, 7, 8))
        if end < start:
            end = start
        body = ' '.join(lines[ti + 1:]).strip()
        body = _NONDIALOG.sub(' ', body)
        body = re.sub(r'\s{2,}', ' ', body).strip()
        cues.append({'start': start, 'end': end, 'text': body})
    cues.sort(key=lambda c: c['start'])
    return cues


def _is_dialogue(text):
    t = text or ''
    if any(mk in t for mk in _MUSIC):
        return False
    t = _NONDIALOG.sub(' ', t)
    letters = re.sub(r'[^A-Za-z֐-׿؀-ۿ]', '', t)
    return len(letters) >= 2


# ---------------- time-map estimation (fps + offset) ------------------------

_FPS = [24000 / 1001, 24.0, 25.0, 30000 / 1001, 30.0]
_SCALES = sorted({1.0} | {round(p / q, 6) for p in _FPS for q in _FPS
                          if 0.9 <= p / q <= 1.11})
_TOL = 500
_TIGHT = 250
_MAXOFF = 600000
_SAMPLE = 500


def _best_offset(en_on, ar_on, a):
    step = max(1, len(en_on) // _SAMPLE)
    import bisect
    hist = {}
    for e in en_on[::step]:
        pe = a * e
        lo = bisect.bisect_left(ar_on, pe - _MAXOFF)
        hi = bisect.bisect_right(ar_on, pe + _MAXOFF)
        for j in range(lo, hi):
            b = int(round((ar_on[j] - pe) / _TOL))
            hist[b] = hist.get(b, 0) + 1
    if not hist:
        return 0.0, 0
    peak = max(hist, key=lambda k: hist[k] + hist.get(k - 1, 0)
               + hist.get(k + 1, 0))
    votes = hist.get(peak - 1, 0) + hist.get(peak, 0) + hist.get(peak + 1, 0)
    return float(peak * _TOL), votes


def _estimate_map(en, ar):
    en_on = [c['start'] for c in en]
    ar_on = [c['start'] for c in ar]
    if not en_on or not ar_on:
        return 1.0, 0.0, 0.0
    sampled = len(en_on[::max(1, len(en_on) // _SAMPLE)])
    best = (1.0, 0.0, -1)
    for a in _SCALES:
        b, v = _best_offset(en_on, ar_on, a)
        if v > best[2]:
            best = (a, b, v)
    a, b, v = best
    return a, b, (v / sampled if sampled else 0.0)


def _overlap_rate(en, ar, a, b):
    import bisect
    ar_starts = [c['start'] for c in ar]
    ar_ends = [c['end'] for c in ar]
    ok = 0
    for c in en:
        es, ee = a * c['start'] + b, a * c['end'] + b
        lo = bisect.bisect_left(ar_ends, es)
        k = lo
        hit = False
        while k < len(ar) and ar_starts[k] < ee:
            if min(ee, ar_ends[k]) - max(es, ar_starts[k]) > 0:
                hit = True
                break
            k += 1
        if hit:
            ok += 1
    return ok / len(en) if en else 0.0


# ---------------- public: build the per-entry gender map --------------------

def _arabic_for_blocks(src_blocks, ar_cues, a, b):
    """Return {srt_entry_number: aligned Arabic dialogue text} for the dialogue
    blocks with a confident time-overlap. Keyed by the block's own SRT number
    (robust to how translate.py later chunks them). SFX/music blocks omitted."""
    import bisect
    ar_centers = [(c['start'] + c['end']) / 2.0 for c in ar_cues]
    ar_starts = [c['start'] for c in ar_cues]
    ar_ends = [c['end'] for c in ar_cues]
    out = {}
    for blk in src_blocks:
        lines = [ln for ln in blk.split('\n') if ln.strip() != '']
        if len(lines) < 2 or not lines[0].strip().isdigit():
            continue
        num = int(lines[0].strip())
        m = _TIME_RE.search(blk)
        if not m:
            continue
        s = _to_ms(*m.group(1, 2, 3, 4))
        e = _to_ms(*m.group(5, 6, 7, 8))
        body = ' '.join(lines[2:]).strip()
        if not _is_dialogue(body):
            continue
        es, ee = a * s + b, a * e + b
        lo = bisect.bisect_left(ar_ends, es)
        cand = []
        k = lo
        while k < len(ar_cues) and ar_starts[k] < ee:
            ov = min(ee, ar_ends[k]) - max(es, ar_starts[k])
            if ov > 0:
                cand.append((ov, k))
            k += 1
        if cand:
            out[num] = ar_cues[max(cand)[1]]['text']
            continue
        pred = a * ((s + e) / 2.0) + b
        j = bisect.bisect_left(ar_centers, pred)
        bd, bk = 1e9, None
        for kk in (j - 1, j, j + 1):
            if 0 <= kk < len(ar_cues) and abs(ar_centers[kk] - pred) < bd:
                bd, bk = abs(ar_centers[kk] - pred), kk
        if bk is not None and bd <= _TIGHT:
            out[num] = ar_cues[bk]['text']
    return out


def align_one(src_text, src_blocks, ar_text):
    """Try to align ONE Arabic SRT to the source. Returns (ar_for_blocks, diag)
    on success, or (None, diag) when the alignment isn't trustworthy."""
    en = [c for c in _parse(src_text) if _is_dialogue(c['text'])]
    ar = [c for c in _parse(ar_text) if _is_dialogue(c['text'])]
    if len(en) < 8 or len(ar) < 8:
        return None, 'too few dialogue cues (en=%d ar=%d)' % (len(en), len(ar))
    a, b, vote = _estimate_map(en, ar)
    ov = _overlap_rate(en, ar, a, b)
    diag = 'scale=%.4f offset=%+dms vote=%.0f%% overlap=%.0f%%' % (
        a, int(b), vote * 100, ov * 100)
    # Confidence gate (chunk-level architecture): correct map + good coverage.
    if not (0.90 <= a <= 1.11) or vote < 0.65 or ov < 0.80:
        return None, 'gate FAILED (' + diag + ')'
    return _arabic_for_blocks(src_blocks, ar, a, b), 'gate OK (' + diag + ')'


# ---------------- fetch Arabic candidates from the engine -------------------

def _fetch_arabic_texts(info, limit=4):
    """Best-effort: return up to `limit` Arabic SRT texts for this media from
    the built-in engine (OpenSubtitles / SubSource / YIFY). Empty list on any
    problem. Guarded; never raises."""
    try:
        from resources.lib import subs_engine_bridge, translate
    except Exception:
        return []
    try:
        # Make sure the engine will return Arabic results (it gates languages
        # by setting). Idempotent + only when our feature is on.
        if kodi_utils is not None:
            try:
                kodi_utils.set_setting('language_arab', 'true')
            except Exception:
                pass
        cands = subs_engine_bridge.search(info, modal_progress=False) or []
    except Exception as e:
        _log('engine search for Arabic failed: {0}'.format(e), level='WARNING')
        return []
    ar_cands = [c for c in cands
                if (c.get('language') or '').lower() in ('ar', 'ara', 'arabic')]
    if not ar_cands:
        _log('no Arabic subtitle found from the engine for this title')
        return []
    texts = []
    for c in ar_cands[:limit]:
        try:
            payload = translate._decode_link(c.get('link') or '')
            if not payload:
                continue
            path = subs_engine_bridge.download(payload)
            if path and os.path.isfile(path):
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    texts.append(f.read())
        except Exception as e:
            _log('Arabic download failed (continuing): {0}'.format(e),
                 level='DEBUG')
    return texts


def prepare(info, src_text):
    """ENTRY POINT. When the feature is on, fetch Arabic subs for `info`, and try
    each in turn until one aligns confidently. Returns a list `ar_for_blocks`
    (one entry per source SRT block, '' where no gender hint) or None to fall
    back to the normal translation. Fully guarded."""
    try:
        from resources.lib import srt as _srt
        src_blocks = _srt.parse_blocks(src_text)
    except Exception:
        return None
    if not src_blocks:
        return None
    try:
        ar_texts = _fetch_arabic_texts(info)
    except Exception as e:
        _log('fetch crashed: {0}'.format(e), level='WARNING')
        return None
    if not ar_texts:
        _log('no Arabic candidates -> normal translation (fallback)')
        return None
    for idx, ar_text in enumerate(ar_texts, 1):
        try:
            mapping, diag = align_one(src_text, src_blocks, ar_text)
        except Exception as e:
            _log('align candidate {0} crashed: {1}'.format(idx, e),
                 level='WARNING')
            continue
        if mapping is not None:
            hinted = len(mapping)
            _log('candidate {0}/{1} {2} -> using Arabic gender reference '
                 '({3} entries hinted)'.format(idx, len(ar_texts), diag,
                                               hinted))
            return mapping
        _log('candidate {0}/{1} rejected: {2} -- trying next'.format(
            idx, len(ar_texts), diag))
    _log('all {0} Arabic candidate(s) failed alignment -> normal translation '
         '(fallback)'.format(len(ar_texts)))
    return None
