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
check('both progressive done sites are still found', len(emissions) >= 4,
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
uses = df.count("canonical = payload.get('path') or ''")
check('both done handlers read the reported path', uses == 2,
      'found %d' % uses)

# The recompute may remain only as a fallback for an older resolve().
for m in re.finditer(r"canonical = payload\.get\('path'\) or ''\n(.*?)if os\.path\.isfile\(canonical\)",
                     df, re.S):
    body = m.group(1)
    check('the recompute is gated behind "if not canonical"',
          'if not canonical:' in body, body.strip()[:120])

# --- the bug this replaces must not creep back -----------------------------
recomputes = df.count('canonical = _cache.translated_path(')
check('the recompute survives only as a fallback, twice', recomputes == 2,
      'found %d' % recomputes)
# (the previous version of this check sliced 34 characters that could not
# contain 'tier=' -- it could not fail. Look at the whole call instead.)
_recompute_calls = [
    df[m:df.index('source_id=', m) + 60]
    for m in [df.index('canonical = _cache.translated_path('),
              df.index('canonical = _cache.translated_path(',
                       df.index('canonical = _cache.translated_path(') + 1)]]
check('neither recompute passes a tier= (it is a fallback, not the answer)',
      not any('tier=' in c for c in _recompute_calls), True)

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
check('a failed swap is reported, not silent',
      df.count("_safe_log(\n                                            'bg_translate_picker: Kodi did not ")
      + df.count("_safe_log(\n                                            'translate_file: Kodi did not "), 2)
check('and "no player" is treated as safe-to-clean, not as failure',
      df.count('if not _grew and not _playing_now():'), 2)

print()
if FAILED:
    print('FAILED (%d): %s' % (len(FAILED), ', '.join(FAILED)))
    sys.exit(1)
print('ALL TESTS PASSED')
