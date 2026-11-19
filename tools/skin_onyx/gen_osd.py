# -*- coding: utf-8 -*-
"""Generate the player of skin.povil.onyx: the on-screen controls (VideoOSD.xml),
the bar shown while seeking or paused (DialogSeekBar.xml) and the picture's own
window with its info panel (VideoFullScreen.xml).

    python gen_osd.py ../../skin.povil.onyx

Text and the build's actions read right to left (title, details and ratings
top right, subtitles first on the right, what is playing as pills over the
controls); the timeline -- the lowest thing on the picture -- and the play
controls stay left to right, as in every player. The actions are the build's own:
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
import gen_osd_styles as S
import ratings_row as RR

NL = chr(10)
WIZARD = 'plugin://plugin.program.kodipovilwizard/'
NOT_LIVE_SOURCE = ('!String.Contains(Player.Folderpath,plugin.video.idanplus) + !String.Contains(Player.Folderpath,plugin.video.supertv)'
                   ' + !String.Contains(Player.Folderpath,plugin.video.flashstream)')
ROW, TIMELINE = 7000, 7001
LEFT_ROW, RIGHT_ROW = 7006, 7007
# The player, bottom up (the owner, Nov 2026: "the player looks uncomfortable, not useful and dated",
# "the source's pills at the bottom, a little above the player's bottom edge"): the timeline is the
# lowest thing on the picture with its two times under it; over it the buttons, three groups of
# glass chips with the main button in the middle of the screen; over them one line -- what is
# playing as pills on the right, the focused button's name on the left. The title, the details and
# the sites' ratings stay top right, the clock top left.
TIMELINE_TOP = 980
ROW_TOP, ROW_HEIGHT, CHIP, MAIN = 838, 124, 84, 108
LINE_TOP = 782                  # the controls' line: pills and the focused button's name
LOW_LINE_TOP = 918              # the same line where there are no buttons (seek bar, info panel)
LOGO_TOP, EPISODE_TOP, DETAILS_TOP, RATINGS_TOP, PLOT_TOP = 44, 188, 226, 272, 322
NO_EPISODE = -38                # a film has no episode line: what is under it moves up
# the picture between the title block (its ratings row ends at 304) and the controls' line: see gen()
TAP_CLOSE, TAP_TOP, TAP_BOTTOM = 7005, 320, 772
# What is playing, as pills, read right to left: the picture's size, its frame rate, its dynamic
# range, the sound, the video codec (the owner, with a photo of another player: "like this"), then
# where the stream comes from, in gold. A pill with nothing to say is not drawn. Listed left to
# right, so the first one here is the last read.
PILLS = ('POVIL_OSD_Codec', 'POVIL_OSD_Audio', 'POVIL_OSD_Hdr', 'POVIL_OSD_Fps', 'POVIL_OSD_Res')
PROVIDER_PILL = 'POVIL_OSD_Provider'
# (id, icon, Hebrew name, onclick list, visible), each group left to right
LEFT_BUTTONS = [
    # the other players (gen_osd_styles.py; the Wizard asks which): the farthest from the middle, the least wanted
    (7013, 'layout', 'החלפת נגן', [S.SWITCH], ''),
    (7010, 'stop', 'עצירה', ['PlayerControl(Stop)'], ''),
    # the controls close at once: Kodi drops an action sent while a dialog's closing animation runs
    (7011, 'info', 'מידע', ['Dialog.Close(VideoOSD,true)', 'Action(Info)'], ''),
    (7012, 'settings', 'הגדרות וידאו', ['ActivateWindow(OSDVideoSettings)'], ''),
]
MAIN_BUTTONS = [
    (7002, 'skipback', '10 שניות אחורה', ['Seek(-10)'], 'Player.SeekEnabled'),
    (7003, 'pause', 'ניגון / השהיה', ['PlayerControl(Play)'], 'Player.PauseEnabled'),
    (7004, 'skipfwd', '30 שניות קדימה', ['Seek(30)'], 'Player.SeekEnabled'),
]
# Outward from the middle by how often a button is wanted (the owner, Nov 2026: "the subtitles button
# closer -- it is an important one, and it took too many presses to reach"): subtitles are two presses
# from the main button, the next episode three.
RIGHT_BUTTONS = [
    (7024, 'subtitles', 'כתוביות', ['RunScript(service.subtitles.kodipovilai,action=choose_subs)'],
     '!VideoPlayer.Content(LiveTV) | VideoPlayer.HasSubtitles'),
    (7020, 'episodes', 'הפרק הבא', ['RunPlugin(%s?mode=player_episodes)' % WIZARD],
     'VideoPlayer.Content(episodes) + !VideoPlayer.Content(LiveTV)'),
    (7021, 'source', 'החלפת מקור', ['RunPlugin(%s?mode=player_change_source)' % WIZARD],
     '[VideoPlayer.Content(movies) | VideoPlayer.Content(episodes)] + !VideoPlayer.Content(LiveTV) + ' + NOT_LIVE_SOURCE),
    (7022, 'audio', 'שמע', ['ActivateWindow(OSDAudioSettings)'], ''),
    (7023, 'sync', 'סנכרון כתוביות', S.SYNC, '!VideoPlayer.Content(LiveTV) | VideoPlayer.HasSubtitles'),
    # Where the subtitles sit (the owner, with a photo of a wide film: the lines fell half on the picture
    # and half on the black bar, and Onyx offered nothing to move them). The controls stay open: a press
    # is a step, and the next one follows it.
    (7025, 'subdown', 'כתוביות למטה', ['RunPlugin(%s?mode=player_subs_position&step=down)' % WIZARD], 'VideoPlayer.HasSubtitles'),
    (7026, 'subup', 'כתוביות למעלה', ['RunPlugin(%s?mode=player_subs_position&step=up)' % WIZARD], 'VideoPlayer.HasSubtitles'),
]
BUTTONS = LEFT_BUTTONS + MAIN_BUTTONS + RIGHT_BUTTONS
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


def title_block(x, depth, below=None):
    """Top right: the title's logo, or its name; the episode; year and genre; what the sites say.
    `below` draws what follows the block (the info panel's plot), so it moves with it."""
    right = 1920 - H.MARGIN
    x(depth, '<control type="image"><left>%d</left><top>%d</top><width>520</width><height>132</height>'
             '<texture background="true">$VAR[POVIL_OSD_Logo]</texture><aspectratio align="right" aligny="bottom">keep</aspectratio></control>'
             % (right - 520, LOGO_TOP))
    x(depth, '<control type="label" id="7901"><left>-2000</left><top>0</top><width>10</width><height>10</height><label>$VAR[POVIL_OSD_Logo]</label></control>')
    x(depth, '<control type="label" id="7902"><left>-2000</left><top>0</top><width>10</width><height>10</height><label>$VAR[POVIL_OSD_Episode]</label></control>')
    x(depth, '<control type="label"><left>%d</left><top>%d</top><width>1200</width><height>108</height><font>povil_hero_small</font>'
             '<textcolor>povil_white</textcolor><shadowcolor>B3000000</shadowcolor><align>right</align><aligny>bottom</aligny><label>$VAR[POVIL_OSD_Title]</label>'
             '<visible>String.IsEmpty(Control.GetLabel(7901))</visible></control>' % (right - 1200, LOGO_TOP + 24))
    x(depth, '<control type="label"><left>%d</left><top>%d</top><width>1200</width><height>36</height><font>povil_meta_bold</font>'
             '<textcolor>povil_gold</textcolor><shadowcolor>B3000000</shadowcolor><align>right</align><aligny>center</aligny>'
             '<label>$VAR[POVIL_OSD_Episode]</label></control>' % (right - 1200, EPISODE_TOP))
    x(depth, '<control type="group" description="under the episode line">')
    x(depth + 1, '<animation effect="slide" end="0,%d" time="0" condition="String.IsEmpty(Control.GetLabel(7902))">Conditional</animation>' % NO_EPISODE)
    x(depth + 1, '<control type="label"><left>%d</left><top>%d</top><width>1200</width><height>36</height><font>povil_meta</font>'
                 '<textcolor>povil_dim</textcolor><shadowcolor>B3000000</shadowcolor><align>right</align><aligny>center</aligny>'
                 '<label>$INFO[VideoPlayer.Year]$INFO[VideoPlayer.Genre,  •  ]</label></control>' % (right - 1200, DETAILS_TOP))
    # What the sites say about what is playing (ratings_row.py): its own key and its own answer,
    # apart from the title the home has in its hero
    RR.key_label(x, depth + 1, H.PLAYER_RATINGS_KEY, '$VAR[POVIL_OSD_RatingsKey]')
    RR.row(x, depth + 1, right, RATINGS_TOP, H.PLAYER_RATINGS_KEY, H.PLAYER_RATINGS_SLOT, 'POVIL_OSD_RatingsTmdb', width=1200)
    if below:
        below(x, depth + 1)
    x(depth, '</control>')


def clock_block(x, depth):
    """Top left: the time, and when what is playing ends."""
    x(depth, '<control type="label"><left>%d</left><top>44</top><width>500</width><height>56</height><font>povil_clock</font>'
             '<textcolor>povil_white</textcolor><shadowcolor>B3000000</shadowcolor><aligny>center</aligny><label>$INFO[System.Time]</label></control>' % H.MARGIN)
    x(depth, '<control type="label"><left>%d</left><top>100</top><width>600</width><height>34</height><font>povil_small</font>'
             '<textcolor>povil_dim</textcolor><shadowcolor>B3000000</shadowcolor><aligny>center</aligny><label>$INFO[Player.FinishTime,מסתיים ב-]</label>'
             '<visible>!String.IsEmpty(Player.Duration)</visible></control>' % H.MARGIN)


def pills_row(x, depth, top, base=7910):
    """What is playing, as pills on the right of the line over the controls. `base`: the ids of the hidden
    labels that say whether a pill has anything to show (another player draws the row with ids of its own)."""
    right = 1920 - H.MARGIN
    names = (PROVIDER_PILL,) + PILLS
    x(depth, '<control type="grouplist" description="what is playing"><left>%d</left><top>%d</top><width>1200</width><height>42</height>'
             '<orientation>horizontal</orientation><align>right</align><itemgap>10</itemgap>' % (right - 1200, top))
    for name in names:
        fill, ink = ('3DD9B77E', 'povil_gold') if name == PROVIDER_PILL else ('30FFFFFF', 'povil_white')
        # a button that cannot take the focus: the one control that sizes itself to its text over a texture
        x(depth + 1, '<control type="button"><width>auto</width><height>42</height><font>povil_chip</font>'
                     '<textcolor>%s</textcolor><disabledcolor>%s</disabledcolor><align>center</align><aligny>center</aligny>'
                     '<textoffsetx>18</textoffsetx><texturenofocus border="24" colordiffuse="%s">povil/pill48.png</texturenofocus>'
                     '<texturefocus border="24" colordiffuse="%s">povil/pill48.png</texturefocus>'
                     '<label>$VAR[%s]</label><enable>false</enable><visible>!String.IsEmpty(Control.GetLabel(%d))</visible></control>'
                     % (ink, ink, fill, fill, name, base + names.index(name)))
    x(depth, '</control>')
    for name in names:
        # a variable cannot be tested for being empty; a label off the screen can
        x(depth, '<control type="label" id="%d"><left>-2000</left><top>0</top><width>10</width><height>10</height>'
                 '<label>$VAR[%s]</label></control>' % (base + names.index(name), name))


def timeline(x, depth, focusable):
    """The timeline, left to right, the lowest thing on the picture: what is buffered, what was
    played, the place as a dot; under it the time on the left and the length on the right. In the
    controls it takes the focus (Down from the buttons): left and right then step as Kodi's own
    seek does -- 10 s, 30 s, and further with every press in a row -- and a finger or a mouse
    can drag the dot anywhere."""
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
         '<texturebg border="4" colordiffuse="38FFFFFF">povil/progress.png</texturebg>'
         '<midtexture border="4" colordiffuse="47FFFFFF">povil/progress.png</midtexture></control>' % (w, bar))
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
        # the keys' own stop on the timeline: off the picture, so it never takes a finger's touch from the dot.
        # Down stays here: a key no control takes falls through to the picture, where it seeks
        x(d, '<control type="button" id="%d"><left>-400</left><top>0</top><width>1</width><height>1</height>'
             '<texturefocus></texturefocus><texturenofocus></texturenofocus><label></label>'
             '<onleft>StepBack</onleft><onright>StepForward</onright><onup>%d</onup><ondown>noop</ondown>'
             '<onclick>PlayerControl(Play)</onclick><visible>Player.SeekEnabled</visible></control>' % (TIMELINE, ROW))
    else:
        dot(22, 'povil_gold', 'Player.SeekBar', 'Player.SeekEnabled')
    x(d, '<control type="label"><left>0</left><top>18</top><width>700</width><height>34</height><font>povil_meta_bold</font>'
         '<textcolor>povil_white</textcolor><aligny>center</aligny><label>$VAR[POVIL_OSD_Time]</label></control>')
    x(d, '<control type="label"><left>%d</left><top>18</top><width>400</width><height>34</height><font>povil_meta</font>'
         '<textcolor>povil_dim</textcolor><align>right</align><aligny>center</aligny><label>$INFO[Player.Duration]</label></control>' % (w - 400))
    x(depth, '</control>')


