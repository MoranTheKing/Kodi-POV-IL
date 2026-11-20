"""MoranSubs 0.3.105: a trailer reply that counted its words wrong is noticed, asked once more, and else placed by length.

The owner, Nov 2026, on The Big Bang Theory's trailer: "something was not right with the subtitles" -- then: "the trailer
that had 40 seconds without subtitles although there should have been". Flash-Lite now and then numbers a subtitle's
words wrong (FIRST-LAST|Hebrew): every subtitle after it held the words and the times of the one before ("approaching
absolute zero" at 0:43, "yes" at 1:20, the next lines gone). One QA reply of four did it; its Hebrew was fine.
A blind study (trailer-echo-012) found that asking the model for the English too cost its Hebrew -- so the request stays
as it is: the lengths tell a miscounted reply (a subtitle's Hebrew is about as long as the English it holds), the
trailer is asked once more (the same request), and should that drift too the lengths place the subtitles.
"""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
DATA = json.load(open(ROOT / 'tests/data/trailer_drift_bigbang.json', encoding='utf-8'))
WORDS = [(float(a), str(w)) for a, w in DATA['words']]


class Drift(unittest.TestCase):
    def setUp(self):
        resources = types.ModuleType('resources')
        lib = types.ModuleType('resources.lib')
        self.said = []
        kodi_utils = types.SimpleNamespace(log=lambda *a, **k: self.said.append(a[0] if a else ''), get_setting=lambda k, d='': d,
                                           addon_profile_path=lambda: self.folder)
        lib.kodi_utils = kodi_utils
        resources.lib = lib
        self.folder = tempfile.mkdtemp()
        gemini = types.SimpleNamespace(API_BASE='https://example.invalid', QuotaExceeded=type('QuotaExceeded', (Exception,), {}),
                                       GeminiError=Exception, _safety_settings=lambda m: [], _classify_429=lambda r: Exception(),
                                       _generated_text=lambda d: d['text'])
        lib.gemini = gemini
        lib.gemini_quota = types.SimpleNamespace(_today_utc=lambda: '2026-11-20')
        self.modules = mock.patch.dict(sys.modules, {'resources': resources, 'resources.lib': lib,
                                                     'resources.lib.kodi_utils': kodi_utils, 'resources.lib.gemini': gemini,
                                                     'resources.lib.gemini_quota': lib.gemini_quota})
        self.modules.start()
        spec = importlib.util.spec_from_file_location('moransubs_drift', ROOT / 'service.subtitles.kodipovilai/resources/lib/trailer_subs.py')
        self.ms = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ms)

    def tearDown(self):
        self.modules.stop()

    def test_the_lengths_tell_a_miscounted_reply(self):
        info = {}
        self.ms.by_words(DATA['drifted'], WORDS, info)
        self.assertGreater(info['drift'], self.ms.DRIFT)
        self.ms.by_words(DATA['sound'], WORDS, info)
        self.assertLess(info['drift'], self.ms.DRIFT)
        self.assertEqual(self.ms.drift([(1, 3, 'א'), (4, 6, 'ב')], WORDS), 0.0, 'a short reply says nothing')

    def test_placed_by_the_lengths_each_subtitle_comes_with_its_own_words(self):
        before = self.ms.by_words(DATA['drifted'], WORDS, {})
        after = self.ms.by_words(DATA['drifted'], WORDS, {}, fix=True)
        self.assertEqual(len(before), len(after))
        self.assertEqual([c[2] for c in before], [c[2] for c in after], 'the Hebrew as the reply wrote it')
        # "the solid theory of exchanges ..." is said at 0:30, "their combined IQ ..." at 0:43, "yes" at 0:58
        self.assertEqual([round(c[0], 1) for c in before[1:4]], [42.9, 63.3, 79.9])
        self.assertEqual([round(c[0], 1) for c in after[1:4]], [29.9, 42.9, 58.1])
        # a sound reply is left as it is
        self.assertEqual(self.ms.by_words(DATA['sound'], WORDS, {}, fix=True), self.ms.by_words(DATA['sound'], WORDS, {}))

    def test_a_sound_reply_that_leaves_words_out_keeps_its_timing(self):
        # (the reviewer: counted over all the words, a reply that left a song out looked miscounted, and its subtitles
        # were moved by 8 to 26 s)
        lines = DATA['sound'].splitlines()
        for name, kept in (('every third line left out', [l for n, l in enumerate(lines) if n % 3 != 2]),
                           ('a run of four left out', lines[:6] + lines[10:]),
                           ('the first three left out', lines[3:]), ('the last three left out', lines[:-3])):
            with self.subTest(name):
                text, info = chr(10).join(kept), {}
                plain = self.ms.by_words(text, WORDS, info)
                self.assertLess(info['drift'], self.ms.DRIFT)
                self.assertEqual(self.ms.by_words(text, WORDS, {}, fix=True), plain)
        # a miscounted reply that leaves words out too is still told
        info = {}
        drifted = DATA['drifted'].splitlines()
        self.ms.by_words(chr(10).join(drifted[:12] + drifted[14:]), WORDS, info)
        self.assertGreater(info['drift'], self.ms.DRIFT)

    def test_a_second_reply_that_is_not_hebrew_is_not_chosen(self):
        english = chr(10).join('%s|%s' % (l.split('|')[0], 'hello there friends') for l in DATA['sound'].splitlines())
        cues, asked, _w = self.handle([DATA['drifted'], english])
        self.assertEqual(asked, 2)
        self.assertEqual(cues, self.ms.by_words(DATA['drifted'], WORDS, {}, fix=True), 'the first, placed by the lengths')

    def test_the_day_s_quota_on_the_second_request_is_remembered(self):
        quota = self.ms.__dict__.get('_quota_out')
        marked = []
        calls = []

        def post(url, json=None, headers=None, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                return types.SimpleNamespace(status_code=200, json=lambda: {'text': DATA['drifted']})
            return types.SimpleNamespace(status_code=429, json=lambda: {})
        job = {'v': 'rCj-Fb1OmXg', 'src': 'asr', 'kind': 'tv', 'lang': 'en', 'words': [list(w) for w in WORDS]}
        gemini = sys.modules['resources.lib.gemini']
        with mock.patch.object(self.ms, '_quota_out', lambda: marked.append(1)), \
                mock.patch.object(gemini, '_classify_429', lambda r: gemini.QuotaExceeded()):
            cues = self.ms.handle(job, key='k', post=post, write=lambda v, c: None, now=1000.0)
        self.assertEqual(marked, [1])
        self.assertEqual(cues, self.ms.by_words(DATA['drifted'], WORDS, {}, fix=True))
        self.assertTrue(quota is not None)

    def handle(self, replies):
        asked = []

        def post(url, json=None, headers=None, timeout=None):
            asked.append(1)
            return types.SimpleNamespace(status_code=200, json=lambda text=replies[len(asked) - 1]: {'text': text})
        written = []
        job = {'v': 'rCj-Fb1OmXg', 'src': 'asr', 'title': 'המפץ הגדול', 'original': 'The Big Bang Theory', 'year': '2007',
               'kind': 'tv', 'lang': 'en', 'words': [list(w) for w in WORDS]}
        cues = self.ms.handle(job, key='k', post=post, write=lambda v, c: written.append(c), now=1000.0)
        return cues, len(asked), written

    def test_a_miscounted_reply_is_asked_once_more(self):
        cues, asked, written = self.handle([DATA['drifted'], DATA['sound']])
        self.assertEqual(asked, 2)
        self.assertEqual(cues, self.ms.by_words(DATA['sound'], WORDS, {}), 'the second reply')
        self.assertEqual(written, [cues])
        self.assertTrue(any('counted the words wrong' in s for s in self.said))

    def test_a_sound_reply_is_one_request(self):
        cues, asked, _w = self.handle([DATA['sound']])
        self.assertEqual(asked, 1)

    def test_twice_miscounted_the_lengths_place_it(self):
        cues, asked, _w = self.handle([DATA['drifted'], DATA['drifted']])
        self.assertEqual(asked, 2)
        self.assertEqual(cues, self.ms.by_words(DATA['drifted'], WORDS, {}, fix=True))
        self.assertTrue(any('placed by the lengths' in s for s in self.said))

    def test_the_second_request_failing_still_gives_the_first_placed(self):
        calls = []

        def post(url, json=None, headers=None, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                return types.SimpleNamespace(status_code=200, json=lambda: {'text': DATA['drifted']})
            return types.SimpleNamespace(status_code=400, json=lambda: {})
        job = {'v': 'rCj-Fb1OmXg', 'src': 'asr', 'kind': 'tv', 'lang': 'en', 'words': [list(w) for w in WORDS]}
        cues = self.ms.handle(job, key='k', post=post, write=lambda v, c: None, now=1000.0)
        self.assertEqual(cues, self.ms.by_words(DATA['drifted'], WORDS, {}, fix=True))


if __name__ == '__main__':
    unittest.main()
