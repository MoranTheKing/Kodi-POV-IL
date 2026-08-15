"""pool.py is FROZEN in this container. Editing it stops a release dead.

The community-pool credential lives inside pool.py between __POOL_KEY_BEGIN__
and __POOL_KEY_END__, and it is not in git and not in this container. A release
cut here gets it by INHERITANCE: build_ai_subtitles_packages.py copies pool.py
byte-for-byte out of the previously shipped zip. That copy takes the whole
file, so it would silently discard any edit made to pool.py -- and rather than
do that, inherit_pool_credential() refuses outright.

The refusal is right. What was wrong was WHEN it arrived: 0.2.496's release
reached step 3 of an eleven-step chain, with three version files already
bumped, before anything said pool.py had changed. The change was one line of a
seventy-line sweep across ~40 files (`except OSError` -> `except Exception`),
made in a different session, by someone not thinking about packaging at all.

So this test moves that discovery to the front. It is not a second copy of the
build tool's guard; it is the same fact asserted at a different time, where it
costs a one-line revert instead of a half-done release.

WHAT THIS MEANS IN PRACTICE: do not edit pool.py here. Not the logic, not a
comment, not whitespace -- the comparison is bytes outside the key block, and a
comment is bytes. A genuine pool.py change has to be packaged by the maintainer
with $POOL_SECRET set, and this test steps aside when it is, because then the
credential can be re-injected rather than inherited.

Run: python3 tools/test_pool_py_frozen.py
"""
import os
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
POOL_PY = ROOT / 'addons' / 'service.subtitles.kodipovilai' / 'resources' / 'lib' / 'pool.py'
DIST = ROOT / 'dist'
MEMBER = 'service.subtitles.kodipovilai/resources/lib/pool.py'
KEY_BLOCK = re.compile(rb'(__POOL_KEY_BEGIN__).*?(__POOL_KEY_END__)', re.S)

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def outside_key_block(data):
    """The file with the credential blanked, so we compare logic and nothing
    else. Blanking rather than deleting keeps the markers themselves in the
    comparison -- losing them is a change worth catching."""
    return KEY_BLOCK.sub(rb'\1\2', data)


def _version_key(p):
    m = re.search(r'-build-(\d+)\.(\d+)\.(\d+)\.zip$', p.name)
    return tuple(int(g) for g in m.groups()) if m else (-1, -1, -1)


def newest_shipped_zip():
    """The highest-numbered build zip in dist/. That is what a release cut here
    inherits from, so it is what pool.py has to match."""
    zips = [p for p in DIST.glob('service.subtitles.kodipovilai-build-*.zip')
            if _version_key(p) != (-1, -1, -1)]
    return max(zips, key=_version_key) if zips else None


def shipped_pool_py(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        if MEMBER not in zf.namelist():
            return None
        return zf.read(MEMBER)


def run(local_bytes=None):
    """Returns (verdict, detail). verdict is True when the tree is releasable
    from this container."""
    zp = newest_shipped_zip()
    if zp is None:
        return None, 'no shipped build zip in dist/ to compare against'
    shipped = shipped_pool_py(zp)
    if shipped is None:
        return None, '%s has no %s' % (zp.name, MEMBER)
    local = POOL_PY.read_bytes() if local_bytes is None else local_bytes
    same = outside_key_block(local) == outside_key_block(shipped)
    return same, zp.name


# --- the real check --------------------------------------------------------
if os.environ.get('POOL_SECRET', '').strip():
    print('POOL_SECRET is set -- pool.py may change; the credential gets')
    print('re-injected rather than inherited. Nothing to freeze.')
    print()
    print('ALL PASS')
    sys.exit(0)

verdict, detail = run()
check('a shipped build zip exists to compare against', verdict is not None,
      detail)

if verdict is not None:
    check('pool.py is unchanged from the last shipped zip (%s)' % detail,
          verdict,
          'pool.py was edited and $POOL_SECRET is absent, so this tree CANNOT '
          'be released from here. Revert pool.py, or package it where the '
          'credential is available. Even a comment counts.')

    # --- SABOTAGE: the check has to be able to fail ------------------------
    # Without this, "pool.py is unchanged" is green on a tree where the
    # comparison is broken just as happily as on a tree that is really clean.
    edited = POOL_PY.read_bytes().replace(b'except OSError:',
                                          b'except Exception:', 1)
    check('SABOTAGE: an edit outside the key block is detected',
          edited != POOL_PY.read_bytes() and run(edited)[0] is False,
          'a one-line edit did not trip the comparison -- the check above '
          'proves nothing')

    # ...and a change to the CREDENTIAL alone must NOT trip it, or every
    # release would look like an illegal edit of pool.py.
    local = POOL_PY.read_bytes()
    m = KEY_BLOCK.search(local)
    if m:
        rekeyed = local[:m.start()] + b'__POOL_KEY_BEGIN__x__POOL_KEY_END__' \
            + local[m.end():]
        check('a different credential is NOT treated as a logic change',
              rekeyed != local and run(rekeyed)[0] is True,
              'the key block is leaking into the comparison')
    else:
        check('pool.py still carries the credential markers', False,
              '__POOL_KEY_BEGIN__/__POOL_KEY_END__ not found')

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
