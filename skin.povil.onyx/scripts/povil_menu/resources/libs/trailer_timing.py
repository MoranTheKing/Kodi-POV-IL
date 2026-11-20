"""How soon the home's trailer starts, and how soon it has the screen to itself (the tile "תזמון טריילרים" in
the Onyx settings screen, Wizard 0.5.20 / Onyx 1.0.21).

The owner, Nov 2026: "the trailer should play as fast as possible, almost at once ... and you could let the
settings change these timings, as the viewer wants". Both are skin strings (tools/skin_onyx/gen_home.py:
TRAILER_WAIT, TRAILER_FULL); unset is the default -- 1 s of rest on a title, and the screen to the trailer
after 4 s, as it always was (the owner: "no later than it is today").
"""
WAIT, FULL = 'POVILTrailerWait', 'POVILTrailerFull'
WAITS = ((1, 'שנייה אחת (ברירת מחדל)'), (2, '2 שניות'), (3, '3 שניות'), (5, '5 שניות'))
FULLS = ((2, '2 שניות'), (3, '3 שניות'), (4, '4 שניות (ברירת מחדל)'), (6, '6 שניות'), (8, '8 שניות'),
         (12, '12 שניות'), (0, 'אף פעם'))
DEFAULTS = {WAIT: 1, FULL: 4}
HEADING = 'תזמון טריילרים'
QUESTIONS = ((WAIT, WAITS, 'הטריילר מתחיל אחרי'), (FULL, FULLS, 'מסך מלא לטריילר אחרי'))
# The trailers' Hebrew subtitles (trailer_subs.py, Wizard 0.5.29): on unless switched off here -- the skin's setting
SUBS_OFF = 'POVILTrailerSubsOff'
SUBS_LINE = 'כתוביות בעברית לטריילרים'


def current(read, setting, choices):
    """The seconds chosen for setting (read: Kodi's getInfoLabel); the default while none of the choices is."""
    try:
        value = int(read('Skin.String(%s)' % setting))
    except ValueError:
        return DEFAULTS[setting]
    return value if value in dict(choices) else DEFAULTS[setting]


def name_of(value, choices):
    return dict(choices)[value].replace(' (ברירת מחדל)', '')


def choose():
    """The tile "תזמון טריילרים": both questions in one list, until the viewer goes back."""
    import xbmc
    import xbmcgui
    dialog = xbmcgui.Dialog()
    # (kept here as chosen: Kodi carries out Skin.SetString a moment later, and the list read the skin's old
    # value back -- seen in the QA Kodi)
    now = {setting: current(xbmc.getInfoLabel, setting, choices) for setting, choices, _question in QUESTIONS}
    while True:
        lines = ['%s: %s' % (question, name_of(now[setting], choices)) for setting, choices, question in QUESTIONS]
        subs_off = now.setdefault(SUBS_OFF, xbmc.getCondVisibility('Skin.HasSetting(%s)' % SUBS_OFF))
        lines.append('%s: %s' % (SUBS_LINE, 'כבוי' if subs_off else 'פועל'))
        line = dialog.select(HEADING, lines)
        if line < 0:
            return
        if line == len(QUESTIONS):
            now[SUBS_OFF] = not subs_off
            xbmc.executebuiltin('Skin.%s(%s)' % ('SetBool' if now[SUBS_OFF] else 'Reset', SUBS_OFF))
            continue
        setting, choices, question = QUESTIONS[line]
        values = [value for value, _name in choices]
        picked = dialog.select(question, [name for _value, name in choices], preselect=values.index(now[setting]))
        if picked >= 0:
            now[setting] = values[picked]
            xbmc.executebuiltin('Skin.SetString(%s,%d)' % (setting, values[picked]))
