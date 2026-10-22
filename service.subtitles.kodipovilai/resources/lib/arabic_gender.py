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
import threading
import time

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
        r'[^A-Za-zÀ-ÖØ-öø-ɏͰ-ϿЀ-ӿ'
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

def _arabic_for_blocks(src_blocks, ar_cues, a, b, segments=None):
    """Return {srt_entry_number: aligned Arabic dialogue text} for the dialogue
    blocks with a confident time-overlap. Keyed by the block's own SRT number
    (robust to how translate.py later chunks them). SFX/music blocks omitted."""
    import bisect
    ar_centers = [(c['start'] + c['end']) / 2.0 for c in ar_cues]
    ar_starts = [c['start'] for c in ar_cues]
    ar_ends = [c['end'] for c in ar_cues]
    out = {}
    segments = list(segments or [])
    ref_boundaries = [float(seg.get('ref_from_ms')) for seg in segments[1:]
                      if seg.get('ref_from_ms') is not None]
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
        applied_b = b
        if segments:
            si = bisect.bisect_right(ref_boundaries, (s + e) / 2.0)
            si = min(si, len(segments) - 1)
            applied_b = float(segments[si].get('offset_ms') or 0.0)
        es, ee = a * s + applied_b, a * e + applied_b
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
        pred = a * ((s + e) / 2.0) + applied_b
        j = bisect.bisect_left(ar_centers, pred)
        bd, bk = 1e9, None
        for kk in (j - 1, j, j + 1):
            if 0 <= kk < len(ar_cues) and abs(ar_centers[kk] - pred) < bd:
                bd, bk = abs(ar_centers[kk] - pred), kk
        if bk is not None and bd <= _TIGHT:
            out[num] = ar_cues[bk]['text']
    return out


def align_one(src_text, src_blocks, ar_text, timing_text=None):
    """Try to align ONE Arabic SRT to the source. Returns (ar_for_blocks, diag)
    on success, or (None, diag) when the alignment isn't trustworthy.

    `timing_text` is the source as it was cued before same-time captions were
    merged. The gate measures the clock on those original cues (measured: a
    Netflix file that aligns cleanly cue-by-cue fails local consistency once
    its split captions are merged), and the hints are then placed on
    `src_blocks`, whose merged captions keep the exact same timecodes."""
    en = [c for c in _parse(timing_text or src_text) if _is_dialogue(c['text'])]
    ar = [c for c in _parse(ar_text) if _is_dialogue(c['text'])]
    if len(en) < 8 or len(ar) < 8:
        return None, 'too few dialogue cues (en=%d ar=%d)' % (len(en), len(ar))
    # Share the hardened SubSync timing engine: deduped/refined global mapping,
    # local-window consistency, and a strictly validated piecewise map for
    # obvious recap/ad/different-cut steps.  Gender-oracle alignment intentionally
    # keeps its historical 65% overlap contract and does not impose SubSync's
    # display-subtitle tight-onset floor: cross-language line segmentation is
    # different, and an oracle miss is fail-soft (it never changes cue timing).
    try:
        from resources.lib import sync_align as _sync_align
        verdict = _sync_align.verify_cue_lists(
            en, ar, min_vote=0.65, min_overlap=0.65,
            allow_piecewise=True, require_tight=False)
        if verdict.get('status') == _sync_align.STATUS_UNKNOWN:
            return None, verdict.get('diag') or 'gate FAILED'
        a = float(verdict.get('scale') or 1.0)
        b = float(verdict.get('offset_ms') or 0.0)
        mapping = _arabic_for_blocks(
            src_blocks, ar, a, b, segments=verdict.get('segments'))
        return mapping, 'gate OK (' + (verdict.get('diag') or '') + ')'
    except Exception as e:
        # sync_align ships in the same add-on.  Falling back to the historical
        # global-only vote here is unsafe: a dominant first half can hide a
        # differently cut second half and attach gender evidence to the wrong
        # dialogue.  Gender hints are optional, so fail closed for this helper.
        _log('hardened aligner failed; declining gender reference: {0}'.format(e),
             level='WARNING')
        return None, 'hardened aligner failed; reference declined'

    # Kept as dead-compatible reference code for old external imports; the
    # production path above always returns and never reaches this weaker gate.
    a, b, vote = _estimate_map(en, ar)
    ov = _overlap_rate(en, ar, a, b)
    diag = 'scale=%.4f offset=%+dms vote=%.0f%% overlap=%.0f%%' % (
        a, int(b), vote * 100, ov * 100)
    # Confidence gate. The MAP must be trustworthy (right framerate band + a
    # strong offset vote), but COVERAGE may be partial: as a gender ORACLE, a
    # reference that overlaps 65-79% of the source still hints gender for most
    # entries -- strictly better than no reference (the un-hinted entries simply
    # translate without a hint, exactly as if there were none). Field data (the
    # D1 no_align overlap distribution) showed ~65% of rejections sat in this
    # 65-79% band WITH a correct map, so the old 0.80 coverage floor was throwing
    # away usable oracles. vote>=0.65 + the framerate band stay the real guards
    # against a spurious alignment. MEASURED, not assumed: a true pair votes
    # 0.742; twenty references with randomised starts vote 0.417-0.441, and
    # nine time-REVERSED real references (same cue density, no correspondence)
    # vote 0.439-0.441. So the floor is ~0.43, not the ~0.30 this comment
    # used to claim -- the gate still clears it, by less than we said.
    if not (0.90 <= a <= 1.11) or vote < 0.65 or ov < 0.65:
        return None, 'gate FAILED (' + diag + ')'
    return _arabic_for_blocks(src_blocks, ar, a, b), 'gate OK (' + diag + ')'


# ---------------- the reference-language priority chain ---------------------

# Priority order for the gender oracle. An out-of-sync HUMAN Hebrew sub is the
# strongest possible reference (it IS the target language); Arabic is the gold
# standard among foreign ones (Semitic, near-1:1 gender marking with Hebrew);
# then languages ranked by gender-signal strength x real-world availability.
_REF_CHAIN = ('he', 'ar', 'hi', 'es', 'ru', 'pt', 'pl', 'uk', 'fr', 'it',
              'cs', 'ro', 'el', 'bg', 'sr', 'hr', 'sk', 'ur', 'nl')

# The chain split into quality tiers, which is what begin() actually walks.
# Tier 1 is the two oracles this feature was built and validated on; tier 2 is
# everything else, which is a useful hint but not in the same class. The
# boundary is the thing to move if real data ever says another language earns
# tier 1 -- not the round-robin, which is only about reaching them.
_REF_TIERS = (('he', 'ar'), _REF_CHAIN[2:])

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

# Try substantially deeper inside each higher-priority language before moving
# to the next one. Provider metadata search is parallel, but the actual subtitle
# downloads + alignment below are lazy, serial and chain-ordered: first aligning
# candidate wins. Ten is deliberately bounded because OpenSubtitles can paginate
# every result for a popular title; "all" could mean hundreds of downloads and
# minutes of blocked playback. A language may receive up to ten attempts; the
# global download budget lets the search fully examine the five strongest
# saturated languages (he/ar/hi/es/ru), while the active-work deadline remains
# the primary latency circuit-breaker. This still avoids the unbounded
# 10-times-every-language worst case and provider request storms.
_PER_LANG_LIMIT = 10
_TOTAL_DOWNLOAD_BUDGET = 50
# The chain is walked round-robin (see begin()), so a usable oracle is
# reached early. The deadline is what decides how much DEPTH is left
# afterwards -- how many candidates per language get a turn once every
# language has had its first. At 30s it was one or two rounds, so the
# fifth Hebrew subtitle, which may well be a different release that
# aligns where the first four did not, was rarely reached at all.
#
# 60s buys full depth on the languages that are actually present
# (~30 downloads) and costs nothing in the common case: next() returns
# the moment something aligns, so a job whose first candidate works
# still pays for one download. Only a job where NOTHING aligns spends
# the ceiling, and it spends it inside a translation that already runs
# for minutes behind a progress bar (a film is ~36 requests paced at 14
# per minute), not in front of playback.
_REFERENCE_DEADLINE_S = 60.0


