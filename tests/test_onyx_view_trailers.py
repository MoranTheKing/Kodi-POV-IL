"""Onyx 1.0.26 / Wizard 0.5.27: a title's trailer in the Videos window's views too.

The owner, Nov 2026: "on the seasons' posters, after pressing a series, there should be the season's trailer as we
agreed -- I see no trailer at all ... and can the trailers work in the search too, not only on the home? In every
screen, the inner menus?" The trailers were asked for on the home only. QA Kodi, on the screen: a series' seasons
(each season its own trailer, a new one within seconds of moving), the season's episodes (the season's trailer goes
on), a search's results (the trailer behind the hero, the plot aside); a menu or a pressed film stops it; back on
the home the home's own trailer plays.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XML = ROOT / 'skin.povil.onyx/xml'
SCREEN = '[Window.IsActive(home) | Window.IsActive(videos)]'


def timer(name):
    text = (XML / 'Timers.xml').read_text(encoding='utf-8')
    block = text.split('<name>%s</name>' % name)[1].split('</timer>')[0]
    return block


def view_include(views, vid):
    """One view's include (it holds includes of its own, so it ends where the next one begins)."""
    rest = views.split('<include name="View_%d_POVIL">' % vid)[1]
    rest = rest.split('<include name="View_')[0] if '<include name="View_' in rest else rest.rsplit('</includes>', 1)[0]
    return rest.rsplit('</include>', 1)[0]


class SkinTests(unittest.TestCase):
    def test_the_trailer_is_asked_for_on_the_home_and_in_the_videos_window(self):
        for name in ('povil_trailer', 'povil_trailer_peek', 'povil_trailer_shown'):
            with self.subTest(name):
                start = re.search(r'<start[^>]*>([^<]*)</start>', timer(name)).group(1)
                self.assertTrue(start.startswith(SCREEN + ' + '), start[:80])
        self.assertIn('<stop>!%s | ' % SCREEN, timer('povil_trailer_shown'))

    def test_it_is_stopped_when_neither_is_on_the_screen(self):
        start = re.search(r'<start[^>]*>([^<]*)</start>', timer('povil_trailer_stop')).group(1)
        self.assertIn('[!%s | ' % SCREEN, start)
        self.assertNotIn('!Window.IsActive(home) |', start)
        self.assertIn('System.HasActiveModalDialog', start, 'a menu over the list stops it, as on the home')

    def test_the_window_has_one_label_naming_the_focused_title_s_trailer(self):
        views = (XML / 'View_POVIL.xml').read_text(encoding='utf-8')
        self.assertEqual(views.count('id="9809"'), 1, 'two controls of one id, one in a hidden group, are not read reliably')
        self.assertIn('<label>$VAR[POVIL_V_Trailer]</label>', views)
        block = views.split('<variable name="POVIL_V_Trailer">')[1].split('</variable>')[0]
        values = re.findall(r'<value condition="([^"]*)">([^<]*)</value>', block)
        self.assertEqual(len(values), 1, 'no trailer named: no value, nothing asked')
        cond, value = values[0]
        self.assertEqual(value, '$INFO[ListItem.Trailer]')
        self.assertIn('String.StartsWith(ListItem.Trailer,plugin://plugin.video.youtube/)', cond)
        self.assertIn('[Control.IsVisible(51) | Control.IsVisible(55)]', cond, 'only the views that have the picture')
        self.assertIn('!Container.IsUpdating', cond)
        # the label is outside the views' own groups (each shows with its view only)
        include = view_include(views, 51)
        self.assertTrue(include.rstrip().endswith('<label>$VAR[POVIL_V_Trailer]</label></control>'), include[-200:])
        group = include.split('<control type="group" description=')[1]
        self.assertNotIn('id="9809"', group.split('<control type="videowindow">')[0])

    def test_each_view_shows_the_trailer_under_its_hero_and_gives_it_the_screen(self):
        views = (XML / 'View_POVIL.xml').read_text(encoding='utf-8')
        home = (XML / 'Home.xml').read_text(encoding='utf-8')
        shown = re.search(r'<control type="videowindow"[^>]*>.*?<visible>([^<]*)</visible>', home, re.S).group(1)
        for vid in (51, 55):
            with self.subTest(vid):
                include = view_include(views, vid)
                self.assertEqual(include.count('<control type="videowindow">'), 1)
                window = include.split('<control type="videowindow">')[1].split('</control>')[0]
                self.assertIn('<visible>%s</visible>' % shown, window, 'only while the trailer playing is the focused title\'s')
                self.assertIn('<hitrect x="-10" y="-10" w="1" h="1"/>', window, 'a tap is not Kodi\'s "to full screen"')
                # the list and the hero come after the picture, in the group that fades when the trailer has the screen
                after = include.split('<control type="videowindow">')[1]
                self.assertIn('description="over the picture"', after)
                self.assertIn('<control type="list" id="%d">' % vid, after.split('description="over the picture"')[1])
                self.assertIn('Skin.TimerElapsedSecs(povil_trailer_shown)', after)

    def test_the_plot_steps_aside_while_the_trailer_plays(self):
        views = (XML / 'View_POVIL.xml').read_text(encoding='utf-8')
        for box in re.findall(r'<control type="textbox">.*?</control>', views, re.S):
            if 'POVIL_V_Plot' in box:
                self.assertIn('effect="fade" start="100" end="0"', box)
                self.assertIn('povil.tr.on', box)
                break
        else:
            self.fail('no plot box')


class WizardTests(unittest.TestCase):
    def test_the_trailer_desk_takes_the_videos_window_for_a_screen_of_its_own(self):
        text = (ROOT / 'plugin.program.kodipovilwizard/resources/libs/trailers.py').read_text(encoding='utf-8')
        self.assertIn("SCREEN = 'Window.IsActive(home) | Window.IsActive(videos)'", text)
        wanted = text.split('def wanted_now(key):')[1].split('def look(key):')[0]
        self.assertIn('xbmc.getCondVisibility(SCREEN)', wanted)
        self.assertNotIn("getCondVisibility('Window.IsActive(home)')", text)


if __name__ == '__main__':
    unittest.main()
