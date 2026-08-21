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
form.

AND THE ADD-ON BUILDS THAT URL ITSELF. Kan's mobile API returns a BARE id --
`content.type='youtube-id'`, `content.src='oRFeZUO5GVw'` -- and kan.py's
_mobStreamFromEntry wraps it into `watch?v=<id>` before handing it to
GetYouTube, which unwraps it back to 'watch'. A round trip that destroys the
data. So this is not a regression and not something Kan changed: every Kan
item of that type has always failed. Verified against the live API -- all five
episodes of the reported program return 'watch' on stock.

WHAT THIS FILE PINS, beyond "the marker is in the file":

  * the STOCK function really does return 'watch', executed, not asserted --
    otherwise this is a fix for a bug nobody has shown;
  * the patched one returns the id for every broken URL shape, and returns the
    SAME ANSWER as stock for every shape stock already got right. That
    agreement is what makes it safe to leave in place if Idan Plus ever fixes
    it too;
  * it stands down on a shape it does not recognise -- WITHOUT running any of
    the add-on's code to decide, and WITHOUT going quiet. Both cleverer
    mechanisms were tried and both failed review; this file pins the plain
    behaviour that replaced them, including that no `exec` survives in the
    patcher;
  * and it works on BOTH the 3.9.1 the build ships and the 4.0.2 devices
    self-update to, whose GetYouTube is byte-identical.

