# SubSync Phase S1 -- the ONE structured release-name scorer.
#
# Replaces the three divergent difflib token scorers (subs_engine/engine.py's
# sort_subtitles, translate._match_pct, he_sub_match._score) so the subtitle
# picker %, the source-screen HEB badge and the autosub ordering all agree,
# and so the number actually reflects SYNC likelihood instead of raw token
# similarity:
#   - exact release           -> 100  (same file everywhere; synced)
#   - same group + source     -> ~90+ (de-facto synced in practice)
#   - same source class only  -> mid  (often synced, not guaranteed)
#   - cross source class      -> CAPPED LOW (WEB vs BluRay drifts by minutes;
#     the old scorer happily gave these 60-75% on token overlap alone)
#   - different edition/PROPER-> capped (different cut / re-release)
#
# Self-contained ON PURPOSE (like he_sub_match): POV imports our modules by
# path with only resources/lib on sys.path, so NO package-relative imports,
# no xbmc, no PTN. Pure stdlib. Deterministic on every surface.

import os
import re
import difflib

# Tiers, strongest first. score() returns (pct, tier, reasons).
TIER_EXACT = 'exact'      # normalized names identical
TIER_GROUP = 'group'      # same release group + same source class
TIER_SOURCE = 'source'    # same source class, group unknown/different
TIER_FUZZY = 'fuzzy'      # token similarity only (source unknown somewhere)
TIER_CROSS = 'cross'      # contradicting source class / edition / proper

# Tiers safe for AUTOMATIC pick without further verification (S2 will verify
# / retime the rest against a timing oracle).
AUTO_OK_TIERS = (TIER_EXACT, TIER_GROUP)

_SEPS = re.compile(r'[\s_+/\-]+')
_EXT_RE = re.compile(
    r'\.(mkv|mp4|m4p|m4v|avi|mov|mpe?g|flv|wmv|webm|3gp|ogg|ogv|rmvb|divx|vob'
    r'|dat|mts|m2ts|ts|yuv|srt|str|sub|sup|idx|ass|ssa|vtt|smi)$', re.I)

_RES_MAP = {
    '4k': '2160p', 'uhd': '2160p', '2160': '2160p',
    '1080': '1080p', '720': '720p', '480': '480p', '576': '576p',
}
_RES_RE = re.compile(r'\b(2160p|1080p|720p|576p|480p|4k|uhd)\b', re.I)

# Source classes. Order matters only for readability; detection is by token.
_SOURCE_CLASSES = (
    ('bluray', ('bluray', 'blueray', 'bdrip', 'brrip', 'brip', 'bdremux',
                'bd25', 'bd50', 'bd66', 'bd100', 'remux')),
    ('web', ('web', 'webdl', 'webrip', 'webhd', 'webdlrip')),
    ('hdtv', ('hdtv', 'hdtvrip', 'pdtv', 'sdtv', 'tvrip', 'dsr')),
    ('dvd', ('dvdrip', 'dvdr', 'dvd', 'dvdfull')),
    ('hdrip', ('hdrip',)),
    ('cam', ('cam', 'hdcam', 'camrip', 'ts', 'hdts', 'telesync', 'tc',
             'telecine', 'screener', 'scr', 'dvdscr', 'dvdscreener')),
)

_EDITION_TOKENS = {
    'extended': 'extended', 'uncut': 'extended', 'unrated': 'unrated',
    'theatrical': 'theatrical', 'imax': 'imax', 'remastered': 'remastered',
    'directors': 'directors', 'dircut': 'directors', 'dc': None,  # ambiguous
}
_PROPER_TOKENS = ('proper', 'repack', 'rerip')

_CODEC_MAP = {
    'x264': 'h264', 'h264': 'h264', 'avc': 'h264', 'h': None,
    'x265': 'h265', 'h265': 'h265', 'hevc': 'h265',
    'av1': 'av1', 'xvid': 'xvid', 'divx': 'xvid',
}

# Tokens that are never a release group even when trailing after '-'.
_NOT_GROUP = set(
    t for _cls, toks in _SOURCE_CLASSES for t in toks
) | set(_PROPER_TOKENS) | set(_CODEC_MAP) | set(_RES_MAP) | {
    '2160p', '1080p', '720p', '576p', '480p', 'hdr', 'hdr10', 'dv', 'dovi',
    'sdr', 'atmos', 'ddp', 'dd', 'dts', 'ac3', 'eac3', 'aac', 'truehd',
    'multi', 'dual', 'audio', 'heb', 'hebrew', 'eng', 'english', 'subbed',
    'hebsub', 'hebsubs', '10bit', '8bit', 'hc', 'internal', 'complete',
}


