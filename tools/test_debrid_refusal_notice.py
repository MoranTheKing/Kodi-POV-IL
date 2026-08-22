#!/usr/bin/env python3
"""A debrid service that refuses the account must say so, on the screen.

THE REPORT: every AllDebrid source failed to resolve, and the log gave no
reason. Three layers swallowed it in a row.

  1. POV's alldebrid_api._request logs only `if not response.ok` -- and
     AllDebrid answers HTTP 200 with the error INSIDE the body, which is how
     its API has always worked.
  2. POV's days_remaining() wraps the whole lookup in a bare `except:` and
     returns None.
  3. and this file read None as "no number, so show nothing".

Verified against the live API, with no credentials and without asking the
reporter for another log: v4/magnet/upload answers 200 with
{"status":"error","error":{"code":...,"message":...}} and v4/magnet/instant
answers 404 -- so the endpoints are alive, the auth style is accepted, and
AllDebrid is refusing THIS account while naming which refusal in a field
nobody read.

WHAT THIS PINS. The notice is narrow on purpose: only an unambiguous error
envelope carrying one of the account-level codes gets a toast. A timeout, a
dropped connection, a Response object or an unrecognised shape says nothing --
because a toast that cries wolf on a flaky night costs more trust than the one
it saves.

Run: python3 tools/test_debrid_refusal_notice.py
"""
import ast
import importlib.util
import io
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
ADDON = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai')
LIB = os.path.join(ADDON, 'resources', 'lib')

FAIL = []


def check(label, cond, detail=''):
    print('%-4s %s%s' % ('ok' if cond else 'FAIL', label,
                         ('  -- ' + detail) if detail and not cond else ''))
    if not cond:
        FAIL.append(label)


