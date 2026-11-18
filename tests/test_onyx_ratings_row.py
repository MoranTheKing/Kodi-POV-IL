"""Onyx 1.0.15: the ratings row -- several sites' ratings for the title on screen, in the home's hero, the list
views, the info screen and the player (tools/skin_onyx/ratings_row.py; the Wizard's ratings.py answers)."""
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'skin.povil.onyx'
XML = SKIN / 'xml'
SITES = ['tmdb', 'imdb', 'tomato', 'popcorn', 'meta', 'trakt', 'letterboxd']
# window file -> (key label id, property prefix)
WINDOWS = {'Home.xml': (9807, 'povil.rt.'), 'View_POVIL.xml': (9807, 'povil.rt.'), 'DialogVideoInfo.xml': (9807, 'povil.rt.'),
           'VideoOSD.xml': (7920, 'povil.rtp.'), 'VideoFullScreen.xml': (7920, 'povil.rtp.')}


def rows(name):
    root = ET.parse(XML / name).getroot()
    return [c for c in root.iter('control') if c.get('type') == 'grouplist' and c.get('description') == 'ratings']


class RowTests(unittest.TestCase):
    def test_every_place_that_shows_a_title_has_the_row(self):
        for name, (key, prefix) in WINDOWS.items():
            found = rows(name)
            self.assertTrue(found, name)
            for row in found:
                units = [g.get('description') for g in row.findall('control')]
                # written last to first: the row is laid out from the right, where reading starts
                self.assertEqual(units, SITES[::-1], name)
                self.assertEqual(row.findtext('visible'), '!String.IsEmpty(Control.GetLabel(%d))' % key)
                self.assertEqual(row.findtext('align'), 'right')

    def test_a_site_shows_only_beside_the_title_it_was_answered_for(self):
        for name, (key, prefix) in WINDOWS.items():
            for row in rows(name):
                for unit in row.findall('control'):
                    site, shown = unit.get('description'), unit.findtext('visible')
                    if site == 'tmdb':
                        # there from the start, from the list's own rating
                        self.assertEqual(shown, '!String.IsEmpty(Control.GetLabel(%d))' % (key + 1), name)
                        continue
                    self.assertEqual(shown, 'String.IsEqual(Control.GetLabel(%d),Window(home).Property(%sfor)) + '
                                            '!String.IsEmpty(Window(home).Property(%s%s))' % (key, prefix, prefix, site), name)

    def test_the_key_names_the_title_by_imdb_id_kind_season_and_episode(self):
        text = ''.join(path.read_text('utf-8') for path in sorted(XML.glob('*.xml')) if '<variable name="POVIL_' in path.read_text('utf-8'))
        for name in ('POVIL_RatingsKey', 'POVIL_V_RatingsKey', 'POVIL_I_RatingsKey', 'POVIL_OSD_RatingsKey'):
            self.assertIn('<variable name="%s">' % name, text)
        view = text[text.index('<variable name="POVIL_V_RatingsKey">'):]
        view = view[:view.index('</variable>')]
        self.assertIn('String.StartsWith(ListItem.UniqueID(imdb),tt)', view, 'only a title POV named')
        self.assertIn('$INFO[ListItem.UniqueID(imdb)]|$INFO[ListItem.DBType]|$INFO[ListItem.Season]|$INFO[ListItem.Episode]', view)
        player = text[text.index('<variable name="POVIL_OSD_RatingsKey">'):]
        player = player[:player.index('</variable>')]
        self.assertIn('|episode|$INFO[VideoPlayer.Season]|$INFO[VideoPlayer.Episode]', player)
        self.assertIn('|movie||', player)
        self.assertEqual(player.count('!VideoPlayer.Content(LiveTV)'), 4, 'never over live TV')

    def test_each_window_carries_its_key_label_and_the_label_tmdb_is_tested_by(self):
        for name, (key, _prefix) in WINDOWS.items():
            text = (XML / name).read_text('utf-8')
            self.assertIn('id="%d" description="ratings key"' % key, text, name)
            self.assertIn('<control type="label" id="%d">' % (key + 1), text, name)

    def test_the_star_gives_way_to_tmdbs_mark(self):
        for name in ('Home.xml', 'View_POVIL.xml', 'DialogVideoInfo.xml'):
            text = (XML / name).read_text('utf-8')
            stars = re.findall(r'povil/star\.png</texture>\s*<visible>([^<]*)</visible>', text)
            self.assertTrue(stars, name)
            for shown in stars:
                self.assertIn('String.IsEmpty(Control.GetLabel(9807))', shown, name)

    def test_the_marks_exist(self):
        for mark in ('tmdb', 'imdb', 'trakt', 'letterboxd', 'square', 'tomato_fresh', 'tomato_certified', 'tomato_rotten',
                     'popcorn_upright', 'popcorn_spilled'):
            self.assertTrue((SKIN / 'media/povil/ratings' / (mark + '.png')).is_file(), mark)
        text = (XML / 'Home.xml').read_text('utf-8')
        self.assertIn('povil/ratings/tomato_$INFO[Window(home).Property(povil.rt.tomato_state)].png', text)
        self.assertIn('povil/ratings/popcorn_$INFO[Window(home).Property(povil.rt.popcorn_state)].png', text)
        for tone in ('good', 'mixed', 'bad'):
            self.assertIn('String.IsEqual(Window(home).Property(povil.rt.meta_tone),%s)' % tone, text)


