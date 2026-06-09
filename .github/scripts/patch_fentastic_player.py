#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

LABEL = "\u05d1\u05d7\u05e8 \u05e0\u05d2\u05df"
REGULAR = "\u05e0\u05d2\u05df \u05e8\u05d2\u05d9\u05dc"
ADVANCED = "\u05e0\u05d2\u05df \u05de\u05ea\u05e7\u05d3\u05dd"
VAR_NAME = "osdchangeplayervar"


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
    set_setting(root, "chooseosdplayer", "true")
    set_setting(root, "disableidan", "false")
    set_setting(root, "playerclosedelay", "false")
    set_setting(root, "playerplaylist_osd", "false")


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
	<expression name="MoviesTvShowsExpression_OSD">VideoPlayer.Content(movies) | VideoPlayer.Content(episodes)</expression>
	<expression name="LivetvExpressionEPG_OSD">VideoPlayer.Content(LiveTv) + VideoPlayer.HasEpg</expression>
	<expression name="Visibilty_Plot_OSd">String.IsEmpty(VideoPlayer.Plot)</expression>
	<expression name="IDANPlusCheck_OSd">String.Contains(Player.FolderPath,idanplus)</expression>
	<expression name="NextItemExist_OSd">!String.IsEmpty(VideoPlayer.offset(1).Title)</expression>
	<expression name="PreviousItemExist_OSd">!String.IsEmpty(VideoPlayer.offset(-1).Title)</expression>
	<expression name="PreviousNextItemCheck">[Container(201).HasFocus(100) + String.IsEmpty(VideoPlayer.offset(-1).Title)] | [Container(201).HasFocus(109) + String.IsEmpty(VideoPlayer.offset(1).Title)]</expression>
"""
        text = text.replace("</includes>", block + "</includes>", 1)
    write_text(path, text)


def apply_tal_variables(xml_dir: Path) -> None:
    path = xml_dir / "Variables.xml"
    text = read_text(path)
    if 'name="middlelabelInfo_OSD_Var"' not in text:
        block = """
	<variable name="middlelabelInfo_OSD_Var">
	<value condition="$EXP[MoviesTvShowsExpression_OSD]">$INFO[VideoPlayer.Genre]</value>
	<value condition="$EXP[LivetvExpressionEPG_OSD]">מתחיל [COLOR button_focus]$INFO[VideoPlayer.StartTime][/COLOR] מסתיים [COLOR button_focus]$INFO[VideoPlayer.EndTime][/COLOR]</value>
	<value>No Information</value>
	</variable>
	
	<variable name="middlelabelInfo_Next_OSD_Var">
	<value condition="!String.IsEmpty(VideoPlayer.offset(1).Genre)">$INFO[VideoPlayer.offset(1).Genre]</value>
	<value condition="VideoPlayer.Content(LiveTv) + VideoPlayer.HasEpg">מתחיל [COLOR button_focus]$INFO[VideoPlayer.NextStartTime][/COLOR] מסתיים [COLOR button_focus]$INFO[VideoPlayer.NextEndTime][/COLOR]</value>
	<value>No Information</value>
	</variable>
	
	<variable name="NextTitleInfo_Next_OSD">
	<value condition="!String.IsEmpty(VideoPlayer.offset(1).Title)">$INFO[VideoPlayer.offset(1).Title]</value>
	<value condition="!String.IsEmpty(Player.offset(1).Title)">$INFO[Player.offset(1).Title]</value>
	<value>No Title</value>
	</variable>
	
	<variable name="PreviousTitleInfo_Next_OSD">
	<value condition="!String.IsEmpty(VideoPlayer.offset(-1).Title)">$INFO[VideoPlayer.offset(-1).Title]</value>
	<value condition="!String.IsEmpty(Player.offset(-1).Title)">$INFO[Player.offset(-1).Title]</value>
	<value>No Title</value>
	</variable>
	
	<variable name="NextTitleInfoYear_Next_OSD">
	<value condition="!String.IsEmpty(VideoPlayer.offset(1).Year)">$INFO[VideoPlayer.offset(1).Year]</value>
	<value condition="!String.IsEmpty(Player.offset(1).Year)">$INFO[Player.offset(1).Year]</value>
	</variable>
	
	<variable name="PreviousTitleInfoYear_Next_OSD">
	<value condition="!String.IsEmpty(VideoPlayer.offset(-1).Year)">$INFO[VideoPlayer.offset(-1).Year]</value>
	<value condition="!String.IsEmpty(Player.offset(-1).Year)">$INFO[Player.offset(-1).Year]</value>
	</variable>

	<variable name="middlelabelInfo_Previous_OSD_Var">
	<value condition="!String.IsEmpty(VideoPlayer.offset(-1).Genre)">$INFO[VideoPlayer.offset(-1).Genre]</value>
	<value>No Information</value>
	</variable>
	
	<variable name="bottomlabelinfo_Previous_OSD_Var">
	<value>$INFO[VideoPlayer.offset(-1).Plot]</value>
	</variable>

	<variable name="bottomlabelinfo_Next_OSD_Var">
	<value>$INFO[VideoPlayer.offset(1).Plot]</value>
	</variable>
	
	<variable name="NextShowIcon_OSD_Var">
	<value condition="!String.IsEmpty(VideoPlayer.offset(1).Cover)">$INFO[VideoPlayer.offset(1).Cover]</value>
	<value condition="!String.IsEmpty(VideoPlayer.offset(1).Icon)">$INFO[VideoPlayer.offset(1).Icon]</value>	
	</variable>
	
	<variable name="PreviousShowIcon_OSD_Var">
	<value condition="!String.IsEmpty(VideoPlayer.offset(-1).Cover)">$INFO[VideoPlayer.offset(-1).Cover]</value>
	<value condition="!String.IsEmpty(VideoPlayer.offset(-1).Icon)">$INFO[VideoPlayer.offset(-1).Icon]</value>
	<value condition="!String.IsEmpty(VideoPlayer.offset(-1).Icon)">$INFO[VideoPlayer.offset(-1).Icon]</value>
	</variable>

