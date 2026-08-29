"""The "חיבור שירותים" tile must not go through a navigator.db row.

THE REPORT THIS IS BUILT AGAINST, replayed rather than described. A viewer
pressed "חיבור שירותים להרחבת POV" on the home screen and landed on POV's own
English root menu (Movies / TV Shows / Anime / Popular People / ...) instead of
the services screen. Her log:

    0.03s route=0.03s mode=navigator.build_shortcut_folder_list
                      &name=[B]חיבור שירותים[/B]
    Control 50 in window 10025 has been asked to focus, but it can't
    Unable to find plugin / GetDirectory - Error getting plugin://

The tile opened a POV "shortcut folder" -- a row in POV's navigator.db holding
one item, {'mode': 'myservices'}. The row was gone, POV returned an empty
directory in 0.03s, and Kodi walked UP: the parent of a plugin path is the
plugin root, which is POV's stock menu. That root menu is the screenshot.

The folder bought one keypress and one thing to lose. Arctic Fuse 3 has always
called mode=myservices directly and never had this report, so the tile now does
the same on every skin.

WHAT THIS PINS.
  1. The shipped canonical fixture carries the direct call, not the folder.
  2. A device already holding the old tile gets it rewritten -- and only that
     one element: name, icon, position and every other tile byte-identical.
  3. Another shortcut-folder favourite a user added themselves is NOT touched.
  4. The per-skin seeds are repaired too. They are copied OVER favourites.xml
     on every skin switch, so a fix only in the user's file comes back broken
     the first time somebody switches skin.
  5. It is idempotent, and it never writes a torn file back.

The sabotage section mutates the module and requires each mutant to be caught,
so this file cannot pass while the repair does nothing.

Run: python3 tools/test_connect_services_tile.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
ADDON = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai')
LIB = os.path.join(ADDON, 'resources', 'lib')
MODULE = os.path.join(LIB, 'favourites_personal_tiles_patcher.py')
FIXTURE = os.path.join(ADDON, 'resources', 'fixtures',
                       'favourites_fentastic_canonical.xml')

OLD_TILE = (
    '<favourite name="[B][COLOR orange]חיבור שירותים להרחבת POV[/COLOR][/B]" '
    'thumb="special://home/media/build_icons/POV/Connect_Services.png">'
    'ActivateWindow(10025,"plugin://plugin.video.pov/?external_list_item=True'
    '&amp;iconImage=folder.png&amp;mode=navigator.build_shortcut_folder_list'
    '&amp;name=%5bB%5d%d7%97%d7%99%d7%91%d7%95%d7%a8%20%d7%a9%d7%99%d7%a8%d7'
    '%95%d7%aa%d7%99%d7%9d%5b%2fB%5d&amp;shortcut_folder=True",return)'
    '</favourite>')
NEW_ACTION = 'RunPlugin("plugin://plugin.video.pov/?mode=myservices")'
# A shortcut folder somebody added themselves, through POV's own context menu.
# Same mode, different folder -- theirs, and none of our business.
USER_TILE = (
    '<favourite name="[B]הסרטים שלי[/B]" thumb="x.png">'
    'ActivateWindow(10025,"plugin://plugin.video.pov/?external_list_item=True'
    '&amp;iconImage=folder.png&amp;mode=navigator.build_shortcut_folder_list'
    '&amp;name=%d7%a1%d7%a8%d7%98%d7%99%d7%9d%20-%20%d7%9c%d7%a4%d7%99%20'
    '%d7%a8%d7%a9%d7%aa%d7%95%d7%aa&amp;shortcut_folder=True",return)'
    '</favourite>')

FAIL = []
_TMP = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def tmpdir():
    d = tempfile.mkdtemp(prefix='cst_')
    _TMP.append(d)
    return d


def load(src=None, home=None):
    """The patcher with xbmc stubbed out, optionally from mutated source and
    with special://home pointed at `home`."""
    for n in list(sys.modules):
        if n.startswith(('xbmc', 'resources', 'cst_mod')):
            sys.modules.pop(n, None)
    for name in ('xbmc', 'xbmcaddon', 'xbmcgui'):
        sys.modules[name] = types.ModuleType(name)
    xv = types.ModuleType('xbmcvfs')
    if home is None:
        xv.translatePath = lambda p: p
    else:
        xv.translatePath = lambda p: p.replace('special://home/', home + os.sep)
    sys.modules['xbmcvfs'] = xv
    pkg = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    pkg.lib = lib
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = lib
    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.logged = []
    ku.log = lambda m, level='INFO': ku.logged.append((level, m))
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku

    path = MODULE
    if src is not None:
        d = tmpdir()
        path = os.path.join(d, 'favourites_personal_tiles_patcher.py')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(src)
    spec = importlib.util.spec_from_file_location('cst_mod', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._ku = ku
    return mod


def doc(*tiles):
    return ('<favourites>\n    '
            + '\n    '.join(tiles)
            + '\n</favourites>\n').encode('utf-8')


def seed_home(*tiles):
    """A fake special://home with both per-skin favourites seeds."""
    home = tmpdir()
    paths = []
    for skin in ('skin.fentastic', 'skin.estuary'):
        d = os.path.join(home, 'media', 'builds_favourites_xml', skin)
        os.makedirs(d)
        p = os.path.join(d, 'favourites.xml')
        with open(p, 'wb') as f:
            f.write(doc(*tiles))
        paths.append(p)
    return home, paths


# ---------------------------------------------------------------- 1. fixture
mod = load()
fixture = open(FIXTURE, 'rb').read()
check('fixture: no shortcut folder left in it',
      b'build_shortcut_folder_list' not in fixture)
check('fixture: carries the direct My Services call',
      NEW_ACTION.encode('utf-8') in fixture)
check('fixture: the tile keeps its name and icon',
      'name="[B][COLOR orange]חיבור שירותים להרחבת POV[/COLOR][/B]"'.encode(
          'utf-8') in fixture
      and b'Connect_Services.png' in fixture)
_, changed = mod._fix_existing_connect_services_action(fixture)
check('fixture: the repair is a no-op on it', not changed)

# ------------------------------------------------------- 2. existing devices
before = doc(OLD_TILE)
after, changed = mod._fix_existing_connect_services_action(before)
check('device: the old tile is rewritten', changed)
check('device: it now calls My Services directly',
      NEW_ACTION.encode('utf-8') in after)
check('device: the folder is gone from it',
      b'build_shortcut_folder_list' not in after)
check('device: ActivateWindow is gone', b'ActivateWindow' not in after)
check('device: name and icon untouched',
      'name="[B][COLOR orange]חיבור שירותים להרחבת POV[/COLOR][/B]"'.encode(
          'utf-8') in after and b'Connect_Services.png' in after)
again, changed2 = mod._fix_existing_connect_services_action(after)
check('device: idempotent', not changed2 and again == after)

# ---------------------------------------------- 3. somebody else's folder
other = doc(USER_TILE)
out, changed = mod._fix_existing_connect_services_action(other)
check("device: a user's own shortcut folder is left alone",
      not changed and out == other)

mixed = doc(USER_TILE, OLD_TILE, '<favourite name="x">Quit()</favourite>')
out, changed = mod._fix_existing_connect_services_action(mixed)
check('device: in a mixed file only the one tile changes',
      changed
      and out.count(b'build_shortcut_folder_list') == 1
      and USER_TILE.encode('utf-8') in out
      and b'<favourite name="x">Quit()</favourite>' in out
      and out.count(b'<favourite ') == 3)

# ------------------------------------------------------------- 4. the seeds
home, seeds = seed_home(OLD_TILE)
mod = load(home=home)
n = mod._fix_favourites_seeds()
check('seeds: both are repaired', n == 2, 'repaired {0}'.format(n))
check('seeds: neither still opens the folder',
      all(b'build_shortcut_folder_list' not in open(p, 'rb').read()
          for p in seeds))
check('seeds: both call My Services directly',
      all(NEW_ACTION.encode('utf-8') in open(p, 'rb').read() for p in seeds))
check('seeds: a second pass writes nothing', mod._fix_favourites_seeds() == 0)

# A torn seed -- caught mid-write, no closing tag -- must be left for later.
torn = b'<favourites>\n    ' + OLD_TILE.encode('utf-8') + b'\n'
home2, seeds2 = seed_home(OLD_TILE)
with open(seeds2[0], 'wb') as f:
    f.write(torn)
mod = load(home=home2)
n = mod._fix_favourites_seeds()
check('seeds: a torn seed is not written back',
      open(seeds2[0], 'rb').read() == torn and n == 1)

# No seeds on disk at all (Arctic Fuse 3 has none) -- silent no-op.
mod = load(home=tmpdir())
check('seeds: missing seeds are a silent no-op',
      mod._fix_favourites_seeds() == 0)

# --------------------------------------------------------- 5. end to end
mod = load()
fixture_text = open(FIXTURE, encoding='utf-8').read()
check('end to end: the fixture and the repair agree on one action',
      fixture_text.count(NEW_ACTION) == 1)


# ------------------------------------------------------------- sabotage
# Each mutant breaks the repair in a way a reader might not notice. If any
# survives, the checks above are not testing what they claim to.
SRC = open(MODULE, encoding='utf-8').read()
MUTANTS = (
    ('M1 replacement is the old folder URL again',
     '_NEW_CONNECT_SERVICES = b\'RunPlugin("plugin://plugin.video.pov/'
     '?mode=myservices")\'',
     '_NEW_CONNECT_SERVICES = b\'ActivateWindow(10025,"plugin://'
     'plugin.video.pov/?mode=navigator.build_shortcut_folder_list")\''),
    ('M2 the repair reports success without changing anything',
     '    new_content, n = _CONNECT_SERVICES_RE.subn(\n'
     '        lambda m: m.group(1) + _NEW_CONNECT_SERVICES + m.group(3), '
     'content)',
     '    new_content, n = content, 1'),
    ('M3 name guard dropped -- every shortcut folder is rewritten',
     "    + _CONNECT_SERVICES_NAME_ENC\n",
     "    + rb''\n"),
    ('M4 seeds are read but never written',
     "            os.replace(tmp, path)\n            updated += 1\n"
     "        except OSError as e:\n            try:\n"
     "                os.remove(tmp)\n            except OSError:\n"
     "                pass\n            _log('could not update favourites "
     "seed {0}: {1}'.format(seed, e),\n                 level='WARNING')\n"
     "    if updated:\n        _log('repaired tile actions in {0} favourites "
     "seed(s), so a skin '\n             'switch keeps the fix'.format("
     "updated))\n    return updated",
     "            pass\n        except OSError:\n            pass\n"
     "    return updated"),
    ('M5 a torn seed is written back anyway',
     "        if b'</favourites>' not in seed_content:\n"
     "            continue                     # torn or mid-write -> leave "
     "it alone\n",
     ""),
)
print('\n-- sabotage --')
for label, old, new in MUTANTS:
    if SRC.count(old) != 1:
        check(label, False, 'mutation target not found exactly once '
                            '({0})'.format(SRC.count(old)))
        continue
    src = SRC.replace(old, new, 1)
    caught = False
    detail = ''
    try:
        home, seeds = seed_home(OLD_TILE)
        m = load(src=src, home=home)
        out, ch = m._fix_existing_connect_services_action(doc(OLD_TILE))
        if not ch or NEW_ACTION.encode('utf-8') not in out \
                or b'build_shortcut_folder_list' in out:
            caught = True
            detail = 'device repair'
        o2, c2 = m._fix_existing_connect_services_action(doc(USER_TILE))
        if c2 or o2 != doc(USER_TILE):
            caught = True
            detail = detail or "user's own folder"
        if m._fix_favourites_seeds() != 2 or any(
                NEW_ACTION.encode('utf-8') not in open(p, 'rb').read()
                for p in seeds):
            caught = True
            detail = detail or 'seeds'
        home2, seeds2 = seed_home(OLD_TILE)
        with open(seeds2[0], 'wb') as f:
            f.write(torn)
        m2 = load(src=src, home=home2)
        m2._fix_favourites_seeds()
        if open(seeds2[0], 'rb').read() != torn:
            caught = True
            detail = detail or 'torn seed'
    except Exception as e:
        caught = True
        detail = 'raised {0}'.format(e)
    check(label + ' -> caught', caught,
          'mutant SURVIVED -- the checks above do not test this')

for d in _TMP:
    shutil.rmtree(d, ignore_errors=True)

print('\n%d check(s) failed' % len(FAIL))
sys.exit(1 if FAIL else 0)
