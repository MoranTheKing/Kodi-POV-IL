# -*- coding: utf-8 -*-
"""Generate the player of skin.povil.onyx: the on-screen controls (VideoOSD.xml),
the bar shown while seeking or paused (DialogSeekBar.xml) and the picture's own
window with its info panel (VideoFullScreen.xml).

    python gen_osd.py ../../skin.povil.onyx

Text and the build's actions read right to left (title and details top
right, subtitles first on the right); the timeline and the play controls
stay left to right, as in every player. The actions are the build's own:
MoranSubs subtitles, the Wizard's change source and next episode (they pick
POV or Umbrella), and Kodi's subtitle sync.

One timeline, drawn the same in all three windows, so the picture never
shows two players: the controls, then (when they close) nothing; a seek with
the controls closed shows the timeline alone.
"""
import os
import sys
from xml.sax.saxutils import escape

import gen_home as H

NL = chr(10)
WIZARD = 'plugin://plugin.program.kodipovilwizard/'
NOT_LIVE_SOURCE = ('!String.Contains(Player.Folderpath,plugin.video.idanplus) + !String.Contains(Player.Folderpath,plugin.video.supertv)'
                   ' + !String.Contains(Player.Folderpath,plugin.video.flashstream)')
ROW, TIMELINE = 7000, 7001
TIMELINE_TOP = 866
# (id, icon, Hebrew name, onclick list, visible) left to right; None = a gap between groups
BUTTONS = [
    (7010, 'stop', 'עצירה', ['PlayerControl(Stop)'], ''),
    # the controls close at once: Kodi drops an action sent while a dialog's closing animation runs
    (7011, 'info', 'מידע', ['Dialog.Close(VideoOSD,true)', 'Action(Info)'], ''),
    (7012, 'settings', 'הגדרות וידאו', ['ActivateWindow(OSDVideoSettings)'], ''),
    None,
    (7002, 'skipback', '10 שניות אחורה', ['Seek(-10)'], 'Player.SeekEnabled'),
    (7003, 'pause', 'ניגון / השהיה', ['PlayerControl(Play)'], 'Player.PauseEnabled'),
    (7004, 'skipfwd', '30 שניות קדימה', ['Seek(30)'], 'Player.SeekEnabled'),
    None,
    (7020, 'episodes', 'הפרק הבא', ['RunPlugin(%s?mode=player_episodes)' % WIZARD],
     'VideoPlayer.Content(episodes) + !VideoPlayer.Content(LiveTV)'),
    (7021, 'source', 'החלפת מקור', ['RunPlugin(%s?mode=player_change_source)' % WIZARD],
     '[VideoPlayer.Content(movies) | VideoPlayer.Content(episodes)] + !VideoPlayer.Content(LiveTV) + ' + NOT_LIVE_SOURCE),
    (7022, 'audio', 'שמע', ['ActivateWindow(OSDAudioSettings)'], ''),
    (7023, 'sync', 'סנכרון כתוביות', ['Dialog.Close(VideoOSD)', 'SubtitleDelay'], '!VideoPlayer.Content(LiveTV) | VideoPlayer.HasSubtitles'),
    (7024, 'subtitles', 'כתוביות', ['RunScript(service.subtitles.kodipovilai,action=choose_subs)'],
     '!VideoPlayer.Content(LiveTV) | VideoPlayer.HasSubtitles'),
]
TIMELINE_HINT = 'ימינה ושמאלה מדלגים · לחיצות רצופות מדלגות רחוק יותר · אישור משהה'
# Kodi's dialogs that sit over the picture: the bar and the info panel give way to them
OVER_PICTURE = ('Window.IsActive(sliderdialog) | Window.IsActive(pvrosdchannels) | Window.IsActive(pvrchannelguide) | '
                'Window.IsActive(videoosd) | Window.IsActive(playerprocessinfo) | Window.IsActive(osdvideosettings) | '
                'Window.IsActive(osdaudiosettings) | Window.IsActive(osdsubtitlesettings) | Window.IsActive(videobookmarks) | '
                'Window.IsActive(subtitlesearch)')
