"""Current-subtitle timing status is exact, private, and skin-visible."""

import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / 'addons/service.subtitles.kodipovilai'
LIB = ADDON / 'resources/lib'


class SubtitleSyncStatus(unittest.TestCase):
    def setUp(self):
        self.props = {}
        self.stream = {'url': 'https://media.invalid/movie.mkv?id=A&token=one'}

        xbmc = types.ModuleType('xbmc')
        xbmc.Player = lambda: types.SimpleNamespace(
            getPlayingFile=lambda: self.stream['url'])
        xbmc.sleep = lambda _ms: None
        xbmc.getInfoLabel = lambda _label: self.props.get(
            'moransubs.current_sub', '')
        xbmcaddon = types.ModuleType('xbmcaddon')
        xbmcvfs = types.ModuleType('xbmcvfs')
        xbmcgui = types.ModuleType('xbmcgui')
        props = self.props
        xbmcgui.Window = lambda _wid: types.SimpleNamespace(
            getProperty=lambda key: props.get(key, ''),
            setProperty=lambda key, value: props.__setitem__(key, value),
            clearProperty=lambda key: props.pop(key, None))
        self.mods = patch.dict(sys.modules, {
            'xbmc': xbmc, 'xbmcaddon': xbmcaddon,
            'xbmcvfs': xbmcvfs, 'xbmcgui': xbmcgui,
        })
        self.mods.start()
        self.addCleanup(self.mods.stop)
        spec = importlib.util.spec_from_file_location(
            'kodi_utils_status_test', LIB / 'kodi_utils.py')
        self.ku = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ku)

    def test_record_matches_exact_candidate_and_stream_without_raw_tokens(self):
        link = 'pool://subtitle?hash=secret-subtitle-id'
        self.ku.set_current_subtitle(link)
        self.assertTrue(self.ku.set_subtitle_sync_status(
            'fixed', source='community'))
        status = self.ku.get_subtitle_sync_status(link)
        self.assertEqual(status['state'], 'fixed')
        self.assertEqual(status['label'], 'סונכרנה אוטומטית')

        prop = (self.ku._CURRENT_SUB_STATUS_PROP + '.'
                + self.ku.get_subtitle_selection_token())
        raw = self.props[prop]
        self.assertNotIn(link, raw)
        self.assertNotIn(self.stream['url'], raw)
        self.assertNotIn('token=one', raw)
        self.assertLess(len(raw), 256)

        # A query-only change is another debrid object/cut, even when the path
        # is identical. Its status must not inherit the first one's verdict.
        self.stream['url'] = 'https://media.invalid/movie.mkv?id=B&token=one'
        self.assertEqual(self.ku.get_subtitle_sync_status(link), {})

    def test_reselect_same_candidate_preserves_but_new_pick_clears_status(self):
        self.ku.set_current_subtitle('candidate-A')
        self.ku.set_subtitle_sync_status('confirmed', source='release')
        old_token = self.ku.get_subtitle_selection_token()
        prop = self.ku._CURRENT_SUB_STATUS_PROP + '.' + old_token
        raw = self.props[prop]

        self.ku.set_current_subtitle('candidate-A')
        self.assertEqual(self.props[prop], raw)
        self.ku.set_current_subtitle('candidate-B')
        self.assertNotIn(prop, self.props)
        self.assertFalse(self.ku.set_subtitle_sync_status(
            'fixed', link='candidate-A'))

    def test_custom_chooser_renders_result_only_on_current_row(self):
        spec = importlib.util.spec_from_file_location(
            'subs_chooser_status_test', LIB / 'subs_chooser.py')
        chooser = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(chooser)
        current = {
            'filename': '» נוכחית · כתובית עברית — Release.Name',
            'language': 'he',
            '_subsync_label': 'כבר מסונכרנת',
        }
        head, rel, _pct, _col, _flag = chooser._classify(
            current, {}, None)
        self.assertEqual(head, 'כתובית עברית')
        self.assertTrue(rel.startswith('כבר מסונכרנת'))
        self.assertIn('Release.Name', rel)

        other = dict(current, filename='כתובית אחרת — Other.Release')
        _head, rel, *_rest = chooser._classify(other, {}, None)
        self.assertNotIn('כבר מסונכרנת', rel)

    def test_fixed_status_is_published_only_after_delivery_confirmation(self):
        self.ku.set_current_subtitle('candidate-A')
        selection = self.ku.current_subtitle_selection(
            expected_link='candidate-A')
        path = r'C:\private\movie.corrected.srt'
        self.assertTrue(self.ku.stage_subtitle_sync_fix(
            path, selection=selection, source='cache'))
        self.assertEqual(self.ku.get_subtitle_sync_status('candidate-A'), {})
        ready_raw = self.props[
            self.ku._CURRENT_SUB_FIX_READY_PROP + '.' + selection['token']]
        self.assertNotIn(path, ready_raw)
        self.assertTrue(self.ku.confirm_subtitle_sync_fix(
            path, selection=selection))
        self.assertEqual(
            self.ku.get_subtitle_sync_status('candidate-A')['state'], 'fixed')

    def test_staged_fix_cannot_follow_the_user_to_another_candidate(self):
        self.ku.set_current_subtitle('candidate-A')
        selection = self.ku.current_subtitle_selection(
            expected_link='candidate-A')
        self.assertTrue(self.ku.stage_subtitle_sync_fix(
            'fixed-A.srt', selection=selection))
        self.ku.set_current_subtitle('candidate-B')
        self.assertFalse(self.ku.confirm_subtitle_sync_fix(
            'fixed-A.srt', selection=selection))
        self.assertEqual(self.ku.get_subtitle_sync_status('candidate-B'), {})

    def test_confirmation_toast_is_suppressed_if_selection_changes_mid_commit(self):
        self.ku.set_current_subtitle('candidate-A')
        selection = self.ku.current_subtitle_selection(
            expected_link='candidate-A')
        self.assertTrue(self.ku.stage_subtitle_sync_fix(
            'fixed-A.srt', selection=selection,
            notice='הכתובית סונכרנה אוטומטית'))
        real_publish = self.ku.set_subtitle_sync_status

        def publish_then_switch(*args, **kwargs):
            accepted = real_publish(*args, **kwargs)
            self.ku.set_current_subtitle('candidate-B')
            return accepted

        notice = Mock()
        with patch.object(self.ku, 'set_subtitle_sync_status',
                          side_effect=publish_then_switch), \
             patch.object(self.ku, 'notify', notice):
            self.assertFalse(self.ku.confirm_subtitle_sync_fix(
                'fixed-A.srt', selection=selection))
        notice.assert_not_called()
        self.assertEqual(self.ku.get_subtitle_sync_status('candidate-B'), {})

    def test_player_registration_and_pin_are_both_required_for_fixed(self):
        xbmc = sys.modules['xbmc']

        def run_case(candidate, grow, pin_ok):
            self.ku.set_current_subtitle(candidate)
            selection = self.ku.current_subtitle_selection(
                expected_link=candidate)
            path = candidate + '.fixed.srt'
            self.assertTrue(self.ku.stage_subtitle_sync_fix(
                path, selection=selection))
            streams = ['embedded']

            def apply(_path):
                if grow:
                    streams.append('external')

            def pin(_index):
                if not pin_ok:
                    raise RuntimeError('synthetic pin failure')

            player = types.SimpleNamespace(
                isPlayingVideo=lambda: True,
                getPlayingFile=lambda: self.stream['url'],
                getAvailableSubtitleStreams=lambda: list(streams),
                setSubtitles=apply, showSubtitles=lambda _on: None,
                setSubtitleStream=pin)
            with patch.object(xbmc, 'Player', return_value=player):
                applied = self.ku.apply_subtitle_file(
                    path, selection=selection)
            return applied, self.ku.get_subtitle_sync_status(candidate)

        applied, status = run_case('no-growth', False, True)
        self.assertFalse(applied)
        self.assertEqual(status, {})
        applied, status = run_case('pin-fails', True, False)
        self.assertFalse(applied)
        self.assertEqual(status, {})
        applied, status = run_case('registered', True, True)
        self.assertTrue(applied)
        self.assertEqual(status['state'], 'fixed')

    def test_delivery_ack_is_exact_to_path_selection_and_stream(self):
        self.ku.set_current_subtitle('candidate-A')
        selection = self.ku.current_subtitle_selection(
            expected_link='candidate-A')
        path = r'C:\private\original.srt'
        self.assertTrue(self.ku.stage_subtitle_delivery(
            path, selection=selection))
        self.assertTrue(self.ku.subtitle_delivery_staged(
            path, selection=selection))
        self.assertFalse(self.ku.subtitle_delivery_is_applied(
            path, selection=selection))
        self.assertFalse(self.ku.mark_subtitle_delivery_applied(
            r'C:\private\other.srt', selection=selection))

        prop = (self.ku._CURRENT_SUB_DELIVERY_PROP + '.'
                + selection['token'])
        raw = self.props[prop]
        self.assertNotIn(path, raw)
        self.assertNotIn(self.stream['url'], raw)
        self.assertTrue(self.ku.mark_subtitle_delivery_applied(
            path, selection=selection))
        self.assertTrue(self.ku.subtitle_delivery_is_applied(
            path, selection=selection))

        self.stream['url'] = 'https://media.invalid/other.mkv?id=B'
        self.assertFalse(self.ku.subtitle_delivery_is_applied(
            path, selection=selection))

    def test_apply_original_marks_delivery_before_worker_may_replace_it(self):
        xbmc = sys.modules['xbmc']
        self.ku.set_current_subtitle('candidate-A')
        selection = self.ku.current_subtitle_selection(
            expected_link='candidate-A')
        original = 'original.srt'
        streams = ['embedded']
        active = {'path': ''}

        def apply(path):
            streams.append(path)
            active['path'] = path

        def pin(index):
            active['path'] = streams[index]

        player = types.SimpleNamespace(
            isPlayingVideo=lambda: True,
            getPlayingFile=lambda: self.stream['url'],
            getAvailableSubtitleStreams=lambda: list(streams),
            setSubtitles=apply, showSubtitles=lambda _on: None,
            setSubtitleStream=pin)
        self.assertTrue(self.ku.stage_subtitle_delivery(
            original, selection=selection))
        self.assertFalse(self.ku.subtitle_delivery_is_applied(
            original, selection=selection))
        with patch.object(xbmc, 'Player', return_value=player):
            self.assertTrue(self.ku.apply_subtitle_file(
                original, selection=selection))
        self.assertEqual(active['path'], original)
        self.assertTrue(self.ku.subtitle_delivery_is_applied(
            original, selection=selection))

    def test_confirmed_status_waits_for_delivery_and_failure_abandons_pick(self):
        xbmc = sys.modules['xbmc']
        link = 'trusted-candidate'
        path = 'trusted.srt'
        self.ku.set_current_subtitle(link)
        selection = self.ku.current_subtitle_selection(expected_link=link)
        self.assertTrue(self.ku.stage_subtitle_delivery(
            path, selection=selection,
            status='confirmed', source='release'))
        self.assertEqual(self.ku.get_subtitle_sync_status(link), {})
        player = types.SimpleNamespace(
            isPlayingVideo=lambda: True,
            getPlayingFile=lambda: self.stream['url'],
            getAvailableSubtitleStreams=lambda: ['embedded'],
            setSubtitles=Mock(side_effect=RuntimeError('delivery failed')),
            showSubtitles=lambda _on: None,
            setSubtitleStream=lambda _index: None)
        with patch.object(xbmc, 'Player', return_value=player):
            self.assertFalse(self.ku.apply_subtitle_file(
                path, selection=selection))
        self.assertEqual(self.ku.get_current_subtitle(), '')
        self.assertEqual(self.ku.get_subtitle_sync_status(link), {})

    def test_confirmed_status_commits_only_after_registration_and_pin(self):
        xbmc = sys.modules['xbmc']
        link = 'trusted-candidate'
        path = 'trusted.srt'
        self.ku.set_current_subtitle(link)
        selection = self.ku.current_subtitle_selection(expected_link=link)
        self.assertTrue(self.ku.stage_subtitle_delivery(
            path, selection=selection,
            status='confirmed', source='release'))
        streams = ['embedded']
        player = types.SimpleNamespace(
            isPlayingVideo=lambda: True,
            getPlayingFile=lambda: self.stream['url'],
            getAvailableSubtitleStreams=lambda: list(streams),
            setSubtitles=lambda value: streams.append(value),
            showSubtitles=lambda _on: None,
            setSubtitleStream=lambda _index: None)
        with patch.object(xbmc, 'Player', return_value=player):
            self.assertTrue(self.ku.apply_subtitle_file(
                path, selection=selection))
        self.assertEqual(
            self.ku.get_subtitle_sync_status(link)['state'], 'confirmed')


if __name__ == '__main__':
    unittest.main()
