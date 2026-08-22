#!/usr/bin/env python3
"""An add-on with an available update must actually get installed.

THE REPORT: "sometimes there are updates and it does not update, and then I
have to go to the add-ons list by hand and update it there. Usually it does
not happen, but on some devices it does."

That sentence rules out most explanations on its own. The update is FOUND --
it shows in the manual list -- and installing it by hand WORKS. So something
filters the list between "found" and "installed". Kodi has exactly two such
filters, and this file pins both.

    updates = GetAvailableUpdates();                          <- manual list
    updates.erase(... !IsAutoUpdateable(addon->ID()) ...);     <- auto list

IsAutoUpdateable is false for an add-on with ANY row in `update_rules`, and
CAddonInstallJob adds rows there by itself: when an add-on's ORIGIN repository
cannot offer a version to compare against -- because it 404s, which a field
log from this build shows one doing -- the installed version is "not the
latest of its origin" and the add-on is pinned as an old version. For good,
invisibly (Kodi logs it at debug level), and only on the devices carrying that
repository. Which is exactly "some devices, at random".

WHAT THIS PINS. The repair reports both filters and repairs narrowly:

  * rule 1 (somebody turned auto-update off) is NEVER touched, including the
    two the build itself ships;
  * rules 2 and 3 (set by the installer, never by a person) are cleared only
    for add-ons this build ships;
  * an add-on the build does not ship is left alone whatever its rule;
  * and an unreadable table is reported as unreadable, not as clean. A repair
    that cannot see the table has not repaired anything, and saying otherwise
    is how a fault stays hidden for another month.

Run: python3 tools/test_addon_autoupdate_repair.py
"""
import importlib.util
import json as _json
import os
import shutil
import sqlite3
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
LIB = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
MODULE = os.path.join(LIB, 'addon_autoupdate_repair.py')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


_SCRATCH = []


def make_db(rows, table=True):
    d = tempfile.mkdtemp(prefix='aur-')
    _SCRATCH.append(d)
    path = os.path.join(d, 'Addons33.db')
    conn = sqlite3.connect(path)
    if table:
        conn.execute('CREATE TABLE update_rules (id integer primary key, '
                     'addonID TEXT, updateRule INTEGER)')
        conn.executemany('INSERT INTO update_rules (addonID, updateRule) '
                         'VALUES (?, ?)', rows)
    else:
        conn.execute('CREATE TABLE something_else (x INTEGER)')
    conn.commit()
    conn.close()
    return d, path


