"""Wizard 0.5.16: the first title on the home gets its ratings too.

The owner, Nov 2026: "the first screen on every device shows only the TMDb rating, and when one goes forward
and back it shows them all -- but the first time Kodi opens only TMDb appears". The skin asks once per title
(a home property and a notification); the Wizard's ratings thread starts once the home has settled, after the
first title had been asked -- nobody heard it.
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'plugin.program.kodipovilwizard/resources/libs/ratings.py'


class FirstAskTests(unittest.TestCase):
    def test_the_listener_answers_what_was_asked_before_it_existed(self):
        text = SOURCE.read_text('utf-8')
        body = text[text.index('def watch():'):]
        made = body.index('listener = Listener()')
        first = body.index('for slot in SLOTS:', made)
        self.assertLess(first, body.index('listener.waitForAbort(600)'), 'before the thread starts waiting')
        self.assertIn('desk.asked(slot)', body[first:first + 200])

    def test_an_ask_left_in_the_home_is_answered_from_what_is_known(self):
        modules = {'xbmc': types.SimpleNamespace(log=lambda *a, **k: None, LOGINFO=1, LOGWARNING=2)}
        with mock.patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location('ratings_first_test', SOURCE)
            ratings = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ratings)

        class Home(object):
            def __init__(self, **values):
                self.values = dict(values)

            def getProperty(self, key):
                return self.values.get(key, '')

            def setProperty(self, key, value):
                self.values[key] = value

            def clearProperty(self, key):
                self.values.pop(key, None)

        class Store(object):
            clock = staticmethod(lambda: 0.0)

            def known(self, key):
                return None, False

        prefix = ratings.SLOTS['home']
        home = Home(**{prefix + 'ask': 'movie|tt0000001'})
        desk = ratings.Desk(home, Store(), lambda label: '')
        self.assertFalse(desk.asked('home'), 'nothing known yet: asked of Trakt')
        self.assertTrue(any(job[2] == 'movie|tt0000001' for job in desk.jobs), 'queued as the title on screen')
        self.assertFalse(Desk_asked_without_ask(ratings, Home, Store))


def Desk_asked_without_ask(ratings, Home, Store):
    """No ask left by the skin: nothing to do."""
    return ratings.Desk(Home(), Store(), lambda label: '').asked('home')


if __name__ == '__main__':
    unittest.main()
