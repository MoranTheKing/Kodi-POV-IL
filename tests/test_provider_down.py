"""A subtitle provider that is down is skipped for ten minutes (subs_engine,
0.3.68).

Ktuvit's own server went unreachable on 2 Nov 2026 (522 after ~20 s): every
search was held to max_search_time, and the provider, still running at the
cut, made the next search wait or be refused. What it finds after the cut is
lost anyway. Two searches in a row that it outlives mark it down; the first
search after the ten minutes tries it again; one that ends in time is clear.
One slow answer alone skips nothing, nor does a cut that nothing beat (then
the device's own network is slow).
"""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ADDON = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai'


class _Window(object):
    props = {}

    def __init__(self, *_a):
        pass

    def setProperty(self, k, v):
        _Window.props[k] = v

    def getProperty(self, k):
        return _Window.props.get(k, '')


SETTINGS = {'max_search_time': '1', 'ktuvit': 'true', 'opensubtitles': 'true',
            'language_hebrew': 'true', 'all_lang': 'false',
            'retry_search_with_all_langs': 'false',
            'enable_autosub_notifications': 'false'}


def _load():
    tmp = tempfile.mkdtemp()
    stubs = dict((n, mock.MagicMock(name=n)) for n in
                 ('xbmc', 'xbmcaddon', 'xbmcgui', 'xbmcvfs', 'xbmcplugin'))
    stubs['xbmcvfs'].translatePath = lambda p: tmp
    addon = mock.MagicMock()
    addon.getSetting = lambda k: SETTINGS.get(k, 'false')
    addon.getAddonInfo = lambda k: tmp
    stubs['xbmcaddon'].Addon = lambda *a, **k: addon
    stubs['xbmcgui'].Window = _Window
    stubs['xbmc'].sleep = lambda ms: time.sleep(ms / 1000.0)
    with mock.patch.dict(sys.modules, stubs):
        sys.path.insert(0, str(ADDON))
        try:
            from resources.lib.subs_engine import engine  # noqa: F401
        finally:
            sys.path.remove(str(ADDON))
        mods = dict((k, v) for k, v in sys.modules.items()
                    if k in stubs or k == 'resources' or k.startswith('resources.'))
    return mods


MODS = _load()


class Base(unittest.TestCase):

    def setUp(self):
        self.mods = mock.patch.dict(sys.modules, MODS)
        self.mods.start()
        self.addCleanup(self.mods.stop)
        self.eng = MODS['resources.lib.subs_engine.engine']
        _Window.props.clear()


class Marks(Base):

    def test_two_cuts_in_a_row_skip_it_for_ten_minutes(self):
        note, down = self.eng._note_provider_outcomes, self.eng._provider_down
        t0 = 1000000.0
        note(['ktuvit'], ['opensubtitles'], ['opensubtitles'], now=t0)
        self.assertFalse(down('ktuvit', now=t0 + 1))          # one slow answer: nothing
        note(['ktuvit'], ['opensubtitles'], ['opensubtitles'], now=t0 + 60)
        self.assertTrue(down('ktuvit', now=t0 + 61))
        self.assertTrue(down('ktuvit', now=t0 + 60 + 599))
        self.assertFalse(down('ktuvit', now=t0 + 60 + 601))   # tried again
        self.assertFalse(down('opensubtitles', now=t0 + 61))
        # outliving the try again: skipped again at once
        note(['ktuvit'], ['opensubtitles'], ['opensubtitles'], now=t0 + 700)
        self.assertTrue(down('ktuvit', now=t0 + 701))
        # ending in time clears it
        note([], ['ktuvit', 'opensubtitles'], ['opensubtitles'], now=t0 + 1400)
        self.assertFalse(down('ktuvit', now=t0 + 1401))
        note(['ktuvit'], ['opensubtitles'], ['opensubtitles'], now=t0 + 1500)
        self.assertFalse(down('ktuvit', now=t0 + 1501))

    def test_strikes_far_apart_and_a_slow_network_mark_nothing(self):
        note, down = self.eng._note_provider_outcomes, self.eng._provider_down
        t0 = 2000000.0
        note(['ktuvit'], ['opensubtitles'], ['opensubtitles'], now=t0)
        note(['ktuvit'], ['opensubtitles'], ['opensubtitles'], now=t0 + 1801)    # over half an hour on
        self.assertFalse(down('ktuvit', now=t0 + 1802))
        _Window.props.clear()
        # nothing ended in time: the device's network, not a provider
        for i in range(3):
            note(['ktuvit', 'opensubtitles'], [], [], now=t0 + i)
        self.assertFalse(down('ktuvit', now=t0 + 3))
        self.assertFalse(down('opensubtitles', now=t0 + 3))
        # a provider that ended at once with nothing (no IMDb id, nothing
        # playing) never went out: no proof the network was fine (review)
        for i in range(3):
            note(['ktuvit', 'opensubtitles'], ['wizdom', 'subsource'], [], now=t0 + 10 + i)
        self.assertFalse(down('ktuvit', now=t0 + 13))

    def test_a_broken_state_is_no_skip(self):
        _Window.props[self.eng._DOWN_PROP] = '{not json'
        self.assertFalse(self.eng._provider_down('ktuvit'))
        skipped = []
        self.assertTrue(self.eng._provider_on('ktuvit', skipped))
        self.assertEqual(skipped, [])
        self.eng._note_provider_outcomes(['ktuvit'], ['yify'], ['yify'])   # never raises


