#!/usr/bin/env python3
"""Umbrella has to actually be on the device the build assumes it is on.

Half this build already behaves as though Umbrella were installed. The home
screen carries Umbrella tiles, the search wiring has an Umbrella branch, the
account manager pushes debrid accounts into it, and a dozen patchers in the AI
add-on exist for no other reason than to make it speak Hebrew. On a device
without it, every one of those quietly does nothing -- and a field log shows
exactly that, one line, at the moment the home patcher asks:

    19:53:17.708  EXCEPTION: Unknown addon id 'plugin.video.umbrella'

It was a pilot behind a menu entry, so whether a device had it came down to
whether somebody went looking. That is now an automatic, once-per-device
install on the same terms as Account Manager, which went through this exact
transition earlier and whose shape is copied deliberately.

WHAT THIS PINS -- the guards, because each one is a way for an automatic
install to become a nuisance:

  * ONCE. A marker setting, written only after the install actually
    succeeded, so a device that was offline retries and a device that has it
    never pays again;
  * and never written on failure, which is the difference between "retries
    tomorrow" and "never again";
  * the build must be installed first -- the pack registers add-ons in a
    database a half-installed device does not have yet;
  * it never raises: it runs from startup.py, and an exception there used to
    be able to stop the rest of the startup script;
  * and the startup hook exists, after the Account Manager one.

Run: python3 tools/test_umbrella_for_everyone.py
"""
import ast
import io
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
WIZ = os.path.join(ROOT, 'wizard', 'source', 'plugin.program.kodipovilwizard')
WIZARD_PY = os.path.join(WIZ, 'resources', 'libs', 'wizard.py')
STARTUP_PY = os.path.join(WIZ, 'startup.py')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


_wsrc = io.open(WIZARD_PY, encoding='utf-8').read()
_wtree = ast.parse(_wsrc)
_ssrc = io.open(STARTUP_PY, encoding='utf-8').read()


def func(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    return None


# --- 1. the function, and the guards that make it safe to run at startup ---
print('=== the once-per-device install ===')
fn = func(_wtree, 'ensure_umbrella_for_everyone')
check('ensure_umbrella_for_everyone exists', fn is not None)

if fn:
    src = ast.get_source_segment(_wsrc, fn) or ''

    check('it installs through the shared pack path',
          [n for n in ast.walk(fn) if isinstance(n, ast.Call)
           and isinstance(n.func, ast.Name)
           and n.func.id == 'ensure_umbrella_installed'],
          'the pack path is what registers the add-ons in Kodi\'s database; '
          'extracting files alone leaves them invisible')

    # THE MARKER MUST BE WRITTEN AFTER THE INSTALL SUCCEEDED, never before.
    # Written first, a device that is offline at the wrong moment is marked
    # done and never gets Umbrella at all.
    set_calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == 'set_setting']
    # TWO writes now, and they are different promises. One records "installed";
    # the other records "this user already removed it, stop asking" and is
    # deliberately BEFORE the install, because on that path there is no install.
    check('the marker is written exactly twice', len(set_calls) == 2,
          'found %d' % len(set_calls))
    install_at = src.index('ok = ensure_umbrella_installed()')
    marker_at = src.rindex('set_setting')
    check('...and the one that means "installed" comes AFTER the install',
          install_at < marker_at,
          'a device that was offline would be marked done and never retry')
    check('...while the one that means "already removed" comes before it',
          src.index('set_setting') < install_at)

    # and the early return on failure has to come between them.
    ok_check = src.index('if not ok:')
    check('a failed install returns before the marker',
          install_at < ok_check < marker_at,
          'no early return means a failure still counts as done')

    check('it reads the marker before doing anything',
          src.index('get_setting') < install_at,
          'without the read it downloads on every single boot')

    check('it refuses to run before the build is installed',
          "get_setting('buildname')" in src,
          'the pack registers add-ons in a database a half-installed device '
          'does not have yet')

    handlers = [n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)]
    check('it never raises', handlers,
          'it runs from startup.py, where an exception stops the rest of the '
          'startup script')
    check('...and the handler swallows rather than re-raises',
          not [n for h in handlers for n in ast.walk(h)
               if isinstance(n, ast.Raise)])


