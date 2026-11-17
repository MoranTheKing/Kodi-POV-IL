"""A skin that left the build (Wizard 0.5.0): every profile moves to the
default skin and the old skin's files leave the device."""

import importlib.util
import re
import os
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / 'plugin.program.kodipovilwizard/resources/libs'
# the skin that left: named once, in the module itself
OLD = re.search(r"RETIRED = \('([^']+)',\)", (LIBS / 'skin_retirement.py').read_text(encoding='utf-8')).group(1)
NEW = 'skin.povil.onyx'


def gui(skin):
    return '<settings version="2"><setting id="lookandfeel.skin">%s</setting><setting id="x">1</setting></settings>' % skin


class Kodi(object):
    """One Kodi with a master profile and a second profile on disk."""

    def __init__(self, active_skin=OLD, other_skin=OLD, onyx_on_disk=False, install_ok=True,
                 playing=0, repairs_done=True, child=False, active='master', switch_ok=True):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.master = self.home / 'userdata'
        self.other = self.master / 'profiles' / 'Dana'
        self.addons = self.home / 'addons'
        for folder in (self.master, self.other, self.addons / 'packages'):
            folder.mkdir(parents=True)
        (self.master / 'kodipovil.provisioned').write_text('1')
        (self.master / 'guisettings.xml').write_text(gui(active_skin if active == 'master' else other_skin))
        (self.other / 'guisettings.xml').write_text(gui(other_skin if active == 'master' else active_skin))
        for folder in (self.master, self.other):
            (folder / 'addon_data' / OLD).mkdir(parents=True)
            (folder / 'addon_data' / OLD / 'settings.xml').write_text('<settings/>')
        (self.addons / OLD / 'xml').mkdir(parents=True)
        (self.addons / OLD / 'addon.xml').write_text('<addon id="%s"/>' % OLD)
        (self.addons / 'packages' / (OLD + '-1.0.22.zip')).write_text('z')
        (self.addons / 'packages' / 'plugin.video.pov-6.zip').write_text('z')
        if onyx_on_disk:
            self.put_onyx()
        self.active = self.master if active == 'master' else self.other
        self.skin = active_skin
        self.install_ok, self.playing, self.repairs_done, self.child = install_ok, playing, repairs_done, child
        self.switch_ok = switch_ok
        self.calls, self.log, self.dialogs, self.builtins = [], [], [], []
        self.waited = 0

    def put_onyx(self):
        (self.addons / NEW).mkdir(parents=True, exist_ok=True)
        (self.addons / NEW / 'addon.xml').write_text('<addon id="%s"/>' % NEW)

    def load(self):
        k = self

        class Monitor(object):
            def waitForAbort(self, seconds):
                k.waited += seconds
                if k.playing:
                    k.playing -= 1
                return False

        def cond(text):
            return bool(k.playing) if text == 'Player.HasMedia' else False

        xbmc = types.ModuleType('xbmc')
        xbmc.LOGINFO, xbmc.LOGWARNING = 1, 2
        xbmc.log = lambda text, level=1: k.log.append(text)
        xbmc.Monitor = Monitor
        xbmc.getSkinDir = lambda: k.skin
        xbmc.getCondVisibility = cond
        xbmc.executebuiltin = lambda text, wait=False: k.builtins.append(text)
        xbmcgui = types.ModuleType('xbmcgui')
        xbmcgui.Window = lambda ident: types.SimpleNamespace(
            getProperty=lambda name: '1' if k.repairs_done else '')
        xbmcgui.Dialog = lambda: types.SimpleNamespace(ok=lambda title, text: k.dialogs.append(text))
        xbmcvfs = types.ModuleType('xbmcvfs')
        xbmcvfs.translatePath = lambda path: {
            'special://masterprofile/': str(k.master), 'special://profile/': str(k.active),
            'special://home/addons/': str(k.addons)}[path]

        def ensure_onyx():
            k.calls.append('install')
            if k.install_ok:
                k.put_onyx()
            return k.install_ok

        def switch(target):
            k.calls.append('switch:' + target)
            if not k.switch_ok:
                return False
            k.skin = target
            (k.active / 'guisettings.xml').write_text(gui(target))
            return True

        wizard = types.ModuleType('resources.libs.wizard')
        wizard.ensure_onyx_installed = ensure_onyx
        build_skin = types.ModuleType('resources.libs.build_skin')
        build_skin.switch = switch
        store = types.ModuleType('resources.libs.profile_store')
        store.registered_profiles = lambda master: [dict(id=0, directory=''), dict(id=1, directory='profiles/Dana')]
        store.profile_path = lambda master, profile: (
            os.path.realpath(master) if profile['id'] == 0 else os.path.realpath(os.path.join(master, profile['directory'])))
        guard = types.ModuleType('resources.libs.patches.profile_age_guard')
        guard.active_policy = lambda: {'blocked': False} if k.child else None
        patches = types.ModuleType('resources.libs.patches')
        patches.profile_age_guard = guard
        libs = types.ModuleType('resources.libs')
        libs.wizard, libs.build_skin, libs.profile_store, libs.patches = wizard, build_skin, store, patches
        resources = types.ModuleType('resources')
        resources.libs = libs
        self.modules = {'xbmc': xbmc, 'xbmcgui': xbmcgui, 'xbmcvfs': xbmcvfs, 'resources': resources,
                        'resources.libs': libs, 'resources.libs.wizard': wizard,
                        'resources.libs.build_skin': build_skin, 'resources.libs.profile_store': store,
                        'resources.libs.patches': patches, 'resources.libs.patches.profile_age_guard': guard}
        with patch.dict(sys.modules, self.modules):
            spec = importlib.util.spec_from_file_location('skin_retirement_test', LIBS / 'skin_retirement.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        return module

    def run(self):
        module = self.load()
        with patch.dict(sys.modules, self.modules):
            module.run()
        return module

    def saved(self, folder):
        return ET.parse(folder / 'guisettings.xml').getroot().findtext("setting[@id='lookandfeel.skin']")


class SkinRetirementTests(unittest.TestCase):
    def kodi(self, **kwargs):
        k = Kodi(**kwargs)
        self.addCleanup(k.tmp.cleanup)
        return k

    def test_a_profile_on_the_old_skin_moves_and_the_files_leave(self):
        k = self.kodi()
        k.run()
        self.assertEqual(k.calls, ['install', 'switch:' + NEW])
        self.assertEqual(k.skin, NEW)
        self.assertEqual(k.saved(k.other), NEW, 'the profile that is not loaded is rewritten on disk')
        self.assertTrue((k.other / 'kodipovil.skin_retired').is_file())
        self.assertFalse((k.addons / OLD).exists())
        self.assertFalse((k.master / 'addon_data' / OLD).exists())
        self.assertFalse((k.other / 'addon_data' / OLD).exists())
        self.assertFalse((k.addons / 'packages' / (OLD + '-1.0.22.zip')).exists())
        self.assertTrue((k.addons / 'packages' / 'plugin.video.pov-6.zip').exists())
        self.assertIn('UpdateLocalAddons', k.builtins)
        self.assertEqual(len(k.dialogs), 1)
        self.assertIn('Onyx', k.dialogs[0])
        self.assertIn('x', [row.get('id') for row in ET.parse(k.other / 'guisettings.xml').getroot()],
                      'every other setting of the profile is kept')

    def test_without_the_new_skin_nothing_changes_and_the_next_start_tries_again(self):
        k = self.kodi(install_ok=False)
        k.run()
        self.assertEqual(k.skin, OLD)
        self.assertNotIn('switch:' + NEW, k.calls)
        self.assertTrue((k.addons / OLD / 'addon.xml').is_file(), 'the skin in use is never deleted')
        self.assertEqual(k.dialogs, [])
        self.assertEqual(k.saved(k.other), OLD, 'no profile is pointed at a skin that is not installed')
        self.assertFalse((k.other / 'kodipovil.skin_retired').exists())
        k.install_ok = True
        k.calls[:] = []
        k.run()
        self.assertEqual(k.skin, NEW)
        self.assertFalse((k.addons / OLD).exists())

    def test_it_waits_for_the_video_to_end(self):
        k = self.kodi(playing=5)
        k.run()
        self.assertEqual(k.skin, NEW)
        # the fake video ends after five waits; then six quiet seconds
        self.assertGreaterEqual(k.waited, 4 * 2 + 6)
        self.assertEqual(k.calls, ['install', 'switch:' + NEW])

    def test_a_profile_on_another_skin_keeps_it_and_still_gets_the_default_skin_installed(self):
        k = self.kodi(active_skin='skin.fentastic', other_skin='skin.estuary')
        k.run()
        self.assertEqual(k.skin, 'skin.fentastic')
        self.assertEqual(k.calls, ['install'])
        self.assertEqual(k.saved(k.other), 'skin.estuary')
        self.assertFalse((k.other / 'kodipovil.skin_retired').exists())
        self.assertFalse((k.addons / OLD).exists())
        self.assertEqual(k.dialogs, [])

    def test_a_marked_profile_finishes_the_move_at_its_own_start(self):
        # its settings were rewritten while it was not loaded; the new skin is
        # disabled in its own add-on database, so Kodi came up on Estuary
        k = self.kodi(active='other', active_skin='skin.estuary', other_skin='skin.fentastic', onyx_on_disk=True)
        (k.other / 'guisettings.xml').write_text(gui(NEW))
        (k.other / 'kodipovil.skin_retired').write_text(NEW)
        k.run()
        self.assertEqual(k.calls, ['install', 'switch:' + NEW])
        self.assertFalse((k.other / 'kodipovil.skin_retired').exists())
        self.assertEqual(k.dialogs, [], 'it was not on the old skin in this start: no notice')

    def test_a_marked_profile_that_chose_another_skin_is_left_alone(self):
        k = self.kodi(active='other', active_skin='skin.fentastic', other_skin='skin.fentastic', onyx_on_disk=True)
        (k.other / 'kodipovil.skin_retired').write_text(NEW)
        k.run()
        self.assertEqual(k.skin, 'skin.fentastic')
        self.assertNotIn('switch:' + NEW, k.calls)
        self.assertFalse((k.other / 'kodipovil.skin_retired').exists())

    def test_the_loaded_profile_side_files_stop_naming_the_old_skin(self):
        k = self.kodi()
        (k.master / 'kodipovil.profile_gui_defaults.xml').write_text(gui(OLD))
        memory = k.master / 'addon_data' / 'plugin.program.kodipovilwizard'
        memory.mkdir(parents=True)
        (memory / 'host_watch_skin.json').write_text('{"skin": "%s", "row": 3}' % OLD)
        k.run()
        self.assertEqual(ET.parse(k.master / 'kodipovil.profile_gui_defaults.xml').getroot()
                         .findtext("setting[@id='lookandfeel.skin']"), NEW)
        import json
        self.assertEqual(json.loads((memory / 'host_watch_skin.json').read_text()), {'skin': NEW, 'row': 3})

    def test_a_switch_that_keeps_failing_stops_after_three_starts(self):
        k = self.kodi(switch_ok=False, onyx_on_disk=True)
        for _ in range(5):
            k.run()
        self.assertEqual(k.calls.count('switch:' + NEW), 3)
        self.assertEqual(k.skin, OLD)
        self.assertTrue((k.addons / OLD / 'addon.xml').is_file())
        # the profile is moved by hand (Switch Skin): the files leave at the next start
        k.skin = 'skin.fentastic'
        (k.master / 'guisettings.xml').write_text(gui('skin.fentastic'))
        k.run()
        self.assertFalse((k.addons / OLD).exists())

    def test_a_marked_profile_moved_by_hand_after_three_failures_is_cleared(self):
        k = self.kodi(active='other', active_skin='skin.estuary', other_skin='skin.fentastic',
                      onyx_on_disk=True, switch_ok=False)
        (k.other / 'kodipovil.skin_retired').write_text(NEW)
        for _ in range(4):
            k.run()
        self.assertEqual(k.calls.count('switch:' + NEW), 3)
        k.skin = 'skin.fentastic'
        k.run()
        self.assertFalse((k.other / 'kodipovil.skin_retired').exists())
        self.assertFalse((k.other / 'kodipovil.skin_retired.tries').exists())

    def test_without_the_repairs_flag_it_goes_on_after_five_minutes(self):
        k = self.kodi(repairs_done=False)
        k.run()
        self.assertGreaterEqual(k.waited, 300)
        self.assertEqual(k.skin, NEW)

    def test_with_the_repairs_flag_it_does_not_wait_for_it(self):
        k = self.kodi()
        k.run()
        self.assertLess(k.waited, 30)

    def test_nothing_left_to_do_costs_nothing(self):
        k = self.kodi(active_skin=NEW, other_skin='skin.fentastic', onyx_on_disk=True)
        import shutil
        shutil.rmtree(k.addons / OLD)
        k.run()
        self.assertEqual((k.calls, k.waited, k.builtins), ([], 0, []))

    def test_a_kids_profile_moves_without_the_notice(self):
        k = self.kodi(child=True)
        k.run()
        self.assertEqual(k.skin, NEW)
        self.assertEqual(k.dialogs, [])

    def test_an_installation_that_is_not_finished_is_left_alone(self):
        k = self.kodi()
        (k.master / 'kodipovil.provisioned').unlink()
        k.run()
        self.assertEqual((k.calls, k.skin), ([], OLD))

    def test_the_build_no_longer_offers_the_old_skin(self):
        for name in ('build_skin.py', 'build_profiles.py', 'child_profiles.py', 'wizard.py', 'modular_updater.py',
                     'fresh_install.py', 'profile_store.py', 'parental_profiles.py', 'gui_repair.py'):
            self.assertNotIn(OLD, (LIBS / name).read_text(encoding='utf-8'), name)
        self.assertIn("DEFAULT_SKIN = 'skin.povil.onyx'", (LIBS / 'build_skin.py').read_text(encoding='utf-8'))
        self.assertFalse((ROOT / OLD).exists())
        startup = (ROOT / 'plugin.program.kodipovilwizard/startup.py').read_text(encoding='utf-8')
        self.assertIn("_start_watch('POVILSkinRetirement', skin_retirement.run)", startup)
        gui_defaults = (ROOT / 'userdata/guisettings.xml').read_text(encoding='utf-8')
        self.assertIn('<setting id="lookandfeel.skin">skin.povil.onyx</setting>', gui_defaults)


if __name__ == '__main__':
    unittest.main()
