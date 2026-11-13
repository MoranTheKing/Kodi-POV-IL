"""Hebrew for the minutes the viewer is at, while the embedded track is still
being read (MoranSubs 0.3.80).

The first attempt (pulled from 0.3.79 in review) was checked by the add-on's
log and looked fine; on the screen nothing arrived after the first step, not
even the finished translation, because the viewer's handler ties what it
shows to one source id. The last class here runs the REAL handler
(default.py _handle_bg_translate_picker) and asserts on what reached the
player."""
import base64
import importlib.util
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_embedded_windows as windows  # noqa: E402  (the extractor, and its stand-in for an HTTP source)
ADDON = ROOT / 'service.subtitles.kodipovilai'


def load_translate():
    """translate.py without Kodi, as a private copy of the package."""
    xbmcgui = types.ModuleType('xbmcgui')
    xbmcgui.Window = lambda ident: types.SimpleNamespace(
        getProperty=lambda name: '', setProperty=lambda name, value: None, clearProperty=lambda name: None)
    stubs = {name: types.ModuleType(name) for name in ('xbmc', 'xbmcaddon', 'xbmcvfs', 'xbmcplugin')}
    stubs['xbmcgui'] = xbmcgui

    def ours(name):
        return name == 'resources' or name.startswith('resources.')
    kept = {name: sys.modules.pop(name) for name in list(sys.modules) if ours(name)}
    try:
        with patch.dict(sys.modules, stubs):
            sys.path.insert(0, str(ADDON))
            try:
                from resources.lib import translate
            finally:
                sys.path.pop(0)
    finally:
        for name in list(sys.modules):
            if ours(name):
                del sys.modules[name]
        sys.modules.update(kept)
    return translate


def stamp(ms):
    return '%02d:%02d:%02d,%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def cue(n, start_ms, text):
    return '%d\n%s --> %s\n%s' % (n, stamp(start_ms), stamp(start_ms + 1500), text)


def english(count, first_ms=0, every_ms=3000):
    """SRT of `count` cues, one every three seconds of film."""
    return '\n\n'.join(cue(i + 1, first_ms + i * every_ms, 'Line %d.' % (i + 1)) for i in range(count)) + '\n'


def every(seconds, minutes, first_ms=0):
    """Cue starts (ms): one every `seconds` for `minutes` of film."""
    return list(range(first_ms, minutes * 60000, int(seconds * 1000)))


