#!/usr/bin/env python3
"""The HEB badge must cost the source window almost nothing, and say the same
thing it always did.

THE REPORT: sources scrape quickly, and then the list takes five to ten
seconds to appear -- on a webOS TV, where it used to be about one. The log
timed three openings, from the line our reorder hook writes at the top of
POV's display_results to the moment the results window loads:

    3 Hebrew subtitle names available ->  2.0 s
    6                                 ->  4.0 s
    17                                -> 10.3 s

Almost exactly linear in the NUMBER OF SUBTITLE NAMES, which is the shape of
a nested loop: every source row was scored against every available name, and
against every embedded-Hebrew name twice on top. Seventy rows and seventeen
names is 1190 scored pairs before a single row can be drawn, and each pair
re-derived both release names from scratch -- so the seventeen names were
normalised, tokenised and parsed seventy times each.

WHAT THIS FILE PINS:

  * the badge is UNCHANGED. Every optimisation here is an equivalence, and the
    test proves it the only way that means anything -- by running the naive
    algorithm alongside and comparing the produced label, character for
    character, over hundreds of randomised source lists;
  * best_pct really is max(match_pct), including for blanks, None and
    non-strings, which is where the first version of it was wrong: a
    whitespace name scored 10 through the new path and 0 through the old one;
  * the floor answer is honest -- 0 or >= 80, never a number in between, and
    >= 80 exactly when the true maximum is;
  * THE COST, measured in difflib passes rather than seconds, because a
    wall-clock assertion is a machine-speed assertion and this has to fail on
    a fast laptop too. The built-in-Hebrew scan must cost ZERO of them: only
    the exact, containment and same-group branches can reach 80, and none of
    the three needs a token ratio;
  * the caches cannot leak into an answer, and cannot grow without bound
    inside POV's long-lived interpreter;
  * and the per-row diagnostic log that used to fire for every row of every
    source list is gone.

Run: python3 tools/test_source_badge_cost.py
"""
import ast
import importlib.util
import io
import json
import os
import random
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, '..', 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
sys.path.insert(0, LIB)

import release_match as rm          # noqa: E402
import he_sub_match as hs           # noqa: E402

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


# --- corpora ----------------------------------------------------------------
_GROUPS = ('RARBG', 'YTS', 'SPARKS', 'NTb', 'FLUX', 'CMRG', 'EVO', 'ColdFilm',
           'GalaxyRG', 'PSA', 'HDT', 'TOMMY', 'QxR', '')
_SOURCES = ('BluRay', 'WEB-DL', 'WEBRip', 'HDTV', 'BRRip', 'REMUX', 'DVDRip',
            'CAM', '')
_RES = ('2160p', '1080p', '720p', '480p', '4K', '')
_CODEC = ('x264', 'x265', 'H.264', 'HEVC', 'AV1', 'XviD', 'DDP5.1', '')
_EDITION = ('EXTENDED', 'UNRATED', 'IMAX', 'REMASTERED', 'PROPER', 'REPACK',
            '')
_TITLES = ('The Movie', 'Some.Show.S01E02', 'A_Film_Name', 'Title (2024)',
           'Movie.Name.2019', 'Shared.Title.2024')


def mk(rnd, title=None):
    parts = [title or rnd.choice(_TITLES), rnd.choice(_RES),
             rnd.choice(_SOURCES), rnd.choice(_CODEC), rnd.choice(_EDITION)]
    name = '.'.join(p for p in parts if p)
    g = rnd.choice(_GROUPS)
    if g:
        name += '-' + g
    if rnd.random() < 0.2:
        name += '.mkv'
    if rnd.random() < 0.1:
        name = name.replace('.', ' ')
    return name


# --- 1. best_pct IS the maximum it replaces ---------------------------------
print('=== best_pct is exactly max(match_pct) ===')
rnd = random.Random(23)
pool = [mk(rnd) for _ in range(400)] + ['', None, ' ', '   \t', 'x',
                                        'a.b.c.d-NTb', 0, 5]
