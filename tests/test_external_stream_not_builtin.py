"""A subtitle file Kodi loaded beside the video is not a built-in track (a
viewer's log, 17 Nov 2026: POV's own Hebrew file, 'POVSubs_tt22084616_he
(חיצוני)', was in the play-start snapshot; the Hebrew word of Kodi's
"(External)" mark made it built-in Hebrew, so the release was reported to the
pool as carrying a Hebrew track)."""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ADDON = str(ROOT / 'service.subtitles.kodipovilai')


def load():
    stubs = {n: types.ModuleType(n) for n in ('xbmc', 'xbmcaddon', 'xbmcvfs', 'xbmcgui', 'xbmcplugin')}
    sys.path.insert(0, ADDON)
    try:
        with patch.dict(sys.modules, stubs):
            for name in [m for m in sys.modules if m == 'resources' or m.startswith('resources.')]:
                sys.modules.pop(name)
            from resources.lib import subs_engine_bridge, pool
            mods = {m: sys.modules[m] for m in sys.modules
                    if m == 'resources' or m.startswith('resources.')}
            mods.update(stubs)
            return subs_engine_bridge, pool, mods
    finally:
        sys.path.remove(ADDON)


class ExternalStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b, cls.pool, cls.mods = load()

    def test_kodis_external_mark_in_hebrew_and_english(self):
        f = self.b.is_external_stream
        self.assertTrue(f('POVSubs_tt22084616_he (חיצוני)'))
        self.assertTrue(f('Film.2026.en (External)'))
        for name in ('heb', 'eng', 'עברית', 'Hebrew (Forced)', 'Hebrew', ''):
            self.assertFalse(f(name), name)

    def run_snapshot(self, streams):
        reported = []
        player = types.SimpleNamespace(isPlayingVideo=lambda: True)
        xbmc = self.mods['xbmc']
        xbmc.Player = lambda: player
        xbmc.log = lambda *a, **k: None
        for level in ('LOGDEBUG', 'LOGINFO', 'LOGWARNING', 'LOGERROR'):
            setattr(xbmc, level, 0)
        with patch.dict(sys.modules, self.mods), \
                patch.object(self.b, '_snap_get', lambda: {}), \
                patch.object(self.b, '_snap_set', lambda *a, **k: None), \
                patch.object(self.pool, 'report_embedded', lambda info: reported.append(info)), \
                patch.object(self.pool, '_release_from', lambda info: 'Film.2026.1080p.WEB-DL'):
            self.b.note_playback_streams({'tmdb_id': '1', 'title': 'Film', 'filepath': 'film.mkv'},
                                         streams=streams, final=True)
        return reported

    def test_an_external_hebrew_file_is_not_reported_as_built_in(self):
        self.assertEqual(self.run_snapshot(['POVSubs_tt22084616_he (חיצוני)']), [])

    def test_a_built_in_hebrew_track_still_is(self):
        self.assertEqual(len(self.run_snapshot(['eng', 'heb'])), 1)
        self.assertEqual(len(self.run_snapshot(['POVSubs_tt22084616_he (חיצוני)', 'heb'])), 1)

    def test_no_embedded_row_for_an_external_file_and_the_indexes_stay(self):
        snap = {'streams': ['eng', 'POVSubs_tt22084616_he (חיצוני)', 'fre']}
        with patch.object(self.b, 'enabled', lambda: True), \
                patch.object(self.b, '_snap_get', lambda: snap), \
                patch.object(self.b, '_snapshot_matches', lambda *a, **k: True):
            rows = self.b.embedded_candidates({'tmdb_id': '1'})
        import json
        import urllib.parse
        picks = [json.loads(urllib.parse.unquote(r['link'])) for r in rows]
        self.assertEqual([(p['stream_index'], p['lang']) for p in picks], [(0, 'en'), (2, 'fr')])


if __name__ == '__main__':
    unittest.main()
