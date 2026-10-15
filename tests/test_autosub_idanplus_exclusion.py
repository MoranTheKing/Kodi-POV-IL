"""Idan Plus live channels and VOD never get the automatic subtitle search.

Idan Plus resolves every item to a plain https:// stream, so the playing file
is not a plugin:// path, and Container.PluginName is empty when playback
starts from a home widget, a favourite or JSON-RPC. Kan then got the search
overlay and an AI-translation toast. The item's own path still names the
plugin; the exclusion must read it.
"""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'service.subtitles.kodipovilai/resources/lib/autosub_service.py'
STREAM = 'https://r.il.cdn-redge.media/hls/oil/kancdn/vod/1/playlist.m3u8'


def _run(labels, excluded='plugin.video.idanplus'):
    searched = []

    class Player:
        def getPlayingFile(self):
            return STREAM

        def isPlayingVideo(self):
            return True

        def getTotalTime(self):
            return 2580.0

        def getAvailableSubtitleStreams(self):
            return []

    xbmc = types.ModuleType('xbmc')
    xbmc.Player = Player
    xbmc.sleep = lambda ms: None
    xbmc.getInfoLabel = lambda name: labels.get(name, '')
    xbmcgui = types.ModuleType('xbmcgui')
    xbmcgui.Window = lambda ident: types.SimpleNamespace(
        getProperty=lambda name: '')

    kodi = types.ModuleType('resources.lib.kodi_utils')
    kodi.get_bool = lambda name, default=False: True
    kodi.hebrew_subtitle_wanted = lambda: True
    kodi.get_setting = lambda name, default='': (
        excluded if name == 'autosub_excluded_addons' else default)
    kodi.current_video_info = lambda: {'filepath': STREAM, 'title': 'x'}
    kodi.get_subtitle_selection_token = lambda: '0'
    kodi.log = lambda *args, **kwargs: None

    translate = types.ModuleType('resources.lib.translate')

    def candidates(info, modal_progress=False):
        searched.append(info)
        return []

    translate.list_candidates = candidates
    translate.set_quiet = lambda quiet: None
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
    subsync.diverse_human_alternatives = lambda rows, **_kw: []
    lib = types.ModuleType('resources.lib')
    lib.kodi_utils, lib.translate = kodi, translate
    lib.subs_engine_bridge, lib.subsync = bridge, subsync
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
        spec = importlib.util.spec_from_file_location('autosub_idan', MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.autosub_on_play()
    return module.STATE['run_id'], searched


class IdanPlusExclusionTests(unittest.TestCase):
    def test_idan_plus_from_a_widget_gets_no_search(self):
        for path in ('plugin://plugin.video.idanplus/?mode=10&module=kan&url=11',
                     'plugin://plugin.video.idanplus/?mode=3&module=kan&url=x'):
            run_id, searched = _run({'Player.Filenameandpath': path})
            self.assertEqual((run_id, searched), (0, []), path)

    def test_idan_plus_folder_path_alone_is_enough(self):
        run_id, searched = _run(
            {'Player.FolderPath': 'plugin://plugin.video.idanplus/'})
        self.assertEqual((run_id, searched), (0, []))

    def test_other_plugins_still_get_the_search(self):
        run_id, _searched = _run(
            {'Player.Filenameandpath': 'plugin://plugin.video.pov/?mode=play'})
        self.assertEqual(run_id, 1)

    def test_an_empty_exclusion_list_is_respected(self):
        run_id, _searched = _run(
            {'Player.Filenameandpath': 'plugin://plugin.video.idanplus/?m=3'},
            excluded='')
        self.assertEqual(run_id, 1)


if __name__ == '__main__':
    unittest.main()
