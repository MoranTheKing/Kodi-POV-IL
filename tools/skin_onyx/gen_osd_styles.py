# -*- coding: utf-8 -*-
"""The player styles of skin.povil.onyx besides its own: the four FENtastic offers -- simple, advanced,
Netflix-style, the large one -- drawn again in Onyx's own look, with the build's own actions (the owner,
Nov 2026: "let the players be switched in the new skin too, as in the other skins").

The viewer's choice is the skin string POVILPlayer (unset: Onyx's own; simple / advanced / netflix /
pretty); the Wizard asks (onyx_player_style.py: the settings tile "סוג נגן", and the button "החלפת נגן"
in every style, Onyx's own too). gen_osd.py draws VideoOSD.xml and calls add() here: one group per style,
shown for its choice only, its own ids (7100-7279), its own button the controls open on.
"""
from xml.sax.saxutils import escape

import gen_home as H

WIZARD = 'plugin://plugin.program.kodipovilwizard/'
CHOICE = 'POVILPlayer'
STYLES = ('simple', 'advanced', 'netflix', 'pretty')
SWITCH = 'RunPlugin(%s?mode=player_style)' % WIZARD
SUBS_SEARCH = 'RunScript(service.subtitles.kodipovilai,action=choose_subs)'
SOURCE = 'RunPlugin(%s?mode=player_change_source)' % WIZARD
EPISODES = 'RunPlugin(%s?mode=player_episodes)' % WIZARD
# Kodi's subtitle-sync slider, from the picture's own window: the controls close at once first -- an action
# sent while their closing animation runs is lost (QA Kodi, Onyx 1.0.21: the sync button showed nothing)
SYNC = ['Dialog.Close(VideoOSD,true)', 'Action(SubtitleDelay)']
NOT_LIVE_SOURCE = ('!String.Contains(Player.Folderpath,plugin.video.idanplus) + !String.Contains(Player.Folderpath,plugin.video.supertv)'
                   ' + !String.Contains(Player.Folderpath,plugin.video.flashstream)')
SOURCE_SHOWN = '[VideoPlayer.Content(movies) | VideoPlayer.Content(episodes)] + !VideoPlayer.Content(LiveTV) + ' + NOT_LIVE_SOURCE
SUBS_SHOWN = '!VideoPlayer.Content(LiveTV) | VideoPlayer.HasSubtitles'
SEEK_SHOWN = 'Player.SeekEnabled + !VideoPlayer.Content(livetv)'
RIGHT = 1920 - H.MARGIN
WIDE = 1920 - 2 * H.MARGIN
GROW = 8                    # a focused chip grows by 12%: the room a row keeps around its chips (a grouplist clips)

# the button each style's controls open on, and the one where nothing can be paused (a live channel)
MAIN = {'simple': 7114, 'advanced': 7153, 'netflix': 7192, 'pretty': 7251}
NO_PAUSE = {'simple': 7115, 'advanced': 7152, 'netflix': 7193, 'pretty': 7250}
# the empty ends of the rows (Kodi links a grouplist's items by their ids: one without an id ends the chain)
GAP_IDS = {'simple': range(7130, 7140), 'advanced': range(7170, 7180), 'netflix': range(7230, 7240)}
GAPS = {}
PILLS_BASE = 7930           # the large style's pills (Onyx's own use 7910-7915, its ratings row 7920-7921)
# Netflix-style forward and back: a row of jumps (FENtastic's own steps)
STEPS = (('', 'הרצה'), ('60', 'דקה'), ('300', '5 דקות'), ('600', '10 דקות'), ('1200', '20 דקות'), ('2400', '40 דקות'),
         ('3600', '60 דקות'), ('4800', '80 דקות'))
REWIND_STEPS, FORWARD_STEPS = 7200, 7201


def e(s):
    return escape(s)


def shown(style):
    return 'String.IsEqual(Skin.String(%s),%s)' % (CHOICE, style)


def onyx_shown():
    """Onyx's own player: no choice made, or a choice this skin does not know."""
    return '![%s]' % ' | '.join(shown(s) for s in STYLES)


def label(x, d, left, top, width, height, text, font='povil_meta', color='povil_white', align='left'):
    x(d, '<control type="label"><left>%d</left><top>%d</top><width>%d</width><height>%d</height><font>%s</font>'
         '<textcolor>%s</textcolor><shadowcolor>B3000000</shadowcolor><align>%s</align><aligny>center</aligny>'
         '<label>%s</label></control>' % (left, top, width, height, font, color, align, text))


