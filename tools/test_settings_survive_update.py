#!/usr/bin/env python3
"""An update must not throw away the settings the user changed today.

THE REPORT: audio passthrough switched itself off after an update. Passthrough
is a setting somebody sets once, on purpose, and notices the moment it stops
working -- which is why this one surfaced and the others did not.

THE MECHANISM: Kodi keeps its settings in memory and writes guisettings.xml on
shutdown. The wizard does not shut Kodi down; it calls os._exit(1), which skips
that write. So every setting changed since Kodi started -- passthrough, audio
device, subtitle size, anything -- reverts to whatever was last on disk.

That kill is CORRECT where it came from. A build install has just extracted a
guisettings.xml and an Addons33.db over a running Kodi, and a shutdown save
would overwrite both (the skin reverts to Estuary, add-ons come back disabled).
The skin switch edits guisettings.xml on disk for the same reason. In those
paths the unsaved memory is the enemy.

The quick update is the opposite case, and it inherited the kill anyway. Its
zip carries addons/, media/, userdata/keymaps/ and the wizard -- no
guisettings.xml, no .db -- so there is nothing a save could overwrite and
everything to lose by skipping it.

WHAT THIS PINS:

  * kill_kodi can close gracefully, and still falls back to the hard kill if
    the graceful close does not take;
  * EVERY close site is classified here by hand. A new one that is not in the
    table fails this test rather than quietly inheriting the kill;
  * and the premise itself, checked against the real artifacts: the quickfix
    zip contains no guisettings.xml and no .db, and the full build contains
    both.

Run: python3 tools/test_settings_survive_update.py
"""
import ast
import io
import os
import re
import sys
import types
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
WIZ = os.path.join(ROOT, 'wizard', 'source', 'plugin.program.kodipovilwizard')
TOOLS_PY = os.path.join(WIZ, 'resources', 'libs', 'common', 'tools.py')
WIZARD_PY = os.path.join(WIZ, 'resources', 'libs', 'wizard.py')
STARTUP_PY = os.path.join(WIZ, 'startup.py')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def _read(path):
    return io.open(path, encoding='utf-8').read()


def _func(src, name):
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    return None


# --- 1. kill_kodi can save on the way out -----------------------------------
print('=== kill_kodi learned to close instead of only killing ===')
_tools_src = _read(TOOLS_PY)
_kill = _func(_tools_src, 'kill_kodi')
check('kill_kodi was found', _kill is not None)

_args = [a.arg for a in _kill.args.args] if _kill else []
check('it takes a graceful flag', 'graceful' in _args,
      'signature is %s' % _args)

# The default has to stay the kill. Every caller that was written before this
# flag existed needed it, and a default of True would silently change all of
# them -- including the build install, where a shutdown save overwrites the
# guisettings.xml that was just extracted.
_defaults = dict(zip(_args[len(_args) - len(_kill.args.defaults):],
                     _kill.args.defaults)) if _kill else {}
_g = _defaults.get('graceful')
check('...defaulting to the hard kill, so nothing changes by accident',
      isinstance(_g, ast.Constant) and _g.value is False,
      'default is %s' % (ast.dump(_g) if _g is not None else None))

_builtins = [n for n in ast.walk(_kill) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == 'executebuiltin'
             and n.args and isinstance(n.args[0], ast.Constant)
             and n.args[0].value == 'Quit'] if _kill else []
check('the graceful path asks Kodi to Quit', len(_builtins) == 1,
      'Quit is what makes Kodi write guisettings.xml on the way out')

_waits = [n for n in ast.walk(_kill) if isinstance(n, ast.Call)
          and isinstance(n.func, ast.Attribute)
          and n.func.attr == 'waitForAbort'] if _kill else []
check('...and waits for Kodi to accept it', len(_waits) == 1)

_exits = [n for n in ast.walk(_kill) if isinstance(n, ast.Call)
          and isinstance(n.func, ast.Attribute)
          and n.func.attr == '_exit'] if _kill else []
check('the hard kill is still reachable as the fallback', len(_exits) == 1,
      'a Quit that never takes must not leave Kodi running forever')

# and the fallback must be OUTSIDE the graceful branch, not inside it: a
# graceful close that succeeds returns, everything else falls through to _exit.
_graceful_ifs = [n for n in ast.walk(_kill) if isinstance(n, ast.If)
                 and isinstance(n.test, ast.Name)
                 and n.test.id == 'graceful'] if _kill else []
check('the graceful attempt is one branch', len(_graceful_ifs) == 1)
if _graceful_ifs and _exits:
    _inside = [n for n in ast.walk(_graceful_ifs[0]) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Attribute) and n.func.attr == '_exit']
    check('...and the kill sits after it, not inside it', not _inside,
          'a failed graceful close has to reach the kill')


