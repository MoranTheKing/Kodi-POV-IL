"""Wizard 0.5.6 / Onyx 1.0.16: a title's trailer behind the home's hero (resources/libs/trailers.py).

The owner, Nov 2026, with a video of another app: "the trailer playing on the title itself". In the QA Kodi,
handing the trailer's address to Kodi's player put the busy dialog over the home for 1.5 s (it takes the
remote's keys) and the YouTube add-on asked its set-up question; asked through that add-on's own resolver from
a thread, nothing is shown and the stream plays in Kodi's preview mode behind the hero.
"""
import importlib.util
import re
import sys
import types
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
XML = ROOT / 'skin.povil.onyx/xml'
spec = importlib.util.spec_from_file_location('trailers_under_test', WIZARD / 'resources/libs/trailers.py')
trailers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trailers)

ADDRESS = 'plugin://plugin.video.youtube/play/?video_id=hoRHBV0m1hw'
STREAM = {'url': 'http://127.0.0.1:50152/youtube/manifest/dash/x.mpd', 'container': 'mpd', 'adaptive': True,
          'headers': {'User-Agent': 'Kodi 21'}}


class Home(object):
    def __init__(self, **values):
        self.values = dict(values)

    def getProperty(self, key):
        return self.values.get(key, '')

    def setProperty(self, key, value):
        self.values[key] = value

    def clearProperty(self, key):
        self.values.pop(key, None)


class Player(object):
    def __init__(self, playing=None):
        self.playing = playing
        self.calls = []

    def isPlaying(self):
        return self.playing is not None

    def getPlayingFile(self):
        if self.playing is None:
            raise RuntimeError('Kodi is not playing any media file')
        return self.playing

    def play(self, url, item, windowed):
        self.calls.append(('play', url, windowed))
        self.playing = url

    def stop(self):
        self.calls.append(('stop',))
        self.playing = None


