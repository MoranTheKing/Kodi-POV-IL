# -*- coding: utf-8 -*-
"""Generate the Kodi POV IL views of skin.povil.onyx (Videos window).

    python gen_views.py ../../skin.povil.onyx

View 51 (POV opens movies, TV shows and seasons in it) and view 55 (POV's
episodes view) become right-to-left showcases built like the home: the
focused item's fanart, its Hebrew logo or title, details and plot on the
right, and one row of posters or episode stills that starts on the right
(the add-on reverses the list, see patches/povil_rtl.py, and a timer starts
the row on its last item). Other windows keep Onyx's own views 51 and 55.
"""
import os
import sys

import gen_home as H

NL = chr(10)
MIN = " דק'"
VIEWS = {51: ('תצוגת יוקרה', 'view'), 55: ('תצוגת פרקים', 'episodes')}


def hero_vars(x):
    # Window title: the list's own name, else one built from what the list holds
    # (a list opened without a name shows only the add-on's name in FolderName)
    addon_names = ('POV', 'Umbrella', 'Idan Plus', 'idanplus')
    named = ' + '.join('!String.IsEqual(Container.FolderName,%s)' % n for n in addon_names)
    x(1, '<variable name="POVIL_V_Header">')
    x(2, '<value condition="Container.Content(episodes) + !String.IsEmpty(ListItem.TVShowTitle)">$INFO[ListItem.TVShowTitle]$INFO[ListItem.Season,  •  עונה ]</value>')
    x(2, '<value condition="Container.Content(seasons) + !String.IsEmpty(ListItem.TVShowTitle)">$INFO[ListItem.TVShowTitle]</value>')
    x(2, '<value condition="!String.IsEmpty(Container.FolderName) + %s">$INFO[Container.FolderName]</value>' % named)
    x(2, '<value condition="Container.Content(movies)">סרטים</value>')
    x(2, '<value condition="Container.Content(tvshows)">סדרות</value>')
    x(2, '<value>$INFO[Container.FolderName]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_V_Fanart">')
    for art in ('fanart', 'landscape', 'thumb'):
        x(2, '<value condition="!String.IsEmpty(ListItem.Art(%s)) + !Container.Content(addons) + ![String.Contains(ListItem.FolderPath,new_page=) | String.Contains(ListItem.FolderPath,Page&amp;url=)]">$INFO[ListItem.Art(%s)]</value>' % (art, art))
    x(1, '</variable>')
    x(1, '<variable name="POVIL_V_Title">')
    x(2, '<value condition="[String.Contains(ListItem.FolderPath,new_page=) | String.Contains(ListItem.FolderPath,Page&amp;url=)]">עוד תוצאות</value>')
    x(2, '<value condition="String.IsEqual(ListItem.DBType,episode) + Control.IsVisible(55)">$INFO[ListItem.Title]</value>')
    x(2, '<value condition="String.IsEqual(ListItem.DBType,episode)">$INFO[ListItem.TVShowTitle]</value>')
    x(2, '<value condition="!String.IsEmpty(ListItem.Title)">$INFO[ListItem.Title]</value>')
    x(2, '<value>$INFO[ListItem.Label]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_V_Logo">')
    x(2, '<value condition="!Control.IsVisible(55) | !String.IsEqual(ListItem.DBType,episode)">$INFO[ListItem.Art(povil_logo)]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_V_Episode">')
    x(2, '<value condition="String.IsEqual(ListItem.DBType,episode) + Control.IsVisible(55)">'
         '$INFO[ListItem.TVShowTitle,, · ]$INFO[ListItem.Season,עונה , · ]$INFO[ListItem.Episode,פרק ]</value>')
    x(2, '<value condition="String.IsEqual(ListItem.DBType,episode)">'
         '$INFO[ListItem.Season,עונה , · ]$INFO[ListItem.Episode,פרק ]$INFO[ListItem.Title,  ·  ]</value>')
    x(2, '<value condition="String.IsEqual(ListItem.DBType,season) + !String.IsEmpty(ListItem.TVShowTitle)">$INFO[ListItem.TVShowTitle]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_V_Meta">')
    x(2, '<value condition="String.IsEqual(ListItem.DBType,episode)">$INFO[ListItem.Premiered]$INFO[ListItem.Duration(mins),  •  ,%s]</value>' % MIN)
    x(2, '<value condition="!String.IsEmpty(ListItem.Year)">$INFO[ListItem.Year]$INFO[ListItem.Genre,  •  ]'
         '$INFO[ListItem.Duration(mins),  •  ,%s]$INFO[ListItem.MPAA,  •  ]</value>' % MIN)
    x(2, '<value>$INFO[ListItem.Genre]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_V_Rating">')
    x(2, '<value condition="Integer.IsGreater(ListItem.Rating,0)">$INFO[ListItem.Rating]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_V_Plot">')
    x(2, '<value condition="!String.IsEmpty(ListItem.Plot) + !String.IsEqual(ListItem.Plot,ListItem.Label)">$INFO[ListItem.Plot]</value>')
    x(2, '<value condition="!String.IsEmpty(ListItem.PlotOutline)">$INFO[ListItem.PlotOutline]</value>')
    x(1, '</variable>')


