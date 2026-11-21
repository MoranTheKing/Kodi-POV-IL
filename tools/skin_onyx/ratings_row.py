# -*- coding: utf-8 -*-
"""The ratings row of skin.povil.onyx: what several sites say about the title on screen.

The owner (Nov 2026): the hero showed one number, TMDb's, with a star. Now a row of
marks: TMDb, IMDb, Rotten Tomatoes' critics and audience, Metacritic, Trakt and
Letterboxd -- for a film, a show and a single episode, wherever Onyx shows a title.

How it gets its numbers (the Wizard's ratings.py answers; nothing here polls):
  * a hidden label holds the title's key -- "<imdb id>|<kind>|<season>|<episode>",
    empty for anything that is not a POV title;
  * a timer notices a key that was not asked yet, writes it to
    Window(home).Property(<slot>ask) and announces it (NotifyAll(povil.ratings,<slot name>));
  * the Wizard writes the sites' numbers to <slot><site> and LAST the key to <slot>for;
  * a mark shows only while <slot>for is still the key on screen, so a slow answer
    never appears beside another title.
TMDb's mark shows at once, from the list's own rating, and takes Trakt's figure for
TMDb when the answer comes (the same site; the list's copy may be older).

Reading order is right to left: TMDb first (it is there from the start, so nothing
moves when the others fade in beside it), then IMDb, the tomato, the popcorn,
Metacritic, Trakt, Letterboxd. Each unit keeps its mark on the left of its number;
Metacritic's number sits on a plate in its verdict's colour, Letterboxd's says "/5".

Last in the row, where a sum belongs, their AVERAGE (Onyx 1.0.37): the word, a gold
star and the number -- the very number on the title's picture (gen_home.py item_layout,
the Wizard's pov_rating.py). The owner, Nov 2026: the picture said 6.6 beside TMDb 6.5,
IMDb 6.6 and Trakt 71% -- "the average on the poster is not the average ... where was
this 6.6 made up from". The Wizard answers it with the sites (<slot>avg); to work it
out it is told the list's own figure for the title (<slot>list). A picture's own
number is put on it where its list is built (ListItem.Property(povil_avg)); Kodi works
a list item's label out once, when its row is loaded, so the Wizard loads the rows
again when a picture is behind the row (ratings.py).
"""
MARKS = 'povil/ratings/'
HEIGHT = 32
MARK = 30               # a mark's height on screen (drawn at 56)
GAP = 22
# (site, mark texture or None, mark width, number width) in reading order
UNITS = (
    ('tmdb', 'tmdb.png', 60, 48),
    ('imdb', 'imdb.png', 60, 48),
    ('tomato', 'tomato_$INFO[Window(home).Property(%(p)stomato_state)].png', 30, 66),
    ('popcorn', 'popcorn_$INFO[Window(home).Property(%(p)spopcorn_state)].png', 30, 66),
    ('meta', 'meta.png', 30, 44),
    ('trakt', 'trakt.png', 60, 58),
    ('letterboxd', 'letterboxd.png', 50, 76),
)
META_TONES = (('good', 'FF66CC33'), ('mixed', 'FFFFCC33'), ('bad', 'FFFF5544'))
# Letterboxd counts to five where the others count to ten or a hundred: its number says so (the owner,
# Nov 2026: "it is not clear that this one is out of 5")
OUT_OF = {'letterboxd': '[COLOR povil_faint]/5[/COLOR]'}
# The average's unit: its word, a star, the number
AVERAGE_WORD, AVERAGE_WORD_W, AVERAGE_STAR, AVERAGE_W = u'\u05de\u05de\u05d5\u05e6\u05e2', 104, 22, 44
# The number on a title's picture: ListItem.Property(povil_avg), written where POV's lists are built
ITEM_AVERAGE = 'ListItem.Property(povil_avg)'


def item_average_variable(x, name):
    """The number on a picture: the average its list gave it, else the list's own rating (a title the Wizard's
    patches did not reach, a build without the Wizard)."""
    x(1, '<variable name="%s">' % name)
    x(2, '<value condition="!String.IsEmpty(%s)">$INFO[%s]</value>' % (ITEM_AVERAGE, ITEM_AVERAGE))
    x(2, '<value>$INFO[ListItem.Rating]</value>')
    x(1, '</variable>')


