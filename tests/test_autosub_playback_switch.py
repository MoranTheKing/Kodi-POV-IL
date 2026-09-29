"""A slow translation for one film must not suppress the next film's autosub."""

import importlib.util
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'service.subtitles.kodipovilai/resources/lib/autosub_service.py'
KODI_UTILS = ROOT / 'service.subtitles.kodipovilai/resources/lib/kodi_utils.py'


class PlaybackSwitchTests(unittest.TestCase):
    def test_verified_same_row_can_take_fresh_selection_ownership(self):
        spec = importlib.util.spec_from_file_location('kodi_utils_renew_test', KODI_UTILS)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        props = {}

        class Window:
            def getProperty(self, name):
                return props.get(name, '')

            def setProperty(self, name, value):
                props[name] = value

            def clearProperty(self, name):
                props.pop(name, None)

        module.KODI_AVAILABLE = True
        module._home_window = Window
        module.set_current_subtitle('same-candidate')
        first = module.get_subtitle_selection_token()
        self.assertTrue(first)
        module.set_current_subtitle('same-candidate')
        self.assertEqual(module.get_subtitle_selection_token(), first)
        module.set_current_subtitle('same-candidate', renew=True)
        self.assertNotEqual(module.get_subtitle_selection_token(), first)

    def test_new_film_runs_while_previous_translation_is_waiting(self):
        current = {'file': 'film-a.mkv', 'link': '', 'token': 0}
        first_resolve_started = threading.Event()
        release_first = threading.Event()
        second_resolve_started = threading.Event()
        release_second = threading.Event()
        applied = []
        second_resolve_kwargs = []

        class Player:
            def getPlayingFile(self):
                return current['file']

            def isPlayingVideo(self):
                return True

            def getTotalTime(self):
                return 90.0

            def getAvailableSubtitleStreams(self):
                return ['fre']

        xbmc = types.ModuleType('xbmc')
        xbmc.Player = Player
        xbmc.sleep = lambda ms: time.sleep(0.001)
        xbmc.getInfoLabel = lambda name: ''
        xbmcgui = types.ModuleType('xbmcgui')
        xbmcgui.Window = lambda ident: types.SimpleNamespace(getProperty=lambda name: '')

        kodi = types.ModuleType('resources.lib.kodi_utils')
        kodi.get_bool = lambda name, default=False: True
        kodi.hebrew_subtitle_wanted = lambda: True
        kodi.get_setting = lambda name, default='': default
        kodi.current_video_info = lambda: {
            'filepath': current['file'], 'imdb_id': current['file'],
            'title': current['file']}
        kodi.get_subtitle_selection_token = lambda: str(current['token'])

        def set_current(link):
            current['link'] = link
            current['token'] += 1

        kodi.set_current_subtitle = set_current
        kodi.current_subtitle_selection = lambda expected_link=None: {
            'token': str(current['token']), 'link_hash': current['link'],
            'stream_hash': current['file']}
        kodi.subtitle_selection_matches = lambda token, link_hash, stream_hash: (
            token == str(current['token']) and link_hash == current['link']
            and stream_hash == current['file'])
        kodi.apply_subtitle_file = lambda path, selection=None: applied.append(
            (current['file'], path)) or True
        kodi.log = lambda *args, **kwargs: None

        translate = types.ModuleType('resources.lib.translate')
        def candidates(info, modal_progress=False):
            rows = [{'language': 'he', 'link': info['filepath'],
                     'filename': info['filepath']}]
            if info['filepath'] == 'film-b.mkv':
                rows += [
                    {'language': 'he', 'link': 'human-b', 'filename': 'human-b'},
                    {'language': 'he', 'link': 'pool-b', 'filename': 'pool-b'},
                ]
            return rows

        translate.list_candidates = candidates
        translate._decode_link = lambda link: {'type': 'pool', 'source': link}
        translate.set_quiet = lambda quiet: None

        def resolve(link, info, selection=None, **kwargs):
            if link == 'film-a.mkv':
                first_resolve_started.set()
                self.assertTrue(release_first.wait(3))
            if link == 'film-b.mkv':
                second_resolve_kwargs.append(kwargs)
                second_resolve_started.set()
                self.assertTrue(release_second.wait(3))
            return link + '.srt'

        translate.resolve = resolve
        bridge = types.ModuleType('resources.lib.subs_engine_bridge')
        bridge.ensure_engine_settings = lambda: None
        bridge._release_ready = lambda info: True
        bridge.note_playback_streams = lambda *args, **kwargs: None
        general = types.ModuleType('resources.lib.subs_engine.general')
        general.show_results = lambda *args: None
        general.show_msg = ''
        subsync = types.ModuleType('resources.lib.subsync')
        subsync.prefetch_autosub_reference = lambda info, rows: False
        subsync.rank_ready_candidates = lambda info, rows: rows
        subsync.diverse_human_alternatives = lambda rows: [
            row['link'] for row in rows if row['link'] == 'human-b']
        lib = types.ModuleType('resources.lib')
        lib.kodi_utils = kodi
        lib.translate = translate
        lib.subs_engine_bridge = bridge
        lib.subsync = subsync
        resources = types.ModuleType('resources')
        resources.lib = lib
        engine = types.ModuleType('resources.lib.subs_engine')
        engine.general = general

        modules = {
            'xbmc': xbmc, 'xbmcgui': xbmcgui, 'resources': resources,
            'resources.lib': lib, 'resources.lib.kodi_utils': kodi,
            'resources.lib.translate': translate,
            'resources.lib.subs_engine_bridge': bridge,
            'resources.lib.subs_engine': engine,
            'resources.lib.subs_engine.general': general,
            'resources.lib.subsync': subsync,
        }
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location('autosub_switch_test', MODULE)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            old = threading.Thread(target=module.autosub_on_play)
            old.start()
            self.assertTrue(first_resolve_started.wait(3))
            current['file'] = 'film-b.mkv'
            new = threading.Thread(target=module.autosub_on_play)
            try:
                new.start()
                self.assertTrue(second_resolve_started.wait(3))
                release_first.set()
                old.join(3)
                self.assertFalse(old.is_alive())
                self.assertTrue(module.STATE['busy'])
                self.assertNotEqual(general.show_msg, 'END')
            finally:
                release_first.set()
                release_second.set()
                old.join(3)
                new.join(3)
            self.assertFalse(new.is_alive())
            self.assertEqual(applied, [('film-b.mkv', 'film-b.mkv.srt')])
            self.assertEqual(second_resolve_kwargs, [{
                'fallback_links': ['human-b']}])
            self.assertFalse(module.STATE['busy'])


if __name__ == '__main__':
    unittest.main()
