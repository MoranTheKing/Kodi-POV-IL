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

    def test_a_failed_connection_is_told_from_a_refusal(self):
        # 0.3.75: the proofread queue keeps a translation whose request never
        # reached Google (a box just awake, no network yet)
        self.assertTrue(getattr(self.send(ConnectionError('dns')), 'transport', False))
        for outcome in (Reply(503, {}), Reply(404, {})):
            self.assertFalse(getattr(self.send(outcome), 'transport', False), outcome)


class Request(unittest.TestCase):
    """_run_gender_proofread asks the next model only after a refusal."""
    # The mechanics of a chain (0.3.58-0.3.74 shipped three models; 0.3.75
    # asks 3.7 alone: OneModel below).
    CHAIN = ('gemini-3.7-flash', 'gemini-3.8-flash', 'gemini-3.6-flash')

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
        if self.CHAIN:
            p = mock.patch.object(gp, 'MODELS', self.CHAIN)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(translate.kodi_utils, 'log', lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)

    def run_it(self, outcomes, stopped=lambda: False, background=False, step=7, rounds=True):
        asked = []
        gem = translate.gemini
        self.slept = []

        def generate(api_key, model, prompt, **kw):
            asked.append(model)
            out = outcomes.pop(0) if outcomes else gem.OverloadError('503')
            if isinstance(out, Exception):
                raise out
            return out
        clock = itertools.count(0, step)
        with mock.patch.object(gem, 'generate', generate), \
                mock.patch.object(translate.time, 'monotonic', lambda: next(clock)), \
                mock.patch.object(translate.time, 'sleep', self.slept.append):
            blocks, report = translate._run_gender_proofread(
                translate.srt.parse_blocks(HE), EN, 'k', 'gemini-3.5-flash-lite', [],
                stopped, background=background, rounds=rounds)
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

    def test_a_background_proofread_asks_a_busy_model_again(self):
        # 0.3.70: the job proofread_later starts (nothing waits for it) asks
        # again when every model was busy -- the field's automatic
        # translations on play were never proofread after a 503 round.
        # 0.3.71: a 503 counts toward the day's quota, so every model gets
        # one request, then one model a round, in turn from the last
        gem = translate.gemini
        M = ['gemini-3.7-flash', 'gemini-3.8-flash', 'gemini-3.6-flash']
        busy = gem.OverloadError('503')
        asked, report = self.run_it([busy] * 3 + ['1|את באה?'], background=True)
        self.assertEqual(asked, M + ['gemini-3.6-flash'])
        self.assertEqual((report['model'], report['rounds'], report['why']),
                         ('gemini-3.6-flash', 2, ''))
        # busy all along: three more rounds, one model each -- six requests,
        # as one round of two each before 0.3.70
        asked, report = self.run_it([], background=True, step=1)
        self.assertEqual(asked, M + ['gemini-3.6-flash', 'gemini-3.8-flash', 'gemini-3.7-flash'])
        self.assertEqual((report['rounds'], report['why']), (4, 'busy'))
        # with the viewer waiting (a live preview): one round of two each
        asked, report = self.run_it([busy] * 6 + ['1|את באה?'])
        self.assertEqual(len(asked), 6)
        self.assertEqual((report['model'], report['rounds'], report['why']), ('', 1, 'busy'))

    def test_what_ends_the_rounds(self):
        # review of 0.3.70: a model refused unread (a retired id) beside busy
        # ones does not end them; a reply of no use or a refused key does; a
        # day's quota everywhere at once is no round
        gem = translate.gemini
        busy = gem.OverloadError('503')
        asked, report = self.run_it([busy, gem.GeminiError('HTTP 404: no such model'), busy,
                                     '1|את באה?'], background=True)
        self.assertEqual((report['model'], report['rounds']), ('gemini-3.6-flash', 2))
        for first, why in ((self.answered(gem.FilteredResponse('x')), 'unusable'),
                           (gem.InvalidKey('bad key'), 'key')):
            asked, report = self.run_it([busy, first, '1|את באה?'], background=True)
            self.assertEqual((len(asked), report['rounds'], report['why']), (2, 1, why))
        asked, report = self.run_it([gem.QuotaExceeded('day')] * 3, background=True)
        self.assertEqual((len(asked), report['rounds'], report['why']), (3, 1, 'quota'))
        # a later round's model out of quota: the next round asks another
        asked, report = self.run_it([busy] * 3 + [gem.QuotaExceeded('day'), '1|את באה?'],
                                    background=True)
        self.assertEqual(asked[3:], ['gemini-3.6-flash', 'gemini-3.8-flash'])
        self.assertEqual((report['model'], report['rounds']), ('gemini-3.8-flash', 3))

    def test_a_model_out_of_quota_is_not_asked_in_a_round(self):
        gem = translate.gemini
        gp = MODS['resources.lib.gender_proofread']
        with mock.patch.object(gp, 'exhausted_today', lambda m, s: m == 'gemini-3.6-flash'):
            asked, report = self.run_it([], background=True, step=1)
        self.assertEqual(asked, ['gemini-3.7-flash', 'gemini-3.8-flash',
                                 'gemini-3.8-flash', 'gemini-3.7-flash', 'gemini-3.8-flash'])
        self.assertEqual(report['rounds'], 4)
        with mock.patch.object(gp, 'exhausted_today', lambda m, s: True):
            asked, report = self.run_it([], background=True)
        self.assertEqual((asked, report['rounds'], report['why']), ([], 1, 'quota'))

    def test_the_rounds_end_within_the_job_budget_or_when_the_viewer_leaves(self):
        gem = translate.gemini
        self.assertEqual((translate._GP_BUSY_WAIT, translate._GP_BUSY_WAIT_MAX,
                          translate._GP_BUSY_ROUNDS, translate._GP_JOB_BUDGET),
                         (120, 480, 3, 1800))
        # the rounds wait 2, 4 and 8 minutes; none starts past the job's
        # budget (here 200 s: the 2-minute round fits, the 4-minute one not)
        with mock.patch.object(translate, '_GP_JOB_BUDGET', 200):
            asked, report = self.run_it([], background=True, step=1)
        self.assertEqual((report['rounds'], len(asked)), (2, 4))
        # the viewer moved on during a wait: no further round
        logs = []
        with mock.patch.object(translate.kodi_utils, 'log', lambda m, **k: logs.append(m)):
            asked, report = self.run_it(
                [], background=True,
                stopped=lambda: any('again in' in m for m in logs))
        self.assertEqual((report['rounds'], len(asked)), (1, 3))

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
        run = src[src.index("    if (progressive_cb is not None and _gp_ref != 'he'\n"):]
        run = run[:run.index('    _emit(True)\n')]
        mark = run.index('            _gp_try_mark(_slot, True)')
        ask = run.index('_proofed = _proofread_gender(_proof_blocks)')
        settle = run.index('_gp_settle(_gp_slots, _gp_report, _proofread_stopper(')
        self.assertLess(mark, ask)
        self.assertLess(ask, settle)
        opened = src[src.index('def _proofread_opened('):src.index('def _pool_gp_base(')]
        self.assertIn('_gp_try_mark(marker, True)', opened)
        self.assertIn('_gp_settle((marker,), report, stopped)', opened)