Run: python3 tools/test_idanplus_youtube_id.py
"""
import ast
import importlib.util
import io
import re
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
LIB = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                   'resources', 'lib')
PATCHER = os.path.join(LIB, 'idanplus_youtube_id_patcher.py')
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
    spec = importlib.util.spec_from_file_location('idan_yt', PATCHER)
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
    """EXECUTE GetYouTube out of that source and return the id it produces.

    Only ever called on this file's own fixtures and on the one function the
    patcher touches -- never as part of the patcher's own decision. That
    distinction is the whole point of round 2's finding: a test may run a
    fixture it wrote; a service running on somebody's device may not run a
    third party's module-level code to decide whether to patch it.
    """
    g = {}
    # STOP AT THE FIRST MODULE-LEVEL LINE, not at the next `def`. Round 2's
    # in-patcher version searched for `\ndef ` and so swallowed whatever sat
    # between the function and the next one -- on the real 4.0.2 tree that is
    # a module-level `_cfSession = {...}`, which it would then have executed.
    # Harmless there and harmless here, but the slice has no business
    # containing it either way, and review round 3 confirmed it did.
    lines = source[source.index('def GetYouTube(url):'):].split('\n')
    body = [lines[0]]
    for ln in lines[1:]:
        if ln.strip() and not ln[:1].isspace():
            break
        body.append(ln)
    exec("import re\nyoutubePlugin = 'plugin://plugin.video.youtube'\n"
         + '\n'.join(body), g)
    return g['GetYouTube'](url).split('video_id=')[1]


IS_ID = re.compile(r'^[0-9A-Za-z_-]{11}$').match

# Every shape a Kan item can carry. The first is the one that breaks.
BROKEN = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
ALREADY_OK = (
    'https://youtu.be/dQw4w9WgXcQ',
    'https://youtu.be/dQw4w9WgXcQ/',
    'https://youtu.be/dQw4w9WgXcQ?t=30',
    'https://www.youtube.com/embed/dQw4w9WgXcQ',
    'https://www.youtube.com/live/dQw4w9WgXcQ',
    # the review's case: a real id in the path AND a stray v= in the query.
    # The ungated version took the query one and got it wrong.
    'https://youtu.be/dQw4w9WgXcQ?v=WRONGIDXXXX',
)
ALSO_BROKEN = (
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s',
    'https://www.youtube.com/watch?list=PL123&v=dQw4w9WgXcQ',
)
# ROUND 2 OF REVIEW FOUND THESE. The first gate was `video_id == 'watch'`, the
# literal signature of the report. These two are broken in exactly the same
# way and neither produces 'watch': the first leaves stock with an EMPTY
# string, the second with 'Watch'. Gating on "what stock produced cannot be an
# id" covers all three by construction instead of by enumeration.
ALSO_BROKEN_ROUND2 = (
    'https://www.youtube.com/watch/?v=dQw4w9WgXcQ',
    'https://www.youtube.com/Watch?v=dQw4w9WgXcQ',
)
WANT = 'dQw4w9WgXcQ'
ALL_BROKEN = (BROKEN,) + ALSO_BROKEN + ALSO_BROKEN_ROUND2

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
    for u in ALSO_BROKEN_ROUND2:
        check('%s: STOCK fails on %s too, without saying "watch"'
              % (label, u.rsplit('/', 1)[-1]),
              not IS_ID(run_fn(before, u) or ''),
              'got %r' % run_fn(before, u))

    st = mod.ensure_patched()
    after = io.open(cp, encoding='utf-8', newline='').read()
    check('%s: it patches' % label, st == 'patched', st)
    for u in ALL_BROKEN:
        check('%s: %s resolves' % (label, u.split('.com/')[-1]),
              run_fn(after, u) == WANT, 'got %r' % run_fn(after, u))

    # THE PROPERTY THAT MAKES IT SAFE TO LEAVE IN PLACE, as an invariant over
    # every shape rather than a sample: THE ANSWER MAY ONLY CHANGE WHERE STOCK
    # PRODUCED SOMETHING THAT IS NOT A YOUTUBE ID. A YouTube id is eleven
    # characters of [0-9A-Za-z_-]; anything else is stock having failed. So no
    # url stock resolved correctly can reach the injected line -- by
    # construction, not by enumeration.
    #
    # A review broke the first version of this, which scanned the whole url
    # ungated: `youtu.be/<ID>?v=<OTHER>` has a real id in the PATH and a stray
    # v= in the query, and the fix took the wrong one -- changing an answer
    # stock had got right. That case is in ALREADY_OK so it can never come
    # back.
    differ = [u for u in ALREADY_OK + ALL_BROKEN
              if run_fn(before, u) != run_fn(after, u)]
    check('%s: the answer only ever changes where stock produced a non-id'
          % label,
          all(not IS_ID(run_fn(before, u) or '') for u in differ),
          'changed a url stock resolved correctly: %s'
          % [u for u in differ if IS_ID(run_fn(before, u) or '')])
    check('%s: every url stock already got right is UNCHANGED' % label,
          all(run_fn(before, u) == run_fn(after, u) for u in ALREADY_OK),
          'changed: %s' % [u for u in ALREADY_OK
                           if run_fn(before, u) != run_fn(after, u)])
    check('%s: ...and those were all correct to begin with' % label,
          all(run_fn(before, u) == WANT for u in ALREADY_OK))
    check('%s: a v= below the length floor is left alone, not guessed at'
          % label,
          run_fn(after, 'https://www.youtube.com/watch?v=abc12') == 'watch',
          'a stray short v= must not be mistaken for an id')

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

# --- WHAT HAPPENS WHEN IDAN PLUS FIXES IT UPSTREAM --------------------------
# The question this was designed around: if Idan Plus ships its own fix, does
# this become a problem? No -- the anchor is the stock buggy body byte for
# byte, so a changed function simply does not match, nothing is written, and
# one WARNING per boot says so. That warning is the signal to retire the file.
#
# TWO CLEVERER ANSWERS WERE TRIED AND BOTH FAILED REVIEW, and this section
# pins the ground each of them lost.
#
# Round 1 read the function text for `v=|parse_qs|query` and stood down
# quietly if it matched. A comment saying "query the path", or a variable
# called search_query, made that true -- so a still-broken version was left
# broken and reported with a status service.py deliberately does not warn
# about. Silently. NOT_FIXED below is those exact bodies, and they must now be
# PATCHED, not stood down.
#
# Round 2 EXECUTED the candidate function to decide. The slice handed to exec
# ran to the next top-level `def`, and on the real 4.0.2 tree that gap already
# holds a module-level statement -- which would then run inside OUR service on
# every boot -- and `except Exception` does not catch SystemExit. NO_EXEC
# below pins that no exec/eval survives anywhere in the patcher.
print()
print('=== what happens when Idan Plus fixes it upstream ===')

_src = io.open(PATCHER, encoding='utf-8').read()
_svc = io.open(os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai',
                            'service.py'), encoding='utf-8').read()


def _own(node):
    """Nodes belonging to this function, NOT to functions defined inside it.

    `ast.walk` descends into nested defs and lambdas, so extracting a small
    local helper out of ensure_patched would have the HELPER's returns
    attributed to ensure_patched. Round 5 reproduced that: the refusal below
    fired with a line number pointing at the wrong function, which is the kind
    of message that sends the next person to fix the wrong thing.
    """
    stack = list(ast.iter_child_nodes(node))
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.Lambda)):
            stack.extend(ast.iter_child_nodes(n))


def _warn_statuses():
    """service.py's warn tuple -- read by AST, never copied and never sliced.

    Two earlier versions of this function got it wrong in the same direction,
    which is the direction that matters: they returned a WRONG answer instead
    of raising. The first read to the end of the function and swept up
    'WARNING' from the log call underneath the tuple. The second sliced to the
    first ')' -- so a comment containing a bracket between two entries would
    truncate the set silently. An AST is immune to every reformatting of that
    tuple: one line or five, trailing comma, comments anywhere in it.
    """
    found = []
    for fn in ast.walk(ast.parse(_svc)):
        if not (isinstance(fn, ast.FunctionDef)
                and fn.name == '_maybe_fix_idanplus_youtube_id'):
            continue
        for n in _own(fn):
            if (isinstance(n, ast.Compare)
                    and isinstance(n.left, ast.Name) and n.left.id == 'st'
                    and len(n.ops) == 1 and isinstance(n.ops[0], ast.In)
                    and isinstance(n.comparators[0], ast.Tuple)):
                found.append(n.comparators[0])
    # EXACTLY ONE, or we do not know which one we read. Round 4 put a decoy
    # `if st in (...)` earlier in the same function and this returned the
    # decoy's set without a murmur -- the same wrong-answer-instead-of-raising
    # failure the AST rewrite was supposed to have ended.
    if len(found) != 1:
        raise AssertionError(
            'service.py has %d `st in (...)` tests inside '
            '_maybe_fix_idanplus_youtube_id; this can only read one' % len(found))
    bad = [e for e in found[0].elts
           if not (isinstance(e, ast.Constant) and isinstance(e.value, str))]
    if bad:
        raise AssertionError('that tuple holds something other than string '
                             'literals, so it cannot be read here')
    return set(e.value for e in found[0].elts)


def _ensure_patched_node():
    for fn in ast.walk(ast.parse(_src)):
        if isinstance(fn, ast.FunctionDef) and fn.name == 'ensure_patched':
            return fn
    raise AssertionError('no ensure_patched in the patcher')


def _returned_statuses():
    """Every string ensure_patched can actually return, by AST.

    THE SHAPE IS PINNED RATHER THAN SEARCHED, which took three tries to get
    right. Reading `ast.Return.value` and requiring a bare constant silently
    missed `return 'repatched' if repatch else 'patched'`. Walking the whole
    return expression for string constants fixed that and bought two new ways
    to be wrong: `result = 'write_failed'` then `return result` collects
    NOTHING, and `return '{0}'.format('x_failed')` collects the format
    template as if it were a status. Both are undercounts or overcounts in the
    one function whose entire job is catching them.

    So every return in ensure_patched must BE a status literal, or a choice
    between two of them, and anything else is refused by name and line number
    instead of being quietly mis-read. If a future version needs a computed
    status, this function is what has to change -- deliberately, not by
    accident.
    """
    out = set()
    for n in _own(_ensure_patched_node()):
        if not isinstance(n, ast.Return):
            continue
        vals = ([n.value.body, n.value.orelse]
                if isinstance(n.value, ast.IfExp) else [n.value])
        for v in vals:
            if not (isinstance(v, ast.Constant) and isinstance(v.value, str)):
                raise AssertionError(
                    'ensure_patched line %d does not return a plain status '
                    'literal, so the status set cannot be read from source'
                    % n.lineno)
            out.add(v.value)
    return out


# Both readers refuse rather than guess, and a refusal has to arrive as a
# FAIL line like everything else here -- not as a traceback that takes the
# rest of the run down with it.
_read_err = []
try:
    ALL_ST = _returned_statuses()
except AssertionError as e:
    ALL_ST, _ = set(), _read_err.append('patcher: %s' % e)
try:
    BAD = tuple(sorted(_warn_statuses()))
except AssertionError as e:
    BAD, _ = (), _read_err.append('service.py: %s' % e)
check('both status lists could be read from source at all',
      not _read_err, ' / '.join(_read_err))

# THE RULE, STATED ONCE, RATHER THAN A LIST COPIED TWICE. Review round 3 found
# the previous version of this check asserted only that a couple of members
# were present and a couple absent -- so quietly dropping 'write_failed' from
# service.py's tuple, a real regression that would stop write failures being
# logged, passed. An equality is the only assertion that catches that, and the
# right-hand side has to be DERIVED or it is just the copied list again.
#
# So: warn about exactly the statuses that mean we failed. Every '_failed'
# name, plus 'unmatched' -- the shape we do not recognise, which is the signal
# to retire this patcher and therefore the one thing we most want said out
# loud. Nothing else: 'no_file' and 'no_idanplus' are the ordinary state of
# every device that simply does not have Idan Plus, and 'unchanged',
# 'patched' and 'repatched' are success.
WANT_BAD = tuple(sorted({s for s in ALL_ST if s.endswith('_failed')}
                        | {'unmatched'}))
check('service.py warns about exactly the failure statuses, no more, no less',
      BAD == WANT_BAD,
      'service.py says %s, the rule says %s' % (BAD, WANT_BAD))
check('...and both sides were read from source, not written down here',
      len(ALL_ST) > 5 and 'patched' in ALL_ST and 'no_file' in ALL_ST,
      'ensure_patched returned nothing recognisable: %s' % (sorted(ALL_ST),))
# Only the part of the docstring AFTER the word "Returns" -- so ordinary
# prose elsewhere in it can quote whatever it likes without breaking this.
DOC_ST = set(re.findall(
    r"'(\w+)'",
    (ast.get_docstring(_ensure_patched_node()) or '').split('Returns', 1)[-1]))
check('the docstring lists exactly the statuses ensure_patched returns',
      DOC_ST == ALL_ST,
      'undocumented %s / documented but never returned %s'
      % (sorted(ALL_ST - DOC_ST), sorted(DOC_ST - ALL_ST)))
check('no status service.py warns about is a silent stand-down',
      'already_fixed' not in ALL_ST and 'no_function' not in ALL_ST,
      'those two statuses no longer exist; if they are back, so is the bug')

# THE PATCHER MUST NOT RUN ANYBODY ELSE'S CODE TO MAKE ITS DECISION.
#
# Three spellings, because a comment on the first version claimed to cover a
# shape it did not and round 4 executed the counter-example: a bare name
# (`exec(...)`, round 2's actual shape), an attribute (`mod.eval(...)`), and
# the STRING 'exec'/'eval' anywhere -- which is what `getattr(builtins,
# 'exec')` and `builtins.__dict__['exec']` reduce to, and what the first two
# rules are blind to.
#
# `compile(src, path, 'exec')` uses that word legitimately and is the one
# exemption: the mode argument of a call to compile(), positional or keyword.
# Round 5 found the keyword spelling was NOT exempt, so an ordinary refactor
# to `compile(src, path, mode='exec')` would have failed this check -- a guard
# that fires on legitimate code is a guard somebody deletes. If the mode is
# ever passed as a VARIABLE the literal sits somewhere this cannot follow and
# it will fire; the message below says what to do about it.
#
# This is a regression guard, not a security boundary. Someone determined to
# hide an exec can still build the name at runtime. The point is that nobody
# reintroduces round 2's mechanism by accident.
_tree = ast.parse(_src)
_compiles = [c for c in ast.walk(_tree)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
             and c.func.id == 'compile']
_exempt = ({id(c.args[2]) for c in _compiles if len(c.args) > 2}
           | {id(k.value) for c in _compiles for k in c.keywords
              if k.arg == 'mode'})
_bad_names = sorted({n.id for n in ast.walk(_tree)
                     if isinstance(n, ast.Name)} & {'exec', 'eval'})
_bad_attrs = sorted({n.attr for n in ast.walk(_tree)
                     if isinstance(n, ast.Attribute)} & {'exec', 'eval'})
_bad_strs = sorted({n.value for n in ast.walk(_tree)
                    if isinstance(n, ast.Constant) and n.value in ('exec', 'eval')
                    and id(n) not in _exempt})
check('NO_EXEC: the patcher never execs or evals, by any spelling',
      not (_bad_names or _bad_attrs or _bad_strs),
      'name %s / attribute %s / string %s -- if a string here is the mode '
      'argument of a legitimate compile() call, exempt it above rather than '
      'deleting the check'
      % (_bad_names, _bad_attrs, _bad_strs))

# A GENUINE UPSTREAM FIX: unrecognised shape, file untouched, and REPORTED.
# Noisy is the intended outcome. We cannot tell a fix from a refactor from a
# different breakage without running their code, and round 2 settled that we
# will not run their code.
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
    'an unrecognisable rewrite that fixes nothing':
        "youtubePlugin = 'x'\n\ndef GetYouTube(url):\n"
        "\tvideo_id = extract_id(url)\n"
        "\treturn '{0}/play/?video_id={1}'.format(youtubePlugin, video_id)\n",
    'GetYouTube deleted outright':
        "youtubePlugin = 'x'\n\ndef Something():\n\tpass\n",
}
for label, body in UPSTREAM.items():
    home, cp = fresh(body=body)
    before = io.open(cp, encoding='utf-8', newline='').read()
    mod = load(home)
    st = mod.ensure_patched()
    after = io.open(cp, encoding='utf-8', newline='').read()
    check('%s -> refused, not guessed at' % label, st == 'unmatched', st)
    check('%s -> the file is untouched' % label, after == before)
    check('%s -> and it is REPORTED, never silent' % label, st in BAD)

# AND THE OTHER DIRECTION, which is the one round 1 got wrong: a version that
# does NOT fix the bug must not make us stand down. These keep the stock shape
# and merely contain the words the old text-search was looking for.
_RET = "\treturn '{0}/play/?video_id={1}'.format(youtubePlugin, video_id)\n"
_STOCK_FN = ("def GetYouTube(url):\n\tif url.endswith('/'):\n\t\turl = url[:-1]\n"
             "\tvideo_id = url[url.rfind('/')+1:]\n\tif '?' in video_id:\n"
             "\t\tvideo_id = video_id[:video_id.find('?')]\n" + _RET)
_HEAD = "import re\nyoutubePlugin = 'plugin://plugin.video.youtube'\n\n"
NOT_FIXED = {
    'a comment that merely says "query"': '\t# query the path\n',
    'a variable called search_query': '\tsearch_query = 1\n',
    'a variable whose name ends in v': '\tconv = 1\n',
}
for label, extra in NOT_FIXED.items():
    home, cp = fresh(body=_HEAD + _STOCK_FN.replace(
        'def GetYouTube(url):\n', 'def GetYouTube(url):\n' + extra))
    mod = load(home)
    st = mod.ensure_patched()
    after = io.open(cp, encoding='utf-8', newline='').read()
    check('STILL BROKEN: %s -> we patch it anyway' % label,
          st == 'patched', st)
    check('STILL BROKEN: %s -> and the url resolves' % label,
          run_fn(after, BROKEN) == WANT, 'got %r' % run_fn(after, BROKEN))

# --- absent installs --------------------------------------------------------
print()
print('=== absent installs ===')
home = tempfile.mkdtemp(prefix='noidan-')
_DIRS.append(home)
check('no Idan Plus at all is no_file, not a traceback',
      load(home).ensure_patched() == 'no_file')
check('...and no_file is NOT warned about -- most devices do not have it',
      'no_file' not in BAD and 'no_idanplus' not in BAD)

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
