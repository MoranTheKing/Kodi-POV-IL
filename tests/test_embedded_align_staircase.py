"""The embedded-align path takes an external subtitle made for another cut
(MoranSubs 0.3.79).

The path re-times an external source subtitle onto the embedded track's cue
times in a few requests, instead of extracting the embedded text in hundreds.
It accepted one shift for the whole file, so a subtitle whose gap grows after
every ad break was refused and the extraction ran. SubSync proves such maps
since 0.3.76; the align path now asks it before giving up on a language."""
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import test_subsync_text_lanes as lanes  # noqa: E402  (the synthetic episode and the loaded SubSync)


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
            sys.path.insert(0, str(ROOT / 'service.subtitles.kodipovilai'))
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


sub, sa = lanes.sub, lanes.sa
EP = lanes.EP
WEB = lanes.WEB
OTHER_CUT = lanes.CLASSIC


def ref_of(ep):
    return [{'start': c['start'], 'end': c['end']} for c in lanes.english_cues(ep)]


class Staircase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.t = load_translate()

    def run_it(self, rejected, playing=WEB, bundle=None, cached=True, abort=lambda: False, ref=None):
        lib = types.ModuleType('resources.lib')
        lib.subsync, lib.sync_align = sub, sa
        resources = types.ModuleType('resources')
        resources.lib = lib
        bundle = EP.bundle() if bundle is None else bundle
        self.probed = []

        def probe(info, playing_name):
            self.probed.append(playing_name)
            return bundle
        self.logged = []
        with patch.dict(sys.modules, {'resources': resources, 'resources.lib': lib,
                                      'resources.lib.subsync': sub, 'resources.lib.sync_align': sa}), \
                patch.object(sub, '_cached_reference_bundle', lambda info: bundle if cached else {}, create=True), \
                patch.object(sub, '_probe_reference_bundle', probe, create=True), \
                patch.object(self.t.kodi_utils, 'log', lambda m, **k: self.logged.append(m), create=True):
            return self.t._embedded_staircase_source({}, playing, ref or ref_of(EP), rejected, abort)

    def test_a_subtitle_made_for_another_cut_is_retimed_onto_the_embedded_track(self):
        text = EP.candidate(OTHER_CUT)
        self.assertNotEqual(sa.verify_cues(ref_of(EP), text).get('status'), sa.STATUS_CONFIRMED)
        aligned, release = self.run_it([('Show.S01E01.720p.WEB-DL-OTHER', text)])
        self.assertEqual(release, 'Show.S01E01.720p.WEB-DL-OTHER')
        self.assertEqual(sa.verify_cues(ref_of(EP), aligned).get('status'), sa.STATUS_CONFIRMED)
        self.assertLess(EP.error_ms(aligned), 350)
        self.assertEqual(aligned.count('-->'), text.count('-->'))
        self.assertTrue(any('made for another cut' in m for m in self.logged), self.logged)
        self.assertEqual(self.probed, [])               # the cached file profile was enough

    def test_the_file_must_pass_subsyncs_own_gates(self):
        text = EP.candidate(OTHER_CUT)
        rejected = [('Show.S01E01.720p.WEB-DL-OTHER', text)]
        # not named as a streaming rip
        self.assertEqual(self.run_it(rejected, playing='Show.S01E01.1080p.BluRay.x264-GRP'), (None, None))
        # one subtitle language in the file: nothing to prove the map with
        self.assertEqual(self.run_it(rejected, bundle=EP.bundle(languages=(), sdh=False)), (None, None))
        # no track timelines at all
        self.assertEqual(self.run_it(rejected, bundle={'track_cues': []}), (None, None))

    def test_another_titles_subtitle_gets_no_map(self):
        other = lanes.Episode(seed=4242).candidate(OTHER_CUT)
        self.assertEqual(self.run_it([('Other.Show.S02E03.WEB-DL', other)]), (None, None))

    def test_it_tries_the_first_three_refused_subtitles_in_order(self):
        good = EP.candidate(OTHER_CUT)
        bad = lanes.Episode(seed=4242).candidate(OTHER_CUT)
        self.assertEqual(self.t._STAIRCASE_TRIES, 3)
        aligned, release = self.run_it([('bad-1', bad), ('bad-2', bad), ('good', good)])
        self.assertEqual(release, 'good')
        self.assertEqual(self.run_it([('bad-1', bad), ('bad-2', bad), ('bad-3', bad), ('good', good)]),
                         (None, None))

    def test_nothing_refused_or_a_stop_is_no_work(self):
        self.assertEqual(self.run_it([]), (None, None))
        self.assertEqual(self.run_it([('x', EP.candidate(OTHER_CUT))], abort=lambda: True), (None, None))

    def test_without_a_cached_file_profile_it_does_nothing_and_reads_nothing(self):
        text = EP.candidate(OTHER_CUT)
        self.assertEqual(self.run_it([('x', text)], cached=False), (None, None))
        self.assertEqual(self.probed, [])

    def test_a_map_that_does_not_end_confirmed_against_the_embedded_track_is_not_taken(self):
        text = EP.candidate(OTHER_CUT)
        # a reference that is not this file's English track
        wrong_ref = [{'start': c['start'], 'end': c['end']} for c in lanes.english_cues(lanes.Episode(seed=77))]
        self.assertEqual(self.run_it([('x', text)], ref=wrong_ref), (None, None))


class Wiring(unittest.TestCase):

    def test_the_align_loop_keeps_what_it_refused_and_asks_before_the_next_language(self):
        text = (ROOT / 'service.subtitles.kodipovilai/resources/lib/translate.py').read_text('utf-8').replace('\r\n', '\n')
        self.assertIn("                    _refused.append((c.get('release') or '', src_text))\n", text)
        loop = text[text.index('            _refused = []\n'):text.index("'deferring to full extract'")]
        self.assertIn('            aligned, _rel = (None, None) if _yielded else (\n'
                      '                _embedded_staircase_source(info, playing, ref, _refused, _abort))\n', loop)

    def test_a_language_that_used_up_its_search_time_gets_no_staircase_run(self):
        text = (ROOT / 'service.subtitles.kodipovilai/resources/lib/translate.py').read_text('utf-8').replace('\r\n', '\n')
        loop = text[text.index('            _refused = []\n'):text.index("'deferring to full extract'")]
        self.assertIn("                    _yielded = True\n                    break\n", loop)
        self.assertLess(loop.index('_yielded = False'), loop.index('for c in cands:'))


if __name__ == '__main__':
    unittest.main()
