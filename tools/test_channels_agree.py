"""A shared changelog over two different services can lie to one of them.

The add-on ships down two channels that do NOT run the same code:

  * the BUILD edition (quickfix / full build) runs the repo's real service.py
  * the STANDALONE (repo channel) runs SLIM_SERVICE, a template written inside
    tools/build_ai_subtitles_packages.py

changelog.txt is filtered per channel but the surviving text is IDENTICAL. So a
release note can describe behaviour that exists in one service and not the
other, and nothing notices.

That is not hypothetical. 0.2.494 promised "The AI translation add-on moves to
Gemini 3.7 Flash. Anyone already on 3.5 or 3.6 Flash is moved across once,
automatically." The migration went into service.py. SLIM_SERVICE never got it.
Build users were migrated; repo-channel users read the promise, kept
gemini-3.6-flash, and had no way to know. It shipped in 0.2.494 and survived
0.2.495, 0.2.496 and 0.2.497 -- found by a user reading the zip, not by us.

So this asserts the claim against BOTH services. It is deliberately written as
"this specific promise, checked in both places" rather than a general diff:
the two services are SUPPOSED to differ, and a test that demanded they match
would be noise. What must not differ is a promise made in shared text.

Add a case here whenever a release note promises behaviour rather than
describing a fix.

Run: python3 tools/test_channels_agree.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILDER = ROOT / 'tools' / 'build_ai_subtitles_packages.py'
SERVICE = ROOT / 'addons' / 'service.subtitles.kodipovilai' / 'service.py'
CHANGELOG = ROOT / 'addons' / 'service.subtitles.kodipovilai' / 'changelog.txt'

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


builder = BUILDER.read_text(encoding='utf-8')
service = SERVICE.read_text(encoding='utf-8')
changelog = CHANGELOG.read_text(encoding='utf-8')


def slim_service():
    """The standalone's service.py, as embedded in the builder."""
    m = re.search(r"SLIM_SERVICE\s*=\s*r?'''(.*?)'''", builder, re.S)
    assert m, 'SLIM_SERVICE template not found in the builder'
    return m.group(1)


slim = slim_service()
check('the SLIM_SERVICE template can be extracted', len(slim) > 2000,
      '%d chars' % len(slim))

# --- the Gemini model-bump promise, the one that shipped broken ------------
# The regular-Flash target moves with Google: 3.7 in 0.2.494, 3.8 from 0.2.517.
# The CLAIM is what is being checked, not a particular version, so this pair
# moves when the picker does -- and the SLIM_SERVICE half is the part that was
# missing for three releases the first time.
TARGET = 'gemini-3.8-flash'
promised = 'Gemini 3.8 Flash' in changelog and 'automatically' in changelog
check('changelog promises the automatic Gemini move', promised,
      'the claim is gone -- delete this case or update it')

if promised:
    for name, src in (('build service.py', service),
                      ('standalone SLIM_SERVICE', slim)):
        check('%s defines the migration' % name,
              '_maybe_bump_gemini_model' in src)
        check('%s CALLS it' % name,
              re.search(r'^\s*_maybe_bump_gemini_model\(\)\s*$', src, re.M)
              is not None,
              'defined but never called is the same as absent')
        check('%s maps 3.6 -> %s' % (name, TARGET),
              "'gemini-3.6-flash': '%s'" % TARGET in src)
        check('%s maps 3.5 -> %s' % (name, TARGET),
              "'gemini-3.5-flash': '%s'" % TARGET in src)
        check('%s gates on the v2 marker, not v1' % name,
              '_gemini_model_bump_v2' in src and '_gemini_model_bump_v1' not in src,
              'reusing v1 makes it a no-op for exactly the 3.6 users')
        # The 3.7 -> 3.8 move is a SECOND migration with its own marker, and it
        # has to exist on both channels for the same reason the first one did.
        check('%s defines the 3.8 migration' % name,
              '_maybe_bump_gemini_model_38' in src)
        check('%s CALLS the 3.8 migration' % name,
              re.search(r'^\s*_maybe_bump_gemini_model_38\(\)\s*$', src, re.M)
              is not None,
              'defined but never called is the same as absent')
        check('%s moves a stored 3.7 to %s' % (name, TARGET),
              "'gemini-3.7-flash'" in src and TARGET in src)
        check('%s gates the 3.8 migration on its own marker' % name,
              '_gemini_model_bump_v3' in src,
              'reusing v2 makes it a no-op for exactly the 3.7 users')

# --- SABOTAGE: the check must be able to fail ------------------------------
# Without this, "standalone has it" passes just as happily on a test that is
# reading the wrong string, which is how the original defect survived review.
broken = slim.replace('_maybe_bump_gemini_model', '_gone', 1)
check('SABOTAGE: a standalone missing the migration is detected',
      '_maybe_bump_gemini_model' in slim and '_gone' in broken
      and broken.count('_maybe_bump_gemini_model') < slim.count('_maybe_bump_gemini_model'),
      'the extraction is not actually reading the template')

uncalled = re.sub(r'^\s*_maybe_bump_gemini_model\(\)\s*$', '', slim, flags=re.M)
check('SABOTAGE: defined-but-never-called is detected',
      re.search(r'^\s*_maybe_bump_gemini_model\(\)\s*$', uncalled, re.M) is None
      and '_maybe_bump_gemini_model' in uncalled,
      'removing the call did not change what the check sees')

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
