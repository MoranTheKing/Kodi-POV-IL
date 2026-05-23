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
    """Daily request limit hit (HTTP 429). Caller may want to
    suggest waiting until UTC midnight."""


class OverloadError(GeminiError):
    """Service-side overload (HTTP 503 / 500). Retryable with
    longer backoff -- Google explicitly tells callers to wait at
    least a few seconds before retrying these."""


class InvalidKey(GeminiError):
    """Key is missing / revoked / malformed."""


def test_key(api_key, model='gemini-3.1-flash-lite'):
    """Cheap sanity check: list the user's available models and
    confirm the chosen one is in the set. Returns the model id we
    matched (so the caller can show "Connected: <model>")."""
    if not requests:
        raise GeminiError('python-requests is not installed')
    if not api_key:
        raise InvalidKey('No API key provided')

    url = '{0}/models?key={1}'.format(API_BASE, urllib.parse.quote(api_key, safe=''))
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        raise GeminiError('Network error: {0}'.format(e))

    if r.status_code == 400 or r.status_code == 403:
        raise InvalidKey('Key rejected by Gemini ({0})'.format(r.status_code))
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


def generate(api_key, model, prompt, temperature=0.2,
             max_output_tokens=16384):
    """One-shot text generation. Returns the model's text response.

    Raises QuotaExceeded on 429, InvalidKey on 400/403, GeminiError
    on anything else."""
    if not requests:
        raise GeminiError('python-requests is not installed')
    if not api_key:
        raise InvalidKey('No API key provided')
    if not model:
        raise GeminiError('No model selected')

    url = '{0}/models/{1}:generateContent?key={2}'.format(
        API_BASE, urllib.parse.quote(model, safe=''),
        urllib.parse.quote(api_key, safe=''))

    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': temperature,
            'maxOutputTokens': max_output_tokens,
        }
    }

    try:
        r = requests.post(url,
                          data=json.dumps(payload),
                          headers={'Content-Type': 'application/json'},
                          timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        raise GeminiError('Network error: {0}'.format(e))

    if r.status_code == 429:
        raise QuotaExceeded('Daily quota exceeded')
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

    cands = data.get('candidates') or []
    if not cands:
        # Often means the prompt triggered a safety filter.
        raise GeminiError('No candidates in response (possibly filtered)')

    parts = (cands[0].get('content') or {}).get('parts') or []
    chunks = [p.get('text', '') for p in parts if isinstance(p, dict)]
    text = ''.join(chunks).strip()
    if not text:
        raise GeminiError('Empty text in response')
    return text
