"""Onyx's player says what is playing: pills over the controls, the provider one of them (Onyx 1.0.12, 1.0.15)."""

import importlib.util
import re
import sys
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
XML = ROOT / 'skin.povil.onyx/xml'
PILLS = ('POVIL_OSD_Res', 'POVIL_OSD_Fps', 'POVIL_OSD_Hdr', 'POVIL_OSD_Audio', 'POVIL_OSD_Codec')


def remember():
    xbmc = types.SimpleNamespace(LOGINFO=1, LOGWARNING=2, LOGERROR=3, log=lambda *a, **k: None,
                                 translatePath=lambda p: p)
    stubs = {'xbmc': xbmc, 'xbmcgui': types.SimpleNamespace(), 'xbmcaddon': types.SimpleNamespace(),
             'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)}
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location(
            'pov_source_remember_under_test',
            ROOT / 'plugin.program.kodipovilwizard/resources/libs/patches/pov_source_remember.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class PlayerPillsTests(unittest.TestCase):
    def test_both_player_windows_carry_the_pills_and_none_takes_the_focus(self):
        # (the controls draw them twice: in Onyx's own player and in the large one, gen_osd_styles.py)
        for name, times in (('VideoOSD.xml', 2), ('VideoFullScreen.xml', 1)):
            root = ET.parse(XML / name).getroot()
            pills = [c for c in root.iter('control')
                     if c.get('type') == 'button' and (c.findtext('label') or '').startswith('$VAR[POVIL_OSD_')]
            self.assertEqual(sorted(c.findtext('label')[5:-1] for c in pills), sorted(list(PILLS + ('POVIL_OSD_Provider',)) * times), name)
            for pill in pills:
                self.assertEqual(pill.findtext('enable'), 'false', 'a pill is not a stop for the remote')
                self.assertEqual(pill.findtext('width'), 'auto')
                self.assertIn('Control.GetLabel(', pill.findtext('visible'), 'a pill with nothing to say is not drawn')

    def test_the_pills_read_right_to_left_from_the_picture_size(self):
        text = (XML / 'VideoOSD.xml').read_text('utf-8')
        order = re.findall(r'<label>\$VAR\[(POVIL_OSD_(?:Res|Fps|Hdr|Audio|Codec))\]</label><enable>', text)
        # a right-aligned row lays its items out left to right: the last one is read first
        self.assertEqual(order[-1], 'POVIL_OSD_Res')
        self.assertEqual(order[0], 'POVIL_OSD_Codec')

    def test_the_variables_name_what_the_decoder_reports(self):
        text = (XML / 'Includes_POVIL_Home.xml').read_text('utf-8')
        for name in PILLS + ('POVIL_OSD_AudioCodec', 'POVIL_OSD_Provider'):
            self.assertIn('<variable name="%s">' % name, text)
        self.assertIn('String.IsEqual(VideoPlayer.HdrType,dolbyvision)">Dolby Vision<', text)
        self.assertIn('String.IsEqual(VideoPlayer.VideoResolution,4K)">4K<', text)
        self.assertIn('String.IsEqual(VideoPlayer.AudioChannels,6)">$VAR[POVIL_OSD_AudioCodec] 5.1<', text)
        self.assertIn('String.IsEqual(VideoPlayer.AudioCodec,eac3)">DD+<', text)

    def test_the_pills_say_it_the_way_people_do(self):
        text = (XML / 'Includes_POVIL_Home.xml').read_text('utf-8')
        # Kodi prints 25.000: said as 25; a rate with no short name keeps Kodi's figure
        self.assertIn('String.IsEqual(Player.Process(videofps),25.000)">25 fps<', text)
        self.assertIn('String.IsEqual(Player.Process(videofps),59.940)">59.94 fps<', text)
        self.assertIn('">$INFO[Player.Process(videofps)] fps<', text)
        # an HDR kind this list does not know is still HDR, after the known ones
        self.assertLess(text.index('VideoPlayer.HdrType,hlg)'), text.index('!String.IsEmpty(VideoPlayer.HdrType)">HDR<'))
        self.assertIn('String.StartsWith(VideoPlayer.AudioCodec,pcm)">PCM<', text)
        self.assertIn('String.IsEqual(VideoPlayer.AudioCodec,dtshd_ma_x_imax)">DTS:X<', text)
        for fourcc in ('hvc1', 'hev1', 'dvh1', 'dvhe'):
            self.assertIn('String.IsEqual(VideoPlayer.VideoCodec,%s)">HEVC<' % fourcc, text)

    def test_the_provider_is_shown_only_for_the_source_it_was_named_for(self):
        text = (XML / 'Includes_POVIL_Home.xml').read_text('utf-8')
        block = text[text.index('<variable name="POVIL_OSD_Provider">'):]
        block = block[:block.index('</variable>')]
        self.assertIn('String.IsEqual(Window(Home).Property(povil_osd_provider_for),'
                      'Window(Home).Property(pov_picked_source_name))', block)
        self.assertIn('!VideoPlayer.Content(LiveTV)', block)
        # a debrid service plays a web stream: a library file or another add-on's resolved item shows none
        self.assertIn('[String.StartsWith(Player.Folderpath,http) | '
                      'String.Contains(Player.Folderpath,plugin.video.pov)]', block)
        # a pill of its own, in gold, the last one read (the owner, Nov 2026: "the source's pills at the bottom")
        for name in ('VideoOSD.xml', 'VideoFullScreen.xml'):
            text = (XML / name).read_text('utf-8')
            self.assertNotIn('$VAR[POVIL_OSD_Provider,', text, 'no longer a word in the details line')
            pill = re.search(r'<control type="button"[^>]*>(?:(?!</control>).)*<label>\$VAR\[POVIL_OSD_Provider\]</label>', text)
            self.assertIsNotNone(pill, name)
            self.assertIn('<textcolor>povil_gold</textcolor>', pill.group(0))
            self.assertLess(pill.start(), text.index('<label>$VAR[POVIL_OSD_Codec]</label>'), 'leftmost: read last')

    def test_the_pills_sit_over_the_controls_not_under_the_title(self):
        # the owner, Nov 2026: "the source's pills at the bottom, a little above the player's bottom edge"
        osd = ET.parse(XML / 'VideoOSD.xml').getroot()
        pills = next(c for c in osd.iter('control') if c.get('description') == 'what is playing')
        buttons = next(c for c in osd.iter('control') if c.get('id') == '7000')
        ratings = next(c for c in osd.iter('control') if c.get('description') == 'ratings')
        bottom = int(pills.findtext('top')) + int(pills.findtext('height'))
        self.assertLessEqual(bottom, int(buttons.findtext('top')))
        self.assertGreater(int(pills.findtext('top')), 700)
        self.assertLess(int(ratings.findtext('top')), 320, 'the ratings stay with the title')
        info = ET.parse(XML / 'VideoFullScreen.xml').getroot()
        low = next(c for c in info.iter('control') if c.get('description') == 'what is playing')
        self.assertTrue(700 < int(low.findtext('top')) < 980 - 42, 'over the timeline')

    def test_the_source_hook_names_the_provider_the_way_its_users_write_it(self):
        label = remember().provider_label
        self.assertEqual(label({'debrid': 'torbox'}), 'TorBox')
        self.assertEqual(label({'debrid': 'Real-Debrid'}), 'Real-Debrid')
        self.assertEqual(label({'cache_provider': 'Uncached TorBox'}), 'TorBox')
        self.assertEqual(label({'debrid': 'SomethingNew'}), 'SomethingNew')
        self.assertEqual(label({}), '')
        self.assertEqual(label({'debrid': 'x' * 40}), '', 'not a name: nothing is shown')

    def test_the_hook_ties_the_provider_to_the_source_it_picked(self):
        source = (ROOT / 'plugin.program.kodipovilwizard/resources/libs/patches/pov_source_remember.py').read_text('utf-8')
        self.assertIn("win.setProperty('povil_osd_provider', provider)", source)
        self.assertIn("win.setProperty('povil_osd_provider_for', name if provider else '')", source)


def player_styles(settings, builtins):
    """player_styles with a Kodi whose settings are the given dict."""
    import json

    def rpc(text):
        request = json.loads(text)
        name = request['params']['setting']
        if request['method'] == 'Settings.GetSettingValue':
            return json.dumps({'result': {'value': settings[name]}})
        if name == 'subtitles.marginvertical' and not 0 <= request['params']['value'] <= 30:
            return json.dumps({'error': {'code': -32602}})
        settings[name] = request['params']['value']
        return json.dumps({'result': True})

    xbmc = types.SimpleNamespace(LOGINFO=1, LOGWARNING=2, LOGERROR=3, log=lambda *a, **k: None,
                                 executeJSONRPC=rpc, executebuiltin=lambda text, *a: builtins.append(text),
                                 getCondVisibility=lambda text: False, getInfoLabel=lambda text: '')
    stubs = {'xbmc': xbmc, 'xbmcgui': types.SimpleNamespace(), 'xbmcaddon': types.SimpleNamespace(),
             'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p)}
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location(
            'player_styles_under_test', ROOT / 'plugin.program.kodipovilwizard/resources/libs/player_styles.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class SubtitlePositionTests(unittest.TestCase):
    def kodi(self, align=2, margin=3.3):
        self.settings = {'subtitles.align': align, 'subtitles.marginvertical': margin}
        self.builtins = []
        return player_styles(self.settings, self.builtins)

    def test_up_moves_the_text_up_the_screen_and_down_brings_it_back(self):
        styles = self.kodi()
        self.assertEqual(styles.subtitles_position('up'), 5.3)
        self.assertEqual(styles.subtitles_position('up'), 7.3)
        self.assertEqual(styles.subtitles_position('down'), 5.3)
        self.assertEqual(self.settings['subtitles.marginvertical'], 5.3)
        self.assertEqual(self.builtins, [])

    def test_it_stops_at_the_edge_and_at_the_ceiling(self):
        styles = self.kodi(margin=1.0)
        self.assertEqual(styles.subtitles_position('down'), 0.0)
        self.assertIsNone(styles.subtitles_position('down'), 'already at the edge')
        styles = self.kodi(margin=29.5)
        self.assertEqual(styles.subtitles_position('up'), 30.0)
        self.assertIsNone(styles.subtitles_position('up'))

    def test_a_top_position_grows_downward(self):
        styles = self.kodi(align=3, margin=4.0)
        self.assertEqual(styles.subtitles_position('up'), 2.0, 'up = toward the top edge the text is tied to')
        self.assertEqual(styles.subtitles_position('down'), 4.0)

    def test_the_manual_position_uses_kodis_own_shift(self):
        styles = self.kodi(align=0)
        self.assertIsNone(styles.subtitles_position('up'))
        self.assertEqual(self.builtins, ['Action(SubtitleShiftUp)'] * 4)
        self.assertEqual(self.settings['subtitles.marginvertical'], 3.3)

    def test_anything_else_changes_nothing(self):
        styles = self.kodi()
        self.assertIsNone(styles.subtitles_position(None))
        self.assertIsNone(styles.subtitles_position('sideways'))
        self.assertEqual(self.settings['subtitles.marginvertical'], 3.3)

    def test_the_player_has_the_two_buttons_and_the_home_a_power_button(self):
        osd = (XML / 'VideoOSD.xml').read_text('utf-8')
        for step, label in (('up', 'כתוביות למעלה'), ('down', 'כתוביות למטה')):
            self.assertIn('?mode=player_subs_position&amp;step=%s)' % step, osd)
            self.assertIn(label, (XML / 'Includes_POVIL_Home.xml').read_text('utf-8') + osd)
        for name in ('subup', 'subdown', 'power'):
            for suffix in ('', '_fo'):
                self.assertTrue((ROOT / 'skin.povil.onyx/media/povil/osd' / (name + suffix + '.png')).is_file(), name)
        router = (ROOT / 'plugin.program.kodipovilwizard/resources/libs/common/router.py').read_text('utf-8')
        self.assertIn("'player_subs_position', 'player_style'):", router, 'a kids profile may move its subtitles too')
        home = ET.parse(XML / 'Home.xml').getroot()
        power = next(c for c in home.iter('control') if c.get('id') == '9099')
        self.assertEqual(power.findtext('onclick'), 'ActivateWindow(ShutdownMenu)')
        # (Onyx 1.0.18: the tabs are the buttons of a list, and the list sends "left" of its first button here)
        bar = next(c for c in home.iter('control') if c.get('id') == '9000')
        self.assertEqual([c.get('id') for c in bar if c.tag == 'control'][0], power.findtext('onright'))
        self.assertEqual(bar.findtext('onleft'), '9099', 'one step left of the last tab')
        for name in ('clock', 'date'):
            label = next(c for c in home.iter('control') if c.get('description') == name)
            self.assertLessEqual(int(label.findtext('left')) + int(label.findtext('width')), int(power.findtext('left')),
                                 'the %s ends before the power button' % name)


if __name__ == '__main__':
    unittest.main()
