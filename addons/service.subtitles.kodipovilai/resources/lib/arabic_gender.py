# Gendered-language reference for AI translation (opt-in).
#
# Hebrew is heavily gendered and the #1 quality issue is per-line gender (who is
# speaking / who is addressed). English doesn't mark it; Arabic does, almost 1:1
# with Hebrew (أنتَ/أنتِ, gendered verbs/imperatives). A HUMAN Arabic subtitle of
# the same title already "solved" gender per line. So, when enabled, we fetch an
# Arabic sub for the same media, time-align it to the source SRT, and hand each
# entry its aligned Arabic line as a GENDER ORACLE in the prompt (see prompt.py).
#
# When no Arabic subtitle exists (or none aligns), we fall through a PRIORITY
# CHAIN of other gender-marking languages (see _REF_CHAIN): an out-of-sync human
# HEBREW sub is the best oracle of all, then Arabic, then Romance/Slavic/Indic
# languages whose adjectives/verbs mark speaker+addressee gender. Same
# fetch-align-hint pipeline, one engine search for all of them.
#
# This module is self-contained + fully guarded: ANY failure returns None and the
# caller falls back to the normal (no-reference) translation. It NEVER raises.
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
    # Letter ranges cover every script in the reference chain: basic+extended
    # Latin (es/fr/it/pt/pl/cs/ro/hr/sk/nl), Greek, Cyrillic (ru/uk/bg/sr),
    # Hebrew, Arabic (also Urdu), Devanagari (Hindi). Without the extra ranges
    # a Cyrillic/Greek/Hindi reference sub would parse as "no dialogue" and be
    # rejected before alignment even ran.
    letters = re.sub(
        r'[^A-Za-zÀ-ɏͰ-ϿЀ-ӿ'
        r'֐-׿؀-ۿऀ-ॿ]', '', t)
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


# ---------------- the reference-language priority chain ---------------------

# Priority order for the gender oracle. An out-of-sync HUMAN Hebrew sub is the
# strongest possible reference (it IS the target language); Arabic is the gold
# standard among foreign ones (Semitic, near-1:1 gender marking with Hebrew);
# then languages ranked by gender-signal strength x real-world availability.
_REF_CHAIN = ('he', 'ar', 'es', 'fr', 'ru', 'it', 'pt', 'pl', 'uk', 'hi',
              'cs', 'ro', 'el', 'bg', 'sr', 'hr', 'sk', 'ur', 'nl')

# Codes/names a provider might report for each chain language (lowercase).
# Providers emit a mix of ISO 639-1, 639-2/B, 639-2/T and English names; the
# bridge normalizes most but not all, so we match generously here.
_REF_LANG_ALIASES = {
    'he': ('he', 'iw', 'heb', 'hebrew'),
    'ar': ('ar', 'ara', 'arabic'),
    'es': ('es', 'sp', 'spa', 'spanish'),
    'fr': ('fr', 'fre', 'fra', 'french'),
    'ru': ('ru', 'rus', 'russian'),
    'it': ('it', 'ita', 'italian'),
    'pt': ('pt', 'por', 'pb', 'pob', 'pt-br', 'ptbr', 'portuguese',
           'brazilian portuguese', 'brazillian portuguese'),
    'pl': ('pl', 'pol', 'polish'),
    'uk': ('uk', 'ukr', 'ukrainian'),
    'hi': ('hi', 'hin', 'hindi'),
    'cs': ('cs', 'cze', 'ces', 'czech'),
    'ro': ('ro', 'rum', 'ron', 'romanian'),
    'el': ('el', 'gr', 'gre', 'ell', 'greek'),
    'bg': ('bg', 'bul', 'bulgarian'),
    'sr': ('sr', 'srp', 'scc', 'serbian'),
    'hr': ('hr', 'hrv', 'scr', 'croatian'),
    'sk': ('sk', 'slo', 'slk', 'slovak'),
    'ur': ('ur', 'urd', 'urdu'),
    'nl': ('nl', 'dut', 'nld', 'dutch'),
}

_ALIAS_TO_CHAIN = {alias: code
                   for code, aliases in _REF_LANG_ALIASES.items()
                   for alias in aliases}

# Try at most this many candidates per language, and at most this many
# downloads in total across the whole chain (latency bound: the common case --
# an Arabic or Hebrew sub that aligns -- still downloads a SINGLE file).
_PER_LANG_LIMIT = 3
_TOTAL_DOWNLOAD_BUDGET = 8


def _chain_lang_of(cand):
    """Map an engine candidate to its chain language code, or None if the
    candidate's language isn't in the chain (or is unusable as an oracle)."""
    lang = _ALIAS_TO_CHAIN.get((cand.get('language') or '').strip().lower())
    if lang == 'he':
        # A machine-translated Hebrew sub is a POISONED oracle (MT defaults to
        # masculine) -- only HUMAN Hebrew subs may anchor gender.
        kind = (cand.get('_engine_kind') or '').strip().lower()
        if kind and kind != 'human_he':
            return None
        if 'HebrewMachineTranslated' in (cand.get('filename') or ''):
            return None
    return lang


# ---------------- fetch reference candidates from the engine ----------------

