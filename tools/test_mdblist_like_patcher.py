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
# A stock POV tree if this machine happens to have one (set POV_STOCK, or drop
# it in the session scratchpad). It is a BONUS case, not the test: the path
# below exists only inside one ephemeral container, and the first version of
# this file skipped with sys.exit(0) when it was missing -- an exit code
# indistinguishable from ALL PASS. Committed to the repo, that meant the test
# proved nothing on any other machine, forever, while still reporting green.
#
# So the real fixture is built here, inline: the two POV lines this patcher
# anchors on, in their real shape (tabs, nesting, argument order), copied from
# POV 6.08.12. That runs everywhere.
STOCK = os.environ.get('POV_STOCK') or (
    '/tmp/claude-0/-home-user-Kodi-POV-IL/'
    '70968383-5f01-52a3-afe7-ced1aba28071/scratchpad/pov6812/plugin.video.pov')

FIXTURE_MENU = (
    "from indexers import mdblist_api, list_helper\n"
    "ls = lambda i: str(i)\n"
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
    "\t\t\t\tname, user, slug, list_id = item['name'], item['user_name'], "
    "item.get('slug', ''), item['id']\n"
    "\t\t\t\tif list_type == 'my_lists':\n"
    "\t\t\t\t\tcm_append((newlist_str, 'RunPlugin(x)'))\n"
    "\t\t\t\t\tcm_append((deletelist_str, 'RunPlugin(x)'))\n"
    "\t\t\t\tcm_append((add2menu_str, 'RunPlugin(x)'))\n"
    "\t\t\t\tcm_append((add2folder_str, 'RunPlugin(x)'))\n"
    "\t\t\texcept: pass\n")

FIXTURE_API = (
    "def call_mdblist(path, params=None, json=None, method=None):\n"
    "\treturn {}\n"
    "\n"
    "def make_new_mdbl_list(params):\n"
    "\tpass\n"
    "\n"
    "def delete_mdbl_list(params):\n"
    "\tresult = call_mdblist('lists/%s' % params['list_id'], method='delete')\n")

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


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
    """A POV tree to patch: the real stock one when present, else the inline
    fixture. Never skips -- a test that reports green without running is worse
    than one that fails."""
    home = tempfile.mkdtemp()
    root = os.path.join(home, 'addons', 'plugin.video.pov')
    if os.path.isdir(STOCK):
        shutil.copytree(STOCK, root)
        return home
    for rel, body in (('resources/lib/menus/mdblist.py', FIXTURE_MENU),
                      ('resources/lib/indexers/mdblist_api.py', FIXTURE_API)):
        path = os.path.join(root, *rel.split('/'))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(body)
    return home


def povfile(home, rel):
    return os.path.join(home, 'addons', 'plugin.video.pov', *rel.split('/'))


print('fixture: %s' % ('real stock POV 6.08.12' if os.path.isdir(STOCK)
                       else 'inline (no stock tree on this machine)'))

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
# Take the marker line, then every line indented DEEPER than it -- that is a
# block, whatever shapes the branch happens to use. The first version listed
# the line prefixes it expected and silently captured only the first line the
# moment the branch grew an `else:`.
lines = menu_txt.split('\n')
start = next(i for i, l in enumerate(lines)
             if mod.MARKER in l and 'list_type' in l)
base = len(lines[start]) - len(lines[start].lstrip('\t '))
block = [lines[start]]
for l in lines[start + 1:]:
    if not l.strip():
        continue
    if len(l) - len(l.lstrip('\t ')) <= base:
        break
    block.append(l)
_outer = re.match(r'^[\t ]*', block[0]).group(0)
src_block = '\n'.join(
    l[len(_outer):] if l.startswith(_outer) else l for l in block)
check('the injected branch was found in the patched menu', len(block) >= 4,
      repr(block))


def run_branch(list_type, liked=()):
    """`liked` = what _ai_liked_ids() reports: a set of ids, or None for
    "cold cache, we do not know"."""
    calls = []
    ns = {'list_type': list_type, 'list_id': 4242,
          'cm_append': lambda t: calls.append(t),
          'build_url': lambda d: 'plugin://pov/?%s' % d['mode'],
          '_ai_liked_ids': (lambda: None) if liked is None
                           else (lambda: set(str(x) for x in liked)),
          '_ai_likelist_str': 'Like List',
          '_ai_unlikelist_str': 'Unlike List'}
    exec(compile(src_block, 'branch', 'exec'), ns)
    return calls


