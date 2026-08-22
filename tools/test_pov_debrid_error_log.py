#!/usr/bin/env python3
"""A debrid that refuses the account must say so in the log.

THE REPORT: AllDebrid stopped working, and the follow-up log said nothing
about why -- no HTTP error, no traceback, just sources that would not play.

THE REASON THE LOG WAS EMPTY: AllDebrid answers 200 OK and puts the refusal in
the body ({"status":"error","error":{"code":"AUTH_BAD_APIKEY",...}}). POV's
_request logs only `if not response.ok`, so a 200 logs nothing; the envelope
travels up to a caller expecting a list, and the caller says "no sources".
Four very different situations -- not connected, key rejected, banned, not
premium -- all arrive at the user as the same sentence, and the log cannot
separate them either.

TorBox is the same shape with a different envelope, and its unwrap line makes
it worse: it tests `'success' in response`, which is TRUE when success is
false, so an error reply returns response['data'] (null) and the error string
is discarded inside the function that received it.

WHAT THIS PINS, and the second one is the point:

  1. the patch applies to real POV, exactly once per file, idempotently, and
     survives CRLF / an older marker / a missing file;
  2. EXECUTION. Stock is made to demonstrate the bug first -- a real refusal
     envelope in, and nothing in the log -- before the patched build is
     allowed to claim it reports it. And the patched version must return the
     SAME value stock did: this is a log line, not a behaviour change, and a
     test that did not check the return could not tell the difference.

Run: python3 tools/test_pov_debrid_error_log.py
"""
import atexit
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
PATCHER = os.path.join(LIB, 'pov_debrid_error_log_patcher.py')
STOCK = os.environ.get('POV_STOCK') or (
    '/tmp/claude-0/-home-user-Kodi-POV-IL/'
    '70968383-5f01-52a3-afe7-ced1aba28071/scratchpad/pov6813/plugin.video.pov')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


# --- fixtures: real POV, byte for byte -------------------------------------
# The _request bodies below are verbatim from POV 6.08.13. Section 0 asserts
# that, against a stock tree when one is present. A hand-written approximation
# would let the anchor drift and the test would still pass.
AD_REQUEST = (
    "\tdef _request(self, method, path, params=None, data=None):\n"
    "\t\turl = base_url + path\n"
    "\t\ttry: response = session.request(method, url, params=params, data=data, timeout=timeout)\n"
    "\t\texcept session.custom_errors: return kodi_utils.notification('%s timeout' % __name__)\n"
    '\t\tif not response.ok: kodi_utils.logger(__name__, f"{response.reason}\\n{response.url}")\n'
    "\t\tresponse = response.json() if 'json' in response.headers.get('Content-Type', '') else response\n"
    "\t\tif 'data' in response and response.get('status') == 'success': response = response['data']\n"
    "\t\treturn response\n"
)
TB_REQUEST = (
    "\tdef _request(self, method, path, params=None, json=None, data=None):\n"
    "\t\turl = base_url + path\n"
    "\t\ttry: response = session.request(method, url, params=params, json=json, data=data, timeout=self.timeout)\n"
    "\t\texcept session.custom_errors: return kodi_utils.notification('%s timeout' % __name__)\n"
    '\t\tif not response.ok: kodi_utils.logger(__name__, f"{response.reason}\\n{response.url}")\n'
    "\t\tresponse = response.json() if 'json' in response.headers.get('Content-Type', '') else response\n"
    "\t\tif not self._is_control(path) and 'data' in response and 'success' in response: response = response['data']\n"
    "\t\treturn response\n"
)
TB_IS_CONTROL = (
    "\tdef _is_control(self, path):\n"
    "\t\treturn any(i in path for i in ('/control', '/edit'))\n"
)

FIXTURES = {
    'resources/lib/debrids/alldebrid_api.py':
        'class AllDebridAPI(object):\n' + AD_REQUEST,
    'resources/lib/debrids/torbox_api.py':
        'class TorBoxAPI(object):\n' + TB_REQUEST + '\n' + TB_IS_CONTROL,
}

_SCRATCH = []


@atexit.register
def _clean():
    for d in _SCRATCH:
        shutil.rmtree(d, ignore_errors=True)


