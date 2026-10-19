"""A model that refuses the BLOCK_NONE safety threshold is resent once with
OFF and remembered (NG Bundle G PR-4); every other rejection is unchanged."""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

LIB = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai' / 'resources' / 'lib'


def _load():
    spec = importlib.util.spec_from_file_location('gem_safety', LIB / 'gemini.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'resources.lib.kodi_utils': types.SimpleNamespace(
            log=lambda *a, **k: None)}):
        spec.loader.exec_module(module)
    return module


class Reply(object):
    def __init__(self, status, body):
        self.status_code = status
        self.text = json.dumps(body)

    def json(self):
        return json.loads(self.text)


OK = Reply(200, {'candidates': [{'content': {'parts': [{'text': 'שלום'}]}, 'finishReason': 'STOP'}]})
THRESHOLD = Reply(400, {'error': {'code': 400, 'status': 'INVALID_ARGUMENT', 'message':
                                  "Invalid value at 'safety_settings[0].threshold', \"BLOCK_NONE\""}})
KEY = Reply(400, {'error': {'code': 400, 'message': 'API key not valid. Please pass a valid API key.'}})


class SafetyFallback(unittest.TestCase):
    def run_with(self, replies):
        g = _load()
        sent = []

        def post(url, data=None, headers=None, timeout=None):
            sent.append(json.loads(data)['safetySettings'][0]['threshold'])
            return replies.pop(0)
        g.requests = types.SimpleNamespace(post=post, RequestException=Exception)
        return g, sent

    def test_a_refused_threshold_is_resent_once_with_off_and_remembered(self):
        g, sent = self.run_with([THRESHOLD, OK, OK])
        self.assertEqual(g.generate(api_key='k', model='m', prompt='p'), 'שלום')
        self.assertEqual(g.generate(api_key='k', model='m', prompt='p'), 'שלום')
        self.assertEqual(sent, ['BLOCK_NONE', 'OFF', 'OFF'])

    def test_off_refused_too_is_not_resent_again(self):
        g, sent = self.run_with([THRESHOLD, THRESHOLD])
        with self.assertRaises(g.GeminiError):
            g.generate(api_key='k', model='m', prompt='p')
        self.assertEqual(sent, ['BLOCK_NONE', 'OFF'])

    def test_other_rejections_are_unchanged(self):
        g, sent = self.run_with([KEY])
        with self.assertRaises(g.InvalidKey):
            g.generate(api_key='k', model='m', prompt='p')
        self.assertEqual(sent, ['BLOCK_NONE'])

    def test_other_models_keep_block_none(self):
        g, sent = self.run_with([THRESHOLD, OK, OK])
        g.generate(api_key='k', model='m', prompt='p')
        g.generate(api_key='k', model='other', prompt='p')
        self.assertEqual(sent, ['BLOCK_NONE', 'OFF', 'BLOCK_NONE'])


if __name__ == '__main__':
    unittest.main()
