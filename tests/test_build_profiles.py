"""Profile repair preserves accounts, preferences and native lock semantics."""
import importlib.util
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree as ET
from test_provisioning_gate import _load_function

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / 'plugin.program.kodipovilwizard/resources/libs'
ARCHIVE = ROOT / 'plugin.program.kodipovilwizard/resources/bootstrap/config.zip'
spec = importlib.util.spec_from_file_location('profile_store', LIBS / 'profile_store.py')
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)


class ProfileStoreTests(unittest.TestCase):
    def test_parent_title_search_uses_actual_host_client_and_encoded_query(self):
        from urllib.parse import urlencode, parse_qs, urlparse
        import os
        calls = []
        host = types.ModuleType('indexers.tmdb_api')
        host.get_tmdb = lambda url: calls.append(url) or {'results': [dict(id=15, name='תוצאה'), dict(id='bad')]}
        fn = _load_function(LIBS / 'parental_profiles.py', 'search_titles',
            dict(os=os, urlencode=urlencode, xbmcaddon=types.SimpleNamespace(
                Addon=lambda _id: types.SimpleNamespace(getAddonInfo=lambda _key: '/QA/POV'))))
        original = list(sys.path)
        try:
            with mock.patch.dict(sys.modules, {'indexers.tmdb_api': host}):
                self.assertEqual(fn('tv', 'שם & עוד'), [dict(id=15, name='תוצאה')])
            params = parse_qs(urlparse(calls[0]).query)
            self.assertEqual(params['query'], ['שם & עוד'])
            self.assertEqual(params['include_adult'], ['false'])
        finally:
            sys.path[:] = original

    def test_login_hook_preserves_existing_layout_and_is_idempotent(self):
        import os
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'skin.example/xml/LoginScreen.xml'
            path.parent.mkdir(parents=True)
            path.write_text('<window><onload>OriginalAction</onload><controls><control id="52"/></controls></window>')
            fn = _load_function(LIBS / 'build_profiles.py', 'install_login_hooks',
                dict(os=os, ET=ET, SKINS=[('skin.example', 'QA')],
                     xbmcvfs=types.SimpleNamespace(translatePath=lambda _p: raw),
                     xbmc=types.SimpleNamespace(LOGWARNING=2, log=lambda *_a: None)))
            fn()
            first = path.read_bytes()
            xml = ET.fromstring(first)
            self.assertEqual(len(xml.findall('onload')), 2)
            self.assertIn('OriginalAction', first.decode())
            fn()
            self.assertEqual(first, path.read_bytes())

    def test_login_window_resumes_only_completely_unlocked_sole_master(self):
        import json
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'profiles.xml'
            requests = []
            sdk = types.SimpleNamespace(getCondVisibility=lambda _c: True,
                executeJSONRPC=lambda data: requests.append(json.loads(data)) or '{"result":"OK"}')
            fn = _load_function(ROOT / 'plugin.program.kodipovilwizard/single_profile_login.py',
                'resume', dict(xbmc=sdk, xbmcvfs=types.SimpleNamespace(translatePath=lambda _p: str(path)),
                               json=json, ET=ET))
            for lockmode, lockcode, extra, expected in (
                    ('0', '-', '', True), ('1', 'PIN_HASH', '', False),
                    ('0', 'PIN_HASH', '', False), ('0', '-', '<profile><id>1</id></profile>', False)):
                path.write_text('<profiles><profile><id>0</id><name>Master</name><lockmode>' + lockmode +
                    '</lockmode><lockcode>' + lockcode + '</lockcode></profile>' + extra + '</profiles>')
                self.assertEqual(fn(), expected)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0]['params'], dict(profile='Master', prompt=True))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.master = Path(self.tmp.name)
        self.profile = dict(id=1, name='Guest', directory='profiles/Guest', lockmode=0)
        self.target = self.master / self.profile['directory']
        self.target.mkdir(parents=True)
        (self.target / 'guisettings.xml').write_text('<settings><setting id="lookandfeel.skin">skin.estuary</setting></settings>')
        (self.master / 'kodipovil.provisioned').write_text('2.0.9')

    def seed(self):
        return store.seed_profile(str(self.master), self.profile, str(ARCHIVE))

    def test_missing_home_is_seeded_without_master_tokens_or_history(self):
        private = self.master / 'addon_data/plugin.video.pov'
        private.mkdir(parents=True)
        (private / 'settings.xml').write_text('<settings>MASTER_PRIVATE_TOKEN</settings>')
        (private / 'watched.db').write_bytes(b'master watch history')
        self.seed()
        self.assertGreater(len(ET.parse(self.target / 'favourites.xml').getroot()), 5)
        self.assertNotIn('MASTER_PRIVATE_TOKEN', (self.target / 'addon_data/plugin.video.pov/settings.xml').read_text())
        # Only the verified shipped layout DB; never account/watch/history DBs.
        self.assertEqual([p.relative_to(self.target).as_posix() for p in self.target.rglob('*.db')],
                         ['addon_data/script.fentastic.helper/cpath_cache.db'])
        self.assertEqual(ET.parse(self.target / 'guisettings.xml').findtext('setting'), 'skin.estuary')
        self.assertEqual((self.target / 'kodipovil.provisioned').read_text(), '2.0.9')

    def test_repeat_repair_preserves_target_preferences_accounts_and_deletions(self):
        (self.target / 'kodipovil.profile_addons_ready').write_text('1')
        values = {'favourites.xml': b'<favourites/>',
                  'addon_data/plugin.video.pov/settings.xml': b'<settings>GUEST_TOKEN</settings>',
                  'addon_data/skin.fentastic/settings.xml': b'<settings>GUEST_PREF</settings>'}
        for name, data in values.items():
            dest = self.target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        self.seed()
        self.seed()
        for name, data in values.items():
            self.assertEqual((self.target / name).read_bytes(), data)
        self.assertFalse((self.target / 'kodipovil.profile_gui_defaults.xml').exists())

    def test_native_copy_settings_and_empty_favourites_still_receive_build_defaults(self):
        (self.target / 'favourites.xml').write_text('<favourites/>')
        wizard = self.target / 'addon_data/plugin.program.kodipovilwizard/settings.xml'
        wizard.parent.mkdir(parents=True)
        wizard.write_text('<settings><setting id="installed">false</setting><setting id="buildname"/></settings>')
        self.seed()
        self.assertTrue((self.target / 'kodipovil.profile_gui_defaults.xml').exists())
        self.assertGreater(len(ET.parse(self.target / 'favourites.xml').getroot()), 5)
        settings = ET.parse(wizard)
        self.assertEqual(settings.findtext("setting[@id='installed']"), 'true')
        self.assertTrue(settings.findtext("setting[@id='buildname']"))

    def test_native_start_fresh_has_no_gui_file_before_first_login(self):
        (self.target / 'guisettings.xml').unlink()
        self.seed()
        values = {s.get('id'): s.text for s in ET.parse(self.target / 'guisettings.xml').getroot().findall('setting')}
        self.assertEqual(values['lookandfeel.skin'], 'skin.povil.nox')
        self.assertEqual(values['locale.language'], 'resource.language.he_il')
        self.assertEqual(values['locale.subtitlelanguage'], 'Hebrew')
        self.assertTrue((self.target / 'kodipovil.provisioned').exists())
        self.assertTrue((self.target / 'kodipovil.profile_gui_defaults.xml').exists())
        favourites = ET.parse(self.target / 'favourites.xml').getroot()
        self.assertTrue(any('mode=profiles' in (row.text or '') for row in favourites))

    def test_unprovisioned_master_or_corrupt_defaults_cannot_claim_ready(self):
        (self.master / 'kodipovil.provisioned').unlink()
        with self.assertRaises(ValueError):
            self.seed()
        (self.master / 'kodipovil.provisioned').write_text('2.0.9')
        bad = self.master / 'bad.zip'
        bad.write_bytes(b'corrupt archive')
        with self.assertRaises(ValueError):
            store.seed_profile(str(self.master), self.profile, str(bad))
        self.assertFalse((self.target / 'kodipovil.provisioned').exists())

    def test_interruption_can_resume_and_receipt_is_last(self):
        original = store.write_missing
        def interrupted(root, name, content):
            if name == 'kodipovil.provisioned':
                raise OSError('interrupted')
            return original(root, name, content)
        with mock.patch.object(store, 'write_missing', side_effect=interrupted), self.assertRaises(OSError):
            self.seed()
        self.assertFalse((self.target / 'kodipovil.provisioned').exists())
        self.seed()
        self.assertTrue((self.target / 'kodipovil.provisioned').is_file())

    def test_master_and_paths_outside_profile_are_protected(self):
        for directory in ('../outside', 'profiles/../../outside', 'special://home/', ''):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                store.seed_profile(str(self.master), dict(self.profile, directory=directory), str(ARCHIVE))
        self.assertFalse(store.seed_profile(str(self.master), dict(self.profile, id=0), str(ARCHIVE)))
        for name in ('../outside', '/outside', 'addon_data/../outside', 'a//b', 'C:/outside'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                store.write_missing(str(self.target), name, b'unsafe')

    def test_single_profile_repair_preserves_locks_and_multi_profile_chooser(self):
        master = dict(id=0, lockmode=0)
        self.assertTrue(store.lone_unlocked([master]))
        self.assertFalse(store.lone_unlocked([dict(master, lockmode=1)]))
        self.assertFalse(store.lone_unlocked([master, self.profile]))


class ProfilePermissionTests(unittest.TestCase):
    def test_secondary_add_handler_denies_direct_calls(self):
        dialog = mock.Mock()
        modules = {'xbmc': mock.Mock(), 'xbmcaddon': mock.Mock(),
                   'xbmcgui': types.SimpleNamespace(WindowXMLDialog=object, Dialog=lambda: dialog),
                   'xbmcvfs': mock.Mock(), 'resources': types.ModuleType('resources'),
                   'resources.libs': types.SimpleNamespace(profile_store=store),
                   'resources.libs.patches': types.SimpleNamespace(profile_age_guard=mock.Mock())}
        with mock.patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location('build_profiles_permission', LIBS / 'build_profiles.py')
            manager = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(manager)
            with mock.patch.object(manager, 'is_master', return_value=False), mock.patch.object(manager, '_native_settings') as native:
                manager.add_profile()
                native.assert_not_called()
                dialog.ok.assert_called_once()


class FirstLoginTests(unittest.TestCase):
    def load_manager(self, target, addons, enabled):
        calls = []
        kodi = types.SimpleNamespace(Monitor=lambda: types.SimpleNamespace(waitForAbort=lambda _: False),
            executebuiltin=mock.Mock(),
            getCondVisibility=lambda cond: cond[16:-1] in enabled)
        modules = {'xbmc': kodi, 'xbmcaddon': mock.Mock(),
            'xbmcgui': types.SimpleNamespace(WindowXMLDialog=object),
            'xbmcvfs': types.SimpleNamespace(translatePath=lambda path: str(addons if 'addons' in path else target)),
            'resources.libs': types.SimpleNamespace(profile_store=store),
            'resources.libs.patches': types.SimpleNamespace(profile_age_guard=mock.Mock())}
        with mock.patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location('profile_login_test', LIBS / 'build_profiles.py')
            manager = importlib.util.module_from_spec(spec); spec.loader.exec_module(manager)
        manager.is_master = lambda: False
        def rpc(method, params):
            if method == 'Addons.GetAddonDetails':
                return {'addon': {'enabled': params['addonid'] in enabled}}
            calls.append(params['addonid'])
            if params['addonid'] != 'service.subtitles.kodipovilai' or not self.fail_required:
                enabled.add(params['addonid'])
            return True
        manager._rpc = rpc
        return manager, calls

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.target = Path(self.tmp.name) / 'profile'; self.target.mkdir()
        self.addons = Path(self.tmp.name) / 'addons'; self.addons.mkdir()
        for ident in ('plugin.program.kodipovilwizard', 'plugin.video.pov', 'skin.povil.nox',
                      'script.fentastic.helper', 'service.subtitles.kodipovilai',
                      'plugin.program.orderfavourites-hebrew'):
            folder = self.addons / ident; folder.mkdir()
            dep = '<requires><import addon="script.fentastic.helper"/></requires>' if ident == 'skin.povil.nox' else ''
            (folder / 'addon.xml').write_text('<addon id="{}">{}</addon>'.format(ident, dep))
        self.fail_required = False

    def test_dependency_first_registration_and_receipt_preserves_later_disabled_choices(self):
        enabled = set(); manager, calls = self.load_manager(self.target, self.addons, enabled)
        self.assertTrue(manager.prepare_first_login())
        self.assertLess(calls.index('script.fentastic.helper'), calls.index('skin.povil.nox'))
        enabled.clear(); calls.clear()
        self.assertTrue(manager.prepare_first_login())
        self.assertEqual(calls, [])

    def test_required_failure_does_not_certify_ready_and_retry_can_recover(self):
        self.fail_required = True
        manager, _ = self.load_manager(self.target, self.addons, set())
        self.assertFalse(manager.prepare_first_login())
        self.assertFalse((self.target / 'kodipovil.profile_addons_ready').exists())
        self.fail_required = False
        self.assertTrue(manager.prepare_first_login())

    def test_selected_nox_with_actual_fallback_causes_a_real_skin_change(self):
        defaults = self.target / 'defaults.xml'
        defaults.write_text('<settings><setting id="lookandfeel.skin">skin.povil.nox</setting></settings>')
        selected, actual, changes = ['skin.povil.nox'], ['skin.estuary'], []
        def rpc(method, params):
            if method == 'Settings.GetSettingValue':
                return {'value': selected[0]}
            value = params['value']; changes.append(value)
            if value != selected[0]:
                actual[0] = value
            selected[0] = value
            return True
        kodi = types.SimpleNamespace(getSkinDir=lambda: actual[0],
            Monitor=lambda: types.SimpleNamespace(abortRequested=lambda: False, waitForAbort=lambda _: False),
            getCondVisibility=lambda _: True)
        fake_threads = types.SimpleNamespace(Event=threading.Event,
            Thread=lambda **_: types.SimpleNamespace(start=lambda: None, join=lambda _: None))
        fn = _load_function(LIBS / 'build_skin.py', 'activate',
            {'xbmc': kodi, 'rpc': rpc, 'threading': fake_threads,
             'SKINS': ['skin.povil.nox'], 'enable_skin': lambda _: True,
             'confirm_requested_skin': lambda _: False, 'persist_live_settings': lambda: True})
        self.assertTrue(fn('skin.povil.nox'))
        self.assertEqual(changes, ['skin.estuary', 'skin.povil.nox'])

    def test_first_login_does_not_start_arbitrary_user_services(self):
        ident = 'service.custom.disabled'
        folder = self.addons / ident; folder.mkdir()
        (folder / 'addon.xml').write_text('<addon id="{}"/>'.format(ident))
        manager, calls = self.load_manager(self.target, self.addons, set())
        self.assertTrue(manager.prepare_first_login())
        self.assertNotIn(ident, calls)

    def test_profile_loader_returns_after_native_message_without_waiting_on_departing_services(self):
        calls = []
        def rpc(method, params=None):
            calls.append((method, params))
            if method == 'Profiles.GetProfiles':
                return dict(profiles=[dict(label='Master'), dict(label='Guest')])
            if method == 'Profiles.GetCurrentProfile':
                return dict(label='Master')
            return 'OK'
        fn = _load_function(LIBS / 'build_profiles.py', 'load_profile',
            dict(_rpc=rpc, is_master=lambda: False, _wait_dialogs=lambda: True,
                 xbmc=types.SimpleNamespace(getCondVisibility=lambda _: False)))
        libs = types.SimpleNamespace(build_skin=types.SimpleNamespace(
            persist_live_settings=lambda: calls.append(('save', None)) or True))
        with mock.patch.dict('sys.modules', {'resources.libs': libs}):
            fn('Guest')
        self.assertEqual(calls[-1], ('Profiles.LoadProfile', dict(profile='Guest', prompt=True)))
        self.assertEqual(calls[-2], ('save', None))
        self.assertEqual(len(calls), 4)


if __name__ == '__main__':
    unittest.main()