bad_max = bad_floor = bad_shape = 0
junk_trials = 0
for _ in range(2500):
    v = rnd.choice(pool)
    names = rnd.sample(pool, rnd.randint(0, 16))
    if (not isinstance(v, str) or not v.strip()
            or any(not isinstance(n, str) or not n.strip() for n in names)):
        junk_trials += 1
    want = max([rm.match_pct(v, n) for n in names], default=0)
    if rm.best_pct(v, names) != want:
        bad_max += 1
    f = rm.best_pct(v, names, stop_at=80, floor=79)
    if (want >= 80) != (f >= 80):
        bad_floor += 1
    if f and f < 80:
        bad_shape += 1
check('best_pct == max(match_pct) over 2500 randomised lists', not bad_max,
      '%d disagreements' % bad_max)
# The label used to be the only evidence: it re-read the previous check's
# counter and confirmed the POOL held a non-string, not that any TRIAL did.
check('...including blanks, None and non-strings',
      not bad_max and junk_trials >= 100,
      'only %d of 2500 trials actually involved one' % junk_trials)
check('the floor answer clears 80 exactly when the true maximum does',
      not bad_floor, '%d disagreements' % bad_floor)
check('...and is never a number between 1 and 79', not bad_shape,
      '%d out-of-range answers' % bad_shape)


# --- 2. the badge itself is unchanged ---------------------------------------
# The naive algorithm, written out here rather than imported, so this compares
# against the shape the field ran and not against a helper that could be
# optimised along with the code under test.
print()
print('=== the badge is character-for-character what it was ===')


def naive_prefix(src, names, embedded, alt, synced):
    def best(a, ns):
        return max([rm.match_pct(a, n) for n in ns or []], default=0)
    if embedded and (src or alt):
        if max(best(src, embedded), best(alt, embedded)) >= 80:
            return '[COLOR FF2ECC71][B]HEB BUILT-IN 101%[/B][/COLOR] | '
    hit = False
    for r in (src, alt):
        if r and synced and hs._worker_norm(r) in synced:
            hit = True
            break
    b = best(src, names)
    if b <= 0:
        return '[COLOR FF2ECC71][B]HEB SYNC[/B][/COLOR] | ' if hit else ''
    if hit:
        return '[COLOR FF2ECC71][B]HEB {0}% SYNC[/B][/COLOR] | '.format(b)
    color = 'FF49C46A' if b >= 66 else ('FFE0B23C' if b >= 33 else 'FFD0594F')
    return '[COLOR {0}][B]HEB {1}%[/B][/COLOR] | '.format(color, b)


rnd = random.Random(77)
differ = []
kinds = set()
for case in range(220):
    title = rnd.choice(_TITLES)
    n_rows = rnd.randint(1, 25)
    rows = [mk(rnd, title if rnd.random() < 0.7 else None)
            for _ in range(rnd.randint(1, max(1, n_rows)))]
    rows = [rows[i % len(rows)] for i in range(n_rows)]
    names = [mk(rnd, title if rnd.random() < 0.6 else None)
             for _ in range(rnd.randint(0, 18))]
    emb = [mk(rnd, title if rnd.random() < 0.35 else None)
           for _ in range(rnd.randint(0, 15))]
    synced = set()
    if rows and rnd.random() < 0.3:
        synced.add(hs._worker_norm(rnd.choice(rows)))
    for r in rows:
        alt = r.replace('.', ' ') if rnd.random() < 0.5 else mk(rnd, title)
        got = hs.label_prefix(r, names, emb, alt, synced)
        want = naive_prefix(r, names, emb, alt, synced)
        if got != want:
            differ.append((r, alt, got, want))
        kinds.add('none' if not want else
                  ('built-in' if 'BUILT-IN' in want else
                   ('sync' if 'SYNC' in want else 'pct')))
check('220 randomised source lists produce the identical badge', not differ,
      '%d rows differ, first: %r' % (len(differ), differ[:1]))
