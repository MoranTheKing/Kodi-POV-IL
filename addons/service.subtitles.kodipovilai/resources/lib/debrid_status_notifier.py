# -*- coding: utf-8 -*-
"""Build-only premium debrid subscription status toasts.

The thresholds are read from POV's existing "Premium Expires
Notification (days)" settings:

  rd.expires / tb.expires / pm.expires / ad.expires

`0` keeps the build's previous behaviour: show the status on every Kodi
startup. Any positive value shows only when the subscription has that
many days or fewer remaining (for example 3 = only in the last 3 days).
"""

import os
import re
import sys

try:
    import xbmc
    import xbmcaddon
    import xbmcgui
    import xbmcvfs
except ImportError:
    xbmc = None
    xbmcaddon = None
    xbmcgui = None
    xbmcvfs = None

from resources.lib import kodi_utils


WINDOW_PROP = 'kodipovilai.debrid_status_shown'

SERVICES = (
    {
        'name': 'Real-Debrid',
        'title': 'Real-Debrid',
        'prefix': 'rd',
        'enabled': 'rd.enabled',
        'connected': ('rd.username', 'rd.token', 'rd.refresh'),
        'expires': 'rd.expires',
        'module': 'real_debrid_api',
        'class': 'RealDebridAPI',
        'icon': 'realdebrid.png',
    },
    {
        'name': 'TorBox',
        'title': 'TorBox',
        'prefix': 'tb',
        'enabled': 'tb.enabled',
        'connected': ('tb.account_id', 'tb.token'),
        'expires': 'tb.expires',
        'module': 'torbox_api',
        'class': 'TorBoxAPI',
        'icon': 'torbox.png',
    },
    {
        'name': 'Premiumize',
        'title': 'Premiumize',
        # Its refusals are {"status":"error","message":"..."} at HTTP 200 --
        # no error object, no code. See _refusal.
        'codeless': True,
        'prefix': 'pm',
        'enabled': 'pm.enabled',
        'connected': ('pm.account_id', 'pm.token'),
        'expires': 'pm.expires',
        'module': 'premiumize_api',
        'class': 'PremiumizeAPI',
        'icon': 'premiumize.png',
    },
    {
        'name': 'AllDebrid',
        'title': 'AllDebrid',
        'prefix': 'ad',
        'enabled': 'ad.enabled',
        'connected': ('ad.account_id', 'ad.token'),
        'expires': 'ad.expires',
        'module': 'alldebrid_api',
        'class': 'AllDebridAPI',
        'icon': 'alldebrid.png',
    },
)


def _pov_addon():
    if xbmcaddon is None:
        return None
    try:
        return xbmcaddon.Addon('plugin.video.pov')
    except Exception:
        return None


def _setting(addon, key, default=''):
    try:
        value = addon.getSetting(key)
        return value if value is not None else default
    except Exception:
        return default


def _pov_lib_path():
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/plugin.video.pov/resources/lib')
    except Exception:
        return ''


def _media_icon(filename):
    if xbmcvfs is None:
        return None
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/plugin.video.pov/resources/'
            'skins/Default/media/' + filename)
    except Exception:
        return None


def _days_remaining(service):
    lib_path = _pov_lib_path()
    if not lib_path or not os.path.isdir(lib_path):
        return None

    inserted = False
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)
        inserted = True
    try:
        module = __import__(
            'debrids.' + service['module'], fromlist=[service['class']])
        cls = getattr(module, service['class'])
        return cls().days_remaining()
    except Exception as exc:
        kodi_utils.log('{0} status lookup failed: {1}'.format(
            service['name'], exc), level='WARNING')
        return None
    finally:
        if inserted:
            try:
                sys.path.remove(lib_path)
            except ValueError:
                pass