def fresh_pov(fixtures=None):
    """A POV tree the patcher can work on: the real one where it exists, the
    byte-slice fixtures where it does not."""
    home = tempfile.mkdtemp(prefix='povdbgerr-')
    _SCRATCH.append(home)
    root = os.path.join(home, 'addons', 'plugin.video.pov')
    if fixtures is None and os.path.isdir(STOCK):
        shutil.copytree(STOCK, root)
        return home, root
    for rel, body in (fixtures or FIXTURES).items():
        p = os.path.join(root, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with io.open(p, 'w', encoding='utf-8', newline='') as f:
            f.write(body)
    return home, root


LOG = []


def load(home):
    """The patcher, pointed at `home` as if it were special://home."""
    for n in list(sys.modules):
        if n.split('.')[0] in ('resources', 'xbmcvfs'):
            sys.modules.pop(n, None)
    vfs = types.ModuleType('xbmcvfs')
    vfs.translatePath = lambda p: p.replace('special://home/', home + os.sep)
    sys.modules['xbmcvfs'] = vfs
    pkg = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    lib.__path__ = [LIB]
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = lib
    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.log = lambda *a, **k: LOG.append(a[0] if a else '')
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku
    spec = importlib.util.spec_from_file_location('pdel_t', PATCHER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _read(root, rel):
    with io.open(os.path.join(root, *rel.split('/')),
                 encoding='utf-8', newline='') as f:
        return f.read()


# --- 0. the fixtures really are POV ----------------------------------------
print('fixture: %s' % ('real stock POV' if os.path.isdir(STOCK)
                       else 'byte-slices of real POV (no stock tree here)'))
if os.path.isdir(STOCK):
    for rel, slice_ in (('resources/lib/debrids/alldebrid_api.py', AD_REQUEST),
                        ('resources/lib/debrids/torbox_api.py', TB_REQUEST),
                        ('resources/lib/debrids/torbox_api.py',
                         TB_IS_CONTROL)):
        real = _read(STOCK, rel)
        check('FIXTURE slice of %s is verbatim POV' % rel.split('/')[-1],
              real.count(slice_) == 1,
              'found %d times -- the anchor has drifted' % real.count(slice_))
else:
    print('---- fixtures NOT checked against a real tree here')


# --- 1. it applies ----------------------------------------------------------
print()
print('=== the patch applies to real POV ===')
home, root = fresh_pov()
mod = load(home)
status = mod.ensure_patched()
print('   status: %s' % status)
check('both sites patch on a stock tree',
      status == 'alldebrid=patched, torbox=patched', status)

for rel in ('resources/lib/debrids/alldebrid_api.py',
            'resources/lib/debrids/torbox_api.py'):
    src = _read(root, rel)
    check('%s carries the marker exactly once' % rel.split('/')[-1],
          src.count(mod.MARKER) == 1, 'found %d' % src.count(mod.MARKER))
    try:
        compile(src, rel, 'exec')
    except SyntaxError as e:
        check('%s still compiles' % rel.split('/')[-1], False, str(e))
    else:
        check('%s still compiles' % rel.split('/')[-1], True)

check('running it again changes nothing',
      mod.ensure_patched() == 'alldebrid=unchanged, torbox=unchanged')


# --- 2. IT ACTUALLY REPORTS THE REFUSAL ------------------------------------
# The whole point. Stock has to fail first: a real AllDebrid refusal envelope
# goes in, and stock writes nothing about it. Only then does the patched run
# get to claim it does.
print()
print('=== the refusal reaches the log, and nothing else changes ===')

# what AllDebrid actually answers, observed against the live API with no
# credentials: HTTP 200, and the reason in the body.
AD_REFUSAL = {'status': 'error',
              'error': {'code': 'AUTH_BAD_APIKEY',
                        'message': 'The auth apikey is invalid'}}
AD_OK = {'status': 'success', 'data': {'user': {'isPremium': True}}}
TB_REFUSAL = {'success': False, 'error': 'AUTH_ERROR',
              'detail': 'Invalid or expired token', 'data': None}
TB_OK = {'success': True, 'detail': 'ok', 'data': {'id': 7}}


class _Resp(object):
    """A requests-like reply that is 200 OK and says no in the body."""

    ok = True
    reason = 'OK'
    url = 'https://api.example/v4/user'
    headers = {'Content-Type': 'application/json'}

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def run_request(source, cls_name, payload, path='v4/user'):
    """exec the module text and call _request with a canned reply.

    Returns (return value, [log lines]). Everything _request touches is a
    module global here, so the fakes go straight into the namespace.
    """
    logged = []

    class _Session(object):
        custom_errors = (RuntimeError,)

        def request(self, *a, **k):
            return _Resp(payload)

    ku = types.SimpleNamespace(
        logger=lambda name, msg: logged.append('%s: %s' % (name, msg)),
        notification=lambda msg: ('notification', msg))
    ns = {'base_url': 'https://api.example/', 'timeout': 10.0,
          'session': _Session(), 'kodi_utils': ku, '__name__': cls_name}
    exec(compile(source, cls_name + '.py', 'exec'), ns)
    obj = ns[cls_name]()
    obj.timeout = 10.0
    return obj._request('get', path), logged


STOCK_AD = FIXTURES['resources/lib/debrids/alldebrid_api.py']
STOCK_TB = FIXTURES['resources/lib/debrids/torbox_api.py']

# -- stock: the bug
val, logged = run_request(STOCK_AD, 'AllDebridAPI', AD_REFUSAL)
check('STOCK AllDebrid logs NOTHING about a refusal', not logged,
      'it logged %s -- then this patch has no reason to exist' % logged)
check('...and hands the raw envelope on as if it were data',
      val == AD_REFUSAL)
STOCK_AD_RETURN = val

val, logged = run_request(STOCK_TB, 'TorBoxAPI', TB_REFUSAL)
check('STOCK TorBox logs NOTHING about a refusal', not logged, str(logged))
check('...and returns the null payload, error string discarded',
      val is None, repr(val))
STOCK_TB_RETURN = val

# -- patched: the fix
home2, root2 = fresh_pov(FIXTURES)
mod2 = load(home2)
st2 = mod2.ensure_patched()
check('the fixtures patch too', st2 == 'alldebrid=patched, torbox=patched',
      st2)

PATCHED_AD = _read(root2, 'resources/lib/debrids/alldebrid_api.py')
PATCHED_TB = _read(root2, 'resources/lib/debrids/torbox_api.py')

val, logged = run_request(PATCHED_AD, 'AllDebridAPI', AD_REFUSAL)
joined = ' | '.join(logged)
check('PATCHED AllDebrid logs the refusal', len(logged) == 1, joined)
check('...naming the code AllDebrid gave', 'AUTH_BAD_APIKEY' in joined,
      joined)
check('...and its message', 'The auth apikey is invalid' in joined, joined)
check('...and which endpoint refused', 'v4/user' in joined, joined)
check('...tagged so a user log can be grepped for it', 'KODI_POV_IL' in joined,
      joined)
# THE WHOLE LINE, NOT FOUR SUBSTRINGS. Checking only that each piece appears
# somewhere passed a mutant with the code and message exchanged -- so it
# proved the pieces were present and nothing about the sentence they formed.
check('...and the line reads as one sentence, in order',
      joined.endswith(
          "KODI_POV_IL refused v4/user -- "
          "{'code': 'AUTH_BAD_APIKEY', 'message': 'The auth apikey is "
          "invalid'}"), joined)
check('AND THE RETURN IS UNCHANGED -- this is a log line, not a behaviour '
      'change', val == STOCK_AD_RETURN, '%r vs %r' % (val, STOCK_AD_RETURN))

val, logged = run_request(PATCHED_TB, 'TorBoxAPI', TB_REFUSAL)
joined = ' | '.join(logged)
check('PATCHED TorBox logs the refusal', len(logged) == 1, joined)
check('...naming its error and detail, in order',
      joined.endswith("KODI_POV_IL refused v4/user -- "
                      "('AUTH_ERROR', 'Invalid or expired token')"), joined)
# STOCK_TB_RETURN is None, so this comparison alone is weak -- it would also
# hold for a patch that made TorBox return None whatever came in. The
# successful-reply pair below carries the non-None half of the claim.
check('AND ITS RETURN IS UNCHANGED TOO', val == STOCK_TB_RETURN,
      '%r vs %r' % (val, STOCK_TB_RETURN))

# AN `error` THAT IS NOT A DICT, which is the case a diagnostic is worth most
# in: an answer whose shape nobody expected. The first version read
# `(response.get('error') or {}).get('code')`, and `or {}` only rescues a
# FALSY value -- a string, a list or a number sailed through and .get raised
# AttributeError into the guard, so NOTHING was logged at all.
for _label, _err in (('a string', 'ACCOUNT_LOCKED'),
                     ('a list', ['ACCOUNT_LOCKED', 'try later']),
                     ('a number', 42),
                     ('null', None)):
    payload = {'status': 'error', 'error': _err}
    pv, plog = run_request(PATCHED_AD, 'AllDebridAPI', payload)
    sv, _sl = run_request(STOCK_AD, 'AllDebridAPI', payload)
    check('an error that is %s is still logged' % _label, len(plog) == 1,
          'logged %s -- the shape we did not expect is the one worth seeing'
          % plog)
    # str, not repr: the injected line formats with %s, so a bare string
    # arrives without quotes around it.
    check('...naming it', plog and str(_err) in plog[0], str(plog))
    check('...and the return is still stock', pv == sv, '%r vs %r' % (pv, sv))

# -- and the case that must stay silent: a reply that is fine.
# A log line on every successful request would be noise in every log forever,
# and would drown the one line that matters.
for label, src, cls, payload, stock_src in (
        ('AllDebrid', PATCHED_AD, 'AllDebridAPI', AD_OK, STOCK_AD),
        ('TorBox', PATCHED_TB, 'TorBoxAPI', TB_OK, STOCK_TB)):
    pval, plog = run_request(src, cls, payload)
    sval, slog = run_request(stock_src, cls, payload)
    check('a successful %s reply logs nothing' % label, not plog, str(plog))
    check('...and returns exactly what stock returned', pval == sval,
          '%r vs %r' % (pval, sval))

# a non-JSON reply: `response` is still the requests object, which has no
# .get at all. isinstance(dict) is what keeps that from raising.
class _RawResp(_Resp):
    headers = {'Content-Type': 'text/html'}


def run_raw(source, cls_name):
    class _Session(object):
        custom_errors = (RuntimeError,)

        def request(self, *a, **k):
            return _RawResp(None)
    logged = []
    ku = types.SimpleNamespace(
        logger=lambda name, msg: logged.append(msg),
        notification=lambda msg: ('notification', msg))
    ns = {'base_url': 'https://api.example/', 'timeout': 10.0,
          'session': _Session(), 'kodi_utils': ku, '__name__': cls_name}
    exec(compile(source, cls_name + '.py', 'exec'), ns)
    obj = ns[cls_name]()
    obj.timeout = 10.0
    try:
        return obj._request('get', 'v4/user'), logged, None
    except Exception as e:
        return None, logged, e


for label, src, cls in (('AllDebrid', PATCHED_AD, 'AllDebridAPI'),
                        ('TorBox', PATCHED_TB, 'TorBoxAPI')):
    _v, _l, err = run_raw(src, cls)
    _sv, _sl, serr = run_raw(
        STOCK_AD if cls == 'AllDebridAPI' else STOCK_TB, cls)
    check('a non-JSON %s reply behaves exactly as stock does' % label,
          type(err) is type(serr) and not _l,
          'patched raised %r, stock raised %r, log %s' % (err, serr, _l))


# --- 3. the awkward trees ---------------------------------------------------
print()
print('=== the trees that are not the happy one ===')

# CRLF
crlf = {rel: body.replace('\n', '\r\n') for rel, body in FIXTURES.items()}
home3, root3 = fresh_pov(crlf)
mod3 = load(home3)
st3 = mod3.ensure_patched()
check('a CRLF tree still patches', st3 == 'alldebrid=patched, torbox=patched',
      st3)
src3 = _read(root3, 'resources/lib/debrids/alldebrid_api.py')
check('...without introducing a bare LF', '\n' not in src3.replace('\r\n', ''))

# AN OLDER INJECTION, aged from a REAL one rather than hand-written. The
# revert matches the whole block, so only a block this module actually wrote
# can be recognised -- which is the point, and a hand-drawn approximation
# would test the opposite of what ships.
home4, root4 = fresh_pov(FIXTURES)
p4 = os.path.join(root4, 'resources', 'lib', 'debrids', 'alldebrid_api.py')
mod4a = load(home4)
mod4a.ensure_patched()
aged = _read(root4, 'resources/lib/debrids/alldebrid_api.py').replace(
    mod4a.MARKER, '# AI_SUBS_POV_DEBRID_ERRLOG_v0')
with io.open(p4, 'w', encoding='utf-8', newline='') as f:
    f.write(aged)
mod4 = load(home4)
st4 = mod4.ensure_patched()
check('an older injection is removed and replaced',
      'alldebrid=repatched' in st4, st4)
src4 = _read(root4, 'resources/lib/debrids/alldebrid_api.py')
check('...leaving exactly one marker', src4.count('ERRLOG_v') == 1,
      'found %d' % src4.count('ERRLOG_v'))
check('...and the file is what a clean patch would have produced',
      src4 == _read(root2, 'resources/lib/debrids/alldebrid_api.py'),
      'a repatch has to land on the same bytes as a first patch')

# A BLOCK NOBODY HERE WROTE IS NOT REMOVED, IT IS REFUSED. The sibling
# patcher's indent walk deletes "the marked line and everything deeper", and a
# review built a file with an unrelated deeper-indented line straight after an
# old marker and watched it be swallowed, reported as success. Deleting
# somebody else's line out of somebody else's add-on is worse than declining
# to upgrade.
home4b, root4b = fresh_pov(FIXTURES)
p4b = os.path.join(root4b, 'resources', 'lib', 'debrids', 'alldebrid_api.py')
tampered = _read(root4b, 'resources/lib/debrids/alldebrid_api.py').replace(
    "\t\tif 'data' in response",
    "\t\tif False:  # AI_SUBS_POV_DEBRID_ERRLOG_v0\n"
    "\t\t\tsomebody_elses_line = 1\n"
    "\t\tif 'data' in response", 1)
with io.open(p4b, 'w', encoding='utf-8', newline='') as f:
    f.write(tampered)
mod4b = load(home4b)
st4b = mod4b.ensure_patched()
check('a block this module did not write is refused, not swept away',
      'alldebrid=revert_failed' in st4b, st4b)
check('...and the intruder is still there',
      'somebody_elses_line' in _read(
          root4b, 'resources/lib/debrids/alldebrid_api.py'),
      'an unrelated line was deleted out of POV')

# a file POV refactored away
home5, root5 = fresh_pov(FIXTURES)
os.remove(os.path.join(root5, 'resources', 'lib', 'debrids',
                       'alldebrid_api.py'))
mod5 = load(home5)
st5 = mod5.ensure_patched()
check('a missing file is reported, and the other site still patches',
      st5 == 'alldebrid=no_file, torbox=patched', st5)

# a shape POV changed: leave the file completely alone
home6, root6 = fresh_pov({
    'resources/lib/debrids/alldebrid_api.py':
        'class AllDebridAPI(object):\n\tdef _request(self, m, p):\n'
        '\t\treturn None\n',
    'resources/lib/debrids/torbox_api.py': STOCK_TB,
})
mod6 = load(home6)
st6 = mod6.ensure_patched()
check('a refactored shape is left untouched, not guessed at',
      st6 == 'alldebrid=unmatched, torbox=patched', st6)
check('...and the file is byte-identical to what was there',
      _read(root6, 'resources/lib/debrids/alldebrid_api.py')
      == 'class AllDebridAPI(object):\n\tdef _request(self, m, p):\n'
         '\t\treturn None\n')

# and a DUPLICATED shape: two copies means we do not know which one matters
home7, root7 = fresh_pov({
    'resources/lib/debrids/alldebrid_api.py':
        STOCK_AD + '\n' + AD_REQUEST.replace('_request', '_request2'),
    'resources/lib/debrids/torbox_api.py': STOCK_TB,
})
_dup = _read(root7, 'resources/lib/debrids/alldebrid_api.py')
mod7 = load(home7)
st7 = mod7.ensure_patched()
check('a duplicated shape is refused rather than patched at the first copy',
      st7 == 'alldebrid=unmatched, torbox=patched', st7)
check('...and that file is untouched too',
      _read(root7, 'resources/lib/debrids/alldebrid_api.py') == _dup)

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
