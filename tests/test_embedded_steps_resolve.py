"""An embedded pick from end to end: the REAL translate.resolve() reporting to
the REAL default.py handler (MoranSubs 0.3.80).

tests/test_embedded_steps.py covers the pieces. This module covers how
resolve() wires them, which is where both earlier drafts of the feature went
wrong: the first showed nothing after its first step, and the second showed
everything but skipped the residual repairs and the gender proofread of the
translation that is saved and shared, because "is this still the translation
being watched" was asked about an id the screen no longer carried (review of
0.3.80; the harness is adapted from the reviewer's).

Replaced: the network (gemini.generate; Google raises), the stream read
(embedded_extract.extract_srt, which drives the steps it is handed as the real
one does), Kodi (stubs with a real property store) and the pool (off)."""
import base64
import importlib.util
import os
import shutil
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / 'service.subtitles.kodipovilai'
RELEASE = 'Show.S01E01.1080p.WEB.h264-GRP'
PROPS = {}
EVENTS = []          # ('view' | 'final' | 'embedded', ...) as they reach the player


class Player(object):
    streams = ['embedded:eng']
    at_s = 0.0

    def isPlayingVideo(self):
        return True

    def getPlayingFile(self):
        return 'https://cdn.example/film.mkv'

    def getAvailableSubtitleStreams(self):
        return list(Player.streams)

    def setSubtitles(self, path):
        Player.streams.append(path)
        EVENTS.append(('final', os.path.basename(path), Path(path).read_text(encoding='utf-8')))

    def showSubtitles(self, on):
        pass

    def setSubtitleStream(self, index):
        pass

    def getTime(self):
        return Player.at_s

    def getTotalTime(self):
        return 2700.0


def _stubs():
    xbmc = types.ModuleType('xbmc')
    xbmc.Player = Player
    xbmc.sleep = lambda ms: None
    xbmc.log = lambda *a, **k: None
    xbmc.LOGINFO = xbmc.LOGWARNING = xbmc.LOGERROR = xbmc.LOGDEBUG = 0
    xbmc.executebuiltin = lambda *a, **k: None
    xbmc.getCondVisibility = lambda *a: False
    xbmc.getInfoLabel = lambda *a: ''
    xbmc.Monitor = lambda: types.SimpleNamespace(abortRequested=lambda: False, waitForAbort=lambda s=0: False)
    xbmcgui = types.ModuleType('xbmcgui')
    xbmcgui.WindowDialog = xbmcgui.WindowXMLDialog = xbmcgui.WindowXML = object
    xbmcgui.Window = lambda ident: types.SimpleNamespace(
        getProperty=lambda name: PROPS.get(name, ''),
        setProperty=lambda name, value: PROPS.__setitem__(name, value),
        clearProperty=lambda name: PROPS.pop(name, None))
    xbmcgui.DialogProgressBG = lambda: types.SimpleNamespace(
        create=lambda *a: EVENTS.append(('bar',)), update=lambda *a: None, close=lambda: None)
    xbmcgui.Dialog = lambda: mock.MagicMock()
    out = {'xbmc': xbmc, 'xbmcgui': xbmcgui}
    for name in ('xbmcaddon', 'xbmcplugin', 'xbmcvfs'):
        out[name] = mock.MagicMock(name=name)
    return out


def _load():
    """The add-on's package, privately: {module name: module} to patch into sys.modules while it runs."""
    stubs = _stubs()

    def ours(name):
        return name == 'resources' or name.startswith('resources.')
    kept = {name: sys.modules.pop(name) for name in list(sys.modules) if ours(name)}
    try:
        with mock.patch.dict(sys.modules, stubs):
            sys.path.insert(0, str(ADDON))
            try:
                from resources.lib import translate, kodi_utils, google_translate, embedded_extract  # noqa: F401
                from resources.lib import subs_engine_bridge, subsync  # noqa: F401
            finally:
                sys.path.remove(str(ADDON))
            mods = dict((k, v) for k, v in sys.modules.items() if k in stubs or ours(k))
    finally:
        for name in list(sys.modules):
            if ours(name):
                del sys.modules[name]
        sys.modules.update(kept)
    return mods


