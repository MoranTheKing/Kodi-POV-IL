#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

LABEL = "בחר נגן"
REGULAR = "נגן רגיל"
ADVANCED = "נגן מתקדם"
VAR_NAME = "osdchangeplayervar"
SELECT_ACTION = "RunPlugin(plugin://plugin.program.kodipovilwizard/?mode=install&amp;action=fentastic_select_player)"
BACKPLATE_MARKER = "KODI-POV-IL - OSD bottom backplate"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def set_setting(root: Path, setting_id: str, value: str) -> None:
    path = root / "userdata" / "addon_data" / "skin.fentastic" / "settings.xml"
    if not path.is_file():
        return
    text = read_text(path)
    pattern = rf'<setting id="{re.escape(setting_id)}" type="bool">(?:true|false)</setting>'
    item = f'<setting id="{setting_id}" type="bool">{value}</setting>'
    if re.search(pattern, text):
        text = re.sub(pattern, item, text, count=1)
    elif "</settings>" in text:
        text = text.replace("</settings>", "    " + item + "\n</settings>", 1)
    write_text(path, text)


def apply_tal_settings(root: Path) -> None:
    # true = regular/simple player, false = advanced player
    set_setting(root, "chooseosdplayer", "true")
    set_setting(root, "disableidan", "false")
    set_setting(root, "playerclosedelay", "false")
    set_setting(root, "playerplaylist_osd", "false")


def ensure_videoosd2_is_loaded(xml_dir: Path) -> None:
    path = xml_dir / "Includes.xml"
    text = read_text(path)
    if 'Includes_VideoOsd2.xml' not in text:
        text = text.replace(
            '<include file="Includes_VideoOsd.xml" />',
            '<include file="Includes_VideoOsd.xml" />\n\t<include file="Includes_VideoOsd2.xml" />',
            1,
        )
    write_text(path, text)


def apply_tal_expressions(xml_dir: Path) -> None:
    path = xml_dir / "Includes_Expression.xml"
    text = read_text(path)
    text = re.sub(
        r'<expression name="OsdFlagsVisible">.*?</expression>',
        '<expression name="OsdFlagsVisible">Container(201).HasFocus(101) | Container(201).HasFocus(102) | Container(201).HasFocus(103) | Container(201).HasFocus(104) | Container(201).HasFocus(105) | Container(201).HasFocus(106) | Container(201).HasFocus(107) | Container(201).HasFocus(108) | Container(201).HasFocus(110) | Container(201).HasFocus(111) | $EXP[PreviousNextItemCheck]</expression>',
        text,
        count=1,
    )
    if 'name="MoviesTvShowsExpression_OSD"' not in text:
        block = """
\t<expression name="MoviesTvShowsExpression_OSD">VideoPlayer.Content(movies) | VideoPlayer.Content(episodes)</expression>
\t<expression name="LivetvExpressionEPG_OSD">VideoPlayer.Content(LiveTv) + VideoPlayer.HasEpg</expression>
\t<expression name="Visibilty_Plot_OSd">String.IsEmpty(VideoPlayer.Plot)</expression>
\t<expression name="IDANPlusCheck_OSd">String.Contains(Player.FolderPath,idanplus)</expression>
\t<expression name="NextItemExist_OSd">!String.IsEmpty(VideoPlayer.offset(1).Title)</expression>
\t<expression name="PreviousItemExist_OSd">!String.IsEmpty(VideoPlayer.offset(-1).Title)</expression>
\t<expression name="PreviousNextItemCheck">[Container(201).HasFocus(100) + String.IsEmpty(VideoPlayer.offset(-1).Title)] | [Container(201).HasFocus(109) + String.IsEmpty(VideoPlayer.offset(1).Title)]</expression>
"""
        text = text.replace("</includes>", block + "</includes>", 1)
    write_text(path, text)


