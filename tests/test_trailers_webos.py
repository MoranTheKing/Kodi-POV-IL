"""Wizard 0.5.14: an LG TV (webOS) asks YouTube for its trailers in VP9.

The owner's LG, Nov 2026 (webOS 26 firmware, Kodi 21.0): films play, but no trailer ever did -- the TV's decoder
refused the trailer's H.264 stream ("CDVDVideoCodecStarfish: Load failed") and the player hung opening.
"""
import importlib.util
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('trailers_webos_test', ROOT / 'plugin.program.kodipovilwizard/resources/libs/trailers.py')
trailers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trailers)


def ask(video_codec=None, features=('avc1', 'vp9', 'av01', 'mp4a', 'opus', 'hdr', 'hfr'), max_height=None):
    seen = {}

    class Settings(object):
        def mpd_video_qualities(self):
            return [{'nom_height': 2160}, {'nom_height': 1080}, {'nom_height': 720}, {'nom_height': 480}]

        def stream_features(self, raw_values=False):
            return list(features) if raw_values else frozenset(features)

    settings = Settings()

    class Client(object):
        def load_stream_info(self, video_id):
            seen['kinds'] = settings.stream_features()
            seen['heights'] = [q['nom_height'] for q in settings.mpd_video_qualities()]
            return [], None

    class Context(object):
        def ipc_exec(self, target, timeout=None):
            return True

        def get_settings(self):
            return settings

    class Provider(object):
        def get_client(self, context):
            return Client()

    args = {} if video_codec is None else {'video_codec': video_codec}
    if max_height:
        args['max_height'] = max_height
    trailers.light_streams('hoRHBV0m1hw', Provider, Context, 'w', **args)
    return seen


