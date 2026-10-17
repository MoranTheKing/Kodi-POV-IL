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
        win = types.SimpleNamespace(getProperty=lambda k: self.props.get(k, ''),
                                    setProperty=lambda k, v: self.props.__setitem__(k, v),
                                    clearProperty=lambda k: self.props.pop(k, None))
        self.toasts = []
        mods = {'xbmc': types.SimpleNamespace(Player=lambda: types.SimpleNamespace(isPlaying=lambda: self.playing),
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


if __name__ == '__main__':
    unittest.main()
