"""The extractor writes what differs and nothing else -- and MISSES NOTHING.

WHY THIS EXISTS. A quickfix is a complete snapshot of the build, so every
update rewrote all 1,969 members. 1,330 of them (23.6 MB) live in
addons/skin.fentastic -- the skin that is loaded and rendering the progress
dialog while its own files are replaced underneath it. Measured across five
consecutive releases, the skin changed in NONE of them; a typical release
moves 2-6 files out of 1,968. Kodi was force-closing partway through the
update on real devices, repeatedly, and the extractor reported Errors:0
because nothing had failed -- Kodi died around it.

THE RISK THE FIX INTRODUCES, and the only one that matters: skipping a file
the device actually needs. A user several updates behind must still receive
every file they are missing. That is what most of this file tests, because
"it is faster now" is worthless if it is also lossy.

The comparison is against THE DEVICE'S OWN DISK, not against the previous
release, so it self-adjusts: a current device matches almost everything, a
device four releases behind matches almost nothing. A member is skipped ONLY
when its bytes are already exactly right.

Run: python3 tools/test_extract_skip_unchanged.py
"""
import ast
import os
import zlib
import shutil
import sys
import tempfile
import types
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
EXTRACT = os.path.normpath(os.path.join(
    HERE, '..', 'wizard', 'source', 'plugin.program.kodipovilwizard',
    'resources', 'libs', 'extract.py'))

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def load(src=None):
    """Execute the real `already_on_disk` out of extract.py.

    extract.py imports xbmc and the wizard's whole config at module scope, so
    it cannot be imported here. The function is lifted by AST instead of being
    retyped, or this would test a copy that drifts from the original the first
    time someone edits it.
    """
    with open(EXTRACT, encoding='utf-8') as f:
        text = src if src is not None else f.read()
    tree = ast.parse(text)
    lines = text.split('\n')
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == 'already_on_disk':
            body = '\n'.join(lines[node.lineno - 1:node.end_lineno])
            ns = {'os': os, 'zlib': __import__('zlib')}
            exec(compile(body, 'extract.py', 'exec'), ns)
            return ns['already_on_disk']
    print('FAIL already_on_disk not found in extract.py')
    sys.exit(1)


already_on_disk = load()

TMP = []


def tmpdir(p):
    d = tempfile.mkdtemp(prefix=p)
    TMP.append(d)
    return d


