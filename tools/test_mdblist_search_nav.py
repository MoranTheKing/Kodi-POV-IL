"""The three navigation defects reported against 0.2.496, each run for real.

All three are reachable in about three keypresses, and the first one shipped:

  1. Like/Unlike on a SEARCH result re-opened the keyboard. POV's search results
     live at a path with no search_title in it, and SearchMdblLists falls back
     to dialog.input() whenever that parameter is absent -- so the bare
     Container.Refresh that 0.2.496 shipped re-ran the prompt.
  2. Cancelling the search built an empty screen and navigated to it.
  3. Searching a second time meant going back to the home screen.

These are not asserted by reading the generated text. The refresh helper is
extracted and EXECUTED against stubbed Kodi info labels, and the two class
overrides are bound to a stub base so their control flow really runs. A test
that only greps for a substring passes just as happily on code that never runs.

Run: python3 tools/test_mdblist_search_nav.py
"""
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PATCHER = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                       'resources', 'lib', 'pov_mdblist_like_patcher.py')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


# Same stock tree the sibling patcher test uses, and the same rule: when it is
# absent, build the shape inline rather than skip. A skip that exits 0 reports
# green while proving nothing -- that mistake is already recorded in
# test_mdblist_like_patcher.py and is not repeated here.
STOCK = os.environ.get('POV_STOCK') or (
    '/tmp/claude-0/-home-user-Kodi-POV-IL/'
    '70968383-5f01-52a3-afe7-ced1aba28071/scratchpad/pov6812/plugin.video.pov')

FIXTURE_MENU = (
    "from indexers import mdblist_api, list_helper\n"
    "ls = lambda i: str(i)\n"
    "build_url, make_listitem = (lambda d: 'u'), (lambda: object())\n"
    "fanart = default_icon = 'x.png'\n"
    "add2menu_str, add2folder_str, copy2str = ls(32730), ls(32731), 'x'\n"
    "newlist_str, deletelist_str, nextpage_str = 'n', ls(32781), ls(32799)\n"
    "\n"
    "class BaseMdblList(object):\n"
    "\tdef process_results(self):\n"
    "\t\tfor item in self.lists:\n"
    "\t\t\ttry:\n"
    "\t\t\t\tcm = []\n"
    "\t\t\t\tcm_append = cm.append\n"
    "\t\t\t\titem, list_type = self.parse_item(item)\n"
    "\t\t\t\tname, user, slug, list_id = 'n', 'u', 's', 1\n"
    "\t\t\t\tcm_append((add2menu_str, 'RunPlugin(x)'))\n"
    "\t\t\t\tyield ('u', None, True)\n"
    "\t\t\texcept: pass\n"
    "\n"
    "class SearchMdblLists(BaseMdblList):\n"
    "\tdef __init__(self, params):\n"
    "\t\tself.search_title = params.get('search_title')\n"
    "\n"
    "\tdef fetch_results(self):\n"
    "\t\tif self.search_title: self.lists = []\n"
    "\t\telse: self.lists = []\n")

FIXTURE_API = (
    "from caches import mdbl_cache\n"
    "from modules import kodi_utils\n"
    "\n"
    "def call_mdblist(path, method='get'): return None\n"
    "\n"
    "def delete_mdbl_list(params):\n"
    "\treturn None\n")

work = tempfile.mkdtemp()
root = os.path.join(work, 'addons', 'plugin.video.pov')
if os.path.isdir(STOCK):
    shutil.copytree(STOCK, root)
    print('fixture: real stock POV 6.08.12')
else:
    print('fixture: inline (no stock tree on this machine)')
    for rel, body in (('resources/lib/menus/mdblist.py', FIXTURE_MENU),
                      ('resources/lib/indexers/mdblist_api.py', FIXTURE_API)):
        p = os.path.join(root, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(body)

ku = types.ModuleType('kodi_utils')
ku.log = lambda *a, **k: None
sys.modules['kodi_utils'] = ku
vfs = types.ModuleType('xbmcvfs')
vfs.translatePath = lambda p: p.replace('special://home/addons/',
                                        os.path.join(work, 'addons') + os.sep)
sys.modules['xbmcvfs'] = vfs
spec = importlib.util.spec_from_file_location('_p', PATCHER)
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)
status = patcher.ensure_patched()
check('the patcher applies to a stock POV tree', 'patched' in str(status),
      repr(status))

API = os.path.join(work, 'addons', 'plugin.video.pov', 'resources', 'lib',
                   'indexers', 'mdblist_api.py')
MENU = os.path.join(work, 'addons', 'plugin.video.pov', 'resources', 'lib',
                    'menus', 'mdblist.py')
api_src = open(API, encoding='utf-8').read()
menu_src = open(MENU, encoding='utf-8').read()

def body(src, name):
    """Just that function, not everything after it. Scoping this to
    end-of-file instead reported a failure on the first run -- it was reading
    POV's OWN delete_mdbl_list, which calls container_refresh and is right to:
    Delete only ever appears on your own lists, never on search results."""
    m = re.search(r'^def %s\(params\):.*?(?=\n(?:def |class )|\Z)' % name,
                  src, re.S | re.M)
    assert m, 'could not extract %s' % name
    return m.group(0)


for _fn in ('mdbl_like_a_list', 'mdbl_unlike_a_list'):
    check('%s no longer calls the bare container_refresh()' % _fn,
          'kodi_utils.container_refresh()' not in body(api_src, _fn),
          'a bare refresh survives in that body -- that IS the shipped bug')
    check('%s routes through the search-aware refresh instead' % _fn,
          '_ai_refresh_after_like()' in body(api_src, _fn))

