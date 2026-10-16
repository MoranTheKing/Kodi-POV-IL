"""Compile add-on sources to bytecode once, so Kodi stops recompiling them on every click.

Kodi starts every add-on interpreter with PYTHONDONTWRITEBYTECODE=1 (QA Kodi
21: sys.dont_write_bytecode is True), so Python never caches what it compiles:
every POV list -- every widget, every category -- compiled 25-31 modules from
source again (0.04 s of 0.16-0.22 s on a PC, several times that on an Android
box). Python still READS a valid .pyc, so we write them ourselves:

* in Kodi's own interpreter, so the magic number, cache tag and optimisation
  level are exactly the ones the import system looks for;
* hash-checked (PEP 552 CHECKED_HASH): the pyc carries a hash of the exact
  bytes that were compiled and Python verifies it on every import, so a file
  rewritten during or after the compile (patch engine, add-on update) can
  never run stale code -- Python just compiles it as before until the next
  pass writes a fresh pyc;
* in the background, one file at a time with a pause at least twice as long
  as the compile, never while a video plays -- Kodi's add-on interpreters
  share one lock, and a long uninterrupted compile holds back every other
  script; very large files are left alone for the same reason.
"""
import importlib.util
import os
import py_compile
import struct
import time

# Add-ons first in this order, then every other add-on with Python sources.
PRIORITY = ('plugin.video.pov', 'plugin.program.kodipovilwizard',
            'service.subtitles.kodipovilai', 'script.module.requests',
            'script.module.urllib3', 'script.module.certifi', 'script.module.idna',
            'script.module.chardet')
SKIP_DIRS = {'__pycache__', '.git', 'tests', 'test'}
MAX_SOURCE_BYTES = 512 * 1024
MAX_WRITE_ERRORS = 20      # read-only or full storage: stop the pass
PAUSE_S = 0.02


def _pyc_current(source, cfile):
    """True when cfile is a checked-hash pyc of source's current bytes."""
    try:
        with open(cfile, 'rb') as fh:
            head = fh.read(16)
        if len(head) < 16 or head[:4] != importlib.util.MAGIC_NUMBER:
            return False
        if struct.unpack('<I', head[4:8])[0] != 0b11:     # hash-based, checked
            return False
        with open(source, 'rb') as fh:
            return importlib.util.source_hash(fh.read()) == head[8:16]
    except OSError:
        return False


def sources(addons_dir):
    """Python sources of every add-on under addons_dir, PRIORITY add-ons first."""
    try:
        # Hidden folders are the Wizard's own staging and rollback trees.
        names = sorted(n for n in os.listdir(addons_dir)
                       if n not in ('packages', 'temp') and not n.startswith('.')
                       and os.path.isdir(os.path.join(addons_dir, n)))
    except OSError:
        return
    order = [n for n in PRIORITY if n in names] + [n for n in names if n not in PRIORITY]
    for name in order:
        for root, dirs, files in os.walk(os.path.join(addons_dir, name)):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith('.'))
            for f in sorted(files):
                if f.endswith('.py'):
                    yield os.path.join(root, f)


def warm(addons_dir, should_stop=lambda: False, should_pause=lambda: False,
         sleep=time.sleep, pause_s=PAUSE_S):
    """One pass: (compiled, current, failed). Stops early when should_stop()."""
    compiled = current = failed = 0
    write_errors = 0
    for source in sources(addons_dir):
        while should_pause():
            if should_stop():
                return compiled, current, failed
            sleep(5)
        if should_stop():
            break
        try:
            if os.path.getsize(source) > MAX_SOURCE_BYTES:
                continue
            cfile = importlib.util.cache_from_source(source)
        except (OSError, ValueError, NotImplementedError):
            continue
        if _pyc_current(source, cfile):
            current += 1
            continue
        started = time.monotonic()
        try:
            py_compile.compile(source, cfile=cfile, doraise=True,
                               invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
            compiled += 1
            write_errors = 0
        except OSError:
            failed += 1
            write_errors += 1
            if write_errors >= MAX_WRITE_ERRORS:
                break
        except (py_compile.PyCompileError, ValueError, SyntaxError):
            failed += 1   # Python 2 leftovers: leave them as they are
        sleep(max(pause_s, 2 * (time.monotonic() - started)))
    return compiled, current, failed