def _chain_lang_of(cand):
    """Map an engine candidate to its chain language code, or None if the
    candidate's language isn't in the chain (or is unusable as an oracle)."""
    # A machine/AI-translated sub in ANY language is a POISONED oracle (MT
    # defaults to masculine) -- only human subs may anchor gender. The bridge
    # sets '_is_mt' from the provider's flag (e.g. OpenSubtitles ai_translated/
    # machine_translated); missing key (old cached results) -> not flagged.
    if cand.get('_is_mt'):
        return None
    lang = _ALIAS_TO_CHAIN.get((cand.get('language') or '').strip().lower())
    if lang == 'he':
        # Hebrew gets an extra belt-and-braces check via the engine kind: only
        # candidates the bridge classified as HUMAN Hebrew are accepted.
        kind = (cand.get('_engine_kind') or '').strip().lower()
        if kind and kind != 'human_he':
            return None
        if 'HebrewMachineTranslated' in (cand.get('filename') or ''):
            return None
    return lang


def _provider_of(cand):
    """The provider in an engine candidate's label ("[XX] Wizdom · 87%  --
    name"), for the log. A Hebrew reference is trusted as a human
    translation; a field log has to show which provider that trust went to
    (NG gender-reference: reference provenance)."""
    import re
    label = re.sub(r'^(?:\[[^\]]*\]\s*)+', '', cand.get('filename') or '')
    return label.split(' · ', 1)[0].strip()[:40] or '?'


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
        # Reference analysis needs logical text, not the player-rendered RTL copy.
        path = subs_engine_bridge.download(payload, for_delivery=False)
        if path and os.path.isfile(path):
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
    except Exception as e:
        _log('reference download failed (continuing): {0}'.format(e),
             level='DEBUG')
    return None


class ReferencePlan(object):
    """A lazy, resumable gender-reference chain. Holds the ordered candidate list
    (metadata only, no downloads yet) and yields aligned per-entry maps ONE
    LANGUAGE AT A TIME in priority order via .next().

    The FIRST .next() gives the primary reference (same single-download cost as
    the old prepare()); each subsequent .next() downloads+aligns the NEXT chain
    language that aligns -- used by translate.py as a fallback when a chunk gets
    prompt-blocked (PROHIBITED_CONTENT), so a blocked chunk can be retried with a
    DIFFERENT human-subtitle gender oracle (e.g. Spanish after Arabic) before
    dropping the reference entirely. Downloads are lazy + bounded by
    _TOTAL_DOWNLOAD_BUDGET, so a job that never blocks pays for exactly one
    reference. Thread-safe (parallel chunk workers may pull a fallback at once)
    and fully guarded: any failure yields (None, None), never raises."""

    def __init__(self, src_text, src_blocks, ordered, total, timing_text=None):
        self._src_text = src_text
        self._timing_text = timing_text
        self._src_blocks = src_blocks
        self._ordered = ordered      # [(lang, candidate), ...] in chain order
        self.total = total
        self._pos = 0
        self._downloads = 0
        # Count only time spent downloading/alignment. Long idle gaps between
        # lazy .next() calls (while Gemini translates) must not expire fallbacks.
        self._active_elapsed = 0.0
        self._used = set()           # chain langs already returned (one map each)
        self._lock = threading.Lock()
        self.last_diag = ''          # diag of the candidate examined last: the
        #                              WINNER right after a successful next(), or
        #                              the last rejection once the chain is dry

    def next(self):
        """Return (lang, map) for the next chain language that aligns, or
        (None, None) when the chain / download budget is exhausted."""
        try:
            with self._lock:
                while self._pos < len(self._ordered):
                    if self._downloads >= _TOTAL_DOWNLOAD_BUDGET:
                        _log('download budget ({0}) exhausted -- stopping the '
                             'chain'.format(_TOTAL_DOWNLOAD_BUDGET))
                        return None, None
                    if self._active_elapsed >= _REFERENCE_DEADLINE_S:
                        _log('reference work budget ({0:.0f}s active) reached -- '
                             'stopping the chain'.format(_REFERENCE_DEADLINE_S))
                        return None, None
                    lang, cand = self._ordered[self._pos]
                    self._pos += 1
                    if lang in self._used:
                        continue     # already yielded a map for this language
                    attempt_started = time.monotonic()
                    try:
                        ref_text = _download_candidate(cand)  # lazy fetch
                        self._downloads += 1
                        if not ref_text:
                            continue
                        try:
                            if self._timing_text:
                                mapping, diag = align_one(
                                    self._src_text, self._src_blocks, ref_text,
                                    timing_text=self._timing_text)
                            else:
                                mapping, diag = align_one(
                                    self._src_text, self._src_blocks, ref_text)
                        except Exception as e:
                            _log('align [{0}] crashed: {1}'.format(lang, e),
                                 level='WARNING')
                            continue
                        # winner (on return) or last rejection once chain is dry
                        self.last_diag = diag
                        if mapping:
                            self._used.add(lang)
                            _log(
                                'reference [{0}] {1} -> {2} entries hinted '
                                '(from {3})'.format(lang, diag, len(mapping),
                                                    _provider_of(cand)))
                            return lang, mapping
                        _log(
                            'candidate [{0}] rejected: {1} -- trying next'
                            .format(lang, diag))
                    finally:
                        self._active_elapsed += max(
                            0.0, time.monotonic() - attempt_started)
                return None, None
        except Exception as e:
            _log('ReferencePlan.next crashed: {0}'.format(e), level='WARNING')
            return None, None