# The values POV REALLY produces, traced rather than invented: BaseList's own
# parse_item hardcodes 'user_lists' (so Search and Top Lists both arrive as
# that, not as 'search'/'top_lists'), and GetMdblLists.parse_item returns
# 'liked_lists', 'external' or 'my_lists'. An earlier version of this list used
# made-up labels, which could only ever re-test the same catch-all branch.
# ONE entry, the one that applies. The liked set is what decides it for a row
# the user reached from a search -- which is the whole point of v2.
for lt, liked, want in (
        ('user_lists', (), ['Like List']),
        ('user_lists', (4242,), ['Unlike List']),     # already liked
        # 'external' gets NEITHER: POV fetches those from external/lists/*,
        # a resource MDBList's schema gives no write routes at all, so a Like
        # there would call lists/<id>/like with an id from the wrong id space.
        ('external', (), []),
        ('external', (4242,), []),
        ('liked_lists', (), ['Unlike List']),         # by definition liked
        ('liked_lists', (4242,), ['Unlike List']),
        ('my_lists', (), []),
        ('my_lists', (4242,), []),                    # never, even if liked
        # Cold cache -> we do not know -> offer BOTH, which is always safe
        # because both verbs are idempotent. Never block the screen for a label.
        ('user_lists', None, ['Like List', 'Unlike List']),
        ('liked_lists', None, ['Unlike List']),
        ('my_lists', None, []),
        ('external', None, [])):
    got = [c[0] for c in run_branch(lt, liked)]
    check('%-12s liked=%-8s -> %s'
          % (lt, 'unknown' if liked is None else bool(liked),
             want or 'neither'),
          got == want, 'got %r' % (got,))

# --- 3b. the REAL helper, executed ------------------------------------------
# Everything above stubs _ai_liked_ids, so until now NOTHING ran the generated
# helper itself: not the SQLite peek, not the json unpack, not the tri-state,
# not the except clause. That gap is exactly why a live defect passed a green
# suite -- POV writes its cache row even when the fetch FAILED, persisting the
# literal string 'null', and the unpack laundered that into "known: nothing"
# instead of "unknown". So extract the real helper and feed it rows.
# Cut at the first column-0 line AFTER the def, not at the next `def` -- what
# follows the injection is POV's own module-level code (which needs names like
# `ls`), and swallowing it makes the extraction fail for reasons that have
# nothing to do with the helper.
_hl = menu_txt.split('\n')
_hs = next(i for i, l in enumerate(_hl) if l.startswith('def _ai_liked_ids():'))
_he = next((i for i in range(_hs + 1, len(_hl))
            if _hl[i].strip() and not _hl[i][:1] in ('\t', ' ')), len(_hl))
helper_src = '\n'.join(_hl[_hs:_he])


def real_helper(row, raises=False):
    """Run the generated _ai_liked_ids() against one fake cache row."""
    import json as _j

    class _Cur(object):
        def execute(self, *a):
            if raises:
                raise RuntimeError('database is locked')

        def fetchone(self):
            return row

    mc = types.ModuleType('caches.mdbl_cache')
    mc.MC_BASE_GET = 'SELECT ...'
    mc.MDBLCache = lambda: types.SimpleNamespace(dbcur=_Cur())
    caches = types.ModuleType('caches')
    caches.mdbl_cache = mc
    sys.modules['caches'] = caches
    sys.modules['caches.mdbl_cache'] = mc
    ns = {'_ai_liked_ids_cache': [False], 'json': _j}
    exec(compile(helper_src, 'helper', 'exec'), ns)
    return ns['_ai_liked_ids'](), ns['_ai_liked_ids_cache']


import json as _json
for label, row, want in (
        ('a real liked-lists payload',
         ('{"lists": [{"id": 7}, {"id": 42}]}',), {'7', '42'}),
        ('an empty but VALID payload -> known, nothing liked',
         ('{"lists": []}',), set()),
        ('no cache row at all -> unknown', None, None),
        # The defect: POV persists json.dumps(None) when its own fetch failed.
        ("a poisoned 'null' row -> unknown, NOT known-empty",
         (_json.dumps(None),), None),
        ('a payload of the wrong shape -> unknown', ('[1, 2, 3]',), None),
        # An entry with no id must not contribute str(None) == 'None' to the
        # set, where it would match any row whose own id was null.
        ('an entry with no id is dropped, the rest survive',
         ('{"lists": [{"id": 7}, {"name": "no id here"}]}',), {'7'}),
        ('an explicit null id is dropped too',
         ('{"lists": [{"id": null}, {"id": 9}]}',), {'9'}),
        ('corrupted text -> unknown', ('not json at all',), None)):
    got, _ = real_helper(row)
    check('real helper: %s' % label, got == want, 'got %r' % (got,))

got, _ = real_helper(('{"lists": []}',), raises=True)
check('real helper: a locked/raising db -> unknown, never an exception',
      got is None, repr(got))

# ...and it must read the row ONCE, not once per row of the listing.
reads = []


class _CountingCur(object):
    """Returns NO row, so the memo holds None -- a FALSY answer.

    With a truthy set here, swapping the memo guard from `is False` to a bare
    truthiness test (`not _ai_liked_ids_cache[0]`) survives green, because
    `not {'7'}` is False either way. The states that matter -- unknown (None)
    and known-empty (set()) -- are exactly the falsy ones, i.e. exactly where
    such a mutation would silently turn one cached read per page into one per
    row."""

    def execute(self, *a):
        reads.append(1)

    def fetchone(self):
        return None


