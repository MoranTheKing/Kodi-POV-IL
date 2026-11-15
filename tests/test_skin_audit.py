"""Defects found by the November 2026 audit of the build's skins, kept fixed."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / 'skin.povil.old'
FEN = ROOT / 'skin.fentastic'
ESTUARY = ROOT / 'skin.estuary'
# names that stay as they are inside a Hebrew label
NAMES = (r'\$[A-Z]+\[[^\]]*\]|\[/?B\]|MDbList|IMDb|TMDb|Trakt|API|Metacritic|Rotten Tomatoes|'
         r'\(Critic\)|\(Audience\)|\(Main\)|\(Popular\)')


def read(path):
    return path.read_text(encoding='utf-8')


def hebrew_strings(skin):
    text = read(skin / 'language' / 'resource.language.he_il' / 'strings.po').replace('\r\n', '\n')
    return dict(re.findall(r'msgctxt "#(\d+)"\nmsgid "[^"\n]*"\n(?:"[^\n]*"\n)*msgstr "([^"\n]*)"', text))


class SkinAudit(unittest.TestCase):
    def test_square_brackets_balance_in_fentastic_conditions(self):
        # a stray "]" makes Kodi read the whole condition as false: the Netflix-style
        # player's next / previous pictures never used the fanart
        text = read(FEN / 'xml' / 'Variables.xml')
        bad = [c for c in re.findall(r'condition="([^"]*)"', text) if c.count('[') != c.count(']')]
        self.assertEqual(bad, [])

    def test_the_old_search_dialog_names_every_row(self):
        text = read(OLD / 'xml' / 'Custom_1107_SearchDialog.xml')
        defined = set()
        for path in (OLD / 'xml').glob('*.xml'):
            defined.update(re.findall(r'<variable\s+name="([^"]+)"', read(path)))
        self.assertEqual(sorted(set(re.findall(r'\$VAR\[([^\],]+)', text)) - defined), [])
        self.assertNotIn('<label>Addons</label>', text)

    def test_a_tap_on_the_picture_closes_the_player_controls_in_every_style(self):
        # 15 Nov 2026, the owner on a phone: "if I press the middle while the player is open, it should
        # close". Estuary, Old's native and simple players had the area; the rest did not.
        def area_first(body, where):
            first = re.search(r'<control type="(\w+)"[^>]*>(.*?)</control>', body, re.S)
            self.assertIsNotNone(first, where)
            self.assertEqual(first.group(1), 'button', where)
            self.assertIn('<onclick>Action(close)</onclick>', first.group(2), where)
            self.assertIn('<texturefocus />', first.group(2), where)
            return first.group(2)

        players = read(OLD / 'xml' / 'Includes_POVIL_Players.xml')
        for n in '1234':
            body = re.search(r'<include name="POVIL_Player_videosd%s">(.*?)\n\t</include>' % n, players, re.S).group(1)
            area = area_first(body, 'Old videosd' + n)
            if n != '3':
                for tag in ('onup', 'ondown', 'onleft', 'onright'):
                    self.assertIn('<%s>201</%s>' % (tag, tag), area, n)
        area_first(read(OLD / 'xml' / 'Includes_POVIL_NativePlayer.xml'), 'Old native player')
        osd = read(FEN / 'xml' / 'VideoOSD.xml')
        area = area_first(osd[osd.index('<controls>'):], 'FENtastic')
        for tag in ('onup', 'ondown', 'onleft', 'onright'):
            self.assertIn('<%s>201</%s>' % (tag, tag), area)
        self.assertIn('<defaultcontrol always="true">201</defaultcontrol>', osd)
        area_first(read(ESTUARY / 'xml' / 'VideoOSD.xml').split('<controls>', 1)[1], 'Estuary')

    def test_skin_settings_are_in_hebrew(self):
        for skin in (OLD, FEN):
            with self.subTest(skin.name):
                labels = re.findall(r'<label>([^<]*)</label>', read(skin / 'xml' / 'SkinSettings.xml'))
                self.assertGreater(len(labels), 40)
                latin = [t for t in labels if re.search(r'[A-Za-z]{3,}', re.sub(NAMES, '', t))]
                self.assertEqual(latin, [])
        self.assertNotIn('<label>Skin settings</label>', read(OLD / 'xml' / 'Settings.xml'))

    def test_player_buttons_use_strings_their_skin_has(self):
        old = read(OLD / 'xml' / 'Includes_POVIL_Players.xml')
        for sid in ('700035', '700016', '700017', '700041'):
            self.assertNotIn('$LOCALIZE[%s]' % sid, old, 'Old has no string %s' % sid)
        fen = hebrew_strings(FEN)
        simple = read(FEN / 'xml' / 'Includes_VideoOsd3.xml')
        for sid in set(re.findall(r'\$LOCALIZE\[(7\d{4,6})\]', simple)):
            self.assertTrue(fen.get(sid), 'FENtastic has no Hebrew string %s' % sid)
        self.assertNotIn('PPlayer.', read(FEN / 'xml' / 'Includes_VideoOsd1.xml'))

    def test_textures_named_by_the_skins_exist(self):
        self.assertTrue((FEN / 'media' / 'masks' / 'menu.png').is_file(),
                        'the focused button of the extended info, trailer and season windows had dark text on no plate')
        for name in ('landscape-502.png', 'landscape1.png', 'poster-50.png'):
            self.assertTrue((ESTUARY / 'media' / 'masks' / name).is_file(), name)

    def test_fonts_named_by_the_estuary_pause_window_exist(self):
        fonts = set(re.findall(r'<name>([^<]+)</name>', read(ESTUARY / 'xml' / 'Font.xml')))
        used = set(re.findall(r'<font>([^<$]+)</font>', read(ESTUARY / 'xml' / 'Custom_1122_PlayerPauseWindow.xml')))
        self.assertEqual(sorted(used - fonts), [])

    def test_skin_strings_shown_on_screen_are_translated(self):
        common = ('31037 31054 31055 31073 31115 31135 31150 31168 31169 31170 31171 31172 31173 31603 31606 31608').split()
        for skin, ids in ((OLD, common), (FEN, common), (ESTUARY, common + ['31147', '31174', '31175', '31176'])):
            with self.subTest(skin.name):
                strings = hebrew_strings(skin)
                self.assertEqual([sid for sid in ids if sid in strings and not strings[sid]], [])

    def test_season_and_episode_are_named_in_the_interface_language(self):
        for path in (OLD / 'xml').glob('*.xml'):
            self.assertNotIn('<label>Season $INFO[ListItem.Season], Episode $INFO[ListItem.Episode]</label>', read(path), path.name)


if __name__ == '__main__':
    unittest.main()
