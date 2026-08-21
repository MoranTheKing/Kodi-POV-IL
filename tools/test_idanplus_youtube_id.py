"""Idan Plus must send YouTube a video id, not the word "watch".

THE REPORT: nothing from Kan 11 plays and a YouTube toast says "This video is
unavailable". The log named the cause without ambiguity:

    Params: {'video_id': 'watch'}
    video_id: 'watch'  Client: 'tv_unplugged'  Reason: 'This video is unavailable'
    ... and the same for tv, ios_testsuite_params, android_testsuite_params,
    android_vr

Five player clients, five identical refusals, because no video has the id
"watch". YouTube answered correctly. The question was wrong.

`common.GetYouTube` reads the id out of the URL PATH and truncates at '?',
which is precisely where the id lives in the ordinary youtube.com/watch?v=
form. Kan evidently moved from embed links to watch links and nothing on the
add-on side could read them.

WHAT THIS FILE PINS, beyond "the marker is in the file":

  * the STOCK function really does return 'watch', executed, not asserted --
    otherwise this is a fix for a bug nobody has shown;
  * the patched one returns the id for every URL shape, and returns the SAME
    ANSWER as stock for every shape stock already got right. That agreement is
    what makes it safe to leave in place if Idan Plus ever fixes it too;
  * it retires itself. An upstream fix must produce a quiet 'already_fixed',
    not an 'unmatched' that logs a WARNING on every boot forever;
  * and it works on BOTH the 3.9.1 the build ships and the 4.0.2 devices
    self-update to, whose GetYouTube is byte-identical.

Run: python3 tools/test_idanplus_youtube_id.py
"""
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
LIB = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
SCRATCH = ('/tmp/claude-0/-home-user-Kodi-POV-IL/'
           '70968383-5f01-52a3-afe7-ced1aba28071/scratchpad')
TREES = {
    '3.9.1 (shipped in the build)':
        os.environ.get('IDANPLUS_391')
        or SCRATCH + '/idan/addons/plugin.video.idanplus',
    '4.0.2 (what devices self-update to)':
        os.environ.get('IDANPLUS_402')
        or SCRATCH + '/idan402/plugin.video.idanplus',
}

FAIL = []
_DIRS = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


# The real function, verbatim. Used when no add-on tree is present, so this
# proves something on any machine: a test that skips is indistinguishable from
# one that passes.
FIXTURE = (
    "import re\n"
    "youtubePlugin = 'plugin://plugin.video.youtube'\n"
    "\n"
    "def GetYouTube(url):\n"
    "\tif url.endswith('/'):\n"
    "\t\turl = url[:-1]\n"
    "\tvideo_id = url[url.rfind('/')+1:]\n"
    "\tif '?' in video_id:\n"
    "\t\tvideo_id = video_id[:video_id.find('?')]\n"
    "\treturn '{0}/play/?video_id={1}'.format(youtubePlugin, video_id)\n"
    "\n"
    "def _after(x):\n"
    "\treturn x\n"
)


