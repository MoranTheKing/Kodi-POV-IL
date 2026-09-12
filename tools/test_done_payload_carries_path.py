"""The finished translation must be DELIVERED, not guessed at.

resolve() writes the translation to cache.translated_path(..., tier='ar')
whenever a gender reference was found -- the default, and force-enabled by
migration, so it is the normal case. Both progressive 'done' handlers in
default.py recomputed that path themselves, WITHOUT the tier and with the
source language hardcoded 'en'. The file therefore did not exist, the canonical
swap was skipped, and the viewer kept the last PROGRESSIVE SLOT file. If the
translation had been interrupted that slot is partly source text -- which is
the "next time I open it, it plays the original language" report.

Run: python3 tools/test_done_payload_carries_path.py
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(HERE, '..', 'addons', 'service.subtitles.kodipovilai')
TRANSLATE = os.path.join(ADDON, 'resources', 'lib', 'translate.py')
DEFAULT = os.path.join(ADDON, 'default.py')

FAILED = []


def check(name, cond, detail=''):
    if cond:
        print('  ok  - %s' % name)
    else:
        print('  FAIL- %s%s' % (name, ('\n        ' + str(detail)) if detail else ''))
        FAILED.append(name)


tr = io.open(TRANSLATE, encoding='utf-8').read()
df = io.open(DEFAULT, encoding='utf-8').read()

# --- every SUCCESS 'done' must report the path it actually wrote ------------
emissions = re.findall(r"progressive_cb\('done', \{(.*?)\}\)", tr, re.S)
check('every progressive done site is still found', len(emissions) == 6,
      'found %d' % len(emissions))
success = [e for e in emissions if "'success': True" in e]
# THREE. The Google-rescue path (AI output was not Hebrew) used to return
# without emitting 'done' at all, so the canonical swap never ran and the
# viewer was left on the progressive slot holding the rejected output. This
# assertion said TWO, which would have failed the moment anyone wired the
# third -- the test was holding the bug in place.
check('all three success paths emit done', len(success) == 3,
      'found %d' % len(success))
for i, e in enumerate(success):
    check('success emission %d carries a path' % (i + 1), "'path':" in e,
          e.strip()[:160])

# --- and the handlers must PREFER it ---------------------------------------
# Structural checks over source text are fragile: three earlier versions of
# this section passed with the bug fully restored, because a regex stopped
# matching (registering ZERO checks instead of failing), because a count that
# is also true of the pre-diff code was used, and because a fixed-width slice
# landed in whitespace. Each check below is written so that it FAILS rather
# than disappears, and every one was verified against a full revert.

# The gate itself. Two handlers, so two gates, and the pre-diff code has none.
gates = df.count('canonical = payload.get(\'path\') or \'\'')
check('both handlers read the reported path first', gates == 2,
      'found %d' % gates)
guards = df.count('if not canonical:')
check('...and both fall back only when it is absent', guards == 2,
      'found %d' % guards)

# ORDER matters: the payload must be consulted BEFORE the recompute, or the
# recompute overwrites it. Check each handler's own slice, not the whole file.
_h = [m for m in range(len(df)) if df.startswith('_canonical_swap_succeeded = False', m)]
check('both swap handlers are still found', len(_h) == 2, 'found %d' % len(_h))
for _n, _start in enumerate(_h):
    _end = df.index('if os.path.isfile(canonical)', _start)
    _blk = df[_start:_end]
    check('handler %d consults the payload before recomputing' % (_n + 1),
          _blk.index("payload.get('path')") < _blk.index('_cache.translated_path('),
          'the recompute comes first and would overwrite the reported path')
    # slice the WHOLE call, to its closing paren, not a fixed width
    _c0 = _blk.index('_cache.translated_path(')
    _call = _blk[_c0:_blk.index(')', _blk.index("source_id=payload['source_id']", _c0))]
    check('handler %d fallback is untiered (it is a fallback, not the answer)'
          % (_n + 1), 'tier=' not in _call, _call[-90:])

# --- and the swap may not claim success it did not verify ------------------
# setSubtitles() posts to the VideoPlayer thread, so it returning is not
# evidence the stream was registered. Claiming success anyway meant the
# cleanup deleted the progressive slots while Kodi was still pointing at one.
check('neither handler claims the swap worked unconditionally',
      '_canonical_swap_succeeded = True' not in df,
      'a handler still trusts "setSubtitles did not raise"')
check('both handlers gate success on the stream count growing',
      df.count('_canonical_swap_succeeded = _grew') == 2,
      'found %d' % df.count('_canonical_swap_succeeded = _grew'))
check('both read the stream count BEFORE adding', df.count('_before = len(') == 2,
      'found %d' % df.count('_before = len('))
check('both wait for the count to grow rather than reading it once',
      df.count('if len(_streams) > _before:') == 2,
      'found %d' % df.count('if len(_streams) > _before:'))
# (the previous version counted the phrase "did not", which occurs twice in
# COMMENTS -- deleting both warning blocks left it passing. Count the call.)
# check() here is check(name, cond, detail) -- passing a count as `cond` made
# these truthy for 1 as well as 2, so they could not see the two handlers
# drifting apart, which is the only thing they exist for. Compare explicitly.
_warn = (df.count("'bg_translate_picker: Kodi did not ")
         + df.count("'translate_file: Kodi did not "))
check('a failed swap is reported in BOTH handlers, not silent', _warn == 2,
      'found %d warning sites' % _warn)
_noplayer = df.count('if not _grew and not _playing_now():')
check('and BOTH treat "no player" as safe-to-clean, not as failure',
      _noplayer == 2, 'found %d' % _noplayer)

print()
if FAILED:
    print('FAILED (%d): %s' % (len(FAILED), ', '.join(FAILED)))
    sys.exit(1)
print('ALL TESTS PASSED')
