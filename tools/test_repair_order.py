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
import types

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
# the guard reaches ON only by an explicit 'true', and OFF by everything else
# --------------------------------------------------------------------------
# THIS CHECK USED TO SAY SOMETHING STRONGER, and the change is deliberate.
# It asserted `WANTED == 'false'` -- the guard could never re-enable the flag,
# full stop. Since 0.2.507 it can, because `pov_fast_navigation` lets a person
# buy POV's speed back knowingly (the module header carries the measurement:
# a fixed ~1.75s per navigation with reuse off).
#
# What survives is the property that actually protects anyone: OFF is not the
# default so much as the DESTINATION OF EVERY FAILURE. kodi_utils missing, the
# settings store throwing, the setting undeclared or empty -- all of them land
# on SAFE. The only route to FAST is a setting that reads back exactly true.
# That is behavioural, so unlike the regex it replaces, it is executed.
GUARD_MOD = os.path.normpath(os.path.join(
    HERE, '..', 'addons', 'service.subtitles.kodipovilai', 'resources', 'lib',
    'pov_language_invoker_guard.py'))
with open(GUARD_MOD, encoding='utf-8') as f:
    GSRC = f.read()


class _KU(object):
    """Stand-in for resources.lib.kodi_utils. RAISE means the settings store
    is unavailable; UNSET returns whatever default the guard passes in, which
    is how Kodi answers for a setting nobody has ever touched."""

    RAISE = object()
    UNSET = object()

    def __init__(self, value):
        self.value = value
        self.asked = []

    def get_bool(self, key, default=False):
        self.asked.append((key, default))
        if self.value is _KU.RAISE:
            raise RuntimeError('settings store unavailable')
        if self.value is _KU.UNSET:
            return default
        return self.value

    def log(self, *a, **k):
        pass


def load_guard(src=None, ku=None):
    """Execute the guard's source with no Kodi present. Its own imports of
    xbmcvfs and kodi_utils fail and land on None, so kodi_utils is assigned
    afterwards -- _wanted() reads the module global at call time."""
    mod = types.ModuleType('_guard_under_test')
    mod.__file__ = GUARD_MOD
    exec(compile(src or GSRC, GUARD_MOD, 'exec'), mod.__dict__)
    mod.kodi_utils = ku
    return mod


G = load_guard()
check("SAFE is 'false' -- reuse off", G.SAFE == 'false', repr(G.SAFE))
check("FAST is 'true' -- reuse on", G.FAST == 'true', repr(G.FAST))
check('the switch is named pov_fast_navigation',
      G.SETTING_FAST == 'pov_fast_navigation', repr(G.SETTING_FAST))

check('no kodi_utils at all -> SAFE',
      load_guard(ku=None)._wanted() == 'false')
check('a settings store that throws -> SAFE',
      load_guard(ku=_KU(_KU.RAISE))._wanted() == 'false')
check('a setting nobody has ever touched -> SAFE',
      load_guard(ku=_KU(_KU.UNSET))._wanted() == 'false',
      'the guard must ask for it with default False')
check('the setting explicitly off -> SAFE',
      load_guard(ku=_KU(False))._wanted() == 'false')
check('the setting explicitly on -> FAST',
      load_guard(ku=_KU(True))._wanted() == 'true',
      'the switch has to actually do something')

_spy = _KU(_KU.UNSET)
load_guard(ku=_spy)._wanted()
check('it reads exactly one setting, and asks for it with default False',
      _spy.asked == [('pov_fast_navigation', False)], repr(_spy.asked))

# --------------------------------------------------------------------------
# SABOTAGE -- the checks must be able to fail
# --------------------------------------------------------------------------
print()
print('=== sabotage ===')

moved = SRC.replace('        %s,\n' % GUARD, '', 1)
check('SABOTAGE: removing the first entry changes the source', moved != SRC)
check('SABOTAGE: the guard no longer running first is caught',
      steps_of(moved)[0] != GUARD)

# Two ways to turn "OFF unless asked" into "ON unless asked", and the checks
# above have to notice both.
lenient = GSRC.replace('get_bool(SETTING_FAST, False)',
                       'get_bool(SETTING_FAST, True)', 1)
check('SABOTAGE: widening the fallback default changes the source',
      lenient != GSRC)
check('SABOTAGE: an untouched setting turning reuse ON is caught',
      load_guard(lenient, _KU(_KU.UNSET))._wanted() != 'false')

blind = GSRC.replace('    if kodi_utils is None:\n        return SAFE',
                     '    if kodi_utils is None:\n        return FAST', 1)
check('SABOTAGE: flipping the no-settings path changes the source',
      blind != GSRC)
check('SABOTAGE: a device with no settings store defaulting to ON is caught',
      load_guard(blind, None)._wanted() != 'false')


# --- the pass's own cost, which nobody was re-deriving -------------------
# The wait under every step was introduced when this tuple had TWENTY-SIX
# entries -- 6.5 seconds of yielding, which is what that change was tested at.
# Nobody re-derived it as steps were added, so by 63 steps the same line cost
# 15.75 seconds of pure sleeping on every boot. Two independent reviews
# measured it. It is a budget now, and this is the assertion that keeps it one.
print()
print('=== the pacing is a budget, not a constant per step ===')
_STEPS = steps_of(SRC)
print('   %d steps' % len(_STEPS))
_pace_src = [n for n in ast.walk(ast.parse(SRC))
             if isinstance(n, ast.Assign)
             and any(getattr(t, 'id', '') == '_pace' for t in n.targets)]
