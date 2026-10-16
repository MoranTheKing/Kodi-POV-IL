"""SubSync against a bitmap (PGS) track: its index holds display EVENTS.

A PGS track's Matroska index lists the instant each caption appears AND the
instant it is cleared.  Read as cues, half of them are gaps between lines; the
text subtitle is therefore compared event to event, and the final offset is
measured on caption starts alone.
"""

import importlib.util
import random
import sys
import types
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai' / 'resources' / 'lib'
_spec = importlib.util.spec_from_file_location('sa_events', LIB / 'sync_align.py')
sa = importlib.util.module_from_spec(_spec)
sys.modules.setdefault('resources.lib.kodi_utils', types.SimpleNamespace(log=lambda *a, **k: None))
_spec.loader.exec_module(sa)


def captions(seed=7, count=420):
    rnd = random.Random(seed)
    t, out = 4000, []
    for _ in range(count):
        dur = rnd.randint(900, 4200)
        out.append((t, t + dur))
        t += dur + rnd.choice((80, 120, 160, 400, 900, 1500, 3000, 6000))
    return out


def srt(cues, end_bias=0):
    def stamp(ms):
        ms = max(0, int(ms))
        return '%02d:%02d:%02d,%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)
    return '\n\n'.join('%d\n%s --> %s\nline %d' % (i + 1, stamp(s), stamp(e + end_bias), i + 1)
                       for i, (s, e) in enumerate(cues)) + '\n'


def pgs_index(cues, shift=0):
    """Index starts of a PGS track: one event to show, one to clear."""
    points = sorted({s + shift for s, _e in cues} | {e + shift for _s, e in cues})
    out = []
    for i, p in enumerate(points):
        nxt = points[i + 1] if i + 1 < len(points) else p + 3000
        out.append({'start': p, 'end': p + max(600, min(3000, nxt - p - 100))})
    return out


class BitmapEventTests(unittest.TestCase):
    def test_an_in_sync_subtitle_is_confirmed_on_its_starts(self):
        cues = captions()
        # The text file ends its captions 150 ms after the disc clears them.
        v = sa.verify_cues(pgs_index(cues), srt(cues, end_bias=150), ref_events=True)
        self.assertEqual(v['status'], sa.STATUS_CONFIRMED)
        self.assertLess(abs(v['offset_ms']), 60)

    def test_a_shifted_subtitle_is_fixed_by_the_onset_offset(self):
        cues = captions()
        late = [(s + 2500, e + 2500) for s, e in cues]
        v = sa.verify_cues(pgs_index(cues), srt(late, end_bias=150), ref_events=True)
        self.assertEqual(v['status'], sa.STATUS_FIXABLE)
        self.assertAlmostEqual(v['offset_ms'], 2500, delta=60)

    def test_events_read_the_bitmap_track_better_than_cues(self):
        cues = captions()
        late = [(s + 2500, e + 2500) for s, e in cues]
        classic = sa.verify_cues(pgs_index(cues), srt(late))
        events = sa.verify_cues(pgs_index(cues), srt(late), ref_events=True)
        self.assertGreater(events['vote'], classic['vote'])

    def test_a_subtitle_of_another_cut_is_not_accepted(self):
        cues = captions()
        other = captions(seed=99)
        v = sa.verify_cues(pgs_index(cues), srt(other), ref_events=True)
        self.assertEqual(v['status'], sa.STATUS_UNKNOWN)

    def test_starts_that_disagree_never_confirm(self):
        cues = captions()
        # Ends match the disc exactly while every start is 600 ms early: the
        # events alone could read this as in sync.
        early = [(s - 600, e) for s, e in cues]
        v = sa.verify_cues(pgs_index(cues), srt(early), ref_events=True)
        self.assertNotEqual(v['status'], sa.STATUS_CONFIRMED)

    def test_events_mirror_the_index_reader(self):
        self.assertEqual(sa.bitmap_events([{'start': 1000, 'end': 2500}, {'start': 2600, 'end': 9000}]),
                         [{'start': 1000, 'end': 2400}, {'start': 2500, 'end': 3100},
                          {'start': 2600, 'end': 5600}, {'start': 9000, 'end': 11900}])


