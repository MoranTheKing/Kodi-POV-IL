"""The top overlay and a timing check that is still running when the subtitle
goes on screen (0.3.77).

Field question: a subtitle made for another cut loads seconds off, the fix
arrives a few seconds later -- what tells the viewer to wait?  The status line
used to leave five seconds after the load whatever the check was doing.  It
now stays until the check ends and then says how it ended; a fix is announced
by SubSync's own toast, so the overlay leaves for it."""

import importlib.util
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'service.subtitles.kodipovilai/resources/lib/autosub_service.py'

CHECKING = 'כתובית נטענה · בודק סנכרון'
CONFIRMED = 'כתובית מסונכרנת'
FIXED = 'כתובית סונכרנה אוטומטית'
NOT_VERIFIED = 'כתובית נטענה · הסנכרון לא אומת'
NOT_YET = 'כתובית נטענה · התזמון טרם אומת'


def load_module():
    spec = importlib.util.spec_from_file_location('autosub_overlay_unit', MODULE)
    module = importlib.util.module_from_spec(spec)
    xbmc = types.ModuleType('xbmc')
    xbmc.Player = object
    with patch.dict(sys.modules, {'xbmc': xbmc}):
        spec.loader.exec_module(module)
    return module


def run_autosub(states, toasts='true', pick_at=None, stop_at=None, overlay=True):
    """One automatic on-play run that applies a Hebrew subtitle.

    states: what the timing status reads, one entry per read (the last one
    repeats).  pick_at / stop_at: the viewer picks another subtitle / stops
    the video at that read.  Returns the overlay lines in order, the seconds
    slept while each was up, and the log."""
    current = {'file': 'film.mkv', 'link': '', 'token': 0, 'playing': True}
    reads = {'n': 0}
    slept = {}
    overlays = []
    log = []

    class Player:
        def getPlayingFile(self):
            return current['file']

        def isPlayingVideo(self):
            return current['playing']

        def getTotalTime(self):
            return 90.0

        def getAvailableSubtitleStreams(self):
            return ['eng']

    def sleep(ms):
        if overlays:
            slept[len(overlays) - 1] = slept.get(len(overlays) - 1, 0.0) + ms / 1000.0

    xbmc = types.ModuleType('xbmc')
    xbmc.Player = Player
    xbmc.sleep = sleep
    xbmc.getInfoLabel = lambda name: ''
    xbmcgui = types.ModuleType('xbmcgui')
    xbmcgui.Window = lambda ident: types.SimpleNamespace(getProperty=lambda name: '')

    settings = {'subs_notifications': toasts}
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
    kodi.apply_subtitle_file = lambda path, selection=None: True

    def status(link):
        index = reads['n']
        reads['n'] += 1
        if pick_at is not None and index == pick_at:
            set_current('picked-by-the-viewer')
        if stop_at is not None and index == stop_at:
            current['playing'] = False
        if link != current['link']:
            return {}
        state = states[min(index, len(states) - 1)]
        return {'state': state} if state else {}

    kodi.get_subtitle_sync_status = status
    kodi.log = lambda message, *args, **kwargs: log.append(message)

    translate = types.ModuleType('resources.lib.translate')
    translate.list_candidates = lambda info, modal_progress=False: [
        {'language': 'he', 'link': 'he-1', 'filename': 'Film.WEB-DL.heb'}]
    translate._decode_link = lambda link: {'type': 'engine'}
    translate.set_quiet = lambda quiet: None
    translate.resolve = lambda link, info, selection=None, **kwargs: link + '.srt'
    translate.proofread_later = lambda link, selection: None
    bridge = types.ModuleType('resources.lib.subs_engine_bridge')
    bridge._release_ready = lambda info: True
    bridge.note_playback_streams = lambda *args, **kwargs: None
    if overlay:
        bridge.ensure_engine_settings = lambda: None
    else:
        def no_engine():
            raise RuntimeError('no overlay')
        bridge.ensure_engine_settings = no_engine
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
        spec = importlib.util.spec_from_file_location('autosub_overlay_test', MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        real_sleep = time.sleep
        with patch.object(module.time, 'sleep', lambda s: real_sleep(0)):
            class Gen(types.ModuleType):
                def __setattr__(self, name, value):
                    if name == 'show_msg':
                        overlays.append(value)
                    super().__setattr__(name, value)
            general.__class__ = Gen
            module.autosub_on_play()
    # the lines about the loaded subtitle, with the seconds each was up
    lines = []
    for index, text in enumerate(overlays):
        if 'כתובית' in text and 'מחפש' not in text:
            heading = text.replace('[COLOR lightblue]', '').replace('[/COLOR]', '').split('\n')[0]
            lines.append((heading, round(slept.get(index, 0.0), 1)))
    return {'lines': lines, 'last': overlays[-1] if overlays else None, 'reads': reads['n'],
            'log': [m for m in log if 'autosub overlay' in m], 'all': overlays, 'cap': module._SYNC_CHECK_OVERLAY_CAP}


class WaitForSyncCheck(unittest.TestCase):

    def setUp(self):
        self.module = load_module()

    def wait(self, states, ours=None, cap=25.0):
        slept = []
        reads = iter(states)
        last = [states[-1]]

        def read():
            try:
                last[0] = next(reads)
            except StopIteration:
                pass
            return last[0]

        state, waited = self.module._wait_for_sync_check(
            read, ours or (lambda: True), slept.append, cap=cap)
        return state, round(waited, 1), round(sum(slept), 1)

    def test_it_returns_the_state_the_check_ended_in(self):
        for end in ('confirmed', 'fixed', 'unverified'):
            self.assertEqual(self.wait(['checking'] * 10 + [end]), (end, 2.0, 2.0))

    def test_a_check_that_already_ended_costs_no_wait(self):
        self.assertEqual(self.wait(['fixed']), ('fixed', 0.0, 0.0))

    def test_the_cap_ends_the_wait_with_no_result(self):
        self.assertEqual(self.wait(['checking']), ('', 25.0, 25.0))
        self.assertEqual(self.wait(['checking'], cap=3.0), ('', 3.0, 3.0))

    def test_a_status_that_is_gone_or_unknown_is_no_result(self):
        # three empty reads in a row, so 0.4 s later than the first of them
        for gone in ('', 'something-else'):
            self.assertEqual(self.wait(['checking', 'checking', gone]), ('', 0.8, 0.8))

    def test_one_empty_read_does_not_end_the_wait(self):
        for hiccup in ([''], ['', '']):
            states = ['checking'] * 3 + hiccup + ['checking'] * 3 + ['confirmed']
            self.assertEqual(self.wait(states)[0], 'confirmed', hiccup)
        self.assertEqual(self.wait(['checking', '', 'fixed']), ('fixed', 0.4, 0.4))

    def test_a_verdict_that_lands_during_the_last_sleep_is_still_read(self):
        self.assertEqual(self.wait(['checking'] * 15 + ['fixed'], cap=3.0), ('fixed', 3.0, 3.0))
        self.assertEqual(self.wait(['checking'] * 16 + ['fixed'], cap=3.0), ('', 3.0, 3.0))

    def test_an_overlay_that_is_no_longer_ours_ends_it_before_the_status_is_read(self):
        answers = iter([True, True, False])
        read = []

        def state():
            read.append(1)
            return 'checking'

        got = self.module._wait_for_sync_check(state, lambda: next(answers), lambda s: None)
        self.assertIsNone(got[0])          # not '': there is no line left to hold
        self.assertEqual(len(read), 2)

    def test_the_toast_switch(self):
        on = self.module._toasts_on
        for value, expected in (('true', True), ('', True), (None, True), ('TRUE ', True),
                                ('false', False), (' False', False)):
            kodi = types.SimpleNamespace(get_setting=lambda name, default='', value=value: value)
            self.assertEqual(on(kodi), expected, value)

        def broken(name, default=''):
            raise RuntimeError('settings')
        self.assertTrue(on(types.SimpleNamespace(get_setting=broken)))


class OverlayThroughTheCheck(unittest.TestCase):

    def test_a_verdict_known_at_load_shows_its_line_once_as_before(self):
        for state, heading in (('confirmed', CONFIRMED), ('fixed', FIXED), ('unverified', NOT_YET),
                               ('', 'כתובית נטענה')):
            r = run_autosub([state])
            self.assertEqual(r['lines'], [(heading, 5.0)], state)
            self.assertEqual(r['last'], 'END')
            self.assertEqual(r['log'], [])

    def test_checking_stays_until_the_fix_and_leaves_for_its_toast(self):
        # the reported case: the check ends 9 s after the load with a fix
        r = run_autosub(['checking'] * 46 + ['fixed'])
        self.assertEqual(r['lines'], [(CHECKING, 9.0)])
        self.assertEqual(r['last'], 'END')
        self.assertEqual(len(r['log']), 1)
        self.assertIn('ended fixed after 9.0s', r['log'][0])

    def test_with_toasts_switched_off_the_overlay_says_the_fix_itself(self):
        r = run_autosub(['checking'] * 46 + ['fixed'], toasts='false')
        self.assertEqual(r['lines'], [(CHECKING, 9.0), (FIXED, 5.0)])

    def test_checking_then_confirmed(self):
        r = run_autosub(['checking'] * 31 + ['confirmed'])
        self.assertEqual(r['lines'], [(CHECKING, 6.0), (CONFIRMED, 5.0)])
        self.assertEqual(r['last'], 'END')

    def test_checking_then_not_verified_says_so_and_not_that_it_is_pending(self):
        r = run_autosub(['checking'] * 31 + ['unverified'])
        self.assertEqual(r['lines'], [(CHECKING, 6.0), (NOT_VERIFIED, 5.0)])

    def test_the_subtitle_name_stays_under_every_line(self):
        r = run_autosub(['checking'] * 5 + ['confirmed'])
        shown = [text for text in r['all'] if 'כתובית' in text and 'מחפש' not in text]
        self.assertEqual(len(shown), 2)
        self.assertTrue(all(text.endswith('\nFilm.WEB-DL.heb[/COLOR]') for text in shown), shown)

    def test_a_check_that_never_ends_is_followed_up_to_the_cap_only(self):
        r = run_autosub(['checking'])
        self.assertEqual(r['lines'], [(CHECKING, r['cap'])])
        self.assertEqual(r['cap'], 25.0)
        self.assertEqual(r['last'], 'END')
        self.assertIn('not followed further after 25.0s', r['log'][0])

    def test_a_quick_verdict_replaces_the_line_at_once(self):
        r = run_autosub(['checking', 'checking', 'confirmed'])
        self.assertEqual(r['lines'], [(CHECKING, 0.2), (CONFIRMED, 5.0)])

    def test_another_pick_by_the_viewer_ends_it_with_no_line_of_ours(self):
        r = run_autosub(['checking'] * 40 + ['confirmed'], pick_at=10)
        self.assertEqual([heading for heading, _secs in r['lines']], [CHECKING])
        self.assertLess(r['lines'][0][1], 2.5)
        self.assertEqual(r['last'], 'END')
        self.assertLess(r['reads'], 15)
        self.assertIn('left to another pick or a stop', r['log'][0])

    def test_a_stop_ends_it(self):
        r = run_autosub(['checking'] * 40 + ['confirmed'], stop_at=10)
        self.assertEqual([heading for heading, _secs in r['lines']], [CHECKING])
        self.assertLess(r['reads'], 15)
        self.assertEqual(r['last'], 'END')
        self.assertIn('left to another pick or a stop', r['log'][0])

    def test_a_status_that_vanishes_early_still_leaves_the_line_its_five_seconds(self):
        r = run_autosub(['checking'] * 6 + [''])
        self.assertEqual(r['lines'], [(CHECKING, 1.4), (CHECKING, 3.6)])
        self.assertIn('not followed further after 1.4s', r['log'][0])
        self.assertEqual(r['last'], 'END')

    def test_without_the_overlay_nothing_waits(self):
        r = run_autosub(['checking'], overlay=False)
        self.assertEqual(r['lines'], [])
        self.assertLess(r['reads'], 3)


if __name__ == '__main__':
    unittest.main()
