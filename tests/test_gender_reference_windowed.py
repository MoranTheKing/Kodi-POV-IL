"""The gender reference's own windowed alignment (arabic_gender, 0.3.64), and
the gate's own map checked window by window (0.3.65).

The SubSync-grade gate protects displayed timing and refuses what a gender
oracle can use: small steps at every ad break, one window of music minutes
off, a whole-file vote just under the floor. When it refuses, a ~5-minute
window counts when a neighbour agrees with its offset, windows within 0.6 s
form a plateau, and a line in a window nothing vouched for gets no reference.
A reference of another title must still never be accepted. And the search for
a reference no longer comes back empty behind the search that found the
source subtitle.
"""
import json
import random
import sys
import unittest
from pathlib import Path
from unittest import mock

ADDON = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai'


def _load():
    stubs = dict((n, mock.MagicMock(name=n)) for n in
                 ('xbmc', 'xbmcaddon', 'xbmcgui', 'xbmcvfs', 'xbmcplugin'))
    with mock.patch.dict(sys.modules, stubs):
        sys.path.insert(0, str(ADDON))
        try:
            from resources.lib import arabic_gender, sync_align, subs_engine_bridge  # noqa: F401
        finally:
            sys.path.remove(str(ADDON))
        mods = dict((k, v) for k, v in sys.modules.items()
                    if k in stubs or k == 'resources' or k.startswith('resources.'))
    return mods


MODS = _load()


def stamp(ms):
    ms = max(0, int(round(ms)))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return '%02d:%02d:%02d,%03d' % (h, m, s, ms)


def srt(cues, prefix):
    return '\n\n'.join('%d\n%s --> %s\n%s %d' % (i, stamp(a), stamp(b), prefix, i)
                       for i, (a, b) in enumerate(cues, 1)) + '\n'


def cues(seed, count=420, gap=(1700, 5600), dur=(900, 3100)):
    rng = random.Random(seed)
    clock, out = 12000, []
    for _ in range(count):
        clock += rng.randint(*gap)
        d = rng.randint(*dur)
        out.append((clock, clock + d))
    return out


def shifted(base, steps):
    """steps: [(from source ms, offset ms)], each holding until the next."""
    out = []
    for a, b in base:
        off = 0
        for at, value in steps:
            if a >= at:
                off = value
        out.append((a + off, b + off))
    return out


