"""POV's debrid error handlers must not destroy the error they exist to report.

THE REPORT: AllDebrid, "no results" for movies and series. The log said
otherwise -- 70 sources found, the scrape fine, and then 38 of 38 AllDebrid
sources failing to play with the SAME line:

    resolve_external_sources exception: cannot access local variable
    'torrent_id' where it is not associated with a value

An UnboundLocalError, not a "no results" condition. `torrent_id` is assigned
inside the try and read by the except, so when `create_transfer` raises -- an
expired key, a lapsed subscription, a changed endpoint -- the HANDLER crashes
and its UnboundLocalError REPLACES the exception that would have said which.
The code written to report the failure is what deletes the evidence.

This file pins two things, one general and one concrete:

  1. AST: after patching, no `except` handler in POV's debrid code reads a name
     that is only ever assigned inside its own try. The same scan that found
     the four sites is the check, so a fifth appearing in a future POV release
     is caught by the shape rather than by having been enumerated here.
  2. EXECUTION: the real exception actually survives. Stock is required to
     demonstrate the bug -- to raise UnboundLocalError and lose the cause --
     before the patched run is allowed to claim it keeps it.

Run: python3 tools/test_pov_debrid_unbound_guard.py
"""
import ast
import importlib.util
import io
import os
import re
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
LIB = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
PATCHER = os.path.join(LIB, 'pov_debrid_unbound_guard_patcher.py')
STOCK = os.environ.get('POV_STOCK') or (
    '/tmp/claude-0/-home-user-Kodi-POV-IL/'
    '70968383-5f01-52a3-afe7-ced1aba28071/scratchpad/pov6813/plugin.video.pov')