def stamp(ms):
    return '%02d:%02d:%02d,%03d' % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


LINES = ['Where are you going tonight?', 'I told you so yesterday.', 'Come back here right now.',
         'She is not coming with us.', 'We need to talk about it.', 'Leave him alone, please.']
N = 60
STARTS = [i * 3000 for i in range(N)]
ENGLISH = '\n\n'.join('%d\n%s --> %s\n%s %d' % (i + 1, stamp(s), stamp(s + 1500), LINES[i % len(LINES)], i + 1)
                      for i, s in enumerate(STARTS)) + '\n'
LEFT_IN_ENGLISH = 7          # the model returns this cue as it got it: work for the residual repair


def until(what, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        if what():
            return True
        time.sleep(0.01)
    return bool(what())


class Job(object):
    """One embedded pick. `views`: the step translator answers. `whole`: the extraction comes back."""

    def __init__(self, mods, views=True, whole=True, handler=True, fed=N, moved_on=False, folder=None,
                 noindex=False, externals=None):
        self.mods = mods
        self.t = mods['resources.lib.translate']
        self.views, self.whole, self.handler, self.fed = views, whole, handler, fed
        self.moved_on, self.folder, self.current = moved_on, folder, True
        self.sent = []               # (model, kind) of every request
        self.log = []
        self.steps = []              # the _EmbeddedSteps resolve() made
        self.spans = []
        self.timelines = []
        self.extract_kwargs = {}
        self.result = None
        self.saved = ''
        # noindex: the stream's index has no subtitle lines (extract_srt says so in stats['why'])
        self.noindex = noindex
        self.externals = externals if externals is not None else [
            {'release': 'Show.S01E01.1080p.WEB.h264-OTHER', 'language': 'en',
             'payload': {'type': 'engine', 'filename': 'Show.S01E01.1080p.WEB.h264-OTHER', 'id': 'a'}},
            {'release': RELEASE, 'language': 'en',
             'payload': {'type': 'engine', 'filename': RELEASE, 'id': 'b'}},
            {'release': RELEASE, 'language': 'fr',
             'payload': {'type': 'engine', 'filename': RELEASE + '.fr', 'id': 'c'}}]
        self.downloads = []

    def run(self):
        t, mods = self.t, self.mods
        kodi_utils = mods['resources.lib.kodi_utils']
        PROPS.clear()
        del EVENTS[:]
        Player.streams = ['embedded:eng']
        Player.at_s = 0.0
        folder = self.folder or tempfile.mkdtemp(prefix='steps_resolve_')
        settings = {'api_key': 'KEY', 'model': 'gemini-3.5-flash-lite', 'translation_mode': 'ai',
                    'thinking_budget': 'medium'}
        bools = {'gender_ref_arabic': False, 'gender_proofread': True, 'pool_share': False, 'pool_use': False,
                 'ai_paid_mode': False}

        def generate(**kw):
            prompt = kw['prompt']
            mark = 'in this order:'
            is_chunk = 'SRT to translate' in prompt and mark in prompt
            blocks = t.srt.parse_blocks(prompt[prompt.rfind(mark) + len(mark):]) if is_chunk else []
            step = bool(blocks) and kw.get('timeout') == t._STEPS_TIMEOUT
            kind = 'step' if step else 'chunk' if blocks else (
                'proofread' if kw['model'] != 'gemini-3.5-flash-lite' else 'repair')
            self.sent.append((kw['model'], kind))
            if kind == 'step' and not self.views:
                raise t.gemini.QuotaExceeded('test: no view')
            if kind in ('proofread', 'repair'):
                raise t.gemini.GeminiError('test: no answer')
            out = []
            for b in blocks:
                head = b.split('\n')[:2]
                num = head[0].strip()
                if kind == 'chunk' and num == str(LEFT_IN_ENGLISH):
                    out.append(b)
                else:
                    out.append('\n'.join(head + [('תצוגה %s' if step else 'שורה בעברית מספר %s.') % num]))
            return '\n\n'.join(out) + '\n'

        def no_google(*a, **k):
            raise RuntimeError('test: no Google')

        real_steps = t._embedded_steps

        def embedded_steps(*a, **k):
            made = real_steps(*a, **k)
            self.steps.append(made)
            return made

        def extract_srt(url, **kw):
            # as embedded_extract.extract_srt drives its `steps`: the cue times, a window, what was read
            self.extract_kwargs = kw
            if self.noindex:
                kw['stats']['why'] = 'no_index'
                if self.moved_on:
                    self.current = False     # the viewer picked something else meanwhile
                return None
            steps = kw.get('steps')
            progress = kw.get('progress_cb') or (lambda done, total: None)
            progress(5, N)                                       # the bar, before anything is shown
            if steps:
                window, show, timeline, moved = steps
                self.moved = moved
                timeline(list(STARTS))
                self.timelines.append(list(STARTS))
                self.spans.append(window())
                show('\n\n'.join(ENGLISH.strip().split('\n\n')[:self.fed]) + '\n')
                if self.views:
                    held = self.steps[0]
                    until(lambda: len(held._he) >= self.fed - 1 and held.on_screen)
                progress(30, N)                                  # the reading goes on under the view
            if self.moved_on:
                self.current = False         # the viewer picks another subtitle while the track is read
            return ENGLISH if self.whole else None

        def download(payload):
            self.downloads.append(dict(payload))
            path = os.path.join(folder, 'external.en.srt')
            Path(path).write_text(ENGLISH, encoding='utf-8')
            return path

        def apply_subtitle_file(path, selection=None, **kw):
            Player.streams.append(path)
            EVENTS.append(('view', os.path.basename(path), Path(path).read_text(encoding='utf-8')))
            return True

        def select_embedded(index, lang=None):
            EVENTS.append(('embedded', index, lang))
            return True

        info = {'title': 'Show', 'imdb_id': 'tt1', 'season': '1', 'episode': '1', 'is_episode': True,
                'tvshow': 'Show', 'picked_release': RELEASE}
        patches = [
            mock.patch.dict(sys.modules, mods),
            mock.patch.object(kodi_utils, 'get_setting', lambda k, d='': settings.get(k, d)),
            mock.patch.object(kodi_utils, 'get_bool', lambda k, d=False: bools.get(k, d)),
            mock.patch.object(kodi_utils, 'get_int', lambda k, d=0: d),
            mock.patch.object(kodi_utils, 'get_float', lambda k, d=0.0: d),
            mock.patch.object(kodi_utils, 'notify', lambda *a, **k: None),
            mock.patch.object(kodi_utils, 'log', lambda m, level='DEBUG': self.log.append(m)),
            mock.patch.object(kodi_utils, 'cache_dir', lambda: folder),
            mock.patch.object(kodi_utils, 'addon_profile_path', lambda: folder),
            mock.patch.object(kodi_utils, 'subtitle_selection_matches', lambda *a, **k: self.current),
            mock.patch.object(kodi_utils, 'current_video_info', lambda: dict(info)),
            mock.patch.object(kodi_utils, 'apply_subtitle_file', apply_subtitle_file),
            mock.patch.object(kodi_utils, 'mark_subtitle_delivery_applied', lambda *a, **k: None),
            mock.patch.object(kodi_utils, 'confirm_subtitle_sync_fix', lambda *a, **k: None),
            mock.patch.object(kodi_utils, 'hebrew_subtitle_wanted', lambda *a, **k: True),
            mock.patch.object(t, 'pool', None),
            mock.patch.object(t, '_embedded_translation_policy', lambda: {
                'enabled': True, 'mode': 'direct', 'try_align': False, 'try_extract': True, 'allow_http': True}),
            mock.patch.object(t, '_embedded_steps', embedded_steps),
            mock.patch.object(t, '_playing_video_url', lambda info: 'https://cdn.example/film.mkv'),
            mock.patch.object(mods['resources.lib.embedded_extract'], 'extract_srt', extract_srt),
            mock.patch.object(mods['resources.lib.subs_engine_bridge'], 'select_embedded', select_embedded),
            mock.patch.object(mods['resources.lib.subs_engine_bridge'], 'download', download),
            mock.patch.object(mods['resources.lib.subsync'], '_oracle_candidates',
                              lambda info, **k: [dict(c) for c in self.externals]),
            mock.patch.object(mods['resources.lib.subsync'], 'playing_release', lambda info: RELEASE),
            mock.patch.object(t, '_sync_hebrew_delivery', lambda info, path, **k: path),
            mock.patch.object(t, '_title_cast', lambda info, imdb, s, e: ([], 'Show', '2020')),
            mock.patch.object(t, '_gemini_rate_gate', lambda interval: None),
            mock.patch.object(t.gemini, 'generate', generate),
            mock.patch.object(mods['resources.lib.google_translate'], '_translate_chunk', no_google),
        ]
        for p in patches:
            p.start()
        try:
            link = t._encode_link({'type': 'embedded_ai', 'src_lang': 'en', 'stream_index': 0})
            selection = {'token': 'tok', 'link_hash': 'lh', 'stream_hash': 'sh'}
            if self.handler:
                spec = importlib.util.spec_from_file_location('default_steps_resolve', ADDON / 'default.py')
                default = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(default)
                b64 = lambda s: base64.b64encode(s.encode('utf-8')).decode('ascii')
                default._handle_bg_translate_picker({
                    'link_b64': b64(link), 'source_id_b64': b64(''),
                    'selection_b64': default._encode_selection_b64(selection)})
            else:
                # the on-play pick: autosub_service calls resolve() with no handler and applies what it returns
                self.result = t.resolve(link, dict(info), selection=selection)
            for root, _dirs, files in os.walk(folder):
                for name in files:
                    if os.sep + 'translated' in root and name.endswith('.he.srt'):
                        self.saved = Path(root, name).read_text(encoding='utf-8')
            self.left = sorted(name for name in os.listdir(folder) if name.endswith('.he.srt'))
        finally:
            for p in reversed(patches):
                p.stop()
            if not self.folder:
                shutil.rmtree(folder, True)
        return self

    # -- what happened

    def of(self, kind):
        return [e for e in EVENTS if e[0] == kind]

    def full_job_requests(self):
        return sorted(r for r in self.sent if r[1] != 'step')

    def logged(self, needle):
        return [m for m in self.log if needle in m]


class EmbeddedPick(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mods = _load()
        # the same film with no view at all: what "the full job as before" means
        cls.plain = Job(cls.mods, views=False).run()
        cls.plain_views = [e for e in EVENTS if e[0] == 'view']
        cls.plain_finals = [e for e in EVENTS if e[0] == 'final']
        cls.job = Job(cls.mods).run()
        cls.job_events = list(EVENTS)

    def events(self, kind):
        return [e for e in self.job_events if e[0] == kind]

    def test_the_extraction_is_handed_the_steps_and_they_get_the_cue_times_and_a_window(self):
        job = self.job
        steps = job.extract_kwargs.get('steps') or ()
        self.assertEqual(len(steps), 4)
        # the 4th asks whether the viewer jumped out of the window being read
        self.assertEqual(getattr(steps[3], '__func__', None), type(job.steps[0]).moved)
        self.assertEqual(job.timelines, [STARTS])
        self.assertEqual(job.spans, [(0, STARTS[50] + 1)])           # 2.5 minutes from the viewer's place

    def test_views_reach_the_player_before_the_whole_track_is_translated(self):
        views = self.events('view')
        self.assertIn('תצוגה 20', views[0][2])
        self.assertNotIn('שורה בעברית', views[0][2])
        self.assertEqual(views[0][1], RELEASE + '.a.he.srt')

    def test_the_full_jobs_chunks_reach_the_player_with_the_views_hebrew_for_the_rest(self):
        mixed = [v for v in self.events('view') if 'שורה בעברית מספר 1.' in v[2] and 'תצוגה 55' in v[2]]
        self.assertTrue(mixed, [v[2][:80] for v in self.events('view')])
        self.assertNotIn('Where are you going', mixed[0][2].split('\n\n')[55])

    def test_the_finished_translation_reaches_the_player_and_is_the_one_saved(self):
        finals = self.events('final')
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0][1], RELEASE + '.he.srt')
        self.assertIn('שורה בעברית מספר 60.', finals[0][2])
        self.assertTrue(self.job.saved)
        self.assertEqual(finals[0][2], self.job.saved)

    def test_no_view_text_is_in_what_is_saved(self):
        self.assertNotIn('תצוגה', self.job.saved)
        self.assertNotIn('תצוגה', self.events('final')[0][2])

    def test_the_full_job_asks_for_everything_it_asks_for_without_views(self):
        # the residual repair of the cue left in English, and the gender proofread, were skipped after a view
        plain, job = self.plain.full_job_requests(), self.job.full_job_requests()
        self.assertTrue(any(kind == 'repair' for _m, kind in plain), plain)
        self.assertTrue(any(kind == 'proofread' for _m, kind in plain), plain)
        self.assertEqual(job, plain)

    def test_and_saves_the_same_translation(self):
        self.assertTrue(self.plain.saved)
        self.assertEqual(self.job.saved, self.plain.saved)

    def test_the_views_stop_when_the_whole_track_is_in(self):
        steps = self.job.steps[0]
        self.assertTrue(steps._closed)
        self.assertTrue(steps._stop.is_set())
        self.assertGreaterEqual(sum(1 for _m, kind in self.job.sent if kind == 'step'), 1)

    def test_no_progress_bar_over_the_view(self):
        # the handler closes the bar on every view; a tick that opened it again made it blink
        bars = [i for i, e in enumerate(self.job_events) if e[0] == 'bar']
        first_view = next(i for i, e in enumerate(self.job_events) if e[0] == 'view')
        self.assertEqual(len(bars), 1)
        self.assertLess(bars[0], first_view)

    def test_the_embedded_track_is_not_touched_when_all_goes_well(self):
        self.assertEqual(self.events('embedded'), [])

    def test_without_a_view_the_job_is_the_old_one(self):
        self.assertFalse(self.plain.steps[0].shown)
        self.assertEqual(len(self.plain_finals), 1)
        self.assertTrue(all('תצוגה' not in v[2] for v in self.plain_views))

    def test_the_view_files_are_gone_once_the_finished_file_is_on(self):
        self.assertNotIn(RELEASE + '.a.he.srt', self.job.left)
        self.assertNotIn(RELEASE + '.b.he.srt', self.job.left)
        self.assertIn(RELEASE + '.he.srt', self.job.left)