# A comparison that never produced a badge would agree with anything.
check('...and the corpus produced every kind of badge, not just blanks',
      kinds == {'none', 'built-in', 'sync', 'pct'},
      'only saw %s' % sorted(kinds))


# --- 3. THE COST ------------------------------------------------------------
print()
print('=== the cost, in difflib passes rather than seconds ===')


def passes(fn):
    """How many token-ratio comparisons `fn` causes. Caches cleared first, so
    this measures a cold window -- the one the user waits for."""
    for c in (rm._NORM_MEMO, rm._TOKS_MEMO, rm._PARSE_MEMO, rm._SCORE_MEMO):
        c.clear()
    n = [0]
    real = rm._token_ratio

    def counting(a, b):
        n[0] += 1
        return real(a, b)
    rm._token_ratio = counting
    try:
        fn()
    finally:
        rm._token_ratio = real
    return n[0]


rnd = random.Random(3)
ROWS = [mk(rnd, 'The.Movie.Title') for _ in range(70)]
NAMES = [mk(rnd, 'The.Movie.Title') for _ in range(17)]
EMB = [mk(rnd, 'Other.Film.%d' % i) for i in range(14)]
NAIVE = len(ROWS) * (2 * len(EMB) + len(NAMES))

window = passes(lambda: [hs.label_prefix(r, NAMES, EMB, r.replace('.', ' '),
                                         set()) for r in ROWS])
print('     %d rows, %d names, %d embedded: %d passes (naive would be %d)'
      % (len(ROWS), len(NAMES), len(EMB), window, NAIVE))