def load(home):
    for n in list(sys.modules):
        if n.split('.')[0] in ('resources', 'xbmcvfs'):
            sys.modules.pop(n, None)
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
    spec = importlib.util.spec_from_file_location(
        'idan_yt', os.path.join(LIB, 'idanplus_youtube_id_patcher.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def fresh(tree=None, body=None):
    """An Idan Plus tree the patcher can work on. Real if one is present."""
    home = tempfile.mkdtemp(prefix='idanyt-')
    _DIRS.append(home)
    dst = os.path.join(home, 'addons', 'plugin.video.idanplus')
    if tree and os.path.isdir(tree):
        shutil.copytree(tree, dst)
    else:
        os.makedirs(os.path.join(dst, 'resources', 'lib'))
        with io.open(os.path.join(dst, 'resources', 'lib', 'common.py'),
                     'w', encoding='utf-8', newline='') as f:
            f.write(body or FIXTURE)
    return home, os.path.join(dst, 'resources', 'lib', 'common.py')


def run_fn(source, url):
    """EXECUTE GetYouTube out of that source and return the id it produces."""
    g = {}
    body = source[source.index('def GetYouTube(url):'):]
    nxt = body.find('\ndef ', 1)
    if nxt != -1:
        body = body[:nxt]
    exec("import re\nyoutubePlugin = 'plugin://plugin.video.youtube'\n" + body,
         g)
    return g['GetYouTube'](url).split('video_id=')[1]


# Every shape a Kan item can carry. The first is the one that breaks.
BROKEN = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
ALREADY_OK = (
    'https://youtu.be/dQw4w9WgXcQ',
    'https://youtu.be/dQw4w9WgXcQ/',
    'https://youtu.be/dQw4w9WgXcQ?t=30',
    'https://www.youtube.com/embed/dQw4w9WgXcQ',
    'https://www.youtube.com/live/dQw4w9WgXcQ',
)
ALSO_BROKEN = (
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s',
    'https://www.youtube.com/watch?list=PL123&v=dQw4w9WgXcQ',
)
WANT = 'dQw4w9WgXcQ'

real = [t for t in TREES.values() if os.path.isdir(t)]
print('fixture: %s' % ('real Idan Plus trees (%d)' % len(real) if real
                       else 'inline (no add-on tree on this machine)'))

for label, tree in list(TREES.items()) + [('inline fixture', None)]:
    if tree is not None and not os.path.isdir(tree):
        print('---- %s NOT CHECKED (tree not on this machine)' % label)
        continue
    home, cp = fresh(tree)
    before = io.open(cp, encoding='utf-8', newline='').read()
    mod = load(home)

    # the defect, demonstrated rather than asserted
    check('%s: STOCK really returns "watch" for a watch?v= url' % label,
          run_fn(before, BROKEN) == 'watch',
          'got %r -- this version does not have the bug being fixed'
          % run_fn(before, BROKEN))

    st = mod.ensure_patched()
    after = io.open(cp, encoding='utf-8', newline='').read()
    check('%s: it patches' % label, st == 'patched', st)
    check('%s: the fixed url now resolves' % label,
          run_fn(after, BROKEN) == WANT, 'got %r' % run_fn(after, BROKEN))
    for u in ALSO_BROKEN:
        check('%s: %s resolves' % (label, u.split('?')[1]),
              run_fn(after, u) == WANT, 'got %r' % run_fn(after, u))

    # THE PROPERTY THAT MAKES IT SAFE TO LEAVE IN PLACE
    same = [u for u in ALREADY_OK if run_fn(before, u) == run_fn(after, u)]
    check('%s: every url stock already got right is UNCHANGED' % label,
          len(same) == len(ALREADY_OK),
          'changed: %s' % [u for u in ALREADY_OK if u not in same])
    check('%s: ...and those were all correct to begin with' % label,
          all(run_fn(before, u) == WANT for u in ALREADY_OK))

    check('%s: a second run is a no-op' % label,
          mod.ensure_patched() == 'unchanged')
    check('%s: revert is byte-exact' % label, mod._revert(after) == before)
    crlf_home, crlf_cp = fresh(body=before.replace('\n', '\r\n'))
    crlf_mod = load(crlf_home)
    check('%s: a CRLF copy patches too' % label,
          crlf_mod.ensure_patched() == 'patched')
    with io.open(crlf_cp, encoding='utf-8', newline='') as f:
        crlf_after = f.read()
    check('%s: CRLF stays CRLF' % label,
          '\n' not in crlf_after.replace('\r\n', ''))
    check('%s: and reverts byte-exact' % label,
          crlf_mod._revert(crlf_after, '\r\n') == before.replace('\n', '\r\n'))

# --- IT RETIRES ITSELF ------------------------------------------------------
# The question this was designed around: if Idan Plus ships its own fix, does
# this become a problem, or does it just stop? It stops -- and quietly, which
# matters, because 'unmatched' is a status service.py WARNs about and a patcher
# that outlives its bug becomes noise on every boot forever.
print()
print('=== what happens when Idan Plus fixes it upstream ===')
BAD = ('unmatched', 'compile_failed', 'write_failed', 'revert_failed',
       'read_failed')
UPSTREAM = {
    'they parse the v= parameter':
        "import re\nyoutubePlugin = 'x'\n\n"
        "def GetYouTube(url):\n"
        "\tfrom urllib.parse import urlparse, parse_qs\n"
        "\tq = parse_qs(urlparse(url).query)\n"
        "\tvideo_id = q['v'][0] if 'v' in q else url.rstrip('/').rsplit('/', 1)[-1]\n"
        "\treturn '{0}/play/?video_id={1}'.format(youtubePlugin, video_id)\n",
    'they regex it':
        "import re\nyoutubePlugin = 'x'\n\n"
        "def GetYouTube(url):\n"
        "\tm = re.search(r'[?&]v=([\\w-]+)', url)\n"
        "\tvideo_id = m.group(1) if m else url.rstrip('/').rsplit('/', 1)[-1]\n"
        "\treturn '{0}/play/?video_id={1}'.format(youtubePlugin, video_id)\n",
}
for label, body in UPSTREAM.items():
    home, cp = fresh(body=body)
    before = io.open(cp, encoding='utf-8', newline='').read()
    mod = load(home)
    st = mod.ensure_patched()
    after = io.open(cp, encoding='utf-8', newline='').read()
    check('%s -> it stands down' % label, st == 'already_fixed', st)
    check('%s -> the file is untouched' % label, after == before)
    check('%s -> and it does NOT log a warning every boot' % label,
          st not in BAD)

# An unrecognisable rewrite is a different thing and SHOULD be noisy: we
# genuinely cannot tell whether it is fixed, and that is worth knowing.
home, cp = fresh(body="youtubePlugin = 'x'\n\ndef GetYouTube(url):\n"
                      "\tvideo_id = extract_id(url)\n"
                      "\treturn '{0}/play/?video_id={1}'.format("
                      "youtubePlugin, video_id)\n")
before = io.open(cp, encoding='utf-8', newline='').read()
mod = load(home)
st = mod.ensure_patched()
check('an unrecognisable rewrite is refused, not guessed at',
      st == 'unmatched', st)
check('...and reported, because we cannot tell if it is fixed',
      st in BAD)
check('...with the file untouched',
      io.open(cp, encoding='utf-8', newline='').read() == before)

# --- absent / broken installs ----------------------------------------------
print()
print('=== absent and malformed installs ===')
home = tempfile.mkdtemp(prefix='noidan-')
_DIRS.append(home)
check('no Idan Plus at all is no_file, not a traceback',
      load(home).ensure_patched() == 'no_file')
home, cp = fresh(body="youtubePlugin = 'x'\n\ndef Something():\n\tpass\n")
check('a common.py without GetYouTube is no_function',
      load(home).ensure_patched() == 'no_function')

# --- SABOTAGE ---------------------------------------------------------------
print()
print('=== sabotage ===')
home, cp = fresh(TREES['4.0.2 (what devices self-update to)']
                 if os.path.isdir(TREES['4.0.2 (what devices self-update to)'])
                 else None)
before = io.open(cp, encoding='utf-8', newline='').read()
mod = load(home)
_real_fix = mod._FIX
try:
    mod._FIX = "\tvideo_id = (\n"          # will not compile
    st = mod.ensure_patched()
    after = io.open(cp, encoding='utf-8', newline='').read()
finally:
    mod._FIX = _real_fix
check('SABOTAGE: an injected line that will not compile is refused',
      st == 'compile_failed', st)
check('SABOTAGE: ...and the file is untouched, because the check runs first',
      after == before)
check('SABOTAGE: the real line was put back', mod._FIX == _real_fix)

_dup_home, _dup_cp = fresh(body=FIXTURE + '\n' + FIXTURE.split('import re\n')[1])
_dup_before = io.open(_dup_cp, encoding='utf-8', newline='').read()
_dup_mod = load(_dup_home)
_dup_st = _dup_mod.ensure_patched()
check('SABOTAGE: a duplicated shape is refused, not patched at the first copy',
      _dup_st == 'unmatched', _dup_st)
check('SABOTAGE: ...file untouched',
      io.open(_dup_cp, encoding='utf-8', newline='').read() == _dup_before)

for d in _DIRS:
    shutil.rmtree(d, ignore_errors=True)

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
