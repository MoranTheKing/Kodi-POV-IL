"""All skin child homes, native presets, live-source denial and age isolation."""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / 'plugin.program.kodipovilwizard/resources/libs'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class ChildProfilesTests(unittest.TestCase):
    def setUp(self):
        self.kodi = types.SimpleNamespace(getLocalizedString=lambda n: 'L'+str(n),
            executebuiltin=Mock(), getCondVisibility=Mock(return_value=False))
        self.gui = types.SimpleNamespace(getCurrentWindowDialogId=Mock(return_value=0))
        self.modules = patch.dict(sys.modules, {'xbmc':self.kodi, 'xbmcgui':self.gui,
            'xbmcaddon':types.SimpleNamespace(Addon=lambda _:types.SimpleNamespace(
                getAddonInfo=lambda _:str(ROOT/'plugin.program.kodipovilwizard')))})
        self.modules.start(); self.addCleanup(self.modules.stop)
        self.child = load('child_ui_test', LIBS/'child_profiles.py')

    def test_each_skin_home_keeps_adult_controls_and_hooks_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as raw:
            for skin in self.child.SKINS:
                folder = Path(raw)/skin/'xml';folder.mkdir(parents=True)
                path = folder/'Home.xml'
                original = '<window><onload>Original</onload><defaultcontrol>42</defaultcontrol><controls><control type="button" id="42"><onclick>OriginalRoute</onclick></control></controls></window>'
                path.write_text(original)
                (folder/'Font.xml').write_text('<fonts><fontset><font><name>actualfont</name><size>30</size></font></fontset></fonts>')
                self.assertTrue(self.child.install_home(str(path)))
                first = path.read_bytes();self.assertFalse(self.child.install_home(str(path)))
                self.assertEqual(first,path.read_bytes())
                root = ET.fromstring(first)
                adult = root.find("controls/control[@id='9879']")
                self.assertEqual(adult.findtext('visible'),'!Skin.HasSetting(POVILChild)')
                self.assertEqual(adult.findtext("control[@id='42']/onclick"),'OriginalRoute')
                self.assertIn('Original',[r.text for r in root.findall('onload')])
                child = root.find("controls/control[@id='9880']")
                self.assertEqual(child.findtext('visible'),'Skin.HasSetting(POVILChild)')
                routes = [r.text for r in child.findall('.//onclick')]
                self.assertTrue(all('profile_child_open' in r or 'mode=profiles)' in r or 'profile_skin' in r for r in routes))
                self.assertNotIn('idanplus',first.decode())
                self.assertEqual(set(f.text for f in child.iter('font')),{'actualfont'})

    def test_flags_cover_all_skins_without_overwriting_preferences(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw)/'addon_data/skin.estuary/settings.xml';path.parent.mkdir(parents=True)
            path.write_text('<settings><setting id="my-choice">custom</setting></settings>')
            self.child.seed_skin_flags(raw)
            self.assertEqual(ET.parse(path).findtext("setting[@id='my-choice']"),'custom')
            for skin in self.child.SKINS:
                self.assertEqual(ET.parse(Path(raw)/'addon_data'/skin/'settings.xml').findtext("setting[@id='POVILChild']"),'true')

    def test_hebrew_controls_never_select_icon_or_codec_fonts(self):
        with tempfile.TemporaryDirectory() as raw:
            path=Path(raw)/'Home.xml'
            path.write_text('<window><controls/></window>')
            (Path(raw)/'Font.xml').write_text('''<fonts><fontset>
                <font><name>PlayerCodecs</name><filename>Nick-Titling.ttf</filename><size>25</size></font>
                <font><name>Icons</name><filename>awesome.ttf</filename><size>30</size></font>
                <font><name>HebrewText</name><filename>Arial.ttf</filename><size>30</size></font>
                </fontset></fonts>''')
            self.child.install_home(str(path))
            child=ET.parse(path).find("controls/control[@id='9880']")
            self.assertEqual({f.text for f in child.iter('font')},{'HebrewText'})
            for button in child.findall(".//control[@type='button']"):
                self.assertEqual(button.findtext('textcolor'),'FFFFFFFF')
                self.assertEqual(button.findtext('focusedcolor'),'FFF0D394')

    def test_settings_preset_selects_all_only_in_its_own_dialog(self):
        self.gui.getCurrentWindowDialogId.return_value=12000
        self.kodi.getInfoLabel=Mock(return_value='unrelated')
        state={'settings_pending':True}
        self.assertFalse(self.child.preset_native_locks(state))
        self.kodi.executebuiltin.assert_not_called()
        self.kodi.getInfoLabel.side_effect=lambda key:'L20043' if key=='Control.GetLabel(1)' else 'L593'
        listing=types.SimpleNamespace(isVisible=lambda:True)
        self.gui.Window=lambda _:types.SimpleNamespace(getControl=lambda _:listing)
        self.assertTrue(self.child.preset_native_locks(state))
        self.assertTrue(state['completed'])
        self.assertFalse(state['settings_pending'])
        self.assertEqual([r.args[0] for r in self.kodi.executebuiltin.call_args_list],
                         ['SetFocus(3,1,absolute)','Action(Select,12000)'])

    def test_nox_root_includes_keep_native_home_and_gain_child_skin_selection(self):
        with tempfile.TemporaryDirectory() as raw:
            path=Path(raw)/'Home.xml'
            text='<window><defaultcontrol>9000</defaultcontrol><include condition="Skin.HasSetting(POVILChild)" content="skin_home_child"/><include condition="!Skin.HasSetting(POVILChild)" content="original_home"/></window>'
            path.write_text(text)
            self.assertTrue(self.child.install_home(str(path)))
            self.assertEqual(path.read_text(),text)
            self.assertFalse(self.child.install_home(str(path)))
            section=ET.parse(Path(raw)/'Home_child.xml').find('include')
            self.assertEqual(section.findtext('defaultcontrol'),'9500')
            self.assertTrue(any('profile_skin' in r.text for r in section.findall('.//onclick')))

    def test_arctic_fuse_fonts_are_resolved_from_parameterized_include(self):
        with tempfile.TemporaryDirectory() as raw:
            path=Path(raw)/'Home.xml';path.write_text('<window><controls/></window>')
            (Path(raw)/'Font.xml').write_text('<fonts><fontset><include content="Font_Default"/></fontset></fonts>')
            names=('font_title_midi','font_head_bold','font_main','font_mini')
            (Path(raw)/'Includes_Font.xml').write_text('<includes><include><definition>'+''.join(
                '<font><name>'+n+'</name><size>$PARAM[size]</size></font>' for n in names)+
                '</definition></include></includes>')
            self.child.install_home(str(path))
            self.assertEqual({r.text for r in ET.parse(path).findall('.//font')},set(names))
            login = ET.parse(ROOT/'plugin.program.kodipovilwizard/resources/skins/Default/1080i/ProfileLogin.xml').getroot()
            self.child.adapt_fonts(login, str(path))
            self.assertEqual({r.text for r in login.iter('font')},set(names))

    def test_lock_defaults_never_change_pin_video_or_repeat_parent_choices(self):
        controls = {-180:('L20068',False),-178:('L20038',False),-177:('L20039',False),
                    -176:('L20040',True),-175:('L20041',False),-174:('L20042',False),
                    -173:('L20043',False),-172:('L24090',False)}
        def control(i):
            if i not in controls:raise RuntimeError()
            label,selected=controls[i]
            if label in ('L20068','L20043'):
                return types.SimpleNamespace(getLabel=lambda:label)
            return types.SimpleNamespace(isSelected=lambda:selected,setSelected=Mock())
        self.gui.Window=lambda _:types.SimpleNamespace(getControl=control)
        self.gui.getCurrentWindowDialogId.return_value=10131
        state={};self.child.preset_native_locks(state)
        sent=[c.args[0] for c in self.kodi.executebuiltin.call_args_list]
        self.assertEqual(sent,['SendClick(10131,-178)','SendClick(10131,-175)',
                               'SendClick(10131,-174)','SendClick(10131,-172)',
                               'SendClick(10131,-173)'])
        self.child.preset_native_locks(state)
        self.assertEqual(len(sent),self.kodi.executebuiltin.call_count)
        state['completed']=True;state['in_locks']=False
        self.child.preset_native_locks(state)
        self.assertEqual(len(sent),self.kodi.executebuiltin.call_count)

    def test_unclassified_live_source_passes_adult_and_denies_child_and_corrupt_policy(self):
        guard=load('live_guard_test',LIBS/'patches/profile_age_guard.py')
        dialog=Mock();plugin=Mock()
        with patch.dict(sys.modules,{'xbmcgui':types.SimpleNamespace(Dialog=lambda:dialog),'xbmcplugin':plugin}), patch.object(sys,'argv',['plugin://idanplus','1','']):
            for policy,expected in ((None,True),({'age':17},False),({'blocked':True},False)):
                with patch.object(guard,'active_policy',return_value=policy):
                    self.assertEqual(guard.unclassified_source_allowed(),expected)
            self.assertEqual(plugin.endOfDirectory.call_count,2)


if __name__ == '__main__':unittest.main()