class AskingTests(unittest.TestCase):
    def timers(self):
        root = ET.parse(XML / 'Timers.xml').getroot()
        return {t.findtext('name'): t for t in root.iter('timer')}

    def test_a_title_is_asked_once_the_moment_it_is_shown_and_the_timer_is_ready_for_the_next(self):
        timers = self.timers()
        for name, key, prefix, slot in (('povil_ratings', 9807, 'povil.rt.', 'home'),
                                        ('povil_ratings_player', 7920, 'povil.rtp.', 'player')):
            timer = timers[name]
            start = timer.findtext('start')
            # the owner, Nov 2026: "all of them at once, instantly" -- no rest before the question
            self.assertNotIn('IdleTime', start)
            self.assertIn('!String.IsEmpty(Control.GetLabel(%d))' % key, start)
            self.assertIn('!String.IsEqual(Control.GetLabel(%d),Window(home).Property(%sask))' % (key, prefix), start)
            self.assertEqual([a.text for a in timer.findall('onstart')],
                             ['SetProperty(%sask,$ESCINFO[Control.GetLabel(%d)],home)' % (prefix, key),
                              'NotifyAll(povil.ratings,%s)' % slot])
            # a skin timer that is running never starts again (QA: only the first title was ever asked)
            self.assertEqual(timer.findtext('stop'), 'true')
        self.assertIn('Window.IsActive(videos)', timers['povil_ratings'].findtext('start'))
        self.assertIn('Window.IsActive(movieinformation)', timers['povil_ratings'].findtext('start'))
        self.assertIn('Player.HasVideo', timers['povil_ratings_player'].findtext('start'))


class LayoutTests(unittest.TestCase):
    def top(self, control):
        return int(control.findtext('top'))

    def test_the_row_sits_between_the_details_and_the_plot(self):
        for name, plot_label in (('Home.xml', '$VAR[POVIL_HeroPlot]'), ('View_POVIL.xml', '$VAR[POVIL_V_Plot]'),
                                 ('DialogVideoInfo.xml', '$INFO[ListItem.Plot]'), ('VideoFullScreen.xml', '$INFO[VideoPlayer.Plot]')):
            root = ET.parse(XML / name).getroot()
            row = rows(name)[0]
            plots = [c for c in root.iter('control') if c.get('type') == 'textbox' and c.findtext('label') == plot_label]
            self.assertTrue(plots, name)
            for plot in plots:
                self.assertGreaterEqual(self.top(plot), self.top(row) + int(row.findtext('height')), name)

    def test_a_title_with_no_row_keeps_the_layout_it_always_had(self):
        home = (XML / 'Home.xml').read_text('utf-8')
        # the hero starts 34 higher for the row, and slides back down by the same when there is none
        self.assertIn('<animation effect="slide" end="0,34" time="140" tween="cubic" easing="out" '
                      'condition="String.IsEmpty(Control.GetLabel(9807))">Conditional</animation>', home)
        self.assertIn('<animation effect="slide" end="0,-40" time="140" tween="cubic" easing="out" '
                      'condition="String.IsEmpty(Control.GetLabel(9807))">Conditional</animation>', home)

    def test_every_control_of_the_full_screen_window_has_an_id(self):
        """Kodi hides "control 0" of this window with its view mode line; the row's groups carry a description."""
        text = (XML / 'VideoFullScreen.xml').read_text('utf-8')
        self.assertEqual(re.findall(r'<control type="[a-z]+"(?![^>]*\bid=)[^>]*>', text), [])

    def test_a_tap_on_the_picture_does_not_land_on_the_row(self):
        osd = ET.parse(XML / 'VideoOSD.xml').getroot()
        tap = next(c for c in osd.iter('control') if c.get('id') == '7005')
        row = rows('VideoOSD.xml')[0]
        self.assertGreaterEqual(self.top(tap), self.top(row) + int(row.findtext('height')))


