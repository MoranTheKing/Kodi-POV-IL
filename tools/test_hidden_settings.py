#!/usr/bin/env python3
"""Regression checks for MoranSubs internal settings visibility.

Kodi's version-1 settings schema requires ``<visible>false</visible>`` as a
child element.  The legacy ``visible="false"`` attribute is ignored there and
caused the internal boolean settings below to render as blank toggle rows in
Expert mode.

With no arguments, this checks the source settings.xml.  Zip paths may be
provided to verify release packages as well.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SETTINGS = (
    ROOT / "addons" / "service.subtitles.kodipovilai" / "resources"
    / "settings.xml"
)
INTERNAL_BOOLEAN_IDS = {
    "embedded_translate",
    "embedded_http_extract",
    "af3_first_launch_dialog_done",
}
INTERNAL_SCHEMA_V1_MARKERS = {"_embedded_mode_v1"}
EMBEDDED_MODE_ID = "embedded_translation_mode"
EMBEDDED_MODE_LABELS = {
    "32423",
    "32424",
    "32425",
    "32426",
    "32427",
    "32428",
    "32429",
}
EMBEDDED_MODE_OPTIONS = {
    "auto": "32425",
    "align_only": "32426",
    "direct": "32427",
    "local_only": "32428",
    "off": "32429",
}
LANGUAGE_FILES = (
    ROOT / "addons" / "service.subtitles.kodipovilai" / "resources"
    / "language" / "resource.language.en_gb" / "strings.po",
    ROOT / "addons" / "service.subtitles.kodipovilai" / "resources"
    / "language" / "resource.language.he_il" / "strings.po",
)
ZIP_SETTINGS_PATHS = (
    "service.subtitles.kodipovilai/resources/settings.xml",
    "addons/service.subtitles.kodipovilai/resources/settings.xml",
)


def _check(data: bytes, source: str) -> None:
    root = ElementTree.fromstring(data)
    if root.tag != "settings" or root.attrib.get("version") != "1":
        raise AssertionError(f"{source}: expected settings schema version 1")

    settings = {
        node.attrib.get("id"): node
        for node in root.findall(".//setting")
    }
    found = {
        setting_id
        for setting_id, node in settings.items()
        if node.attrib.get("type") == "boolean"
        and node.attrib.get("label") == "30000"
    }
    if found != INTERNAL_BOOLEAN_IDS:
        raise AssertionError(
            f"{source}: internal boolean set changed: "
            f"expected {sorted(INTERNAL_BOOLEAN_IDS)}, got {sorted(found)}"
        )

    for setting_id in sorted(INTERNAL_BOOLEAN_IDS):
        node = settings[setting_id]
        if "visible" in node.attrib:
            raise AssertionError(
                f"{source}: {setting_id} uses legacy visible attribute"
            )
        if node.findtext("level") != "4":
            raise AssertionError(
                f"{source}: {setting_id} must use internal level 4"
            )
        if node.findtext("visible") != "false":
            raise AssertionError(
                f"{source}: {setting_id} lacks schema-v1 visible=false child"
            )
        control = node.find("control")
        if control is None or control.attrib.get("type") != "toggle":
            raise AssertionError(
                f"{source}: {setting_id} no longer has a toggle control"
            )

    for setting_id in sorted(INTERNAL_SCHEMA_V1_MARKERS):
        node = settings.get(setting_id)
        if node is None:
            raise AssertionError(f"{source}: missing {setting_id}")
        if "visible" in node.attrib or node.findtext("visible") != "false":
            raise AssertionError(
                f"{source}: {setting_id} must use schema-v1 visible child"
            )
        if node.findtext("level") != "4":
            raise AssertionError(f"{source}: {setting_id} must be internal")

    mode = settings.get(EMBEDDED_MODE_ID)
    if mode is None:
        raise AssertionError(f"{source}: missing {EMBEDDED_MODE_ID}")
    if mode.attrib.get("type") != "string":
        raise AssertionError(f"{source}: embedded mode must be a string")
    if mode.attrib.get("label") != "32423" or mode.attrib.get("help") != "32424":
        raise AssertionError(f"{source}: embedded mode label/help changed")
    if mode.findtext("level") != "0" or mode.findtext("default") != "auto":
        raise AssertionError(f"{source}: embedded mode must be visible, default auto")
    if mode.find("visible") is not None or "visible" in mode.attrib:
        raise AssertionError(f"{source}: embedded mode must remain user-visible")
    options = {
        option.text: option.attrib.get("label")
        for option in mode.findall("./constraints/options/option")
    }
    if options != EMBEDDED_MODE_OPTIONS:
        raise AssertionError(
            f"{source}: embedded mode options changed: {options}"
        )
    control = mode.find("control")
    if (
        control is None
        or control.attrib.get("type") != "list"
        or control.attrib.get("format") != "string"
        or control.findtext("heading") != "32423"
    ):
        raise AssertionError(f"{source}: embedded mode list control is invalid")


def _check_localizations() -> None:
    for path in LANGUAGE_FILES:
        text = path.read_text(encoding="utf-8")
        for label_id in sorted(EMBEDDED_MODE_LABELS):
            marker = f'msgctxt "#{label_id}"'
            if text.count(marker) != 1:
                raise AssertionError(
                    f"{path}: expected exactly one non-ambiguous {marker}"
                )
            block = text.split(marker, 1)[1].split("\n\n", 1)[0]
            if 'msgstr ""' in block:
                raise AssertionError(f"{path}: empty translation for #{label_id}")


def _zip_settings(path: Path) -> tuple[bytes, str]:
    with zipfile.ZipFile(path) as archive:
        matches = [name for name in ZIP_SETTINGS_PATHS if name in archive.namelist()]
        if len(matches) != 1:
            raise AssertionError(
                f"{path}: expected exactly one MoranSubs settings.xml, "
                f"found {matches}"
            )
        name = matches[0]
        return archive.read(name), f"{path}:{name}"


def main() -> None:
    _check(SOURCE_SETTINGS.read_bytes(), str(SOURCE_SETTINGS))
    _check_localizations()
    print(f"PASS source: {SOURCE_SETTINGS.relative_to(ROOT)}")

    for raw_path in sys.argv[1:]:
        path = Path(raw_path)
        data, source = _zip_settings(path)
        _check(data, source)
        print(f"PASS package: {path}")


if __name__ == "__main__":
    main()
