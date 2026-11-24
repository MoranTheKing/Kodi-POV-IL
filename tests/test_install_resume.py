"""Wizard 0.5.51: a first install that stopped half-way finishes, and the skin switcher offers to finish it.

New streamers, Nov 2026 (the owner: "several hit it"): Onyx on the screen, the Wizard saying the installation did
not complete, and the skin switcher answering "no build installed"; only uninstalling the app and installing it
again helped. Traced in the code:

- A resumed install runs the updater in fresh mode. When MoranSubs was already on disk and a newer one was out,
  the updater staged the new one to swap at the next Kodi start -- but fresh mode never ran that swap, and the
  completeness check demanded the new version now. So every start: "incomplete", the install marker stayed,
  startup stopped there (no updates), and the old MoranSubs yielded to the pending swap on every boot.
- The skin switcher looked at buildname alone; Onyx is switched on before buildname is written.
- Finishing read a settings snapshot that only a fresh settings-pack apply writes; without it, it failed on
  every start.
"""
import os
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from test_provisioning_gate import _load_function, ROOT

LIBS = ROOT / 'plugin.program.kodipovilwizard' / 'resources' / 'libs'


class StagedMoranSubs(unittest.TestCase):
    def fn(self, staged=True, allowed=True, messages=None):
        staged_mod = types.SimpleNamespace(prepared_matches=lambda _d, _a, ver, sha: staged and ver == '0.3.115'
                                           and sha == 'a' * 64)
        import sys
        sys.modules['resources.libs.staged_addon_install'] = staged_mod
        libs = types.ModuleType('resources.libs')
        libs.staged_addon_install = staged_mod
        sys.modules['resources.libs'] = libs
        sys.modules.setdefault('resources', types.ModuleType('resources'))
        self.addCleanup(sys.modules.pop, 'resources.libs.staged_addon_install', None)
        self.addCleanup(sys.modules.pop, 'resources.libs', None)
        log = types.SimpleNamespace(log=lambda m, **kw: (messages if messages is not None else []).append(m))
        f = _load_function(LIBS / 'modular_updater.py', '_service_staged_for_restart',
                           {'CONFIG': types.SimpleNamespace(ADDONS='addons'), 'logging': log,
                            'xbmc': types.SimpleNamespace(LOGINFO=1)}, class_name='ModularUpdater')
        updater = types.SimpleNamespace(_service_update_allowed=lambda: allowed)
        return lambda aid='service.subtitles.kodipovilai', actual='0.3.110': f(
            updater, aid, {'version': '0.3.115', 'sha256': 'A' * 64}, actual)

    def test_a_running_moransubs_with_this_manifest_s_package_staged_is_complete(self):
        messages = []
        self.assertTrue(self.fn(messages=messages)())
        self.assertEqual(messages, ['[Provisioning] MoranSubs 0.3.110 runs; 0.3.115 is staged for the next start'])

    def test_nothing_staged_is_still_missing(self):
        self.assertFalse(self.fn(staged=False)())

    def test_a_legacy_service_or_another_add_on_is_never_excused(self):
        self.assertFalse(self.fn(allowed=False)())
        self.assertFalse(self.fn()('plugin.video.pov'))
        self.assertFalse(self.fn()(actual=None))

    def test_the_completeness_check_asks_before_calling_it_missing(self):
        versions = {'plugin.video.pov': '6.11.3', 'service.subtitles.kodipovilai': '0.3.110'}
        manifest = {'addons': {'plugin.video.pov': {'version': '6.11.3'},
                               'service.subtitles.kodipovilai': {'version': '0.3.115'}},
                    'config': {'config_version': '2.0.12'}}
        messages = []
        xbmc = types.SimpleNamespace(LOGERROR=4, LOGINFO=1, getCondVisibility=lambda _c: True)
        f = _load_function(LIBS / 'modular_updater.py', '_fresh_install_complete',
                           {'CONFIG': types.SimpleNamespace(get_setting=lambda _k: '2.0.12'),
                            'logging': types.SimpleNamespace(log=lambda m, **kw: messages.append(m)),
                            'xbmc': xbmc}, class_name='ModularUpdater')

        def updater(staged):
            return types.SimpleNamespace(
                get_local_version=versions.get, OPTIONAL_SKINS=frozenset(), CORE_PROVISION_IDS=(),
                _version_tuple=lambda v: tuple(int(p) for p in v.split('.')),
                _pending_addon_receipt=lambda _a: False,
                _service_staged_for_restart=lambda aid, mod, actual: staged)
        self.assertTrue(f(updater(True), manifest))
        self.assertFalse(f(updater(False), manifest))
        self.assertIn('service.subtitles.kodipovilai (0.3.110, expected 0.3.115)', messages[-1])


