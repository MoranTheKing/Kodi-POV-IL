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


def make_db(rows, table=True, installed=()):
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
    # Kodi's real shape, because the origin repair reads it.
    conn.execute('CREATE TABLE installed (id INTEGER PRIMARY KEY, '
                 'addonID TEXT UNIQUE, enabled BOOLEAN, installDate TEXT, '
                 'lastUpdated TEXT, lastUsed TEXT, '
                 "origin TEXT NOT NULL DEFAULT '', "
                 'disabledReason INTEGER NOT NULL DEFAULT 0)')
    conn.executemany('INSERT INTO installed (addonID, enabled, installDate, '
                     'origin) VALUES (?, 1, "", ?)', installed)
    conn.commit()
    conn.close()
    return d, path


def origins_in(path):
    conn = sqlite3.connect(path)
    rows = sorted(conn.execute(
        'SELECT addonID, origin FROM installed').fetchall())
    conn.close()
    return rows


def load(db_dir, mode=0, settings=None, set_ok=True,
         repo='on', disable_ok=True):
    """The module with a fake Kodi. Returns (module, state)."""
    state = {'log': [], 'mode': mode, 'set_calls': [],
             'settings': dict(settings or {})}

    def _rpc(payload):
        req = _json.loads(payload)
        method, params = req.get('method'), req.get('params') or {}
        if method == 'Settings.GetSettingValue':
            return _json.dumps({'result': {'value': state['mode']}})
        if method == 'Addons.GetAddonDetails':
            # repo: 'on' installed+enabled | 'off' installed+disabled
            #       'absent' -> Kodi answers an error, as it does for an
            #       add-on it does not know
            state.setdefault('asked', []).append(params.get('addonid'))
            if repo == 'absent':
                return _json.dumps(
                    {'error': {'code': -32602, 'message': 'Invalid params.'}})
            return _json.dumps({'result': {'addon': {
                'addonid': params.get('addonid'),
                'enabled': repo != 'off'}}})
        if method == 'Addons.SetAddonEnabled':
            if params.get('enabled') is False:
                state.setdefault('disabled', []).append(params.get('addonid'))
            if not disable_ok:
                return _json.dumps(
                    {'error': {'code': -32100, 'message': 'Failed.'}})
            return _json.dumps({'result': 'OK'})
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


# --- 2b. the dead repository that keeps writing the pins --------------------
# Clearing pins treats the symptom. The cause is the origin: Kodi compares the
# installed version against the newest THAT REPOSITORY offers, and one that
# answers 404 offers nothing, so the add-on is "not the latest" and is pinned
# again on every future install.
#
# Kodi's own code says what to do. An EMPTY origin takes the other branch,
# which looks for the newest version in ANY repository and pins only if the
# installed one is older -- with nothing offering it, that is
# `installed < 0.0.0`, which is false. So an empty origin UNPINS where a dead
# origin pins. Clearing the record is the fix, not housekeeping.
print()
print('=== the origin that keeps writing them ===')
DEAD = 'repository.KodiRealDebridIsrael'
d2b, p2b = make_db([], installed=[
    ('skin.fentastic', DEAD),
    ('script.fentastic.helper', DEAD),
    ('plugin.video.pov', 'repository.kodifitzwell'),
    ('plugin.video.youtube', 'repository.xbmc.org'),
    ('script.speedtester', ''),
])
mod2b, state2b = load(d2b)
st2b = mod2b.ensure_repaired()
print('   status: %s' % st2b)
after = dict(origins_in(p2b))
check('the dead repository is the one this build actually has',
      DEAD in mod2b.DEAD_ORIGINS, str(mod2b.DEAD_ORIGINS))
check('add-ons registered to it lose that origin',
      after['skin.fentastic'] == '' and after['script.fentastic.helper'] == '',
      str(after))
check('...and a LIVE origin is left exactly as it was',
      after['plugin.video.pov'] == 'repository.kodifitzwell'
      and after['plugin.video.youtube'] == 'repository.xbmc.org', str(after))
check('...and an add-on that never had one is untouched',
      after['script.speedtester'] == '', str(after))
check('every one is named in the log, so a device says which',
      any('skin.fentastic' in l and 'script.fentastic.helper' in l
          for l in state2b['log']), str(state2b['log'])[:300])
check('...and the dead repository is switched off so Kodi stops asking it',
      any(c == DEAD for c in state2b.get('disabled', [])),
      'disabled: %s' % state2b.get('disabled'))

# IT RUNS ON A DEVICE WITH NO PINS AT ALL, which is the device that has not
# collected one YET. The rules block returns early there, and the origin
# repair used to sit below that return.
check('a device with a clean update_rules still gets the origin repair',
      'origins=2:cleared_2' in st2b, st2b)

# and once cleared, nothing to do
mod2c, _ = load(d2b)
check('running it again finds nothing', 'origins=none' in mod2c.ensure_repaired())


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
# AND IT DOES NOT COUNT AS THE ONE CORRECTION EITHER. This checked only the
# status string, so the second way of burning the marker for nothing lived
# right underneath it: the read succeeded, the WRITE failed, and the marker
# went down anyway -- a device whose settings store refuses the write was
# abandoned after one attempt and warned at every boot forever.
check('...and the one-shot marker is not burned by it',
      '_addon_update_mode_seeded' not in state9['settings'],
      str(state9['settings']))
