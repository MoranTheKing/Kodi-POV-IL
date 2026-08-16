"""The OSD auto-close seeding does what it says, across boots.

THE BUG THIS EXISTS FOR. The migration that turns on the skin's own "hide the
player bar after 4s" used to read `getSkinDir() != 'skin.fentastic'` and return
otherwise. skin.povil.nox ships the identical feature, so every Nox user had
the bar stay up since the day it shipped. That was the report.

THE BUG THE REWRITE THEN INTRODUCED, which is why this file exists at all: the
"already seeded" mark was written with Skin.SetString and read with
Skin.HasSetting. Kodi keeps skin bools and skin strings in TWO SEPARATE MAPS
(CSkinInfo::m_bools / m_strings, each with its own name->id table), and
Skin.HasSetting resolves through TranslateBool into the bool one. The guard
read false forever, so the migration re-forced the values on every single
boot and a deliberate opt-out could never survive one.

So the fake Kodi below models that split EXACTLY -- SetBool and SetString
write different dicts, HasSetting reads only the bool one. A fake with a
single settings dict would have passed the broken code, which is the whole
failure mode this file is built to catch. The sabotage section at the bottom
reintroduces the bug and asserts the harness sees it.

Nothing is mocked at the function level: the real source of
_maybe_enable_osd_autoclose is lifted out of service.py and executed.

Run: python3 tools/test_osd_autoclose.py
"""
import ast
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.normpath(os.path.join(
    HERE, '..', 'addons', 'service.subtitles.kodipovilai'))
SERVICE = os.path.join(ADDON, 'service.py')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


# --------------------------------------------------------------------------
# the real function, lifted from service.py
# --------------------------------------------------------------------------
def extract(*names):
    """Pull named top-level functions out of service.py verbatim.

    Importing service.py is not an option -- it runs a whole Kodi service at
    import time -- and retyping the body here would test a copy that drifts
    the moment someone edits the original. The AST gives the exact lines.
    """
    with open(SERVICE, encoding='utf-8') as f:
        src = f.read()
    tree = ast.parse(src)
    lines = src.split('\n')
    out = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            out[node.name] = '\n'.join(lines[start - 1:node.end_lineno])
    missing = [n for n in names if n not in out]
    if missing:
        print('FAIL could not find %s in service.py' % ', '.join(missing))
        sys.exit(1)
    return out


FUNCS = extract('_maybe_enable_osd_autoclose', '_walk_all',
                '_without', '_other_addon_version')