check('the whole window costs under a quarter of the naive count',
      window <= NAIVE // 4, '%d of %d' % (window, NAIVE))

emb_only = passes(lambda: [hs.best_score(r, EMB, stop_at=80, floor=79)
                           for r in ROWS])
check('the built-in-Hebrew scan costs ZERO difflib passes', emb_only == 0,
      '%d passes -- the floor=79 shortcut is not being taken' % emb_only)

# Every name is derived once, not once per row.
for c in (rm._NORM_MEMO, rm._TOKS_MEMO, rm._PARSE_MEMO, rm._SCORE_MEMO):
    c.clear()
n = [0]
_real_parse = rm._parse
rm._parse = lambda name: (n.__setitem__(0, n[0] + 1), _real_parse(name))[1]
try:
    for r in ROWS:
        hs.label_prefix(r, NAMES, EMB, r, set())
finally:
    rm._parse = _real_parse
check('each release name is parsed once, not once per pair',
      n[0] <= len(ROWS) + len(NAMES) + len(EMB) + 2,
      '%d parses for %d distinct names'
      % (n[0], len(set(ROWS)) + len(NAMES) + len(EMB)))

# AND THE PAIR CACHE, which needs its own corpus to be visible at all.
# Review round 11 disabled _SCORE_MEMO on its own and every cost check above
# still passed -- because those seventy rows are seventy DISTINCT releases,
# so no pair ever repeats and the pair cache has nothing to do. The thing it
# exists for is the ordinary case its own docstring names: one release
# offered by several hosts, which is most of a real source list.
DUP_ROWS = [ROWS[i % 12] for i in range(70)]


def _score_calls(rows):
    for c in (rm._NORM_MEMO, rm._TOKS_MEMO, rm._PARSE_MEMO, rm._SCORE_MEMO):
        c.clear()
    k = [0]
    real = rm._score

    def counting(a, b, floor=0):
        k[0] += 1
        return real(a, b, floor=floor)
    rm._score = counting
    try:
        for r in rows:
            hs.label_prefix(r, NAMES, EMB, r.replace('.', ' '), set())
    finally:
        rm._score = real
    return k[0]


class _AlwaysMisses(dict):
    def get(self, *a, **k):
        return None


with_memo = _score_calls(DUP_ROWS)
_real_memo = rm._SCORE_MEMO
rm._SCORE_MEMO = _AlwaysMisses()   # stores, never hits
try:
    without_memo = _score_calls(DUP_ROWS)
finally:
    rm._SCORE_MEMO = _real_memo
print('     12 releases across 70 rows: %d scored pairs, %d without the pair'
      ' cache' % (with_memo, without_memo))
check('the pair cache spares work when a release repeats across rows',
      with_memo < without_memo,
      '%d vs %d -- disabling _SCORE_MEMO changed nothing'
      % (with_memo, without_memo))


# --- 4. the caches cannot leak into an answer -------------------------------
print()
print('=== the caches are invisible ===')
key = 'The.Film.2024.1080p.BluRay.x264-NTb'
d = rm.parse(key)
d['group'] = 'MUTATED'
check('mutating a parse() result does not poison the cache',
      rm.parse(key)['group'] == 'ntb')
t = rm.tokens(key)
t.append('MUTATED')
check('mutating a tokens() result does not poison the cache',
      'MUTATED' not in rm.tokens(key))
pair = (key, 'The.Film.2024.1080p.WEB-DL-FLUX')
r = rm.score(*pair)
r[2].append('MUTATED')
check('mutating a score() reasons list does not poison the cache',
      'MUTATED' not in rm.score(*pair)[2])

before = [rm.match_pct(a, b) for a in ROWS[:12] for b in NAMES[:6]]
for c in (rm._NORM_MEMO, rm._TOKS_MEMO, rm._PARSE_MEMO, rm._SCORE_MEMO):
    c.clear()
after = [rm.match_pct(a, b) for a in ROWS[:12] for b in NAMES[:6]]
check('clearing every cache changes no answer', before == after)

for c in (rm._NORM_MEMO, rm._TOKS_MEMO, rm._PARSE_MEMO, rm._SCORE_MEMO):
    c.clear()
big = random.Random(5)
for i in range(rm._MEMO_CAP + 500):
    rm.match_pct(mk(big), mk(big))
check('the caches stay bounded inside POV\'s long-lived interpreter',
      all(len(c) <= rm._MEMO_CAP
          for c in (rm._NORM_MEMO, rm._TOKS_MEMO, rm._PARSE_MEMO,
                    rm._SCORE_MEMO)),
      'sizes: %s' % [len(c) for c in (rm._NORM_MEMO, rm._TOKS_MEMO,
                                      rm._PARSE_MEMO, rm._SCORE_MEMO)])


# --- 5. the diagnostic that lived in the hot path ---------------------------
print()
print('=== no diagnostic left in the per-row path ===')
# By AST, so the historical note explaining WHY the log was removed does not
# trip the check that it was. A comment is not a call.
_src = io.open(os.path.join(LIB, 'he_sub_match.py'), encoding='utf-8').read()
_tree = ast.parse(_src)
_hot = [f for f in ast.walk(_tree) if isinstance(f, ast.FunctionDef)
        and f.name in ('label_prefix', 'best_score')]
check('both per-row functions were found to inspect', len(_hot) == 2,
      'found %s' % [f.name for f in _hot])
_logs = [f.name for f in _hot for n in ast.walk(f)
         if isinstance(n, ast.Call)
         and ((isinstance(n.func, ast.Attribute) and n.func.attr == 'log')
              or (isinstance(n.func, ast.Name) and n.func.id == 'log'))]
check('neither label_prefix nor best_score logs', not _logs,
      'a log call here runs once per row of every source list: %s' % _logs)

# --- 5b. the difflib fallback refuses what the real scorer refuses ---------
# Only reachable when release_match cannot be imported, and it had a bug that
# the early exit turned from consistent into ORDER-DEPENDENT. _score has no
# type guard, so a truthy non-string entry raises inside re.sub; the old
# max()-over-a-generator turned that into a flat 0 for the whole list, which
# threw away a genuine match sitting next to it. Stopping early would have
# meant the same list answered differently depending on which entry came
# first. Both paths skip the same inputs now.
print()
print('=== the fallback scorer refuses the same inputs ===')
_fb_dir = tempfile.mkdtemp(prefix='nofallback-')
shutil.copy(os.path.join(LIB, 'he_sub_match.py'),
            os.path.join(_fb_dir, 'he_sub_match.py'))
_saved_path, _saved_mods = list(sys.path), {}
for _m in ('he_sub_match', 'release_match'):
    _saved_mods[_m] = sys.modules.pop(_m, None)
try:
    sys.path = [_fb_dir] + [q for q in sys.path if q != LIB]
    _spec = importlib.util.spec_from_file_location(
        'he_sub_match', os.path.join(_fb_dir, 'he_sub_match.py'))
    fb = importlib.util.module_from_spec(_spec)
    sys.modules['he_sub_match'] = fb
    _spec.loader.exec_module(fb)
    check('the fallback is the one under test here',
          fb._release_match_mod() is None,
          'release_match was importable -- this tested the wrong path')
    GOOD = 'Movie.X.2024.1080p.BluRay.x264-GRP'
    _orders = [fb.best_score(GOOD, ns) for ns in
               ([-1, GOOD], [GOOD, -1], [None, GOOD], [GOOD, None],
                ['  ', GOOD], [GOOD, '  '], [{}, GOOD], [GOOD, {}])]
    check('a junk entry never decides the answer, wherever it sits',
          set(_orders) == {100}, 'got %s' % _orders)
    check('a non-string source release is refused, not scored',
          [fb.best_score(v, [GOOD]) for v in (-1, None, '   ', {})]
          == [0, 0, 0, 0])
finally:
    sys.path = _saved_path
    sys.modules.pop('he_sub_match', None)
    for _m, _mod in _saved_mods.items():
        if _mod is not None:
            sys.modules[_m] = _mod
    shutil.rmtree(_fb_dir, ignore_errors=True)
import he_sub_match as hs        # noqa: E402,F811  (restore the real one)

# --- 6. the lists that feed the hot loop cannot grow without bound ---------
# WHY THIS SECTION EXISTS, and it is the answer to 'but it was fast
# yesterday'. Nothing in the scoring path changed between fast and slow. The
# LISTS grew. `embedded` and `sync_rel` were union-only and never trimmed --
# every release ever seen carrying a built-in Hebrew track stayed in a list
# that the badge walks once per source row, forever. A per-row cost that
# grows monotonically with use is a slowdown with no event to blame it on,
# which is exactly how this one arrived.
print()
print('=== the per-title lists are bounded ===')

check('_bounded_union dedupes without regard to case',
      hs._bounded_union(['A.Release-NTb'], ['a.release-ntb', 'Other-FLUX'])
      == ['A.Release-NTb', 'Other-FLUX'])
# THIS READS A JSON FILE OTHER PROCESSES WRITE, so an entry can be a number
# or an object without anyone having written bad Python. The inline code
# this replaced raised on .lower() for one of those, inside a try/except
# that swallows -- so the WRITE silently did not happen.
check('a non-string entry is skipped, not raised on',
      hs._bounded_union(['keep-me', 7, None, {}, []], [3.5, 'new-one', ' '])
      == ['keep-me', 'new-one'])
check('a cap of zero means zero, not everything',
      hs._bounded_union(['a', 'b'], ['c'], cap=0) == [],
      'out[-0:] is the whole list -- the guard is what stops that')
check('...and can be told not to, for the confirmed-sync keys',
      hs._bounded_union(['abc'], ['ABC'], fold_case=False) == ['abc', 'ABC'])
_big = [str(i) for i in range(hs._MAX_NAMES + 80)]
_capped = hs._bounded_union(_big, ['newest'])
check('the union caps at _MAX_NAMES', len(_capped) == hs._MAX_NAMES,
      'got %d' % len(_capped))
check('...and it is the NEWEST that survives the cap',
      _capped[-1] == 'newest' and _big[0] not in _capped)

_tmp = tempfile.mkdtemp(prefix='avail-')
_cache = os.path.join(_tmp, 'he_avail.json')
_real_path = hs._engine_cache_path
hs._engine_cache_path = lambda: _cache
try:
    flood = ['Flood.%d.2024.1080p.WEB-DL-GRP%d' % (i, i) for i in range(500)]
    hs._store_avail('k', flood, flood, 3600, flood)
    ent = json.load(io.open(_cache, encoding='utf-8'))['k']
    for field in ('names', 'embedded', 'sync_rel'):
        check('_store_avail caps %s' % field,
              len(ent[field]) <= hs._MAX_NAMES,
              'stored %d' % len(ent[field]))
    # A second warm must not be able to grow the unioned fields past the cap.
    hs._store_avail('k', flood, flood[::-1], 3600, flood[::-1])
    ent = json.load(io.open(_cache, encoding='utf-8'))['k']
    check('a second warm cannot push the unioned lists past the cap',
          len(ent['embedded']) <= hs._MAX_NAMES
          and len(ent['sync_rel']) <= hs._MAX_NAMES,
          'embedded=%d sync_rel=%d'
          % (len(ent['embedded']), len(ent['sync_rel'])))

    _real_enabled, _real_params, _real_key = (hs._enabled, hs._media_params,
                                              hs._media_key)
    hs._enabled = lambda: True
    hs._media_params = lambda meta: {'id': 'x'}
    hs._media_key = lambda p: 'k'
    try:
        for chunk in range(6):
            hs.merge_names({}, ['Merge.%d.%d-G' % (chunk, i)
                                for i in range(100)])
            hs.merge_embedded({}, ['Emb.%d.%d-G' % (chunk, i)
                                   for i in range(100)])
        ent = json.load(io.open(_cache, encoding='utf-8'))['k']
        check('merge_names cannot grow the list without bound',
              len(ent['names']) <= hs._MAX_NAMES, 'grew to %d'
              % len(ent['names']))
        check('merge_embedded cannot either',
              len(ent['embedded']) <= hs._MAX_NAMES, 'grew to %d'
              % len(ent['embedded']))
        check('and the newest merge is the one that survived',
              any('Merge.5.' in n for n in ent['names'])
              and any('Emb.5.' in n for n in ent['embedded']))
    finally:
        hs._enabled, hs._media_params, hs._media_key = (
            _real_enabled, _real_params, _real_key)
finally:
    hs._engine_cache_path = _real_path
    shutil.rmtree(_tmp, ignore_errors=True)

_merge_fns = [f for f in ast.walk(_tree) if isinstance(f, ast.FunctionDef)
              and f.name in ('merge_names', 'merge_embedded')]
check('both merge functions were found to inspect', len(_merge_fns) == 2)
_merge_logs = [f.name for f in _merge_fns for n in ast.walk(f)
               if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Attribute) and n.func.attr == 'log']
