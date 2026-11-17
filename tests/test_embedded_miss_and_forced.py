"""An embedded pick that gives nothing is reported to the automatic subtitle,
and a forced file is no stand-in for an unreadable embedded track (QA Kodi,
17 Nov 2026: Inception BDRip 2xUKR ENG SUB -- the 12-line Ukrainian
"Forced" file was translated as the film's subtitle)."""

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
            from resources.lib import translate, subsync
            mods = {m: sys.modules[m] for m in sys.modules
                    if m == 'resources' or m.startswith('resources.')}
            mods.update(stubs)
            return translate, subsync, mods
    finally:
        sys.path.remove(ADDON)


def row(language, release, n):
    return {'language': language, 'release': release, 'payload': {'type': 'engine', 'id': n}}


class EmbeddedMissTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t, cls.subsync, cls.mods = load()

    def test_a_miss_is_reported_once_it_happened_and_only_after_the_run_began(self):
        t = self.t
        t._EMBEDDED_MISS.clear()
        self.assertIsNone(t.embedded_miss_since(0))
        with patch.object(t.time, 'time', lambda: 1000.0):
            t._note_embedded_miss('no_index')
        self.assertEqual(t.embedded_miss_since(999.0), 'no_index')
        self.assertIsNone(t.embedded_miss_since(1001.0))     # an earlier run's
        with patch.object(t.time, 'time', lambda: 2000.0):
            t._note_embedded_miss(None)
        self.assertEqual(t.embedded_miss_since(1500.0), '')

    def pick(self, rows, lang='uk', playing='Inception.2010.BDRip.2xUKR.ENG.SUB', info=None):
        with patch.dict(sys.modules, self.mods), \
                patch.object(self.subsync, '_oracle_candidates', lambda info: rows), \
                patch.object(self.subsync, 'playing_release', lambda info: playing):
            return self.t._external_for_unreadable_embedded(info or {}, lang)

    def test_a_forced_file_is_never_the_stand_in(self):
        rows = [row('uk', 'Inception (2010) BDRip. Forced', 1),
                row('uk', 'Inception.2010.BDRip.UKR', 2),
                row('en', 'Inception.2010.BDRip.ENG', 3)]
        self.assertEqual(self.pick(rows)['id'], 2)
        # the picked language has only a forced file: English, not the forced one
        self.assertEqual(self.pick([rows[0], rows[2]])['id'], 3)
        self.assertIsNone(self.pick([rows[0]]))
        for name in ('Film.FORCED.srt', 'Film forcés', 'Film.forzados', 'Фільм форсовані'):
            self.assertIsNone(self.pick([row('uk', name, 9)]), name)

    def test_a_title_with_force_in_it_is_not_forced(self):
        # review of 0.3.91: 'forc[ée]s?' matched "Force" and "Forces"
        for name in ('Star.Wars.The.Force.Awakens.2015.UKR', 'Air.Force.One.1997.UKR',
                     'Space.Force.S01E01.UKR', 'Armed.Forces.2020.UKR', 'Reinforced.2020.UKR'):
            self.assertEqual(self.pick([row('uk', name, 5)], playing=name)['id'], 5, name)

    def test_a_film_called_forced_keeps_its_subtitles(self):
        rows = [row('en', 'Forced.Entry.2023.1080p.WEB.ENG', 7)]
        out = self.pick(rows, lang='en', playing='Forced.Entry.2023.1080p.WEB-DL',
                        info={'title': 'Forced Entry'})
        self.assertEqual(out['id'], 7)
        # ... and a forced file of it is still left out when the word is the file's own mark
        self.assertIsNone(self.pick([row('en', 'Inception.2010.Forced', 8)], lang='en',
                                    playing='Inception.2010.1080p'))

    def test_busy_is_not_a_miss_and_a_miss_belongs_to_its_file(self):
        t = self.t
        t._EMBEDDED_MISS.clear()
        t._note_embedded_miss('busy')
        self.assertIsNone(t.embedded_miss_since(0))
        xbmc = types.ModuleType('xbmc')
        xbmc.Player = lambda: types.SimpleNamespace(getPlayingFile=lambda: 'old-film.mkv')
        with patch.dict(sys.modules, {'xbmc': xbmc}):
            t._note_embedded_miss('no_index')
        self.assertEqual(t.embedded_miss_since(0, 'old-film.mkv'), 'no_index')
        self.assertIsNone(t.embedded_miss_since(0, 'next-film.mkv'))   # another run's file
        self.assertEqual(t.embedded_miss_since(0), 'no_index')          # a side that does not know

    def test_a_name_with_no_forced_mark_is_as_before(self):
        rows = [row('uk', 'Inception.2010.BDRip.UKR', 2), row('en', 'Inception.2010.WEB.ENG', 3)]
        out = self.pick(rows)
        self.assertEqual((out['id'], out['type'], out['src_lang']), (2, 'engine_ai', 'uk'))


if __name__ == '__main__':
    unittest.main()