class Kodi(object):
    """A Kodi whose skin settings split into bools and strings, as Kodi's do.

    CSkinInfo keeps m_bools and m_strings apart, each with its own allocator,
    so a name set in one is invisible to a read of the other. Modelling them
    as one dict is precisely the mistake that let the blocker through review.
    """

    def __init__(self, skin, addons_root, versions=None, bundled_root=None):
        self.skin = skin
        self.addons_root = addons_root
        self.bundled_root = bundled_root or os.path.join(
            tempfile.mkdtemp(prefix='nokodi-'), 'addons')
        self.versions = versions or {}
        self.bools = {}
        self.strings = {}
        self.settings = {}     # OUR add-on settings, a separate store again
        self.slept = 0
        self.logs = []

    # --- the xbmc module -------------------------------------------------
    def module_xbmc(self):
        m = types.ModuleType('xbmc')
        m.getSkinDir = lambda: self.skin
        m.getCondVisibility = self._cond
        m.executebuiltin = lambda cmd, wait=False: self._builtin(cmd)
        m.sleep = self._sleep
        return m

    def _sleep(self, ms):
        self.slept += ms

    def _cond(self, cond):
        if cond.startswith('Skin.HasSetting(') and cond.endswith(')'):
            # BOOL map only. This one line is the whole point of the file.
            return bool(self.bools.get(cond[16:-1]))
        raise AssertionError('unmodelled condition: %s' % cond)

    def _builtin(self, cmd):
        if cmd.startswith('Skin.SetBool(') and cmd.endswith(')'):
            self.bools[cmd[13:-1]] = True          # no arg == true
        elif cmd.startswith('Skin.SetString(') and cmd.endswith(')'):
            name, _, val = cmd[15:-1].partition(',')
            self.strings[name] = val
        else:
            raise AssertionError('unmodelled builtin: %s' % cmd)

    # --- the xbmcvfs / xbmcaddon modules ---------------------------------
    def module_xbmcvfs(self):
        m = types.ModuleType('xbmcvfs')

        def tp(p):
            if p.startswith('special://home/addons/'):
                return os.path.join(self.addons_root,
                                    p[len('special://home/addons/'):])
            if p.startswith('special://xbmc/addons/'):
                return os.path.join(self.bundled_root,
                                    p[len('special://xbmc/addons/'):])
            return p
        m.translatePath = tp
        return m

    def module_xbmcaddon(self):
        m = types.ModuleType('xbmcaddon')
        versions = self.versions

        class Addon(object):
            def __init__(self, addon_id=None):
                if addon_id not in versions:
                    raise RuntimeError('not installed')
                self._id = addon_id

            def getAddonInfo(self, key):
                return versions[self._id] if key == 'version' else ''
        m.Addon = Addon
        return m

    # --- our own settings -------------------------------------------------
    def module_kodi_utils(self):
        m = types.ModuleType('resources.lib.kodi_utils')
        m.get_setting = lambda k, d='': self.settings.get(k, d)
        m.set_setting = lambda k, v: self.settings.__setitem__(k, v)
        m.log = lambda msg, level='INFO': self.logs.append((level, msg))
        return m


def boot(kodi, source=None):
    """Run one Kodi start: execute the real function against this Kodi."""
    ns = {'os': os}
    body = source or '\n\n'.join(FUNCS.values())
    for name, mod in (('xbmc', kodi.module_xbmc()),
                      ('xbmcvfs', kodi.module_xbmcvfs()),
                      ('xbmcaddon', kodi.module_xbmcaddon())):
        sys.modules[name] = mod
    pkg = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    ku = kodi.module_kodi_utils()
    lib.kodi_utils = ku
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = lib
    sys.modules['resources.lib.kodi_utils'] = ku
    exec(compile(body, 'service.py', 'exec'), ns)
    ns['_maybe_enable_osd_autoclose']()
    return kodi


def make_skin(root, skin_id, feature=True, xml_files=40, bulk_dirs=True):
    """A skin tree shaped like a real one: markup under xml/, art elsewhere."""
    base = os.path.join(root, skin_id)
    xmldir = os.path.join(base, 'xml')
    os.makedirs(xmldir, exist_ok=True)
    with open(os.path.join(base, 'addon.xml'), 'w', encoding='utf-8') as f:
        f.write('<addon id="%s" version="1.0.0"/>' % skin_id)
    for i in range(xml_files):
        with open(os.path.join(xmldir, 'View%02d.xml' % i), 'w',
                  encoding='utf-8') as f:
            f.write('<window><control id="%d"/></window>' % i)
    if feature:
        with open(os.path.join(xmldir, 'Timers.xml'), 'w',
                  encoding='utf-8') as f:
            f.write('<timers><timer><start>Skin.HasSetting(OSDAutoClose)'
                    '</start></timer></timers>')
    if bulk_dirs:
        # The art the walk must NOT read. Named .xml on purpose: pruning has
        # to happen by DIRECTORY, since an extension check alone would still
        # open these.
        for d in ('media', 'extras', 'themes'):
            p = os.path.join(base, d)
            os.makedirs(p, exist_ok=True)
            for i in range(30):
                with open(os.path.join(p, 'art%02d.xml' % i), 'w',
                          encoding='utf-8') as f:
                    f.write('OSDAutoClose')   # a false positive if ever read
    return base