_mc = types.ModuleType('caches.mdbl_cache')
_mc.MC_BASE_GET = 'SELECT ...'
_mc.MDBLCache = lambda: types.SimpleNamespace(dbcur=_CountingCur())
_c = types.ModuleType('caches')
_c.mdbl_cache = _mc
sys.modules['caches'], sys.modules['caches.mdbl_cache'] = _c, _mc
_ns = {'_ai_liked_ids_cache': [False]}
exec(compile(helper_src, 'helper', 'exec'), _ns)
for _ in range(5):
    _ns['_ai_liked_ids']()
check('real helper: the cache row is read once, not once per row',
      len(reads) == 1, '%d reads' % len(reads))

modes = [c[1] for c in run_branch('user_lists', ())
         + run_branch('user_lists', (4242,))]
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
# POV ships reuselanguageinvoker=true, so the menu module stays warm and
# container_refresh() redraws in the same interpreter -- the on-disk cache
# clear alone would leave the memo holding the pre-click answer.
# Not a string match on one sentinel value: assert the reset writes the SAME
# value the helper's "not computed yet" test looks for. Those live in two
# different injected files, and a mismatch between them means every like
# silently stops refreshing the menu -- which is exactly what nearly shipped
# when the sentinel changed from None to False on one side only.
_init = re.search(r'_ai_liked_ids_cache = \[(\w+)\]', menu_txt).group(1)
_test = re.search(r'if _ai_liked_ids_cache\[0\] is (\w+):', menu_txt).group(1)
check('the helper tests for the value it initialises to', _init == _test,
      'init=%r tested=%r' % (_init, _test))
for name in ('mdbl_like_a_list', 'mdbl_unlike_a_list'):
    body = api_txt.split('def %s(params):' % name, 1)[1].split('\ndef ', 1)[0]
    m_reset = re.search(r'_ai_liked_ids_cache\[0\] = (\w+)', body)
    check('%s resets the menu memo, not just the disk cache' % name,
          m_reset is not None, body[:300])
    check('%s resets it to the sentinel the helper checks (%s)' % (name, _init),
          m_reset and m_reset.group(1) == _init,
          'resets to %r, helper checks %r'
          % (m_reset and m_reset.group(1), _init))
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

# --- 6b. the OTHER two anchors drift too ------------------------------------
for rel, old, new, expect in (
        ('resources/lib/menus/mdblist.py', 'deletelist_str', 'gone_str',
         'menu=unmatched'),
        ('resources/lib/indexers/mdblist_api.py', 'def delete_mdbl_list',
         'def removed_mdbl_list', 'api=unmatched')):
    h = fresh_pov()
    f = povfile(h, rel)
    txt = open(f, encoding='utf-8').read()
    with open(f, 'w', encoding='utf-8') as fh:
        fh.write(txt.replace(old, new))
    st = load(h).ensure_patched()
    check('a drifted %s anchor is reported' % old.split()[-1], expect in st, st)

# --- 6c. THE MENU MUST NEVER OUTLIVE ITS HANDLER ----------------------------
# If the API anchor misses, the menu entry must NOT be added: it would fire a
# mode at a function that does not exist, and POV's router resolves modes with
# a bare getattr and does not suppress -- so the user gets an uncaught
# AttributeError out of the plugin entry point, permanently (the menu marker
# blocks any retry of that half forever).
h = fresh_pov()
f = povfile(h, 'resources/lib/indexers/mdblist_api.py')
txt = open(f, encoding='utf-8').read()
with open(f, 'w', encoding='utf-8') as fh:
    fh.write(txt.replace('def delete_mdbl_list', 'def removed_mdbl_list'))
mod4 = load(h)
st4 = mod4.ensure_patched()
menu4 = open(povfile(h, 'resources/lib/menus/mdblist.py'),
             encoding='utf-8').read()
check('with the API half unmatched, the menu is left alone',
      'menu=skipped_no_api' in st4, st4)
check('...and no Like entry was written', mod4.MARKER not in menu4)

# --- 7. SABOTAGE: the compile guard -----------------------------------------
# If the injected block were malformed, the compile check must refuse rather
# than write a POV that cannot start. Break the block and confirm.
home3 = fresh_pov()
mod3 = load(home3, sabotage=(
    '"%sif list_type not in (\'my_lists\', \'external\'):  %s\\n"',
    '"%sif list_type not in (\'my_lists\', \'external\')  %s\\n"'))
st3 = mod3.ensure_patched()
check('SABOTAGE: a malformed block is refused by the compile check',
      'compile_failed' in st3, st3)
menu3 = open(povfile(home3, 'resources/lib/menus/mdblist.py'),
             encoding='utf-8').read()
check('SABOTAGE: and nothing was written', mod3.MARKER not in menu3)

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