class Windowed(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mods = mock.patch.dict(sys.modules, MODS)
        cls.mods.start()
        cls.ag = MODS['resources.lib.arabic_gender']
        cls.base = cues(8917)
        cls.source = srt(cls.base, 'Source line')
        cls.blocks = cls.source.strip().split('\n\n')

    @classmethod
    def tearDownClass(cls):
        cls.mods.stop()

    def at(self, fraction):
        return self.base[int(len(self.base) * fraction)][0]

    def right_share(self, mapping):
        right = sum(1 for n, text in mapping.items() if text == 'Ref line %d' % n)
        return right / float(len(mapping))

    def test_a_staircase_of_small_steps_is_aligned_window_by_window(self):
        # a broadcast master: +3-4 s at every ad break, five plateaus -- the
        # gate refuses (steps under 5 s, more than four regions)
        steps = [(0, 0), (self.at(0.2), 3500), (self.at(0.4), 7000),
                 (self.at(0.6), 10500), (self.at(0.8), 14000)]
        mapping, diag = self.ag.align_one(self.source, self.blocks,
                                          srt(shifted(self.base, steps), 'Ref line'))
        self.assertIsNotNone(mapping, diag)
        self.assertTrue(diag.startswith('windowed '), diag)
        self.assertIn('plateaus=5', diag)
        self.assertGreater(len(mapping), 0.9 * len(self.base))
        self.assertGreaterEqual(self.right_share(mapping), 0.97, diag)

    def test_negative_and_small_steps_and_a_drifting_clock(self):
        rng = random.Random(77)
        shapes = {
            'negative': [(0, 0)] + [(self.at(f), -k * 3200) for k, f in enumerate((0.2, 0.4, 0.6, 0.8), 1)],
            'small': [(0, 0)] + [(self.at(f), rng.choice((1, -1)) * rng.randint(1000, 1450) * k)
                                 for k, f in enumerate((0.15, 0.3, 0.45, 0.6, 0.75, 0.9), 1)],
        }
        for name, steps in shapes.items():
            ref = shifted(self.base, steps)
            mapping, diag = self.ag.align_one(self.source, self.blocks, srt(ref, 'Ref line'))
            if mapping is not None:
                self.assertGreaterEqual(self.right_share(mapping), 0.97, (name, diag))
        drift = [(a * 1.0006, b * 1.0006) for a, b in shifted(
            self.base, [(0, 0), (self.at(0.3), 3500), (self.at(0.6), 7000)])]
        mapping, diag = self.ag.align_one(self.source, self.blocks, srt(drift, 'Ref line'))
        self.assertIsNotNone(mapping, diag)
        self.assertGreaterEqual(self.right_share(mapping), 0.97, diag)

    def test_a_short_source_never_takes_a_dense_reference_of_another_title(self):
        # 80-120 dialogue lines make 4-5 windows, which a dense reference
        # saturates: the windowed pass needs 8 (review, 0.3.64)
        for count in (80, 100, 120):
            src = srt(cues(4040 + count, count=count), 'Source line')
            blocks = src.strip().split('\n\n')
            for seed in (1, 2, 3):
                other = srt(cues(seed, count=1400, gap=(500, 1500), dur=(600, 1400)), 'Ref line')
                mapping, diag = self.ag.align_one(src, blocks, other)
                self.assertIsNone(mapping, (count, seed, diag))

    def test_the_shape_the_legacy_helper_refused(self):
        steps = [(0, 0), (self.at(1 / 3.0), 3000), (self.at(0.5), 8000),
                 (self.at(2 / 3.0), 12000)]
        mapping, diag = self.ag.align_one(self.source, self.blocks,
                                          srt(shifted(self.base, steps), 'Ref line'))
        self.assertIsNotNone(mapping, diag)
        self.assertGreaterEqual(self.right_share(mapping), 0.97, diag)

    def test_a_window_off_by_minutes_gets_no_line_the_rest_do(self):
        # a stretch of music/silence where the estimate lands minutes away:
        # one window's cues of the reference are replaced by unrelated timing
        ref = list(self.base)
        lo, hi = int(len(ref) * 0.45), int(len(ref) * 0.52)
        rng = random.Random(5)
        span = (ref[lo][0], ref[hi][0])
        for i in range(lo, hi):
            a = rng.randint(*span)
            ref[i] = (a, a + 1500)
        ref.sort()
        mapping, diag = self.ag.align_one(self.source, self.blocks,
                                          srt(shifted(ref, [(0, 0), (self.at(0.7), 2500)]),
                                              'Ref line'))
        self.assertIsNotNone(mapping, diag)
        outside = {n: t for n, t in mapping.items() if not lo < n <= hi}
        self.assertGreaterEqual(self.right_share(outside), 0.97, diag)

    def test_a_reference_of_another_title_is_never_accepted(self):
        for seed, density in ((101, (1700, 5600)), (202, (900, 2600)), (303, (600, 1800))):
            other = srt(cues(seed, count=700, gap=density), 'Ref line')
            mapping, diag = self.ag.align_one(self.source, self.blocks, other)
            self.assertIsNone(mapping, (seed, diag))

    def test_a_clean_pair_stays_on_the_gate(self):
        mapping, diag = self.ag.align_one(
            self.source, self.blocks, srt(shifted(self.base, [(0, 2000)]), 'Ref line'))
        self.assertTrue(diag.startswith('gate OK'), diag)
        self.assertEqual(self.right_share(mapping), 1.0)

    def body(self, rows):
        return '\n\n'.join('%d\n%s --> %s\n%s' % (i, stamp(a), stamp(b), text)
                           for i, (a, b, text) in enumerate(rows, 1)) + '\n'

    def test_a_reference_whose_middle_is_another_title_loses_that_middle(self):
        # The gate needs 60% of its windows and then maps every line: a
        # reference with a stretch of another title's subtitle in it passed
        # with that stretch mapped (review, 0.3.64: 26-34% of lines wrong on
        # the corpus). The windows that contradict its map now hand the
        # reference to the windowed plan.
        rng = random.Random(43)
        lo, hi = self.at(0.6), self.at(0.78)
        rows = [(a, b, 'Ref line %d' % n) for n, (a, b) in enumerate(self.base, 1)
                if not lo <= a < hi]
        clock = lo
        while clock < hi:
            clock += rng.randint(1200, 4000)
            rows.append((clock, clock + rng.randint(700, 1800), 'Other title'))
        rows.sort()
        mapping, diag = self.ag.align_one(self.source, self.blocks, self.body(rows))
        self.assertIsNotNone(mapping, diag)
        self.assertIn('contradict', diag)
        self.assertGreaterEqual(self.right_share(mapping), 0.97, diag)
        self.assertGreater(len(mapping), 0.5 * len(self.base))

    def test_scenes_cut_from_the_reference(self):
        # three scenes cut: the gate accepts a piecewise map that put 6.8% of
        # the lines on a neighbour (0.3.64); the windows contradict it
        rng = random.Random(23)
        cuts = sorted((self.at(rng.uniform(0.1, 0.9)), rng.randint(20000, 60000))
                      for _ in range(3))
        rows = []
        for n, (a, b) in enumerate(self.base, 1):
            if any(at <= a < at + length for at, length in cuts):
                continue
            shift = sum(length for at, length in cuts if a >= at + length)
            rows.append((a - shift, b - shift, 'Ref line %d' % n))
        mapping, diag = self.ag.align_one(self.source, self.blocks, self.body(rows))
        self.assertIsNotNone(mapping, diag)
        self.assertIn('contradict', diag)
        self.assertGreaterEqual(self.right_share(mapping), 0.97, diag)

    def test_a_short_source_keeps_the_gate_map_where_it_held(self):
        # 140 lines make 7 windows, too few for the windowed plan: with one
        # contradicting window the lines of those that hold keep the gate's
        # map where they fit it, and the other title's stretch gets nothing
        base = cues(5290, count=140)
        source = srt(base, 'Source line')
        at = lambda f: base[int(len(base) * f)][0]
        rng = random.Random(3)
        lo, hi = at(0.4), at(0.6)
        rows = [(a, b, 'Ref line %d' % n) for n, (a, b) in enumerate(base, 1)
                if not lo <= a < hi]
        clock = lo
        while clock < hi:
            clock += rng.randint(1200, 4000)
            rows.append((clock, clock + rng.randint(700, 1800), 'Other title'))
        rows.sort()
        mapping, diag = self.ag.align_one(source, source.strip().split('\n\n'),
                                          self.body(rows))
        self.assertIsNotNone(mapping, diag)
        self.assertTrue(diag.startswith('windowed: the gate map where it held'), diag)
        self.assertNotIn('Other title', mapping.values())
        self.assertEqual(self.right_share(mapping), 1.0)
        self.assertGreater(len(mapping), 0.7 * len(base))

    def test_a_short_source_loses_a_stretch_its_windows_cannot_see(self):
        # 100 lines, 5 windows of 20: a twelfth of another title fits inside
        # one window's tolerance, so no window contradicts the gate -- the
        # line-level stretch check (0.3.66) still leaves it out
        base = cues(6200, count=100)
        source = srt(base, 'Source line')
        blocks = source.strip().split('\n\n')
        at = lambda f: base[int(len(base) * f)][0]
        rng = random.Random(3)
        lo, hi = at(0.4), at(0.52)
        rows = [(a, b, 'Ref line %d' % n) for n, (a, b) in enumerate(base, 1)
                if not lo <= a < hi]
        clock = lo
        while clock < hi:
            clock += rng.randint(1200, 4000)
            rows.append((clock, clock + rng.randint(700, 1800), 'Other title'))
        rows.sort()
        mapping, diag = self.ag.align_one(source, blocks, self.body(rows))
        self.assertIsNotNone(mapping, diag)
        self.assertIn('stretches off the map left out', diag)
        self.assertNotIn('Other title', mapping.values())
        self.assertEqual(self.right_share(mapping), 1.0)
        # the same short source with a clean reference keeps every line
        mapping, diag = self.ag.align_one(
            source, blocks, srt(shifted(base, [(0, 1200)]), 'Ref line'))
        self.assertNotIn('stretches', diag)
        self.assertEqual(len(mapping), len(base))

    def test_a_clean_pair_keeps_every_line(self):
        mapping, diag = self.ag.align_one(
            self.source, self.blocks, srt(shifted(self.base, [(0, -1500)]), 'Ref line'))
        self.assertTrue(diag.startswith('gate OK'), diag)
        self.assertNotIn('contradict', diag)
        self.assertEqual(len(mapping), len(self.base))
        self.assertEqual(self.right_share(mapping), 1.0)



class SearchAfterACutSearch(unittest.TestCase):
    """The search that found the source subtitle stops at max_search_time and
    leaves its slowest provider running; the engine refuses every search until
    it ends, so the reference search right after it found nothing (QA Kodi,
    2 Nov 2026: Friends, Breaking Bad, The Untouchables -- 0 in 0.4 s, then
    19-335 candidates once the provider ended)."""

    def run_search(self, reused, results, busy):
        calls = []
        fake = mock.MagicMock()
        fake.reusable_results.side_effect = lambda info: calls.append('reuse') or reused
        fake.search.side_effect = lambda info, modal_progress=True: (
            calls.append('search') or results.pop(0))
        fake.providers_busy.side_effect = lambda: busy
        fake.wait_for_providers.side_effect = lambda s: calls.append(('wait', s)) or True
        ag = MODS['resources.lib.arabic_gender']
        settings = {'all_lang': 'false', 'language_arab': 'false'}

        def set_setting(k, v):
            calls.append(('set', k, v))
            settings[k] = v
        with mock.patch.dict(sys.modules, MODS), \
                mock.patch.dict(sys.modules, {'resources.lib.subs_engine_bridge': fake}), \
                mock.patch.object(sys.modules['resources.lib'], 'subs_engine_bridge', fake,
                                  create=True), \
                mock.patch.object(ag.kodi_utils, 'get_setting', lambda k, d='': settings.get(k, d)), \
                mock.patch.object(ag.kodi_utils, 'set_setting', set_setting):
            found = ag._reference_candidates({'imdb_id': 'tt1'})
        return found, calls, settings

    def test_what_the_source_search_found_is_used_without_searching(self):
        reused = [{'language': 'en'}, {'language': 'ar'}]
        found, calls, _s = self.run_search(reused, [], busy=True)
        self.assertEqual((found, calls), (reused, ['reuse']))

    def test_refused_search_waits_first_then_flips_and_searches_once(self):
        found, calls, settings = self.run_search(
            [{'language': 'en'}], [[{'language': 'es'}]], busy=True)
        self.assertEqual(found, [{'language': 'es'}])
        self.assertEqual(calls[:2], ['reuse', ('wait', 20.0)])
        self.assertEqual(calls.count('search'), 1)
        self.assertLess(calls.index(('wait', 20.0)), calls.index(('set', 'language_arab', 'true')))
        self.assertEqual(settings, {'all_lang': 'false', 'language_arab': 'false'})   # restored

    def test_hebrew_alone_is_kept_and_the_other_languages_searched_for(self):
        he = {'language': 'he', '_engine_kind': 'human_he', 'link': 'h1'}
        found, calls, _s = self.run_search([he, {'language': 'en'}],
                                           [[{'language': 'ar', 'link': 'a1'}]], busy=False)
        self.assertEqual(found, [{'language': 'ar', 'link': 'a1'}, he])
        self.assertEqual(calls.count('search'), 1)

    def test_nothing_reused_nothing_running_is_one_search(self):
        found, calls, _s = self.run_search([], [[]], busy=False)
        self.assertEqual(found, [])
        self.assertEqual([c for c in calls if not isinstance(c, tuple)], ['reuse', 'search'])


class FakeWindow(object):
    store = {}

    def __init__(self, wid=None):
        pass

    def getProperty(self, k):
        return self.store.get(k, '')

    def setProperty(self, k, v):
        self.store[k] = v


class Bridge(unittest.TestCase):

    def setUp(self):
        self.mods = mock.patch.dict(sys.modules, MODS)
        self.mods.start()
        self.addCleanup(self.mods.stop)
        self.sb = MODS['resources.lib.subs_engine_bridge']
        FakeWindow.store = {}
        gui = mock.MagicMock()
        gui.Window = FakeWindow
        for p in (mock.patch.dict(sys.modules, {'xbmcgui': gui}),
                  mock.patch.object(self.sb, 'enabled', lambda: True),
                  mock.patch.object(self.sb, '_release_ready', lambda info: False)):
            p.start()
            self.addCleanup(p.stop)

    def engine(self, alive):
        eng = mock.MagicMock()
        eng._lingering_provider_threads = [mock.MagicMock(is_alive=lambda: a) for a in alive]
        return eng

    def test_providers_busy(self):
        self.assertFalse(self.sb.providers_busy())     # the engine never loaded
        with mock.patch.dict(sys.modules, {'resources.lib.subs_engine.engine': self.engine([False])}):
            self.assertFalse(self.sb.providers_busy())
        with mock.patch.dict(sys.modules, {'resources.lib.subs_engine.engine': self.engine([False, True])}):
            self.assertTrue(self.sb.providers_busy())

    def test_the_wait_ends_with_the_provider_or_with_kodi(self):
        eng = self.engine([True])
        answers = [False, False, True]
        eng._provider_workers_ready.side_effect = lambda t: answers.pop(0)
        monitor = mock.MagicMock()
        monitor.abortRequested.return_value = False
        with mock.patch.dict(sys.modules, {'resources.lib.subs_engine.engine': eng}), \
                mock.patch.object(sys.modules['xbmc'], 'Monitor', lambda: monitor):
            self.assertTrue(self.sb.wait_for_providers(20))
            eng._provider_workers_ready.side_effect = lambda t: False
            self.assertFalse(self.sb.wait_for_providers(0))
            monitor.abortRequested.return_value = True
            self.assertFalse(self.sb.wait_for_providers(20))   # Kodi exits: no 20 s

    def test_a_cut_search_serves_the_reference_never_the_picker(self):
        info = {'imdb_id': 'tt1', 'season': '1', 'episode': '1'}
        runs = []
        with mock.patch.object(self.sb, '_search_inner',
                               lambda i, modal_progress=True: runs.append(1) or [{'language': 'ar'}]), \
                mock.patch.object(self.sb, '_search_finished', lambda took=None: False):
            self.assertEqual(self.sb.search(info, modal_progress=False), [{'language': 'ar'}])
            self.assertEqual(self.sb.reusable_results(info), [{'language': 'ar'}])
            self.sb.search(info, modal_progress=False)      # the picker searches again
        self.assertEqual(len(runs), 2)
        self.assertNotIn(self.sb._RECENT_PROP, FakeWindow.store)
        self.assertEqual(json.loads(FakeWindow.store[self.sb._CUT_PROP])[-1]['out'], [{'language': 'ar'}])


if __name__ == '__main__':
    unittest.main()
