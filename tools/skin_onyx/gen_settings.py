# -*- coding: utf-8 -*-
"""Generate Kodi's settings screens for skin.povil.onyx.

    python gen_settings.py ../../skin.povil.onyx

Settings.xml           the settings home: tiles, the first on the right
SettingsCategory.xml   a section's settings (Kodi fills the categories and the rows)
DialogSettings.xml     a settings card (the player's sound and picture settings, and Kodi's other small dialogs)
DialogAddonSettings.xml  an add-on's settings

Right to left as far as Kodi allows: the page is mirrored (the title and the
categories on the right, the clock on the left, the buttons in Hebrew order),
but inside a row Kodi itself draws the value of a setting at the row's right
end (GUIButtonControl / GUISpinControlEx / GUISettingsSliderControl /
GUIEditControl: the second text is always right-aligned), so a setting's name
stays on the row's left in every row -- switches included, so the rows of a
list all read the same way.

A row is tall, sits on a faint plate so the eye follows it from the name to
the value, and the focused row gets a gold frame; a switch shows both its
states (Onyx drew nothing for "off").
"""
import os
import sys
from xml.sax.saxutils import escape

import gen_home as H

NL = chr(10)
RIGHT = 1920 - H.MARGIN
ROW_H, GAP = 72, 8
CAT_W = 390
CAT_LEFT = RIGHT - CAT_W
LIST_LEFT = H.MARGIN
LIST_W = CAT_LEFT - 60 - LIST_LEFT
TOP = 140
S = 'povil/settings/'


def e(s):
    return escape(s)


# ---------------------------------------------------------------- rows
def plate(focus=True, nofocus='0DFFFFFF'):
    out = '<texturefocus border="30">%srow_focus.png</texturefocus>' % S if focus else '<texturefocus></texturefocus>'
    if nofocus:
        out += '<texturenofocus border="30" colordiffuse="%s">povil/rounded_fill.png</texturenofocus>' % nofocus
    else:
        out += '<texturenofocus></texturenofocus>'
    return out


def text(font='povil_row', align='left', offset=28):
    return ('<font>%s</font><textcolor>povil_white</textcolor><focusedcolor>povil_white</focusedcolor>'
            '<disabledcolor>66F5F2EC</disabledcolor><shadowcolor>00000000</shadowcolor><align>%s</align><aligny>center</aligny>'
            '<textoffsetx>%d</textoffsetx><pulseonselect>false</pulseonselect>' % (font, align, offset))


def templates(x, d, width, height=ROW_H, font='povil_row', edit=True):
    """The controls Kodi copies for every setting (ids 7-15)."""
    size = '<width>%d</width><height>%d</height>' % (width, height)
    x(d, '<control type="button" id="7" description="A setting with a value, or an action">%s%s%s</control>' % (size, text(font), plate()))
    x(d, '<control type="radiobutton" id="8" description="A switch">%s%s%s'
         '<radiowidth>88</radiowidth><radioheight>48</radioheight>'
         '<textureradioonfocus>%sswitch_on.png</textureradioonfocus><textureradioonnofocus>%sswitch_on.png</textureradioonnofocus>'
         '<textureradioofffocus>%sswitch_off.png</textureradioofffocus><textureradiooffnofocus>%sswitch_off.png</textureradiooffnofocus>'
         '<textureradioondisabled>%sswitch_on_dim.png</textureradioondisabled><textureradiooffdisabled>%sswitch_off_dim.png</textureradiooffdisabled>'
         '</control>' % (size, text(font), plate(), S, S, S, S, S, S))
    x(d, '<control type="spincontrolex" id="9" description="A value stepped with two arrows">%s%s%s'
         '<spinwidth>40</spinwidth><spinheight>40</spinheight>'
         '<textureup colordiffuse="B3FFFFFF">%sarrow_up.png</textureup><textureupfocus colordiffuse="povil_gold">%sarrow_up.png</textureupfocus>'
         '<textureupdisabled colordiffuse="33FFFFFF">%sarrow_up.png</textureupdisabled>'
         '<texturedown colordiffuse="B3FFFFFF">%sarrow_down.png</texturedown><texturedownfocus colordiffuse="povil_gold">%sarrow_down.png</texturedownfocus>'
         '<texturedowndisabled colordiffuse="33FFFFFF">%sarrow_down.png</texturedowndisabled>'
         '</control>' % (size, text(font), plate(), S, S, S, S, S, S))
    x(d, '<control type="image" id="11" description="A line between groups"><width>%d</width><height>2</height>'
         '<texture colordiffuse="1FFFFFFF">povil/white.png</texture></control>' % width)
    if edit:
        x(d, '<control type="edit" id="12" description="A text">%s%s%s</control>' % (size, text(font), plate()))
    x(d, '<control type="sliderex" id="13" description="A slider">%s%s%s'
         '<sliderwidth>300</sliderwidth><sliderheight>26</sliderheight>'
         '<texturesliderbar border="16,0,16,0" colordiffuse="59FFFFFF">%sslider_bar.png</texturesliderbar>'
         '<textureslidernib colordiffuse="povil_white">povil/pill.png</textureslidernib>'
         '<textureslidernibfocus colordiffuse="povil_gold">povil/pill.png</textureslidernibfocus>'
         '</control>' % (size, text(font), plate(), S))
    x(d, '<control type="label" id="14" description="A group\'s title"><width>%d</width><height>56</height><font>povil_chip</font>'
         '<textcolor>povil_gold</textcolor><aligny>center</aligny><textoffsetx>28</textoffsetx></control>' % width)
    x(d, '<control type="colorbutton" id="15" description="A colour">%s%s%s<colorwidth>88</colorwidth><colorheight>40</colorheight>'
         '<texturecolormask>picker/color-button-box.png</texturecolormask>'
         '<texturecolordisabledmask colordiffuse="Disabled">picker/color-button-box.png</texturecolordisabledmask></control>'
         % (size, text(font), plate()))


