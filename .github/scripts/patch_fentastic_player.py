#!/usr/bin/env python3
"""Patch FENtastic player-switch integration before packaging.

This script is used by the Publish FENtastic Player Update workflow.
It works on an extracted build/quickfix root that contains:
  addons/skin.fentastic/xml/...

It intentionally fails hard if the expected anchors are missing, so a bad
Quick Update is not published silently.
"""

from __future__ import annotations

import sys
from pathlib import Path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def patch_video_osd(xml_dir: Path) -> None:
    path = xml_dir / "VideoOSD.xml"
    text = read_text(path)
    old = "<include>videosd1</include>"
    new = (
        '<include condition="Skin.HasSetting(chooseosdplayer)">videosd1</include>\n'
        '<include condition="!Skin.HasSetting(chooseosdplayer)">videosd2</include>'
    )
    if old in text:
        text = text.replace(old, new, 1)
    elif "Skin.HasSetting(chooseosdplayer)" not in text or "videosd2" not in text:
        raise SystemExit("VideoOSD.xml does not contain videosd1 anchor or existing player switch logic")
    write_text(path, text)


def inline_taller_power_menu_list(xml_dir: Path, dialog_text: str) -> str:
    """Make the power menu tall enough to show the extra row.

    ButtonMenuList is a shared include with a 380px panel, which shows about five
    rows. The new button is intentionally placed below Reload skin, so we inline
    a taller copy only in DialogButtonMenu instead of changing the shared include
    for search dialogs too.
    """

    if "KODI-POV-IL - Taller power menu list" in dialog_text:
        return dialog_text

    includes_path = xml_dir / "Includes_Buttons.xml"
    includes_text = read_text(includes_path)
    start = includes_text.find('<include name="ButtonMenuList">')
    if start < 0:
        raise SystemExit("ButtonMenuList include not found in Includes_Buttons.xml")

    end_marker = "\n\t</include>"
    end = includes_text.find(end_marker, start)
    if end < 0:
        raise SystemExit("ButtonMenuList include end not found in Includes_Buttons.xml")

    include_block = includes_text[start : end + len(end_marker)]
    inner = include_block.split("\n", 1)[1].rsplit(end_marker, 1)[0]
    inner = inner.replace("<height>380</height>", "<height>455</height>", 1)
    inner = "\t\t\t\t<!-- KODI-POV-IL - Taller power menu list -->\n" + inner

    old = "\t\t\t\t<include>ButtonMenuList</include>"
    if old in dialog_text:
        return dialog_text.replace(old, inner, 1)

    old = "<include>ButtonMenuList</include>"
    if old in dialog_text:
        return dialog_text.replace(old, inner, 1)

    if "ButtonMenuList" not in dialog_text:
        # Already inlined somehow; keep going as long as the height is tall enough.
        if "<height>455</height>" in dialog_text:
            return dialog_text
    raise SystemExit("DialogButtonMenu.xml does not contain ButtonMenuList include")


def patch_power_menu(xml_dir: Path) -> None:
    path = xml_dir / "DialogButtonMenu.xml"
    text = read_text(path)

    # Give the popup enough room for the new row. Without this, the button exists
    # in XML but appears below the visible five rows on some devices.
    text = text.replace('<param name="height" value="485" />', '<param name="height" value="560" />', 1)
    text = inline_taller_power_menu_list(xml_dir, text)

    marker = "KODI-POV-IL - Toggle FENtastic player"
    if marker not in text:
        block = "\n".join(
            [
                "                        <item>",
                "                            <!-- KODI-POV-IL - Toggle FENtastic player -->",
                "                            <label>[B][COLOR blue]שנה נגן[/COLOR][/B]</label>",
                "                            <label2>$VAR[OSDPlayerModeVar]</label2>",
                "                            <onclick>Skin.ToggleSetting(chooseosdplayer)</onclick>",
                "                            <onclick>Dialog.Close(all)</onclick>",
                "                            <onclick>ReloadSkin()</onclick>",
                "                        </item>",
            ]
        )

        anchor = "<!-- Reload skin -->"
        idx = text.find(anchor)
        if idx < 0:
            raise SystemExit("Reload skin anchor not found in DialogButtonMenu.xml")

        end = text.find("</item>", idx)
        if end < 0:
            raise SystemExit("Reload skin item end not found in DialogButtonMenu.xml")
        end += len("</item>")

        text = text[:end] + "\n" + block + text[end:]

    write_text(path, text)