def apply_tal_variables(xml_dir: Path) -> None:
    path = xml_dir / "Variables.xml"
    text = read_text(path)
    if 'name="middlelabelInfo_OSD_Var"' not in text:
        block = """
\t<variable name="middlelabelInfo_OSD_Var">
\t<value condition="$EXP[MoviesTvShowsExpression_OSD]">$INFO[VideoPlayer.Genre]</value>
\t<value condition="$EXP[LivetvExpressionEPG_OSD]">מתחיל [COLOR button_focus]$INFO[VideoPlayer.StartTime][/COLOR] מסתיים [COLOR button_focus]$INFO[VideoPlayer.EndTime][/COLOR]</value>
\t<value>No Information</value>
\t</variable>
\t<variable name="NextShowIcon_OSD_Var">
\t<value condition="!String.IsEmpty(VideoPlayer.offset(1).Cover)">$INFO[VideoPlayer.offset(1).Cover]</value>
\t<value condition="!String.IsEmpty(VideoPlayer.offset(1).Icon)">$INFO[VideoPlayer.offset(1).Icon]</value>
\t</variable>
"""
        marker = '<variable name="_FixaudiolangugeOsd">'
        text = text.replace(marker, block + marker, 1)
    write_text(path, text)


def apply_tal_videoosd1(xml_dir: Path) -> None:
    path = xml_dir / "Includes_VideoOsd.xml"
    text = read_text(path)
    text = text.replace('<icon>osd/fullscreen/buttons/previous.png</icon>\n\t\t\t<onclick>SkipPrevious</onclick>', '<icon>osd/fullscreen/buttons/previous.png</icon>\n\t\t\t<property name="id">previous</property>\n\t\t\t<onclick>SkipPrevious</onclick>', 1)
    text = text.replace('<icon>osd/fullscreen/buttons/next.png</icon>\n\t\t\t<onclick>SkipNext</onclick>', '<icon>osd/fullscreen/buttons/next.png</icon>\n\t\t\t<property name="id">next</property>\n\t\t\t<onclick>SkipNext</onclick>', 1)
    write_text(path, text)


def keep_user_subtitle_delay(xml_dir: Path) -> None:
    path = xml_dir / "Includes_VideoOsd.xml"
    text = read_text(path)
    text = re.sub(r'(<item id="110">.*?<onclick>)(SubtitleDelayMinus|SubtitleDelayPlus)(</onclick>.*?</item>)', r'\1SubtitleDelayPlus\3', text, count=1, flags=re.S)
    text = re.sub(r'(<item id="111">.*?<onclick>)(SubtitleDelayMinus|SubtitleDelayPlus)(</onclick>.*?</item>)', r'\1SubtitleDelayMinus\3', text, count=1, flags=re.S)
    write_text(path, text)


def patch_video_osd_switch(xml_dir: Path) -> None:
    path = xml_dir / "VideoOSD.xml"
    text = read_text(path)
    switch = '<include condition="Skin.HasSetting(chooseosdplayer)">videosd2</include>\n\t<include condition="!Skin.HasSetting(chooseosdplayer)">videosd1</include>'
    text = re.sub(
        r'<include[^>]*Skin\.HasSetting\(chooseosdplayer\)[^>]*>videosd[12]</include>\s*<include[^>]*!Skin\.HasSetting\(chooseosdplayer\)[^>]*>videosd[12]</include>',
        switch,
        text,
        count=1,
        flags=re.S,
    )
    if "Skin.HasSetting(chooseosdplayer)" not in text:
        text = text.replace("<include>videosd1</include>", switch, 1)
    write_text(path, text)