# ---------------- gender VERIFICATION (after the translation) ---------------
# The reference is a hint in a prompt, and a prompt is an instruction rather
# than a guarantee. Measured on a full film with a perfectly aligned Arabic
# oracle: 51 of 52 scorable lines came back with the right addressee gender,
# and the one that did not had an unambiguous "\u0623\u0646\u062a\u0650" (feminine) sitting in
# its own prompt. So the last few points are compliance, not knowledge, and
# the way to close them is to CHECK the output rather than ask more loudly.
#
# ONE DIRECTION ONLY, deliberately. "\u05d0\u05ea\u05d4" can only be the masculine
# second-person pronoun, so finding it where the reference says feminine is
# proof of an error. The feminine "\u05d0\u05ea" is also Hebrew's definite-object
# marker -- "\u05e8\u05d0\u05d9\u05ea\u05d9 \u05d0\u05ea \u05d3\u05df" is not addressing a woman -- so the mirror check
# would flag correct lines, and there is no reliable way to tell the two apart
# without parsing. That asymmetry costs nothing in practice: every one of the
# 24 gender errors in the file a viewer reported was masculine-where-feminine,
# which is exactly what an unhinted translation defaulting to masculine looks
# like. The direction that can be checked safely is the direction that fails.
# EVERY pattern above the blank line needs HARAKAT, and real subtitles do not
# carry it. Measured on a full human Arabic episode: 7,415 Arabic letters, TWO
# diacritics, zero vocalised \u0623\u0646\u062a\u064e/\u0623\u0646\u062a\u0650 -- so the whole Arabic branch read
# F=0 M=0 None=370. Arabic anchors the largest share of real jobs, which made
# it the emptiest reader we had.
#
# The 2fs PRESENT suffix is different: \u062a...\u064a\u0646 is consonantal and is always
# written. Two noun classes wear the same ending and must not be read as an
# addressee:
#   * the \u062a\u0641\u0639\u064a\u0644 verbal noun -- \u062a\u0645\u0631\u064a\u0646, \u062a\u0639\u064a\u064a\u0646, \u062a\u062d\u0633\u064a\u0646, \u062a\u062f\u062e\u064a\u0646 -- which is
#     FIVE letters and structurally identical to a real 5-letter verb like
#     \u062a\u0628\u062f\u064a\u0646. Nothing short of a lexicon separates them, so the floor is
#     six letters and \u062a\u0628\u062f\u064a\u0646 / \u062a\u0638\u0646\u064a\u0646 / \u062a\u0642\u0636\u064a\u0646 are given up on purpose.
#   * the feminine sound dual -- \u062a\u0641\u0635\u064a\u0644\u0629 -> \u062a\u0641\u0635\u064a\u0644\u062a\u064a\u0646 -- so the letter before
#     the suffix may not be \u062a.
# Recall loses a little, precision wins, and that is the right way round: this
# reader feeds a repair pass, and a false F spends a request rewriting a line
# that was already correct. Measured on the same episode: 19 of 370 cues
# (5.1%), eleven distinct forms, every one a genuine 2fs verb, and twelve
# noun controls (\u062a\u0645\u0631\u064a\u0646, \u0633\u0646\u062a\u064a\u0646, \u0645\u0631\u062a\u064a\u0646, ...) all correctly refused.
# Arabic glues object pronouns straight onto the verb -- \u062a\u062e\u064a\u0641\u064a\u0646\u0646\u064a, \u062a\u0631\u064a\u062f\u064a\u0646\u0647,
# \u062a\u0639\u0631\u0641\u064a\u0646\u0647\u0627 -- and a suffix-must-end-the-word rule misses all of them. The
# clitic set is closed, so allowing it costs no precision against the noun
# classes above: those are blocked by the six-letter floor whatever follows.
# It DOES open one new class, a 6+ letter broken plural in \u064a\u0646 carrying a
# possessive (\u062a\u0645\u0627\u0631\u064a\u0646\u0647\u0627, \u062a\u0646\u0627\u0646\u064a\u0646\u0647\u0627). The two verified noun stems are
# excluded below; the general morphological ambiguity remains a limitation.
_AR_2FS_PRESENT = (u'(?<![\u0621-\u064a])\u062a[\u0621-\u064a]{2,5}[\u0621-\u0629\u062b-\u064a]\u064a\u0646'
                   u'(?:\u0646\u064a|\u0647\u0645\u0627|\u0647\u0627|\u0647\u0645|\u0647\u0646|\u0643\u0645|\u0647|\u0643)?(?![\u0621-\u064a])')

_AR_FEM = tuple(re.compile(p) for p in (
    u'\u0623\u0646\u062a\u0650', u'\u0644\u0643\u0650', u'\u0628\u0643\u0650', u'\u0639\u0644\u064a\u0643\u0650', u'\u0645\u0639\u0643\u0650', u'\u0625\u0644\u064a\u0643\u0650', u'\u0645\u0646\u0643\u0650',
    u'\u0643\u0650\\s', u'\u0643\u0650$', u'\u062a\u0650\\s', u'\u062a\u0650$', u'\u064a\u0627 \u0633\u064a\u062f\u062a\u064a',
    _AR_2FS_PRESENT,
))
_AR_MASC = tuple(re.compile(p) for p in (
    u'\u0623\u0646\u062a\u064e', u'\u0644\u0643\u064e', u'\u0628\u0643\u064e', u'\u0639\u0644\u064a\u0643\u064e', u'\u0645\u0639\u0643\u064e', u'\u0625\u0644\u064a\u0643\u064e', u'\u0645\u0646\u0643\u064e',
    u'\u0643\u064e\\s', u'\u0643\u064e$', u'\u062a\u064e\\s', u'\u062a\u064e$',
))
# Narrow lexical exceptions to the productive 2fs shape. These are nouns
# (exercises / dragons), including possessives, not feminine-address verbs.
# Keep other evidence in the same cue; this is not a general Arabic parser.
_AR_NOUN_EXCEPTIONS = re.compile(
    r'(?<![\u0621-\u064a])(?:[وفلب]|ال|وال|بال|فال|لل)?(?:تمارين|تنانين)'
    r'(?:ها|هما|هم|هن|ه|كم|كن|ك|نا|ي)?(?![\u0621-\u064a])')
# Hebrew reference: read the pronoun straight off it.
# The SAME proclitic alternation _HE_MASC carries below. Without it we looked
# for \u05d5\u05d0\u05ea\u05d4/\u05e9\u05d0\u05ea\u05d4 but never for \u05d5\u05d0\u05ea/\u05e9\u05d0\u05ea -- an asymmetry that made the
# reader better at finding a MALE addressee than a female one, in a check whose
# whole purpose is catching masculine-where-feminine.
_HE_PRO = u'(?:\u05d5|\u05e9|\u05db\u05e9|\u05d5\u05e9|\u05d5\u05db\u05e9)?'
_HE_REF_FEM = re.compile(
    u'(?<![\u05d0-\u05ea])' + _HE_PRO + u'\u05d0\u05ea(?![\u05d0-\u05ea])(?!\\s*\u05d4)')

# A letter shape is not morphology: תפקידי, תורכי and תלמידי are
# ordinary nouns/adjectives, not commands. Use a small reviewed vocabulary
# for repair candidates; unknown forms abstain. These are hints, not proof.
_HE_FEM_VERB = re.compile(
    u'(?<![א-ת])' + _HE_PRO +
    u'(?:תגידי|תסמכי|תשמרי|תעשי|תבואי|תלכי|תחכי|תקחי|תתני|תדברי|תראי|תשמעי)(?![א-ת])')
_HE_FEM_IMPER = re.compile(
    u'(?<![א-ת])' + _HE_PRO +
    u'(?:בואי|לכי|חכי|קחי|תני|סלחי|עזרי)(?![א-ת])')
# Bare את is also an object marker, even before a name (ראיתי את דני).
# Admit only a clause-leading pronoun or an explicit subordinating clitic.
_HE_FEM_CLAUSE = re.compile(
    r'(?:^|[.!?\n,:;—-])\s*(?:ו)?את(?![א-ת])|'
    u'(?<![א-ת])(?:ש|כש|וש|וכש)את(?![א-ת])')
# A narrow verbal continuation avoids treating הולכת בלי/איתי as a
# definite noun. Bare הולכת and הולכת הרגל remain ambiguous and abstain.
_HE_AT_OBJ = re.compile(
    r'\s+(?:זה|זאת|זו|אלה|אלו|כל(?!\s+כך)|מה|מי|עצמ|אות|כך|של|ה(?!ולכת\s+(?:בלי|איתי)(?![א-ת]))[א-ת])')
# Clause position alone is insufficient: "את דני ראיתי" fronts an object.
# Require a reviewed predicate too; unseen predicates remain prompt-only hints.
_HE_AT_PREDICATE = re.compile(
    r'\s+(?:(?:כל\s+כך|מאוד|ממש|ודאי|בטעות|כבר|עדיין|לא)\s+){0,3}'
    r'(?:יפה|מוכנה|מבהילה|מפחידה|מעמידה|יודעת|חוזרת|צריכה|יכולה|רוצה|'
    r'חייבת|בטוחה|עייפה|צודקת|טועה|מבינה|מקשיבה|מדברת|הולכת|נראית)(?![א-ת])')


def _he_addresses_female(text):
    """Conservative candidate evidence; uncertain Hebrew does not trigger repair."""
    try:
        if _HE_FEM_VERB.search(text) or _HE_FEM_IMPER.search(text):
            return True
        return any(not _HE_AT_OBJ.match(text[m.end():])
                   and _HE_AT_PREDICATE.match(text[m.end():])
                   for m in _HE_FEM_CLAUSE.finditer(text))
    except Exception:
        return False