# --- 1b. AND IT REALLY REACHES THE KILL -------------------------------------
# The checks above count AST nodes. They cannot tell a fallback that runs from
# one that is merely present: a single `return` added at the end of the
# graceful branch leaves `os._exit` textually outside the branch and counted
# exactly once, and every check above still passes while a Quit that never
# takes leaves Kodi running for good. So run the function.
print()
print('=== the fallback is reached, not merely present ===')


def _run_kill(graceful, quit_taken=True, monitor_raises=False,
              logger_raises=False):
    """Execute the REAL kill_kodi with a fake Kodi.

    Returns (exit_calls, builtins_issued, returned_normally, raised).
    """
    tree = ast.parse(_tools_src)
    fn = [n for n in tree.body
          if isinstance(n, ast.FunctionDef) and n.name == 'kill_kodi']
    mod = ast.Module(body=fn, type_ignores=[])
    ast.fix_missing_locations(mod)

    exits, builtins_run = [], []

    class _Monitor(object):
        def waitForAbort(self, secs):
            return bool(quit_taken)

    class _Xbmc(object):
        LOGWARNING = 2

        def Monitor(self):
            if monitor_raises:
                raise RuntimeError('this box has no monitor')
            return _Monitor()

        def executebuiltin(self, cmd):
            builtins_run.append(cmd)

    def _log(*a, **k):
        if logger_raises:
            raise IOError('the wizard log file cannot be written')

    logging_mod = types.ModuleType('resources.libs.common.logging')
    logging_mod.log = _log
    for name, parent in (('resources', None),
                         ('resources.libs', 'resources'),
                         ('resources.libs.common', 'resources.libs')):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules['resources.libs.common'].logging = logging_mod
    sys.modules['resources.libs.common.logging'] = logging_mod

    ns = {
        'os': types.SimpleNamespace(_exit=lambda code: exits.append(code)),
        'xbmc': _Xbmc(),
        'xbmcgui': types.SimpleNamespace(Dialog=lambda: None),
        'CONFIG': types.SimpleNamespace(COLOR2='white'),
        'platform': lambda: 'android',
    }
    exec(compile(mod, TOOLS_PY, 'exec'), ns)
    raised = None
    returned = False
    try:
        ns['kill_kodi'](over=True, graceful=graceful)
        returned = True
    except BaseException as e:      # SystemExit is not an Exception
        raised = e
    return exits, builtins_run, returned, raised


exits, builtins_run, returned, raised = _run_kill(graceful=False)
check('a hard close kills and never asks Kodi to quit',
      exits == [1] and not builtins_run and raised is None,
      'exits=%s builtins=%s raised=%r' % (exits, builtins_run, raised))

exits, builtins_run, returned, raised = _run_kill(graceful=True,
                                                  quit_taken=True)
check('a graceful close that IS accepted returns without killing',
      not exits and builtins_run == ['Quit'] and returned and raised is None,
      'exits=%s builtins=%s raised=%r' % (exits, builtins_run, raised))

exits, builtins_run, returned, raised = _run_kill(graceful=True,
                                                  quit_taken=False)
check('a Quit that never takes still ends in the kill', exits == [1],
      'Kodi would be left running after telling the user it would close')

exits, _b, _r, raised = _run_kill(graceful=True, monitor_raises=True)
check('a box that cannot give us a Monitor still ends in the kill',
      exits == [1] and raised is None, 'exits=%s raised=%r' % (exits, raised))

# THE ONE THAT WAS ACTUALLY BROKEN. The failure handler logged, the wizard's
# logger writes a FILE, and startup.py already carries a comment about a
# handler that fails because writing that file is what went wrong. Raising
# there walked straight past os._exit and out of the function.
exits, _b, _r, raised = _run_kill(graceful=True, quit_taken=False,
                                  logger_raises=True)
check('a logger that is itself broken does not skip the kill',
      exits == [1] and raised is None,
      'exits=%s raised=%r -- Kodi stays up and the user was told it would '
      'close' % (exits, raised))


# --- 2. every close site is classified by hand ------------------------------
# NO DEFAULTS. The bug this file exists for was a call site that inherited a
# behaviour nobody had thought about for it. So the rule is: name every site
# in the wizard that closes Kodi, say which side it is on, and let an unlisted
# one fail -- including the ones that call kill_kodi directly and never go
# near force_close_kodi_in_5_seconds.
print()
print('=== every close site is on a side, deliberately ===')

GRACEFUL = 'GRACEFUL'   # nothing extracted that a settings save could clobber
HARD = 'HARD'           # a file was just written under a running Kodi