# THE FIXTURES ARE REAL POV, NOT A SKETCH OF IT.
#
# One byte-slice per site -- the exact method, verbatim from POV 6.08.13,
# under a one-line class header so it stands alone as a module. Generated
# and asserted to be a substring of the real file, never typed.
#
# This exists because the alternative was a test that goes RED on every
# machine without a stock tree, and release 601 established that such a
# test is worse than no test: it teaches people to scroll past red. The
# same reasoning, and the same remedy, as tools/test_mdblist_search_nav.py.
FIXTURES = {
    'resources/lib/debrids/alldebrid_api.py': (
        'class AllDebridAPI(object):\n'
        '\tdef parse_magnet_pack(self, magnet_url, info_hash, errors=False):\n'
        '\t\tfrom modules.source_utils import supported_video_extensions\n'
        '\t\ttry:\n'
        '\t\t\textensions = tuple(supported_video_extensions())\n'
        '\t\t\ttorrent_id = self.create_transfer(magnet_url)\n'
        "\t\t\tfor key in ['completionDate'] * 3:\n"
        '\t\t\t\tkodi_utils.sleep(500)\n'
        '\t\t\t\ttorrent_info = self.torrent_info(torrent_id)\n'
        '\t\t\t\tif torrent_info[key]: break\n'
        "\t\t\telse: raise Exception('alldebrid uncached magnet')\n"
        "\t\t\ttorrent_info['links'] = self.flatten_magnet_files(torrent_info['files'])\n"
        '\t\t\treturn [\n'
        "\t\t\t\t{'link': item['l'],\n"
        "\t\t\t\t 'size': item['s'],\n"
        "\t\t\t\t 'torrent_id': torrent_id,\n"
        "\t\t\t\t 'filename': item['n']}\n"
        "\t\t\t\tfor item in torrent_info['links']\n"
        "\t\t\t\tif item['n'].lower().endswith(extensions)\n"
        '\t\t\t]\n'
        '\t\texcept Exception as e:\n'
        '\t\t\tif torrent_id: self.delete_torrent(torrent_id)\n'
        '\t\t\tif errors: raise\n'
    ),
    'resources/lib/debrids/real_debrid_api.py': (
        'class RealDebridAPI(object):\n'
        '\tdef parse_magnet_pack(self, magnet_url, info_hash, errors=False):\n'
        '\t\tfrom modules.source_utils import supported_video_extensions\n'
        '\t\ttry:\n'
        '\t\t\textensions = tuple(supported_video_extensions())\n'
        '\t\t\ttorrent_id = self.create_transfer(magnet_url)\n'
        "\t\t\tif not torrent_id: raise Exception('real debrid null magnet')\n"
        "\t\t\tfor key in ['ended'] * 3:\n"
        '\t\t\t\tkodi_utils.sleep(500)\n'
        '\t\t\t\ttorrent_info = self.torrent_info(torrent_id)\n'
        '\t\t\t\tif key in torrent_info: break\n'
        "\t\t\telse: raise Exception('real debrid uncached magnet')\n"
        "\t\t\tselected = (i for i in torrent_info['files'] if i['selected'])\n"
        '\t\t\treturn [\n'
        "\t\t\t\t{'link': link,\n"
        "\t\t\t\t 'size': item['bytes'],\n"
        "\t\t\t\t 'torrent_id': torrent_id,\n"
        "\t\t\t\t 'filename': item['path'].replace('/', '')}\n"
        "\t\t\t\tfor item, link in zip(selected, torrent_info['links'])\n"
        "\t\t\t\tif item['path'].lower().endswith(extensions)\n"
        '\t\t\t]\n'
        '\t\texcept Exception as e:\n'
        '\t\t\tif torrent_id: self.delete_torrent(torrent_id)\n'
        '\t\t\tif errors: raise\n'
    ),
    'resources/lib/debrids/torbox_api.py': (
        'class TorBoxAPI(object):\n'
        '\tdef parse_magnet_pack(self, magnet_url, info_hash):\n'
        '\t\tfrom modules.source_utils import supported_video_extensions\n'
        '\t\ttry:\n'
        '\t\t\textensions = tuple(supported_video_extensions())\n'
        "\t\t\tpath = 'torrents' if magnet_url.startswith('magnet') else 'usenet'\n"
        '\t\t\ttorrent_id = self.create_transfer(magnet_url)\n'
        '\t\t\ttorrent_files = self.torrent_info(torrent_id, path)\n'
        '\t\t\treturn [\n'
        "\t\t\t\t{'link': '%s,%s,%s' % (torrent_id, item['id'], path),\n"
        "\t\t\t\t 'size': item['size'],\n"
        "\t\t\t\t 'torrent_id': '%s,%s' % (torrent_id, path),\n"
        "\t\t\t\t 'filename': item['short_name']}\n"
        "\t\t\t\tfor item in torrent_files['files']\n"
        "\t\t\t\tif item['short_name'].lower().endswith(extensions)\n"
        '\t\t\t]\n'
        '\t\texcept Exception as e:\n'
        "\t\t\tif torrent_id: self.delete_torrent('%s,%s' % (torrent_id, path))\n"
    ),
    'resources/lib/modules/debrid.py': (
        'class Debrid(object):\n'
        '\tdef resolve_external_sources(self, title, season, episode):\n'
        '\t\tfrom modules.source_utils import supported_video_extensions, seas_ep_filter, extras_filter\n'
        '\t\ttry:\n'
        '\t\t\textensions = tuple(supported_video_extensions())\n'
        '\t\t\textras_filtering_list = tuple(i for i in extras_filter() if i not in title.lower())\n'
        "\t\t\tif self.url.startswith('magnet'):\n"
        '\t\t\t\tstore_to_cloud = settings.store_resolved_torrent_to_cloud(self.debrid)\n'
        '\t\t\telse: store_to_cloud = settings.store_resolved_usenet_to_cloud(self.debrid)\n'
        "\t\t\tif self.debrid in ('realdebrid', 'alldebrid'): args = self.url, self.hash, True\n"
        '\t\t\telse: args = self.url, self.hash\n'
        '\t\t\tapi = import_debrid(self.debrid)\n'
        '\t\t\tfiles = api.parse_magnet_pack(*args)\n'
        '\t\t\tselected_files = []\n'
        '\t\t\tselected_files_append = selected_files.append\n'
        '\t\t\tfor i in files or []:\n'
        "\t\t\t\ttorrent_id, filename = i.get('torrent_id'), i['filename'].lower()\n"
        "\t\t\t\tif filename.endswith('.m2ts'): raise Exception('_m2ts_check failed')\n"
        '\t\t\t\tif not filename.endswith(extensions): continue\n'
        '\t\t\t\tif season:\n'
        '\t\t\t\t\tif not seas_ep_filter(season, episode, filename): continue\n'
        '\t\t\t\telif any(x in filename for x in extras_filtering_list): continue\n'
        '\t\t\t\tselected_files_append(i)\n'
        "\t\t\tif not selected_files: raise Exception('selected_files failed')\n"
        "\t\t\tif not season: selected_files.sort(key=lambda k: k['size'], reverse=True)\n"
        "\t\t\tfile_key = next((i['link'] for i in selected_files), None)\n"
        '\t\t\tfile_url = api.unrestrict_link(file_key)\n'
        '\t\t\tif not api.defaults_to_cloud:\n'
        '\t\t\t\tif store_to_cloud: Thread(target=api.create_transfer, args=(self.url,)).start()\n'
        '\t\t\tif api.defaults_to_cloud:\n'
        '\t\t\t\tif not store_to_cloud: self._delete(api, torrent_id)\n'
        '\t\t\treturn file_url\n'
        '\t\texcept Exception as e:\n'
        '\t\t\tkodi_utils.logger(\'resolve_external_sources exception\', f"{e}\\n{self.dumps()}")\n'
        '\t\t\tif files and torrent_id: self._delete(api, torrent_id)\n'
    ),
}


FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def stock_version():
    try:
        with open(os.path.join(STOCK, 'addon.xml'), encoding='utf-8') as f:
            m = re.search(r'<addon[^>]*?version="([0-9.]+)"', f.read(), re.S)
        return m.group(1) if m else 'unknown version'
    except Exception:
        return 'unknown version'


# --- the scan that found the bug, and is now the check ---------------------
#
# WHAT IT IS AND IS NOT. A syntactic heuristic, not scope-and-flow analysis.
# It reads "which names does an except handler read that nothing binds before
# its try?" and that is enough to have found all four real sites. Two rounds of
# review have now each moved its boundary, so the boundary is written down:
#
#   HANDLED. A try nested inside an if/for (round 1 missed it entirely -- the
#   old scan walked only top-level statements and swept the try's OWN
#   assignments into `pre`). Names bound in a NESTED function, lambda or
#   comprehension, which are different variables in a different scope and used
#   to mask a real bug in the outer one. `global`/`nonlocal` names, which can
#   never raise UnboundLocalError and used to be flagged as if they could.
#
#   NOT HANDLED, deliberately. A name bound in only ONE branch of an if/else
#   before the try is treated as bound. Deciding otherwise needs real
#   reachability analysis, and this is a test guard, not a type checker. If a
#   future POV writes that shape, this scan will not find it -- so do not read
#   a clean run as proof that POV is clean, only that these shapes are.
_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                  ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def own_scope_stores(node):
    """Every Name bound in `node`'s OWN scope -- not in a nested one."""
    out = []

    def walk(n, top=False):
        if not top and isinstance(n, _NESTED_SCOPES):
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.append(n)
        for child in ast.iter_child_nodes(n):
            walk(child)

    walk(node, top=True)
    return out


