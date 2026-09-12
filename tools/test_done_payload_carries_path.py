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
check('there are exactly two success emissions', len(success) == 2,
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
bare = re.findall(r"canonical = _cache\.translated_path\(\s*\n(?:[^)]*\n)*?\s*source_id=payload\['source_id'\]\)",
                  df)
for b in bare:
    check('a recompute never passes tier= (it is a fallback, not the answer)',
          'tier=' not in b, b[:100])
check('no handler computes the canonical path unconditionally',
      "canonical = _cache.translated_path" not in df.split(
          "canonical = payload.get('path') or ''")[0],
      'an ungated recompute still runs before the payload is consulted')

print()
if FAILED:
    print('FAILED (%d): %s' % (len(FAILED), ', '.join(FAILED)))
    sys.exit(1)
print('ALL TESTS PASSED')
