"""An embedded track read from a stream waits for the player's buffer
(MoranSubs 0.3.81).

QA of 13 Nov 2026 (TorBox at a busy hour, the same episode, alternating runs):
without an extraction the picture never froze; with one -- the old one-pass
reading or the stepped one -- it froze in most runs, 6-12 s after the reading
began, and the provider kept the player starved for minutes after the 8 s
stall guard had stopped the reading. The guard acts once the picture is
already frozen. So the reading now looks at the player's buffer before every
request: it starts only with the buffer stocked, and once the buffer runs low
it sends nothing until it is stocked again.

These tests run the REAL _extract_embedded_srt (translate.py) and its abort
callback against a scripted player on a fake clock. Only the stream read
(embedded_extract.extract_srt) is replaced: it asks the callback before every
request, as the real one does."""
import json
import os
import shutil
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / 'service.subtitles.kodipovilai'
URL = 'https://cdn.example/dld/film.mkv'
TOTAL_S = 2700
SRT = ''.join('%d\n00:00:%02d,000 --> 00:00:%02d,500\nLine %d\n\n' % (i + 1, i, i, i + 1) for i in range(20))


class World(object):
    """A fake clock and a scripted player. `buffer(t)` -> (seconds of film
    ahead, cache %); `paused(t)`, `frozen(t)`, `playing(t)`."""

    def __init__(self, buffer, paused=None, frozen=None, playing=None, jsonrpc_fails=False,
                 slow=1.0, jump=None, film0=1200.0, tick=0.0):
        self.slow = slow            # a sleep takes this many times as long (a busy interpreter)
        self.jump = jump            # (at t, seconds): the viewer skips within the cache, once
        self.tick = tick            # Player.getTime() moves in steps of this many seconds
        self.t = 0.0
        self.film = film0
        self.buffer = buffer
        self.paused = paused or (lambda t: False)
        self.frozen = frozen or (lambda t: False)
        self.playing = playing or (lambda t: True)
        self.jsonrpc_fails = jsonrpc_fails
        self.requests = []          # (t, ahead, level) at every request
        self.releases = []          # when the idle connection was closed
        self.logs = []

    def time(self):
        return 10 ** 6 + self.t

    def sleep(self, s):
        end = self.t + s * self.slow
        while self.t < end - 1e-9:
            if self.jump and self.t >= self.jump[0]:
                self.film += self.jump[1]
                self.jump = None
            step = min(0.1, end - self.t)
            if self.playing(self.t) and not self.paused(self.t) and not self.frozen(self.t):
                self.film += step
            self.t += step

    def jsonrpc(self, raw):
        if self.jsonrpc_fails == 'reply':
            return json.dumps({'id': 1, 'jsonrpc': '2.0', 'error': {'code': -32100, 'message': 'Failed'}})
        if self.jsonrpc_fails:
            raise RuntimeError('no JSON-RPC')
        ahead, _lvl = self.buffer(self.t)
        return json.dumps({'id': 1, 'jsonrpc': '2.0', 'result': {
            'percentage': self.film * 100.0 / TOTAL_S,
            'cachepercentage': (self.film + ahead) * 100.0 / TOTAL_S,
            'totaltime': {'hours': TOTAL_S // 3600, 'minutes': TOTAL_S // 60 % 60,
                          'seconds': TOTAL_S % 60, 'milliseconds': 0}}})

    def clock(self):
        if self.tick:
            return int(self.film / self.tick) * self.tick
        return self.film

    def label(self, name):
        if name == 'Player.CacheLevel':
            return str(int(self.buffer(self.t)[1]))
        return ''


WORLD = [None]


class Player(object):

    def isPlayingVideo(self):
        return WORLD[0].playing(WORLD[0].t)

    def getPlayingFile(self):
        return URL

    def getTime(self):
        return WORLD[0].clock()