def make_zip(members):
    """members: {name: bytes}"""
    path = os.path.join(tmpdir('exzip-'), 'a.zip')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def lay_down(root, files):
    for name, data in files.items():
        p = os.path.join(root, *name.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(data)


def decide(zip_path, out):
    """What the loop would do: {name: 'skip' | 'write'}."""
    z = zipfile.ZipFile(zip_path)
    return {i.filename: ('skip' if already_on_disk(i, out) else 'write')
            for i in z.infolist()}


# --------------------------------------------------------------------------
# 1. the ordinary case: a current device
# --------------------------------------------------------------------------
ARCHIVE = {
    'addons/skin.fentastic/xml/Home.xml':        b'<window>home</window>',
    'addons/skin.fentastic/media/icon.png':      b'\x89PNG' + b'x' * 900,
    'addons/skin.fentastic/xml/Includes.xml':    b'<includes/>',
    'addons/plugin.video.pov/addon.xml':         b'<addon version="6.08.13"/>',
    'addons/service.subtitles.kodipovilai/service.py': b'print(1)\n' * 40,
    'userdata/guisettings.xml':                  b'<settings/>',
}

out = tmpdir('exout-')
lay_down(out, ARCHIVE)                       # device is fully up to date
z = make_zip(ARCHIVE)
d = decide(z, out)
check('a device already current writes NOTHING',
      list(d.values()).count('write') == 0,
      'would still write: %s' % [k for k, v in d.items() if v == 'write'])

# --------------------------------------------------------------------------
# 2. one changed file -- and it is the only one written
# --------------------------------------------------------------------------
NEW = dict(ARCHIVE)
NEW['addons/service.subtitles.kodipovilai/service.py'] = b'print(2)\n' * 40
z2 = make_zip(NEW)
d = decide(z2, out)
check('a changed file is written',
      d['addons/service.subtitles.kodipovilai/service.py'] == 'write')
check('and it is the ONLY one written',
      list(d.values()).count('write') == 1,
      'also writing: %s' % [k for k, v in d.items()
                            if v == 'write'
                            and not k.endswith('service.py')])

# --------------------------------------------------------------------------
# 3. THE CASE THAT MATTERS: same length, different content
# --------------------------------------------------------------------------
# A size check alone would call this identical and skip it forever. This is
# the single reason the comparison reads the CRC instead of trusting st_size.
SAME_LEN = dict(ARCHIVE)
SAME_LEN['addons/skin.fentastic/xml/Home.xml'] = b'<window>HOME</window>'
assert len(SAME_LEN['addons/skin.fentastic/xml/Home.xml']) == \
    len(ARCHIVE['addons/skin.fentastic/xml/Home.xml'])
z3 = make_zip(SAME_LEN)
d = decide(z3, out)
check('a file that changed WITHOUT changing length is still written',
      d['addons/skin.fentastic/xml/Home.xml'] == 'write',
      'size alone was trusted -- this file would never be updated again')

# A CRC that matches while the SIZE does not must still be written. Dropping
# the size check passed every check in this file until this case existed.
trunc = tmpdir('extrunc-')
lay_down(trunc, ARCHIVE)
tp = os.path.join(trunc, 'addons', 'skin.fentastic', 'xml', 'Home.xml')
with open(tp, 'ab') as f:
    f.write(b'\x00' * 16)          # same CRC is not claimed; the SIZE differs
d = decide(z, trunc)
check('a file whose LENGTH differs is written even before the CRC is read',
      d['addons/skin.fentastic/xml/Home.xml'] == 'write')

# --------------------------------------------------------------------------
# 4. a device several updates behind receives EVERYTHING it is missing
# --------------------------------------------------------------------------
# The reported worry, and the one that would be unforgivable to get wrong.
behind = tmpdir('exold-')
OLD_STATE = {
    # stale content
    'addons/skin.fentastic/xml/Home.xml':        b'<window>v1</window>',
    'addons/plugin.video.pov/addon.xml':         b'<addon version="6.08.09"/>',
    # unchanged since forever
    'addons/skin.fentastic/media/icon.png':      ARCHIVE[
        'addons/skin.fentastic/media/icon.png'],
    # and three members simply absent
}
lay_down(behind, OLD_STATE)
d = decide(make_zip(ARCHIVE), behind)
missing = [n for n in ARCHIVE if n not in OLD_STATE]
stale = ['addons/skin.fentastic/xml/Home.xml',
         'addons/plugin.video.pov/addon.xml']
check('every file the device does NOT have is written',
      all(d[n] == 'write' for n in missing),
      'not written: %s' % [n for n in missing if d[n] != 'write'])
check('every file the device has at the WRONG version is written',
      all(d[n] == 'write' for n in stale),
      'not written: %s' % [n for n in stale if d[n] != 'write'])
check('and the one file it already had correct is skipped',
      d['addons/skin.fentastic/media/icon.png'] == 'skip')
check('so a device 4 updates behind still receives 5 of 6 members',
      list(d.values()).count('write') == 5,
      'wrote %d' % list(d.values()).count('write'))

# --------------------------------------------------------------------------
# 5. every uncertainty writes
# --------------------------------------------------------------------------
edge = tmpdir('exedge-')
EDGE = {'a/f.txt': b'hello', 'a/empty.txt': b'', 'a/dir_like/x.txt': b'q'}
ze = make_zip(EDGE)
d = decide(ze, edge)
check('nothing on disk at all -> everything written',
      list(d.values()).count('write') == len(EDGE))

lay_down(edge, EDGE)
d = decide(ze, edge)
check('a zero-byte member that matches is skipped', d['a/empty.txt'] == 'skip')

# a directory in the way of a file must not read as "already correct"
shutil.rmtree(edge)
os.makedirs(os.path.join(edge, 'a', 'f.txt'))
d = decide(ze, edge)
check('a DIRECTORY where a file belongs is written, not skipped',
      d['a/f.txt'] == 'write')

# Each guard tested DIRECTLY, because indirect attempts do not reach them.
# A NUL in the path looks like it would force an exception -- os.path.isfile
# swallows ValueError itself and returns False, so the comparison exits at the
# isfile line and the exception handler is never entered. chmod 0 is worse:
# it is a no-op for root, which is how CI runs. Both mutations survived this
# file until these three cases existed.
unread = tmpdir('exunread-')
lay_down(unread, EDGE)
real_size = len(EDGE['a/f.txt'])
real_crc = zlib.crc32(EDGE['a/f.txt']) & 0xffffffff


class Item(object):
    def __init__(self, filename, file_size, CRC):
        self.filename, self.file_size, self.CRC = filename, file_size, CRC


check('SELF-CHECK: the fixture matches when it should',
      already_on_disk(Item('a/f.txt', real_size, real_crc), unread) is True,
      'the direct-item cases below would prove nothing')

check('a right CRC with a WRONG size is written',
      already_on_disk(Item('a/f.txt', real_size + 1, real_crc),
                      unread) is False,
      'the size guard is doing no work -- CRC alone is not identity')

check('a right size with a WRONG CRC is written',
      already_on_disk(Item('a/f.txt', real_size, real_crc ^ 0xffff),
                      unread) is False)

# The '..' sanitisation. zipfile.extract DROPS '..' components before
# joining, so member 'a/../f.txt' is written to <out>/a/f.txt. A filter that
# removes only empty components inspects <out>/a/../f.txt instead, which
# resolves to <out>/f.txt -- a DIFFERENT FILE. Put matching bytes at that
# wrong path and the comparison must still say "write", because the real
# target does not have them.
dots = tmpdir('exdots-')
# 'a/' must EXIST, or the unsanitised path <out>/a/../f.txt fails on isfile
# for the wrong reason and the buggy filter looks correct. That is exactly
# how this case passed a mutated build the first time it was written.
lay_down(dots, {'f.txt': EDGE['a/f.txt'],           # the WRONG location
                'a/other.txt': b'so a/ exists'})
check('a member containing ".." is judged at the path extract() writes',
      already_on_disk(Item('a/../f.txt', real_size, real_crc), dots) is False,
      'it matched a file at the unsanitised path, so the real target would '
      'be skipped and never written')
lay_down(dots, {'a/f.txt': EDGE['a/f.txt']})        # the RIGHT location
check('and it matches once the real target is there',
      already_on_disk(Item('a/../f.txt', real_size, real_crc), dots) is True)

# An exception INSIDE the comparison, reached no other way.
_raiser = load()
_ns = _raiser.__globals__


class _BoomPath(object):
    """The real os.path, except getsize explodes. Delegating rather than
    re-declaring: a hand-built stand-in was missing curdir/pardir and the
    comparison died on an AttributeError instead of reaching the handler,
    which proved nothing at all."""
    def __getattr__(self, k):
        return getattr(os.path, k)

    @staticmethod
    def isfile(q):
        return True

    @staticmethod
    def getsize(q):
        raise OSError('storage went away mid-update')


class _BoomOS(object):
    path = _BoomPath()

    def __getattr__(self, k):
        return getattr(os, k)


_ns['os'] = _BoomOS()
check('an exception anywhere in the comparison writes, never skips',
      _raiser(Item('a/f.txt', real_size, real_crc), unread) is False,
      'the handler returned True -- every I/O hiccup would silently skip a '
      'file, which is the one thing this function must never do')

# explicit directory entries in the archive are never "already on disk"
dz = os.path.join(tmpdir('exdirent-'), 'd.zip')
with zipfile.ZipFile(dz, 'w') as z_:
    z_.writestr('a/', b'')
    z_.writestr('a/f.txt', b'hello')
d = decide(dz, unread)
check('an archive directory entry that already exists is skipped',
      d['a/'] == 'skip',
      "198 of the 1,969 members are directory entries; counting them as "
      "writes made a 5-file update look like a 203-file one")
fresh = tmpdir('exfresh-')
check('but on a fresh device the directory entry IS created',
      decide(dz, fresh)['a/'] == 'write')

# --------------------------------------------------------------------------
# 6. against the REAL quickfixes, if they are here
# --------------------------------------------------------------------------
DIST = os.path.normpath(os.path.join(HERE, '..', 'dist'))
prev = os.path.join(DIST, 'Kodi-POV-IL-FENtastic-quickfix-0.1.543.zip')
cur = os.path.join(DIST, 'Kodi-POV-IL-FENtastic-quickfix-0.1.544.zip')
if os.path.isfile(prev) and os.path.isfile(cur):
    real = tmpdir('exreal-')
    zp = zipfile.ZipFile(prev)
    zp.extractall(real)                      # a device on the last release
    d = decide(cur, real)
    w = [k for k, v in d.items() if v == 'write']
    skin_w = [k for k in w if k.startswith('addons/skin.fentastic/')]
    print()
    print('   real 0.1.543 device receiving 0.1.544: %d of %d members written'
          % (len(w), len(d)))
    check('the real update writes a handful, not a build',
          len(w) <= 20, 'wrote %d: %s' % (len(w), w[:8]))
    check('and it does not touch the live skin at all',
          len(skin_w) == 0,
          'would still rewrite %d skin files' % len(skin_w))
else:
    print()
    print('   (dist quickfixes not present -- real-archive check skipped)')

# --------------------------------------------------------------------------
# 7. THE OWNER'S WORRY, against ground truth: a device MANY updates behind
# --------------------------------------------------------------------------
# "what if someone missed 10 updates" -- so this checks 10, 50 and 186, and it
# does not trust the decision function to grade itself. Ground truth is
# recomputed from the bytes on disk, and the assertion that matters is
# WRONGLY SKIPPED == 0. A needless write is wasted effort; a wrong skip is a
# file the device never receives, which is the only outcome here that would
# actually hurt someone.
def _truth_same(item, root):
    path = os.path.join(root, *[q for q in item.filename.split('/')
                                if q not in ('', os.path.curdir, os.path.pardir)])
    if item.filename.endswith('/'):
        return os.path.isdir(path)
    if not (os.path.isfile(path)
            and os.path.getsize(path) == item.file_size):
        return False
    with open(path, 'rb') as fh:
        return (zlib.crc32(fh.read()) & 0xffffffff) == (item.CRC & 0xffffffff)


print()
for _old in ('0.1.534', '0.1.494', '0.1.358'):
    _p = os.path.join(DIST, 'Kodi-POV-IL-FENtastic-quickfix-%s.zip' % _old)
    if not (os.path.isfile(_p) and os.path.isfile(cur)):
        print('   (quickfix %s absent -- span check skipped)' % _old)
        continue
    _dev = tmpdir('exspan-')
    zipfile.ZipFile(_p).extractall(_dev)
    _bad, _wrote, _skipped = [], 0, 0
    for _i in zipfile.ZipFile(cur).infolist():
        _skip = already_on_disk(_i, _dev)
        if _skip and not _truth_same(_i, _dev):
            _bad.append(_i.filename)
        _skipped += _skip
        _wrote += not _skip
    _n = 544 - int(_old.rsplit('.', 1)[1])
    print('   %3d updates behind: %d written, %d skipped' % (_n, _wrote, _skipped))
    check('a device %d updates behind loses NOTHING' % _n, not _bad,
          'wrongly skipped %d, e.g. %s' % (len(_bad), _bad[:3]))
    shutil.rmtree(_dev, ignore_errors=True)

# --------------------------------------------------------------------------
# SABOTAGE
# --------------------------------------------------------------------------
# The progress count is incremented BEFORE the ASCII gate. Structural, not
# behavioural: the loop needs a whole Kodi to run, but the ordering is the
# entire fix -- a member rejected by the gate must still advance `count`, or
# `count == nFiles` never becomes true and the bar stops short. Six such names
# exist in dist/Kodi-POV-IL-AF3-skin-pack.zip today.
with open(EXTRACT, encoding='utf-8') as f:
    _src = f.read()
_body = _src[_src.index('for item in zin.infolist():'):]
_at_count = _body.find('count += 1')
_at_ascii = _body.find("encode('ascii')")
check('count is incremented before the ASCII gate, not after',
      _at_count != -1 and _at_ascii != -1 and _at_count < _at_ascii,
      'a non-ASCII member advances nFiles but not count, so the final '
      'redraw never fires and the bar stalls below 100%')

print()
print('=== sabotage ===')

with open(EXTRACT, encoding='utf-8') as f:
    SRC = f.read()

# size-only: the classic wrong version of this fix
sized = SRC.replace(
    '        crc = 0\n', '        return True\n        crc = 0\n', 1)
check('SABOTAGE: the size-only sabotage applies', sized != SRC)
aod = load(sized)
zz = zipfile.ZipFile(z3)
info = {i.filename: i for i in zz.infolist()}
check('SABOTAGE: trusting size alone is caught',
      aod(info['addons/skin.fentastic/xml/Home.xml'], out) is True,
      'the size-only variant should wrongly report "already correct" here')

# swallow-everything: a comparison that always says "skip"
always = SRC.replace('    name = item.filename\n',
                     '    return True\n    name = item.filename\n', 1)
check('SABOTAGE: the always-skip sabotage applies', always != SRC)
aod = load(always)
zb = zipfile.ZipFile(make_zip(ARCHIVE))
check('SABOTAGE: a comparison that always skips is caught',
      all(aod(i, behind) for i in zb.infolist()),
      'the always-skip variant should skip files this device does not have')

for d_ in TMP:
    shutil.rmtree(d_, ignore_errors=True)

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