"""
        marker = '<variable name="_FixaudiolangugeOsd">'
        text = text.replace(marker, block + marker, 1)
    write_text(path, text)


def apply_tal_videoosd1(xml_dir: Path) -> None:
    path = xml_dir / "Includes_VideoOsd.xml"
    text = read_text(path)
    text = text.replace('<icon>osd/fullscreen/buttons/previous.png</icon>\n\t\t\t<onclick>SkipPrevious</onclick>', '<icon>osd/fullscreen/buttons/previous.png</icon>\n\t\t\t<property name="id">previous</property>\n\t\t\t<onclick>SkipPrevious</onclick>', 1)
    text = text.replace('<icon>osd/fullscreen/buttons/next.png</icon>\n\t\t\t<onclick>SkipNext</onclick>', '<icon>osd/fullscreen/buttons/next.png</icon>\n\t\t\t<property name="id">next</property>\n\t\t\t<onclick>SkipNext</onclick>', 1)
    new_info = """<!-- OSD CURRENT INFO -->
<include content="PoweredOsdInfo">
<param name="groupheight">550</param>
<param name="texture">$VAR[_FixOsdIcon]</param>
<param name="bottomlabel">$INFO[VideoPlayer.Plot]</param>
<param name="middlelabel">$VAR[middlelabelInfo_OSD_Var]</param>
<param name="grouplistheight">250</param>
<param name="visible">String.IsEqual(Container(201).ListItem.Property(info),info) + !$EXP[IDANPlusCheck_OSd]</param>
</include>
<include content="PoweredOsdInfo">
<param name="groupheight">250</param>
<param name="texture">$INFO[Player.Icon]</param>
<param name="bottomlabel">$INFO[VideoPlayer.Plot]</param>
<param name="middlelabel">$VAR[middlelabelInfo_OSD_Var]</param>
<param name="grouplistheight">150</param>
<param name="visible">String.IsEqual(Container(201).ListItem.Property(info),info) + $EXP[IDANPlusCheck_OSd]</param>
</include>
<!-- END OSD CURRENT INFO -->

