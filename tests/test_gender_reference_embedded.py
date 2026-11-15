"""A gender reference from the other subtitle tracks inside the playing file.

The pool's numbers on 15 Nov 2026 (14 days, 1,079 AI translations): 343 had no gender reference, 267 of
them because no provider had a subtitle in any reference language; 187 of the 343 were translated from an
embedded track. A file with an English text track often carries Spanish, Arabic, Portuguese ... beside it,
on the same clock. They join the reference candidates (arabic_gender.begin(embedded=)), read through the
same guarded extraction as the source track, quietly (translate._extract_embedded_srt(reference=)).

Blind study 008 (15 Nov 2026): a Spanish track of the file against no reference, 8-10-2 -- no gain. So
since 0.3.88 only an ARABIC track is a reference (the owner's word; _EMBEDDED_REF_LANGS), and only for a
translation made from the file's own track. The mechanics below are exercised on every chain language
(Candidates opens _EMBEDDED_REF_LANGS to the whole chain); Shipped pins what is on."""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_embedded_buffer_gate as gate          # noqa: E402  (the real _extract_embedded_srt on a scripted player)
import test_gender_reference_windowed as win      # noqa: E402  (synthetic subtitle pairs, arabic_gender)


def track(num, lang, name='', **more):
    out = {'num': num, 'codec': 'S_TEXT/UTF8', 'lang': lang, 'forced': False, 'is_text': True, 'name': name,
           'sdh': False, 'signs': False, 'lang_explicit': True}
    out.update(more)
    return out


