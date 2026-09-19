"""Current-subtitle timing status is exact, private, and skin-visible."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / 'addons/service.subtitles.kodipovilai'
LIB = ADDON / 'resources/lib'


class SubtitleSyncStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
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

    def test_refreshed_pool_link_keeps_initial_auto_selection_current(self):
        import urllib.parse

        def link(payload):
            return urllib.parse.quote(json.dumps(payload, ensure_ascii=False))

        first = link({
            'type': 'pool', 'hash': 'stable-content-hash',
            'release': 'The.Flash.WEB-DL', 'pool_kind': 'ktuvit',
            'source_lang': 'he-v1',
        })
        refreshed = link({
            'type': 'pool', 'hash': 'stable-content-hash',
            'release': 'The.Flash.WEB-DL', 'pool_kind': 'ktuvit',
            'source_lang': 'he-v2',
        })
        self.ku.set_current_subtitle(first)
        self.assertTrue(self.ku.set_subtitle_sync_status(
            'unverified', source='local'))
        opaque_id = self.props[self.ku._CURRENT_SUB_ID_PROP]
        self.assertEqual(len(opaque_id), 24)
        self.assertNotIn('stable-content-hash', opaque_id)

        spec = importlib.util.spec_from_file_location(
            'resources.lib.translate_current_identity_test',
            LIB / 'translate.py')
        translate = importlib.util.module_from_spec(spec)
        resources = types.ModuleType('resources')
        resources.__path__ = [str(ADDON / 'resources')]
        resources_lib = types.ModuleType('resources.lib')
        resources_lib.__path__ = [str(LIB)]
        with patch.dict(sys.modules, {
                'resources': resources,
                'resources.lib': resources_lib,
                'resources.lib.kodi_utils': self.ku}):
            resources.lib = resources_lib
            resources_lib.kodi_utils = self.ku
            spec.loader.exec_module(translate)
        rows = translate._mark_current([{
            'filename': 'כתובית · מאגר — The.Flash.WEB-DL',
            'language': 'he', 'link': refreshed,
        }])
        self.assertTrue(rows[0]['filename'].startswith('» נוכחית ·'))
        self.assertEqual(rows[0]['_subsync_label'], 'התזמון טרם אומת')

    def test_malformed_pool_rows_without_hash_do_not_share_an_identity(self):
        import urllib.parse

        left = urllib.parse.quote(json.dumps({
            'type': 'pool', 'release': 'left'}))
        right = urllib.parse.quote(json.dumps({
            'type': 'pool', 'release': 'right'}))
        self.assertNotEqual(
            self.ku.subtitle_candidate_identity(left),
            self.ku.subtitle_candidate_identity(right))

    def test_engine_identity_uses_provider_id_and_never_marks_a_sibling_row(self):
        import urllib.parse

        def link(file_id, token):
            return urllib.parse.quote(json.dumps({
                'type': 'engine', 'source': 'opensubtitles',
                'language': 'he', 'filename': 'Same.Release.srt',
                'download_data': {
                    'id': file_id, 'filename': 'Same.Release.srt',
                    'temporary_url': 'https://provider.invalid/' + token,
                },
            }, ensure_ascii=False))

        selected = link(101, 'old-token')
        same_row_refreshed = link(101, 'new-token')
        sibling = link(202, 'other-token')
        self.assertEqual(
            self.ku.subtitle_candidate_identity(selected),
            self.ku.subtitle_candidate_identity(same_row_refreshed))
        self.assertNotEqual(
            self.ku.subtitle_candidate_identity(selected),
            self.ku.subtitle_candidate_identity(sibling))
        self.ku.set_current_subtitle(selected)
        self.assertTrue(self.ku.set_subtitle_sync_status(
            'confirmed', source='release'))

        spec = importlib.util.spec_from_file_location(
            'resources.lib.translate_engine_identity_test',
            LIB / 'translate.py')
        translate = importlib.util.module_from_spec(spec)
        resources = types.ModuleType('resources')
        resources.__path__ = [str(ADDON / 'resources')]
        resources_lib = types.ModuleType('resources.lib')
        resources_lib.__path__ = [str(LIB)]
        with patch.dict(sys.modules, {
                'resources': resources,
                'resources.lib': resources_lib,
                'resources.lib.kodi_utils': self.ku}):
            resources.lib = resources_lib
            resources_lib.kodi_utils = self.ku
            spec.loader.exec_module(translate)

        rows = translate._mark_current([
            {'filename': 'Same.Release.srt', 'language': 'he',
             'link': sibling},
            {'filename': 'Same.Release.srt', 'language': 'he',
             'link': same_row_refreshed},
        ])
        self.assertTrue(rows[0]['filename'].startswith('» נוכחית ·'))
        self.assertEqual(rows[0]['link'], same_row_refreshed)
        self.assertEqual(rows[0]['_subsync_label'], 'כבר מסונכרנת')
        self.assertFalse(rows[1]['filename'].startswith('» נוכחית ·'))
        self.assertNotIn('_subsync_label', rows[1])

    def test_engine_without_provider_id_keeps_strict_link_identity(self):
        import urllib.parse

        left = urllib.parse.quote(json.dumps({
            'type': 'engine', 'source': 'unknown', 'language': 'he',
            'filename': 'Same.srt',
            'download_data': {'url': 'https://one.invalid/token'},
        }))
        right = urllib.parse.quote(json.dumps({
            'type': 'engine', 'source': 'unknown', 'language': 'he',
            'filename': 'Same.srt',
            'download_data': {'url': 'https://two.invalid/token'},
        }))
        self.assertNotEqual(
            self.ku.subtitle_candidate_identity(left),
            self.ku.subtitle_candidate_identity(right))

    def test_malformed_ktuvit_request_never_uses_film_id_as_row_id(self):
        import urllib.parse

        def link(raw_request):
            return urllib.parse.quote(json.dumps({
                'type': 'engine', 'source': 'ktuvit', 'language': 'he',
                'filename': 'Same.Release.srt',
                'download_data': {
                    'Ktuvit_Page_ID': '777',
                    'subtitle_download_data': raw_request,
                },
            }))

        left = link('{bad-A')
        right = link('{bad-B')
        self.assertNotEqual(left, right)
        self.assertNotEqual(
            self.ku.subtitle_candidate_identity(left),
            self.ku.subtitle_candidate_identity(right))

    def test_stream_identity_includes_kodi_header_suffix_privately(self):
        first = 'https://media.invalid/shared|Authorization=secret-A'
        second = 'https://media.invalid/shared|Authorization=secret-B'
        first_hash = self.ku._current_stream_hash(first)
        second_hash = self.ku._current_stream_hash(second)
        self.assertNotEqual(first_hash, second_hash)
        self.assertNotIn('secret-A', first_hash)
        self.assertEqual(len(first_hash), 24)

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

    def test_player_append_is_pinned_and_valid_replacement_is_accepted(self):
        xbmc = sys.modules['xbmc']

        def run_case(candidate, grow, pin_ok):
            self.ku.set_current_subtitle(candidate)
            selection = self.ku.current_subtitle_selection(
                expected_link=candidate)
            path_obj = Path(self.tmp.name) / (candidate + '.fixed.srt')
            path_obj.write_text(
                '1\n00:00:01,000 --> 00:00:02,000\nשלום\n',
                encoding='utf-8')
            path = str(path_obj)
            self.assertTrue(self.ku.stage_subtitle_sync_fix(
                path, selection=selection))
            streams = ['embedded', 'he'] if not grow else ['embedded']

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
        self.assertTrue(applied)
        self.assertEqual(status['state'], 'fixed')
        applied, status = run_case('pin-fails', True, False)
        self.assertFalse(applied)
        self.assertEqual(status, {})
        applied, status = run_case('registered', True, True)
        self.assertTrue(applied)
        self.assertEqual(status['state'], 'fixed')

    def test_sequential_external_slot_replacements_follow_each_new_pick(self):
        """Every manual pick may reuse Kodi's one external-subtitle slot.

        The Android field log kept the same stream count/name while replacing
        source 1028, then 1029 and 1030.  Prove each new exact selection can be
        acknowledged independently and that an earlier selection cannot own
        the later correction.
        """
        xbmc = sys.modules['xbmc']
        streams = ['embedded', 'he']
        handed = []
        player = types.SimpleNamespace(
            isPlayingVideo=lambda: True,
            getPlayingFile=lambda: self.stream['url'],
            getAvailableSubtitleStreams=lambda: list(streams),
            setSubtitles=lambda path: handed.append(path),
            showSubtitles=lambda _on: None,
            setSubtitleStream=lambda _index: None)

        selections = []
        with patch.object(xbmc, 'Player', return_value=player):
            for index, candidate in enumerate(
                    ('candidate-A', 'candidate-B', 'candidate-C'), 1):
                self.ku.set_current_subtitle(candidate)
                selection = self.ku.current_subtitle_selection(
                    expected_link=candidate)
                selections.append(selection)
                path = Path(self.tmp.name) / ('fixed-%d.srt' % index)
                path.write_text(
                    '1\n00:00:01,000 --> 00:00:02,000\nשלום %d\n'
                    % index, encoding='utf-8')
                self.assertTrue(self.ku.stage_subtitle_sync_fix(
                    str(path), selection=selection))
                self.assertTrue(self.ku.apply_subtitle_file(
                    str(path), selection=selection))
                self.assertEqual(
                    self.ku.get_subtitle_sync_status(candidate)['state'],
                    'fixed')

        self.assertEqual(len(handed), 3)
        self.assertEqual(len(set(handed)), 3)
        self.assertFalse(self.ku.subtitle_selection_matches(
            selections[0]['token'], selections[0]['link_hash'],
            selections[0]['stream_hash']))
        self.assertFalse(self.ku.subtitle_selection_matches(
            selections[1]['token'], selections[1]['link_hash'],
            selections[1]['stream_hash']))
        self.assertTrue(self.ku.subtitle_selection_matches(
            selections[2]['token'], selections[2]['link_hash'],
            selections[2]['stream_hash']))

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