class WholeTrackIn(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mods = _load()

    def test_the_lines_the_last_pass_read_are_shown_before_the_full_job_reaches_them(self):
        # 20 of 60 cues were in a view; the rest came with the complete pass. The handler does not show the
        # full job's first_ready, so without one more view they would wait for the first translated chunk.
        job = Job(self.mods, fed=20).run()
        whole = [v for v in job.of('view') if 'Leave him alone, please. 60' in v[2]]
        self.assertTrue(whole)
        self.assertIn('תצוגה 20', whole[0][2])
        self.assertNotIn('שורה בעברית', whole[0][2])
        self.assertEqual(job.of('embedded'), [])


class OpenedFromTheCache(unittest.TestCase):
    """The film was translated before; its proofread got no answer then. The embedded pick reads the track
    again (views on the way) and finds the saved translation: the proofread is asked for again."""

    @classmethod
    def setUpClass(cls):
        cls.mods = _load()
        cls.first = tempfile.mkdtemp(prefix='steps_cached_a_')
        cls.second = tempfile.mkdtemp(prefix='steps_cached_b_')
        Job(cls.mods, views=False, folder=cls.first).run()
        for root, _dirs, files in os.walk(cls.first):
            for name in files:
                if name.endswith('.gp.try') or name == 'gp_later.json':
                    os.remove(os.path.join(root, name))      # the wait before a proofread is asked for again is over
        shutil.rmtree(cls.second)
        shutil.copytree(cls.first, cls.second)
        cls.plain = Job(cls.mods, views=False, folder=cls.first).run()
        cls.plain_finals = [e for e in EVENTS if e[0] == 'final']
        cls.job = Job(cls.mods, folder=cls.second).run()
        cls.job_events = list(EVENTS)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.first, True)
        shutil.rmtree(cls.second, True)

    def test_it_is_a_cache_hit(self):
        self.assertFalse(any(kind == 'chunk' for _m, kind in self.plain.sent), self.plain.sent)
        self.assertFalse(any(kind == 'chunk' for _m, kind in self.job.sent), self.job.sent)
        self.assertTrue(any(e[0] == 'view' for e in self.job_events))

    def test_the_proofread_is_asked_for_after_views_as_it_is_without_them(self):
        plain, job = self.plain.full_job_requests(), self.job.full_job_requests()
        self.assertTrue(any(kind == 'proofread' for _m, kind in plain), plain)
        self.assertEqual(job, plain)

    def test_the_saved_translation_reaches_the_player(self):
        finals = [e for e in self.job_events if e[0] == 'final']
        self.assertEqual(len(finals), len(self.plain_finals))
        self.assertTrue(finals)
        self.assertIn('שורה בעברית מספר 60.', finals[-1][2])