class Candidates(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mods = mock.patch.dict(sys.modules, win.MODS)
        cls.mods.start()
        cls.ag = win.MODS['resources.lib.arabic_gender']
        cls.base = win.cues(4242)
        cls.source = win.srt(cls.base, 'Source line')
        cls.langs = mock.patch.object(cls.ag, '_EMBEDDED_REF_LANGS', cls.ag._REF_CHAIN)
        cls.langs.start()

    @classmethod
    def tearDownClass(cls):
        cls.langs.stop()
        cls.mods.stop()

    def embedded(self, tracks, texts=None, read_log=None):
        def read(t):
            if read_log is not None:
                read_log.append(t['num'])
            return (texts or {}).get(t['num'])
        return (lambda: tracks), read

    def begin(self, embedded, provider=()):
        with mock.patch.object(self.ag, '_reference_candidates', lambda info: list(provider)):
            return self.ag.begin({'imdb_id': 'tt1'}, self.source, embedded=embedded)

    def test_one_track_a_language_in_the_chains_order(self):
        tracks = [track(3, 'fre'), track(4, 'spa', 'Español (SDH)', sdh=True), track(5, 'spa', 'Español'),
                  track(6, 'ara'), track(7, 'jpn'), track(8, 'por', 'Brazilian'), track(9, 'pt-BR')]
        got = self.ag._embedded_candidates(self.embedded(tracks))
        self.assertEqual([lang for lang, _c in got], ['ar', 'es', 'pt', 'fr'])
        self.assertIn('#5', dict(got)['es']['filename'])              # the plain track before the SDH one
        self.assertIn('#8', dict(got)['pt']['filename'])              # the first of two equals
        self.assertTrue(all(c['_embedded'] for _l, c in got))

    def test_tracks_nobody_can_vouch_for_are_left_out(self):
        tracks = [track(2, 'heb'),                                   # Hebrew: never a reference from a file
                  track(3, 'spa', 'Spanish (Machine Translated)'), track(4, 'ara', 'Arabic [MT]'),
                  track(5, 'rus', 'Google'), track(6, 'ita', 'AI'), track(7, 'por', 'auto-generated'),
                  track(8, 'fre', lang_explicit=False),              # no language of its own: 'eng' by default
                  track(9, 'pol', 'Polski')]
        got = self.ag._embedded_candidates(self.embedded(tracks))
        self.assertEqual([lang for lang, _c in got], ['pl'])

    def test_a_name_that_only_contains_those_letters_is_kept(self):
        got = self.ag._embedded_candidates(self.embedded([track(3, 'ita', 'Italiano'), track(4, 'spa', 'Latin'),
                                                          track(5, 'ara', 'Automne')]))
        self.assertEqual(sorted(lang for lang, _c in got), ['ar', 'es', 'it'])

    def test_the_providers_own_codes_for_portuguese_and_spanish_are_read(self):
        # QA Kodi, 15 Nov 2026: the engine handed back 'pt-pt' (three human subtitles in sixteen episodes)
        # and 'ea' (OpenSubtitles' Latin American Spanish); neither was taken for a chain language
        for code, lang in (('pt-pt', 'pt'), ('PT-PT', 'pt'), ('pt-br', 'pt'), ('ea', 'es'), ('es', 'es')):
            self.assertEqual(self.ag._chain_lang_of({'language': code}), lang, code)
        self.assertIsNone(self.ag._chain_lang_of({'language': 'pt-pt', '_is_mt': True}))     # a machine's is still out
        for code in ('sv', 'da', 'hu', 'tr', 'zh-cn', 'en'):
            self.assertIsNone(self.ag._chain_lang_of({'language': code}), code)

    def test_no_provider_has_anything_and_the_file_has_spanish(self):
        reads = []
        plan, diag = self.begin(self.embedded([track(5, 'spa')], {5: win.srt(self.base, 'Ref line')}, reads))
        self.assertEqual(diag, {'reason': 'pending', 'cands': 1})
        lang, mapping = plan.next()
        self.assertEqual(lang, 'es')
        self.assertEqual(reads, [5])
        self.assertGreater(len(mapping), 380)
        right = sum(1 for n, text in mapping.items() if text == 'Ref line %d' % n)
        self.assertGreater(right / float(len(mapping)), 0.97)

    def test_nothing_inside_the_file_is_as_before(self):
        for embedded in (None, self.embedded([]), self.embedded([track(5, 'jpn')])):
            plan, diag = self.begin(embedded)
            self.assertIsNone(plan)
            self.assertEqual(diag, {'reason': 'no_arabic', 'cands': 0})

    def test_a_track_of_the_file_takes_its_languages_turn_before_the_providers_own(self):
        # a provider's Hebrew first, as ever; then the file's Arabic, then the providers' Arabic
        provider = [{'language': 'he', '_engine_kind': 'human_he', 'link': 'h1'}, {'language': 'ar', 'link': 'a1'},
                    {'language': 'es', 'link': 's1'}, {'language': 'ru', 'link': 'r1'}]
        plan, _d = self.begin(self.embedded([track(5, 'spa'), track(6, 'ara'), track(7, 'fre')]), provider)
        order = [(lang, bool(c.get('_embedded'))) for lang, c in plan._ordered]
        self.assertEqual(order, [('he', False), ('ar', True), ('ar', False),
                                 ('es', True), ('es', False), ('ru', False), ('fr', True)])
        # deeper rounds are the providers' alone
        provider = [{'language': 'he', '_engine_kind': 'human_he', 'link': 'h%d' % i} for i in range(3)]
        provider += [{'language': 'ar', 'link': 'a%d' % i} for i in range(2)]
        plan, _d = self.begin(self.embedded([track(6, 'ara')]), provider)
        self.assertEqual([(lang, bool(c.get('_embedded'))) for lang, c in plan._ordered],
                         [('he', False), ('ar', True), ('ar', False), ('he', False), ('ar', False),
                          ('he', False)])
        # no provider has Arabic: the file's track still comes after the first Hebrew
        plan, _d = self.begin(self.embedded([track(6, 'ara')]), provider[:3])
        self.assertEqual([(lang, bool(c.get('_embedded'))) for lang, c in plan._ordered],
                         [('he', False), ('ar', True), ('he', False), ('he', False)])

    def test_a_track_that_cannot_be_read_gives_way_to_the_next_candidate(self):
        provider = [{'language': 'es', 'link': 's1'}]
        ref = win.srt(self.base, 'Ref line')
        plan, _d = self.begin(self.embedded([track(6, 'ara')], {}), provider)       # read() -> None
        with mock.patch.object(self.ag, '_download_candidate',
                               lambda c: c['_read']() if c.get('_embedded') else ref):
            lang, mapping = plan.next()
        self.assertEqual(lang, 'es')
        self.assertTrue(mapping)

    def test_the_providers_budget_does_not_take_the_files_tracks_with_it(self):
        # ten Hebrew and ten Arabic subtitles that do not align can spend the whole 60 s; a Spanish track of
        # the file comes after them and costs no provider anything
        provider = [{'language': 'he', '_engine_kind': 'human_he', 'link': 'h%d' % i} for i in range(3)]
        provider += [{'language': 'pl', 'link': 'p1'}]
        ref = win.srt(self.base, 'Ref line')
        reads = []
        plan, _d = self.begin(self.embedded([track(5, 'spa')], {5: ref}, reads), provider)
        plan._active_elapsed = self.ag._REFERENCE_DEADLINE_S                 # spent
        downloads = []
        with mock.patch.object(self.ag, '_download_candidate',
                               lambda c: (c['_read']() if c.get('_embedded') else downloads.append(c) or ref)):
            lang, mapping = plan.next()
            self.assertEqual((lang, downloads, reads), ('es', [], [5]))
            self.assertEqual(plan.next(), (None, None))                      # the Polish one stays unasked
        self.assertEqual(downloads, [])

    def test_a_track_of_the_file_does_not_count_against_the_providers_budget(self):
        ref = win.srt(self.base, 'Ref line')
        plan, _d = self.begin(self.embedded([track(6, 'ara')], {6: ref}), [])
        plan.next()
        self.assertEqual((plan._downloads, plan._active_elapsed), (0, 0.0))

    def fallbacks(self, good=()):
        """A plan whose Arabic aligns and whose nine second-tier candidates do not, but for `good`."""
        provider = [{'language': 'ar', 'link': 'ar1'}] + [
            {'language': lang, 'link': lang + '1'} for lang in ('es', 'ru', 'pt', 'pl', 'uk', 'fr', 'it', 'cs', 'ro')]
        ref, other = win.srt(self.base, 'Ref line'), win.srt(win.cues(99), 'Other')
        plan, _d = self.begin(None, provider)
        downloads = []

        def fetch(c):
            downloads.append(c['link'])
            return ref if c['link'] == 'ar1' or c['link'] in good else other
        return plan, downloads, mock.patch.object(self.ag, '_download_candidate', fetch)

    def test_a_fallback_reference_is_looked_for_briefly(self):
        # QA Kodi, 16 Nov 2026: with the first reference in hand, a blocked chunk had 33 subtitles downloaded and
        # refused over 40 s -- every candidate left
        plan, downloads, fetch = self.fallbacks()
        with fetch:
            self.assertEqual(plan.next()[0], 'ar')
            self.assertEqual(plan.next(max_tries=3), (None, None))
            self.assertEqual(downloads, ['ar1', 'es1', 'ru1', 'pt1'])
            # nothing is lost by the bound: an unbounded call goes on from there
            self.assertEqual(plan.next(), (None, None))
            self.assertEqual(len(downloads), 10)

    def test_a_fallback_that_aligns_within_the_bound_is_taken(self):
        plan, downloads, fetch = self.fallbacks(good=('ru1',))
        with fetch:
            self.assertEqual(plan.next()[0], 'ar')
            lang, mapping = plan.next(max_tries=3, max_seconds=15.0)
            self.assertEqual((lang, downloads), ('ru', ['ar1', 'es1', 'ru1']))
            self.assertTrue(mapping)

    def test_a_fallback_is_given_up_by_the_clock_too(self):
        plan, downloads, fetch = self.fallbacks()
        with fetch:
            self.assertEqual(plan.next()[0], 'ar')
            clock = iter(range(0, 100000, 4))                 # every look at the clock is 4 s on
            with mock.patch.object(self.ag.time, 'monotonic', lambda: next(clock)):
                self.assertEqual(plan.next(max_seconds=15.0), (None, None))
            self.assertLess(len(downloads), 6)                # not the nine that were left
            self.assertGreater(len(downloads), 1)

    def test_the_translation_asks_for_a_fallback_briefly_and_once(self):
        src = (gate.ADDON / 'resources' / 'lib' / 'translate.py').read_text(encoding='utf-8').replace('\r\n', '\n')
        fn = src[src.index('    def _ref_ensure(level):'):src.index('    def _pool_key(base_hash):')]
        self.assertIn('                    if _ref_stack:\n'
                      '                        lang, mp = plan.next(max_tries=_REF_FALLBACK_TRIES,\n'
                      '                                             max_seconds=_REF_FALLBACK_SECONDS)\n'
                      '                    else:\n'
                      '                        lang, mp = plan.next()\n', fn)
        self.assertIn('                    if _ref_stack:\n'
                      '                        _ref_plan[0] = None    # no later chunk looks again\n', fn)
        self.assertIn('    _REF_FALLBACK_TRIES = 6\n    _REF_FALLBACK_SECONDS = 15.0\n', src)

    def test_a_track_of_another_film_is_refused_like_any_candidate(self):
        other = win.srt(win.cues(99), 'Other')
        plan, _d = self.begin(self.embedded([track(6, 'ara')], {6: other}), [])
        self.assertEqual(plan.next(), (None, None))


class Shipped(unittest.TestCase):
    """What is on in 0.3.88: an Arabic track, for a translation made from the file's own track."""

    def setUp(self):
        self.mods = mock.patch.dict(sys.modules, win.MODS)
        self.mods.start()
        self.addCleanup(self.mods.stop)
        self.ag = win.MODS['resources.lib.arabic_gender']

    def test_only_an_arabic_track(self):
        self.assertEqual(self.ag._EMBEDDED_REF_LANGS, ('ar',))
        tracks = [track(3, 'spa'), track(4, 'rus'), track(5, 'fre'), track(6, 'ara', 'Arabic (SDH)', sdh=True),
                  track(7, 'ara'), track(8, 'por'), track(9, 'heb')]
        got = self.ag._embedded_candidates(((lambda: tracks), (lambda t: None)))
        self.assertEqual([lang for lang, _c in got], ['ar'])
        self.assertIn('#7', got[0][1]['filename'])
        self.assertEqual(self.ag._embedded_candidates(((lambda: tracks[:3]), (lambda t: None))), [])

    def test_a_file_with_spanish_only_is_as_before(self):
        with mock.patch.object(self.ag, '_reference_candidates', lambda info: []):
            plan, diag = self.ag.begin({'imdb_id': 'tt1'}, win.srt(win.cues(4242), 'Source line'),
                                       embedded=((lambda: [track(5, 'spa')]), (lambda t: None)))
        self.assertIsNone(plan)
        self.assertEqual(diag, {'reason': 'no_arabic', 'cands': 0})

    def test_only_a_translation_made_from_the_files_own_track_asks_the_file(self):
        src = (gate.ADDON / 'resources' / 'lib' / 'translate.py').read_text(encoding='utf-8')
        self.assertIn("                if payload.get('embedded') else None)", src.replace('\r\n', '\n'))
        self.assertTrue(gate.MODS['resources.lib.translate']._EMB_REF_DEFAULT)


class Reading(unittest.TestCase):
    """translate._embedded_reference and the quiet mode of the real _extract_embedded_srt."""

    def setUp(self):
        self.t = gate.MODS['resources.lib.translate']
        self.ku = gate.MODS['resources.lib.kodi_utils']
        self.ee = gate.MODS['resources.lib.embedded_extract']
        self.settings = {'embedded_reference': True}
        self.policy = {'enabled': True, 'allow_http': True}
        self.tracks = [track(2, 'eng'), track(3, 'spa'), track(4, 'ara', forced=True), track(5, 'fre', signs=True),
                       dict(track(6, 'ger'), is_text=False, codec='S_HDMV/PGS'), track(7, 'por')]

    def source(self, url=gate.URL, source_lang='en'):
        with mock.patch.dict(sys.modules, dict(gate.MODS)), \
                mock.patch.object(self.ku, 'get_bool', lambda k, d=False: self.settings.get(k, d)), \
                mock.patch.object(self.t, '_embedded_translation_policy', lambda: self.policy), \
                mock.patch.object(self.t, '_playing_video_url', lambda info: url):
            return self.t._embedded_reference({}, source_lang)

    def test_on_unless_the_setting_says_no(self):
        self.assertTrue(self.t._EMB_REF_DEFAULT)            # 0.3.88
        self.settings = {}
        self.assertIsNotNone(self.source())
        self.settings = {'embedded_reference': False}
        self.assertIsNone(self.source())

    def test_not_where_the_file_may_not_be_read(self):
        self.policy = {'enabled': False, 'allow_http': True}
        self.assertIsNone(self.source())
        self.policy = {'enabled': True, 'allow_http': False}        # 'local only'
        self.assertIsNone(self.source())
        self.assertIsNotNone(self.source(url=r'C:\films\film.mkv'))
        self.assertIsNone(self.source(url=''))                      # HLS / a plugin path

    def test_tracks_are_text_whole_and_not_the_sources_language(self):
        tracks, _read = self.source()
        with mock.patch.dict(sys.modules, dict(gate.MODS)), \
                mock.patch.object(self.ee, 'probe_tracks', lambda url, log=None: list(self.tracks)):
            self.assertEqual([t['num'] for t in tracks()], [3, 7])
        tracks, _read = self.source(source_lang='es')               # a Spanish source: Spanish is no reference
        with mock.patch.dict(sys.modules, dict(gate.MODS)), \
                mock.patch.object(self.ee, 'probe_tracks', lambda url, log=None: list(self.tracks)):
            self.assertEqual([t['num'] for t in tracks()], [2, 7])

    def test_the_tracks_the_extraction_parsed_are_used_and_the_head_is_not_read_again(self):
        # review, 0.3.88: probe_tracks is a 2 MB request beside the player, for a file that mostly has no Arabic
        probes = []

        def probe(url, log=None):
            probes.append(url)
            return list(self.tracks)
        self.t._EMB_TRACKS.clear()
        self.addCleanup(self.t._EMB_TRACKS.clear)
        tracks, _read = self.source()
        with mock.patch.dict(sys.modules, dict(gate.MODS)), mock.patch.object(self.ee, 'probe_tracks', probe):
            self.assertEqual([t['num'] for t in tracks()], [3, 7])
            self.assertEqual(probes, [gate.URL])                    # nothing remembered: the head is read
            self.t._remember_tracks(gate.URL, [track(2, 'eng'), track(9, 'ara')])
            self.assertEqual([t['num'] for t in tracks()], [9])
            self.assertEqual(len(probes), 1)                        # remembered: not read again
            self.t._remember_tracks('https://cdn.example/other.mkv', [track(2, 'eng')])
            self.assertEqual([t['num'] for t in tracks()], [9])     # another file's list is not this one's
        for i in range(4):
            self.t._remember_tracks('u%d' % i, [])
        self.assertEqual(len(self.t._EMB_TRACKS), self.t._EMB_TRACKS_KEEP)

    def test_an_extraction_hands_its_track_list_over(self):
        # the real extract_srt on a local Matroska file notes the tracks it parsed in stats
        src = (gate.ADDON / 'resources' / 'lib' / 'embedded_extract.py').read_text(encoding='utf-8')
        self.assertIn("src._stats['tracks'] = _track_rows(tracks)", src)
        tr = (gate.ADDON / 'resources' / 'lib' / 'translate.py').read_text(encoding='utf-8').replace('\r\n', '\n')
        self.assertIn("        if reference is None and isinstance(_xstats.get('tracks'), list):\n"
                      "            _remember_tracks(url, _xstats['tracks'])\n", tr)

    def read_with(self, world, n_requests=30, total=600, per_request=20):
        """read(track) through the REAL _extract_embedded_srt; the stream read is a loop that asks the abort
        callback before every request and reports its progress, as the real one does."""
        gate.WORLD[0] = world
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        seen = {'toasts': [], 'calls': []}

        def extract(url_or_path, track_num=None, lang=None, allow_http=False, deadline_s=0, abort_cb=None,
                    progress_cb=None, resume_path=None, stats=None, steps=None, log=None, **more):
            seen['calls'].append((track_num, lang, deadline_s, more.get('other_text'), more.get('on_track'),
                                  steps, os.path.basename(resume_path or '')))
            done = 0
            for _ in range(n_requests):
                if abort_cb():
                    return None
                time.sleep(1.0)
                done += per_request
                stats.update(done=done, total=total)
                progress_cb(done, total)
            return gate.SRT

        props = {}
        window = mock.MagicMock()
        window.getProperty.side_effect = lambda name: props.get(name, '')
        window.setProperty.side_effect = lambda name, value: props.__setitem__(name, value)
        window.clearProperty.side_effect = lambda name: props.pop(name, None)
        props['povil.embedded_partial'] = 'left by a pick'
        with mock.patch.dict(sys.modules, dict(gate.MODS)), \
                mock.patch('time.time', world.time), mock.patch('time.sleep', world.sleep), \
                mock.patch('time.monotonic', world.time), \
                mock.patch.object(self.t, '_playing_video_url', lambda info: gate.URL), \
                mock.patch.object(self.t, '_embedded_translation_policy', lambda: self.policy), \
                mock.patch.object(self.ku, 'get_bool', lambda k, d=False: self.settings.get(k, d)), \
                mock.patch.object(self.ku, 'cache_dir', lambda: tmp), \
                mock.patch.object(self.ku, 'log', lambda msg, level=None: world.logs.append(msg)), \
                mock.patch.object(self.ku, 'notify', lambda *a, **k: seen['toasts'].append(a)), \
                mock.patch.object(sys.modules['xbmcgui'], 'Window', lambda ident: window), \
                mock.patch.object(self.ee, 'extract_srt', extract):
            _tracks, read = self.t._embedded_reference({}, 'en')
            text = read(track(3, 'spa'))
        seen['props'] = props
        seen['read'] = read
        return text, seen

    def test_a_track_read_in_seconds_comes_back_as_text_and_nothing_is_said(self):
        text, seen = self.read_with(gate.World(lambda t: (95.0, 100)), n_requests=30)
        self.assertEqual(text, gate.SRT)
        self.assertEqual(seen['toasts'], [])                                   # no toast for a reference
        self.assertEqual(seen['props'].get('povil.embedded_partial'), 'left by a pick')     # a picker's flag untouched
        track_num, lang, deadline, other_text, on_track, steps, resume = seen['calls'][0]
        self.assertEqual((track_num, lang, deadline), (3, 'es', self.t._EMB_REF_DEADLINE_S))
        self.assertEqual((other_text, on_track, steps), (None, None, None))    # that track or nothing; no views
        self.assertEqual(resume, 'embedded_resume_es.bin')                     # never the source's own file

    def test_a_reading_that_would_take_minutes_is_given_up_early(self):
        # a line a request: 2 lines a second of 1,900 -- sixteen minutes
        world = gate.World(lambda t: (95.0, 100))
        text, seen = self.read_with(world, n_requests=2000, total=1900, per_request=2)
        self.assertIsNone(text)
        self.assertLess(world.t, self.t._EMB_REF_PROBE_S + 5)                  # stopped at the first look
        self.assertEqual(seen['toasts'], [])                                   # and no "stopped at N%"
        self.assertEqual(seen['props'].get('povil.embedded_partial'), 'left by a pick')
        self.assertEqual(len(seen['calls']), 1)
        self.assertTrue(any('too slow here for a reference' in m for m in world.logs))
        # the pace is the provider's: the file's next language is not tried (QA Kodi: French, then Italian)
        self.assertIsNone(seen['read'](track(7, 'por')))
        self.assertEqual(len(seen['calls']), 1)

    def test_a_track_that_takes_a_minute_is_read_to_the_end(self):
        world = gate.World(lambda t: (95.0, 100))
        text, _seen = self.read_with(world, n_requests=60, total=1200, per_request=20)    # 60 s in all
        self.assertEqual(text, gate.SRT)

    def test_a_viewer_who_picks_something_else_ends_it(self):
        world = gate.World(lambda t: (95.0, 100), playing=lambda t: t < 5)
        text, _seen = self.read_with(world, n_requests=60)
        self.assertIsNone(text)
        self.assertLess(world.t, 10)

    def test_a_pick_is_read_as_it_always_was(self):
        # the same function without reference=: its toasts and its flag are the pick's
        world = gate.World(lambda t: (95.0, 100))
        gate.WORLD[0] = world
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        toasts = []

        def extract(url_or_path, abort_cb=None, progress_cb=None, stats=None, **more):
            progress_cb(5, 100)
            return gate.SRT
        with mock.patch.dict(sys.modules, dict(gate.MODS)), \
                mock.patch('time.time', world.time), mock.patch('time.sleep', world.sleep), \
                mock.patch('time.monotonic', world.time), \
                mock.patch.object(self.t, '_playing_video_url', lambda info: gate.URL), \
                mock.patch.object(self.ku, 'cache_dir', lambda: tmp), \
                mock.patch.object(self.ku, 'log', lambda msg, level=None: None), \
                mock.patch.object(self.ku, 'notify', lambda *a, **k: toasts.append(a)), \
                mock.patch.object(self.ee, 'extract_srt', extract):
            self.assertTrue(self.t._extract_embedded_srt({}, 'en', allow_http=True))
        self.assertEqual(len(toasts), 1)                                       # "extracting ... N lines"


if __name__ == '__main__':
    unittest.main()