# WHY A REFUSED ACCOUNT USED TO SHOW NOTHING AT ALL.
#
# A field report: every AllDebrid source failed to resolve. The log showed no
# reason, and three separate layers were why. POV's alldebrid_api._request
# logs only when the HTTP STATUS is bad -- and AllDebrid answers 200 with the
# error inside the body, the way its API has always worked. POV's
# days_remaining() wraps the lot in a bare `except: days = None`. And this
# file then read None as 'no number, so say nothing'. Three swallows in a row,
# and the one field that holds the answer never reached anyone.
#
# Verified against the live API, without the reporter's log or credentials:
#
#     GET v4/magnet/upload  ->  200  {"status":"error",
#                                     "error":{"code":"AUTH_...",
#                                              "message":"..."}}
#
# and v4/magnet/instant answers 404, so the endpoints are alive and it is not
# an API generation problem: AllDebrid is refusing THIS account, and naming
# which refusal in a field nobody read.
#
# NARROW ON PURPOSE. This speaks only for an unambiguous error envelope with
# one of the codes below -- reasons about the ACCOUNT, which a user can act
# on. A timeout, a dropped connection or an unrecognised shape says nothing,
# because a toast that cries wolf on a flaky night is worse than silence.
_REFUSAL_TEXT = {
    'AUTH_MISSING_APIKEY': 'החשבון לא מחובר',
    'AUTH_BAD_APIKEY': 'המפתח אינו תקף -- צריך לחבר מחדש',
    'AUTH_BLOCKED': 'הגישה חסומה',
    'AUTH_USER_BANNED': 'החשבון מושעה',
    'MUST_BE_PREMIUM': 'החשבון אינו פרימיום',
}


# A SERVICE WITH NO CODES: TWO WORDS, NOT ONE PHRASE.
#
# Premiumize refuses with {"status":"error","message":"..."} and no code, so
# the code gate silenced it entirely. The first fix accepted ANY message from a
# codeless service and a review put three plausible non-refusals on screen. The
# second fix was a list of fourteen substrings, and the same review took it
# apart in both directions at once: ten of eleven non-account errors matched
# something (a maintenance notice matched "disabled", an IP ban matched
# "banned", an expired download link matched "expired", an outage matched
# "authentication"), while eight real refusals matched nothing at all
# ("Account locked.", "...permanently blocked.", "No active plan on this
# account.", "Invalid session, please log in again."). A flat substring list
# cannot separate "your account is blocked" from "downloads are temporarily
# disabled", because the distinguishing word is not the one being matched.
#
# WHAT ACTUALLY SEPARATES THEM is that a refusal names a SUBJECT that belongs
# to the user -- their account, their key, their membership, their session --
# AND says something happened to it. A transient failure names a service, a
# link, a parameter, an IP. So: one word from each column, in any order, with
# anything in between.
#
#     "Your account has been permanently blocked."   account + blocked   -> yes
#     "Downloads temporarily disabled for maintenance."   no subject     -> no
#     "Your IP has been banned."                     no subject          -> no
#     "This link has expired."                       no subject          -> no
#     "Missing parameter customer_id."               no subject          -> no
#
# A few refusals are complete sentences with no predicate ("Not logged in.")
# and are listed whole.
#
# WHAT AN UNMATCHED MESSAGE GETS: the log, not the screen. That is the trade
# this file has always made -- a toast that cries wolf costs more trust than
# the one it saves -- and it is affordable precisely because the log line is
# now the thing that diagnoses (see pov_debrid_error_log_patcher). Precision
# on the screen, recall in the log.

# Sentence and clause boundaries. `but`/`however`/`although` are here
# because they are exactly how a message says "this part is fine, that
# part is not", which is the shape that fooled the previous rule.
_OWNED_BRAND_RE = re.compile(
    r'\b(your|my|the)\s+(?:premiumize|alldebrid|torbox|offcloud)\b')

_IDENT_RE = re.compile(r'^[A-Z0-9_.\-]{3,}$')

_CLAUSE_RE = re.compile(
    r'[.;!?\n]+|,\s*(?:but|however|although|though|while|and)\b'
    r'|\s+(?:but|however|although|though)\b')

_URL_RE = re.compile(r'\S+://\S+|\bwww\.\S+')

# Something of the user's. Never a service, a link, a parameter or an IP.
_ACCOUNT_SUBJECTS = (
    'account', 'apikey', 'api key', 'api-key', 'membership', 'premium',
    'subscription', 'session', 'login', 'log in', 'logged in', 'credentials',
)

