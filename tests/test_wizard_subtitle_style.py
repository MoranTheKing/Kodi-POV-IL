"""Wizard 0.4.99: the build's subtitles without the box behind them.

The owner (15 Nov 2026): "the default should be without the black rectangle
created for the subtitles -- only white text with a black outline". The build
shipped Kodi's box background with border size 41; the look is now no
background and Kodi's own border size, 25 (41 fills the letters once Kodi
draws the outline: seen in the QA Kodi). A device still on exactly the
shipped background and border gets it once; any other look is left alone.
"""
import importlib.util
import json
import sys
import types
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / 'plugin.program.kodipovilwizard'
SOURCE = ROOT / 'resources/libs/subtitle_style.py'

SHIPPED = {'subtitles.backgroundtype': 2, 'subtitles.bgcolorpick': 'FF000000', 'subtitles.bgopacity': 35,
           'subtitles.bordersize': 41, 'subtitles.bordercolorpick': 'FF000000',
           'subtitles.fontsize': 52, 'subtitles.colorpick': 'FFFFFFFF'}


class SubtitleStyleTests(unittest.TestCase):
    def setUp(self):
        self.settings = {}
        self.kodi = dict(SHIPPED)
        self.writes, self.saves, self.logged = [], [], []
        self.refuse, self.silent, self.saved, self.mark_holds = set(), False, True, True

        def set_setting(key, value):
            if self.mark_holds:
                self.settings[key] = value
        config = types.SimpleNamespace(get_setting=lambda key: self.settings.get(key, ''), set_setting=set_setting)
        common = types.ModuleType('resources.libs.common')
        common.logging = types.SimpleNamespace(log=lambda text, level=None: self.logged.append(text))
        common.config = types.SimpleNamespace(CONFIG=config)

        def rpc(text):
            req = json.loads(text)
            key = req['params']['setting']
            if req['method'] == 'Settings.GetSettingValue':
                # Kodi's own rule (system/settings/settings.xml): the box's colour and opacity are visible,
                # and answered by the API, only with background type 2 or 3 (seen in the QA Kodi: the first
                # version asked for all five again after the change, got no answer, and never marked it done)
                hidden = key in ('subtitles.bgcolorpick', 'subtitles.bgopacity') and                     self.kodi.get('subtitles.backgroundtype') not in (2, 3)
                if self.silent or hidden:
                    return json.dumps({'error': {'code': -32602}})
                return json.dumps({'result': {'value': self.kodi.get(key)}})
            self.writes.append((key, req['params']['value']))
            if key in self.refuse:
                return json.dumps({'result': False})
            self.kodi[key] = req['params']['value']
            return json.dumps({'result': True})

        xbmc = types.SimpleNamespace(LOGINFO=1, LOGWARNING=2, executeJSONRPC=rpc)
        build_skin = types.ModuleType('resources.libs.build_skin')
        build_skin.persist_live_settings = lambda: (self.saves.append(dict(self.kodi)) or self.saved)
        libs = types.ModuleType('resources.libs')
        libs.common, libs.build_skin = common, build_skin
        modules = {'xbmc': xbmc, 'resources': types.ModuleType('resources'), 'resources.libs': libs,
                   'resources.libs.common': common, 'resources.libs.common.config': common.config,
                   'resources.libs.common.logging': common.logging, 'resources.libs.build_skin': build_skin}
        patcher = mock.patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location('povil_subtitle_style', SOURCE)
        self.style = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.style)

    def test_a_device_on_the_shipped_box_gets_the_outline_and_kodi_saves_it(self):
        self.assertTrue(self.style.migrate())
        self.assertEqual(sorted(self.writes), [('subtitles.backgroundtype', 0), ('subtitles.bordersize', 25)])
        self.assertEqual((self.kodi['subtitles.backgroundtype'], self.kodi['subtitles.bordersize']), (0, 25))
        self.assertEqual(len(self.saves), 1)                                # Kodi 21 changes memory only
        self.assertEqual(self.saves[0]['subtitles.backgroundtype'], 0)      # ...saved after both were set
        self.assertEqual(self.settings['subtitle_outline_v1'], 'applied')
        self.assertEqual((self.kodi['subtitles.fontsize'], self.kodi['subtitles.colorpick']), (52, 'FFFFFFFF'))
        self.assertEqual(self.writes[0][0], 'subtitles.backgroundtype')      # first: the border is greyed out under a box
        self.assertTrue(any('the box behind the subtitles is off' in line for line in self.logged))

    def test_once(self):
        self.style.migrate()
        self.kodi.update({'subtitles.backgroundtype': 2, 'subtitles.bordersize': 41})   # the user's own box, later
        del self.writes[:]
        self.assertFalse(self.style.migrate())
        self.assertEqual(self.writes, [])

    def test_a_look_someone_chose_is_left_alone(self):
        for key, value in (('subtitles.backgroundtype', 3), ('subtitles.backgroundtype', 1),
                           ('subtitles.bgopacity', 60), ('subtitles.bgcolorpick', 'FF202020'),
                           ('subtitles.bordersize', 30), ('subtitles.bordercolorpick', 'FFFF0000')):
            self.setUp()
            self.kodi[key] = value
            self.assertFalse(self.style.migrate(), key)
            self.assertEqual(self.writes, [], key)

    def test_a_changed_font_size_or_colour_does_not_keep_the_box(self):
        self.kodi.update({'subtitles.fontsize': 64, 'subtitles.colorpick': 'FFFFFF00'})
        self.assertTrue(self.style.migrate())
        self.assertEqual((self.kodi['subtitles.fontsize'], self.kodi['subtitles.colorpick']), (64, 'FFFFFF00'))

    def test_a_profile_seen_before_it_has_the_builds_settings_is_not_marked(self):
        # Kodi's own defaults at a profile's first moments; the build's settings (the Wizard's copy of the
        # pack: the box) arrive later in that start
        self.kodi.update({'subtitles.backgroundtype': 0, 'subtitles.bordersize': 25, 'subtitles.bgopacity': 80})
        self.assertFalse(self.style.migrate())
        self.assertEqual(self.settings, {})
        self.kodi.update(SHIPPED)
        self.assertTrue(self.style.migrate())

    def test_a_device_without_the_box_is_not_touched(self):
        # moved from the old build (its own migration), or installed from pack 2.0.11
        self.kodi.update({'subtitles.backgroundtype': 0, 'subtitles.bordersize': 25})
        self.assertFalse(self.style.migrate())
        self.assertEqual(self.writes, [])

    def test_a_start_cut_between_the_two_values_is_finished_at_the_next(self):
        self.refuse.add('subtitles.bordersize')
        self.assertFalse(self.style.migrate())
        self.assertEqual(self.settings['subtitle_outline_v1'], 'pending')
        self.assertEqual(self.kodi['subtitles.backgroundtype'], 0)          # half done
        self.refuse.clear()
        self.assertTrue(self.style.migrate())
        self.assertEqual((self.kodi['subtitles.backgroundtype'], self.kodi['subtitles.bordersize']), (0, 25))
        self.assertEqual(self.settings['subtitle_outline_v1'], 'applied')

    def test_a_start_cut_after_both_values_but_before_the_mark_is_marked_at_the_next(self):
        # the QA Kodi: values set and saved, Kodi closed before the mark -- the box's colour and opacity no
        # longer answer, and that must not read as "Kodi is not answering" for ever
        self.settings['subtitle_outline_v1'] = 'pending'
        self.kodi.update({'subtitles.backgroundtype': 0, 'subtitles.bordersize': 25})
        self.assertTrue(self.style.migrate())
        self.assertEqual(self.writes, [])
        self.assertEqual(self.settings['subtitle_outline_v1'], 'applied')

    def test_a_value_changed_by_hand_while_half_done_ends_it(self):
        self.refuse.add('subtitles.bordersize')
        self.style.migrate()
        self.refuse.clear()
        self.kodi['subtitles.bordersize'] = 60
        del self.writes[:]
        self.assertFalse(self.style.migrate())
        self.assertEqual(self.writes, [])
        self.assertEqual(self.settings['subtitle_outline_v1'], 'kept')

    def test_not_saved_is_not_marked_done_and_the_next_start_checks_again(self):
        self.saved = False
        self.assertTrue(self.style.migrate())
        self.assertEqual(self.settings['subtitle_outline_v1'], 'pending')
        self.kodi.update(SHIPPED)                 # Android killed Kodi before it saved: the box is back
        self.saved = True
        self.assertTrue(self.style.migrate())
        self.assertEqual(self.settings['subtitle_outline_v1'], 'applied')

    def test_nothing_is_changed_when_the_mark_cannot_be_kept_or_kodi_does_not_answer(self):
        self.mark_holds = False
        self.assertFalse(self.style.migrate())
        self.assertEqual(self.writes, [])
        self.mark_holds, self.silent = True, True
        self.assertFalse(self.style.migrate())
        self.assertEqual((self.writes, self.settings), ([], {}))

    def test_the_wizards_own_copy_of_the_pack_is_read_with_the_new_look(self):
        with zipfile.ZipFile(ROOT / 'resources/bootstrap/config.zip') as pack:
            root = ET.fromstring(pack.read('guisettings.xml'))
        self.assertEqual(root.findtext("setting[@id='subtitles.backgroundtype']"), '2')     # the copy is immutable
        self.style.apply_to(root)
        for key, value in (('subtitles.backgroundtype', '0'), ('subtitles.bordersize', '25')):
            node = root.find("setting[@id='%s']" % key)
            self.assertEqual(node.text, value)
            self.assertIsNone(node.get('default'))        # apply_live_settings passes over default="true" rows
        self.assertEqual(root.findtext("setting[@id='subtitles.fontsize']"), '52')

    def test_the_pack_a_fresh_install_gets_has_no_box(self):
        root = ET.parse(REPO / 'userdata/guisettings.xml').getroot()
        for key, value in self.style.OUTLINE.items():
            node = root.find("setting[@id='%s']" % key)
            self.assertEqual(node.text, str(value))
            self.assertIsNone(node.get('default'))
        policy = json.loads((REPO / 'userdata/config_policy.json').read_text('utf-8'))
        self.assertEqual(policy['config_version'], '2.0.12')

    def test_the_shipped_values_are_the_ones_the_wizards_copy_of_the_pack_carries(self):
        with zipfile.ZipFile(ROOT / 'resources/bootstrap/config.zip') as pack:
            root = ET.fromstring(pack.read('guisettings.xml'))
        for key, value in self.style.BOX.items():
            self.assertEqual(root.findtext("setting[@id='%s']" % key), str(value), key)

    def test_the_restore_button_and_the_start_up_use_it(self):
        repair = (ROOT / 'resources/libs/gui_repair.py').read_text('utf-8')
        self.assertIn('subtitle_style.apply_to(root)', repair)
        startup = (ROOT / 'startup.py').read_text('utf-8')
        self.assertEqual(startup.count('subtitle_style.migrate()'), 1)
        self.assertLess(startup.index('subtitle_style.migrate()'), startup.index('gui_repair.offer_after_reset()'))


if __name__ == '__main__':
    unittest.main()
