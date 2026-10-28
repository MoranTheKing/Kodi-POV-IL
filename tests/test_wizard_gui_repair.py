"""Wizard 0.4.84: Kodi's own settings back to the build's.

Field report (28 Oct 2026, Android, Kodi 21.3): Kodi came up in English with
Estuary and a 12-hour clock -- Kodi's defaults -- on a build installed in
Hebrew with NOX, and with them went the build's subtitle settings. The Wizard
now restores the build's guisettings through Kodi's Settings API (menu button)
and offers it at start-up when the language and region look reset.
"""
import importlib.util
import sys
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard'
SOURCE = ROOT / 'resources/libs/gui_repair.py'
FRESH = ROOT / 'resources/libs/fresh_install.py'


class GuiRepairTests(unittest.TestCase):
    def setUp(self):
        self.settings = {}
        self.kodi = {'locale.language': 'resource.language.en_gb', 'locale.country': 'USA (12h)'}
        self.asked, self.answers, self.toasts, self.applied, self.activated = [], [], [], [], []
        self.skin = 'skin.estuary'
        self.playing = False
        config = types.SimpleNamespace(
            ADDON_PATH=str(ROOT),
            get_setting=lambda key: self.settings.get(key, ''),
            set_setting=lambda key, value: self.settings.__setitem__(key, value))
        common = types.ModuleType('resources.libs.common')
        common.logging = types.SimpleNamespace(log=lambda *a, **k: None)
        common.config = types.SimpleNamespace(CONFIG=config)

        def rpc(text):
            import json
            req = json.loads(text)
            key = req['params'].get('setting')
            return json.dumps({'result': {'value': self.kodi.get(key)}})

        def yesno(heading, message, nolabel='', yeslabel=''):
            self.asked.append(message)
            return self.answers.pop(0) if self.answers else False

        dialog = types.SimpleNamespace(yesno=yesno, ok=lambda *a: self.asked.append(a[1]),
                                       notification=lambda *a: self.toasts.append(a[1]))
        self.installed = True
        self.events = []
        xbmc = types.SimpleNamespace(
            LOGINFO=1, LOGWARNING=2, executeJSONRPC=rpc,
            getSkinDir=lambda: self.skin,
            getCondVisibility=lambda cond: self.installed,
            Player=lambda: types.SimpleNamespace(isPlayingVideo=lambda: self.playing))
        fresh = types.ModuleType('resources.libs.fresh_install')
        fresh.apply_live_settings = lambda root: (self.applied.append(root) or self.events.append('apply')
                                                  or (len(root), []))
        build_skin = types.ModuleType('resources.libs.build_skin')
        build_skin.SKINS = ('skin.estuary', 'skin.fentastic', 'skin.povil.nox', 'skin.arctic.fuse.3')
        build_skin.activate = lambda target: self.activated.append(target) or True
        self.saves = True
        build_skin.persist_live_settings = lambda: self.events.append('save') or self.saves
        self.memory = ('', 0.0)
        watch = types.ModuleType('resources.libs.host_patch_watch')
        watch.read_skin_memory = lambda: self.memory
        libs = types.ModuleType('resources.libs')
        libs.fresh_install, libs.build_skin, libs.host_patch_watch = fresh, build_skin, watch
        modules = {
            'xbmc': xbmc,
            'xbmcgui': types.SimpleNamespace(Dialog=lambda: dialog, NOTIFICATION_INFO='info'),
            'resources': types.ModuleType('resources'),
            'resources.libs': libs,
            'resources.libs.common': common,
            'resources.libs.common.logging': common.logging,
            'resources.libs.common.config': common.config,
            'resources.libs.fresh_install': fresh,
            'resources.libs.build_skin': build_skin,
            'resources.libs.host_patch_watch': watch,
        }
        patcher = mock.patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location('gui_repair_t', SOURCE)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    # --- the build's defaults ---------------------------------------------
    def test_the_build_defaults_come_from_the_wizard_pack_without_per_device_ids(self):
        root = self.mod.build_defaults()
        ids = {s.get('id') for s in root.findall('setting')}
        self.assertEqual('resource.language.he_il', root.findtext("setting[@id='locale.language']"))
        self.assertEqual('service.subtitles.kodipovilai', root.findtext("setting[@id='subtitles.movie']"))
        for device_id in ('videoscreen.resolution', 'pictures.displayresolution', 'services.devicename',
                          'services.deviceuuid', 'addons.unknownsources', 'audiooutput.config'):
            self.assertNotIn(device_id, ids)
        self.assertFalse([i for i in ids if i.startswith('audiooutput.')])
        self.assertEqual('locale.language', root.findall('setting')[-1].get('id'))

    # --- detection ---------------------------------------------------------
    def test_english_with_a_foreign_region_looks_reset(self):
        self.assertTrue(self.mod.looks_reset())

    def test_english_by_choice_with_the_build_region_is_left_alone(self):
        self.kodi['locale.country'] = 'Israel'
        self.assertFalse(self.mod.looks_reset())

    def test_hebrew_is_not_reset(self):
        self.kodi['locale.language'] = 'resource.language.he_il'
        self.assertFalse(self.mod.looks_reset())

    # --- start-up offer ----------------------------------------------------
    def test_start_up_offers_once_and_a_no_is_remembered(self):
        self.settings['buildname'] = 'Kodi POV IL'
        self.assertFalse(self.mod.offer_after_reset())
        self.assertEqual(1, len(self.asked))
        self.assertEqual('true', self.settings['gui_reset_dismissed'])
        self.assertFalse(self.mod.offer_after_reset())
        self.assertEqual(1, len(self.asked), 'asked again after a no')
        # Hebrew again re-arms it.
        self.kodi['locale.language'] = 'resource.language.he_il'
        self.mod.offer_after_reset()
        self.assertEqual('', self.settings['gui_reset_dismissed'])

    def test_start_up_yes_restores_and_offers_the_build_skin(self):
        self.settings['buildname'] = 'Kodi POV IL'
        self.answers = [True, True]          # restore, then the skin
        self.memory = ('skin.estuary', 1.0)   # what a reset leaves in the memory
        self.assertTrue(self.mod.offer_after_reset())
        self.assertEqual(1, len(self.applied))
        self.assertEqual(['skin.povil.nox'], self.activated)
        self.assertTrue(self.toasts)

    def test_the_remembered_build_skin_is_offered(self):
        self.answers = [True, True]
        self.memory = ('skin.arctic.fuse.3', 1.0)
        self.mod.restore()
        self.assertEqual(['skin.arctic.fuse.3'], self.activated)

    def test_no_offer_without_a_build_or_during_playback(self):
        self.assertFalse(self.mod.offer_after_reset())
        self.settings['buildname'] = 'Kodi POV IL'
        self.playing = True
        self.assertFalse(self.mod.offer_after_reset())
        self.assertEqual([], self.asked)

    def test_the_menu_button_asks_first_and_cancel_changes_nothing(self):
        self.answers = [False]
        self.assertFalse(self.mod.restore())
        self.assertEqual([], self.applied)
        self.assertEqual([], self.events)

    def test_the_settings_are_saved_without_a_skin_switch(self):
        # Kodi 21's Settings API changes memory only; the field case had NOX
        # back already, so no skin switch would have saved them.
        self.skin = 'skin.povil.nox'
        self.answers = [True]
        self.assertTrue(self.mod.restore())
        self.assertEqual(['apply', 'save'], self.events)
        self.assertEqual([], self.activated)
        self.assertEqual(1, len(self.asked), 'no skin question for the active skin')

    def test_an_unsaved_repair_says_how_to_keep_it(self):
        self.skin = 'skin.povil.nox'
        self.saves = False
        self.answers = [True]
        self.assertTrue(self.mod.restore())
        self.assertEqual([], self.toasts)
        self.assertIn('תפריט הכיבוי', self.asked[-1])

    def test_a_declined_skin_still_leaves_the_settings_saved(self):
        self.answers = [True, False]
        self.assertTrue(self.mod.restore())
        self.assertEqual(['apply', 'save'], self.events)
        self.assertEqual([], self.activated)

    def test_a_skin_that_is_not_installed_is_not_offered(self):
        self.installed = False
        self.answers = [True, True]
        self.assertTrue(self.mod.restore())
        self.assertEqual(1, len(self.asked))
        self.assertEqual([], self.activated)