# PRECOMPUTED ONCE, not per call. parse() used to build seven sets on every
# invocation -- one per source class plus the PROPER set -- and it is called
# twice for every scored pair. See the memo note below for why that mattered.
_SOURCE_SETS = tuple((cls, frozenset(toks)) for cls, toks in _SOURCE_CLASSES)
_PROPER_SET = frozenset(_PROPER_TOKENS)
_DOTS_RE = re.compile(r'\.+')
_GROUP_RE = re.compile(r'[a-z0-9]+')

# MEMOISED BECAUSE THE CALLER'S SHAPE IS QUADRATIC AND CANNOT EASILY STOP
# BEING SO. POV's source window scores every row against every available
# Hebrew subtitle name: seventy rows against seventeen names is 1190 scored
# pairs, and each pair re-derived the same seventeen names from scratch. A
# field log from a webOS TV showed ten seconds between the scrape finishing
# and the list appearing, scaling almost exactly with the NUMBER OF NAMES --
# three names took two seconds, six took four, seventeen took ten.
#
# Keyed on the raw string, so a name is normalised, tokenised and parsed once
# per interpreter no matter how many rows it is compared against. Bounded and
# cleared wholesale on overflow: this runs inside POV's own long-lived
# interpreter (reuselanguageinvoker), so an unbounded dict here is a leak in
# somebody else's process.
_MEMO_CAP = 4096
_NORM_MEMO = {}
_TOKS_MEMO = {}
_PARSE_MEMO = {}


def _memo_put(cache, key, value):
    if len(cache) >= _MEMO_CAP:
        cache.clear()
    cache[key] = value
    return value


def _strip_ext(name):
    return _EXT_RE.sub('', (name or '').strip())


def _normalize(name):
    s = _strip_ext(name).lower()
    s = _SEPS.sub('.', s)
    return _DOTS_RE.sub('.', s).strip('.')


def normalize(name):
    """Canonical comparison form: lowercase, extension stripped, all
    separators collapsed to single dots."""
    if not isinstance(name, str):
        return _normalize(name)
    cached = _NORM_MEMO.get(name)
    if cached is None:
        cached = _memo_put(_NORM_MEMO, name, _normalize(name))
    return cached


def _toks(name):
    """The token TUPLE, cached. Internal callers use this directly; the
    public tokens() hands out a fresh list so nobody can mutate the cache."""
    if not isinstance(name, str):
        return tuple(t for t in normalize(name).split('.') if t)
    cached = _TOKS_MEMO.get(name)
    if cached is None:
        cached = _memo_put(
            _TOKS_MEMO, name,
            tuple(t for t in normalize(name).split('.') if t))
    return cached


def tokens(name):
    return list(_toks(name))


def _parse(name):
    toks = _toks(name)
    tokset = set(toks)
    out = {'resolution': '', 'source': '', 'group': '', 'codec': '',
           'edition': '', 'proper': False}

    m = _RES_RE.search(normalize(name))
    if m:
        r = m.group(1).lower()
        out['resolution'] = _RES_MAP.get(r, r if r.endswith('p') else '')

    for cls, cls_tokens in _SOURCE_SETS:
        if tokset & cls_tokens:
            out['source'] = cls
            break
    # 'web' + 'dl'/'rip' appear as separate tokens after normalization;
    # the plain 'web' token above already catches them.

    for i, t in enumerate(toks):
        c = _CODEC_MAP.get(t)
        if c:
            out['codec'] = c
            break
        # Split forms: 'H.264' / 'x 265' normalize to two tokens ('h','264').
        if t in ('h', 'x') and i + 1 < len(toks) and toks[i + 1] in ('264', '265'):
            out['codec'] = 'h' + toks[i + 1]
            break

    for t in toks:
        e = _EDITION_TOKENS.get(t)
        if e:
            out['edition'] = e
            break

    out['proper'] = bool(tokset & _PROPER_SET)

    # Group: the token after the LAST '-' in the raw name (scene convention
    # "...-NTb"), if it isn't a known technical tag. Fall back to the last
    # normalized token under the same filter.
    raw = _strip_ext(name)
    cand = ''
    if '-' in raw:
        cand = raw.rsplit('-', 1)[1].strip()
        cand = _SEPS.sub('.', cand.lower()).split('.')[0]
    if not cand and toks:
        cand = toks[-1]
    if (cand and cand not in _NOT_GROUP and not cand.isdigit()
            and 2 <= len(cand) <= 20 and _GROUP_RE.fullmatch(cand)):
        out['group'] = cand
    return out


def _parse_c(name):
    """The cached dict itself. Internal, READ-ONLY callers only."""
    if not isinstance(name, str):
        return _parse(name)
    cached = _PARSE_MEMO.get(name)
    if cached is None:
        cached = _memo_put(_PARSE_MEMO, name, _parse(name))
    return cached