# (file relative to the wizard addon, enclosing function) -> side, and why.
SITES = {
    ('startup.py', 'auto_quick_update'): (
        GRACEFUL, 'the quickfix zip ships no guisettings.xml and no .db'),
    ('resources/libs/wizard.py', 'quick_update'): (
        GRACEFUL, 'same package, started by hand instead of at startup'),

    ('resources/libs/wizard.py', 'build'): (
        HARD, 'the build zip extracted userdata/guisettings.xml + Addons33.db'),
    ('startup.py', 'fresh_build_auto_install_if_needed'): (
        HARD, 'same, on the automatic first-run install'),
    ('resources/libs/wizard.py', 'build_switch_skin'): (
        HARD, 'switch_skin_in_gui_settings just edited guisettings.xml on '
              'disk; a save would put the old skin straight back'),
    ('resources/libs/wizard.py', 'gui'): (
        HARD, 'the guifix zip IS a guisettings package, and this path also '
              'calls skin_to_default + look_and_feel_data(save)'),
    ('resources/libs/install.py', 'fresh_start'): (
        HARD, 'wipes userdata and restores defaults'),
    ('resources/libs/restore.py', '_from_file'): (
        HARD, 'restores a backup over the running profile'),
    ('resources/libs/db.py', 'fix_update'): (
        HARD, 'rewrites the addon databases underneath Kodi'),
    ('resources/libs/clear.py', 'remove_addon_menu'): (
        HARD, 'removes addons and their db rows'),
    ('resources/libs/advanced.py', 'write_advanced'): (
        HARD, 'wrote advancedsettings.xml; unchanged from before this flag'),
    ('resources/libs/common/router.py', 'dispatch'): (
        HARD, 'the user picked "Force Close Kodi" from the menu'),

    # not a site of its own -- the shared helper both flavours funnel through
    ('resources/libs/wizard.py', 'restart_kodi'): (
        None, 'forwards whatever its caller asked for'),
}


def _close_sites():
    """Every call in the wizard that closes Kodi, and how it closes it."""
    found = {}
    for root, _dirs, files in os.walk(WIZ):
        for fn in sorted(files):
            if not fn.endswith('.py'):
                continue
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, WIZ).replace(os.sep, '/')
            try:
                tree = ast.parse(_read(path))
            except SyntaxError:
                continue
            stack = []

            def walk(node):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    stack.append(node.name)
                    for child in ast.iter_child_nodes(node):
                        walk(child)
                    stack.pop()
                    return
                if isinstance(node, ast.Call):
                    name = (node.func.attr
                            if isinstance(node.func, ast.Attribute)
                            else getattr(node.func, 'id', None))
                    if name in ('kill_kodi', 'force_close_kodi_in_5_seconds'):
                        how = HARD
                        for kw in node.keywords:
                            if kw.arg != 'graceful':
                                continue
                            if isinstance(kw.value, ast.Constant):
                                how = GRACEFUL if kw.value.value else HARD
                            else:
                                how = None   # forwarded, not decided here
                        # A LIST, NOT A DICT WRITE. This was `found[key] =
                        # ...`, and a second close call added ABOVE an
                        # existing one in the same function silently
                        # overwrote it -- the earlier call was never checked
                        # against anything, and a wrongly-graceful one added
                        # to Wizard.gui() passed this whole section. Proved
                        # with a mutated copy of gui(), not argued.
                        key = (rel, stack[-1] if stack else '<module>')
                        found.setdefault(key, []).append((how, node.lineno))
                for child in ast.iter_child_nodes(node):
                    walk(child)

            walk(tree)
    return found


_seen = _close_sites()

# EVERY call, not one per function. A function with two closes has to have
# them agree, because the table can only say one thing about it -- and a
# function that grew a second, differently-classified close is exactly the
# edit this section exists to catch.
_split = sorted(k for k, v in _seen.items() if len({h for h, _l in v}) > 1)
check('no function closes Kodi two different ways', not _split,
      'split verdicts in %s -- the table cannot describe that; give the new '
      'call its own function, or make both sides agree' % _split)

_unclassified = sorted(k for k in _seen if k not in SITES)
check('no close site is missing from the table', not _unclassified,
      'unclassified: %s -- decide whether a shutdown save would overwrite '
      'something that site just wrote, then add it' % _unclassified)

_gone = sorted(k for k in SITES if k not in _seen)
check('...and the table has no sites that no longer exist', not _gone,
      'stale: %s' % _gone)