def category_button(x, d, cid=10, width=CAT_W):
    x(d, '<control type="button" id="%d" description="A category"><width>%d</width><height>%d</height>'
         '<font>povil_row</font><textcolor>povil_dim</textcolor><focusedcolor>povil_white</focusedcolor><selectedcolor>povil_gold</selectedcolor>'
         '<disabledcolor>66F5F2EC</disabledcolor><shadowcolor>00000000</shadowcolor><align>right</align><aligny>center</aligny>'
         '<textoffsetx>28</textoffsetx><pulseonselect>false</pulseonselect>%s</control>' % (cid, width, ROW_H, plate(nofocus='')))


def pill_button(x, d, bid, width, label='', nav=''):
    """OK / Cancel and their like: a pill, gold with dark text when focused."""
    x(d, '<control type="button" id="%d"><width>%d</width><height>64</height>%s'
         '<font>povil_row</font><textcolor>povil_white</textcolor><focusedcolor>povil_ink</focusedcolor><disabledcolor>66F5F2EC</disabledcolor>'
         '<shadowcolor>00000000</shadowcolor><align>center</align><aligny>center</aligny><textoffsetx>16</textoffsetx><pulseonselect>false</pulseonselect>'
         '<texturenofocus border="24" colordiffuse="1FFFFFFF">povil/pill48.png</texturenofocus>'
         '<texturefocus border="24" colordiffuse="povil_gold">povil/pill48.png</texturefocus>%s</control>'
         % (bid, width, ('<label>%s</label>' % label) if label else '', nav))


def scrollbar(x, d, left, top, height, onright):
    """Left of its list (the page reads right to left); reached with the mouse or a finger only."""
    x(d, '<control type="scrollbar" id="60"><left>%d</left><top>%d</top><width>8</width><height>%d</height>'
         '<texturesliderbackground border="4" colordiffuse="14FFFFFF">povil/progress.png</texturesliderbackground>'
         '<texturesliderbar border="4" colordiffuse="59FFFFFF">povil/progress.png</texturesliderbar>'
         '<texturesliderbarfocus border="4" colordiffuse="povil_gold">povil/progress.png</texturesliderbarfocus>'
         '<orientation>vertical</orientation><showonepage>false</showonepage><onright>%d</onright>'
         '<visible>$EXP[isEnabledScrollbar]</visible></control>' % (left, top, height, onright))


