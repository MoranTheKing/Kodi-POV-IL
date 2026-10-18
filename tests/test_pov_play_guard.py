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
        self.visible, self.timers, self.builtins = False, [], []
        win = types.SimpleNamespace(getProperty=lambda k: self.props.get(k, ''),
                                    setProperty=lambda k, v: self.props.__setitem__(k, v),
                                    clearProperty=lambda k: self.props.pop(k, None))
        self.toasts = []
        mods = {'xbmc': types.SimpleNamespace(Player=lambda: types.SimpleNamespace(isPlaying=lambda: self.playing),
                                              getCondVisibility=lambda c: (True if 'notification' in c else self.visible),
                                              executebuiltin=lambda b: self.builtins.append(b),
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
        thread = mock.patch('threading.Thread', lambda target, args: types.SimpleNamespace(
            start=lambda: self.timers.append((target, args))))
        thread.start()
        self.addCleanup(thread.stop)

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
        self.assertIn('פרק אחר', self.toasts[-1][1])

    def test_a_stale_mark_does_not_block(self):
        self.props[self.m.PROPERTY] = repr(1.0)     # left by a killed request long ago
        self.assertFalse(self.tap())

    def test_the_notice_shows_at_once(self):
        self.tap()
        self.assertEqual(len(self.toasts), 1)
        self.assertEqual(len(self.timers), 1)        # its watcher

    def test_the_notice_is_taken_down_when_sources_show(self):
        self.tap()
        fn, args = self.timers[0]
        self.visible = True                         # POV's sources window is up
        fn(*args)
        self.assertEqual(self.builtins, ['Dialog.Close(notification,true)'])

    def test_the_notice_is_taken_down_when_the_request_ended(self):
        self.tap()
        fn, args = self.timers[0]
        self.m.request_over()                       # no results / cancelled
        fn(*args)
        self.assertEqual(len(self.builtins), 1)

    def test_a_watcher_never_outlives_its_notice(self):
        self.tap()
        fn, args = self.timers[0]
        sys.modules['xbmc'].Monitor = lambda: types.SimpleNamespace(waitForAbort=lambda s: False)
        fn(*args)                                   # nothing ever shows: gives up after NOTICE_S
        self.assertEqual(self.builtins, [])

    def test_no_notice_during_playback(self):
        self.playing = True                         # POV's own next episode
        self.assertFalse(self.tap())
        self.assertEqual(self.toasts, [])

    def test_dropped_taps_start_no_notice(self):
        self.tap(); self.tap()
        self.assertEqual(len(self.timers), 1)
        self.assertEqual(len(self.toasts), 2)       # the notice + "another episode is starting"

if __name__ == '__main__':
    unittest.main()