# The proclitics Hebrew glues straight onto a pronoun: ו (and), ש (that),
# כש (when) and their combinations. Without them "ואתה", "שאתה" and
# "כשאתה" -- ordinary, high-frequency Hebrew -- read as no pronoun at all,
# which both hides real errors from the check and lets a "repair" that is
# still masculine pass as fixed. The set is deliberately just these: allowing
# ANY preceding letter would match the אתה inside ראתה ("she saw").
_HE_MASC = re.compile(
    u'(?<![\u05d0-\u05ea])(?:\u05d5|\u05e9|\u05db\u05e9|\u05d5\u05e9|\u05d5\u05db\u05e9)?\u05d0\u05ea\u05d4(?![\u05d0-\u05ea])')


# The rest of the chain. Arabic and Hebrew are read above; these are the
# languages whose ADDRESSEE marking can be read without parsing, because the
# marker is a VERB ending tied to the second person -- there is no other thing
# in the language it could be.
#
# Deliberately NOT here, and this is the whole design: es, it, pt, fr, ro and
# el mark gender on ADJECTIVES, and an adjective ending is not distinguishable
# from a feminine noun's ending without knowing which word is which ("eres una
# estrella" ends in -a and says nothing about who is being addressed). nl marks
# only referent gender, never the addressee. ur is written in Arabic script but
# marks gender through Indic verb morphology, not the Arabic diacritics above,
# so the patterns there do not transfer. For all of those this returns None and
# the verification pass simply does not fire -- which is exactly today's
# behaviour, and far better than rewriting a line that was already right.
#
# Every pattern below is validated in tools/test_gender_verification.py against
# both genders and against a first/third-person sentence that must NOT match.
def _rx(*pats):
    return tuple(re.compile(p, re.I | re.U) for p in pats)


_ADDRESSEE_MARKERS = {
    # Slavic past tense: the second-person pronoun plus a gendered participle.
    'ru': (_rx(r'(?<![\u0430-\u044f\u0451])\u0442\u044b\b[^.!?]{0,40}?\b\w+\u043b\u0430\b'),
           _rx(r'(?<![\u0430-\u044f\u0451])\u0442\u044b\b[^.!?]{0,40}?\b\w+\u043b\b')),
    'uk': (_rx(r'(?<![\u0430-\u044f\u0456\u0457])\u0442\u0438\b[^.!?]{0,40}?\b\w+\u043b\u0430\b'),
           _rx(r'(?<![\u0430-\u044f\u0456\u0457])\u0442\u0438\b[^.!?]{0,40}?\b\w+(\u0432|\u0438\u0439)\b')),
    'bg': (_rx(r'(?<![\u0430-\u044f])\u0442\u0438\b[^.!?]{0,40}?\b\w+(\u043b\u0430|\u043d\u0430)\b'),
           _rx(r'(?<![\u0430-\u044f])\u0442\u0438\b[^.!?]{0,40}?\b\w+(\u0435\u043d|\u043b)\b')),
    # Polish encodes person AND gender in the ending itself.
    'pl': (_rx(r'\w+\u0142a\u015b\b'), _rx(r'\w+\u0142e\u015b\b')),
    # Czech / Slovak / Serbian / Croatian: participle + the 2sg auxiliary.
    # sr/hr take -ao/-io rather than a bare -o: ordinary words end in -o
    # ('tamo'), so a bare -o matched alongside the feminine -la and every
    # line came back ambiguous.
    'cs': (_rx(r'\w+la\s+jsi\b'), _rx(r'\w+l\s+jsi\b')),
    'sk': (_rx(r'\w+la\s+si\b'), _rx(r'\w+l\s+si\b')),
    'sr': (_rx(r'\bti\s+si\b[^.!?]{0,30}?\b\w+la\b'),
           _rx(r'\bti\s+si\b[^.!?]{0,30}?\b\w+(ao|io)\b')),
    'hr': (_rx(r'\bti\s+si\b[^.!?]{0,30}?\b\w+la\b'),
           _rx(r'\bti\s+si\b[^.!?]{0,30}?\b\w+(ao|io)\b')),
    # Hindi: the second-person copula with a feminine/masculine participle.
    'hi': (_rx(r'(\u0924\u0941\u092e|\u0906\u092a)[^\u0964?!]{0,30}?\u0940\s+(\u0939\u094b|\u0939\u0948\u0902)'),
           _rx(r'(\u0924\u0941\u092e|\u0906\u092a)[^\u0964?!]{0,30}?\u0947\s+(\u0939\u094b|\u0939\u0948\u0902)')),
}


# Invisible direction marks are not text: a human Hebrew file that starts a
# line with U+202B still starts it with "את" (measured by SRT AI Translator
# NG, Round 19A A.1 -- _HE_FEM_CLAUSE anchors on the line start).
_DIRECTION_MARKS = re.compile(u'[‎‏‪-‮⁦-⁩؜﻿]')


def _visible(text):
    return _DIRECTION_MARKS.sub(u'', text or u'')


def reference_addressee_gender(ref_text, lang):
    """'F', 'M', or None when the reference does not mark it unambiguously.

    'he' and 'ar' are read directly; every language in _ADDRESSEE_MARKERS
    (ru, uk, bg, pl, cs, sk, sr, hr, hi) is read from its own validated
    pattern pair. Anything else returns None, so the verification pass does
    not fire rather than guessing from a marking nobody checked here.
    (This used to say only he/ar were read, which stopped being true when
    _ADDRESSEE_MARKERS landed -- tools/test_gender_verification.py exercises
    all nine against both genders plus a must-not-match control.)
    """
    if not ref_text:
        return None
    try:
        ref_text = _visible(ref_text)
        if lang in ('es', 'pt'):
            # A short reviewed list of second-person predicate adjectives
            # (estás cansada / você está pronto); anything else stays None.
            gg = _gg()
            return gg.romance_addressee(ref_text, lang) if gg is not None else None
        if lang == 'he':
            f = _he_addresses_female(ref_text)
            m = bool(_HE_MASC.search(ref_text))
        elif lang == 'ar':
            signal_text = _AR_NOUN_EXCEPTIONS.sub(' ', ref_text)
            f = any(p.search(signal_text) for p in _AR_FEM)
            m = any(p.search(ref_text) for p in _AR_MASC)
            more_f, more_m = _ar_more_addressee(ref_text, signal_text)
            f, m = f or more_f, m or more_m
        elif lang in _ADDRESSEE_MARKERS:
            fem_pats, masc_pats = _ADDRESSEE_MARKERS[lang]
            f = any(p.search(ref_text) for p in fem_pats)
            m = any(p.search(ref_text) for p in masc_pats)
        else:
            return None
        if f and not m:
            return 'F'
        if m and not f:
            return 'M'
        return None
    except Exception:
        return None


# The SPEAKER's own gender, read off a non-Hebrew reference. Only first-person
# forms that cannot be anything else: Arabic "أنا"/"لست" + an adjective
# (feminine ends in ة; masculine from a short reviewed list -- an Arabic word
# without ة is not by itself masculine), and Russian/Ukrainian "я" + a
# past-tense verb or short adjective (-ла / -л, уверена / уверен). Anything
# else is None, and None never triggers a rewrite.
_AR_ME = u'(?<![ء-ي])(?:أنا|لست)\\s+'
_AR_SPEAKER_ADJ = (u'آسف', u'متأكد', u'سعيد', u'مستعد', u'جاهز', u'خائف', u'متعب',
                   u'مشغول', u'متأسف', u'غاضب', u'حزين', u'جائع', u'مسرور', u'موافق',
                   u'قلق', u'فخور', u'مخطئ', u'محق', u'متزوج', u'وحيد', u'مريض',
                   u'نادم')
