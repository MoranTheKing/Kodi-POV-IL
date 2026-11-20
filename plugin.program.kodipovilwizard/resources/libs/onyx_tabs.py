"""Which screens the top bar of the Onyx home shows (Wizard 0.5.12 / Onyx 1.0.18).

A viewer, Nov 2026: "I want to remove live TV and Israeli and put a screen of my own choice there,
say continue watching -- I see no way to change the screens at the top". The home has nine screens
now (the ninth is "המשך צפייה", everything the viewer is in the middle of); this asks which of
them stand on the bar. Films and settings always do: the home opens on the first, and the second
is where this question lives.

A screen is off the bar while the skin's setting POVILHideTab_<id> is set (tools/skin_onyx/
gen_home.py, BAR): a skin setting is unset until someone sets it, so every screen is on the bar
until the viewer takes it off.
"""
# (id in the skin, the name on the bar) -- in the bar's order, the first on the right
TABS = (('tv', 'סדרות'), ('continue', 'המשך צפייה'), ('israeli', 'ישראלי'), ('live', 'שידור חי'),
        ('kids', 'ילדים'), ('favourites', 'מועדפים'), ('search', 'חיפוש'))
SETTING = 'POVILHideTab_%s'
HEADING = 'המסכים בסרגל העליון (סרטים והגדרות מוצגים תמיד)'


def shown(visible):
    """The places in TABS of the screens that are on the bar now."""
    return [place for place, (tab, _name) in enumerate(TABS) if not visible('Skin.HasSetting(%s)' % (SETTING % tab))]


def apply(picked, run):
    """Put on the bar exactly the screens picked (places in TABS). Returns the ids taken off it."""
    off = []
    for place, (tab, _name) in enumerate(TABS):
        if place in picked:
            run('Skin.Reset(%s)' % (SETTING % tab))
        else:
            run('Skin.SetBool(%s)' % (SETTING % tab))
            off.append(tab)
    return off


def choose():
    """The tile "בחירת מסכים" in the home's settings screen."""
    import xbmc
    import xbmcgui
    picked = xbmcgui.Dialog().multiselect(HEADING, [name for _tab, name in TABS], preselect=shown(xbmc.getCondVisibility))
    if picked is None:
        return None             # closed without a choice: nothing changes
    off = apply(picked, xbmc.executebuiltin)
    home = xbmcgui.Window(10000)
    if home.getProperty('povil.tab') in off:
        # the screen that was up has left the bar: the home goes back to its first
        home.setProperty('povil.tab', 'movies')
        # (the films' button, wherever on the bar the viewer put it -- Onyx 1.0.28; a skin before it: 9010)
        from resources.libs import menu_editor
        films = menu_editor.button_id('movies', xbmc.getInfoLabel, xbmc.getCondVisibility)
        if films:
            xbmc.executebuiltin('SetFocus(%d)' % films)
    return off
