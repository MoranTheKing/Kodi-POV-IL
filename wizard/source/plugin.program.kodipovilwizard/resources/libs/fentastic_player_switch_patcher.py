# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re

import xbmc

from resources.libs.common.config import CONFIG
from resources.libs.common import logging

LABEL = "\u05d1\u05d7\u05e8 \u05e0\u05d2\u05df"
REGULAR = "\u05e0\u05d2\u05df \u05e8\u05d2\u05d9\u05dc"
ADVANCED = "\u05e0\u05d2\u05df \u05de\u05ea\u05e7\u05d3\u05dd"
VAR_NAME = "osdchangeplayervar"
MARKER_POWER = "KODI-POV-IL - Open FENtastic player selector"
MARKER_OSD = "KODI-POV-IL - OSD player mode"
MARKER_TALLER = "KODI-POV-IL - Taller power menu list"
OLD_MARKER_POWER = "KODI-POV-IL - Toggle FENtastic player"
BACKPLATE_MARKER = "KODI-POV-IL - OSD bottom backplate"
SELECT_ACTION = "RunPlugin(plugin://plugin.program.kodipovilwizard/?mode=install&amp;action=fentastic_select_player)"

# Keep the Kodi POV IL build home clean. Tal's player update contained a
# full skin.fentastic settings.xml, and when that file was applied it could
# expose the raw Kodi home categories again. These booleans restore the
# intended build menu on every startup without touching user add-on logins.
HOME_MENU_HIDE = (
    "HomeMenuNoMusicButton",
    "HomeMenuNoMusicVideoButton",
    "HomeMenuNoTVButton",
    "HomeMenuNoRadioButton",
    "HomeMenuNoGamesButton",
    "HomeMenuNoProgramsButton",
    "HomeMenuNoPicturesButton",
    "HomeMenuNoVideosButton",
    "HomeMenuNoWeatherButton",
    "HomeMenuNoCustom2Button",
    "HomeMenuNoCustom3Button",
)
HOME_MENU_SHOW = (
    "HomeMenuNoMoviesButton",
    "HomeMenuNoTVShowsButton",
    "HomeMenuNoCustom1Button",
    "HomeMenuNoFavButton",
    "HomeMenuNoIdanPlusButton",
    "HomeMenuNoMovieButton",
    "HomeMenuNoTVShowButton",
)