class FreshModeFinishesTheSwap(unittest.TestCase):
    def test_run_update_check_no_longer_skips_the_swap_in_fresh_mode(self):
        source = (LIBS / 'modular_updater.py').read_text(encoding='utf-8')
        body = source.split('    def run_update_check(')[1].split('\n    def ')[0]
        self.assertNotIn("if not getattr(self, 'fresh', False):\n            self._complete_pending_service_handoff()",
                         body.replace('\r\n', '\n'))
        self.assertIn('        self._complete_pending_service_handoff()\n', body.replace('\r\n', '\n'))


class NoSettingsSnapshot(unittest.TestCase):
    def test_finishing_without_the_snapshot_sets_the_skin_only(self):
        activated, applied, messages = [], [], []
        build_skin = types.SimpleNamespace(activate=lambda skin: activated.append(skin) or True)
        import sys
        libs = types.ModuleType('resources.libs')
        libs.build_skin = build_skin
        sys.modules['resources.libs'] = libs
        sys.modules['resources.libs.build_skin'] = build_skin
        sys.modules.setdefault('resources', types.ModuleType('resources'))
        self.addCleanup(sys.modules.pop, 'resources.libs.build_skin', None)
        self.addCleanup(sys.modules.pop, 'resources.libs', None)
        with tempfile.TemporaryDirectory() as folder:
            xbmc = types.SimpleNamespace(Monitor=lambda: types.SimpleNamespace(waitForAbort=lambda _s: False),
                                         getCondVisibility=lambda _c: True, executebuiltin=lambda _c: None,
                                         LOGWARNING=2)
            f = _load_function(LIBS / 'fresh_install.py', 'apply_live_defaults',
                               {'os': os, 'ET': ET, 'xbmc': xbmc,
                                'CONFIG': types.SimpleNamespace(USERDATA=folder),
                                'logging': types.SimpleNamespace(log=lambda m, **kw: messages.append(m)),
                                'apply_live_settings': lambda root, strict=False: applied.append(len(root)) or (0, [])})
            self.assertTrue(f())
        self.assertEqual(activated, ['skin.povil.onyx'])
        self.assertEqual(applied, [0])
        self.assertIn('no fresh settings snapshot', messages[0])


class CompletePending(unittest.TestCase):
    def run_complete(self, finalize_result, reload_during=False, provisioned=True):
        calls = []
        with tempfile.TemporaryDirectory() as folder:
            counter = Path(folder, 'kodipovil.fresh_profile_reload')

            def finalize():
                calls.append('finalize')
                if reload_during:
                    counter.write_text('1')
                return finalize_result
            import sys
            updater = types.SimpleNamespace(is_provisioned=lambda: provisioned)
            mod = types.ModuleType('resources.libs.modular_updater')
            mod.ModularUpdater = updater
            saved = sys.modules.get('resources.libs.modular_updater')
            sys.modules['resources.libs.modular_updater'] = mod
            try:
                dialog = types.SimpleNamespace(ok=lambda _t, m: calls.append(('ok', m)),
                                               notification=lambda _t, m, **kw: calls.append(('note', m)))
                scope = {'os': os, 'xbmc': types.SimpleNamespace(LOGINFO=1, LOGERROR=4),
                         'xbmcgui': types.SimpleNamespace(Dialog=lambda: dialog),
                         'CONFIG': types.SimpleNamespace(USERDATA=folder, ADDONTITLE='Wizard'),
                         'logging': types.SimpleNamespace(log=lambda *a, **kw: None),
                         'finalize': finalize, 'begin': lambda: calls.append('begin'),
                         'provision': lambda: (calls.append('provision') or (True, [])),
                         'failure_message': lambda issues: 'failed'}
                scope['_profile_reloads'] = _load_function(LIBS / 'fresh_install.py', '_profile_reloads', scope)
                f = _load_function(LIBS / 'fresh_install.py', 'complete_pending', scope)
                result = f()
            finally:
                if saved is None:
                    sys.modules.pop('resources.libs.modular_updater', None)
                else:
                    sys.modules['resources.libs.modular_updater'] = saved
        return result, calls

    def test_a_provisioned_build_only_finishes(self):
        result, calls = self.run_complete(True)
        self.assertTrue(result)
        self.assertEqual(calls, ['finalize', ('note', 'הבילד הותקן ומוכן לשימוש')])

    def test_an_unprovisioned_build_resumes_first_and_clears_nothing(self):
        result, calls = self.run_complete(True, provisioned=False)
        self.assertEqual(calls[:3], ['begin', 'provision', 'finalize'])

    def test_a_profile_reload_mid_way_is_no_failure(self):
        result, calls = self.run_complete(False, reload_during=True)
        self.assertFalse(result)
        self.assertEqual(calls[1][0], 'note')
        self.assertIn('טוען מחדש את הפרופיל', calls[1][1])

    def test_a_real_failure_says_so(self):
        result, calls = self.run_complete(False)
        self.assertFalse(result)
        self.assertEqual(calls[1][0], 'ok')
        self.assertIn('עדיין לא הושלמה', calls[1][1])