class WhoseNumberTests(unittest.TestCase):
    """The owner, Nov 2026: "the one in a plain square is not clear -- nor that the one that reaches 5 is out of 5"."""

    def test_metacritic_stands_beside_its_mark_and_letterboxd_says_out_of_five(self):
        for name in WINDOWS:
            for row in rows(name):
                meta = next(c for c in row if c.get('description') == 'meta')
                images = [c.findtext('texture') for c in meta if c.get('type') == 'image']
                self.assertEqual(images[0], 'povil/ratings/meta.png', name)
                self.assertEqual(images.count('povil/ratings/square.png'), 3, 'the plate, once per verdict')
                mark, plate = [c for c in meta if c.get('type') == 'image'][:2]
                self.assertGreaterEqual(int(plate.findtext('left')), int(mark.findtext('left')) + int(mark.findtext('width')),
                                        'beside the mark, not over it')
                letterboxd = next(c for c in row if c.get('description') == 'letterboxd')
                label = next(c for c in letterboxd if c.get('type') == 'label').findtext('label')
                self.assertTrue(label.endswith('[COLOR povil_faint]/5[/COLOR]'), label)
                for site in ('imdb', 'trakt', 'tomato'):
                    unit = next(c for c in row if c.get('description') == site)
                    self.assertNotIn('/5', next(c for c in unit if c.get('type') == 'label').findtext('label'))
        self.assertTrue((ROOT / 'skin.povil.onyx/media/povil/ratings/meta.png').is_file())


class PosterBadgeTests(unittest.TestCase):
    """The owner, Nov 2026: "a general rating on the poster itself, top right -- something luxurious"."""

    def layouts(self):
        root = ET.parse(XML / 'Includes_POVIL_Home.xml').getroot()
        return {i.get('name'): i for i in root.findall('include') if (i.get('name') or '').startswith(('POVIL_Item_', 'POVIL_ViewItem_'))}

    def test_every_poster_and_wide_tile_carries_its_rating_top_right(self):
        layouts = self.layouts()
        self.assertEqual(len(layouts), 8)
        for name, layout in layouts.items():
            badges = [c for c in layout.iter('control') if c.get('description') == 'rating on the picture']
            if name.endswith('square'):
                self.assertEqual(badges, [], "an add-on's or a channel's tile has no rating")
                continue
            self.assertEqual(len(badges), 2, name + ': at rest and focused')
            for badge in badges:
                shown = badge.findtext('visible')
                self.assertIn('Integer.IsGreater(ListItem.Rating,0)', shown)
                self.assertIn('!ListItem.IsParentFolder', shown)
                self.assertIn('new_page=', shown, 'not on the "more" item of POV')
                self.assertEqual(badge.find('control').findtext('texture'), 'povil/ratings/badge.png')
                self.assertIn('$INFO[ListItem.Rating]', [c.findtext('label') for c in badge.iter('control')])
        # top right: the plate ends ten pixels inside the picture's right edge; the watched check moved left
        text = (XML / 'Includes_POVIL_Home.xml').read_text('utf-8')
        self.assertNotRegex(text, r'<left>\d{3}</left><top>\d+</top><width>34</width><height>34</height>\s*<texture[^>]*>povil/check\.png')
        self.assertRegex(text, r'<left>10</left><top>\d+</top><width>34</width><height>34</height>\s*<texture[^>]*>povil/check\.png')
        self.assertTrue((ROOT / 'skin.povil.onyx/media/povil/ratings/badge.png').is_file())


if __name__ == '__main__':
    unittest.main()