class BusyAtTheEnd(unittest.TestCase):
    """The default model answers busy just as the whole track comes in: its retry is not sent."""

    @classmethod
    def setUpClass(cls):
        cls.mods = _load()

    def test_no_retry_after_the_reading_is_over(self):
        t = self.mods['resources.lib.translate']
        made = []
        real = t._embedded_steps

        def capture(*a, **k):
            steps = real(*a, **k)
            made.append(steps)
            return steps
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            made[0]._stop.set()                  # finish() lands during the five seconds
        sent = []

        def generate(**kw):
            sent.append(kw.get('timeout'))
            raise t.gemini.OverloadError('503')
        kodi_utils = self.mods['resources.lib.kodi_utils']
        with mock.patch.dict(sys.modules, self.mods), \
                mock.patch.object(t, '_embedded_steps', capture), \
                mock.patch.object(t, '_playing_video_url', lambda info: 'https://cdn.example/film.mkv'), \
                mock.patch.object(t, '_title_cast', lambda info, imdb, s, e: ([], 'Show', '2020')), \
                mock.patch.object(t, '_gemini_rate_gate', lambda interval: None), \
                mock.patch.object(t.gemini, 'generate', generate), \
                mock.patch.object(t.time, 'sleep', sleep), \
                mock.patch.object(kodi_utils, 'get_setting', lambda k, d='': {
                    'api_key': 'KEY', 'translation_mode': 'ai'}.get(k, d)), \
                mock.patch.object(kodi_utils, 'get_bool', lambda k, d=False: d), \
                mock.patch.object(kodi_utils, 'get_int', lambda k, d=0: d), \
                mock.patch.object(kodi_utils, 'get_float', lambda k, d=0.0: d), \
                mock.patch.object(kodi_utils, 'log', lambda *a, **k: None):
            steps = t._embedded_steps({'title': 'Show'}, 'en', lambda text: None, lambda: False)
            self.assertIsNotNone(steps)
            got = steps._translate(t.srt.parse_blocks(ENGLISH)[:3], [])
        self.assertEqual(sleeps, [5])
        self.assertEqual(len(sent), 1)
        self.assertIsNone(got)