def parse(name):
    """Structured fields out of a release name. Every field may be '' when
    not present -- callers must treat '' as UNKNOWN, never as a mismatch.

    A COPY of the cached dict: the cache is shared across every caller in the
    process, and one caller assigning into the result would silently rewrite
    what every other caller sees. Nothing does that today; the copy is what
    keeps that true."""
    return dict(_parse_c(name))


def _token_ratio(a_tokens, b_tokens):
    if not a_tokens or not b_tokens:
        return 0.0
    try:
        return difflib.SequenceMatcher(None, a_tokens, b_tokens).ratio()
    except Exception:
        return 0.0


_SCORE_MEMO = {}


def score(video_name, sub_name):
    """Structured match: (pct 0-100, tier, reasons list). Either name empty
    -> (0, TIER_FUZZY, []).

    The pair is memoised as well as its two halves, because the same release
    routinely appears in a source list several times over -- one row per host
    offering it -- and each of those rows is scored against the same list of
    subtitle names. The reasons list is copied out, for the same reason parse()
    copies its dict."""
    if not (video_name or '').strip() or not (sub_name or '').strip():
        return 0, TIER_FUZZY, []

    memo_key = None
    if isinstance(video_name, str) and isinstance(sub_name, str):
        memo_key = (video_name, sub_name)
        hit = _SCORE_MEMO.get(memo_key)
        if hit is not None:
            return hit[0], hit[1], list(hit[2])

    pct, tier, reasons = _score(video_name, sub_name)
    if memo_key is not None:
        _memo_put(_SCORE_MEMO, memo_key, (pct, tier, tuple(reasons)))
    return pct, tier, reasons


def best_pct(video_name, sub_names, stop_at=100, floor=0):
    """max(match_pct(video_name, n) for n in sub_names), computed without
    doing work that cannot change the answer.

    EXACTLY EQUAL to the max it replaces when floor=0: a pair is skipped only
    when the branch it lands in provably cannot exceed the running maximum,
    and a skipped pair cannot be the maximum.

    `floor` starts that running maximum higher, for callers that only care
    whether anything clears a bar. floor=79 is the useful one: only the exact,
    containment and same-group branches can return 80 or more, and none of the
    three needs the token ratio -- so "does any of these releases carry a
    built-in Hebrew track" costs no difflib passes at all instead of one per
    candidate. Below the bar it returns 0 rather than the true maximum, which
    is what asking with a floor means."""
    # THE SAME EMPTY-NAME GUARD score() APPLIES, because this calls _score()
    # directly and _score() does not have it. Without this line a whitespace
    # name scored 10 here and 0 through match_pct -- caught by the randomised
    # equivalence test, which is the only reason it is not in the shipped
    # build: eight disagreements in seven hundred trials, all of them a blank.
    try:
        if not (video_name or '').strip():
            return 0
    except AttributeError:
        return 0
    best = 0 if floor <= 0 else floor
    seen_any = False
    for n in sub_names or []:
        try:
            if not (n or '').strip():
                continue
        except AttributeError:
            continue
        key = None
        if isinstance(video_name, str) and isinstance(n, str):
            key = (video_name, n)
            hit = _SCORE_MEMO.get(key)
            if hit is not None:
                seen_any = True
                if hit[0] > best:
                    best = hit[0]
                    if best >= stop_at:
                        break
                continue
        r = _score(video_name, n, floor=best)
        if r is None:
            continue
        seen_any = True
        if key is not None:
            _memo_put(_SCORE_MEMO, key, (r[0], r[1], tuple(r[2])))
        if r[0] > best:
            best = r[0]
            if best >= stop_at:
                break
    if not seen_any and floor <= 0:
        return 0
    return 0 if best <= floor else best


# The most a branch can ever return. Used ONLY to skip work that provably
# cannot change a maximum -- never to change what a branch returns. Each is
# read straight off the branch below it: min(25, ...), min(35, ...),
# min(40, ...); same-source tops out at 55+6+3+15 = 79 before its own cap; and
# fuzzy at 10 + 55 = 65.
_CEIL_EDITION = 25
_CEIL_SOURCE = 35
_CEIL_PROPER = 40
_CEIL_SAME_SOURCE = 79
_CEIL_FUZZY = 65


