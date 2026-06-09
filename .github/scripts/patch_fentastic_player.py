#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

LABEL = "\u05e9\u05e0\u05d4 \u05e0\u05d2\u05df"
REGULAR = "\u05e0\u05d2\u05df \u05e8\u05d2\u05d9\u05dc"
ADVANCED = "\u05e0\u05d2\u05df \u05de\u05ea\u05e7\u05d3\u05dd"
VAR_NAME = "osdchangeplayervar"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def set_default_regular(root: Path) -> None:
    path = root / "userdata" / "addon_data" / "skin.fentastic" / "settings.xml"
    if not path.is_file():
        return
    text = read_text(path)
    item = '<setting id="chooseosdplayer" type="bool">true</setting>'
    text = re.sub(r'<setting id="chooseosdplayer" type="bool">(?:true|false)</setting>', item, text, count=1)
    if "chooseosdplayer" not in text and "</settings>" in text:
        text = text.replace("</settings>", "    " + item + "\n</settings>", 1)
    write_text(path, text)


def patch_video_osd(xml_dir: Path) -> None:
    path = xml_dir / "VideoOSD.xml"
    text = read_text(path)
    switch = (
        '<include condition="Skin.HasSetting(chooseosdplayer)">videosd2</include>\n'
        '\t<include condition="!Skin.HasSetting(chooseosdplayer)">videosd1</include>'
    )
    text = re.sub(
        r'<include[^>]*Skin\.HasSetting\(chooseosdplayer\)[^>]*>videosd[12]</include>\s*<include[^>]*!Skin\.HasSetting\(chooseosdplayer\)[^>]*>videosd[12]</include>(?:\s*<!--[^>]*videosd2[^>]*-->)?',
        switch,
        text,
        count=1,
    )
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
        block = "\n".join([
            "                        <item>",
            "                            <!-- KODI-POV-IL - Toggle FENtastic player -->",
            f"                            <label>[B][COLOR blue]{LABEL}[/COLOR][/B]</label>",
            f"                            <label2>$VAR[{VAR_NAME}]</label2>",
            "                            <onclick>Skin.ToggleSetting(chooseosdplayer)</onclick>",
            "                            <onclick>Dialog.Close(all)</onclick>",
            "                            <onclick>ReloadSkin()</onclick>",
            "                        </item>",
        ])
        idx = text.find("<!-- Reload skin -->")
        end = text.find("</item>", idx)
        if idx >= 0 and end >= 0:
            text = text[:end + len("</item>")] + "\n" + block + text[end + len("</item>"):]
    else:
        text = text.replace("Skin.SetBool(chooseosdplayer)", "Skin.ToggleSetting(chooseosdplayer)")
        text = text.replace("$VAR[OSDPlayerModeVar]", f"$VAR[{VAR_NAME}]")
    write_text(path, text)


def patch_osd_settings_menu(xml_dir: Path) -> None:
    path = xml_dir / "Includes_Items.xml"
    text = read_text(path)
    marker = "KODI-POV-IL - OSD player mode"
    if marker not in text:
        block = "\n".join([
            "        <item>",
            "            <!-- KODI-POV-IL - OSD player mode -->",
            f"            <label>{LABEL}</label>",
            f"            <label2>$VAR[{VAR_NAME}]</label2>",
            "            <onclick>Skin.ToggleSetting(chooseosdplayer)</onclick>",
            "            <onclick>ReloadSkin()</onclick>",
            "        </item>",
        ])
        idx = text.find('<include name="BasedMenuOsdSecondMenu">')
        end = text.find("</content>", idx)
        if idx >= 0 and end >= 0:
            text = text[:end] + block + "\n" + text[end:]
    else:
        text = text.replace("Skin.SetBool(chooseosdplayer)", "Skin.ToggleSetting(chooseosdplayer)")
        text = text.replace("$VAR[OSDPlayerModeVar]", f"$VAR[{VAR_NAME}]")
    write_text(path, text)


def patch_variables(xml_dir: Path) -> None:
    path = xml_dir / "Variables.xml"
    text = read_text(path)
    block = "\n".join([
        "",
        f'    <variable name="{VAR_NAME}">',
        f'        <value condition="Skin.HasSetting(chooseosdplayer)">{REGULAR}</value>',
        f"        <value>{ADVANCED}</value>",
        "    </variable>",
        "",
    ])
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
    for dep in ["Includes.xml", "Includes_VideoOsd.xml", "Includes_VideoOsd2.xml", "Includes_Buttons.xml", "Includes_Items.xml", "Variables.xml"]:
        if not (xml_dir / dep).is_file():
            raise SystemExit(f"missing dependency {dep}")
    includes = read_text(xml_dir / "Includes.xml")
    if 'include name="syncfakebutton"' not in includes or 'include name="TouchBackOSDButton"' not in includes:
        raise SystemExit("videosd2 dependencies are missing from Includes.xml")
    settings = root / "userdata" / "addon_data" / "skin.fentastic" / "settings.xml"
    if settings.is_file() and '<setting id="chooseosdplayer" type="bool">true</setting>' not in read_text(settings):
        raise SystemExit("chooseosdplayer default is not true")
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
    set_default_regular(root)
    patch_video_osd(xml_dir)
    patch_power_menu(xml_dir)
    patch_osd_settings_menu(xml_dir)
    patch_variables(xml_dir)
    verify(root, xml_dir)
    print("FENtastic player switch mapped to Tal OSD files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
