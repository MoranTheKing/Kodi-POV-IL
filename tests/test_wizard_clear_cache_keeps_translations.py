"""Wizard 0.4.80: Maintenance > Clear Cache (and Total Clean Up) keeps
MoranSubs' finished AI translations.

clear_cache() deletes every add-on folder whose name contains "cache";
MoranSubs keeps its translations in addon_data/service.subtitles.kodipovilai/
cache (QA Kodi: 145 .he.srt files), so a Clear Cache meant translating them
again on Gemini quota. Its other caches (downloaded subtitles, search results)
are cheap to fetch again and are still cleared.
"""
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard'
SOURCE = ROOT / 'resources/libs/clear.py'


class ClearCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = self.tmp.name
        self.addon_data = os.path.join(home, 'userdata', 'addon_data')
        config = types.SimpleNamespace(
            HOME=home, PROFILE=os.path.join(home, 'userdata') + os.sep,
            ADDON_DATA=self.addon_data, LOGFILES=['kodi.log'],
            INCLUDEVIDEO='false', ADDONTITLE='Kodi POV IL', COLOR2='white')
        logging = types.SimpleNamespace(log=lambda *a, **k: None,
                                        log_notify=lambda *a, **k: None)
        common = types.ModuleType('resources.libs.common')
        common.logging = logging
        common.tools = types.SimpleNamespace()
        common.config = types.SimpleNamespace(CONFIG=config)
        patcher = mock.patch.dict(sys.modules, {
            'xbmc': types.SimpleNamespace(LOGINFO=1, LOGWARNING=2, LOGERROR=4),
            'xbmcgui': types.SimpleNamespace(),
            'resources': types.ModuleType('resources'),
            'resources.libs': types.ModuleType('resources.libs'),
            'resources.libs.common': common,
            'resources.libs.common.config': common.config,
            'resources.libs.common.logging': logging,
            'resources.libs.common.tools': common.tools,
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location('clear_cache_t', SOURCE)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def put(self, *parts):
        path = os.path.join(self.addon_data, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write('x')
        return path

    def test_ai_translations_stay_and_other_caches_go(self):
        kept = self.put('service.subtitles.kodipovilai', 'cache', 'Movie.he.srt')
        gone = [self.put('service.subtitles.kodipovilai', 'Cached_subs_v2', 'a.srt'),
                self.put('service.subtitles.kodipovilai', 'Cached_subs', 'd.srt'),
                self.put('service.subtitles.kodipovilai', 'cache_f', 'sources.db'),
                self.put('service.subtitles.kodipovilai', 'engine_cache', 'b.json'),
                self.put('plugin.video.pov', 'cache', 'c.db')]
        self.mod.clear_cache(over=True)
        self.assertTrue(os.path.exists(kept))
        for path in gone:
            self.assertFalse(os.path.exists(path), path)

    def test_the_menu_size_leaves_the_translations_out(self):
        # QA Kodi: "Clear Cache: 8.57 MB" right after a clear -- the kept
        # translations, which made the clear look like it did nothing.
        self.put('service.subtitles.kodipovilai', 'cache', 'Movie.he.srt')
        seen = []
        self.mod.CONFIG.INCLUDEVIDEO = 'false'
        sys.modules['resources.libs.common'].tools.get_size = (
            lambda path, total=0: seen.append(path) or total + 1)
        self.assertEqual(0, self.mod.get_cache_size())
        self.assertFalse(any('kodipovilai' in p for p in seen), seen)


if __name__ == '__main__':
    unittest.main()
