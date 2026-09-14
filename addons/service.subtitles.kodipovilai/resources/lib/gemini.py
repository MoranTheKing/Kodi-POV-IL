# Google Generative Language API client. Just the bits we need:
# generateContent for translation, ListModels for the connection
# test. Bring your own API key.

import json
import re
import urllib.parse

try:
    import requests
except ImportError:
    requests = None

API_BASE = 'https://generativelanguage.googleapis.com/v1beta'

REQUEST_TIMEOUT = 90


# ---------------------------------------------------------------------------
# The sampling knobs, and which models still take them.
#
# Google's own words, from the Gemini API docs:
#
#     temperature, top_p, and top_k are deprecated and ignored. In future
#     model generations, supplying these parameters returns an HTTP 400
#     error. Remove these parameters from all requests.
#
# "Ignored" today, a hard 400 tomorrow -- and a 400 on a translation chunk is
# not a degraded translation, it is no translation at all. So the rule is
# applied by MODEL, not globally: everything from 3.5 up gets a request with
# no sampling fields in it, and 2.5 / 3.1 keep them, where they still do real
# work (they are what the build's validated 1.0 / 0.95 tuning was measured on).
#
# THIS IS THE ONLY PLACE THAT DECIDES. Both request builders below consult it,
# so a caller may keep passing temperature= and top_p= without knowing the
# rule, and a caller added later cannot forget it. That is deliberate: the
# alternative -- an `if` at every call site -- is how one of them ends up
# missed, and subsync.py's audio call (a hardcoded temperature=0.0, nowhere
# near translate.py) is exactly the site that would have been.
#
# top_k is in Google's list too. We have never sent it and there is no setting
# for it, so there is nothing to gate -- noted here so the next reader does not
# go looking for the missing third branch.
_SAMPLING_RETIRED_FROM = (3, 5)

# The generation out of a model id: 'gemini-3.5-flash-lite' -> (3, 5). Written
# as a search rather than a full match so the dated preview ids Google hands
# out ('gemini-2.5-flash-lite-preview-06-17') still resolve -- the trailing
# 06-17 has no dot, so the first X.Y in the string is the generation.
_GENERATION_RE = re.compile(r'(?:^|[^0-9.])(\d+)\.(\d+)')


def model_generation(model):
    """(major, minor) for a Gemini model id, or None when it carries no
    version -- an alias like 'gemini-flash-latest', say."""
    m = _GENERATION_RE.search((model or '').strip().lower())
    if not m:
        return None
    try:
        return (int(m.group(1)), int(m.group(2)))
    except (TypeError, ValueError):
        return None


def sampling_params_supported(model):
    """True when this model still honours temperature / top_p / top_k.

    An id we cannot read a generation out of answers False. That direction is
    chosen, not accidental: an unversioned alias resolves to whatever is newest
    (which is where the parameters are going away), omitting them is a valid
    request on every model that ever accepted them, and the cost of guessing
    wrong the other way is an HTTP 400 that kills the whole translation."""
    generation = model_generation(model)
    if generation is None:
        return False
    return generation < _SAMPLING_RETIRED_FROM


class GeminiError(Exception):
    """Raised on any non-recoverable API failure."""


class QuotaExceeded(GeminiError):
    """DAILY request limit hit (HTTP 429, RPD). Terminal for today -- caller
    should fall back (Google Translate) and may suggest waiting until UTC
    midnight. Distinct from RateLimited (a temporary per-minute 429)."""


class RateLimited(GeminiError):
    """TEMPORARY per-minute rate limit (HTTP 429, RPM/TPM) -- NOT the daily
    quota. Clears within ~60s, so the caller should back off and RETRY the same
    request rather than abort. `retry_after` is the API-suggested wait in seconds
    (0 when the response didn't provide one)."""
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


class OverloadError(GeminiError):
    """Service-side overload (HTTP 503 / 500). Retryable with
    longer backoff -- Google explicitly tells callers to wait at
    least a few seconds before retrying these."""


class InvalidKey(GeminiError):
    """Key is missing / revoked / malformed."""


class TruncatedResponse(GeminiError):
    """Model hit its output-token cap mid-response. The text we
    received is real but cut off (incomplete subtitle entries at
    the end). Caller should re-issue with smaller input."""
    def __init__(self, message, partial_text=''):
        super().__init__(message)
        self.partial_text = partial_text


class FilteredResponse(GeminiError):
    """Gemini returned no candidates (a safety filter blocked the chunk, even
    with safety set to BLOCK_NONE). Caller should bisect; a single still-blocked
    entry can be left in the source language rather than aborting everything."""
    def __init__(self, message, partial_text=''):
        super().__init__(message)
        self.partial_text = partial_text