class NoTranslator(unittest.TestCase):
    """No Gemini key, or Google as the translator: no view can come, so the track is read in one pass."""

    @classmethod
    def setUpClass(cls):
        cls.mods = _load()

    def test_read_in_one_pass(self):
        t = self.mods['resources.lib.translate']
        job = Job(self.mods, views=False)
        with mock.patch.object(t, '_steps_translator', lambda info, lang, cancelled: None):
            job.run()
        self.assertEqual(job.steps, [None])
        self.assertIsNone(job.extract_kwargs.get('steps'))
        self.assertEqual(len(job.of('final')), 1)


class GivenUp(unittest.TestCase):
    """The extraction is interrupted after a view was shown."""

    @classmethod
    def setUpClass(cls):
        cls.mods = _load()

    def test_the_embedded_track_goes_back_on_screen(self):
        # the view holds 20 of 60 cues; before 0.3.80 the embedded track stayed on screen through a failure
        job = Job(self.mods, whole=False, fed=20).run()
        self.assertTrue(job.of('view'))
        self.assertEqual(job.of('embedded'), [('embedded', 0, 'en')])
        self.assertEqual(EVENTS[-1][0], 'embedded')
        self.assertEqual(job.of('final'), [])
        self.assertFalse(any(kind == 'chunk' for _m, kind in job.sent))

    def test_not_when_the_viewer_has_chosen_another_subtitle_since(self):
        job = Job(self.mods, whole=False, fed=20, moved_on=True).run()
        self.assertTrue(job.of('view'))
        self.assertEqual(job.of('embedded'), [])

    def test_nothing_is_put_back_when_no_view_was_shown(self):
        job = Job(self.mods, views=False, whole=False, fed=20).run()
        self.assertEqual([e for e in EVENTS if e[0] != 'bar'], [])

    def test_the_on_play_pick_has_no_embedded_track_to_put_back(self):
        job = Job(self.mods, whole=False, fed=20, handler=False).run()
        self.assertTrue(job.of('view'))
        self.assertEqual(job.of('embedded'), [])
        self.assertIsNone(job.result)


