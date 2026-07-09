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


def _strip_ext(name):
    return _EXT_RE.sub('', (name or '').strip())


def normalize(name):
    """Canonical comparison form: lowercase, extension stripped, all
    separators collapsed to single dots."""
    s = _strip_ext(name).lower()
    s = _SEPS.sub('.', s)
    s = re.sub(r'\.+', '.', s).strip('.')
    return s


def tokens(name):
    return [t for t in normalize(name).split('.') if t]


def parse(name):
    """Structured fields out of a release name. Every field may be '' when
    not present -- callers must treat '' as UNKNOWN, never as a mismatch."""
    toks = tokens(name)
    tokset = set(toks)
    out = {'resolution': '', 'source': '', 'group': '', 'codec': '',
           'edition': '', 'proper': False}

    m = _RES_RE.search(normalize(name))
    if m:
        r = m.group(1).lower()
        out['resolution'] = _RES_MAP.get(r, r if r.endswith('p') else '')

    for cls, cls_tokens in _SOURCE_CLASSES:
        if tokset & set(cls_tokens):
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

    out['proper'] = bool(tokset & set(_PROPER_TOKENS))

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
            and 2 <= len(cand) <= 20 and re.fullmatch(r'[a-z0-9]+', cand)):
        out['group'] = cand
    return out


def _token_ratio(a_tokens, b_tokens):
    if not a_tokens or not b_tokens:
        return 0.0
    try:
        return difflib.SequenceMatcher(None, a_tokens, b_tokens).ratio()
    except Exception:
        return 0.0


def score(video_name, sub_name):
    """Structured match: (pct 0-100, tier, reasons list). Either name empty
    -> (0, TIER_FUZZY, [])."""
    if not (video_name or '').strip() or not (sub_name or '').strip():
        return 0, TIER_FUZZY, []

    va, sa = normalize(video_name), normalize(sub_name)
    if va == sa:
        return 100, TIER_EXACT, ['identical release']

    v, s = parse(video_name), parse(sub_name)
    vt, st = tokens(video_name), tokens(sub_name)
    ratio = _token_ratio(vt, st)
    reasons = []

    # HARD contradictions first -- these caps are the whole point: the old
    # token scorer let a WEB sub score 70% against a BluRay source.
    if v['edition'] and s['edition'] and v['edition'] != s['edition']:
        pct = min(25, int(ratio * 40))
        return pct, TIER_CROSS, ['different edition/cut']
    if v['source'] and s['source'] and v['source'] != s['source']:
        pct = min(35, int(ratio * 45))
        return pct, TIER_CROSS, [
            'source mismatch ({0} vs {1})'.format(v['source'], s['source'])]
    if v['proper'] != s['proper'] and (v['source'] and s['source']):
        pct = min(40, int(ratio * 55))
        return pct, TIER_CROSS, ['PROPER/REPACK mismatch']

    same_source = bool(v['source'] and s['source'])  # equal if both set here
    same_group = bool(v['group'] and s['group'] and v['group'] == s['group'])

    if same_group and same_source:
        pct = 90
        reasons.append('same group + source')
        if v['resolution'] and v['resolution'] == s['resolution']:
            pct += 4
            reasons.append('same resolution')
        if v['codec'] and v['codec'] == s['codec']:
            pct += 3
            reasons.append('same codec')
        return min(pct, 99), TIER_GROUP, reasons

    if same_source:
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
        pct += int(ratio * 15)   # token tie-break WITHIN the tier
        return max(20, min(pct, 84)), TIER_SOURCE, reasons

    # Source unknown on at least one side: token similarity only, bounded so
    # it can never outrank a structural match.
    pct = int(10 + ratio * 55)
    if same_group:
        pct = max(pct, 72)
        reasons.append('same group (source unknown)')
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
