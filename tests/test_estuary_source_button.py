"""Repair an existing duplicate while preserving native action bytes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('estuary_source_repair',
    ROOT / 'service.subtitles.kodipovilai/resources/lib/estuary_change_source_patcher.py')
repair = importlib.util.module_from_spec(spec); spec.loader.exec_module(repair)
NATIVE = ('<control type="button" id="700458"><description>native</description>'
          '<onclick condition="Player.Playing">PlayerControl(Play)</onclick>'
          '<onclick>RunPlugin(plugin://plugin.video.pov/?mode=play_media&amp;'
          'mediatype=movie&amp;autoplay=false)</onclick></control>\r\n')
ANCHOR = '<control type="button" id="700452"><description>audio</description></control>\r\n'


class EstuarySourceButtonTests(unittest.TestCase):
    def apply(self, text):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'VideoOSD.xml'; path.write_bytes(text.encode())
            with patch.object(repair, '_osd_path', return_value=str(path)):
                status = repair.ensure_patched()
                result = path.read_bytes().decode()
                repeated = repair.ensure_patched()
                self.assertEqual(path.read_bytes().decode(), result)
            return status, result, repeated

    def test_real_duplicate_removed_and_native_pause_preserved(self):
        injected = repair._button_block('', '\r\n')
        status, result, _ = self.apply('<window><controls>\r\n'+NATIVE+injected+ANCHOR+'</controls></window>')
        self.assertEqual(status, 'deduplicated')
        self.assertIn(NATIVE, result)
        self.assertNotIn(repair.MARKER, result)
        self.assertEqual(len(ET.fromstring(result).findall(".//control[@id='700458']")), 1)

    def test_baked_action_under_another_id_needs_no_extra_button(self):
        original = '<window><controls>\r\n'+NATIVE.replace('700458','1234')+ANCHOR+'</controls></window>'
        status, result, _ = self.apply(original)
        self.assertEqual(status, 'unchanged'); self.assertEqual(result, original)

    def test_duplicate_without_marker_and_commented_examples(self):
        original='<window><controls>\r\n<!--'+NATIVE+'-->\r\n'+NATIVE+NATIVE+ANCHOR+'</controls></window>'
        status,result,_=self.apply(original)
        self.assertEqual(status, 'deduplicated')
        self.assertEqual(len(ET.fromstring(result).findall(".//control[@id='700458']")), 1)
        self.assertIn('<!--'+NATIVE+'-->', result)

    def test_comments_do_not_suppress_missing_button_repair(self):
        original = '<window><controls>\r\n<!--'+NATIVE+'-->\r\n'+ANCHOR+'</controls></window>'
        status, result, repeated = self.apply(original)
        self.assertEqual(status, 'patched'); self.assertEqual(repeated, 'unchanged')
        self.assertEqual(len(ET.fromstring(result).findall(".//control[@id='700458']")), 1)

    def test_lost_marker_with_comment_inside_native_button(self):
        native = NATIVE.replace('<onclick condition=', '<!-- AI_SUBS_CHGSRC_PAUSE --><onclick condition=')
        duplicate = NATIVE.replace('<onclick condition="Player.Playing">PlayerControl(Play)</onclick>', '')
        original = '<window><controls>\r\n'+native+duplicate+ANCHOR+'</controls></window>'
        status, result, repeated = self.apply(original)
        self.assertEqual(status, 'deduplicated')
        self.assertEqual(repeated, 'unchanged')
        self.assertIn(native, result)
        self.assertEqual(len(ET.fromstring(result).findall(".//control[@id='700458']")), 1)

    def test_commented_anchor_is_not_used_for_insertion(self):
        original = '<window><controls>\r\n<!--\r\n'+ANCHOR+'-->\r\n'+ANCHOR+'</controls></window>'
        status, result, _ = self.apply(original)
        self.assertEqual(status, 'patched')
        self.assertIn('<!--\r\n'+ANCHOR+'-->\r\n', result)
        self.assertEqual(len(ET.fromstring(result).findall(".//control[@id='700458']")), 1)

    def test_unrelated_id_owner_and_invalid_xml_are_not_overwritten(self):
        for fragment, expected in [('<control type="button" id="700458"><onclick>Other</onclick></control>','id_conflict'),
                                   ('<control>', 'parse_failed')]:
            original='<window><controls>\r\n'+fragment+ANCHOR+'</controls></window>'
            status,result,_=self.apply(original)
            self.assertEqual(status,expected); self.assertEqual(result,original)

    def test_active_twilight_icon_and_text_pair(self):
        legacy = ('<control type="radiobutton" id="700453">'
                  '<description>Twilight Switch Source Button</description>'
                  '<include content="OSDButtonAdvanced"><param name="label">'
                  '$LOCALIZE[700036]</param></include>'
                  '<onclick>RunPlugin(plugin://plugin.video.pov/?mode=play_media'
                  '&amp;media_type=movie&amp;autoplay=false)</onclick></control>')
        for addition in (NATIVE, repair._button_block('', '\r\n'), ''):
            original = '<window><controls><control type="grouplist">'+legacy+addition+'\r\n'+ANCHOR+'</control></controls></window>'
            _, result, repeated = self.apply(original)
            tree = ET.fromstring(result)
            self.assertIsNone(tree.find(".//control[@id='700453']"))
            self.assertEqual(len(tree.findall(".//control[@id='700458']")), 1)
            self.assertEqual(repeated, 'unchanged')

    def test_native_radiobutton_does_not_receive_extra_text_control(self):
        native = NATIVE.replace('type="button"', 'type="radiobutton"').replace('700458', '700453')
        original = '<window><controls>'+native+ANCHOR+'</controls></window>'
        _, result, repeated = self.apply(original)
        self.assertEqual(result, original)
        self.assertEqual(repeated, 'unchanged')

    def test_equivalent_different_id_preserved_in_separate_layout(self):
        native = NATIVE.replace('700458', '700453').replace('<description>native</description>',
                 '<description>Twilight Switch Source Button</description>')
        original = '<window><controls><control type="group">'+native+'</control><control type="group">'+NATIVE+ANCHOR+'</control></controls></window>'
        _, result, _ = self.apply(original)
        self.assertEqual(result, original)

    def test_same_group_different_id_equivalent_copy_removed(self):
        native = NATIVE.replace('700458', '700453').replace('<description>native</description>',
                 '<description>Twilight Switch Source Button</description>')
        original = '<window><controls><control type="group">'+native+NATIVE+ANCHOR+'</control></controls></window>'
        _, result, repeated = self.apply(original)
        self.assertIn(native, result)
        self.assertIsNone(ET.fromstring(result).find(".//control[@id='700458']"))
        self.assertEqual(repeated, 'unchanged')

    def test_old_bare_ampersand_urls_do_not_block_duplicate_repair(self):
        legacy = ('<control type="radiobutton" id="700453">'
                  '<description>Twilight Switch Source Button</description>'
                  '<onclick>RunPlugin(plugin://plugin.video.pov/?mode=play_media'
                  '&media_type=movie&autoplay=false)</onclick></control>')
        native = NATIVE.replace('&amp;', '&')
        original = '<window><controls>'+legacy+native+ANCHOR+'</controls></window>'
        status, result, repeated = self.apply(original)
        self.assertEqual(status, 'deduplicated')
        self.assertIn(native, result)
        self.assertNotIn('id="700453"', result)
        self.assertEqual(repeated, 'unchanged')