# Feminine from the same reviewed list (+ة). "Any word ending in ة" also
# matched gender-neutral phrases -- "أنا بحاجة" (I need), "أنا عادة" (I usually).
_AR_SPEAKER_F = re.compile(
    _AR_ME + u'(?:' + u'|'.join(w + u'\u0629' for w in _AR_SPEAKER_ADJ)
    + u')(?![\u0621-\u064a])')
_AR_SPEAKER_M = re.compile(
    _AR_ME + u'(?:آسف|متأكد|سعيد|'
    u'مستعد|جاهز|خائف|متعب|'
    u'مشغول|متأسف|غاضب|حزين|'
    u'جائع|مسرور|موافق|قلق|'
    u'فخور|مخطئ|محق|متزوج|'
    u'وحيد|مريض|نادم)(?![ء-ي])')


# ---------------- more of what an Arabic line says -------------------------
# The two readers above leave most of an Arabic subtitle's gender unread.
# Measured against the human Hebrew of five titles (that Hebrew read by
# he_person_gender as the truth): they found the addressee on 23% of the lines
# where the Hebrew marks one and the speaker on 2%. Everything below is
# consonantal -- no harakat -- and each form was kept only when its own hits
# agreed with the human Hebrew: together 47% / 9%, at 98.7% / 96.1%
# precision. On real no-Hebrew AI translations (two episodes, two runs) the
# check found 19 of 59 gender errors instead of 1, with no new false flag.
_AR_L = u'\u0621-\u064a'
_AR_START = u'(?<![' + _AR_L + u'])'
_AR_END = u'(?![' + _AR_L + u'])'
_AR_CLITIC = u'(?:ني|هما|ها|هم|هن|نا|كم|ه|ك)?'
_AR_CLAUSE = u'(?:^|[.!?\u061f\u060c,:\\-\u2026"]\\s*)'


def _ar_words(words):
    return u'(?:' + u'|'.join(words) + u')'


# 2fs present behind a question/conjunction/future prefix: أتريدين, ستفعلين.
# The six-letter floor on the stem is _AR_2FS_PRESENT's, for the same nouns.
_AR_2FS_PREFIXED = re.compile(
    _AR_START + u'(?:أ|و|ف|س|وس|فس|أف|أو|ل)ت[' + _AR_L + u']{2,5}'
    u'[\u0621-\u0629\u062b-\u064a]ين' + _AR_CLITIC + _AR_END)
# Five-letter 2fs verbs the floor gives up on, from a reviewed list.
_AR_2FS_SHORT = re.compile(
    _AR_START + u'(?:أ|و|ف|س|وس|فس|ل)?' + _ar_words((
        u'تبدين', u'تحبين', u'تظنين', u'ترين', u'تقولين', u'تريدين', u'تعرفين',
        u'تكونين', u'تفعلين', u'تخافين', u'تشعرين', u'تعملين', u'تذهبين', u'تعنين',
        u'تحتاجين', u'تقصدين', u'تمزحين', u'تعتقدين', u'تعيشين', u'تبقين',
        u'تجيئين', u'تأتين', u'تفهمين', u'تسمعين')) + _AR_CLITIC + _AR_END)
# 2fs subjunctive/jussive (the nuun drops) after أن/لن/لم/لا. Only sound and
# hollow verbs: a defective root keeps its ي in the 3fs ("أن تبقي", she
# keeps), so تبقي/تبكي/تأتي stay out.
_AR_2FS_SUBJ = re.compile(
    _AR_START + u'(?:أن|ان|لن|لم|لا|كي|حتى|ألا)\\s+' + _ar_words((
        u'تكوني', u'تقلقي', u'تخافي', u'تفعلي', u'تقولي', u'تذهبي', u'تتكلمي',
        u'تسألي', u'تخبري', u'تلمسي', u'تغضبي', u'تتحدثي', u'تعودي', u'ترحلي',
        u'تقتلي', u'تنظري', u'تعرفي', u'تفكري', u'تضحكي', u'تصدقي', u'تتركي'))
    + _AR_CLITIC + _AR_END)
# Imperatives. Feminine ones end in ي, which no masculine imperative does.
# Left out: أعطي / استرخي, which are also "I give" / "I relax"; and the ones
# that also read as a noun + "my" (توقفي, my stopping) count only where they
# open a clause.
_AR_IMP_F = re.compile(
    _AR_START + u'(?:و|ف)?' + _ar_words((
        u'تعالي', u'انظري', u'أنظري', u'إنظري', u'اسمعي', u'إسمعي', u'اذهبي',
        u'إذهبي', u'اجلسي', u'إجلسي', u'انتظري', u'إنتظري', u'ابقي',
        u'إبقي', u'عودي', u'ارجعي', u'إرجعي', u'قولي', u'خذي', u'دعي', u'اخبري',
        u'أخبري', u'اتصلي', u'اهدئي', u'إهدئي', u'اصمتي', u'إصمتي', u'اسكتي',
        u'انهضي', u'قفي', u'افعلي', u'انسي', u'اركضي', u'ابتعدي', u'ادخلي',
        u'أدخلي', u'اخرجي', u'أخرجي', u'اقرئي', u'اقرأي', u'استمعي',
        u'ساعدي', u'صدقي', u'التقطي', u'اهربي', u'احضري', u'اجلبي',
        u'أجلبي', u'ابتسمي', u'استيقظي',
        u'اتبعي', u'اصعدي', u'انزلي', u'انتبهي', u'تمهلي', u'أسرعي',
        u'اسرعي', u'أريني', u'اريني')) + _AR_CLITIC + _AR_END
    + u'|' + _AR_CLAUSE + u'(?:و|ف)?' + _ar_words((
        u'توقفي', u'تذكري', u'تحركي', u'تنفسي', u'فكري')) + _AR_CLITIC + _AR_END)
# Masculine: forms that cannot be anything else anywhere in a line, then the
# alif-initial ones only where they open a clause -- mid-line, "اسمع" can be
# "أسمع" (I hear) with the hamza dropped. A kasra after the word marks the
# short feminine (تعالِ), but subtitlers also put it on a man's "خذِ", so a
# kasra is read as neither. Left out: forms that are also a past tense or an
# "I ..." verb (اتصل "he called", أخبرني "he told me", أخرج "I go out"); the
# commonest of those count only as a whole utterance opening a subtitle line
# or a dash turn ("توقف!", "أحب إصبعك - توقف -"); "قلت له: توقف." is
# reported speech.
_AR_MARKS = u'[\\s\u200e\u200f\u202a-\u202e]*'
_AR_LINE_START = u'(?:^|\n|\\s-)' + _AR_MARKS + u'(?:-' + _AR_MARKS + u')?'
_AR_IMP_M = re.compile(
    _AR_START + u'(?:و|ف)?' + _ar_words((u'تعال', u'قل', u'خذ', u'دعني', u'دعنا'))
    + u'(?![\u0621-\u064a\u0650])'
    u'|' + _AR_CLAUSE + u'(?:و|ف)?' + _ar_words((
        u'انظر', u'إنظر', u'أنظر', u'اسمع', u'إسمع', u'اجلس', u'إجلس', u'اذهب',
        u'إذهب', u'ارجع', u'إرجع', u'اهدأ', u'إهدأ', u'اصمت',
        u'إصمت', u'اسكت', u'ابق', u'إبق', u'استرخ', u'اخرج',
        u'ادخل', u'صدقني',
        u'أعطني', u'اعطني', u'اتركني', u'أرني', u'ارني', u'خذني', u'اسمعني',
        u'اركض', u'اهرب')) + u'(?![\u0621-\u064a\u0650])'
    u'|' + _AR_LINE_START + u'(?:و|ف)?' + _ar_words((
        u'توقف', u'انتظر', u'إنتظر', u'انتبه', u'إنتبه', u'تمهل', u'تحرك',
        u'استيقظ', u'أسرع', u'اسرع')) + u'(?![\u0621-\u064a\u0650])'
    + _AR_MARKS + u'[.!\u060c,\\-\u2026]')
