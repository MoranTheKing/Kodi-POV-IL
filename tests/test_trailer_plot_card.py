"""Onyx 1.0.34 / Wizard 0.5.39: the plot goes with the trailer.

A viewer, Nov 2026: "can the series' text stay longer on the screen before the trailer starts? It feels like a race to
read it before the trailer plays". The owner: "a film's too ... that it shows but does not get in the trailer's way",
and not a second later to the full screen ("a few more seconds without the trailer full screen -- that's a pity"); then
"a line every 4 seconds feels a bit slow ... normal speed, not too slow", and "once the last line is done, make it go, so
the trailer is cleaner". The plot stays in the hero while the trailer plays behind it; when the trailer has the screen
to itself (as soon as it always did) the plot rises to a card at the top, scrolls on through the rest of it at a
reading pace, and goes once its last line has been read. QA Kodi 21: a six-line plot -- the card's first lines from the
trailer's 5th second, the scroll from its 9th, a line every 3 s, the last at the 17th, gone by the 21st.
"""
import importlib.util
import sys
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIZARD = ROOT / 'plugin.program.kodipovilwizard'
SKIN = ROOT / 'skin.povil.onyx'
XML = SKIN / 'xml'
TOOLS = ROOT / 'tools/skin_onyx'
spec = importlib.util.spec_from_file_location('trailers_plot_card', WIZARD / 'resources/libs/trailers.py')
trailers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trailers)


def gen_home():
    sys.path.insert(0, str(TOOLS))
    try:
        import gen_home as H
    finally:
        sys.path.remove(str(TOOLS))
    return H


class Home(object):
    def __init__(self):
        self.values = {}

    def getProperty(self, key):
        return self.values.get(key, '')

    def setProperty(self, key, value):
        self.values[key] = value

    def clearProperty(self, key):
        self.values.pop(key, None)


class ReadingTime(unittest.TestCase):
    def test_a_plot_read_before_the_trailer_has_the_screen_brings_no_card(self):
        for plot in ('', 'א' * 60, 'א' * 100):
            self.assertEqual(trailers.reading_seconds(plot), 4, len(plot))
        self.assertNotIn(4, gen_home().TRAILER_READ_STEPS, 'the skin shows no card for 4')

    def test_three_lines_at_a_reading_pace_from_the_moment_the_title_is_on_the_screen(self):
        # ~174 letters: 9.7 s from the title, the trailer's first picture ~2 s after it
        self.assertEqual(trailers.reading_seconds('א' * 174), 8)
        # just past the full screen: the card stays a few seconds, not a flash
        self.assertEqual(trailers.reading_seconds('א' * 115), 4 + trailers.CARD_MIN_S)

    def test_a_longer_plot_scrolls_on_and_the_card_goes_a_line_s_time_after_its_last_line(self):
        # six lines: the card at 4, its first lines for 4 s, three lines more at 3 s each, the last read for 3 s
        self.assertEqual(trailers.reading_seconds('א' * 348), 4 + 4 + 3 * 3 + 3)
        # the viewer's own "full screen after" moves the card with it
        self.assertEqual(trailers.reading_seconds('א' * 348, 6), 6 + 4 + 3 * 3 + 3)
        self.assertEqual(trailers.reading_seconds('א' * 5000), trailers.READ_STEPS[-1], 'the longest step at the most')

    def test_each_paragraph_starts_a_line_of_its_own(self):
        # two short paragraphs are two lines, not one; four of them scroll on in the card
        self.assertEqual(trailers.reading_seconds('א' * 100), trailers.reading_seconds('א' * 50 + '\n\n' + 'א' * 50))
        four = '\n\n'.join(['א' * 40] * 4)
        self.assertEqual(trailers.reading_seconds(four), 4 + 4 + 1 * 3 + 3)
        self.assertEqual(trailers.reading_seconds('[CR]'.join(['א' * 40] * 4)), trailers.reading_seconds(four))

    def test_kodi_s_tags_are_not_read(self):
        self.assertEqual(trailers.reading_seconds('[B]%s[/B][COLOR gold] [/COLOR]' % ('א' * 100)),
                         trailers.reading_seconds('א' * 100))

    def test_the_desk_measures_the_plot_when_the_title_asks_for_its_trailer(self):
        home = Home()
        home.setProperty(trailers.ASK, 'plugin://plugin.video.youtube/play/?video_id=abcdefghijk')
        player = types.SimpleNamespace(stop=lambda: None, isPlaying=lambda: False)
        desk = trailers.Desk(home, player, lambda video: [], lambda url, stream: None, lambda: False,
                             plot=lambda: 'א' * 348, alone_after=lambda: 4)
        desk.asked()
        self.assertEqual(home.getProperty(trailers.READ), '20', 'even when no trailer plays: it is read first')

        def broken():
            raise RuntimeError('no skin')
        trailers.Desk(home, player, lambda video: [], lambda url, stream: None, lambda: False, plot=broken).asked()
        self.assertEqual(home.getProperty(trailers.READ), '4')
        source = (WIZARD / 'resources/libs/trailers.py').read_text(encoding='utf-8')
        self.assertIn("plot=lambda: xbmc.getInfoLabel('Control.GetLabel(%d)' % PLOT_LABEL)", source)
        self.assertIn('trailer_timing.current(xbmc.getInfoLabel, trailer_timing.FULL, trailer_timing.FULLS)', source)


