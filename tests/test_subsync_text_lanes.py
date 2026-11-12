"""SubSync on a file whose subtitles are all text (a streaming WEB-DL).

Field report (The 100 S01E01, AMZN WEB-DL, 28 embedded text tracks): the
Hebrew subtitle named for a WEB-DL belonged to another cut and ran +1.0 s in
the first act and +16.3 s in the last.  The file's own English track showed
the six-region map and 26 of its 27 other tracks agreed, yet the subtitle
stayed "unverified": region maps were only ever proven with a disc's PGS
tracks, the English track was tagged 'en-US' and not read as English, and act
steps under a second were merged into drifting plateaus.
"""

import importlib.util
import random
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

LIB = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai' / 'resources' / 'lib'


def _load_subsync():
    ku = types.ModuleType('resources.lib.kodi_utils')
    ku.log = lambda *a, **k: None
    ku.get_setting = lambda _k, default='': default
    lib = types.ModuleType('resources.lib')
    lib.__path__ = [str(LIB)]          # the real sync_align / release_match
    lib.kodi_utils = ku
    pkg = types.ModuleType('resources')
    pkg.__path__ = []
    pkg.lib = lib
    with patch.dict(sys.modules, {'resources': pkg, 'resources.lib': lib,
                                  'resources.lib.kodi_utils': ku}):
        spec = importlib.util.spec_from_file_location('text_lane_subsync', LIB / 'subsync.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # The language table is loaded on first use (in Kodi the media probe
        # has loaded its module by then): use it once while the package is
        # importable here.
        mod._track_base_language({'lang': 'en'})
    return mod


sub = _load_subsync()
sa = sub.sync_align


def speech(seed, minutes=44):
    """Episode-like dialogue: a line every 3-4 s, a long pause now and then."""
    rng = random.Random(seed)
    t, out = rng.uniform(20000, 60000), []
    while t < minutes * 60000:
        dur = rng.uniform(900, 4200)
        out.append((t, t + dur))
        r = rng.random()
        t += dur + (rng.uniform(80, 700) if r < 0.60 else
                    rng.uniform(700, 3000) if r < 0.95 else
                    rng.uniform(5000, 14000))
    return out


def author(seed, lines, merge, split, jit_on, jit_off, drop, extra=0.0):
    """One subber's cues for the same speech: merges, splits, drops, jitter."""
    rng = random.Random(seed)
    cues, i = [], 0
    while i < len(lines):
        s, e = lines[i]
        while (i + 1 < len(lines) and lines[i + 1][0] - e < 600
               and lines[i + 1][1] - s < 6500 and rng.random() < merge):
            i += 1
            e = lines[i][1]
        parts = [(s, e)]
        if e - s > 3500 and rng.random() < split:
            cut = s + (e - s) * rng.uniform(0.35, 0.65)
            parts = [(s, cut), (cut + 40, e)]
        for ps, pe in parts:
            if rng.random() < drop:
                continue
            ns = ps + rng.gauss(0, jit_on)
            cues.append([ns, max(ns + 500, pe + rng.gauss(0, jit_off) + rng.uniform(0, 400))])
        i += 1
    if extra:
        more = []
        for a, b in zip(cues, cues[1:]):
            if b[0] - a[1] > 2500 and rng.random() < extra:
                m = a[1] + rng.uniform(300, b[0] - a[1] - 1500)
                more.append([m, m + rng.uniform(900, 1800)])
        cues.extend(more)
    cues.sort()
    for a, b in zip(cues, cues[1:]):
        if a[1] > b[0] - 40:
            a[1] = max(a[0] + 300, b[0] - 40)
    return cues


def act_breaks(lines, fractions):
    span = lines[-1][1] - lines[0][0]
    gaps = [((a[1] + b[0]) / 2.0) for a, b in zip(lines, lines[1:]) if b[0] - a[1] >= 5000]
    out = []
    for fraction in fractions:
        target = lines[0][0] + span * fraction
        out.append(min((g for g in gaps if g not in out), key=lambda g: abs(g - target)))
    return sorted(out)


def stepped(cues, breaks, offsets):
    out = []
    for s, e in cues:
        k = sum(s >= b for b in breaks)
        out.append([s + offsets[k], e + offsets[k]])
    return out


def srt(cues, scale=1.0):
    return '\n'.join('%d\n%s --> %s\nline\n' % (n, sa._ms_to_stamp(s * scale), sa._ms_to_stamp(e * scale))
                     for n, (s, e) in enumerate(cues, 1))


def index(cues, shift=0):
    """A text track as the remote reader hands it over: start times only."""
    return sub._starts_to_cues([int(s + shift) for s, _e in cues])


def track(num, lang, cues, sdh=False, codec='S_TEXT/UTF8', shift=0):
    return {'track': {'num': num, 'codec': codec, 'lang': lang, 'forced': False,
                      'name': 'SDH' if sdh else '', 'hearing_impaired': sdh},
            'cues': index(cues, shift)}


FRACTIONS = (0.26, 0.45, 0.53, 0.72, 0.86)
CLASSIC = [-200, 1700, 3600, 5700, 7700, 9650]       # ~2 s at every act break
FINE = [-460, 350, 900, 1450, 1950, 2500]            # about half a second each
ZIGZAG = [0, 2000, 2850, 900, 1800, 2700]            # one act shorter in the other cut
LANGS = {                                             # merge, split, jitter, drop
    'fre': (0.45, 0.10, 150, 250, 0.08),
    'ger': (0.10, 0.30, 150, 250, 0.02),
    'spa': (0.35, 0.20, 170, 260, 0.05),
    'dut': (0.55, 0.05, 150, 250, 0.15),
}


class Episode:
    def __init__(self, seed=911):
        self.lines = speech(seed)
        self.breaks = act_breaks(self.lines, FRACTIONS)
        self.english = author(seed + 1, self.lines, 0.2, 0.15, 160, 260, 0.03, extra=0.15)
        self.hebrew = author(seed + 2, self.lines, 0.3, 0.25, 200, 300, 0.05)
        self.other = {lang: author(seed + 10 + n, self.lines, *p)
                      for n, (lang, p) in enumerate(sorted(LANGS.items()))}

    def candidate(self, offsets):
        return srt(stepped(self.hebrew, self.breaks, offsets))

    def bundle(self, languages=('fre', 'ger', 'spa', 'dut'), english='en-US', sdh=True):
        tracks = [track(3, english, self.english)]
        if sdh:
            tracks.append(track(4, english, self.english + [[5000, 6000]], sdh=True))
        for n, lang in enumerate(languages):
            tracks.append(track(5 + n, lang, self.other[lang]))
        return {'track_cues': tracks}

    def error_ms(self, fixed_text):
        """Largest distance of a re-timed line from where its speech is."""
        fixed = [c['start'] for c in sa.parse_srt(fixed_text)]
        return max(abs(a - b[0]) for a, b in zip(fixed, self.hebrew))

    def share_off(self, fixed_text, limit=300):
        """Share of re-timed lines further than ``limit`` from their speech."""
        fixed = [c['start'] for c in sa.parse_srt(fixed_text)]
        return sum(1 for a, b in zip(fixed, self.hebrew) if abs(a - b[0]) > limit) / float(len(fixed))


EP = Episode()


def english_cues(ep):
    return sa.parse_srt(srt(ep.english))


def validated(offsets, ep=None, **modes):
    ep = ep or EP
    return sa.validate_micro_piecewise(english_cues(ep), ep.candidate(offsets), **modes)


class FinePlannerTests(unittest.TestCase):
    def test_sub_second_act_steps_are_recovered_when_asked_for(self):
        v = validated(FINE, fine=True)
        self.assertIsNotNone(v)
        self.assertEqual(v.get('planner'), 'region-fine')
        self.assertGreaterEqual(v['validation_folds'], 4)
        got = [s['offset_ms'] for s in v['segments']]
        self.assertEqual(len(got), len(FINE))
        for a, b in zip(got, FINE):
            self.assertLess(abs(a - b), 200, got)

    def test_no_other_caller_gets_the_fine_or_free_modes(self):
        # The disc and provider proofs call these with no mode, as before.
        for offsets in (FINE, ZIGZAG, [0, 0, 0, 1400, 1400, 1400]):
            self.assertIsNone(validated(offsets))
            self.assertIsNone(sa.micro_piecewise_proposal(english_cues(EP), EP.candidate(offsets)))
        self.assertEqual(sa._planner_names(False, False), ('micro', 'region'))
        self.assertEqual(sa._planner_names(True, False), ('micro', 'region', 'region-fine'))
        self.assertEqual(sa._planner_names(False, True), ('micro', 'region', 'region-fine', 'region-free'))

    def test_steps_of_seconds_still_come_from_a_classic_planner(self):
        for modes in ({}, {'fine': True}, {'fine': True, 'free': True}):
            v = validated(CLASSIC, **modes)
            self.assertIsNotNone(v)
            self.assertNotIn(v.get('planner'), ('region-fine', 'region-free'))
            self.assertEqual(len(v['segments']), len(CLASSIC))

    def test_one_act_break_is_enough(self):
        ep = Episode(931)
        v = validated([0, 0, 0, 1400, 1400, 1400], ep, fine=True)
        self.assertIsNotNone(v)
        self.assertEqual(v.get('planner'), 'region-fine')
        self.assertEqual(len(v['segments']), 2)
        self.assertLess(abs(v['segments'][1]['offset_ms'] - v['segments'][0]['offset_ms'] - 1400), 200)

    def test_fine_mode_keeps_one_direction_and_the_step_ceiling(self):
        self.assertIsNone(validated([-200, 900, 300, 1500, 800, 2100], fine=True))
        self.assertIsNone(validated(ZIGZAG, fine=True))
        self.assertIsNone(validated([0, 6000, 12000, 18000, 24000, 30000], fine=True))

    def test_a_zigzag_is_planned_only_in_free_mode(self):
        v = validated(ZIGZAG, free=True)
        self.assertIsNotNone(v)
        self.assertEqual(v.get('planner'), 'region-free')
        got = [s['offset_ms'] for s in v['segments']]
        self.assertEqual(len(got), len(ZIGZAG))
        for a, b in zip(got, ZIGZAG):
            self.assertLess(abs(a - b), 200, got)

    def test_plateaus_closer_than_300_ms_are_one_plateau(self):
        ep = Episode(931)
        v = validated([0, 0, 0, 1400, 1680, 1680], ep, fine=True)
        self.assertIsNotNone(v)
        self.assertEqual(len(v['segments']), 2)
        with patch.object(sa, '_REGION_FINE_MIN_STEP_MS', 100.0):
            self.assertEqual(len(validated([0, 0, 0, 1400, 1680, 1680], ep, fine=True)['segments']), 3)

    def test_a_spread_under_a_second_is_left_alone(self):
        # Every line 475 ms off, a 950 ms step: a clear map, and not worth it.
        ep = Episode(931)
        narrow = [-475, -475, -475, 475, 475, 475]
        self.assertIsNone(validated(narrow, ep, fine=True))
        with patch.object(sa, '_REGION_FINE_MIN_RANGE_MS', 0.0):
            self.assertIsNotNone(validated(narrow, ep, fine=True))
        self.assertIsNotNone(validated([-600, -600, -600, 600, 600, 600], ep, fine=True))

    def test_a_slow_clock_drift_is_not_a_staircase(self):
        english = english_cues(EP)
        for scale in (1.0004, 1.0006, 1.0008, 1.0010, 1.0012):
            for modes in ({'fine': True}, {'fine': True, 'free': True}):
                self.assertIsNone(sa.validate_micro_piecewise(english, srt(EP.hebrew, scale), **modes), scale)

    def test_one_shift_or_another_title_gives_no_map(self):
        english = english_cues(EP)
        flat = srt([[s + 2600, e + 2600] for s, e in EP.hebrew])
        other = srt(stepped(author(77, speech(5555), 0.5, 0.45, 260, 340, 0.10), EP.breaks, FINE))
        for modes in ({}, {'fine': True}, {'fine': True, 'free': True}):
            self.assertIsNone(sa.validate_micro_piecewise(english, flat, **modes))
            self.assertIsNone(sa.micro_piecewise_proposal(english, other, **modes))

    def test_a_proposal_alone_can_never_be_applied(self):
        for offsets, modes in ((FINE, {'fine': True}), (ZIGZAG, {'free': True})):
            with self.assertRaises(ValueError):
                sa.apply_verdict(EP.candidate(offsets), validated(offsets, **modes))

    def test_offsets_are_whole_milliseconds(self):
        # A median of deltas can end in .5; a cue one millisecond long then
        # has both ends rounded to the same stamp and the rewrite is refused.
        for offsets, modes in ((CLASSIC, {}), (FINE, {'fine': True}), (ZIGZAG, {'free': True})):
            v = validated(offsets, **modes)
            self.assertTrue(all(float(s['offset_ms']).is_integer() for s in v['segments']), offsets)

    def test_fine_folds_must_time_the_lines_alike(self):
        full = validated(FINE, fine=True)
        cand = sa.dialogue_cues(sa.parse_srt(EP.candidate(FINE)))
        self.assertTrue(sa._piecewise_maps_agree_on_lines(full, full, cand))
        moved = dict(full, segments=[dict(s, offset_ms=s['offset_ms'] + (400 if n == 3 else 0))
                                     for n, s in enumerate(full['segments'])])
        self.assertFalse(sa._piecewise_maps_agree_on_lines(full, moved, cand))
        nudged = dict(full, segments=[dict(s, offset_ms=s['offset_ms'] + 150) for s in full['segments']])
        self.assertTrue(sa._piecewise_maps_agree_on_lines(full, nudged, cand))
        with patch.object(sa, '_piecewise_maps_agree_on_lines', return_value=False):
            self.assertIsNone(validated(FINE, fine=True))         # the folds do ask it
            self.assertIsNotNone(validated(CLASSIC, fine=True))   # classic folds do not

    def test_the_pause_decides_a_cut_only_under_a_second(self):
        text = EP.candidate(FINE)
        ref = sa._preflight_cues(index(EP.english))[0]
        cand = sa.dialogue_cues(sa.parse_srt(text))

        def off(plan):
            fixed = sa._map_cues_piecewise(cand, 1.0, plan['segments'])
            return sum(1 for a, b in zip(fixed, EP.hebrew) if abs(a['start'] - b[0]) > 300)
        with_pause = off(sa._region_fine_plan(ref, cand)[0])
        with patch.object(sa, '_REGION_FINE_GAP_WEIGHT', 0.0):
            without = off(sa._region_fine_plan(ref, cand)[0])
        self.assertLess(with_pause, without)                       # half-second steps: it helps
        seconds = sa.dialogue_cues(sa.parse_srt(EP.candidate(CLASSIC)))
        plain = sa._region_fine_plan(ref, seconds)[0]['segments']
        with patch.object(sa, '_REGION_FINE_GAP_WEIGHT', 50.0):
            pushed = sa._region_fine_plan(ref, seconds)[0]['segments']
        self.assertEqual([s['cand_from_ms'] for s in plain], [s['cand_from_ms'] for s in pushed])


def lanes(ep, text, tracks):
    """The text-lane proof itself, away from the checks around it."""
    return sub._validated_text_lane_piecewise(
        tracks, text, sa.micro_piecewise_proposal, sa.validate_micro_piecewise,
        sa.evaluate_piecewise_family)


CUT_A = [0, -1500, -3000, -4500, -6000, -7500]       # a track muxed in from another cut
WEB = 'Show.S01E01.Pilot.1080p.AMZN.WEB-DL.DD.5.1.H.264-GRP'


class TextLaneTests(unittest.TestCase):
    def decide(self, bundle, text, playing=WEB):
        return sub._verify_file_bundle(bundle, text, playing)

    def test_only_a_file_named_as_a_streaming_rip_uses_the_text_lanes(self):
        # Nothing on this path looks at the video: on a disc or broadcast
        # encode the text tracks may be a set taken from a WEB source.
        text = EP.candidate(CLASSIC)
        for playing in ('Show.S01E01.1080p.WEBRip.x265-GRP', 'Show.S01E01.1080p.NF.WEB.H264-GRP', WEB):
            self.assertEqual(self.decide(EP.bundle(), text, playing)[0]['status'], sa.STATUS_FIXABLE, playing)
        self.assertTrue(all(sub._named_streaming_rip(name) for name in (
            'The.100.S01E01.Pilot.1080p.AMZN.WEB-DL.DD.5.1.H.264-playWEB',
            'The.100.S01.1080p.AMZN.WEB-DL.DDP5.1.H.264-GRP', 'Madame.Web.2024.1080p.WEB-DL.H264-GRP',
            'Supernatural.S05E01.MULTi.1080p.AMZN.WEB-DL.H264-LAZARUS.mkv', 'Movie 2019 720p WEBRip x264')))
        for playing in ('Show.S01E01.1080p.BluRay.x264-GRP', 'Show.S01E01.720p.HDTV.x264-GRP',
                        'Show.S01E01.DVDRip.XviD-GRP', 'Show S01E01', '', None,
                        # 'web' as a word of the title is not a source
                        'Web.of.Lies.S01E01.720p.HDTV.x264-GRP', 'Web.Therapy.S01E01.DVDRip.x264-GRP',
                        'The.Dark.Web.S01E01.1080p.x265-GRP', 'Madame.Web.2024.1080p.BluRay.x264-GRP',
                        'Show.WEB-DL', 'Show.S01E01.1080p.BluRay.WEB-DL.Hybrid-GRP'):
            with patch.object(sub, '_validated_text_lane_piecewise', side_effect=AssertionError('text lanes')):
                verdict, _label, _count = self.decide(EP.bundle(), text, playing)
            self.assertNotEqual((verdict or {}).get('status'), sa.STATUS_FIXABLE, playing)

    def test_any_other_kind_of_subtitle_track_keeps_the_text_lanes_out(self):
        text = EP.candidate(CLASSIC)
        forced = EP.english[100:103]                      # three captions: under the reader's minimum
        for extra in (track(9, 'eng', forced, codec='S_HDMV/PGS'),
                      track(9, 'eng', EP.english, codec='S_VOBSUB'),
                      track(9, 'eng', EP.english, codec='S_DVBSUB')):
            bundle = EP.bundle()
            bundle['track_cues'].append(extra)
            with patch.object(sub, '_validated_text_lane_piecewise', side_effect=AssertionError('text lanes')):
                verdict, _label, _count = self.decide(bundle, text)
            self.assertNotEqual((verdict or {}).get('status'), sa.STATUS_FIXABLE, extra['track']['codec'])
        # ... also when only the file's header lists it (nothing read of it).
        bundle = EP.bundle()
        bundle['tracks'] = [p['track'] for p in bundle['track_cues']] + [
            {'num': 9, 'codec': 'S_HDMV/PGS', 'lang': 'eng', 'forced': True}]
        with patch.object(sub, '_validated_text_lane_piecewise', side_effect=AssertionError('text lanes')):
            self.decide(bundle, text)

    def test_one_key_per_language_whatever_the_tag(self):
        key = sub._track_base_language
        self.assertEqual({key({'lang': x}) for x in ('en-US', 'en', 'eng', 'EN-gb', 'en_AU')}, {'en'})
        self.assertEqual({key({'lang': x}) for x in ('fre', 'fra', 'fr', 'fr-CA')}, {'fr'})
        self.assertEqual({key({'lang': x}) for x in ('nor', 'nob', 'nno', 'no')}, {'no'})
        self.assertEqual({key({'lang': x}) for x in ('pt-BR', 'por', 'pob')}, {'pt'})
        rank = sub._track_language_rank
        self.assertEqual([rank({'lang': x}) for x in ('en-US', 'eng', 'he-IL', 'heb', 'iw', 'pt-BR', 'enm', '')],
                         [1, 1, 0, 0, 0, 2, 2, 2])
        self.assertEqual([rank({'lang': x}) for x in ('English', 'hebrew')], [1, 0])     # as before
        self.assertEqual([key({'lang': x}) for x in ('English', 'hebrew')], ['en', 'he'])

    def test_a_streaming_rip_proves_the_map_with_its_other_languages(self):
        text = EP.candidate(CLASSIC)
        verdict, label, count = self.decide(EP.bundle(), text)
        self.assertEqual(verdict['status'], sa.STATUS_FIXABLE, verdict.get('diag'))
        self.assertTrue(label.startswith('FILE TRACK VALIDATED #3 en-US'), label)
        self.assertEqual(count, len(EP.english))
        self.assertEqual(len(verdict['segments']), len(CLASSIC))
        self.assertEqual(verdict.get('validation_proof'), 'native-text-lane-v1')
        self.assertLess(EP.error_ms(sa.apply_verdict(text, verdict)), 350)

    def test_sub_second_steps_are_fixed_too(self):
        text = EP.candidate(FINE)
        verdict, label, _count = self.decide(EP.bundle(), text)
        self.assertEqual(verdict['status'], sa.STATUS_FIXABLE, verdict.get('diag'))
        self.assertEqual(verdict.get('planner'), 'region-fine')
        # Before: every act but the second more than 300 ms off (71% of the
        # lines).  After: at most a line or two beside a cut.
        self.assertGreater(EP.share_off(text), 0.70)
        self.assertLess(EP.share_off(sa.apply_verdict(text, verdict)), 0.01)

    def test_a_zigzag_is_fixed_with_other_languages_to_ask(self):
        text = EP.candidate(ZIGZAG)
        self.assertGreater(EP.share_off(text), 0.70)
        for languages in (('fre', 'ger', 'spa', 'dut'), ('fre',)):
            verdict, label, _count = self.decide(EP.bundle(languages=languages), text)
            self.assertEqual(verdict['status'], sa.STATUS_FIXABLE, verdict.get('diag'))
            self.assertEqual(verdict.get('planner'), 'region-free')
            self.assertLess(EP.share_off(sa.apply_verdict(text, verdict)), 0.02)

    def test_two_languages_cut_differently_are_two_families(self):
        text = EP.candidate(CLASSIC)
        verdict, _label, _count = self.decide(EP.bundle(languages=('fre',), sdh=False), text)
        self.assertEqual(verdict['status'], sa.STATUS_FIXABLE, verdict.get('diag'))
        self.assertEqual(verdict.get('timing_family_count'), 2)
        self.assertNotIn('validation_proof', verdict)
        self.assertLess(EP.error_ms(sa.apply_verdict(text, verdict)), 350)

    def test_one_language_alone_never_rewrites(self):
        # Review: with only its English track, moved onto another cut, a
        # Hebrew that was in sync was re-timed and 78% of its lines ended more
        # than 700 ms off.  One track cannot tell which of the two is off.
        for tracks in ([track(3, 'en-US', EP.english)],
                       [track(3, 'en-US', EP.english), track(4, 'eng', EP.english, sdh=True)],
                       [track(3, 'en-US', EP.english), track(4, 'en', EP.english), track(5, 'und', EP.other['fre'])]):
            for offsets in (CLASSIC, FINE, ZIGZAG):
                text = EP.candidate(offsets)
                with patch.object(sub.sync_align, 'micro_piecewise_proposal',
                                  side_effect=AssertionError('planned')) as spy:
                    self.assertIsNone(lanes(EP, text, tracks))
                verdict, _label, _count = self.decide({'track_cues': tracks}, text)
                self.assertNotEqual((verdict or {}).get('status'), sa.STATUS_FIXABLE)
        del spy
        # The very case: the lone track sits on another cut, the Hebrew is right.
        moved = [track(3, 'en-US', stepped(EP.english, EP.breaks, CUT_A))]
        verdict, _label, _count = self.decide({'track_cues': moved}, srt(EP.hebrew))
        self.assertNotEqual((verdict or {}).get('status'), sa.STATUS_FIXABLE)

    def test_a_twin_under_another_tag_is_not_a_second_language(self):
        # 'en-US' beside its SDH twin tagged 'eng' and one translation laid on
        # the same cues: one language asked, and no family of its own.
        tracks = [track(3, 'en-US', EP.english), track(4, 'eng', EP.english, sdh=True),
                  track(5, 'hin', EP.english)]
        self.assertIsNone(lanes(EP, EP.candidate(CLASSIC), tracks))
        tracks = [track(3, 'en-US', EP.english), track(5, 'fre', EP.english), track(6, 'fr-CA', EP.english)]
        self.assertIsNone(lanes(EP, EP.candidate(CLASSIC), tracks))

    def test_two_copies_in_other_languages_are_native_lanes_with_strong_folds(self):
        tracks = [track(3, 'en-US', EP.english), track(5, 'hin', EP.english), track(6, 'tha', EP.english)]
        text = EP.candidate(CLASSIC)
        out = lanes(EP, text, tracks)
        self.assertEqual(out['verdict'].get('validation_proof'), 'native-text-lane-v1')
        self.assertEqual(out['verdict'].get('native_lane_tracks'), 2)
        self.assertGreaterEqual(out['verdict']['holdout_score_min'], 0.85)
        self.assertLess(EP.error_ms(sa.apply_verdict(text, out['verdict'])), 350)

    def test_copies_cannot_stand_in_for_weak_folds(self):
        # A lane laid on the primary's own cues scores what the primary does;
        # with held-out folds under 0.85 two such lanes prove nothing, and a
        # language cut differently is what it takes.
        ep = Episode(921)
        ep.hebrew = author(923, ep.lines, 0.35, 0.30, 260, 340, 0.12)
        text = ep.candidate(CLASSIC)
        weak = sa.validate_micro_piecewise(english_cues(ep), text, fine=True, free=True)
        self.assertLess(weak['holdout_score_min'], 0.85)
        copies = [track(3, 'en-US', ep.english), track(5, 'hin', ep.english), track(6, 'tha', ep.english)]
        self.assertIsNone(lanes(ep, text, copies))
        out = lanes(ep, text, copies + [track(7, 'fre', ep.other['fre'])])
        self.assertEqual(out['verdict'].get('timing_family_count'), 2)
        self.assertEqual(out['verdict'].get('validation_family_track'), '#7/fre')

    def test_languages_that_do_not_accept_the_map_mean_no_rewrite(self):
        # The English track and the Hebrew differ by one staircase; the
        # file's other languages sit on a third timeline and fit neither.
        third = [900, -700, 1100, -500, 1300, -300]
        tracks = [track(3, 'en-US', EP.english),
                  track(5, 'fre', stepped(EP.other['fre'], EP.breaks, third)),
                  track(6, 'ger', stepped(EP.other['ger'], EP.breaks, third))]
        text = EP.candidate(CLASSIC)
        self.assertIsNotNone(validated(CLASSIC, fine=True, free=True))     # the primary alone would
        self.assertIsNone(lanes(EP, text, tracks))
        verdict, _label, _count = self.decide({'track_cues': tracks}, text)
        self.assertNotEqual((verdict or {}).get('status'), sa.STATUS_FIXABLE)

    def test_one_language_the_subtitle_already_fits_vetoes(self):
        # English, French and German all muxed in from another cut; the
        # Spanish track is the file's own and the Hebrew fits it.
        shifted = [track(3, 'en-US', stepped(EP.english, EP.breaks, CUT_A)),
                   track(5, 'fre', stepped(EP.other['fre'], EP.breaks, CUT_A)),
                   track(6, 'ger', stepped(EP.other['ger'], EP.breaks, CUT_A))]
        text = srt(EP.hebrew)
        self.assertIsNotNone(lanes(EP, text, shifted))                     # nothing to object
        self.assertIsNone(lanes(EP, text, shifted + [track(7, 'spa', EP.other['spa'])]))

    def test_a_twin_the_subtitle_already_fits_vetoes(self):
        # The same, with the file's own timeline only on a track that counts
        # for nothing as agreement: the SDH twin, an untagged track.
        shifted = [track(3, 'en-US', stepped(EP.english, EP.breaks, CUT_A)),
                   track(5, 'fre', stepped(EP.other['fre'], EP.breaks, CUT_A)),
                   track(6, 'ger', stepped(EP.other['ger'], EP.breaks, CUT_A))]
        text = srt(EP.hebrew)
        for twin in (track(4, 'eng', EP.english, sdh=True), track(4, 'und', EP.other['spa'])):
            self.assertIsNone(lanes(EP, text, shifted + [twin]))

    def test_a_subtitle_the_other_languages_already_fit_is_not_moved(self):
        english = stepped(EP.english, EP.breaks, [0, -1700, -3400, -5100, -6800, -8500])
        bundle = {'track_cues': [track(3, 'en-US', english), track(5, 'fre', EP.other['fre']),
                                 track(6, 'ger', EP.other['ger'])]}
        verdict, label, _count = self.decide(bundle, srt(EP.hebrew))
        self.assertEqual(verdict['status'], sa.STATUS_CONFIRMED, verdict.get('diag'))
        self.assertNotIn('#3', label)

    def test_a_lane_must_fit_better_than_before(self):
        text = EP.candidate(CLASSIC)
        v = validated(CLASSIC, fine=True, free=True)
        m = sa.evaluate_piecewise_family(index(EP.other['fre']), text, v)
        gain = m['after_score'] - m['before_score']
        self.assertTrue(sa.evaluate_piecewise_family(index(EP.other['fre']), text, v, min_gain=gain - 0.01)['accepted'])
        self.assertFalse(sa.evaluate_piecewise_family(index(EP.other['fre']), text, v, min_gain=gain + 0.01)['accepted'])
        asked = []
        real = sa.evaluate_piecewise_family

        def judge(cues, text, verdict, **kw):
            asked.append(kw.get('min_gain'))
            return real(cues, text, verdict, **kw)
        sub._validated_text_lane_piecewise(EP.bundle()['track_cues'], text, sa.micro_piecewise_proposal,
                                           sa.validate_micro_piecewise, judge)
        self.assertTrue(asked and all(g == 0.08 for g in asked), asked)
        with patch.object(sub, '_TEXT_LANE_MIN_GAIN', 0.9):                # no lane can gain that much
            self.assertIsNone(lanes(EP, text, EP.bundle()['track_cues']))

    def test_a_map_that_cannot_be_applied_is_no_proof(self):
        text = EP.candidate(CLASSIC)
        with patch.object(sub.sync_align, 'apply_verdict', side_effect=ValueError('refused')):
            self.assertIsNone(lanes(EP, text, EP.bundle()['track_cues']))
        # A second family must gain as a family does, not as a lane.
        fine_text = EP.candidate(FINE)
        two = [track(3, 'en-US', EP.english), track(5, 'fre', EP.other['fre'])]
        self.assertIsNotNone(lanes(EP, fine_text, two))
        with patch.object(sub, '_TEXT_FINE_FAMILY_GAIN', 0.9):
            self.assertIsNone(lanes(EP, fine_text, two))
        # Review: a spoken cue one millisecond long under a staircase.
        cues = stepped(EP.hebrew, EP.breaks, CLASSIC)
        cues[300][1] = cues[300][0] + 1
        verdict, _label, _count = self.decide(EP.bundle(), srt(cues))
        self.assertEqual(verdict['status'], sa.STATUS_FIXABLE, verdict.get('diag'))
        self.assertEqual(len(sa.parse_srt(sa.apply_verdict(srt(cues), verdict))), len(cues))

    def test_a_flat_shift_never_reaches_the_planners(self):
        text = srt([[s + 2600, e + 2600] for s, e in EP.hebrew])
        with patch.object(sub, '_validated_micro_piecewise', side_effect=AssertionError('planners ran')):
            verdict, _label, _count = self.decide(EP.bundle(), text)
        self.assertEqual(verdict['status'], sa.STATUS_FIXABLE, verdict.get('diag'))
        self.assertEqual(verdict.get('mode', 'global'), 'global')
        self.assertLess(abs(verdict['offset_ms'] - 2600), 200)

    def test_a_disc_keeps_its_own_proofs(self):
        # Any PGS track, whole or partial, makes the file a disc.
        half = EP.english[:len(EP.english) // 2]
        for pgs in (track(9, 'eng', EP.english, codec='S_HDMV/PGS'),
                    track(9, 'eng', half, codec='S_HDMV/PGS')):
            bundle = EP.bundle()
            bundle['track_cues'].append(pgs)
            with patch.object(sub, '_validated_text_lane_piecewise', side_effect=AssertionError('text path')):
                sub._verify_file_bundle(bundle, EP.candidate(CLASSIC), WEB)

    def test_stored_verdicts_recompute(self):
        self.assertEqual(sub._VERDICT_VERSION, 30)


class ZeroLengthCueTests(unittest.TestCase):
    """A cue that starts and ends at the same instant is never on screen.
    Field: four of 29 Hebrew files (Arrow S01E01, the Blu-ray lineage) carry
    a '+' marker of zero length at every act break, and each of those files
    was refused whole -- 'non-positive cue duration' -- before any check."""

    def with_markers(self, offsets):
        cues = stepped(EP.hebrew, EP.breaks, offsets)
        marks = []
        for cut in EP.breaks:
            k = sum(c[0] < cut + offsets[sum(cut >= b for b in EP.breaks) - 1] for c in cues)
            at = cues[k - 1][1] + 2000 if k else 1000
            marks.append([at, at])
        merged = sorted(cues + marks)
        text = '\n'.join('%d\n%s --> %s\n%s\n' % (
            n, sa._ms_to_stamp(s), sa._ms_to_stamp(e), '+' if e == s else 'line')
            for n, (s, e) in enumerate(merged, 1))
        return text, merged

    def test_markers_at_the_act_breaks_do_not_block_the_fix(self):
        text, merged = self.with_markers(CLASSIC)
        self.assertEqual(sum(1 for s, e in merged if e == s), len(EP.breaks))
        verdict, label, _count = sub._verify_file_bundle(EP.bundle(), text, WEB)
        self.assertEqual(verdict['status'], sa.STATUS_FIXABLE, verdict.get('diag'))
        self.assertEqual(len(verdict['segments']), len(CLASSIC))
        before = sa._timed_signature(text)
        after = sa._timed_signature(sa.apply_verdict(text, verdict))
        self.assertEqual([b[2] for b in before], [a[2] for a in after])
        self.assertEqual([i for i, b in enumerate(before) if b[1] == b[0]],
                         [i for i, a in enumerate(after) if a[1] == a[0]])
        self.assertTrue(all(after[i][0] >= after[i - 1][0] for i in range(1, len(after))))
        spoken = [a[0] for a in after if a[1] > a[0]]
        self.assertLess(max(abs(a - b[0]) for a, b in zip(spoken, EP.hebrew)), 350)

    def test_a_flat_shift_carries_the_marker_along(self):
        cues = [[s + 2600, e + 2600] for s, e in EP.hebrew]
        cues.insert(100, [cues[99][1] + 500, cues[99][1] + 500])
        text = '\n'.join('%d\n%s --> %s\n%s\n' % (
            n, sa._ms_to_stamp(s), sa._ms_to_stamp(e), '+' if e == s else 'line')
            for n, (s, e) in enumerate(cues, 1))
        verdict, _label, _count = sub._verify_file_bundle(EP.bundle(), text, WEB)
        self.assertEqual(verdict['status'], sa.STATUS_FIXABLE, verdict.get('diag'))
        after = sa._timed_signature(sa.apply_verdict(text, verdict))
        self.assertEqual(len(after), len(cues))
        self.assertEqual(after[100][0], after[100][1])
        self.assertLess(abs(after[0][0] - EP.hebrew[0][0]), 200)

    def test_a_cue_that_ends_before_it_starts_still_refuses_the_file(self):
        cues = [list(c) for c in stepped(EP.hebrew, EP.breaks, CLASSIC)]
        cues[50][1] = cues[50][0] - 400
        verdict, _label, _count = sub._verify_file_bundle(EP.bundle(), srt(cues), WEB)
        self.assertEqual(verdict['status'], sa.STATUS_UNKNOWN)
        self.assertIn('non-positive cue duration', verdict.get('diag', ''))

    def test_markers_are_never_timing_evidence(self):
        text = ('1\n00:00:05,000 --> 00:00:05,000\nword word\n\n'
                '2\n00:00:07,000 --> 00:00:09,000\nword word\n')
        cues, error = sa._preflight_srt(text, True)
        self.assertEqual(error, '')
        self.assertEqual(len(cues), 2)
        self.assertEqual([c['start'] for c in sa.dialogue_cues(cues)], [7000])
        self.assertEqual(sa._preflight_srt('1\n00:00:05,000 --> 00:00:05,000\nword\n', True)[1],
                         'no cue with a duration')
        # A reference is still read strictly.
        self.assertIn('non-positive cue duration', sa._preflight_srt(text)[1])
        self.assertEqual(sa.verify(text, srt(EP.hebrew))['status'], sa.STATUS_UNKNOWN)

    def test_a_rewrite_never_gives_a_spoken_line_zero_length(self):
        text = '1\n00:00:05,000 --> 00:00:05,001\nword word\n\n2\n00:00:07,000 --> 00:00:09,000\nword word\n'
        with self.assertRaises(ValueError):
            sa.apply_verdict(text, {'status': sa.STATUS_FIXABLE, 'scale': 2.0, 'offset_ms': 0.0})


class ProofRegistryTests(unittest.TestCase):
    """apply_verdict re-checks every proof: a stored verdict is only JSON."""

    @classmethod
    def setUpClass(cls):
        cls.text = EP.candidate(FINE)
        cls.fine = validated(FINE, fine=True)

    def refused(self, verdict):
        with self.assertRaises(ValueError):
            sa.apply_verdict(self.text, verdict)

    def test_the_lane_proof_needs_two_languages_and_strong_folds(self):
        base = dict(self.fine, validation_proof='native-text-lane-v1', holdout_score_min=0.9)
        sa.apply_verdict(self.text, dict(base, native_lane_tracks=2))
        self.refused(dict(base, native_lane_tracks=1))
        self.refused(dict(base, native_lane_tracks=2, holdout_score_min=0.84))
        self.refused(dict(base, native_lane_tracks=2, holdout_score_min=0.84, native_lane_score=0.99))
        self.refused(dict(base, native_lane_tracks=2, holdout_gain_min=0.09))
        self.refused(dict(base, native_lane_tracks=2, validation_folds=3))

    def test_there_is_no_single_track_proof(self):
        strong = dict(self.fine, planner='region', validation_folds=5, holdout_score_min=0.95,
                      holdout_gain_min=0.3, after_score=0.95, unique=0.95, post_residual_ms=50)
        self.refused(dict(strong, validation_proof='native-single-track-v1'))
        self.refused(strong)

    def test_a_proven_map_survives_the_stored_json(self):
        import json
        text = EP.candidate(ZIGZAG)
        verdict, _label, _count = sub._verify_file_bundle(EP.bundle(), text, WEB)
        again = json.loads(json.dumps(verdict))
        self.assertEqual(sa.apply_verdict(text, again), sa.apply_verdict(text, verdict))


if __name__ == '__main__':
    unittest.main()