_FILTERED_FINISH_REASONS = frozenset((
    'SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST',
))
_CONTENT_REJECTION_RE = re.compile(
    r'PROHIBITED_CONTENT|'
    r'(?:PROMPT|CONTENT)\s+(?:WAS\s+)?(?:BLOCKED|PROHIBITED)(?:\s+FOR\s+SAFETY)?|'
    r'REQUEST\s+(?:WAS\s+)?BLOCKED\s*:\s*(?:SAFETY|BLOCKLIST)', re.I)
_CONFIG_OR_ACCESS_REJECTION_RE = re.compile(
    r'SAFETY_?SETTINGS?|INVALID\s+(?:ENUM|VALUE)|UNSUPPORTED|NOT\s+A\s+VALID|'
    r'VPC\s+SERVICE\s+CONTROLS?', re.I)


def _structured_block_reason(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if (str(key).replace('_', '').lower() == 'blockreason'
                    and str(item or '').upper() in _FILTERED_FINISH_REASONS):
                return str(item).upper()
            found = _structured_block_reason(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _structured_block_reason(item)
            if found:
                return found
    return ''


def _raise_rejected_request(r):
    """Classify 400/403 bodies without losing recoverable content blocks."""
    body = r.text or ''
    snippet = body[:600]
    upper = snippet.upper()
    if ('API KEY' in upper or 'API_KEY' in upper
            or 'X-GOOG-API-KEY' in upper):
        raise InvalidKey('Key rejected: {0}'.format(snippet[:300]))
    structured_reason = ''
    try:
        structured_reason = _structured_block_reason(r.json())
    except (ValueError, TypeError, AttributeError):
        pass
    if (structured_reason or (
            not _CONFIG_OR_ACCESS_REJECTION_RE.search(snippet)
            and _CONTENT_REJECTION_RE.search(snippet))):
        raise FilteredResponse(
            'Request content blocked (HTTP {0})'.format(r.status_code))
    raise GeminiError('Request rejected: {0}'.format(snippet[:300]))


def _generated_text(data):
    """Return visible candidate text or the precise recoverable exception.

    Gemini may attach a filtered finish reason to a candidate that still has
    partial text.  Accepting that text silently creates missing subtitle cues,
    so finish reason wins over presence of text.  Thinking parts are model
    internals and must never become subtitle or SubSync output.
    """
    if not isinstance(data, dict):
        raise GeminiError('Bad response shape: top level is not an object')
    feedback = data.get('promptFeedback') or {}
    if isinstance(feedback, dict) and feedback.get('blockReason'):
        raise FilteredResponse(
            'prompt blocked: {0}'.format(feedback.get('blockReason')))
    candidates = data.get('candidates') or []
    if not isinstance(candidates, list) or not candidates:
        raise FilteredResponse(
            'No candidates in response (possibly filtered)')
    candidate = candidates[0] if isinstance(candidates[0], dict) else {}
    content = candidate.get('content') or {}
    content = content if isinstance(content, dict) else {}
    parts = content.get('parts') or []
    parts = parts if isinstance(parts, list) else []
    chunks = []
    for part in parts:
        if not isinstance(part, dict) or part.get('thought'):
            continue
        chunk = part.get('text', '')
        if isinstance(chunk, str):
            chunks.append(chunk)
    text = ''.join(chunks).strip()
    finish_reason = str(candidate.get('finishReason') or '').upper()
    if finish_reason in _FILTERED_FINISH_REASONS:
        raise FilteredResponse(
            'candidate blocked (finish={0})'.format(finish_reason),
            partial_text=text,
        )
    if not text:
        if finish_reason in ('OTHER', ''):
            raise FilteredResponse(
                'empty/blocked content (finish={0})'.format(finish_reason))
        raise GeminiError('Empty text in response')
    if finish_reason in ('MAX_TOKENS', 'LENGTH'):
        raise TruncatedResponse(
            'Gemini hit output-token cap (finishReason={0})'.format(
                finish_reason),
            partial_text=text,
        )
    return text


def _classify_429(r):
    """A Gemini 429 is EITHER a temporary per-minute rate limit (RPM/TPM) OR the
    daily quota (RPD) -- identical status code, so inspect the body. A QuotaFailure
    violation whose quota id/metric mentions 'per day' -> terminal QuotaExceeded;
    anything else (per-minute, or unparseable) -> RateLimited so the caller retries.
    Defaulting the ambiguous case to RateLimited is safe: if it truly were daily the
    retries keep getting 429 and the caller falls back anyway (just later), whereas
    mislabelling a per-minute burst as 'daily quota' (the old behaviour) needlessly
    kills AI translation for the rest of the movie."""
    retry_after = 0
    is_daily = False
    try:
        err = (r.json() or {}).get('error', {}) or {}
        for d in err.get('details', []) or []:
            typ = str(d.get('@type', ''))
            if typ.endswith('RetryInfo'):
                rd = str(d.get('retryDelay', '') or '').strip().rstrip('s')
                try:
                    retry_after = int(float(rd)) if rd else 0
                except (ValueError, TypeError):
                    retry_after = 0
            if typ.endswith('QuotaFailure'):
                for v in d.get('violations', []) or []:
                    q = (str(v.get('quotaId', '')) + '|'
                         + str(v.get('quotaMetric', ''))).lower()
                    if 'perday' in q or 'per_day' in q:
                        is_daily = True
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    if is_daily:
        return QuotaExceeded('Daily quota exceeded')
    return RateLimited('Per-minute rate limit (HTTP 429)', retry_after=retry_after)


def test_key(api_key, model='gemini-3.5-flash-lite'):
    """Cheap sanity check: list the user's available models and
    confirm the chosen one is in the set. Returns the model id we
    matched (so the caller can show "Connected: <model>")."""
    if not requests:
        raise GeminiError('python-requests is not installed')
    if not api_key:
        raise InvalidKey('No API key provided')

    # Auth via the x-goog-api-key HEADER, not ?key= -- Google's newer
    # 'AQ.'-prefixed keys reject the query-param method with 401 while the
    # header method works for every key type. Send exactly ONE credential
    # (key in both places returns 400 "multiple auth").
    url = '{0}/models'.format(API_BASE)
    try:
        r = requests.get(url, headers={'x-goog-api-key': api_key},
                         timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        raise GeminiError('Network error: {0}'.format(e))

    if r.status_code in (401, 407):
        # 401 is always an auth failure (invalid/expired/revoked key) -- surface
        # it as a rejected key so the connect dialog says so plainly.
        raise InvalidKey('Gemini rejected the key (HTTP {0} -- invalid or '
                         'expired): {1}'.format(r.status_code,
                                                (r.text or '').strip()[:140]))
    if r.status_code == 400 or r.status_code == 403:
        # Surface Google's actual error reason -- the API returns JSON
        # like {"error":{"code":400,"message":"API key not valid. ..."}}
        # and the user otherwise sees only "rejected (400)" with no
        # clue WHY (typo'd key vs revoked vs quota vs project not
        # enabled all show the same way). Trim to a sensible length.
        reason = ''
        try:
            err = (r.json() or {}).get('error') or {}
            reason = err.get('message') or err.get('status') or ''
        except Exception:
            pass
        if not reason:
            reason = (r.text or '').strip()[:140]
        raise InvalidKey('Gemini rejected the key ({0}): {1}'.format(
            r.status_code, reason or '(no reason returned)'))
    if r.status_code != 200:
        raise GeminiError('HTTP {0}: {1}'.format(r.status_code, r.text[:200]))

    try:
        data = r.json()
    except ValueError:
        raise GeminiError('Unparseable response from API')

    available = [m.get('name', '').replace('models/', '')
                 for m in data.get('models', [])]
    if model in available:
        return model
    # If the user's chosen model isn't listed, fall back to any
    # flash-lite variant so the dialog still shows a happy result.
    for cand in available:
        if 'flash-lite' in cand:
            return cand
    return available[0] if available else 'unknown'


def generate_media(api_key, model, prompt, media_bytes, mime,
                   temperature=0.0, max_output_tokens=8192,
                   timeout=REQUEST_TIMEOUT):
    """One-shot generation with an inline media part (e.g. an AAC audio clip
    for speech-interval extraction -- SubSync S5). Same error contract as
    generate(). Kept separate so the translation path is untouched."""
    if not requests:
        raise GeminiError('python-requests is not installed')
    if not api_key:
        raise InvalidKey('No API key provided')
    if not model:
        raise GeminiError('No model selected')
    import base64 as _b64
    url = '{0}/models/{1}:generateContent'.format(
        API_BASE, urllib.parse.quote(model, safe=''))
    media_config = {'maxOutputTokens': max_output_tokens}
    if sampling_params_supported(model):
        media_config['temperature'] = temperature
    payload = {
        'contents': [{'parts': [
            {'text': prompt},
            {'inline_data': {
                'mime_type': mime,
                'data': _b64.b64encode(media_bytes).decode('ascii'),
            }},
        ]}],
        'generationConfig': media_config,
    }
    try:
        r = requests.post(url, data=json.dumps(payload),
                          headers={'Content-Type': 'application/json',
                                   'x-goog-api-key': api_key},
                          timeout=timeout)
    except requests.RequestException as e:
        raise GeminiError('Network error: {0}'.format(e))
    if r.status_code == 429:
        raise _classify_429(r)
    if r.status_code in (500, 502, 503, 504):
        raise OverloadError(
            'Gemini overloaded (HTTP {0})'.format(r.status_code))
    if r.status_code in (401, 407):
        raise InvalidKey('Key rejected (HTTP {0} -- invalid/expired key): {1}'
                         .format(r.status_code, (r.text or '')[:180]))
    if r.status_code in (400, 403):
        _raise_rejected_request(r)
    if r.status_code != 200:
        raise GeminiError('HTTP {0}: {1}'.format(r.status_code, r.text[:200]))
    try:
        data = r.json()
    except ValueError:
        raise GeminiError('Unparseable response from API')
    return _generated_text(data)


def generate(api_key, model, prompt, temperature=0.2,
             max_output_tokens=16384, top_p=None,
             thinking_budget=None, thinking_level=None,
             timeout=REQUEST_TIMEOUT):
    """One-shot text generation. Returns the model's text response.

    Raises QuotaExceeded on 429, InvalidKey on 400/403, GeminiError
    on anything else."""
    if not requests:
        raise GeminiError('python-requests is not installed')
    if not api_key:
        raise InvalidKey('No API key provided')
    if not model:
        raise GeminiError('No model selected')

    url = '{0}/models/{1}:generateContent'.format(
        API_BASE, urllib.parse.quote(model, safe=''))

    generation_config = {'maxOutputTokens': max_output_tokens}
    # See sampling_params_supported(): from Gemini 3.5 on these are deprecated
    # and ignored, and a future generation answers 400 to a request carrying
    # them. The arguments stay in the signature so callers need not know that.
    if sampling_params_supported(model):
        generation_config['temperature'] = temperature
        if top_p is not None:
            generation_config['topP'] = top_p
    if thinking_level:
        generation_config['thinkingConfig'] = {
            'thinkingLevel': thinking_level,
        }
    elif thinking_budget:
        generation_config['thinkingConfig'] = {
            'thinkingBudget': thinking_budget,
        }

    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': generation_config,
        # Subtitles legitimately contain profanity / violence / sexual language;
        # we're only TRANSLATING existing dialogue, so turn the safety filters
        # OFF. Otherwise Gemini returns "no candidates (filtered)" on a chunk and
        # the whole translation aborts. BLOCK_NONE is the most permissive
        # threshold the Gemini API accepts.
        'safetySettings': [
            {'category': 'HARM_CATEGORY_HARASSMENT', 'threshold': 'BLOCK_NONE'},
            {'category': 'HARM_CATEGORY_HATE_SPEECH', 'threshold': 'BLOCK_NONE'},
            {'category': 'HARM_CATEGORY_SEXUALLY_EXPLICIT',
             'threshold': 'BLOCK_NONE'},
            {'category': 'HARM_CATEGORY_DANGEROUS_CONTENT',
             'threshold': 'BLOCK_NONE'},
        ],
    }

    try:
        r = requests.post(url,
                          data=json.dumps(payload),
                          headers={'Content-Type': 'application/json',
                                   'x-goog-api-key': api_key},
                          timeout=timeout)
    except requests.RequestException as e:
        raise GeminiError('Network error: {0}'.format(e))

    if r.status_code == 429:
        raise _classify_429(r)
    if r.status_code in (500, 502, 503, 504):
        raise OverloadError(
            'Gemini overloaded (HTTP {0})'.format(r.status_code))
    if r.status_code in (401, 407):
        # 401 (and 407 proxy-auth) is ALWAYS an authentication failure -- the key
        # is invalid / expired / revoked, or the project has no access. It is
        # never a transient error, so classify it as InvalidKey (terminal, no
        # retries) rather than a generic GeminiError (which retries pointlessly).
        raise InvalidKey('Key rejected (HTTP {0} -- invalid/expired key): {1}'
                         .format(r.status_code, (r.text or '')[:180]))
    if r.status_code in (400, 403):
        _raise_rejected_request(r)
    if r.status_code != 200:
        raise GeminiError('HTTP {0}: {1}'.format(r.status_code, r.text[:200]))

    try:
        data = r.json()
    except ValueError:
        raise GeminiError('Unparseable response from API')

    text = _generated_text(data)

    # Bump the daily-quota counter. Lazy import + try/except so a
    # bug here can never break translation. We only count successful
    # responses (i.e. after all the error branches above), and the
    # tracker itself decides which models to actually record.
    try:
        from . import gemini_quota
        gemini_quota.note_request(model)
    except Exception:
        pass

    return text