class OneModel(unittest.TestCase):
    """0.3.75: the proofread asks gemini-3.7-flash alone (blind studies 004 and
    005, 11 Nov 2026: without a Hebrew reference it fixed 27 lines and broke
    none, where 3.6 had broken 6)."""
    CHAIN = None
    setUp = Request.setUp
    run_it = Request.run_it

    def test_the_shipped_chain_is_3_7_alone(self):
        self.assertEqual(MODS['resources.lib.gender_proofread'].MODELS, ('gemini-3.7-flash',))

    def test_with_the_viewer_waiting_3_7_twice_and_no_other_model(self):
        busy = translate.gemini.OverloadError('503')
        asked, report = self.run_it([busy, busy, '1|את באה?'])
        self.assertEqual(asked, ['gemini-3.7-flash'] * 2)
        self.assertEqual((report['model'], report['why']), ('', 'busy'))
        asked, report = self.run_it([busy, '1|את באה?'])
        self.assertEqual((asked, report['model']), (['gemini-3.7-flash'] * 2, 'gemini-3.7-flash'))

    def test_in_the_background_four_requests_at_most(self):
        asked, report = self.run_it([], background=True, step=1)
        self.assertEqual(asked, ['gemini-3.7-flash'] * 4)
        self.assertEqual((report['rounds'], report['why']), (4, 'busy'))

    def test_a_failed_connection_says_so(self):
        gem = translate.gemini
        err = gem.GeminiError('Network error: dns')
        err.transport = True
        asked, report = self.run_it([err], background=True, rounds=False)
        self.assertEqual((report['why'], report['net']), ('error', True))
        asked, report = self.run_it([gem.GeminiError('HTTP 404: no such model')],
                                    background=True, rounds=False)
        self.assertEqual((report['why'], report['net']), ('error', False))

    def test_the_queue_asks_once(self):
        # gp_later's ask again: one request, no rounds, no second try
        asked, report = self.run_it([], background=True, step=1, rounds=False)
        self.assertEqual(asked, ['gemini-3.7-flash'])
        self.assertEqual((report['rounds'], report['why'], report['asked']), (1, 'busy', True))
        asked, report = self.run_it(['1|את באה?'], background=True, rounds=False)
        self.assertEqual((asked, report['model']), (['gemini-3.7-flash'], 'gemini-3.7-flash'))


if __name__ == '__main__':
    unittest.main()