def view(x, vid, label, layout):
    right = 1920 - H.MARGIN
    x(1, '<include name="View_%d_POVIL">' % vid)
    x(2, '<control type="group" description="%s">' % label)
    x(3, '<visible>Control.IsVisible(%d)</visible>' % vid)
    x(3, '<control type="image"><left>0</left><top>0</top><width>1920</width><height>1080</height><texture>povil/ambient.jpg</texture></control>')
    x(3, '<control type="image"><left>0</left><top>0</top><width>1920</width><height>1080</height>'
         '<texture background="true">$VAR[POVIL_V_Fanart]</texture><aspectratio>scale</aspectratio><fadetime>420</fadetime></control>')
    for left, top, w, h, tex in ((520, 0, 1400, 1080, 'grad_right'), (0, 330, 1920, 750, 'grad_bottom'),
                                 (0, 0, 1920, 240, 'grad_top'), (0, 0, 1920, 1080, 'vignette')):
        x(3, '<control type="image"><left>%d</left><top>%d</top><width>%d</width><height>%d</height>'
             '<texture>povil/%s.png</texture></control>' % (left, top, w, h, tex))
    # Folder name (top right) and clock (top left)
    x(3, '<control type="label"><left>%d</left><top>34</top><width>1100</width><height>56</height><font>povil_menu</font>'
         '<textcolor>povil_white</textcolor><align>right</align><aligny>center</aligny>'
         '<label>$VAR[POVIL_V_Header]</label></control>' % (right - 1100))
    x(3, '<control type="image"><left>%d</left><top>92</top><width>44</width><height>4</height>'
         '<texture colordiffuse="povil_gold">povil/underline.png</texture></control>' % (right - 44))
    x(3, '<control type="label"><left>%d</left><top>30</top><width>400</width><height>52</height><font>povil_clock</font>'
         '<textcolor>povil_white</textcolor><aligny>center</aligny><label>$INFO[System.Time]</label></control>' % H.MARGIN)
    # Hero
    x(3, '<control type="image"><left>%d</left><top>138</top><width>620</width><height>176</height>'
         '<texture background="true">$VAR[POVIL_V_Logo]</texture>'
         '<aspectratio align="right" aligny="bottom">keep</aspectratio><fadetime>120</fadetime></control>' % (right - 620))
    x(3, '<control type="label" id="%d"><left>-2000</left><top>0</top><width>10</width><height>10</height>'
         '<label>$VAR[POVIL_V_Logo]</label></control>' % (vid * 100 + 1))
    x(3, '<control type="label"><left>%d</left><top>184</top><width>1100</width><height>130</height><font>povil_hero</font>'
         '<textcolor>povil_white</textcolor><align>right</align><aligny>bottom</aligny><label>$VAR[POVIL_V_Title]</label>'
         '<visible>String.IsEmpty(Control.GetLabel(%d))</visible></control>' % (right - 1100, vid * 100 + 1))
    x(3, '<control type="label"><left>%d</left><top>322</top><width>1100</width><height>34</height><font>povil_meta_bold</font>'
         '<textcolor>povil_gold</textcolor><align>right</align><aligny>center</aligny>'
         '<label>$VAR[POVIL_V_Episode]</label></control>' % (right - 1100))
    x(3, '<control type="grouplist"><left>%d</left><top>356</top><width>1100</width><height>40</height>'
         '<orientation>horizontal</orientation><align>right</align><itemgap>16</itemgap>'
         '<usecontrolcoords>true</usecontrolcoords>' % (right - 1100))
    x(4, '<control type="label"><width>auto</width><height>40</height><font>povil_meta</font><textcolor>povil_dim</textcolor>'
         '<aligny>center</aligny><label>$VAR[POVIL_V_Meta]</label></control>')
    x(4, '<control type="label"><width>auto</width><height>40</height><font>povil_meta_bold</font><textcolor>povil_gold</textcolor>'
         '<aligny>center</aligny><label>$VAR[POVIL_V_Rating]</label></control>')
    x(4, '<control type="image"><top>9</top><width>22</width><height>22</height><texture colordiffuse="povil_gold">povil/star.png</texture>'
         '<visible>Integer.IsGreater(ListItem.Rating,0)</visible></control>')
    x(3, '</control>')
    x(3, '<control type="textbox"><left>%d</left><top>402</top><width>860</width><height>152</height><font>povil_plot</font>'
         '<textcolor>povil_dim</textcolor><align>right</align><label>$VAR[POVIL_V_Plot]</label></control>' % (right - 860))
    # The row: right to left (reversed by the add-on), whole slots flush with the right margin
    g = H.GEOM['landscape' if layout == 'episodes' else 'poster']
    end = 1920 - H.MARGIN + (g['step'] - g['w'])
    slots = -(-end // g['step'])
    x(3, '<control type="list" id="%d">' % vid)
    x(4, '<left>%d</left><top>640</top><width>%d</width><height>380</height>' % (end - slots * g['step'], slots * g['step']))
    x(4, '<viewtype label="%s">wrap</viewtype>' % label)
    x(4, '<orientation>horizontal</orientation><preloaditems>2</preloaditems>')
    x(4, '<scrolltime tween="cubic" easing="out">260</scrolltime>')
    x(4, '<onup condition="!Skin.HasSetting(ViewOptions_Hide)">9000</onup>')
    x(4, '<ondown condition="!Skin.HasSetting(ViewOptions_Hide)">9000</ondown>')
    x(4, '<animation effect="fade" start="100" end="0" time="0" condition="%s">Conditional</animation>' % view_waiting(vid))
    if layout == 'episodes':
        x(4, '<include content="POVIL_ViewItem_episodes"><param name="id" value="%d" /></include>' % vid)
    else:
        for kind in ('poster', 'landscape', 'square'):
            x(4, '<include content="POVIL_ViewItem_%s"><param name="id" value="%d" /></include>' % (kind, vid))
    x(3, '</control>')
    x(2, '</control>')
    x(1, '</include>')


def view_waiting(vid):
    """A reversed list (marked by the add-on) that still sits on its first item."""
    # Kodi's own '..' item, when shown, is item 0 (CurrentItem 0): the list's items start at 1.
    return ('Control.IsVisible(%d) + !Container.IsUpdating + Integer.IsGreater(Container.NumItems,1)'
            ' + !Integer.IsGreater(Container.CurrentItem,1)'
            ' + [String.IsEqual(Container.ListItemAbsolute(0).Property(povil_rtl),1) | String.IsEqual(Container.ListItemAbsolute(1).Property(povil_rtl),1)]'
            ' + !String.IsEqual(Window(home).Property(povil.rtl.view),Container.FolderPath)') % vid


def gen():
    x = H.X()
    x(0, '<?xml version="1.0" encoding="UTF-8"?>')
    x(0, '<!-- Generated by tools/skin_onyx/gen_views.py. Do not edit by hand. -->')
    x(0, '<includes>')
    hero_vars(x)
    for vid, (label, layout) in VIEWS.items():
        view(x, vid, label, layout)
    x(0, '</includes>')
    return x.text()


def timers():
    x = H.X()
    x(1, '<!-- POVIL VIEWS BEGIN: generated by tools/skin_onyx/gen_views.py -->')
    for vid in VIEWS:
        x(1, '<timer>')
        x(2, '<name>povil_rtl_view_%d</name>' % vid)
        x(2, '<start reset="true">Window.IsActive(videos) + %s</start>' % view_waiting(vid))
        x(2, '<onstart>SetProperty(povil.rtl.view,"$INFO[Container.FolderPath]",home)</onstart>')
        x(2, '<onstart>Control.Move(%d,-1)</onstart>' % vid)
        x(2, '<stop>true</stop>')
        x(1, '</timer>')
    x(1, '<!-- POVIL VIEWS END -->')
    return x.text()


def replace_block(text, begin, end, block, before):
    if begin in text:
        start = text.rindex(NL, 0, text.index(begin)) + 1
        stop = text.index(NL, text.index(end)) + 1
        text = text[:start] + text[stop:]
    return text.replace(before, block + before, 1)


def wire(folder):
    """Include the views file and use the POVIL views 51 and 55 in the Videos window."""
    path = os.path.join(folder, 'Includes.xml')
    text = open(path, encoding='utf-8').read()
    line = '\t<include file="View_POVIL.xml" />' + NL
    if line not in text:
        anchor = '\t<include file="Includes_POVIL_Home.xml" />' + NL
        text = text.replace(anchor, anchor + line, 1)
        with open(path, 'w', encoding='utf-8', newline=NL) as f:
            f.write(text)
    path = os.path.join(folder, 'MyVideoNav.xml')
    text = open(path, encoding='utf-8').read()
    text = text.replace('<include condition="true">View_51</include>', '<include condition="true">View_51_POVIL</include>', 1)
    text = text.replace('<include condition="!Skin.HasSetting(Disable55)">View_55</include>', '<include condition="true">View_55_POVIL</include>', 1)
    with open(path, 'w', encoding='utf-8', newline=NL) as f:
        f.write(text)


def main():
    folder = os.path.join(sys.argv[1], 'xml')
    with open(os.path.join(folder, 'View_POVIL.xml'), 'w', encoding='utf-8', newline=NL) as f:
        f.write(gen())
    path = os.path.join(folder, 'Timers.xml')
    text = open(path, encoding='utf-8').read()
    text = replace_block(text, '<!-- POVIL VIEWS BEGIN', '<!-- POVIL VIEWS END -->', timers(), '</timers>')
    with open(path, 'w', encoding='utf-8', newline=NL) as f:
        f.write(text)
    wire(folder)
    print('views generated:', ', '.join(str(v) for v in VIEWS))


if __name__ == '__main__':
    main()
