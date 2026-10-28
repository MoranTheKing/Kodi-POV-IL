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
    print('onyx edits: %d applied, %d already there' % (applied, skipped))


if __name__ == '__main__':
    main()