def _stubs():
    xbmc = types.ModuleType('xbmc')
    xbmc.Player = Player
    xbmc.sleep = lambda ms: None
    xbmc.log = lambda *a, **k: None
    xbmc.LOGINFO = xbmc.LOGWARNING = xbmc.LOGERROR = xbmc.LOGDEBUG = 0
    xbmc.executebuiltin = lambda *a, **k: None
    xbmc.getCondVisibility = lambda cond: (cond == 'Player.Paused' and WORLD[0].paused(WORLD[0].t))
    xbmc.getInfoLabel = lambda name: WORLD[0].label(name)
    xbmc.executeJSONRPC = lambda raw: WORLD[0].jsonrpc(raw)
    xbmc.Monitor = lambda: types.SimpleNamespace(abortRequested=lambda: False, waitForAbort=lambda s=0: False)
    xbmcgui = types.ModuleType('xbmcgui')
    xbmcgui.WindowDialog = xbmcgui.WindowXMLDialog = xbmcgui.WindowXML = object
    props = {}
    xbmcgui.Window = lambda ident: types.SimpleNamespace(
        getProperty=lambda name: props.get(name, ''),
        setProperty=lambda name, value: props.__setitem__(name, value),
        clearProperty=lambda name: props.pop(name, None))
    xbmcgui.DialogProgressBG = lambda: mock.MagicMock()
    xbmcgui.Dialog = lambda: mock.MagicMock()
    out = {'xbmc': xbmc, 'xbmcgui': xbmcgui}
    for name in ('xbmcaddon', 'xbmcplugin', 'xbmcvfs'):
        out[name] = mock.MagicMock(name=name)
    return out


def _load():
    stubs = _stubs()

    def ours(name):
        return name == 'resources' or name.startswith('resources.')
    kept = {name: sys.modules.pop(name) for name in list(sys.modules) if ours(name)}
    try:
        with mock.patch.dict(sys.modules, stubs):
            sys.path.insert(0, str(ADDON))
            try:
                from resources.lib import translate, kodi_utils, embedded_extract  # noqa: F401
            finally:
                sys.path.remove(str(ADDON))
            mods = dict((k, v) for k, v in sys.modules.items() if k in stubs or ours(k))
    finally:
        for name in list(sys.modules):
            if ours(name):
                del sys.modules[name]
        sys.modules.update(kept)
    return mods


MODS = _load()


