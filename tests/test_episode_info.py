"""Native episode data stays current and focused UI needs no extra API reads."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
def load(filename):
    spec=importlib.util.spec_from_file_location('episode_'+Path(filename).stem,ROOT/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
info=load('plugin.program.kodipovilwizard/resources/libs/patches/pov_episode_info.py')
widgets=load('plugin.program.kodipovilwizard/resources/libs/fentastic_widgets.py')

class EpisodeInfoTests(unittest.TestCase):
    def test_real_episode_plot_is_preserved_and_title_is_supplied_separately(self):
        item=Mock();info.complete(item,{'plot':'Show plot'},{'plot':'Episode plot'},'Episode name')
        item.getVideoInfoTag.assert_not_called()
        self.assertIn(('povil_episode_name','Episode name'),[c.args for c in item.setProperty.call_args_list])
        self.assertIn(('povil_episode_plot_label','תקציר הפרק'),[c.args for c in item.setProperty.call_args_list])

    def test_empty_episode_plot_uses_cached_show_plot_with_an_explicit_label(self):
        item=Mock();episode={'plot':'','season':3,'episode':7,'duration':1800}
        before=dict(episode);info.complete(item,{'plot':'Show plot'},episode,'Episode name')
        item.getVideoInfoTag.return_value.setPlot.assert_called_once_with('Show plot')
        self.assertIn(('povil_episode_plot_label','תקציר הסדרה'),[c.args for c in item.setProperty.call_args_list])
        self.assertEqual(episode,before)

    def test_missing_all_plots_does_not_invent_a_synopsis(self):
        item=Mock();info.complete(item,{}, {},'Episode name')
        item.getVideoInfoTag.assert_not_called()
        self.assertIn(('povil_episode_plot_label',''),[c.args for c in item.setProperty.call_args_list])

    def test_live_panel_upgrade_preserves_other_controls_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'skin.fentastic/xml/Home.xml';path.parent.mkdir(parents=True)
            path.write_text('''<window><controls><control type="group" id="10"><visible>Skin.HasSetting(Disable.RatingsINF) | String.IsEmpty(Skin.String(mdblist_api_key))</visible><control type="textbox"><label>$VAR[InfoPanelEpisode]</label></control><control type="label"><label>$LOCALIZE[700015] $INFO[ListItem.Season], $LOCALIZE[700016] $INFO[ListItem.Episode]</label></control></control><include condition="![Skin.HasSetting(Disable.RatingsINF) | String.IsEmpty(Skin.String(mdblist_api_key))]" content="RatingsInfoPanel"><param name="width" value="410"/></include><control type="label" id="99"><label>Custom item</label></control></controls></window>''',encoding='utf8')
            self.assertEqual(widgets.repair_episode_panel(directory),1)
            root=ET.parse(path).getroot()
            self.assertEqual(root.find('.//control[@id="99"]/label').text,'Custom item')
            include=root.find('.//include[@content="RatingsInfoPanel"]')
            self.assertNotIn('ListItem',include.get('condition'))  # Runtime visibility, not include-time focus.
            parents={child:parent for parent in root.iter() for child in parent}
            self.assertEqual(parents[include].find('visible').text,'!String.IsEqual(ListItem.DBtype,episode)')
            saved=path.read_bytes();self.assertEqual(widgets.repair_episode_panel(directory),0)
            self.assertEqual(path.read_bytes(),saved)

    def test_shipped_and_repaired_panels_use_identical_episode_fields(self):
        root=ET.parse(ROOT/'skin.fentastic/xml/Home.xml').getroot()
        self.assertEqual(sum(node.text==widgets.EPISODE_INFO for node in root.iter('label')),1)
        for field in ('povil_episode_name','ListItem.Premiered','ListItem.Duration','ListItem.Mpaa','ListItem.Plot'):
            self.assertIn(field,widgets.EPISODE_INFO)

if __name__=='__main__':unittest.main()
