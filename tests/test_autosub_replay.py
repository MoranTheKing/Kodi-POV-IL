"""The automatic subtitle runs again when the same file is played a second time in a row."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'service.subtitles.kodipovilai/resources/lib/autosub_service.py'


def load(playing):
    xbmc = types.ModuleType('xbmc')

    class Player(object):
        def __init__(self, *a, **k):
            pass

        def isPlaying(self):
            if isinstance(playing[0], Exception):
                raise playing[0]
            return playing[0]

    xbmc.Player = Player
    with patch.dict(sys.modules, {'xbmc': xbmc}):
        spec = importlib.util.spec_from_file_location('autosub_replay_test', MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class ReplayTests(unittest.TestCase):
    def test_a_stop_with_nothing_playing_forgets_the_file(self):
        playing = [False]
        m = load(playing)
        for event in ('onPlayBackStopped', 'onPlayBackEnded', 'onPlayBackError'):
            m.STATE['last_file'] = 'film.mkv'
            getattr(m.AutoSubPlayer(), event)()
            self.assertIsNone(m.STATE['last_file'], event)

    def test_a_stop_while_another_file_plays_keeps_that_files_mark(self):
        # the old file's stop can arrive after the new one started: its run owns last_file
        playing = [True]
        m = load(playing)
        m.STATE['last_file'] = 'next-film.mkv'
        m.AutoSubPlayer().onPlayBackStopped()
        self.assertEqual(m.STATE['last_file'], 'next-film.mkv')

    def test_a_player_that_cannot_be_asked_changes_nothing(self):
        playing = [RuntimeError('no player')]
        m = load(playing)
        m.STATE['last_file'] = 'film.mkv'
        self.assertFalse(m.playback_over())
        self.assertEqual(m.STATE['last_file'], 'film.mkv')

    def test_the_repeat_guard_is_still_what_stops_a_second_onavstarted(self):
        src = MODULE.read_text(encoding='utf-8')
        self.assertIn("if f and f == STATE['last_file']:", src)
        self.assertEqual(src.count("STATE['last_file'] = None"), 1)


if __name__ == '__main__':
    unittest.main()
