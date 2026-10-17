"""Taps that piled up while Kodi was busy start one episode, not several."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

MOD = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard' / 'resources' / 'libs' / 'patches' / 'pov_play_guard.py'


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.props, self.playing, self.exits = {}, False, []
        self.visible, self.timers = False, []
        win = types.SimpleNamespace(getProperty=lambda k: self.props.get(k, ''),
                                    setProperty=lambda k, v: self.props.__setitem__(k, v),
                                    clearProperty=lambda k: self.props.pop(k, None))
        self.toasts = []
        mods = {'xbmc': types.SimpleNamespace(Player=lambda: types.SimpleNamespace(isPlaying=lambda: self.playing),
                                              getCondVisibility=lambda c: self.visible,
                                              Monitor=lambda: types.SimpleNamespace(waitForAbort=lambda s: True),
                                              log=lambda *a: None, LOGINFO=1),
                'xbmcgui': types.SimpleNamespace(Window=lambda wid: win, Dialog=lambda: types.SimpleNamespace(
                    notification=lambda *a, **k: self.toasts.append(a)))}
        patcher = mock.patch.dict(sys.modules, mods)
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location('guard_test', MOD)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)
        reg = mock.patch('atexit.register', lambda fn, *a: self.exits.append((fn, a)))
        reg.start()
        self.addCleanup(reg.stop)
        timer = mock.patch('threading.Timer', lambda delay, fn, args: types.SimpleNamespace(
            start=lambda: self.timers.append((delay, fn, args))))
        timer.start()
        self.addCleanup(timer.stop)

    def tap(self, mode='play_media', reused=False):
        if not reused:
            self.m._LAST[0] = None                  # each request: a fresh interpreter
        return self.m.duplicate(['plugin://plugin.video.pov/', '-1', '?mode=%s&tmdb_id=1' % mode])

    def test_queued_taps_are_dropped_until_the_first_is_over(self):
        self.assertFalse(self.tap())
        self.assertTrue(self.tap())
        self.assertTrue(self.tap())
        fn, args = self.exits[0]
        fn(*args)                                   # cancelled / playing / failed
        self.assertFalse(self.tap())                # a new choice

    def test_playback_and_other_routes_are_never_dropped(self):
        self.assertFalse(self.tap())
        self.playing = True                         # POV's own next episode
        self.assertFalse(self.tap())
        self.assertFalse(self.tap('build_movie_list'))

    def test_a_reused_interpreter_clears_its_previous_mark(self):
        self.assertFalse(self.tap())                # fast navigation: no exit, no atexit
        self.assertFalse(self.tap(reused=True))     # this interpreter's own earlier request is over

    def test_a_dropped_tap_says_so(self):
        self.tap(); self.tap()
        self.assertEqual(len(self.toasts), 1)

    def test_a_stale_mark_does_not_block(self):
        self.props[self.m.PROPERTY] = repr(1.0)     # left by a killed request long ago
        self.assertFalse(self.tap())

    def test_a_slow_start_says_the_tap_counted(self):
        self.tap()
        delay, fn, args = self.timers[0]
        self.assertEqual(delay, self.m.NOTICE_AFTER_S)
        fn(*args)                                   # nothing on screen yet
        self.assertEqual(len(self.toasts), 1)

    def test_no_notice_once_sources_show_or_the_request_ended(self):
        self.tap()
        fn, args = self.timers[0][1:]
        self.visible = True
        fn(*args)                                   # POV's sources window is up
        self.visible = False
        self.playing = True
        fn(*args)                                   # already playing
        self.playing = False
        self.m.request_over()                       # POV's route returned (no results / cancelled)
        fn(*args)
        self.assertEqual(self.toasts, [])

    def test_a_later_request_keeps_its_own_notice(self):
        clock = iter([1000.0, 1001.0])
        mock.patch.object(self.m.time, 'time', lambda: next(clock)).start()
        self.addCleanup(mock.patch.stopall)
        self.tap()
        first = self.timers[0][1:]
        self.m.request_over()                       # fast navigation: the same interpreter
        self.assertFalse(self.tap(reused=True))
        second = self.timers[1][1:]
        first[0](*first[1]); second[0](*second[1])
        self.assertEqual(len(self.toasts), 1)       # only the request still running

    def test_dropped_taps_start_no_notice_timer(self):
        self.tap(); self.tap()
        self.assertEqual(len(self.timers), 1)


if __name__ == '__main__':
    unittest.main()
