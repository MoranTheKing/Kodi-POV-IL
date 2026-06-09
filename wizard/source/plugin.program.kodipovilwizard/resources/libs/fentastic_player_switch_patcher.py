# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re

import xbmc

from resources.libs.common.config import CONFIG
from resources.libs.common import logging

LABEL = "\u05e9\u05e0\u05d4 \u05e0\u05d2\u05df"
REGULAR = "\u05e0\u05d2\u05df \u05e8\u05d2\u05d9\u05dc"
ADVANCED = "\u05e0\u05d2\u05df \u05de\u05ea\u05e7\u05d3\u05dd"
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


def _set_default_regular():
    path = os.path.join(CONFIG.ADDON_DATA, "skin.fentastic", "settings.xml")
    if not os.path.isfile(path):
        return False
    text = _read(path)
    item = '<setting id="chooseosdplayer" type="bool">true</setting>'
    new = re.sub(r'<setting id="chooseosdplayer" type="bool">(?:true|false)</setting>', item, text, count=1)
    if new == text and "chooseosdplayer" not in text and "</settings>" in text:
        new = text.replace("</settings>", "    " + item + "\n</settings>", 1)
    if new != text:
        _write(path, new)
        return True
    return False


def _patch_video_osd(xml_dir):
    path = os.path.join(xml_dir, "VideoOSD.xml")
    text = _read(path)
    original = text
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
    if text != original:
        _write(path, text)
        return True
    return False


def _inline_taller_power_menu_list(xml_dir, text):
    if MARKER_TALLER in text:
        return text
    includes_path = os.path.join(xml_dir, "Includes_Buttons.xml")
    if not os.path.isfile(includes_path):
        return text
    includes_text = _read(includes_path)
    start = includes_text.find('<include name="ButtonMenuList">')
    end = includes_text.find("\n\t</include>", start)
    if start < 0 or end < 0:
        return text
    end += len("\n\t</include>")
    inner = includes_text[start:end].split("\n", 1)[1].rsplit("\n\t</include>", 1)[0]
    inner = inner.replace("<height>380</height>", "<height>455</height>", 1)
    inner = "\t\t\t\t<!-- {0} -->\n".format(MARKER_TALLER) + inner
    return text.replace("\t\t\t\t<include>ButtonMenuList</include>", inner, 1)


def _patch_power_menu(xml_dir):
    path = os.path.join(xml_dir, "DialogButtonMenu.xml")
    text = _read(path)
    original = text
    text = text.replace('<param name="height" value="485" />', '<param name="height" value="560" />', 1)
    text = _inline_taller_power_menu_list(xml_dir, text)
    if MARKER_POWER not in text:
        block = "\n".join([
            "                        <item>",
            "                            <!-- {0} -->".format(MARKER_POWER),
            "                            <label>[B][COLOR blue]{0}[/COLOR][/B]</label>".format(LABEL),
            "                            <label2>$VAR[OSDPlayerModeVar]</label2>",
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
    if text != original:
        _write(path, text)
        return True
    return False


def _patch_osd_settings_menu(xml_dir):
    path = os.path.join(xml_dir, "Includes_Items.xml")
    text = _read(path)
    original = text
    if MARKER_OSD not in text:
        block = "\n".join([
            "        <item>",
            "            <!-- {0} -->".format(MARKER_OSD),
            "            <label>{0}</label>".format(LABEL),
            "            <label2>$VAR[OSDPlayerModeVar]</label2>",
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
    if text != original:
        _write(path, text)
        return True
    return False


def _patch_variables(xml_dir):
    path = os.path.join(xml_dir, "Variables.xml")
    text = _read(path)
    original = text
    block = '\n\t<variable name="OSDPlayerModeVar">\n\t\t<value condition="Skin.HasSetting(chooseosdplayer)">{0}</value>\n\t\t<value>{1}</value>\n\t</variable>'.format(REGULAR, ADVANCED)
    if '<variable name="OSDPlayerModeVar">' in text:
        text = re.sub(r'<variable name="OSDPlayerModeVar">.*?</variable>', block, text, count=1, flags=re.S)
    else:
        text = text.replace("</includes>", block + "\n</includes>", 1)
    if text != original:
        _write(path, text)
        return True
    return False


def _verify(xml_dir):
    video = _read(os.path.join(xml_dir, "VideoOSD.xml"))
    if 'Skin.HasSetting(chooseosdplayer)">videosd2</include>' not in video:
        raise RuntimeError("true state is not videosd2")
    if '!Skin.HasSetting(chooseosdplayer)">videosd1</include>' not in video:
        raise RuntimeError("false state is not videosd1")
    includes = _read(os.path.join(xml_dir, "Includes.xml"))
    if 'include name="syncfakebutton"' not in includes or 'include name="TouchBackOSDButton"' not in includes:
        raise RuntimeError("videosd2 dependencies are missing")


def ensure_patched():
    xml_dir = os.path.join(CONFIG.ADDONS, "skin.fentastic", "xml")
    if not os.path.isdir(xml_dir):
        logging.log("[FENtastic player switch] xml folder not found", level=xbmc.LOGINFO)
        return False
    changed = False
    changed = _set_default_regular() or changed
    changed = _patch_video_osd(xml_dir) or changed
    changed = _patch_power_menu(xml_dir) or changed
    changed = _patch_osd_settings_menu(xml_dir) or changed
    changed = _patch_variables(xml_dir) or changed
    _verify(xml_dir)
    if changed:
        logging.log("[FENtastic player switch] Tal mapping applied", level=xbmc.LOGINFO)
        xbmc.executebuiltin("ReloadSkin()")
    return changed


def safe_ensure_patched():
    try:
        return ensure_patched()
    except Exception as exc:
        logging.log("[FENtastic player switch] failed: {0}".format(exc), level=xbmc.LOGERROR)
        return False
