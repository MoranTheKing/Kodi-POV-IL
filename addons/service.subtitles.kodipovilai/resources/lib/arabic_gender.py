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
    # Confidence gate. The MAP must be trustworthy (right framerate band + a
    # strong offset vote), but COVERAGE may be partial: as a gender ORACLE, a
    # reference that overlaps 65-79% of the source still hints gender for most
    # entries -- strictly better than no reference (the un-hinted entries simply
    # translate without a hint, exactly as if there were none). Field data (the
    # D1 no_align overlap distribution) showed ~65% of rejections sat in this
    # 65-79% band WITH a correct map, so the old 0.80 coverage floor was throwing
    # away usable oracles. vote>=0.65 + the framerate band stay the real guards
    # against a spurious alignment (a random pairing votes ~0.30).
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

    def __init__(self, src_text, src_blocks, ordered, total):
        self._src_text = src_text
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
                                'reference [{0}] {1} -> {2} entries hinted'
                                .format(lang, diag, len(mapping)))
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
_AR_FEM = tuple(re.compile(p) for p in (
    u'\u0623\u0646\u062a\u0650', u'\u0644\u0643\u0650', u'\u0628\u0643\u0650', u'\u0639\u0644\u064a\u0643\u0650', u'\u0645\u0639\u0643\u0650', u'\u0625\u0644\u064a\u0643\u0650', u'\u0645\u0646\u0643\u0650',
    u'\u0643\u0650\\s', u'\u0643\u0650$', u'\u062a\u0650\\s', u'\u062a\u0650$', u'\u064a\u0627 \u0633\u064a\u062f\u062a\u064a',
))
_AR_MASC = tuple(re.compile(p) for p in (
    u'\u0623\u0646\u062a\u064e', u'\u0644\u0643\u064e', u'\u0628\u0643\u064e', u'\u0639\u0644\u064a\u0643\u064e', u'\u0645\u0639\u0643\u064e', u'\u0625\u0644\u064a\u0643\u064e', u'\u0645\u0646\u0643\u064e',
    u'\u0643\u064e\\s', u'\u0643\u064e$', u'\u062a\u064e\\s', u'\u062a\u064e$',
))
# Hebrew reference: read the pronoun straight off it.
_HE_REF_FEM = re.compile(u'(?<![\u05d0-\u05ea])\u05d0\u05ea(?![\u05d0-\u05ea])(?!\\s*\u05d4)')
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


def reference_addressee_gender(ref_text, lang):
    """'F', 'M', or None when the reference does not mark it unambiguously.

    Only 'ar' and 'he' are read. They are the top two of the chain and cover
    almost every job; for any other language this returns None, so the
    verification pass simply does not fire rather than guessing from a
    language whose marking has not been validated here.
    """
    if not ref_text:
        return None
    try:
        if lang == 'he':
            f = bool(_HE_REF_FEM.search(ref_text))
            m = bool(_HE_MASC.search(ref_text))
        elif lang == 'ar':
            f = any(p.search(ref_text) for p in _AR_FEM)
            m = any(p.search(ref_text) for p in _AR_MASC)
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


def addresses_male(text):
    """True when `text` contains the Hebrew masculine second-person pronoun.

    Public because the repair pass has to PROVE a rewrite actually fixed the
    error before it accepts it -- a replacement that still says the same thing
    is not a repair, and swapping one wrong line for another wrong line would
    spend a request to stand still.
    """
    try:
        return bool(_HE_MASC.search(text or ''))
    except Exception:
        return False


def wrong_gender_entries(blocks, ref_map, lang):
    """Entry numbers whose Hebrew addresses a man where the reference says the
    addressee is a woman. See the note above for why only this direction is
    reported. Never raises."""
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
            if reference_addressee_gender(ref, lang) != 'F':
                continue
            if _HE_MASC.search('\n'.join(lines[2:])):
                out.append(num)
    except Exception as e:
        _log('gender verification crashed: {0}'.format(e), level='WARNING')
    return out


def begin(info, src_text):
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
    by_lang = {}
    for c in all_cands:
        lang = _chain_lang_of(c)
        if lang and len(by_lang.setdefault(lang, [])) < _PER_LANG_LIMIT:
            by_lang[lang].append(c)

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
    return (ReferencePlan(src_text, src_blocks, ordered, total),
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
