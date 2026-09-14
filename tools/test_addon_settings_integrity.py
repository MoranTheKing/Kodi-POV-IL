#!/usr/bin/env python3
"""Regression tests for source-stack settings recovery.

The field failure this pins is a malformed POV values file. Kodi then keeps
the add-on defaults in memory, Account Manager cannot save into that object,
and a valid AllDebrid subscription appears as "No External Scrapers Enabled".
These tests execute the recovery code against real temporary files; they do
not merely look for implementation strings.
"""

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / 'addons' / 'service.subtitles.kodipovilai'
MODULE = Path(os.environ.get(
    'ADDON_SETTINGS_INTEGRITY_MODULE',
    str(ADDON / 'resources' / 'lib' / 'addon_settings_integrity.py')))
SERVICE = ADDON / 'service.py'


def load_integrity():
    spec = importlib.util.spec_from_file_location(
        'test_addon_settings_integrity_module', str(MODULE))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def values(path):
    root = ET.parse(str(path)).getroot()
    return {n.get('id'): n.text or '' for n in root.iter('setting')
            if n.get('id')}


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_integrity()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, raw):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def test_healthy_file_is_unchanged_and_snapshotted(self):
        raw = (b'<?xml version="1.0" encoding="utf-8"?>\n'
               b'<settings version="2"><setting id="one">kept</setting>'
               b'</settings>\n')
        path = self.write('settings.xml', raw)
        good = self.root / 'backup' / 'pov.xml'
        result = self.mod.repair_file(
            str(path), str(good), 'plugin.video.pov', pause=lambda _n: None)
        self.assertEqual('healthy', result['status'])
        self.assertEqual(raw, path.read_bytes())
        self.assertEqual(raw, good.read_bytes())

    def test_healthy_file_reports_when_last_good_cannot_be_saved(self):
        raw = b'<settings version="2"><setting id="one">kept</setting></settings>'
        path = self.write('settings.xml', raw)
        with mock.patch.object(self.mod, '_copy_if_changed',
                               return_value=False):
            result = self.mod.repair_file(
                str(path), str(self.root / 'good.xml'), 'plugin.video.pov')
        self.assertEqual('healthy_snapshot_failed', result['status'])
        self.assertEqual(raw, path.read_bytes())

    def test_truncated_file_salvages_complete_nodes_and_preserves_bad_bytes(self):
        raw = (b'<settings version="2">\n'
               b'<setting id="ad.token">surviving-token</setting>\n'
               b'<setting id="user.choice">2160p</setting>\n'
               b'<setting id="torn">never finished')
        path = self.write('pov/settings.xml', raw)
        result = self.mod.repair_file(
            str(path), str(self.root / 'good/pov.xml'), 'plugin.video.pov',
            pause=lambda _n: None)
        self.assertEqual('repaired_salvage', result['status'])
        self.assertEqual(2, result['salvaged'])
        self.assertEqual('surviving-token', values(path)['ad.token'])
        self.assertEqual('2160p', values(path)['user.choice'])
        backups = list(path.parent.glob('settings.xml.corrupt-*.bak'))
        self.assertEqual(1, len(backups))
        self.assertEqual(raw, backups[0].read_bytes())

    def test_last_good_copy_wins_over_incomplete_salvage(self):
        bad = b'<settings><setting id="only">partial</setting><setting'
        good_raw = (b'<settings version="2"><setting id="only">complete</setting>'
                    b'<setting id="other">preserved</setting></settings>')
        path = self.write('pov/settings.xml', bad)
        good = self.write('good/pov.xml', good_raw)
        result = self.mod.repair_file(
            str(path), str(good), 'plugin.video.pov', pause=lambda _n: None)
        self.assertEqual('repaired_last_good', result['status'])
        self.assertEqual('complete', values(path)['only'])
        self.assertEqual('preserved', values(path)['other'])

    def test_account_manager_token_is_merged_without_exposing_its_value(self):
        bad = b'<settings><setting id="user.choice">kept</setting><torn'
        path = self.write('pov/settings.xml', bad)
        secret = 'TEST-SENTINEL-MUST-NOT-BE-RETURNED'
        result = self.mod.repair_file(
            str(path), '', 'plugin.video.pov',
            account=('person', secret), pause=lambda _n: None)
        got = values(path)
        self.assertEqual(secret, got['ad.token'])
        self.assertEqual('true', got['ad.enabled'])
        self.assertEqual('true', got['ad.torrent.enabled'])
        self.assertNotIn(secret, repr(result))
        self.assertTrue(result['account_restored'])

    def test_explicit_torrent_disable_survives_account_restore(self):
        bad = (b'<settings><setting id="ad.torrent.enabled">false</setting>'
               b'<setting id="x">y</setting><torn')
        path = self.write('pov/settings.xml', bad)
        self.mod.repair_file(
            str(path), '', 'plugin.video.pov', account=('u', 'token'),
            pause=lambda _n: None)
        self.assertEqual('false', values(path)['ad.torrent.enabled'])

    def test_explicit_pov_account_disable_survives_account_restore(self):
        bad = (b'<settings><setting id="ad.enabled">false</setting>'
               b'<setting id="x">y</setting><torn')
        path = self.write('pov/settings.xml', bad)
        self.mod.repair_file(
            str(path), '', 'plugin.video.pov', account=('u', 'token'),
            pause=lambda _n: None)
        got = values(path)
        self.assertEqual('false', got['ad.enabled'])
        self.assertEqual('token', got['ad.token'])

    def test_explicit_umbrella_account_disable_survives_account_restore(self):
        bad = (b'<settings><setting id="alldebrid.enable">false</setting>'
               b'<setting id="x">y</setting><torn')
        path = self.write('umbrella/settings.xml', bad)
        self.mod.repair_file(
            str(path), '', 'plugin.video.umbrella', account=('u', 'token'),
            pause=lambda _n: None)
        got = values(path)
        self.assertEqual('false', got['alldebrid.enable'])
        self.assertEqual('token', got['alldebridtoken'])

    def test_changing_invalid_file_is_never_touched_or_backed_up(self):
        first = b'<settings><setting id="a">one</setting><'
        second = b'<settings><setting id="a">two</setting><'
        path = self.write('pov/settings.xml', first)

        def writer(_seconds):
            path.write_bytes(second)

        result = self.mod.repair_file(
            str(path), '', 'plugin.video.pov', pause=writer)
        self.assertEqual('changing', result['status'])
        self.assertEqual(second, path.read_bytes())
        self.assertFalse(list(path.parent.glob('settings.xml.corrupt-*.bak')))

    def test_new_writer_between_backup_and_install_wins(self):
        raw = b'<settings><setting id="old">recover-me</setting><torn'
        newer = (b'<settings version="2"><setting id="new-user-choice">'
                 b'keep-me</setting></settings>')
        path = self.write('pov/settings.xml', raw)
        preserve = self.mod._preserve_corrupt

        def preserve_then_write_newer(target, bad_bytes):
            ok = preserve(target, bad_bytes)
            path.write_bytes(newer)
            return ok

        with mock.patch.object(self.mod, '_preserve_corrupt',
                               side_effect=preserve_then_write_newer):
            result = self.mod.repair_file(
                str(path), '', 'plugin.video.pov', pause=lambda _n: None)
        self.assertEqual('changed_before_install', result['status'])
        self.assertEqual(newer, path.read_bytes())
        self.assertEqual(raw, next(path.parent.glob(
            'settings.xml.corrupt-*.bak')).read_bytes())

    def test_failed_install_keeps_original_and_forensic_backup(self):
        raw = b'<settings><setting id="a">one</setting><'
        path = self.write('pov/settings.xml', raw)
        with mock.patch.object(self.mod, '_atomic_write', return_value=False):
            result = self.mod.repair_file(
                str(path), '', 'plugin.video.pov', pause=lambda _n: None)
        self.assertEqual('write_failed', result['status'])
        self.assertEqual(raw, path.read_bytes())
        backups = list(path.parent.glob('settings.xml.corrupt-*.bak'))
        self.assertEqual(raw, backups[0].read_bytes())

    def test_real_replace_failure_keeps_original_and_removes_temp(self):
        raw = b'<settings><setting id="a">one</setting><'
        path = self.write('pov/settings.xml', raw)
        real_replace = self.mod.os.replace

        def fail_only_target(source, destination):
            if os.path.normcase(str(destination)) == os.path.normcase(str(path)):
                raise OSError('simulated full disk during final replace')
            return real_replace(source, destination)

        with mock.patch.object(self.mod.os, 'replace', side_effect=fail_only_target):
            result = self.mod.repair_file(
                str(path), '', 'plugin.video.pov', pause=lambda _n: None)
        self.assertEqual('write_failed', result['status'])
        self.assertEqual(raw, path.read_bytes())
        self.assertFalse(list(path.parent.glob('*.aitmp')))
        self.assertEqual(raw, next(path.parent.glob(
            'settings.xml.corrupt-*.bak')).read_bytes())

    def test_many_truncation_points_always_end_as_valid_xml(self):
        nodes = [('<setting id="s{0}">value-{0}</setting>'.format(i))
                 for i in range(80)]
        complete = ('<settings version="2">' + ''.join(nodes) + '</settings>')
        raw = complete.encode('utf-8')
        # Boundaries include cuts inside tags, values, closing tags and the
        # root close. Each run starts from the exact bytes a killed writer
        # could have left behind.
        cuts = sorted(set(range(1, len(raw), max(1, len(raw) // 97))))
        for index, cut in enumerate(cuts):
            with self.subTest(cut=cut):
                path = self.write('cuts/{0}/settings.xml'.format(index),
                                  raw[:cut])
                result = self.mod.repair_file(
                    str(path), '', 'plugin.video.pov', pause=lambda _n: None)
                self.assertTrue(result['status'].startswith('repaired_'))
                ET.parse(str(path))
                self.assertEqual(raw[:cut], next(path.parent.glob(
                    'settings.xml.corrupt-*.bak')).read_bytes())

    def test_duplicate_complete_nodes_keep_the_last_value(self):
        bad = (b'<settings><setting id="same">old</setting>'
               b'<setting id="same">new</setting><torn')
        path = self.write('settings.xml', bad)
        self.mod.repair_file(str(path), '', 'plugin.video.pov',
                             pause=lambda _n: None)
        self.assertEqual('new', values(path)['same'])

    def test_comment_text_never_becomes_a_phantom_setting(self):
        bad = (b'<settings><!-- <setting id="phantom">wrong</setting> -->'
               b'<setting id="real">right</setting><torn')
        path = self.write('settings.xml', bad)
        self.mod.repair_file(str(path), '', 'plugin.video.pov',
                             pause=lambda _n: None)
        self.assertEqual({'real': 'right'}, values(path))

    def test_cdata_markup_stays_text_instead_of_becoming_a_setting(self):
        bad = (b'<settings><setting id="outer"><![CDATA[value <setting '
               b'id="phantom">wrong</setting>]]></setting><torn')
        path = self.write('settings.xml', bad)
        self.mod.repair_file(str(path), '', 'plugin.video.pov',
                             pause=lambda _n: None)
        self.assertEqual({'outer': 'value <setting id="phantom">wrong'
                                   '</setting>'}, values(path))

    def test_comment_shaped_text_inside_cdata_is_preserved(self):
        bad = (b'<settings><setting id="literal"><![CDATA['
               b'abc<!--literal-->xyz]]></setting><torn')
        path = self.write('settings.xml', bad)
        self.mod.repair_file(str(path), '', 'plugin.video.pov',
                             pause=lambda _n: None)
        self.assertEqual('abc<!--literal-->xyz', values(path)['literal'])

    def test_cdata_shaped_text_inside_comment_cannot_hide_later_setting(self):
        bad = (b'<settings><!-- example <![CDATA[ --> '
               b'<setting id="token">sentinel-preserve</setting>')
        path = self.write('settings.xml', bad)
        self.mod.repair_file(str(path), '', 'plugin.video.pov',
                             pause=lambda _n: None)
        self.assertEqual({'token': 'sentinel-preserve'}, values(path))

    def test_complete_nodes_before_a_torn_comment_are_salvaged(self):
        bad = (b'<settings><setting id="real">right</setting>'
               b'<!-- <setting id="phantom">wrong</setting>')
        path = self.write('settings.xml', bad)
        self.mod.repair_file(str(path), '', 'plugin.video.pov',
                             pause=lambda _n: None)
        self.assertEqual({'real': 'right'}, values(path))

    def test_no_complete_node_becomes_valid_profile_and_keeps_bad_copy(self):
        raw = b'<settings><setting id="token">cut off'
        path = self.write('settings.xml', raw)
        result = self.mod.repair_file(
            str(path), '', 'plugin.video.pov', pause=lambda _n: None)
        self.assertEqual('repaired_salvage', result['status'])
        self.assertEqual({}, values(path))
        self.assertEqual(raw, next(path.parent.glob(
            'settings.xml.corrupt-*.bak')).read_bytes())

    def test_oversized_file_is_left_byte_for_byte_untouched(self):
        self.mod._MAX_SETTINGS_BYTES = 32
        raw = b'<settings>' + (b'x' * 80)
        path = self.write('settings.xml', raw)
        result = self.mod.repair_file(
            str(path), '', 'plugin.video.pov', pause=lambda _n: None)
        self.assertEqual('too_large', result['status'])
        self.assertEqual(raw, path.read_bytes())
        self.assertFalse(list(path.parent.glob('settings.xml.corrupt-*.bak')))

    def test_resync_preserves_explicit_pov_torrent_opt_out(self):
        secret = 'ACCOUNT-MASTER-SENTINEL'

        class Addon(object):
            def __init__(self, data):
                self.data = data

            def getSetting(self, key):
                return self.data.get(key, '')

        pov = Addon({'ad.token': 'old', 'ad.enabled': 'false',
                     'ad.torrent.enabled': 'false'})
        umb = Addon({'alldebridtoken': secret})
        addons = {'plugin.video.pov': pov, 'plugin.video.umbrella': umb}
        calls = []

        class Presence(object):
            @staticmethod
            def addon(addon_id):
                return addons.get(addon_id)

        class Safe(object):
            @staticmethod
            def apply(addon_id, wanted, guard_property=None):
                calls.append((addon_id, tuple(wanted), guard_property))
                addons[addon_id].data.update(dict(wanted))
                return [k for k, _v in wanted], [], []

        self.mod.addon_presence = Presence()
        self.mod.addon_settings_safe = Safe()
        self.mod._account_manager_alldebrid = lambda: ('user', secret)
        result = self.mod.sync_alldebrid_from_account_manager()
        self.assertEqual(1, len(result))
        wanted = dict(calls[0][1])
        self.assertNotIn('ad.enabled', wanted)
        self.assertNotIn('ad.torrent.enabled', wanted)
        self.assertEqual('false', pov.data['ad.enabled'])
        self.assertEqual('false', pov.data['ad.torrent.enabled'])
        self.assertNotIn(secret, repr(result))

    def test_resync_preserves_explicit_umbrella_account_opt_out(self):
        class Addon(object):
            def __init__(self, data):
                self.data = data

            def getSetting(self, key):
                return self.data.get(key, '')

        umbrella = Addon({'alldebridtoken': 'old',
                          'alldebrid.enable': 'false'})
        calls = []
        self.mod.addon_presence = types.SimpleNamespace(
            addon=lambda addon_id: umbrella
            if addon_id == 'plugin.video.umbrella' else None)
        self.mod.addon_settings_safe = types.SimpleNamespace(
            apply=lambda addon_id, wanted, guard_property=None:
            (calls.append((addon_id, tuple(wanted), guard_property))
             or ([k for k, _v in wanted], [], [])))
        self.mod._account_manager_alldebrid = lambda: ('u', 'new')
        self.mod.sync_alldebrid_from_account_manager()
        self.assertEqual(1, len(calls))
        self.assertNotIn('alldebrid.enable', dict(calls[0][1]))

    def test_resync_enables_torrents_only_when_the_switch_is_missing(self):
        class Addon(object):
            data = {'ad.token': 'old'}

            def getSetting(self, key):
                return self.data.get(key, '')

        addon = Addon()
        captured = []
        self.mod.addon_presence = types.SimpleNamespace(
            addon=lambda addon_id: addon if addon_id == 'plugin.video.pov'
            else None)
        self.mod.addon_settings_safe = types.SimpleNamespace(
            apply=lambda addon_id, wanted, guard_property=None:
            (captured.extend(wanted) or ([k for k, _v in wanted], [], [])))
        self.mod._account_manager_alldebrid = lambda: ('u', 'new')
        self.mod.sync_alldebrid_from_account_manager()
        self.assertIn(('ad.torrent.enabled', 'true'), captured)

    def test_resync_skips_a_target_whose_file_was_just_repaired(self):
        class Addon(object):
            def getSetting(self, _key):
                return ''

        calls = []
        self.mod.addon_presence = types.SimpleNamespace(
            addon=lambda _addon_id: Addon())
        self.mod.addon_settings_safe = types.SimpleNamespace(
            apply=lambda *args, **kwargs: calls.append(args) or ([], [], []))
        self.mod._account_manager_alldebrid = lambda: ('u', 'master')
        self.mod.sync_alldebrid_from_account_manager(
            skip_addons=('plugin.video.pov',))
        self.assertEqual(1, len(calls))
        self.assertEqual('plugin.video.umbrella', calls[0][0])

    def test_recovery_runs_before_every_cross_addon_settings_writer(self):
        src = SERVICE.read_text(encoding='utf-8')
        tuple_start = src.index('steps = (')
        tuple_end = src.index('\n    )', tuple_start)
        steps = src[tuple_start:tuple_end]
        recovery = steps.index('_maybe_repair_addon_settings_integrity,')
        self.assertLess(recovery, steps.index('_maybe_patch_pov_language_invoker,'))
        self.assertLess(recovery, steps.index('_maybe_patch_umbrella_language,'))
        self.assertLess(recovery, steps.index('_maybe_patch_pov_scraper_settings,'))


class UmbrellaProviderSelfHealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ADDON))
        from resources.lib import kodi_utils
        from resources.lib import umbrella_setup_patcher
        cls.ku = kodi_utils
        cls.mod = umbrella_setup_patcher

    @classmethod
    def tearDownClass(cls):
        try:
            sys.path.remove(str(ADDON))
        except ValueError:
            pass

    def run_case(self, marker, data):
        writes = []

        class Addon(object):
            def getSetting(self, key):
                return data.get(key, '')

        class Safe(object):
            @staticmethod
            def apply(addon_id, wanted, guard_property=None):
                writes.extend(wanted)
                data.update(dict(wanted))
                return [k for k, _v in wanted], [], []

        with mock.patch.object(self.mod, '_addon', return_value=Addon()), \
                mock.patch.object(self.mod, 'addon_settings_safe', Safe()), \
                mock.patch.object(self.mod, 'xbmcvfs', None), \
                mock.patch.object(self.ku, 'get_setting',
                                  return_value='done' if marker else ''), \
                mock.patch.object(self.ku, 'set_setting'):
            status = self.mod.ensure_external_provider()
        return status, writes

    def test_marker_done_heals_missing_coco_pair_when_still_enabled(self):
        status, writes = self.run_case(True, {
            'provider.external.enabled': 'true',
            'external_provider.module': '',
            'external_provider.name': '',
        })
        self.assertEqual('repaired', status)
        self.assertEqual(self.mod.COCO_MODULE, dict(writes)[
            'external_provider.module'])
        self.assertEqual(self.mod.COCO_NAME, dict(writes)[
            'external_provider.name'])

    def test_marker_done_respects_explicit_off(self):
        status, writes = self.run_case(True, {
            'provider.external.enabled': 'false',
            'external_provider.module': '',
            'external_provider.name': '',
        })
        self.assertEqual('unchanged', status)
        self.assertEqual([], writes)

    def test_marker_done_respects_a_complete_custom_provider(self):
        status, writes = self.run_case(True, {
            'provider.external.enabled': 'true',
            'external_provider.module': 'script.module.someoneelse',
            'external_provider.name': 'someoneelse',
        })
        self.assertEqual('unchanged', status)
        self.assertEqual([], writes)

    def test_first_run_still_wires_coco(self):
        status, writes = self.run_case(False, {})
        self.assertEqual('patched', status)
        self.assertEqual('true', dict(writes)['provider.external.enabled'])

    def test_first_run_respects_an_existing_custom_provider(self):
        status, writes = self.run_case(False, {
            'provider.external.enabled': 'true',
            'external_provider.module': 'script.module.someoneelse',
            'external_provider.name': 'someoneelse',
        })
        self.assertEqual('unchanged', status)
        self.assertEqual([], writes)


if __name__ == '__main__':
    unittest.main(verbosity=2)