# --- 1b. AND IT IS RUN, NOT ONLY READ --------------------------------------
# Everything above inspects the source text. That is not enough, and it was
# proved not to be: a mutant with the `return False` deleted from the `if not
# ok:` block -- so the marker is written even when the install failed -- keeps
# every token in the same relative order and passes all thirteen checks above.
# The positional check can only see that the words `if not ok:` sit between
# two other words. So execute it.
print()
print('=== the guards hold when the function actually runs ===')


def run_ensure(install_ok, buildname='Kodi POV IL - FENtastic', seeded='',
               install_raises=None, was_removed=False):
    """The REAL ensure_umbrella_for_everyone, with fakes around it.

    Compiled out of wizard.py by AST so it is the shipped function, not a
    copy -- a copy would drift the first time somebody edited one of them.
    """
    calls, logged = [], []
    settings = {'umbrella_auto': seeded, 'buildname': buildname}

    def _installed():
        calls.append('install')
        if install_raises is not None:
            raise install_raises
        return install_ok

    ns = {
        'CONFIG': types.SimpleNamespace(
            get_setting=lambda k: settings.get(k, ''),
            set_setting=lambda k, v: settings.__setitem__(k, v)),
        'ensure_umbrella_installed': _installed,
        '_umbrella_was_removed': lambda: was_removed,
        'logging': types.SimpleNamespace(
            log=lambda msg, level=None: logged.append(msg)),
        'xbmc': types.SimpleNamespace(
            sleep=lambda ms: None,
            executebuiltin=lambda cmd: calls.append(cmd),
            LOGINFO=1, LOGERROR=3),
        'UMBRELLA_PACK_VERSION': '0.0.0',
    }
    # the function AND the two constants it reads. Leaving them out made every
    # call raise NameError into the function's own catch-all and return False,
    # which looked exactly like "the guard fired" -- a fake that fails closed
    # is a test that proves nothing.
    wanted = ('UMBRELLA_AUTO_SETTING', 'UMBRELLA_AUTO_DONE')
    body = [n for n in _wtree.body
            if (isinstance(n, ast.Assign)
                and any(getattr(t, 'id', '') in wanted for t in n.targets))]
    fn = [n for n in _wtree.body if isinstance(n, ast.FunctionDef)
          and n.name == 'ensure_umbrella_for_everyone']
    mod = ast.Module(body=body + fn, type_ignores=[])
    ast.fix_missing_locations(mod)
    exec(compile(mod, WIZARD_PY, 'exec'), ns)
    raised = None
    try:
        result = ns['ensure_umbrella_for_everyone']()
    except BaseException as e:
        result, raised = None, e
    return result, settings, calls, logged, raised


res, settings, calls, logged, raised = run_ensure(install_ok=True)
check('a first boot installs it', 'install' in calls and res is True,
      '%s / %r' % (calls, res))
check('...and records the marker',
      settings.get('umbrella_auto') == 'installed', str(settings))
check('...and tells Kodi to rescan, or the add-ons stay invisible',
      any('UpdateLocalAddons' in c for c in calls), str(calls))

# THE ONE THE MUTANT BROKE. An offline device, or a pack host that is down,
# must be tried again tomorrow -- not marked done forever.
res, settings, calls, _l, raised = run_ensure(install_ok=False)
check('AN INSTALL THAT FAILED DOES NOT WRITE THE MARKER',
      settings.get('umbrella_auto') in ('', None), str(settings))
check('...and says so rather than returning success', res is not True,
      'returned %r' % res)

res, settings, calls, _l, raised = run_ensure(install_ok=True,
                                              seeded='installed')
check('a device that already has it does not install again',
      'install' not in calls and res is False, '%s / %r' % (calls, res))

# A HALF-INSTALLED DEVICE IS NOT ONE TO INSTALL INTO. The pack registers its
# add-ons in a database that does not exist yet before the build is installed.
res, settings, calls, _l, raised = run_ensure(install_ok=True, buildname='')
check('a device with no build installed is left alone',
      'install' not in calls and res is False, '%s / %r' % (calls, res))