def load(db_dir, mode=0, settings=None, set_ok=True):
    """The module with a fake Kodi. Returns (module, state)."""
    state = {'log': [], 'mode': mode, 'set_calls': [],
             'settings': dict(settings or {})}

    def _rpc(payload):
        req = _json.loads(payload)
        method, params = req.get('method'), req.get('params') or {}
        if method == 'Settings.GetSettingValue':
            return _json.dumps({'result': {'value': state['mode']}})
        if method == 'Settings.SetSettingValue':
            state['set_calls'].append(params.get('value'))
            if set_ok:
                state['mode'] = params.get('value')
                return _json.dumps({'result': True})
            return _json.dumps({'result': False})
        return _json.dumps({'result': None})

    for n in list(sys.modules):
        if n.split('.')[0] in ('resources', 'xbmc', 'xbmcvfs'):
            sys.modules.pop(n, None)
    x = types.ModuleType('xbmc')
    x.executeJSONRPC = _rpc
    sys.modules['xbmc'] = x
    vfs = types.ModuleType('xbmcvfs')
    vfs.translatePath = lambda p: (
        db_dir + os.sep if p == 'special://database/' else p)
    sys.modules['xbmcvfs'] = vfs
    pkg = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    lib.__path__ = [LIB]
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = lib
    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.log = lambda msg, level='INFO': state['log'].append(
        '%s %s' % (level, msg))
    ku.get_setting = lambda k, d='': state['settings'].get(k, d)

    def _set(k, v):
        state['settings'][k] = str(v)
        return True
    ku.set_setting = _set
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku
    spec = importlib.util.spec_from_file_location('aur_t', MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m, state


def rules_in(path):
    conn = sqlite3.connect(path)
    rows = sorted(conn.execute(
        'SELECT addonID, updateRule FROM update_rules').fetchall())
    conn.close()
    return rows


# --- 1. the pins -----------------------------------------------------------
print('=== the installer-set pins, and only those ===')

# a device with the real mix: two deliberate rule-1 pins the build ships, one
# installer pin on an add-on the build owns, one on an add-on it does not.
ROWS = [
    ('resource.language.he_il', 1),
    ('skin.estuary', 1),
    ('plugin.video.idanplus', 2),          # ours, installer-set -> clear
    ('plugin.video.pov', 3),               # ours, but a PERSON did it -> leave
    ('plugin.video.somebodyelses', 2),     # not ours -> leave
    ('plugin.video.otaku', 1),             # ours, but a human said no -> leave
]
d, path = make_db(ROWS)
mod, state = load(d)
st = mod.ensure_repaired()
print('   status: %s' % st)
left = rules_in(path)

check('the installer pin on a build add-on is gone',
      ('plugin.video.idanplus', 2) not in left, str(left))
# RULE 3 IS A PERSON, NOT THE INSTALLER, and this check used to say the
# opposite. Kodi writes PIN_ZIP_INSTALL only when somebody used its own
# "Install from zip file" with a version older than the repository's -- an add-on
# deliberately held back. The wizard's own installs cannot produce it: they
# extract files and write the database row directly, never going through
# CAddonInstallJob. Clearing it would defeat that choice on every boot, which
# is precisely what rule 1 is protected from.
check('A HAND-INSTALLED ZIP KEEPS ITS PIN',
      ('plugin.video.pov', 3) in left,
      'somebody installed that version on purpose; only Kodi\'s own '
      '"install from zip" writes rule 3')
check('A HUMAN "NO" IS NEVER OVERRIDDEN',
      ('plugin.video.otaku', 1) in left,
      'rule 1 means somebody turned auto-update off; an update that ignores '
      'that is the complaint, not the fix')
check('...including the two the build itself ships that way',
      ('resource.language.he_il', 1) in left and ('skin.estuary', 1) in left,
      str(left))
check('an add-on the build does not ship is left alone',
      ('plugin.video.somebodyelses', 2) in left,
      'somebody who pinned their own add-on keeps it')
check('exactly one row went', len(left) == len(ROWS) - 1,
      '%d left of %d' % (len(left), len(ROWS)))

# EVERY PIN IS NAMED IN THE LOG, not only the ones cleared. Kodi records the
# pinning at debug level, so on a normal user log there is no other way to
# see it -- and the ones we deliberately do NOT clear are exactly the ones
# somebody will ask about.
logged = ' | '.join(state['log'])
for addon_id in (a for a, _ in ROWS):
    check('the log names %s' % addon_id, addon_id in logged, logged[:400])
check('...and says which rule pinned it',
      'rule 1' in logged and 'rule 2' in logged and 'rule 3' in logged,
      logged[:400])

check('running it again is a no-op', 'cleared_0' in mod.ensure_repaired()
      or 'none_ours' in mod.ensure_repaired())


# --- 1b. the states that used to burn the one-shot repair -------------------
# A JSON-RPC read that FAILS is not an answer, and it used to be recorded as
# one: the marker was written at the end of the section regardless of which
# branch ran, so a single transient failure -- the RPC not being up yet on a
# slow boot is entirely ordinary this early -- permanently retired the repair
# on a device that then turned out to need it.
print()
print('=== a mode we could not read is not a mode we fixed ===')
d1b, _p = make_db([])
mod1b, state1b = load(d1b, mode=1)
mod1b.update_mode = lambda: None          # the RPC did not answer this boot
st1b = mod1b.ensure_repaired()
check('an unreadable mode is reported as unknown', 'mode=unknown' in st1b, st1b)
check('...and the one-shot marker is NOT burned',
      '_addon_update_mode_seeded' not in state1b['settings'],
      'one transient RPC failure would retire the repair for good')

# ...and the next boot, when the RPC does answer, still repairs it.
mod1c, state1c = load(d1b, mode=1, settings=dict(state1b['settings']))
st1c = mod1c.ensure_repaired()
check('the next boot that CAN read it does the repair',
      state1c['set_calls'] == [0], '%s / %s' % (state1c['set_calls'], st1c))


# --- 2. the states that are not "a table with rows in it" ------------------
print()
print('=== the devices that are not the tidy one ===')

d2, path2 = make_db([])
mod2, _ = load(d2)
check('a clean table reports none', 'rules=none' in mod2.ensure_repaired())

# AN UNREADABLE TABLE IS NOT A CLEAN ONE. Kodi renames this file with every
# schema bump, and a build carrying an older or newer one must say it could
# not look rather than report success.
d3, path3 = make_db([], table=False)
mod3, _ = load(d3)
check('a table that is not there reports unreadable',
      'rules=unreadable' in mod3.ensure_repaired())

d4 = tempfile.mkdtemp(prefix='aur-empty-')
_SCRATCH.append(d4)
mod4, _ = load(d4)
check('no database at all reports no_db', 'rules=no_db' in mod4.ensure_repaired())

# Kodi bumps the number with the schema; the newest is the live one.
d5, _ = make_db([('plugin.video.pov', 2)])
for name in ('Addons27.db', 'Addons9.db'):
    conn = sqlite3.connect(os.path.join(d5, name))
    conn.execute('CREATE TABLE update_rules (id integer primary key, '
                 'addonID TEXT, updateRule INTEGER)')
    conn.execute("INSERT INTO update_rules (addonID, updateRule) "
                 "VALUES ('decoy', 2)")
    conn.commit()
    conn.close()
mod5, _ = load(d5)
mod5.ensure_repaired()
check('the NEWEST database is the one that gets repaired',
      rules_in(os.path.join(d5, 'Addons33.db')) == []
      and rules_in(os.path.join(d5, 'Addons27.db')) == [('decoy', 2)],
      'an old schema file is not the live one')

# THE NAMES THAT ARE NOT SCHEMA NUMBERS. The picker used to pull digits out of
# anywhere in the name, so a backup or a half-renamed file could outrank the
# live database and be repaired instead of it -- and ties were settled by
# whatever order the directory listing came back in, which is undefined.
print()
print('=== the picker cannot be fooled by a neighbouring file ===')


def _decoy_db(directory, name, rows):
    conn = sqlite3.connect(os.path.join(directory, name))
    conn.execute('CREATE TABLE update_rules (id integer primary key, '
                 'addonID TEXT, updateRule INTEGER)')
    conn.executemany('INSERT INTO update_rules (addonID, updateRule) '
                     'VALUES (?, ?)', rows)
    conn.commit()
    conn.close()


d6, _p6 = make_db([('plugin.video.pov', 2)])
for decoy in ('Addonsfoo9.db', 'Addons3x30.db', 'Addons.db',
              'Addons33_bak.db', 'Addons99.db.bak'):
    _decoy_db(d6, decoy, [('decoy', 2)])
mod6b, _ = load(d6)
mod6b.ensure_repaired()
check('a name that is not Addons<number>.db is never picked',
      rules_in(os.path.join(d6, 'Addons33.db')) == [],
      'the live database was not the one repaired')
for decoy in ('Addonsfoo9.db', 'Addons3x30.db', 'Addons.db',
              'Addons33_bak.db', 'Addons99.db.bak'):
    check('...%s is untouched' % decoy,
          rules_in(os.path.join(d6, decoy)) == [('decoy', 2)])

# A DIRECTORY that happens to be named like a newer database used to WIN and be
# returned, and the caller then called the whole device unreadable while a
# perfectly good database sat next to it.
d7, _p7 = make_db([('plugin.video.pov', 2)])
os.makedirs(os.path.join(d7, 'Addons99.db'), exist_ok=True)
mod7b, _ = load(d7)
st7b = mod7b.ensure_repaired()
check('a directory named like a database does not mask the real one',
      rules_in(os.path.join(d7, 'Addons33.db')) == [], st7b)


# --- 3. the mode -----------------------------------------------------------
# The other filter, and the one a user can trip without meaning to: it sits at
# level 0 in Settings > Add-ons. At "notify" the symptom is word for word the
# report -- found, announced, never installed.
print()
print('=== the update mode ===')

d6, _ = make_db([])
mod6, state6 = load(d6, mode=0)
st6 = mod6.ensure_repaired()
check('a device already on "install automatically" is left alone',
      'mode=ok' in st6 and not state6['set_calls'], str(state6['set_calls']))

d7, _ = make_db([])
mod7, state7 = load(d7, mode=1)
st7 = mod7.ensure_repaired()
check('a device on "notify only" is put back', state7['set_calls'] == [0],
      str(state7['set_calls']))
check('...and said so at WARNING, because that one line is the whole answer',
      any(l.startswith('WARNING') and 'notify' in l for l in state7['log']),
      str(state7['log']))
check('...and the seed is recorded so it is a repair, not a policy',
      state7['settings'].get('_addon_update_mode_seeded') == 'v1',
      str(state7['settings']))

# AND ONCE. If the user puts it back to notify, that is their choice: report
# it every start, never fight it. Silently reverting a setting somebody set
# is the "an update changed my settings" complaint in a different costume.
d8, _ = make_db([])
mod8, state8 = load(d8, mode=2,
                    settings={'_addon_update_mode_seeded': 'v1'})
st8 = mod8.ensure_repaired()
check('a mode the user set AFTER the seed is reported, not overridden',
      not state8['set_calls'] and 'left' in st8,
      '%s / %s' % (state8['set_calls'], st8))
check('...but still shouted about every start',
      any(l.startswith('WARNING') and 'never check' in l
          for l in state8['log']),
      str(state8['log']))

d9, _ = make_db([])
mod9, state9 = load(d9, mode=1, set_ok=False)
st9 = mod9.ensure_repaired()
check('a write that does not take is reported as failed, not as fixed',
      'failed' in st9, st9)


# --- 4. the managed set is real --------------------------------------------
# A list of add-on ids typed by hand rots. This checks it against the build's
# own contents, so an add-on the build starts shipping and this forgets is
# caught here rather than by a user whose add-on quietly stops updating.
print()
print('=== the managed list matches what the build actually ships ===')
import re as _re
import zipfile as _zipfile

DIST = os.path.join(ROOT, 'dist')
best, best_n = None, ()
for name in os.listdir(DIST):
    m = _re.match(r'Kodi-POV-IL-FENtastic-test-([0-9.]+)\.zip$', name)
    if not m:
        continue
    n = tuple(int(p) for p in m.group(1).split('.'))
    if n > best_n:
        best, best_n = name, n
check('a build package was found to compare against', best is not None)
if best:
    with _zipfile.ZipFile(os.path.join(DIST, best)) as z:
        shipped = {m.group(1) for n in z.namelist()
                   for m in [_re.match(r'^addons/([^/]+)/addon\.xml$', n)]
                   if m}
    # Kodi's own bundled pieces are not add-ons anybody updates.
    SYSTEM = ('kodi.binary', 'xbmc.', 'metadata.common', 'resource.uisounds',
              'screensaver.', 'audioencoder.', 'game.controller',
              'peripheral.', 'webinterface.', 'inputstream.')
    interesting = {a for a in shipped if not a.startswith(SYSTEM)}
    # the two the build deliberately pins with rule 1 are deliberately out
    deliberate = {'resource.language.he_il', 'skin.estuary'}
    missing = sorted(interesting - set(mod.MANAGED) - deliberate)
    check('every add-on the build ships is either managed or deliberately not',
          not missing,
          'not in MANAGED and not one of the two pinned on purpose: %s'
          % missing)


for d in _SCRATCH:
    shutil.rmtree(d, ignore_errors=True)

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