class WebosTests(unittest.TestCase):
    def test_an_lg_tv_is_known_by_what_webos_gives_its_apps(self):
        self.assertTrue(trailers.on_webos('org.xbmc.kodi', '', ''))
        self.assertTrue(trailers.on_webos(None, '/media/developer/apps/usr/palm/applications/org.xbmc.kodi/', ''))
        self.assertTrue(trailers.on_webos(None, '', 'webOS TV 11.2.0, kernel: Linux ARM 64-bit version 6.12'))
        for os_info in ('Windows 11', 'Android 17.0.0 API level 37', 'LibreELEC 12.2.1', ''):
            self.assertFalse(trailers.on_webos(None, 'C:\\Program Files\\Kodi\\', os_info), os_info)
        self.assertFalse(trailers.on_webos('', None, None))

    def test_every_other_device_asks_720p_and_an_lg_tv_1080p_both_h264(self):
        self.assertEqual(ask()['kinds'], frozenset(('avc1', 'mp4a', 'opus')))
        self.assertEqual(ask()['heights'], [720, 480], 'up to 720p elsewhere')
        # an LG TV: H.264 like a film, and a film's size (0.5.13-0.5.15: 720p H.264 and VP9 were refused there)
        self.assertEqual((trailers.WEBOS_VIDEO, trailers.WEBOS_HEIGHT), ('avc1', 1080))
        lg = ask(trailers.WEBOS_VIDEO, max_height=trailers.WEBOS_HEIGHT)
        self.assertEqual(lg['kinds'], frozenset(('avc1', 'mp4a', 'opus')))
        self.assertEqual(lg['heights'], [1080, 720, 480])
        self.assertNotIn('hdr', lg['kinds'])
        self.assertNotIn('hfr', lg['kinds'])
        # (the codec can still be asked for by name)
        self.assertIn('vp9', ask('vp9', features=('avc1', 'mp4a'))['kinds'])
        source = (ROOT / 'plugin.program.kodipovilwizard/resources/libs/trailers.py').read_text('utf-8')
        self.assertIn("on_webos(app_id, xbmcvfs.translatePath('special://xbmc/'), xbmc.getInfoLabel('System.OSVersionInfo'))", source)
        self.assertIn("os.environ.get('APPID') if xbmc.getCondVisibility('System.Platform.Linux + !System.Platform.Android') else None", source)

    def test_an_lg_tv_whose_trailer_shows_no_picture_switches_them_off_once_per_kodi(self):
        import json
        import tempfile
        said, skin = [], {'off': False}
        with tempfile.TemporaryDirectory() as folder:
            path = folder + '/trailers_webos_off.json'
            guard = lambda version: trailers.webos_guard(path, version, off=lambda: skin['off'],
                                                         set_off=lambda on: skin.update(off=on), log=said.append)
            back, switch_off = guard('21.0 (21.0.0) Git:20240406')
            self.assertFalse(back)
            switch_off()
            self.assertTrue(skin['off'], 'the settings tile reads "off"')
            with open(path, encoding='utf-8') as handle:
                self.assertEqual(json.load(handle), {'kodi': '21.0 (21.0.0) Git:20240406', 'way': trailers.WEBOS_WAY})
            # switched off when they were played another way (0.5.14/0.5.15 on the owner's LG): tried once the new way
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump({'kodi': '21.0 (21.0.0) Git:20240406'}, handle)
            back, _ = guard('21.0 (21.0.0) Git:20240406')
            self.assertTrue(back)
            self.assertFalse(skin['off'])
            self.assertIn('a new way to play them', said[-1])
            switch_off()
            # the next start on the same Kodi: still off, nothing said
            said.clear()
            self.assertEqual(guard('21.0 (21.0.0) Git:20240406')[0], False)
            self.assertTrue(skin['off'])
            self.assertEqual(said, [])
            # the TV's Kodi upgraded: on again, once
            back, _ = guard('22.0 (22.0.0) Git:20261110')
            self.assertTrue(back)
            self.assertFalse(skin['off'])
            self.assertIn('trailers on again', said[-1])
            self.assertEqual(guard('22.0 (22.0.0) Git:20261110')[0], False)
            # the viewer switched them back on by hand: the file goes, and an "off" of theirs later is never undone
            switch_off()
            skin['off'] = False
            self.assertEqual(guard('22.0 (22.0.0) Git:20261110')[0], False)
            self.assertFalse(os.path.exists(path))
            skin['off'] = True
            self.assertEqual(guard('22.1')[0], False)
            self.assertTrue(skin['off'])
        # the desk calls it for a trailer that showed no picture at all, not for one that stood still later
        calls = []

        class Player(object):
            def isPlaying(self):
                return False

            def getTime(self):
                return 0.0

        class Home(object):
            def __init__(self):
                self.values = {}

            def getProperty(self, key):
                return self.values.get(key, '')

            def setProperty(self, key, value):
                self.values[key] = value

            def clearProperty(self, key):
                self.values.pop(key, None)
        now = [0.0]
        desk = trailers.Desk(Home(), Player(), lambda video: [], lambda url, stream: None, lambda: True,
                             clock=lambda: now[0], halt=lambda: None, no_picture=lambda: calls.append(1))
        desk.ours, desk.key, desk.opening = 'http://x/m.mpd', 'plugin://plugin.video.youtube/play/?video_id=hoRHBV0m1hw', 0.0

        class Tick(object):
            def wait(self, seconds):
                now[0] += seconds
                return False
        desk.waiting = Tick()
        self.assertTrue(desk.guard())
        self.assertEqual(calls, [1])
        # the owner's LG, 0.5.14: he moved on nine seconds into an opening that never showed a picture -- still
        # counted (the stop waits for the first picture, and none came)
        calls.clear()
        now[0] = 1000.0
        desk.given_up.clear()
        desk.ours, desk.key, desk.opening = 'http://x/n.mpd', 'plugin://plugin.video.youtube/play/?video_id=bbbbbbbbbbb', now[0]
        desk.stop()
        self.assertTrue(desk.stop_wanted)
        self.assertTrue(desk.guard())
        self.assertEqual(calls, [1])
        # ... but a trailer the viewer stopped after its first picture is simply over
        calls.clear()
        desk.ours, desk.key, desk.opening, desk.stop_wanted = 'http://x/o.mpd', 'plugin://plugin.video.youtube/play/?video_id=ccccccccccc', None, False
        desk.ticket += 1
        guard_ticket = desk.ticket

        class Turn(object):
            def wait(self, seconds):
                desk.ticket = guard_ticket + 1      # moved on while the guard watched
                now[0] += seconds
                return False
        desk.waiting = Turn()
        self.assertFalse(desk.guard())
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