class Gate(unittest.TestCase):

    def run_pick(self, world, url=URL, n_requests=30, deadline_s=900.0, cancelled=None):
        """One extraction of `n_requests` requests, 0.2 s apart. Returns the
        path handed back (None when the reading stopped)."""
        WORLD[0] = world
        t = MODS['resources.lib.translate']
        ku = MODS['resources.lib.kodi_utils']
        ee = MODS['resources.lib.embedded_extract']
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)

        def extract(url_or_path, track_num=None, lang=None, allow_http=False, deadline_s=0,
                    abort_cb=None, progress_cb=None, resume_path=None, stats=None, steps=None, log=None):
            if stats is not None and url_or_path.startswith('http'):
                stats['release'] = lambda: world.releases.append(world.t)
            for _ in range(n_requests):
                if abort_cb():
                    return None
                ahead, lvl = world.buffer(world.t)
                world.requests.append((world.t, ahead, lvl))
                time.sleep(0.2)
            return SRT

        with mock.patch.dict(sys.modules, dict((k, v) for k, v in MODS.items())), \
                mock.patch('time.time', world.time), mock.patch('time.sleep', world.sleep), \
                mock.patch('time.monotonic', world.time), \
                mock.patch.object(t, '_playing_video_url', lambda info: url), \
                mock.patch.object(ku, 'cache_dir', lambda: tmp), \
                mock.patch.object(ku, 'log', lambda msg, level=None: world.logs.append(msg)), \
                mock.patch.object(ku, 'notify', lambda *a, **k: None), \
                mock.patch.object(ee, 'extract_srt', extract):
            return t._extract_embedded_srt({}, 'en', deadline_s=deadline_s, allow_http=True,
                                           cancelled=cancelled)

    def logged(self, world, text):
        return [m for m in world.logs if text in m]

    def test_a_stocked_buffer_reads_at_once(self):
        w = World(lambda t: (95.0, 100))
        self.assertTrue(self.run_pick(w))
        self.assertEqual(len(w.requests), 30)
        self.assertLess(w.requests[0][0], 0.01)
        self.assertFalse(self.logged(w, "buffer"))
        self.assertEqual(w.releases, [])

    def test_the_first_request_waits_for_the_buffer(self):
        # just after the subtitle list let go of the pause at a busy hour:
        # 3 s of film ahead, filling at 4 s of film a second
        w = World(lambda t: (3.0 + 4.0 * t, min(100, 2 + 4 * t)))
        self.assertTrue(self.run_pick(w))
        first_t, ahead, lvl = w.requests[0]
        self.assertGreaterEqual(ahead, 30.0)
        self.assertGreater(first_t, 6.5)
        self.assertTrue(self.logged(w, 'is not stocked yet'))
        self.assertTrue(self.logged(w, 'is back after'))
        # the connection was closed when the wait began, before any request
        self.assertEqual(len(w.releases), 1)
        self.assertLess(w.releases[0], first_t)

    def test_a_cache_full_by_its_own_measure_is_enough(self):
        # a small cache under a heavy file: full at a few seconds of film --
        # neither the start nor the reading waits for 40 s of film it can never hold
        w = World(lambda t: (6.0, 95))
        self.assertTrue(self.run_pick(w, n_requests=100))
        self.assertLess(w.requests[0][0], 0.01)
        self.assertLess(w.requests[-1][0], 20.5)
        self.assertFalse(self.logged(w, 'buffer'))

    def test_a_large_cache_part_full_is_enough(self):
        # the build's 128 MB cache at a busy hour: half empty, minutes of film
        w = World(lambda t: (75.0, 35))
        self.assertTrue(self.run_pick(w, n_requests=100))
        self.assertLess(w.requests[-1][0], 20.5)
        self.assertFalse(self.logged(w, 'buffer'))

    def test_nothing_is_sent_while_the_buffer_is_low(self):
        # stocked, then drained from t=2 to t=30 (the provider slowed down), then back
        def buf(t):
            if t < 2:
                return 90.0, 100
            if t < 30:
                return max(5.0, 90.0 - 10.0 * (t - 2)), max(4, 100 - 12 * (t - 2))
            return 60.0, 70
        w = World(buf)
        self.assertTrue(self.run_pick(w, n_requests=100))
        self.assertEqual(len(w.requests), 100)
        for t, ahead, lvl in w.requests:
            # the gate reads the buffer at most about once a second
            seen = [buf(max(0.0, t - 1.0)), buf(t)]
            self.assertTrue(any(a1 >= 15.0 or l1 >= 50 for a1, l1 in seen), (t, seen))
        # falling from t=2 (10 s of film a second, the cache under 90% from
        # t=2.8): it stood aside once the fall showed, and stayed aside --
        # through the low mark at t=9.5 -- until the buffer was stocked again
        # at t=30, not merely back above the low mark
        self.assertTrue([r for r in w.requests if r[0] < 4.0])
        self.assertFalse([r for r in w.requests if 9.0 < r[0] < 30.0])
        self.assertTrue([r for r in w.requests if r[0] >= 30.0])
        self.assertTrue(self.logged(w, 'is falling'))
        self.assertEqual(len(w.releases), 1)
        self.assertTrue(4.0 <= w.releases[0] <= 9.0, w.releases)

    def test_a_buffer_that_never_fills_stops_the_reading(self):
        w = World(lambda t: (8.0, 10))
        self.assertIsNone(self.run_pick(w))
        self.assertEqual(w.requests, [])
        self.assertTrue(self.logged(w, 'did not fill in 180s'))
        self.assertGreater(w.t, 179.0)
        self.assertLess(w.t, 185.0)

    def test_a_frozen_picture_during_the_wait_is_waited_out(self):
        # the provider stops serving the player (QA: TorBox froze the picture
        # in runs where nothing else touched the link): stopping would throw
        # the reading away for nothing -- wait, sending nothing, and go on
        w = World(lambda t: (2.0, 3) if t < 60 else (55.0, 70), frozen=lambda t: 5 <= t < 60)
        self.assertTrue(self.run_pick(w))
        self.assertEqual(len(w.requests), 30)
        self.assertGreaterEqual(w.requests[0][0], 60.0)
        self.assertFalse(self.logged(w, 'player stalled'))
        self.assertEqual(len(self.logged(w, 'picture is frozen')), 1)

    def test_the_freeze_sat_out_is_not_counted_after_the_wait(self):
        # the buffer is stocked a couple of seconds before the clock moves
        # again: the 8 s guard must measure from the end of the wait, not
        # from the freeze it sat out
        w = World(lambda t: (2.0, 3) if t < 61 else (55.0, 70), frozen=lambda t: 5 <= t < 63.5)
        self.assertTrue(self.run_pick(w))
        self.assertEqual(len(w.requests), 30)
        self.assertFalse(self.logged(w, 'player stalled'))

    def test_a_picture_frozen_past_the_limit_stops_the_reading(self):
        w = World(lambda t: (0.0, 1), frozen=lambda t: t >= 3)
        self.assertIsNone(self.run_pick(w))
        self.assertEqual(w.requests, [])
        self.assertTrue(self.logged(w, 'did not fill in 180s'))

    def test_a_player_that_reports_no_buffer_reads_as_before(self):
        # Kodi's buffering switched off: nothing reported, the film plays on
        w = World(lambda t: (0.0, 0))
        self.assertTrue(self.run_pick(w))
        self.assertEqual(len(w.requests), 30)
        self.assertTrue(self.logged(w, 'reports no buffer'))
        self.assertLess(w.requests[0][0], 12.0)

    def test_no_json_rpc_reads_as_before(self):
        w = World(lambda t: (2.0, 3), jsonrpc_fails=True)
        self.assertTrue(self.run_pick(w))
        self.assertLess(w.requests[0][0], 0.01)

    def test_a_slow_steady_buffer_is_enough(self):
        # the provider a little faster than the film: the buffer sits between
        # the marks and the film plays on -- after 20 s of film the wait ends
        # (review: it used to wait out the limit and give the reading up)
        w = World(lambda t: (22.0 + 0.05 * t, 20))
        self.assertTrue(self.run_pick(w))
        first_t = w.requests[0][0]
        self.assertGreaterEqual(first_t, 19.5)
        self.assertLess(first_t, 25.0)
        self.assertTrue(self.logged(w, 'is steady after'))

    def test_a_falling_buffer_is_not_steady(self):
        # between the marks but draining until t=30: no reading while it falls
        w = World(lambda t: (max(22.0, 28.0 - 0.2 * t), 20))
        self.assertTrue(self.run_pick(w))
        self.assertGreaterEqual(w.requests[0][0], 30.0)

    def test_a_short_pause_keeps_the_wait(self):
        # a pause too short to count as one (Kodi reports Paused through a
        # seek or a hiccup): reading while it lasts is allowed as before,
        # but afterwards the wait goes on -- the buffer is in the band
        # between the marks, where only a wait that was kept holds back
        def buf(t):
            return (10.0, 8) if t < 4 else (22.0, 20)
        w = World(buf, paused=lambda t: 3.0 <= t < 4.5)
        self.assertTrue(self.run_pick(w, n_requests=60))
        self.assertTrue([r for r in w.requests if 3.0 <= r[0] < 4.6])
        self.assertFalse([r for r in w.requests if 5.0 < r[0] < 24.0])
        self.assertFalse([r for r in w.requests if r[0] < 3.0])

    def test_a_pause_tap_during_a_frozen_wait_does_not_stop_the_reading(self):
        # the viewer taps pause and play to unstick a frozen picture
        def buf(t):
            return (2.0, 3) if t < 45 else (55.0, 70)
        w = World(buf, frozen=lambda t: 5 <= t < 46, paused=lambda t: 20.0 <= t < 21.0)
        self.assertTrue(self.run_pick(w))
        self.assertFalse(self.logged(w, 'player stalled'))
        self.assertEqual(len(w.requests), 30)

    def test_a_json_rpc_error_reply_is_not_an_empty_buffer(self):
        w = World(lambda t: (2.0, 3), jsonrpc_fails='reply')
        self.assertTrue(self.run_pick(w, n_requests=40))
        self.assertLess(w.requests[0][0], 0.01)
        self.assertFalse(self.logged(w, 'not stocked'))
        self.assertTrue(self.logged(w, 'cannot be read'))

    def test_the_wait_ends_with_the_extraction_deadline(self):
        w = World(lambda t: (5.0, 6))
        self.assertIsNone(self.run_pick(w, deadline_s=60.0))
        self.assertTrue(self.logged(w, 'did not fill in 60s'))
        self.assertLess(w.t, 65.0)

    def test_a_pause_during_the_wait_lets_the_reading_run(self):
        # paused from t=3 to t=20 with a low buffer: reading while paused is
        # allowed as before; once the picture moves again the gate is back
        def buf(t):
            return (5.0, 6) if t < 25 else (50.0, 60)
        w = World(buf, paused=lambda t: 3 <= t < 20)
        self.assertTrue(self.run_pick(w, n_requests=200))
        while_paused = [r for r in w.requests if 3 <= r[0] < 20]
        after = [r for r in w.requests if r[0] >= 20]
        self.assertTrue(while_paused)
        self.assertTrue(after)
        self.assertFalse([r for r in after if r[0] < 25], after[:3])
        self.assertFalse([r for r in w.requests if r[0] < 3])

    def test_after_a_long_pause_the_buffer_decides(self):
        # a real pause (the subtitle list is one): the old 15 s stand-aside on
        # resume, with our connection closed, and then the buffer gate -- the
        # buffer still low at the end of the 15 s means no reading yet
        def buf(t):
            return (5.0, 6) if t < 60 else (50.0, 60)
        w = World(buf, paused=lambda t: 3 <= t < 20)
        self.assertTrue(self.run_pick(w, n_requests=200))
        self.assertFalse([r for r in w.requests if 21.0 < r[0] < 59.0])
        self.assertTrue([r for r in w.requests if r[0] >= 60.0])
        self.assertTrue([x for x in w.releases if 19.0 <= x <= 22.0], w.releases)

    def test_a_falling_buffer_while_reading_stands_aside(self):
        # the provider slows down with the buffer still well stocked: 60 s
        # ahead, losing a second of film a second -- stand aside at once,
        # long before the low mark, and read again when it is back up
        def buf(t):
            if t < 4:
                return 60.0, 60
            if t < 20:
                return 60.0 - (t - 4), 60 - 2 * (t - 4)
            return min(80.0, 44.0 + 4 * (t - 20)), 60
        w = World(buf)
        self.assertTrue(self.run_pick(w, n_requests=100))
        self.assertTrue(self.logged(w, 'is falling'))
        self.assertTrue([r for r in w.requests if r[0] < 4.0])
        self.assertFalse([r for r in w.requests if 10.5 < r[0] < 20.0])
        self.assertTrue([r for r in w.requests if r[0] >= 20.0])

    def test_minutes_in_hand_are_not_a_fall(self):
        # 465 s of film ahead, losing a second a second (review): there is
        # time to see whether it goes on -- no stand-aside
        w = World(lambda t: (465.0 - t, 80))
        self.assertTrue(self.run_pick(w, n_requests=100))
        self.assertFalse(self.logged(w, 'buffer'))

    def test_a_full_cache_is_not_falling(self):
        # Kodi tops a full cache up in steps: the seconds ahead wobble
        w = World(lambda t: (92.5 - 4.0 * ((t * 10) % 50) / 50.0, 99))
        self.assertTrue(self.run_pick(w, n_requests=100))
        self.assertFalse(self.logged(w, 'buffer'))

    def test_a_pause_after_the_buffer_ran_low_sends_nothing(self):
        # the picture ran short and the viewer pauses to let it refill: no
        # reading while paused (reading while paused is for a stocked buffer)
        def buf(t):
            if t < 5:
                return 60.0, 60
            return (10.0, 10) if t < 25 else (50.0, 60)
        w = World(buf, paused=lambda t: 8 <= t < 20)
        self.assertTrue(self.run_pick(w, n_requests=100))
        self.assertTrue([r for r in w.requests if r[0] < 5.0])
        self.assertFalse([r for r in w.requests if 6.0 < r[0] < 25.0])

    def test_a_skip_within_the_cache_is_not_a_fall(self):
        # the viewer skips 10 s ahead inside what is cached: the buffer is
        # 10 s shorter at once, but nothing is falling
        def buf(t):
            return (80.0, 70) if t < 5 else (70.0, 70)
        w = World(buf, jump=(5.0, 10.0))
        self.assertTrue(self.run_pick(w, n_requests=100))
        self.assertFalse(self.logged(w, 'is falling'))
        gaps = [b[0] - a[0] for a, b in zip(w.requests, w.requests[1:])]
        self.assertLess(max(gaps), 1.0)

    def test_a_replaced_pick_ends_the_wait(self):
        w = World(lambda t: (5.0, 6))
        self.assertIsNone(self.run_pick(w, cancelled=lambda: WORLD[0].t >= 10.0))
        self.assertEqual(w.requests, [])
        self.assertTrue(self.logged(w, 'pick was replaced'))
        self.assertLess(w.t, 13.0)

    def test_steady_is_measured_against_the_clock(self):
        # a busy interpreter: every one-second poll takes three -- the film
        # still plays as far as the clock goes, and that is steady
        w = World(lambda t: (22.0, 20), slow=3.0)
        self.assertTrue(self.run_pick(w))
        self.assertTrue(self.logged(w, 'is steady after'))
        self.assertLess(w.requests[0][0], 40.0)

    def test_steady_needs_more_than_the_low_mark(self):
        # 17 s ahead and flat: just over the low mark -- reading would put it
        # straight back under, so this is not steady enough
        w = World(lambda t: (17.0, 20))
        self.assertIsNone(self.run_pick(w, deadline_s=90.0))
        self.assertEqual(w.requests, [])

    def test_a_small_cache_is_steady_by_how_full_it_is(self):
        # a heavy file on a small cache: 6 s of film, the cache 60% and flat
        w = World(lambda t: (6.0, 60))
        self.assertTrue(self.run_pick(w))
        self.assertTrue(self.logged(w, 'is steady after'))
        self.assertGreaterEqual(w.requests[0][0], 19.5)
        self.assertLess(w.requests[0][0], 25.0)

    def test_a_cache_that_reaches_the_end_of_the_film_is_stocked(self):
        # ten minutes left, all of it in Kodi's cache: the seconds ahead are
        # the rest of the film and fall with it, the cache % falls too --
        # that is not a provider falling behind (review)
        w = World(lambda t: (TOTAL_S - WORLD[0].film, max(40, 77 - int(t / 10))), film0=TOTAL_S - 600.0)
        self.assertTrue(self.run_pick(w, n_requests=400))
        self.assertEqual(len(w.requests), 400)
        self.assertFalse(self.logged(w, 'buffer'))

    def test_the_end_of_the_film_ends_a_wait(self):
        # a wait that began short of the end: once the cache reaches the end
        # of the film -- 25 s of it left, under every mark and falling with
        # the film -- it is stocked
        w = World(lambda t: (5.0, 6) if t < 15 else (max(0.0, TOTAL_S - WORLD[0].film), 20),
                  film0=TOTAL_S - 40.0)
        self.assertTrue(self.run_pick(w))
        self.assertTrue(self.logged(w, 'is back after'))
        self.assertLess(w.requests[0][0], 17.0)

    def test_a_short_fall_shows_through_a_clock_in_steps(self):
        # a fall of 7 s with Kodi's play time in whole seconds and late polls:
        # the window comparison must not keep starting over
        def buf(t):
            if t < 4:
                return 60.0, 60
            return (60.0 - 1.2 * (t - 4), 60) if t < 11 else (70.0, 70)
        w = World(buf, tick=1.0, slow=1.3)
        self.assertTrue(self.run_pick(w, n_requests=100))
        self.assertTrue(self.logged(w, 'is falling'))

    def test_a_frozen_picture_is_not_steady(self):
        # in the steady band, but the picture stands from t=5 to t=15: the
        # 20 s of play count from when it moves again
        w = World(lambda t: (22.0, 20), frozen=lambda t: 5 <= t < 15)
        self.assertTrue(self.run_pick(w))
        self.assertTrue(self.logged(w, 'is steady after'))
        self.assertGreaterEqual(w.requests[0][0], 33.0)

    def test_a_play_clock_in_steps_is_still_steady(self):
        # Kodi's play time moving in whole seconds, polls a little late
        w = World(lambda t: (22.0, 20), slow=1.3, tick=1.0)
        self.assertTrue(self.run_pick(w))
        self.assertTrue(self.logged(w, 'is steady after'))
        self.assertLess(w.requests[0][0], 32.0)

    def test_a_play_clock_in_steps_still_shows_a_fall(self):
        def buf(t):
            if t < 4:
                return 60.0, 60
            return (60.0 - (t - 4), 60 - 2 * (t - 4)) if t < 20 else (min(80.0, 44.0 + 4 * (t - 20)), 60)
        w = World(buf, tick=1.0, slow=1.3)
        self.assertTrue(self.run_pick(w, n_requests=100))
        self.assertTrue(self.logged(w, 'is falling'))
        # within about 7 s of the fall starting at t=4 (a tolerance too tight
        # for a clock in steps would keep starting over and stand aside late)
        self.assertTrue(w.releases and w.releases[0] <= 11.0, w.releases)
        self.assertFalse([r for r in w.requests if 11.0 < r[0] < 20.0])

    def test_a_local_file_does_not_wait(self):
        w = World(lambda t: (2.0, 3))
        self.assertTrue(self.run_pick(w, url=r'C:\films\film.mkv'))
        self.assertLess(w.requests[0][0], 0.01)

    def test_a_stall_without_a_wait_still_stops_the_reading(self):
        # the old guard is untouched: a stocked buffer and a frozen picture
        w = World(lambda t: (90.0, 100), frozen=lambda t: t >= 1)
        self.assertIsNone(self.run_pick(w, n_requests=200))
        self.assertTrue(self.logged(w, 'player stalled'))
        self.assertLess(w.t, 11.0)


if __name__ == '__main__':
    unittest.main()
