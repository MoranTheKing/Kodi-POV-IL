"""Onyx 1.0.22 / Wizard 0.5.23: the players the Onyx skin can show besides its own -- FENtastic's four (simple,
advanced, Netflix-style, large), drawn in Onyx's look (tools/skin_onyx/gen_osd_styles.py), chosen in the Wizard
(resources/libs/onyx_player_style.py) from the settings tile "סוג נגן" or the button "החלפת נגן" in every player.

The owner, Nov 2026: "let the players be switched in the new skin too, as in the other skins ... and check every
player in depth". QA Kodi, on the screen: each style opens on its main button, Right and Left walk every button
of it and stop at its ends, the zoom buttons zoom in and back to the same picture, and the subtitle-sync button
brings Kodi's slider up (it brought nothing in Onyx 1.0.21: the action was sent while the controls closed).
"""
import importlib.util
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'skin.povil.onyx'
TOOLS = ROOT / 'tools/skin_onyx'
OSD = SKIN / 'xml/VideoOSD.xml'
sys.path.insert(0, str(TOOLS))
import gen_osd_styles as S  # noqa: E402
sys.path.remove(str(TOOLS))
spec = importlib.util.spec_from_file_location('onyx_player_style_under_test',
                                              ROOT / 'plugin.program.kodipovilwizard/resources/libs/onyx_player_style.py')
choice = importlib.util.module_from_spec(spec)
spec.loader.exec_module(choice)


def osd():
    return ET.parse(OSD).getroot()


def groups(root):
    return {g.get('description'): g for g in root.iter('control') if g.get('type') == 'group' and g.get('description')}