check('...and is not marked done either',
      settings.get('umbrella_auto') in ('', None), str(settings))

res, settings, calls, logged, raised = run_ensure(
    install_ok=True, install_raises=RuntimeError('the host is down'))
check('an exception is swallowed, not thrown at startup.py', raised is None,
      'it raised %r' % raised)
check('...and the marker is not written on the way out',
      settings.get('umbrella_auto') in ('', None), str(settings))


# --- 1c. the marker has to be able to persist ------------------------------
# It cannot if the id is not declared: this whole settings file declares every
# hidden flag it uses, including the Account Manager marker this one is copied
# from. Undeclared, the write is a no-op on some Kodi/Android combinations and
# the "once per device" promise becomes "a progress dialog on every boot,
# forever".
print()
print('=== the marker is declared where every other one is ===')
_settings_xml = io.open(os.path.join(WIZ, 'resources', 'settings.xml'),
                        encoding='utf-8').read()
_marker_id = None
for n in ast.walk(_wtree):
    if (isinstance(n, ast.Assign)
            and any(getattr(t, 'id', '') == 'UMBRELLA_AUTO_SETTING'
                    for t in n.targets)
            and isinstance(n.value, ast.Constant)):
        _marker_id = n.value.value
check('the marker id was found in the source', bool(_marker_id))
if _marker_id:
    check('%s is declared in the wizard settings.xml' % _marker_id,
          'id="%s"' % _marker_id in _settings_xml,
          'every other hidden flag in that file is; an undeclared one may '
          'never persist, and then this runs on every single boot')


# --- 2. the pack it installs -----------------------------------------------
print()
print('=== the pack carries what the build assumes ===')
# The pack dicts interpolate two module constants, so they are not literals.
# Executing just those three assignments is closer to the truth than a
# hand-copied duplicate here, which would go stale the first time the URL or
# the version moved and would still pass.
_WANTED = ('AF3_PACK_BASE_URL', 'UMBRELLA_PACK_VERSION', 'UMBRELLA_PACKS')
_ns = {}
_picked = [n for n in _wtree.body if isinstance(n, ast.Assign)
           and any(getattr(t, 'id', '') in _WANTED for t in n.targets)]
check('the three pack constants were found', len(_picked) == len(_WANTED),
      'found %s' % [t.id for n in _picked for t in n.targets
                    if hasattr(t, 'id')])
_mod = ast.Module(body=_picked, type_ignores=[])
ast.fix_missing_locations(_mod)
exec(compile(_mod, WIZARD_PY, 'exec'), _ns)
packs = _ns.get('UMBRELLA_PACKS')
check('UMBRELLA_PACKS was found', packs is not None)
if packs:
    ids = set()
    for pack in packs:
        ids.update(pack.get('addon_ids') or [])
    for wanted in ('plugin.video.umbrella', 'script.module.cocoscrapers'):
        check('the pack installs %s' % wanted, wanted in ids, str(sorted(ids)))
    # AND THE REPOSITORIES, which is what makes this a one-time favour rather
    # than a commitment: from the moment they land, the developers ship
    # Umbrella's updates, not us.
    for wanted in ('repository.umbrella', 'repository.cocoscrapers'):
        check('...and %s, so we are not its update channel' % wanted,
              wanted in ids, str(sorted(ids)))

# the pack really contains them, in dist/
print()
import zipfile
import re
PACK = os.path.join(ROOT, 'dist', 'Kodi-POV-IL-Umbrella-pack.zip')
check('the pack file is in dist/', os.path.isfile(PACK))
if os.path.isfile(PACK) and packs:
    with zipfile.ZipFile(PACK) as z:
        present = {m.group(1) for n in z.namelist()
                   for m in [re.match(r'^addons/([^/]+)/addon\.xml$', n)] if m}
        versions = {}
        for n in z.namelist():
            m = re.match(r'^addons/([^/]+)/addon\.xml$', n)
            if not m:
                continue
            raw = z.read(n).decode('utf-8', 'replace')
            at = raw.find('<addon')
            mv = re.search(r'\bversion="([^"]+)"', raw[at if at >= 0 else 0:])
            if mv:
                versions[m.group(1)] = mv.group(1)
    missing = sorted(set(ids) - present)
    check('every id the pack claims is really inside it', not missing,
          'claimed but absent: %s -- the DB registration would enable an '
          'add-on that is not on disk' % missing)
    expected = None
    for pack in packs:
        expected = pack.get('expected_version') or expected
    check('the version gate matches the Umbrella actually shipped',
          expected == versions.get('plugin.video.umbrella'),
          'gate says %s, pack contains %s -- a gate above the contents '
          're-downloads on every boot, one below never upgrades'
          % (expected, versions.get('plugin.video.umbrella')))