def patch_osd_backplates(xml_dir: Path) -> None:
    """Add a solid dark rail behind the OSD controls so white icons stay readable on bright video."""
    video1_path = xml_dir / "Includes_VideoOsd.xml"
    text = read_text(video1_path)
    if BACKPLATE_MARKER not in text:
        block = """\n\t\t\t<!-- KODI-POV-IL - OSD bottom backplate -->
\t\t\t<control type=\"image\">
\t\t\t\t<left>-40</left>
\t\t\t\t<width>120%</width>
\t\t\t\t<height>110</height>
\t\t\t\t<bottom>0</bottom>
\t\t\t\t<texture>colors/black.png</texture>
\t\t\t\t<colordiffuse>B0000000</colordiffuse>
\t\t\t</control>"""
        marker = "\t\t\t<!-- OSD MAIN MENU -->"
        if marker in text:
            text = text.replace(marker, block + "\n" + marker, 1)
        else:
            text = text.replace('<control type="list" id="201">', block + '\n\t\t\t<control type="list" id="201">', 1)
    write_text(video1_path, text)

    video2_path = xml_dir / "Includes_VideoOsd2.xml"
    if not video2_path.is_file():
        return
    text = read_text(video2_path)
    if BACKPLATE_MARKER not in text:
        block = """\n\t\t\t\t<!-- KODI-POV-IL - OSD bottom backplate -->
\t\t\t\t<control type=\"image\">
\t\t\t\t\t<left>0</left>
\t\t\t\t\t<bottom>0</bottom>
\t\t\t\t\t<width>100%</width>
\t\t\t\t\t<height>180</height>
\t\t\t\t\t<texture>colors/black.png</texture>
\t\t\t\t\t<colordiffuse>B0000000</colordiffuse>
\t\t\t\t</control>"""
        marker = '<animation effect="fade" time="200">VisibleChange</animation>'
        if marker in text:
            text = text.replace(marker, marker + block, 1)
        else:
            text = text.replace('<control type="label">', block + '\n\t\t\t\t<control type="label">', 1)
    write_text(video2_path, text)


def inline_taller_power_menu_list(xml_dir: Path, text: str) -> str:
    if "KODI-POV-IL - Taller power menu list" in text:
        return text
    includes_path = xml_dir / "Includes_Buttons.xml"
    if not includes_path.is_file():
        return text
    includes_text = read_text(includes_path)
    start = includes_text.find('<include name="ButtonMenuList">')
    end = includes_text.find("\n\t</include>", start)
    if start < 0 or end < 0:
        return text
    end += len("\n\t</include>")
    inner = includes_text[start:end].split("\n", 1)[1].rsplit("\n\t</include>", 1)[0]
    inner = inner.replace("<height>380</height>", "<height>455</height>", 1)
    inner = "\t\t\t\t<!-- KODI-POV-IL - Taller power menu list -->\n" + inner
    return text.replace("\t\t\t\t<include>ButtonMenuList</include>", inner, 1)


def patch_power_menu(xml_dir: Path) -> None:
    path = xml_dir / "DialogButtonMenu.xml"
    text = read_text(path)
    text = text.replace('<param name="height" value="485" />', '<param name="height" value="560" />', 1)
    text = inline_taller_power_menu_list(xml_dir, text)
    text = re.sub(r'\s*<item>\s*<!-- KODI-POV-IL - (?:Toggle FENtastic player|Open FENtastic player selector) -->.*?</item>', '', text, count=1, flags=re.S)
    block = "\n".join([
        "                        <item>",
        "                            <!-- KODI-POV-IL - Open FENtastic player selector -->",
        f"                            <label>[B][COLOR blue]{LABEL}[/COLOR][/B]</label>",
        f"                            <label2>$VAR[{VAR_NAME}]</label2>",
        f"                            <onclick>{SELECT_ACTION}</onclick>",
        "                        </item>",
    ])
    idx = text.find("<!-- Reload skin -->")
    end = text.find("</item>", idx)
    if idx >= 0 and end >= 0 and "fentastic_select_player" not in text:
        text = text[:end + len("</item>")] + "\n" + block + text[end + len("</item>"):]
    write_text(path, text)


def patch_osd_settings_menu(xml_dir: Path) -> None:
    path = xml_dir / "Includes_Items.xml"
    text = read_text(path)
    text = re.sub(r'\s*<item>\s*<!-- KODI-POV-IL - OSD player mode -->.*?</item>', '', text, count=1, flags=re.S)
    block = "\n".join([
        "        <item>",
        "            <!-- KODI-POV-IL - OSD player mode -->",
        f"            <label>{LABEL}</label>",
        f"            <label2>$VAR[{VAR_NAME}]</label2>",
        f"            <onclick>{SELECT_ACTION}</onclick>",
        "        </item>",
    ])
    idx = text.find('<include name="BasedMenuOsdSecondMenu">')
    end = text.find("</content>", idx)
    if idx >= 0 and end >= 0:
        text = text[:end] + block + "\n" + text[end:]
    write_text(path, text)


