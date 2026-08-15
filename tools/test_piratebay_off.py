"""provider.piratebay goes OFF once, and stays off ONLY if the user leaves it.

Two requirements, and the second is the one that is easy to get wrong:

  1. every device -- fresh install and existing install alike -- ends up with
     POV's provider.piratebay set to false;
  2. a user who turns it back ON afterwards is NEVER overridden again, not on
     the next boot and not when a future edit to the tune list bumps its
     fingerprint.

Requirement 2 is not a special case written for this key. It falls out of the
patcher's state map, which remembers the value WE wrote so a later run can tell
"still ours" from "the user has since changed it". This file exists to prove
that claim against the real ensure_patched(), because the whole instruction was
"מי שיחזיר אחר כך מוזמן להחזיר, זה לא יבטל לו שוב" -- and an untested claim
about that is worth nothing.

Run: python3 tools/test_piratebay_off.py
"""
import importlib.util
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, '..', 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')

KEY = 'provider.piratebay'
FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


class Device(object):
    """One device: POV's settings, and our own add-on's settings."""

    def __init__(self, pov=None, ours=None):
        # POV's own defaults, as shipped in POV 6.08.12's settings.xml.
        self.pov = {'include_prerelease_results': 'false',
                    'include_3d_results': 'false',
                    KEY: 'true',
                    'scrapers.timeout.1': '10'}
        self.pov.update(pov or {})
        self.ours = dict(ours or {})
        self.cleared = []

    def load(self):
        dev = self
        for name in list(sys.modules):
            if name.split('.')[0] in ('xbmc', 'xbmcgui', 'xbmcaddon',
                                      'xbmcvfs', 'resources'):
                sys.modules.pop(name, None)

        class _Addon(object):
            def __init__(self, addon_id=None):
                if addon_id != 'plugin.video.pov':
                    raise Exception('only POV is stubbed here')

            def getSetting(self, k):
                # POV returns '' for a key its schema does not have; the
                # patcher must leave those alone rather than create them.
                return dev.pov.get(k, '')

            def setSetting(self, k, v):
                dev.pov[k] = v

        addon_mod = types.ModuleType('xbmcaddon')
        addon_mod.Addon = _Addon

        class _Win(object):
            def __init__(self, *a):
                pass

            def clearProperty(self, k):
                dev.cleared.append(k)
        gui = types.ModuleType('xbmcgui')
        gui.Window = _Win

        sys.modules['xbmcaddon'] = addon_mod
        sys.modules['xbmcgui'] = gui

        pkg = types.ModuleType('resources')
        lib = types.ModuleType('resources.lib')
        sys.modules['resources'] = pkg
        sys.modules['resources.lib'] = lib
        ku = types.ModuleType('resources.lib.kodi_utils')
        ku.log = lambda m, level='INFO', **k: None
        ku.get_setting = lambda k, d='': dev.ours.get(k, d)
        ku.set_setting = lambda k, v: dev.ours.__setitem__(k, v)
        sys.modules['resources.lib.kodi_utils'] = ku
        lib.kodi_utils = ku

        spec = importlib.util.spec_from_file_location(
            'pov_scraper_settings_patcher',
            os.path.join(LIB, 'pov_scraper_settings_patcher.py'))
        mod = importlib.util.module_from_spec(spec)
        sys.modules['pov_scraper_settings_patcher'] = mod
        spec.loader.exec_module(mod)
        return mod


# --- 1. what the build actually intends -------------------------------------
d = Device()
mod = d.load()
check('the tune asks for piratebay OFF',
      dict(mod.DESIRED).get(KEY) == 'false', repr(dict(mod.DESIRED)))

# --- 2. a fresh install (POV default is true) -------------------------------
d = Device()
mod = d.load()
st = mod.ensure_patched()
check('fresh install: tune applies', st == 'patched', st)
check('fresh install: piratebay ends up off', d.pov[KEY] == 'false', d.pov[KEY])
check('fresh install: pre-release still turned on',
      d.pov['include_prerelease_results'] == 'true')
check('fresh install: 3D still turned on', d.pov['include_3d_results'] == 'true')
check("fresh install: POV's settings cache was dropped",
      'pov_settings' in d.cleared, repr(d.cleared))