def _subsync_pairing():
    """_paired_bitmap_cues and its constants, executed from the source alone
    (subsync itself needs Kodi)."""
    import ast
    src = (LIB / 'subsync.py').read_text(encoding='utf-8')
    tree = ast.parse(src)
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name == '_paired_bitmap_cues')
            or (isinstance(n, ast.Assign) and any(
                getattr(t, 'id', '').startswith(('_PGS_PAIR_', 'MIN_REMOTE_CUES'))
                for t in n.targets))]
    ns = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), 'subsync_pairing', 'exec'), ns)
    return ns['_paired_bitmap_cues']


class PgsPairingTests(unittest.TestCase):
    def test_appear_and_clear_events_pair_into_captions(self):
        cues = captions()
        paired = _subsync_pairing()(pgs_index(cues))
        self.assertEqual([(c['start'], c['end']) for c in paired], cues)

    def test_the_parity_follows_the_display_times(self):
        cues = captions()
        # An index that starts with a stray clear event: the pairs must
        # still be show -> clear, not clear -> next show.
        events = pgs_index(cues)
        events.insert(0, {'start': 100, 'end': 700})
        paired = _subsync_pairing()(events)
        self.assertEqual([(c['start'], c['end']) for c in paired], cues)

    def test_a_track_whose_alternation_breaks_is_not_paired(self):
        # Review finding: 2% of captions back to back share one timestamp, so
        # every later pair flips to clear -> next appear.  The median alone
        # still looked like captions.
        rnd = random.Random(3)
        cues = captions(count=600)
        points = []
        for i, (s, e) in enumerate(cues):
            points.append(s)
            if rnd.random() >= 0.02:
                points.append(e)
        events = [{'start': p, 'end': p + 600} for p in points]
        self.assertIsNone(_subsync_pairing()(events))

    def test_events_that_do_not_pair_into_captions_are_left_alone(self):
        # Every event 5 s apart: neither pairing looks like captions with gaps.
        events = [{'start': 5000 * i, 'end': 5000 * i + 3000} for i in range(400)]
        long_pairs = [{'start': 30000 * i, 'end': 30000 * i + 600} for i in range(100)]
        self.assertIsNotNone(_subsync_pairing()(events))   # 5 s captions are plausible
        self.assertIsNone(_subsync_pairing()(long_pairs + [{'start': 30000 * 100 + 15000, 'end': 0}]))


class SubSyncWiringTests(unittest.TestCase):
    def test_one_pgs_representative_is_read_as_events_then_classic(self):
        text = (LIB / 'subsync.py').read_text(encoding='utf-8')
        body = text[text.index('def _verify_profile('):text.index('def _track_span(')]
        self.assertIn('bitmap_events and _track_codec_family', body)
        self.assertIn('ref_events=True', body)
        self.assertIn('return sync_align.verify_cues(cues, text, **kwargs)', body)
        self.assertEqual(text.count('bitmap_events=profile is events_profile'), 2)

    def test_a_pgs_only_file_needs_another_disc_language(self):
        text = (LIB / 'subsync.py').read_text(encoding='utf-8')
        body = text[text.index('def _validated_pgs_only_piecewise('):text.index('def _validated_micro_piecewise(')]
        self.assertIn('folds < 4 or holdout_min < 0.85 or gain_min < 0.15', body)
        self.assertIn('if not accepting:', body)
        self.assertIn("'validation_proof': 'native-disc-pgs-v1'", body)


class PgsProofApplyTests(unittest.TestCase):
    """apply_verdict accepts native-disc-pgs-v1 only with a second disc language."""

    def verdict(self, lanes):
        return {'status': sa.STATUS_FIXABLE, 'mode': 'piecewise', 'scale': 1.0,
                'offset_ms': -1000.0, 'validation_required': True,
                'validation_folds': 4, 'holdout_score_min': 0.90, 'holdout_gain_min': 0.20,
                'validation_proof': 'native-disc-pgs-v1', 'pgs_lane_tracks': lanes,
                'segments': [{'cand_from_ms': None, 'offset_ms': -1000.0},
                             {'cand_from_ms': 600000.0, 'offset_ms': -3000.0},
                             {'cand_from_ms': 1200000.0, 'offset_ms': -5000.0}]}

    def test_without_a_second_language_nothing_is_rewritten(self):
        text = srt(captions())
        with self.assertRaises(ValueError):
            sa.apply_verdict(text, self.verdict(0))

    def test_with_a_second_language_the_map_applies(self):
        text = srt(captions())
        out = sa.apply_verdict(text, self.verdict(1))
        self.assertNotEqual(out, text)


if __name__ == '__main__':
    unittest.main()
