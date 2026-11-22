"""MoranSubs 0.3.111: the video's own subtitle whose index did not answer this time.

A viewer on Real-Debrid, Nov 2026, twice: "it says it found no translation, and there were built-in ones" and "if it
fails to extract, it should go on to another subtitle and translate it -- otherwise I have to pick by hand". His
log: the reading of the English track (S_TEXT/UTF8) gave up 2.5 s after the start, with nothing in the log after the
head -- the read of the SeekHead that lists the index came back empty -- while the player was still filling its
buffer, and the run ended with "no Hebrew subtitle". The same release reads whole in the QA Kodi (TorBox, 1699
lines in 9 s). Now:
  * the read that came back empty says what it was answered (HTTP status, error, or standing aside);
  * an index that did not answer is 'index_unread' (not 'no_index', not unknown): the caller translates a matching
    external subtitle instead, as for the other unreadable kinds;
  * the automatic pick reads it once more by itself once the film has played on steadily.
"""
import importlib.util
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.path.insert(0, str(TESTS))
import test_embedded_seekhead_chain as chain  # noqa: E402
from test_autosub_ai_when_no_hebrew import MODULE as AUTOSUB  # noqa: E402

TRANSLATE = ROOT / 'service.subtitles.kodipovilai/resources/lib/translate.py'


class Answered(chain.FakeSource):
    """A source over HTTP whose reads at `dead` come back empty (or as `body`), answered `answer`."""

    def __init__(self, data, dead=(), answer='', body=b''):
        super().__init__(data)
        self.dead, self.answer, self.body = set(dead), answer, body
        self.tripped = False
        self._stats = {}
        self.last_answer = ''

    def read(self, offset, length):
        self.reads.append((offset, length))
        if offset in self.dead:
            self.last_answer = self.answer
            return self.body
        self.last_answer = 'HTTP 206'
        return self.data[offset:offset + length]