# --- 3. an EXISTING install that we previously set to true ------------------
# This is the whole user base: the old tune wrote true, and the state map says
# so. The new tune must still reach them.
d = Device(pov={KEY: 'true'},
           ours={'_pov_scraper_tune': 'v3-oldfingerprint',
                 '_pov_scraper_tune_state':
                     '{"provider.piratebay": "true",'
                     ' "include_prerelease_results": "true",'
                     ' "include_3d_results": "true"}'})
mod = d.load()
st = mod.ensure_patched()
check('existing install: tune re-applies after the list changed',
      st == 'patched', st)
check('existing install: piratebay ends up off', d.pov[KEY] == 'false',
      d.pov[KEY])

# --- 4. THE REQUIREMENT: turn it back on and we never touch it again --------
d = Device()
mod = d.load()
mod.ensure_patched()
check('setup: it is off', d.pov[KEY] == 'false')
d.pov[KEY] = 'true'                      # the user turns it back on
st = mod.ensure_patched()
check('the very next boot does nothing', st == 'already', st)
check('...and it is still ON', d.pov[KEY] == 'true', d.pov[KEY])

# ...and a FUTURE edit to the tune list must not undo their choice either.
# Simulated by bumping the marker the way any DESIRED/MINIMUMS edit would.
d.ours['_pov_scraper_tune'] = 'v3-some-future-fingerprint'
st = mod.ensure_patched()
check('a future tune bump still respects the user', d.pov[KEY] == 'true',
      d.pov[KEY])

# The same protection must hold for the other keys, which is the behaviour
# this relies on -- so it is checked rather than assumed.
d2 = Device()
mod2 = d2.load()
mod2.ensure_patched()
d2.pov['include_prerelease_results'] = 'false'    # user opts out
d2.ours['_pov_scraper_tune'] = 'v3-another-future-fingerprint'
mod2.ensure_patched()
check('a user who turned pre-release off keeps it off',
      d2.pov['include_prerelease_results'] == 'false',
      d2.pov['include_prerelease_results'])

# --- 5. an EMPTY read still results in the write ----------------------------
# This case was written the other way round first -- asserting that a key POV
# does not declare is left alone, which is what the patcher's comment claimed.
# It is not what the code does, because Kodi answers an unknown setting id with
# '' rather than raising, so the "absent" branch is only ever reached when
# getSetting itself blows up.
#
# The behaviour is right and the comment was wrong. An empty read ALSO happens
# transiently while POV is still starting, and skipping on it would mark the
# tune done and never retry -- the setting would stay wrong forever with
# nothing in the log. Writing an id Kodi then ignores is the cheaper mistake.
d = Device()
del d.pov[KEY]
mod = d.load()
mod.ensure_patched()
check('an empty read is written rather than silently skipped',
      d.pov.get(KEY) == 'false', repr(d.pov))

# --- 6. SABOTAGE: the user-changed guard is what produces case 4 -------------
# Without it, a future fingerprint bump re-forces the value and the user's
# choice is silently reverted -- the "every update resets my settings"
# complaint. If deleting the guard does NOT break case 4, case 4 proves
# nothing.
ORIGINAL = open(os.path.join(LIB, 'pov_scraper_settings_patcher.py'),
                encoding='utf-8').read()
GUARD = ("        if key in state and cur_norm != "
         "(state.get(key) or '').strip().lower():\n")
assert GUARD in ORIGINAL, 'sabotage anchor not found'
import tempfile
sab_path = os.path.join(tempfile.mkdtemp(), 'pov_scraper_settings_patcher.py')
with open(sab_path, 'w', encoding='utf-8') as f:
    f.write(ORIGINAL.replace(GUARD, "        if False:\n", 1))

d = Device()
d.load()
spec = importlib.util.spec_from_file_location('sabotaged', sab_path)
sab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sab)
sab.ensure_patched()
d.pov[KEY] = 'true'
d.ours['_pov_scraper_tune'] = 'v3-future'
sab.ensure_patched()
check("SABOTAGE: without the guard, the user's choice IS reverted",
      d.pov[KEY] == 'false',
      'still %r -- case 4 is not proving what it claims' % d.pov[KEY])

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
