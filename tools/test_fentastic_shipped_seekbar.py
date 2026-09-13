"""Release regression: actual FENtastic seekbar must parse before startup repair."""
from pathlib import Path
import re
import tempfile
import importlib.util
import unittest
import xml.etree.ElementTree as ET
import zipfile
ROOT=Path(__file__).resolve().parents[1]
REPAIR=ROOT/'addons/service.subtitles.kodipovilai/resources/skin_repair/fentastic_xml/DialogSeekBar.xml'
MEMBER='addons/skin.fentastic/xml/DialogSeekBar.xml'

class ShippedSeekbar(unittest.TestCase):
    def test_source_repair_is_valid_window_with_controls(self):
        root=ET.fromstring(REPAIR.read_bytes())
        self.assertEqual(root.tag,'window')
        self.assertIsNotNone(root.find('controls'))
        self.assertIsNotNone(root.find("controls/control[@type='group']"))

    def test_manifest_selected_skin_payload_parses_and_matches_repair(self):
        config=(ROOT/'wizard/assets/build.txt').read_text(encoding='utf-8')
        for field in ('gui','url'):
            urls=re.findall(r'^'+field+r'="([^"]+)"',config,re.M)
            self.assertEqual(len(urls),1)
            package=ROOT/'dist'/urls[0].rsplit('/',1)[-1]
            with self.subTest(package=package.name),zipfile.ZipFile(package) as archive:
                data=archive.read(MEMBER)
                self.assertEqual(ET.fromstring(data).tag,'window')
                self.assertEqual(data,REPAIR.read_bytes())


    def test_builder_repairs_malformed_existing_skin_only(self):
        spec=importlib.util.spec_from_file_location('quickfix_seek_review',ROOT/'tools/build_addon_quickfix.py')
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        repair_name=builder.SEEK_REPAIR
        pool=builder.POOL_MEMBER
        valid=b'<window><controls><!-- user layout --></controls></window>'
        for skin in (b'<window><controls><control></controls></window>',valid,None):
            with self.subTest(skin=skin),tempfile.TemporaryDirectory() as d:
                d=Path(d);old=d/'old.zip';addon=d/'addon.zip';new=d/'new.zip'
                with zipfile.ZipFile(old,'w') as z:
                    z.writestr(repair_name,REPAIR.read_bytes());z.writestr(pool,b'unchanged')
                    z.writestr('addons/unrelated/file.txt',b'preserve')
                    if skin is not None:z.writestr(MEMBER,skin)
                with zipfile.ZipFile(addon,'w') as z:
                    z.writestr(repair_name[len('addons/'):],REPAIR.read_bytes());z.writestr(pool[len('addons/'):],b'unchanged')
                changed=builder.build(old,addon,new);builder.verify(old,new,changed)
                with zipfile.ZipFile(new) as z:
                    self.assertEqual(z.read('addons/unrelated/file.txt'),b'preserve')
                    if skin is None:self.assertNotIn(MEMBER,z.namelist())
                    elif skin==valid:self.assertEqual(z.read(MEMBER),valid)
                    else:
                        self.assertEqual(z.read(MEMBER),REPAIR.read_bytes())
                        self.assertEqual(ET.fromstring(z.read(MEMBER)).tag,'window')
                        self.assertEqual(changed,[MEMBER])

if __name__=='__main__':unittest.main()
