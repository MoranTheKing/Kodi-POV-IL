"""Offline contract tests for Gemini response-envelope classification."""
import importlib.util
import json
import os
import sys
import types


ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
MODULE = os.path.join(
    ROOT, 'addons', 'service.subtitles.kodipovilai',
    'resources', 'lib', 'gemini.py')


class Response(object):
    def __init__(self, status=200, payload=None, text=None):
        self.status_code = status
        self.payload = payload
        self._text = text

    @property
    def text(self):
        if self._text is not None:
            return self._text
        return json.dumps(self.payload or {})

    def json(self):
        if self.payload is None:
            raise ValueError('not json')
        return self.payload


def load(response):
    for name in list(sys.modules):
        if name in ('requests', 'gemini_response_test'):
            sys.modules.pop(name, None)
    requests = types.ModuleType('requests')
    requests.RequestException = Exception
    requests.post = lambda *args, **kwargs: response
    requests.get = requests.post
    sys.modules['requests'] = requests
    spec = importlib.util.spec_from_file_location('gemini_response_test', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidate(reason='STOP', parts=None):
    return {'candidates': [{
        'finishReason': reason,
        'content': {'parts': parts or [{'text': 'visible'}]},
    }]}


def expect(exc_type, callback):
    try:
        callback()
    except exc_type as exc:
        return exc
    except Exception as exc:
        raise AssertionError('wrong exception: %r' % (exc,))
    raise AssertionError('expected %s' % exc_type.__name__)


def text_call(module):
    return module.generate('key', 'gemini-3.5-flash-lite', 'prompt')


def media_call(module):
    return module.generate_media(
        'key', 'gemini-3.5-flash-lite', 'prompt', b'audio', 'audio/aac')


# A filtered finish reason wins even when Gemini includes usable-looking text.
for reason in ('SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST'):
    mod = load(Response(payload=candidate(reason, [{'text': 'partial'}])))
    exc = expect(mod.FilteredResponse, lambda: text_call(mod))
    assert exc.partial_text == 'partial', (reason, exc.partial_text)

# Prompt-level block and HTTP rejection both enter the recoverable path.
mod = load(Response(payload={
    'promptFeedback': {'blockReason': 'PROHIBITED_CONTENT'},
    'candidates': [],
}))
expect(mod.FilteredResponse, lambda: text_call(mod))
mod = load(Response(
    status=400,
    payload={'error': {'message': 'Request blocked: PROHIBITED_CONTENT'}},
))
expect(mod.FilteredResponse, lambda: text_call(mod))
mod = load(Response(
    status=403,
    payload={'error': {'message': 'content was blocked for SAFETY'}},
))
expect(mod.FilteredResponse, lambda: media_call(mod))

# Authentication remains terminal and is never mistaken for subtitle safety.
mod = load(Response(
    status=400,
    payload={'error': {'message': 'API key not valid'}},
))
expect(mod.InvalidKey, lambda: text_call(mod))
mod = load(Response(
    status=400,
    payload={'error': {'message': 'Invalid safetySettings threshold value'}},
))
try:
    text_call(mod)
except Exception as exc:
    assert type(exc) is mod.GeminiError, type(exc)
else:
    raise AssertionError('invalid safety configuration must remain an error')
for message in (
        'Invalid content: safetySettings threshold is unsupported',
        'Request blocked by VPC Service Controls for generateContent',
        'Invalid value for safetySettings: BLOCKLIST is not a valid enum'):
    mod = load(Response(status=400, payload={'error': {'message': message}}))
    try:
        text_call(mod)
    except Exception as exc:
        assert type(exc) is mod.GeminiError, (message, type(exc))
    else:
        raise AssertionError('configuration/access error was accepted: ' + message)

# A structured block reason is authoritative even when the prose is unusual.
mod = load(Response(status=400, payload={
    'error': {
        'message': 'generation refused',
        'details': [{'blockReason': 'PROHIBITED_CONTENT'}],
    },
}))
expect(mod.FilteredResponse, lambda: text_call(mod))

# Thinking parts are private model work; only visible parts may be returned.
envelope = candidate('STOP', [
    {'thought': True, 'text': 'internal reasoning'},
    {'text': 'visible'},
])
mod = load(Response(payload=envelope))
assert text_call(mod) == 'visible'
mod = load(Response(payload=envelope))
assert media_call(mod) == 'visible'

# Null/non-string parts cannot pre-empt the filtered finish reason or leak out.
mod = load(Response(payload=candidate(
    'PROHIBITED_CONTENT', [{'text': None}, {'text': 7}])))
expect(mod.FilteredResponse, lambda: text_call(mod))
mod = load(Response(payload=candidate(
    'STOP', [{'text': None}, {'text': 7}, {'text': 'visible'}])))
assert text_call(mod) == 'visible'

# Token truncation preserves visible partial text for the production bisection.
mod = load(Response(payload=candidate('MAX_TOKENS', [{'text': 'partial'}])))
exc = expect(mod.TruncatedResponse, lambda: text_call(mod))
assert exc.partial_text == 'partial'

print('PASS: Gemini blocks, thoughts, auth and truncation are classified offline')