def page_top(x, d, heading):
    """A full page's top line: the title on the right, the clock on the left."""
    x(d, '<control type="label" description="Title"><left>%d</left><top>2</top><width>1300</width><height>72</height>'
         '<font>povil_clock</font><textcolor>povil_white</textcolor><align>right</align><aligny>center</aligny>'
         '<label>%s</label></control>' % (RIGHT - 1300, heading))
    x(d, '<control type="image" description="Title rule"><left>%d</left><top>92</top><width>%d</width><height>2</height>'
         '<texture colordiffuse="1FFFFFFF">povil/white.png</texture></control>' % (H.MARGIN, RIGHT - H.MARGIN))


# ---------------------------------------------------------------- the settings home
# (id, label, icon, onclick, visible, hint) in reading order: the first is the top right tile
TILES = [
    ('skin', 'סקין', 'skin', 'ActivateWindow(SkinSettings)', '', '$LOCALIZE[22080] $LOCALIZE[166]. $LOCALIZE[14090]. $LOCALIZE[14081]. $LOCALIZE[24008]'),
    ('interface', '$LOCALIZE[14206]', 'interface', 'ActivateWindow(InterfaceSettings)', '',
     '$LOCALIZE[20077]. $LOCALIZE[33063]. $LOCALIZE[111].'),
    ('player', '$LOCALIZE[14200]', 'player', 'ActivateWindow(PlayerSettings)', '',
     '$LOCALIZE[14022]. $LOCALIZE[14086]. $LOCALIZE[14081]. $LOCALIZE[24012]. $LOCALIZE[14087]'),
    ('media', '$LOCALIZE[14211]', 'media', 'ActivateWindow(MediaSettings)', '', '$LOCALIZE[21359] $LOCALIZE[21364]. $LOCALIZE[21365].'),
    ('services', '$LOCALIZE[24018]', 'network', 'ActivateWindow(ServiceSettings)', '', '$LOCALIZE[14036]. $LOCALIZE[1200]. $LOCALIZE[798].'),
    ('system', '$LOCALIZE[24992]', 'system', 'ActivateWindow(SystemSettings)', '',
     '$LOCALIZE[21373]. $LOCALIZE[337]. $LOCALIZE[14094]. $LOCALIZE[14095]. $LOCALIZE[14092]. $LOCALIZE[20100].'),
    ('pvr', '$LOCALIZE[14204]', 'livetv', 'ActivateWindow(PVRSettings)', '', '$LOCALIZE[19069]. $LOCALIZE[264]. $LOCALIZE[14095]. $LOCALIZE[19259].'),
    ('addons', '$LOCALIZE[24001]', 'addons', 'ActivateWindow(AddonBrowser,root)', '',
     '$LOCALIZE[24033]. $LOCALIZE[24022]. $LOCALIZE[24021]. $LOCALIZE[24034]. $LOCALIZE[25000].'),
    ('profiles', '$LOCALIZE[13200]', 'profiles', 'ActivateWindow(Profiles)', '', '$LOCALIZE[20096]. $LOCALIZE[20100]. $LOCALIZE[20115].'),
    ('files', '$LOCALIZE[10003]', 'filemanager', 'ActivateWindow(FileManager)', '', '$LOCALIZE[744]. $LOCALIZE[115]. $LOCALIZE[116]. $LOCALIZE[117]. $LOCALIZE[118].'),
    ('sysinfo', '$LOCALIZE[138]', 'sysinfo', 'ActivateWindow(SystemInfo)', '', '$LOCALIZE[154]. $LOCALIZE[705]. $LOCALIZE[1212]. $LOCALIZE[13281].'),
    ('games', '$LOCALIZE[15016]', 'games', 'ActivateWindow(GameSettings)', 'System.GetBool(gamesgeneral.enable)', '$LOCALIZE[35203]. $LOCALIZE[35253].'),
    ('libreelec', 'LibreELEC', 'libreelec', 'RunAddon(service.libreelec.settings)', 'System.HasAddon(service.libreelec.settings)', ''),
]
COLS, TILE_W, TILE_H, TILE_GAP = 5, 328, 236, 25
TILE_BASE = 9100