check('the per-step wait is computed, not a literal', len(_pace_src) == 1)
check('...and nothing waits on a bare 0.25 any more',
      'waitForAbort(0.25)' not in SRC)
check('...it is what the loop actually waits on',
      'waitForAbort(_pace)' in SRC)

_ns = {}
exec(compile(ast.Expression(_pace_src[0].value), '<pace>', 'eval'), {},
     _ns) if False else None
_pace = eval(compile(ast.Expression(_pace_src[0].value), '<pace>', 'eval'),
             {'max': max, 'min': min, 'len': len}, {'steps': _STEPS})
_total = _pace * len(_STEPS)
print('   pace %.3fs -> %.2fs total (a flat 0.25 would be %.2fs)'
      % (_pace, _total, 0.25 * len(_STEPS)))
check('the whole pass yields about what 26 steps used to', _total <= 7.0,
      'the pass sleeps %.2fs before doing any work' % _total)
check('...and each step still yields enough to be a yield', _pace >= 0.05)
check('...and never more than the figure it replaced', _pace <= 0.25)
# STEP 64 IS FREE, which is the property being pinned -- up to the point where
# the per-step FLOOR takes over from the budget. Past that the total grows
# again, on purpose: a yield of nothing is not a yield. What must never happen
# is that it grows SILENTLY, the way 0.25 did for 37 steps, so the source has
# to warn when the floor starts binding.
for _n in (26, 63, 120, 130):
    _p = eval(compile(ast.Expression(_pace_src[0].value), '<pace>', 'eval'),
              {'max': max, 'min': min, 'len': len}, {'steps': [0] * _n})
    check('%d steps still yields <= 7s in total' % _n, _p * _n <= 7.0,
          '%.2fs' % (_p * _n))
_p400 = eval(compile(ast.Expression(_pace_src[0].value), '<pace>', 'eval'),
             {'max': max, 'min': min, 'len': len}, {'steps': [0] * 400})
check('past the floor it does grow -- that is the trade, not a bug',
      _p400 * 400 > 7.0)
check('...and the source says so out loud when it starts to',
      'the per-step floor is binding' in SRC
      and "level='WARNING'" in SRC.split('_pace = ')[1][:1200],
      'a pass that grows again must not do it silently')


# --- a step that ABORTS the pass may not do it silently ------------------
# `except Exception` does not catch SystemExit or KeyboardInterrupt, so a
# patcher raising either ended the whole pass -- and everything queued behind
# it, including the step that puts Hebrew subtitles on screen -- with nothing
# whatsoever in the log. HANDOFF records a patcher raising SystemExit as a
# thing that has actually happened here.
print()
print('=== an aborted pass says so ===')
_loop = [f for f in ast.walk(ast.parse(SRC)) if isinstance(f, ast.FunctionDef)
         and f.name == '_run_build_startup_repairs']
check('the pass was found', len(_loop) == 1)
if _loop:
    _handlers = [h for n in ast.walk(_loop[0])
                 if isinstance(n, ast.Try) for h in n.handlers
                 if isinstance(h.type, ast.Name)]
    _names = {h.type.id for h in _handlers}
    check('BaseException is handled, not only Exception',
          'BaseException' in _names, str(sorted(_names)))
    _base = [h for h in _handlers if h.type.id == 'BaseException']
    check('...and it is re-raised, so an aborted pass never looks finished',
          any(isinstance(n, ast.Raise) for h in _base for n in ast.walk(h)))
    check('...after saying which step and what it raised',
          any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == 'log' for h in _base for n in ast.walk(h)))
    check('...and the finished marker is still outside every handler',
          '_publish_repairs_state(_addon_version())' in SRC
          and SRC.index('_publish_repairs_state(_addon_version())')
          > SRC.index('build startup repair'))


# --- the steps this release added are placed, and pinned ------------------
# This file pinned three orderings and said nothing about anything else, so
# five new steps went in with no assertion about where. None of them conflicts
# today -- checked file by file -- and this records that rather than leaving
# the next person to re-derive it.
print()
print('=== where this release put its new steps ===')
NEW = ('_maybe_fix_fentastic_clearlogo_var', '_maybe_time_pov_directories',
       '_maybe_repair_addon_autoupdate', '_maybe_log_pov_debrid_errors',
       '_maybe_keep_sources_when_debrid_is_late')
for _n in NEW:
    check('%s is in the pass' % _n, _n in _STEPS)
check('every one of them is after the language-invoker guard',
      all(_STEPS.index(n) > 0 for n in NEW if n in _STEPS))
check('...and the two debrid patchers are adjacent, in the order they read',
      abs(_STEPS.index('_maybe_log_pov_debrid_errors')
          - _STEPS.index('_maybe_keep_sources_when_debrid_is_late')) == 1)
check('...and all of them before the step that reloads POV',
      all(_STEPS.index(n) < _STEPS.index('_maybe_reload_for_tiles')
          for n in NEW if n in _STEPS),
      'a patch applied after the reload waits a whole boot to take effect')

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