def progress(x, d, left, top, width, height=8):
    """What was played, gold over a faint track (Onyx's own bar), what is buffered under it."""
    bar = '<lefttexture></lefttexture><righttexture></righttexture><overlaytexture></overlaytexture>'
    x(d, '<control type="progress"><left>%d</left><top>%d</top><width>%d</width><height>%d</height><info>Player.ProgressCache</info>'
         '<reveal>false</reveal>%s<texturebg border="4" colordiffuse="38FFFFFF">povil/progress.png</texturebg>'
         '<midtexture border="4" colordiffuse="47FFFFFF">povil/progress.png</midtexture></control>' % (left, top, width, height, bar))
    x(d, '<control type="progress"><left>%d</left><top>%d</top><width>%d</width><height>%d</height><info>Player.Progress</info>'
         '<reveal>false</reveal>%s<texturebg border="4" colordiffuse="00FFFFFF">povil/progress.png</texturebg>'
         '<midtexture border="4" colordiffuse="FFD9B77E">povil/progress.png</midtexture></control>' % (left, top, width, height, bar))


def chip(x, d, bid, icon, name, clicks, visible='', size=84, toggle=False):
    """An Onyx button: the icon on a glass chip, a gold disc when focused. Its name is its label, drawn
    clear: the style's name line reads it (System.CurrentControl)."""
    kind = 'togglebutton' if toggle else 'button'
    x(d, '<control type="%s" id="%d">' % (kind, bid))
    x(d + 1, '<width>%d</width><height>%d</height><top>%d</top>' % (size, size, GROW))
    x(d + 1, '<texturenofocus>povil/osd/%s_nf.png</texturenofocus><texturefocus>povil/osd/%s_fo.png</texturefocus>' % (icon, icon))
    if toggle:
        x(d + 1, '<alttexturenofocus>povil/osd/play_nf.png</alttexturenofocus><alttexturefocus>povil/osd/play_fo.png</alttexturefocus>')
        x(d + 1, '<usealttexture>Player.Paused | Player.Forwarding | Player.Rewinding</usealttexture>')
        x(d + 1, '<altlabel>%s</altlabel>' % e('המשך ניגון'))
    x(d + 1, '<label>%s</label><font>povil_small</font><textcolor>00FFFFFF</textcolor><focusedcolor>00FFFFFF</focusedcolor>' % e(name))
    x(d + 1, '<animation effect="zoom" start="100" end="112" center="auto" time="130" tween="cubic" easing="out">Focus</animation>')
    x(d + 1, '<animation effect="zoom" start="112" end="100" center="auto" time="130" tween="cubic" easing="out">Unfocus</animation>')
    for c in clicks:
        x(d + 1, '<onclick>%s</onclick>' % e(c))
        if toggle:
            x(d + 1, '<altclick>%s</altclick>' % e(c))
    if visible:
        x(d + 1, '<visible>%s</visible>' % e(visible))
    x(d, '</control>')


def text_button(x, d, bid, text, clicks, visible='', height=84, top=GROW):
    """A button that is its words, on a pill: glass at rest, gold when focused."""
    x(d, '<control type="button" id="%d"><width>auto</width><height>%d</height><top>%d</top><font>povil_meta_bold</font>' % (bid, height, top))
    x(d + 1, '<textcolor>povil_white</textcolor><focusedcolor>FF17130D</focusedcolor><align>center</align><aligny>center</aligny><textoffsetx>34</textoffsetx>')
    x(d + 1, '<texturenofocus border="24" colordiffuse="40FFFFFF">povil/pill48.png</texturenofocus>'
             '<texturefocus border="24" colordiffuse="FFD9B77E">povil/pill48.png</texturefocus>')
    x(d + 1, '<label>%s</label>' % e(text))
    for c in clicks:
        x(d + 1, '<onclick>%s</onclick>' % e(c))
    if visible:
        x(d + 1, '<visible>%s</visible>' % e(visible))
    x(d, '</control>')


def nav(x, d, tag, targets):
    """targets: a control id, 'noop', or [ids]: the first of them on the screen."""
    if not isinstance(targets, list):
        x(d, '<%s>%s</%s>' % (tag, targets, tag))
        return
    for target in targets[:-1]:
        x(d, '<%s condition="Control.IsVisible(%d)">%d</%s>' % (tag, target, target, tag))
    x(d, '<%s>%d</%s>' % (tag, targets[-1], tag))