def until(what, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        if what():
            return True
        time.sleep(0.01)
    return bool(what())


class Model(object):
    """A translator that answers 'שורה N' for 'Line N.'."""

    def __init__(self, answer=None):
        self.asked = []                 # the cue numbers of each request
        self.before = []
        self.answer = answer
        self.gate = threading.Event()
        self.gate.set()

    def __call__(self, blocks, before):
        self.gate.wait(5)
        texts = [b.split('\n', 2)[2] for b in blocks]
        self.asked.append(texts)
        self.before.append(list(before))
        if self.answer is not None:
            return self.answer(blocks, len(self.asked))
        return dict((i, text.replace('Line', 'שורה')) for i, text in enumerate(texts))


class Steps(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.t = load_translate()

    def make(self, model, at_ms=0, cues=None, restore=None):
        self.place = {'ms': at_ms}
        self.now = {'s': 1000.0}
        self.views = []
        steps = self.t._EmbeddedSteps(lambda: self.place['ms'], model, self.views.append, restore=restore,
                                      clock=lambda: self.now['s'])
        if cues is not None:
            # the extractor hands every line's time over before the first window; without it (no timeline)
            # the view's last line is all the view goes by
            steps.timeline(cues)
        self.addCleanup(steps.finish)
        return steps

    def watch(self, seconds):
        """The film plays for `seconds` while a window is read."""
        self.now['s'] += seconds
        self.place['ms'] += int(seconds * 1000)

    # -- the windows

    def next_window(self, steps):
        """window(), then the feed that follows a window once it is read."""
        span = steps.window()
        steps.feed('')
        return span

    def test_a_jump_back_into_a_stretch_not_read_starts_a_window_there(self):
        # picked at minute 30, two windows read; the viewer goes back to minute 20
        cues = every(3.0, 100)
        steps = self.make(None, at_ms=30 * 60000, cues=cues)
        self.next_window(steps)
        self.watch(60)
        self.next_window(steps)
        self.place['ms'] = 20 * 60000
        self.watch(1)
        low, high = self.next_window(steps)
        self.assertEqual(low, 20 * 60000 + 1000 - 15000)
        self.assertLessEqual(high, 20 * 60000 + 1000 + 150000 + 1)        # small: the viewer is waiting

    def test_a_jump_back_into_a_stretch_read_carries_on_where_the_reading_stops(self):
        cues = every(3.0, 100)
        steps = self.make(None, at_ms=30 * 60000, cues=cues)
        first = self.next_window(steps)
        self.watch(60)
        second = self.next_window(steps)
        self.place['ms'] = 30 * 60000 + 10000          # back, but inside what was read
        self.watch(5)
        low, high = self.next_window(steps)
        self.assertGreater(high, second[1])
        self.assertEqual(low, self.place['ms'] - 15000)

    def test_the_first_window_is_two_and_a_half_minutes_from_where_the_viewer_is(self):
        steps = self.make(None, at_ms=20 * 60000, cues=every(3.0, 45))
        self.assertEqual(self.next_window(steps), (20 * 60000 - 15000, 20 * 60000 + 150000 + 1))
        self.assertEqual(steps.windows, 1)

    def test_a_quiet_stretch_does_not_make_the_first_window_empty(self):
        # nothing is said in the film's first three minutes
        cues = [180000 + i * 3000 for i in range(600)]
        steps = self.make(None, cues=cues)
        self.assertEqual(self.next_window(steps), (0, cues[self.t._STEPS_FIRST_MIN_CUES - 1] + 1))

    def test_dense_dialogue_does_not_make_the_first_window_long_to_read(self):
        cues = every(1.0, 45)
        steps = self.make(None, cues=cues)
        self.assertEqual(self.next_window(steps), (0, cues[self.t._STEPS_FIRST_MAX_CUES - 1] + 1))

    def test_the_next_window_is_the_cues_that_can_be_read_in_sixty_percent_of_the_lead(self):
        # measured in the QA Kodi: the first window (150 s of film) read in 68 s
        cues = every(3.0, 45)
        steps = self.make(None, cues=cues)
        self.assertEqual(self.next_window(steps), (0, 150001))            # cues 0..50
        self.watch(68)
        rate = 51 / 68.0                                         # cues a second
        lead = (cues[51] - 68000) / 1000.0                       # until the viewer reaches the first cue not read
        count = int(0.6 * rate * lead)
        self.assertEqual(count, 38)
        self.assertEqual(self.next_window(steps), (68000 - 15000, cues[51 + count - 1] + 1))

    def test_a_quiet_minute_is_not_mistaken_for_a_fast_provider(self):
        # the second window holds two minutes of silence: sized by film time it "read 120 s in no time"
        cues = [c for c in every(4.0, 45) if not 150000 <= c < 270000]
        steps = self.make(None, cues=cues)
        first = self.next_window(steps)[1]
        n1 = sum(1 for c in cues if c < first)
        self.watch(n1 / 0.55)
        second = self.next_window(steps)[1]
        n2 = sum(1 for c in cues if first <= c < second)
        self.watch(n2 / 0.55)
        third = self.next_window(steps)[1]
        n3 = sum(1 for c in cues if second <= c < third)
        self.assertLess(n3, 3 * n2)
        self.assertLess(n3 / 0.55, (second - self.place['ms']) / 1000.0)      # read before the viewer gets there

    def test_a_window_is_never_under_ten_cues_nor_over_eight_times_the_last(self):
        t = self.t
        cues = every(3.0, 300)
        steps = self.make(None, cues=cues)
        self.next_window(steps)                               # 51 cues
        self.watch(149)                              # read at the film's own pace: four seconds of lead left
        low, high = self.next_window(steps)
        self.assertEqual(high, cues[51 + t._STEPS_MIN_CUES - 1] + 1)
        steps = self.make(None, cues=cues)
        self.next_window(steps)
        self.watch(3)                                # 17 cues a second
        self.assertEqual(self.next_window(steps)[1], cues[51 + t._STEPS_GROW_MAX * 51 - 1] + 1)

    def test_a_window_read_in_no_time_measures_nothing(self):
        # it was already in the resume file of an earlier attempt
        cues = every(3.0, 300)
        steps = self.make(None, cues=cues)
        self.next_window(steps)
        self.watch(0.5)
        self.assertEqual(self.next_window(steps)[1], cues[51 + 2 * 51 - 1] + 1)       # twice the last, no more
        self.watch(100)                              # 102 cues in 100 s: this one is a measurement
        lead = (cues[153] - self.place['ms']) / 1000.0
        self.assertEqual(self.next_window(steps)[1], cues[153 + int(0.6 * 1.02 * lead) - 1] + 1)

    def test_a_window_follows_a_viewer_who_has_passed_everything_read(self):
        steps = self.make(None, cues=every(3.0, 45))
        self.next_window(steps)                               # to 2.5 min
        self.place['ms'] = 10 * 60000                # a jump ahead, or a provider slower than the film
        self.assertEqual(self.next_window(steps), (10 * 60000 - 15000, 12.5 * 60000 + 1))

    def test_the_last_window_is_everything_ahead_and_then_there_are_no_more(self):
        cues = every(3.0, 12)
        steps = self.make(None, at_ms=5 * 60000, cues=cues)
        self.assertEqual(self.next_window(steps)[1], 7.5 * 60000 + 1)
        self.watch(10)                               # 5.6 cues a second: what is left fits one window
        last = self.next_window(steps)
        self.assertEqual(last, (5 * 60000 + 10000 - 15000, cues[-1] + 1))
        self.assertIsNone(self.next_window(steps))            # what is behind the viewer: the complete pass
        self.assertIsNone(self.next_window(steps))

    def test_a_handful_of_cues_left_ahead_go_with_the_window(self):
        t = self.t
        cues = every(3.0, 45)[:51 + t._STEPS_TAIL_CUES]
        steps = self.make(None, cues=cues)
        self.assertEqual(self.next_window(steps)[1], cues[-1] + 1)
        self.assertIsNone(self.next_window(steps))

    def test_a_viewer_past_the_last_cue_gets_no_window(self):
        steps = self.make(None, at_ms=50 * 60000, cues=every(3.0, 45))
        self.assertIsNone(self.next_window(steps))

    def test_no_window_once_the_player_is_gone_or_without_the_cue_times(self):
        steps = self.make(None, cues=every(3.0, 45))
        self.place['ms'] = None
        self.assertIsNone(self.next_window(steps))
        steps = self.make(None, cues=[])
        self.assertIsNone(self.next_window(steps))

    # -- the whole reading, with the real extractor loop

    def read_film(self, cues, per_cue_s, at_ms=0):
        """The REAL _EmbeddedSteps.window() and the REAL embedded_extract._extract_in_windows; only the
        network pass is replaced, by a clock that charges `per_cue_s` for every cue read while the film
        plays. Returns the cues the viewer reached before a view held them (after the first view, before
        the whole track was in) and the spans asked for."""
        ee = windows.load()
        clock = {'s': 0.0}
        position = lambda: int(at_ms + clock['s'] * 1000)
        steps = self.t._EmbeddedSteps(position, None, lambda text: None, clock=lambda: clock['s'])
        positions = [(1000 + 10 * i, 5, ms) for i, ms in enumerate(cues)]      # 1 tick = 1 ms
        done, fed_at, feeds, spans = set(), {}, [], []

        def http(src, part, entries, want, deadline_s, t0, abort_cb, log, progress_cb, finished, scan):
            for cpos, _rel, _ms in part:
                if cpos not in finished:
                    clock['s'] += per_cue_s
                    finished.add(cpos)
            return True

        def window():
            span = steps.window()
            if span:
                spans.append((clock['s'], span[0], span[1]))
            return span

        def show():
            steps.feed('')
            feeds.append(clock['s'])
            for cpos in done:
                fed_at.setdefault(cpos, clock['s'])

        with patch.object(ee, '_extract_cues_http', http):
            ee._extract_in_windows(windows.Source(), positions, [], 3, 900.0, 0.0, None, lambda m: None, None,
                                   done, set(), (window, show, steps.timeline), lambda: None)
        clock['s'] += per_cue_s * sum(1 for p in positions if p[0] not in done)
        whole_track = clock['s']
        first_view = (feeds[0] + 8.0) if feeds else None                        # the first request's answer
        missed = []
        for cpos, _rel, ms in positions:
            reached = (ms - at_ms) / 1000.0
            if ms < at_ms or first_view is None or reached < first_view or reached > whole_track:
                continue
            if fed_at.get(cpos, whole_track) > reached:
                missed.append(ms)
        return missed, spans, first_view

    def test_the_rate_measured_in_kodi_keeps_the_view_ahead_of_the_viewer(self):
        missed, spans, first_view = self.read_film(every(4.0, 45), 1 / 0.55)    # 2.2 times real time
        self.assertEqual(missed, [])
        self.assertLess(first_view, 90)

    def test_so_do_two_quiet_minutes_wherever_they_fall(self):
        for quiet in ((150, 270), (258, 370), (600, 720)):
            cues = [c for c in every(4.0, 45) if not quiet[0] * 1000 <= c < quiet[1] * 1000]
            missed, spans, _first = self.read_film(cues, 1 / 0.55)
            self.assertEqual(missed, [], quiet)

    def test_and_a_film_that_opens_with_three_minutes_of_no_dialogue(self):
        cues = [c for c in every(4.0, 100) if c >= 180000]
        missed, spans, first_view = self.read_film(cues, 1 / 0.55)
        self.assertEqual(missed, [])
        self.assertLess(first_view, 60)                  # 15 cues, not 20 minutes of film

    def test_and_a_viewer_who_starts_in_the_middle_of_the_film(self):
        missed, spans, first_view = self.read_film(every(4.0, 100), 1 / 0.55, at_ms=40 * 60000)
        self.assertEqual(missed, [])
        self.assertEqual(spans[0][1], 40 * 60000 - 15000)

    def test_a_provider_barely_faster_than_the_film_is_still_kept_ahead_of(self):
        # the slowest pace the extractor falls to (2 s a request) and dense dialogue: 1.25 times real time
        missed, spans, _first = self.read_film(every(2.5, 45), 2.0)
        self.assertEqual(missed, [])

    def test_a_fast_provider_gets_a_handful_of_windows(self):
        missed, spans, _first = self.read_film(every(3.0, 45), 0.25)            # 4 cues a second
        self.assertEqual(missed, [])
        self.assertLessEqual(len(spans), 5)

    # -- the embedded track back on screen

    def shown_view(self, restore, count=10):
        steps = self.make(Model(), restore=restore, cues=every(3.0, 45))
        steps.feed(english(count))
        self.assertTrue(until(lambda: steps.on_screen and 'שורה %d.' % count in self.views[-1]))
        return steps

    def test_the_embedded_track_goes_back_when_the_viewer_passes_the_last_line_read(self):
        back = []
        steps = self.shown_view(lambda: back.append(self.place['ms']))
        self.place['ms'] = 27000                     # the view's last cue starts at 27 s
        steps.check()
        self.assertEqual(back, [])
        self.place['ms'] = 28500
        steps.check()
        self.assertEqual(back, [28500])
        self.assertFalse(steps.on_screen)
        steps.check()                                # once
        self.assertEqual((back, steps.handed_back), ([28500], 1))

    def test_and_the_view_returns_when_it_has_a_hebrew_line_ahead_again(self):
        back = []
        steps = self.shown_view(lambda: back.append(1))
        self.place['ms'] = 40000
        steps.check()
        shown = len(self.views)
        steps.feed(english(12))                      # two more cues, both behind the viewer
        self.assertTrue(until(lambda: len(steps._he) == 12))
        time.sleep(0.05)
        self.assertEqual(len(self.views), shown)
        self.assertFalse(steps.on_screen)
        steps.feed(english(20))                      # cues to 57 s: ahead
        self.assertTrue(until(lambda: steps.on_screen))
        self.assertIn('שורה 20.', self.views[-1])
        self.assertEqual(back, [1])

    def test_the_view_needs_twenty_seconds_read_ahead_of_the_viewer(self):
        steps = self.make(Model(), cues=every(3.0, 45))
        steps.feed(english(6))                       # read to 15 s, the next line at 18 s
        time.sleep(0.2)
        self.assertEqual(self.views, [])
        steps.feed(english(7))                       # the next line not read is at 21 s
        self.assertTrue(until(lambda: steps.on_screen))

    def test_the_embedded_track_goes_back_just_before_a_line_not_read_is_reached(self):
        back = []
        steps = self.make(Model(), cues=every(3.0, 45), restore=lambda: back.append(self.place['ms']))
        steps.feed(english(10))                      # read to 27 s; 30 s is not
        self.assertTrue(until(lambda: steps.on_screen))
        self.place['ms'] = 27000
        steps.check()
        self.assertEqual(back, [])
        self.place['ms'] = 27600                     # the line at 30 s would be reached before the next check
        steps.check()
        self.assertEqual(back, [27600])

    def test_the_embedded_track_goes_back_when_the_viewer_jumps_back_to_a_stretch_not_read(self):
        back = []
        steps = self.make(Model(), at_ms=20 * 60000, cues=every(3.0, 45),
                          restore=lambda: back.append(self.place['ms']))
        steps.feed('\n\n'.join(cue(400 + i, 20 * 60000 + 3000 * i, 'Line %d.' % (400 + i)) for i in range(20)))
        self.assertTrue(until(lambda: steps.on_screen))
        self.place['ms'] = 20 * 60000 + 30000        # inside what was read
        steps.check()
        self.assertEqual(back, [])
        self.place['ms'] = 10 * 60000                # before the pick: the view has nothing there
        steps.check()
        self.assertEqual(back, [10 * 60000])

    def test_a_window_still_being_read_does_not_count_as_read(self):
        # its lines count once the feed after it arrives, not when it is asked for
        back = []
        steps = self.make(Model(), cues=every(3.0, 45), restore=lambda: back.append(1))
        steps.window()
        steps.feed(english(51))                      # the first window, read: 0-150 s
        self.assertTrue(until(lambda: steps.on_screen))
        self.watch(60)
        steps.window()                               # the next one, asked for and being read
        self.place['ms'] = 151000                    # the line at 153 s is not read yet
        steps.check()
        self.assertEqual(back, [1])

    def test_the_view_comes_back_from_check_when_the_viewer_returns_to_what_it_has(self):
        back = []
        steps = self.shown_view(lambda: back.append(1))
        self.place['ms'] = 10 * 60000                # a jump ahead: the embedded track
        steps.check()
        self.assertFalse(steps.on_screen)
        shown = len(self.views)
        self.place['ms'] = 0                         # and back to where the view has Hebrew
        steps.check()
        self.assertTrue(steps.on_screen)
        self.assertEqual(len(self.views), shown + 1)

    def test_no_view_while_the_player_gives_no_position(self):
        model = Model()
        steps = self.make(model, cues=every(3.0, 45))
        self.place['ms'] = None
        steps.feed(english(20))
        self.assertTrue(until(lambda: len(model.asked) == 1))
        time.sleep(0.1)
        self.assertEqual(self.views, [])

    def test_the_last_feed_is_shown_but_asks_for_nothing(self):
        model = Model()
        steps = self.make(model)
        steps.feed(english(5))
        self.assertTrue(until(lambda: steps.on_screen and len(model.asked) == 1))
        steps.feed(english(120), translate=False)
        self.assertIn('Line 120.', self.views[-1])
        steps._wake.set()                            # the worker's own two-second wait ends
        time.sleep(0.3)
        self.assertEqual(len(model.asked), 1)

    def test_nothing_is_asked_after_finish_even_with_a_batch_in_hand(self):
        model = Model()
        steps = self.make(model)
        take = steps._next_batch

        def batch_then_finish():
            got = take()
            steps._stop.set()                        # finish() lands between the batch and the request
            return got
        steps._next_batch = batch_then_finish
        steps.feed(english(120))
        time.sleep(0.3)
        self.assertEqual(model.asked, [])
        self.assertEqual(steps.requests, 0)

    def test_a_watcher_does_this_while_the_reading_goes_on(self):
        back = []
        with patch.object(self.t, '_STEPS_WATCH_S', 0.02):
            steps = self.shown_view(lambda: back.append(1))
            self.assertIsNotNone(steps._watcher)
            self.place['ms'] = 60000
            self.assertTrue(until(lambda: back == [1]))
            steps.finish()
            self.assertTrue(until(lambda: not steps._watcher.is_alive()))

    def test_backing_out_puts_the_embedded_track_back_once(self):
        back = []
        steps = self.shown_view(lambda: back.append(1))
        steps.finish()
        steps.back_out()
        steps.back_out()
        self.assertEqual(back, [1])
        self.assertFalse(steps.on_screen)

    def test_nothing_to_put_back_when_no_view_was_shown_or_there_is_no_way_to(self):
        back = []
        steps = self.make(None, restore=lambda: back.append(1))
        steps.feed(english(10))
        steps.finish()
        steps.back_out()
        self.assertEqual(back, [])
        steps = self.shown_view(None)                # the on-play pick: nothing was on screen before the view
        self.assertIsNone(steps._watcher)
        self.place['ms'] = 60000
        steps.check()
        steps.finish()
        steps.back_out()
        self.assertTrue(steps.on_screen)

    def test_a_restore_that_raises_is_logged_and_the_view_stays_the_views(self):
        def boom():
            raise RuntimeError('player')
        steps = self.shown_view(boom)
        self.place['ms'] = 60000
        steps.check()
        self.assertTrue(steps.on_screen)

    # -- the views

    def test_nothing_is_shown_before_the_first_hebrew_line(self):
        model = Model()
        model.gate.clear()
        steps = self.make(model)
        steps.feed(english(10))
        time.sleep(0.1)
        self.assertEqual(self.views, [])             # the embedded track itself is still on screen
        model.gate.set()
        self.assertTrue(until(lambda: self.views))
        self.assertIn('שורה 1.', self.views[0])
        self.assertIn('שורה 10.', self.views[0])

    def test_the_first_view_waits_until_the_line_the_viewer_is_at_was_read(self):
        # the viewer jumped to minute 20 while the first window (from minute 0) was being read
        cues = every(3.0, 1) + [20 * 60000 + 5000, 20 * 60000 + 30000, 20 * 60000 + 60000]
        model = Model()
        steps = self.make(model, at_ms=20 * 60000, cues=cues)
        steps.feed(english(10))
        time.sleep(0.2)
        self.assertEqual(model.asked, [])            # all behind the viewer: left to the full translation
        self.assertEqual(self.views, [])             # the embedded track still has the line being spoken
        later = lambda n: '\n\n'.join(cue(11 + i, 20 * 60000 + 5000 + 25000 * i, 'Line %d.' % (11 + i))
                                        for i in range(n))
        steps.feed(english(10) + '\n' + later(1) + '\n')
        self.assertTrue(until(lambda: self.views and 'שורה 11.' in self.views[-1]))
        self.assertNotIn('שורה 1.', self.views[-1])
        steps.feed(english(10) + '\n' + later(2) + '\n')      # once shown, every feed updates it
        self.assertTrue(until(lambda: 'שורה 12.' in self.views[-1]))

    def test_no_view_while_a_stretch_not_read_lies_between_the_viewer_and_the_hebrew(self):
        # read: minutes 0-0.5 and 30-30.5 (an earlier jump); the viewer is back at minute 10
        cues = every(3.0, 40)
        model = Model()
        steps = self.make(model, at_ms=10 * 60000, cues=cues)
        far = '\n\n'.join(cue(600 + i, 30 * 60000 + 3000 * i, 'Line %d.' % (600 + i)) for i in range(10))
        steps.feed(english(10) + '\n' + far + '\n')
        self.assertTrue(until(lambda: len(steps._he) == 10))
        time.sleep(0.1)
        self.assertEqual(self.views, [])

    def test_new_lines_are_shown_at_once_in_their_own_language_and_then_in_hebrew(self):
        model = Model()
        steps = self.make(model)
        steps.feed(english(4))
        self.assertTrue(until(lambda: self.views))
        model.gate.clear()
        steps.feed(english(8))
        self.assertTrue(until(lambda: len(self.views) >= 2))
        self.assertIn('שורה 4.', self.views[1])
        self.assertIn('Line 8.', self.views[1])      # read, not translated yet -- still better than no line
        model.gate.set()
        self.assertTrue(until(lambda: 'שורה 8.' in self.views[-1]))
        self.assertNotIn('Line', self.views[-1])

    def test_a_view_is_a_whole_srt_with_the_cues_own_times(self):
        steps = self.make(Model(), at_ms=600000)
        steps.feed(english(3, first_ms=600000))
        self.assertTrue(until(lambda: self.views))
        blocks = self.t.srt.parse_blocks(self.views[-1])
        self.assertEqual(len(blocks), 3)
        self.assertEqual([self.t._srt_start_ms(b) for b in blocks], [600000, 603000, 606000])

    def test_fifty_cues_a_request_with_the_lines_before_them_as_context(self):
        model = Model()
        steps = self.make(model)
        steps.feed(english(120))
        self.assertTrue(until(lambda: len(model.asked) == 3 and 'שורה 120.' in (self.views or [''])[-1]))
        self.assertEqual([len(a) for a in model.asked], [50, 50, 20])
        self.assertEqual(model.before[0], [])
        self.assertEqual(model.before[1], ['Line 48.', 'Line 49.', 'Line 50.'])

    def test_the_lines_the_viewer_reaches_next_are_translated_first(self):
        # an attempt carried on from the resume file: 200 cues are there at once, the viewer is at minute 5
        model = Model()
        model.gate.clear()
        steps = self.make(model, at_ms=5 * 60000)
        steps.feed(english(200))                     # one every 3 s: minute 5 is cue 101
        model.gate.set()
        self.assertTrue(until(lambda: len(model.asked) >= 1))
        self.assertEqual(model.asked[0][0], 'Line 96.')      # 15 s behind the viewer
        self.assertTrue(until(lambda: len(model.asked) == 3))
        time.sleep(0.1)
        self.assertEqual([a[0] for a in model.asked], ['Line 96.', 'Line 146.', 'Line 196.'])
        # what is behind the viewer is left to the full translation: no request for it
        self.assertEqual(len(model.asked), 3)

    # -- when the model does not answer

    def test_a_cue_answered_without_hebrew_keeps_its_line_and_is_not_asked_again(self):
        def answer(blocks, n):
            return dict((i, '' if '♪' in b else 'שלום') for i, b in enumerate(blocks))
        model = Model(answer)
        steps = self.make(model)
        steps.feed(cue(1, 0, 'Hello.') + '\n\n' + cue(2, 3000, '♪') + '\n')
        self.assertTrue(until(lambda: self.views))
        time.sleep(0.2)
        self.assertEqual(len(model.asked), 1)
        self.assertIn('♪', self.views[-1])

    def test_a_cue_missing_from_the_answer_is_asked_once_more(self):
        def answer(blocks, n):
            return {0: 'שלום'} if n == 1 else dict((i, 'ושוב') for i in range(len(blocks)))
        model = Model(answer)
        steps = self.make(model)
        steps.feed(english(3))
        self.assertTrue(until(lambda: len(model.asked) == 2))
        self.assertEqual(model.asked[1], ['Line 2.', 'Line 3.'])
        self.assertTrue(until(lambda: self.views and 'Line' not in self.views[-1]))

    def test_none_stops_the_asking_for_good(self):
        model = Model(lambda blocks, n: None)        # no quota, no key, cancelled
        steps = self.make(model)
        steps.feed(english(5))
        self.assertTrue(until(lambda: len(model.asked) == 1))
        steps.feed(english(10))
        time.sleep(0.2)
        self.assertEqual(len(model.asked), 1)
        self.assertEqual(self.views, [])
        self.assertEqual(steps.finish(), {})

    def test_three_failed_requests_in_a_row_stop_the_asking(self):
        model = Model(lambda blocks, n: {})
        steps = self.make(model)
        with patch.object(steps._stop, 'wait', lambda seconds: None):
            steps.feed(english(200))
            self.assertTrue(until(lambda: steps._dead))
        self.assertEqual(len(model.asked), self.t._STEPS_GIVE_UP)
        self.assertEqual(self.views, [])

    def test_a_translator_that_raises_is_a_failed_request_not_a_crash(self):
        def answer(blocks, n):
            if n == 1:
                raise RuntimeError('boom')
            return dict((i, 'שלום') for i in range(len(blocks)))
        steps = self.make(Model(answer))
        with patch.object(steps._stop, 'wait', lambda seconds: None):
            steps.feed(english(3))
            self.assertTrue(until(lambda: self.views))

    def test_without_a_translator_nothing_is_shown_and_no_thread_starts(self):
        steps = self.make(None)                      # no key, or Google chosen as the translator
        steps.feed(english(10))
        self.assertEqual(self.views, [])
        self.assertIsNone(steps._thread)

    # -- the end

    def test_finish_returns_the_hebrew_by_start_and_nothing_is_shown_after_it(self):
        model = Model()
        steps = self.make(model)
        steps.feed(english(4))
        self.assertTrue(until(lambda: self.views))
        model.gate.clear()
        steps.feed(english(8))                       # a request is in the air
        self.assertTrue(until(lambda: len(self.views) == 2))
        he = steps.finish()
        model.gate.set()
        time.sleep(0.2)
        self.assertEqual(len(self.views), 2)
        self.assertEqual(he, {0: 'שורה 1.', 3000: 'שורה 2.', 6000: 'שורה 3.', 9000: 'שורה 4.'})
        steps.feed(english(12))
        self.assertEqual(len(self.views), 2)

    def test_two_cues_with_one_start_are_left_as_they_are(self):
        model = Model()
        steps = self.make(model)
        steps.feed(cue(1, 0, 'Up.') + '\n\n' + cue(2, 0, 'Down.') + '\n\n' + cue(3, 3000, 'Line 3.') + '\n')
        self.assertTrue(until(lambda: self.views))
        self.assertEqual(model.asked, [['Line 3.']])
        self.assertEqual(steps.finish(), {3000: 'שורה 3.'})

    def test_a_show_that_raises_does_not_end_the_worker(self):
        model = Model()
        calls = []

        def show(text):
            calls.append(text)
            if len(calls) == 1:
                raise OSError('disk')
        steps = self.t._EmbeddedSteps(lambda: 0, model, show)
        self.addCleanup(steps.finish)
        steps.feed(english(3))
        self.assertTrue(until(lambda: len(calls) == 1))
        steps.feed(english(6))
        self.assertTrue(until(lambda: len(calls) >= 3))


class OnScreen(unittest.TestCase):
    """What the viewer has on screen for every line reached while the track is read: the REAL
    _EmbeddedSteps (window, feed, the view, check, the worker with a model that answers at once) and the
    REAL embedded_extract._extract_in_windows; the network pass is a clock charging a fixed time a line
    while the film plays, check() is called every 2 s of that clock as the watcher would (review of 0.3.80,
    round 2: a jump back to before the pick left 146 lines with nothing on screen)."""

    @classmethod
    def setUpClass(cls):
        cls.t = load_translate()
        cls.ee = windows.load()

    def simulate(self, cues, per_cue_s, at_ms=0, seeks=()):
        t, ee = self.t, self.ee
        clock = {'s': 0.0}
        seeks = sorted(seeks)

        def position():
            base_t, base_ms = 0.0, at_ms
            for when, to_ms in seeks:
                if when <= clock['s']:
                    base_t, base_ms = when, to_ms
            return int(base_ms + (clock['s'] - base_t) * 1000)

        shown = {'starts': set()}
        backs = []

        def show(text):
            shown['starts'] = set(t._srt_start_ms(b) for b in t.srt.parse_blocks(text))

        model = lambda blocks, before: dict((i, 'שורה') for i in range(len(blocks)))
        with patch.object(t, '_STEPS_WATCH_S', 3600.0):
            steps = t._EmbeddedSteps(position, model, show, restore=lambda: backs.append(clock['s']),
                                     clock=lambda: clock['s'])
        self.addCleanup(steps.finish)
        positions = [(1000 + 10 * i, 5, ms) for i, ms in enumerate(cues)]
        done = set()
        tally = {'embedded': 0, 'view': 0, 'nothing': 0}
        state = {'checked': 0.0}

        def advance(seconds):
            end = clock['s'] + seconds
            while clock['s'] < end:
                step = min(0.5, end - clock['s'])
                before = position()
                clock['s'] += step
                after = position()
                crossed = any(clock['s'] - step < when <= clock['s'] for when, _to in seeks)
                if after >= before and not crossed:
                    for ms in cues:
                        if before < ms <= after:
                            if not steps.on_screen:
                                tally['embedded'] += 1
                            elif ms in shown['starts']:
                                tally['view'] += 1
                            else:
                                tally['nothing'] += 1
                if clock['s'] - state['checked'] >= 2.0:
                    state['checked'] = clock['s']
                    steps.check()

        def http(src, part, entries, want, deadline_s, t0, abort_cb, log, progress_cb, finished, scan):
            for cpos, _rel, _ms in part:
                if cpos not in finished:
                    advance(per_cue_s)
                    finished.add(cpos)
            return True

        def feed():
            read = sorted(ms for cpos, _rel, ms in positions if cpos in done)
            steps.feed('\n\n'.join(cue(i + 1, ms, 'Line.') for i, ms in enumerate(read)) + '\n')
            until(lambda: len(steps._he) >= sum(1 for ms in read if ms >= position() - 15000))
            time.sleep(0.01)

        with patch.object(ee, '_extract_cues_http', http):
            ee._extract_in_windows(windows.Source(), positions, [], 3, 900.0, 0.0, None, lambda m: None, None,
                                   done, set(), (steps.window, feed, steps.timeline), lambda: None)
            http(None, positions, None, None, None, None, None, None, None, done, None)     # the complete pass
        steps.finish()
        return tally, backs

    def film(self, minutes, every_s):
        return [int(2000 + i * every_s * 1000) for i in range(int(minutes * 60 / every_s))]

    def test_no_seek(self):
        tally, backs = self.simulate(self.film(100, 4.0), 1 / 0.55)
        self.assertEqual(tally['nothing'], 0, tally)
        self.assertGreater(tally['view'], 100)

    def test_back_to_before_the_pick(self):
        # picked at minute 30; at 100 s the viewer goes back to minute 20
        tally, backs = self.simulate(self.film(100, 4.0), 1 / 0.55, at_ms=30 * 60000, seeks=[(100.0, 20 * 60000)])
        self.assertLessEqual(tally['nothing'], 1, tally)          # until the next check, 2 s at most
        self.assertTrue(backs)
        self.assertGreater(tally['view'], 100)

    def test_ahead_and_back(self):
        # from the start; at 100 s a jump to minute 50; at 300 s back to minute 30
        tally, backs = self.simulate(self.film(100, 4.0), 1 / 0.55, seeks=[(100.0, 50 * 60000), (300.0, 30 * 60000)])
        self.assertLessEqual(tally['nothing'], 2, tally)
        self.assertGreater(tally['view'], 100)

    def test_back_ninety_seconds(self):
        tally, backs = self.simulate(self.film(100, 4.0), 1 / 0.55, at_ms=30 * 60000,
                                     seeks=[(100.0, 30 * 60000 + 100000 - 90000)])
        self.assertLessEqual(tally['nothing'], 1, tally)

    def test_a_provider_as_fast_as_the_film_does_not_switch_back_and_forth(self):
        tally, backs = self.simulate(self.film(45, 2.5), 2.5)
        self.assertLessEqual(len(backs), 2, tally)
        self.assertLessEqual(tally['nothing'], 1, tally)

    def test_a_provider_slower_than_the_film(self):
        # a line every 2.5 s, 2.8 s to read one: the view can never stay ahead; the embedded track covers it
        tally, backs = self.simulate(self.film(45, 2.5), 2.8)
        self.assertLessEqual(tally['nothing'], len(backs) + 1, (tally, len(backs)))


class Preview(unittest.TestCase):
    """The full job shows the views' Hebrew for the lines it has not reached."""

    @classmethod
    def setUpClass(cls):
        cls.t = load_translate()

    def test_a_pending_cue_gets_the_hebrew_of_the_cue_with_its_start(self):
        t = self.t
        blocks = t.srt.parse_blocks(english(3))
        out = t._with_steps_preview(blocks, {3000: 'שלום\nלך'})
        self.assertEqual(out[0], blocks[0])
        self.assertEqual(out[1], '2\n00:00:03,000 --> 00:00:04,500\nשלום\nלך')
        self.assertEqual(out[2], blocks[2])

    def test_a_cue_keeps_its_own_number_and_end_time(self):
        # the last cue of a window has no following cue yet, so its end can differ from the complete file's
        t = self.t
        block = '17\n00:00:03,000 --> 00:00:09,000\nHello.'
        self.assertEqual(t._with_steps_preview([block], {3000: 'שלום'}),
                         ['17\n00:00:03,000 --> 00:00:09,000\nשלום'])

    def test_no_hebrew_is_no_change(self):
        t = self.t
        blocks = t.srt.parse_blocks(english(3))
        self.assertEqual(t._with_steps_preview(blocks, {}), blocks)

    def test_unique_starts(self):
        t = self.t
        blocks = [cue(1, 0, 'a'), cue(2, 0, 'b'), cue(3, 3000, 'c'), 'no time here']
        self.assertEqual(t._unique_starts(blocks), [None, None, 3000, None])

    def test_the_thinking_setting_is_read_as_before(self):
        t = self.t
        self.assertEqual(t._thinking_params('medium', 'gemini-3.5-flash-lite'), ('medium', None))
        self.assertEqual(t._thinking_params('1024', 'gemini-3.5-flash-lite'), ('medium', None))
        self.assertEqual(t._thinking_params('1024', 'gemini-2.5-flash'), (None, 1024))
        self.assertEqual(t._thinking_params('0', 'gemini-3.5-flash-lite'), (None, None))
        self.assertEqual(t._thinking_params('junk', 'gemini-3.5-flash-lite'), (None, None))


class Translator(unittest.TestCase):
    """_steps_translator: one request, the default model, never Google."""

    @classmethod
    def setUpClass(cls):
        cls.t = load_translate()

    def make(self, settings=None, reply=None, error=None, cancelled=lambda: False):
        t = self.t
        values = {'translation_mode': 'ai', 'api_key': 'KEY', 'model': 'gemini-3.7-flash', 'thinking_budget': 'medium'}
        values.update(settings or {})
        self.sent = []

        def generate(**kwargs):
            self.sent.append(kwargs)
            if error is not None:
                e = error[min(len(self.sent), len(error)) - 1]
                if e is not None:
                    raise e
            return reply(kwargs) if callable(reply) else reply

        patches = [
            patch.object(t.kodi_utils, 'get_setting', lambda key, default='': values.get(key, default)),
            patch.object(t.kodi_utils, 'get_float', lambda key, default=0.0: default),
            patch.object(t.kodi_utils, 'get_int', lambda key, default=0: default),
            patch.object(t.kodi_utils, 'get_bool', lambda key, default=False: default),
            patch.object(t.kodi_utils, 'log', lambda *a, **k: None),
            patch.object(t, '_title_cast', lambda info, imdb, season, episode: ([], 'Film', '2020')),
            patch.object(t, '_gemini_rate_gate', lambda interval: None),
            patch.object(t.gemini, 'generate', generate),
            patch.object(t.time, 'sleep', lambda seconds: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return t._steps_translator({'title': 'Film'}, 'en', cancelled)

    def blocks(self, count=3):
        return self.t.srt.parse_blocks(english(count))

    def hebrew(self, count=3):
        return '\n\n'.join(cue(i + 1, i * 3000, 'שורה %d.' % (i + 1)) for i in range(count))

    def test_the_default_model_whatever_model_is_chosen(self):
        translate = self.make(reply=self.hebrew())
        self.assertEqual(translate(self.blocks(), []), {0: 'שורה 1.', 1: 'שורה 2.', 2: 'שורה 3.'})
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]['model'], 'gemini-3.5-flash-lite')
        self.assertEqual(self.sent[0]['count_usage'], False)      # the counter holds the chosen model's requests
        self.assertEqual(self.sent[0]['timeout'], self.t._STEPS_TIMEOUT)
        self.assertIn('Line 2.', self.sent[0]['prompt'])
        self.assertIn('00:00:03,000', self.sent[0]['prompt'])     # with timecodes, like the full job's requests

    def test_requests_count_when_the_default_model_is_the_chosen_one(self):
        translate = self.make(settings={'model': 'gemini-3.5-flash-lite'}, reply=self.hebrew())
        translate(self.blocks(), [])
        self.assertEqual(self.sent[0]['count_usage'], True)

    def test_no_translator_without_a_key_or_when_google_is_the_translator(self):
        self.assertIsNone(self.make(settings={'api_key': ''}))
        self.assertIsNone(self.make(settings={'translation_mode': 'google'}))

    def test_a_cue_answered_without_hebrew_and_a_cue_not_answered(self):
        reply = cue(1, 0, 'שלום') + '\n\n' + cue(2, 3000, 'Line 2.')
        translate = self.make(reply=reply)
        self.assertEqual(translate(self.blocks(), []), {0: 'שלום', 1: ''})

    def test_a_reply_numbered_from_one_still_lands_on_its_own_cues(self):
        # cues 41-43 were sent; the model answered them as 1-3
        t = self.t
        sent = [cue(41 + i, 120000 + i * 3000, 'Line %d.' % (41 + i)) for i in range(3)]
        reply = '\n\n'.join(cue(1 + i, 120000 + i * 3000, 'שורה %d.' % (41 + i)) for i in range(3))
        translate = self.make(reply=reply)
        self.assertEqual(translate(sent, []), {0: 'שורה 41.', 1: 'שורה 42.', 2: 'שורה 43.'})

    def test_a_reply_with_other_times_is_no_answer_for_those_cues(self):
        sent = [cue(1 + i, i * 3000, 'Line %d.' % (1 + i)) for i in range(3)]
        reply = cue(1, 0, 'שלום') + '\n\n' + cue(2, 99000, 'לא שלי') + '\n\n3\nבלי זמן'
        translate = self.make(reply=reply)
        self.assertEqual(translate(sent, []), {0: 'שלום', 2: 'בלי זמן'})

    def test_a_busy_model_is_asked_once_more_and_then_the_lines_wait(self):
        t = self.t
        translate = self.make(reply=self.hebrew(), error=[t.gemini.OverloadError('503'), None])
        self.assertEqual(len(translate(self.blocks(), [])), 3)
        self.assertEqual(len(self.sent), 2)
        translate = self.make(reply=self.hebrew(), error=[t.gemini.OverloadError('503')])
        self.assertEqual(translate(self.blocks(), []), {})
        self.assertEqual(len(self.sent), 2)

    def test_no_quota_or_a_bad_key_ends_the_asking(self):
        t = self.t
        for error in (t.gemini.QuotaExceeded('429'), t.gemini.InvalidKey('400'), t.gemini.ModelUnavailable('404')):
            translate = self.make(reply=self.hebrew(), error=[error])
            self.assertIsNone(translate(self.blocks(), []))
            self.assertEqual(len(self.sent), 1)

    def test_any_other_failure_is_one_failed_request(self):
        t = self.t
        translate = self.make(reply=self.hebrew(), error=[t.gemini.GeminiError('timeout')])
        self.assertEqual(translate(self.blocks(), []), {})
        self.assertEqual(len(self.sent), 1)

    def test_a_cancelled_pick_sends_nothing(self):
        translate = self.make(reply=self.hebrew(), cancelled=lambda: True)
        self.assertIsNone(translate(self.blocks(), []))
        self.assertEqual(self.sent, [])

    def test_it_never_reaches_for_google_or_the_cache_or_the_pool(self):
        # the view is not the translation that is kept: read the function, not just its behaviour
        source = (ADDON / 'resources/lib/translate.py').read_text(encoding='utf-8')
        start = source.index('class _EmbeddedSteps(object):')
        end = source.index('def _build_prev_context_by_idx(')
        code = '\n'.join(line for line in source[start:end].split('\n') if not line.strip().startswith('#'))
        self.assertIn('def _steps_translator(', code)
        self.assertIn('class _StepsScreen(object):', code)
        self.assertIn('def _embedded_steps(', code)
        for word in ('google_translate', '_google_', 'cache.', 'translated_path', 'pool.', 'telemetry',
                     'gender_proofread', 'contribute', 'resolve('):
            self.assertFalse(word in code, word)


# ---------------------------------------------------------------------------
# The real handler

class Player(object):
    streams = []
    playing = 'https://cdn.example/film.mkv'

    def isPlayingVideo(self):
        return True

    def getPlayingFile(self):
        return Player.playing

    def getAvailableSubtitleStreams(self):
        return list(Player.streams)

    def setSubtitles(self, path):
        Player.streams.append(path)
        Screen.events.append(('final', os.path.basename(path), Path(path).read_text(encoding='utf-8')))

    def showSubtitles(self, on):
        pass

    def setSubtitleStream(self, index):
        Screen.events.append(('stream', index))


class Screen(object):
    events = []


class RealHandler(unittest.TestCase):
    """default.py's _handle_bg_translate_picker, as Kodi runs it for an
    embedded pick, fed by the code resolve() runs."""

    RELEASE = 'Show.S01E01.1080p.WEB.h264-GRP'

    @classmethod
    def setUpClass(cls):
        cls.t = load_translate()

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='steps_handler_')
        self.addCleanup(shutil.rmtree, self.dir, True)
        Player.streams = ['embedded:eng']
        Screen.events = []
        self.props = {}
        props = self.props

        xbmc = types.ModuleType('xbmc')
        xbmc.Player = Player
        xbmc.sleep = lambda ms: None
        xbmc.log = lambda *a, **k: None
        xbmc.LOGINFO = xbmc.LOGWARNING = xbmc.LOGERROR = xbmc.LOGDEBUG = 0
        xbmc.executebuiltin = lambda *a, **k: None
        xbmc.getCondVisibility = lambda *a: False
        xbmc.getInfoLabel = lambda *a: ''
        xbmcgui = types.ModuleType('xbmcgui')
        xbmcgui.WindowDialog = xbmcgui.WindowXMLDialog = xbmcgui.WindowXML = object
        xbmcgui.Window = lambda ident: types.SimpleNamespace(
            getProperty=lambda name: props.get(name, ''),
            setProperty=lambda name, value: props.__setitem__(name, value),
            clearProperty=lambda name: props.pop(name, None))
        xbmcgui.DialogProgressBG = lambda: types.SimpleNamespace(
            create=lambda *a: None, update=lambda *a: None, close=lambda: None)

        ku = types.ModuleType('resources.lib.kodi_utils')
        ku.subtitle_selection_matches = lambda token, link_hash, stream_hash: True
        ku.current_video_info = lambda: {'title': 'Show'}
        ku.cache_dir = lambda: self.dir
        ku.safe_release_filename = lambda release, fallback='': (release or fallback or '').replace('/', '_')
        ku.notify = lambda *a, **k: None
        ku.log = lambda *a, **k: None
        ku.mark_subtitle_delivery_applied = lambda *a, **k: None
        ku.confirm_subtitle_sync_fix = lambda *a, **k: None

        def apply_subtitle_file(path, selection=None, **kwargs):
            Player.streams.append(path)
            Screen.events.append(('view', os.path.basename(path), Path(path).read_text(encoding='utf-8')))
            return True
        ku.apply_subtitle_file = apply_subtitle_file

        self.tr = types.ModuleType('resources.lib.translate')
        self.tr._decode_link = lambda link: {'type': 'embedded_ai'}
        lib = types.ModuleType('resources.lib')
        lib.kodi_utils, lib.translate = ku, self.tr
        resources = types.ModuleType('resources')
        resources.lib = lib
        self.stubs = {'xbmc': xbmc, 'xbmcgui': xbmcgui, 'resources': resources, 'resources.lib': lib,
                      'resources.lib.kodi_utils': ku, 'resources.lib.translate': self.tr}
        for name in ('xbmcaddon', 'xbmcplugin', 'xbmcvfs'):
            self.stubs[name] = types.ModuleType(name)
        spec = importlib.util.spec_from_file_location('default_steps_test', ADDON / 'default.py')
        self.default = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, self.stubs):
            spec.loader.exec_module(self.default)

    def pick(self, resolve):
        """An embedded pick, as _handle_download fires it: no source id yet."""
        self.tr.resolve = resolve
        b64 = lambda s: base64.b64encode(s.encode('utf-8')).decode('ascii')
        selection = {'token': 'tok', 'link_hash': 'lh', 'stream_hash': 'sh'}
        with patch.dict(sys.modules, self.stubs):
            self.default._handle_bg_translate_picker({
                'link_b64': b64('the-embedded-link'), 'source_id_b64': b64(''),
                'selection_b64': self.default._encode_selection_b64(selection)})

    def job(self, keep_one_source_id=True):
        """resolve() for an embedded pick, reduced to what it reports: views
        while the track is read, then the full job under the id of the
        complete source file."""
        t = self.t
        final_text = '\n\n'.join(cue(i + 1, i * 3000, 'סופי %d.' % (i + 1)) for i in range(12)) + '\n'
        final_path = os.path.join(self.dir, 'translated_canonical.he.srt')

        def resolve(link, info, progressive_cb=None, extract_progress_cb=None, selection=None):
            screen = t._StepsScreen(link, self.RELEASE, progressive_cb, selection)
            steps = t._EmbeddedSteps(lambda: 0, Model(), screen.show)
            steps.feed(english(4))                               # the first window
            assert until(lambda: any(e[0] == 'view' for e in Screen.events))
            steps.feed(english(8))                               # the second
            assert until(lambda: 'שורה 8.' in [e for e in Screen.events if e[0] == 'view'][-1][2])
            he = steps.finish()
            report = screen.handler() if keep_one_source_id else progressive_cb
            source = t.srt.parse_blocks(english(12))             # the whole track is in
            first = t.srt.stitch_blocks(t._with_steps_preview(source, he))
            report('first_ready', {'fallback_text': first, 'source_id': 'c0ffee0123456789', 'release': self.RELEASE})
            half = t.srt.parse_blocks(final_text)[:6] + t._with_steps_preview(source[6:], he)
            report('chunk_ready', {'completed': 1, 'total': 2, 'merged_text': t.srt.stitch_blocks(half),
                                   'source_id': 'c0ffee0123456789', 'release': self.RELEASE})
            with open(final_path, 'w', encoding='utf-8') as f:
                f.write(final_text)
            report('done', {'success': True, 'path': final_path, 'source_id': 'c0ffee0123456789',
                            'release': self.RELEASE})
            return final_path
        return resolve

    def views(self):
        return [e for e in Screen.events if e[0] == 'view']

    def finals(self):
        return [e for e in Screen.events if e[0] == 'final']

    def test_every_view_then_the_full_jobs_chunks_then_the_finished_file_reach_the_player(self):
        self.pick(self.job())
        views = self.views()
        self.assertGreaterEqual(len(views), 4)
        self.assertIn('שורה 4.', views[0][2])                    # the first window, in Hebrew
        self.assertIn('שורה 8.', views[-2][2])                   # the second
        # the full job's first chunk: its own Hebrew, and the views' Hebrew for what it has not reached
        self.assertIn('סופי 6.', views[-1][2])
        self.assertIn('שורה 8.', views[-1][2])
        self.assertIn('Line 12.', views[-1][2])
        # the finished translation
        self.assertEqual(len(self.finals()), 1)
        self.assertEqual(self.finals()[0][1], self.RELEASE + '.he.srt')
        self.assertIn('סופי 12.', self.finals()[0][2])
        self.assertNotIn('שורה', self.finals()[0][2])
        self.assertEqual(Screen.events[-1], ('stream', len(Player.streams) - 1))

    def test_the_views_alternate_between_two_files_named_after_the_release(self):
        self.pick(self.job())
        names = [e[1] for e in self.views()]
        self.assertEqual(set(names), {self.RELEASE + '.a.he.srt', self.RELEASE + '.b.he.srt'})
        self.assertTrue(all(a != b for a, b in zip(names, names[1:])))

    def test_the_view_files_are_removed_once_the_finished_file_is_on(self):
        self.pick(self.job())
        left = sorted(os.listdir(self.dir))
        self.assertEqual(left, [self.RELEASE + '.he.srt', 'translated_canonical.he.srt'])

    def test_the_handler_is_released_at_the_end(self):
        self.pick(self.job())
        self.assertEqual(self.props.get('ai_subs.live_translate_job', ''), '')
        self.assertEqual(self.props.get('ai_subs.live_translate_source', ''), '')

    def test_with_two_source_ids_the_screen_froze_on_the_views(self):
        # the fault the first attempt shipped to review: this is what the handler does with a full job
        # that reports under its own id -- kept as a test so the reason for _StepsScreen.handler() stays visible
        self.pick(self.job(keep_one_source_id=False))
        self.assertTrue(all('סופי' not in e[2] for e in self.views()))
        self.assertEqual(self.finals(), [])

    def test_a_cache_hit_after_the_views_is_delivered_too(self):
        # resolve() returns a path without reporting: the handler delivers it under the id it adopted
        t = self.t
        final_path = os.path.join(self.dir, 'translated_canonical.he.srt')

        def resolve(link, info, progressive_cb=None, extract_progress_cb=None, selection=None):
            screen = t._StepsScreen(link, '', progressive_cb, selection)
            steps = t._EmbeddedSteps(lambda: 0, Model(), screen.show)
            steps.feed(english(4))
            assert until(lambda: self.views())
            steps.finish()
            with open(final_path, 'w', encoding='utf-8') as f:
                f.write(cue(1, 0, 'מהמטמון'))
            return final_path
        self.pick(resolve)
        self.assertEqual(len(self.finals()), 1)
        self.assertIn('מהמטמון', self.finals()[0][2])
        self.assertTrue(self.views()[0][1].startswith('progressive_steps'))     # no release: named by the id

    def test_nothing_shown_means_the_full_job_reports_as_it_always_did(self):
        t = self.t
        seen = []
        screen = t._StepsScreen('link', self.RELEASE, lambda phase, data: seen.append((phase, data)), {})
        report = screen.handler()
        report('chunk_ready', {'source_id': 'own', 'merged_text': 'x'})
        self.assertEqual(seen[0][1]['source_id'], 'own')
        self.assertIsNone(t._StepsScreen('link', '', None, {}).handler())


