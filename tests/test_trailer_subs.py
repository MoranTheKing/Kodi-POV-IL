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
import time
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

    def test_the_device_says_itself_once_a_day_and_the_season_goes_with_the_translation(self):
        said = []
        switches = {'use': True, 'share': True}
        pool = types.SimpleNamespace(say_seen=lambda body: said.append(body) or (200, {'ok': True}),
                                     use_enabled=lambda: switches['use'], share_enabled=lambda: switches['share'],
                                     share_trailer=lambda body: said.append(('share', body)) or (200, {'ok': True}))
        xbmc = types.SimpleNamespace(getSkinDir=lambda: 'skin.povil.onyx')
        tokens = os.path.join(self.folder, 'tokens.json')
        xbmcvfs = types.SimpleNamespace(translatePath=lambda p: tokens)
        with mock.patch.dict(sys.modules, {'resources.lib.pool': pool, 'xbmc': xbmc, 'xbmcvfs': xbmcvfs}):
            sys.modules['resources.lib'].pool = pool
            self.assertTrue(self.ms.say_seen(now=1795190000))
            self.assertEqual(said, [{'sync': False, 'onyx': True}])
            self.assertFalse(self.ms.say_seen(now=1795190000 + 3600), 'once a UTC day')
            open(tokens, 'w').close()
            self.assertTrue(self.ms.say_seen(now=1795190000 + 86400))
            self.assertEqual(said[-1], {'sync': True, 'onyx': True}, 'the Wizard\'s cloud sync connected')
            switches.update(use=False, share=False)
            n = len(said)
            self.assertFalse(self.ms.say_seen(now=1795190000 + 2 * 86400), 'both pool switches off: nothing leaves the device')
            self.assertEqual(len(said), n)
            switches.update(use=True, share=True)
            # an older Worker answers /seen with its landing page: ONE try a day all the same, never a retry storm
            pool.say_seen = lambda body: said.append(body) or (0, {})
            n = len(said)
            self.assertFalse(self.ms.say_seen(now=1795190000 + 3 * 86400))
            self.assertFalse(self.ms.say_seen(now=1795190000 + 3 * 86400 + 600))
            self.assertEqual(len(said), n + 1, 'tried once that day')
            pool.say_seen = lambda body: said.append(body) or (200, {'ok': True})
            self.ms.share({'v': 'aBc_dEf-123', 'src': 'asr', 'title': 'מובלנד', 'year': '2025', 'kind': 'tv', 'season': 2},
                          [(0.0, 1.0, 'שלום')])
            for _ in range(50):
                if any(isinstance(x, tuple) for x in said):
                    break
                time.sleep(0.02)
            body = [x for x in said if isinstance(x, tuple)][0][1]
            self.assertEqual((body['k'], body['e']), ('tv', 2))

    def test_the_words_time_the_lines_and_a_bad_line_is_left_out(self):
        # The Simpsons' trailer (the owner, Nov 2026: "lines come early or late"): "green screen", spoken at 12.2-12.6
        # with nothing more until 31.1, stayed seven seconds; now about one and a half
        words = [(4.4, 'i'), (4.7, 'love'), (5.0, 'this'), (5.4, 'place'), (12.2, 'green'), (12.6, 'screen'),
                 (31.1, 'wait'), (31.4, 'who'), (31.5, 'are'), (31.7, 'you')]
        info = {}
        cues = self.ms.by_words('1-4|אני מת על המקום הזה.\n5-6|מסך ירוק.\n7-10|רגע, מי אתה?', words, info)
        self.assertEqual([c[0] for c in cues], [4.3, 12.1, 31.0], 'each with its first word')
        self.assertLess(cues[0][1], 7.0, 'gone a moment after "place" (5.4), not at the next line (12.2)')
        self.assertLess(cues[1][1], 14.0, '"green screen" no longer stays seven seconds')
        self.assertEqual((info['covered'], info['words']), (10, 10))
        # out of order, overlapping, past the last word, or empty: left out
        cues = self.ms.by_words('5-6|ב\n3-4|א\n6-7|ג\n9-12|ד\n7-8|\n7-8|ה', words, info)
        self.assertEqual([c[2] for c in cues], ['ב', 'ה'])
        self.assertEqual(info['covered'], 4)
        # the captions heard the last word long after the rest ("...a car accident last [8 s] night", QA): not waited for
        tail = [(2.9, 'dr'), (3.2, 'larsson'), (3.4, 'was'), (3.5, 'in'), (3.6, 'a'), (3.7, 'car'), (3.9, 'accident'),
                (4.2, 'last'), (12.5, 'night'), (13.5, 'she')]
        cues = self.ms.by_words('1-9|ד"ר לארסון עברה תאונת דרכים אמש.\n10-10|היא', tail, info)
        self.assertLess(cues[0][1], 6.0, 'gone after "last", not at "night" eight seconds later')
        # a long pause inside a line, then MORE than two words: the line holds them, so it stays
        long = [(1.0, 'a'), (1.2, 'b'), (5.0, 'c'), (5.2, 'd'), (5.4, 'e')]
        cues = self.ms.by_words('1-5|א ב ג ד ה', long, info)
        self.assertGreater(cues[0][1], 5.4)
        # an exclamation long before the sentence (the blind judges: such lines came 5-7 s early): with the sentence
        head = [(10.0, 'wooo'), (16.0, 'searching'), (16.3, 'for'), (16.6, 'him')]
        cues = self.ms.by_words('1-4|וואו, מחפשים אותו', head, info)
        self.assertEqual(cues[0][0], 15.9)
        # never into the next line, a lead of 0.1 s at most
        cues = self.ms.by_words('1-1|אני\n2-4|אוהב את המקום הזה מאוד מאוד מאוד', words, info)
        self.assertLessEqual(cues[0][1], cues[1][0])

    def test_gemini_busy_is_asked_once_more_and_then_again_soon(self):
        answers = []

        def post(url, json=None, headers=None, timeout=None):
            code = answers.pop(0)
            return types.SimpleNamespace(status_code=code, json=lambda: {'text': '1-2|שלום לכם חברים יקרים מאוד, מה שלומכם היום הזה?'})
        job = {'v': 'busy0000001', 'src': 'asr', 'words': [[1.0, 'hello'], [2.0, 'there']], 'lang': 'en'}
        with mock.patch.object(self.ms, 'BUSY_RETRY_S', 0), mock.patch.object(self.ms, '_write', lambda v, c: None):
            answers[:] = [503, 200]
            self.assertTrue(self.ms.handle(dict(job), key='k', post=post, now=1000.0), 'busy, then answered at once')
            answers[:] = [503, 503]
            self.assertIsNone(self.ms.handle(dict(job, v='busy0000002'), key='k', post=post, now=1000.0))
            self.assertTrue(self.ms._recently_failed('busy0000002', now=1000.0 + 60))
            self.assertFalse(self.ms._recently_failed('busy0000002', now=1000.0 + self.ms.BUSY_S + 1), 'again in 30 minutes')
            answers[:] = [400]
            self.assertIsNone(self.ms.handle(dict(job, v='badreq00003'), key='k', post=post, now=1000.0))
            self.assertEqual(answers, [], 'a request\'s own fault: not asked twice')
            self.assertTrue(self.ms._recently_failed('badreq00003', now=1000.0 + self.ms.BUSY_S + 1), 'a day')

    def test_a_trailer_playing_when_the_service_starts_gets_no_search(self):
        """0.3.101: the owner, Nov 2026 -- at Kodi's first start the home's first trailer began before the service,
        and its start-up 'kick' (no trailer check) brought the subtitles' overlay up over it."""
        source = (ROOT / 'service.subtitles.kodipovilai/resources/lib/autosub_service.py').read_text(encoding='utf-8')
        self.assertIn('if xbmc.Player().isPlayingVideo() and not _home_trailer(xbmc.Player()):', source)
        self.assertIn('            if _home_trailer(self):\n                return', source.replace('\r\n', '\n'))
        body = source.split('def _home_trailer(player):')[1].split('\nif xbmc is not None:')[0]
        namespace = {}
        exec('def _home_trailer(player):' + body, namespace)
        window = types.SimpleNamespace(getProperty=lambda k: 'trailer-file' if k == 'povil.tr.file' else '')
        with mock.patch.dict(sys.modules, {'xbmcgui': types.SimpleNamespace(Window=lambda wid: window)}):
            self.assertTrue(namespace['_home_trailer'](types.SimpleNamespace(getPlayingFile=lambda: 'trailer-file')))
            self.assertFalse(namespace['_home_trailer'](types.SimpleNamespace(getPlayingFile=lambda: 'a-film')))

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
        self.assertIn('[1]winter [2]is [3]coming [4]my [5]lord', parts[0]['text'], 'every word numbered (0.3.103)')
        self.assertIn('FIRST-LAST|Hebrew text', parts[0]['text'])
        self.assertIn('the series "Game of Thrones" (2011), known in Hebrew as "משחקי הכס"', parts[0]['text'])
        written = []
        reply = '1-3|החורף מגיע\n4-5|אדוני, ואנחנו צריכים להתכונן עכשיו לבאות'
        cues = self.ms.handle(job, key='k', post=lambda *a, **k: types.SimpleNamespace(status_code=200, json=lambda: {'text': reply}),
                              write=lambda v, c: written.append((v, c)))
        self.assertEqual([c[2] for c in cues], ['החורף מגיע', 'אדוני, ואנחנו צריכים להתכונן עכשיו לבאות'])
        # timed by the words: a moment before "winter" (1.0) to a moment after "coming" (1.9) -- not the next line's start
        self.assertEqual(cues[0][:2], (0.9, 2.9))
        self.assertEqual(cues[1][0], 3.3, 'with "my" (3.4)')
        self.assertGreaterEqual(round(cues[1][1] - cues[1][0], 2), 3.0, 'a long line stays long enough to be read')
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