class OnPlayPick(unittest.TestCase):
    """autosub_service: resolve() with no handler."""

    @classmethod
    def setUpClass(cls):
        cls.mods = _load()
        cls.job = Job(cls.mods, handler=False).run()
        cls.events = list(EVENTS)

    def test_the_views_go_to_the_player_from_inside_the_job(self):
        views = [e for e in self.events if e[0] == 'view']
        self.assertTrue(views)
        self.assertIn('תצוגה 20', views[0][2])
        self.assertEqual({v[1] for v in views} - {RELEASE + '.a.he.srt', RELEASE + '.b.he.srt'}, set())

    def test_the_job_returns_the_finished_translation_for_the_service_to_apply(self):
        self.assertTrue(self.job.result)
        self.assertIn('שורה בעברית מספר 60.', self.job.saved)
        self.assertNotIn('תצוגה', self.job.saved)

    def test_no_watcher_and_no_embedded_track_switch(self):
        self.assertIsNone(self.job.steps[0]._watcher)
        self.assertEqual([e for e in self.events if e[0] == 'embedded'], [])


if __name__ == '__main__':
    unittest.main()


class NoIndex(unittest.TestCase):
    """A file whose index has no entry for the subtitle lines: over a stream they cannot be found short of
    reading the whole film (QA 14 Nov 2026: Inception 2010 HURTOM BDRip on TorBox; the pick ended in "could
    not extract"). The owner: do not hide the row -- fix it. The external subtitle that best matches the
    release is translated instead, as its own "AI translation" row would be."""

    @classmethod
    def setUpClass(cls):
        cls.mods = _load()

    def test_the_external_subtitle_for_the_release_is_translated_instead(self):
        job = Job(self.mods, views=False, whole=False, noindex=True).run()
        self.assertEqual([d.get('filename') for d in job.downloads], [RELEASE])     # the best match, English
        self.assertEqual(job.downloads[0].get('type'), 'engine_ai')
        finals = job.of('final')
        self.assertTrue(finals, job.log[-12:])
        self.assertIn('שורה בעברית', finals[-1][2])
        self.assertTrue(job.logged('cannot be read from the stream'))
        self.assertFalse(job.logged('deferring to the external path'))

    def test_the_picked_language_comes_first_then_english(self):
        externals = [{'release': RELEASE, 'language': 'en', 'payload': {'type': 'engine', 'filename': 'EN', 'id': 'e'}},
                     {'release': RELEASE, 'language': 'fr', 'payload': {'type': 'engine', 'filename': 'FR', 'id': 'f'}}]
        job = Job(self.mods, views=False, whole=False, noindex=True, externals=externals)
        job.run()
        self.assertEqual([d.get('filename') for d in job.downloads], ['EN'])
        job = Job(self.mods, views=False, whole=False, noindex=True, externals=externals[1:])
        job.run()
        self.assertEqual(job.downloads, [])                                  # no English: nothing to translate from
        self.assertTrue(job.logged('deferring to the external path'))

    def test_with_no_external_subtitle_it_ends_as_before(self):
        job = Job(self.mods, views=False, whole=False, noindex=True, externals=[]).run()
        self.assertEqual(job.downloads, [])
        self.assertTrue(job.logged('deferring to the external path'))

    def test_any_other_failure_ends_as_before(self):
        # a reading given up (a provider pushing back, the viewer gone): not the case for an external
        job = Job(self.mods, views=False, whole=False, noindex=False).run()
        self.assertEqual(job.downloads, [])
        self.assertTrue(job.logged('deferring to the external path'))

