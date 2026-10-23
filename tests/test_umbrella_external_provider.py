"""MoranSubs 0.3.52: Umbrella's External Providers is wired to CocoScrapers again
when it is found off, not only on the first run.

Field report, 24 Oct 2026: TorBox connected, POV found sources, Umbrella
answered every search with no results until External Providers was turned back
on by hand. In this build Umbrella finds practically nothing without it (its own
scrapers need accounts the build does not set up), and it switches the toggle
off by itself when its provider picker is backed out of. A complete custom provider is still left alone.
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

LIB = (Path(__file__).resolve().parents[1] / 'service.subtitles.kodipovilai'
       / 'resources' / 'lib')


class ExternalProviderTests(unittest.TestCase):
    def setUp(self):
        self.marker = {}
        self.ku = types.SimpleNamespace(
            log=lambda *a, **k: None,
            get_setting=lambda key, default='': self.marker.get(key, default),
            set_setting=lambda key, value: self.marker.__setitem__(key, value))
        self.writes = []
        safe = types.SimpleNamespace(apply=self._apply)
        self.data = {}
        presence = types.SimpleNamespace(addon=lambda _id: self._addon())
        package = types.ModuleType('resources.lib')
        package.kodi_utils = self.ku
        package.addon_settings_safe = safe
        package.addon_presence = presence
        self.modules = mock.patch.dict(sys.modules, {
            'resources': types.ModuleType('resources'),
            'resources.lib': package,
            'resources.lib.kodi_utils': self.ku,
            'resources.lib.addon_settings_safe': safe,
            'resources.lib.addon_presence': presence,
            'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location(
            'umb_ext_provider', LIB / 'umbrella_setup_patcher.py')
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.mod.xbmcvfs = None     # CocoScrapers "on disk" check skipped

    def _addon(self):
        data = self.data

        class Addon(object):
            def getSetting(self, key):
                return data.get(key, '')
        return Addon()

    def _apply(self, addon_id, wanted, guard_property=None):
        self.writes.extend(wanted)
        self.data.update(dict(wanted))
        return [k for k, _v in wanted], [], []

    def run_case(self, marker_done, data):
        if marker_done:
            self.marker[self.mod.PROVIDER_DONE_SETTING] = 'done'
        self.data.update(data)
        return self.mod.ensure_external_provider()

    def test_found_off_after_the_first_run_is_switched_back_on(self):
        status = self.run_case(True, {'provider.external.enabled': 'false',
                                      'external_provider.module': '',
                                      'external_provider.name': ''})
        self.assertEqual('reenabled', status)
        self.assertEqual('true', self.data['provider.external.enabled'])
        self.assertEqual(self.mod.COCO_MODULE, self.data['external_provider.module'])
        self.assertEqual(self.mod.COCO_NAME, self.data['external_provider.name'])
        # the toggle goes FIRST: Umbrella's late callbacks blank both names
        # whenever they read it off (QA Kodi: names came back empty)
        self.assertEqual('provider.external.enabled', self.writes[0][0])

    def test_names_umbrella_blanks_after_the_wiring_are_written_again(self):
        calls = []

        def apply(addon_id, wanted, guard_property=None):
            calls.append(tuple(wanted))
            self.writes.extend(wanted)
            self.data.update(dict(wanted))
            if len(calls) == 1:     # Umbrella's monitor blanks them late
                self.data['external_provider.name'] = ''
                self.data['external_provider.module'] = ''
            return [k for k, _v in wanted], [], []
        self.mod.addon_settings_safe = types.SimpleNamespace(apply=apply)
        status = self.run_case(True, {'provider.external.enabled': 'false'})
        self.assertEqual('reenabled', status)
        self.assertEqual(2, len(calls))
        self.assertEqual(self.mod.COCO_MODULE, self.data['external_provider.module'])
        self.assertEqual(self.mod.COCO_NAME, self.data['external_provider.name'])

    def test_each_look_reads_a_new_addon_object(self):
        # In Kodi an Addon object keeps the settings it loaded when it was
        # made; the one read before the wiring still says off.
        data = self.data

        class Snapshot(object):
            def __init__(self):
                self.values = dict(data)

            def getSetting(self, key):
                return self.values.get(key, '')
        self._addon = Snapshot
        status = self.run_case(True, {'provider.external.enabled': 'false'})
        self.assertEqual('reenabled', status)
        self.assertEqual(3, len(self.writes))       # no phantom second write

    def test_a_key_reported_failed_but_found_set_counts_as_done(self):
        def apply(addon_id, wanted, guard_property=None):
            self.writes.extend(wanted)
            self.data.update(dict(wanted))
            return [k for k, _v in wanted], [], ['external_provider.name']
        self.mod.addon_settings_safe = types.SimpleNamespace(apply=apply)
        status = self.run_case(True, {'provider.external.enabled': 'false'})
        self.assertEqual('reenabled', status)
        self.assertEqual('done', self.marker[self.mod.PROVIDER_DONE_SETTING])

    def test_kodi_quitting_before_the_first_look_keeps_the_write_result(self):
        aborting = types.SimpleNamespace(Monitor=lambda: types.SimpleNamespace(
            waitForAbort=lambda _s: True))
        with mock.patch.dict(sys.modules, {'xbmc': aborting}):
            self.assertEqual(['external_provider.name'], self.mod._settle(
                (('external_provider.name', 'x'),), ['external_provider.name']))

    def test_on_with_the_pair_missing_is_still_repaired(self):
        status = self.run_case(True, {'provider.external.enabled': 'true'})
        self.assertEqual('repaired', status)

    def test_a_complete_custom_provider_is_left_alone_on_or_off(self):
        for enabled in ('true', 'false'):
            self.writes[:] = []
            self.data.clear()
            status = self.run_case(True, {'provider.external.enabled': enabled,
                                          'external_provider.module': 'script.module.someoneelse',
                                          'external_provider.name': 'someoneelse'})
            self.assertEqual('unchanged', status)
            self.assertEqual([], self.writes)

    def test_already_wired_is_unchanged(self):
        status = self.run_case(True, {'provider.external.enabled': 'true',
                                      'external_provider.module': self.mod.COCO_MODULE,
                                      'external_provider.name': self.mod.COCO_NAME})
        self.assertEqual('unchanged', status)
        self.assertEqual([], self.writes)

    def test_first_run_still_wires_coco(self):
        self.assertEqual('patched', self.run_case(False, {}))


if __name__ == '__main__':
    unittest.main()
