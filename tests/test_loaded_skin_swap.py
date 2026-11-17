"""Windows: the update of the skin Kodi has loaded is swapped in with the skin unloaded (Wizard 0.5.2).

Kodi keeps the loaded skin's texture bundle open and Windows refuses to rename a folder that holds an open
file, so the staged swap of the active skin failed with "Access is denied" at every start.
"""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_provisioning_gate import _load_function  # noqa: E402

LIBS = Path(__file__).resolve().parents[1] / 'plugin.program.kodipovilwizard/resources/libs'
SKIN = 'skin.povil.onyx'
CALM = 'Window.IsActive(home) + !System.HasActiveModalDialog + !Player.HasMedia'


class Kodi:
    """The parts of xbmc the swap touches, with a log of what was asked of it."""

    LOGINFO = 1

    def __init__(self, skin=SKIN, calm=True, leaving=False):
        self.skin, self.calm, self.leaving, self.calls = skin, calm, leaving, []

    def getSkinDir(self):
        return self.skin

    def getCondVisibility(self, condition):
        assert condition == CALM, condition
        return self.calm

    def executebuiltin(self, command, wait=False):
        self.calls.append(command)

    def Monitor(self):
        return types.SimpleNamespace(waitForAbort=lambda seconds: self.leaving)


def updater(kodi, install, activate, background=True, prepared=True, installed=lambda: '1.0.11', addons='addons'):
    """ModularUpdater's three methods over a staged installer that behaves as told."""
    config = types.SimpleNamespace(ADDON_DATA='data', ADDON_ID='plugin.program.kodipovilwizard', ADDONS=addons)
    scope = dict(os=os, CONFIG=config, xbmc=kodi,
                 logging=types.SimpleNamespace(log=lambda *a, **k: None))
    names = ('_install_verified_module', '_may_swap_loaded_skin', '_swap_loaded_skin')
    methods = {name: _load_function(LIBS / 'modular_updater.py', name, scope, class_name='ModularUpdater')
               for name in names}
    this = types.SimpleNamespace(background=background, _on_disk=lambda _id: True,
                                 _runtime_addon_enabled=lambda _id: False,
                                 get_local_version=lambda _id: installed())
    for name in names[1:]:
        setattr(this, name, types.MethodType(methods[name], this))
    receipts = []
    libs = types.ModuleType('resources.libs')
    libs.staged_addon_install = types.SimpleNamespace(
        install=install, activate_prepared=activate,
        prepared_matches=lambda addons_dir, addon_id, version, sha256: (
            prepared and (addons_dir, version, sha256) == (addons, '1.0.12', 'a' * 64)))
    libs.addon_install_receipt = types.SimpleNamespace(
        begin=lambda *a: receipts.append('begin'), complete=lambda *a: receipts.append('complete'))

    def run(addon_id=SKIN):
        with mock.patch.dict(sys.modules, {'resources.libs': libs}):
            return methods['_install_verified_module'](this, 'x.zip', dict(id=addon_id, version='1.0.12'), 'a' * 64)
    return run, receipts


def refused(*_args, **_kwargs):
    raise PermissionError(13, 'Access is denied')


