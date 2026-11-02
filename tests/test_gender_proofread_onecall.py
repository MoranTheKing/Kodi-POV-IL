"""One counted request per gender proofread (0.3.65).

Asked whether a proofread ever spends more than one request of 3.7/3.8: a
model that took the request and sent back nothing usable (cut off, blocked,
no reply in time) was followed by the next model -- a second counted request
for one proofread. Now the proofread stops there and that title waits a week.
A model that refused it unread (overloaded, its per-minute limit) is still
followed by the next. A fresh translation's proofread holds the in-progress
marker an opened one does, so an open in its minutes does not ask again.
"""
import importlib.util
import itertools
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ADDON = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai'
LIB = ADDON / 'resources' / 'lib'


def _gemini():
    spec = importlib.util.spec_from_file_location('gem_onecall', LIB / 'gemini.py')
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {'resources.lib.kodi_utils': types.SimpleNamespace(
            log=lambda *a, **k: None)}):
        spec.loader.exec_module(module)
    return module


def _load():
    stubs = dict((n, mock.MagicMock(name=n)) for n in
                 ('xbmc', 'xbmcaddon', 'xbmcgui', 'xbmcvfs', 'xbmcplugin'))
    with mock.patch.dict(sys.modules, stubs):
        sys.path.insert(0, str(ADDON))
        try:
            from resources.lib import gender_proofread, translate  # noqa: F401
        finally:
            sys.path.remove(str(ADDON))
        mods = dict((k, v) for k, v in sys.modules.items()
                    if k in stubs or k == 'resources' or k.startswith('resources.'))
    return translate, mods


translate, MODS = _load()


class Reply(object):
    def __init__(self, status, body):
        self.status_code = status
        self.text = json.dumps(body)

    def json(self):
        return json.loads(self.text)


class ReadTimeout(Exception):
    pass


class ChunkedEncodingError(Exception):
    pass


def block(n, text):
    return '%d\n00:00:%02d,000 --> 00:00:%02d,900\n%s' % (n, n * 3, n * 3 + 1, text)


def srt_text(*texts):
    return '\n\n'.join(block(i, t) for i, t in enumerate(texts, 1)) + '\n'


HE = srt_text('אתה בא?', 'כן, אני מצטער.')
EN = srt_text('Are you coming?', "Yes, I'm sorry.")


class AnsweredErrors(unittest.TestCase):
    """gemini.generate says which failures came after the model took it."""

    def send(self, outcome):
        g = _gemini()

        def post(url, data=None, headers=None, timeout=None):
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        g.requests = types.SimpleNamespace(
            post=post, RequestException=Exception, ReadTimeout=ReadTimeout,
            exceptions=types.SimpleNamespace(ChunkedEncodingError=ChunkedEncodingError))
        with self.assertRaises(g.GeminiError) as caught:
            g.generate(api_key='k', model='m', prompt='p')
        return caught.exception

    def test_a_reply_of_no_use_was_answered(self):
        for body in ({'candidates': [{'finishReason': 'SAFETY'}]},
                     {'promptFeedback': {'blockReason': 'OTHER'}},
                     {'candidates': [{'content': {'parts': [{'text': 'כן'}]},
                                      'finishReason': 'MAX_TOKENS'}]},
                     {'candidates': [{'content': {'parts': []}, 'finishReason': 'STOP'}]}):
            self.assertTrue(self.send(Reply(200, body)).answered, body)
        self.assertTrue(self.send(ReadTimeout('read')).answered)
        self.assertTrue(self.send(ChunkedEncodingError('cut mid-read')).answered)
        self.assertTrue(self.send(Reply(504, {})).answered)       # past its deadline

    def test_one_refused_unread_was_not(self):
        for outcome in (Reply(503, {}), Reply(500, {}), Reply(429, {'error': {}}), Reply(404, {}),
                        Reply(400, {'error': {'message': 'bad'}}), ConnectionError('dns')):
            self.assertFalse(self.send(outcome).answered, outcome)