home = tempfile.mkdtemp(prefix='osd-home-')
addons = os.path.join(home, 'addons')
os.makedirs(addons)
make_skin(addons, 'skin.povil.nox', feature=True)
make_skin(addons, 'skin.fentastic', feature=True)
make_skin(addons, 'skin.arcticfuse3', feature=False)
VERS = {'skin.povil.nox': '3.2.14', 'skin.fentastic': '2.0.1',
        'skin.arcticfuse3': '3.2.14'}

# --------------------------------------------------------------------------
# 1. the report: Nox gets the feature turned on
# --------------------------------------------------------------------------
k = boot(Kodi('skin.povil.nox', addons, VERS))
check('Nox -- the skin from the report -- gets auto-close turned on',
      k.bools.get('OSDAutoClose') is True,
      'this is the reported bug; the old code returned before here')
check('and the 4s timeout with it',
      k.strings.get('OSDAutoCloseTime') == '4',
      'got %r' % k.strings.get('OSDAutoCloseTime'))
check('the seeding mark is recorded', k.bools.get('AISubsOsdSeeded') is True)
check('it waits for the queued write before verifying it', k.slept >= 150,
      'executebuiltin queues; reading straight back can report a failure '
      'that did not happen')
check('the art directories are never opened',
      not [m for lv, m in k.logs if 'art' in m])

# --------------------------------------------------------------------------
# 2. THE BLOCKER: a deliberate opt-out survives the next boot
# --------------------------------------------------------------------------
k.bools['OSDAutoClose'] = False      # the user turns it off in skin settings
k.strings['OSDAutoCloseTime'] = '10'
boot(k)                              # ... and reboots
check('a manual opt-out is still off after the next boot',
      k.bools.get('OSDAutoClose') is False,
      'the mark is invisible to its own guard, so the migration re-forces '
      'the value on every single start')
check('and a manually changed timeout is left alone',
      k.strings.get('OSDAutoCloseTime') == '10')

# --------------------------------------------------------------------------
# 3. per-skin, because the mark lives in the skin
# --------------------------------------------------------------------------
k2 = Kodi('skin.povil.nox', addons, VERS)
boot(k2)
k2.skin = 'skin.fentastic'
k2.bools.pop('AISubsOsdSeeded')   # a different skin = a different settings file
k2.bools.pop('OSDAutoClose')
boot(k2)
check('switching to a never-seeded skin seeds that skin too',
      k2.bools.get('OSDAutoClose') is True)

# --------------------------------------------------------------------------
# 4. a skin without the feature: no write, and no rescan next boot
# --------------------------------------------------------------------------
k3 = boot(Kodi('skin.arcticfuse3', addons, VERS))
check('a skin without the feature is not written to',
      'OSDAutoClose' not in k3.bools and 'AISubsOsdSeeded' not in k3.bools)
check('the negative is remembered so it is not re-walked every boot',
      k3.settings.get('_osd_autoclose_nofeature') == 'skin.arcticfuse3=3.2.14',
      'got %r' % k3.settings.get('_osd_autoclose_nofeature'))
k3.logs = []
boot(k3)
check('and the second boot short-circuits on it',
      k3.settings.get('_osd_autoclose_nofeature') == 'skin.arcticfuse3=3.2.14')

# a skin UPDATE that adds the feature must still be found
k3.versions = dict(VERS, **{'skin.arcticfuse3': '3.3.0'})
make_skin(addons, 'skin.arcticfuse3', feature=True)
boot(k3)
check('a skin update that ADDS the feature is picked up',
      k3.bools.get('OSDAutoClose') is True,
      'the cache is keyed on the skin VERSION for exactly this')
check('and the superseded stamp does not accumulate',
      'skin.arcticfuse3=3.2.14'
      not in k3.settings.get('_osd_autoclose_nofeature', ''))

