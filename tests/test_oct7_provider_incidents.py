"""Provider contracts for localized actions, old caches and expired auth."""
import importlib.util
import json
import os
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
PATCHES = ROOT / 'plugin.program.kodipovilwizard/resources/libs/patches'


def load(name):
    spec = importlib.util.spec_from_file_location('incident_' + name, PATCHES / (name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class ProviderIncidents(unittest.TestCase):
    def test_translated_tmdb_and_trakt_actions_keep_provider_ids(self):
        module = load('pov_list_actions')
        labels = dict(watchl_str='לצפייה', fav_str='מועדפים', coll_str='קולקציה')
        for media in ('movie', 'tvshow'):
            manager = types.SimpleNamespace(params={}, mediatype=media, icon='ICON')
            tmdb = module.default_choices(manager, labels, 'tmdb')
            trakt = module.default_choices(manager, labels, 'trakt')
            self.assertEqual([row[0] for row in tmdb], ['watchlist', 'favorites'])
            self.assertEqual([row[0] for row in trakt][:3], ['watchlist', 'favorites', 'collection'])
            self.assertEqual(tmdb[1][1], 'מועדפים')
            self.assertEqual(len(trakt), 4 if media == 'tvshow' else 3)
            for source in ('trakt_list_name', 'mdbl_list_name'):
                manager.params = {source: 'Copy this list'}
                self.assertEqual(module.default_choices(manager, labels, 'tmdb'), [])
                manager.params = {}

    def test_old_metadata_and_memory_tuple_are_read_without_data_loss(self):
        module = load('pov_cache_read')
        value = {'results': [{'id': 1399, 'name': 'סדרה', 'adult': False, 'poster_path': None}]}
        self.assertEqual(module.loads(repr(value)), value)
        self.assertEqual(module.loads(json.dumps(value)), value)
        self.assertEqual(module.loads(repr((9999999999, value))), (9999999999, value))
        self.assertIsNone(module.loads(''))
        with self.assertRaises((ValueError, SyntaxError)):
            module.loads('__import__("os").system("should never run")')

    def auth(self, payload, status=200):
        properties = {}; settings = {'trakt.token': 'old', 'trakt.refresh': 'refresh-old',
            'trakt.client_id': 'client', 'trakt.client_secret': 'secret'}
        notifications = []
        window = types.SimpleNamespace(getProperty=lambda key: properties.get(key, ''),
            setProperty=properties.__setitem__, clearProperty=lambda key: properties.pop(key, None))
        gui = types.SimpleNamespace(Window=lambda _: window, Dialog=lambda: types.SimpleNamespace(
            notification=lambda *a, **k: notifications.append(a)))
        with patch.dict('sys.modules', {'xbmcgui': gui}):
            module = load('pov_trakt_reauth')
        requests = []
        def request(method, url, **kwargs):
            requests.append((method, url))
            if url.endswith('oauth/token'):
                return types.SimpleNamespace(ok=status == 200, status_code=status, json=lambda: payload)
            return types.SimpleNamespace(ok=settings['trakt.token'] == 'new',
                status_code=200 if settings['trakt.token'] == 'new' else 401)
        target = types.SimpleNamespace(session=types.SimpleNamespace(request=request), timeout=1,
            kodi_utils=types.SimpleNamespace(sleep=lambda _: None),
            get_setting=lambda key, default='': settings.get(key, default), set_setting=settings.__setitem__)
        def original(path, **kwargs):
            response = target.session.request('get', path)
            return {'saved': 'show'} if response.ok else None
        target.call_trakt = original
        module.run(target)
        return target, settings, requests, properties, notifications

    def test_refresh_without_created_at_retries_original_tv_request(self):
        target, settings, requests, properties, _ = self.auth(
            {'access_token': 'new', 'refresh_token': 'refresh-new', 'expires_in': 3600})
        original = {'path': '/sync/last_activities', 'with_auth': True}
        self.assertEqual(target.call_trakt(original), {'saved': 'show'})
        self.assertEqual(original, {'path': '/sync/last_activities', 'with_auth': True})
        self.assertEqual(settings['trakt.refresh'], 'refresh-new')
        self.assertGreater(int(settings['trakt.expires']), 3600)
        self.assertEqual(len(requests), 3)
        self.assertNotIn('pov_ai_trakt_refreshing', properties)

    def test_failed_or_incomplete_refresh_preserves_both_tokens(self):
        for payload, status in (({'error': 'invalid_grant'}, 400), ({'access_token': 'new'}, 200),
                                ({'access_token': 'new', 'refresh_token': 'new', 'expires_in': 0}, 200)):
            with self.subTest(payload=payload):
                target, settings, requests, properties, _ = self.auth(payload, status)
                self.assertIsNone(target.call_trakt('/sync/watchlist'))
                self.assertEqual(settings['trakt.token'], 'old')
                self.assertEqual(settings['trakt.refresh'], 'refresh-old')
                self.assertEqual(len(requests), 2)
                self.assertNotIn('pov_ai_trakt_refreshing', properties)

    def test_public_requests_do_not_refresh_private_auth(self):
        target, settings, requests, _, _ = self.auth({})
        self.assertIsNone(target.call_trakt('/shows/trending', with_auth=False))
        self.assertEqual(len(requests), 1)
        self.assertEqual(settings['trakt.token'], 'old')

    def test_invoker_mismatch_never_unloads_profile_or_opens_modal(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'addon.xml'
            path.write_bytes(b'<addon><extension><reuselanguageinvoker>true</reuselanguageinvoker></extension></addon>')
            preferences = {'pov_fast_navigation': 'false'}; settings = {}; properties = {}
            notice = Mock(); kodi = types.SimpleNamespace(LOGINFO=1, LOGWARNING=2, log=Mock(), executebuiltin=Mock())
            gui = types.SimpleNamespace(Window=lambda _: types.SimpleNamespace(
                getProperty=lambda key: properties.get(key, ''), setProperty=properties.__setitem__),
                Dialog=lambda: types.SimpleNamespace(notification=notice, ok=Mock(side_effect=AssertionError('modal'))))
            addon = types.SimpleNamespace(getSetting=lambda key: preferences.get(key, ''), setSetting=preferences.__setitem__)
            modules = {'xbmc': kodi, 'xbmcgui': gui, 'xbmcaddon': types.SimpleNamespace(Addon=lambda _: addon),
                'xbmcvfs': types.SimpleNamespace(translatePath=lambda _: str(path)),
                'modules': types.SimpleNamespace(kodi_utils=types.SimpleNamespace(
                    get_setting=lambda key, default='': settings.get(key, default), set_setting=settings.__setitem__))}
            with patch.dict('sys.modules', modules):
                module = load('pov_invoker_safe')
                self.assertTrue(module.check()); self.assertTrue(module.check())
                self.assertIn(b'>false<', path.read_bytes())
                self.assertEqual(settings['reuse_language_invoker'], 'false')
                notice.assert_called_once(); kodi.executebuiltin.assert_not_called()
                module.manual_toggle_applied('true')
                self.assertEqual(preferences['pov_fast_navigation'], 'true')
                self.assertTrue(module.check()); self.assertIn(b'>true<', path.read_bytes())
                kodi.executebuiltin.assert_not_called()


if __name__ == '__main__':
    unittest.main()
