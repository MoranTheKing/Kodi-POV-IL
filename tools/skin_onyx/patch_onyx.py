# -*- coding: utf-8 -*-
"""Kodi POV IL changes to Onyx's own XML (the files that are not generated).

    python patch_onyx.py ../../skin.povil.onyx

Every edit is (file, old, new): applied once, skipped when already applied,
and an error when neither text is there (Onyx changed: look again).
"""
import os
import sys

import gen_home as H

NL = chr(10)
GOLD = 'FFD9B77E'
AUTOCOMPLETE = ('plugin://plugin.program.autocompletion?info=autocomplete&amp;&amp;id='
                '$INFO[Control.GetLabel(312).index(1)]&amp;&amp;limit=9&amp;&amp;povil_rtl=1')

EDITS = [
    # Headings, section titles and descriptions: the build's gold, not Onyx's mint
    ('Includes_Variables.xml',
     '<value condition="!String.IsEmpty(Skin.String(HighlightColor))">$INFO[Skin.String(HighlightColor)]</value>' + NL + '\t\t<value>FF80E0B0</value>',
     '<value condition="!String.IsEmpty(Skin.String(HighlightColor))">$INFO[Skin.String(HighlightColor)]</value>' + NL + '\t\t<value>' + GOLD + '</value>'),
    # Keyboard keys: rounded, gold when focused
    ('CommonViews.xml',
     '\t<include name="KeyboardButtons">' + NL + '\t\t<texturenofocus border="4">img/SettingsButtonNF.png</texturenofocus>',
     '\t<include name="KeyboardButtons">' + NL + '\t\t<texturenofocus border="24" colordiffuse="14FFFFFF">povil/pill48.png</texturenofocus>' + NL +
     '\t\t<texturefocus border="24" colordiffuse="povil_gold">povil/pill48.png</texturefocus>' + NL +
     '\t\t<textcolor>povil_white</textcolor>' + NL + '\t\t<focusedcolor>povil_ink</focusedcolor>'),
    # Keyboard panel and edit field
    ('DialogKeyboard.xml',
     '\t\t\t<control type="image">' + NL + '\t\t\t\t<centerleft>960</centerleft>' + NL + '\t\t\t\t<centertop>744</centertop>' + NL +
     '\t\t\t\t<width>1350</width>' + NL + '\t\t\t\t<height>680</height>' + NL + '\t\t\t\t<texture border="128">img/DialogCE.png</texture>' + NL + '\t\t\t</control>',
     '\t\t\t<control type="image">' + NL + '\t\t\t\t<left>0</left><top>0</top><width>1920</width><height>1080</height>' + NL +
     '\t\t\t\t<texture colordiffuse="99000000">povil/white.png</texture>' + NL + '\t\t\t</control>' + NL +
     '\t\t\t<control type="image">' + NL + '\t\t\t\t<centerleft>960</centerleft>' + NL + '\t\t\t\t<centertop>744</centertop>' + NL +
     '\t\t\t\t<width>1350</width>' + NL + '\t\t\t\t<height>680</height>' + NL +
     '\t\t\t\t<texture border="30" colordiffuse="F2141416">povil/rounded_fill.png</texture>' + NL + '\t\t\t</control>'),
    ('DialogKeyboard.xml',
     '<texture border="24,8,24,8">HUD/KeyEdit.png</texture>',
     '<texture border="24" colordiffuse="1FFFFFFF">povil/pill48.png</texture>'),
    # Up from the first row: the suggestions when there are any
    ('DialogKeyboard.xml',
     '<onup>309</onup>',
     '<onup condition="Integer.IsGreater(Container(9010).NumItems,0)">9010</onup><onup condition="!Integer.IsGreater(Container(9010).NumItems,0)">309</onup>'),
    # Voice search (Android's speech recogniser; Kodi only has it on Android)
    ('DialogKeyboard.xml',
     '\t\t\t\t\t\t\t<control type="button" id="309" description="Layout">' + NL + '\t\t\t\t\t\t\t\t<width>380</width>',
     '\t\t\t\t\t\t\t<control type="button" id="309" description="Layout">' + NL + '\t\t\t\t\t\t\t\t<width>330</width>'),
    ('DialogKeyboard.xml',
     '\t\t\t\t\t\t\t<control type="button" id="32">' + NL + '\t\t\t\t\t\t\t\t<description>SPACE button</description>' + NL + '\t\t\t\t\t\t\t\t<width>535</width>',
     '\t\t\t\t\t\t\t<control type="button" id="3010" description="Voice search">' + NL +
     '\t\t\t\t\t\t\t\t<width>250</width>' + NL + '\t\t\t\t\t\t\t\t<label>חיפוש קולי</label>' + NL +
     '\t\t\t\t\t\t\t\t<onclick>VoiceRecognizer</onclick>' + NL + '\t\t\t\t\t\t\t\t<onclick>SetFocus(300)</onclick>' + NL +
     '\t\t\t\t\t\t\t\t<onup>302</onup>' + NL + '\t\t\t\t\t\t\t\t<font>size20</font>' + NL +
     '\t\t\t\t\t\t\t\t<visible>System.Platform.Android</visible>' + NL +
     '\t\t\t\t\t\t\t\t<include>KeyboardButtons</include>' + NL + '\t\t\t\t\t\t\t</control>' + NL +
     '\t\t\t\t\t\t\t<control type="button" id="32">' + NL + '\t\t\t\t\t\t\t\t<description>SPACE button</description>' + NL + '\t\t\t\t\t\t\t\t<width>335</width>', 'id="3010" description="Voice search"'),
    # Hebrew search suggestions (plugin.program.autocompletion), above the keyboard
    ('DialogKeyboard.xml',
     '\t\t</control>' + NL + '\t</controls>' + NL + '</window>',
     '\t\t</control>' + NL +
     '\t\t<control type="list" id="9010" description="Suggestions">' + NL +
     '\t\t\t<left>345</left><top>318</top><width>1230</width><height>66</height>' + NL +
     '\t\t\t<orientation>horizontal</orientation><scrolltime tween="cubic" easing="out">200</scrolltime>' + NL +
     '\t\t\t<ondown>100</ondown><onup>9010</onup>' + NL +
     '\t\t\t<animation effect="fade" start="100" end="0" time="0" condition="' + H.rtl_waiting(9010) + '">Conditional</animation>' + NL +
     '\t\t\t<visible>!Window.IsVisible(numericinput)</visible>' + NL +
     '\t\t\t<itemlayout width="306" height="66">' + NL +
     '\t\t\t\t<control type="image"><left>0</left><top>6</top><width>294</width><height>54</height>'
     '<texture border="24" colordiffuse="33FFFFFF">povil/pill48.png</texture></control>' + NL +
     '\t\t\t\t<control type="label"><left>16</left><top>6</top><width>262</width><height>54</height><font>povil_chip</font>'
     '<textcolor>povil_white</textcolor><align>center</align><aligny>center</aligny><label>$INFO[ListItem.Label]</label></control>' + NL +
     '\t\t\t</itemlayout>' + NL +
     '\t\t\t<focusedlayout width="306" height="66">' + NL +
     '\t\t\t\t<control type="image"><left>0</left><top>6</top><width>294</width><height>54</height>'
     '<texture border="24" colordiffuse="povil_gold">povil/pill48.png</texture><visible>Control.HasFocus(9010)</visible></control>' + NL +
     '\t\t\t\t<control type="image"><left>0</left><top>6</top><width>294</width><height>54</height>'
     '<texture border="24" colordiffuse="33FFFFFF">povil/pill48.png</texture><visible>!Control.HasFocus(9010)</visible></control>' + NL +
     '\t\t\t\t<control type="label"><left>16</left><top>6</top><width>262</width><height>54</height><font>povil_chip</font>'
     '<textcolor>povil_ink</textcolor><align>center</align><aligny>center</aligny><label>$INFO[ListItem.Label]</label>'
     '<visible>Control.HasFocus(9010)</visible></control>' + NL +
     '\t\t\t\t<control type="label"><left>16</left><top>6</top><width>262</width><height>54</height><font>povil_chip</font>'
     '<textcolor>povil_white</textcolor><align>center</align><aligny>center</aligny><label>$INFO[ListItem.Label]</label>'
     '<visible>!Control.HasFocus(9010)</visible></control>' + NL +
     '\t\t\t</focusedlayout>' + NL +
     '\t\t\t<content>$VAR[POVIL_AutoComplete]</content>' + NL +
     '\t\t</control>' + NL + '\t</controls>' + NL + '</window>', 'id="9010" description="Suggestions"'),
    ('Includes_Variables.xml',
     '\t<variable name="FrameColor"',
     '\t<variable name="POVIL_AutoComplete" description="Hebrew search suggestions while typing">' + NL +
     '\t\t<value condition="System.AddonIsEnabled(plugin.program.autocompletion) + !System.HasHiddenInput + !String.IsEmpty(Control.GetLabel(312).index(1))">' +
     AUTOCOMPLETE + '</value>' + NL + '\t</variable>' + NL + '\t<variable name="FrameColor"', 'name="POVIL_AutoComplete"'),
    # Skin settings: Onyx's Homepage category shapes Onyx's own home, which this skin replaces
    ('SkinSettings.xml',
     '<item id="3104" description="Homepage">' + NL + '					<label>$LOCALIZE[31102]</label>',
     '<item id="3104" description="Homepage">' + NL + '					<visible>false</visible>' + NL + '					<label>$LOCALIZE[31102]</label>'),
    # Keyboard: the layout button says which language is on, in Hebrew (Kodi writes the layout's own name)
    ('DialogKeyboard.xml',
     '\t\t\t\t\t\t\t<control type="button" id="309" description="Layout">\n\t\t\t\t\t\t\t\t<width>330</width>',
     '\t\t\t\t\t\t\t<control type="button" id="309" description="Layout">\n\t\t\t\t\t\t\t\t<width>330</width>\n\t\t\t\t\t\t\t\t<textcolor>00FFFFFF</textcolor>\n\t\t\t\t\t\t\t\t<focusedcolor>00FFFFFF</focusedcolor>'),
    ('DialogKeyboard.xml', '\t\t\t\t\t\t</control>\n\t\t\t\t\t</control>\n\t\t\t\t</control>\n\t\t\t</control>\n\t\t</control>\n\t\t<control type="list" id="9010"',
     '\t\t\t\t\t\t</control>\n\t\t\t\t\t\t<control type="label" description="Keyboard language"><left>0</left><top>312</top><width>330</width><height>72</height><font>size20</font><align>center</align><aligny>center</aligny><textcolor>povil_white</textcolor><label>$VAR[POVIL_KbLang]</label><visible>!Control.HasFocus(309)</visible></control>\n\t\t\t\t\t\t<control type="label" description="Keyboard language"><left>0</left><top>312</top><width>330</width><height>72</height><font>size20</font><align>center</align><aligny>center</aligny><textcolor>povil_ink</textcolor><label>$VAR[POVIL_KbLang]</label><visible>Control.HasFocus(309)</visible></control>\n\t\t\t\t\t</control>\n\t\t\t\t</control>\n\t\t\t</control>\n\t\t</control>\n\t\t<control type="list" id="9010"', 'description="Keyboard language"'),
    ('Includes_Variables.xml', '\t<variable name="FrameColor"',
     '\t<variable name="POVIL_KbLang" description="The keyboard layout button, in Hebrew">\n\t\t<value condition="String.Contains(Control.GetLabel(309),Hebrew)">מקלדת: עברית</value>\n\t\t<value condition="String.Contains(Control.GetLabel(309),English)">מקלדת: אנגלית</value>\n\t\t<value>$INFO[Control.GetLabel(309)]</value>\n\t</variable>\n\t<variable name="FrameColor"', 'name="POVIL_KbLang"'),
    # The skin settings, right to left (skin_settings_rtl): the shared SkinSettingsButton
    # stays as it is for add-on settings, where Kodi fills both labels itself.
    ('Includes.xml', '	<include name="DimBG">',
     '''	<include name="POVIL_SkinSettingsButton" description="SkinSettingsButton, right to left: the name on the right, a switch on its left">
		<height>81</height>
		<width>1260</width>
		<textoffsetx>20</textoffsetx>
		<focusedcolor>$VAR[FocusTextColor]</focusedcolor>
		<texturefocus border="5" colordiffuse="$VAR[FocusBoxColor]">img/MediaButton2.png</texturefocus>
		<align>right</align>
		<aligny>center</aligny>
		<font>size23</font>
		<pulseonselect>false</pulseonselect>
	</include>
	<include name="POVIL_SkinSettingsValue" description="SkinSettingsButton, right to left: the value (label) on the left, the name (label2) on the right">
		<height>81</height>
		<width>1260</width>
		<textoffsetx>20</textoffsetx>
		<focusedcolor>$VAR[FocusTextColor]</focusedcolor>
		<texturefocus border="5" colordiffuse="$VAR[FocusBoxColor]">img/MediaButton2.png</texturefocus>
		<align>left</align>
		<aligny>center</aligny>
		<font>size23</font>
		<pulseonselect>false</pulseonselect>
	</include>
	<include name="DimBG">''', 'name="POVIL_SkinSettingsButton"'),
    # The suggestions' guard, inserted above before rtl_waiting put the container's
    # label first (Kodi reads a Container(id) infolabel as text when it comes second)
    ('DialogKeyboard.xml', '!String.IsEqual(Window(home).Property(povil.rtl.9010),Container(9010).ListItemAbsolute(0).Label)',
     '!String.IsEqual(Container(9010).ListItemAbsolute(0).Label,Window(home).Property(povil.rtl.9010))'),
    # Onyx's letter jump buttons are hidden but focusable, and 9002/9003 sit over
    # the middle of the right-to-left views: a tap on a phone landed on them, and
    # left/right then paged through letters. Off while views 51/55 are shown.
    ('MyVideoNav.xml', '<control type="button" id="9001">',
     '<control type="button" id="9001">\n\t\t\t<enable>!Control.IsVisible(51) + !Control.IsVisible(55)</enable>'),
    ('MyVideoNav.xml', '<control type="button" id="9002">',
     '<control type="button" id="9002">\n\t\t\t<enable>!Control.IsVisible(51) + !Control.IsVisible(55)</enable>'),
    ('MyVideoNav.xml', '<control type="button" id="9003">',
     '<control type="button" id="9003">\n\t\t\t<enable>!Control.IsVisible(51) + !Control.IsVisible(55)</enable>'),
    # The parent folder switch: once the user sets it, the home stops turning ".." off
    ('SkinSettings.xml', '<onclick>RunScript(special://skin/scripts/onyx_tools.py,parentdir)</onclick>',
     '<onclick>Skin.SetBool(POVILParentDirChosen)</onclick>\n\t\t\t\t\t<onclick>RunScript(special://skin/scripts/onyx_tools.py,parentdir)</onclick>'),
    # Two Kodi words glued in English order: "MediumLow" -> "Medium-Low" (בינוני-נמוך),
    # "Music player" -> in Hebrew the player comes first (נגן מוזיקה)
    ('SkinSettings.xml', '$LOCALIZE[392]$LOCALIZE[391]', '$LOCALIZE[392]-$LOCALIZE[391]'),
    ('SkinSettings.xml', '$LOCALIZE[392]$LOCALIZE[393]', '$LOCALIZE[392]-$LOCALIZE[393]'),
    ('SkinSettings.xml', '<label>$LOCALIZE[249] [LOWERCASE]$LOCALIZE[14200][/LOWERCASE]</label>', '<label>$VAR[POVIL_MusicPlayer]</label>'),
    ('SkinSettings.xml', '<label>$LOCALIZE[157] [LOWERCASE]$LOCALIZE[14200][/LOWERCASE]</label>', '<label>$VAR[POVIL_VideoPlayer]</label>'),
    ('Includes_Variables.xml', '\t<variable name="FrameColor"',
     '\t<variable name="POVIL_MusicPlayer" description="Music player; Hebrew puts the player first">\n\t\t<value condition="String.StartsWith(System.Language,Hebrew)">$LOCALIZE[14200] $LOCALIZE[249]</value>\n\t\t<value>$LOCALIZE[249] [LOWERCASE]$LOCALIZE[14200][/LOWERCASE]</value>\n\t</variable>\n'
     '\t<variable name="POVIL_VideoPlayer" description="Video player; Hebrew puts the player first">\n\t\t<value condition="String.StartsWith(System.Language,Hebrew)">$LOCALIZE[14200] $LOCALIZE[157]</value>\n\t\t<value>$LOCALIZE[157] [LOWERCASE]$LOCALIZE[14200][/LOWERCASE]</value>\n\t</variable>\n\t<variable name="FrameColor"', 'name="POVIL_MusicPlayer"'),
    # Choice lists (Wizard, POV, Kodi): the item text on the right
    ('Includes_DialogSelect.xml', '<control type="label" description="Main Label">',
     '<control type="label" description="Main Label"><align>right</align><posx>96</posx>', '<align>right</align><posx>96</posx>'),
]