check('neither merge dumps whole release lists into the Kodi log',
      not _merge_logs, 'still logging: %s' % _merge_logs)

# The third one of these, and the one in the path the user actually waits
# through: embedded_names runs once per source window, before any row is
# drawn, and it logged the whole list it had just read.
_win_fns = [f for f in ast.walk(_tree) if isinstance(f, ast.FunctionDef)
            and f.name in ('embedded_names', 'release_names',
                           'confirmed_releases')]
check('the three once-per-window reads were found', len(_win_fns) == 3,
      'found %s' % [f.name for f in _win_fns])
_win_logs = [f.name for f in _win_fns for n in ast.walk(f)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == 'log']
check('embedded_names no longer logs its whole list per window',
      'embedded_names' not in _win_logs,
      'still logging from: %s' % sorted(set(_win_logs)))

# AND THE DEAD SECOND WRITER. default.py::_he_avail_store had no callers and
# wrote the same cache with no bound and an OVERWRITE of the embedded list --
# the two bugs the live writer had to be fixed for. Copying from it would
# have brought both back.
_dflt = io.open(os.path.join(LIB, '..', '..', 'default.py'),
                encoding='utf-8').read()
check('there is exactly one writer of the availability cache',
      'def _he_avail_store' not in _dflt,
      'default.py still defines a second, unbounded one')

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
