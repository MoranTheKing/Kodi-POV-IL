"""Onyx 1.0.38: the wide rows to the screen's left edge; a screen's thirteenth chip an id of its own.

A viewer, Nov 2026, with a video of the home's "next episode" row: "really strange ... I installed the latest
(1.0.37) ... the episodes still pass *under* some bar". A findings report on Onyx 1.0.33 said the same: four wide
pictures of 352 x 198 started at x=290, and the picture past the row's end stood dimmed and still at x=-50 (the
peek) while the row slid under it -- "a black bar that hides part of the screen". Now five of 330 x 186, the row
from the screen's edge and the peek a sliver there, as the posters' rows have always been. QA Kodi, on the screen:
a season's 17 episodes and the films' "trending this week", at rest and mid-scroll (the scroll slowed to 3 s).

The same report: on the films' and the series' screens Right on the first chip jumped to the last (Umbrella), and
Left on the series' last to their first. 9100 + (ti + 1) * 12 + ci gave a screen's thirteenth chip the next
screen's first chip's id, and Kodi links a grouplist's children by id. QA Kodi: both ends of both rows stop now.
"""
import re
import sys
import unittest
from collections import Counter
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


def list_rect(text, cid):
    block = text.split('<control type="list" id="%d">' % cid)[1].split('</control>')[0]
    m = re.search(r'<left>(-?\d+)</left><top>\d+</top><width>(\d+)</width>', block)
    return int(m.group(1)), int(m.group(2)), block


class WideRows(unittest.TestCase):
    def setUp(self):
        self.H = tools('gen_home')

    def tiles(self, kind):
        """(first tile's left, last tile's right, the peek's visible width) of a right-to-left row of `kind`."""
        H = self.H
        g = H.GEOM[kind]
        left, width, peek = H.rtl_slots(g)
        slots = width // g['step']
        return left + H.PAD, left + H.PAD + (slots - 1) * g['step'] + g['w'], peek + g['w']

    def test_a_wide_row_reaches_the_screen_s_left_edge_as_a_poster_row_does(self):
        first, last, peek = self.tiles('landscape')
        p_first, p_last, p_peek = self.tiles('poster')
        self.assertLessEqual(first, 60, 'the first picture at the edge, not at x=332')
        self.assertLessEqual(abs(first - p_first), 10)
        self.assertEqual(last, 1920 - self.H.MARGIN)
        self.assertEqual(p_last, 1920 - self.H.MARGIN)
        self.assertTrue(0 < peek <= 24, 'the picture past the end a sliver at the edge (%d px)' % peek)
        self.assertTrue(0 < p_peek <= 24)
        self.assertEqual(self.H.rtl_slots(self.H.GEOM['landscape'])[1] // self.H.GEOM['landscape']['step'], 5)

    def test_room_for_the_focus_glow_between_two_pictures(self):
        g = self.H.GEOM['landscape']
        self.assertGreaterEqual(g['step'] - g['w'], 30)
        self.assertAlmostEqual(g['w'] / g['h'], 16 / 9, delta=0.01)
        # the title and the line under it still inside the row's height
        self.assertLessEqual(22 + g['h'] + 46 + 28, g['list_h'])

    def test_the_episodes_view_from_the_edge(self):
        text = xml('View_POVIL.xml')
        left, width, block = list_rect(text, 55)
        self.assertEqual(left, 10)
        self.assertEqual(width, 5 * 362 + self.H.PAD)
        self.assertNotIn('end="280,0"', text, 'no wide row in the films\' view starts at x=290 either')
        peek = text.split('<control type="list" id="55">')[1].split('description="peek"')[1]
        self.assertIn('<left>-310</left>', peek.split('</control>')[0])

    def test_every_wide_row_of_the_home_from_the_edge(self):
        H, text = self.H, xml('Home.xml')
        seen = 0
        for ti, tab in enumerate(H.TABS):
            if H.slot_tab(tab):
                continue
            for ri, (_title, path, kind, _opt) in enumerate(tab['rows']):
                if kind == 'landscape' and H.is_rtl(path):
                    with self.subTest(tab['id'], row=ri):
                        self.assertEqual(list_rect(text, H.row_id(ti, ri))[0], 10)
                        seen += 1
        self.assertGreater(seen, 3)
        self.assertNotIn('<left>290</left>', text)
        self.assertNotIn('end="280,0"', text, 'a wide row in a poster row\'s place needs no shift now')


class ChipIds(unittest.TestCase):
    def setUp(self):
        self.H = tools('gen_home')

    def test_no_control_id_twice_on_the_home(self):
        ids = re.findall(r'<control type="\w+" id="(\d+)"', xml('Home.xml'))
        self.assertEqual([i for i, n in Counter(ids).items() if n > 1], [])

    def test_every_chip_an_id_of_its_own(self):
        H = self.H
        build = [cid for ti, tab in enumerate(H.TABS) for cid in H.chip_ids(ti, tab)]
        self.assertEqual(len(build), len(set(build)))
        own = {cid for ti in range(len(H.TABS)) for cid in H.custom_chip_ids(ti)}
        self.assertFalse(own & set(build))
        self.assertTrue(max(build) < 9510, 'below the ids Onyx\'s own home uses')

    def test_the_first_twelve_keep_their_ids(self):
        H = self.H
        for ti, tab in enumerate(H.TABS):
            for ci, cid in enumerate(H.chip_ids(ti, tab)[:12]):
                self.assertEqual(cid, 9100 + (ti + 1) * 12 + ci)

    def test_umbrella_keeps_its_hide_switch_and_the_end_of_the_row(self):
        H, text = self.H, xml('Home.xml')
        chips = text.split('<control type="grouplist" id="9100"')[1]
        for tab_id in ('movies', 'tv'):
            ti = [t['id'] for t in H.TABS].index(tab_id)
            ids = H.chip_ids(ti, H.TABS[ti])
            self.assertEqual(len(ids), 13)
            umbrella = chips.split('<control type="button" id="%d">' % ids[12])[1].split('</control>')[0]
            self.assertIn('<label>Umbrella</label>', umbrella)
            self.assertIn('!Skin.HasSetting(POVILHideChip_%s_12)' % tab_id, umbrella)
            # left to right in the XML: the last chip first
            self.assertLess(chips.index('id="%d"' % ids[12]), chips.index('id="%d"' % ids[0]))


class OnyxTextures(unittest.TestCase):
    def test_three_textures_named_as_they_are(self):
        names = {f[0].lower() for f in tools('xbt_info').read(str(SKIN / 'media/Textures.xbt'))[1]}
        for name, old, new in (('SettingsScreenCalibration.xml', 'dubuggrid1080.png', 'debuggrid1080.png'),
                               ('MyPVRTimers.xml', 'list/ListNF.png', 'img/ListNF.png'),
                               ('CustomFanart.xml', 'colors/BlackDot.png', 'img/BlackDot.png')):
            with self.subTest(name):
                text = xml(name)
                self.assertNotIn('>%s<' % old, text)
                self.assertIn('>%s<' % new, text)
                self.assertIn(new.lower(), names)
                self.assertNotIn(old.lower(), names)


if __name__ == '__main__':
    unittest.main()