# --- 3. the startup hook ---------------------------------------------------
print()
print('=== it is actually called, and in a fixed order ===')
_am = _ssrc.find('ensure_acctmgr_for_everyone()')
_umb = _ssrc.find('ensure_umbrella_for_everyone()')
check('startup.py calls it', _umb > 0,
      'a function nobody calls installs nothing')
check('...after the Account Manager hook', 0 < _am < _umb,
      'both are one-time downloads; a fixed order keeps a first boot '
      'predictable instead of racing two progress dialogs')
check('...exactly once', _ssrc.count('ensure_umbrella_for_everyone()') == 1)

# and the call is wrapped, so a failure here cannot take the rest of startup
# down with it -- the same defence the Account Manager hook has.
_tail = _ssrc[_umb:_umb + 400]
check('the call site catches its own exceptions',
      'except Exception' in _tail, _tail[:200])


# --- somebody who already said no is not asked again ---------------------
# THE REVIEW FINDING. Umbrella has been behind a menu entry for several
# releases and that entry never wrote this setting, so a user who installed it
# there and then deliberately removed it looked exactly like a user who never
# had it -- and the new automatic install would put it back. That is the one
# thing the function's own docstring promises not to do.
print()
print('=== a deliberate removal is not undone ===')
_res, _set, _calls, _logged, _raised = run_ensure(True, was_removed=True)
check('a device that removed Umbrella is not reinstalled',
      'install' not in _calls, str(_calls))
check('...and nothing raised on the way', _raised is None, repr(_raised))
check('...and is recorded, so it is asked once and never again',
      _set.get('umbrella_auto') == 'installed', str(_set))
check('...and says why in the log',
      any('deliberate removal' in m for m in _logged), str(_logged))
_res, _set, _calls, _logged, _raised = run_ensure(True, was_removed=False)
check('a device that never had it still gets it', 'install' in _calls)

# and the evidence the decision rests on
_ns = {}
_src_w = io.open(WIZARD_PY, encoding='utf-8').read()
check('the removal test looks for settings without the add-on',
      '_umbrella_was_removed' in _src_w
      and 'addon_data/plugin.video.umbrella' in _src_w)
check('...and an EMPTY addon_data does not count as having had it',
      'dirs, files = xbmcvfs.listdir(data)' in _src_w
      and 'return bool(dirs or files)' in _src_w,
      'Kodi makes that directory the first time anything asks for a setting')
check('...and the manual entry records the marker too, so it stops guessing',
      _src_w.count('CONFIG.set_setting(UMBRELLA_AUTO_SETTING') >= 2)

# --- and a pack is never registered into Kodi unless its files are there ---
# TWO FINDINGS, ONE SHAPE. The "already current" fast path decides it may skip
# the download from ONE sentinel file, and a failed EXTRACT used to fall
# through to the same registration. Both ended with Kodi told that add-ons
# exist which are not on disk -- and Kodi then resolves dependencies against
# that lie, which is the silent-fallback-to-Estuary bug this pack code exists
# to prevent.
print()
print('=== an add-on is registered only when its files are on disk ===')
check('registration filters by what is actually on disk',
      '_addon_on_disk(i) for i in wanted' in _src_w.replace('[', '').replace(']', '')
      or 'present = [i for i in wanted if _addon_on_disk(i)]' in _src_w,
      'the static id list must not be registered unconditionally')
check('...and reports failure when something is missing',
      'return not absent' in _src_w)