class Request(unittest.TestCase):
    """_run_gender_proofread asks the next model only after a refusal."""

    def setUp(self):
        self.mods = mock.patch.dict(sys.modules, MODS)
        self.mods.start()
        self.addCleanup(self.mods.stop)
        gp = MODS['resources.lib.gender_proofread']
        for target, value in (('exhausted_today', lambda m, s: False),
                              ('note_exhausted', lambda m, s: None)):
            p = mock.patch.object(gp, target, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(translate.kodi_utils, 'log', lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)

    def run_it(self, outcomes, stopped=lambda: False):
        asked = []
        gem = translate.gemini

        def generate(api_key, model, prompt, **kw):
            asked.append(model)
            out = outcomes.pop(0)
            if isinstance(out, Exception):
                raise out
            return out
        clock = itertools.count(0, 7)
        with mock.patch.object(gem, 'generate', generate), \
                mock.patch.object(translate.time, 'monotonic', lambda: next(clock)), \
                mock.patch.object(translate.time, 'sleep', lambda s: None):
            blocks, report = translate._run_gender_proofread(
                translate.srt.parse_blocks(HE), EN, 'k', 'gemini-3.5-flash-lite', [],
                stopped)
        return asked, report

    def answered(self, exc):
        exc.answered = True
        return exc

    def test_a_reply_of_no_use_ends_it_at_one_request(self):
        gem = translate.gemini
        for exc in (gem.FilteredResponse('blocked'), gem.TruncatedResponse('cut'),
                    gem.GeminiError('Network error: read timed out')):
            asked, report = self.run_it([self.answered(exc), '1|את באה?'])
            self.assertEqual(asked, ['gemini-3.7-flash'])
            self.assertEqual((report['model'], report['spent'], report['asked']),
                             ('', 'gemini-3.7-flash', True))

    def test_past_its_deadline_is_one_request_too(self):
        gem = translate.gemini
        asked, report = self.run_it([self.answered(gem.OverloadError('504')), '1|את באה?'])
        self.assertEqual(asked, ['gemini-3.7-flash'])
        self.assertEqual(report['spent'], 'gemini-3.7-flash')

    def test_a_refusal_unread_still_goes_on(self):
        gem = translate.gemini
        asked, report = self.run_it([gem.OverloadError('503'), gem.OverloadError('503'),
                                     gem.GeminiError('HTTP 404: no such model'),
                                     '1|את באה?'])
        self.assertEqual(asked, ['gemini-3.7-flash', 'gemini-3.7-flash',
                                 'gemini-3.8-flash', 'gemini-3.6-flash'])
        self.assertEqual(report['model'], 'gemini-3.6-flash')
        self.assertNotIn('spent', report)
        self.assertEqual(report['why'], '')

    def test_why_no_model_answered(self):
        # 0.3.67: the telemetry says why, from what already happened
        gem = translate.gemini
        busy = [gem.OverloadError('503')] * 6
        self.assertEqual(self.run_it(list(busy))[1]['why'], 'busy')
        quota = [gem.QuotaExceeded('day')] * 3
        self.assertEqual(self.run_it(list(quota))[1]['why'], 'quota')
        self.assertEqual(self.run_it([self.answered(gem.FilteredResponse('x'))])[1]['why'],
                         'unusable')
        self.assertEqual(self.run_it([gem.InvalidKey('bad key')])[1]['why'], 'key')
        mixed = [gem.QuotaExceeded('day'), gem.OverloadError('503'), gem.OverloadError('503'),
                 gem.GeminiError('HTTP 404')]
        self.assertEqual(self.run_it(mixed)[1]['why'], 'busy')
        # the viewer left after every model had refused: still 'busy'
        # (review, 0.3.67); a stop that cut it short: 'stopped'
        busy_then_left = [gem.OverloadError('503')] * 6
        # stopped from the moment every refusal is in (the list consumed)
        self.assertEqual(self.run_it(busy_then_left,
                                     stopped=lambda: not busy_then_left)[1]['why'], 'busy')
        self.assertEqual(busy_then_left, [])
        calls = []

        def stop_after_first():
            calls.append(1)
            return len(calls) > 1
        self.assertEqual(self.run_it([gem.OverloadError('503')] * 6,
                                     stopped=stop_after_first)[1]['why'], 'stopped')
        why = translate._gp_why
        self.assertEqual(why({'model': 'm'}, ['quota'], True), '')
        self.assertEqual(why({}, ['busy'], True), 'stopped')
        self.assertEqual(why({}, [], False), 'error')
        self.assertEqual(why({}, ['quota', 'time'], False), 'time')

    def test_the_event_carries_it(self):
        src = (LIB / 'translate.py').read_text(encoding='utf-8').replace('\r\n', '\n')
        emit = src[src.index('    def _gp_event_note(ok, note):'):src.index('    if whole_subtitle_request:')]
        self.assertIn("'gp_note': _gp_event_note(ok, note),", emit)
        for word in ("return 'off'", "_gp_report.get('why')"):
            self.assertIn(word, emit)
        # 0.3.69: 'deferred' only when the job can ask a model (Frasier,
        # 2 Nov: 'deferred' on a device that never proofread)
        self.assertIn("return 'later' if _gp_models_left() else 'quota'", emit)


class Markers(unittest.TestCase):

    def setUp(self):
        self.mods = mock.patch.dict(sys.modules, MODS)
        self.mods.start()
        self.addCleanup(self.mods.stop)
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, 'tt1.he.srt')
        open(self.path, 'w').close()

    def settle(self, report, stopped=False):
        translate._gp_try_mark(self.path, True)
        translate._gp_settle((self.path,), report, lambda: stopped)
        return os.path.isfile(self.path + '.gp.try')

    def test_after_a_proofread(self):
        self.assertFalse(self.settle({'model': 'gemini-3.7-flash', 'asked': True}))
        self.assertFalse(self.settle({'model': '', 'asked': False}))     # all out of quota
        self.assertFalse(self.settle({'model': '', 'asked': True}, stopped=True))
        self.assertTrue(self.settle({'model': '', 'asked': True}))       # overloaded
        held = os.path.getmtime(self.path + '.gp.try')
        self.assertLess(abs(held - time.time()), 60)                    # six hours
        self.assertTrue(self.settle({'model': '', 'asked': True, 'spent': 'gemini-3.7-flash'}))
        held = os.path.getmtime(self.path + '.gp.try')
        week = translate._GP_SPENT_SECS - translate._GP_RETRY_SECS
        self.assertLess(abs(held - time.time() - week), 60)
        self.assertTrue(translate._gp_trying(self.path))
        # spent, and the viewer moved on while it was asked: still spent
        # (review of 0.3.65 -- the next open would ask a second time)
        self.assertTrue(self.settle({'model': '', 'asked': True, 'spent': 'gemini-3.7-flash'},
                                    stopped=True))
        held = os.path.getmtime(self.path + '.gp.try')
        self.assertLess(abs(held - time.time() - week), 60)

    def test_the_fresh_path_holds_it_as_an_opened_one_does(self):
        src = (LIB / 'translate.py').read_text(encoding='utf-8').replace('\r\n', '\n')
        run = src[src.index("    if progressive_cb is not None and kodi_utils.get_bool('gender_proofread', True):"):]
        run = run[:run.index('    _emit(True)\n')]
        mark = run.index('            _gp_try_mark(_slot, True)')
        ask = run.index('_proofed = _proofread_gender(_proof_blocks)')
        settle = run.index('_gp_settle(_gp_slots, _gp_report, _proofread_stopper(')
        self.assertLess(mark, ask)
        self.assertLess(ask, settle)
        opened = src[src.index('def _proofread_opened('):src.index('def _pool_gp_base(')]
        self.assertIn('_gp_try_mark(marker, True)', opened)
        self.assertIn('_gp_settle((marker,), report, stopped)', opened)


if __name__ == '__main__':
    unittest.main()