def load():
    for n in list(sys.modules):
        if n.split('.')[0] in ('resources', 'xbmc', 'xbmcgui', 'xbmcaddon',
                               'xbmcvfs'):
            sys.modules.pop(n, None)
    for name in ('xbmc', 'xbmcgui', 'xbmcaddon', 'xbmcvfs'):
        sys.modules[name] = types.ModuleType(name)
    pkg = types.ModuleType('resources')
    lib = types.ModuleType('resources.lib')
    lib.__path__ = [LIB]
    sys.modules['resources'] = pkg
    sys.modules['resources.lib'] = lib
    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.log = lambda *a, **k: None
    ku.notify = lambda *a, **k: None
    sys.modules['resources.lib.kodi_utils'] = ku
    lib.kodi_utils = ku
    spec = importlib.util.spec_from_file_location(
        'dsn', os.path.join(LIB, 'debrid_status_notifier.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


mod = load()
AD = [s for s in mod.SERVICES if s['module'] == 'alldebrid_api']
check('AllDebrid is one of the services this watches', len(AD) == 1)
AD = AD[0] if AD else {'name': 'AllDebrid', 'module': 'alldebrid_api',
                       'class': 'AllDebridAPI'}


# --- what _refusal accepts, and what it refuses to speak about --------------
print('=== only an unambiguous account refusal is reported ===')


def refusal_from(reply, service=None):
    """Run the real _refusal against a stubbed provider returning `reply`."""
    # STUB THE SERVICE BEING ASKED ABOUT, not always AllDebrid. _refusal
    # imports 'debrids.' + service['module'], so pinning the stub to AllDebrid
    # made every Premiumize case fail its import and answer None -- which is
    # the same answer a correct refusal-free reply gives, so the test would
    # have "passed" for the wrong reason had it expected None.
    svc = service or AD
    mod._pov_lib_path = lambda: LIB          # any real dir; the import is stubbed
    api = types.ModuleType('debrids.' + svc['module'])

    class _Api(object):
        def account_info(self):
            if isinstance(reply, Exception):
                raise reply
            return reply
    setattr(api, svc['class'], _Api)
    sys.modules['debrids'] = types.ModuleType('debrids')
    sys.modules['debrids.' + svc['module']] = api
    try:
        return mod._refusal(svc)
    finally:
        sys.modules.pop('debrids.' + svc['module'], None)
        sys.modules.pop('debrids', None)


REAL = {'status': 'error',
        'error': {'code': 'AUTH_BAD_APIKEY',
                  'message': 'The auth apikey is invalid'}}
check('the live envelope is read', refusal_from(REAL)
      == ('AUTH_BAD_APIKEY', 'The auth apikey is invalid'))
check('a healthy account says nothing',
      refusal_from({'user': {'premiumUntil': 99999999}}) is None)
for label, reply in (
        ('a timeout', TimeoutError('timed out')),
        ('an exception of any kind', RuntimeError('boom')),
        ('None', None),
        ('a Response-ish object', object()),
        ('a list', [1, 2]),
        ('an envelope with no error block', {'status': 'error'}),
        ('an error block that is not a dict',
         {'status': 'error', 'error': 'nope'}),
        ('an error block with no code',
         {'status': 'error', 'error': {'message': 'x'}}),
        ('an empty code',
         {'status': 'error', 'error': {'code': '   ', 'message': 'x'}})):
    check('%s is not a refusal' % label, refusal_from(reply) is None)


# PREMIUMIZE HAS NO CODES AT ALL, and reading only AllDebrid's shape meant a
# refused Premiumize account said nothing -- on screen or in the log. Its
# envelope is {"status":"error","message":"..."} at HTTP 200, with no error
# object. Reported as: "the numbers go up while it searches and then it says
# no results, and only on Premiumize".
print()
print('=== a service that refuses without a code ===')
PM = [x for x in mod.SERVICES if x['prefix'] == 'pm'][0]
AD_SVC = [x for x in mod.SERVICES if x['prefix'] == 'ad'][0]
check('Premiumize is marked as having no codes', PM.get('codeless') is True)
check('...and AllDebrid is not', not AD_SVC.get('codeless'),
      'widening the rule for a service that DOES send codes would put an '
      'arbitrary string on screen the first time it answered oddly')
check('a bare message from Premiumize is a refusal',
      refusal_from({'status': 'error', 'message': 'Not logged in.'}, PM)
      == ('', 'Not logged in.'))
check('...and the same reply from AllDebrid is still nothing',
      refusal_from({'status': 'error', 'message': 'Not logged in.'}) is None)
check('a healthy Premiumize reply still says nothing',
      refusal_from({'status': 'success', 'customer_id': 1}, PM) is None)


# --- the queue: a refusal is shown, an unknown code is not ------------------
print()
print('=== what actually reaches the screen ===')
codes = set(mod._REFUSAL_TEXT)
check('the account-level codes are the ones AllDebrid documents',
      {'AUTH_BAD_APIKEY', 'AUTH_BLOCKED', 'AUTH_USER_BANNED',
       'MUST_BE_PREMIUM'} <= codes,
      'got %s' % sorted(codes))
check('every one of them has Hebrew a user can act on',
      all(v.strip() and any('֐' <= ch <= 'ת' for ch in v)
          for v in mod._REFUSAL_TEXT.values()))
msg = mod._refusal_message(AD, 'AUTH_BAD_APIKEY', 'The auth apikey is invalid')
check('the toast names the service and the reason, in Hebrew',
      AD['name'] in msg and mod._REFUSAL_TEXT['AUTH_BAD_APIKEY'] in msg,
      'got %r' % msg)
check('...and not the raw English the API sent',
      'apikey' not in msg, 'got %r' % msg)
# AN UNRECOGNISED CODE. This used to assert the provider's English reached the
# screen. It no longer does, and that is the fix, not a regression: this is a
# Hebrew build, the only route here is an account-shaped code with no wording
# yet, and "the account was refused (AUTH_SOMETHING_NEW)" is readable by
# somebody who does not read English where the provider's sentence is not. The
# English still goes to the log.
unknown = mod._refusal_message(AD, 'AUTH_SOMETHING_NEW', 'a new reason')
check('an unrecognised account code says so in Hebrew',
      mod._UNKNOWN_CODE_TEXT in unknown)
check('...and names the code, so a log can be matched to a screenshot',
      'AUTH_SOMETHING_NEW' in unknown, unknown)
check('...and does not put the raw English on a Hebrew screen',
      'a new reason' not in unknown, unknown)

# AND IT MUST REACH THE QUEUE AT ALL. The gate used to require the code be one
# of the four this build has Hebrew for, so a NEW AllDebrid AUTH_ code produced
# no toast whatsoever -- the same silence this whole file exists to end.
check('an account-shaped code this build does not know still counts',
      mod._unknown_account_code('AUTH_SOMETHING_NEW') is True)
# A CODE IS UNDERSCORE-SEPARATED TOKENS, so it gets the same subject-plus-
# predicate shape the prose rule uses -- a flat "contains one of five words"
# list had the same two-sided failure: MAINTENANCE_MODE_BANNED_IPS and
# SUBSCRIPTION_TIER_METADATA_REFRESH both matched (neither is a refusal) while
# REFRESH_TOKEN_EXPIRED and USER_ACCOUNT_REMOVED matched nothing (both are).
for _c in ('MUST_BE_PREMIUM_TOO', 'USER_BANNED_X', 'SUBSCRIPTION_BLOCKED',
           'REFRESH_TOKEN_EXPIRED', 'USER_ACCOUNT_REMOVED',
           'APIKEY_REVOKED', 'SESSION_INVALID'):
    check('...%s too' % _c, mod._unknown_account_code(_c) is True)
for _c in ('ACCOUNT_BLOCKED', 'APIKEY_REVOKED', 'SESSION_INVALID'):
    check('...%s too' % _c, mod._unknown_account_code(_c) is True)
for _c in ('', '   ', 'AUTH_BAD_APIKEY', 'NO_SERVER', 'LINK_ERROR',
           'MAGNET_INVALID_ID', 'FILE_NOT_FOUND',
           'MAINTENANCE_MODE_BANNED_IPS', 'SUBSCRIPTION_TIER_METADATA_REFRESH',
           'TASK_FAILED_TO_START',
           # ORDER is what separates a job name from an account code: the job
           # puts the verb first (FAILED ... SESSION), the account code names
           # the thing first (SESSION_INVALID). Membership alone read this one
           # as a login failure.
           'TASK_FAILED_TO_START_SESSION', 'JOB_EXPIRED_ACCOUNT_SYNC'):
    check('...but %r is not an account code' % _c,
          mod._unknown_account_code(_c) is False)

# AND AN IDENTIFIER THAT IS ITSELF THE REFUSAL. A codeless service whose only
# human-facing text is `ACCOUNT_BLOCKED` was swallowed by the not-prose guard
# -- the same silence this file exists to end.
for _t in ('ACCOUNT_BLOCKED', 'ACCOUNT_SUSPENDED', 'SUBSCRIPTION.CANCELLED'):
    check('a bare %s message is still a refusal' % _t,
          mod._codeless_reason(_t) == mod._UNKNOWN_CODE_TEXT,
          repr(mod._codeless_reason(_t)))
check('...but a job identifier still is not',
      mod._codeless_reason('TASK_FAILED_TO_START_SESSION') is None)

# THE BRAND IS NOT A SUBJECT, EXCEPT WHEN IT IS POSSESSED. Blanking it killed
# the URL false positive and also killed "Your Premiumize has expired."
check('a possessed brand name reads as the account',
      mod._codeless_reason('Your Premiumize has expired.') is not None)
check('...and a bare brand in a URL still does not',
      mod._codeless_reason('https://www.premiumize.me/link-expired') is None)
_src_gate = io.open(os.path.join(LIB, 'debrid_status_notifier.py'),
                    encoding='utf-8').read()
check('...and the queue gate actually asks',
      '_unknown_account_code(refused[0])' in _src_gate)


# --- the two-word rule, against the corpus that broke its predecessors -----
# A FLAT SUBSTRING LIST WAS TRIED TWICE AND FAILED BOTH WAYS. "any message"
# put three plausible non-refusals on screen; a fourteen-phrase allowlist then
# matched ten of eleven non-account errors AND missed eight real refusals. The
# rule now needs a SUBJECT that belongs to the user and a PREDICATE saying what
# happened to it. This corpus is the review's, verbatim, plus the URL case that
# survived the first repair of it.
print()
print('=== a codeless message: precision on screen, recall in the log ===')
NOT_REFUSALS = (
    'Too many requests, please slow down.',
    'Downloads are temporarily disabled for maintenance.',
    'Service temporarily suspended for maintenance.',
    'Your IP has been banned.',
    'This link has expired.',
    'Missing parameter customer_id.',
    'Authentication service is currently down, try later.',
    '<html><head><title>503 Service Unavailable</title></head></html>',
    'https://www.premiumize.me/link-expired',
    'Rate limit exceeded. Retry after 60 seconds.',
    'Internal server error.',
    'Transfer failed: source unreachable.',
    'The file has been deleted from the cloud.',
    'Torrent not found in cache.',
)
REFUSALS = (
    'Not logged in.',
    'Your account has been permanently blocked.',
    'Account locked.',
    'Account terminated due to ToS violation.',
    'Invalid session, please log in again.',
    'No active plan on this account.',
    'Account not found.',
    'Access blocked for this account.',
    'Your account access has been revoked.',
    'Your premium membership has expired.',
    'Invalid apikey.',
    'The api key is invalid.',
    'Account is not premium.',
    'Login failed.',
    'Your subscription is inactive.',
    'Account suspended.',
    'Credentials required.',
)
# ROUND FOUR'S CORPUS, which broke the flat two-word rule: the words are in
# DIFFERENT CLAUSES, which is the ordinary shape of a status message and not
# an edge case. Plus the identifier that is not prose at all.
NOT_REFUSALS = NOT_REFUSALS + (
    'Your account is fine, but the server is blocked for maintenance.',
    'Your subscription remains active, however one of our mirror servers has '
    'been banned.',
    'Attention: your account dashboard is available. Our edge network blocked '
    'this request.',
    'Your account works normally. ' + 'x' * 2500 + ' The node is blocked.',
    'TASK_FAILED_TO_START_SESSION',
    'Maintenance window: downloads disabled until 04:00 UTC.',
    'Cloudflare: Access denied. Error 1020. Manage your account at the '
    'dashboard.',
    'The torrent was deleted from your cloud, but your account is active.',
)
# ...and the refusals the round-three repair had silently dropped by removing
# a whole word instead of gating it.
REFUSALS = REFUSALS + (
    'Your account has been disabled.',
    'Your account was closed.',
    'This account is frozen.',
    'Your membership was cancelled.',
    'Your api key has been deactivated.',
    'This account no longer exists.',
)
_fp = [t for t in NOT_REFUSALS if mod._codeless_reason(t)]
_fn = [t for t in REFUSALS if not mod._codeless_reason(t)]
check('no transient failure reaches the screen', not _fp,
      'these would raise a toast: %s' % _fp)
check('every real refusal does', not _fn, 'these say nothing: %s' % _fn)
check('...and every one of them in Hebrew',
      all(any('֐' <= ch <= 'ת' for ch in mod._codeless_reason(t) or '')
          for t in REFUSALS))
check('an unmatched message is written to the log, not simply dropped',
      'kodi_utils.log(' in _src_gate
      and 'account refusal, so nothing is shown' in _src_gate,
      'recall has to live somewhere, and it lives in the log')

_src = io.open(os.path.join(LIB, 'debrid_status_notifier.py'),
               encoding='utf-8').read()
check('only a KNOWN code reaches the queue',
      'refused[0] in _REFUSAL_TEXT' in _src,
      'an unrecognised code must not raise a toast at startup')
check('...or a message from a service that has no codes at all',
      'not refused[0] and refused[1]' in _src,
      'Premiumize sends no code, so the code-only gate silenced it entirely')
check('the extra request is paid only when there is no number',
      'if days is None:' in _src and '_refusal(service)' in _src)
check('...and only for a service the user actually connected',
      _src.index('_is_connected(addon, service)')
      < _src.index('refused = _refusal(service)'))

# --- and none of it may stand in front of the subtitle service -------------
# THE ONE REAL WEAKNESS THE REVIEW FOUND. This asks four services about the
# account over the network, through POV's client, and since 0.2.505 asks a
# second question of any that could not answer the first. POV bounds each
# request at 10-20s, so it cannot hang outright -- but the arithmetic reaches
# minutes on a bad night, and it used to run INLINE as a step of the startup
# repair pass, whose loop has no per-step budget. Everything after it waited,
# including the step that puts Hebrew subtitles on screen by itself.
print()
print('=== a subscription toast never delays the subtitle service ===')
_svc = io.open(os.path.join(ADDON, 'service.py'), encoding='utf-8').read()
_tree = ast.parse(_svc)
_fn = [f for f in ast.walk(_tree) if isinstance(f, ast.FunctionDef)
       and f.name == '_maybe_show_debrid_status']
check('the startup step was found', len(_fn) == 1)
if _fn:
    _threads = [n for n in ast.walk(_fn[0]) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == 'start']
    check('it starts a thread and returns', len(_threads) == 1)
    _daemon = [k for n in ast.walk(_fn[0]) if isinstance(n, ast.Call)
               for k in n.keywords if k.arg == 'daemon']
    check('...a daemon one, so quitting Kodi is never held up',
          len(_daemon) == 1)
    _inline = [n for n in ast.walk(_fn[0]) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Attribute)
               and n.func.attr == 'maybe_notify']
    _nested = [f.name for f in ast.walk(_fn[0])
               if isinstance(f, ast.FunctionDef) and f is not _fn[0]]
    check('the network work happens inside the thread, not before it',
          len(_inline) == 1 and len(_nested) == 1
          and any(isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)
                  and n.func.attr == 'maybe_notify'
                  for f in ast.walk(_fn[0])
                  if isinstance(f, ast.FunctionDef) and f is not _fn[0]
                  for n in ast.walk(f)),
          'a call outside the worker blocks the pass again')

print()
print('FAILED: %d -> %s' % (len(FAIL), FAIL) if FAIL else 'ALL PASS')
sys.exit(1 if FAIL else 0)