# What was done to it, and the Hebrew that says so. Most specific first; the
# first predicate that matches decides the wording.
_ACCOUNT_PREDICATES = (
    ('blocked', 'החשבון חסום'),
    ('banned', 'החשבון מושעה'),
    ('suspended', 'החשבון מושעה'),
    ('locked', 'החשבון נעול'),
    ('terminated', 'החשבון נסגר'),
    ('revoked', 'ההרשאה בוטלה'),
    ('deleted', 'החשבון נמחק'),
    ('expired', 'המנוי פג'),
    ('no active', 'המנוי אינו פעיל'),
    ('inactive', 'המנוי אינו פעיל'),
    ('not premium', 'החשבון אינו פרימיום'),
    ('not found', 'החשבון לא נמצא'),
    ('no longer exists', 'החשבון לא נמצא'),
    # 'disabled' WAS DROPPED WHOLESALE after it matched a maintenance notice,
    # and that reopened "Your account has been disabled." -- one of the
    # commonest real refusals there is -- as total silence. The subject gate
    # was already what separated them: "downloads are temporarily disabled"
    # names no account, no key and no subscription, so it still says nothing.
    # Dropping the word bought nothing and cost a whole class of refusal.
    ('disabled', 'החשבון מושבת'),
    ('deactivated', 'החשבון מושבת'),
    ('closed', 'החשבון נסגר'),
    ('frozen', 'החשבון מוקפא'),
    ('cancelled', 'המנוי בוטל'),
    ('canceled', 'המנוי בוטל'),
    ('invalid', 'הפרטים אינם תקפים -- צריך לחבר מחדש'),
    ('incorrect', 'הפרטים אינם תקפים -- צריך לחבר מחדש'),
    ('unauthorized', 'הגישה נדחתה'),
    ('denied', 'הגישה נדחתה'),
    ('forbidden', 'הגישה נדחתה'),
    ('required', 'החשבון לא מחובר'),
    ('missing', 'החשבון לא מחובר'),
    ('failed', 'ההתחברות נכשלה'),
)

# Complete refusals that carry no predicate of their own.
_WHOLE_REFUSALS = (
    ('not logged in', 'החשבון לא מחובר'),
    ('not authenticated', 'החשבון לא מחובר'),
    ('login failed', 'ההתחברות נכשלה'),
    ('not premium', 'החשבון אינו פרימיום'),
)


# A code this build has no Hebrew for, but whose family says "account".
# Deliberately two prefixes and one word rather than anything cleverer: these
# are machine-readable identifiers, not prose, so there is nothing to parse.
_UNKNOWN_CODE_TEXT = 'החשבון נדחה'

# A code this build has no Hebrew for, but whose family says "account".
#
# A flat "does it contain one of these five words" list had the same two-sided
# problem the prose rule had: MAINTENANCE_MODE_BANNED_IPS and
# SUBSCRIPTION_TIER_METADATA_REFRESH both matched (neither is an account
# refusal), while REFRESH_TOKEN_EXPIRED and USER_ACCOUNT_REMOVED matched
# nothing (both are). A code is underscore-separated tokens, so the same
# subject-plus-predicate shape works and there is no clause problem to solve.
_CODE_SUBJECTS = frozenset((
    'AUTH', 'ACCOUNT', 'USER', 'APIKEY', 'KEY', 'PREMIUM', 'SUBSCRIPTION',
    'MEMBERSHIP', 'LOGIN', 'SESSION', 'TOKEN', 'CREDENTIALS', 'PLAN',
))
_CODE_PREDICATES = frozenset((
    'BANNED', 'BLOCKED', 'LOCKED', 'SUSPENDED', 'TERMINATED', 'REVOKED',
    'EXPIRED', 'INVALID', 'DENIED', 'DISABLED', 'DEACTIVATED', 'REMOVED',
    'DELETED', 'MISSING', 'BAD', 'FAILED', 'REQUIRED', 'UNAUTHORIZED',
    'FORBIDDEN', 'INACTIVE', 'CANCELLED', 'CANCELED', 'CLOSED',
))
# NOT 'PREMIUM' -- it is already a SUBJECT, and a token that is both satisfies
# any subject-and-predicate rule against itself. CATALOG_PREMIUM_TIER_SYNC_JOB
# and PREMIUM_CACHE_WARM both produced "the account was rejected" on that
# alone. MUST_BE_PREMIUM, the real code, is in _REFUSAL_TEXT and never
# reaches here.


