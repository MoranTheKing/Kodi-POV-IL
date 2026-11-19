"""Wizard 0.5.23: the YouTube add-on's server on a port this device lets it open (resources/libs/youtube_port.py).

A viewer, Nov 2026: "YouTube gives an error every time Kodi starts ... 10013 ... the trailers do not play; from the
info screen the trailer does". His log: the add-on's server could not open its port ([WinError 10013]: Windows
keeps that port for itself), and every home trailer found the server asleep. Reproduced in the QA Kodi with the
port held exclusively (the same 10013): the port moved, the add-on's server came up on the new one, and the next
home trailer played on the screen.
"""
import http.server
import importlib.util
import socket
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / 'plugin.program.kodipovilwizard/resources/libs'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


port_fix = load('youtube_port_under_test', LIBS / 'youtube_port.py')
trailers = load('trailers_port_under_test', LIBS / 'trailers.py')
ADDRESS = 'plugin://plugin.video.youtube/play/?video_id=hoRHBV0m1hw'


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
    calls = ()

    def isPlaying(self):
        return False

    def getPlayingFile(self):
        raise RuntimeError('Kodi is not playing any media file')

    def stop(self):
        pass


class ChooseTests(unittest.TestCase):
    def test_a_port_that_answers_or_can_be_opened_stays(self):
        self.assertIsNone(port_fix.choose('127.0.0.1', 50152, can_open=lambda a, p: False, serving=lambda a, p: True))
        self.assertIsNone(port_fix.choose('127.0.0.1', 50152, can_open=lambda a, p: True, serving=lambda a, p: False))

    def test_a_port_this_device_refuses_moves_to_the_first_one_that_opens(self):
        free = {42152, 50252}
        self.assertEqual(port_fix.choose('127.0.0.1', 50152, can_open=lambda a, p: p in free, serving=lambda a, p: False), 42152)
        # never "moved" to the port it is already on
        self.assertEqual(port_fix.choose('127.0.0.1', 41152, can_open=lambda a, p: p in {41152 + 1, 42152} and p != 41152,
                                         serving=lambda a, p: False), 42152)
        self.assertEqual(port_fix.choose('127.0.0.1', 50152, can_open=lambda a, p: False, serving=lambda a, p: False), 0)
        self.assertEqual(port_fix.CANDIDATES[0], 41152, "outside Windows' dynamic range (49152-65535) first")

    def test_a_port_another_socket_holds_cannot_be_opened(self):
        held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            held.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)     # Windows: the viewer's 10013
        held.bind(('127.0.0.1', 0))
        held.listen(1)
        port = held.getsockname()[1]
        try:
            self.assertFalse(port_fix.usable('127.0.0.1', port))
        finally:
            held.close()
        self.assertTrue(port_fix.usable('127.0.0.1', port))

    def test_the_add_on_s_server_is_known_by_its_ping(self):
        class Ping(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(204 if self.path == '/youtube/ping' else 404)
                self.end_headers()

            def log_message(self, *args):
                pass
        server = http.server.HTTPServer(('127.0.0.1', 0), Ping)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            self.assertTrue(port_fix.answers('127.0.0.1', port))
            self.assertTrue(port_fix.answers('0.0.0.0', port), 'listening everywhere: asked at this device')
        finally:
            server.shutdown()
            server.server_close()
        self.assertFalse(port_fix.answers('127.0.0.1', port, seconds=0.5))


class RunTests(unittest.TestCase):
    def kodi(self, settings):
        addon = mock.Mock()
        addon.getSetting = lambda key: settings.get(key, '')
        xbmc = types.SimpleNamespace(getCondVisibility=lambda cond: True)
        return addon, {'xbmc': xbmc, 'xbmcaddon': types.SimpleNamespace(Addon=lambda addon_id: addon)}

    def test_the_new_port_is_the_add_on_s_own_setting_and_its_loaded_modules_read_it_again(self):
        addon, modules = self.kodi({'kodion.http.port': '50152', 'kodion.http.listen': '0.0.0.0'})
        refreshed = []

        class XbmcContext(object):
            def get_settings(self, refresh=False):
                refreshed.append(refresh)
        modules['youtube_plugin.kodion.context'] = types.SimpleNamespace(XbmcContext=XbmcContext)
        said = []
        with mock.patch.dict(sys.modules, modules), mock.patch.object(port_fix, 'choose', return_value=41152) as choose:
            self.assertEqual(port_fix.run(said.append), 41152)
        choose.assert_called_once_with('0.0.0.0', 50152)
        addon.setSetting.assert_called_once_with('kodion.http.port', '41152')
        self.assertEqual(refreshed, [True])
        self.assertEqual(said, ['the YouTube add-on could not open port 50152 on this device: moved to 41152'])

    def test_a_good_port_is_left_alone_and_an_unset_one_is_the_add_on_s_default(self):
        addon, modules = self.kodi({})
        with mock.patch.dict(sys.modules, modules), mock.patch.object(port_fix, 'choose', return_value=None) as choose:
            self.assertIsNone(port_fix.run(lambda text: None))
        choose.assert_called_once_with('127.0.0.1', 50152)
        addon.setSetting.assert_not_called()


class DeskTests(unittest.TestCase):
    def test_a_server_that_did_not_wake_has_its_port_looked_at_once_a_minute(self):
        now = [1000.0]
        repairs = []

        def repair():
            repairs.append(now[0])
            return 41152 if len(repairs) == 1 else None

        def asleep(video):
            raise trailers.Asleep()
        home = Home(**{trailers.ASK: ADDRESS})
        desk = trailers.Desk(home, Player(), asleep, lambda url, stream: ('item', url), lambda: True,
                             clock=lambda: now[0], repair=repair)
        desk.born = 0.0
        said = []
        desk.log = said.append
        self.assertFalse(desk.asked()())
        self.assertEqual(said, ['the YouTube add-on did not wake its server: its port was moved'])
        self.assertEqual(desk.failed, 0, 'not counted: the next title has the server on its new port')
        now[0] += 5
        self.assertFalse(desk.asked()())
        self.assertEqual(len(repairs), 1, 'looked at again only a minute later')
        self.assertEqual(desk.failed, 1)
        now[0] += trailers.PORT_CHECK_S
        self.assertFalse(desk.asked()())
        self.assertEqual(len(repairs), 2)
        self.assertEqual(desk.failed, 2)

    def test_both_ways_in_are_wired(self):
        startup = (ROOT / 'plugin.program.kodipovilwizard/startup.py').read_text(encoding='utf-8')
        self.assertIn("_start_watch('POVILYouTubePort', _youtube_port)", startup)
        source = (LIBS / 'trailers.py').read_text(encoding='utf-8')
        self.assertIn('youtube_port.run(log)', source)
        self.assertIn('repair=repair)', source)


if __name__ == '__main__':
    unittest.main()
