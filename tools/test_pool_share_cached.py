"""'Share my cached translations' uploaded nothing at all.

cache.translated_path() writes '<key>.ar.he.srt' whenever a gender reference
aligned -- the normal case, since the setting defaults on and is force-enabled
by migration. pool._CACHE_NAME_RE had no tier group, so it matched almost no
real file: every one counted as `skipped` and the action reported success
having uploaded nothing.

The second half matters as much as the first. The tier decides the pool `kind`,
and it must come from the FILENAME, not from the setting's value today -- the
setting says nothing about whether a reference actually aligned for that title
back then. Uploading a boosted file as plain 'ai' understates it; the reverse
would serve a non-boosted file to every other user as the boosted variant.

Run: python3 tools/test_pool_share_cached.py
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(HERE, '..', 'addons', 'service.subtitles.kodipovilai')
POOL = os.path.join(ADDON, 'resources', 'lib', 'pool.py')

FAILED = []


def check(name, got, want):
    if got == want:
        print('  ok  - %s' % name)
    else:
        print('  FAIL- %s\n        got  %r\n        want %r' % (name, got, want))
        FAILED.append(name)


src = io.open(POOL, encoding='utf-8').read()

# Lift the pattern out of the source rather than importing pool.py, which pulls
# in xbmc. If the pattern moves, this fails loudly instead of testing nothing.
m = re.search(r"_CACHE_NAME_RE = re\.compile\(\s*\n\s*(r'[^']*')\s*\n\s*(r'[^']*')\)",
              src)
check('the cache-name pattern is still where this test expects it',
      m is not None, True)
if m is None:
    print('\nFAILED: pattern not found')
    sys.exit(1)
RE = re.compile(eval(m.group(1)) + eval(m.group(2)))

# What cache.translated_path actually produces, both tiers.
CASES = [
    ('tt0993846_S0E0_en_996492fc440d2c6a.he.srt', ''),
    ('tt0993846_S0E0_en_996492fc440d2c6a.ar.he.srt', 'ar'),
    ('tt1234567_S1E5_es_aabbccdd11223344.ar.he.srt', 'ar'),
    ('tt7654321_S2E10_ru_00112233aabbccdd.he.srt', ''),
]
for name, want_tier in CASES:
    mm = RE.match(name)
    check('matches %s' % name, mm is not None, True)
    if mm:
        check('  ...and reads tier %r' % want_tier,
              mm.group('tier') or '', want_tier)

# Things that must NOT be taken for a translation.
for name in ('tt1_S0E0_en_abcd1234.ar.he.srt.google',
             'tt1_S0E0_en_abcd1234.ar.he.srt.shared',
             'tt1_S0E0_en_abcd1234.ar.he.srt.release',
             'progressive_abc_a.he.srt'):
    check('refuses %s' % name, RE.match(name) is None, True)

# The imdb group must not swallow the tier: a greedy .+? plus an optional group
# could in principle match by absorbing the suffix into <imdb>.
mm = RE.match('tt0993846_S0E0_en_996492fc440d2c6a.ar.he.srt')
check('the imdb group does not swallow the suffix', mm.group('imdb'), 'tt0993846')
check('...nor the language', mm.group('lang'), 'en')

# And the kind must be derived from that tier, not defaulted.
check('the upload derives kind from the parsed tier',
      "kind=('ai_ar' if _tier == 'ar' else 'ai')" in src, True)
check("...and does not fall back to _build_body's plain default",
      "_build_body(info, '', lang, text, release_override=rel_override)" not in src,
      True)
check('the tier comes from the filename, not from the setting',
      "_tier = (m.group('tier') or '')" in src, True)
check('an unknown tier stays plain rather than being guessed at',
      "if _tier == 'ar' else 'ai'" in src, True)

print()
if FAILED:
    print('FAILED (%d): %s' % (len(FAILED), ', '.join(FAILED)))
    sys.exit(1)
print('ALL TESTS PASSED')
