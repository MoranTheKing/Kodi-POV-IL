"""SubSync's long computations leave room for other Kodi scripts.

Measured in QA Kodi (21, Python 3.11): while one add-on's thread runs a
CPU-bound loop that never sleeps, a new script -- the "בחירת כתוביות" button
-- does not start until the loop ends (15.8 s behind a 20 s loop, 0.3 s
idle); a 1 ms sleep every ~20 ms restores 0.3 s. Field logs from an Android
box showed 5-11 s waits behind SubSync's deep check.
"""

import importlib.util
import random
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / 'service.subtitles.kodipovilai' / 'resources' / 'lib'


def _load(name):
    with patch.dict(sys.modules, {'resources.lib.kodi_utils': types.SimpleNamespace(
            log=lambda *a, **k: None)}):
        spec = importlib.util.spec_from_file_location('breathe_' + name, LIB / (name + '.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


def _captions(seed, n=900):
    rnd = random.Random(seed)
    t, out = 4000, []
    for _ in range(n):
        d = rnd.randint(900, 4200)
        out.append({'start': t, 'end': t + d})
        t += d + rnd.choice((80, 160, 400, 900, 1500, 3000))
    return out


class BreatheTests(unittest.TestCase):
    def test_breathe_naps_at_most_once_per_slice(self):
        sa = _load('sync_align')
        clock = [100.0]
        naps = []
        with patch.object(sa.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(sa.time, 'sleep', side_effect=naps.append):
            sa._breath[0] = 0.0
            for _ in range(10):
                sa._breathe()            # same instant: one nap only
            clock[0] += sa._BREATHE_SLICE + 0.001
            sa._breathe()
        self.assertEqual(naps, [0.001, 0.001])

    def test_the_alignment_breathes_while_it_works(self):
        sa = _load('sync_align')
        naps = []
        ref = _captions(1)
        cand = _captions(99)
        with patch.object(sa.time, 'sleep', side_effect=naps.append):
            sa._breath[0] = 0.0
            sa._BREATHE_SLICE = 0.0      # every call counts: shows the call sites run
            sa.verify_cue_lists(ref, cand)
        self.assertGreater(len(naps), 100)

    def test_the_hot_loops_call_it(self):
        for name, funcs in (('sync_align', ('_best_offset', '_region_cost_rows', '_region_dp_path',
                                            'parse_srt', '_preflight_srt', '_is_dialogue',
                                            '_envelope_scores', 'retime', '_timed_signature')),
                            ('mp4_probe', ('audio_envelope',)),
                            ('subsync', ('_onset_coverage', '_shift_invariant_shape_coverage')),
                            ('embedded_extract', ('_walk',))):
            src = (LIB / (name + '.py')).read_text(encoding='utf-8')
            for fn in funcs:
                body = src[src.index('def %s(' % fn):]
                body = body[:body.index('\ndef ', 10)]
                self.assertIn('_breathe()', body, msg='%s.%s' % (name, fn))


if __name__ == '__main__':
    unittest.main()