class StartupPlacementTests(unittest.TestCase):
    def test_the_start_up_offer_is_last_and_never_on_a_kids_profile(self):
        text = (ROOT / 'startup.py').read_text(encoding='utf-8')
        call = text.index('gui_repair.offer_after_reset()')
        self.assertGreater(call, text.index("_start_watch('POVILHostPatchWatch', _host_watch)"))
        self.assertIn('if profile_age_guard.active_policy() is None:', text[call - 200:call])
        self.assertEqual(1, text.count('offer_after_reset'))


class ApplyLiveSettingsTests(unittest.TestCase):
    """fresh_install.apply_live_settings: shared by a fresh install (strict)
    and the repair (lenient)."""

    def setUp(self):
        self.values = {'locale.language': 'resource.language.en_gb', 'subtitles.fontsize': 42,
                       'videoplayer.seeksteps': [-10, 10], 'videoplayer.convertdovi': False}
        self.reject, self.fail = set(), set()
        xbmc = self.xbmc = types.SimpleNamespace(
            Monitor=lambda: types.SimpleNamespace(abortRequested=lambda: False),
            executeJSONRPC=self.rpc, LOGINFO=1, LOGWARNING=2)
        modules = {'xbmc': xbmc, 'xbmcgui': types.SimpleNamespace(), 'xbmcvfs': types.SimpleNamespace()}
        common = types.ModuleType('resources.libs.common')
        for name in ('logging', 'tools'):
            setattr(common, name, types.SimpleNamespace(log=lambda *a, **k: None))
        common.config = types.SimpleNamespace(CONFIG=types.SimpleNamespace())
        libs = types.ModuleType('resources.libs')
        libs.common = common
        for name in ('db', 'check', 'wizard', 'youtube_platform'):
            setattr(libs, name, types.SimpleNamespace())
        modules.update({'resources': types.ModuleType('resources'), 'resources.libs': libs,
                        'resources.libs.common': common, 'resources.libs.common.logging': common.logging,
                        'resources.libs.common.tools': common.tools, 'resources.libs.common.config': common.config,
                        'resources.libs.db': libs.db, 'resources.libs.check': libs.check,
                        'resources.libs.youtube_platform': libs.youtube_platform})
        patcher = mock.patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location('fresh_t', FRESH)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.root = ET.fromstring(
            '<settings version="2">'
            '<setting id="locale.language">resource.language.he_il</setting>'
            '<setting id="subtitles.fontsize">52</setting>'
            '<setting id="videoplayer.seeksteps">-30,-10,10,30</setting>'
            '<setting id="videoplayer.convertdovi">true</setting>'
            '<setting id="lookandfeel.skin">skin.povil.nox</setting>'
            '<setting id="services.devicename">X</setting>'
            '<setting id="gone.setting">1</setting>'
            '<setting id="locale.country" default="true">USA (12h)</setting>'
            '</settings>')

    def rpc(self, text):
        import json
        req = json.loads(text)
        key = req['params']['setting']
        if req['method'] == 'Settings.GetSettingValue':
            if key not in self.values:
                return json.dumps({'error': {'code': -32602}})
            return json.dumps({'result': {'value': self.values[key]}})
        if key in self.reject:
            return json.dumps({'result': False})
        if key in self.fail:
            return json.dumps({'error': {'code': -32602}})
        self.values[key] = req['params']['value']
        return json.dumps({'result': True})

    def test_lenient_applies_what_it_can_and_lists_the_rest(self):
        self.reject.add('subtitles.fontsize')
        changed, rejected = self.mod.apply_live_settings(self.root)
        self.assertEqual(['subtitles.fontsize'], rejected)
        self.assertEqual(3, changed)
        self.assertEqual('resource.language.he_il', self.values['locale.language'])
        self.assertEqual([-30, -10, 10, 30], self.values['videoplayer.seeksteps'])
        self.assertIs(True, self.values['videoplayer.convertdovi'])
        self.assertNotIn('lookandfeel.skin', self.values)

    def test_strict_raises_on_a_rejected_setting(self):
        self.reject.add('subtitles.fontsize')
        with self.assertRaises(RuntimeError):
            self.mod.apply_live_settings(self.root, strict=True)

    def test_lenient_goes_on_past_an_api_error_or_an_unreadable_value(self):
        self.fail.add('subtitles.fontsize')
        self.root.find("setting[@id='videoplayer.seeksteps']").text = 'x'
        self.values['videoplayer.seeksteps'] = 5          # an int setting: 'x' is no int
        changed, rejected = self.mod.apply_live_settings(self.root)
        self.assertEqual(['subtitles.fontsize', 'videoplayer.seeksteps'], rejected)
        self.assertEqual('resource.language.he_il', self.values['locale.language'])
        self.assertIs(True, self.values['videoplayer.convertdovi'])
        self.assertEqual(2, changed)
        with self.assertRaises(RuntimeError):
            self.mod.apply_live_settings(self.root, strict=True)

    def test_a_fresh_install_still_waits_for_the_home(self):
        # The settings loop (and its monitor) moved out of apply_live_defaults;
        # its wait for the home after the skin still needs one.
        import os
        import tempfile
        home, waits, shown = [False], [], []
        self.xbmc.Monitor = lambda: types.SimpleNamespace(
            abortRequested=lambda: False,
            waitForAbort=lambda secs: waits.append(secs) or home.__setitem__(0, True) or False)
        self.xbmc.getCondVisibility = lambda cond: home[0]
        self.xbmc.executebuiltin = shown.append
        sys.modules['resources.libs'].build_skin = types.SimpleNamespace(activate=lambda target: True)
        with tempfile.TemporaryDirectory() as raw:
            path = os.path.join(raw, 'defaults.xml')
            ET.ElementTree(self.root).write(path)
            self.assertTrue(self.mod.apply_live_defaults(path))
        self.assertEqual(['ActivateWindow(Home)'], shown)
        self.assertEqual([0.2], waits)
        self.assertEqual('resource.language.he_il', self.values['locale.language'])


if __name__ == '__main__':
    unittest.main()