mod9b, state9b = load(d9, mode=1, settings=dict(state9['settings']))
st9b = mod9b.ensure_repaired()
check('...so the next boot tries again', state9b['set_calls'] == [0],
      '%s / %s' % (state9b['set_calls'], st9b))

# a device that was ALREADY correct has had its one correction; it must not
# keep re-checking forever.
d9c, _ = make_db([])
mod9c, state9c = load(d9c, mode=0)
mod9c.ensure_repaired()
check('a device already correct is marked seeded',
      state9c['settings'].get('_addon_update_mode_seeded') == 'v1',
      str(state9c['settings']))


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



# --- the dead repository is switched off, and a failure is not swallowed ----
# THE REVIEW FINDING. The disable used to live inside the `elif origins:`
# branch, so it was only attempted while add-ons were STILL registered to the
# dead repo -- and the clear one line above is what stops that being true. Make
# SetAddonEnabled fail on the same boot the clear succeeds and the old code
# logged nothing, never retried, and left Kodi polling a 404 index hourly for
# ever. These four cases are that finding, pinned.
print()
print('=== switching the dead repository off ===')

_d, _p = make_db([], installed=[('skin.fentastic', DEAD),
                                ('plugin.video.pov', '')])
_m, _st = load(_d, repo='on', disable_ok=False)
_out = _m.ensure_repaired()
check('a disable that FAILS is reported, not swallowed',
      any('could not switch off' in l and 'WARNING' in l for l in _st['log']),
      str([l for l in _st['log'] if 'switch' in l]))
check('...and the origins were still cleared', 'cleared_1' in _out, _out)
# the next boot: origins are empty now, which is exactly when the old code
# stopped trying.
_m2, _st2 = load(_d, repo='on', disable_ok=False)
_m2.ensure_repaired()
check('...and the NEXT boot tries the disable again',
      DEAD in (_st2.get('disabled') or []),
      'never retried once the origins were clean')
check('...and warns again, so it cannot rot silently',
      any('could not switch off' in l for l in _st2['log']))

_m3, _st3 = load(make_db([], installed=[('skin.fentastic', DEAD)])[0],
                 repo='on', disable_ok=True)
_m3.ensure_repaired()
check('a disable that WORKS is reported', DEAD in (_st3.get('disabled') or [])
      and any('switched off' in l for l in _st3['log']))

_m4, _st4 = load(make_db([], installed=[('skin.fentastic', DEAD)])[0],
                 repo='absent')
_m4.ensure_repaired()
check('a device that never had the repository writes nothing',
      not _st4.get('disabled'))
check('...and says nothing about it either',
      not any('switch' in l for l in _st4['log']), str(_st4['log']))

_m5, _st5 = load(make_db([], installed=[('skin.fentastic', DEAD)])[0],
                 repo='off')
_m5.ensure_repaired()
check('a repository already switched off is left alone',
      not _st5.get('disabled'))
check('...silently, because nothing is wrong',
      not any('switch' in l for l in _st5['log']), str(_st5['log']))


# --- a database Kodi is writing to must not hold up the startup pass --------
# Four connections, each able to burn its own busy-timeout, on the thread that
# also starts the subtitle service. Bounded to ONE wait: the first read that
# times out ends the pass, and the next start does the whole thing.
print()
print('=== a locked database costs one wait, not four ===')
import sqlite3 as _sq
import time as _t
_d, _p = make_db([('plugin.video.pov', 2)],
                 installed=[('skin.fentastic', DEAD)])
_hold = _sq.connect(_p, timeout=1)
_hold.execute('BEGIN EXCLUSIVE')
try:
    _m, _st = load(_d)
    _t0 = _t.time()
    _out = _m.ensure_repaired()
    _took = _t.time() - _t0
finally:
    _hold.rollback()
    _hold.close()
check('a locked database is reported, not crashed through',
      'unreadable' in _out, _out)
check('...and the pass stops there instead of paying the wait again',
      'rules=' not in _out, _out)
check('...costing about one timeout, not four',
      _took < _m._DB_TIMEOUT * 2 + 1,
      'took %.1fs with _DB_TIMEOUT=%s' % (_took, _m._DB_TIMEOUT))
check('...and the repair still works once the lock is gone',
      'cleared_1' in load(_d)[0].ensure_repaired())


# --- more than one dead origin ---------------------------------------------
print()
print('=== the dead-origin list is a list ===')
_second = 'repository.somethingElseThatDied'
_d, _p = make_db([], installed=[('skin.fentastic', DEAD),
                                ('plugin.video.idanplus', _second),
                                ('plugin.video.pov', 'repository.kodifitzwell')])
_m, _st = load(_d)
_m.DEAD_ORIGINS = (DEAD, _second)
_out = _m.ensure_repaired()
check('both dead origins are cleared in one pass', 'cleared_2' in _out, _out)
check('...and both repositories are switched off',
      set(_st.get('disabled') or []) == {DEAD, _second},
      str(_st.get('disabled')))
_rows = dict(origins_in(_p))
check('...and a LIVE origin is still untouched',
      _rows.get('plugin.video.pov') == 'repository.kodifitzwell',
      str(_rows))


for d in _SCRATCH:
    shutil.rmtree(d, ignore_errors=True)

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