def _unknown_account_code(code):
    code = (code or '').strip().upper()
    if not code or code in _REFUSAL_TEXT:
        return False
    # AUTH_ is the documented account namespace for the providers that send
    # codes at all, so the prefix alone is enough -- AUTH_SOMETHING_NEW is
    # exactly the case this function exists for.
    if code.startswith('AUTH_'):
        return True
    # ADJACENCY, NOT ORDER. The previous rule was "the subject comes first",
    # which rejected TASK_FAILED_TO_START_SESSION correctly and then rejected
    # EXPIRED_SUBSCRIPTION_NOTICE and BLOCKED_ACCOUNT_REGION with it -- real
    # refusals that happen to put the verb in front. Order is not the signal;
    # DISTANCE is. An account code says the two things next to each other, in
    # either order:
    #
    #     ACCOUNT_BLOCKED        BLOCKED_ACCOUNT_REGION
    #     SUBSCRIPTION_EXPIRED   EXPIRED_SUBSCRIPTION_NOTICE
    #     REFRESH_TOKEN_EXPIRED  USER_ACCOUNT_REMOVED
    #
    # while a job code has the whole job name in between:
    #
    #     TASK_FAILED_TO_START_SESSION      (FAILED ... SESSION, three apart)
    tokens = re.split(r'[^A-Z0-9]+', code)
    subjects = [i for i, t in enumerate(tokens) if t in _CODE_SUBJECTS]
    predicates = [i for i, t in enumerate(tokens) if t in _CODE_PREDICATES]
    if not subjects or not predicates:
        return False
    return any(abs(a - b) <= 1 for a in subjects for b in predicates)


