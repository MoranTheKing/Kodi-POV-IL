"""Player selection must preserve playback and instantiate one control set."""
import importlib.util
import json
import re
import sys
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'skin.povil.nox/xml'


def load_player(choice, current='__advancedplayer', provider='pov', playing=True):
    calls = []
    info = {'Skin.String(__chooseplayer)': current, 'VideoPlayer.UniqueID(tmdb)': '123',
            'VideoPlayer.Season': '2', 'VideoPlayer.Episode': '3',
            'VideoPlayer.Title': 'Title', 'VideoPlayer.TVShowTitle': 'Series',
            'VideoPlayer.IMDBNumber': 'tt1234567', 'VideoPlayer.Year': '2020'}
    xbmc = types.SimpleNamespace(getInfoLabel=lambda key: info.get(key, ''),
        getCondVisibility=lambda key: playing if key == 'Player.Playing' else key in
            ('Window.IsVisible(videoosd)', 'Player.HasVideo', 'VideoPlayer.Content(episodes)',
             'System.HasAddon(plugin.video.umbrella)'), executebuiltin=calls.append,
        executeJSONRPC=lambda _req: json.dumps({'result': {'totaltime': {'hours': 0, 'minutes': 42, 'seconds': 28}}}))
    dialog = types.SimpleNamespace(select=lambda *_a, **_kw: choice, notification=lambda *_a: None)
    with patch.dict(sys.modules, {'xbmc': xbmc, 'xbmcgui': types.SimpleNamespace(Dialog=lambda: dialog),
            'xbmcaddon': types.SimpleNamespace(Addon=lambda _id: types.SimpleNamespace(getSetting=lambda _k: provider))}):
        spec = importlib.util.spec_from_file_location('qa_player_styles',
            ROOT / 'plugin.program.kodipovilwizard/resources/libs/player_styles.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module, calls


class NoxPlayerStylesTests(unittest.TestCase):
    def test_selection_and_cancel_preserve_playback(self):
        module, calls = load_player(2); module.choose()
        self.assertEqual(calls, ['Dialog.Close(videoosd,true)',
            'Skin.SetString(__chooseplayer,__netflixplayer)', 'ActivateWindow(videoosd)'])
        module, calls = load_player(-1); module.choose()
        self.assertEqual(calls, ['Dialog.Close(videoosd,true)', 'ActivateWindow(videoosd)'])

    def test_separate_control_sets_and_shared_settings_entry(self):
        root = ET.parse(SKIN / 'VideoOSD.xml').getroot()
        includes = root.findall('controls/include')
        self.assertEqual(len(includes), 5)
        self.assertEqual(len({inc.get('condition') for inc in includes}), 5)
        self.assertFalse(root.findall('.//control'), 'duplicate invisible IDs must not be instantiated')
        for filename in ('SkinSettings.xml', 'Custom_1101_SettingsList.xml',
                         'Includes_POVIL_NativePlayer.xml', 'Includes_POVIL_Players.xml'):
            self.assertIn('mode=choose_player_style', (SKIN / filename).read_text('utf8'))

    def test_port_conditions_and_dependencies(self):
        root = ET.parse(SKIN / 'Includes_POVIL_Players.xml').getroot()
        names = {(c.tag, c.get('name')) for c in root if c.get('name')}
        for element in root.iter():
            for key, value in element.attrib.items():
                if key == 'condition':
                    self.assertEqual(value.count('('), value.count(')'), value)
                    self.assertEqual(value.count('['), value.count(']'), value)
            if element.tag in ('texture', 'texturefocus', 'texturenofocus', 'icon'):
                self.assertFalse((element.text or '').startswith(('http://', 'https://')))
        text = ET.tostring(root, encoding='unicode')
        for kind, name in re.findall(r'\$(VAR|EXP)\[([^\]]+)\]', text):
            if name.startswith('POVIL_Player_'):
                self.assertIn(('variable' if kind == 'VAR' else 'expression', name.split(',')[0]), names)

    def test_source_routes_use_selected_provider_and_pause_only_when_playing(self):
        module, calls = load_player(0, provider='umbrella', playing=False); module.change_source()
        self.assertEqual(len(calls), 1)
        self.assertIn('plugin.video.umbrella/?', calls[0])
        self.assertTrue(calls[0].startswith('PlayMedia('), 'Umbrella needs a resolving media handle')
        self.assertIn('action=play_Item', calls[0]); self.assertIn('select=0', calls[0])
        params = parse_qs(urlparse(calls[0][len('PlayMedia('):-1]).query)
        meta = json.loads(params['meta'][0])
        self.assertEqual((meta['season'], meta['episode'], meta['tvshowtitle'], meta['duration']), ('2', '3', 'Series', 2548))
        module, calls = load_player(0); module.change_source()
        self.assertEqual(calls[0], 'PlayerControl(Play)')
        self.assertIn('mode=play_media', calls[1]); self.assertIn('autoplay=false', calls[1])

    def test_seek_labels_and_remote_navigation_match_real_controls(self):
        root = ET.parse(SKIN / 'Includes_POVIL_Players.xml').getroot()
        for direction, sign in [('forward', 1), ('rewind', -1)]:
            block = root.find("include[@name='POVIL_Player_seek_" + direction + "_osd_item']")
            for item in block.findall('content/item')[2:]:
                minutes = int(item.findtext('label').split()[0])
                self.assertEqual(item.findtext('onclick').lower(), 'seek(%d)' % (minutes * 60 * sign))
        text = ET.tostring(root, encoding='unicode')
        self.assertNotIn('60015', text); self.assertNotIn('<onup>87</onup>', text)
        for number in range(1, 5):
            style = root.find("include[@name='POVIL_Player_videosd%d']" % number)
            self.assertIn('POVIL_Player_StyleSelector', [inc.text for inc in style.findall('include')])
        native = ET.parse(SKIN / 'Includes_POVIL_NativePlayer.xml')
        self.assertIn('mode=player_change_source', ET.tostring(native.getroot(), encoding='unicode'))
        self.assertIn('mode=player_episodes', ET.tostring(native.getroot(), encoding='unicode'))

    def test_native_source_helper_survives_legacy_repair(self):
        spec = importlib.util.spec_from_file_location('nox_source_repair',
            ROOT / 'service.subtitles.kodipovilai/resources/lib/nox_change_source_patcher.py')
        repair = importlib.util.module_from_spec(spec); spec.loader.exec_module(repair)
        source = (SKIN / 'Includes_POVIL_NativePlayer.xml').read_text('utf8')
        repaired = repair._REVERT_RE.sub('', source)
        self.assertIn('mode=player_change_source', repaired)
        self.assertEqual(len(ET.fromstring(repaired).findall(".//control[@id='39517']")), 1)


if __name__ == '__main__':
    unittest.main()
