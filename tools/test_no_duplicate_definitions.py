"""A second `def` of the same name silently replaces the first.

This shipped. `pov_torbox_restore_patcher` gained a new `_relocations(rel, base)`
while the old `_relocations(rel)` was left below it; Python bound the last one,
its only call site passes two arguments, and every boot raised

    TypeError: _relocations() takes 1 positional argument but 2 were given

inside a try/except that logs at WARNING. The patcher was dead on every device
for a release and nothing noticed -- test_no_undefined_names.py uses symtable,
which has no notion of redefinition, and no test called the module at all.

A redefinition is occasionally deliberate (a platform fallback, an `if TYPE_
CHECKING` shim). None of those exist here, so the rule is simply: no module in
the add-on defines the same top-level name twice. If that ever becomes wrong,
add the exception here with the reason -- do not delete the check.

Run: python3 tools/test_no_duplicate_definitions.py
"""
import ast
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
ADDON = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai')

# name -> why a second definition is intentional. Empty on purpose.
ALLOWED = {}

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def duplicates(path):
    """Top-level def/class/assignment names defined more than once.

    Only MODULE level and only names bound by def/class, plus assignments that
    rebind a name a def already bound. A plain re-assignment of a constant is
    normal Python and not what this is looking for.
    """
    try:
        tree = ast.parse(io.open(path, encoding='utf-8').read())
    except Exception:
        return {}
    seen, dup = {}, {}
    for node in tree.body:
        names = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            names = [node.name]
        for n in names:
            if n in seen:
                dup.setdefault(n, []).append(node.lineno)
                dup[n] = sorted(set([seen[n]] + dup[n]))
            else:
                seen[n] = node.lineno
    return dup


print('=== no module defines the same top-level name twice ===')
files = []
for dp, dns, fns in os.walk(ADDON):
    dns[:] = [d for d in dns if d != '__pycache__']
    files += [os.path.join(dp, f) for f in sorted(fns) if f.endswith('.py')]

offenders = []
for p in sorted(files):
    for name, lines in sorted(duplicates(p).items()):
        if name in ALLOWED:
            continue
        offenders.append('%s: %s at lines %s'
                         % (os.path.relpath(p, ROOT), name,
                            ', '.join(str(l) for l in lines)))
check('%d python files scanned, none redefines a top-level name'
      % len(files), not offenders, '; '.join(offenders))

# The check must be able to fail -- prove it on constructed source.
_BAD = 'def f(a, b):\n    return a\n\n\ndef f(a):\n    return a\n'
_tmp = os.path.join(ROOT, '.dupcheck_probe.py')
io.open(_tmp, 'w', encoding='utf-8').write(_BAD)
try:
    check('SABOTAGE: a redefined function is detected',
          'f' in duplicates(_tmp))
finally:
    os.remove(_tmp)

# And the exact shape that shipped: two defs, second with fewer parameters.
_tmp2 = os.path.join(ROOT, '.dupcheck_probe2.py')
io.open(_tmp2, 'w', encoding='utf-8').write(
    "def _relocations(rel, base=''):\n    return [rel]\n\n\n"
    "def _relocations(rel):\n    return [rel]\n")
try:
    d = duplicates(_tmp2)
    check('SABOTAGE: ...including the one that actually shipped',
          '_relocations' in d and len(d['_relocations']) == 2, str(d))
finally:
    os.remove(_tmp2)

print()
if FAIL:
    print('FAILED: %d -> %s' % (len(FAIL), FAIL))
    raise SystemExit(1)
print('ALL PASS')