def gap(x, d, style, height):
    if style in GAPS:
        x(d, '<control type="image" id="%d"><width>10</width><height>%d</height><texture></texture></control>' % (next(GAPS[style]), height))


def row_open(x, d, gid, left, top, width, height, align, onleft='noop', onright='noop', itemgap=14, style=None):
    """A row of buttons. Every side leads somewhere or stays: a key no control takes falls through to the
    picture, where the arrows seek."""
    x(d, '<control type="grouplist" id="%d"><left>%d</left><top>%d</top><width>%d</width><height>%d</height>'
         '<orientation>horizontal</orientation><align>%s</align><itemgap>%d</itemgap><usecontrolcoords>true</usecontrolcoords>'
         % (gid, left, top, width, height, align, itemgap))
    nav(x, d + 1, 'onleft', onleft)
    nav(x, d + 1, 'onright', onright)
    x(d + 1, '<onup>noop</onup><ondown>noop</ondown>')
    gap(x, d + 1, style, height)


def row_close(x, d, height, style=None):
    gap(x, d + 1, style, height)
    x(d, '</control>')


def tap_close(x, d, bid, style):
    """A tap or a click on the picture closes the controls; any arrow from it goes back to the buttons."""
    back = [MAIN[style], NO_PAUSE[style]]
    x(d, '<control type="button" id="%d"><left>0</left><top>0</top><width>1920</width><height>740</height>'
         '<texturefocus></texturefocus><texturenofocus></texturenofocus><label></label><onclick>Dialog.Close(VideoOSD)</onclick>' % bid)
    for tag in ('onup', 'ondown', 'onleft', 'onright'):
        nav(x, d + 1, tag, back)
    x(d, '</control>')


def shade(x, d, top=440):
    x(d, '<control type="image"><left>-320</left><top>%d</top><width>2560</width><height>%d</height><texture>povil/grad_bottom.png</texture></control>'
         % (top, 1080 - top))


# ------------------------------------------------------------------ simple
def simple(x, d):
    """FENtastic's simple player: a dark band at the bottom -- what plays, the time and the chapter (or the
    episode) over the bar -- and two groups of buttons: the subtitles' and the playing on the left, the
    picture's and the source's on the right."""
    style, size = 'simple', 84
    tap_close(x, d, 7105, style)
    x(d, '<control type="image"><left>0</left><top>796</top><width>1920</width><height>284</height>'
         '<texture colordiffuse="D9000000">povil/white.png</texture></control>')
    label(x, d, H.MARGIN, 744, 1000, 44, '$INFO[System.CurrentControl]', 'povil_meta_bold', 'povil_gold')
    label(x, d, H.MARGIN, 810, 720, 44, '$VAR[POVIL_OSD_Title]', 'povil_meta_bold')
    label(x, d, 960 - 300, 810, 600, 44, '$INFO[Player.Time]$INFO[Player.Duration, / ]', 'povil_meta', align='center')
    label(x, d, RIGHT - 600, 810, 600, 44, '$VAR[POVIL_PS_Part]', 'povil_meta', 'povil_gold', 'right')
    progress(x, d, H.MARGIN, 866, WIDE)
    height = size + 2 * GROW
    row_open(x, d, 7101, H.MARGIN - 10 - 14, 904, 960, height, 'left', 'noop', [7120, 7121], style=style)
    chip(x, d + 1, 7110, 'subtitles', 'הגדרות כתוביות', ['ActivateWindow(OSDSubtitleSettings)'], SUBS_SHOWN)
    chip(x, d + 1, 7111, 'sync', 'סנכרון כתוביות', SYNC, 'VideoPlayer.SubtitlesEnabled')
    text_button(x, d + 1, 7112, 'בחירת כתוביות', [SUBS_SEARCH], SUBS_SHOWN)
    chip(x, d + 1, 7113, 'rewind', 'הרצה אחורה', ['PlayerControl(Rewind)'], SEEK_SHOWN + ' + !Player.Paused')
    chip(x, d + 1, MAIN[style], 'pause', 'השהיה', ['PlayerControl(Play)'], 'Player.PauseEnabled', toggle=True)
    chip(x, d + 1, 7115, 'stop', 'עצירה', ['PlayerControl(Stop)'])
    chip(x, d + 1, 7116, 'forward', 'הרצה קדימה', ['PlayerControl(Forward)'], SEEK_SHOWN + ' + !Player.Paused')
    row_close(x, d, height, style)
    row_open(x, d, 7102, RIGHT - 900 + 10 + 14, 904, 900, height, 'right', [7116, 7115], 'noop', style=style)
    chip(x, d + 1, 7120, 'source', 'החלפת מקור', [SOURCE], SOURCE_SHOWN)
    chip(x, d + 1, 7121, 'layout', 'החלפת נגן', [SWITCH])
    chip(x, d + 1, 7122, 'audio', 'רצועת השמע הבאה', ['AudioNextLanguage'], 'Integer.IsGreater(VideoPlayer.AudioStreamCount,1)')
    chip(x, d + 1, 7123, 'zoomin', 'הגדלת התמונה', ['ZoomIn'])
    chip(x, d + 1, 7124, 'zoomout', 'הקטנת התמונה', ['ZoomOut'])
    chip(x, d + 1, 7125, 'settings', 'הגדרות וידאו', ['ActivateWindow(OSDVideoSettings)'])
    row_close(x, d, height, style)


