"""Like List / Unlike List really reach MDBList's long-press menu.

Runs the patcher against a PRISTINE copy of stock POV 6.08.12 and then checks
the result the way it will actually be used: the menu file compiles, the two
entries are built for the right list types and NOT for the wrong ones, the
modes they fire resolve to functions that now exist, and those functions call
the endpoint with the verb the API asked for.

A "the marker is in the file" assertion would pass on a patch that produced
nonsense, so the menu block is executed rather than grepped.

Run: python3 tools/test_mdblist_like_patcher.py
"""
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, '..', 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
STOCK = ('/tmp/claude-0/-home-user-Kodi-POV-IL/'
         '70968383-5f01-52a3-afe7-ced1aba28071/scratchpad/pov6812/'
         'plugin.video.pov')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


if not os.path.isdir(STOCK):
    print('SKIP: no stock POV tree at %s' % STOCK)
    sys.exit(0)


def load(home, sabotage=None):
    """Install stubs pointing at `home`, then load the patcher."""
    for name in list(sys.modules):
        if name.split('.')[0] in ('resources', 'xbmc', 'xbmcvfs', 'xbmcgui',
                                  'xbmcaddon'):
            sys.modules.pop(name, None)
    vfs = types.ModuleType('xbmcvfs')

    def _tp(p):
        if isinstance(p, str) and p.startswith('special://home/'):
            return os.path.join(home, p[len('special://home/'):])
        return p
    vfs.translatePath = _tp
    sys.modules['xbmcvfs'] = vfs

    pkg = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = lib
    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.log = lambda *a, **k: None
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku

    src = os.path.join(LIB, 'pov_mdblist_like_patcher.py')
    if sabotage:
        text = open(src, encoding='utf-8').read()
        old, new = sabotage
        assert old in text, 'sabotage anchor not found: %r' % old
        src = os.path.join(tempfile.mkdtemp(), 'p.py')
        with open(src, 'w', encoding='utf-8') as f:
            f.write(text.replace(old, new, 1))
    spec = importlib.util.spec_from_file_location('pov_mdblist_like', src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fresh_pov():
    home = tempfile.mkdtemp()
    shutil.copytree(STOCK, os.path.join(home, 'addons', 'plugin.video.pov'))
    return home


def povfile(home, rel):
    return os.path.join(home, 'addons', 'plugin.video.pov', *rel.split('/'))


# --- 1. against stock POV ---------------------------------------------------
home = fresh_pov()
mod = load(home)
status = mod.ensure_patched()
print('   status: %s' % status)
check('both halves patch a stock POV 6.08.12',
      status == 'api=patched, menu=patched', status)

api_txt = open(povfile(home, mod.API_REL_PATH), encoding='utf-8').read()
menu_txt = open(povfile(home, mod.MENU_REL_PATH), encoding='utf-8').read()
check('the API file still compiles',
      compile(api_txt, 'api', 'exec') is not None)
check('the menu file still compiles',
      compile(menu_txt, 'menu', 'exec') is not None)

# --- 2. re-running changes nothing -----------------------------------------
again = mod.ensure_patched()
check('a second run is a no-op', again == 'api=unchanged, menu=unchanged',
      again)
check('the API file was not touched again',
      open(povfile(home, mod.API_REL_PATH), encoding='utf-8').read() == api_txt)

# --- 3. the MENU BLOCK, executed rather than grepped ------------------------
# Pull the injected branch out of the patched file and run it for each list
# type, with cm_append/build_url captured. This is what proves the entries
# appear for the right lists -- a marker check would pass on nonsense.
block = []
for line in menu_txt.split('\n'):
    if mod.MARKER in line and 'list_type' in line:
        block.append(line)
        continue
    if block:
        if line.strip().startswith(('cm_append((_ai_', 'elif list_type')):
            block.append(line)
            continue
        break
# De-indent by the OUTER prefix only. Stripping every leading tab flattens
# the nested cm_append lines into the if-body's own level, which then does not
# parse -- the block must keep its relative nesting to be worth executing.
_outer = re.match(r'^[\t ]*', block[0]).group(0)
src_block = '\n'.join(
    l[len(_outer):] if l.startswith(_outer) else l for l in block)
check('the injected branch was found in the patched menu', len(block) >= 4,
      repr(block))


def run_branch(list_type):
    calls = []
    ns = {'list_type': list_type, 'list_id': 4242,
          'cm_append': lambda t: calls.append(t),
          'build_url': lambda d: 'plugin://pov/?%s' % d['mode'],
          '_ai_likelist_str': 'Like List',
          '_ai_unlikelist_str': 'Unlike List'}
    exec(compile(src_block, 'branch', 'exec'), ns)
    return calls


for lt, want in (('search', ['Like List', 'Unlike List']),
                 ('top_lists', ['Like List', 'Unlike List']),
                 ('user_lists', ['Like List', 'Unlike List']),
                 ('liked_lists', ['Unlike List']),
                 ('my_lists', [])):
    got = [c[0] for c in run_branch(lt)]
    check('list_type %-12s offers %s' % (lt, want or 'neither'), got == want,
          'got %r' % (got,))

modes = [c[1] for c in run_branch('search')]
check('the entries fire the mdblist.* modes',
      all('mdblist.mdbl_' in m and '_a_list' in m for m in modes),
      repr(modes))

# --- 4. the modes resolve to functions that now exist -----------------------
# entry.py routes any 'mdblist.<f>' to indexers.mdblist_api and calls <f>.
for m in modes:
    # The cm entry is 'RunPlugin(plugin://...?mdblist.<fn>)', so a plain split
    # carries the closing paren into the name and every lookup misses.
    fn = re.search(r'mdblist\.(\w+)', m).group(1)
    check('%s exists in mdblist_api' % fn,
          re.search(r'^def %s\(params\):' % re.escape(fn), api_txt, re.M)
          is not None)

# --- 5. and they use the verbs the API actually asked for -------------------
verbs = {}
for name in ('mdbl_like_a_list', 'mdbl_unlike_a_list'):
    body = api_txt.split('def %s(params):' % name, 1)[1].split('\ndef ', 1)[0]
    mm = re.search(r"method='(\w+)'", body)
    verbs[name] = mm.group(1) if mm else None
    check('%s calls lists/<id>/like' % name, "'lists/%s/like'" in body,
          body[:200])
check('like uses PUT', verbs.get('mdbl_like_a_list') == 'put', repr(verbs))
check('unlike uses DELETE', verbs.get('mdbl_unlike_a_list') == 'delete',
      repr(verbs))

# --- 6. shape changes upstream are refused, not guessed at ------------------
home2 = fresh_pov()
mp = povfile(home2, 'resources/lib/menus/mdblist.py')
renamed = open(mp, encoding='utf-8').read().replace(
    'cm_append((add2menu_str,', 'cm_append((renamed_str,')
with open(mp, 'w', encoding='utf-8') as f:
    f.write(renamed)
mod2 = load(home2)
st2 = mod2.ensure_patched()
check('a renamed menu anchor is reported, not guessed',
      'menu=unmatched' in st2, st2)
check('...and the file is left exactly as it was',
      open(mp, encoding='utf-8').read() == renamed)

# --- 7. SABOTAGE: the compile guard -----------------------------------------
# If the injected block were malformed, the compile check must refuse rather
# than write a POV that cannot start. Break the block and confirm.
home3 = fresh_pov()
mod3 = load(home3, sabotage=("%sif list_type == 'liked_lists':  %s\\n%s%s\\n",
                             "%sif list_type == 'liked_lists'  %s\\n%s%s\\n"))
st3 = mod3.ensure_patched()
check('SABOTAGE: a malformed block is refused by the compile check',
      'compile_failed' in st3, st3)
menu3 = open(povfile(home3, 'resources/lib/menus/mdblist.py'),
             encoding='utf-8').read()
check('SABOTAGE: and nothing was written', mod3.MARKER not in menu3)

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
