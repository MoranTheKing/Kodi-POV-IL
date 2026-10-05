"""Filtering, parent permissions, profile isolation and playback receipts."""
import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / 'plugin.program.kodipovilwizard/resources/libs'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load('profile_age_guard_test', LIBS / 'patches/profile_age_guard.py')
store = load('profile_store_test_age', LIBS / 'profile_store.py')


class AgeGuardTests(unittest.TestCase):
    def test_unknown_is_not_inferred_from_ratings_genres_or_title(self):
        policy = {'age': 7, 'approved': {}}
        for value in ('', 'NR', 'Unrated', '7.8', 'Children', '18+', 7, None):
            with self.subTest(value=value):
                self.assertFalse(guard.allows(policy, {'mpaa': value, 'rating': 3, 'genre': ['Kids']}))
        self.assertTrue(guard.allows(None, {'mpaa': 'NC-17'}))

    def test_age_boundaries_and_country_prefix(self):
        for rating, age in [('TV-Y', 0), ('TV-Y7-FV', 7), ('US:PG', 10), ('PG-13', 13),
                            ('US:TV-14', 14), ('GB:15', 15), ('R', 17), ('TV-MA', 18)]:
            with self.subTest(rating=rating):
                self.assertFalse(guard.allows({'age': age - 1}, {'mpaa': rating}))
                self.assertEqual(guard.allows({'age': min(age, 17)}, {'mpaa': rating}), age <= 17)
        self.assertFalse(guard.allows({'age': 15}, {'mpaa': 'G', 'adult': True}))

    def test_parent_approval_is_specific_to_media_type_and_identity(self):
        policy = {'age': 7, 'approved': {'tv:15': 'Known series'}}
        self.assertTrue(guard.allows(policy, {'mediatype': 'episode', 'tmdb_id': 15}))
        self.assertFalse(guard.allows(policy, {'mediatype': 'movie', 'tmdb_id': 15}))
        self.assertFalse(guard.allows(policy, {'mediatype': 'tvshow', 'tmdb_id': 16}))
        self.assertFalse(guard.allows({'blocked': True}, {'mpaa': 'G'}))

    def test_unknown_playable_rows_and_classified_folders_are_filtered(self):
        def item(rating, kind, ident=''):
            return types.SimpleNamespace(getProperty=lambda _key: json.dumps({'mpaa': rating}),
                getVideoInfoTag=lambda: types.SimpleNamespace(
                getMediaType=lambda: kind, getUniqueID=lambda key: ident))
        self.assertTrue(guard.visible(item('', ''), True, {'age': 7}))
        self.assertFalse(guard.visible(item('', 'movie'), False, {'age': 7}))
        self.assertFalse(guard.visible(item('TV-MA', 'tvshow'), True, {'age': 7}))
        self.assertTrue(guard.visible(item('G', 'movie'), False, {'age': 7}))
        self.assertFalse(guard.visible(item('', '', '15'), True, {'age': 7}))
        self.assertFalse(guard.visible(item('', ''), True, {'age': 7}, 'plugin://host/?tmdb_id=15'))
        self.assertFalse(guard.visible(item('', ''), True, {'blocked': True}))

    def test_metadata_capture_works_without_a_nonexistent_kodi_mpaa_getter(self):
        values = {}
        item = types.SimpleNamespace(setProperty=lambda k,v: values.update({k:v}),
            getProperty=lambda k: values.get(k, ''),
            getVideoInfoTag=lambda: types.SimpleNamespace(getMediaType=lambda: 'movie',
                                                         getUniqueID=lambda _k: '15'))
        with patch.object(guard, 'active_policy', return_value={'age': 7}):
            guard.stamp_item(item, {'mpaa': 'G', 'mediatype': 'movie', 'tmdb_id': 15})
        self.assertTrue(guard.visible(item, False, {'age': 7}))
        self.assertFalse(guard.visible(item, False, {'age': -1}))

    def test_reused_directory_wrapper_rereads_policy_for_each_profile(self):
        api = types.SimpleNamespace(addDirectoryItem=Mock(return_value=True), addDirectoryItems=Mock(return_value=True))
        api.addDirectoryItem._povil_age_guard = False
        original = api.addDirectoryItems
        with patch.dict(sys.modules, {'xbmcplugin': api}):
            guard.install_directory_guard()
            guard.install_directory_guard()
            rows = [('url', object(), False)]
            with patch.object(guard, 'active_policy', side_effect=[{'age': 7}, None]), patch.object(guard, 'visible', return_value=False):
                api.addDirectoryItems(1, rows)
                api.addDirectoryItems(1, rows)
        self.assertEqual(original.call_args_list[0].args[1], [])
        self.assertEqual(original.call_args_list[1].args[1], rows)

    def test_child_block_does_not_issue_a_playback_receipt(self):
        window = Mock()
        with patch.dict(sys.modules, {'xbmcgui': types.SimpleNamespace(Window=lambda _: window, Dialog=lambda: Mock())}), \
                patch.object(guard, 'active_policy', return_value={'age': 7}):
            self.assertFalse(guard.permit_play({'mpaa': 'R'}, 'pov', 'test://video'))
            window.setProperty.assert_not_called()


class ProfilePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.master = Path(self.tmp.name); self.child = self.master / 'profiles/Child'
        self.child.mkdir(parents=True)
        (self.master / 'profiles.xml').write_text('''<profiles><profile><id>0</id><name>Master</name>
            <directory>special://masterprofile/</directory><lockmode>1</lockmode><lockcode>QA</lockcode></profile>
            <profile><id>1</id><name>Child</name><directory>profiles/Child</directory>
            <locksettings>1</locksettings><lockfiles>true</lockfiles><lockaddonmanager>true</lockaddonmanager>
            <lockmode>0</lockmode></profile></profiles>''')
        (self.child / 'guisettings.xml').write_text('<settings><setting id="lookandfeel.skin">skin.estuary</setting></settings>')
        self.modules = patch.dict(sys.modules, {'xbmc': types.SimpleNamespace(), 'xbmcaddon': Mock(),
            'xbmcgui': types.SimpleNamespace(), 'xbmcvfs': types.SimpleNamespace(),
            'resources.libs': types.SimpleNamespace(profile_store=store),
            'resources.libs.patches': types.SimpleNamespace(profile_age_guard=guard)})
        self.modules.start(); self.addCleanup(self.modules.stop)
        self.parent = load('parental_profile_test', LIBS / 'parental_profiles.py')
        self.profile = store.registered_profiles(str(self.master))[1]

    def test_child_setup_approvals_and_settings_are_profile_local(self):
        self.parent.set_child(str(self.master), self.profile, 7)
        self.assertEqual(guard.policy_for(str(self.master), str(self.child))['age'], 7)
        self.assertIsNone(guard.policy_for(str(self.master), str(self.master)))
        self.parent.approve(str(self.master), self.profile, 'tv', 15, 'Known series')
        policy = guard.policy_for(str(self.master), str(self.child))
        self.assertTrue(guard.allows(policy, {'mediatype': 'episode', 'tmdb_id': 15}))
        self.parent.set_child(str(self.master), self.profile, 9)
        self.assertIn('tv:15', guard.policy_for(str(self.master), str(self.child))['approved'])

    def test_missing_corrupt_policy_and_unlocked_parent_fail_closed(self):
        self.parent.set_child(str(self.master), self.profile, 7)
        path = self.master / guard.POLICY_FILE
        content = path.read_bytes(); path.unlink()
        self.assertTrue(guard.policy_for(str(self.master), str(self.child))['blocked'])
        path.write_text('broken')
        self.assertTrue(guard.policy_for(str(self.master), str(self.child))['blocked'])
        path.write_bytes(content)
        profiles = self.master / 'profiles.xml'
        profiles.write_text(profiles.read_text().replace('<lockmode>1</lockmode>', '<lockmode>0</lockmode>'))
        self.assertTrue(guard.policy_for(str(self.master), str(self.child))['blocked'])

    def test_plain_profile_cannot_be_activated_as_child_without_native_locks(self):
        with self.assertRaises(ValueError):
            self.parent.set_child(str(self.master), dict(self.profile, locksettings=0), 7)
        self.assertFalse((self.child / guard.CHILD_MARKER).exists())

    def test_debrid_copy_does_not_copy_watchlist_accounts_or_history(self):
        source = self.master / 'addon_data/plugin.video.pov'; source.mkdir(parents=True)
        (source / 'settings.xml').write_text('<settings><setting id="rd.token">QA_DEBRID</setting><setting id="trakt.token">QA_PRIVATE</setting></settings>')
        self.parent.copy_debrid(str(self.master), self.profile)
        content = (self.child / 'addon_data/plugin.video.pov/settings.xml').read_text()
        self.assertIn('QA_DEBRID', content); self.assertNotIn('QA_PRIVATE', content)

    def test_playback_receipt_binds_video_profile_and_time(self):
        service = load('profile_service_test', LIBS.parents[1] / 'profile_service.py')
        receipt = dict(profile='child', host='pov', key='movie:15', mpaa='G', issued=10,
                       url_hash=hashlib.sha256(b'test://video').hexdigest())
        self.assertTrue(service.permitted_receipt(receipt, 'child', 'test://video', {'age': 7}, 12))
        self.assertFalse(service.permitted_receipt(receipt, 'adult', 'test://video', {'age': 7}, 12))
        self.assertFalse(service.permitted_receipt(receipt, 'child', 'test://other', {'age': 7}, 12))
        self.assertFalse(service.permitted_receipt(receipt, 'child', 'test://video', {'age': 7}, 400))

    def test_next_episode_preparation_does_not_stop_current_approved_video(self):
        window = Mock(); properties = {}
        window.setProperty.side_effect = lambda k,v: properties.update({k:v})
        current = dict(profile='child', host='pov', key='movie:15', mpaa='G', issued=10,
                      url_hash=hashlib.sha256(b'test://current').hexdigest())
        upcoming = dict(current, key='movie:16', url_hash=hashlib.sha256(b'test://next').hexdigest())
        receipts = iter([json.dumps(current), json.dumps(upcoming)])
        window.getProperty.side_effect = lambda k: next(receipts) if k == 'POVIL.ChildPlay' else properties.get(k, '')
        monitor = types.SimpleNamespace(waitForAbort=Mock(side_effect=[False, False, True]))
        player = Mock(); player.isPlayingVideo.return_value = True; player.getPlayingFile.return_value = 'test://current'
        kodi = types.SimpleNamespace(Monitor=lambda: monitor, Player=lambda: player)
        with patch.dict(sys.modules, {'xbmc': kodi,
                'xbmcgui': types.SimpleNamespace(Window=lambda _: window, Dialog=lambda: Mock()),
                'xbmcvfs': types.SimpleNamespace(translatePath=lambda _: 'child')}):
            service = load('profile_service_next_episode_test', LIBS.parents[1] / 'profile_service.py')
        with patch.object(guard, 'active_policy', return_value={'age': 7}), patch.object(service.time, 'time', return_value=12):
            service.run()
        player.stop.assert_not_called()

    def test_missing_master_cannot_certify_native_locks(self):
        self.parent.set_child(str(self.master), self.profile, 7)
        path = self.master / 'profiles.xml'
        from xml.etree import ElementTree as ET
        tree = ET.parse(path); root = tree.getroot()
        root.remove(root.find('profile'))
        tree.write(path)
        self.assertTrue(guard.policy_for(str(self.master), str(self.child))['blocked'])


if __name__ == '__main__':
    unittest.main()