def _codeless_reason(message):
    """The Hebrew for an account-level refusal with no code, or None.

    None means "this service said error, but not about the account" -- a rate
    limit, a maintenance window, a shape nobody here recognises. The caller
    must then say nothing on screen and write the text to the log instead.

    WHAT THIS STILL GETS WRONG, written down rather than tuned for a fifth
    round. Within one clause there is no way to tell WHICH noun the predicate
    belongs to, so these are misread as refusals:

        "We blocked your account's IP."          (the IP was blocked)
        "Your account password reset link expired."   (the link expired)
        "your account is active and downloads are blocked"  (no comma, so no
                                                             clause split)

    and a refusal whose subject and predicate land in different sentences,
    joined by a pronoun, is missed:

        "Please review your account. It has been suspended."

    Each of those is fixable with another rule and each new rule has cost a
    false negative somewhere else -- three rounds have now traded one for the
    other. The reason it is acceptable to stop here is the GATE this runs
    behind: the service must be connected, days_remaining() must have already
    failed, AND a second account lookup must have returned a structured error.
    Nobody whose account is working ever reaches this function. So the worst a
    residual false positive does is give a wrong REASON to somebody whose
    account really is failing -- and the full text is in the log either way.
    """
    low = ' '.join((message or '').lower().split())
    # A URL IS CONTEXT, NEVER THE REFUSAL, and it is made of exactly the words
    # this rule looks for: `https://www.premiumize.me/link-expired` carries the
    # subject "premium" (inside the brand name) and the predicate "expired",
    # and read as prose it says the account's subscription has lapsed. It was
    # the one survivor of the adversarial corpus. Stripped, along with the
    # service's own name, before anything is matched.
    low = _URL_RE.sub(' ', low)
    # THE BRAND IS NOT A SUBJECT, EXCEPT WHEN IT IS. Blanking it outright
    # removes a false subject ("premiumize" contains "premium") -- which is
    # what the URL case needed -- but it also removes a real one: "Your
    # Premiumize has expired" becomes "your has expired" and matches nothing.
    # Possessed, the brand IS the account being talked about, so it becomes
    # the word for it; everywhere else it goes.
    low = _OWNED_BRAND_RE.sub(r'\1 account', low)
    low = low.replace('premiumize', ' ').replace('alldebrid', ' ')
    low = low.replace('torbox', ' ').replace('offcloud', ' ')
    low = ' '.join(low.split())
    if not low:
        return None
    # AN IDENTIFIER IS NOT PROSE. `TASK_FAILED_TO_START_SESSION` is a backend
    # job name, and reading it as a sentence found "session" and "failed" in
    # one clause and called it a login failure. Anything with no spaces that is
    # only caps, digits, underscores and dots is a machine code -- it belongs
    # to _unknown_account_code, which reads codes, not to a rule that reads
    # English.
    if _IDENT_RE.match(message or ''):
        # ...but an identifier can still BE the refusal. A codeless service
        # whose only human-facing text is `ACCOUNT_BLOCKED` was swallowed
        # here, which is the same silence this file exists to end. Codes have
        # their own reader; use it, and fall back to the generic wording since
        # there is no prose to derive a specific one from.
        return _UNKNOWN_CODE_TEXT if _unknown_account_code(message) else None
    for needle, hebrew in _WHOLE_REFUSALS:
        if needle in low:
            return hebrew
    # SAME CLAUSE, NOT SAME STRING. Two independent whole-string tests have no
    # proximity constraint at all, and a review showed that is not an edge
    # case but the ordinary shape of a status message:
    #
    #     "Your account is fine, but the server is blocked for maintenance."
    #
    # subject in the first clause, predicate in the second, and the old rule
    # called it an account refusal. So did a Cloudflare block page that
    # mentions "account" in its boilerplate, and a benign string with the two
    # words 2,500 characters apart.
    #
    # Splitting on clause boundaries is not linguistics -- it is the one thing
    # that separates "my account is blocked" from "my account is fine BUT
    # something else is blocked", which is the whole failure mode.
    for clause in _CLAUSE_RE.split(low):
        if not any(subject in clause for subject in _ACCOUNT_SUBJECTS):
            continue
        for needle, hebrew in _ACCOUNT_PREDICATES:
            if needle in clause:
                return hebrew
    return None


def _refusal(service):
    """(code, message) when the service refuses the account, else None.

    Costs one extra request, and only for a service that is connected and
    already failed to report its days -- so nobody who is fine pays for it.
    """
    lib_path = _pov_lib_path()
    if not lib_path or not os.path.isdir(lib_path):
        return None
    inserted = False
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)
        inserted = True
    try:
        module = __import__(
            'debrids.' + service['module'], fromlist=[service['class']])
        info = getattr(module, service['class'])().account_info()
        if not isinstance(info, dict) or info.get('status') != 'error':
            return None
        err = info.get('error') or {}
        if not isinstance(err, dict):
            # PREMIUMIZE PUTS THE REASON SOMEWHERE ELSE, and reading only
            # AllDebrid's shape meant a refused Premiumize account said
            # nothing at all -- on screen or in the log. Its envelope is
            # {"status":"error","message":"..."} at HTTP 200, with no `error`
            # object and no code, so this used to return None here and the
            # user was left with a search that found sources and then showed
            # an empty list.
            err = {}
        code = (err.get('code') or '').strip()
        message = (err.get('message') or info.get('message') or '').strip()
        if code:
            return (code, message)
        # A BARE MESSAGE COUNTS ONLY WHERE THE SERVICE HAS NO CODES, and that
        # is one service. AllDebrid always sends a code, so a coded envelope
        # arriving without one from AllDebrid is a shape nobody recognises and
        # is still nothing -- widening the rule for everyone would put an
        # arbitrary string on screen the first time a provider answered oddly.
        # Premiumize never sends a code at all; the narrow rule alone let it
        # refuse an account in perfect silence.
        if service.get('codeless') and message:
            if _codeless_reason(message):
                return ('', message)
            try:
                kodi_utils.log(
                    '{0} answered an error this build does not read as an '
                    'account refusal, so nothing is shown: {1!r}'.format(
                        service['name'], message))
            except Exception:
                pass
        return None
    except Exception:
        return None
    finally:
        if inserted:
            try:
                sys.path.remove(lib_path)
            except ValueError:
                pass


