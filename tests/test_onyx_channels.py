"""Onyx 1.0.33: a channel list in the player.

The owner, Nov 2026: "add a channel list button in Onyx's players -- I think the other skins have it" (FENtastic: the
live-TV channels and Idan Plus's channels and radio). QA Kodi 21, on the screen: an Idan Plus channel playing (כאן 11),
the player's controls showed the button beside the subtitles; it opened a panel on the right -- the channels (48), each
its logo and its name with what is on now; Up and Left to the radio (35 stations) and back; a press on a channel played
it, the panel closed and the player was full screen again.
"""
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'skin.povil.onyx'
XML = SKIN / 'xml'
SHOWN = 'VideoPlayer.Content(LiveTV) | String.Contains(Player.FolderPath,plugin.video.idanplus)'


class TheButton(unittest.TestCase):
    def setUp(self):
        self.osd = ET.parse(XML / 'VideoOSD.xml').getroot()

    def button(self, bid):
        return next(c for c in self.osd.iter('control') if c.get('id') == str(bid))

    def test_it_shows_while_a_channel_plays_and_opens_the_right_list(self):
        b = self.button(7027)
        self.assertEqual(b.findtext('visible'), SHOWN, 'only then: the row is full while a film or an episode plays')
        self.assertEqual([(c.get('condition'), c.text) for c in b.findall('onclick')],
                         [(None, 'Dialog.Close(VideoOSD,true)'),
                          ('VideoPlayer.Content(LiveTV)', 'ActivateWindow(PVROSDChannels)'),
                          ('!VideoPlayer.Content(LiveTV)', 'ActivateWindow(1164)')])
        self.assertEqual(b.findtext('texturefocus'), 'povil/osd/channels_fo.png')
        for name in ('channels.png', 'channels_fo.png', 'channels_nf.png'):
            self.assertTrue((SKIN / 'media/povil/osd' / name).exists(), name)

    def test_every_player_style_has_it(self):
        # (the reviewer: Onyx's own player only, at first -- the owner asked for "Onyx's players"; FENtastic's simple
        # and advanced players, of which Onyx's are redraws, have their Idan Plus channels button)
        clicks = [(None, 'Dialog.Close(VideoOSD,true)'), ('VideoPlayer.Content(LiveTV)', 'ActivateWindow(PVROSDChannels)'),
                  ('!VideoPlayer.Content(LiveTV)', 'ActivateWindow(1164)')]
        for bid in (7027, 7126, 7163, 7215, 7256):
            with self.subTest(bid):
                b = self.button(bid)
                self.assertEqual(b.findtext('visible'), SHOWN)
                self.assertEqual([(c.get('condition'), c.text) for c in b.findall('onclick')], clicks)
        # where it is a row's first button, the row beside it leads to it while it is on the screen
        for row, target in (('7101', '7126'), ('7181', '7215')):
            with self.subTest(row):
                ups = [(n.get('condition'), n.text) for n in self.button(row).findall('onright')]
                self.assertEqual(ups[0], ('Control.IsVisible(%s)' % target, target))

    def test_it_sits_beside_the_subtitles_button(self):
        row = [c.get('id') for c in self.osd.iter('control') if c.get('id') in ('7024', '7027', '7020', '7021')]
        self.assertEqual(row[:2], ['7024', '7027'])

    def test_the_bar_gives_way_to_the_channels_window(self):
        source = (ROOT / 'tools/skin_onyx/gen_osd.py').read_text(encoding='utf-8')
        self.assertIn("'Window.IsActive(subtitlesearch) | Window.IsActive(%d)' % CHANNELS_ID", source)


class TheWindow(unittest.TestCase):
    def setUp(self):
        self.win = ET.parse(XML / 'Custom_POVILChannels.xml').getroot()

    def test_a_dialog_over_the_picture_with_idan_plus_s_channels_or_radio(self):
        self.assertEqual((self.win.get('type'), self.win.get('id')), ('dialog', '1164'))
        lst = next(c for c in self.win.iter('control') if c.get('id') == '9520')
        self.assertEqual(lst.findtext('orientation'), 'vertical')
        self.assertEqual([c.text for c in lst.findall('content')], ['$VAR[POVIL_ChannelsPath]'],
                         'one address: Kodi does not read the list again when a <content> condition changes (QA Kodi)')
        includes = (XML / 'Includes_POVIL_Home.xml').read_text(encoding='utf-8')
        var = includes.split('<variable name="POVIL_ChannelsPath">')[1].split('</variable>')[0]
        self.assertIn('<value condition="String.IsEqual(Window(home).Property(povil.ch.kind),radio)">plugin://plugin.video.idanplus/', var)
        self.assertIn('mode=3', var.split('</value>')[0], 'radio')
        self.assertIn('mode=1', var.split('</value>')[1], 'the channels')

    def test_a_press_plays_the_channel_and_closes(self):
        lst = next(c for c in self.win.iter('control') if c.get('id') == '9520')
        self.assertEqual([(c.get('condition'), c.text) for c in lst.findall('onclick')],
                         [('!ListItem.IsFolder', 'PlayMedia($ESCINFO[ListItem.FileNameAndPath])'),
                          ('ListItem.IsFolder', 'ActivateWindow(Videos,$ESCINFO[ListItem.FolderPath],return)'),
                          (None, 'Dialog.Close(1164)')])
        self.assertEqual([(c.get('condition'), c.text) for c in lst.findall('onup')],
                         [('!String.IsEqual(Window(home).Property(povil.ch.kind),radio)', '9511'),
                          ('String.IsEqual(Window(home).Property(povil.ch.kind),radio)', '9512')])

    def test_right_to_left_the_channels_chip_on_the_right_and_the_names_in_a_text_box(self):
        chips = next(c for c in self.win.iter('control') if c.get('id') == '9510')
        self.assertEqual([c.get('id') for c in chips.findall('control')], ['9512', '9511'], 'a grouplist lays out left to right')
        self.assertEqual([c.findtext('onfocus') for c in chips.findall('control')],
                         ['SetProperty(povil.ch.kind,radio,home)', 'SetProperty(povil.ch.kind,tv,home)'])
        lst = next(c for c in self.win.iter('control') if c.get('id') == '9520')
        names = [c for c in lst.iter('control') if c.findtext('label') == '$INFO[ListItem.Label]']
        self.assertEqual({c.get('type') for c in names}, {'textbox'}, 'Kodi cut a one-line Hebrew label at its start')
        self.assertTrue(all(c.findtext('align') == 'right' for c in names))
        self.assertIn('<onload condition="String.IsEmpty(Window(home).Property(povil.ch.kind))">SetProperty(povil.ch.kind,tv,home)</onload>',
                      (XML / 'Custom_POVILChannels.xml').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
