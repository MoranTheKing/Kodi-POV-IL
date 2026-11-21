"""MoranSubs 0.3.109: a trailer reply that numbered its words too low is noticed, asked once more, and else placed by
length over all the words.

The owner, Nov 2026, on FBI's trailer: "it translated, but the timing is so bad against the trailer and when things are
said". The reply's last subtitle named word 375 of 520: every subtitle held words too early, the Hebrew of the whole
trailer sat in its first 175 s of 247 (up to 70 s before its words) and the last 72 s of speech had none. Its own split
was even, so 0.3.105's drift check passed it (0.046). The lengths tell it: a sound reply's Hebrew runs 0.73-0.81 the length
of the English it holds (9 QA replies of 7 trailers, all to the last word), that one 1.09 -- with speech left after it.
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
DATA = json.load(open(ROOT / 'tests/data/trailer_short_fbi.json', encoding='utf-8'))
WORDS = [(float(a), str(w)) for a, w in DATA['words']]
BIGBANG = json.load(open(ROOT / 'tests/data/trailer_drift_bigbang.json', encoding='utf-8'))
BB_WORDS = [(float(a), str(w)) for a, w in BIGBANG['words']]


class Short(unittest.TestCase):
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
        lib.gemini_quota = types.SimpleNamespace(_today_utc=lambda: '2026-11-21')
        self.modules = mock.patch.dict(sys.modules, {'resources': resources, 'resources.lib': lib,
                                                     'resources.lib.kodi_utils': kodi_utils, 'resources.lib.gemini': gemini,
                                                     'resources.lib.gemini_quota': lib.gemini_quota})
        self.modules.start()
        spec = importlib.util.spec_from_file_location('moransubs_short', ROOT / 'service.subtitles.kodipovilai/resources/lib/trailer_subs.py')
        self.ms = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ms)

    def tearDown(self):
        self.modules.stop()

    def test_numbered_too_low_is_noticed_where_the_drift_check_was_not(self):
        info = {}
        self.ms.by_words(DATA['short'], WORDS, info)
        self.assertTrue(info['short'])
        self.assertLess(info['drift'], self.ms.DRIFT, 'its own split is even: the drift check alone passed it')
        self.ms.by_words(DATA['sound'], WORDS, info)
        self.assertFalse(info['short'])

    def test_a_sound_reply_that_leaves_the_end_out_is_not_short(self):
        # (a song at the end, or lines the model judged not worth a subtitle: the Hebrew keeps its usual length for
        # what it holds)
        lines = DATA['sound'].splitlines()
        for name, kept in (('the last tenth', lines[:int(len(lines) * 0.9)]), ('the last quarter', lines[:int(len(lines) * 0.75)])):
            with self.subTest(name):
                info = {}
                self.ms.by_words('\n'.join(kept), WORDS, info)
                self.assertFalse(info['short'])
        bb = BIGBANG['sound'].splitlines()
        for kept in (bb[:-3], bb[:-6]):
            info = {}
            self.ms.by_words('\n'.join(kept), BB_WORDS, info)
            self.assertFalse(info['short'])

    def test_speech_in_another_script_is_never_called_short(self):
        # (the reviewer: the ratio is measured on Latin letters -- a Korean or Russian word counts as one letter, and a
        # sound reply that leaves an end song out would look too long and be stretched over it)
        for script in ('слово', '단어'):
            words = [(i * 0.6, '%s%d' % (script, i)) for i in range(100)]
            rows = [(1 + 17 * k, 17 * (k + 1), 'משפט עברי באורך רגיל לגמרי') for k in range(5)]
            self.assertFalse(self.ms.short(rows, words), script)
        latin = [(i * 0.6, 'go') for i in range(100)]  # 15 words, 9 s after the last subtitle
        long_rows = [(1 + 17 * k, 17 * (k + 1), 'משפט עברי ארוך מאוד שיש בו הרבה יותר אותיות מהאנגלית שהוא מחזיק בו בכלל')
                     for k in range(5)]
        self.assertTrue(self.ms.short(long_rows, latin), 'the same shape in English is caught')

    def test_placed_over_all_the_words_each_line_comes_with_its_own(self):
        before = self.ms.by_words(DATA['short'], WORDS, {})
        after = self.ms.by_words(DATA['short'], WORDS, {}, fix=True)
        self.assertEqual([c[2] for c in before], [c[2] for c in after], 'the Hebrew as the reply wrote it')
        # the last line ("it turns out you're the one who can't handle uncomfortable truths") is said at 244.4 s:
        # published at 171.9, placed now with its words
        self.assertAlmostEqual(before[-1][0], 171.86, places=1)
        self.assertAlmostEqual(after[-1][0], 244.27, places=1)
        # "FBI" (word 13, 5.8 s), "CBS this fall" (7.6 s), "the job doesn't stop" (13.0 s)
        self.assertEqual([round(c[0]) for c in after[1:4]], [6, 8, 13])
        self.assertEqual([round(c[0]) for c in before[1:4]], [4, 4, 5])
        # every line within a few seconds of where the sound reply put the same text, where both have it
        sound = {t: a for a, _b, t in self.ms.by_words(DATA['sound'], WORDS, {})}
        far = [(round(a), round(sound[t])) for a, _b, t in after if t in sound and abs(a - sound[t]) > 8]
        self.assertLessEqual(len(far), 2, far)

    def handle(self, replies):
        asked = []

        def post(url, json=None, headers=None, timeout=None):
            asked.append(1)
            return types.SimpleNamespace(status_code=200, json=lambda text=replies[len(asked) - 1]: {'text': text})
        written = []
        job = {'v': DATA['video'], 'src': 'asr', 'title': 'אף-בי-איי', 'original': 'FBI', 'year': '2018',
               'kind': 'tv', 'lang': 'en', 'words': [list(w) for w in WORDS]}
        cues = self.ms.handle(job, key='k', post=post, write=lambda v, c: written.append(c), now=1000.0)
        return cues, len(asked), written

    def test_a_reply_numbered_too_low_is_asked_once_more(self):
        cues, asked, written = self.handle([DATA['short'], DATA['sound']])
        self.assertEqual(asked, 2)
        self.assertEqual(cues, self.ms.by_words(DATA['sound'], WORDS, {}), 'the second reply')
        self.assertTrue(any('numbered too low' in s for s in self.said), self.said)

    def test_twice_short_the_lengths_place_it_over_all_the_words(self):
        cues, asked, _w = self.handle([DATA['short'], DATA['short']])
        self.assertEqual(asked, 2)
        self.assertEqual(cues, self.ms.by_words(DATA['short'], WORDS, {}, fix=True))
        self.assertGreater(cues[-1][0], 240)
        self.assertTrue(any('placed by the lengths' in s for s in self.said))

    def test_a_sound_reply_is_one_request(self):
        _cues, asked, _w = self.handle([DATA['sound']])
        self.assertEqual(asked, 1)


if __name__ == '__main__':
    unittest.main()
