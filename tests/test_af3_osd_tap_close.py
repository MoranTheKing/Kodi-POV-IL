"""MoranSubs 0.3.85: a tap on the picture closes Arctic Fuse 3's player controls.

The owner (15 Nov 2026, a phone): "if I press the middle while the player is open, the player should close
-- in the other skins' players too". Estuary has such an area, the build's own skins got one in the same
release; Arctic Fuse 3 updates itself, so MoranSubs puts the control into its VideoOSD.xml after every
update."""
import importlib.util
import os
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / 'service.subtitles.kodipovilai'
SOURCE = ADDON / 'resources/lib/af3_osd_tap_close_patcher.py'

OSD = '''<?xml version="1.0" encoding="UTF-8"?>
<window>
    <defaultcontrol always="true">6001</defaultcontrol>
    <onunload>CancelAlarm(osd_timeout,true)</onunload>
    <controls>

        <control type="group">
            <include>OSD_HideControls</include>
            <control type="grouplist" id="6091">
                <control type="button" id="6001"><onclick>PlayerControl(Play)</onclick></control>
            </control>
        </control>
    </controls>
</window>
'''


class Af3OsdTapClose(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix='af3osd_')
        self.addCleanup(__import__('shutil').rmtree, self.home, True)
        self.logged = []
        os.makedirs(os.path.join(self.home, 'skin.arctic.fuse.3', '1080i'))
        self.path = os.path.join(self.home, 'skin.arctic.fuse.3', '1080i', 'VideoOSD.xml')
        xbmcvfs = types.SimpleNamespace(
            translatePath=lambda p: p.replace('special://home/addons/', self.home + os.sep))
        kodi_utils = types.SimpleNamespace(log=lambda msg, level='INFO': self.logged.append((level, msg)))
        package = types.ModuleType('af3osd_pkg')
        package.__path__ = []
        package.kodi_utils = kodi_utils
        modules = {'xbmcvfs': xbmcvfs, 'af3osd_pkg': package, 'af3osd_pkg.kodi_utils': kodi_utils}
        patcher = mock.patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location('af3osd_pkg.af3_osd_tap_close_patcher', SOURCE)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def write(self, text, eol='\n'):
        with open(self.path, 'wb') as f:
            f.write(text.replace('\n', eol).encode('utf-8'))

    def read(self):
        with open(self.path, 'rb') as f:
            return f.read()

    def test_the_area_is_the_first_control_and_closes_the_controls(self):
        self.write(OSD)
        self.assertEqual(self.mod.ensure_patched(), 'patched')
        root = ET.fromstring(self.read())
        first = root.find('controls')[0]
        self.assertEqual((first.get('type'), first.get('id')), ('button', '6990'))
        self.assertEqual(first.findtext('onclick'), 'Action(close)')
        self.assertEqual((first.findtext('top'), first.findtext('bottom')), ('0', '280'))     # the buttons keep the bottom
        self.assertFalse(first.findtext('texturefocus') or first.findtext('texturenofocus'))
        # no key leads to it; every arrow from it goes to the window's default control
        self.assertEqual([first.findtext(t) for t in ('onup', 'ondown', 'onleft', 'onright')], ['6001'] * 4)
        self.assertEqual(self.read().count(b'6990'), 1)
        self.assertIn(self.mod.MARKER.encode(), self.read())

    def test_once_and_the_rest_of_the_file_is_untouched(self):
        for eol in ('\n', '\r\n'):
            self.write(OSD, eol)
            before = self.read()
            self.assertEqual(self.mod.ensure_patched(), 'patched')
            after = self.read()
            self.assertEqual(self.mod.ensure_patched(), 'already_patched')
            self.assertEqual(self.read(), after)
            cut = after.index(b'<controls>') + len(b'<controls>' + eol.encode())
            added = len(after) - len(before)
            self.assertEqual(after[:cut] + after[cut + added:], before)
            self.assertEqual(after.count(b'\r\n') > 0, eol == '\r\n')
            self.assertNotIn(b'\r\r', after)
            if eol == '\r\n':
                self.assertEqual(after.count(b'\n'), after.count(b'\r\n'))        # the file's own line ends

    def test_a_file_of_another_shape_is_left_alone(self):
        for text in (OSD.replace('<controls>\n', '<controls><!-- x -->\n<controls>\n', 1),      # two
                     OSD.replace('<controls>', '<kontrols>').replace('</controls>', '</kontrols>'),
                     OSD.replace('    <defaultcontrol always="true">6001</defaultcontrol>\n', ''),
                     OSD.replace('id="6091"', 'id="6990"')):                                 # the id is the skin's now
            self.write(text)
            before = self.read()
            self.assertEqual(self.mod.ensure_patched(), 'unmatched')
            self.assertEqual(self.read(), before)
            self.assertTrue(any(level == 'WARNING' for level, _msg in self.logged))

    def test_a_default_control_left_in_a_comment_is_not_the_windows(self):
        real = '    <defaultcontrol always="true">6001</defaultcontrol>\n'
        old = '    <!-- <defaultcontrol>4000</defaultcontrol> -->\n'
        self.write(OSD.replace(real, old + real))
        self.assertEqual(self.mod.ensure_patched(), 'patched')
        first = ET.fromstring(self.read()).find('controls')[0]
        self.assertEqual(first.findtext('ondown'), '6001')
        self.write(OSD.replace(real, old))
        self.assertEqual(self.mod.ensure_patched(), 'unmatched')

    def test_the_health_check_sees_the_marker_and_the_skin(self):
        # 'unmatched' counts as done for the repair after an AF3 update; what reports a patch that stopped
        # applying is patcher_health, which finds a patcher by its marker and the add-on it names
        spec = importlib.util.spec_from_file_location('af3osd_health', ADDON / 'resources/lib/patcher_health.py')
        health = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(health)
        markers, hosts = health.markers_and_hosts(SOURCE.read_text('utf-8'))
        self.assertIn('AI_SUBS_AF3_OSD_TAP_CLOSE_v1', markers)
        self.assertIn('skin.arctic.fuse.3', hosts)

    def test_no_skin_no_work(self):
        self.assertEqual(self.mod.ensure_patched(), 'no_file')
        self.assertEqual(self.logged, [])

    def test_a_write_that_fails_leaves_the_file_and_no_temp_file(self):
        self.write(OSD)
        before = self.read()
        with mock.patch.object(self.mod.os, 'replace', side_effect=OSError('read-only')):
            self.assertEqual(self.mod.ensure_patched(), 'write_failed')
        self.assertEqual(self.read(), before)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ['VideoOSD.xml'])

    def test_the_start_up_and_the_repair_after_an_af3_update_both_run_it(self):
        service = (ADDON / 'service.py').read_text('utf-8')
        step = service[service.index('def _maybe_patch_af3_dialog_subtitles'):]
        step = step[:step.index('\ndef ', 10)]
        self.assertIn('af3_osd_tap_close_patcher.ensure_patched()', step)
        self.assertIn('af3_osd_tap_close_patcher.ensure_patched()', (ADDON / 'repair_af3.py').read_text('utf-8'))
        # the marker is one the health check and the upgrade-path harness can find
        self.assertRegex(self.mod.MARKER, r'AI_SUBS_AF3_OSD_TAP_CLOSE_v\d+')
        self.assertEqual(self.mod.AF3_ADDON_ID, 'skin.arctic.fuse.3')


if __name__ == '__main__':
    unittest.main()