class SeasonTests(unittest.TestCase):
    """Wizard 0.5.34 / MoranSubs 0.3.102: the channel's post says a series trailer's season (the owner, Nov 2026)."""

    def test_the_season_a_series_trailer_is_of(self):
        trailers = load('plugin.program.kodipovilwizard/resources/libs/trailers.py', 'povil_trailers_season')
        seasons = [{'season_number': 1, 'air_date': '2021-03-01'}, {'season_number': 2, 'air_date': '2023-03-01'},
                   {'season_number': 3, 'air_date': '2025-03-01'}]
        meta = {'season_data': seasons, 'all_trailers': [
            {'key': 'named000002', 'name': 'Season 2 Official Trailer', 'published_at': '2023-01-10'},
            {'key': 'final000003', 'name': 'The Final Season | Trailer', 'published_at': '2025-02-01'},
            {'key': 'dated000003', 'name': 'Official Trailer', 'published_at': '2025-02-20'},
            {'key': 'stale000000', 'name': 'Official Trailer', 'published_at': '2027-06-01'}]}
        pick = load('plugin.program.kodipovilwizard/resources/libs/patches/pov_trailer_pick.py', 'pick_for_season')
        packages = {name: types.ModuleType(name) for name in ('resources', 'resources.libs', 'resources.libs.patches')}
        packages['resources.libs.patches'].pov_trailer_pick = pick
        packages['resources.libs.patches.pov_trailer_pick'] = pick
        with mock.patch.dict(sys.modules, packages):
            self.assertEqual(trailers.trailer_season(meta, 'named000002'), 2, 'its name')
            self.assertEqual(trailers.trailer_season(meta, 'final000003'), 3, '"final season": the last there is')
            self.assertEqual(trailers.trailer_season(meta, 'dated000003'), 3, 'the season it came out for')
            self.assertIsNone(trailers.trailer_season(meta, 'stale000000'), 'long after the last season: the series\' own')
            self.assertIsNone(trailers.trailer_season(meta, 'unknown0000'))
            self.assertEqual(trailers.trailer_season({'season_data': seasons[:1], 'all_trailers': [{'key': 'one00000001', 'name': 'Trailer'}]},
                                                     'one00000001'), 1, 'a series of one season')
        source = (ROOT / 'plugin.program.kodipovilwizard/resources/libs/trailers.py').read_text(encoding='utf-8')
        self.assertIn("season = trailer_season(meta, video)", source)