# The seek bar shows while a seek is being chosen or has just been made, for the
# first seconds of a pause, and while winding. A seek made from the controls does
# not bring it up when they close (field report: "another player under the player").
SEEKING = ('Player.Seeking | !String.IsEmpty(Player.SeekNumeric) | '
           '[Player.HasPerformedSeek(3) + !Skin.TimerIsRunning(povil_osd_closed)]')
PAUSED = '[Player.Paused + !Player.Caching + !Integer.IsGreaterOrEqual(Skin.TimerElapsedSecs(povil_pause),5)]'
WINDING = 'Player.Forwarding | Player.Rewinding'


def e(s):
    return escape(s)


# An 8-pixel-wide shade stretched over the screen fades out over its last half
# pixel (120 screen pixels) at both ends: it is drawn wider than the screen.


def title_block(x, depth):
    """Top right: the title's logo, or its name; the episode; year and genre."""
    right = 1920 - H.MARGIN
    x(depth, '<control type="image"><left>%d</left><top>54</top><width>560</width><height>150</height>'
             '<texture background="true">$VAR[POVIL_OSD_Logo]</texture><aspectratio align="right" aligny="bottom">keep</aspectratio></control>' % (right - 560))
    x(depth, '<control type="label" id="7901"><left>-2000</left><top>0</top><width>10</width><height>10</height><label>$VAR[POVIL_OSD_Logo]</label></control>')
    x(depth, '<control type="label"><left>%d</left><top>96</top><width>1200</width><height>108</height><font>povil_hero_small</font>'
             '<textcolor>povil_white</textcolor><align>right</align><aligny>bottom</aligny><label>$VAR[POVIL_OSD_Title]</label>'
             '<visible>String.IsEmpty(Control.GetLabel(7901))</visible></control>' % (right - 1200))
    x(depth, '<control type="label"><left>%d</left><top>214</top><width>1200</width><height>36</height><font>povil_meta_bold</font>'
             '<textcolor>povil_gold</textcolor><align>right</align><aligny>center</aligny><label>$VAR[POVIL_OSD_Episode]</label></control>' % (right - 1200))
    x(depth, '<control type="label"><left>%d</left><top>252</top><width>1200</width><height>36</height><font>povil_meta</font>'
             '<textcolor>povil_dim</textcolor><align>right</align><aligny>center</aligny>'
             '<label>$INFO[VideoPlayer.Year]$INFO[VideoPlayer.Genre,  •  ]</label></control>' % (right - 1200))