<!-- OSD NEXT SHOW INFO -->
<include content="PoweredOsdInfo">
<param name="groupheight">250</param>
<param name="texture">$VAR[NextShowIcon_OSD_Var]</param>
<param name="label">$VAR[NextTitleInfo_Next_OSD] $VAR[NextTitleInfoYear_Next_OSD]</param>
<param name="bottomlabel">$VAR[bottomlabelinfo_Next_OSD_Var]</param>
<param name="middlelabel">$VAR[middlelabelInfo_Next_OSD_Var]</param>
<param name="grouplistheight">150</param>
<param name="visible">String.IsEqual(Container(201).ListItem.Property(id),next) + $EXP[IDANPlusCheck_OSd] + $EXP[NextItemExist_OSd]</param>
</include>
<!-- END OSD NEXT SHOW INFO -->

<!-- OSD PREVIOUS SHOW INFO -->
<include content="PoweredOsdInfo">
<param name="groupheight">250</param>
<param name="texture">$VAR[PreviousShowIcon_OSD_Var]</param>
<param name="label">$VAR[PreviousTitleInfo_Next_OSD] $VAR[PreviousTitleInfoYear_Next_OSD]</param>
<param name="bottomlabel">$VAR[bottomlabelinfo_Previous_OSD_Var]</param>
<param name="middlelabel">$VAR[middlelabelInfo_Previous_OSD_Var]</param>
<param name="grouplistheight">150</param>
<param name="visible">String.IsEqual(Container(201).ListItem.Property(id),previous) + $EXP[IDANPlusCheck_OSd] + $EXP[PreviousItemExist_OSd]</param>
</include>
<!-- END OSD PREVIOUS SHOW INFO -->