def power_menu(folder):
    """The power menu: the build's exit (the Wizard closes Kodi cleanly and saves),
    switch skin and profiles, in right-to-left order (the first item on the right;
    the menu opens on it)."""
    path = os.path.join(folder, 'DialogButtonMenu.xml')
    text = open(path, encoding='utf-8').read()
    marker = '<!-- POVIL power menu -->'
    if marker in text:
        return False
    wizard = 'plugin://plugin.program.kodipovilwizard/'
    text = text.replace('<onclick>Quit()</onclick>', '<onclick>RunPlugin(%s?action=force_close)</onclick>' % wizard, 1)
    start = text.index('<content>') + len('<content>')
    end = text.index('</content>')
    body = text[start:end]
    items = []
    pos = 0
    while True:
        i = body.find('<item>', pos)
        if i < 0:
            break
        j = body.index('</item>', i) + len('</item>')
        items.append(body[i:j])
        pos = j
    extra = []
    for label, icon, mode in (('החלפת סקין', 'DefaultAddonSkin.png', 'profile_skin'),
                              ('מי צופה? פרופילים', 'DefaultUser.png', 'profiles')):
        extra.append(NL.join(['<item>', '					<label>%s</label>' % label, '					<icon>%s</icon>' % icon,
                              '					<onclick>Dialog.Close(all)</onclick>',
                              '					<onclick>RunPlugin(%s?mode=%s)</onclick>' % (wizard, mode), '				</item>']))
    ordered = items[:1] + extra + items[1:]
    body = NL + '				' + marker + NL + '				' + (NL + '				').join(reversed(ordered)) + NL + '			'
    text = text[:start] + body + text[end:]
    with open(path, 'w', encoding='utf-8', newline=NL) as f:
        f.write(text)
    return True