class RenewedTests(unittest.TestCase):
    """0.5.35 / MoranSubs 0.3.103: the automatic captions' translations timed the old way are made again (the owner,
    Nov 2026: "replace what was there until now, as exact as can be")."""

    def test_only_the_old_automatic_captions_ones_are_outdated(self):
        ts = load('plugin.program.kodipovilwizard/resources/libs/trailer_subs.py', 'povil_wizard_trailer_subs_renew')
        self.assertTrue(ts.outdated({'c': [[0, 1, 'א']], 's': 'asr'}), 'no version: the old way')
        self.assertTrue(ts.outdated({'s': 'asr', 'f': 1}))
        self.assertFalse(ts.outdated({'s': 'asr', 'f': 2}))
        self.assertFalse(ts.outdated({'s': 'manual'}), 'a person\'s captions keep their own times')
        self.assertFalse(ts.outdated({'s': 'listen'}), 'nothing better there')
        self.assertFalse(ts.outdated(None))

    def test_an_outdated_one_is_made_again_on_a_device_that_translates(self):
        ts = load('plugin.program.kodipovilwizard/resources/libs/trailer_subs.py', 'povil_wizard_trailer_subs_renew2')
        folder = tempfile.mkdtemp()
        home = {ts.ABLE: '1'}

        class Home:
            def getProperty(self, k):
                return home.get(k, '')

            def setProperty(self, k, v):
                home[k] = v

            def clearProperty(self, k):
                home.pop(k, None)
        said = []
        subs = ts.Subs(Home(), None, said.append, lambda where: os.path.join(folder, where.rsplit('/', 2)[-2]),
                       lambda b: None, fetch=lambda u: (404, b''))
        subs.keep('aBc_dEf-123', {'c': [[0, 1000, 'ישן']], 's': 'asr'})
        new = [[100, 900, 'חדש']]
        subs.translated_here = lambda video, stream, key, config: (subs.keep(video, {'c': new, 's': 'asr', 'f': 2}) or new)
        subs._ready = lambda video, path, cues=None: said.append(('ready', cues))
        subs.current = 'aBc_dEf-123'
        subs._prepare('aBc_dEf-123', {'video': 'aBc_dEf-123'}, None)
        self.assertIn(('ready', new), said)
        self.assertIn('trailer subtitles: aBc_dEf-123 from MoranSubs (renewed) (1 lines)', said)
        self.assertEqual(subs.cached_data('aBc_dEf-123')['f'], 2, 'kept: not made again next time')
        # a device that does not translate shows the old one
        subs.keep('bBc_dEf-123', {'c': [[0, 1000, 'ישן']], 's': 'asr'})
        home[ts.ABLE] = '0'
        subs.current = 'bBc_dEf-123'
        subs._prepare('bBc_dEf-123', {'video': 'bBc_dEf-123'}, None)
        self.assertIn(('ready', [[0, 1000, 'ישן']]), said)


