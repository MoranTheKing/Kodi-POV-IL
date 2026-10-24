"""MoranSubs 0.3.53: with POV patching switched off (the Wizard patches a clean
POV since the host handoff), MoranSubs' own POV markers are absent by design.
patcher_health reported them as "STOPPED APPLYING" -- QA Kodi, POV 6.10.21:
"pov_hebrew_genres_patcher -> plugin.video.pov 6.10.21 (was applied at
6.10.06)" while the genres were Hebrew through the Wizard's translate_genres.
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

LIB = (Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai'
       / 'resources' / 'lib')


class PovOffTests(unittest.TestCase):
    def setUp(self):
        self.settings = {}
        ku = types.SimpleNamespace(
            log=lambda *a, **k: None,
            get_setting=lambda key, default='': self.settings.get(key, default))
        package = types.ModuleType('resources.lib')
        package.kodi_utils = ku
        patcher = mock.patch.dict(sys.modules, {
            'resources': types.ModuleType('resources'),
            'resources.lib': package,
            'resources.lib.kodi_utils': ku})
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location(
            'patcher_health_t', LIB / 'patcher_health.py')
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.mod.kodi_utils = ku

    def row(self, host, present=False):
        return {'patcher': 'pov_hebrew_genres_patcher', 'marker': 'M',
                'host': host, 'host_version': '6.10.22', 'installed': True,
                'present': present, 'rebuilt': False, 'fixed_in': '',
                'host_fixed': False}

    def state(self):
        return {'seen': {'pov_hebrew_genres_patcher|plugin.video.pov|M':
                         {'last_ok_version': '6.10.06'},
                         'pov_hebrew_genres_patcher|plugin.video.umbrella|M':
                         {'last_ok_version': '6.7.90'}}}

    def test_absent_pov_marker_is_switched_off_not_lapsed(self):
        rows, state = self.mod.classify(
            [self.row('plugin.video.pov'), self.row('plugin.video.umbrella')],
            self.state(), pov_off=True)
        self.assertEqual(['switched_off', 'lapsed'], [r['status'] for r in rows])
        self.assertEqual([rows[1]], self.mod.lapsed(rows))
        # the last good version is kept: switching back on can warn again
        self.assertEqual('6.10.06', state['seen'][
            'pov_hebrew_genres_patcher|plugin.video.pov|M']['last_ok_version'])

    def test_with_pov_patching_on_it_still_warns(self):
        rows, _ = self.mod.classify([self.row('plugin.video.pov')],
                                    self.state(), pov_off=False)
        self.assertEqual('lapsed', rows[0]['status'])

    def test_run_reads_the_setting(self):
        self.settings['_pov_patching_off'] = 'true'
        self.assertTrue(self.mod._pov_patching_off())
        self.settings['_pov_patching_off'] = 'false'
        self.assertFalse(self.mod._pov_patching_off())


if __name__ == '__main__':
    unittest.main()