def _reference_candidates(info):
    """Return ALL subtitle CANDIDATES (metadata only -- NOT yet downloaded) for
    this media from the built-in engine (OpenSubtitles / SubSource / YIFY /
    Hebrew providers). Filtering to chain languages happens in prepare().

    The engine gates languages by setting, so JUST for this search we flip
    `language_arab` on and force `all_lang` on (so every chain language comes
    back in one search), then restore. language_arab always settles to 'false'
    (it must never pollute normal searches -- Arabic is only ever an internal
    gender oracle, not a target language); all_lang is restored to whatever the
    user had. Guarded; never raises."""
    try:
        from resources.lib import subs_engine_bridge
    except Exception:
        return []
    cands = []
    prev_all_lang = None
    try:
        if kodi_utils is not None:
            try:
                kodi_utils.set_setting('language_arab', 'true')
            except Exception:
                pass
            try:
                prev_all_lang = kodi_utils.get_setting('all_lang', '')
                if (prev_all_lang or '').strip().lower() != 'true':
                    kodi_utils.set_setting('all_lang', 'true')
                else:
                    prev_all_lang = None  # already true -> nothing to restore
            except Exception:
                prev_all_lang = None
        try:
            cands = subs_engine_bridge.search(info, modal_progress=False) or []
        except Exception as e:
            _log('engine search for gender reference failed: {0}'.format(e),
                 level='WARNING')
            cands = []
    finally:
        # Always settle Arabic back OFF so it never pollutes normal searches
        # (also self-heals installs left 'true' by the old eager code).
        if kodi_utils is not None:
            try:
                kodi_utils.set_setting('language_arab', 'false')
            except Exception:
                pass
            if prev_all_lang is not None:
                try:
                    kodi_utils.set_setting('all_lang', prev_all_lang)
                except Exception:
                    pass
    return cands


def _download_candidate(c):
    """Download ONE reference candidate and return its text, or None. Guarded."""
    try:
        from resources.lib import subs_engine_bridge, translate
        payload = translate._decode_link(c.get('link') or '')
        if not payload:
            return None
        path = subs_engine_bridge.download(payload)
        if path and os.path.isfile(path):
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
    except Exception as e:
        _log('reference download failed (continuing): {0}'.format(e),
             level='DEBUG')
    return None


def prepare(info, src_text):
    """ENTRY POINT. When the feature is on, find gender-reference subs for
    `info` and try them in PRIORITY-CHAIN order (Hebrew, Arabic, then the other
    gender-marking languages) until one aligns confidently. Downloads LAZILY --
    one at a time, stopping at the first that aligns -- so the common case pulls
    a SINGLE reference file. Returns a dict {srt_entry_number: reference_text}
    (gender hints) or None to fall back to the normal translation. ALSO returns
    a small diag dict for telemetry: reason is 'ok' / 'no_source' / 'no_arabic'
    (kept name: means NO chain-language candidate at all) / 'no_align' /
    'crash'; on success diag['lang'] is the chain code actually used.
    Fully guarded."""
    try:
        from resources.lib import srt as _srt
        src_blocks = _srt.parse_blocks(src_text)
    except Exception:
        return None, {'reason': 'crash'}
    if not src_blocks:
        return None, {'reason': 'no_source'}
    try:
        all_cands = _reference_candidates(info)
    except Exception as e:
        _log('fetch crashed: {0}'.format(e), level='WARNING')
        return None, {'reason': 'crash'}

    # Bucket by chain language, preserving the engine's own ranking (it sorts
    # by release-match %, so earlier candidates align more often).
    by_lang = {}
    for c in all_cands:
        lang = _chain_lang_of(c)
        if lang and len(by_lang.setdefault(lang, [])) < _PER_LANG_LIMIT:
            by_lang[lang].append(c)

    # NOTE on Hebrew-first: the user reached AI translation, so any Hebrew sub
    # here is out-of-sync / unmatched for their release -- but as a GENDER
    # ORACLE it only needs to time-align to the SOURCE sub, which the scale+
    # offset estimator handles. It is the strongest oracle (it IS Hebrew).
    ordered = [(lang, c) for lang in _REF_CHAIN for c in by_lang.get(lang, [])]
    if not ordered:
        _log('no gender-reference candidates in any chain language -> normal '
             'translation (fallback)')
        return None, {'reason': 'no_arabic', 'cands': 0}

    total = len(ordered)
    langs_present = [l for l in _REF_CHAIN if l in by_lang]
    _log('reference candidates: {0} across {1}'.format(
        total, ','.join(langs_present)))
    best_diag = ''
    attempts = 0
    for idx, (lang, c) in enumerate(ordered, 1):
        if attempts >= _TOTAL_DOWNLOAD_BUDGET:
            _log('download budget ({0}) exhausted -- stopping the chain'.format(
                _TOTAL_DOWNLOAD_BUDGET))
            break
        attempts += 1
        ref_text = _download_candidate(c)  # lazy: fetch only when we reach it
        if not ref_text:
            continue
        try:
            mapping, diag = align_one(src_text, src_blocks, ref_text)
        except Exception as e:
            _log('align candidate {0} [{1}] crashed: {2}'.format(idx, lang, e),
                 level='WARNING')
            continue
        if mapping is not None:
            _log('candidate {0}/{1} [{2}] {3} -> using {2} gender reference '
                 '({4} entries hinted)'.format(idx, total, lang, diag,
                                               len(mapping)))
            return mapping, {'reason': 'ok', 'cands': total,
                             'hinted': len(mapping), 'diag': diag,
                             'lang': lang}
        best_diag = diag
        _log('candidate {0}/{1} [{2}] rejected: {3} -- trying next'.format(
            idx, total, lang, diag))
    _log('all {0} reference candidate(s) failed alignment -> normal '
         'translation (fallback)'.format(total))
    return None, {'reason': 'no_align', 'cands': total, 'diag': best_diag}