def first_shown(buttons, fallback):
    """(condition, id) pairs: the first of `buttons` that is on the screen, else `fallback`."""
    targets = []
    for bid, _icon, _name, _clicks, vis in buttons:
        targets.append((vis, bid))
        if not vis:
            return targets          # always on the screen: nothing after it is ever needed
    return targets + [('', fallback)]


def button_group(x, depth, gid, buttons, left, width, align, onleft, onright, gaps):
    """One group of the player's buttons: glass chips, the focused one a gold disc a size up."""
    x(depth, '<control type="grouplist" id="%d"><left>%d</left><top>%d</top><width>%d</width><height>%d</height>'
             % (gid, left, ROW_TOP, width, ROW_HEIGHT))
    d = depth + 1
    x(d, '<orientation>horizontal</orientation><align>%s</align><itemgap>14</itemgap><usecontrolcoords>true</usecontrolcoords>' % align)
    # A key no control takes falls through to the picture underneath, where the arrows
    # seek (field report: "it only skips 10 seconds"): every side leads somewhere, or stays
    # (an end that led to the group itself would make Kodi wrap the group round: "noop" takes the key and stays)
    for tag, targets in (('onleft', onleft), ('onright', onright)):
        for condition, target in targets:
            x(d, '<%s%s>%s</%s>' % (tag, ' condition="%s"' % e(condition) if condition else '', target, tag))
    # Down: the timeline (field report: "only 30-second jumps, no real seeking as in the other players")
    x(d, '<onup>noop</onup><ondown condition="Player.SeekEnabled">%d</ondown><ondown>noop</ondown>' % TIMELINE)
    # the focused chip grows past its place: a little room at both ends, or the group's edge cuts it.
    # (Kodi links a grouplist's items by their ids and passes over one that cannot take the focus --
    # an item without an id ended the chain there)
    x(d, '<control type="image" id="%d"><width>10</width><height>%d</height><texture></texture></control>' % (next(gaps), ROW_HEIGHT))
    for bid, icon, _name, clicks, vis in buttons:
        main = icon == 'pause'
        kind = 'togglebutton' if main else 'button'
        size = MAIN if main else CHIP
        rest = '_hi' if main else '_nf'
        grown = 108 if main else 112
        x(d, '<control type="%s" id="%d">' % (kind, bid))
        x(d + 1, '<width>%d</width><height>%d</height><top>%d</top>' % (size, size, (ROW_HEIGHT - size) // 2))
        x(d + 1, '<texturenofocus>povil/osd/%s%s.png</texturenofocus>' % (icon, rest))
        x(d + 1, '<texturefocus>povil/osd/%s_fo.png</texturefocus>' % icon)
        if main:
            x(d + 1, '<alttexturenofocus>povil/osd/play_hi.png</alttexturenofocus>')
            x(d + 1, '<alttexturefocus>povil/osd/play_fo.png</alttexturefocus>')
            x(d + 1, '<usealttexture>Player.Paused | Player.Forwarding | Player.Rewinding</usealttexture>')
        x(d + 1, '<label></label>')
        x(d + 1, '<animation effect="zoom" start="100" end="%d" center="auto" time="130" tween="cubic" easing="out">Focus</animation>' % grown)
        x(d + 1, '<animation effect="zoom" start="%d" end="100" center="auto" time="130" tween="cubic" easing="out">Unfocus</animation>' % grown)
        for c in clicks:
            x(d + 1, '<onclick>%s</onclick>' % e(c))
            if main:
                x(d + 1, '<altclick>%s</altclick>' % e(c))
        if vis:
            x(d + 1, '<visible>%s</visible>' % e(vis))
        x(d, '</control>')
    x(d, '<control type="image" id="%d"><width>10</width><height>%d</height><texture></texture></control>' % (next(gaps), ROW_HEIGHT))
    x(depth, '</control>')


def gen():
    x = H.X()
    right = 1920 - H.MARGIN
    x(0, '<?xml version="1.0" encoding="UTF-8"?>')
    x(0, '<!-- Generated by tools/skin_onyx/gen_osd.py. Do not edit by hand. -->')
    x(0, '<window>')
    x(1, '<defaultcontrol always="true">7003</defaultcontrol>')
    onyx = S.onyx_shown()
    x(1, '<onload condition="%s + !Player.PauseEnabled">SetFocus(7024)</onload>' % onyx)
    # (a live channel that cannot pause and has no subtitles shows neither: the sound button is always there)
    x(1, '<onload condition="%s + !Player.PauseEnabled + !Control.IsVisible(7024)">SetFocus(7022)</onload>' % onyx)
    # the other players open on their own main button (gen_osd_styles.py)
    S.onloads(x, 1)
    # closing the controls right after a seek leaves the picture clean (see SEEKING)
    x(1, '<onunload>Skin.TimerStart(povil_osd_closed)</onunload>')
    x(1, '<zorder>2</zorder>')
    x(1, '<controls>')
    x(2, '<control type="group" description="the Onyx player">')
    x(3, '<visible>Player.HasMedia + %s</visible>' % onyx)
    x(3, '<animation type="WindowOpen"><effect type="fade" start="0" end="100" time="220" /></animation>')
    x(3, '<animation type="WindowClose"><effect type="fade" start="100" end="0" time="180" /></animation>')
    x(3, '<animation effect="fade" start="100" end="0" time="160" condition="Window.IsVisible(sliderdialog) | Window.IsVisible(osdsubtitlesettings) | '
         'Window.IsVisible(osdvideosettings) | Window.IsVisible(osdaudiosettings) | Window.IsVisible(videobookmarks)">Conditional</animation>')
    x(3, '<control type="image"><left>-320</left><top>0</top><width>2560</width><height>360</height><texture>povil/grad_top.png</texture></control>')
    x(3, '<control type="image"><left>-320</left><top>440</top><width>2560</width><height>640</height><texture>povil/grad_bottom.png</texture></control>')
    # A tap (or a click) on the picture between the title and the controls closes them
    # (the owner, on a phone: "if I press the middle while the player is open, it should
    # close"). Kodi only ever opens the controls from a click on the picture. The first
    # control, so every button drawn after it takes its own taps; no key leads here,
    # and any arrow from it goes back to the buttons.
    x(3, '<control type="button" id="%d"><left>0</left><top>%d</top><width>1920</width><height>%d</height>'
         '<texturefocus></texturefocus><texturenofocus></texturenofocus><label></label>'
         '<onclick>Dialog.Close(VideoOSD)</onclick>%s</control>'
         % (TAP_CLOSE, TAP_TOP, TAP_BOTTOM - TAP_TOP,
            # back to the main buttons, or -- where there are none (a channel that cannot pause) -- to
            # the right group, whose sound button is always on the screen
            ''.join('<%s condition="Player.PauseEnabled">%d</%s><%s>%d</%s>' % (tag, ROW, tag, tag, RIGHT_ROW, tag)
                    for tag in ('onup', 'ondown', 'onleft', 'onright'))))
    title_block(x, 3)
    clock_block(x, 3)
    # The controls' line: what is playing on the right, the focused button's name on the left
    pills_row(x, 3, LINE_TOP)
    x(3, '<control type="label"><left>%d</left><top>%d</top><width>1080</width><height>42</height><font>povil_meta_bold</font>'
         '<textcolor>povil_gold</textcolor><shadowcolor>B3000000</shadowcolor><aligny>center</aligny><label>$VAR[POVIL_OSD_Focused]</label></control>'
         % (H.MARGIN, LINE_TOP))
    # The buttons: three groups, the main one in the middle of the screen. Each side of a group leads
    # to the button beside it in the next group that is on the screen (some are not, for live TV).
    gaps = iter(range(7090, 7100))
    pad = 10 + 14           # the room at a group's end and the gap after it: the chips line up with the timeline's ends
    settings = LEFT_BUTTONS[-1][0]
    button_group(x, 3, LEFT_ROW, LEFT_BUTTONS, H.MARGIN - pad, 520, 'left',
                 [('', 'noop')], first_shown(MAIN_BUTTONS, 0)[:-1] + first_shown(RIGHT_BUTTONS, RIGHT_ROW), gaps)
    button_group(x, 3, ROW, MAIN_BUTTONS, 960 - 240, 480, 'center',
                 [('', settings)], first_shown(RIGHT_BUTTONS, RIGHT_ROW), gaps)
    button_group(x, 3, RIGHT_ROW, RIGHT_BUTTONS, right - 800 + pad, 800, 'right',
                 first_shown(list(reversed(MAIN_BUTTONS)), 0)[:-1] + [('', settings)], [('', 'noop')], gaps)
    timeline(x, 3, True)
    x(2, '</control>')
    # the other players, one group each for the viewer's choice
    S.add(x, 2, pills_row)
    x(1, '</controls>')
    x(0, '</window>')
    return x.text()


def state_line(x, depth, title=True, top=LOW_LINE_TOP):
    """Over the timeline where there are no buttons: what is playing on the right (where no title
    block says it), what the player is doing on the left."""
    right = 1920 - H.MARGIN
    if title:
        x(depth, '<control type="label"><left>%d</left><top>%d</top><width>1100</width><height>42</height><font>povil_meta</font>'
                 '<textcolor>povil_dim</textcolor><shadowcolor>B3000000</shadowcolor><align>right</align><aligny>center</aligny>'
                 '<label>$VAR[POVIL_OSD_Title]$VAR[POVIL_OSD_Episode,  •  ]</label></control>' % (right - 1100, top))
    x(depth, '<control type="label"><left>%d</left><top>%d</top><width>600</width><height>42</height><font>povil_meta_bold</font>'
             '<textcolor>povil_gold</textcolor><shadowcolor>B3000000</shadowcolor><aligny>center</aligny><label>$VAR[POVIL_OSD_State]</label></control>' % (H.MARGIN, top))


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
    x(3, '<control type="image"><left>-320</left><top>720</top><width>2560</width><height>360</height><texture>povil/grad_bottom.png</texture></control>')
    state_line(x, 3)
    timeline(x, 3, False)
    x(2, '</control>')
    x(1, '</controls>')
    x(0, '</window>')
    return x.text()


def gen_fullscreen():
    """The picture's window. Its info panel (the Info key, or the controls' info
    button) is the controls' own look without the buttons: the title block with the
    plot under it, the clock, the pills over the timeline."""
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
    x(3, '<control type="image"><left>-320</left><top>0</top><width>2560</width><height>560</height><texture>povil/grad_top.png</texture></control>')
    x(3, '<control type="image"><left>-320</left><top>520</top><width>2560</width><height>560</height><texture>povil/grad_bottom.png</texture></control>')

    def plot(x, depth):
        # under the ratings row (it ends at 304); inside the block, so a film's plot moves up with it
        x(depth, '<control type="textbox"><left>%d</left><top>%d</top><width>1000</width><height>111</height><font>povil_plot</font>'
                 '<textcolor>povil_white</textcolor><shadowcolor>FF000000</shadowcolor><align>right</align>'
                 '<label>$INFO[VideoPlayer.Plot]</label><autoscroll delay="6000" time="3000" repeat="6000">true</autoscroll></control>'
                 % (right - 1000, PLOT_TOP))
    title_block(x, 3, below=plot)
    clock_block(x, 3)
    # (the line that named the file's formats here -- "4Kp - HEVC - DOLBYVISION" -- is gone: the pills say it)
    pills_row(x, 3, LOW_LINE_TOP)
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
    return re.sub(r'<control type="([a-z]+)"( description="[^"]*")?>', r'<control type="\1" id="1"\2>', x.text())


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
    # The ratings row: what is playing, named for the Wizard (a film, or one episode of a show by its
    # show's id); never for live TV or an Israeli stream
    x(1, '<variable name="POVIL_OSD_RatingsKey">')
    for item in ('VideoPlayer.UniqueID(imdb)', 'VideoPlayer.IMDBNumber'):
        x(2, '<value condition="String.StartsWith(%s,tt) + VideoPlayer.Content(episodes) + !VideoPlayer.Content(LiveTV) + %s">'
             '$INFO[%s]|episode|$INFO[VideoPlayer.Season]|$INFO[VideoPlayer.Episode]</value>' % (item, NOT_LIVE_SOURCE, item))
        x(2, '<value condition="String.StartsWith(%s,tt) + VideoPlayer.Content(movies) + !VideoPlayer.Content(LiveTV) + %s">'
             '$INFO[%s]|movie||</value>' % (item, NOT_LIVE_SOURCE, item))
    x(1, '</variable>')
    x(1, '<variable name="POVIL_OSD_ListRating">')
    x(2, '<value condition="Integer.IsGreater(VideoPlayer.Rating,0)">$INFO[VideoPlayer.Rating]</value>')
    x(1, '</variable>')
    RR.tmdb_variable(x, 'POVIL_OSD_RatingsTmdb', H.PLAYER_RATINGS_KEY, H.PLAYER_RATINGS_SLOT, '$VAR[POVIL_OSD_ListRating]')
    # The pills. Kodi names what the decoder reports; the pills say it the way a box's own player does.
    x(1, '<variable name="POVIL_OSD_Res">')
    for value, text in (('8K', '8K'), ('4K', '4K'), ('1080', '1080p'), ('720', '720p'), ('576', '576p'), ('540', '540p'), ('480', '480p')):
        x(2, '<value condition="String.IsEqual(VideoPlayer.VideoResolution,%s)">%s</value>' % (value, text))
    x(1, '</variable>')
    x(1, '<variable name="POVIL_OSD_Fps">')
    # Kodi prints three decimals: 25.000 is said as 25, and 23.976 stays as it is
    for value, text in (('24.000', '24'), ('25.000', '25'), ('30.000', '30'), ('48.000', '48'), ('50.000', '50'),
                        ('60.000', '60'), ('120.000', '120'), ('29.970', '29.97'), ('59.940', '59.94')):
        x(2, '<value condition="String.IsEqual(Player.Process(videofps),%s)">%s fps</value>' % (value, text))
    x(2, '<value condition="!String.IsEmpty(Player.Process(videofps)) + !String.IsEqual(Player.Process(videofps),0.000)">$INFO[Player.Process(videofps)] fps</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_OSD_Hdr">')
    for value, text in (('dolbyvision', 'Dolby Vision'), ('hdr10plus', 'HDR10+'), ('hdr10', 'HDR10'), ('hlg', 'HLG')):
        x(2, '<value condition="String.IsEqual(VideoPlayer.HdrType,%s)">%s</value>' % (value, text))
    # a kind Kodi names in a way this list does not know is still HDR
    x(2, '<value condition="!String.IsEmpty(VideoPlayer.HdrType)">HDR</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_OSD_AudioCodec">')
    for value, text in (('eac3_ddp_atmos', 'DD+ Atmos'), ('truehd_atmos', 'TrueHD Atmos'), ('eac3', 'DD+'), ('ac3', 'DD'),
                        ('truehd', 'TrueHD'), ('dtshd_ma_x_imax', 'DTS:X'), ('dtshd_ma_x', 'DTS:X'),
                        ('dtshd_ma', 'DTS-HD MA'), ('dtshd_hra', 'DTS-HD'),
                        ('dca', 'DTS'), ('dts', 'DTS'), ('aac_latm', 'AAC'), ('aac', 'AAC'), ('flac', 'FLAC'), ('opus', 'Opus'),
                        ('mp3', 'MP3'), ('mp2', 'MP2'), ('vorbis', 'Vorbis')):
        x(2, '<value condition="String.IsEqual(VideoPlayer.AudioCodec,%s)">%s</value>' % (value, text))
    # pcm_s16le, pcm_s24le, pcm_bluray ...
    x(2, '<value condition="String.StartsWith(VideoPlayer.AudioCodec,pcm)">PCM</value>')
    x(2, '<value>$INFO[VideoPlayer.AudioCodec]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_OSD_Audio">')
    for value, text in (('8', '7.1'), ('7', '6.1'), ('6', '5.1'), ('3', '2.1'), ('2', '2.0'), ('1', '1.0')):
        x(2, '<value condition="!String.IsEmpty(VideoPlayer.AudioCodec) + String.IsEqual(VideoPlayer.AudioChannels,%s)">$VAR[POVIL_OSD_AudioCodec] %s</value>' % (value, text))
    x(2, '<value condition="!String.IsEmpty(VideoPlayer.AudioCodec)">$VAR[POVIL_OSD_AudioCodec]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_OSD_Codec">')
    for value, text in (('hevc', 'HEVC'), ('h265', 'HEVC'), ('hvc1', 'HEVC'), ('hev1', 'HEVC'), ('dvh1', 'HEVC'),
                        ('dvhe', 'HEVC'), ('h264', 'H.264'), ('avc1', 'H.264'), ('av1', 'AV1'), ('vp9', 'VP9'),
                        ('mpeg2video', 'MPEG-2'), ('mpeg4', 'MPEG-4'), ('vc1', 'VC-1'), ('wvc1', 'VC-1')):
        x(2, '<value condition="String.IsEqual(VideoPlayer.VideoCodec,%s)">%s</value>' % (value, text))
    x(2, '<value>$INFO[VideoPlayer.VideoCodec]</value>')
    x(1, '</variable>')
    # Where the stream comes from (TorBox, Real-Debrid...): the Wizard's source hook names it for the source
    # that was picked; shown only while the picked source is still the one that hook named it for, and never
    # over live TV or another add-on's video. A POV play's folder is the stream's own web address (seen in
    # the QA Kodi), so a library file, or an item another add-on resolved (its folder is plugin://...),
    # shows no provider even when POV's last pick is still remembered.
    x(1, '<variable name="POVIL_OSD_Provider">')
    x(2, '<value condition="!String.IsEmpty(Window(Home).Property(povil_osd_provider)) + '
         'String.IsEqual(Window(Home).Property(povil_osd_provider_for),Window(Home).Property(pov_picked_source_name)) + '
         '[VideoPlayer.Content(movies) | VideoPlayer.Content(episodes)] + !VideoPlayer.Content(LiveTV) + '
         '[String.StartsWith(Player.Folderpath,http) | String.Contains(Player.Folderpath,plugin.video.pov)] + %s">'
         '$INFO[Window(Home).Property(povil_osd_provider)]</value>' % NOT_LIVE_SOURCE)
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
    x(1, '<variable name="POVIL_OSD_Focused">')
    x(2, '<value condition="Control.HasFocus(%d)">%s</value>' % (TIMELINE, e(TIMELINE_HINT)))
    for b in BUTTONS:
        x(2, '<value condition="Control.HasFocus(%d)">%s</value>' % (b[0], e(b[2])))
    x(1, '</variable>')
    S.variables(x)
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
    print('osd generated:', len(BUTTONS), 'buttons, seek bar, info panel')


if __name__ == '__main__':
    main()