def key(item, kind=None, season=None, episode=None):
    """The label's text for one item ('ListItem', 'Container(5010).ListItem', 'VideoPlayer')."""
    return '$INFO[%s.UniqueID(imdb)]|%s|%s|%s' % (
        item, kind or '$INFO[%s.DBType]' % item, season or '$INFO[%s.Season]' % item, episode or '$INFO[%s.Episode]' % item)


def has_key(item):
    return 'String.StartsWith(%s.UniqueID(imdb),tt)' % item


def key_label(x, d, cid, value):
    x(d, '<control type="label" id="%d" description="ratings key"><left>-2000</left><top>0</top><width>10</width><height>10</height>'
         '<label>%s</label></control>' % (cid, value))


def answered(cid, prefix):
    return 'String.IsEqual(Control.GetLabel(%d),Window(home).Property(%sfor))' % (cid, prefix)


def tmdb_variable(x, name, cid, prefix, list_rating):
    """TMDb's number: the list's own at once, Trakt's figure for TMDb once the answer is in."""
    x(1, '<variable name="%s">' % name)
    x(2, '<value condition="%s + !String.IsEmpty(Window(home).Property(%stmdb))">$INFO[Window(home).Property(%stmdb)]</value>'
         % (answered(cid, prefix), prefix, prefix))
    x(2, '<value condition="!String.IsEmpty(Control.GetLabel(%d))">%s</value>' % (cid, list_rating))
    x(1, '</variable>')


def timer(x, name, cid, prefix, slot, where):
    """Ask once per key, the moment it is on the screen (the owner, Nov 2026: "all of them at once,
    instantly" -- the second's rest that was here came before every answer, known or not; the Wizard
    now answers a known title in milliseconds and asks the titles beside it ahead)."""
    x(1, '<timer>')
    x(2, '<name>%s</name>' % name)
    x(2, '<start reset="true">%s + !String.IsEmpty(Control.GetLabel(%d)) + '
         '!String.IsEqual(Control.GetLabel(%d),Window(home).Property(%sask))</start>' % (where, cid, cid, prefix))
    # the list's own figure for the title (the hidden label TMDb's unit shows: not answered yet, it is the list's),
    # written before the question so the answer finds it
    x(2, '<onstart>SetProperty(%slist,$ESCINFO[Control.GetLabel(%d)],home)</onstart>' % (prefix, cid + 1))
    # (this skin shows the averages: the Wizard asks the home's rows again for what it learns -- ratings.py SKIN_SHOWS)
    x(2, '<onstart>SetProperty(povil.avg.skin,1,home)</onstart>')
    x(2, '<onstart>SetProperty(%sask,$ESCINFO[Control.GetLabel(%d)],home)</onstart>' % (prefix, cid))
    x(2, '<onstart>NotifyAll(povil.ratings,%s)</onstart>' % slot)
    # a timer that is running never starts again: it stops at once, ready for the next title
    x(2, '<stop>true</stop>')
    x(1, '</timer>')


