#!/usr/bin/env python3
"""No name is read that nothing ever defines.

WHY THIS EXISTS. An edit of mine glued two module-level assignments into

    _cycled = False_pending = False

which is a perfectly legal chained assignment to a variable named
False_pending. It compiled. The module imported. `_pending` simply never
existed -- so reload_if_patched raised NameError into service.py's bare
except, and the POV cycle silently never happened again, for everyone.

A compile check passed it. A thirty-check test file passed it. A full suite
sweep passed it. None of them CALLED the function; they all tested around it.
That is the shape of the bug this file is for: a name that is only wrong at
the moment it is read, inside a try/except that swallows, on a path no test
walks.

Running it over the whole add-on immediately found three more, all real, all
in the SubSync human-delay watch: `json` used by two nested functions with
nothing named json in scope, and `kodi_utils` in a third. Every one of them
sat inside its own `except Exception`, so the delay probe returned 0.0 for
ever and the watch never started -- the community never received a single
human sync report from that path, and nothing anywhere said so.

HOW IT DECIDES. CPython's own symtable, not a hand-rolled scope walk -- the
same tool this project already leans on for exactly this reason. A name is
reported when it is READ, resolves to module scope, and is neither assigned
nor imported at module level, nor declared `global` and assigned somewhere,
nor a builtin. That last pair matters: a module-level global written only from
inside a function is a normal pattern and is not a defect.

WHAT IT DOES NOT CATCH, said plainly, because the whole reason this file
exists is a guard that looked like it covered more than it did. A global that
is only ever assigned from inside a function counts as defined here -- and it
IS defined, from the moment that function runs. Read it BEFORE then and it is
a NameError the scan cannot see. That is exactly what `_pending` was after the
glued line: `note_patched()` declared it global and assigned it, so the scan
was satisfied, while `reload_if_patched()` read it on a path that ran first.
The named checks at the bottom cover that one instance; the scan does not
generalise it, and pretending otherwise would be the same mistake again.

It misses one more, found by the review: CPython runs an implicit `del name`
at the end of every `except E as name:` block, so reading that name after the
block is a guaranteed NameError whenever the handler fired -- and symtable
records it as an ordinary local assignment with no notion of the auto-del. No
such pattern exists in this tree today.

And it can be WRONG the other way, which is worse, because a false positive
blocks a legitimate change. A file using `from x import *` and then reading a
name that star-import provides is flagged as undefined, because symtable
cannot see through the star. The tree's one star-import lives in the vendored
pyxbmct, which passes today only because it happens to re-export through
__all__ string literals rather than reading such a name -- an accident of
style, not a property. pyxbmct is skipped for that reason, alongside the other
vendored trees.

WHAT IS EXEMPT, and why each one:
  * vendored third-party under subs_engine/_libs -- not ours to fix;
  * pool.py -- not read by anything here, deliberately;
  * the one entry in ALLOWED below, which is a Python-2 shim in the vendored
    srt parser, guarded by `except NameError` and annotated as such upstream.

Run: python3 tools/test_no_undefined_names.py
"""
import builtins
import io
import os
import symtable
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
ADDON = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai')

BUILTIN = set(dir(builtins)) | {
    '__file__', '__name__', '__doc__', '__package__', '__spec__',
    '__loader__', '__builtins__', '__path__',
}

# (path suffix, name) -> why it is allowed to be undefined.
ALLOWED = {
    ('subs_engine/srt.py', 'file'):
        'Python-2 shim in the vendored srt parser: `FILE_TYPES = (file, '
        'io.IOBase)` inside try/except NameError, annotated upstream with '
        '# pytype: disable=name-error.',
}

SKIP_DIRS = ('__pycache__', os.path.join('subs_engine', '_libs'),
             'pyxbmct')
SKIP_FILES = ('pool.py',)

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def _defined_globals(table, acc):
    for sym in table.get_symbols():
        if (table.get_type() == 'module'
                and (sym.is_assigned() or sym.is_imported()
                     or sym.is_parameter())):
            acc.add(sym.get_name())
        # A global written only from inside a function is still defined.
        if sym.is_declared_global() and sym.is_assigned():
            acc.add(sym.get_name())
    for child in table.get_children():
        _defined_globals(child, acc)
    return acc


def _undefined(table, defined, path, out):
    for sym in table.get_symbols():
        name = sym.get_name()
        if (sym.is_assigned() or sym.is_parameter() or sym.is_imported()
                or not sym.is_referenced()):
            continue
        # Only names that resolve to module scope can be undefined this way;
        # a free variable is bound by an enclosing function.
        if sym.is_global() or table.get_type() == 'module':
            if name not in defined and name not in BUILTIN:
                out.append((path, table.get_name(), name))
    for child in table.get_children():
        _undefined(child, defined, path, out)
    return out


def scan():
    found, scanned = [], 0
    for root, _dirs, files in os.walk(ADDON):
        if any(s in root for s in SKIP_DIRS):
            continue
        for fn in sorted(files):
            if not fn.endswith('.py') or fn in SKIP_FILES:
                continue
            path = os.path.join(root, fn)
            src = io.open(path, encoding='utf-8').read()
            table = symtable.symtable(src, path, 'exec')
            _undefined(table, _defined_globals(table, set()), path, found)
            scanned += 1
    return scanned, found


scanned, found = scan()
check('the scan actually read the add-on', scanned > 100,
      'only %d files' % scanned)

rel = [(os.path.relpath(p, ADDON).replace(os.sep, '/'), scope, name)
       for p, scope, name in found]
unexplained = [r for r in rel
               if not any(r[0].endswith(k[0]) and r[2] == k[1]
                          for k in ALLOWED)]
for r in sorted(unexplained):
    print('     %s :: %s :: %s' % r)
check('every name read in this add-on is defined somewhere', not unexplained,
      '%d undefined: %s' % (len(unexplained), sorted(unexplained)))

# The exemptions have to still be real, or they are just a place to hide.
still = {(p, n) for p, _s, n in rel}
for (suffix, name), why in sorted(ALLOWED.items()):
    check('the exemption for %s in %s is still needed' % (name, suffix),
          any(p.endswith(suffix) and n == name for p, n in still),
          'nothing reports it any more -- delete the exemption: ' + why)

# And the two bugs that prompted this, by name, so a revert is loud.
_svc = io.open(os.path.join(ADDON, 'service.py'), encoding='utf-8').read()
check('service.py imports json, which two nested functions call',
      '\nimport json\n' in _svc)
check('the delay watch imports kodi_utils, which its loop logs through',
      'from resources.lib import kodi_utils\n            import xbmcgui'
      in _svc)
_pr = io.open(os.path.join(ADDON, 'resources', 'lib', 'pov_reload.py'),
              encoding='utf-8').read()
check('pov_reload defines _pending on its own line',
      '\n_pending = False\n' in _pr,
      'the glued `_cycled = False_pending = False` is legal Python and ends '
      'the cycle for ever')

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