class SkinSwitcher(unittest.TestCase):
    def run_switcher(self, pending, answer=True, completed=True):
        calls = []
        with tempfile.TemporaryDirectory() as folder:
            if pending:
                Path(folder, 'kodipovil.modular_install_started').write_text('1\n')
            import sys
            guard = types.SimpleNamespace(active_policy=lambda: None)
            fresh = types.SimpleNamespace(complete_pending=lambda: calls.append('complete') or completed)
            skin = types.SimpleNamespace(close_switch_menu=lambda: calls.append('menu') or False)
            patches = types.ModuleType('resources.libs.patches')
            patches.profile_age_guard = guard
            libs = types.ModuleType('resources.libs')
            libs.fresh_install, libs.build_skin, libs.patches = fresh, skin, patches
            mods = {'resources': types.ModuleType('resources'), 'resources.libs': libs,
                    'resources.libs.patches': patches, 'resources.libs.patches.profile_age_guard': guard,
                    'resources.libs.fresh_install': fresh, 'resources.libs.build_skin': skin}
            saved = {k: sys.modules.get(k) for k in mods}
            sys.modules.update(mods)
            try:
                dialog = types.SimpleNamespace(
                    yesno=lambda *a, **kw: calls.append(('yesno', a[1])) or answer,
                    ok=lambda *a, **kw: calls.append('ok'))
                f = _load_function(LIBS / 'wizard.py', 'build_switch_skin', {
                    'os': os, 'xbmcgui': types.SimpleNamespace(Dialog=lambda: dialog),
                    'CONFIG': types.SimpleNamespace(get_setting=lambda _k: '', USERDATA=folder,
                                                    ADDONTITLE='Wizard', COLOR2='white'),
                    'logging': types.SimpleNamespace(log_notify=lambda _t, m: calls.append(('notify', m)))})
                f()
            finally:
                for k, v in saved.items():
                    if v is None:
                        sys.modules.pop(k, None)
                    else:
                        sys.modules[k] = v
        return calls

    def test_no_install_at_all_still_says_so(self):
        self.assertEqual(self.run_switcher(pending=False), [('notify', '[COLOR white]לא מותקן בילד![/COLOR]')])

    def test_a_pending_install_is_offered_and_finished_then_the_switcher_opens(self):
        calls = self.run_switcher(pending=True)
        self.assertEqual(calls[0][0], 'yesno')
        self.assertIn('התקנת הבילד לא הושלמה', calls[0][1])
        self.assertEqual(calls[1:], ['complete', 'menu'])

    def test_not_now_or_a_failed_finish_stops_there(self):
        self.assertEqual(len(self.run_switcher(pending=True, answer=False)), 1)
        self.assertEqual(self.run_switcher(pending=True, completed=False)[1:], ['complete'])


if __name__ == '__main__':
    unittest.main()