check("POV's own delete_mdbl_list is left exactly as it was",
      'kodi_utils.container_refresh()' in body(api_src, 'delete_mdbl_list'),
      'the patcher reached code it has no business editing')


# --- 1. the refresh helper, executed -------------------------------------
def extract(src, name):
    m = re.search(r'^def %s\(\):.*?(?=\n(?:def |class )|\Z)' % name, src,
                  re.S | re.M)
    assert m, 'could not extract %s' % name
    return m.group(0)


def run_refresh(folder_path, category, boom=False):
    """Execute the REAL generated helper; return the builtin it fired, if any."""
    fired = []
    xbmc = types.ModuleType('xbmc')

    def _label(k):
        if boom:
            raise RuntimeError('getInfoLabel unavailable')
        return {'Container.FolderPath': folder_path,
                'Container.PluginCategory': category}.get(k, '')
    xbmc.getInfoLabel = _label
    sys.modules['xbmc'] = xbmc

    k = types.ModuleType('ku2')
    k.execute_builtin = lambda s: fired.append(s)
    k.container_refresh = lambda: fired.append('Container.Refresh')
    g = {'kodi_utils': k}
    exec(extract(api_src, '_ai_refresh_after_like'), g)
    g['_ai_refresh_after_like']()
    return fired


SEARCH = 'plugin://plugin.video.pov/?mode=build_mdbl_list.search_mdbl_lists'

fired = run_refresh(SEARCH, 'Sport')
check('on a search screen it refreshes WITH the typed title, not blindly',
      len(fired) == 1 and 'search_title=Sport' in fired[0]
      and fired[0] != 'Container.Refresh', repr(fired))
check('...and it stays on the same path rather than navigating somewhere new',
      fired and fired[0].startswith('Container.Refresh(' + SEARCH), repr(fired))

fired = run_refresh(SEARCH, '')
check('with no recoverable title it does NOTHING rather than re-prompt',
      fired == [], repr(fired))

fired = run_refresh(SEARCH + '&search_title=Sport', 'Sport')
check('a search path that already carries the title refreshes normally',
      fired == ['Container.Refresh'], repr(fired))

fired = run_refresh('plugin://plugin.video.pov/?mode=mdblist.get_mdbl_lists'
                    '&list_type=liked_lists', 'My Liked Lists')
check('on any ordinary listing the plain refresh still happens',
      fired == ['Container.Refresh'], repr(fired))

fired = run_refresh(SEARCH, 'Sport', boom=True)
check('if it cannot tell which screen this is, it fails CLOSED',
      fired == [], repr(fired) + ' -- an unknown screen must not be refreshed')


# --- 2 & 3. the two class overrides, executed ----------------------------
def bind_overrides():
    """Bind the generated build/process_results onto a stub whose base records
    what it was asked to do."""
    calls = {'base_build': 0, 'ended': []}

    class Base(object):
        def build(self):
            calls['base_build'] += 1

        def process_results(self):
            yield ('url://real', 'real-item', True)

    body = re.search(
        r'^(?P<ind>[ \t]+)def build\(self\):  # AI_SUBS_MDBL_LIKE.*?'
        r'(?=\n(?P=ind)def fetch_results)', menu_src, re.S | re.M)
    assert body, 'the search overrides are not in the patched file'
    text = body.group(0)
    ind = body.group('ind')
    text = '\n'.join(ln[len(ind):] if ln.startswith(ind) else ln
                     for ln in text.split('\n'))

    xp = types.ModuleType('xbmcplugin')
    xp.endOfDirectory = lambda h, succeeded=True: calls['ended'].append(succeeded)
    sys.modules['xbmcplugin'] = xp
    sys.argv = ['plugin://x', '7', '']

    g = {'build_url': lambda d: 'url://' + d['mode'],
         '_ai_new_search_item': lambda: 'new-search-item'}
    ns = {}
    exec('class Sub(Base):\n' + '\n'.join(
        '    ' + ln if ln.strip() else '' for ln in text.split('\n')),
        dict(g, Base=Base), ns)
    return ns['Sub'], calls


Sub, calls = bind_overrides()

s = Sub()
s.search_title = ''
s.build()
check('a cancelled search ends the directory as NOT succeeded',
      calls['ended'] == [False], repr(calls['ended']))
check('...and never builds the listing behind it',
      calls['base_build'] == 0,
      'POV built an empty directory anyway -- that is the blank screen')

s = Sub()
s.search_title = 'Sport'
s.build()
check('a real search still builds normally', calls['base_build'] == 1
      and calls['ended'] == [False], repr(calls))

rows = list(Sub().process_results())
check('the "new search" row comes FIRST in the results',
      len(rows) == 2 and rows[0][1] == 'new-search-item', repr(rows))
check('...and it re-invokes search with no title, which is what prompts',
      rows and rows[0][0] == 'url://build_mdbl_list.search_mdbl_lists'
      and 'search_title' not in rows[0][0], repr(rows[0] if rows else None))
check('...and the real results are still all there, after it',
      len(rows) == 2 and rows[1] == ('url://real', 'real-item', True),
      repr(rows))

# --- SABOTAGE: the refresh checks must be able to fail --------------------
# Restore the shipped-and-wrong behaviour and confirm the suite goes red.
sab = api_src.replace(
    extract(api_src, '_ai_refresh_after_like'),
    'def _ai_refresh_after_like():\n\tkodi_utils.container_refresh()\n')
saved, api_src = api_src, sab
try:
    fired = run_refresh(SEARCH, 'Sport')
    check('SABOTAGE: the 0.2.496 behaviour is detected as wrong',
          fired == ['Container.Refresh'],
          'restoring the bare refresh did not change the outcome -- the '
          'checks above are not testing the fix')
finally:
    api_src = saved

shutil.rmtree(work, ignore_errors=True)
print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
