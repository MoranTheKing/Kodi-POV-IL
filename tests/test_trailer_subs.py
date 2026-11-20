"""Hebrew subtitles on the home's trailers (Wizard 0.5.31, MoranSubs 0.3.99, the trailer-subs workflow).

The owner, Nov 2026, after a blind study (Gemini 3.1 Flash Lite against Google Translate on 13 trailers, 13-0): "go" --
the viewers' own FREE Gemini quota only, a trailer translated once for everyone, read from GitHub Pages so the pool's
Worker never nears Cloudflare's free plan, nothing on the trailer but the trailer and its subtitles. QA Kodi, on the
screen: a trailer with no captions translated by listening in 3.3 s (one request), shown once it had the screen,
hidden when the home came back; captions read for a trailer with a person's track (25 lines) and an automatic one
(286 words).
"""
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VTT_ASR = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.000 align:start position:0%
winter<00:00:01.500><c> is</c><00:00:01.900><c> coming</c>

00:00:03.000 --> 00:00:03.010 align:start position:0%
winter is coming

00:00:03.010 --> 00:00:05.000 align:start position:0%
winter is coming
my<00:00:03.400><c> lord</c>
"""

VTT_MANUAL = """WEBVTT

00:00:01.000 --> 00:00:02.500
Winter is coming.