def _refusal_message(service, code, message):
    # Hebrew first, from whichever table can supply it: the code table for a
    # service that sends codes, the two-word rule for one that does not. The
    # last resort is a GENERIC Hebrew line rather than the provider's English:
    # the only way to get here is an account-shaped code this build has no
    # wording for yet (AUTH_SOMETHING_NEW), and "the account was refused --
    # AUTH_SOMETHING_NEW" is readable by somebody who does not read English,
    # where the provider's sentence is not. The raw text still goes to the log.
    known = _REFUSAL_TEXT.get(code) or (
        _UNKNOWN_CODE_TEXT if code else _codeless_reason(message))
    detail = known or message or code
    if known is _UNKNOWN_CODE_TEXT and code:
        detail = '%s (%s)' % (known, code)
    return '[B]{0}: [COLOR red]{1}[/COLOR][/B]'.format(service['name'], detail)


def _threshold(addon, service):
    raw = _setting(addon, service['expires'], '0')
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 0
    # 0 = always show. This preserves the status-on-startup behaviour
    # users already saw, while positive values become "warn only when
    # days_remaining <= value".
    return max(0, value)


def _is_connected(addon, service):
    if _setting(addon, service['enabled'], 'true').lower() != 'true':
        return False
    return any(_setting(addon, key) for key in service['connected'])


def _should_show(days, threshold):
    if days is None:
        return False
    return threshold == 0 or days <= threshold


def _message(service, days):
    if days > 0:
        status = '[COLOR limegreen]פרימיום[/COLOR]'
        suffix = ' (נותרו {0} ימים)'.format(days)
    else:
        status = '[COLOR red]לא בתוקף[/COLOR]'
        suffix = ''
    return '[B]סטטוס מנוי {0}: {1}{2}[/B]'.format(
        service['name'], status, suffix)


def maybe_notify():
    if xbmc is None:
        return 'no_kodi'

    try:
        window = xbmcgui.Window(10000)
        if window.getProperty(WINDOW_PROP) == '1':
            return 'already_shown'
    except Exception:
        window = None

    addon = _pov_addon()
    if addon is None:
        return 'no_pov'

    queue = []
    for service in SERVICES:
        if not _is_connected(addon, service):
            continue
        days = _days_remaining(service)
        if days is None:
            # No number is not nothing to say. Ask once why.
            refused = _refusal(service)
            # THREE WAYS THROUGH, and the third was a hole a review found.
            #
            #   1. a code this build has Hebrew for;
            #   2. a code it does NOT know but whose SHAPE says account -- the
            #      providers that send codes prefix the account-level ones
            #      AUTH_, and MUST_BE_PREMIUM is the other family. Without
            #      this, a new AUTH_ code from AllDebrid produced no toast at
            #      all, not even in English, which is the same silence the
            #      whole file exists to end -- and a comment two functions
            #      down claimed the opposite was true;
            #   3. a service with no codes at all, whose message reads as an
            #      account refusal (see _codeless_reason).
            if refused and (refused[0] in _REFUSAL_TEXT
                            or _unknown_account_code(refused[0])
                            or (not refused[0] and refused[1])):
                queue.append((service, refused))
            continue
        threshold = _threshold(addon, service)
        if _should_show(days, threshold):
            queue.append((service, days))

    if not queue:
        return 'nothing_to_show'

    monitor = xbmc.Monitor()
    if monitor.waitForAbort(1.8):
        return 'aborted'

    shown = 0
    for idx, (service, days) in enumerate(queue):
        if idx and monitor.waitForAbort(4.8):
            return 'aborted'
        text = (_refusal_message(service, days[0], days[1])
                if isinstance(days, tuple) else _message(service, days))
        kodi_utils.notify(
            text,
            title=service['title'],
            icon=_media_icon(service['icon']),
            time_ms=4500)
        shown += 1

    if window is not None:
        try:
            window.setProperty(WINDOW_PROP, '1')
        except Exception:
            pass
    return 'shown:{0}'.format(shown)