class NoIndexChoice(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mods = _load()

    def test_no_external_for_a_pick_already_replaced(self):
        job = Job(self.mods, views=False, whole=False, noindex=True, moved_on=True).run()
        self.assertEqual(job.downloads, [])
        self.assertTrue(job.logged('deferring to the external path'))

    def test_the_best_match_wins_across_the_picked_language_and_english(self):
        t = self.mods['resources.lib.translate']
        sub = self.mods['resources.lib.subsync']
        rm = self.mods['resources.lib.release_match']
        cands = [{'release': 'Film.2010.720p.HDTV-X', 'language': 'fr',
                  'payload': {'type': 'engine', 'filename': 'FR-poor'}},
                 {'release': RELEASE, 'language': 'en', 'payload': {'type': 'engine', 'filename': 'EN-exact'}},
                 {'release': RELEASE, 'language': 'de', 'payload': {'type': 'engine', 'filename': 'DE-exact'}}]
        with mock.patch.dict(sys.modules, self.mods), \
                mock.patch.object(sub, '_oracle_candidates', lambda info, **k: cands), \
                mock.patch.object(sub, 'playing_release', lambda info: RELEASE), \
                mock.patch.object(rm, 'match_pct', lambda a, b: 100 if b == RELEASE else 20):
            got = t._external_for_unreadable_embedded({}, 'fr')
            tie = t._external_for_unreadable_embedded({}, 'en')
        self.assertEqual((got['filename'], got['src_lang'], got['type']), ('EN-exact', 'en', 'engine_ai'))
        self.assertEqual(tie['filename'], 'EN-exact')                 # German is neither language
