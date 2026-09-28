"""Exercise restored public actions without network or an installed Kodi profile."""

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


DEFAULT = Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai/default.py'
spec = importlib.util.spec_from_file_location('candidate_default_actions', DEFAULT)
mod = importlib.util.module_from_spec(spec)
_kodi_stubs = {name: types.ModuleType(name)
               for name in ('xbmc', 'xbmcaddon', 'xbmcgui', 'xbmcplugin', 'xbmcvfs')}
_kodi_stubs['xbmcgui'].WindowDialog = object
with patch.dict(sys.modules, _kodi_stubs):
    spec.loader.exec_module(mod)


class PublicActionTests(unittest.TestCase):
    def test_dispatcher_invokes_the_three_restored_handlers(self):
        for name in ('connect_mdblist', 'remember_source_status', 'torbox_status'):
            handler_name = '_handle_' + name
            handler = Mock()
            with patch.object(mod, 'xbmc', object()), patch.object(
                    mod, '_parse_query', return_value={'action': name}), patch.object(
                    mod, handler_name, handler), patch.object(
                    mod.sys, 'argv', ['script.py', 'action=' + name]):
                mod.main()
            handler.assert_called_once_with({'action': name})

    def test_failed_mdblist_token_write_never_sets_watched_provider(self):
        with patch.object(mod, '_mdblist_pov_addon', return_value=object()), patch.object(
                mod, '_mdblist_pov_write', return_value=['mdblist.token']) as write:
            self.assertFalse(mod._mdblist_apply_connect('synthetic-key', 'tester'))
            write.assert_called_once_with((('mdblist.token', 'synthetic-key'),))

    def test_successful_mdblist_connect_sets_account_after_verified_token(self):
        writes = []

        def write(pairs):
            writes.append(pairs)
            return []

        with patch.object(mod, '_mdblist_pov_addon', return_value=object()), patch.object(
                mod, '_mdblist_pov_write', side_effect=write):
            self.assertTrue(mod._mdblist_apply_connect('key', 'tester'))
        self.assertEqual(writes[0], (('mdblist.token', 'key'),))
        self.assertIn(('watched_indicators', '2'), writes[1])
        self.assertIn(('mdbl_indicators_active', 'true'), writes[1])

    def test_invalid_mdblist_key_cannot_reach_connect(self):
        dialog = types.SimpleNamespace(ok=Mock(), yesno=Mock(return_value=False))
        fake_gui = types.SimpleNamespace(Dialog=lambda: dialog)
        pair = types.SimpleNamespace(validate_key_full=lambda _key: (False, ''))
        notify = types.SimpleNamespace(notify=Mock())
        with patch.object(mod, 'xbmcgui', fake_gui), patch.object(
                mod, '_mdblist_apply_connect') as connect:
            self.assertEqual(mod._test_save_mdblist(notify, pair, 'bad'), 'cancel')
        connect.assert_not_called()

    def test_verified_mdblist_connect_refreshes_home_after_persisting(self):
        dialog = types.SimpleNamespace(ok=Mock())
        pair = types.SimpleNamespace(validate_key_full=lambda _key: (True, 'tester'))
        notify = types.SimpleNamespace(notify=Mock())
        with patch.object(mod, 'xbmcgui', types.SimpleNamespace(Dialog=lambda: dialog)), patch.object(
                mod, '_mdblist_apply_connect', return_value=True) as connect, patch.object(
                mod, '_mdblist_surface_lists') as surface, patch.object(
                mod, '_mdblist_push_to_acctmgr', return_value=False):
            self.assertEqual(mod._test_save_mdblist(notify, pair, 'valid'), 'ok')
        connect.assert_called_once_with('valid', 'tester')
        surface.assert_called_once_with()

    def test_mdblist_refresh_invalidates_service_cache_before_rebuilding(self):
        order = []
        manager = types.ModuleType('pov_visibility_mgr')
        manager.invalidate = lambda: order.append('invalidate')
        manager._trigger_favourites_refresh = lambda: order.append('refresh')
        vfs = types.SimpleNamespace(translatePath=lambda _path: '/synthetic/wizard/patches')
        with patch.object(mod, 'xbmcvfs', vfs), patch.dict(
                sys.modules, {'pov_visibility_mgr': manager}):
            mod._mdblist_surface_lists()
        self.assertEqual(order, ['invalidate', 'refresh'])

    def test_torbox_status_reads_account_and_stats_without_exposing_token(self):
        dialog = types.SimpleNamespace(ok=Mock(), textviewer=Mock())
        gui = types.SimpleNamespace(Dialog=lambda: dialog)
        pov = types.SimpleNamespace(getSetting=lambda _key: 'synthetic-private-token')

        def api(_token, path, params=None):
            if path == 'user/me':
                return {'plan': 2, 'email': 'test@example.invalid',
                        'customer': 'tester', 'total_downloaded': 20}
            self.assertEqual(path, 'user/stats')
            self.assertEqual(params['bandwidth_grouping'], 'day')
            return {'bandwidth': [{'bytes_downloaded': 1024}]}

        with patch.object(mod, 'xbmcgui', gui), patch.object(
                mod, '_pov_addon', return_value=pov), patch.object(
                mod, '_torbox_api_get', side_effect=api):
            mod._handle_torbox_status({})
        body = dialog.textviewer.call_args.args[1]
        self.assertIn('1.0 KB', body)
        self.assertIn('Pro', body)
        self.assertNotIn('synthetic-private-token', body)

    def test_remember_source_diagnostic_reads_modular_wizard_record(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            pov = root / 'plugin.video.pov'
            sources = pov / 'resources/lib/modules/sources.py'
            sources.parent.mkdir(parents=True)
            sources.write_text('pov_source_remember.run_capture\n'
                               'pov_source_remember.run_reorder', encoding='utf-8')
            record = root / 'profile/addon_data/plugin.program.kodipovilwizard/source_memory/one.json'
            record.parent.mkdir(parents=True)
            record.write_text('{"name":"source-one","quality":"1080p",'
                              '"provider":"test"}', encoding='utf-8')
            addons = {
                'plugin.video.pov': types.SimpleNamespace(
                    getAddonInfo=lambda _key: str(pov)),
                'plugin.program.kodipovilwizard': types.SimpleNamespace(
                    getSetting=lambda _key: 'true'),
                mod.ADDON_ID: types.SimpleNamespace(getSetting=lambda _key: 'false'),
            }
            addon = types.SimpleNamespace(Addon=lambda aid: addons[aid])
            vfs = types.SimpleNamespace(translatePath=lambda path: (
                str(root / 'profile' / path.split('special://profile/', 1)[1])
                if path.startswith('special://profile/') else path))
            dialog = types.SimpleNamespace(ok=Mock(), textviewer=Mock())
            gui = types.SimpleNamespace(Dialog=lambda: dialog)
            with patch.object(mod, 'xbmcaddon', addon), patch.object(
                    mod, 'xbmcvfs', vfs), patch.object(mod, 'xbmcgui', gui):
                mod._handle_remember_source_status({})
            body = dialog.textviewer.call_args.args[1]
            self.assertIn('source-one', body)
            self.assertIn('מותקן', body)
            self.assertIn('רשומות מקומיות: 1', body)


if __name__ == '__main__':
    unittest.main()