check('...and registers nothing at all when NOTHING is there',
      'if not present:' in _src_w and _src_w.split('if not present:')[1]
      .lstrip().startswith('return False'))
# STRUCTURAL, not a character window: the handler around extract.all must end
# in `continue`, so nothing below it can run for a pack that did not extract.
_wt = ast.parse(_src_w)
_ext = [h for n in ast.walk(_wt) if isinstance(n, ast.Try)
        for h in n.handlers
        if any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
               and c.func.attr == 'all'
               and getattr(c.func.value, 'id', '') == 'extract'
               for c in ast.walk(n.body[0] if n.body else n))]
check('the extract.all handler was found', len(_ext) == 1, str(len(_ext)))
check('a failed extract stops before the registration',
      bool(_ext) and isinstance(_ext[0].body[-1], ast.Continue),
      'a truncated download used to end with every id marked installed')


# --- every pack's DECLARED version must be the one it CONTAINS -----------
# There was a check like this for Umbrella and for nothing else, and Account
# Manager was quietly a version behind: the pack shipped script.module.acctmgr
# 1.1.5a while its own developer's repository published 1.1.6, so a fresh
# install spent its first day fetching what should have arrived with it.
#
# The gate matters in BOTH directions. _af3_pack_current compares the version
# the SENTINEL file on disk reports against the constant declared here. If the
# constant is AHEAD of what the pack contains, every device re-downloads the
# pack on every boot for ever and never satisfies the gate. If it is BEHIND,
# the pack never refreshes. Either way nothing says so out loud.
print()
print('=== each pack declares the version it actually contains ===')
import zipfile as _zf
import re as _re

_consts = {}
for _n in _wtree.body:
    if isinstance(_n, ast.Assign) and isinstance(getattr(_n, 'value', None),
                                                 ast.Constant):
        for _t in _n.targets:
            if isinstance(_t, ast.Name):
                _consts[_t.id] = _n.value.value

_FAMILIES = (
    ('UMBRELLA_PACK_VERSION', 'Kodi-POV-IL-Umbrella-pack.zip',
     'plugin.video.umbrella'),
    ('ACCTMGR_PACK_VERSION', 'Kodi-POV-IL-AcctMgr-pack.zip',
     'script.module.acctmgr'),
)
for _const, _zipname, _sentinel in _FAMILIES:
    _declared = _consts.get(_const)
    check('%s is declared in wizard.py' % _const, _declared is not None)
    _path = os.path.join(ROOT, 'dist', _zipname)
    check('...and %s is in dist/' % _zipname, os.path.isfile(_path))
    if not (_declared and os.path.isfile(_path)):
        continue
    with _zf.ZipFile(_path) as _z:
        _raw = _z.read('addons/%s/addon.xml' % _sentinel).decode('utf-8',
                                                                'replace')
    _at = _raw.find('<addon')
    _m = _re.search(r'\bversion="([^"]+)"', _raw[_at if _at >= 0 else 0:])
    check('...and its sentinel carries a version', _m is not None)
    if _m:
        check('...which is exactly what %s declares' % _const,
              _m.group(1) == _declared,
              'declared %r, pack contains %r -- the gate either never fires '
              'or fires for ever' % (_declared, _m.group(1)))
    # and every id the pack claims must really be inside it, or the new
    # all-ids-present fast path re-downloads on every boot without end
    _ids = None
    for _n in ast.walk(_wtree):
        if isinstance(_n, ast.Assign):
            for _t in _n.targets:
                if getattr(_t, 'id', '') == _const.replace('_PACK_VERSION',
                                                           '_PACKS'):
                    try:
                        _ids = ast.literal_eval(_n.value)[0]['addon_ids']
                    except Exception:
                        _ids = None
    if _ids:
        with _zf.ZipFile(_path) as _z:
            _present = {_mm.group(1) for _nn in _z.namelist()
                        for _mm in [_re.match(r'^addons/([^/]+)/addon\.xml$',
                                              _nn)] if _mm}
        check('...and every id %s claims is inside its zip'
              % _const.replace('_PACK_VERSION', '_PACKS'),
              set(_ids) <= _present,
              'claimed but absent: %s' % sorted(set(_ids) - _present))

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