class TheSkin(unittest.TestCase):
    def test_the_skin_and_the_desk_count_alike(self):
        H = gen_home()
        self.assertEqual(H.PLOT_LABEL, trailers.PLOT_LABEL)
        self.assertEqual(H.TRAILER_READ, 'Window(home).Property(%s)' % trailers.READ)
        self.assertEqual(tuple(H.TRAILER_READ_STEPS), tuple(trailers.READ_STEPS[1:]), 'every step the desk writes')
        self.assertEqual((H.PLOT_CARD_LINES, H.PLOT_CARD_HOLD_S, H.PLOT_CARD_LINE_S),
                         (trailers.CARD_LINES, trailers.CARD_HOLD_S, trailers.CARD_LINE_S))
        # Kodi scrolls by the lines that fit whole: povil_plot's line is ~41.3 px
        self.assertGreater(H.PLOT_CARD_HEIGHT, 41.3 * H.PLOT_CARD_LINES)
        self.assertLess(H.PLOT_CARD_HEIGHT, 41.3 * (H.PLOT_CARD_LINES + 1))

    def test_the_trailer_has_the_screen_as_soon_as_it_always_did(self):
        alone = gen_home().TRAILER_ALONE
        self.assertIn('[[String.IsEqual(Skin.String(POVILTrailerFull),4) | String.IsEmpty(Skin.String(POVILTrailerFull))] + '
                      'Integer.IsGreaterOrEqual(Skin.TimerElapsedSecs(povil_trailer_shown),4) + System.IdleTime(3)]', alone)
        self.assertNotIn('povil.tr.read', alone)

    def test_the_plot_stays_in_the_hero_while_the_trailer_plays(self):
        H = gen_home()
        home = ET.parse(XML / 'Home.xml').getroot()
        plot = next(c for c in home.iter('control') if c.get('description') == 'plot')
        self.assertFalse([a for a in plot.findall('animation') if a.get('condition') == H.TRAILER_SHOWN])
        views = ET.parse(XML / 'View_POVIL.xml').getroot()
        boxes = [c for c in views.iter('control') if c.get('type') == 'textbox' and c.findtext('label') == '$VAR[POVIL_V_Plot]']
        self.assertTrue(boxes)
        for box in boxes:
            self.assertFalse([a for a in box.findall('animation') if 'povil.tr.on' in (a.get('condition') or '')])

    def test_the_plot_shown_is_there_for_the_desk_to_measure(self):
        for name, plot in (('Home.xml', '$VAR[POVIL_HeroPlot]'), ('View_POVIL.xml', '$VAR[POVIL_V_Plot]')):
            labels = [c for c in ET.parse(XML / name).getroot().iter('control') if c.get('id') == str(trailers.PLOT_LABEL)]
            self.assertEqual(len(labels), 1, '%s: one for the window' % name)
            self.assertEqual(labels[0].findtext('label'), plot)

    def test_the_card_rises_to_the_top_scrolls_at_a_reading_pace_and_goes(self):
        H = gen_home()
        self.assertTrue(H.PLOT_CARD.startswith(H.TRAILER_ALONE + ' + '), 'only while the trailer has the screen to itself')
        for s in H.TRAILER_READ_STEPS:
            self.assertIn('[String.IsEqual(Window(home).Property(povil.tr.read),%d) + '
                          '!Integer.IsGreaterOrEqual(Skin.TimerElapsedSecs(povil_trailer_shown),%d)]' % (s, s), H.PLOT_CARD)
        for name, title, plot in (('Home.xml', '$VAR[POVIL_HeroTitle]', '$VAR[POVIL_HeroPlot]'),
                                  ('View_POVIL.xml', '$VAR[POVIL_V_Title]', '$VAR[POVIL_V_Plot]')):
            root = ET.parse(XML / name).getroot()
            cards = [c for c in root.iter('control') if c.get('description') == 'plot card']
            self.assertTrue(cards, name)
            for card in cards:
                self.assertIsNone(card.find('visible'), 'the group is always there (see below)')
                parts = {c.get('description'): c for c in card.findall('control')}
                self.assertEqual(set(parts), {'plot card corner', 'plot card title', 'plot card text'})
                for part in parts.values():
                    # each shows by itself: Kodi puts a textbox's scroll back to its start only while the box itself
                    # is hidden (in a hidden group the card came up already scrolling, QA)
                    self.assertEqual(part.findtext('visible'), H.PLOT_CARD)
                    self.assertIn('Hidden', [a.text for a in part.findall('animation')])
                self.assertEqual(parts['plot card title'].findtext('label'), title)
                text = parts['plot card text']
                self.assertEqual(text.findtext('label'), plot)
                self.assertEqual(text.findtext('height'), str(H.PLOT_CARD_HEIGHT))
                scroll = text.find('autoscroll')
                self.assertEqual((scroll.get('delay'), scroll.get('time')), ('4000', '3000'), 'not slow, not too fast')
                self.assertEqual(scroll.text, H.PLOT_CARD)
                rise = [a for a in text.findall('animation') if a.get('type') == 'Visible']
                self.assertTrue(rise and rise[0].find("effect[@type='slide']") is not None, 'it rises from the hero')
                self.assertEqual(parts['plot card corner'].findtext('texture'), 'povil/grad_corner.png')
        self.assertTrue((SKIN / 'media/povil/grad_corner.png').is_file())
        # on the home, not in the group that fades: it shows when everything else has gone
        home = ET.parse(XML / 'Home.xml').getroot()
        over = next(c for c in home.iter('control') if c.get('description') == 'over the picture')
        self.assertFalse([c for c in over.iter('control') if c.get('description') == 'plot card'])


if __name__ == '__main__':
    unittest.main()
