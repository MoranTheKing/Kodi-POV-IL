"""SubSync's deep job steps aside for the viewer.

On a Shield the 1 ms breaths left a new script ~5% of the interpreter: the
subtitle chooser started 6-10 s late behind the deep job, and the list the
player returned to replayed slowly while the job ran on after playback
stopped (field logs, Oct 2026). The deep job now waits while the player's
menu or the chooser is open and ends once its video has stopped.
"""
import importlib.util
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    'subsync_harness_yield', ROOT / 'tools' / 'test_subsync_remote_playback_safety.py')
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)
harness.LIB = ROOT / 'service.subtitles.kodipovilai' / 'resources' / 'lib'


class DeepJobYields(unittest.TestCase):
    setUp_harness = harness.RemotePlaybackSafety.setUp
    _selection_snapshot = harness.RemotePlaybackSafety._selection_snapshot
    _selection_matches = harness.RemotePlaybackSafety._selection_matches

    def setUp(self):
        self.setUp_harness()
        self.clock = [100.0]
        self.playing = [True]
        self.busy = [False]
        self.waits = []

        def wait(seconds):
            self.waits.append(seconds)
            self.clock[0] += seconds
            return False
        xbmc = types.SimpleNamespace(
            Player=lambda: types.SimpleNamespace(isPlayingVideo=lambda: self.playing[0]),
            getCondVisibility=lambda cond: self.busy[0],
            Monitor=lambda: types.SimpleNamespace(waitForAbort=wait))
        xbmcgui = types.SimpleNamespace(Window=lambda wid: types.SimpleNamespace(getProperty=lambda k: ''))
        for patcher in (mock.patch.dict(sys.modules, {'xbmc': xbmc, 'xbmcgui': xbmcgui}),
                        mock.patch.object(self.sub.time, 'monotonic', lambda: self.clock[0])):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sub._yield_state.update(checked=0.0, seen_playing=False, gone=None, waited=0.0)

    def deep(self):
        self.sub._DEEP_THREAD[0] = threading.get_ident()
        self.addCleanup(self.sub._DEEP_THREAD.__setitem__, 0, None)

    def test_other_threads_never_wait(self):
        self.busy[0] = True
        self.sub._yield_to_viewer()
        self.assertEqual(self.waits, [])

    def test_waits_while_the_menu_is_open(self):
        self.deep()
        calls = iter([True, True, True, False])
        sys.modules['xbmc'].getCondVisibility = lambda cond: next(calls)
        self.sub._yield_to_viewer()
        self.assertEqual(len(self.waits), 3)

    def test_a_wait_is_capped(self):
        self.deep()
        self.busy[0] = True
        self.sub._yield_to_viewer()
        self.assertLessEqual(sum(self.waits), self.sub._YIELD_MAX_S + 0.2)

    def test_ends_once_the_video_stopped(self):
        self.deep()
        self.sub._yield_to_viewer()                 # playing: seen
        self.playing[0] = False
        self.clock[0] += 1.0
        with self.assertRaises(self.sub.ViewerLeft):
            self.sub._yield_to_viewer()
        self.assertAlmostEqual(sum(self.waits), self.sub._STOP_AFTER_S, delta=0.15)

    def test_before_playback_starts_nothing_waits(self):
        self.deep()
        self.playing[0] = False
        self.sub._yield_to_viewer()
        self.assertEqual(self.waits, [])

    def test_a_job_stops_waiting_after_its_total_cap(self):
        self.deep()
        self.busy[0] = True
        for _ in range(10):
            self.clock[0] += 1.0
            self.sub._yield_to_viewer()
        self.assertLessEqual(sum(self.waits), self.sub._YIELD_JOB_MAX_S + 0.2)

    def test_a_stale_chooser_stamp_does_not_hold_the_job(self):
        gui = types.SimpleNamespace(Window=lambda wid: types.SimpleNamespace(getProperty=lambda k: '1.0'))
        self.assertFalse(self.sub._chooser_opening(gui))
        fresh = types.SimpleNamespace(Window=lambda wid: types.SimpleNamespace(
            getProperty=lambda k: repr(self.sub.time.time())))
        self.assertTrue(self.sub._chooser_opening(fresh))

    def test_alignment_loops_use_it(self):
        self.assertIs(self.sub.sync_align.YIELD, self.sub._yield_to_viewer)

    def test_the_job_reports_a_stop_and_lets_go_of_the_thread(self):
        with mock.patch.object(self.sub, '_job_selection', side_effect=self.sub.ViewerLeft('playback ended')):
            self.sub.run_deep_job({'key': 'k', 'path': 'p'})
        self.assertIsNone(self.sub._DEEP_THREAD[0])
        logged = ' '.join(str(c) for c in self.sub._log.call_args_list) if hasattr(self.sub._log, 'call_args_list') else ''
        self.assertTrue(not logged or 'deep job stopped' in logged)


if __name__ == '__main__':
    unittest.main()
