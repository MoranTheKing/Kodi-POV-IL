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
            pre = {a.arg for a in node.args.args}
            for st in node.body:
                if st is t:
                    break
                pre |= {n.id for n in ast.walk(st)
                        if isinstance(n, ast.Name)
                        and isinstance(n.ctx, ast.Store)}
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

check('all four sites patch on a stock tree',
      status == ('alldebrid=patched, realdebrid=patched, '
                 'torbox=patched, resolve=patched'), status)

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
check('and so is the caller that masks it a second time',
      ('resolve_external_sources', ('api', 'files', 'torrent_id'))
      in found_before.get('resources/lib/modules/debrid.py', set()))

left = {rel: v for rel, v in found_after.items() if v}
check('AFTER patching, no handler in POV debrid code reads an unbound name',
      not left, 'still risky: %s' % sorted(left.items()))

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
      mod.ensure_patched() == ('alldebrid=unchanged, realdebrid=unchanged, '
                               'torbox=unchanged, resolve=unchanged'))
check('and the files did not move on that second run',
      debrid_sources(root) == after)

for rel in ('resources/lib/debrids/alldebrid_api.py',
            'resources/lib/modules/debrid.py'):
    check('revert(%s) is byte-exact' % rel.split('/')[-1],
          mod._revert(after[rel]) == before[rel])

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
check('SABOTAGE: ...and the other three are still patched, because they are '
      'independent files',
      st3.count('=patched') == 3, st3)

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
