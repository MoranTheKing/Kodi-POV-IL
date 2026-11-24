"""Onyx 1.0.39: an empty row of the continue-watching screen takes no room.

A viewer, Nov 2026: "even after 12 minutes it does not show". He has no Trakt account, so POV keeps its own
places and its "next episode" row stays empty until an episode is finished. The screen's three rows were all
optional and sat at fixed places: with "הפרק הבא" and "סרטים שהתחלתם" empty, "פרקים שהתחלתם" stood a row under
the bottom of the screen, and its rows loaded only after a step down from the top bar -- the screen looked empty
with four episodes in it (QA Kodi, POV without Trakt, on the screen). Now an empty optional row gives its room to
the rows under it, the focus slide counts only the rows above with something in them, and the rows under an
empty first row load without the step down. Slot screens (films, series, kids, favourites) are not touched.

The same screen showed the next episode's season, episode and name above a film from "סרטים שהתחלתם": the gold
line went on to the screen's first row whenever the focused item was no episode.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'skin.povil.onyx'
TOOLS = ROOT / 'tools/skin_onyx'


def tools(name):
    sys.path.insert(0, str(TOOLS))
    try:
        return __import__(name)
    finally:
        sys.path.remove(str(TOOLS))


def xml(name):
    return (SKIN / 'xml' / name).read_text(encoding='utf-8')


def group(text, description):
    start = text.index('<control type="group" description="%s">' % description)
    return text[start:text.index('<control type="list"', start)]


KEPT = '[Integer.IsGreater(Container(%d).NumItems,0) | Container(%d).IsUpdating]'


class ContinueRows(unittest.TestCase):
    def setUp(self):
        self.home = xml('Home.xml')
        self.rows = group(self.home, 'rows continue')

    def test_an_empty_row_gives_its_room_to_the_rows_under_it(self):
        films = group(self.home, 'סרטים שהתחלתם')
        episodes = group(self.home, 'פרקים שהתחלתם')
        slide = '<animation effect="slide" end="0,-362" time="0" condition="!%s">Conditional</animation>'
        self.assertIn(slide % (KEPT % (5101, 5101)), films)
        self.assertNotIn(KEPT % (5102, 5102), films)
        self.assertIn(slide % (KEPT % (5101, 5101)), episodes)
        self.assertIn(slide % (KEPT % (5102, 5102)), episodes)

    def test_the_focus_slide_counts_only_the_rows_above_with_something_in_them(self):
        outer = self.rows.split('<control type="group" description="הפרק הבא">')[0]
        slides = re.findall(r'<animation effect="slide" end="0,-(\d+)"[^>]*condition="([^"]*)"', outer)
        focus = {5102: [], 5103: []}
        for amount, cond in slides:
            rid = int(re.search(r'Control\.HasFocus\((\d+)\)', cond).group(1))
            focus[rid].append((int(amount), cond))
        self.assertEqual([a for a, _c in focus[5102]], [362])
        self.assertIn(KEPT % (5101, 5101), focus[5102][0][1])
        # two rows above: one row's height for each that keeps its room (Kodi adds the two slides up)
        self.assertEqual(sorted(a for a, _c in focus[5103]), [362, 362])
        self.assertEqual(sorted(KEPT % (r, r) in c for _a, c in focus[5103] for r in (5101, 5102)).count(True), 2)

    def test_the_rows_under_an_empty_first_row_load_without_a_step_down(self):
        timers = xml('Timers.xml')
        start = timers.split('<name>povil_deep_continue</name>')[1].split('</start>')[0]
        self.assertIn('[!ControlGroup(9000).HasFocus() | [!String.IsEmpty(Window(home).Property(povil.tab.continue)) + '
                      '!Container(5101).IsUpdating + !Integer.IsGreater(Container(5101).NumItems,0)]]', start)
        self.assertIn('!Skin.HasSetting(POVILChild)', start)

    def test_slot_screens_and_screens_of_fixed_rows_are_not_touched(self):
        # only the plain screens with optional rows above others: continue watching (3) and search (1)
        self.assertEqual(len(re.findall(r'time="0" condition="!\[Integer\.IsGreater\(Container\(\d+\)', self.home)), 4)
        self.assertEqual(len(re.findall(r'\]\] \+ \[Integer\.IsGreater\(Container\(\d+\)\.NumItems,0\) \| '
                                        r'Container\(\d+\)\.IsUpdating\]">Conditional', self.home)), 4)
        timers = xml('Timers.xml')
        movies = timers.split('<name>povil_deep_movies</name>')[1].split('</start>')[0]
        self.assertIn('String.IsEqual(Window(home).Property(povil.tab),movies) + !ControlGroup(9000).HasFocus() + ', movies)

    def test_a_film_in_focus_shows_no_episode_line_from_another_row(self):
        incl = xml('Includes_POVIL_Home.xml')
        var = incl.split('<variable name="POVIL_HeroEpisode">')[1].split('</variable>')[0]
        focus = ('[Control.HasFocus(5102) | [String.IsEmpty(System.CurrentControlId) + '
                 'String.IsEqual(Window(home).Property(povil.focus),5102)]]')
        episode = var.index('<value condition="%s + String.IsEqual(Container(5102).ListItem.DBType,episode)">' % focus)
        empty = var.index('<value condition="%s"></value>' % focus)
        fallback = var.index('String.IsEqual(Window(home).Property(povil.tab),continue)')
        self.assertLess(episode, empty)
        self.assertLess(empty, fallback)

    def test_a_row_keeps_its_room_while_it_loads_or_has_items(self):
        H = tools('gen_home')
        self.assertTrue(hasattr(H, 'row_kept'))
        self.assertEqual(H.row_kept(5101), KEPT % (5101, 5101))


if __name__ == '__main__':
    unittest.main()