# ------------------------------------------------------------------ advanced
def advanced(x, d):
    """FENtastic's advanced player: one row of small buttons at the bottom left -- everything the player
    does, in order -- with the focused one's description on the right; what plays, the time and the
    episode (or the chapters) over the bar."""
    style, size = 'advanced', 64
    tap_close(x, d, 7145, style)
    shade(x, d)
    label(x, d, H.MARGIN, 850, 760, 44, '$VAR[POVIL_OSD_Title]$INFO[VideoPlayer.Year, (,)]', 'povil_meta_bold')
    label(x, d, 960 - 300, 850, 600, 44, '$INFO[Player.Time]$INFO[Player.Duration, / ]', 'povil_meta', align='center')
    label(x, d, RIGHT - 600, 850, 600, 44, '$VAR[POVIL_PS_InfoLine]', 'povil_meta', 'povil_gold', 'right')
    progress(x, d, H.MARGIN, 904, WIDE)
    label(x, d, 1160, 940, RIGHT - 1160, 80, '$INFO[System.CurrentControl]', 'povil_meta', 'povil_gold', 'right')
    height = size + 2 * GROW
    row_open(x, d, 7141, H.MARGIN - 10 - 10, 940, 1060, height, 'left', itemgap=10, style=style)
    small = dict(size=size)
    chip(x, d + 1, 7150, 'previous', 'הפרק או המקטע הקודם', ['PlayerControl(Previous)'], **small)
    chip(x, d + 1, 7151, 'rewind', 'הרצה אחורה', ['PlayerControl(Rewind)'], SEEK_SHOWN, **small)
    chip(x, d + 1, 7152, 'stop', 'עצירה', ['PlayerControl(Stop)'], **small)
    chip(x, d + 1, MAIN[style], 'pause', 'השהיה', ['PlayerControl(Play)'], 'Player.PauseEnabled', toggle=True, **small)
    chip(x, d + 1, 7154, 'forward', 'הרצה קדימה', ['PlayerControl(Forward)'], SEEK_SHOWN, **small)
    chip(x, d + 1, 7155, 'next', 'הפרק או המקטע הבא', ['PlayerControl(Next)'], **small)
    chip(x, d + 1, 7156, 'subtitles', '$VAR[POVIL_PS_Subs]', ['ShowSubtitles'], 'VideoPlayer.HasSubtitles', **small)
    chip(x, d + 1, 7157, 'search', 'חיפוש כתובית', [SUBS_SEARCH], SUBS_SHOWN, **small)
    chip(x, d + 1, 7158, 'sync', 'סנכרון כתוביות', SYNC, 'VideoPlayer.SubtitlesEnabled', **small)
    chip(x, d + 1, 7159, 'settings', 'הגדרות וידאו', ['ActivateWindow(OSDVideoSettings)'], **small)
    chip(x, d + 1, 7160, 'audio', 'הגדרות שמע', ['ActivateWindow(OSDAudioSettings)'], **small)
    chip(x, d + 1, 7161, 'source', 'החלפת מקור', [SOURCE], SOURCE_SHOWN, **small)
    chip(x, d + 1, 7162, 'layout', 'החלפת נגן', [SWITCH], **small)
    row_close(x, d, height, style)