class StyleTests(unittest.TestCase):
    def test_one_group_per_style_each_shown_for_its_choice_only(self):
        found = groups(osd())
        self.assertIn('the Onyx player', found)
        onyx = found['the Onyx player'].findtext('visible')
        for style in S.STYLES:
            group = found['player style: %s' % style]
            self.assertEqual(group.findtext('visible'), 'Player.HasMedia + String.IsEqual(Skin.String(POVILPlayer),%s)' % style)
            self.assertIn('String.IsEqual(Skin.String(POVILPlayer),%s)' % style, onyx, "Onyx's own hides for it")
        self.assertTrue(onyx.startswith('Player.HasMedia + ![') and onyx.endswith(']'), "unset (or unknown): Onyx's own")

    def test_ids_are_unique_and_every_key_and_focus_leads_to_a_control_that_exists(self):
        root = osd()
        ids = Counter(c.get('id') for c in root.iter('control') if c.get('id'))
        self.assertEqual([i for i, n in ids.items() if n > 1], [], 'a repeated id breaks the remote (FENtastic 1.0.35)')
        text = OSD.read_text(encoding='utf-8')
        targets = set(re.findall(r'<on(?:left|right|up|down|back)[^>]*>(\d+)</', text)) | set(re.findall(r'SetFocus\((\d+)\)', text))
        self.assertEqual(sorted(t for t in targets if t not in ids), [])

    def test_each_style_opens_on_its_main_button(self):
        loads = [(o.get('condition'), o.text) for o in osd().findall('onload')]
        for style in S.STYLES:
            self.assertIn((S.shown(style) + ' + Player.PauseEnabled', 'SetFocus(%d)' % S.MAIN[style]), loads)
            self.assertIn((S.shown(style) + ' + !Player.PauseEnabled', 'SetFocus(%d)' % S.NO_PAUSE[style]), loads)
        onyx = [cond for cond, _action in loads if cond and 'SetFocus(7024)' in _action]
        self.assertTrue(onyx and onyx[0].startswith(S.onyx_shown()), "Onyx's own focus moves only in Onyx's own player")

    def test_every_player_has_the_switch_and_its_own_working_buttons(self):
        found = groups(osd())
        players = ['the Onyx player'] + ['player style: %s' % style for style in S.STYLES]
        for name, group in ((name, found[name]) for name in players):
            clicks = [c.text for c in group.iter('onclick')]
            with self.subTest(name):
                self.assertIn('RunPlugin(plugin://plugin.program.kodipovilwizard/?mode=player_style)', clicks)
                self.assertIn('PlayerControl(Play)', clicks)
                self.assertIn('PlayerControl(Stop)', clicks)
                self.assertIn('RunScript(service.subtitles.kodipovilai,action=choose_subs)', clicks)
                self.assertNotIn('SubtitleDelay', clicks, 'an action sent while the controls close is lost')
                for button in group.iter('control'):
                    sent = [c.text for c in button.findall('onclick')]
                    if 'Action(SubtitleDelay)' in sent:
                        self.assertEqual(sent, ['Dialog.Close(VideoOSD,true)', 'Action(SubtitleDelay)'])

    def test_the_netflix_jumps_go_the_way_and_the_distance_they_say(self):
        root = osd()
        lists = {c.get('id'): c for c in root.iter('control') if c.get('type') == 'list'}
        for lid, sign, wind in ((str(S.REWIND_STEPS), '-', 'Rewind'), (str(S.FORWARD_STEPS), '', 'Forward')):
            items = [(i.findtext('label'), i.findtext('onclick')) for i in lists[lid].find('content').findall('item')]
            self.assertEqual(items[0], ('הרצה', 'PlayerControl(%s)' % wind))
            self.assertEqual(items[1:], [('דקה', 'Seek(%s60)' % sign), ('5 דקות', 'Seek(%s300)' % sign),
                                         ('10 דקות', 'Seek(%s600)' % sign), ('20 דקות', 'Seek(%s1200)' % sign),
                                         ('40 דקות', 'Seek(%s2400)' % sign), ('60 דקות', 'Seek(%s3600)' % sign),
                                         ('80 דקות', 'Seek(%s4800)' % sign)])

    def test_every_icon_a_player_draws_is_in_the_skin(self):
        for icon in set(re.findall(r'povil/osd/([a-z_]+)\.png', OSD.read_text(encoding='utf-8'))):
            self.assertTrue((SKIN / 'media/povil/osd' / (icon + '.png')).is_file(), icon)

    def test_the_variables_the_players_read_are_defined(self):
        includes = (SKIN / 'xml/Includes_POVIL_Home.xml').read_text(encoding='utf-8')
        for name in set(re.findall(r'\$VAR\[([A-Za-z_]+)', OSD.read_text(encoding='utf-8'))):
            self.assertIn('<variable name="%s">' % name, includes)


class ChoiceTests(unittest.TestCase):
    def test_the_wizard_offers_exactly_the_skin_s_styles(self):
        self.assertEqual(sorted(v for v, _name in choice.STYLES if v), sorted(S.STYLES))
        self.assertEqual(choice.STYLES[0][0], '', "Onyx's own first: the default")
        self.assertEqual(choice.SETTING, S.CHOICE)

    def test_what_is_set_and_what_is_read(self):
        self.assertEqual(choice.builtin('netflix'), 'Skin.SetString(POVILPlayer,netflix)')
        self.assertEqual(choice.builtin(''), 'Skin.Reset(POVILPlayer)')
        self.assertEqual(choice.current(lambda label: 'pretty'), 'pretty')
        self.assertEqual(choice.current(lambda label: ''), '')
        self.assertEqual(choice.current(lambda label: 'old'), '', 'an unknown value is Onyx\'s own, as the skin shows it')

    def test_asked_from_the_settings_tile_and_from_every_player(self):
        home = (SKIN / 'xml/Home.xml').read_text(encoding='utf-8')
        self.assertIn('?mode=player_style', home)
        self.assertIn('$VAR[POVIL_PlayerTile]', home)
        router = (ROOT / 'plugin.program.kodipovilwizard/resources/libs/common/router.py').read_text(encoding='utf-8')
        self.assertIn("mode == 'player_style'", router)
        self.assertIn("'player_subs_position', 'player_style'):", router, 'a child profile may switch players too')


if __name__ == '__main__':
    unittest.main()
