# Google Generative Language API client. Just the bits we need:
# generateContent for translation, ListModels for the connection
# test. Bring your own API key.

import json
import urllib.parse

try:
    import requests
except ImportError:
    requests = None

API_BASE = 'https://generativelanguage.googleapis.com/v1beta'

REQUEST_TIMEOUT = 90


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


def test_key(api_key, model='gemini-3.1-flash-lite'):
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
    payload = {
        'contents': [{'parts': [
            {'text': prompt},
            {'inline_data': {
                'mime_type': mime,
                'data': _b64.b64encode(media_bytes).decode('ascii'),
            }},
        ]}],
        'generationConfig': {
            'temperature': temperature,
            'maxOutputTokens': max_output_tokens,
        },
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
    if r.status_code in (400, 403):
        snippet = r.text[:300] if r.text else ''
        if 'API key' in snippet or 'API_KEY' in snippet:
            raise InvalidKey('Key rejected: {0}'.format(snippet))
        raise GeminiError('Request rejected: {0}'.format(snippet))
    if r.status_code != 200:
        raise GeminiError('HTTP {0}: {1}'.format(r.status_code, r.text[:200]))
    try:
        data = r.json()
        parts = data['candidates'][0]['content']['parts']
        return ''.join(p.get('text', '') for p in parts)
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise GeminiError('Bad response shape: {0}'.format(e))


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

    generation_config = {
        'temperature': temperature,
        'maxOutputTokens': max_output_tokens,
    }
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
    if r.status_code in (400, 403):
        # Distinguish key-related vs content-related rejection by
        # looking at the body when we can.
        snippet = r.text[:300] if r.text else ''
        if 'API key' in snippet or 'API_KEY' in snippet:
            raise InvalidKey('Key rejected: {0}'.format(snippet))
        raise GeminiError('Request rejected: {0}'.format(snippet))
    if r.status_code != 200:
        raise GeminiError('HTTP {0}: {1}'.format(r.status_code, r.text[:200]))

    try:
        data = r.json()
    except ValueError:
        raise GeminiError('Unparseable response from API')

    # Prompt-level block (blockReason: PROHIBITED_CONTENT / SAFETY / ...). This
    # rejects the whole PROMPT before any generation and is NOT overridable by
    # safetySettings. Surface as FilteredResponse so the caller can retry the
    # chunk WITHOUT the Arabic gender block (a common trigger) / bisect, rather
    # than aborting the whole translation.
    pf = data.get('promptFeedback') or {}
    if pf.get('blockReason'):
        raise FilteredResponse(
            'prompt blocked: {0}'.format(pf.get('blockReason')))

    cands = data.get('candidates') or []
    if not cands:
        # Often means the prompt triggered a safety filter.
        raise FilteredResponse(
            'No candidates in response (possibly filtered)')

    parts = (cands[0].get('content') or {}).get('parts') or []
    chunks = [p.get('text', '') for p in parts if isinstance(p, dict)]
    text = ''.join(chunks).strip()
    if not text:
        # Empty content with a SAFETY/PROHIBITED finishReason -> treat as a
        # block (retry without Arabic / bisect), not a hard error.
        fr = (cands[0].get('finishReason') or '').upper()
        if fr in ('SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST', 'OTHER', ''):
            raise FilteredResponse('empty/blocked content (finish={0})'.format(fr))
        raise GeminiError('Empty text in response')

    # If the model hit its output cap, the last entry in the
    # returned SRT is almost always cut off and the chunk has a
    # silent gap. Surface this so the caller can bisect and retry
    # with a smaller request, rather than silently saving an
    # incomplete translation. Flash Lite caps at 8192 output
    # tokens, which Hebrew SRT can blow through around the
    # 150-200 entry mark.
    finish_reason = (cands[0].get('finishReason') or '').upper()
    if finish_reason in ('MAX_TOKENS', 'LENGTH'):
        raise TruncatedResponse(
            'Gemini hit output-token cap (finishReason={0})'.format(
                finish_reason),
            partial_text=text,
        )

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