def _score(video_name, sub_name, floor=0):
    """The scorer. `floor` is a caller's running maximum: any branch that
    provably cannot exceed it returns None instead of finishing, and the token
    ratio -- a difflib pass, and by far the most expensive thing here -- is
    computed only if a branch that needs it is actually reached.

    None means "cannot beat `floor`", never "no match". Only best_pct() passes
    a floor; score() does not, so the public result is unchanged."""
    va, sa = normalize(video_name), normalize(sub_name)
    if va == sa:
        return 100, TIER_EXACT, ['identical release']

    v, s = _parse_c(video_name), _parse_c(sub_name)
    vt, st = _toks(video_name), _toks(sub_name)
    ratio = -1.0
    reasons = []

    # HARD contradictions first -- these caps are the whole point: the old
    # token scorer let a WEB sub score 70% against a BluRay source.
    if v['edition'] and s['edition'] and v['edition'] != s['edition']:
        if floor >= _CEIL_EDITION:
            return None
        ratio = _token_ratio(vt, st)
        pct = min(25, int(ratio * 40))
        return pct, TIER_CROSS, ['different edition/cut']
    if v['source'] and s['source'] and v['source'] != s['source']:
        if floor >= _CEIL_SOURCE:
            return None
        ratio = _token_ratio(vt, st)
        pct = min(35, int(ratio * 45))
        return pct, TIER_CROSS, [
            'source mismatch ({0} vs {1})'.format(v['source'], s['source'])]
    if v['proper'] != s['proper'] and (v['source'] and s['source']):
        if floor >= _CEIL_PROPER:
            return None
        ratio = _token_ratio(vt, st)
        pct = min(40, int(ratio * 55))
        return pct, TIER_CROSS, ['PROPER/REPACK mismatch']

    same_source = bool(v['source'] and s['source'])  # equal if both set here
    same_group = bool(v['group'] and s['group'] and v['group'] == s['group'])

    # Containment: one normalized name fully inside the other (after the
    # contradiction guards above). Covers provider-decorated variants of the
    # SAME release ("...ColdFilm" vs "...ColdFilm.rus"). Requires the shorter
    # side to be a real identity (enough tokens + some structural field).
    shorter, longer = (va, sa) if len(va) <= len(sa) else (sa, va)
    if shorter in longer:
        sp = v if shorter == va else s
        if (len(shorter.split('.')) >= 4
                and (sp['group'] or sp['source'] or sp['resolution'])):
            return 96, TIER_GROUP, ['release name contained']

    if same_group:
        # Same release group is the strongest identity signal. With the same
        # source class it's a near-certain sync; with source UNKNOWN on one or
        # both sides (groups like ColdFilm often ship no WEB/BluRay tag at
        # all) it's still group-level trust -- contradicting sources already
        # returned TIER_CROSS above.
        pct = 90 if same_source else 86
        reasons.append('same group + source' if same_source
                       else 'same group (source untagged)')
        if v['resolution'] and v['resolution'] == s['resolution']:
            pct += 4
            reasons.append('same resolution')
        if v['codec'] and v['codec'] == s['codec']:
            pct += 3
            reasons.append('same codec')
        return min(pct, 99), TIER_GROUP, reasons

    if same_source:
        if floor >= _CEIL_SAME_SOURCE:
            return None
        pct = 55
        reasons.append('same source class ({0})'.format(v['source']))
        if v['resolution'] and v['resolution'] == s['resolution']:
            pct += 6
            reasons.append('same resolution')
        if v['codec'] and v['codec'] == s['codec']:
            pct += 3
        if v['group'] and s['group'] and v['group'] != s['group']:
            pct -= 8
            reasons.append('different group')
        if ratio < 0:
            ratio = _token_ratio(vt, st)
        pct += int(ratio * 15)   # token tie-break WITHIN the tier
        return max(20, min(pct, 84)), TIER_SOURCE, reasons

    # Source unknown on at least one side (and groups don't match): token
    # similarity only, bounded so it can never outrank a structural match.
    if floor >= _CEIL_FUZZY:
        return None
    if ratio < 0:
        ratio = _token_ratio(vt, st)
    pct = int(10 + ratio * 55)
    return min(pct, 79), TIER_FUZZY, reasons


def match_pct(video_name, sub_name):
    """Drop-in int replacement for the three legacy scorers."""
    try:
        return score(video_name, sub_name)[0]
    except Exception:
        return 0


def match_tier(video_name, sub_name):
    try:
        return score(video_name, sub_name)[1]
    except Exception:
        return TIER_FUZZY


def best(video_name, sub_names):
    """(best_pct, best_name) across a list of candidate release names."""
    best_pct, best_name = 0, ''
    for n in sub_names or []:
        p = match_pct(video_name, n)
        if p > best_pct:
            best_pct, best_name = p, n
    return best_pct, best_name


# A synthesized "release" (subs_filename_publisher fallback builds
# Title.SxxExx.QUALITYp.mkv when POV published nothing) must never be treated
# as a real release identity: it has no group/source, so exact/group tiers
# against it are meaningless -- and it must never anchor a timing oracle (S2).
def is_synthetic(name):
    p = parse(name)
    return not p['group'] and not p['source']