# ------------------------------------------------------------------ netflix
def step_list(x, d, lid, button, back):
    """The jumps of a forward or back button: shown while the button or the list has the focus."""
    x(d, '<control type="list" id="%d"><left>290</left><top>770</top><width>1340</width><height>54</height>' % lid)
    x(d + 1, '<orientation>horizontal</orientation><scrolltime>150</scrolltime>')
    x(d + 1, '<onup>%d</onup><ondown>%d</ondown><onback>%d</onback><onleft>noop</onleft><onright>noop</onright>' % (button, button, button))
    x(d + 1, '<visible>Control.HasFocus(%d) | Control.HasFocus(%d)</visible>' % (lid, button))
    x(d + 1, '<itemlayout width="160" height="54">')
    x(d + 2, '<control type="label"><left>6</left><top>4</top><width>148</width><height>46</height><font>povil_meta</font>'
             '<textcolor>povil_dim</textcolor><align>center</align><aligny>center</aligny><label>$INFO[ListItem.Label]</label></control>')
    x(d + 1, '</itemlayout>')
    x(d + 1, '<focusedlayout width="160" height="54">')
    x(d + 2, '<control type="image"><left>6</left><top>4</top><width>148</width><height>46</height>'
             '<texture border="22" colordiffuse="FFD9B77E">povil/pill48.png</texture><visible>Control.HasFocus(%d)</visible></control>' % lid)
    x(d + 2, '<control type="label"><left>6</left><top>4</top><width>148</width><height>46</height><font>povil_meta</font>'
             '<textcolor>FF17130D</textcolor><align>center</align><aligny>center</aligny><label>$INFO[ListItem.Label]</label>'
             '<visible>Control.HasFocus(%d)</visible></control>' % lid)
    x(d + 2, '<control type="label"><left>6</left><top>4</top><width>148</width><height>46</height><font>povil_meta</font>'
             '<textcolor>povil_dim</textcolor><align>center</align><aligny>center</aligny><label>$INFO[ListItem.Label]</label>'
             '<visible>!Control.HasFocus(%d)</visible></control>' % lid)
    x(d + 1, '</focusedlayout>')
    x(d + 1, '<content>')
    for seconds, name in STEPS:
        x(d + 2, '<item><label>%s</label>' % e(name))
        if seconds:
            x(d + 3, '<onclick>Seek(%s%s)</onclick>' % ('-' if back else '', seconds))
        else:
            x(d + 3, '<onclick>PlayerControl(%s)</onclick>' % ('Rewind' if back else 'Forward'))
        x(d + 2, '</item>')
    x(d + 1, '</content>')
    x(d, '</control>')