# "أنت" + a second-person imperfect: the verb's own ending says which.
_AR_ANTA = (_AR_START + u'(?:أ|هل\\s+|و|ف)?(?:أنت|انت)[\u064b-\u0652]*\\s+'
            u'(?:(?:لا|لم|لن|لست|لازلت|فعلاً|فعلا|حقاً|حقا|فقط|دائماً|دائما)\\s+)?')
_AR_ANTA_VERB = re.compile(_AR_ANTA + u'(ت[' + _AR_L + u']{2,9})' + _AR_END)
_AR_CLITICS = (u'هما', u'ني', u'ها', u'هم', u'هن', u'نا', u'كم', u'ه', u'ك')
# t- words after أنت that are not a second-person verb: an adjective or noun
# (ة, tanween), a past tense (ت, also before an object: تركتني), and a few
# frequent function words. ى stays: ترى / تنسى are second-person verbs.
_AR_NOT_IMPERFECT = (u'ة', u'ت', u'ا', u'\u064b', u'\u064c', u'\u064d')
_AR_T_NOT_VERBS = frozenset((u'تلك', u'تحت', u'تماما', u'تقريبا', u'تحديدا',
                             u'تماماً', u'تقريباً', u'تحديداً', u'تاريخ', u'تجربة'))
# ... or + an adjective from the speaker list and a few more (ة = feminine).
_AR_ADDR_ADJ = _ar_words(_AR_SPEAKER_ADJ + (
    u'جميل', u'وسيم', u'غبي', u'ذكي', u'مجنون', u'رائع', u'مجبر', u'مضحك',
    u'لطيف', u'محظوظ', u'متأخر', u'مرتاح', u'مستيقظ', u'متوتر'))
_AR_ANTA_ADJ_F = re.compile(_AR_ANTA + _AR_ADDR_ADJ + u'ة' + _AR_END)
_AR_ANTA_ADJ_M = re.compile(_AR_ANTA + _AR_ADDR_ADJ + u'(?:اً|ًا|ا)?' + _AR_END)
# "تبدو" + a masculine accusative adjective (the feminine says تبدين). تبدو
# is also "she looks", so only an adjective with written tanween counts
# ("تبدو جميلاً"); an adverb wears it too ("تبدو تماماً مثل أمها").
_AR_YOU_LOOK_M = re.compile(_AR_START + u'تبدو\\s+' + _AR_ADDR_ADJ + u'(?:اً|ًا)' + _AR_END)
# Vocatives. A bare endearment counts only after a comma ("أمابيلا، عزيزتي
# هل ...") or as a clause of its own ("عزيزي، اسمع"): "حبيبتي تركتني" and
# "تركتني حبيبتي." are "my girlfriend left me", somebody else. "ابنتي" and
# "صديقي" read as "my daughter / my friend" too often; they count after يا.
_AR_AFTER_COMMA = u'[\u060c,]\\s*'
_AR_VSEP_END = u'\\s*(?:[.!?\u061f\u060c,:\\-\u2026"]|$)'
_AR_VOC_F_BARE = _ar_words((u'عزيزتي', u'حبيبتي', u'صغيرتي', u'سيدتي', u'آنستي'))
_AR_VOC_M_BARE = _ar_words((u'عزيزي', u'حبيبي', u'سيدي'))
_AR_VOC_F = re.compile(
    _AR_START + u'يا\\s+' + _ar_words((
        u'فتاة', u'امرأة', u'سيدة', u'آنسة', u'أمي', u'امي', u'صديقتي', u'عزيزتي',
        u'حبيبتي', u'ابنتي', u'سيدتي', u'أختي', u'اختي', u'جميلة')) + _AR_END
    + u'|' + _AR_AFTER_COMMA + _AR_VOC_F_BARE + _AR_END
    + u'|' + _AR_CLAUSE + _AR_VOC_F_BARE + _AR_VSEP_END)
_AR_VOC_M = re.compile(
    _AR_START + u'يا\\s+' + _ar_words((
        u'رجل', u'صاح', u'سيدي', u'أبي', u'ابي', u'بني', u'فتى', u'صديقي', u'عزيزي',
        u'حبيبي', u'أخي', u'اخي')) + _AR_END
    + u'|' + _AR_AFTER_COMMA + _AR_VOC_M_BARE + _AR_END
    + u'|' + _AR_CLAUSE + _AR_VOC_M_BARE + _AR_VSEP_END)
# A question: هل + a t-imperfect, or the a- question prefix on a verb whose
# own first person is not a+t ("أتعرف" asks, "أتفق" is "I agree"; أتفهم is
# also "I understand", أتعرف على "I get to know"). The same
# t- form is also "she ..."; measured, it reads as "you" in questions. "هل
# تمزح معي" is an idiom subtitlers write in the masculine to anyone.
_AR_QUESTION = re.compile(
    u'(?:' + _AR_START + u'هل\\s+(?:لا\\s+)?(?!تمزح)(ت[' + _AR_L + u']{2,7})|'
    + _AR_START + u'[وف]?أ(' + u'|'.join((
        u'تعرف(?!\\s+عل)', u'تعتقد', u'تريد', u'تحب', u'تظن', u'تسمع', u'ترى',
        u'تقصد', u'تعني', u'تشعر', u'تود', u'ترغب', u'تقول', u'تستطيع', u'تمانع',
        u'تعمل', u'تعيش', u'تبحث', u'تنتظر', u'تصدق', u'تثق', u'تحاول', u'تملك'))
    + u')' + _AR_CLITIC + u')(?![\u0621-\u064a\u064b-\u0652])')


def _ar_strip_clitic(word):
    for c in _AR_CLITICS:
        if len(word) > len(c) + 3 and word.endswith(c):
            return word[:-len(c)]
    return word


def _ar_verb_gender(word):
    """'F'/'M'/None for a bare second-person imperfect (clitic stripped)."""
    word = _ar_strip_clitic(word)
    if word.endswith(u'ين'):
        return 'F'
    # ي ends a defective verb in both genders (تمشي); ون/ان/وا are plural/dual.
    if word.endswith((u'ي', u'ون', u'ان', u'وا')):
        return None
    return 'M'


def _ar_more_addressee(text, signal_text):
    """(feminine, masculine) addressee evidence from the forms above."""
    f = bool(_AR_2FS_PREFIXED.search(signal_text) or _AR_2FS_SHORT.search(text)
             or _AR_2FS_SUBJ.search(text) or _AR_IMP_F.search(text)
             or _AR_VOC_F.search(text))
    m = bool(_AR_IMP_M.search(text) or _AR_YOU_LOOK_M.search(text)
             or _AR_VOC_M.search(text))
    for mt in _AR_ANTA_VERB.finditer(text):
        word = mt.group(1)
        bare = _ar_strip_clitic(word)
        if word in _AR_T_NOT_VERBS or bare.endswith(_AR_NOT_IMPERFECT):
            continue          # تعيسة, تحت, تماماً ... or a past tense (تركتني)
        g = _ar_verb_gender(word)
        f, m = f or g == 'F', m or g == 'M'
    if _AR_ANTA_ADJ_F.search(text):
        f = True
    elif _AR_ANTA_ADJ_M.search(text):
        m = True
    for mt in _AR_QUESTION.finditer(text):
        if mt.group(2):
            m = True
            continue
        word = _ar_strip_clitic(mt.group(1))
        if word.endswith((u'ت', u'تم', u'تن', u'ن')) and not word.endswith(u'ين'):
            continue          # a past tense (تحققت) or a plural (تعرفن)
        g = _ar_verb_gender(word)
        f, m = f or g == 'F', m or g == 'M'
    return f, m