class OnPlay(unittest.TestCase):
    """No handler (the on-play pick): the view goes to the player from here."""

    @classmethod
    def setUpClass(cls):
        cls.t = load_translate()

    def test_two_alternating_files_applied_under_the_picks_selection(self):
        t = self.t
        folder = tempfile.mkdtemp(prefix='steps_onplay_')
        self.addCleanup(shutil.rmtree, folder, True)
        applied = []
        selection = {'token': 'tok', 'link_hash': 'lh', 'stream_hash': 'sh'}
        with patch.object(t.kodi_utils, 'cache_dir', lambda: folder), \
                patch.object(t.kodi_utils, 'safe_release_filename', lambda release, fallback='': release), \
                patch.object(t.kodi_utils, 'apply_subtitle_file',
                             lambda path, selection=None, abandon_on_failure=True: applied.append(
                                 (os.path.basename(path), Path(path).read_text(encoding='utf-8'), selection,
                                  abandon_on_failure))):
            screen = t._StepsScreen('link', 'Film.2020.WEB', None, selection)
            screen.show('one')
            screen.show('two')
            screen.show('three')
        self.assertEqual([a[0] for a in applied], ['Film.2020.WEB.a.he.srt', 'Film.2020.WEB.b.he.srt',
                                                   'Film.2020.WEB.a.he.srt'])
        self.assertEqual([a[1] for a in applied], ['one', 'two', 'three'])
        self.assertTrue(all(a[2] is selection and a[3] is False for a in applied))
        self.assertEqual(sorted(os.listdir(folder)), ['Film.2020.WEB.a.he.srt', 'Film.2020.WEB.b.he.srt'])
        self.assertIsNone(screen.handler())


if __name__ == '__main__':
    unittest.main()