def _read(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def _write(path, text):
    tmp = path + ".kodipovtmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _skin_settings_path():
    return os.path.join(CONFIG.ADDON_DATA, "skin.fentastic", "settings.xml")


def _set_settings_xml_bool(text, setting_id, value):
    item = '<setting id="{0}" type="bool">{1}</setting>'.format(setting_id, value)
    pattern = re.compile(
        r'<setting id="' + re.escape(setting_id) + r'" type="bool">(?:true|false)</setting>',
        re.I,
    )
    if pattern.search(text):
        return pattern.sub(item, text, count=1)
    if "</settings>" in text:
        return text.replace("</settings>", "    " + item + "\n</settings>", 1)
    return text


def _set_skin_bool_runtime(setting_id, wanted_true):
    try:
        is_true = xbmc.getCondVisibility("Skin.HasSetting({0})".format(setting_id))
        if wanted_true and not is_true:
            xbmc.executebuiltin("Skin.SetBool({0})".format(setting_id))
            return True
        if not wanted_true and is_true:
            xbmc.executebuiltin("Skin.Reset({0})".format(setting_id))
            return True
    except Exception:
        pass
    return False


def _ensure_home_menu_visibility():
    changed = False
    path = _skin_settings_path()
    text = _read(path) if os.path.isfile(path) else "<settings>\n</settings>\n"
    original = text

    for setting_id in HOME_MENU_HIDE:
        changed = _set_skin_bool_runtime(setting_id, True) or changed
        text = _set_settings_xml_bool(text, setting_id, "true")
    for setting_id in HOME_MENU_SHOW:
        changed = _set_skin_bool_runtime(setting_id, False) or changed
        text = _set_settings_xml_bool(text, setting_id, "false")

    if text != original:
        base = os.path.dirname(path)
        try:
            os.makedirs(base, exist_ok=True)
        except Exception:
            pass
        _write(path, text)
        changed = True
    return changed


def _set_default_regular():
    path = _skin_settings_path()
    if not os.path.isfile(path):
        return False
    text = _read(path)
    original = text
    text = _set_settings_xml_bool(text, "chooseosdplayer", "true")
    changed = _set_skin_bool_runtime("chooseosdplayer", True)
    if text != original:
        _write(path, text)
        changed = True
    return changed


def _ensure_videoosd2_is_loaded(xml_dir):
    path = os.path.join(xml_dir, "Includes.xml")
    if not os.path.isfile(path):
        return False
    text = _read(path)
    original = text
    if 'Includes_VideoOsd2.xml' not in text:
        text = text.replace(
            '<include file="Includes_VideoOsd.xml" />',
            '<include file="Includes_VideoOsd.xml" />\n\t<include file="Includes_VideoOsd2.xml" />',
            1,
        )
    if text != original:
        _write(path, text)
        return True
    return False


def _patch_video_osd_switch(xml_dir):
    path = os.path.join(xml_dir, "VideoOSD.xml")
    if not os.path.isfile(path):
        return False
    text = _read(path)
    original = text
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
    if text != original:
        _write(path, text)
        return True
    return False


def _patch_osd_backplates(xml_dir):
    changed = False
    video1 = os.path.join(xml_dir, "Includes_VideoOsd.xml")
    if os.path.isfile(video1):
        text = _read(video1)
        original = text
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
        if text != original:
            _write(video1, text)
            changed = True

    video2 = os.path.join(xml_dir, "Includes_VideoOsd2.xml")
    if os.path.isfile(video2):
        text = _read(video2)
        original = text
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
        if text != original:
            _write(video2, text)
            changed = True
    return changed


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
    if not os.path.isfile(path):
        return False
    text = _read(path)
    original = text
    text = text.replace('<param name="height" value="485" />', '<param name="height" value="560" />', 1)
    text = _inline_taller_power_menu_list(xml_dir, text)
    text = re.sub(r'\s*<item>\s*<!-- (?:' + re.escape(OLD_MARKER_POWER) + '|' + re.escape(MARKER_POWER) + r') -->.*?</item>', '', text, count=1, flags=re.S)
    block = "\n".join([
        "                        <item>",
        "                            <!-- {0} -->".format(MARKER_POWER),
        "                            <label>[B][COLOR blue]{0}[/COLOR][/B]</label>".format(LABEL),
        "                            <label2>$VAR[{0}]</label2>".format(VAR_NAME),
        "                            <onclick>{0}</onclick>".format(SELECT_ACTION),
        "                        </item>",
    ])
    idx = text.find("<!-- Reload skin -->")
    end = text.find("</item>", idx)
    if idx >= 0 and end >= 0:
        text = text[:end + len("</item>")] + "\n" + block + text[end + len("</item>"):]
    if text != original:
        _write(path, text)
        return True
    return False


def _patch_osd_settings_menu(xml_dir):
    path = os.path.join(xml_dir, "Includes_Items.xml")
    if not os.path.isfile(path):
        return False
    text = _read(path)
    original = text
    text = re.sub(r'\s*<item>\s*<!-- KODI-POV-IL - OSD player mode -->.*?</item>', '', text, count=1, flags=re.S)
    block = "\n".join([
        "        <item>",
        "            <!-- {0} -->".format(MARKER_OSD),
        "            <label>{0}</label>".format(LABEL),
        "            <label2>$VAR[{0}]</label2>".format(VAR_NAME),
        "            <onclick>{0}</onclick>".format(SELECT_ACTION),
        "        </item>",
    ])
    idx = text.find('<include name="BasedMenuOsdSecondMenu">')
    end = text.find("</content>", idx)
    if idx >= 0 and end >= 0:
        text = text[:end] + block + "\n" + text[end:]
    if text != original:
        _write(path, text)
        return True
    return False


def _patch_variables(xml_dir):
    path = os.path.join(xml_dir, "Variables.xml")
    if not os.path.isfile(path):
        return False
    text = _read(path)
    original = text
    block = '\n\t<variable name="{0}">\n\t\t<value condition="Skin.HasSetting(chooseosdplayer)">{1}</value>\n\t\t<value>{2}</value>\n\t</variable>'.format(VAR_NAME, REGULAR, ADVANCED)
    if '<variable name="{0}">'.format(VAR_NAME) in text:
        text = re.sub(r'<variable name="' + VAR_NAME + r'">.*?</variable>', block, text, count=1, flags=re.S)
    else:
        text = text.replace("</includes>", block + "\n</includes>", 1)
    text = re.sub(r'<variable name="OSDPlayerModeVar">.*?</variable>', '', text, count=1, flags=re.S)
    if text != original:
        _write(path, text)
        return True
    return False


def _verify(xml_dir):
    includes = _read(os.path.join(xml_dir, "Includes.xml"))
    video = _read(os.path.join(xml_dir, "VideoOSD.xml"))
    power = _read(os.path.join(xml_dir, "DialogButtonMenu.xml"))
    items = _read(os.path.join(xml_dir, "Includes_Items.xml"))
    video1 = _read(os.path.join(xml_dir, "Includes_VideoOsd.xml"))
    video2 = _read(os.path.join(xml_dir, "Includes_VideoOsd2.xml"))
    if 'Includes_VideoOsd2.xml' not in includes:
        raise RuntimeError("Includes.xml does not load Includes_VideoOsd2.xml")
    if 'Skin.HasSetting(chooseosdplayer)">videosd2</include>' not in video:
        raise RuntimeError("regular player is not mapped to videosd2")
    if '!Skin.HasSetting(chooseosdplayer)">videosd1</include>' not in video:
        raise RuntimeError("advanced player is not mapped to videosd1")
    if 'fentastic_select_player' not in power or 'Skin.ToggleSetting(chooseosdplayer)' in power:
        raise RuntimeError("power menu is not using selector dialog")
    if 'fentastic_select_player' not in items or 'Skin.ToggleSetting(chooseosdplayer)' in items:
        raise RuntimeError("OSD settings menu is not using selector dialog")
    if BACKPLATE_MARKER not in video1 or BACKPLATE_MARKER not in video2:
        raise RuntimeError("OSD bottom backplate is missing")


def ensure_patched():
    xml_dir = os.path.join(CONFIG.ADDONS, "skin.fentastic", "xml")
    if not os.path.isdir(xml_dir):
        logging.log("[FENtastic player selector] xml folder not found", level=xbmc.LOGINFO)
        return False
    changed = False
    changed = _ensure_home_menu_visibility() or changed
    changed = _set_default_regular() or changed
    changed = _ensure_videoosd2_is_loaded(xml_dir) or changed
    changed = _patch_video_osd_switch(xml_dir) or changed
    changed = _patch_osd_backplates(xml_dir) or changed
    changed = _patch_power_menu(xml_dir) or changed
    changed = _patch_osd_settings_menu(xml_dir) or changed
    changed = _patch_variables(xml_dir) or changed
    _verify(xml_dir)
    if changed:
        logging.log("[FENtastic player selector] both player modes loaded, home menu restored, OSD backplate applied", level=xbmc.LOGINFO)
        xbmc.executebuiltin("ReloadSkin()")
    return changed


def safe_ensure_patched():
    try:
        return ensure_patched()
    except Exception as exc:
        logging.log("[FENtastic player selector] failed: {0}".format(exc), level=xbmc.LOGERROR)
        return False