class DrawnLinesTests(unittest.TestCase):
    """Wizard 0.5.33 / Onyx 1.0.30: the skin draws the lines. The owner, Nov 2026, Android: "much of the trailer passed,
    and no Hebrew subtitle appeared yet" -- the subtitle was loaded into the player at once, but Kodi draws no subtitles
    over a video window whose picture is on a layer of its own (MediaCodec surface; CGUIVideoControl::Render)."""

    def make(self, draws, times):
        ts = load('plugin.program.kodipovilwizard/resources/libs/trailer_subs.py', 'povil_wizard_trailer_subs_lines')
        home = {'povil.tr.file': 'trailer-file'}
        seen, calls = [], []

        class Home:
            def getProperty(self, k):
                return home.get(k, '')

            def setProperty(self, k, v):
                home[k] = v
                seen.append((k, v))

            def clearProperty(self, k):
                home.pop(k, None)
                seen.append((k, None))

        class Player:
            def isPlayingVideo(self):
                return True

            def getPlayingFile(self):
                return 'trailer-file'

            def getTime(self):
                return times.pop(0) if times else 99.0

            def setSubtitles(self, path):
                calls.append(('set', path))

            def showSubtitles(self, on):
                calls.append(('show', on))

        subs = None

        class Waiting:
            def wait(self, seconds):
                if not times:
                    subs.gone()          # the trailer ended
                return False
        subs = ts.Subs(Home(), Player(), lambda m: None, lambda w: w, lambda b: None, waiting=Waiting(),
                       draws=lambda: draws)
        subs.current = 'aBc_dEf-123'
        return ts, subs, home, seen, calls

    def test_the_line_of_the_moment_and_kodi_s_tags_kept_out(self):
        ts = load('plugin.program.kodipovilwizard/resources/libs/trailer_subs.py', 'povil_wizard_trailer_subs_lines2')
        cues = [[1000, 2500, 'שלום'], [3000, 4000, 'שורה ראשונה\nשורה שנייה']]
        self.assertEqual(ts.line_at(cues, 999), '')
        self.assertEqual(ts.line_at(cues, 1000), 'שלום')
        self.assertEqual(ts.line_at(cues, 2600), '', 'between lines: nothing')
        self.assertEqual(ts.label_text(cues[1][2]), 'שורה ראשונה[CR]שורה שנייה')
        self.assertEqual(ts.label_text('[B]מה?[/B]'), '(B)מה?(/B)', 'never a Kodi tag')

    def test_with_onyx_1_0_30_the_skin_draws_them_by_the_trailer_s_clock(self):
        ts, subs, home, seen, calls = self.make(True, [0.5, 1.2, 1.3, 2.7, 3.2])
        subs._ready('aBc_dEf-123', 'unused.srt', [[1000, 2500, 'שלום'], [3000, 4000, 'עוד שורה']])
        for _ in range(100):
            if 'povil.tsub.on' not in home and seen:
                break
            import time as _t
            _t.sleep(0.02)
        lines = [v for k, v in seen if k == ts.LINE]
        self.assertEqual(lines, ['שלום', None, 'עוד שורה', None], 'set when it changes, cleared between and at the end')
        self.assertIn((ts.LINES_ON, 'aBc_dEf-123'), seen)
        self.assertNotIn(ts.LINES_ON, home, 'gone with the trailer')
        self.assertEqual(calls, [], 'no subtitle file for the player')

    def test_with_an_older_skin_the_player_gets_the_file_as_before(self):
        ts, subs, home, seen, calls = self.make(False, [])
        subs.is_alone = True
        subs._ready('aBc_dEf-123', 'trailer.he.srt', [[0, 1000, 'שלום']])
        self.assertEqual(calls, [('set', 'trailer.he.srt')])

    def test_the_skin_draws_it_only_while_the_trailer_has_the_screen(self):
        sys.path.insert(0, str(ROOT / 'tools' / 'skin_onyx'))
        import gen_home as H
        for name in ('Home.xml', 'View_POVIL.xml'):
            text = (ROOT / 'skin.povil.onyx/xml' / name).read_text(encoding='utf-8')
            label = text.split('<control type="label" description="trailer subtitles">')[1].split('</control>')[0]
            self.assertIn('<label>$INFO[Window(home).Property(povil.tsub.line)]</label>', label, name)
            self.assertIn('<visible>%s + !String.IsEmpty(Window(home).Property(povil.tsub.line))</visible>'
                          % H.TRAILER_ALONE, label, name)
            self.assertIn('<font>povil_trailer_sub</font>', label)
            shade = text.split('<control type="image" description="trailer subtitles backdrop">')[1].split('</control>')[0]
            self.assertIn('!String.IsEmpty(Window(home).Property(povil.tsub.on))', shade, 'a shade only under a trailer that has them')
        fonts = (ROOT / 'skin.povil.onyx/xml/Font.xml').read_text(encoding='utf-8')
        self.assertEqual(fonts.count('<name>povil_trailer_sub</name>'), 2, 'Heebo and the Arial fallback')
        source = (ROOT / 'plugin.program.kodipovilwizard/resources/libs/trailers.py').read_text(encoding='utf-8')
        self.assertIn("xbmc.getSkinDir() == 'skin.povil.onyx'", source)


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
        subs._ready = lambda video, path, cues=None: said.append('ready ' + video)
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

    def test_a_newer_version_overwrites_the_file_and_the_same_does_not(self):
        exporter = load('tools/trailer_subs_export.py', 'povil_trailer_subs_export4')
        folder = tempfile.mkdtemp()
        old = {'seq': 1, 'v': 'aBc_dEf-123', 'c': [[0, 1000, 'ישן']], 's': 'asr', 'ts': 1}
        new = dict(old, seq=2, c=[[100, 900, 'חדש']], f=2, k='tv', e=3)
        same = dict(new, seq=3, c=[[0, 1, 'עוד']])
        pages = {0: [old], 1: [new], 2: [same]}
        for after in (0, 1, 2):
            exporter.export(folder, lambda a, after=after: {'rows': pages[after] if a == after else [], 'drop': []})
        sub, name = exporter.path_of('aBc_dEf-123')
        data = json.load(open(os.path.join(folder, sub, name), encoding='utf-8'))
        self.assertEqual((data['c'], data['f'], data['k'], data['e']), ([[100, 900, 'חדש']], 2, 'tv', 3))

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