def patch_osd_settings_menu(xml_dir: Path) -> None:
    path = xml_dir / "Includes_Items.xml"
    text = read_text(path)
    marker = "KODI-POV-IL - OSD player mode"
    if marker in text:
        write_text(path, text)
        return

    block = "\n".join(
        [
            "        <item>",
            "            <!-- KODI-POV-IL - OSD player mode -->",
            "            <label>שנה נגן</label>",
            "            <label2>$VAR[OSDPlayerModeVar]</label2>",
            "            <onclick>Skin.ToggleSetting(chooseosdplayer)</onclick>",
            "            <onclick>ReloadSkin()</onclick>",
            "        </item>",
        ]
    )

    include_idx = text.find('<include name="BasedMenuOsdSecondMenu">')
    if include_idx < 0:
        raise SystemExit("BasedMenuOsdSecondMenu not found in Includes_Items.xml")

    end = text.find("</content>", include_idx)
    if end < 0:
        raise SystemExit("BasedMenuOsdSecondMenu content end not found in Includes_Items.xml")

    text = text[:end] + block + "\n" + text[end:]
    write_text(path, text)


def patch_variables(xml_dir: Path) -> None:
    path = xml_dir / "Variables.xml"
    text = read_text(path)
    marker = '<variable name="OSDPlayerModeVar">'
    if marker in text:
        write_text(path, text)
        return

    block = "\n".join(
        [
            "",
            '    <variable name="OSDPlayerModeVar">',
            '        <value condition="Skin.HasSetting(chooseosdplayer)">נגן מתקדם</value>',
            "        <value>נגן קלאסי</value>",
            "    </variable>",
            "",
        ]
    )

    end = text.rfind("</includes>")
    if end < 0:
        raise SystemExit("Variables.xml closing </includes> not found")

    text = text[:end] + block + text[end:]
    write_text(path, text)


def verify(xml_dir: Path) -> None:
    checks = {
        xml_dir / "DialogButtonMenu.xml": [
            "KODI-POV-IL - Taller power menu list",
            "<height>455</height>",
            "שנה נגן",
            "Skin.ToggleSetting(chooseosdplayer)",
            "ReloadSkin()",
        ],
        xml_dir / "VideoOSD.xml": ["Skin.HasSetting(chooseosdplayer)", "videosd1", "videosd2"],
        xml_dir / "Includes_Items.xml": ["KODI-POV-IL - OSD player mode", "Skin.ToggleSetting(chooseosdplayer)"],
        xml_dir / "Variables.xml": ["OSDPlayerModeVar", "נגן מתקדם", "נגן קלאסי"],
    }
    for path, needles in checks.items():
        text = read_text(path)
        for needle in needles:
            if needle not in text:
                raise SystemExit(f"Missing {needle!r} in {path}")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_fentastic_player.py <extracted-root>")

    root = Path(sys.argv[1])
    xml_dir = root / "addons" / "skin.fentastic" / "xml"
    if not xml_dir.is_dir():
        raise SystemExit(f"FENtastic XML folder not found: {xml_dir}")

    patch_video_osd(xml_dir)
    patch_power_menu(xml_dir)
    patch_osd_settings_menu(xml_dir)
    patch_variables(xml_dir)
    verify(xml_dir)
    print("FENtastic player switch patch verified successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