def risky_names(src):
    """{(function, sorted names)} an except reads but the try alone assigns."""
    found = set()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.FunctionDef):
            continue
        for t in [n for n in ast.walk(node) if isinstance(n, ast.Try)]:
            read = {n.id for h in t.handlers for n in ast.walk(h)
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
            assigned = {n.id for st in t.body for n in ast.walk(st)
                        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
            # Everything bound on a line BEFORE the try starts -- in THIS
            # function's own scope. Walking every Store in the subtree was the
            # round-2 finding: a `tid` bound inside a nested helper or a
            # comprehension is a different variable entirely, and counting it
            # masked a real bug in the enclosing function.
            pre = {a.arg for a in node.args.args}
            pre |= {n.id for n in own_scope_stores(node)
                    if n.lineno < t.lineno}
            # A name declared global/nonlocal is bound elsewhere and cannot
            # raise UnboundLocalError, so reading it in a handler is safe.
            pre |= {name for d in ast.walk(node)
                    if isinstance(d, (ast.Global, ast.Nonlocal))
                    for name in d.names}
            bad = (read & assigned) - pre
            if bad:
                found.add((node.name, tuple(sorted(bad))))
    return found


# The four files the patcher touches, plus the rest of the debrid directory,
# so a new provider with the same shape is not silently outside the scan.
def debrid_sources(root):
    out = {}
    for rel in ['resources/lib/modules/debrid.py'] + [
            'resources/lib/debrids/' + f
            for f in sorted(os.listdir(os.path.join(root, 'resources', 'lib',
                                                    'debrids')))
            if f.endswith('.py')]:
        p = os.path.join(root, *rel.split('/'))
        with io.open(p, encoding='utf-8', newline='') as f:
            out[rel] = f.read()
    return out


def load(home):
    for name in list(sys.modules):
        if name.split('.')[0] in ('resources', 'xbmcvfs'):
            sys.modules.pop(name, None)
    vfs = types.ModuleType('xbmcvfs')
    vfs.translatePath = lambda p: p.replace(
        'special://home/addons/', os.path.join(home, 'addons') + os.sep)
    sys.modules['xbmcvfs'] = vfs
    pkg = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    lib.__path__ = [LIB]
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = lib
    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.log = lambda *a, **k: None
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku
    spec = importlib.util.spec_from_file_location('_g', PATCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fresh_pov():
    """A POV tree the patcher can work on: the real one where it exists, the
    byte-slice fixtures where it does not. Both paths run every assertion
    below -- the fixtures carry the exact anchors and the exact handlers."""
    home = tempfile.mkdtemp(prefix='povdbg-')
    root = os.path.join(home, 'addons', 'plugin.video.pov')
    if os.path.isdir(STOCK):
        shutil.copytree(STOCK, root)
        return home, root
    for rel, body in FIXTURES.items():
        p = os.path.join(root, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with io.open(p, 'w', encoding='utf-8', newline='') as f:
            f.write(body)
    # the scan walks the whole debrids directory; give it the clean providers
    # too, so "was already clean and NOT touched" is not vacuous here either
    for name in ('easynews_api.py', 'premiumize_api.py'):
        p = os.path.join(root, 'resources', 'lib', 'debrids', name)
        with io.open(p, 'w', encoding='utf-8', newline='') as f:
            f.write('class Clean(object):\n\tdef go(self):\n'
                    '\t\ttry:\n\t\t\tx = 1\n'
                    '\t\texcept Exception:\n\t\t\tpass\n')
    return home, root


print('fixture: %s' % ('real stock POV ' + stock_version()
                       if os.path.isdir(STOCK)
                       else 'byte-slices of real POV (no stock tree here)'))

home, root = fresh_pov()
before = debrid_sources(root)
mod = load(home)
status = mod.ensure_patched()
after = debrid_sources(root)
print('   status: %s' % status)

check('all three sites patch on a stock tree',
      status == 'alldebrid=patched, realdebrid=patched, torbox=patched',
      status)

# --- 0. the scan must see the bug wherever it is written -------------------
_NESTED = ('def f(self, x):\n'
           '\tif x:\n'
           '\t\ttry:\n'
           '\t\t\ttid = self.go()\n'
           '\t\texcept Exception:\n'
           '\t\t\tif tid: self.undo(tid)\n')
_FLAT = ('def f(self, x):\n'
         '\ttry:\n'
         '\t\ttid = self.go()\n'
         '\texcept Exception:\n'
         '\t\tif tid: self.undo(tid)\n')
check('the scan catches the defect as a plain statement',
      ('f', ('tid',)) in risky_names(_FLAT))
check('...and catches it nested inside an if, which it used to miss entirely',
      ('f', ('tid',)) in risky_names(_NESTED),
      'a future POV release that indents its try one level deeper would walk '
      'straight past this check')
_SAFE = ('def f(self, x):\n\ttid = None\n\tif x:\n\t\ttry:\n'
         '\t\t\ttid = self.go()\n\t\texcept Exception:\n'
         '\t\t\tif tid: self.undo(tid)\n')
check('...and does NOT cry wolf once the name is bound first',
      not risky_names(_SAFE),
      'every guarded site would report as still broken')

# Round 2 found three more shapes. Two are fixed; the third is a stated limit.
_HELPER = ('def f(self, x):\n'
           '\tdef helper():\n\t\ttid = 99\n\t\treturn tid\n'
           '\ttry:\n\t\ttid = self.go()\n'
           '\texcept Exception:\n\t\tif tid: self.undo(tid)\n')
check('a name bound only in a NESTED function does not count as bound here',
      ('f', ('tid',)) in risky_names(_HELPER),
      "it is a different variable in a different scope, and counting it hid a "
      'real bug in the enclosing function')
_COMP = ('def f(self, x):\n\ty = [tid for tid in range(3)]\n'
         '\ttry:\n\t\ttid = self.go()\n'
         '\texcept Exception:\n\t\tif tid: self.undo(tid)\n')
check('...nor one bound only as a comprehension variable',
      ('f', ('tid',)) in risky_names(_COMP),
      'comprehensions have their own scope in Python 3')
_GLOBAL = ('def f(self, x):\n\tglobal tid\n'
           '\ttry:\n\t\ttid = self.go()\n'
           '\texcept Exception:\n\t\tif tid: self.undo(tid)\n')
check('a global/nonlocal name is NOT flagged -- it cannot be unbound',
      not risky_names(_GLOBAL),
      'flagging it would send someone to fix a function that is already safe')

# --- 0b. the embedded fixtures really are real POV -------------------------
# The comment above them says "asserted to be a substring of the real file".
# Nothing was asserting it. A hand-edit could have drifted them from POV with
# the suite still green on every machine without a stock tree.
if os.path.isdir(STOCK):
    for rel, body in FIXTURES.items():
        with io.open(os.path.join(STOCK, *rel.split('/')),
                     encoding='utf-8', newline='') as f:
            real = f.read()
        slice_only = body.split('\n', 1)[1]      # drop the class header
        check('FIXTURE %s is a byte-slice of real POV' % rel.split('/')[-1],
              slice_only in real,
              'it has drifted from the file it claims to be quoting')
else:
    print('---- %d fixture(s) NOT CHECKED against a real tree here'
          % len(FIXTURES))

# --- 1. the scan: before it finds the bug, after it finds nothing ----------
found_before = {rel: risky_names(t) for rel, t in before.items()}
found_after = {rel: risky_names(t) for rel, t in after.items()}

hits = {rel: v for rel, v in found_before.items() if v}
check('the scan finds the defect in stock POV, in more than one provider',
      len(hits) >= 3,
      'found it in %s -- if stock is clean the patch has nothing to do'
      % sorted(hits))
check('and the reported one is among them',
      ('parse_magnet_pack', ('torrent_id',))
      in found_before.get('resources/lib/debrids/alldebrid_api.py', set()))
# The caller has the identical defect and is NOT this patcher's job:
# pov_debrid_resolve_patcher.py, months older, already binds files and
# torrent_id at the top of resolve_external_sources. The first draft of this
# module patched it a second time and could never have matched, because that
# patcher's line lands in the middle of this one's anchor. So the scan is
# expected to still flag it here, and the patcher is expected to leave it
# alone.
check('the caller is flagged by the scan but left to the patcher that owns it',
      ('resolve_external_sources', ('api', 'files', 'torrent_id'))
      in found_before.get('resources/lib/modules/debrid.py', set()))
check('...and this patcher does NOT touch it',
      before.get('resources/lib/modules/debrid.py')
      == after.get('resources/lib/modules/debrid.py'),
      'two patchers writing the same function is how one of them starts '
      'reporting unmatched forever')

left = {rel: v for rel, v in found_after.items() if v}
check('AFTER patching, no PROVIDER handler reads an unbound name',
      not [r for r in left if '/debrids/' in r],
      'still risky: %s' % sorted((r, v) for r, v in left.items()
                                 if '/debrids/' in r))

for rel in before:
    if not found_before[rel]:
        check('%s was already clean and was NOT touched' % rel.split('/')[-1],
              before[rel] == after[rel],
              'the patcher edited a file that did not need it')

# --- 2. execution: the real exception has to survive -----------------------
# Lift parse_magnet_pack out of the class and run it with a create_transfer
# that fails the way AllDebrid's does -- the KeyError from result['magnets'].


def lift(src, name):
    """A class method, dedented one level into a plain function."""
    lines = src.split('\n')
    start = next(i for i, l in enumerate(lines)
                 if l.startswith('\tdef %s(' % name))
    end = start + 1
    while end < len(lines) and (not lines[end].strip()
                                or lines[end].startswith('\t\t')):
        end += 1
    body = '\n'.join(l[1:] if l.startswith('\t') else l
                     for l in lines[start:end])
    return body + '\n'


class Boom(Exception):
    pass


def run_parse(src):
    """Execute alldebrid's parse_magnet_pack with a failing create_transfer.

    Returns the exception it raised, or None."""
    su = types.ModuleType('modules.source_utils')
    su.supported_video_extensions = lambda: ['.mkv', '.mp4']
    mods = types.ModuleType('modules')
    mods.source_utils = su
    sys.modules['modules'] = mods
    sys.modules['modules.source_utils'] = su

    class FakeAPI(object):
        deleted = []

        def create_transfer(self, magnet):
            # exactly the shape of the real failure: AllDebrid answered with an
            # error object, so result['magnets'] is a KeyError
            raise Boom("real debrid provider said no")

        def delete_torrent(self, tid):
            FakeAPI.deleted.append(tid)

    g = {'kodi_utils': types.SimpleNamespace(sleep=lambda ms: None)}
    exec(compile(lift(src, 'parse_magnet_pack'), 'alldebrid_api.py', 'exec'), g)
    try:
        g['parse_magnet_pack'](FakeAPI(), 'magnet:?xt=urn:btih:deadbeef',
                               'deadbeef', True)
        return None
    except Exception as e:
        return e


AD = 'resources/lib/debrids/alldebrid_api.py'
print()
print('=== executing the real function ===')
stock_exc = run_parse(before[AD])
check('STOCK: the handler raises UnboundLocalError (this is the defect)',
      isinstance(stock_exc, (UnboundLocalError, NameError)),
      'got %r -- if stock no longer loses the error, retire this patcher'
      % stock_exc)
check("STOCK: ...and the provider's real error is GONE",
      not isinstance(stock_exc, Boom),
      'stock kept the cause, so there is nothing to fix')

patched_exc = run_parse(after[AD])
check('PATCHED: the provider\'s real error reaches the caller',
      isinstance(patched_exc, Boom),
      'got %r -- the whole point is that the diagnosis survives'
      % patched_exc)
check('PATCHED: and it is not swallowed into a bare None either',
      patched_exc is not None)

# --- 3. idempotence, repatch, revert, CRLF --------------------------------
print()
print('=== the patcher contract ===')
check('a second run is a no-op',
      mod.ensure_patched()
      == 'alldebrid=unchanged, realdebrid=unchanged, torbox=unchanged')
check('and the files did not move on that second run',
      debrid_sources(root) == after)

# Only files this patcher actually writes. modules/debrid.py used to be in
# this loop and, once site 4 was removed, it passed for nothing: _revert() on
# content with no marker line is the identity function, so the assertion held
# for any input. The real property for that file -- that it is left alone --
# is checked above, by name.
for rel, _, _ in mod._SITES:
    check('revert(%s) is byte-exact' % rel.split('/')[-1],
          mod._revert(after[rel]) == before[rel])
    check('...and it really was patched, so that revert had work to do',
          after[rel] != before[rel],
          'a revert check on an untouched file is the identity function')

# an older marker version must be reverted and replaced, not stacked
p = os.path.join(root, *AD.split('/'))
with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(after[AD].replace(mod.MARKER, '# AI_SUBS_POV_DEBRID_UNBOUND_v9'))
st = mod.ensure_patched()
with io.open(p, encoding='utf-8', newline='') as f:
    final = f.read()
check('an older marker is reverted and re-applied', 'alldebrid=repatched' in st,
      st)
check('the older marker is gone', '_UNBOUND_v9' not in final)
check('exactly one initialiser remains', final.count(mod.MARKER) == 1,
      'a repatch that stacks binds the name twice')

home2, root2 = fresh_pov()
p2 = os.path.join(root2, *AD.split('/'))
with io.open(p2, 'w', encoding='utf-8', newline='') as f:
    f.write(before[AD].replace('\n', '\r\n'))
mod2 = load(home2)
st2 = mod2.ensure_patched()
with io.open(p2, encoding='utf-8', newline='') as f:
    crlf = f.read()
check('a CRLF file is still patched', 'alldebrid=patched' in st2, st2)
check('a CRLF file stays CRLF', '\n' not in crlf.replace('\r\n', ''))
check('reverting a CRLF file is byte-exact',
      mod2._revert(crlf, '\r\n') == before[AD].replace('\n', '\r\n'))

# --- a missing file is a per-file 'no_file', never an exception ------------
# The code was right and nothing exercised it, so a refactor of _pov_path or
# _patch_one could have broken it silently. Three shapes: one file gone, the
# whole directory gone, POV not installed at all.
home7, root7 = fresh_pov()
os.remove(os.path.join(root7, 'resources', 'lib', 'debrids', 'alldebrid_api.py'))
mod7 = load(home7)
st7 = mod7.ensure_patched()
check('one missing file is no_file, and the others still patch',
      st7 == 'alldebrid=no_file, realdebrid=patched, torbox=patched', st7)

home8, root8 = fresh_pov()
shutil.rmtree(os.path.join(root8, 'resources', 'lib', 'debrids'))
mod8 = load(home8)
st8 = mod8.ensure_patched()
check('the whole directory missing is three no_file, not a traceback',
      st8 == 'alldebrid=no_file, realdebrid=no_file, torbox=no_file', st8)

home9 = tempfile.mkdtemp(prefix='nopov-')
mod9 = load(home9)
st9 = mod9.ensure_patched()
check('POV not installed at all is handled the same way',
      st9 == 'alldebrid=no_file, realdebrid=no_file, torbox=no_file', st9)
check('...and none of those statuses is one service.py WARNs about',
      not any(p.split('=')[-1] in ('unmatched', 'compile_failed',
                                   'write_failed', 'revert_failed',
                                   'read_failed')
              for p in st9.split(', ')),
      'a device without POV would log a warning every boot')

# --- COEXISTENCE: the sibling patcher runs FIRST on every real device ------
# THE TEST THAT WOULD HAVE CAUGHT THE FIRST DRAFT. Every patcher here was
# tested against a pristine POV tree, and on a real device POV is never
# pristine by the time the next patcher runs -- service.py applies a queue of
# them in one pass. The first draft of this module added a fourth site on
# resolve_external_sources; pov_debrid_resolve_patcher had already been
# guarding that function for months, and it inserts its line BETWEEN the `def`
# and the import, which is the middle of the anchor the fourth site used. It
# would have reported 'unmatched' on every device forever, logging a WARNING
# every boot, and no test would have said a word -- because every test started
# from a clean tree.
#
# So: apply the sibling first, exactly as the startup pass does, then this one.
home5, root5 = fresh_pov()
mod5 = load(home5)
sib_spec = importlib.util.spec_from_file_location(
    '_sib', os.path.join(LIB, 'pov_debrid_resolve_patcher.py'))
sib = importlib.util.module_from_spec(sib_spec)
sib_spec.loader.exec_module(sib)
sib_status = sib.ensure_patched()
check('the sibling patcher still applies (it owns resolve_external_sources)',
      'patch' in str(sib_status).lower() or 'unchanged' in str(sib_status),
      'sibling said %r' % (sib_status,))
after5 = mod5.ensure_patched()
check('and THEN this patcher still gets all three of its own sites',
      after5 == 'alldebrid=patched, realdebrid=patched, torbox=patched',
      'got %r -- a sibling moved a line inside one of these anchors' % after5)
check('...and it reports no unmatched site, which is what would have logged a '
      'WARNING on every boot forever',
      'unmatched' not in after5, after5)

# and the other order, since nothing guarantees the queue keeps its shape
home6, root6 = fresh_pov()
mod6 = load(home6)
first = mod6.ensure_patched()
sib_spec2 = importlib.util.spec_from_file_location(
    '_sib2', os.path.join(LIB, 'pov_debrid_resolve_patcher.py'))
sib2 = importlib.util.module_from_spec(sib_spec2)
sib_spec2.loader.exec_module(sib2)
sib2_status = sib2.ensure_patched()
check('the reverse order works too', 'unmatched' not in first
      and ('patch' in str(sib2_status).lower()
           or 'unchanged' in str(sib2_status)),
      'this=%r sibling=%r' % (first, sib2_status))

# --- SABOTAGE --------------------------------------------------------------
print()
print('=== sabotage ===')
home3, root3 = fresh_pov()
p3 = os.path.join(root3, *AD.split('/'))
with io.open(p3, 'w', encoding='utf-8', newline='') as f:
    f.write(before[AD].replace(
        '\t\tfrom modules.source_utils import supported_video_extensions\n'
        '\t\ttry:\n',
        '\t\tfrom modules.source_utils import supported_video_extensions\n'
        '\t\t# POV moved something\n\t\ttry:\n', 1))
mod3 = load(home3)
st3 = mod3.ensure_patched()
check('SABOTAGE: a moved anchor is refused, not guessed at',
      'alldebrid=unmatched' in st3, st3)
check('SABOTAGE: ...and the others are still patched, because they are '
      'independent files',
      st3.count('=patched') == 2, st3)

_dup = before[AD] + '\n' + before[AD]
home4, root4 = fresh_pov()
with io.open(os.path.join(root4, *AD.split('/')), 'w', encoding='utf-8',
             newline='') as f:
    f.write(_dup)
mod4 = load(home4)
check('SABOTAGE: a DUPLICATED shape is unrecognised, not patched at the first '
      'copy', 'alldebrid=unmatched' in mod4.ensure_patched())

_scan_sab = before[AD].replace('\t\ttorrent_id = self.create_transfer',
                               '\t\tzzz = self.create_transfer')
check('SABOTAGE: the AST scan is sensitive to the name it looks for',
      ('parse_magnet_pack', ('torrent_id',)) not in risky_names(_scan_sab)
      or _scan_sab == before[AD])

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
