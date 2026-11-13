"""The embedded track is read in windows that start where the viewer is
(MoranSubs 0.3.80).

Field report: "extracting the embedded subtitle takes half the film before
any translation shows". The first attempt at reading the head first (pulled
from 0.3.79 in review) handed the HTTP pass only the cues before a mark; that
pass records a cluster as finished once the cues it was handed came back, so
a cluster that straddled the mark lost its later cues for good. These tests
run the REAL _extract_cues_http, with only the network read replaced."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'service.subtitles.kodipovilai/resources/lib/embedded_extract.py'


def load():
    spec = importlib.util.spec_from_file_location('embedded_windows_test', MODULE)
    module = importlib.util.module_from_spec(spec)
    stubs = {name: types.ModuleType(name) for name in ('xbmc', 'xbmcaddon', 'xbmcvfs', 'xbmcgui')}
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


class Source(object):
    """As much of the HTTP source as the cue pass touches. A window scan reads nothing (an empty body:
    the pass defers)."""
    is_http = True
    total = 10 ** 9
    tripped = False
    reqs = 0
    http_reqs = 0
    fetched = 0
    _prefix = None            # never "healthy": one connection, in order
    _cue_time_ok = None
    _pace = 0.2
    _429_total = 0

    def __init__(self):
        self._stats = {}

    def fetched_now(self):
        return self.fetched

    def open_pool(self):
        return 1

    def close_pool(self):
        pass

    def read(self, offset, length):
        return b''


class Run(object):

    def __init__(self, ee, positions, prior=None, trip_at=None, abort_once_at=None, partial=()):
        self.ee = ee
        self.positions = positions
        self.fetches = []           # (cluster, [cue times]) as asked of the network
        self.saved = []
        self.cleared = []
        self.shown = []             # how many cues there were at each show()
        self.windows = []
        self.timelines = []
        self.progress = []
        self.prior = prior or ([], set(), set())
        self.trip_at = trip_at
        self.abort_once_at = abort_once_at
        self.partial = set(partial)       # clusters whose targeted fetch comes back one block short
        self.saved_scan = []
        self.aborts = 0
        self.src = Source()

    def abort(self):
        # the player stalls once: whatever runs AFTER the pass that saw it would carry on unhindered
        if self.abort_once_at is not None and len(self.fetches) >= self.abort_once_at and not self.aborts:
            self.aborts += 1
            return True
        return False

    def go(self, spans=(), resume_path='resume.bin', with_steps=True):
        entries = []
        spans = list(spans)

        def fetch(src, cpos, items, want, local, log):
            if self.trip_at is not None and len(self.fetches) >= self.trip_at:
                src.tripped = True
                return 0
            self.fetches.append((cpos, [t for _r, t in items]))
            local.extend((t, None, b'x') for _r, t in items)
            return len(items) - 1 if cpos in self.partial else len(items)

        def window():
            self.windows.append(len(entries))
            return spans.pop(0) if spans else None

        ee = self.ee
        steps = (window, lambda: self.shown.append(len(entries)), self.timelines.append) if with_steps else None
        with patch.object(ee, '_read_cues', lambda *a: (self.positions, True)), \
                patch.object(ee, '_fetch_cluster_blocks', fetch), \
                patch.object(ee, '_resume_identity', lambda *a: 'the-file'), \
                patch.object(ee, '_resume_load', lambda path, identity, log: (
                    list(self.prior[0]), set(self.prior[1]), set(self.prior[2]))), \
                patch.object(ee, '_resume_save', lambda path, identity, got, done, scan, log: (
                    self.saved.append((len(got), sorted(done))), self.saved_scan.append(sorted(scan)))), \
                patch.object(ee, '_resume_clear', lambda path: self.cleared.append(path)):
            ok = ee._extract_cues(self.src, [], 0, 3, entries, 0, 900.0, __import__('time').time(), self.abort,
                                  lambda m: None, lambda n, t: self.progress.append((n, t)),
                                  resume_path, 'S_TEXT/UTF8', steps)
        return ok, entries


def one_per_cluster(n, step=1000):
    # (cluster position, relative position, cue time in ticks)
    return [(1000 + 10 * i, 5, i * step) for i in range(n)]


class Windows(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ee = load()

    def test_a_cluster_that_straddles_the_end_of_a_window_keeps_every_cue(self):
        # cluster 2000 holds cues at 400, 450 and 900; the window ends at 500
        positions = [(1000, 5, 100), (2000, 5, 400), (2000, 9, 450), (2000, 14, 900), (3000, 5, 1500)]
        run = Run(self.ee, positions)
        ok, entries = run.go(spans=[(0, 500)])
        self.assertTrue(ok)
        self.assertEqual(sorted(e[0] for e in entries), [100, 400, 450, 900, 1500])     # none lost, none twice
        self.assertEqual(run.fetches[:2], [(1000, [100]), (2000, [400, 450, 900])])     # the WHOLE cluster
        self.assertEqual(run.fetches[2:], [(3000, [1500])])                             # the complete pass: the rest only
        self.assertEqual(run.shown, [4])

    def test_each_window_is_shown_and_saved_and_the_complete_pass_reads_only_the_rest(self):
        run = Run(self.ee, one_per_cluster(10))
        ok, entries = run.go(spans=[(0, 2500), (0, 5500)])
        self.assertTrue(ok)
        self.assertEqual(run.shown, [3, 6])
        self.assertEqual(run.saved, [(3, [1000, 1010, 1020]), (6, [1000, 1010, 1020, 1030, 1040, 1050])])
        self.assertEqual([c for c, _t in run.fetches], [1000 + 10 * i for i in range(10)])   # each exactly once
        self.assertEqual(len(entries), 10)
        self.assertEqual(run.cleared, ['resume.bin'])

    def test_a_window_starts_where_the_viewer_is_not_at_the_start_of_the_film(self):
        run = Run(self.ee, one_per_cluster(10))
        ok, entries = run.go(spans=[(5000, 7000)])
        self.assertTrue(ok)
        self.assertEqual([c for c, _t in run.fetches][:3], [1050, 1060, 1070])
        self.assertEqual(run.shown, [3])
        self.assertEqual(len(entries), 10)

    def test_a_window_that_cannot_be_finished_ends_the_extraction_and_nothing_follows_it(self):
        run = Run(self.ee, one_per_cluster(10), trip_at=2)
        ok, entries = run.go(spans=[(0, 4500), (0, 8500)])
        self.assertFalse(ok)
        self.assertEqual(len(run.fetches), 2)            # no second window, no complete pass
        self.assertEqual(run.shown, [])
        self.assertEqual(run.cleared, [])
        self.assertEqual(run.saved[-1], (2, [1000, 1010]))

    def test_an_aborted_window_is_not_followed_by_the_complete_pass(self):
        # the abort is over by the time anything else could run: a complete pass started now would read on
        run = Run(self.ee, one_per_cluster(10), abort_once_at=2)
        ok, entries = run.go(spans=[(0, 4500), (0, 8500)])
        self.assertFalse(ok)
        self.assertEqual(run.aborts, 1)
        self.assertEqual(len(run.fetches), 2)
        self.assertEqual(len(run.windows), 1)
        self.assertEqual(run.cleared, [])

    def test_a_window_with_no_cues_in_it_is_passed_over_and_the_next_one_is_asked_for(self):
        # a quiet opening: nothing is said in the first span
        positions = [(1000 + 10 * i, 5, 9000 + i * 1000) for i in range(6)]
        run = Run(self.ee, positions)
        ok, entries = run.go(spans=[(0, 2500), (0, 11500)])
        self.assertTrue(ok)
        self.assertEqual(run.shown, [0, 3])
        self.assertEqual(len(run.windows), 3)
        self.assertEqual(len(entries), 6)

    def test_the_window_that_is_all_that_is_left_is_the_complete_pass(self):
        run = Run(self.ee, one_per_cluster(6))
        ok, entries = run.go(spans=[(0, 2500), (0, 10 ** 9), (0, 10 ** 9)])
        self.assertTrue(ok)
        self.assertEqual(run.shown, [3])                 # the last span is not "shown": the whole track is returned
        self.assertEqual(len(run.windows), 2)
        self.assertEqual(run.cleared, ['resume.bin'])
        self.assertEqual(len(entries), 6)

    def test_clusters_an_earlier_attempt_finished_are_not_read_again(self):
        prior = ([(0, None, b'x'), (1000, None, b'x')], {1000, 1010}, set())
        run = Run(self.ee, one_per_cluster(8), prior=prior)
        ok, entries = run.go(spans=[(0, 3500)])
        self.assertTrue(ok)
        self.assertEqual([c for c, _t in run.fetches][:2], [1020, 1030])
        self.assertEqual(run.shown, [4])
        self.assertEqual(len(entries), 8)

    def test_a_window_already_read_by_an_earlier_attempt_is_shown_without_a_request(self):
        prior = ([(i * 1000, None, b'x') for i in range(4)], {1000, 1010, 1020, 1030}, set())
        run = Run(self.ee, one_per_cluster(8), prior=prior)
        run.go(spans=[(0, 3500)])
        self.assertEqual(run.shown, [4])
        self.assertEqual([c for c, _t in run.fetches], [1040, 1050, 1060, 1070])

    def test_a_cluster_left_for_a_scan_by_a_failed_window_is_remembered_for_the_next_attempt(self):
        # the targeted fetch of 1010 comes back short, its scan gets an empty body: the window fails
        run = Run(self.ee, one_per_cluster(10), partial={1010})
        ok, entries = run.go(spans=[(0, 2500)])
        self.assertFalse(ok)
        self.assertEqual(run.saved_scan[-1], [1010])           # the next attempt goes straight to the scan
        self.assertNotIn(1010, run.saved[-1][1])               # and does not count it finished

    def test_progress_after_a_window_that_skips_ahead_counts_what_came_before(self):
        run = Run(self.ee, one_per_cluster(10))
        run.go(spans=[(0, 2500), (7000, 9500)])
        counts = [n for n, _t in run.progress]
        self.assertEqual(counts, sorted(counts))
        self.assertIn((4, 10), run.progress)                   # 3 from the first window, then the first of the next

    def test_progress_is_about_the_whole_track_and_never_goes_back(self):
        run = Run(self.ee, one_per_cluster(10))
        run.go(spans=[(0, 2500), (0, 5500)])
        self.assertTrue(all(t == 10 for _n, t in run.progress))
        counts = [n for n, _t in run.progress]
        self.assertEqual(counts, sorted(counts))
        self.assertEqual(counts[-1], 10)
        self.assertNotIn((3, 3), run.progress)           # not "100%" of a window
        self.assertEqual(run.src._stats, {'done': 10, 'total': 10})

    def test_cues_without_times_get_the_complete_pass_only(self):
        positions = one_per_cluster(6)
        positions[4] = (1040, 5, None)
        run = Run(self.ee, positions)
        ok, entries = run.go(spans=[(0, 2500)])
        self.assertEqual((ok, run.windows, run.shown, len(entries)), (True, [], [], 6))
        self.assertEqual(run.timelines, [])

    def test_without_a_resume_file_there_are_no_windows(self):
        run = Run(self.ee, one_per_cluster(6))
        ok, entries = run.go(spans=[(0, 2500)], resume_path=None)
        self.assertEqual((ok, run.windows, run.shown, len(entries)), (True, [], [], 6))

    def test_no_steps_is_exactly_the_old_call(self):
        run = Run(self.ee, one_per_cluster(6))
        ok, entries = run.go(with_steps=False)
        self.assertEqual((ok, len(entries), run.saved, run.cleared), (True, 6, [], ['resume.bin']))

    def test_the_caller_is_told_every_cue_time_once_before_the_first_window(self):
        positions = [(3000, 5, 1500), (1000, 5, 100), (2000, 9, 450), (2000, 5, 400)]
        run = Run(self.ee, positions)
        run.go(spans=[(0, 500), (0, 1000)])
        self.assertEqual(run.timelines, [[100, 400, 450, 1500]])
        self.assertEqual(run.windows[0], 0)              # asked for after the timeline, before anything was read

    def test_a_timeline_that_raises_means_one_pass(self):
        run = Run(self.ee, one_per_cluster(6))

        def boom(ticks):
            raise RuntimeError('no')

        ok = self.ee._extract_in_windows(run.src, run.positions, [], 3, 900.0, 0.0, None, lambda m: None,
                                         None, set(), set(), (lambda: (0, 2500), lambda: None, boom),
                                         lambda: None)
        self.assertTrue(ok)

    def test_film_time_becomes_the_files_ticks_and_back(self):
        # a file whose tick is 2 ms and whose first frame sits at 10 s
        ee = self.ee
        got = {}
        entries = [(6000, None, b'Hello')]               # tick 6000 = 12 s in the file = 2 s of film
        window, show, timeline = ee._steps_in_ticks(
            (lambda: (2000, 152000), lambda text: got.setdefault('srt', text),
             lambda starts: got.setdefault('starts', starts)),
            entries, 2.0, 10000.0, 'S_TEXT/UTF8')
        self.assertEqual(window(), (6000.0, 81000.0))
        timeline([6000, 81000])
        self.assertEqual(got['starts'], [2000, 152000])
        show()
        self.assertIn('00:00:02,000 -->', got['srt'])
        self.assertIn('Hello', got['srt'])
        none = ee._steps_in_ticks((lambda: None, None, None), entries, 2.0, 10000.0, 'S_TEXT/UTF8')[0]
        self.assertIsNone(none())

    def test_a_window_ending_on_a_cue_takes_that_cue(self):
        # the caller's span ends 1 ms after the last cue it wants; through the tick conversion it must stay inside
        ee = self.ee
        for scale, origin in ((1.0, 0.0), (2.0, 10000.0), (0.4, 333.0), (1.0, 41.0)):
            ticks = [int((ms + origin) / scale) for ms in (2000, 6000, 10000)]
            starts = []
            window, _show, timeline = ee._steps_in_ticks(
                (lambda: (0, starts[1] + 1), None, starts.extend), [], scale, origin, 'S_TEXT/UTF8')
            timeline(ticks)
            low, high = window()
            self.assertEqual([t for t in ticks if low <= t <= high], ticks[:2], (scale, origin))

    def test_a_caller_that_never_says_stop_does_not_loop_for_ever(self):
        run = Run(self.ee, one_per_cluster(40))
        calls = {'n': 0}

        def window():
            calls['n'] += 1
            return (0, 500)

        ee = self.ee
        entries = []
        with patch.object(ee, '_extract_cues_http', lambda *a: True):
            ok = ee._extract_in_windows(run.src, run.positions, entries, 3, 900.0, 0.0, None, lambda m: None,
                                        None, set(), set(), (window, lambda: None, lambda ticks: None), lambda: None)
        self.assertTrue(ok)
        self.assertEqual(calls['n'], ee._WINDOWS_MAX)

    def test_a_window_that_raises_falls_back_to_the_complete_pass(self):
        run = Run(self.ee, one_per_cluster(6))

        def boom():
            raise RuntimeError('player gone')

        ee = self.ee
        ok = ee._extract_in_windows(run.src, run.positions, [], 3, 900.0, 0.0, None, lambda m: None,
                                    None, set(), set(), (boom, lambda: None, lambda ticks: None), lambda: None)
        self.assertTrue(ok)


if __name__ == '__main__':
    unittest.main()
