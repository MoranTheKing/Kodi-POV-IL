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

    def install_af3(self, ours=True):
        write(self.addons / AF3 / 'addon.xml', '<addon id="%s" version="3.4.6"/>' % AF3)
        write(self.addons / AF3 / '1080i' / 'Font.xml',
              '<fonts>%s</fonts>' % ('NotoSans-Regular.ttf' if ours else 'Inter-Regular.ttf'))

    def test_font_check(self):
        self.assertTrue(self.watch.af3_font_current(str(self.addons)))     # no AF3: nothing to do
        self.install_af3(ours=False)
        self.assertFalse(self.watch.af3_font_current(str(self.addons)))
        self.install_af3(ours=True)
        self.assertTrue(self.watch.af3_font_current(str(self.addons)))

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
        self.install_af3(ours=False)
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
        repair.assert_called_once()
        previous, current = repair.call_args[0][1:3]
        self.assertEqual(dict((r[0], r[1:]) for r in previous)[AF3], (-1, -1))
        self.assertEqual(current, rows)

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


if __name__ == '__main__':
    unittest.main()