def netflix(x, d):
    """FENtastic's Netflix-style player: a long bar between the time played and the time left; round
    buttons under it, the playing on the left and the settings on the right; forward and back open a
    row of jumps over the bar (a minute up to eighty)."""
    style, size = 'netflix', 68
    tap_close(x, d, 7185, style)
    shade(x, d, 400)
    label(x, d, H.MARGIN, 836, 700, 44, '$VAR[POVIL_OSD_State]', 'povil_meta_bold')
    label(x, d, RIGHT - 1000, 836, 1000, 44, '$INFO[System.CurrentControl]', 'povil_meta', 'povil_gold', 'right')
    label(x, d, H.MARGIN, 882, 180, 40, '$INFO[Player.Time]', 'povil_meta_bold')
    progress(x, d, 290, 899, 1340, 6)
    label(x, d, RIGHT - 180, 882, 180, 40, '$INFO[Player.TimeRemaining]', 'povil_meta', 'povil_dim', 'right')
    step_list(x, d, REWIND_STEPS, 7191, True)
    step_list(x, d, FORWARD_STEPS, 7198, False)
    height = size + 2 * GROW
    small = dict(size=size)
    row_open(x, d, 7181, H.MARGIN - 10 - 12, 936, 1060, height, 'left', 'noop', [7210, 7211, 7212], itemgap=12, style=style)
    chip(x, d + 1, 7190, 'previous', 'הקודם', ['PlayerControl(Previous)'], **small)
    chip(x, d + 1, 7191, 'rewind', 'אחורה: בחירת קפיצה', ['SetFocus(%d)' % REWIND_STEPS], SEEK_SHOWN, **small)
    chip(x, d + 1, MAIN[style], 'pause', 'השהיה', ['PlayerControl(Play)'], 'Player.PauseEnabled', toggle=True, **small)
    chip(x, d + 1, 7198, 'forward', 'קדימה: בחירת קפיצה', ['SetFocus(%d)' % FORWARD_STEPS], SEEK_SHOWN, **small)
    chip(x, d + 1, 7193, 'stop', 'עצירה', ['PlayerControl(Stop)'], **small)
    chip(x, d + 1, 7199, 'next', 'הבא', ['PlayerControl(Next)'], **small)
    chip(x, d + 1, 7194, 'info', 'מידע', ['Dialog.Close(VideoOSD,true)', 'Action(Info)'], **small)
    chip(x, d + 1, 7195, 'search', 'חיפוש כתובית', [SUBS_SEARCH], SUBS_SHOWN, **small)
    chip(x, d + 1, 7196, 'subtitles', '$VAR[POVIL_PS_Subs]', ['ShowSubtitles'], 'VideoPlayer.HasSubtitles', **small)
    chip(x, d + 1, 7197, 'sync', 'סנכרון כתוביות', SYNC, 'VideoPlayer.SubtitlesEnabled', **small)
    row_close(x, d, height, style)
    row_open(x, d, 7182, RIGHT - 640 + 10 + 12, 936, 640, height, 'right', [7197, 7196, 7195, 7194], 'noop', itemgap=12, style=style)
    chip(x, d + 1, 7210, 'episodes', 'הפרק הבא', [EPISODES], 'VideoPlayer.Content(episodes) + !VideoPlayer.Content(LiveTV)', **small)
    chip(x, d + 1, 7211, 'source', 'החלפת מקור', [SOURCE], SOURCE_SHOWN, **small)
    chip(x, d + 1, 7212, 'audio', 'הגדרות שמע', ['ActivateWindow(OSDAudioSettings)'], **small)
    chip(x, d + 1, 7213, 'settings', 'הגדרות וידאו', ['ActivateWindow(OSDVideoSettings)'], **small)
    chip(x, d + 1, 7214, 'layout', 'החלפת נגן', [SWITCH], **small)
    row_close(x, d, height, style)


# ------------------------------------------------------------------ pretty (large)
def pretty(x, d, pills_row):
    """FENtastic's large player ("for grown-ups"): big buttons that say what they do, a card in the middle
    with the picture, the title and how much is left, what is playing as pills over the bar."""
    style = 'pretty'
    tap_close(x, d, 7245, style)
    shade(x, d, 300)
    x(d, '<control type="group"><left>690</left><top>110</top>')
    x(d + 1, '<control type="image"><left>0</left><top>0</top><width>540</width><height>600</height>'
             '<texture border="128" colordiffuse="E6121212">povil/panel.png</texture></control>')
    x(d + 1, '<control type="image"><left>20</left><top>20</top><width>500</width><height>282</height><aspectratio>scale</aspectratio>'
             '<texture background="true">$VAR[POVIL_PS_Picture]</texture></control>')
    label(x, d + 1, 20, 314, 500, 50, '$VAR[POVIL_OSD_Title]$INFO[VideoPlayer.Year, (,)]', 'povil_meta_bold', align='center')
    label(x, d + 1, 20, 362, 500, 40, '$VAR[POVIL_PS_Genre]', 'povil_meta', 'povil_gold', 'center')
    label(x, d + 1, 20, 404, 500, 40, '$VAR[POVIL_PS_Left]', 'povil_meta', align='center')
    progress(x, d + 1, 40, 456, 460, 10)
    x(d + 1, '<control type="image"><left>60</left><top>480</top><width>420</width><height>100</height><aspectratio>keep</aspectratio>'
             '<texture background="true">$INFO[Player.Art(povil_logo)]</texture></control>')
    x(d, '</control>')
    pills_row(x, d, 760, PILLS_BASE)
    progress(x, d, H.MARGIN, 830, WIDE, 10)
    row_open(x, d, 7241, H.MARGIN, 870, WIDE, 96, 'center', itemgap=20)
    text_button(x, d + 1, 7250, 'עצירה', ['PlayerControl(Stop)'], height=80)
    text_button(x, d + 1, MAIN[style], '$VAR[POVIL_PS_Play]', ['PlayerControl(Play)'], 'Player.PauseEnabled', height=80)
    text_button(x, d + 1, 7252, 'חיפוש כתובית', [SUBS_SEARCH], SUBS_SHOWN, height=80)
    text_button(x, d + 1, 7253, 'החלפת מקור', [SOURCE], SOURCE_SHOWN, height=80)
    text_button(x, d + 1, 7254, '$VAR[POVIL_PS_Subs]', ['ShowSubtitles'], 'VideoPlayer.HasSubtitles', height=80)
    text_button(x, d + 1, 7255, 'החלפת נגן', [SWITCH], height=80)
    row_close(x, d, 96)


