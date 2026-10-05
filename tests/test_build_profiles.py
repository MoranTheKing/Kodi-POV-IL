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
    def test_picker_recovers_stale_ownership_and_releases_before_loading(self):
        values = {'POVIL.ProfilesBusy': 'true'}
        home = types.SimpleNamespace(getProperty=lambda key: values.get(key, ''),
            setProperty=lambda key, value: values.update({key: value}),
            clearProperty=lambda key: values.pop(key, None))
        class Cards:
            def __init__(self, *_a): pass
            def doModal(self): self.result = ('load', 'Guest')
        loaded = []
        def load(name):
            self.assertNotIn('POVIL.ProfilesBusy', values)
            loaded.append(name)
        gui = types.SimpleNamespace(Window=lambda _: home, getCurrentWindowDialogId=lambda: 9999)
        sdk = types.SimpleNamespace(Monitor=lambda: types.SimpleNamespace(waitForAbort=lambda _: False))
        fn = _load_function(LIBS / 'build_profiles.py', 'show', dict(
            xbmcgui=gui, xbmc=sdk, WIZARD='QA', ProfileCards=Cards, load_profile=load,
            xbmcaddon=types.SimpleNamespace(Addon=lambda _: types.SimpleNamespace(getAddonInfo=lambda _: 'QA'))))
        fn()
        self.assertEqual(loaded, ['Guest'])
        values['POVIL.ProfilesBusy'] = 'true'
        gui.getCurrentWindowDialogId = lambda: 13000
        fn()
        self.assertEqual(loaded, ['Guest'])

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

    def test_login_design_preserves_native_loader_and_skin_actions(self):
        import os
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'LoginScreen.xml'
            path.write_text('<window><onload>OriginalAction</onload><onload>RunScript(single_profile_login.py)</onload>'
                            '<controls><control id="52"/></controls></window>')
            fn = _load_function(LIBS / 'build_profiles.py', 'install_login_design',
                dict(os=os, ET=ET, WIZARD='QA', xbmcaddon=types.SimpleNamespace(Addon=lambda _:
                     types.SimpleNamespace(getAddonInfo=lambda _: str(ROOT / 'plugin.program.kodipovilwizard')))))
            with mock.patch.dict('sys.modules', {'resources.libs': types.SimpleNamespace(
                    child_profiles=types.SimpleNamespace(adapt_fonts=lambda *_: None))}):
                self.assertTrue(fn(str(path)))
            first = path.read_bytes()
            xml = ET.fromstring(first)
            self.assertEqual([a.text for a in xml.findall('onload')], ['OriginalAction'])
            self.assertIsNotNone(xml.find(".//control[@id='52']"))
            self.assertEqual(xml.findtext(".//control[@id='20']/onclick"), 'ActivateWindow(ShutdownMenu)')
            self.assertNotIn('Profiles.LoadProfile', first.decode())
            with mock.patch.dict('sys.modules', {'resources.libs': types.SimpleNamespace(
                    child_profiles=types.SimpleNamespace(adapt_fonts=lambda *_: None))}):
                self.assertFalse(fn(str(path)))
            self.assertEqual(first, path.read_bytes())

    def test_old_login_hook_never_bypasses_selection_or_locks(self):
        fn = _load_function(ROOT / 'plugin.program.kodipovilwizard/single_profile_login.py', 'resume', {})
        self.assertFalse(fn())

    def test_copy_defaults_only_handles_the_two_native_questions(self):
        values = {1:'L20058',9:'L20048',11:'L20064'}
        sdk = types.SimpleNamespace(getInfoLabel=lambda key: values[int(key.split('(')[1].split(')')[0])],
            getLocalizedString=lambda ident: 'L'+str(ident), executebuiltin=mock.Mock())
        gui = types.SimpleNamespace(getCurrentWindowDialogId=lambda:10100)
        fn = _load_function(LIBS / 'build_profiles.py','copy_native_profile_defaults',
            dict(xbmc=sdk, xbmcgui=gui, is_master=lambda:True))
        self.assertTrue(fn()); values[9]='L20071'; self.assertTrue(fn())
        # Existing-settings overwrite, master PIN and unrelated questions are left alone.
        for body in ('L20104','PIN','L20118','L13111'):
            values[9]=body;self.assertFalse(fn())
        values[9]='L20048'; values[11]='Wrong button'; self.assertFalse(fn())
        self.assertEqual(sdk.executebuiltin.call_args_list,
                         [mock.call('SendClick(10100,11)',True)]*2)

    def test_login_default_is_once_and_keeps_manual_off(self):
        import os
        with tempfile.TemporaryDirectory() as raw:
            state={'login':False}
            def visible(cond):
                return state['login'] if cond=='System.HasLoginScreen' else cond in ('Window.IsActive(home)','Window.IsActive(10034)')
            def builtin(action,*_):
                if action=='SendClick(10034,4)':state['login']=True
            sdk=types.SimpleNamespace(getCondVisibility=visible,executebuiltin=mock.Mock(side_effect=builtin))
            fn=_load_function(LIBS/'build_profiles.py','repair_single_login',dict(os=os,
                _master_path=lambda:raw,is_master=lambda:True,xbmc=sdk,
                xbmcgui=types.SimpleNamespace(getCurrentWindowDialogId=lambda:0),
                _native_settings=lambda:True,profile_store=store))
            self.assertTrue(fn());self.assertTrue(state['login'])
            self.assertTrue((Path(raw)/'kodipovil.login_default_v2').exists())
            state['login']=False;sdk.executebuiltin.reset_mock()
            self.assertFalse(fn());self.assertFalse(state['login']);sdk.executebuiltin.assert_not_called()

    def test_login_default_defers_if_native_toggle_not_confirmed(self):
        import os
        with tempfile.TemporaryDirectory() as raw:
            sdk=types.SimpleNamespace(getCondVisibility=lambda c:c in ('Window.IsActive(home)','Window.IsActive(10034)'),executebuiltin=mock.Mock())
            fn=_load_function(LIBS/'build_profiles.py','repair_single_login',dict(os=os,
                _master_path=lambda:raw,is_master=lambda:True,xbmc=sdk,
                xbmcgui=types.SimpleNamespace(getCurrentWindowDialogId=lambda:0),
                _native_settings=lambda:True,profile_store=store))
            self.assertFalse(fn())
            self.assertFalse((Path(raw)/'kodipovil.login_default_v2').exists())

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
        (self.target / 'kodipovil.profile_home_ready').write_text('1')
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

    def test_old_addon_receipt_without_complete_home_still_queues_nox(self):
        (self.target / 'kodipovil.profile_addons_ready').write_text('1')
        self.seed()
        queue = ET.parse(self.target / 'kodipovil.profile_gui_defaults.xml')
        self.assertEqual(queue.findtext("setting[@id='lookandfeel.skin']"), 'skin.povil.nox')
        self.assertFalse((self.target / 'kodipovil.profile_home_ready').exists())

    def test_master_prepares_initial_nox_before_load_but_keeps_completed_skin(self):
        gui = self.target / 'guisettings.xml'
        gui.write_text('<settings><setting id="lookandfeel.skin" default="true">skin.estuary</setting>'
                       '<setting id="device.preference">KEEP</setting></settings>')
        store.seed_profile(str(self.master), self.profile, str(ARCHIVE), prepare_login=True)
        root = ET.parse(gui)
        self.assertEqual(root.findtext("setting[@id='lookandfeel.skin']"), 'skin.povil.nox')
        self.assertIsNone(root.find("setting[@id='lookandfeel.skin']").get('default'))
        self.assertEqual(root.findtext("setting[@id='device.preference']"), 'KEEP')
        (self.target / 'kodipovil.profile_home_ready').write_text('1')
        gui.write_text('<settings><setting id="lookandfeel.skin">skin.fentastic</setting></settings>')
        store.seed_profile(str(self.master), self.profile, str(ARCHIVE), prepare_login=True)
        self.assertEqual(ET.parse(gui).findtext("setting[@id='lookandfeel.skin']"), 'skin.fentastic')

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