class IndexUnread(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ee = chain.load()

    def head(self, src):
        seg_start, _ts, _tracks, seeks = self.ee._parse_head(src, len(src.data), lambda m: None)
        return seg_start, seeks

    def test_a_seekhead_that_did_not_answer_says_why_and_is_index_unread(self):
        data, seg, pos = chain.build()
        src = Answered(data, dead={seg + pos['sh3']}, answer='HTTP 200 for a range (the whole file)')
        seg_start, seeks = self.head(src)
        said = []
        ok = self.ee._extract_cues(src, seeks, seg_start, 1, [], 0, 90.0, 0.0, None, said.append)
        self.assertFalse(ok)
        self.assertEqual(src._stats.get('why'), 'index_unread')
        self.assertTrue(any('did not answer (HTTP 200 for a range' in m for m in said), said)
        self.assertTrue(any('could not be read this time (HTTP 200' in m for m in said), said)

    def test_an_index_that_did_not_answer(self):
        data, seg, pos = chain.build(chain=False)
        src = Answered(data, dead={seg + pos['cues']}, answer='ConnectionError')
        seg_start, seeks = self.head(src)
        said = []
        self.assertEqual(self.ee._read_cues(src, seeks, seg_start, 1, said.append), ([], False))
        self.assertTrue(src._cues_unsure)
        self.assertTrue(any('the index did not answer (ConnectionError)' in m for m in said), said)
        src._cues_unsure = False
        self.ee._extract_cues(src, seeks, seg_start, 1, [], 0, 90.0, 0.0, None, said.append)
        self.assertEqual(src._stats.get('why'), 'index_unread')

    def test_an_error_page_where_the_index_is(self):
        data, seg, pos = chain.build(chain=False)
        src = Answered(data, dead={seg + pos['cues']}, answer='HTTP 403', body=b'<html>Forbidden</html>')
        seg_start, seeks = self.head(src)
        said = []
        self.assertFalse(self.ee._extract_cues(src, seeks, seg_start, 1, [], 0, 90.0, 0.0, None, said.append))
        self.assertEqual(src._stats.get('why'), 'index_unread')
        self.assertTrue(any('no index where the SeekHead points (HTTP 403)' in m for m in said), said)

    def test_standing_aside_for_the_player_is_said_too(self):
        data, seg, pos = chain.build()
        src = Answered(data, dead={seg + pos['sh3']}, answer='stood aside for the player')
        seg_start, seeks = self.head(src)
        src.tripped = True
        said = []
        self.ee._extract_cues(src, seeks, seg_start, 1, [], 0, 90.0, 0.0, None, said.append)
        self.assertEqual(src._stats.get('why'), 'index_unread')
        self.assertTrue(any('stood aside for the player, stood aside' in m for m in said), said)

    def test_a_file_with_no_index_is_still_no_index(self):
        data, seg, pos = chain.build()
        src = Answered(b'\x00' * seg + chain.seekhead([(chain.TAGS, 0)]))
        said = []
        ok = self.ee._extract_cues(src, {self.ee._SEEKHEAD: seg}, seg, 1, [], 0, 90.0, 0.0, None, said.append)
        self.assertFalse(ok)
        self.assertEqual(src._stats.get('why'), 'no_index')

    def test_a_fault_of_the_file_itself_keeps_no_reason(self):
        # the same on every read: not 'index_unread', so nothing waits to read it again (review of 0.3.111)
        data, seg, pos = chain.build(chain=False)
        src = Answered(data)                              # every read answered whole (206)
        seg_start, seeks = self.head(src)
        seeks[self.ee._CUES] = seg + pos['info']          # something else where the index should be
        said = []
        self.assertFalse(self.ee._extract_cues(src, seeks, seg_start, 1, [], 0, 90.0, 0.0, None, said.append))
        self.assertNotIn('why', src._stats)
        self.assertTrue(any('no index where the SeekHead points (HTTP 206)' in m for m in said), said)
        src = Answered(data)
        seg_start, seeks = self.head(src)
        with patch.object(self.ee, '_CUES_CAP', 8):       # an index too large to read
            self.assertFalse(self.ee._extract_cues(src, seeks, seg_start, 1, [], 0, 90.0, 0.0, None, said.append))
        self.assertNotIn('why', src._stats)
        self.assertTrue(any('too large' in m for m in said), said)

    def test_an_index_cut_short_is_index_unread(self):
        data, seg, pos = chain.build(chain=False)
        src = Answered(data)
        real = src.read
        at = seg + pos['cues']
        # the index's first piece comes back short, and the rest of it does not come at all
        src.read = lambda offset, length: (real(offset, length)[:20] if offset == at
                                           else b'' if at < offset < at + 4096 else real(offset, length))
        seg_start, seeks = self.head(src)
        said = []
        self.assertFalse(self.ee._extract_cues(src, seeks, seg_start, 1, [], 0, 90.0, 0.0, None, said.append))
        self.assertEqual(src._stats.get('why'), 'index_unread')
        self.assertTrue(any('truncated' in m for m in said), said)

    def test_a_local_file_with_no_index_says_nothing_new(self):
        data, seg, pos = chain.build(chain=False)
        src = Answered(data)
        src.is_http = False
        src._stats = None
        seg_start, seeks = self.head(src)
        seeks[self.ee._CUES] = seg + pos['info']          # not the index there
        said = []
        self.assertEqual(self.ee._read_cues(src, seeks, seg_start, 1, said.append), ([], False))
        self.assertFalse(getattr(src, '_cues_unsure', False))

    def test_the_read_layer_keeps_the_answer(self):
        ee = self.ee

        class Resp(object):
            def __init__(self, code, body=b''):
                self.status_code, self.headers = code, {}
                self.raw = types.SimpleNamespace(read=lambda n, b=[body]: b.pop() if b else b'')

            def close(self):
                pass

        class Sess(object):
            def __init__(self, answer):
                self.answer = answer

            def get(self, *a, **k):
                if isinstance(self.answer, Exception):
                    raise self.answer
                return self.answer

        src = ee._Source.__new__(ee._Source)
        src.url, src.is_http, src._abort_cb, src._stats, src._log = 'http://example.invalid/x.mkv', True, None, None, None
        src._lock, src.http_reqs, src.fetched, src.last_answer = threading.RLock(), 0, 0, ''
        src._429_streak = src._clean_streak = 0
        src._pace = src._pace_floor = ee._HTTP_REQ_PACE_S
        self.assertEqual(src._read_session_inner(Sess(Resp(200, b'xx')), 100, 2, False), b'')
        self.assertEqual(src.last_answer, 'HTTP 200 for a range (the whole file)')
        self.assertEqual(src._read_session_inner(Sess(ConnectionError('down')), 100, 2, False), b'')
        self.assertEqual(src.last_answer, 'ConnectionError')
        self.assertEqual(src._read_session_inner(Sess(Resp(206, b'ab')), 100, 2, False), b'ab')
        self.assertEqual(src.last_answer, 'HTTP 206')


class TheCallerTranslatesAnotherSubtitle(unittest.TestCase):
    def test_index_unread_is_among_the_reasons_for_a_matching_external_subtitle(self):
        text = TRANSLATE.read_text(encoding='utf-8')
        at = text.index("if (_emb_why.get('reason') in ('no_index', 'no_text', 'not_mkv',")
        self.assertIn("'index_unread')", text[at:at + 140])
        self.assertIn('לא הצלחתי לקרוא מהסטרים הפעם', text)


# ---------------------------------------------------------------- the automatic pick
def run(rows, fail_first=(), fail_always=(), steady=True, reason='index_unread'):
    """One automatic run (no Hebrew). `fail_first`: links whose first resolve gives nothing; `fail_always`: every
    resolve. The embedded pick's miss is reported as `reason`. `steady`: the film plays on (else it is paused)."""
    current = {'file': 'film.mkv', 'link': '', 'token': 0, 't': 0.0, 'clock': 1000.0}
    resolved, applied, overlays, logs = [], [], [], []
    misses = {}

    class Player:
        def getPlayingFile(self):
            return current['file']

        def isPlayingVideo(self):
            return True

        def getTotalTime(self):
            return 90.0

        def getAvailableSubtitleStreams(self):
            return ['eng']

        def getTime(self):
            return current['t']

    class Monitor:
        def waitForAbort(self, s):
            current['clock'] += s
            if steady:
                current['t'] += s
            return False

    xbmc = types.ModuleType('xbmc')
    xbmc.Player, xbmc.Monitor = Player, Monitor
    xbmc.sleep = lambda ms: None
    xbmc.getInfoLabel = lambda name: ''
    xbmc.getCondVisibility = lambda name: (not steady) and name == 'Player.Paused'
    xbmcgui = types.ModuleType('xbmcgui')
    xbmcgui.Window = lambda ident: types.SimpleNamespace(getProperty=lambda name: '')
    settings = {'api_key': 'k', 'translation_mode': 'ai', 'ai_when_no_hebrew': 'auto'}
    kodi = types.ModuleType('resources.lib.kodi_utils')
    kodi.get_bool = lambda name, default=False: False if name == 'engine_force_translate' else True
    kodi.hebrew_subtitle_wanted = lambda: True
    kodi.get_setting = lambda name, default='': settings.get(name, default)
    kodi.current_video_info = lambda: {'filepath': current['file'], 'imdb_id': 'tt1', 'title': 'T'}
    kodi.get_subtitle_selection_token = lambda: str(current['token'])

    def set_current(link):
        if link != current['link']:
            current['token'] += 1
        current['link'] = link

    kodi.set_current_subtitle = set_current
    kodi.current_subtitle_selection = lambda expected_link=None: {
        'token': str(current['token']), 'link_hash': current['link'], 'stream_hash': current['file']}
    kodi.subtitle_selection_matches = lambda token, link_hash, stream_hash: (
        token == str(current['token']) and link_hash == current['link'] and stream_hash == current['file'])
    kodi.apply_subtitle_file = lambda path, selection=None: applied.append(path) or True
    kodi.get_subtitle_sync_status = lambda link: {}
    kodi.log = lambda msg, *a, **k: logs.append(msg)
    translate = types.ModuleType('resources.lib.translate')
    translate.list_candidates = lambda info, modal_progress=False: list(rows)
    kinds = {'ai-': 'engine_ai', 'emb-': 'embedded_ai', 'he-': 'engine'}
    translate._decode_link = lambda link: {'type': next((v for k, v in kinds.items() if link.startswith(k)),
                                                        'engine'), 'filename': link + '.name'}
    translate.set_quiet = lambda quiet: None

    def resolve(link, info, selection=None, **kwargs):
        resolved.append(link)
        if link in fail_always or (link in fail_first and resolved.count(link) == 1):
            if link.startswith('emb-'):
                misses['at'] = current['clock']
            return None
        return link + '.he.srt'

    translate.resolve = resolve
    translate.proofread_later = lambda link, selection: None
    translate.embedded_miss_since = lambda t0, f='': reason if 'at' in misses else None
    bridge = types.ModuleType('resources.lib.subs_engine_bridge')
    bridge.ensure_engine_settings = lambda: None
    bridge._release_ready = lambda info: True
    bridge.note_playback_streams = lambda *args, **kwargs: None
    general = types.ModuleType('resources.lib.subs_engine.general')
    general.show_results = lambda *args: None
    general.show_msg = ''
    subsync = types.ModuleType('resources.lib.subsync')
    subsync.prefetch_autosub_reference = lambda info, rows: False
    subsync.rank_ready_candidates = lambda info, rows: rows
    subsync.diverse_human_alternatives = lambda rows, **_kw: []
    lib = types.ModuleType('resources.lib')
    lib.kodi_utils, lib.translate, lib.subs_engine_bridge, lib.subsync = kodi, translate, bridge, subsync
    resources = types.ModuleType('resources')
    resources.lib = lib
    engine = types.ModuleType('resources.lib.subs_engine')
    engine.general = general
    modules = {'xbmc': xbmc, 'xbmcgui': xbmcgui, 'resources': resources, 'resources.lib': lib,
               'resources.lib.kodi_utils': kodi, 'resources.lib.translate': translate,
               'resources.lib.subs_engine_bridge': bridge, 'resources.lib.subs_engine': engine,
               'resources.lib.subs_engine.general': general, 'resources.lib.subsync': subsync}
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location('autosub_index_unread_test', AUTOSUB)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class Gen(types.ModuleType):
            def __setattr__(self, name, value):
                if name == 'show_msg':
                    overlays.append(value)
                super().__setattr__(name, value)
        general.__class__ = Gen
        clock = types.SimpleNamespace(time=lambda: current['clock'], sleep=lambda s: None)
        with patch.object(module, 'time', clock):
            module.autosub_on_play()
    return {'resolved': resolved, 'applied': applied, 'overlays': [o for o in overlays if o], 'logs': logs,
            'played': current['t']}


EMB = {'language': 'he', 'link': 'emb-1', 'filename': '[מובנה] EN'}
ENG = {'language': 'en', 'link': 'ai-1', 'filename': 'Film.en'}


class AutomaticPickReadsItOnceMore(unittest.TestCase):

    def test_read_again_once_the_film_plays_steadily(self):
        r = run([EMB], fail_first={'emb-1'})
        self.assertEqual(r['resolved'], ['emb-1', 'emb-1'])
        self.assertEqual(r['applied'], ['emb-1.he.srt'])
        self.assertGreaterEqual(r['played'], 20.0)
        self.assertTrue(any('מנסה שוב בעוד רגע' in o for o in r['overlays']), r['overlays'])
        self.assertTrue(any('read the second time: yes' in m for m in r['logs']), r['logs'])

    def test_once_only(self):
        r = run([EMB], fail_always={'emb-1'})
        self.assertEqual(r['resolved'], ['emb-1', 'emb-1'])
        self.assertEqual(r['applied'], [])
        self.assertTrue(any('לא הצלחתי לקרוא מהסטרים' in o for o in r['overlays']), r['overlays'])

    def test_a_film_that_does_not_play_on_is_not_read_again(self):
        r = run([EMB], fail_first={'emb-1'}, steady=False)
        self.assertEqual(r['resolved'], ['emb-1'])
        self.assertEqual(r['applied'], [])

    def test_the_providers_subtitle_first_when_there_is_one(self):
        # a matching external subtitle is translated (as the embedded pick's own stand-in did, or this one)
        # before any second reading
        r = run([EMB, ENG], fail_first={'emb-1'})
        self.assertEqual(r['resolved'], ['emb-1', 'ai-1'])
        self.assertEqual(r['applied'], ['ai-1.he.srt'])

    def test_other_reasons_are_not_read_again(self):
        for reason in ('no_index', 'no_text', 'not_mkv', ''):
            with self.subTest(reason):
                r = run([EMB], fail_first={'emb-1'}, reason=reason)
                self.assertEqual(r['resolved'], ['emb-1'])


if __name__ == '__main__':
    unittest.main()
