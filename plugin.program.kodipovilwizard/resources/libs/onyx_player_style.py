"""Which player the Onyx skin shows (Wizard 0.5.23 / Onyx 1.0.22): its own, or one of the four FENtastic
offers drawn again in Onyx's look -- the owner, Nov 2026: "let the players be switched in the new skin too,
as in the other skins".

The choice is the skin string POVILPlayer (tools/skin_onyx/gen_osd_styles.py draws a group for each); unset
is Onyx's own player. Asked from the settings tile "סוג נגן" and from the button "החלפת נגן" in every player:
there the controls close and open again, so the new player is on the screen at once.
"""
SETTING = 'POVILPlayer'
# (the skin's value, the name in the list); '' = Onyx's own
STYLES = (('', 'הנגן של Onyx (ברירת מחדל)'), ('netflix', 'נגן נטפליקס'), ('advanced', 'נגן מתקדם'),
          ('simple', 'נגן פשוט'), ('pretty', 'נגן גדול (למבוגרים)'))
HEADING = 'סוג נגן'


def current(read):
    """The style chosen now (read: Kodi's getInfoLabel); Onyx's own while none of STYLES is."""
    value = read('Skin.String(%s)' % SETTING)
    return value if value in dict(STYLES) else ''


def builtin(style):
    """The Kodi command that makes `style` the player."""
    return 'Skin.SetString(%s,%s)' % (SETTING, style) if style else 'Skin.Reset(%s)' % SETTING


def choose():
    """The list; a choice is the player from now on."""
    import xbmc
    import xbmcgui
    now = current(xbmc.getInfoLabel)
    values = [value for value, _name in STYLES]
    picked = xbmcgui.Dialog().select(HEADING, [name for _value, name in STYLES], preselect=values.index(now))
    if picked < 0 or values[picked] == now:
        return None
    xbmc.executebuiltin(builtin(values[picked]))
    if xbmc.getCondVisibility('Window.IsActive(videoosd)'):
        # asked from a player's own button: its controls make way for the new player's
        # (the focus was on a button the new player does not have)
        xbmc.executebuiltin('Dialog.Close(videoosd,true)')
        xbmc.sleep(400)
        if xbmc.getCondVisibility('Player.HasVideo'):
            xbmc.executebuiltin('ActivateWindow(videoosd)')
    return values[picked]
