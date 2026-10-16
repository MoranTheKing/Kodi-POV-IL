"""Compile add-on sources to bytecode once, so Kodi stops recompiling them on every click.

Kodi starts every add-on interpreter with PYTHONDONTWRITEBYTECODE=1 (QA Kodi
21: sys.dont_write_bytecode is True), so Python never caches what it compiles:
every POV list -- every widget, every category -- compiled 25-31 modules from
source again (0.04 s of 0.16-0.22 s on a PC, several times that on an Android
box). Python still READS a valid .pyc, so we write them ourselves:

* in Kodi's own interpreter, so the magic number, cache tag and optimisation
  level are exactly the ones the import system looks for;
* timestamp-checked (source mtime + size, the CPython default): a file the
  patch engine or an add-on update rewrites gets a new pyc on the next pass,
  and until then Python simply compiles it as before;
* in the background, one file at a time with a short sleep in between, never
  while a video plays -- Kodi's add-on interpreters share one lock, and a
  long uninterrupted compile would hold back every other script.
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
MAX_SOURCE_BYTES = 2 * 1024 * 1024
PAUSE_S = 0.02


def _pyc_current(source, cfile):
    """True when cfile is a timestamp pyc for source as it is now."""
    try:
        st = os.stat(source)
        with open(cfile, 'rb') as fh:
            head = fh.read(16)
    except OSError:
        return False
    if len(head) < 16 or head[:4] != importlib.util.MAGIC_NUMBER:
        return False
    flags, mtime, size = struct.unpack('<III', head[4:16])
    return flags == 0 and mtime == (int(st.st_mtime) & 0xFFFFFFFF) and size == (st.st_size & 0xFFFFFFFF)


def sources(addons_dir):
    """Python sources of every add-on under addons_dir, PRIORITY add-ons first."""
    try:
        names = sorted(n for n in os.listdir(addons_dir)
                       if n not in ('packages', 'temp') and os.path.isdir(os.path.join(addons_dir, n)))
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
        try:
            py_compile.compile(source, cfile=cfile, doraise=True,
                               invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
            compiled += 1
        except (py_compile.PyCompileError, OSError, ValueError, SyntaxError):
            failed += 1   # Python 2 leftovers, read-only trees: leave them as they are
        sleep(pause_s)
    return compiled, current, failed
