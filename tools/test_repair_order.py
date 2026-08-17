"""The startup repair sequence has orderings that MATTER, and they are pinned.

`_run_build_startup_repairs()` runs ~56 steps in a fixed order. Most of them
are independent and the order is arbitrary. Three are not, and each one is
here because getting it wrong cost something real:

  * `_maybe_patch_pov_language_invoker` MUST BE FIRST. POV runs its own
    ReuseLanguageInvokerCheck a few seconds into its service start; if POV's
    addon.xml and its hidden reuse_language_invoker setting disagree it throws
    an English "SETTING/XML mismatch" dialog at the user. They disagree after
    every POV self-update, because POV is not in our quickfix at all and its
    own addon.xml ships the flag ON while our setting says OFF -- OFF being
    the fix for the Arctic Fuse 3 native crash. Measured on a reporter's
    device: from 27th in the tuple the guard wrote 9.4 SECONDS AFTER POV's
    check and lost every time, even though the pass as a whole starts 20
    seconds before it. First in the tuple it writes ~19 seconds ahead.

  * the two cache-schema repairs must come before anything that reads those
    caches, which their own comments in service.py say at length.

WHY A SOURCE-TEXT TEST AND NOT A BEHAVIOURAL ONE. service.py needs a whole
Kodi to import. The ordering is a property of the source, so the source is
what gets checked -- the same shape tools/test_wizard_startup_order.py uses
for the wizard's own ordering constraint. It is a weak test in the sense that
it cannot prove the guard WINS the race; it is a strong test of the only thing
that can silently regress, which is someone inserting a step above it.

Run: python3 tools/test_repair_order.py
"""
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVICE = os.path.normpath(os.path.join(
    HERE, '..', 'addons', 'service.subtitles.kodipovilai', 'service.py'))

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def steps_of(src):
    """The step names, in order, from the `steps = (...)` tuple.

    Parsed out of the AST rather than by regex over the whole file, so a
    function NAMED in a comment or docstring elsewhere cannot be mistaken for
    a step, and a step cannot be missed because its line is formatted oddly.
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id == 'steps' and \
                    isinstance(node.value, ast.Tuple):
                return [e.id for e in node.value.elts
                        if isinstance(e, ast.Name)]
    return []


with open(SERVICE, encoding='utf-8') as f:
    SRC = f.read()

STEPS = steps_of(SRC)

check('the steps tuple was found and parsed', len(STEPS) > 20,
      'found %d' % len(STEPS))
check('no step is registered twice',
      len(STEPS) == len(set(STEPS)),
      'duplicated: %s' % sorted({s for s in STEPS if STEPS.count(s) > 1}))

# --------------------------------------------------------------------------
# the ordering this file exists for
# --------------------------------------------------------------------------
GUARD = '_maybe_patch_pov_language_invoker'
check('the invoker guard is still registered', GUARD in STEPS)
check('the invoker guard runs FIRST',
      STEPS and STEPS[0] == GUARD,
      'it is at position %s; POV checks a few seconds into its own start and '
      'shows the user a SETTING/XML mismatch dialog if we have not written '
      'yet. From 27th it lost that race by 9.4s on a real device.'
      % (STEPS.index(GUARD) + 1 if GUARD in STEPS else 'ABSENT'))

# the two schema repairs still precede every reader of those caches
for name in ('_maybe_fix_pov_maincache_schema', '_maybe_repair_pov_cache_schema'):
    check('%s is still near the front' % name,
          name in STEPS and STEPS.index(name) <= 3,
          'at position %s -- POV menus that read these caches are wrong until '
          'the tables are rebuilt'
          % (STEPS.index(name) + 1 if name in STEPS else 'ABSENT'))
check('the two schema repairs keep their documented order',
      STEPS.index('_maybe_fix_pov_maincache_schema')
      < STEPS.index('_maybe_repair_pov_cache_schema'))

# --------------------------------------------------------------------------
# the guard can only ever turn the flag OFF
# --------------------------------------------------------------------------
# Not an ordering property, but it is the thing the owner asked to be certain
# of when this step moved, and it is one line to keep certain.
GUARD_MOD = os.path.normpath(os.path.join(
    HERE, '..', 'addons', 'service.subtitles.kodipovilai', 'resources', 'lib',
    'pov_language_invoker_guard.py'))
with open(GUARD_MOD, encoding='utf-8') as f:
    GSRC = f.read()
wanted = re.findall(r"^WANTED\s*=\s*'([^']*)'", GSRC, re.M)
check('the guard has exactly one target value', len(wanted) == 1,
      'found %s' % wanted)
check("and that value is 'false' -- it can never re-enable the flag",
      wanted == ['false'],
      'reuse-language-invoker being ON is the Arctic Fuse 3 native crash')

# --------------------------------------------------------------------------
# SABOTAGE -- the checks must be able to fail
# --------------------------------------------------------------------------
print()
print('=== sabotage ===')

moved = SRC.replace('        %s,\n' % GUARD, '', 1)
check('SABOTAGE: removing the first entry changes the source', moved != SRC)
check('SABOTAGE: the guard no longer running first is caught',
      steps_of(moved)[0] != GUARD)

flipped = GSRC.replace("WANTED = 'false'", "WANTED = 'true'", 1)
check('SABOTAGE: flipping the target value changes the source',
      flipped != GSRC)
check('SABOTAGE: a guard that would re-enable the flag is caught',
      re.findall(r"^WANTED\s*=\s*'([^']*)'", flipped, re.M) != ['false'])

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