<include>_FixedCachedOSd</include>"""
    text = re.sub(r'<!-- OSD INFO -->.*?<include>_FixedCachedOSd</include>', new_info, text, count=1, flags=re.S)
    text = text.replace('<label>$INFO[VideoPlayer.Genre]</label>\n\t\t<visible>!String.IsEmpty(VideoPlayer.Genre)</visible>', '<label>$PARAM[middlelabel]</label>', 1)
    text = text.replace('<label>$INFO[VideoPlayer.Plot]</label>', '<label>$PARAM[bottomlabel]</label>\n\t\t<visible>$PARAM[bottomlabevisible]</visible> <!-- IF NO PLOT -->', 1)
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
    text = re.sub(r'<include[^>]*Skin\.HasSetting\(chooseosdplayer\)[^>]*>videosd[12]</include>\s*<include[^>]*!Skin\.HasSetting\(chooseosdplayer\)[^>]*>videosd[12]</include>(?:\s*<!--[^>]*videosd2[^>]*-->)?', switch, text, count=1)
    if "Skin.HasSetting(chooseosdplayer)" not in text:
        text = text.replace("<include>videosd1</include>", switch, 1)
    write_text(path, text)


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
    marker = "KODI-POV-IL - Toggle FENtastic player"
    if marker not in text:
        block = "\n".join(["                        <item>", "                            <!-- KODI-POV-IL - Toggle FENtastic player -->", f"                            <label>[B][COLOR blue]{LABEL}[/COLOR][/B]</label>", f"                            <label2>$VAR[{VAR_NAME}]</label2>", "                            <onclick>Skin.ToggleSetting(chooseosdplayer)</onclick>", "                            <onclick>Dialog.Close(all)</onclick>", "                            <onclick>ReloadSkin()</onclick>", "                        </item>"])
        idx = text.find("<!-- Reload skin -->")
        end = text.find("</item>", idx)
        if idx >= 0 and end >= 0:
            text = text[:end + len("</item>")] + "\n" + block + text[end + len("</item>"):]
    else:
        text = text.replace("Skin.SetBool(chooseosdplayer)", "Skin.ToggleSetting(chooseosdplayer)").replace("$VAR[OSDPlayerModeVar]", f"$VAR[{VAR_NAME}]")
    write_text(path, text)


def patch_osd_settings_menu(xml_dir: Path) -> None:
    path = xml_dir / "Includes_Items.xml"
    text = read_text(path)
    marker = "KODI-POV-IL - OSD player mode"
    if marker not in text:
        block = "\n".join(["        <item>", "            <!-- KODI-POV-IL - OSD player mode -->", f"            <label>{LABEL}</label>", f"            <label2>$VAR[{VAR_NAME}]</label2>", "            <onclick>Skin.ToggleSetting(chooseosdplayer)</onclick>", "            <onclick>ReloadSkin()</onclick>", "        </item>"])
        idx = text.find('<include name="BasedMenuOsdSecondMenu">')
        end = text.find("</content>", idx)
        if idx >= 0 and end >= 0:
            text = text[:end] + block + "\n" + text[end:]
    else:
        text = text.replace("Skin.SetBool(chooseosdplayer)", "Skin.ToggleSetting(chooseosdplayer)").replace("$VAR[OSDPlayerModeVar]", f"$VAR[{VAR_NAME}]")
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
    video = read_text(xml_dir / "VideoOSD.xml")
    if 'Skin.HasSetting(chooseosdplayer)">videosd2</include>' not in video:
        raise SystemExit("true state is not mapped to videosd2 regular player")
    if '!Skin.HasSetting(chooseosdplayer)">videosd1</include>' not in video:
        raise SystemExit("false state is not mapped to videosd1 advanced player")
    for dep in ["Includes.xml", "Includes_VideoOsd.xml", "Includes_VideoOsd2.xml", "Includes_Buttons.xml", "Includes_Items.xml", "Variables.xml", "Includes_Expression.xml"]:
        if not (xml_dir / dep).is_file():
            raise SystemExit(f"missing dependency {dep}")
    variables = read_text(xml_dir / "Variables.xml")
    expressions = read_text(xml_dir / "Includes_Expression.xml")
    video1 = read_text(xml_dir / "Includes_VideoOsd.xml")
    for needle in ["middlelabelInfo_OSD_Var", "NextShowIcon_OSD_Var", VAR_NAME]:
        if needle not in variables:
            raise SystemExit(f"missing variable {needle}")
    for needle in ["IDANPlusCheck_OSd", "PreviousNextItemCheck"]:
        if needle not in expressions:
            raise SystemExit(f"missing expression {needle}")
    if 'property name="id">previous' not in video1 or 'property name="id">next' not in video1:
        raise SystemExit("Tal previous/next OSD properties missing")
    if "SubtitleDelayPlus" not in video1 or "SubtitleDelayMinus" not in video1:
        raise SystemExit("subtitle delay actions missing")
    for name in ["DialogButtonMenu.xml", "Includes_Items.xml"]:
        text = read_text(xml_dir / name)
        if LABEL not in text or "Skin.ToggleSetting(chooseosdplayer)" not in text or f"$VAR[{VAR_NAME}]" not in text:
            raise SystemExit(f"{name} missing Tal-style toggle")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_fentastic_player.py <extracted-root>")
    root = Path(sys.argv[1])
    xml_dir = root / "addons" / "skin.fentastic" / "xml"
    if not xml_dir.is_dir():
        raise SystemExit(f"FENtastic XML folder not found: {xml_dir}")
    apply_tal_settings(root)
    apply_tal_expressions(xml_dir)
    apply_tal_variables(xml_dir)
    apply_tal_videoosd1(xml_dir)
    keep_user_subtitle_delay(xml_dir)
    patch_video_osd_switch(xml_dir)
    patch_power_menu(xml_dir)
    patch_osd_settings_menu(xml_dir)
    patch_player_var(xml_dir)
    verify(root, xml_dir)
    print("FENtastic Tal full player update applied with user subtitle delay")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
