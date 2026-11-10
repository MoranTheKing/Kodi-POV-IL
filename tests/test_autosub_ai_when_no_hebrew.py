"""What the automatic subtitle does when there is no Hebrew at all (0.3.74):
translate with AI as before ('auto'), ask each time ('ask': a yes/no that
closes itself as a 'no'), or leave it to a pick from the list ('manual').
A user asked to decide per video: a translation costs requests, and the best
foreign subtitle may not fit the release's timing."""

import importlib.util
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'service.subtitles.kodipovilai/resources/lib/autosub_service.py'


def ai_mode(value):
    spec = importlib.util.spec_from_file_location('autosub_ai_mode_only', MODULE)
    module = importlib.util.module_from_spec(spec)
    xbmc = types.ModuleType('xbmc')
    xbmc.Player = object
    with patch.dict(sys.modules, {'xbmc': xbmc}):
        spec.loader.exec_module(module)
    kodi = types.SimpleNamespace(get_setting=lambda name, default='': value)
    return module.ai_when_no_hebrew(kodi)


def run_autosub(mode, answer=None, key='k', rows=None, fail=(), translation='ai'):
    """One automatic on-play run with no Hebrew candidate. Returns what was
    resolved, whether the question was asked (and how), and the last overlay."""
    current = {'file': 'film.mkv', 'link': '', 'token': 0}
    resolved, asked, applied = [], [], []

    class Player:
        def getPlayingFile(self):
            return current['file']

        def isPlayingVideo(self):
            return True

        def getTotalTime(self):
            return 90.0

        def getAvailableSubtitleStreams(self):
            return ['eng']

    class Dialog:
        def yesno(self, heading, message, nolabel='', yeslabel='', autoclose=0, defaultbutton=None):
            asked.append({'heading': heading, 'message': message, 'autoclose': autoclose,
                          'yes': yeslabel, 'no': nolabel, 'default': defaultbutton})
            return answer

    xbmc = types.ModuleType('xbmc')
    xbmc.Player = Player
    xbmc.sleep = lambda ms: time.sleep(0.001)
    xbmc.getInfoLabel = lambda name: ''
    xbmcgui = types.ModuleType('xbmcgui')
    xbmcgui.Window = lambda ident: types.SimpleNamespace(getProperty=lambda name: '')
    xbmcgui.Dialog = Dialog
    xbmcgui.DLG_YESNO_NO_BTN = 10

    settings = {'api_key': key, 'translation_mode': translation, 'ai_when_no_hebrew': mode}
    kodi = types.ModuleType('resources.lib.kodi_utils')
    kodi.get_bool = lambda name, default=False: False if name == 'engine_force_translate' else True
    kodi.hebrew_subtitle_wanted = lambda: True
    kodi.get_setting = lambda name, default='': settings.get(name, default)
    kodi.current_video_info = lambda: {'filepath': current['file'], 'imdb_id': 'tt1', 'title': 'T'}
    kodi.get_subtitle_selection_token = lambda: str(current['token'])

    def set_current(link):
        # as kodi_utils: the same link keeps its selection token
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
    kodi.log = lambda *args, **kwargs: None

    translate = types.ModuleType('resources.lib.translate')
    translate.list_candidates = lambda info, modal_progress=False: list(
        rows if rows is not None else [{'language': 'en', 'link': 'ai-1', 'filename': 'Film.en'}])
    kinds = {'ai-': 'engine_ai', 'emb-': 'embedded_ai', 'loc-': 'ai', 'he-': 'engine'}
    translate._decode_link = lambda link: {'type': next(
        (v for k, v in kinds.items() if link.startswith(k)), 'engine')}
    translate.set_quiet = lambda quiet: None

    def resolve(link, info, selection=None, **kwargs):
        resolved.append(link)
        return None if link in fail else link + '.he.srt'

    translate.resolve = resolve
    translate.proofread_later = lambda link, selection: None
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
        spec = importlib.util.spec_from_file_location('autosub_ai_mode_test', MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        overlays = []
        real_sleep = time.sleep
        with patch.object(module.time, 'sleep', lambda s: real_sleep(0)):
            # every overlay the run writes ends in general.show_msg; keep them all
            class Gen(types.ModuleType):
                def __setattr__(self, name, value):
                    if name == 'show_msg':
                        overlays.append(value)
                    super().__setattr__(name, value)
            general.__class__ = Gen
            module.autosub_on_play()
    return {'resolved': resolved, 'asked': asked, 'applied': applied,
            'overlays': [o for o in overlays if o]}


class AiWhenNoHebrew(unittest.TestCase):

    def test_auto_translates_as_before(self):
        r = run_autosub('auto')
        self.assertEqual(r['resolved'], ['ai-1'])
        self.assertEqual(r['asked'], [])
        self.assertEqual(r['applied'], ['ai-1.he.srt'])

    def test_ask_and_yes_translates(self):
        r = run_autosub('ask', answer=True)
        self.assertEqual(len(r['asked']), 1)
        self.assertEqual(r['asked'][0]['autoclose'], 10000)
        self.assertEqual(r['asked'][0]['default'], 10)       # 'no' has the focus
        self.assertEqual(r['resolved'], ['ai-1'])

    def test_ask_and_no_or_timeout_translates_nothing(self):
        for answer in (False, None):
            r = run_autosub('ask', answer=answer)
            self.assertEqual(len(r['asked']), 1)
            self.assertEqual(r['resolved'], [])
            self.assertTrue(any('תרגום AI זמין ברשימת הכתוביות' in o for o in r['overlays']), r['overlays'])

    def test_manual_never_asks_and_never_translates(self):
        r = run_autosub('manual')
        self.assertEqual(r['asked'], [])
        self.assertEqual(r['resolved'], [])
        self.assertTrue(any('תרגום AI זמין ברשימת הכתוביות' in o for o in r['overlays']), r['overlays'])

    def test_ask_without_a_key_or_a_translation_asks_nothing(self):
        self.assertEqual(run_autosub('ask', answer=True, key='')['asked'], [])
        r = run_autosub('ask', answer=True, rows=[])
        self.assertEqual(r['asked'], [])
        self.assertEqual(r['resolved'], [])

    def test_an_unknown_value_is_auto(self):
        for value in ('sometimes', '', None):
            self.assertEqual(ai_mode(value), 'auto')
        self.assertEqual(ai_mode('ASK '), 'ask')
        r = run_autosub('sometimes')
        self.assertEqual(r['resolved'], ['ai-1'])


EMB = {'language': 'he', 'link': 'emb-1', 'filename': 'embedded en -> he (AI)'}
LOC = {'language': 'he', 'link': 'loc-1', 'filename': 'AI Hebrew (local en)'}
HUMAN = {'language': 'he', 'link': 'he-1', 'filename': 'Film.heb'}
ENG = {'language': 'en', 'link': 'ai-1', 'filename': 'Film.en'}


class AiRowsListedAsHebrew(unittest.TestCase):
    """The translation of the video's own foreign track, or of a foreign file
    beside it, is listed among the Hebrew rows: outside 'auto' it waits too."""

    def test_auto_still_takes_the_embedded_translation(self):
        r = run_autosub('auto', rows=[EMB, ENG])
        self.assertEqual(r['resolved'], ['emb-1'])
        self.assertEqual(r['asked'], [])

    def test_manual_translates_none_of_them(self):
        r = run_autosub('manual', rows=[EMB, LOC, ENG])
        self.assertEqual(r['resolved'], [])
        self.assertEqual(r['asked'], [])
        self.assertTrue(any('תרגום AI זמין ברשימת הכתוביות' in o for o in r['overlays']), r['overlays'])

    def test_ask_no_translates_none_and_asks_once(self):
        r = run_autosub('ask', answer=False, rows=[EMB, LOC, ENG])
        self.assertEqual(r['resolved'], [])
        self.assertEqual(len(r['asked']), 1)

    def test_ask_yes_takes_the_embedded_translation_first(self):
        r = run_autosub('ask', answer=True, rows=[EMB, ENG])
        self.assertEqual(r['resolved'], ['emb-1'])
        self.assertEqual(len(r['asked']), 1)

    def test_a_real_hebrew_subtitle_goes_first_and_asks_nothing(self):
        r = run_autosub('ask', answer=True, rows=[EMB, HUMAN, ENG])
        self.assertEqual(r['resolved'], ['he-1'])
        self.assertEqual(r['asked'], [])

    def test_when_the_real_one_fails_the_question_comes_once(self):
        r = run_autosub('ask', answer=True, rows=[HUMAN, EMB, ENG], fail=('he-1', 'emb-1'))
        self.assertEqual(r['resolved'], ['he-1', 'emb-1', 'ai-1'])
        self.assertEqual(len(r['asked']), 1)

    def test_no_hint_without_a_key(self):
        r = run_autosub('manual', key='', rows=[EMB, ENG])
        self.assertEqual(r['resolved'], [])
        self.assertFalse(any('תרגום AI זמין' in o for o in r['overlays']), r['overlays'])

    def test_google_mode_says_google(self):
        r = run_autosub('ask', answer=False, rows=[ENG], translation='google')
        self.assertIn('Google Translate', r['asked'][0]['message'])


if __name__ == '__main__':
    unittest.main()