def add(x, d, pills_row):
    """The four styles, each a group of its own for its choice."""
    GAPS.update((style, iter(ids)) for style, ids in GAP_IDS.items())
    for style, draw in (('simple', simple), ('advanced', advanced), ('netflix', netflix), ('pretty', pretty)):
        x(d, '<control type="group" description="player style: %s">' % style)
        x(d + 1, '<visible>Player.HasMedia + %s</visible>' % shown(style))
        x(d + 1, '<animation type="WindowOpen"><effect type="fade" start="0" end="100" time="220" /></animation>')
        x(d + 1, '<animation type="WindowClose"><effect type="fade" start="100" end="0" time="180" /></animation>')
        x(d + 1, '<animation effect="fade" start="100" end="0" time="160" condition="Window.IsVisible(sliderdialog) | '
                 'Window.IsVisible(osdsubtitlesettings) | Window.IsVisible(osdvideosettings) | Window.IsVisible(osdaudiosettings) | '
                 'Window.IsVisible(videobookmarks)">Conditional</animation>')
        if style == 'pretty':
            draw(x, d + 1, pills_row)
        else:
            draw(x, d + 1)
        x(d, '</control>')


def onloads(x, d):
    """The controls open on the style's main button, or (a live channel that cannot pause) on stop."""
    for style in STYLES:
        x(d, '<onload condition="%s + Player.PauseEnabled">SetFocus(%d)</onload>' % (shown(style), MAIN[style]))
        x(d, '<onload condition="%s + !Player.PauseEnabled">SetFocus(%d)</onload>' % (shown(style), NO_PAUSE[style]))


def variables(x):
    x(1, '<variable name="POVIL_PS_Part">')
    x(2, '<value condition="VideoPlayer.Content(episodes)">$INFO[VideoPlayer.Season,עונה , · ]$INFO[VideoPlayer.Episode,פרק ]</value>')
    x(2, '<value condition="Integer.IsGreater(Player.ChapterCount,1)">[COLOR povil_dim]מקטע[/COLOR] $INFO[Player.Chapter]/$INFO[Player.ChapterCount]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_PS_InfoLine">')
    x(2, '<value condition="VideoPlayer.Content(episodes)">$INFO[VideoPlayer.Season,עונה , · ]$INFO[VideoPlayer.Episode,פרק ]</value>')
    x(2, '<value condition="Integer.IsGreater(Player.ChapterCount,1)">מקטע $INFO[Player.Chapter] מתוך $INFO[Player.ChapterCount]</value>')
    x(2, '<value>$INFO[VideoPlayer.Genre]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_PS_Genre">')
    x(2, '<value condition="VideoPlayer.Content(episodes)">$INFO[VideoPlayer.Season,עונה , · ]$INFO[VideoPlayer.Episode,פרק ]</value>')
    x(2, '<value>$INFO[VideoPlayer.Genre]</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_PS_Subs">')
    x(2, '<value condition="VideoPlayer.SubtitlesEnabled">כתוביות: מוצגות</value>')
    x(2, '<value>כתוביות: מוסתרות</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_PS_Play">')
    x(2, '<value condition="Player.Paused | Player.Forwarding | Player.Rewinding">המשך ניגון</value>')
    x(2, '<value>השהיה</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_PS_Left">')
    x(2, '<value condition="!String.IsEmpty(Player.Duration)">נותרו $INFO[Player.TimeRemaining]  ·  נצפו $INFO[Player.Progress]%</value>')
    x(1, '</variable>')
    x(1, '<variable name="POVIL_PS_Picture">')
    for art in ('fanart', 'landscape', 'thumb'):
        x(2, '<value condition="!String.IsEmpty(Player.Art(%s))">$INFO[Player.Art(%s)]</value>' % (art, art))
    x(1, '</variable>')
