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


class ForegroundTests(unittest.TestCase):
    """Quick Update and the install window (field report with a log, 17 Nov 2026): the window is drawn by the
    loaded skin, so the swap waits until it has closed."""

    def finish(self, kodi, manifest_version='1.0.12', prepared=True, quiet=True, swap=None):
        config = types.SimpleNamespace(ADDON_DATA='data', ADDON_ID='plugin.program.kodipovilwizard', ADDONS='addons')
        kodi.getCondVisibility = lambda condition: (
            self.assertEqual(condition, '!System.HasActiveModalDialog + !Player.HasMedia') or quiet)
        kodi.LOGERROR = 4
        fn = _load_function(LIBS / 'modular_updater.py', '_finish_loaded_skin_swap',
                            dict(os=os, CONFIG=config, xbmc=kodi,
                                 logging=types.SimpleNamespace(log=lambda *a, **k: None)),
                            class_name='ModularUpdater')
        swaps, receipts = [], []

        def default_swap(addon_id, version, sha256):
            swaps.append((addon_id, version, sha256))
        this = types.SimpleNamespace(
            _manifest={'addons': {SKIN: {'version': manifest_version, 'sha256': 'a' * 64}}},
            _swap_loaded_skin=swap or default_swap)
        libs = types.ModuleType('resources.libs')
        libs.staged_addon_install = types.SimpleNamespace(
            prepared_matches=lambda addons, addon_id, version, sha256: (
                prepared and (addons, addon_id, version, sha256) == ('addons', SKIN, '1.0.12', 'a' * 64)))
        libs.addon_install_receipt = types.SimpleNamespace(complete=lambda *a: receipts.append(a[1]))

        def run(done=()):
            with mock.patch.dict(sys.modules, {'resources.libs': libs}):
                return fn(this, list(done))
        run.waiting = lambda: getattr(this, '_skin_swap_waiting', False)
        return run, swaps, receipts

    def test_the_package_the_window_left_waiting_goes_in_once_it_has_closed(self):
        run, swaps, receipts = self.finish(Kodi())
        self.assertEqual(run(), SKIN)
        self.assertEqual(swaps, [(SKIN, '1.0.12', 'a' * 64)])
        self.assertEqual(receipts, [SKIN])
        self.assertFalse(run.waiting())

    def test_a_promised_swap_that_did_not_happen_is_remembered_so_the_viewer_is_told(self):
        run, _swaps, _receipts = self.finish(Kodi(), quiet=False)
        self.assertIsNone(run())
        self.assertTrue(run.waiting(), 'a video or a dialog: the next start does it')
        run, _swaps, _receipts = self.finish(Kodi(), prepared=False)
        self.assertIsNone(run())
        self.assertFalse(run.waiting(), 'nothing was promised')
        source = (LIBS / 'modular_updater.py').read_text('utf-8')
        self.assertIn("elif getattr(self, '_skin_swap_waiting', False):", source)
        self.assertIn("'הסקין יעודכן בהפעלה הבאה של Kodi'", source)

    def test_nothing_happens_without_a_waiting_package_or_at_a_bad_moment(self):
        for kwargs, done in ((dict(prepared=False), ()),            # nothing was left waiting
                             (dict(quiet=False), ()),               # a video, or a dialog still up
                             (dict(manifest_version='1.0.13'), ()),  # the waiting package is not the manifest's
                             (dict(), (SKIN,))):                    # it went in by itself (not Windows)
            run, swaps, receipts = self.finish(Kodi(), **kwargs)
            self.assertIsNone(run(done))
            self.assertEqual((swaps, receipts), ([], []))
        run, swaps, receipts = self.finish(Kodi(skin='skin.estuary'))
        self.assertIsNone(run(), 'a skin the manifest does not ship')

    def test_a_swap_that_fails_is_reported_as_not_done(self):
        def broken(*_args):
            raise PermissionError(13, 'Access is denied')
        run, _swaps, receipts = self.finish(Kodi(), swap=broken)
        self.assertIsNone(run())
        self.assertTrue(run.waiting())
        self.assertEqual(receipts, [], 'the next start tries again')

    def install_job(self, kodi, prepared):
        config = types.SimpleNamespace(ADDON_DATA='data', ADDON_ID='plugin.program.kodipovilwizard', ADDONS='addons')
        kodi.LOGERROR = 4
        fn = _load_function(LIBS / 'gui/install_manager.py', '_install_job',
                            dict(os=os, CONFIG=config, xbmc=kodi, LATER='later',
                                 logging=types.SimpleNamespace(log=lambda *a, **k: None),
                                 config_apply=types.SimpleNamespace(sha256_file=lambda path: 'a' * 64)))
        libs = types.ModuleType('resources.libs')
        libs.staged_addon_install = types.SimpleNamespace(
            install=refused, prepared_matches=lambda addons, addon_id, version, sha256: (
                prepared and (addons, version, sha256) == ('addons', '1.0.12', 'a' * 64)))
        libs.addon_install_receipt = types.SimpleNamespace(begin=lambda *a: None, complete=lambda *a: None)

        def run(addon_id):
            with mock.patch.dict(sys.modules, {'resources.libs': libs}):
                return fn(dict(id=addon_id, version='1.0.12', sha256='a' * 64), 'x.zip', lambda *a: None)
        return run

    def test_the_window_says_later_for_the_loaded_skin_and_failed_for_anything_else(self):
        self.assertEqual(self.install_job(Kodi(), prepared=True)(SKIN), 'later')
        self.assertIs(self.install_job(Kodi(), prepared=False)(SKIN), False, 'no verified package: a real failure')
        self.assertIs(self.install_job(Kodi(skin='skin.estuary'), prepared=True)(SKIN), False)
        self.assertIs(self.install_job(Kodi(), prepared=True)('script.fentastic.helper'), False)

    def test_the_updater_finishes_the_swap_before_it_registers_what_was_installed(self):
        source = (LIBS / 'modular_updater.py').read_text('utf-8')
        body = source[source.index('    def execute_updates('):]
        finish = body.index('landed = self._finish_loaded_skin_swap(extracted_addons)')
        self.assertLess(body.index('run_install_manager(orchestrator_func=_orchestrator)'), finish)
        self.assertLess(finish, body.index('# 4. Database Registration for all extracted addons'))
        window = (LIBS / 'gui/install_manager.py').read_text('utf-8')
        self.assertIn("if ok == LATER:", window)
        self.assertIn("state='downloaded', status='יותקן מיד עם סגירת החלון'", window)

    def test_the_windows_marks_are_in_every_font(self):
        """A check, a cross and an hourglass are boxes in a skin whose font lacks them (a viewer's photo)."""
        window = (LIBS / 'gui/install_manager.py').read_text('utf-8')
        glyphs = window[window.index('def _glyph(state):'):window.index('def _refresh(self):')]
        for mark in ('✓', '✗', '⌛'):
            self.assertNotIn(mark, glyphs)
        layout = (LIBS.parent / 'skins/Default/1080i/DialogModularInstall.xml').read_text('utf-8')
        header = layout[layout.index('<control type="label" id="200">'):layout.index('<control type="label" id="201">')]
        self.assertIn('<label></label>', header, 'the panel carries the logo there')


if __name__ == '__main__':
    unittest.main()
