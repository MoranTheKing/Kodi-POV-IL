# -*- coding: utf-8 -*-
"""Runtime safety patch for the Kodi POV IL FENtastic player switch.

Why this exists:
Quick Update packages can include addons/skin.fentastic, but some existing
installations keep/preserve skin files during extraction, or Kodi may continue
loading the already-installed skin copy. The wizard itself is extracted with
ignore=True, so this module is delivered reliably with the wizard and patches the
active FENtastic XML files directly on the next startup.
"""

from __future__ import annotations

import os

import xbmc

from resources.libs.common.config import CONFIG
from resources.libs.common import logging


MARKER_POWER = "KODI-POV-IL - Toggle FENtastic player"
MARKER_OSD = "KODI-POV-IL - OSD player mode"
MARKER_TALLER = "KODI-POV-IL - Taller power menu list"


def _read(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def _write(path, text):
    tmp = path + ".kodipovtmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _patch_video_osd(xml_dir):
    path = os.path.join(xml_dir, "VideoOSD.xml")
    text = _read(path)
    old = "<include>videosd1</include>"
    new = (
        '<include condition="Skin.HasSetting(chooseosdplayer)">videosd1</include>\n'
        '<include condition="!Skin.HasSetting(chooseosdplayer)">videosd2</include>'
    )
    if old in text:
        text = text.replace(old, new, 1)
        _write(path, text)
        return True
    if "Skin.HasSetting(chooseosdplayer)" in text and "videosd2" in text:
        return False
    raise RuntimeError("VideoOSD.xml missing videosd1 anchor/player switch logic")


def _inline_taller_power_menu_list(xml_dir, dialog_text):
    if MARKER_TALLER in dialog_text:
        return dialog_text, False

    includes_path = os.path.join(xml_dir, "Includes_Buttons.xml")
    includes_text = _read(includes_path)
    start = includes_text.find('<include name="ButtonMenuList">')
    if start < 0:
        raise RuntimeError("ButtonMenuList include not found")

    end_marker = "\n\t</include>"
    end = includes_text.find(end_marker, start)
    if end < 0:
        raise RuntimeError("ButtonMenuList include end not found")

    include_block = includes_text[start : end + len(end_marker)]
    inner = include_block.split("\n", 1)[1].rsplit(end_marker, 1)[0]
    inner = inner.replace("<height>380</height>", "<height>455</height>", 1)
    inner = "\t\t\t\t<!-- {0} -->\n".format(MARKER_TALLER) + inner

    old = "\t\t\t\t<include>ButtonMenuList</include>"
    if old in dialog_text:
        return dialog_text.replace(old, inner, 1), True

    old = "<include>ButtonMenuList</include>"
    if old in dialog_text:
        return dialog_text.replace(old, inner, 1), True

    if "<height>455</height>" in dialog_text:
        return dialog_text, False
    raise RuntimeError("DialogButtonMenu.xml does not contain ButtonMenuList include")


def _patch_power_menu(xml_dir):
    path = os.path.join(xml_dir, "DialogButtonMenu.xml")
    text = _read(path)
    original = text

    text = text.replace('<param name="height" value="485" />', '<param name="height" value="560" />', 1)
    text, _ = _inline_taller_power_menu_list(xml_dir, text)

    if MARKER_POWER not in text:
        block = "\n".join([
            "                        <item>",
            "                            <!-- {0} -->".format(MARKER_POWER),
            "                            <label>[B][COLOR blue]שנה נגן[/COLOR][/B]</label>",
            "                            <label2>$VAR[OSDPlayerModeVar]</label2>",
            "                            <onclick>Skin.ToggleSetting(chooseosdplayer)</onclick>",
            "                            <onclick>Dialog.Close(all)</onclick>",
            "                            <onclick>ReloadSkin()</onclick>",
            "                        </item>",
        ])
        anchor = "<!-- Reload skin -->"
        idx = text.find(anchor)
        if idx < 0:
            raise RuntimeError("Reload skin anchor not found in DialogButtonMenu.xml")
        end = text.find("</item>", idx)
        if end < 0:
            raise RuntimeError("Reload skin item end not found in DialogButtonMenu.xml")
        end += len("</item>")
        text = text[:end] + "\n" + block + text[end:]

    if text != original:
        _write(path, text)
        return True
    return False


def _patch_osd_settings_menu(xml_dir):
    path = os.path.join(xml_dir, "Includes_Items.xml")
    text = _read(path)
    if MARKER_OSD in text:
        return False

    block = "\n".join([
        "        <item>",
        "            <!-- {0} -->".format(MARKER_OSD),
        "            <label>שנה נגן</label>",
        "            <label2>$VAR[OSDPlayerModeVar]</label2>",
        "            <onclick>Skin.ToggleSetting(chooseosdplayer)</onclick>",
        "            <onclick>ReloadSkin()</onclick>",
        "        </item>",
    ])
    include_idx = text.find('<include name="BasedMenuOsdSecondMenu">')
    if include_idx < 0:
        raise RuntimeError("BasedMenuOsdSecondMenu not found in Includes_Items.xml")
    end = text.find("</content>", include_idx)
    if end < 0:
        raise RuntimeError("BasedMenuOsdSecondMenu content end not found in Includes_Items.xml")
    text = text[:end] + block + "\n" + text[end:]
    _write(path, text)
    return True


def _patch_variables(xml_dir):
    path = os.path.join(xml_dir, "Variables.xml")
    text = _read(path)
    if '<variable name="OSDPlayerModeVar">' in text:
        return False

    block = "\n".join([
        "",
        '    <variable name="OSDPlayerModeVar">',
        '        <value condition="Skin.HasSetting(chooseosdplayer)">נגן מתקדם</value>',
        "        <value>נגן קלאסי</value>",
        "    </variable>",
        "",
    ])
    end = text.rfind("</includes>")
    if end < 0:
        raise RuntimeError("Variables.xml closing </includes> not found")
    text = text[:end] + block + text[end:]
    _write(path, text)
    return True


def _verify(xml_dir):
    checks = {
        "DialogButtonMenu.xml": [MARKER_TALLER, "<height>455</height>", "שנה נגן", "Skin.ToggleSetting(chooseosdplayer)"],
        "VideoOSD.xml": ["Skin.HasSetting(chooseosdplayer)", "videosd1", "videosd2"],
        "Includes_Items.xml": [MARKER_OSD, "Skin.ToggleSetting(chooseosdplayer)"],
        "Variables.xml": ["OSDPlayerModeVar", "נגן מתקדם", "נגן קלאסי"],
    }
    for filename, needles in checks.items():
        text = _read(os.path.join(xml_dir, filename))
        for needle in needles:
            if needle not in text:
                raise RuntimeError("Missing {0!r} in {1}".format(needle, filename))


def ensure_patched():
    """Patch installed FENtastic XML files. Returns True if files changed."""
    xml_dir = os.path.join(CONFIG.ADDONS, "skin.fentastic", "xml")
    if not os.path.isdir(xml_dir):
        logging.log("[FENtastic player switch patch] skin.fentastic xml folder not found: {0}".format(xml_dir), level=xbmc.LOGINFO)
        return False

    changed = False
    changed = _patch_video_osd(xml_dir) or changed
    changed = _patch_power_menu(xml_dir) or changed
    changed = _patch_osd_settings_menu(xml_dir) or changed
    changed = _patch_variables(xml_dir) or changed
    _verify(xml_dir)

    if changed:
        logging.log("[FENtastic player switch patch] installed skin files patched successfully", level=xbmc.LOGINFO)
        xbmc.executebuiltin("ReloadSkin()")
    else:
        logging.log("[FENtastic player switch patch] installed skin files already patched", level=xbmc.LOGINFO)
    return changed


def safe_ensure_patched():
    try:
        return ensure_patched()
    except Exception as exc:
        logging.log("[FENtastic player switch patch] failed: {0}".format(exc), level=xbmc.LOGERROR)
        return False