class DeskTests(unittest.TestCase):
    def desk(self, home, player, streams=(STREAM,), on=True, age=1000.0):
        self.resolved = []
        now = [age]

        def resolve(video):
            self.resolved.append(video)
            return list(streams)
        desk = trailers.Desk(home, player, resolve, lambda url, stream: ('item', url), lambda: on, clock=lambda: now[0])
        desk.born = 0.0
        return desk

    def test_the_address_pov_gives_names_the_video_and_nothing_else_does(self):
        self.assertEqual(trailers.video_id(ADDRESS), 'hoRHBV0m1hw')
        self.assertEqual(trailers.video_id(ADDRESS + '&x=1'), 'hoRHBV0m1hw')
        for other in ('', None, 'plugin://plugin.video.pov/?mode=x&video_id=hoRHBV0m1hw', 'https://youtu.be/hoRHBV0m1hw',
                      'plugin://plugin.video.youtube/play/?video_id=short', 'plugin://plugin.video.youtube/play/?playlist_id=PL1'):
            self.assertIsNone(trailers.video_id(other), other)

    def test_a_rested_title_gets_its_trailer_in_preview_mode_named_before_it_starts(self):
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        desk = self.desk(home, player)
        job = desk.asked()
        self.assertIsNotNone(job)
        self.assertEqual(player.calls, [], 'nothing on the thread the question arrives on')
        order = []
        home.setProperty = lambda key, value, keep=home.setProperty: (order.append(key), keep(key, value))
        player.play = lambda url, item, windowed, keep=player.play: (order.append('play'), keep(url, item, windowed))
        self.assertTrue(job())
        self.assertEqual(self.resolved, ['hoRHBV0m1hw'])
        self.assertEqual(player.calls, [('play', STREAM['url'], True)], 'windowed: the home stays on the screen')
        self.assertEqual(order, [trailers.ON, trailers.FILE, trailers.OPENING, 'play'], 'named before the playback begins')
        self.assertEqual(home.values[trailers.FILE], STREAM['url'])
        self.assertEqual(home.values[trailers.ON], ADDRESS)
        desk.playback_started()
        self.assertNotIn(trailers.OPENING, home.values, "the first picture is there: the spinner is Kodi's again")
        self.assertEqual(home.values[trailers.ON], ADDRESS)
        self.assertIsNone(desk.asked(), 'already playing it')

    def test_nothing_starts_while_something_else_plays_or_the_switch_is_off(self):
        film = Player(playing='http://debrid/film.mkv')
        self.assertIsNone(self.desk(Home(**{trailers.ASK: ADDRESS}), film).asked())
        self.assertIsNone(self.desk(Home(**{trailers.ASK: ADDRESS}), Player(), on=False).asked())
        self.assertIsNone(self.desk(Home(**{trailers.ASK: 'plugin://plugin.video.idanplus/?x'}), Player()).asked())
        # a film began while the trailer's stream was being named: the film stays
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        desk = self.desk(home, player)
        job = desk.asked()
        player.playing = 'http://debrid/film.mkv'
        self.assertFalse(job())
        self.assertEqual((player.calls, home.values.get(trailers.ON)), ([], None))

    def test_the_viewer_moved_on_while_the_stream_was_being_named(self):
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        desk = self.desk(home, player)
        job = desk.asked()
        home.values[trailers.ASK] = ADDRESS.replace('hoRHBV0m1hw', 'aaaaaaaaaaa')
        self.assertFalse(job())
        self.assertEqual(player.calls, [])
        # ... or was told to stop
        home.values[trailers.ASK] = ADDRESS
        job = desk.asked()
        desk.stop()
        self.assertFalse(job())
        self.assertEqual(player.calls, [])

    def test_stop_stops_only_the_trailer_this_desk_started(self):
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        desk = self.desk(home, player)
        desk.asked()()
        desk.playback_started()
        self.assertTrue(desk.stop())
        self.assertEqual(player.calls[-1], ('stop',))
        self.assertNotIn(trailers.ON, home.values)
        self.assertNotIn(trailers.FILE, home.values)
        # a film picked while the trailer ran took the player over: it is left alone
        desk.asked()()
        desk.playback_started()
        player.playing = 'http://debrid/film.mkv'
        desk.playback_started()
        self.assertNotIn(trailers.ON, home.values)
        self.assertNotIn(trailers.FILE, home.values, 'the subtitles add-on must not take the film for a trailer')
        calls = len(player.calls)
        self.assertFalse(desk.stop())
        self.assertEqual(len(player.calls), calls, 'nothing was stopped')
        self.assertEqual(player.playing, 'http://debrid/film.mkv')

    def test_a_trailer_that_ends_or_fails_gives_the_still_back(self):
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        desk = self.desk(home, player)
        desk.asked()()
        player.playing = None
        desk.playback_over()
        self.assertNotIn(trailers.ON, home.values)
        # the resolver failing, or answering nothing, starts nothing and says so in the log only
        for streams in ((), ({'url': ''},), ({'url': 'http://x', 'live': True},)):
            home, player = Home(**{trailers.ASK: ADDRESS}), Player()
            self.assertFalse(self.desk(home, player, streams=streams).asked()())
            self.assertEqual(player.calls, [])
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        desk = self.desk(home, player)
        desk.resolve = lambda video: 1 / 0
        self.assertFalse(desk.asked()())

    def test_none_while_kodi_is_still_starting(self):
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        desk = self.desk(home, player, age=3.0)
        waits = []
        desk.waiting.wait = lambda seconds: waits.append(seconds)
        job = desk.asked()
        self.assertTrue(job(), 'still the title on screen when the start is over: it plays then')
        self.assertEqual(waits, [trailers.QUIET_START_S - 3.0])
        self.assertLessEqual(trailers.QUIET_START_S, 10, 'the thread starts after the home has settled: a few seconds, not a minute')
        # the viewer moved on during the wait: nothing is asked of YouTube at all
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        desk = self.desk(home, player, age=3.0)
        desk.waiting.wait = lambda seconds: home.values.update({trailers.ASK: ''})
        self.assertFalse(desk.asked()())
        self.assertEqual(self.resolved, [])

    def test_it_is_on_until_the_viewer_switches_it_off(self):
        # the owner, Nov 2026: "on by default for everyone". A skin setting is unset until someone sets it,
        # so the setting says OFF -- nothing has to be written on anyone's device for the trailers to be on
        source = (WIZARD / 'resources/libs/trailers.py').read_text('utf-8')
        self.assertNotIn('Skin.SetBool', source)
        self.assertNotIn('Skin.ToggleSetting', source)
        self.assertEqual(trailers.OFF_SWITCH, 'POVILNoTrailers')
        self.assertIn("not xbmc.getCondVisibility('Skin.HasSetting(%s)' % OFF_SWITCH)", source)
        home = Home(**{trailers.ASK: ADDRESS})
        self.assertIsNone(self.desk(home, Player(), on=False).asked())
        self.assertEqual(self.resolved, [])

    def guarded(self, clock_of_trailer):
        """A desk whose trailer has just started; every wait of the guard is one second of the fake clock,
        and clock_of_trailer(second) is what the player's clock says then (None: nothing plays)."""
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        now = [1000.0]
        desk = trailers.Desk(home, player, lambda video: [STREAM], lambda url, stream: ('item', url), lambda: True,
                             clock=lambda: now[0])
        desk.born = 0.0
        self.assertTrue(desk.asked()())
        start = now[0]

        def wait(seconds):
            now[0] += seconds
            return now[0] - start > 120
        desk.waiting.wait = wait

        def get_time():
            value = clock_of_trailer(now[0] - start)
            if value is None:
                raise RuntimeError('Kodi is not playing any media file')
            return value
        player.getTime = get_time
        return desk, home, player, now

    def test_a_trailer_whose_clock_stands_still_is_given_up_and_the_still_comes_back(self):
        # seen once in the QA Kodi: what YouTube hands an unsigned viewer stopped coming after ten seconds
        desk, home, player, now = self.guarded(lambda second: min(second, 10.0))
        desk.playback_started()
        self.assertTrue(desk.guard())
        self.assertEqual(now[0] - 1000.0, 10 + trailers.STALL_S)
        self.assertEqual(player.calls[-1], ('stop',))
        for key in (trailers.ON, trailers.FILE, trailers.OPENING):
            self.assertNotIn(key, home.values)
        # ... and the title is not asked again for a while (the skin does not ask twice for the same title,
        # but the viewer may come back to it)
        self.assertIsNone(desk.asked())
        now[0] += trailers.GIVEN_UP_S
        self.assertIsNotNone(desk.asked())

    def test_a_trailer_that_never_shows_a_picture_is_given_up_too(self):
        desk, home, player, now = self.guarded(lambda second: 0.0)
        self.assertTrue(desk.guard())
        self.assertEqual(now[0] - 1000.0, trailers.OPEN_S)
        self.assertEqual(player.calls, [('play', STREAM['url'], True)], 'a player that is still opening is not told to stop')
        self.assertNotIn(trailers.ON, home.values)
        self.assertIsNone(desk.asked(), 'its title rests for a while')
        desk.playback_started()
        self.assertEqual(player.calls[-1], ('stop',), 'if it ever shows a picture it is stopped then')

    def test_the_guard_leaves_a_playing_trailer_and_anything_that_is_not_the_trailer_alone(self):
        desk, home, player, now = self.guarded(lambda second: second)
        self.assertFalse(desk.guard(), 'played on until Kodi closed')
        self.assertEqual(player.calls, [('play', STREAM['url'], True)])
        # the trailer ended by itself
        desk, home, player, now = self.guarded(lambda second: second)
        keep = desk.waiting.wait
        desk.waiting.wait = lambda s: (keep(s), now[0] >= 1030.0 and (setattr(player, 'playing', None), desk.playback_over()))[0]
        self.assertFalse(desk.guard())
        self.assertEqual(player.calls, [('play', STREAM['url'], True)], 'nothing stopped')
        # a film took the player over and its clock stands still (paused): never the guard's to stop
        desk, home, player, now = self.guarded(lambda second: 5.0)
        player.playing = 'http://debrid/film.mkv'
        desk.playback_started()
        self.assertFalse(desk.guard())
        self.assertEqual(player.playing, 'http://debrid/film.mkv')
        # the viewer moved on (the skin said stop) while it opened, and its first picture came after: stopped
        # then, and not a trailer that failed
        desk, home, player, now = self.guarded(lambda second: 0.0)
        keep = desk.waiting.wait
        desk.waiting.wait = lambda s: (keep(s), now[0] >= 1005.0 and desk.ours and desk.stop(),
                                       now[0] >= 1007.0 and desk.ours and desk.playback_started())[0]
        self.assertFalse(desk.guard())
        self.assertEqual(desk.given_up, {}, 'stopped by the viewer is not a trailer that failed')
        # ... the same after its first picture
        desk, home, player, now = self.guarded(lambda second: second)
        desk.playback_started()
        keep = desk.waiting.wait
        desk.waiting.wait = lambda s: (keep(s), now[0] >= 1005.0 and desk.ours and desk.stop())[0]
        self.assertFalse(desk.guard())
        self.assertEqual(desk.given_up, {})
        # but an opening that never shows a picture is one, whether or not the viewer moved on meanwhile (the
        # owner's LG, 0.5.14: he moved on after nine seconds, the player had hung opening)
        desk, home, player, now = self.guarded(lambda second: 0.0)
        keep = desk.waiting.wait
        desk.waiting.wait = lambda s: (keep(s), now[0] >= 1009.0 and desk.ours and desk.stop())[0]
        self.assertTrue(desk.guard())
        self.assertIn(ADDRESS, desk.given_up)
        self.assertEqual(player.calls, [('play', STREAM['url'], True)], 'still never told to stop while it opens')

    def test_every_device_gets_h264_up_to_720p_and_the_youtube_add_on_keeps_its_settings(self):
        # of ten trailers in the QA Kodi three came as 1080p AV1 and one as 4K VP9 (a small box decodes those
        # in software); asked this way all came as 720p H.264
        asked = {}

        class Settings(object):
            def mpd_video_qualities(self, value=None):
                self.written = value is not None
                return [{'nom_height': h} for h in (2160, 1440, 1080, 720, 480, 360)]

            def stream_features(self, value=None, raw_values=False):
                self.written = value is not None
                return frozenset(('avc1', 'vp9', 'av01', 'hdr', 'hfr', 'vorbis', 'mp4a', 'ssa', 'filter'))

        settings = Settings()

        woken = []

        class Context(object):
            def ipc_exec(self, target, timeout=None):
                woken.append((target, timeout))
                return True

            def get_settings(self):
                return settings

        class Client(object):
            def load_stream_info(self, video_id):
                asked.update(video=video_id, heights=[q['nom_height'] for q in settings.mpd_video_qualities()],
                             kinds=settings.stream_features(), raw=settings.stream_features(raw_values=True))
                return [dict(STREAM, sort=(2, 0)), dict(STREAM, url='http://first', sort=(1, 0))], None

        class Provider(object):
            def get_client(self, context):
                return Client()

        streams = trailers.light_streams('hoRHBV0m1hw', Provider, Context, 'server_wakeup')
        self.assertEqual(woken, [('server_wakeup', trailers.WAKE_S)], 'the add-on\'s server is woken first, as its own player does')
        self.assertEqual(streams[0]['url'], 'http://first', 'in the add-on\'s own order')
        self.assertEqual(asked['heights'], [720, 480, 360])
        self.assertEqual(asked['kinds'], frozenset(('avc1', 'vorbis', 'mp4a', 'ssa', 'filter')))
        self.assertEqual(asked['raw'], sorted(asked['kinds']))
        self.assertFalse(settings.written, 'nothing is written to the YouTube add-on\'s settings')
        # an add-on set to no adaptive streams at all: no trailer (nothing heavier is ever asked for instead)
        settings2 = Settings()
        settings2.mpd_video_qualities = lambda value=None: []
        with self.assertRaises(ValueError):
            trailers.light_streams('hoRHBV0m1hw', Provider, type('C', (Context,), {'get_settings': lambda self: settings2}), 'w')
        # its server did not wake: no trailer this time, and its code is not asked for a stream at all
        asked.clear()
        with self.assertRaises(trailers.Asleep):
            trailers.light_streams('hoRHBV0m1hw', Provider, type('C', (Context,), {'ipc_exec': lambda self, target, timeout=None: None}), 'w')
        self.assertEqual(asked, {})
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        desk = self.desk(home, player)
        said = []
        desk.log = said.append

        def asleep(video):
            raise trailers.Asleep()
        desk.resolve = asleep
        self.assertFalse(desk.asked()())
        self.assertEqual((player.calls, said, desk.given_up), ([], ['the YouTube add-on did not wake its server'], {}),
                         'nothing on the screen, a line in the log, and the title may be asked again')

    def test_a_stream_is_read_here_before_kodis_player_hears_of_it(self):
        # the YouTube add-on shuts its own server down once Kodi has rested half a minute; a stream handed to
        # Kodi's player then cost twenty seconds per part, with Kodi's screen frozen at the next stop
        manifest = ('<MPD><Period>'
                    '<AdaptationSet id="0" mimeType="video/mp4"><Representation id="136"><BaseURL>http://127.0.0.1:50152/youtube/stream?itag=136&amp;a=1</BaseURL></Representation>'
                    '<Representation id="135"><BaseURL>http://127.0.0.1:50152/youtube/stream?itag=135</BaseURL></Representation></AdaptationSet>'
                    '<AdaptationSet id="1" mimeType="audio/mp4" lang="en"><Representation id="140"><BaseURL>http://127.0.0.1:50152/youtube/stream?itag=140</BaseURL></Representation></AdaptationSet>'
                    '<AdaptationSet id="2" mimeType="audio/mp4" lang="he"><Representation id="140-1"><BaseURL>http://127.0.0.1:50152/youtube/stream?itag=140&amp;xtags=he</BaseURL></Representation></AdaptationSet>'
                    '</Period></MPD>')
        self.assertEqual(trailers.first_addresses(manifest),
                         ['http://127.0.0.1:50152/youtube/stream?itag=136&a=1', 'http://127.0.0.1:50152/youtube/stream?itag=140'])
        self.assertEqual(trailers.first_addresses('not a manifest'), [])
        read = []

        def fetch(address, headers, seconds, span):
            read.append((address.rpartition('?')[2] or address, headers.get('User-Agent'), seconds, span))
            return manifest.encode('utf-8') if span is None else b'x' * 1024
        self.assertEqual(trailers.reachable(STREAM, fetch), dict(STREAM, seconds=None),
                         'it answers at its own address: handed on as it is (this manifest does not say how long)')
        self.assertEqual(read, [('http://127.0.0.1:50152/youtube/manifest/dash/x.mpd', 'Kodi 21', trailers.ANSWER_S, None),
                                ('itag=136&a=1', 'Kodi 21', trailers.ANSWER_S, 'bytes=0-1023'),
                                ('itag=140', 'Kodi 21', trailers.ANSWER_S, 'bytes=0-1023')])
        self.assertLessEqual(trailers.ANSWER_S, 5, 'a short wait: this is what replaces twenty seconds inside Kodi')
        # the manifest does not come, a stream stays silent, or the read fails: a no, and only the log hears why
        said = []
        self.assertIsNone(trailers.reachable(STREAM, lambda a, h, s, span: b'' if span is None else b'x', log=said.append))
        self.assertIsNone(trailers.reachable(STREAM, lambda a, h, s, span: manifest.encode() if span is None else b'', log=said.append))

        def refused(address, headers, seconds, span):
            raise ConnectionRefusedError('http://127.0.0.1:50152/secret-address')
        self.assertIsNone(trailers.reachable(STREAM, refused, log=said.append))
        self.assertEqual(said, ['no answer: empty manifest', 'no answer: empty stream',
                                'no answer: manifest ConnectionRefusedError at a "this device" address'],
                         'which step and how -- never the address')
        # a plain file address (no manifest): its first bytes
        read[:] = []
        plain = {'url': 'https://x/video.mp4', 'container': 'mp4'}
        self.assertIs(trailers.reachable(plain, fetch), plain)
        self.assertEqual([r[3] for r in read], ['bytes=0-1023'])
        # the desk: a stream that does not answer never reaches the player, and its title rests for a while
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        desk = self.desk(home, player)
        desk.ready = lambda stream: None
        self.assertFalse(desk.asked()())
        self.assertEqual((player.calls, home.values.get(trailers.ON), home.values.get(trailers.FILE)), ([], None, None))
        self.assertIsNone(desk.asked())
        source = (WIZARD / 'resources/libs/trailers.py').read_text('utf-8')
        self.assertIn('desk = Desk(home, player, resolve, make_item, enabled, log, ready=ready,', source)
        self.assertIn('stream = reachable(stream, fetch, save, log)', source)
        self.assertIn('urllib.request.ProxyHandler({})', source, 'an address inside the device is read with no proxy')

    def test_a_server_that_refuses_its_own_address_is_read_through_the_device_itself(self):
        # the owner's phone, Nov 2026: every trailer ended with an HTTP error on the manifest and none played.
        # The YouTube add-on's server answers only callers from a home-network address, and names its streams
        # at the address of the network interface -- on a mobile or a VPN connection not such an address
        import urllib.error
        there = 'http://100.82.14.7:50152'
        stream = dict(STREAM, url=there + '/youtube/manifest/dash?file=x.mpd')
        manifest = ('<MPD><Period><AdaptationSet mimeType="video/mp4"><Representation><BaseURL>%s/youtube/stream?itag=136&amp;a=1</BaseURL></Representation></AdaptationSet>'
                    '<AdaptationSet mimeType="audio/mp4"><Representation><BaseURL>%s/youtube/stream?itag=140</BaseURL></Representation></AdaptationSet></Period></MPD>' % (there, there))
        read, kept, said = [], [], []

        def fetch(address, headers, seconds, span):
            read.append(address)
            if address.startswith(there):
                raise urllib.error.HTTPError(address, 403, 'Forbidden', None, None)
            return manifest.encode('utf-8') if span is None else b'x' * 1024

        def save(text, address):
            kept.append(text)
            name, served = trailers.kept_address(address)
            self.assertEqual(name, 'povil_x.mpd')
            return served
        got = trailers.reachable(stream, fetch, save, said.append)
        self.assertEqual(got['url'], 'http://127.0.0.1:50152/youtube/manifest/dash?file=povil_x.mpd',
                         "Kodi's player is handed the turned manifest, served by the same server through the device itself")
        # (a manifest that is a FILE is not opened by Kodi's adaptive player: seen in the QA Kodi, three ways)
        self.assertEqual(trailers.kept_address('http://127.0.0.1:50152/youtube/manifest/dash?file=..%2Fx.mpd'), (None, None))
        self.assertEqual(trailers.kept_address('http://127.0.0.1:50152/youtube/manifest/dash'), (None, None))
        self.assertEqual(got['headers'], STREAM['headers'])
        self.assertEqual(read, [there + '/youtube/manifest/dash?file=x.mpd', 'http://127.0.0.1:50152/youtube/manifest/dash?file=x.mpd',
                                'http://127.0.0.1:50152/youtube/stream?itag=136&a=1', 'http://127.0.0.1:50152/youtube/stream?itag=140'])
        self.assertNotIn('100.82.14.7', kept[0], 'every stream address in it is turned the same way')
        self.assertEqual(kept[0].count('http://127.0.0.1:50152/youtube/stream?'), 2)
        self.assertEqual(said, ['manifest HTTP 403 at a "other" address: read through this device instead'], 'the log says why, never where')
        # the server does not answer through the device either (it listens on one address only): no trailer
        said[:] = []

        def nowhere(address, headers, seconds, span):
            raise urllib.error.HTTPError(address, 403, 'Forbidden', None, None) if address.startswith(there) else ConnectionRefusedError()
        self.assertIsNone(trailers.reachable(stream, nowhere, save, said.append))
        self.assertEqual(said, ['no answer: manifest HTTP 403 at a "other" address, ConnectionRefusedError through this device'])
        # the kinds of address the log names
        for url, kind in (('http://127.0.0.1:50152/x', 'this device'), ('http://localhost/x', 'this device'), ('http://192.168.1.20:50152/x', 'home network'),
                          ('http://10.0.0.5/x', 'home network'), ('http://172.20.1.1/x', 'home network'), ('http://192.0.0.4:50152/x', 'other'),
                          ('http://100.82.14.7/x', 'other'), ('http://172.40.1.1/x', 'other'), ('not an address', 'other')):
            self.assertEqual(trailers.address_kind(url), kind, url)
        self.assertIsNone(trailers.through_this_device('http://127.0.0.1:50152/x'))
        self.assertIsNone(trailers.through_this_device('https://rr1.example/videoplayback'))
        source = (WIZARD / 'resources/libs/trailers.py').read_text('utf-8')
        self.assertIn('stream = reachable(stream, fetch, save, log)', source)
        self.assertIn('os.path.join(xbmcvfs.translatePath(TEMP_PATH), name)', source, "kept in the folder the add-on's server serves from")

    def test_a_stop_that_comes_while_the_trailer_opens_is_looked_at_again(self):
        # the owner's phone, his second log: the same trailer opened five times in a row, each stopped within a
        # tenth of a second of its first picture, and the fifth stop froze the screen for twenty seconds. The
        # skin said "stop" during the opening (Kodi's busy dialog is over the home then), the stop was carried
        # out at the first picture, the skin asked again, and so on
        def desk_on(home, player, wanted, said, now):
            desk = trailers.Desk(home, player, lambda video: [STREAM], lambda url, stream: ('item', url), lambda: True,
                                 log=said.append, clock=lambda: now[0], wanted_now=wanted, look=lambda key: 'home=1 dialog=0 busy=1 title=none focus=none')
            desk.born = 0.0
            return desk
        home, player, said, now = Home(**{trailers.ASK: ADDRESS}), Player(), [], [1000.0]
        seen = []
        desk = desk_on(home, player, lambda key: (seen.append(key), True)[1], said, now)
        self.assertTrue(desk.asked()())
        home.values[trailers.ASK] = ''              # the skin: ClearProperty + "stop"
        desk.stop()
        self.assertEqual(said, ['stop while opening (home=1 dialog=0 busy=1 title=none focus=none)'], 'what the screen looked like, for the log')
        desk.playback_started()                      # the first picture: the home is asked again
        self.assertEqual(seen, [ADDRESS])
        self.assertEqual(player.calls, [('play', STREAM['url'], True)], 'not stopped: the title is still the one on screen')
        self.assertEqual((home.values[trailers.ASK], home.values[trailers.ON]), (ADDRESS, ADDRESS),
                         "the skin's question is put back: it neither asks again nor hides the picture")
        self.assertEqual(said[-1], 'a stop that came while the trailer opened was not meant: it plays on')
        self.assertIsNone(desk.asked(), 'and nothing is asked of YouTube a second time')
        # ... and when the viewer did move on, it is stopped as before
        home, player, said, now = Home(**{trailers.ASK: ADDRESS}), Player(), [], [1000.0]
        desk = desk_on(home, player, lambda key: False, said, now)
        desk.asked()()
        home.values[trailers.ASK] = ''
        desk.stop()
        desk.playback_started()
        self.assertEqual(player.calls[-1], ('stop',))
        self.assertNotIn(trailers.ON, home.values)
        # the home cannot be read (Kodi closing, an error): stopped, never left playing unseen
        home, player, said, now = Home(**{trailers.ASK: ADDRESS}), Player(), [], [1000.0]
        desk = desk_on(home, player, lambda key: 1 / 0, said, now)
        desk.asked()()
        home.values[trailers.ASK] = ''
        desk.stop()
        desk.playback_started()
        self.assertEqual(player.calls[-1], ('stop',))
        # in Kodi the second look is half a second after the first picture, off the thread Kodi speaks on
        source = (WIZARD / 'resources/libs/trailers.py').read_text('utf-8')
        self.assertIn('wanted_now=wanted_now, look=look, settle=SETTLE_S, no_picture=no_picture, translated=translated)', source)
        self.assertIn("threading.Thread(target=self._late_stop, args=late, name='POVILTrailerLook').start()", source)
        self.assertIn("xbmc.getInfoLabel('Control.GetLabel(%d)' % HERO_LABEL) == key", source)
        self.assertEqual(trailers.HERO_LABEL, 9809)
        home_xml = (XML / 'Home.xml').read_text('utf-8')
        self.assertEqual(home_xml.count('<control type="label" id="9809">'), 1)
        # an id of its own: until Onyx 1.0.17 it shared 9808 with the ratings row's hidden TMDb label
        self.assertEqual(home_xml.count('id="9808"'), 1)
        self.assertIn('id="9808"><left>-2000</left><top>0</top><width>10</width><height>10</height><label>$VAR[POVIL_RatingsTmdb]</label>', home_xml)
        # the log is told of a stop during an opening five times at most
        home, player, said, now = Home(**{trailers.ASK: ADDRESS}), Player(), [], [1000.0]
        desk = desk_on(home, player, lambda key: True, said, now)
        for _ in range(8):
            home.values[trailers.ASK] = ADDRESS
            desk.ours, desk.key, desk.opening = STREAM['url'], ADDRESS, now[0]
            desk.stop()
        self.assertEqual(sum(1 for line in said if line.startswith('stop while opening')), 5)

    def test_a_title_whose_trailer_is_stopped_as_it_begins_twice_is_left_alone(self):
        # whatever stops it would stop it again: on the phone it was five times in ten seconds
        home, player, said, now = Home(**{trailers.ASK: ADDRESS}), Player(), [], [1000.0]
        desk = trailers.Desk(home, player, lambda video: [STREAM], lambda url, stream: ('item', url), lambda: True,
                             log=said.append, clock=lambda: now[0])
        desk.born = 0.0
        for n in range(2):
            home.values[trailers.ASK] = ADDRESS
            self.assertTrue(desk.asked()(), n)
            desk.playback_started()
            now[0] += 0.2                           # a moment after its first picture
            home.values[trailers.ASK] = ''
            self.assertTrue(desk.stop())
            player.playing = None
            desk.playback_over()
        self.assertEqual(said, ['stopped as it began, twice: hoRHBV0m1hw'])
        home.values[trailers.ASK] = ADDRESS
        self.assertIsNone(desk.asked(), 'this title rests')
        other = ADDRESS.replace('hoRHBV0m1hw', 'aaaaaaaaaaa')
        home.values[trailers.ASK] = other
        self.assertIsNotNone(desk.asked(), 'another title is tried as always')
        # a trailer watched for a while and then left is not "as it began": the count starts again
        home, player, said, now = Home(**{trailers.ASK: ADDRESS}), Player(), [], [1000.0]
        desk = trailers.Desk(home, player, lambda video: [STREAM], lambda url, stream: ('item', url), lambda: True,
                             log=said.append, clock=lambda: now[0])
        desk.born = 0.0
        for seconds in (0.2, trailers.QUICK_S + 5, 0.2):
            home.values[trailers.ASK] = ADDRESS
            self.assertTrue(desk.asked()())
            desk.playback_started()
            now[0] += seconds
            home.values[trailers.ASK] = ''
            desk.stop()
            player.playing = None
            desk.playback_over()
            now[0] += trailers.OPENS_S          # (each visit to the title a while after the last)
        self.assertEqual(said, [])

    def test_one_titles_trailer_is_opened_twice_a_minute_at_most(self):
        # the owner, after every fix above: removing a series from "next episode" still opened the trailer five
        # times and left the screen stuck -- a case the QA Kodi would not show. Whatever stops a trailer and
        # asks for it again, it cannot do so more than twice
        home, player, said, now = Home(**{trailers.ASK: ADDRESS}), Player(), [], [1000.0]
        desk = trailers.Desk(home, player, lambda video: [STREAM], lambda url, stream: ('item', url), lambda: True,
                             log=said.append, clock=lambda: now[0])
        desk.born = 0.0
        for n in range(trailers.OPENS):
            home.values[trailers.ASK] = ADDRESS
            self.assertTrue(desk.asked()(), n)
            # (stopped before its first picture each time -- by another add-on's play, say -- so neither the
            # desk's own "stopped as it began" nor anything else has counted it)
            player.playing = None
            desk.opening = None
            desk._forget()
        home.values[trailers.ASK] = ADDRESS
        self.assertFalse(desk.asked()())
        self.assertEqual(said, ['opened %d times in %d s: hoRHBV0m1hw' % (trailers.OPENS, trailers.OPENS_S)])
        self.assertEqual(sum(1 for call in player.calls if call[0] == 'play'), trailers.OPENS)
        self.assertIsNone(desk.asked(), 'the title rests')
        other = ADDRESS.replace('hoRHBV0m1hw', 'aaaaaaaaaaa')
        home.values[trailers.ASK] = other
        self.assertTrue(desk.asked()(), 'another title is opened as always')
        # the owner: "someone browsing sees four, five trailers a minute, even more" -- a trailer that was watched
        # for a few seconds is not counted at all: back and forth between two titles, as often as one likes
        home, player, said, now = Home(), Player(), [], [1000.0]
        desk = trailers.Desk(home, player, lambda video: [STREAM], lambda url, stream: ('item', url), lambda: True,
                             log=said.append, clock=lambda: now[0])
        desk.born = 0.0
        for n in range(8):
            home.values[trailers.ASK] = ADDRESS if n % 2 == 0 else other
            self.assertTrue(desk.asked()(), n)
            desk.playback_started()
            now[0] += 4.0
            home.values[trailers.ASK] = ''
            desk.stop()
            player.playing = None
            desk.playback_over()
        self.assertEqual(said, [])
        self.assertEqual(sum(1 for call in player.calls if call[0] == 'play'), 8)

    def test_no_trailer_starts_while_pov_carries_out_an_action(self):
        # a menu's action may ask a question a few seconds later (a slow box), a pressed title starts a film:
        # neither may find a trailer opening under it. POV's router notes every action before POV loads
        acting = [True]
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        desk = trailers.Desk(home, player, lambda video: [STREAM], lambda url, stream: ('item', url), lambda: True,
                             acting=lambda: acting[0])
        desk.born = 0.0
        self.assertIsNone(desk.asked())
        acting[0] = False
        job = desk.asked()
        acting[0] = True                            # the action began while the stream was being named
        self.assertFalse(job())
        self.assertEqual(player.calls, [])
        with mock.patch.dict(sys.modules, {'xbmc': types.SimpleNamespace(log=lambda *a: None, LOGINFO=1, LOGWARNING=2)}):
            spec_s = importlib.util.spec_from_file_location('snap_action_test', WIZARD / 'resources/libs/patches/pov_list_snapshot.py')
            snap = importlib.util.module_from_spec(spec_s)
            spec_s.loader.exec_module(snap)
        self.assertEqual(snap.ACTION_PROPERTY, trailers.ACTION)
        source = (WIZARD / 'resources/libs/patches/pov_list_snapshot.py').read_text('utf-8')
        early = source[source.index('def serve_early(argv):'):]
        self.assertLess(early.index("setProperty(ACTION_PROPERTY, '%.3f' % time.time())"), early.index('if params is not None and handle < 0 and params.get'),
                        'for every route that is not a list, before anything else')
        code = (WIZARD / 'resources/libs/trailers.py').read_text('utf-8')
        self.assertIn('float(home.getProperty(ACTION) or 0) < ACTION_REST_S', code)

    def test_a_real_trailer_not_a_ten_second_spot(self):
        # the owner: "how am I to know in ten seconds whether I want to watch?" The Hebrew "trailer" TMDb names
        # for a film is often a distributor's short spot
        self.assertEqual(trailers.video_ids(ADDRESS), ['hoRHBV0m1hw'])
        named = ADDRESS + '&povil_alt=bbbbbbbbbbb.ccccccccccc.not-an-id.hoRHBV0m1hw'
        self.assertEqual(trailers.video_ids(named), ['hoRHBV0m1hw', 'bbbbbbbbbbb', 'ccccccccccc'])
        self.assertEqual(trailers.video_id(named), 'hoRHBV0m1hw')
        self.assertEqual(trailers.video_ids('plugin://plugin.video.pov/?x&povil_alt=bbbbbbbbbbb'), [])
        for text, seconds in (('<MPD mediaPresentationDuration="PT10.5S">', 10.5), ('<MPD mediaPresentationDuration="PT2M30S">', 150.0),
                              ('<MPD mediaPresentationDuration="PT1H2M3.5S">', 3723.5), ('<MPD>', None), ('', None)):
            self.assertEqual(trailers.manifest_seconds(text), seconds, text)
        lengths = {'hoRHBV0m1hw': 10.0, 'bbbbbbbbbbb': 30.0, 'ccccccccccc': 150.0}

        def desk_for(home, player, lengths):
            resolved = []
            desk = trailers.Desk(home, player, lambda video: (resolved.append(video), [dict(STREAM, url='http://x/%s.mpd' % video)])[1],
                                 lambda url, stream: ('item', url), lambda: True,
                                 ready=lambda stream: dict(stream, seconds=lengths[stream['url'][9:20]]))
            desk.born = 0.0
            return desk, resolved
        home, player = Home(**{trailers.ASK: named}), Player()
        desk, resolved = desk_for(home, player, lengths)
        self.assertTrue(desk.asked()())
        self.assertEqual(resolved, ['hoRHBV0m1hw', 'bbbbbbbbbbb', 'ccccccccccc'], 'ten seconds, thirty seconds, then a real one')
        self.assertEqual(player.calls, [('play', 'http://x/ccccccccccc.mpd', True)])
        self.assertEqual(home.values[trailers.ON], named, 'for the skin it is the title\'s trailer whichever of them plays')
        # the next visit asks for the one found, alone
        desk.playback_started()
        home.values[trailers.ASK] = ''
        desk.stop()
        player.playing = None
        desk.playback_over()
        home.values[trailers.ASK] = named
        desk.clock = lambda: 5000.0
        self.assertTrue(desk.asked()())
        self.assertEqual(resolved[3:], ['ccccccccccc'])
        # none is long enough: the longest of those read
        home, player = Home(**{trailers.ASK: named}), Player()
        desk, resolved = desk_for(home, player, {'hoRHBV0m1hw': 20.0, 'bbbbbbbbbbb': 30.0, 'ccccccccccc': 12.0})
        self.assertTrue(desk.asked()())
        self.assertEqual(player.calls, [('play', 'http://x/bbbbbbbbbbb.mpd', True)])
        # the first is long enough: nothing else is asked of YouTube
        home, player = Home(**{trailers.ASK: named}), Player()
        desk, resolved = desk_for(home, player, {'hoRHBV0m1hw': 95.0})
        self.assertTrue(desk.asked()())
        self.assertEqual(resolved, ['hoRHBV0m1hw'])
        # the viewer moved on while the alternatives were being read: nothing plays, nothing more is asked
        home, player = Home(**{trailers.ASK: named}), Player()
        desk, resolved = desk_for(home, player, lengths)
        job = desk.asked()
        keep = desk.ready
        desk.ready = lambda stream: (home.values.update({trailers.ASK: ''}), keep(stream))[1]
        self.assertFalse(job())
        self.assertEqual((resolved, player.calls), (['hoRHBV0m1hw'], []))
        self.assertLessEqual(trailers.TRIES, 3, 'each alternative costs a second or two before the trailer starts')

    def test_three_trailers_in_a_row_that_do_not_play_and_the_trailers_rest(self):
        # a device they do not work on is not asked of YouTube at every title
        home, player = Home(), Player()
        now = [1000.0]
        said = []
        desk = trailers.Desk(home, player, lambda video: [STREAM], lambda url, stream: ('item', url), lambda: True,
                             log=said.append, clock=lambda: now[0], ready=lambda stream: None)
        desk.born = 0.0
        resolved = []
        desk.resolve = lambda video: (resolved.append(video), [STREAM])[1]
        for n in range(trailers.FAILS):
            home.values[trailers.ASK] = ADDRESS.replace('hoRHBV0m1hw', 'aaaaaaaaaa%d' % n)
            self.assertFalse(desk.asked()())
        self.assertEqual(said[-1], '%d trailers in a row did not play: none is tried for %d minutes' % (trailers.FAILS, trailers.REST_S // 60))
        home.values[trailers.ASK] = ADDRESS
        self.assertIsNone(desk.asked(), 'resting')
        self.assertEqual(len(resolved), trailers.FAILS)
        now[0] += trailers.REST_S
        self.assertIsNotNone(desk.asked(), 'and tried again later')
        # one that plays in between: the count starts again
        desk = trailers.Desk(home, player, lambda video: [STREAM], lambda url, stream: ('item', url), lambda: True, clock=lambda: now[0])
        desk.born = 0.0
        desk.failed = trailers.FAILS - 1
        self.assertTrue(desk.asked()())
        desk.playback_started()
        self.assertEqual(desk.failed, 0)

    def test_a_player_that_is_still_opening_is_never_told_to_stop(self):
        # seen twice in one hour in the QA Kodi: the viewer moved on in the second the trailer opened, the
        # player was told to stop, and Kodi's screen waited minutes for it
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        desk = self.desk(home, player)
        self.assertTrue(desk.asked()())
        home.values[trailers.ASK] = ''
        self.assertFalse(desk.stop())
        self.assertEqual(player.calls, [('play', STREAM['url'], True)], 'no stop yet')
        self.assertNotIn(trailers.ON, home.values, 'but the picture is off the screen at once')
        self.assertNotIn(trailers.OPENING, home.values, "and Kodi's spinner is Kodi's again")
        self.assertEqual(home.values[trailers.FILE], STREAM['url'], 'still a trailer to the subtitles add-on and to a film about to start')
        # the next title's trailer waits for it
        other = ADDRESS.replace('hoRHBV0m1hw', 'aaaaaaaaaaa')
        home.values[trailers.ASK] = other
        job = desk.asked()
        waits = []

        def wait(seconds):
            waits.append(seconds)
            if len(waits) == 3:
                desk.playback_started()         # the first trailer shows its first picture
                self.assertEqual(player.calls[-1], ('stop',), 'and is stopped right then')
            return False
        desk.waiting.wait = wait
        self.assertTrue(job())
        self.assertEqual(len(waits), 3)
        self.assertEqual(player.calls[-1][0], 'play', 'the next trailer, once the player is free')
        self.assertEqual(home.values[trailers.ON], other)
        # the viewer came back to the title before its trailer had opened: it simply goes on
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        desk = self.desk(home, player)
        desk.asked()()
        home.values[trailers.ASK] = ''
        desk.stop()
        home.values[trailers.ASK] = ADDRESS
        self.assertIsNone(desk.asked(), 'not asked of YouTube again')
        self.assertEqual(home.values[trailers.ON], ADDRESS)
        desk.playback_started()
        self.assertEqual(player.calls, [('play', STREAM['url'], True)], 'and not stopped at its first picture')
        # it fails while it opens: the desk forgets it, its title rests, and Kodi's box is to be closed
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        desk = self.desk(home, player)
        desk.asked()()
        home.values[trailers.ASK] = ''
        desk.stop()
        player.playing = None
        self.assertTrue(desk.playback_over(), 'it never showed a picture')
        self.assertEqual((desk.ours, home.values.get(trailers.FILE)), (None, None))
        home.values[trailers.ASK] = ADDRESS
        self.assertIsNone(desk.asked())
        self.assertFalse(desk.playback_over(), 'a playback that is not the trailer\'s: nothing to close')

    def test_kodis_playback_failed_box_never_shows_for_a_trailer(self):
        # seen in the QA Kodi with an address that answers nothing: Kodi put "playback failed" on the home
        ran, naps = [], []
        shown = iter([False, False, True])
        self.assertTrue(trailers.close_failure_box(lambda cond: (self.assertEqual(cond, trailers.FAILURE_BOX), next(shown))[1],
                                                   ran.append, lambda s: naps.append(s)))
        # only Kodi's own box (its heading is Kodi's "Playback failed"): another OK box is not this module's
        self.assertEqual(trailers.FAILURE_BOX, 'Window.IsActive(okdialog) + String.IsEqual(Control.GetLabel(1),$LOCALIZE[16026])')
        self.assertEqual((ran, len(naps)), (['Dialog.Close(okdialog,true)'], 2))
        # no box came up (or Kodi is closing): nothing is closed, and the look-out ends
        ran[:] = []
        naps[:] = []
        self.assertFalse(trailers.close_failure_box(lambda cond: False, ran.append, lambda s: naps.append(s)))
        self.assertEqual((ran, len(naps)), ([], round(trailers.FAILURE_BOX_S / 0.1)))
        self.assertFalse(trailers.close_failure_box(lambda cond: False, ran.append, lambda s: True))
        # a trailer that played and ended, or was stopped: no look-out at all
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        desk = self.desk(home, player)
        desk.asked()()
        desk.playback_started()
        player.playing = None
        self.assertFalse(desk.playback_over())
        source = (WIZARD / 'resources/libs/trailers.py').read_text('utf-8')
        self.assertIn('if desk.playback_over():', source)
        self.assertIn('target=close_failure_box', source)

    def test_a_trailer_the_desk_forgot_is_stopped_if_it_shows_a_picture_after_all(self):
        # review, Nov 2026: a "stopped" of another playback arriving while the trailer opens is taken for its
        # failing; the trailer then opened anyway and played unseen, with its sound, until it ended
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        desk = self.desk(home, player)
        desk.asked()()
        player.playing = None                       # Kodi has not begun to open it yet
        self.assertTrue(desk.playback_over())       # ... and says a playback stopped (an earlier one's)
        self.assertIsNone(desk.ours)
        player.playing = STREAM['url']              # it opens after all
        desk.playback_started()
        self.assertEqual(player.calls[-1], ('stop',), 'stopped at its first picture')
        self.assertIsNone(desk.let_go)
        # a film that starts next is nobody's orphan
        player.playing = 'http://debrid/film.mkv'
        calls = len(player.calls)
        desk.playback_started()
        self.assertEqual(len(player.calls), calls)
        # a trailer stopped the ordinary way leaves nothing to stop later
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        desk = self.desk(home, player)
        desk.asked()()
        desk.playback_started()
        desk.stop()
        desk.playback_over()
        player.playing = 'http://debrid/film.mkv'
        calls = len(player.calls)
        desk.playback_started()
        self.assertEqual((len(player.calls), desk.let_go), (calls, None))

    def test_an_opening_kodi_never_says_a_word_about_ends_by_itself(self):
        other = ADDRESS.replace('hoRHBV0m1hw', 'aaaaaaaaaaa')
        # Kodi never says a word about it: after a while the opening is over by itself
        home, player = Home(**{trailers.ASK: ADDRESS}), Player()
        now = [1000.0]
        desk = trailers.Desk(home, player, lambda video: [STREAM], lambda url, stream: ('item', url), lambda: True, clock=lambda: now[0])
        desk.born = 0.0
        desk.asked()()
        player.playing = None
        home.values[trailers.ASK] = ''
        desk.stop()
        now[0] += trailers.OPEN_LIMIT_S
        home.values[trailers.ASK] = other
        self.assertTrue(desk.asked()(), 'the next title is not kept waiting for ever')

    def test_headers_reach_the_player_as_kodi_wants_them(self):
        self.assertEqual(trailers.headers_text({'User-Agent': 'Kodi 21', 'Accept': '*/*'}), 'Accept=%2A/%2A&User-Agent=Kodi%2021')
        self.assertEqual(trailers.headers_text('a=b'), 'a=b')
        self.assertEqual(trailers.headers_text(None), '')


class SkinTests(unittest.TestCase):
    def test_the_skin_asks_after_a_rest_and_says_stop_the_moment_anything_changes(self):
        timers = {t.findtext('name'): t for t in ET.parse(XML / 'Timers.xml').getroot().findall('timer')}
        start = timers['povil_trailer'].findtext('start')
        for part in ('Window.IsActive(home)', '!Skin.HasSetting(POVILNoTrailers)', '!System.HasActiveModalDialog',
                     # the rest is the viewer's choice: 1 s while none is made (the owner: "almost at once")
                     '[[String.IsEqual(Skin.String(POVILTrailerWait),1) | String.IsEmpty(Skin.String(POVILTrailerWait))] + System.IdleTime(1)]',
                     '[String.IsEqual(Skin.String(POVILTrailerWait),3) + System.IdleTime(3)]',
                     # none while an add-on is finding a pressed title's sources (a film is about to start)
                     '!Window.IsVisible(extendedprogressdialog)',
                     '!String.IsEmpty(Control.GetLabel(9809))',
                     '[!Player.HasMedia | !String.IsEmpty(Window(home).Property(povil.tr.on))]'):
            self.assertIn(part, start)
        # (every new trailer counts its seconds on the screen from its own first picture)
        self.assertEqual([n.text for n in timers['povil_trailer'].findall('onstart')],
                         ['Skin.TimerStop(povil_trailer_shown)',
                          'SetProperty(povil.tr.ask,$ESCINFO[Control.GetLabel(9809)],home)', 'NotifyAll(povil.trailer,ask)'])
        stop = timers['povil_trailer_stop'].findtext('start')
        for part in ('!Window.IsActive(home)', '| Skin.HasSetting(POVILNoTrailers) |',
                     # the title is compared only with no busy dialog over the home: under one the label reads
                     # empty (the owner's phone: the trailer stopped at its first picture, five times in a row)
                     '[!Window.IsActive(busydialog) + !Window.IsActive(busydialognocancel) + '
                     '!String.IsEqual(Control.GetLabel(9809),Window(home).Property(povil.tr.ask))]',
                     # Kodi's own busy dialog comes up while the trailer itself opens: it must not stop it
                     # (seen in the QA Kodi: the trailer was stopped by the dialog its own start brought up)
                     '[System.HasActiveModalDialog + !Window.IsActive(busydialog) + !Window.IsActive(busydialognocancel)]'):
            self.assertIn(part, stop)
        busy = (XML / 'DialogBusy.xml').read_text('utf-8')
        self.assertIn('<visible>String.IsEmpty(Window(home).Property(povil.tr.opening)) | '
                      'Integer.IsGreater(Skin.TimerElapsedSecs(povil_trailer_opening),5)</visible>', busy,
                      'no spinner over a title being read while its trailer opens -- for its first seconds only')
        opening = timers['povil_trailer_opening']
        self.assertEqual((opening.findtext('start'), opening.findtext('stop')),
                         ('!String.IsEmpty(Window(home).Property(povil.tr.opening))',
                          'String.IsEmpty(Window(home).Property(povil.tr.opening))'))
        self.assertEqual(opening.find('start').get('reset'), 'true')
        self.assertEqual([n.text for n in timers['povil_trailer_stop'].findall('onstart')],
                         ['Skin.TimerStop(povil_trailer_shown)', 'ClearProperty(povil.tr.ask,home)', 'NotifyAll(povil.trailer,stop)'])
        for name in ('povil_trailer', 'povil_trailer_stop', 'povil_trailer_peek'):
            self.assertEqual(timers[name].findtext('stop'), 'true', 'ready for the next title')
        # the title the screen is on is named at once: the Wizard reads its trailer while the screen rests
        peek = timers['povil_trailer_peek']
        for part in ('Window.IsActive(home)', '!Skin.HasSetting(POVILNoTrailers)', '!System.HasActiveModalDialog',
                     '!String.IsEqual(Control.GetLabel(9809),Window(home).Property(povil.tr.peek))'):
            self.assertIn(part, peek.findtext('start'))
        self.assertNotIn('IdleTime', peek.findtext('start'))
        self.assertEqual([n.text for n in peek.findall('onstart')],
                         ['SetProperty(povil.tr.peek,$ESCINFO[Control.GetLabel(9809)],home)', 'NotifyAll(povil.trailer,peek)'])

    def test_the_picture_is_behind_the_hero_only_for_the_title_on_screen(self):
        home = ET.parse(XML / 'Home.xml').getroot()
        controls = list(home.iter('control'))
        video = next(c for c in controls if c.get('type') == 'videowindow')
        shown = video.findtext('visible')
        self.assertIn('Player.HasVideo', shown)
        self.assertIn('String.IsEqual(Window(home).Property(povil.tr.on),Window(home).Property(povil.tr.ask))', shown)
        self.assertIn('!String.IsEmpty(Window(home).Property(povil.tr.on))', shown)
        # its first picture has come (the owner's LG: a player that hung opening said it had a video)
        self.assertIn('String.IsEmpty(Window(home).Property(povil.tr.opening))', shown)
        # and it takes no clicks: a click on a video window is Kodi's "to full screen" (the owner's phone: a tap
        # on the trailer stopped it and brought the home back on the films tab)
        hit = video.find('hitrect')
        self.assertIsNotNone(hit)
        self.assertLess(int(hit.get('x')) + int(hit.get('w')), 0)
        self.assertLess(int(hit.get('y')) + int(hit.get('h')), 0)
        order = [c.get('description') for c in controls]
        self.assertLess(order.index('backdrop'), order.index('trailer'))
        self.assertLess(order.index('under the trailer'), order.index('trailer'))
        for shade in ('hero shade', 'rows shade', 'top shade'):
            self.assertLess(order.index('trailer'), order.index(shade), 'under every shade: the text stays clear')
        plot = next(c for c in controls if c.get('description') == 'plot')
        self.assertTrue(any(a.get('condition') == shown for a in plot.findall('animation')), 'the plot steps aside meanwhile')
        # only a POV title's YouTube trailer is ever asked for
        variables = {v.get('name'): v for v in ET.parse(XML / 'Includes_POVIL_Home.xml').getroot().findall('variable')}
        values = [v for v in variables['POVIL_HeroTrailer'].findall('value') if v.text]
        self.assertTrue(values)
        for value in values:
            self.assertIn('ListItem.Trailer,plugin://plugin.video.youtube/)', value.get('condition'))
            self.assertIn('new_page=', value.get('condition'))

    def test_the_trailer_gets_the_screen_to_itself_and_any_key_brings_the_home_back(self):
        # the owner, Nov 2026: "so the viewer can watch the trailer if they want, and read it" -- a Hebrew
        # trailer's words are in the picture, under the home's rows until everything over it steps aside
        home = ET.parse(XML / 'Home.xml').getroot()
        over = next(c for c in home.iter('control') if c.get('description') == 'over the picture')
        fade = over.find('animation')
        alone = fade.get('condition')
        self.assertEqual((fade.get('effect'), fade.get('end'), fade.text), ('fade', '0', 'Conditional'))
        for part in ('Player.HasVideo', 'povil.tr.on',
                     # the count of THIS trailer: a stopped timer keeps the last one's (the home faded at once)
                     'Skin.TimerIsRunning(povil_trailer_shown)',
                     # 4 s on the screen and the remote still for 3, as always, while the viewer chose nothing
                     '[[String.IsEqual(Skin.String(POVILTrailerFull),4) | String.IsEmpty(Skin.String(POVILTrailerFull))] + '
                     'Integer.IsGreaterOrEqual(Skin.TimerElapsedSecs(povil_trailer_shown),4) + System.IdleTime(3)]',
                     '[String.IsEqual(Skin.String(POVILTrailerFull),2) + '
                     'Integer.IsGreaterOrEqual(Skin.TimerElapsedSecs(povil_trailer_shown),2) + System.IdleTime(2)]'):
            self.assertIn(part, alone, 'only a trailer that has been on a few seconds, and only while the remote is still')
        self.assertNotIn('POVILTrailerFull),0)', alone, '"never": no fade at all')
        inside = {c.get('description') for c in over.iter('control')} | {c.get('id') for c in over.iter('control')}
        for part in ('hero', 'chips', 'clock', '9000', '5011'):
            self.assertIn(part, inside, part)
        self.assertNotIn('trailer', inside, 'the picture itself stays')
        shades = [c for c in home.iter('control') if (c.get('description') or '').endswith('shade') or c.get('description') == 'vignette']
        self.assertEqual(len(shades), 4)
        for shade in shades:
            self.assertEqual(shade.find('animation').get('condition'), alone, shade.get('description'))
        timers = {t.findtext('name'): t for t in ET.parse(XML / 'Timers.xml').getroot().findall('timer')}
        shown = timers['povil_trailer_shown']
        self.assertIn('Player.HasVideo', shown.findtext('start'))
        self.assertIn('!Window.IsActive(home)', shown.findtext('stop'))

    def test_it_is_on_for_everyone_and_a_tile_switches_it_off(self):
        # the owner, Nov 2026: "turn it on by default for everyone". The setting says OFF, so a device that
        # never saw it has the trailers on; the tile among the home's shortcuts says which and switches
        for name in ('Home.xml', 'Includes_POVIL_Home.xml', 'Timers.xml'):
            text = (XML / name).read_text('utf-8')
            self.assertNotIn('POVILTrailers)', text, name + ': the old on-switch is gone')
        home = (XML / 'Home.xml').read_text('utf-8') + (XML / 'Includes_POVIL_Home.xml').read_text('utf-8')
        self.assertEqual(home.count('Skin.ToggleSetting(POVILNoTrailers)'), 1)
        variables = {v.get('name'): v for v in ET.parse(XML / 'Includes_POVIL_Home.xml').getroot().findall('variable')}
        said = [(v.get('condition'), v.text) for v in variables['POVIL_TrailersTile'].findall('value')]
        self.assertEqual(said, [('Skin.HasSetting(POVILNoTrailers)', 'טריילרים: כבוי'), (None, 'טריילרים: פועל')])

    def test_the_trailer_is_gone_before_pov_or_umbrella_start_their_player(self):
        # review, Nov 2026: POV's player waits for Kodi's first word about a playback after it starts one; the
        # trailer's "stopped" came first and the film played with no resume point and no watched mark
        spec_g = importlib.util.spec_from_file_location('gone_test', WIZARD / 'resources/libs/patches/home_trailer_gone.py')
        gone = importlib.util.module_from_spec(spec_g)
        spec_g.loader.exec_module(gone)
        self.assertEqual(gone.FILE, trailers.FILE)

        def kodi(playing, named, stops_after=2, opens_after=None, over_after=None):
            """playing: what the player plays; named: the trailer's address in the home's property.
            stops_after: the player is gone that many sleeps after the built-in stop. opens_after: the
            trailer shows its first picture after that many sleeps. over_after: the desk empties the
            property after that many sleeps."""
            did, home = [], Home(**({trailers.FILE: named} if named else {}))
            player = Player(playing=playing)
            player.stop = lambda: self.fail('never Python\'s own stop: it holds Python while Kodi asks a Python server')

            def sleep(ms):
                did.append(('sleep', ms))
                naps = sum(1 for d in did if d[0] == 'sleep')
                if opens_after is not None and naps >= opens_after and 'stop' not in did:
                    player.playing = named
                if over_after is not None and naps >= over_after:
                    home.clearProperty(trailers.FILE)
                if 'stop' in did and sum(1 for d in did[did.index('stop'):] if d[0] == 'sleep') >= stops_after:
                    player.playing = None
            xbmc = types.SimpleNamespace(Player=lambda: player, sleep=sleep,
                                         executebuiltin=lambda text: did.append('stop' if text == 'PlayerControl(Stop)' else text))
            return xbmc, types.SimpleNamespace(Window=lambda _id: home), player, did

        xbmc, xbmcgui, player, did = kodi(STREAM['url'], STREAM['url'])
        self.assertTrue(gone.before_play(xbmc, xbmcgui))
        self.assertEqual(did, ['stop', ('sleep', 50), ('sleep', 50), ('sleep', gone.SETTLE_MS)],
                         'Kodi\'s built-in stop, waited for until it is gone, and a moment for its "stopped" to be said')
        self.assertIsNone(player.playing)
        # nothing of the trailer's plays, or what plays is not the trailer: nothing is touched
        for playing, named in ((None, None), ('http://debrid/film.mkv', STREAM['url']), ('http://debrid/film.mkv', None)):
            xbmc, xbmcgui, player, did = kodi(playing, named)
            self.assertFalse(gone.before_play(xbmc, xbmcgui))
            self.assertEqual(did, [])
        # the trailer is still opening: waited for, then stopped -- a player that opens is not told to stop
        xbmc, xbmcgui, player, did = kodi(None, STREAM['url'], opens_after=3)
        self.assertTrue(gone.before_play(xbmc, xbmcgui))
        self.assertEqual(did.index('stop'), 3, 'three waits, then the stop')
        # ... or it failed while it opened (the desk emptied the property): the film just starts
        xbmc, xbmcgui, player, did = kodi(None, STREAM['url'], over_after=2)
        self.assertFalse(gone.before_play(xbmc, xbmcgui))
        self.assertNotIn('stop', did)
        # ... or it never opens: the film starts anyway, after a bounded wait and with nothing stopped
        xbmc, xbmcgui, player, did = kodi(None, STREAM['url'])
        self.assertFalse(gone.before_play(xbmc, xbmcgui))
        self.assertEqual((sum(d[1] for d in did), 'stop' in did), (gone.OPEN_WAIT_S * 1000, False))
        # a trailer that will not go: the film starts anyway, two seconds later at most
        xbmc, xbmcgui, player, did = kodi(STREAM['url'], STREAM['url'], stops_after=10 ** 6)
        self.assertTrue(gone.before_play(xbmc, xbmcgui))
        self.assertEqual(sum(d[1] for d in did if d != 'stop'), gone.GONE_WAIT_S * 1000 + gone.SETTLE_MS)
        # both add-ons call the Wizard right before they start: the call is the first thing there, and a
        # failure of it never stops a film
        guard = (WIZARD / 'resources/libs/patches/profile_age_guard.py').read_text('utf-8')
        body = guard[guard.index('def permit_play('):guard.index('def work_policy(')]
        self.assertLess(body.index('home_trailer_gone.before_play()'), body.index('policy = active_policy()'))
        self.assertIn('    except Exception:\n        pass\n    policy = active_policy()', body.replace('\r\n', '\n'))
        config = (WIZARD / 'resources/libs/patches/patches_config.py').read_text('utf-8')
        for host in ("permit_play(meta or {}, 'pov', url)", "permit_play(_age_meta, 'umbrella', url)"):
            self.assertIn(host, config)

    def test_the_wizard_runs_it_as_a_thread_and_the_subtitles_add_on_leaves_a_trailer_alone(self):
        startup = (WIZARD / 'startup.py').read_text('utf-8')
        self.assertIn("_start_watch('POVILTrailers', _trailers_watch)", startup)
        source = (WIZARD / 'resources/libs/trailers.py').read_text('utf-8')
        self.assertIn('light_streams(video, Provider, XbmcContext, SERVER_WAKEUP, video_codec=video_codec, max_height=max_height)', source)
        self.assertNotIn('youtube_resolver', source.split('"""', 2)[2], 'that door does not wake the add-on\'s server')
        code = source.split('"""', 2)[2]
        self.assertIn("halt=lambda: xbmc.executebuiltin('PlayerControl(Stop)')", code)
        self.assertEqual(len(re.findall(r'player\.stop\b', code)), 1, 'never the blocking stop (40 s of frozen screen, measured)')
        self.assertIn('self.halt = halt or player.stop', code, 'the one mention: the default for a desk run without Kodi')
        self.assertIn('job = desk.asked()', code[code.index('listener = Listener()'):], 'an ask from before the thread listened is not lost')
        self.assertNotIn('PlayMedia', source.split('"""', 2)[2], 'never through Kodi\'s own play of the address: the busy dialog')
        autosub = (ROOT / 'service.subtitles.kodipovilai/resources/lib/autosub_service.py').read_text('utf-8')
        start = autosub.index('def onAVStarted(self):', autosub.index('class AutoSubPlayer'))
        body = autosub[start:autosub.index('def onPlayBackStopped', start)]
        self.assertLess(body.index("getProperty('povil.tr.file')"), body.index('snapshot_on_play'))
        self.assertIn('self.getPlayingFile() == _trailer', body, 'by the address: a film that takes over from a trailer is a film')


if __name__ == '__main__':
    unittest.main()