for key in sorted(SITES):
    if key not in _seen:
        continue
    want, why = SITES[key]
    for got, lineno in _seen[key]:
        check('%s:%s (%s) is %s'
              % (key[0], lineno, key[1], want or 'FORWARDED'),
              got == want, 'it is %s -- the table says %s: %s'
              % (got or 'FORWARDED', want or 'FORWARDED', why))

# and the two that matter most, spelled out rather than left to the table:
_graceful = sorted(k for k, v in _seen.items()
                   if any(h == GRACEFUL for h, _l in v))
check('the quick update is the ONLY thing that closes gracefully',
      _graceful == [('resources/libs/wizard.py', 'quick_update'),
                    ('startup.py', 'auto_quick_update')],
      'graceful sites: %s' % _graceful)

# A GRACEFUL CLOSE RETURNS, AND EVERY CLOSE BEFORE THIS ONE DID NOT. So each
# graceful site has to stop its caller. startup.py's automatic path is the
# one that matters: ~110 lines run below its call site, including two network
# checks, an 11 MB pack install and an ActivateWindow, and before this change
# none of them could ever be reached because kill_kodi never came back.
_auto = _read(STARTUP_PY)
_at = _auto.index('def auto_quick_update')
_body = _auto[_at:_auto.index('\ndef ', _at + 10)]
check('auto_quick_update reports that it closed Kodi',
      _body.rstrip().endswith('return True'),
      'it closes and then returns None, so its caller cannot tell')
# EVERY OTHER RETURN HAS TO BE FALSY, and "the last line says return True" did
# not check that. The caller is `if auto_quick_update(): sys.exit()`, so a
# truthy return from any of the nine paths that did NOT close Kodi ends the
# startup script early -- skipping the hooks below it -- while this check
# still passed.
_fn = [n for n in ast.walk(ast.parse(_auto))
       if isinstance(n, ast.FunctionDef) and n.name == 'auto_quick_update']
check('auto_quick_update was found to inspect', len(_fn) == 1)
if _fn:
    _returns = [n for n in ast.walk(_fn[0]) if isinstance(n, ast.Return)]
    _truthy = [n.lineno for n in _returns
               if n.value is not None
               and not (isinstance(n.value, ast.Constant)
                        and not n.value.value)]
    check('exactly one return is truthy, and it is the last line',
          len(_truthy) == 1 and _truthy[0] == max(n.lineno for n in _returns),
          'truthy returns at lines %s of %d returns' % (_truthy,
                                                        len(_returns)))
# the CALL site, not the def -- `sync_quickfix_build_version()` appears first
# as a definition two hundred lines earlier, and anchoring on it found that
# instead and reported a fix that was in place as missing.
_callsite = _auto[_auto.index('# KODI-RD-IL - AUTO QUICK UPDATE'):][:500]
check('...and its caller stops when it does',
      'if auto_quick_update():' in _callsite and 'sys.exit()' in _callsite,
      'the rest of startup.py runs against a Kodi that is shutting down')


# --- 3. the premise, against the real zips ----------------------------------
# The whole argument rests on one factual claim about the two packages. If a
# future quickfix starts shipping a guisettings.xml, the graceful close becomes
# wrong and this is where that gets caught.
print()
print('=== the packages are what the argument assumes ===')
DIST = os.path.join(ROOT, 'dist')


def _newest(pattern):
    rx = re.compile(pattern)
    best, best_n = None, -1
    for name in os.listdir(DIST):
        m = rx.match(name)
        if not m:
            continue
        try:
            n = tuple(int(p) for p in m.group(1).split('.'))
        except ValueError:
            continue
        if n > (best_n if isinstance(best_n, tuple) else (-1,)):
            best, best_n = name, n
    return os.path.join(DIST, best) if best else None


def _entries(zpath):
    with zipfile.ZipFile(zpath) as z:
        return z.namelist()


_qf = _newest(r'Kodi-POV-IL-FENtastic-quickfix-([0-9.]+)\.zip$')
check('a quickfix package was found to inspect', _qf is not None)
if _qf:
    names = _entries(_qf)
    bad = [n for n in names
           if n.lower().endswith(('guisettings.xml', '.db'))]
    check('%s carries no guisettings.xml and no .db'
          % os.path.basename(_qf), not bad,
          'it now ships %s -- the graceful close would overwrite them; make '
          'that site HARD again' % bad[:5])

_build = _newest(r'Kodi-POV-IL-FENtastic-test-([0-9.]+)\.zip$')
check('a full build package was found to inspect', _build is not None)
if _build:
    names = _entries(_build)
    check('%s does carry them, which is why IT keeps the hard kill'
          % os.path.basename(_build),
          any(n.lower().endswith('userdata/guisettings.xml') for n in names)
          and any(n.lower().endswith('.db') for n in names))

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