def patch_player_var(xml_dir: Path) -> None:
    path = xml_dir / "Variables.xml"
    text = read_text(path)
    block = "\n".join(["", f'    <variable name="{VAR_NAME}">', f'        <value condition="Skin.HasSetting(chooseosdplayer)">{REGULAR}</value>', f"        <value>{ADVANCED}</value>", "    </variable>", ""])
    if f'<variable name="{VAR_NAME}">' in text:
        text = re.sub(r'<variable name="' + VAR_NAME + r'">.*?</variable>', block, text, count=1, flags=re.S)
    else:
        text = text.replace("</includes>", block + "</includes>", 1)
    text = re.sub(r'<variable name="OSDPlayerModeVar">.*?</variable>', '', text, count=1, flags=re.S)
    write_text(path, text)


def verify(root: Path, xml_dir: Path) -> None:
    includes = read_text(xml_dir / "Includes.xml")
    video = read_text(xml_dir / "VideoOSD.xml")
    variables = read_text(xml_dir / "Variables.xml")
    power = read_text(xml_dir / "DialogButtonMenu.xml")
    items = read_text(xml_dir / "Includes_Items.xml")
    video1 = read_text(xml_dir / "Includes_VideoOsd.xml")
    video2 = read_text(xml_dir / "Includes_VideoOsd2.xml") if (xml_dir / "Includes_VideoOsd2.xml").is_file() else ""
    if 'Includes_VideoOsd2.xml' not in includes:
        raise SystemExit("Includes.xml does not load Includes_VideoOsd2.xml")
    if 'Skin.HasSetting(chooseosdplayer)">videosd2</include>' not in video:
        raise SystemExit("regular player is not mapped to videosd2")
    if '!Skin.HasSetting(chooseosdplayer)">videosd1</include>' not in video:
        raise SystemExit("advanced player is not mapped to videosd1")
    if 'osdchangeplayervar' not in variables:
        raise SystemExit("missing Tal label variable")
    if 'fentastic_select_player' not in power or 'Skin.ToggleSetting(chooseosdplayer)' in power:
        raise SystemExit("power button is not using safe selector dialog")
    if 'fentastic_select_player' not in items or 'Skin.ToggleSetting(chooseosdplayer)' in items:
        raise SystemExit("OSD settings button is not using safe selector dialog")
    if BACKPLATE_MARKER not in video1 or BACKPLATE_MARKER not in video2:
        raise SystemExit("OSD bottom backplate is missing")
    settings = root / "userdata" / "addon_data" / "skin.fentastic" / "settings.xml"
    if settings.is_file() and '<setting id="chooseosdplayer" type="bool">true</setting>' not in read_text(settings):
        raise SystemExit("default player is not regular/simple")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_fentastic_player.py <extracted-root>")
    root = Path(sys.argv[1])
    xml_dir = root / "addons" / "skin.fentastic" / "xml"
    if not xml_dir.is_dir():
        raise SystemExit(f"FENtastic XML folder not found: {xml_dir}")
    apply_tal_settings(root)
    ensure_videoosd2_is_loaded(xml_dir)
    apply_tal_expressions(xml_dir)
    apply_tal_variables(xml_dir)
    apply_tal_videoosd1(xml_dir)
    keep_user_subtitle_delay(xml_dir)
    patch_video_osd_switch(xml_dir)
    patch_osd_backplates(xml_dir)
    patch_power_menu(xml_dir)
    patch_osd_settings_menu(xml_dir)
    patch_player_var(xml_dir)
    verify(root, xml_dir)
    print("FENtastic Tal player selector applied with readable OSD backplate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
