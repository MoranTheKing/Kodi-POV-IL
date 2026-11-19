"""How soon the home's trailer starts and has the screen (the owner, Nov 2026: "as fast as possible, almost at
once ... and let the settings change these timings"): the tile, its question, and the trailer read ahead."""
import importlib.util
import sys
import threading
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XML = ROOT / 'skin.povil.onyx' / 'xml'


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


timing = load('qa_trailer_timing', 'plugin.program.kodipovilwizard/resources/libs/trailer_timing.py')
trailers = load('qa_trailers_timing', 'plugin.program.kodipovilwizard/resources/libs/trailers.py')
KEY = 'plugin://plugin.video.youtube/play/?video_id=AAAAAAAAAAA'
OTHER = 'plugin://plugin.video.youtube/play/?video_id=BBBBBBBBBBB'


class Home(dict):
    def getProperty(self, name):
        return self.get(name, '')

    def setProperty(self, name, value):
        self[name] = value

    def clearProperty(self, name):
        self.pop(name, None)


class Player(object):
    def __init__(self):
        self.calls = []

    def play(self, url, item, windowed):
        self.calls.append(url)

    def isPlaying(self):
        return False

    def getPlayingFile(self):
        return ''

    def stop(self):
        pass


class TimingTests(unittest.TestCase):
    def test_the_defaults_until_the_viewer_chooses(self):
        self.assertEqual(timing.current(lambda label: '', timing.WAIT, timing.WAITS), 1)
        self.assertEqual(timing.current(lambda label: '', timing.FULL, timing.FULLS), 4, 'as it always was')
        self.assertEqual(timing.current(lambda label: '3', timing.WAIT, timing.WAITS), 3)
        self.assertEqual(timing.current(lambda label: '0', timing.FULL, timing.FULLS), 0, 'never')
        self.assertEqual(timing.current(lambda label: '7', timing.WAIT, timing.WAITS), 1, 'not a choice: the default')
        self.assertEqual(timing.name_of(4, timing.FULLS), '4 שניות')

    def test_the_skin_knows_every_choice_and_the_tile_asks(self):
        start = {t.findtext('name'): t for t in ET.parse(XML / 'Timers.xml').getroot().findall('timer')}['povil_trailer'].findtext('start')
        for seconds, _name in timing.WAITS:
            self.assertIn('String.IsEqual(Skin.String(POVILTrailerWait),%d)' % seconds, start)
        home = (XML / 'Home.xml').read_text('utf-8')
        for seconds, _name in timing.FULLS:
            if seconds:
                self.assertIn('String.IsEqual(Skin.String(POVILTrailerFull),%d)' % seconds, home)
        self.assertNotIn('String.IsEqual(Skin.String(POVILTrailerFull),0)', home)
        self.assertIn('?mode=trailer_timing', home)
        router = (ROOT / 'plugin.program.kodipovilwizard/resources/libs/common/router.py').read_text('utf-8')
        self.assertIn("mode == 'trailer_timing'", router)


class ReadAheadTests(unittest.TestCase):
    def desk(self, resolve):
        home = Home()
        player = Player()
        desk = trailers.Desk(home, player, resolve, lambda url, stream: url, lambda: True, halt=lambda: None,
                             log=lambda text: None)
        desk.born = 0.0
        return home, player, desk

    def test_the_trailer_read_while_the_screen_rests_is_the_one_played(self):
        asked = []
        home, player, desk = self.desk(lambda video: (asked.append(video), [{'url': 'http://x/%s.mpd' % video}])[1])
        home[trailers.PEEK] = KEY
        job = desk.peeked()
        self.assertIsNotNone(job)
        self.assertFalse(job())
        self.assertEqual(asked, ['AAAAAAAAAAA'], 'read once the screen stayed on it')
        home[trailers.ASK] = KEY
        self.assertTrue(desk.asked()())
        self.assertEqual(asked, ['AAAAAAAAAAA'], 'the ask plays what was read: YouTube is not asked again')
        self.assertEqual(player.calls, ['http://x/AAAAAAAAAAA.mpd'])
        self.assertNotIn(KEY, desk.found, 'read once, played once')

    def test_a_title_passed_on_the_way_is_not_read(self):
        asked = []
        home, player, desk = self.desk(lambda video: (asked.append(video), [{'url': 'u'}])[1])
        home[trailers.PEEK] = KEY
        job = desk.peeked()
        home[trailers.PEEK] = OTHER           # the screen moved on before PEEK_S
        self.assertFalse(job())
        self.assertEqual(asked, [])

    def test_an_ask_during_the_reading_waits_for_it(self):
        asked, go = [], threading.Event()

        def resolve(video):
            asked.append(video)
            go.wait(5)
            return [{'url': 'http://x/a.mpd'}]
        home, player, desk = self.desk(resolve)
        home[trailers.PEEK] = KEY
        reader = threading.Thread(target=desk.peeked())
        reader.start()
        for _ in range(100):
            if asked:
                break
            threading.Event().wait(0.02)
        home[trailers.ASK] = KEY
        job = desk.asked()
        result = []
        player_thread = threading.Thread(target=lambda: result.append(job()))
        player_thread.start()
        go.set()
        reader.join(5)
        player_thread.join(5)
        self.assertEqual(result, [True])
        self.assertEqual(asked, ['AAAAAAAAAAA'], 'one reading for both')
        self.assertEqual(player.calls, ['http://x/a.mpd'])

    def test_a_trailer_read_ahead_that_failed_counts_when_it_is_asked(self):
        home, player, desk = self.desk(lambda video: (_ for _ in ()).throw(ValueError('gone')))
        home[trailers.PEEK] = KEY
        desk.peeked()()
        self.assertEqual(desk.failed, 0, 'nothing counted for a title only looked at')
        home[trailers.ASK] = KEY
        self.assertFalse(desk.asked()())
        self.assertEqual(desk.failed, 1)
        self.assertIn(KEY, desk.given_up)
        self.assertEqual(player.calls, [])

    def test_one_reading_ahead_at_a_time(self):
        # (review: every reading is several requests to YouTube -- a row browsed with short stops must not
        # start one for each poster at once)
        asked, go = [], threading.Event()

        def resolve(video):
            asked.append(video)
            go.wait(5)
            return [{'url': 'http://x/%s.mpd' % video}]
        home, player, desk = self.desk(resolve)
        home[trailers.PEEK] = KEY
        first = threading.Thread(target=desk.peeked())
        first.start()
        for _ in range(100):
            if asked:
                break
            threading.Event().wait(0.02)
        home[trailers.PEEK] = OTHER
        second = threading.Thread(target=desk.peeked())
        second.start()
        threading.Event().wait(trailers.PEEK_S + 0.3)
        self.assertEqual(asked, ['AAAAAAAAAAA'], 'the next waits while the last one is still reading')
        go.set()
        first.join(5)
        second.join(5)
        self.assertEqual(asked, ['AAAAAAAAAAA', 'BBBBBBBBBBB'])
        self.assertIn(OTHER, desk.found)

    def test_nothing_is_read_at_kodis_start_or_while_switched_off(self):
        home, player, desk = self.desk(lambda video: [{'url': 'u'}])
        home[trailers.PEEK] = KEY
        desk.born = desk.clock()
        self.assertIsNone(desk.peeked())
        desk.born = 0.0
        desk.enabled = lambda: False
        self.assertIsNone(desk.peeked())


if __name__ == '__main__':
    unittest.main()