def confirm_rtl(folder):
    """Yes/no questions: Yes on the right, No to its left, the extra button last."""
    path = os.path.join(folder, 'DialogConfirm.xml')
    text = open(path, encoding='utf-8').read()
    marker = '<!-- POVIL right to left -->'
    if marker in text:
        return False
    blocks = {}
    for bid in ('10', '11', '12'):
        start = text.index('<control type="button" id="%s">' % bid)
        end = text.index('</control>', start) + len('</control>')
        blocks[bid] = text[start:end]
    first = text.index(blocks['10'])
    last = text.index(blocks['12']) + len(blocks['12'])
    indent = NL + chr(9) * 3
    text = text[:first] + marker + indent + blocks['12'] + indent + blocks['10'] + indent + blocks['11'] + text[last:]
    with open(path, 'w', encoding='utf-8', newline=NL) as f:
        f.write(text)
    return True


def skin_settings_rtl(folder):
    """The skin settings, mirrored: the categories on the right, every setting's
    name on the right with its switch or value to its left, and the left and
    right keys swapped. Kodi always draws a button's label2 on the right, so a
    setting that shows a value swaps its two labels (the value in label, on the
    left; the name in label2). Add-on settings keep the shared button: Kodi
    fills those labels itself."""
    import re
    path = os.path.join(folder, 'SkinSettings.xml')
    text = open(path, encoding='utf-8').read()
    marker = '<!-- POVIL right to left -->'
    if marker in text:
        return False
    hold = chr(0)
    text = text.replace('<window>', '<window>' + NL + chr(9) + marker, 1)
    # keys and alignment, everywhere in the window
    text = text.replace('<onleft', hold + 'L').replace('</onleft>', hold + '/L')
    text = text.replace('<onright', '<onleft').replace('</onright>', '</onleft>')
    text = text.replace(hold + 'L', '<onright').replace(hold + '/L', '</onright>')
    text = text.replace('<align>left</align>', hold)
    text = text.replace('<align>right</align>', '<align>left</align>').replace(hold, '<align>right</align>')

    def place(old, new, count=1):
        nonlocal text
        if text.count(old) != count:
            raise SystemExit('patch_onyx: SkinSettings.xml anchor %r found %d times' % (old, text.count(old)))
        text = text.replace(old, new)

    tabs = NL + chr(9) * 3
    place('<control type="image" description="Sidebar">' + tabs + '<left>0</left>',
          '<control type="image" description="Sidebar">' + tabs + '<left>1449</left>')
    place('<texture>img/Sidebar.png</texture>', '<texture flipx="true">img/Sidebar.png</texture>')
    place('description="Left panel - categories">' + tabs + '<posx>40</posx>',
          'description="Left panel - categories">' + tabs + '<posx>1490</posx>')
    place('description="Right panel">' + tabs + '<posx>540</posx>', 'description="Right panel">' + tabs + '<posx>100</posx>')
    place('<right>35</right>', '<left>35</left>', 2)                 # the scrollbars
    place('<left>560</left>', '<left>60</left>')                     # the help line
    place('<posx>1728</posx>', '<posx>132</posx>')                   # the reset warning icon

    def labels(m):
        block = m.group(0)
        if '<align>' not in block:
            block = block.replace('>', '><align>right</align>', 1)
        # the transparency rows: their name on the right, the level on the left
        if '<left>18</left>' in block and '<width>800</width>' in block:
            block = block.replace('<left>18</left>', '<left>442</left>')
        if '<left>450</left>' in block and '<width>790</width>' in block:
            block = block.replace('<left>450</left>', '<left>20</left>')
        return block
    text = re.sub(r'<control type="(?:label|textbox)"[^>]*>.*?</control>', labels, text, flags=re.S)

    def buttons(m):
        block = m.group(0)
        name = re.search(r'<label>(.*?)</label>', block, re.S)
        value = re.search(r'<label2>(.*?)</label2>', block, re.S)
        if name and value:
            block = (block[:name.start()] + hold + 'N' + block[name.end():value.start()] + hold + 'V'
                     + block[value.end():])
            block = block.replace(hold + 'N', '<label>%s</label>' % value.group(1))
            block = block.replace(hold + 'V', '<label2>%s</label2>' % name.group(1))
            return block.replace('<include>SkinSettingsButton</include>', '<include>POVIL_SkinSettingsValue</include>')
        return block.replace('<include>SkinSettingsButton</include>', '<include>POVIL_SkinSettingsButton</include>')
    text = re.sub(r'<control type="button"[^>]*>.*?</control>', buttons, text, flags=re.S)

    def radios(m):
        block = m.group(0).replace('<include>SkinSettingsButton</include>', '<include>POVIL_SkinSettingsButton</include>')
        if '<radioposx>' in block:
            return re.sub(r'<radioposx>\d+</radioposx>', '<radioposx>20</radioposx>', block)
        return block.replace('>', '><radioposx>20</radioposx>', 1)
    text = re.sub(r'<control type="radiobutton"[^>]*>.*?</control>', radios, text, flags=re.S)
    if 'SkinSettingsButton</include>' in text.replace('POVIL_SkinSettingsButton', ''):
        raise SystemExit('patch_onyx: SkinSettings.xml has a SkinSettingsButton control of another kind')
    with open(path, 'w', encoding='utf-8', newline=NL) as f:
        f.write(text)
    return True


def main():
    folder = os.path.join(sys.argv[1], 'xml')
    applied = skipped = 0
    for edit in EDITS:
        name, old, new = edit[:3]
        path = os.path.join(folder, name)
        text = open(path, encoding='utf-8').read()
        # Inserts carry a marker: once it is there the insert is never repeated,
        # even after its own text is changed here.
        if new in text or (len(edit) > 3 and edit[3] in text):
            skipped += 1
            continue
        if old not in text:
            raise SystemExit('patch_onyx: anchor not found in %s: %s' % (name, old[:80]))
        text = text.replace(old, new)
        with open(path, 'w', encoding='utf-8', newline=NL) as f:
            f.write(text)
        applied += 1
    if power_menu(folder):
        applied += 1
    if confirm_rtl(folder):
        applied += 1
    if skin_settings_rtl(folder):
        applied += 1
    print('onyx edits: %d applied, %d already there' % (applied, skipped))


if __name__ == '__main__':
    main()