class Search(Base):
    """c_get_subtitles with a provider that hangs past the cut (1 s)."""

    def run_search(self):
        return self.eng.c_get_subtitles({'title': 'x', 'imdb': 'tt1', 'season': '0',
                                          'episode': '0', 'year': '2020'})

    def test_a_hanging_provider_is_left_out_after_two_searches(self):
        eng = self.eng
        calls = []
        release = threading.Event()

        def hang(video_data):
            calls.append('ktuvit')
            release.wait(2.5)

        def fast(video_data, all_lang_override=False):
            calls.append('opensubtitles')
            eng.opensubtitles.global_var = [{'name': 'en.srt'}]

        with mock.patch.object(eng.ktuvit, 'get_subs', hang), \
                mock.patch.object(eng.opensubtitles, 'get_subs', fast):
            for n in (1, 2):
                calls.clear()
                started = time.monotonic()
                out = self.run_search()
                self.assertEqual(sorted(calls), ['ktuvit', 'opensubtitles'])
                self.assertTrue(eng.last_search_cut_short)
                self.assertGreaterEqual(time.monotonic() - started, 1.0)
                self.assertEqual(out, [{'name': 'en.srt'}])
                self.assertTrue(eng._provider_workers_ready(5))   # it ends at last
            self.assertTrue(eng._provider_down('ktuvit'))
            calls.clear()
            eng.last_search_cut_short = False
            started = time.monotonic()
            out = self.run_search()
            self.assertEqual(calls, ['opensubtitles'])            # not started
            self.assertLess(time.monotonic() - started, 0.9)      # not held to the cut
            self.assertFalse(eng.last_search_cut_short)
            self.assertEqual(out, [{'name': 'en.srt'}])

    def test_a_timing_pass_without_a_provider_is_temporary(self):
        # review of 0.3.68: the all-language timing pass is all or nothing; one
        # with a provider skipped as down must not come back as complete
        eng = self.eng
        now = time.time()
        for i in (0, 60):
            eng._note_provider_outcomes(['opensubtitles'], ['yify'], ['yify'], now=now - 120 + i)
        self.assertTrue(eng._provider_down('opensubtitles'))
        started = []
        with mock.patch.object(eng.opensubtitles, 'get_subs', lambda *a: started.append('os')), \
                mock.patch.object(eng.yify, 'get_subs', lambda *a: started.append('yify')), \
                mock.patch.dict(SETTINGS, {'yify': 'true'}):
            with self.assertRaises(eng.ProviderSearchBusy):
                eng.c_get_subtitles({'title': 'x', 'imdb': 'tt1', 'season': '0', 'episode': '0',
                                     'year': '2020'}, all_lang_override=True, timing_only=True)
        self.assertEqual(started, [])
        self.assertTrue(eng.last_search_cut_short)


if __name__ == '__main__':
    unittest.main()