# The speaker: "أنا" plus the clitic forms (فأنا, إنني, لكني ...) and a longer
# reviewed adjective list; and "آسفة"/"آسف" opening a clause -- an apology is
# the speaker's own.
_AR_ME_MORE = (_AR_START + u'(?:[وف]?(?:أنا|انا)|[وف]?لست|إنني|انني|إني|أنني|أني|اني|'
               u'لأنني|لأني|لكنني|لكني|فإنني)\\s+(?:(?:جداً|جدا|حقاً|حقا|فعلاً|فعلا|لست)\\s+)?')
_AR_ME_ADJ = _ar_words(_AR_SPEAKER_ADJ + (
    u'ذاهب', u'قادم', u'واثق', u'متوتر', u'مرتبك', u'مستيقظ', u'عائد', u'متحمس',
    u'مستعجل', u'ممتن', u'محرج', u'جاد', u'مجنون', u'غبي', u'مرتاح', u'مسؤول',
    u'متردد', u'مهتم', u'مصدوم', u'متفاجئ', u'متأخر'))
_AR_ME_F = re.compile(_AR_ME_MORE + _AR_ME_ADJ + u'ة' + _AR_END
                      + u'|' + _AR_CLAUSE + u'(?:آسفة|متأسفة)' + _AR_END)
_AR_ME_M = re.compile(_AR_ME_MORE + _AR_ME_ADJ + u'(?:اً|ًا|ا)?' + _AR_END
                      + u'|' + _AR_CLAUSE + u'(?:آسف|متأسف)' + _AR_END)


_SLAVIC_ME = u'(?<![а-яёії])я\\s+(?:не\\s+)?'
_SLAVIC_SPEAKER_F = re.compile(
    _SLAVIC_ME + u'(?:[а-яёії]{2,}ла|уверена|'
    u'рада|готова|должна)'
    u'(?![а-яёії])', re.I)
_SLAVIC_SPEAKER_M = re.compile(
    _SLAVIC_ME + u'(?:[а-яёії]{2,}л|уверен|'
    u'рад|готов|должен)'
    u'(?![а-яёії])', re.I)


# The same first-person reading for the rest of the chain, only where the
# ending itself carries person AND gender -- the counterpart of
# _ADDRESSEE_MARKERS. Polish -łam/-łem is anchored to "ja", a negation or the
# line start, because instrumental nouns end the same way ("przed stołem",
# "całym ciałem"); "zdołam" is a future, not a past. Portuguese thanks agree
# with the speaker. Spanish/Italian/French adjectives stay out for the reason
# given above _ADDRESSEE_MARKERS' callers: a feminine noun looks the same.
_PL_ANCHOR = r'(?:^|[.!?\-]\s*|\b(?:ja|nie|już|też|tylko|właśnie|zawsze|nigdy|nawet)\s+)'
_SPEAKER_MARKERS = {
    'pl': (_rx(_PL_ANCHOR + r'(?!zdołam\b|podołam\b)\w{2,}łam\b',
               r'\bjestem\s+(?:pewna|gotowa|zmęczona|szczęśliwa|wdzięczna)\b'),
           _rx(_PL_ANCHOR + r'\w{2,}łem\b',
               r'\bjestem\s+(?:pewien|pewny|gotowy|zmęczony|szczęśliwy|wdzięczny)\b')),
    'cs': (_rx(r'\b\w+la\s+jsem\b', r'\bjsem\s+\w+la\b'),
           _rx(r'\b\w+l\s+jsem\b', r'\bjsem\s+\w+l\b')),
    'sk': (_rx(r'\b\w+la\s+som\b', r'\bsom\s+\w+la\b'),
           _rx(r'\b\w+l\s+som\b', r'\bsom\s+\w+l\b')),
    'sr': (_rx(r'\b\w+la\s+sam\b', r'\bsam\s+\w+la\b'),
           _rx(r'\b\w+(?:ao|io)\s+sam\b', r'\bsam\s+\w+(?:ao|io)\b')),
    'hr': (_rx(r'\b\w+la\s+sam\b', r'\bsam\s+\w+la\b'),
           _rx(r'\b\w+(?:ao|io)\s+sam\b', r'\bsam\s+\w+(?:ao|io)\b')),
    # Thanks only: at the start of a clause or after "muito". As a participle
    # ("ela foi obrigada", she was forced) it is about somebody else.
    'pt': (_rx(r'(?:^|[.!?,;:"\-]\s*|\bmuit[oí]ssimo\s+|\bmuito\s+)obrigada\b'),
           _rx(r'(?:^|[.!?,;:"\-]\s*|\bmuit[oí]ssimo\s+|\bmuito\s+)obrigado\b')),
}


def reference_speaker_gender(ref_text, lang):
    """'F', 'M' or None: the speaker's gender in a non-Hebrew reference line."""
    if not ref_text:
        return None
    try:
        ref_text = _visible(ref_text)
        if lang == 'ar':
            f = bool(_AR_SPEAKER_F.search(ref_text) or _AR_ME_F.search(ref_text))
            m = bool(_AR_SPEAKER_M.search(ref_text) or _AR_ME_M.search(ref_text))
        elif lang in ('ru', 'uk'):
            f = bool(_SLAVIC_SPEAKER_F.search(ref_text))
            m = bool(_SLAVIC_SPEAKER_M.search(ref_text))
        elif lang in _SPEAKER_MARKERS:
            fem_pats, masc_pats = _SPEAKER_MARKERS[lang]
            f = any(p.search(ref_text) for p in fem_pats)
            m = any(p.search(ref_text) for p in masc_pats)
        else:
            return None
        if f != m:
            return 'F' if f else 'M'
    except Exception:
        pass
    return None


_GG = []


