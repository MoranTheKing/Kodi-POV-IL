"""Defects found by the November 2026 audit of the build's skins, kept fixed."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOX = ROOT / 'skin.povil.nox'
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

    def test_the_nox_search_dialog_names_every_row(self):
        text = read(NOX / 'xml' / 'Custom_1107_SearchDialog.xml')
        defined = set()
        for path in (NOX / 'xml').glob('*.xml'):
            defined.update(re.findall(r'<variable\s+name="([^"]+)"', read(path)))
        self.assertEqual(sorted(set(re.findall(r'\$VAR\[([^\],]+)', text)) - defined), [])
        self.assertNotIn('<label>Addons</label>', text)

    def test_skin_settings_are_in_hebrew(self):
        for skin in (NOX, FEN):
            with self.subTest(skin.name):
                labels = re.findall(r'<label>([^<]*)</label>', read(skin / 'xml' / 'SkinSettings.xml'))
                self.assertGreater(len(labels), 40)
                latin = [t for t in labels if re.search(r'[A-Za-z]{3,}', re.sub(NAMES, '', t))]
                self.assertEqual(latin, [])
        self.assertNotIn('<label>Skin settings</label>', read(NOX / 'xml' / 'Settings.xml'))

    def test_player_buttons_use_strings_their_skin_has(self):
        nox = read(NOX / 'xml' / 'Includes_POVIL_Players.xml')
        for sid in ('700035', '700016', '700017', '700041'):
            self.assertNotIn('$LOCALIZE[%s]' % sid, nox, 'Nox has no string %s' % sid)
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
        for skin, ids in ((NOX, common), (FEN, common), (ESTUARY, common + ['31147', '31174', '31175', '31176'])):
            with self.subTest(skin.name):
                strings = hebrew_strings(skin)
                self.assertEqual([sid for sid in ids if sid in strings and not strings[sid]], [])

    def test_season_and_episode_are_named_in_the_interface_language(self):
        for path in (NOX / 'xml').glob('*.xml'):
            self.assertNotIn('<label>Season $INFO[ListItem.Season], Episode $INFO[ListItem.Episode]</label>', read(path), path.name)


if __name__ == '__main__':
    unittest.main()