# --------------------------------------------------------------------------
# 5. an empty walk is not an answer
# --------------------------------------------------------------------------
k4 = boot(Kodi('skin.nowhere', addons, {'skin.nowhere': '1.0.0'}))
check('a skin that could not be walked at all is NOT cached as featureless',
      not k4.settings.get('_osd_autoclose_nofeature'),
      'a "no" nobody measured would be permanent for that skin version')

# a skin bundled inside Kodi, under special://xbmc rather than special://home
bundled = tempfile.mkdtemp(prefix='osd-xbmc-')
make_skin(bundled, 'skin.builtin', feature=True)
k5 = Kodi('skin.builtin', addons, {'skin.builtin': '1.0.0'},
          bundled_root=bundled)
boot(k5)
check('a skin bundled with Kodi is found under special://xbmc too',
      k5.bools.get('OSDAutoClose') is True,
      'looking only under special://home means such a skin can never be '
      'detected, on any boot')

# --------------------------------------------------------------------------
# 6. the old FENtastic migration is honoured, not overridden
# --------------------------------------------------------------------------
k6 = Kodi('skin.fentastic', addons, VERS)
k6.settings['_fen_osd_autoclose_v1'] = '1'   # seeded by the old migration
k6.bools['OSDAutoClose'] = False             # ... and then turned back off
boot(k6)
check('an opt-out made after the OLD migration is not undone',
      k6.bools.get('OSDAutoClose') is False,
      'the legacy add-on-side marker is that user\'s only seeding record')
check('and it is carried over to the skin-side mark',
      k6.bools.get('AISubsOsdSeeded') is True,
      'otherwise the carry-over branch re-runs on every boot')

# --------------------------------------------------------------------------
# SABOTAGE -- every check above must be able to fail
# --------------------------------------------------------------------------
print()
print('=== sabotage ===')

broken = '\n\n'.join(FUNCS.values()).replace(
    "xbmc.executebuiltin('Skin.SetBool(AISubsOsdSeeded)')",
    "xbmc.executebuiltin('Skin.SetString(AISubsOsdSeeded,1)')")
check('SABOTAGE: the string/bool sabotage applies',
      broken != '\n\n'.join(FUNCS.values()))
ks = Kodi('skin.povil.nox', addons, VERS)
boot(ks, broken)
ks.bools['OSDAutoClose'] = False
boot(ks, broken)
check('SABOTAGE: a mark in the STRING map is caught stomping the opt-out',
      ks.bools.get('OSDAutoClose') is True,
      'the harness models one settings store, so it cannot see the bug this '
      'whole file exists for')

nowait = '\n\n'.join(FUNCS.values()).replace('        xbmc.sleep(150)\n', '')
check('SABOTAGE: the sleep sabotage applies',
      nowait != '\n\n'.join(FUNCS.values()))
kw = Kodi('skin.povil.nox', addons, VERS)
boot(kw, nowait)
check('SABOTAGE: a missing wait before the verify is caught', kw.slept == 0)

noscan = '\n\n'.join(FUNCS.values()).replace('            if scanned:',
                                             '            if True:')
check('SABOTAGE: the empty-walk sabotage applies',
      noscan != '\n\n'.join(FUNCS.values()))
kn = Kodi('skin.nowhere', addons, {'skin.nowhere': '1.0.0'})
boot(kn, noscan)
check('SABOTAGE: caching an unmeasured negative is caught',
      kn.settings.get('_osd_autoclose_nofeature') == 'skin.nowhere=1.0.0')

onlyhome = '\n\n'.join(FUNCS.values()).replace(
    "for r in ('special://home/addons/', 'special://xbmc/addons/')",
    "for r in ('special://home/addons/',)")
check('SABOTAGE: the single-root sabotage applies',
      onlyhome != '\n\n'.join(FUNCS.values()))
kb = Kodi('skin.builtin', addons, {'skin.builtin': '1.0.0'},
          bundled_root=bundled)
boot(kb, onlyhome)
check('SABOTAGE: dropping the special://xbmc root is caught',
      kb.bools.get('OSDAutoClose') is None)

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