def row(x, d, right, top, cid, prefix, tmdb_var, width=1200, font='povil_meta_bold', extra_visible=''):
    """The marks, right-aligned to `right`, as one line `HEIGHT` high at `top`."""
    seen = answered(cid, prefix)
    x(d, '<control type="grouplist" description="ratings"><left>%d</left><top>%d</top><width>%d</width><height>%d</height>'
         '<orientation>horizontal</orientation><align>right</align><itemgap>%d</itemgap><usecontrolcoords>true</usecontrolcoords>'
         % (right - width, top, width, HEIGHT, GAP))
    x(d + 1, '<visible>!String.IsEmpty(Control.GetLabel(%d))%s</visible>' % (cid, (' + ' + extra_visible) if extra_visible else ''))
    # the average: written first, so it stands last in the reading -- after the sites it is the average of
    average = 'Window(home).Property(%savg)' % prefix
    x(d + 1, '<control type="group" description="average"><width>%d</width><height>%d</height>'
             % (AVERAGE_WORD_W + 8 + AVERAGE_STAR + 6 + AVERAGE_W, HEIGHT))
    x(d + 2, '<visible>%s + !String.IsEmpty(%s)</visible>' % (seen, average))
    x(d + 2, '<animation effect="fade" start="0" end="100" time="220">Visible</animation>')
    x(d + 2, '<control type="label"><left>0</left><top>0</top><width>%d</width><height>%d</height><font>%s</font>'
             '<textcolor>povil_dim</textcolor><align>right</align><aligny>center</aligny><label>%s</label></control>'
             % (AVERAGE_WORD_W, HEIGHT, font, AVERAGE_WORD))
    x(d + 2, '<control type="image"><left>%d</left><top>5</top><width>%d</width><height>%d</height>'
             '<texture colordiffuse="povil_gold">povil/star.png</texture></control>' % (AVERAGE_WORD_W + 8, AVERAGE_STAR, AVERAGE_STAR))
    x(d + 2, '<control type="label"><left>%d</left><top>0</top><width>%d</width><height>%d</height><font>%s</font>'
             '<textcolor>povil_gold</textcolor><align>left</align><aligny>center</aligny><label>$INFO[%s]</label></control>'
             % (AVERAGE_WORD_W + 8 + AVERAGE_STAR + 6, AVERAGE_W, HEIGHT, font, average))
    x(d + 1, '</control>')
    for site, mark, mark_w, text_w in reversed(UNITS):
        prop = 'Window(home).Property(%s%s)' % (prefix, site)
        # (a variable cannot be tested directly: TMDb's unit follows the hidden label that shows its number)
        shown = '!String.IsEmpty(Control.GetLabel(%d))' % (cid + 1) if site == 'tmdb' else '%s + !String.IsEmpty(%s)' % (seen, prop)
        value = '$VAR[%s]' % tmdb_var if site == 'tmdb' else '$INFO[%s]' % prop
        x(d + 1, '<control type="group" description="%s"><width>%d</width><height>%d</height>'
                 % (site, mark_w + 8 + text_w, HEIGHT))
        x(d + 2, '<visible>%s</visible>' % shown)
        x(d + 2, '<animation effect="fade" start="0" end="100" time="220">Visible</animation>')
        x(d + 2, '<control type="image"><left>0</left><top>1</top><width>%d</width><height>%d</height>'
                 '<texture>%s%s</texture><aspectratio>keep</aspectratio></control>' % (mark_w, MARK, MARKS, mark % {'p': prefix}))
        if site == 'meta':
            # the site's mark, then its score on a plate in the verdict's colour
            for tone, colour in META_TONES:
                x(d + 2, '<control type="image"><left>%d</left><top>1</top><width>%d</width><height>%d</height>'
                         '<texture colordiffuse="%s">%ssquare.png</texture>'
                         '<visible>String.IsEqual(Window(home).Property(%smeta_tone),%s)</visible></control>'
                         % (mark_w + 8, text_w, MARK, colour, MARKS, prefix, tone))
            x(d + 2, '<control type="label"><left>%d</left><top>0</top><width>%d</width><height>%d</height><font>%s</font>'
                     '<textcolor>povil_ink</textcolor><align>center</align><aligny>center</aligny><label>%s</label></control>'
                     % (mark_w + 8, text_w, HEIGHT, font, value))
        else:
            x(d + 2, '<control type="label"><left>%d</left><top>0</top><width>%d</width><height>%d</height><font>%s</font>'
                     '<textcolor>povil_white</textcolor><align>left</align><aligny>center</aligny><label>%s%s</label></control>'
                     % (mark_w + 8, text_w, HEIGHT, font, value, OUT_OF.get(site, '')))
        x(d + 1, '</control>')
    x(d, '</control>')
    # the label the TMDb unit is tested by (a variable cannot be tested for being empty)
    x(d, '<control type="label" id="%d"><left>-2000</left><top>0</top><width>10</width><height>10</height>'
         '<label>$VAR[%s]</label></control>' % (cid + 1, tmdb_var))