def tile_slots():
    """(tile, variant id, column, row, extra condition). A tile that is not always
    there sits last in its row; the one after it has a copy one slot to the right
    for when it is missing, so the row never has a hole."""
    slots = []
    for i, tile in enumerate(TILES):
        optional_before = [t for t in TILES[:i] if t[4]]
        if not optional_before:
            slots.append((tile, TILE_BASE + i, i % COLS, i // COLS, ''))
            continue
        # one copy per number of earlier optional tiles that are missing
        for missing in range(len(optional_before) + 1):
            if missing == 0:
                cond = ' + '.join(t[4] for t in optional_before)
            elif missing == len(optional_before):
                cond = ' + '.join('!' + t[4] for t in optional_before)
            else:
                raise SystemExit('gen_settings: more than one optional tile before %s' % tile[0])
            pos = i - missing
            slots.append((tile, TILE_BASE + i + 100 * missing, pos % COLS, pos // COLS, cond))
    return slots


def gen_home():
    x = H.X()
    slots = tile_slots()
    by_pos = {}
    for tile, sid, col, row, cond in slots:
        by_pos.setdefault((col, row), []).append((tile, sid, cond))

    def conds(tile, cond):
        return [c for c in (tile[4], cond) if c]

    def last_col(row):
        return max(c for (c, r) in by_pos if r == row)

    def step(tag, col, row, descend=False):
        """The tile at a slot: every copy that may sit there is named under its own
        condition. Going up or down, a slot that is empty (or past the row's end)
        gives the move to the nearest tile on its right."""
        out, emptier = '', []
        for cc in range(min(col, last_col(row)), -1, -1):
            here = by_pos.get((cc, row), [])
            for tile, sid, cond in here:
                cs = conds(tile, cond)
                if emptier:
                    cs = cs + ['![%s]' % ' | '.join('[%s]' % c for c in emptier)]
                out += '<%s%s>%d</%s>' % (tag, (' condition="%s"' % e(' + '.join(cs))) if cs else '', sid, tag)
            if not descend or any(not conds(t, c) for t, _s, c in here):
                break
            emptier = [' + '.join(conds(t, c)) for t, _s, c in here]
        return out
    x(0, '<?xml version="1.0" encoding="UTF-8"?>')
    x(0, '<!-- Generated by tools/skin_onyx/gen_settings.py. Do not edit by hand. -->')
    x(0, '<window>')
    x(1, '<defaultcontrol always="true">%d</defaultcontrol>' % TILE_BASE)
    x(1, '<controls>')
    x(2, '<include>FullBackground</include>')
    x(2, '<control type="group" description="Content">')
    x(3, '<include>OpenClose</include>')
    page_top(x, 3, '$LOCALIZE[10004]')
    rows = (len(TILES) + COLS - 1) // COLS
    for tile, sid, col, row, cond in slots:
        tid, label, icon, click, vis, _hint = tile
        left = RIGHT - TILE_W - col * (TILE_W + TILE_GAP)
        top = TOP + row * (TILE_H + TILE_GAP)
        show = ' + '.join(conds(tile, cond))
        x(3, '<control type="group" description="%s">' % tid)
        x(4, '<left>%d</left><top>%d</top>' % (left, top))
        if show:
            x(4, '<visible>%s</visible>' % e(show))
        moves = step('onleft', col + 1, row) if col < last_col(row) else ''
        moves += step('onright', col - 1, row) if col > 0 else ''
        if row > 0:
            moves += step('onup', col, row - 1, True)
        if row < rows - 1:
            moves += step('ondown', col, row + 1, True)
        x(4, '<control type="button" id="%d"><left>0</left><top>0</top><width>%d</width><height>%d</height><label></label>'
             '<texturenofocus border="30" colordiffuse="12FFFFFF">povil/rounded_fill.png</texturenofocus>'
             '<texturefocus border="30">%srow_focus.png</texturefocus><onclick>%s</onclick>%s</control>'
             % (sid, TILE_W, TILE_H, S, e(click), moves))
        x(4, '<control type="image"><left>%d</left><top>22</top><width>128</width><height>128</height><aspectratio>keep</aspectratio>'
             '<texture colordiffuse="povil_white">settings/%s.png</texture><visible>!Control.HasFocus(%d)</visible></control>' % ((TILE_W - 128) // 2, icon, sid))
        x(4, '<control type="image"><left>%d</left><top>22</top><width>128</width><height>128</height><aspectratio>keep</aspectratio>'
             '<texture colordiffuse="povil_gold">settings/%s.png</texture><visible>Control.HasFocus(%d)</visible></control>' % ((TILE_W - 128) // 2, icon, sid))
        x(4, '<control type="label"><left>12</left><top>150</top><width>%d</width><height>60</height><font>povil_menu</font>'
             '<textcolor>povil_white</textcolor><align>center</align><aligny>center</aligny><label>%s</label></control>' % (TILE_W - 24, label))
        x(3, '</control>')
    x(3, '<control type="label" description="What the focused tile holds"><left>%d</left><top>%d</top><width>%d</width><height>48</height>'
         '<font>povil_meta</font><textcolor>povil_dim</textcolor><align>right</align><aligny>center</aligny>'
         '<label>$VAR[POVIL_SettingsHint]</label></control>' % (H.MARGIN, TOP + rows * (TILE_H + TILE_GAP) + 4, RIGHT - H.MARGIN))
    x(2, '</control>')
    x(1, '</controls>')
    x(0, '</window>')
    return x.text()


# ---------------------------------------------------------------- a section's settings
def gen_category():
    x = H.X()
    list_h = 9 * ROW_H + 8 * GAP
    x(0, '<?xml version="1.0" encoding="UTF-8"?>')
    x(0, '<!-- Generated by tools/skin_onyx/gen_settings.py. Do not edit by hand. -->')
    x(0, '<window>')
    x(1, '<defaultcontrol always="true">3</defaultcontrol>')
    x(1, '<controls>')
    x(2, '<include>FullBackground</include>')
    x(2, '<control type="group" description="Content">')
    x(3, '<include>OpenClose</include>')
    page_top(x, 3, '$LOCALIZE[10004]$INFO[Control.GetLabel(2),  ·  ]')
    x(3, '<control type="label" id="2" description="Kodi writes the section\'s name here"><left>-2000</left><top>0</top><width>10</width><height>10</height><font>povil_tiny</font></control>')
    x(3, '<control type="grouplist" id="3" description="Categories, on the right"><left>%d</left><top>%d</top><width>%d</width><height>%d</height>'
         '<itemgap>%d</itemgap><orientation>vertical</orientation><onleft>5</onleft><onright>5</onright><onup>20</onup><ondown>20</ondown></control>'
         % (CAT_LEFT, TOP, CAT_W, 8 * ROW_H + 7 * GAP, GAP))
    category_button(x, 3)
    x(3, '<control type="label" description="Settings level"><left>%d</left><top>852</top><width>%d</width><height>40</height><font>povil_small</font>'
         '<textcolor>povil_faint</textcolor><align>right</align><aligny>center</aligny><textoffsetx>28</textoffsetx><label>$LOCALIZE[31299]</label></control>' % (CAT_LEFT, CAT_W))
    x(3, '<control type="button" id="20" description="Settings level"><left>%d</left><top>894</top><width>%d</width><height>%d</height>'
         '<font>povil_row</font><textcolor>povil_white</textcolor><focusedcolor>povil_white</focusedcolor><shadowcolor>00000000</shadowcolor>'
         '<align>right</align><aligny>center</aligny><textoffsetx>28</textoffsetx><pulseonselect>false</pulseonselect>%s'
         '<onclick>SettingsLevelChange</onclick><onleft>5</onleft><onright>noop</onright><onup>3</onup><ondown>3</ondown></control>'
         % (CAT_LEFT, CAT_W, ROW_H, plate()))
    x(3, '<control type="grouplist" id="5" description="The settings"><left>%d</left><top>%d</top><width>%d</width><height>%d</height>'
         '<itemgap>%d</itemgap><orientation>vertical</orientation><pagecontrol>60</pagecontrol>'
         '<onleft>noop</onleft><onright>3</onright><onup>5</onup><ondown>5</ondown></control>' % (LIST_LEFT, TOP, LIST_W, list_h, GAP))
    templates(x, 3, LIST_W)
    scrollbar(x, 3, LIST_LEFT - 30, TOP, list_h, 5)
    x(3, '<control type="textbox" id="6" description="What the focused setting does"><left>%d</left><top>%d</top><width>%d</width><height>78</height>'
         '<font>povil_meta</font><textcolor>povil_dim</textcolor><align>right</align>'
         '<autoscroll time="3000" delay="4000" repeat="5000">true</autoscroll></control>' % (LIST_LEFT, TOP + list_h + 20, LIST_W))
    x(2, '</control>')
    x(1, '</controls>')
    x(0, '</window>')
    return x.text()


# ---------------------------------------------------------------- a settings card
def gen_dialog():
    x = H.X()
    w, rows, row_h = 1040, 6, 64
    list_w = w - 120
    left = (1920 - w) // 2
    list_h = rows * row_h + (rows - 1) * 6
    top = 140
    h = 118 + list_h + 130
    x(0, '<?xml version="1.0" encoding="UTF-8"?>')
    x(0, '<!-- Generated by tools/skin_onyx/gen_settings.py. Do not edit by hand. -->')
    x(0, '<window>')
    x(1, '<defaultcontrol always="true">5</defaultcontrol>')
    x(1, '<include>DialogOpenClose</include>')
    x(1, '<coordinates><left>0</left><top>0</top></coordinates>')
    x(1, '<controls>')
    x(2, '<control type="group"><include>DimBG</include><visible>!Window.IsVisible(VideoFullScreen.xml)</visible></control>')
    x(2, '<control type="group">')
    # Kodi's own dialogs open over this card: it steps back while one is up
    x(3, '<animation effect="fade" start="100" end="0" time="150" condition="Window.Is(contentsettings) + Window.IsActive(AddonSettings)">Conditional</animation>')
    x(3, '<animation effect="fade" start="100" end="0" time="300" condition="[Window.Is(osdaudiosettings) | Window.Is(osdvideosettings) | '
         'Window.Is(osdsubtitlesettings)] + [Window.IsVisible(SliderDialog) | Window.IsVisible(FileBrowser) | Window.IsVisible(SelectDialog)]">Conditional</animation>')
    x(3, '<animation effect="fade" start="100" end="0" time="400" condition="Window.IsVisible(SliderDialog)">Conditional</animation>')
    x(3, '<left>%d</left><top>%d</top>' % (left, top))
    x(3, '<control type="image"><left>-30</left><top>-22</top><width>%d</width><height>%d</height>'
         '<texture border="54">povil/shadow.png</texture></control>' % (w + 60, h + 60))
    x(3, '<control type="image"><left>0</left><top>0</top><width>%d</width><height>%d</height>'
         '<texture border="30" colordiffuse="F2141416">povil/rounded_fill.png</texture></control>' % (w, h))
    x(3, '<control type="label" id="2" description="Title"><left>60</left><top>26</top><width>%d</width><height>64</height>'
         '<font>povil_menu</font><textcolor>povil_gold</textcolor><align>center</align><aligny>center</aligny></control>' % list_w)
    x(3, '<control type="grouplist" id="5"><left>60</left><top>104</top><width>%d</width><height>%d</height><itemgap>6</itemgap>'
         '<orientation>vertical</orientation><pagecontrol>60</pagecontrol><onleft>noop</onleft><onright>noop</onright>'
         '<onup>9000</onup><ondown>9000</ondown></control>' % (list_w, list_h))
    templates(x, 3, list_w, row_h, 'povil_chip')
    scrollbar(x, 3, 30, 104, list_h, 5)
    # OK on the right, Cancel to its left (Hebrew order): the XML order is the screen's left-to-right order
    x(3, '<control type="grouplist" id="9000"><left>60</left><top>%d</top><width>%d</width><height>64</height><align>center</align>'
         '<orientation>horizontal</orientation><itemgap>20</itemgap><onup>5</onup><ondown>5</ondown>' % (104 + list_h + 28, list_w))
    for bid in (30, 29, 28):
        pill_button(x, 4, bid, 260)
    x(3, '</control>')
    x(2, '</control>')
    x(1, '</controls>')
    x(0, '</window>')
    return x.text()


# ---------------------------------------------------------------- an add-on's settings
def gen_addon():
    x = H.X()
    list_h = 9 * ROW_H + 8 * GAP
    cats_h = 6 * ROW_H + 5 * GAP
    x(0, '<?xml version="1.0" encoding="UTF-8"?>')
    x(0, '<!-- Generated by tools/skin_onyx/gen_settings.py. Do not edit by hand. -->')
    x(0, '<window>')
    x(1, '<defaultcontrol always="true">3</defaultcontrol>')
    x(1, '<coordinates><left>0</left><top>0</top></coordinates>')
    x(1, '<controls>')
    x(2, '<include>FullBackground</include>')
    x(2, '<control type="group"><include>DimBG</include></control>')
    x(2, '<control type="group" description="Content">')
    x(3, '<include>OpenClose</include>')
    page_top(x, 3, '$INFO[Control.GetLabel(2)]')
    x(3, '<control type="label" id="2" description="Kodi writes the add-on\'s name here"><left>-2000</left><top>0</top><width>10</width><height>10</height><font>povil_tiny</font></control>')
    x(3, '<control type="grouplist" id="3" description="Categories, on the right"><left>%d</left><top>%d</top><width>%d</width><height>%d</height>'
         '<itemgap>%d</itemgap><orientation>vertical</orientation><onleft>5</onleft><onright>5</onright><onup>8999</onup><ondown>8999</ondown></control>'
         % (CAT_LEFT, TOP, CAT_W, cats_h, GAP))
    category_button(x, 3)
    x(3, '<control type="grouplist" id="8999" description="OK, cancel, defaults"><left>%d</left><top>%d</top><width>%d</width><height>230</height>'
         '<itemgap>14</itemgap><orientation>vertical</orientation><onleft>5</onleft><onright>noop</onright><onup>3</onup><ondown>3</ondown>'
         % (CAT_LEFT, TOP + cats_h + 36, CAT_W))
    for bid, label in ((28, '$LOCALIZE[186]'), (29, '$LOCALIZE[222]'), (30, '$LOCALIZE[409]')):
        pill_button(x, 4, bid, CAT_W, label)
    x(3, '</control>')
    x(3, '<control type="grouplist" id="5" description="The settings"><left>%d</left><top>%d</top><width>%d</width><height>%d</height>'
         '<itemgap>%d</itemgap><orientation>vertical</orientation><pagecontrol>60</pagecontrol>'
         '<onleft>noop</onleft><onright>3</onright><onup>5</onup><ondown>5</ondown></control>' % (LIST_LEFT, TOP, LIST_W, list_h, GAP))
    templates(x, 3, LIST_W)
    scrollbar(x, 3, LIST_LEFT - 30, TOP, list_h, 5)
    x(3, '<control type="textbox" id="6" description="What the focused setting does"><left>%d</left><top>%d</top><width>%d</width><height>78</height>'
         '<font>povil_meta</font><textcolor>povil_dim</textcolor><align>right</align>'
         '<autoscroll time="3000" delay="4000" repeat="5000">true</autoscroll></control>' % (LIST_LEFT, TOP + list_h + 20, LIST_W))
    x(2, '</control>')
    x(1, '</controls>')
    x(0, '</window>')
    return x.text()


def variables():
    x = H.X()
    x(1, '<variable name="POVIL_SettingsHint">')
    for tile, sid, _col, _row, _cond in tile_slots():
        if tile[5]:
            x(2, '<value condition="Control.HasFocus(%d)">%s</value>' % (sid, tile[5]))
    x(1, '</variable>')
    return x.text()


def main():
    folder = os.path.join(sys.argv[1], 'xml')
    for name, body in (('Settings.xml', gen_home()), ('SettingsCategory.xml', gen_category()),
                       ('DialogSettings.xml', gen_dialog()), ('DialogAddonSettings.xml', gen_addon())):
        with open(os.path.join(folder, name), 'w', encoding='utf-8', newline=NL) as f:
            f.write(body)
    path = os.path.join(folder, 'Includes_POVIL_Home.xml')
    text_ = open(path, encoding='utf-8').read()
    begin, end = '<!-- POVIL SETTINGS BEGIN -->', '<!-- POVIL SETTINGS END -->'
    if begin in text_:
        text_ = text_[:text_.index(begin) - 1] + text_[text_.index(end) + len(end) + 1:]
    text_ = text_.replace('</includes>', '\t' + begin + NL + variables() + '\t' + end + NL + '</includes>')
    with open(path, 'w', encoding='utf-8', newline=NL) as f:
        f.write(text_)
    print('settings generated: home (%d tiles), category, dialog, add-on' % len(TILES))


if __name__ == '__main__':
    main()
