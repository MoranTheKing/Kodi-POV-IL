"""Arctic Fuse 3 keeps the build's Hebrew and child gating after it updates itself.

Field report (22 Oct 2026): after AF3 updated itself (3.4.4 -> 3.4.6) the
login screen showed "last login" as boxes and Hebrew inside Kodi came back
only after one or more restarts. Kodi replaces the whole skin folder on an
update: MoranSubs' Hebrew font and edits and the Wizard's child-profile
gating go with it. The Wizard's host watch now repairs right after the
update; MoranSubs' repair_af3.py does its part without racing its own
start-up pass, without reloading the skin during playback and without
retry loops.
"""
import importlib.util
import json
import os
import re
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / 'plugin.program.kodipovilwizard/resources/libs'
MS = ROOT / 'service.subtitles.kodipovilai'
AF3 = 'skin.arctic.fuse.3'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode('utf-8'))


class HostWatchAF3(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addons = Path(tmp.name) / 'addons'
        self.xbmc = types.SimpleNamespace(LOGINFO=1, LOGWARNING=2, log=Mock(), executebuiltin=Mock())
        mods = patch.dict(sys.modules, {'xbmc': self.xbmc,
                                        'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)})
        mods.start()
        self.addCleanup(mods.stop)
        self.watch = load('af3_watch', LIBS / 'host_patch_watch.py')

    def install_af3(self, ours=True, hooks=None):
        write(self.addons / AF3 / 'addon.xml', '<addon id="%s" version="3.4.6"/>' % AF3)
        write(self.addons / AF3 / '1080i' / 'Font.xml',
              '<fonts>%s</fonts>' % ('NotoSans-Regular.ttf' if ours else 'Inter-Regular.ttf'))
        hooked = ours if hooks is None else hooks
        write(self.addons / AF3 / '1080i' / 'Home.xml',
              '<window>%s<controls/></window>' % (
                  '<onload>RunScript(special://home/addons/plugin.program.kodipovilwizard/'
                  'profile_bootstrap.py)</onload>' if hooked else ''))

    def test_font_check(self):
        self.assertTrue(self.watch.af3_font_current(str(self.addons)))     # no AF3: nothing to do
        self.install_af3(ours=False)
        self.assertFalse(self.watch.af3_font_current(str(self.addons)))
        self.install_af3(ours=True)
        self.assertTrue(self.watch.af3_font_current(str(self.addons)))

    def test_hooks_check(self):
        self.assertTrue(self.watch.af3_hooks_current(str(self.addons)))    # no AF3: nothing to do
        self.install_af3(ours=True, hooks=False)
        self.assertFalse(self.watch.af3_hooks_current(str(self.addons)))
        self.install_af3(ours=True, hooks=True)
        self.assertTrue(self.watch.af3_hooks_current(str(self.addons)))
        (self.addons / AF3 / '1080i' / 'Home.xml').unlink()
        self.assertFalse(self.watch.af3_hooks_current(str(self.addons)))

    def af3_repair(self, moransubs_result):
        calls = []
        profiles = types.SimpleNamespace(install_login_hooks=lambda: calls.append('login_hooks'))
        with patch.dict(sys.modules, {'resources.libs': types.SimpleNamespace(build_profiles=profiles)}), \
                patch.object(self.watch, 'run_moransubs_repair',
                             side_effect=lambda *a, **k: calls.append((a[3], k)) or moransubs_result):
            result = self.watch.repair_af3(str(self.addons), None, None)
        return result, calls

    def test_wizard_hooks_then_moransubs(self):
        result, calls = self.af3_repair(True)
        self.assertTrue(result)
        self.assertEqual(calls[0], 'login_hooks')          # child gating, bootstrap, login design
        self.assertEqual(calls[1][0], 'repair_af3.py')
        self.assertTrue(calls[1][1]['missing'])             # an older MoranSubs is not a failure

    def test_best_effort_never_a_retry_loop(self):
        for moransubs in (False, True):                     # no ack / bad ack: logged, accepted
            self.assertTrue(self.af3_repair(moransubs)[0])
        self.assertIsNone(self.af3_repair(None)[0])          # Kodi closing

    def repair_changed(self, old, new):
        engine = Mock(return_value=types.SimpleNamespace(run=lambda: {}))
        with patch.dict(sys.modules, {'resources.libs.patch_engine': types.SimpleNamespace(PatchEngine=engine)}), \
                patch.object(self.watch, 'repair_af3', return_value=True) as af3:
            result = self.watch.repair_changed(str(self.addons), old, new, None, None)
        return result, engine.called, af3.called

    def test_af3_change_alone_skips_the_patch_engine(self):
        old = (('plugin.video.pov', 1, 1), ('plugin.video.umbrella', None, None), (AF3, 1, 1))
        self.assertEqual(self.repair_changed(old, old[:2] + ((AF3, 2, 1),)), (True, False, True))
        self.assertEqual(self.repair_changed(old, (('plugin.video.pov', 2, 1),) + old[1:]),
                         (True, True, False))

    def test_closing_kodi_during_the_af3_repair_is_not_accepted(self):
        old = (('plugin.video.pov', 1, 1), ('plugin.video.umbrella', None, None), (AF3, 1, 1))
        with patch.dict(sys.modules, {'resources.libs.patch_engine': types.SimpleNamespace(PatchEngine=Mock())}), \
                patch.object(self.watch, 'repair_af3', return_value=None):
            self.assertFalse(self.watch.repair_changed(str(self.addons), old, old[:2] + ((AF3, 2, 1),), None, None))

    def test_an_update_before_the_watch_started_is_repaired_on_the_first_settled_poll(self):
        for ours, hooks in ((False, False), (True, False)):
            with self.subTest(font=ours, hooks=hooks):
                self.install_af3(ours=ours, hooks=hooks)
                self.start_up_repair()

    def test_nothing_to_repair_at_start_up(self):
        self.install_af3(ours=True, hooks=True)
        self.assertIsNone(self.start_up_repair(expect=False))

    def start_up_repair(self, expect=True):
        rows = (('plugin.video.pov', 1, 1), ('plugin.video.umbrella', None, None), (AF3, 5, 5))
        props = {}
        window = types.SimpleNamespace(getProperty=lambda k: props.get(k, ''),
                                       setProperty=lambda k, v: props.__setitem__(k, v),
                                       clearProperty=lambda k: props.pop(k, None))
        monitor = types.SimpleNamespace(waitForAbort=Mock(side_effect=[False, False, True]),
                                        abortRequested=lambda: False)
        self.xbmc.Monitor = lambda: monitor
        self.xbmc.Player = lambda: types.SimpleNamespace(isPlayingVideo=lambda: False)
        vfs = types.SimpleNamespace(translatePath=lambda p: 'profile' if p == 'special://profile/'
                                    else str(self.addons))
        with patch.dict(sys.modules, {'xbmcgui': types.SimpleNamespace(Window=lambda n: window),
                                      'xbmcvfs': vfs}), \
                patch.object(self.watch, 'signature', return_value=rows), \
                patch.object(self.watch, 'repair_changed', return_value=True) as repair:
            self.watch.run()
        if not expect:
            repair.assert_not_called()
            return None
        repair.assert_called_once()
        previous, current = repair.call_args[0][1:3]
        self.assertEqual(dict((r[0], r[1:]) for r in previous)[AF3], (-1, -1))
        self.assertEqual(current, rows)
        return True

    def test_moransubs_repair_runner(self):
        props = {}
        window = types.SimpleNamespace(getProperty=lambda k: props.get(k, ''),
                                       clearProperty=lambda k: props.pop(k, None))
        monitor = types.SimpleNamespace(waitForAbort=lambda s: False)
        self.assertTrue(self.watch.run_moransubs_repair(str(self.addons), window, monitor, 'repair_af3.py',
                                                        'kodipovil.af3_repair.', missing=True))
        write(self.addons / 'service.subtitles.kodipovilai' / 'repair_af3.py', '')

        def run(action):
            ack = action.rsplit(', ', 1)[1].rstrip(')')
            props[ack] = json.dumps({'ok': True})
        self.xbmc.executebuiltin = run
        self.assertTrue(self.watch.run_moransubs_repair(str(self.addons), window, monitor, 'repair_af3.py',
                                                        'kodipovil.af3_repair.', wait=3))
        self.assertEqual(props, {})


class MoranSubsRepairScript(unittest.TestCase):
    """service.subtitles.kodipovilai/repair_af3.py, run with fake Kodi modules."""

    def run_script(self, home_status='patched', props=None, playing=(), settled=True, active=True,
                   rebuild=True):
        props = {} if props is None else props
        props.setdefault('kodipovil_startup_repairs_done', '0.3.44')
        calls = []
        playing = list(playing)
        window = types.SimpleNamespace(getProperty=lambda k: props.get(k, ''),
                                       setProperty=lambda k, v: props.__setitem__(k, v),
                                       clearProperty=lambda k: props.pop(k, None))
        clock = [1000.0]

        def wait(seconds):                                     # simulated time, no real sleeping
            calls.append(('wait', seconds))
            clock[0] += seconds
            return False
        xbmc = types.SimpleNamespace(
            Monitor=lambda: types.SimpleNamespace(waitForAbort=wait),
            Player=lambda: types.SimpleNamespace(isPlaying=lambda: playing.pop(0) if playing else False))
        home = types.SimpleNamespace(
            ensure_patched=lambda: calls.append('home') or home_status,
            _is_af3_active=lambda: active,
            _rebuild_af3_shortcuts=lambda: calls.append('rebuild') or rebuild)
        lib = types.SimpleNamespace(
            kodi_utils=types.SimpleNamespace(log=lambda msg: calls.append(('log', msg))),
            af3_dialog_subtitles_patcher=types.SimpleNamespace(ensure_patched=lambda: 'already_patched'),
            af3_home_patcher=home,
            pov_reload=types.SimpleNamespace(wait_until_settled=lambda timeout: settled))
        mods = {'xbmc': xbmc, 'xbmcgui': types.SimpleNamespace(Window=lambda n: window),
                'resources': types.SimpleNamespace(lib=lib), 'resources.lib': lib}
        for name in ('kodi_utils', 'af3_dialog_subtitles_patcher', 'af3_home_patcher', 'pov_reload'):
            mods['resources.lib.' + name] = getattr(lib, name)
        import time
        with patch.dict(sys.modules, mods), patch.object(sys, 'argv', ['repair_af3.py', 'kodipovil.af3_repair.x']), \
                patch.object(time, 'monotonic', lambda: clock[0]):
            runpy.run_path(str(MS / 'repair_af3.py'), run_name='__main__')
        ack = props.get('kodipovil.af3_repair.x')
        return (json.loads(ack)['ok'] if ack else None), calls, props

    def test_statuses_cover_the_patchers_real_results(self):
        source = (MS / 'repair_af3.py').read_text('utf-8')
        good = set(re.findall(r"'([a-z_]+)'", source[source.index('GOOD = {'):source.index('}', source.index('GOOD = {'))]))
        transient = {'read_failed', 'write_failed', 'no_kodi', 'rebuild_deferred_pov_cycling',
                     'rebuild_deferred_quick_update_notice', ''}
        for name in ('af3_dialog_subtitles_patcher.py', 'af3_home_patcher.py'):
            text = (MS / 'resources/lib' / name).read_text('utf-8')
            body = text[text.index('def ensure_patched'):]
            statuses = set(re.findall(r"return '([a-z_]*)'", body.split('\ndef ')[0]))
            self.assertTrue(statuses)
            self.assertEqual(statuses - good - transient, set(), name)
        self.assertIn('unmatched', good)                      # a moved anchor is not retried for ever

    def test_patched_run_acks_ok_and_releases_the_lock(self):
        ok, calls, props = self.run_script('patched_rebuilt')
        self.assertTrue(ok)
        self.assertNotIn('kodipovil.af3_repair.running', props)

    def test_waits_for_the_start_up_pass_and_for_playback(self):
        ok, calls, _ = self.run_script(props={'kodipovil_startup_repairs_done': ''}, playing=[True, True])
        self.assertTrue(ok)
        waits = [c for c in calls if isinstance(c, tuple) and c[0] == 'wait']
        self.assertGreaterEqual(len(waits), 90)               # 180 s start-up window, 2 s steps
        self.assertIn(('wait', 5), waits)                     # then playback, 5 s steps
        self.assertLess(calls.index(('wait', 5)), calls.index('home'))

    def test_a_deferred_rebuild_is_finished_here(self):
        ok, calls, _ = self.run_script('rebuild_deferred_pov_cycling')
        self.assertTrue(ok)
        self.assertEqual(calls.count('rebuild'), 1)

    def test_a_deferred_rebuild_that_cannot_finish_is_reported(self):
        ok, calls, _ = self.run_script('rebuild_deferred_pov_cycling', settled=False)
        self.assertFalse(ok)
        self.assertNotIn('rebuild', calls)

    def test_a_second_run_while_one_is_working_does_nothing(self):
        ok, calls, _ = self.run_script(props={'kodipovil.af3_repair.running': '900.0'})   # clock 1000
        self.assertTrue(ok)
        self.assertNotIn('home', calls)

    def test_a_stale_lock_does_not_block(self):
        ok, calls, _ = self.run_script(props={'kodipovil.af3_repair.running': '50.0'})
        self.assertTrue(ok)
        self.assertIn('home', calls)

    def test_playback_must_stay_off_for_30_seconds(self):
        # playing, stopped once (an autoplay gap), playing again, then stopped for good
        ok, calls, _ = self.run_script(playing=[True, False, True])
        self.assertTrue(ok)
        before = calls[:calls.index('home')]
        waits = [c for c in before if isinstance(c, tuple) and c == ('wait', 5)]
        self.assertGreaterEqual(len(waits), 8)              # >= 30 s of quiet after the last play


class AF3EstuaryRestore(unittest.TestCase):
    """Kodi can drop a profile to Estuary while it installs an AF3 update
    (QA, 22 Oct 2026). The watch puts it back -- once, through the Wizard's
    guarded Switch Skin, and never over a deliberate Estuary choice."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.addons = self.root / 'addons'
        self.profile = self.root / 'profile'
        self.skins = []
        self.skin = AF3
        self.xbmc = types.SimpleNamespace(LOGINFO=1, LOGWARNING=2, log=Mock(), executebuiltin=Mock(),
                                          getSkinDir=lambda: self.skins.pop(0) if self.skins else self.skin)
        vfs = types.SimpleNamespace(translatePath=lambda p: str(self.profile / p.split('special://profile/')[1])
                                    if p.startswith('special://profile/') else str(self.addons) + '/')
        mods = patch.dict(sys.modules, {'xbmc': self.xbmc, 'xbmcvfs': vfs})
        mods.start()
        self.addCleanup(mods.stop)
        self.watch = load('af3_restore_watch', LIBS / 'host_patch_watch.py')
        write(self.addons / AF3 / 'addon.xml', '<addon/>')
        write(self.addons / AF3 / '1080i' / 'Font.xml', 'NotoSans-Regular.ttf')
        write(self.addons / AF3 / '1080i' / 'Home.xml', 'profile_bootstrap.py')   # hooks in place
        def switch(target):
            if self.switch_ok:
                self.skin = target
            return self.switch_ok
        self.switch_ok = True
        self.switch = Mock(side_effect=switch)
        self.build_skin = types.SimpleNamespace(switch=self.switch)

    def restore(self, previous, row=(AF3, 1, 1)):
        with patch.dict(sys.modules, {'resources.libs': types.SimpleNamespace(build_skin=self.build_skin)}):
            return self.watch.restore_af3(previous, row)

    def test_back_to_af3_once_per_update_through_switch(self):
        self.skin = 'skin.estuary'
        self.assertTrue(self.restore(AF3))
        self.switch.assert_called_once_with(AF3)
        self.skin = 'skin.estuary'
        self.assertIsNone(self.restore(AF3))                 # same update: never again
        self.switch_ok = False
        self.assertFalse(self.restore(AF3, (AF3, 2, 1)))    # a later update gets one try
        self.assertEqual(self.switch.call_count, 2)

    def test_nothing_to_do(self):
        self.skin = 'skin.estuary'
        self.assertIsNone(self.restore('skin.estuary'))      # the user's own choice
        self.skin = AF3
        self.assertIsNone(self.restore(AF3))                 # no fallback happened
        self.switch.assert_not_called()

    def test_one_evaluation_per_update_even_when_still_on_af3(self):
        # first look: still on AF3 (no fallback); a retry of the same repair
        # after the user picked Estuary must not "restore" over that choice
        self.assertIsNone(self.restore(AF3, (AF3, 7, 1)))
        self.skin = 'skin.estuary'
        self.assertIsNone(self.restore(AF3, (AF3, 7, 1)))
        self.switch.assert_not_called()

    def test_waits_for_moransubs_start_up_and_30_quiet_seconds(self):
        self.skin = 'skin.estuary'
        self.watch.remember_skin(AF3)
        props, waits, media = {}, [], [True, True, False, True]
        window = types.SimpleNamespace(getProperty=lambda k: props.get(k, ''))

        def wait(seconds):
            waits.append(seconds)
            if len(waits) == 5:                              # MoranSubs finishes its pass
                props['kodipovil_startup_repairs_done'] = '0.3.44'
            self.assertFalse(self.switch.called)             # nothing before both waits end
            return False
        self.xbmc.getCondVisibility = lambda c: media.pop(0) if media else False
        with patch.dict(sys.modules, {'resources.libs': types.SimpleNamespace(build_skin=self.build_skin)}):
            self.assertTrue(self.watch.restore_af3(AF3, (AF3, 9, 1),
                                                   types.SimpleNamespace(waitForAbort=wait), window))
        self.assertEqual(waits[:5], [5] * 5)                 # 25 s of start-up wait
        self.assertGreaterEqual(sum(waits[5:]), 30)          # then 30 quiet seconds
        self.switch.assert_called_once_with(AF3)

    def test_quiet_for(self):
        quiet = self.watch._quiet_for
        never = types.SimpleNamespace(waitForAbort=lambda s: False)
        self.assertTrue(quiet(never, lambda: True, 0, 10))
        self.assertFalse(quiet(never, lambda: False, 0, 10))
        flips = [False, True, True, True, True, True, True, True]
        self.assertTrue(quiet(never, lambda: flips.pop(0), 30, 100))
        self.assertIsNone(quiet(types.SimpleNamespace(waitForAbort=lambda s: True), lambda: False, 0, 10))

    def test_mid_install_is_capped_and_future_mtimes_are_no_update(self):
        self.xbmc.getCondVisibility = lambda c: False
        with patch.object(self.watch.time, 'monotonic', side_effect=[100.0, 100.0, 800.0]):
            self.assertTrue(self.watch.af3_mid_install(str(self.addons)))
            self.assertFalse(self.watch.af3_mid_install(str(self.addons)))   # 700 s: not an install
        import time as _t
        os.utime(self.addons / AF3 / 'addon.xml', (_t.time() + 86400, _t.time() + 86400))
        self.assertFalse(self.watch.af3_updated_since(0))

    def test_a_choice_made_during_the_wait_wins(self):
        self.skin = 'skin.estuary'
        self.watch.remember_skin(AF3)
        window = types.SimpleNamespace(getProperty=lambda k: '1')
        self.xbmc.getCondVisibility = lambda c: False

        def wait(seconds):
            self.watch.remember_skin('skin.estuary')         # picked in the Wizard meanwhile
            return False
        with patch.dict(sys.modules, {'resources.libs': types.SimpleNamespace(build_skin=self.build_skin)}):
            self.assertIsNone(self.watch.restore_af3(AF3, (AF3, 10, 1),
                                                     types.SimpleNamespace(waitForAbort=wait), window))
        self.switch.assert_not_called()

    def test_memory_round_trip(self):
        self.assertEqual(self.watch.read_skin_memory(), ('', 0.0))
        self.watch.remember_skin(AF3, 100.0)
        self.assertEqual(self.watch.read_skin_memory(), (AF3, 100.0))
        self.watch.remember_skin('')
        self.assertEqual(self.watch.read_skin_memory()[0], AF3)

    def run_watch(self, rows, polls):
        """rows: signature per poll (the first one is the start-up baseline)."""
        props = {}
        window = types.SimpleNamespace(getProperty=lambda k: props.get(k, ''),
                                       setProperty=lambda k, v: props.__setitem__(k, v),
                                       clearProperty=lambda k: props.pop(k, None))
        monitor = types.SimpleNamespace(waitForAbort=Mock(side_effect=[False] * polls + [True]),
                                        abortRequested=lambda: False)
        self.xbmc.Monitor = lambda: monitor
        self.xbmc.Player = lambda: types.SimpleNamespace(isPlayingVideo=lambda: False)
        with patch.dict(sys.modules, {'xbmcgui': types.SimpleNamespace(Window=lambda n: window)}), \
                patch.object(self.watch, 'signature', side_effect=rows + [rows[-1]] * 50), \
                patch.object(self.watch, 'prebuild_lists'), patch.object(self.watch, 'warm_bytecode'), \
                patch.object(self.watch, 'repair_changed', return_value=True) as repair:
            self.watch.run()
        return repair

    def rows(self, af3):
        return (('plugin.video.pov', 1, 1), ('plugin.video.umbrella', None, None), (AF3, af3, 1))

    def test_a_user_who_never_switches_is_remembered(self):
        self.run_watch([self.rows(1)] * 5, 4)
        self.assertEqual(self.watch.read_skin_memory()[0], AF3)

    def test_the_fallback_during_an_update_is_not_a_choice(self):
        # settled on AF3, then Kodi falls back to Estuary while AF3's files change
        self.skins = [AF3, AF3, AF3, 'skin.estuary', 'skin.estuary', 'skin.estuary']
        self.skin = 'skin.estuary'
        rows = [self.rows(1)] * 5 + [self.rows(2)] * 3
        repair = self.run_watch(rows, 6)
        self.assertEqual(repair.call_args.kwargs['previous_skin'], AF3)
        self.assertEqual(self.watch.read_skin_memory()[0], AF3)

    def test_estuary_while_af3_is_unloaded_for_its_install_is_never_remembered(self):
        # a slow box: Kodi shows Estuary for minutes before AF3's addon.xml changes
        self.skins = [AF3, AF3, AF3] + ['skin.estuary'] * 20
        self.skin = 'skin.estuary'
        has_addon = [True] * 3 + [False] * 20
        self.xbmc.getCondVisibility = lambda c: has_addon.pop(0) if has_addon else False
        rows = [self.rows(1)] * 12 + [self.rows(2)] * 3
        repair = self.run_watch(rows, 14)
        self.assertEqual(self.watch.read_skin_memory()[0], AF3)
        self.assertEqual(repair.call_args.kwargs['previous_skin'], AF3)

    def test_a_wizard_switch_counts_at_once(self):
        # Switch Skin writes the memory file; the watch's in-loop copy is older
        self.skins = [AF3, AF3, AF3]
        self.skin = 'skin.estuary'
        rows = [self.rows(1)] * 5 + [self.rows(2)] * 3
        original = self.watch.read_skin_memory
        calls = []

        def read():
            calls.append(1)
            if len(calls) > 1:
                self.watch.remember_skin('skin.estuary')     # the user's Switch Skin, mid-session
            return original()
        with patch.object(self.watch, 'read_skin_memory', side_effect=read):
            repair = self.run_watch(rows, 6)
        self.assertEqual(repair.call_args.kwargs['previous_skin'], 'skin.estuary')

    def test_a_deliberate_estuary_is_respected(self):
        self.skins = [AF3, AF3, AF3] + ['skin.estuary'] * 4
        self.skin = 'skin.estuary'
        rows = [self.rows(1)] * 8 + [self.rows(2)] * 3
        repair = self.run_watch(rows, 9)
        self.assertEqual(self.watch.read_skin_memory()[0], 'skin.estuary')
        self.assertEqual(repair.call_args.kwargs['previous_skin'], 'skin.estuary')

    def test_an_update_before_start_up_with_the_fallback(self):
        self.watch.remember_skin(AF3, 100.0)                 # AF3's files are newer than this
        self.skin = 'skin.estuary'
        repair = self.run_watch([self.rows(1)] * 4, 2)
        repair.assert_called_once()
        self.assertEqual(repair.call_args.kwargs['previous_skin'], AF3)

    def test_estuary_chosen_last_session_without_an_update_is_kept(self):
        self.watch.remember_skin(AF3)                        # newer than AF3's files
        os.utime(self.addons / AF3 / 'addon.xml', (50, 50))
        self.skin = 'skin.estuary'
        repair = self.run_watch([self.rows(1)] * 4, 2)
        repair.assert_not_called()


if __name__ == '__main__':
    unittest.main()