class LoadedSkinSwapTests(unittest.TestCase):
    def test_the_loaded_skin_is_unloaded_for_the_swap_and_loaded_again(self):
        kodi = Kodi()
        order = []

        def activate(addons, addon_id, version, sha256):
            order.append(list(kodi.calls))
            self.assertEqual((addons, addon_id, version, sha256), ('addons', SKIN, '1.0.12', 'a' * 64))
            return 209
        run, receipts = updater(kodi, refused, activate)
        self.assertEqual(run(), 209)
        self.assertEqual(order, [['UnloadSkin()']], 'the swap happens while the skin is unloaded')
        self.assertEqual(kodi.calls, ['UnloadSkin()', 'ReloadSkin()'])
        self.assertEqual(receipts, ['begin', 'complete'])

    def test_the_folder_may_need_a_moment_to_be_free(self):
        kodi = Kodi()
        tries = []

        def activate(*_args):
            tries.append(1)
            if len(tries) < 3:
                refused()
            return 209
        run, _receipts = updater(kodi, refused, activate)
        self.assertEqual(run(), 209)
        self.assertEqual(len(tries), 3)
        self.assertEqual(kodi.calls, ['UnloadSkin()', 'ReloadSkin()'])

    def test_a_swap_that_stays_refused_fails_and_the_skin_is_still_loaded_again(self):
        kodi = Kodi()
        run, receipts = updater(kodi, refused, refused)
        with self.assertRaises(PermissionError):
            run()
        self.assertEqual(kodi.calls, ['UnloadSkin()', 'ReloadSkin()'], 'never left without a skin')
        self.assertEqual(receipts, ['begin'], 'not marked done: the next start tries again')

    def test_another_error_in_the_swap_also_loads_the_skin_again(self):
        kodi = Kodi()

        def broken(*_args):
            raise ValueError('prepared package failed identity/count check')
        run, _receipts = updater(kodi, refused, broken)
        with self.assertRaises(ValueError):
            run()
        self.assertEqual(kodi.calls, ['UnloadSkin()', 'ReloadSkin()'])

    def test_nothing_is_unloaded_unless_it_is_the_loaded_skin_at_a_calm_home_in_the_background(self):
        never = lambda *_args: self.fail('no swap attempt is expected')  # noqa: E731
        for kodi, background, addon_id in ((Kodi(skin='skin.estuary'), True, SKIN),
                                           (Kodi(), True, 'script.fentastic.helper'),
                                           (Kodi(calm=False), True, SKIN),      # a video, a dialog, another window
                                           (Kodi(), False, SKIN)):
            run, receipts = updater(kodi, refused, never, background=background)
            with self.assertRaises(PermissionError):
                run(addon_id)
            self.assertEqual(kodi.calls, [])
            self.assertEqual(receipts, ['begin'])

    def test_a_refusal_that_left_no_verified_package_unloads_nothing(self):
        """An old backup's removal, a scanner during extraction: unloading the skin would gain nothing."""
        kodi = Kodi()
        run, receipts = updater(kodi, refused, lambda *_a: self.fail('nothing to swap'), prepared=False)
        with self.assertRaises(PermissionError):
            run()
        self.assertEqual(kodi.calls, [])
        self.assertEqual(receipts, ['begin'])

    def test_a_swap_whose_old_copy_could_not_be_removed_still_counts(self):
        kodi = Kodi()
        with tempfile.TemporaryDirectory() as raw:
            skin = Path(raw) / SKIN
            (skin / 'xml').mkdir(parents=True)
            for name in ('addon.xml', 'xml/Home.xml', 'xml/VideoOSD.xml'):
                (skin / name).write_text('x')
            version = ['1.0.11']

            def activate(*_args):
                version[0] = '1.0.12'       # both renames happened; the backup's removal was refused
                refused()
            run, receipts = updater(kodi, refused, activate, installed=lambda: version[0], addons=raw)
            self.assertEqual(run(), 3)
        self.assertEqual(kodi.calls, ['UnloadSkin()', 'ReloadSkin()'])
        self.assertEqual(receipts, ['begin', 'complete'])

    def test_kodi_closing_during_the_swap_is_not_asked_to_load_a_skin(self):
        kodi = Kodi(leaving=True)
        run, _receipts = updater(kodi, refused, refused)
        with self.assertRaises(PermissionError):
            run()
        self.assertEqual(kodi.calls, ['UnloadSkin()'])

    def test_a_swap_that_works_touches_nothing(self):
        kodi = Kodi()
        run, receipts = updater(kodi, lambda *a, **k: 209, None)
        self.assertEqual(run(), 209)
        self.assertEqual(kodi.calls, [])
        self.assertEqual(receipts, ['begin', 'complete'])


if __name__ == '__main__':
    unittest.main()