00:00:03.000 --> 00:00:04.000
[Music]
"""


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.ts = load('plugin.program.kodipovilwizard/resources/libs/trailer_subs.py', 'povil_wizard_trailer_subs')

    def test_the_path_is_the_export_s(self):
        exporter = load('tools/trailer_subs_export.py', 'povil_trailer_subs_export')
        for video in ('aBc_dEf-123', 'ABC_DEF-123', 'iOjzJsHS0M0'):
            self.assertEqual(self.ts.path_of(video), exporter.path_of(video))
        # letter case makes another file: a case-blind file system never merges two trailers
        self.assertNotEqual(self.ts.path_of('aBc_dEf-123'), self.ts.path_of('ABC_DEF-123'))

    def test_captions_become_words_with_their_second_and_lines(self):
        words = self.ts.vtt_words(VTT_ASR)
        self.assertEqual([w for _a, w in words], ['winter', 'is', 'coming', 'my', 'lord'])
        self.assertEqual(words[1][0], 1.5)
        self.assertEqual(self.ts.vtt_words(VTT_MANUAL), [])
        self.assertEqual(self.ts.vtt_cues(VTT_MANUAL)[0], (1.0, 2.5, 'Winter is coming.'))

    def test_the_file_is_right_to_left_line_by_line(self):
        text = self.ts.srt([[500, 2500, 'תסתכלו! תסתכלו!'], [3000, 4000, 'שורה ראשונה\nשורה שנייה']])
        self.assertIn('00:00:00,500 --> 00:00:02,500', text)
        self.assertIn('‫תסתכלו! תסתכלו!‬', text)
        self.assertIn('‫שורה ראשונה‬\n‫שורה שנייה‬', text)

    def test_a_trailer_that_carries_hebrew_gets_nothing(self):
        self.assertTrue(self.ts.is_hebrew_trailer({'video': 'x', 'hebrew': True}))
        self.assertTrue(self.ts.is_hebrew_trailer({'meta': {'title': 'דקסטר | טריילר מתורגם'}}))
        self.assertTrue(self.ts.is_hebrew_trailer({'meta': {'video': {'title': 'מואנה 2 - טריילר מדובב'}}}))
        self.assertFalse(self.ts.is_hebrew_trailer({'meta': {'title': 'Dune: Part Two | Official Trailer'}}))

    def test_only_a_job_s_video_is_kept_and_answered_no_subtitles(self):
        class Subtitles:
            def __init__(self, video):
                self.video_id = video

            def get_subtitles(self):
                return {'en': 'theirs'}
        self.ts.capture(Subtitles)
        self.assertEqual(Subtitles('other').get_subtitles(), {'en': 'theirs'}, 'any other trailer: the add-on\'s own')
        seen = []

        def loader(video):
            seen.append(Subtitles(video).get_subtitles())
        self.assertEqual(self.ts.load_tracks('wanted00001', loader), '')
        self.assertEqual(seen, [False], 'False: no subtitles, and nothing more asked of YouTube')
        self.assertIsNotNone(self.ts.captured_tracks('wanted00001')[0])
        self.assertEqual(self.ts.load_tracks('broken00001', lambda v: 1 / 0), 'ZeroDivisionError: division by zero')

    def test_pages_then_moransubs_and_shown_only_while_the_trailer_has_the_screen(self):
        home = {'povil.tr.file': 'trailer-file'}
        calls = []

        class Home:
            def getProperty(self, k):
                return home.get(k, '')

            def setProperty(self, k, v):
                home[k] = v

        class Player:
            def isPlayingVideo(self):
                return True

            def getPlayingFile(self):
                return 'trailer-file'

            def setSubtitles(self, path):
                calls.append(('set', os.path.basename(path)))

            def showSubtitles(self, on):
                calls.append(('show', on))
        folder = tempfile.mkdtemp()
        cues = [[1000, 2000, 'שלום לכולם וברוכים הבאים לטריילר']]
        pages = {}

        def fetch(url):
            if url.endswith('config.json'):
                return 404, b''
            return (200, json.dumps({'c': cues}).encode()) if url in pages else (404, b'')
        subs = self.ts.Subs(Home(), Player(), lambda t: None, lambda p: os.path.join(folder, p.split('//')[1]),
                            lambda cmd: None, fetch=fetch)
        sub, name = self.ts.path_of('aBc_dEf-123')
        pages[self.ts.PAGES + 'tsubs/%s/%s' % (sub, name)] = True
        subs.current = 'aBc_dEf-123'
        subs._prepare('aBc_dEf-123', {'video': 'aBc_dEf-123'}, 'key')
        self.assertEqual(calls, [], 'the home is over the trailer: nothing yet')
        subs.alone(True)
        self.assertEqual(calls, [('set', 'aBc_dEf-123.show.he.srt')])
        subs.alone(False)
        subs.alone(True)
        self.assertEqual(calls[1:], [('show', False), ('show', True)])
        # kept on the device: the next time, nothing is asked
        self.assertEqual(subs.cached('aBc_dEf-123'), cues)
        # a trailer not on Pages: asked again only after MISS_S; MoranSubs not able -> nothing
        self.assertIsNone(subs.from_pages('zzzzzzzzzzz'))
        self.assertIn('zzzzzzzzzzz', subs.misses)
        self.assertIsNone(subs.translated_here('zzzzzzzzzzz', {}, 'key', {}))


class MoranSubsTests(unittest.TestCase):
    def setUp(self):
        resources = types.ModuleType('resources')
        lib = types.ModuleType('resources.lib')
        kodi_utils = types.SimpleNamespace(log=lambda *a, **k: None, get_setting=lambda k, d='': self.settings.get(k, d),
                                           addon_profile_path=lambda: self.folder)
        lib.kodi_utils = kodi_utils
        resources.lib = lib
        self.settings = {'api_key': 'free-key', 'model': 'gemini-3.5-flash-lite', 'translation_mode': 'ai'}
        self.folder = tempfile.mkdtemp()
        gemini_quota = types.SimpleNamespace(_today_utc=lambda: '2026-11-20')
        gemini = types.SimpleNamespace(ai_mode_on=lambda: self.settings.get('translation_mode') == 'ai',
                                       API_BASE='https://example.invalid', QuotaExceeded=type('QuotaExceeded', (Exception,), {}),
                                       GeminiError=Exception, _safety_settings=lambda m: [], _classify_429=lambda r: Exception(),
                                       _generated_text=lambda d: d['text'])
        lib.gemini, lib.gemini_quota = gemini, gemini_quota
        self.modules = mock.patch.dict(sys.modules, {'resources': resources, 'resources.lib': lib,
                                                     'resources.lib.kodi_utils': kodi_utils, 'resources.lib.gemini': gemini,
                                                     'resources.lib.gemini_quota': gemini_quota})
        self.modules.start()
        self.ms = load('service.subtitles.kodipovilai/resources/lib/trailer_subs.py', 'moransubs_trailer_subs')

    def tearDown(self):
        self.modules.stop()

    def test_the_word_is_yes_or_no_never_empty_and_at_once_when_the_key_s_tier_is_known(self):
        """0.3.100 (the owner's log, 20 Nov 2026: the first trailer after a start was left untranslated)."""
        said = {}
        xbmcgui = types.SimpleNamespace(Window=lambda wid: types.SimpleNamespace(setProperty=lambda k, v: said.__setitem__(k, v)))
        with mock.patch.dict(sys.modules, {'xbmcgui': xbmcgui}):
            self.ms.publish_able(False)
            self.assertEqual(said[self.ms.ABLE], '0', 'no is said, not left empty: empty means not yet')
            self.ms.publish_able(True)
            self.assertEqual(said[self.ms.ABLE], '1')
        with mock.patch.object(self.ms, '_key', return_value='free-key'):
            self.assertFalse(self.ms.tier_cached(now=1000.0), 'never checked: the check waits for a moment after the start')
            self.ms.tier('free-key', now=1000.0, probe=lambda key: 'free')
            self.assertTrue(self.ms.tier_cached(now=1000.0 + 3600), 'this week\'s check: the word at once')
            self.assertFalse(self.ms.tier_cached(now=1000.0 + self.ms.TIER_S + 1), 'a week later: checked again first')
        with mock.patch.object(self.ms, '_key', return_value=''):
            self.assertTrue(self.ms.tier_cached(), 'no key: "no" is known at once')
        source = (ROOT / 'service.subtitles.kodipovilai/resources/lib/trailer_subs.py').read_text(encoding='utf-8')
        self.assertIn('if not tier_cached() and listener.waitForAbort(20):', source)

    def test_a_free_key_is_told_from_a_billed_one_at_no_cost(self):
        free = json.dumps({'error': {'details': [{'violations': [{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}]}})
        self.assertEqual(self.ms.classify_probe(429, free), 'free')
        self.assertEqual(self.ms.classify_probe(429, '{"error": {}}'), 'unknown', 'a billed key\'s per-minute limit')
        self.assertEqual(self.ms.classify_probe(400, '{}'), 'billed', 'past the quota, refused as invalid: never billed')
        self.assertEqual(self.ms.classify_probe(503, ''), 'unknown')
        sent = []

        def post(url, json=None, headers=None, timeout=None):
            sent.append((url.rsplit('/', 1)[1], json))
            return types.SimpleNamespace(status_code=404 if 'pro-preview' in url else 429, text=free)
        self.assertEqual(self.ms.free_tier('k', post=post), 'free')
        self.assertEqual(sent[0][1]['contents'][0]['role'], 'nobody', 'an invalid request: nothing is generated, nothing billed')
        self.assertEqual([s[0] for s in sent], ['gemini-3.1-pro-preview:generateContent', 'gemini-pro-latest:generateContent'])

    def test_only_a_free_key_within_its_day_and_never_the_film_model(self):
        free = lambda key: 'free'
        self.assertEqual(self.ms.eligible(probe=free), (True, ''))
        # (the tier is kept a week: a new state file for each case below)
        os.remove(os.path.join(self.folder, self.ms.STATE_FILE))
        self.assertFalse(self.ms.eligible(probe=lambda key: 'billed')[0], 'a billed key: nothing beyond the free tier')
        os.remove(os.path.join(self.folder, self.ms.STATE_FILE))
        self.assertFalse(self.ms.eligible(probe=lambda key: 'unknown')[0], 'unknown fails closed')
        os.remove(os.path.join(self.folder, self.ms.STATE_FILE))
        self.settings['model'] = self.ms.MODEL
        self.assertEqual(self.ms.eligible(probe=free), (False, 'the films use this model'))
        self.settings['model'] = 'gemini-3.5-flash-lite'
        self.settings['translation_mode'] = 'google'
        self.assertEqual(self.ms.eligible(probe=free)[1], 'not AI translation')
        self.settings['translation_mode'] = 'ai'
        for _ in range(self.ms.DAY_CAP):
            self.ms._count_request()
        self.assertEqual(self.ms.eligible(probe=free)[1], 'the day\'s requests are used')

    def test_one_request_and_its_reply_read_back_as_timed_lines(self):
        job = {'v': 'aBc_dEf-123', 'src': 'asr', 'title': 'משחקי הכס', 'original': 'Game of Thrones', 'year': '2011', 'kind': 'tv',
               'words': [[1.0, 'winter'], [1.5, 'is'], [1.9, 'coming'], [3.4, 'my'], [3.8, 'lord']], 'lang': 'en'}
        parts, read = self.ms.request_parts(job)
        self.assertIn('[1.0] winter is coming', parts[0]['text'])
        self.assertIn('the series "Game of Thrones" (2011), known in Hebrew as "משחקי הכס"', parts[0]['text'])
        written = []
        reply = '1.0-3.0|החורף מגיע\n3.4-4.0|אדוני, ואנחנו צריכים להתכונן עכשיו לבאות'
        cues = self.ms.handle(job, key='k', post=lambda *a, **k: types.SimpleNamespace(status_code=200, json=lambda: {'text': reply}),
                              write=lambda v, c: written.append((v, c)))
        self.assertEqual([c[2] for c in cues], ['החורף מגיע', 'אדוני, ואנחנו צריכים להתכונן עכשיו לבאות'])
        self.assertEqual(cues[0][1], 3.0)
        self.assertGreaterEqual(round(cues[1][1] - cues[1][0], 2), 1.2, 'at least 1.2 s on the screen')
        self.assertEqual(written[0][0], 'aBc_dEf-123')
        # no captions: Gemini listens to the trailer itself, and a trailer Hebrew already is answered NONE
        parts, _read = self.ms.request_parts({'v': 'aBc_dEf-123', 'src': 'listen'})
        self.assertEqual(parts[0]['fileData']['fileUri'], 'https://www.youtube.com/watch?v=aBc_dEf-123')
        self.assertIn('answer only: NONE', parts[1]['text'])
        none = self.ms.handle({'v': 'bBc_dEf-123', 'src': 'listen'}, key='k',
                              post=lambda *a, **k: types.SimpleNamespace(status_code=200, json=lambda: {'text': 'NONE'}),
                              write=lambda v, c: written.append(v))
        self.assertIsNone(none)
        self.assertEqual(len(written), 1)

    def test_a_person_s_captions_keep_their_timing(self):
        english = [[1.0, 2.5, 'Winter is coming.'], [3.0, 4.0, '[Music]']]
        parts, read = self.ms.request_parts({'v': 'x', 'src': 'manual', 'cues': english})
        self.assertIn('1|Winter is coming.', parts[0]['text'])
        self.assertEqual(read('1|החורף מגיע.\n2|'), [(1.0, 2.5, 'החורף מגיע.')])


class WordTests(unittest.TestCase):
    """Wizard 0.5.32: MoranSubs' word is waited for right after Kodi's start (the owner's log, 20 Nov 2026, Android: the
    first trailer after the start -- "not on Pages; this device does not translate" -- and "this device translates"
    11 s later)."""

    def subs(self, answers, values):
        ts = load('plugin.program.kodipovilwizard/resources/libs/trailer_subs.py', 'povil_wizard_trailer_subs_word')
        home = {}
        said = []

        class Home:
            def getProperty(self, k):
                return home.get(k, '')

        class Waiting:
            calls = 0

            def wait(self, seconds):
                Waiting.calls += 1
                if values:
                    home[ts.ABLE] = values.pop(0)
                return False
        subs = ts.Subs(Home(), None, said.append, lambda w: w, lambda b: None, fetch=lambda u: (404, b''),
                       waiting=Waiting(), answers=lambda: answers)
        subs.current = 'aBc_dEf-123'
        return ts, subs, home, Waiting, said

    def test_no_word_yet_is_waited_for_and_a_yes_translates(self):
        ts, subs, home, waiting, said = self.subs(True, ['', '', '1'])
        self.assertTrue(subs.able('aBc_dEf-123'))
        self.assertEqual(waiting.calls, 3)
        self.assertIn("trailer subtitles: waiting for MoranSubs' word (aBc_dEf-123)", said)

    def test_a_no_is_a_no_at_once_and_an_older_moransubs_s_silence_is_a_no(self):
        ts, subs, home, waiting, said = self.subs(True, [])
        home[ts.ABLE] = '0'
        self.assertFalse(subs.able('aBc_dEf-123'))
        self.assertEqual(waiting.calls, 0)
        ts, subs, home, waiting, said = self.subs(False, ['1'])
        self.assertFalse(subs.able('aBc_dEf-123'), 'MoranSubs 0.3.99 leaves "no" empty: not waited for')
        self.assertEqual(waiting.calls, 0)

    def test_the_wait_ends_with_the_trailer_and_has_a_limit(self):
        ts, subs, home, waiting, said = self.subs(True, [])
        subs.current = 'other000001'
        self.assertFalse(subs.able('aBc_dEf-123'), 'the trailer changed: not waited for')
        ts, subs, home, waiting, said = self.subs(True, [])
        self.assertFalse(subs.able('aBc_dEf-123'))
        self.assertEqual(waiting.calls, int(ts.ABLE_WAIT_S * 2), 'MoranSubs never said: given up after ABLE_WAIT_S')

    def test_the_version_that_gives_the_word(self):
        ts = load('plugin.program.kodipovilwizard/resources/libs/trailer_subs.py', 'povil_wizard_trailer_subs_word2')
        self.assertTrue(ts.version_at_least('0.3.100', ts.WORD_FROM))
        self.assertTrue(ts.version_at_least('0.4.0', ts.WORD_FROM))
        self.assertFalse(ts.version_at_least('0.3.99', ts.WORD_FROM), '100 > 99: compared as numbers')
        self.assertFalse(ts.version_at_least('', ts.WORD_FROM))
        source = (ROOT / 'plugin.program.kodipovilwizard/resources/libs/trailers.py').read_text(encoding='utf-8')
        self.assertIn('answers=moransubs_answers', source)
        self.assertIn("System.AddonVersion(service.subtitles.kodipovilai)", source)


class WithdrawnTests(unittest.TestCase):
    """The reviewer (Nov 2026): a bad translation must be takeable back -- from Pages AND from the devices' own copies."""

    def subs(self, answers):
        ts = load('plugin.program.kodipovilwizard/resources/libs/trailer_subs.py', 'povil_wizard_trailer_subs_drop')
        folder = tempfile.mkdtemp()
        asked, said = [], []
        now = [1000.0]

        def fetch(url):
            asked.append(url.rsplit('/', 1)[-1])
            return answers.get(url.rsplit('tsubs/', 1)[-1], (404, b''))

        class Home:
            def getProperty(self, k):
                return ''
        subs = ts.Subs(Home(), None, said.append, lambda where: os.path.join(folder, where.rsplit('/', 2)[-2]),
                       lambda builtin: None, fetch=fetch, clock=lambda: now[0])
        subs._ready = lambda video, path: said.append('ready ' + video)
        return ts, subs, asked, said, now

    def test_a_withdrawn_trailer_is_never_shown_even_from_this_device_s_copy(self):
        ts, subs, asked, said, _now = self.subs({'drop.json': (200, b'{"drop": ["aBc_dEf-123"]}'),
                                                 'config.json': (200, b'{"read": true, "drop": ["xYz_dEf-999"]}')})
        for video in ('aBc_dEf-123', 'xYz_dEf-999'):
            subs.keep(video, {'c': [[0, 1000, 'א']], 's': 'asr'})
            subs._prepare(video, {'video': video}, None)
            self.assertIn('trailer subtitles: none (%s withdrawn)' % video, said)
            self.assertIsNone(subs.cached(video), 'its own copy deleted')
        self.assertNotIn('ready aBc_dEf-123', said)
        # any other trailer: from this device's copy as before
        subs.keep('other000001', {'c': [[0, 1000, 'ב']], 's': 'asr'})
        subs._prepare('other000001', {'video': 'other000001'}, None)
        self.assertIn('ready other000001', said)

    def test_switched_off_for_everyone_shows_none_even_from_this_device(self):
        ts, subs, asked, said, _now = self.subs({'config.json': (200, b'{"read": false}')})
        subs.keep('aBc_dEf-123', {'c': [[0, 1000, 'א']], 's': 'asr'})
        subs._prepare('aBc_dEf-123', {'video': 'aBc_dEf-123'}, None)
        self.assertIn('trailer subtitles: none (switched off for everyone)', said)
        self.assertNotIn('ready aBc_dEf-123', said)

    def test_no_answer_keeps_the_last_lists_and_asks_again_sooner(self):
        answers = {'drop.json': (200, b'{"drop": ["aBc_dEf-123"]}')}
        ts, subs, asked, said, now = self.subs(answers)
        subs._config()
        self.assertEqual(subs.withdrawn(subs.config), {'aBc_dEf-123'})
        now[0] += ts.CONFIG_S
        answers['drop.json'] = answers['config.json'] = (0, b'')
        subs._config()
        self.assertEqual(subs.withdrawn(subs.config), {'aBc_dEf-123'}, 'Pages did not answer: the list stays')
        n = len(asked)
        now[0] += ts.CONFIG_RETRY_S
        subs._config()
        self.assertGreater(len(asked), n, 'asked again after a few minutes, not hours')
        answers['drop.json'] = (404, b'')
        now[0] += ts.CONFIG_S
        subs._config()
        self.assertEqual(subs.withdrawn(subs.config), set(), 'no list on Pages: none withdrawn')


class ExportTests(unittest.TestCase):
    def test_new_rows_become_one_file_each_and_the_first_stays(self):
        exporter = load('tools/trailer_subs_export.py', 'povil_trailer_subs_export2')
        folder = tempfile.mkdtemp()
        pages = [{'rows': [{'seq': 1, 'v': 'aBc_dEf-123', 'c': [[0, 1000, 'א']], 's': 'asr', 'm': 'm', 'ts': 1},
                           {'seq': 2, 'v': 'bad id', 'c': []}], 'more': True},
                 {'rows': [{'seq': 3, 'v': 'aBc_dEf-123', 'c': [[0, 1000, 'ב']], 's': 'listen', 'ts': 2}], 'more': False}]
        asked = []

        def fetch(after):
            asked.append(after)
            return pages.pop(0) if pages else {'rows': [], 'more': False}
        written, removed, after = exporter.export(folder, fetch)
        self.assertEqual((written, removed, after), (1, 0, 3))
        self.assertFalse(os.path.exists(os.path.join(folder, 'drop.json')), 'nothing withdrawn: no list')
        self.assertEqual(asked, [0, 2])
        sub, name = exporter.path_of('aBc_dEf-123')
        data = json.load(open(os.path.join(folder, sub, name), encoding='utf-8'))
        self.assertEqual(data['c'], [[0, 1000, 'א']], 'a trailer translated twice keeps its first')
        self.assertEqual(json.load(open(os.path.join(folder, 'state.json')))['after'], 3)
        # the next run asks from there
        written, removed, after = exporter.export(folder, lambda a: (asked.append(a) or {'rows': [], 'more': False}))
        self.assertEqual(asked[-1], 3)

    def test_a_withdrawn_trailer_s_file_goes_and_the_list_is_published(self):
        exporter = load('tools/trailer_subs_export.py', 'povil_trailer_subs_export3')
        folder = tempfile.mkdtemp()
        row = {'seq': 1, 'v': 'aBc_dEf-123', 'c': [[0, 1000, 'א']], 's': 'asr', 'ts': 1}
        self.assertEqual(exporter.export(folder, lambda a: {'rows': [row] if a == 0 else [], 'drop': []}), (1, 1, 1))
        # nothing withdrawn: an empty list all the same (the devices get a 200, not a missing file)
        self.assertEqual(json.load(open(os.path.join(folder, 'drop.json'))), {'drop': []})
        sub, name = exporter.path_of('aBc_dEf-123')
        self.assertTrue(os.path.exists(os.path.join(folder, sub, name)))
        # withdrawn: the file goes, the list is written; a row of it that still comes is not written again
        late = dict(row, seq=2)
        page = {'rows': [late], 'drop': ['aBc_dEf-123', 'bad id']}
        self.assertEqual(exporter.export(folder, lambda a: page if a == 1 else {'rows': [], 'drop': page['drop']}), (0, 2, 2))
        self.assertFalse(os.path.exists(os.path.join(folder, sub, name)))
        self.assertEqual(json.load(open(os.path.join(folder, 'drop.json'))), {'drop': ['aBc_dEf-123']})
        # the same list again: nothing changes (no commit, no Pages run)
        self.assertEqual(exporter.export(folder, lambda a: {'rows': [], 'drop': ['aBc_dEf-123']}), (0, 0, 2))
        # given back: the list empties
        self.assertEqual(exporter.export(folder, lambda a: {'rows': [], 'drop': []}), (0, 1, 2))
        self.assertEqual(json.load(open(os.path.join(folder, 'drop.json'))), {'drop': []})
        # an older Worker that sends no list leaves the list alone
        self.assertEqual(exporter.export(folder, lambda a: {'rows': []}), (0, 0, 2))

    def test_the_workflow_asks_github_s_token_and_publishes_through_pages(self):
        flow = (ROOT / '.github/workflows/trailer-subs.yml').read_text(encoding='utf-8')
        self.assertIn('id-token: write', flow)
        self.assertNotIn('workers.dev', flow, 'the Worker\'s address is read from pool.py, not written again')
        self.assertIn('deploy-pages.yml/dispatches', flow)
        pages = (ROOT / '.github/workflows/deploy-pages.yml').read_text(encoding='utf-8')
        self.assertIn('--branch=trailer-subs', pages)
        self.assertIn('gh/tsubs', pages)
        config = json.loads((ROOT / 'tsubs/config.json').read_text(encoding='utf-8'))
        self.assertEqual(config, {'read': True, 'translate': True})


if __name__ == '__main__':
    unittest.main()