def timeline(x, depth, focusable):
    """The timeline, left to right: what is buffered, what was played, the place
    as a dot, the time on the left and the length on the right. In the controls
    it takes the focus (Up from the buttons): left and right then step as Kodi's
    own seek does -- 10 s, 30 s, and further with every press in a row -- and a
    finger or a mouse can drag the dot anywhere."""
    w = 1920 - 2 * H.MARGIN
    bar = '<lefttexture></lefttexture><righttexture></righttexture><overlaytexture></overlaytexture>'
    has_length = '!String.IsEmpty(Player.Duration)'
    x(depth, '<control type="group"><left>%d</left><top>%d</top>' % (H.MARGIN, TIMELINE_TOP))
    d = depth + 1
    x(d, '<visible>%s</visible>' % has_length)
    if focusable:
        x(d, '<control type="image"><left>-6</left><top>-5</top><width>%d</width><height>18</height>'
             '<texture border="4" colordiffuse="33FFFFFF">povil/progress.png</texture><visible>Control.HasFocus(%d)</visible></control>' % (w + 12, TIMELINE))
    x(d, '<control type="progress"><left>0</left><top>0</top><width>%d</width><height>8</height><info>Player.ProgressCache</info><reveal>false</reveal>%s'
         '<texturebg border="4" colordiffuse="33FFFFFF">povil/progress.png</texturebg>'
         '<midtexture border="4" colordiffuse="40FFFFFF">povil/progress.png</midtexture></control>' % (w, bar))
    x(d, '<control type="progress"><left>0</left><top>0</top><width>%d</width><height>8</height><info>Player.Progress</info><reveal>false</reveal>%s'
         '<texturebg border="4" colordiffuse="00FFFFFF">povil/progress.png</texturebg>'
         '<midtexture border="4" colordiffuse="FFD9B77E">povil/progress.png</midtexture></control>' % (w, bar))

    def dot(size, colour, info, visible, action=''):
        # a slider's dot is its picture scaled by the control's height over the bar
        # picture's height: the (unseen) bar uses the dot's own picture, so they match
        x(d, '<control type="slider"><left>%d</left><top>%d</top><width>%d</width><height>%d</height>'
             '<texturesliderbar colordiffuse="00FFFFFF">povil/pill.png</texturesliderbar>'
             '<textureslidernib colordiffuse="%s">povil/pill.png</textureslidernib>'
             '<textureslidernibfocus colordiffuse="povil_gold">povil/pill.png</textureslidernibfocus>'
             '<info>%s</info>%s<visible>%s</visible></control>'
             % (-size // 2, 4 - size // 2, w + size, size, colour, info, action, e(visible)))
    if focusable:
        # the place itself; a finger or a mouse drags it (a control with no id is never reached by the keys)
        dot(22, 'povil_white', 'Player.Progress', 'Player.SeekEnabled + !Control.HasFocus(%d)' % TIMELINE, '<action>seek</action>')
        # with the focus on the timeline: where the seek being chosen will land
        dot(30, 'povil_gold', 'Player.SeekBar', 'Player.SeekEnabled + Control.HasFocus(%d)' % TIMELINE)
        # the keys' own stop on the timeline: off the picture, so it never takes a finger's touch from the dot
        x(d, '<control type="button" id="%d"><left>-400</left><top>0</top><width>1</width><height>1</height>'
             '<texturefocus></texturefocus><texturenofocus></texturenofocus><label></label>'
             '<onleft>StepBack</onleft><onright>StepForward</onright><onup>%d</onup><ondown>%d</ondown>'
             '<onclick>PlayerControl(Play)</onclick><visible>Player.SeekEnabled</visible></control>' % (TIMELINE, ROW, ROW))
    else:
        dot(22, 'povil_gold', 'Player.SeekBar', 'Player.SeekEnabled')
    x(d, '<control type="label"><left>0</left><top>16</top><width>700</width><height>34</height><font>povil_meta</font>'
         '<textcolor>povil_white</textcolor><aligny>center</aligny><label>$VAR[POVIL_OSD_Time]</label></control>')
    x(d, '<control type="label"><left>%d</left><top>16</top><width>400</width><height>34</height><font>povil_meta</font>'
         '<textcolor>povil_dim</textcolor><align>right</align><aligny>center</aligny><label>$INFO[Player.Duration]</label></control>' % (w - 400))
    x(depth, '</control>')


def gen():
    x = H.X()
    right = 1920 - H.MARGIN
    x(0, '<?xml version="1.0" encoding="UTF-8"?>')
    x(0, '<!-- Generated by tools/skin_onyx/gen_osd.py. Do not edit by hand. -->')
    x(0, '<window>')
    x(1, '<defaultcontrol always="true">7003</defaultcontrol>')
    x(1, '<onload condition="!Player.PauseEnabled">SetFocus(7024)</onload>')
    # closing the controls right after a seek leaves the picture clean (see SEEKING)
    x(1, '<onunload>Skin.TimerStart(povil_osd_closed)</onunload>')
    x(1, '<zorder>2</zorder>')
    x(1, '<controls>')
    x(2, '<control type="group">')
    x(3, '<visible>Player.HasMedia</visible>')
    x(3, '<animation type="WindowOpen"><effect type="fade" start="0" end="100" time="220" /></animation>')
    x(3, '<animation type="WindowClose"><effect type="fade" start="100" end="0" time="180" /></animation>')
    x(3, '<animation effect="fade" start="100" end="0" time="160" condition="Window.IsVisible(sliderdialog) | Window.IsVisible(osdsubtitlesettings) | '
         'Window.IsVisible(osdvideosettings) | Window.IsVisible(osdaudiosettings) | Window.IsVisible(videobookmarks)">Conditional</animation>')
    x(3, '<control type="image"><left>-320</left><top>0</top><width>2560</width><height>330</height><texture>povil/grad_top.png</texture></control>')
    x(3, '<control type="image"><left>-320</left><top>520</top><width>2560</width><height>560</height><texture>povil/grad_bottom.png</texture></control>')
    title_block(x, 3)
    # Clock and end time
    x(3, '<control type="label"><left>%d</left><top>812</top><width>900</width><height>40</height><font>povil_meta</font>'
         '<textcolor>povil_dim</textcolor><align>right</align><aligny>center</aligny>'
         '<label>$INFO[System.Time]$INFO[Player.FinishTime,  •  מסתיים ב-]</label></control>' % (right - 900))
    timeline(x, 3, True)
    # Buttons
    w = 1920 - 2 * H.MARGIN
    x(3, '<control type="grouplist" id="%d"><left>%d</left><top>924</top><width>%d</width><height>96</height>' % (ROW, H.MARGIN, w))
    x(4, '<orientation>horizontal</orientation><align>center</align><itemgap>20</itemgap>')
    # The ends wrap round: an action no button takes falls through to the video
    # underneath, where left / right seek (field report: "it only skips 10 seconds")
    x(4, '<onleft>%d</onleft><onright>%d</onright>' % (ROW, ROW))
    # Up: the timeline (field report: "only 30-second jumps, no real seeking as in the other players")
    x(4, '<onup>%d</onup>' % TIMELINE)
    gaps = iter(range(7090, 7100))
    for b in BUTTONS:
        if b is None:
            # Kodi links a grouplist's items by their ids and passes over one that
            # cannot take the focus -- a gap without an id ended the chain there
            x(4, '<control type="image" id="%d"><width>56</width><height>96</height><texture></texture></control>' % next(gaps))
            continue
        bid, icon, name, clicks, vis = b
        kind = 'togglebutton' if icon == 'pause' else 'button'
        x(4, '<control type="%s" id="%d">' % (kind, bid))
        x(5, '<width>84</width><height>84</height><top>6</top>')
        x(5, '<texturenofocus colordiffuse="D9FFFFFF">povil/osd/%s.png</texturenofocus>' % icon)
        x(5, '<texturefocus>povil/osd/%s_fo.png</texturefocus>' % icon)
        if kind == 'togglebutton':
            x(5, '<alttexturenofocus colordiffuse="D9FFFFFF">povil/osd/play.png</alttexturenofocus>')
            x(5, '<alttexturefocus>povil/osd/play_fo.png</alttexturefocus>')
            x(5, '<usealttexture>Player.Paused | Player.Forwarding | Player.Rewinding</usealttexture>')
        x(5, '<label></label>')
        for c in clicks:
            x(5, '<onclick>%s</onclick>' % e(c))
            if kind == 'togglebutton':
                x(5, '<altclick>%s</altclick>' % e(c))
        if vis:
            x(5, '<visible>%s</visible>' % e(vis))
        x(4, '</control>')
    x(3, '</control>')
    x(3, '<control type="label"><left>%d</left><top>1022</top><width>%d</width><height>40</height><font>povil_small</font>'
         '<textcolor>povil_gold</textcolor><align>center</align><aligny>center</aligny><label>$VAR[POVIL_OSD_Focused]</label></control>' % (H.MARGIN, w))
    x(2, '</control>')
    x(1, '</controls>')
    x(0, '</window>')
    return x.text()


def state_line(x, depth, title=True):
    """Above the timeline: what is playing on the right (where no title block says it),
    what the player is doing on the left."""
    right = 1920 - H.MARGIN
    if title:
        x(depth, '<control type="label"><left>%d</left><top>812</top><width>1100</width><height>40</height><font>povil_meta</font>'
                 '<textcolor>povil_dim</textcolor><align>right</align><aligny>center</aligny>'
                 '<label>$VAR[POVIL_OSD_Title]$VAR[POVIL_OSD_Episode,  •  ]</label></control>' % (right - 1100))
    x(depth, '<control type="label"><left>%d</left><top>812</top><width>600</width><height>40</height><font>povil_meta_bold</font>'
             '<textcolor>povil_gold</textcolor><aligny>center</aligny><label>$VAR[POVIL_OSD_State]</label></control>' % H.MARGIN)


def gen_seekbar():
    x = H.X()
    x(0, '<?xml version="1.0" encoding="UTF-8"?>')
    x(0, '<!-- Generated by tools/skin_onyx/gen_osd.py. Do not edit by hand. -->')
    x(0, '<window type="dialog">')
    x(1, '<visible>%s | %s | %s | !String.IsEmpty(PVR.ChannelNumberInput)</visible>' % (e(SEEKING), e(PAUSED), WINDING))
    x(1, '<visible>![%s]</visible>' % OVER_PICTURE)
    # the info panel draws the same timeline itself
    x(1, '<visible>Window.IsActive(fullscreenvideo) + !Player.ShowInfo</visible>')
    x(1, '<animation effect="fade" start="0" end="100" time="200">Visible</animation>')
    x(1, '<animation effect="fade" start="100" end="0" time="200">Hidden</animation>')
    x(1, '<controls>')
    x(2, '<control type="label"><left>0</left><top>0</top><width>1920</width><height>1080</height><font>povil_hero</font>'
         '<textcolor>povil_gold</textcolor><shadowcolor>FF000000</shadowcolor><align>center</align><aligny>center</aligny>'
         '<label>$INFO[PVR.ChannelNumberInput]</label><visible>!String.IsEmpty(PVR.ChannelNumberInput)</visible></control>')
    x(2, '<control type="group">')
    x(3, '<visible>String.IsEmpty(PVR.ChannelNumberInput)</visible>')
    x(3, '<control type="image"><left>-320</left><top>640</top><width>2560</width><height>440</height><texture>povil/grad_bottom.png</texture></control>')
    state_line(x, 3)
    timeline(x, 3, False)
    x(2, '</control>')
    x(1, '</controls>')
    x(0, '</window>')
    return x.text()


def gen_fullscreen():
    """The picture's window. Its info panel (the Info key, or the controls' info
    button) is the controls' own look without the buttons: the title block, the
    plot under it, the file's picture and sound on the left, the timeline below."""
    x = H.X()
    right = 1920 - H.MARGIN
    x(0, '<?xml version="1.0" encoding="UTF-8"?>')
    x(0, '<!-- Generated by tools/skin_onyx/gen_osd.py. Do not edit by hand. -->')
    x(0, '<window>')
    x(1, '<include>AutoMuteBG</include>')
    x(1, '<defaultcontrol></defaultcontrol>')
    x(1, '<controls>')
    # Kodi writes its codec lines (the O key) into labels 10-12
    x(2, '<control type="group" id="0">')
    for cid, top in ((10, 15), (11, 45), (12, 75)):
        x(3, '<control type="label" id="%d"><left>45</left><top>%d</top><width>1770</width><height>100</height><label></label>'
             '<font>size14</font><shadowcolor>Shadow</shadowcolor></control>' % (cid, top))
    x(2, '</control>')
    x(2, '<control type="group" id="1">')
    x(3, '<visible>Player.ShowInfo + ![%s]</visible>' % OVER_PICTURE)
    x(3, '<animation effect="fade" start="0" end="100" time="200">Visible</animation>')
    x(3, '<animation effect="fade" start="100" end="0" time="160">Hidden</animation>')
    x(3, '<control type="image"><left>-320</left><top>0</top><width>2560</width><height>520</height><texture>povil/grad_top.png</texture></control>')
    x(3, '<control type="image"><left>-320</left><top>520</top><width>2560</width><height>560</height><texture>povil/grad_bottom.png</texture></control>')
    title_block(x, 3)
    x(3, '<control type="textbox"><left>%d</left><top>300</top><width>1000</width><height>148</height><font>povil_plot</font>'
         '<textcolor>povil_white</textcolor><shadowcolor>FF000000</shadowcolor><align>right</align>'
         '<label>$INFO[VideoPlayer.Plot]</label><autoscroll delay="6000" time="3000" repeat="6000">true</autoscroll></control>' % (right - 1000))
    # Clock, end time and the file itself, top left
    x(3, '<control type="label"><left>%d</left><top>54</top><width>500</width><height>56</height><font>povil_clock</font>'
         '<textcolor>povil_white</textcolor><aligny>center</aligny><label>$INFO[System.Time]</label></control>' % H.MARGIN)
    x(3, '<control type="label"><left>%d</left><top>112</top><width>600</width><height>36</height><font>povil_meta</font>'
         '<textcolor>povil_dim</textcolor><aligny>center</aligny><label>$INFO[Player.FinishTime,מסתיים ב-]</label>'
         '<visible>!String.IsEmpty(Player.Duration)</visible></control>' % H.MARGIN)
    x(3, '<control type="label"><left>%d</left><top>150</top><width>700</width><height>36</height><font>povil_meta</font>'
         '<textcolor>povil_gold</textcolor><aligny>center</aligny><label>$VAR[POVIL_OSD_File]</label></control>' % H.MARGIN)
    state_line(x, 3, title=False)
    timeline(x, 3, False)
    x(2, '</control>')
    # Buffering in the middle of the picture
    x(2, '<control type="group" id="1">')
    x(3, '<visible>Player.Caching</visible>')
    x(3, '<animation delay="300" effect="fade" time="200">Visible</animation>')
    x(3, '<animation effect="fade" delay="200" time="150">Hidden</animation>')
    x(3, '<left>912</left><top>492</top>')
    x(3, '<control type="image"><left>-36</left><top>-36</top><width>168</width><height>168</height>'
         '<texture colordiffuse="B3000000">povil/pill.png</texture></control>')
    x(3, '<control type="image"><left>0</left><top>0</top><width>96</width><height>96</height>'
         '<texture colordiffuse="26FFFFFF">povil/spinner_track.png</texture></control>')
    x(3, '<control type="image"><left>0</left><top>0</top><width>96</width><height>96</height>'
         '<texture colordiffuse="povil_gold">povil/spinner.png</texture>'
         '<animation effect="rotate" start="0" end="-360" center="48,48" time="900" loop="true" condition="true">Conditional</animation></control>')
    x(3, '<control type="label"><left>0</left><top>0</top><width>96</width><height>96</height><font>povil_badge</font>'
         '<textcolor>povil_white</textcolor><align>center</align><aligny>center</aligny><label>$INFO[Player.CacheLevel,,%]</label></control>')
    x(2, '</control>')
    x(1, '</controls>')
    x(0, '</window>')
    # Kodi hides "control 0" of this window whenever its view mode line is off, and a
    # control with no id is control 0: every control here carries an id
    import re
    return re.sub(r'<control type="([a-z]+)">', r'<control type="\1" id="1">', x.text())


def variables():
    x = H.X()
    x(1, '<variable name="POVIL_OSD_Logo">')
    x(2, '<value condition="!String.IsEmpty(Player.Art(povil_logo))">$INFO[Player.Art(povil_logo)]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_OSD_Title">')
    x(2, '<value condition="!String.IsEmpty(VideoPlayer.TVShowTitle)">$INFO[VideoPlayer.TVShowTitle]</value>')
    x(2, '<value condition="!String.IsEmpty(VideoPlayer.Title)">$INFO[VideoPlayer.Title]</value>')
    x(2, '<value>$INFO[Player.Title]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_OSD_Episode">')
    x(2, '<value condition="VideoPlayer.Content(episodes)">$INFO[VideoPlayer.Season,עונה , · ]$INFO[VideoPlayer.Episode,פרק ]$INFO[VideoPlayer.Title,  ·  ]</value>')
    x(2, '<value condition="VideoPlayer.HasEpg">$INFO[VideoPlayer.Title]</value>')
    x(1, '</variable>')
    # The time on the timeline's left: while a seek is being chosen, where it will land and by how much
    x(1, '<variable name="POVIL_OSD_Time">')
    x(2, '<value condition="Player.Seeking + !String.IsEmpty(Player.SeekStepSize)">$INFO[Player.SeekTime]   [COLOR povil_gold]$INFO[Player.SeekStepSize][/COLOR]</value>')
    x(2, '<value condition="!String.IsEmpty(Player.SeekNumeric)">$INFO[Player.SeekNumeric]</value>')
    # Kodi keeps the last seek's size for good: shown for the three seconds after it only
    x(2, '<value condition="Player.HasPerformedSeek(3) + !String.IsEmpty(Player.SeekOffset)">$INFO[Player.Time]   [COLOR povil_gold]$INFO[Player.SeekOffset][/COLOR]</value>')
    x(2, '<value>$INFO[Player.Time]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_OSD_State">')
    x(2, '<value condition="Player.Forwarding">הרצה קדימה ×$INFO[Player.PlaySpeed]</value>')
    x(2, '<value condition="Player.Rewinding">הרצה אחורה ×$INFO[Player.PlaySpeed]</value>')
    x(2, '<value condition="Player.Paused + Player.Caching">טוען...</value>')
    x(2, '<value condition="Player.Paused">מושהה</value>')
    x(1, '</variable>')
    # The file: picture height, picture and sound formats (the info panel)
    x(1, '<variable name="POVIL_OSD_File">')
    x(2, '<value>$INFO[VideoPlayer.VideoResolution,,p]$INFO[VideoPlayer.VideoCodec,  •  [UPPERCASE],[/UPPERCASE]]'
         '$INFO[VideoPlayer.HdrType,  •  [UPPERCASE],[/UPPERCASE]]$INFO[VideoPlayer.AudioCodec,  •  [UPPERCASE],[/UPPERCASE]]'
         '$VAR[POVIL_OSD_Channels, ]</value>')
    x(1, '</variable>')
    # Kodi counts the sound's channels (6); people know them by their layout (5.1)
    x(1, '<variable name="POVIL_OSD_Channels">')
    for count, name in (('1', 'מונו'), ('2', 'סטריאו'), ('3', '2.1'), ('4', '4.0'), ('5', '5.0'), ('6', '5.1'), ('7', '6.1'), ('8', '7.1'), ('10', '9.1')):
        x(2, '<value condition="String.IsEqual(VideoPlayer.AudioChannels,%s)">%s</value>' % (count, name))
    x(2, '<value>$INFO[VideoPlayer.AudioChannels]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_OSD_Focused">')
    x(2, '<value condition="Control.HasFocus(%d)">%s</value>' % (TIMELINE, e(TIMELINE_HINT)))
    for b in BUTTONS:
        if b:
            x(2, '<value condition="Control.HasFocus(%d)">%s</value>' % (b[0], e(b[2])))
    x(1, '</variable>')
    return x.text()


def timers():
    x = H.X()
    x(1, '<!-- POVIL OSD BEGIN: generated by tools/skin_onyx/gen_osd.py -->')
    # started by the controls as they close: for these seconds a seek just made does not bring the bar up
    x(1, '<timer>')
    x(2, '<name>povil_osd_closed</name>')
    x(2, '<stop>Integer.IsGreaterOrEqual(Skin.TimerElapsedSecs(povil_osd_closed),4) | !Player.HasMedia</stop>')
    x(1, '</timer>')
    # a pause shows the bar for its first seconds, then the picture is left clean
    x(1, '<timer>')
    x(2, '<name>povil_pause</name>')
    x(2, '<start reset="true">Player.Paused</start>')
    x(2, '<stop>!Player.Paused</stop>')
    x(1, '</timer>')
    x(1, '<!-- POVIL OSD END -->')
    return x.text()


def replace_block(path, begin, end, block, before):
    text = open(path, encoding='utf-8').read()
    if begin in text:
        start = text.rindex(NL, 0, text.index(begin)) + 1
        stop = text.index(NL, text.index(end)) + 1
        text = text[:start] + text[stop:]
    if before not in text:
        raise SystemExit('gen_osd: %s has no %s' % (os.path.basename(path), before))
    text = text.replace(before, block + before)
    with open(path, 'w', encoding='utf-8', newline=NL) as f:
        f.write(text)


def main():
    folder = os.path.join(sys.argv[1], 'xml')
    for name, text in (('VideoOSD.xml', gen()), ('DialogSeekBar.xml', gen_seekbar()), ('VideoFullScreen.xml', gen_fullscreen())):
        with open(os.path.join(folder, name), 'w', encoding='utf-8', newline=NL) as f:
            f.write(text)
    # The OSD variables live with the home's generated includes
    path = os.path.join(folder, 'Includes_POVIL_Home.xml')
    text = open(path, encoding='utf-8').read()
    begin, end = '<!-- POVIL OSD BEGIN -->', '<!-- POVIL OSD END -->'
    if begin in text:
        text = text[:text.index(begin)] + text[text.index(end) + len(end) + 1:]
    text = text.replace('</includes>', '\t' + begin + NL + variables() + '\t' + end + NL + '</includes>')
    with open(path, 'w', encoding='utf-8', newline=NL) as f:
        f.write(text)
    replace_block(os.path.join(folder, 'Timers.xml'), '<!-- POVIL OSD BEGIN', '<!-- POVIL OSD END -->', timers(), '</timers>')
    print('osd generated:', sum(1 for b in BUTTONS if b), 'buttons, seek bar, info panel')


if __name__ == '__main__':
    main()