def _gg():
    """gender_guard, as a package module or (standalone load) its file."""
    if _GG:
        return _GG[0]
    mod = None
    try:
        from resources.lib import gender_guard as mod
    except Exception:
        try:
            import importlib.util
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'gender_guard.py')
            spec = importlib.util.spec_from_file_location('gender_guard', path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception:
            mod = None
    _GG.append(mod)
    return mod


_HPG = []


def _hpg():
    """he_person_gender, as a package module or (standalone load) its file."""
    if _HPG:
        return _HPG[0]
    mod = None
    try:
        from resources.lib import he_person_gender as mod
    except Exception:
        try:
            import importlib.util
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'he_person_gender.py')
            spec = importlib.util.spec_from_file_location('he_person_gender', path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception:
            mod = None
    _HPG.append(mod)
    return mod


_SLASH_FORM = re.compile(u'[\u05d0-\u05ea]/[\u05d0-\u05ea]')


def person_roles_fixed(body, roles, ref_text=None):
    """True when a rewritten line provably carries the required genders.

    roles: [(role, 'F'|'M')]. Speaker roles need positive proof from the
    person-form reader -- or, given the HEBREW reference line, the
    reference's own word for that person. An addressee role also passes on
    the older rule -- the opposite address form is gone and nothing reads
    as the opposite -- because the older check flags forms outside that
    reader's lexicon.
    """
    # Both forms at once ("תוכל/י") is a hedge, not a choice -- measured
    # in a repair the older addressee rule below let through.
    if _SLASH_FORM.search(body or ''):
        return False
    hpg = _hpg()
    if hpg is not None and hpg.fixed(body, roles, ref_text):
        return True
    # With the Hebrew reference at hand, a rewrite that still contradicts it
    # for the role is no fix -- measured: only the verb changed and
    # "את-את נראה נחמד" kept the feminine pronoun.
    if hpg is not None and ref_text:
        try:
            left = set(r for r, _g in hpg.conflicts(body, ref_text))
        except Exception:
            left = set()
        if any(role in left for role, _gender in roles):
            return False
    for role, gender in roles:
        if role != 'addressee':
            return False
        if (addresses_male(body) if gender == 'F' else addresses_female(body)):
            return False
        if hpg is not None:
            seen = [t['addressee'] for t in hpg.read(body) if t['addressee']]
            if any(g != gender for g in seen):
                return False
    return True


def person_gender_conflicts(blocks, ref_map, lang):
    """{entry_number: [(role, reference_gender)]} where the Hebrew output
    contradicts the human reference about the SPEAKER or the ADDRESSEE.

    A Hebrew reference is compared word for word (he_person_gender.conflicts);
    any other language is read for its own speaker/addressee marking and
    compared with what the Hebrew line says, single-speaker lines only.
    Unknown on either side is never a conflict. Never raises.
    """
    out = {}
    if not ref_map:
        return out
    hpg = _hpg()
    if hpg is None:
        return out
    for block in blocks:
        try:
            lines = block.split('\n')
            if len(lines) < 3 or not lines[0].strip().isdigit():
                continue
            num = int(lines[0].strip())
            ref = ref_map.get(num)
            if not ref:
                continue
            body = '\n'.join(lines[2:])
            if lang == 'he':
                found = hpg.conflicts(body, ref)
            else:
                turns = hpg.read(body)
                if len(turns) != 1:
                    continue
                found = []
                for role, want in (
                        ('speaker', reference_speaker_gender(ref, lang)),
                        ('addressee', reference_addressee_gender(ref, lang))):
                    if want and turns[0][role] and turns[0][role] != want:
                        found.append((role, want))
            if found:
                out[num] = found
        except Exception:
            continue
    return out


def addresses_female(text):
    """Conservative feminine-address candidate; not speaker/referent identity."""
    return _he_addresses_female(_visible(text))


def addresses_male(text):
    """True when `text` contains the Hebrew masculine second-person pronoun.

    Public because the repair pass has to PROVE a rewrite actually fixed the
    error before it accepts it -- a replacement that still says the same thing
    is not a repair, and swapping one wrong line for another wrong line would
    spend a request to stand still.
    """
    try:
        return bool(_HE_MASC.search(_visible(text)))
    except Exception:
        return False


def wrong_gender_entries(blocks, ref_map, lang, both_directions=False):
    """Conservative addressee-conflict candidates. Legacy default is F-only.
    The production repair opts into both directions and declines mixed M/F
    output; source context must still be checked by the repair. Never raises."""
    out = []
    if not ref_map:
        return out
    try:
        for block in blocks:
            lines = block.split('\n')
            if len(lines) < 3 or not lines[0].strip().isdigit():
                continue
            num = int(lines[0].strip())
            ref = ref_map.get(num)
            if not ref:
                continue
            target=reference_addressee_gender(ref, lang)
            body='\n'.join(lines[2:])
            male=addresses_male(body);female=_he_addresses_female(body)
            if target=='F' and male and (not both_directions or not female):
                out.append(num)
            elif both_directions and target=='M' and female and not male:
                out.append(num)
    except Exception as e:
        _log('gender verification crashed: {0}'.format(e), level='WARNING')
    return out


def begin(info, src_text, timing_text=None):
    """ENTRY POINT (lazy). When the feature is on, find gender-reference
    candidates for `info` and return a ReferencePlan that yields aligned maps in
    PRIORITY-CHAIN order (Hebrew, Arabic, then the other gender-marking
    languages -- see _REF_CHAIN), ONE language per .next() call, downloading
    lazily. Returns (plan, diag). `plan` is None when there is no candidate at
    all (diag.reason = 'crash'/'no_source'/'no_arabic'); otherwise call
    plan.next() to pull the primary (and, later, fallback) references. Fully
    guarded; never raises."""
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
    #
    # GUARDED because the docstring promises it. Everything from here down used
    # to sit outside every handler, so a candidate the source engine handed back
    # in an unexpected shape -- a bare string, or one whose 'language' is a list
    # -- left this function as an AttributeError. The single caller does wrap the
    # call, so the user outcome was always the correct silent fallback; but a
    # module documented as never raising has to actually never raise, or the next
    # caller inherits a promise the code does not keep.
    by_lang = {}
    try:
        for c in all_cands:
            lang = _chain_lang_of(c)
            if lang and len(by_lang.setdefault(lang, [])) < _PER_LANG_LIMIT:
                by_lang[lang].append(c)
    except Exception as e:
        _log('bucketing crashed: {0}'.format(e), level='WARNING')
        return None, {'reason': 'crash'}

    # NOTE on Hebrew-first: the user reached AI translation, so any Hebrew sub
    # here is out-of-sync / unmatched for their release -- but as a GENDER
    # ORACLE it only needs to time-align to the SOURCE sub, which the scale+
    # offset estimator handles. It is the strongest oracle (it IS Hebrew).
    #
    # ROUND-ROBIN WITHIN A TIER, tiers in order.
    #
    # Two different things have to be true at once, and each one alone gets
    # the other wrong.
    #
    # 1. A STRONG oracle must win even from deep in its own list. Hebrew and
    #    Arabic are not merely first in the chain, they are a different class:
    #    Hebrew IS the target language, and Arabic marks addressee gender with
    #    explicit diacritics that map almost one-to-one onto Hebrew (the block
    #    built around it lifted gender accuracy from ~27% to ~90%+). The third
    #    Arabic candidate is worth far more than the first Slovak one. A flat
    #    round-robin does not know that: it takes whatever aligns first, so a
    #    weak language's opening candidate beats a strong language's third.
    #
    # 2. A strong oracle must be REACHED. The old order walked one language at
    #    a time, so ten Hebrew candidates came before the first Arabic one --
    #    and since the deadline is spent on downloads, the chain could stop
    #    before Arabic was tried at all, leaving the job with no oracle and a
    #    translation that defaults to masculine.
    #
    # Tiers give both. Inside tier 1 the two strong languages alternate, so
    # Arabic is attempt 2 rather than attempt 11; and tier 1 is exhausted
    # completely before tier 2 is touched, so no weaker language can take a
    # job away from an Arabic candidate that would have aligned. Within tier 2
    # the languages are close enough in value that reaching ANY of them
    # matters more than which, so they alternate too.
    ordered = []
    for tier in _REF_TIERS:
        depth = max([len(by_lang.get(l, ())) for l in tier] or [0])
        ordered.extend(
            (lang, by_lang[lang][i])
            for i in range(depth)
            for lang in tier
            if i < len(by_lang.get(lang, ())))
    if not ordered:
        _log('no gender-reference candidates in any chain language -> normal '
             'translation (fallback)')
        return None, {'reason': 'no_arabic', 'cands': 0}

    total = len(ordered)
    langs_present = [l for l in _REF_CHAIN if l in by_lang]
    _log('reference candidates: {0} across {1}'.format(
        total, ','.join(langs_present)))
    return (ReferencePlan(src_text, src_blocks, ordered, total,
                          timing_text=timing_text),
            {'reason': 'pending', 'cands': total})


def prepare(info, src_text):
    """Back-compat single-shot entry point (used where only the primary
    reference is needed). Returns (map, diag) -- identical semantics to the
    original: map is the primary aligned reference (or None), diag.reason is
    'ok'/'no_source'/'no_arabic'/'no_align'/'crash', and diag['lang'] is the
    chain code used on success. Implemented over begin()+plan.next()."""
    plan, diag = begin(info, src_text)
    if plan is None:
        return None, diag
    lang, mapping = plan.next()
    cands = diag.get('cands', 0)
    if mapping is None:
        _log('all {0} reference candidate(s) failed alignment -> normal '
             'translation (fallback)'.format(cands))
        return None, {'reason': 'no_align', 'cands': cands,
                      'diag': plan.last_diag}
    return mapping, {'reason': 'ok', 'cands': cands, 'hinted': len(mapping),
                     'diag': plan.last_diag, 'lang': lang}
