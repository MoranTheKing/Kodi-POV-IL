#!/usr/bin/env python3
"""Regression checks for the box-to-outline Kodi settings migration."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addons" / "service.subtitles.kodipovilai"
sys.path.insert(0, str(ADDON))

from resources.lib import hebrew_build_ui_patcher as patcher  # noqa: E402


class FakeXbmc:
    def __init__(self, values, fail_setting=None):
        self.values = dict(values)
        self.fail_setting = fail_setting
        self.set_calls = []

    def executeJSONRPC(self, raw):
        request = json.loads(raw)
        setting = request["params"]["setting"]
        if request["method"] == "Settings.GetSettingValue":
            return json.dumps({
                "jsonrpc": "2.0", "id": 1,
                "result": {"value": self.values.get(setting)},
            })
        value = request["params"]["value"]
        self.set_calls.append((setting, value))
        if setting == self.fail_setting:
            return json.dumps({
                "jsonrpc": "2.0", "id": 1,
                "error": {"code": -1, "message": "simulated"},
            })
        self.values[setting] = value
        # Kodi 21 Settings.SetSettingValue returns boolean true.
        return json.dumps({"jsonrpc": "2.0", "id": 1, "result": True})


def _run(values, marker="", fail_setting=None):
    addon_settings = {patcher._SUBTITLE_OUTLINE_FLAG: marker}
    fake = FakeXbmc(values, fail_setting=fail_setting)
    old_xbmc = patcher.xbmc
    old_get = patcher.kodi_utils.get_setting
    old_set = patcher.kodi_utils.set_setting
    try:
        patcher.xbmc = fake
        patcher.kodi_utils.get_setting = (
            lambda key, default="": addon_settings.get(key, default))
        patcher.kodi_utils.set_setting = (
            lambda key, value: addon_settings.__setitem__(key, value))
        changed = patcher._ensure_subtitle_outline_style()
        return changed, fake, addon_settings
    finally:
        patcher.xbmc = old_xbmc
        patcher.kodi_utils.get_setting = old_get
        patcher.kodi_utils.set_setting = old_set


def test_exact_old_applies() -> None:
    changed, fake, settings = _run(patcher._SUBTITLE_STYLE_OLD)
    assert changed
    assert fake.values["subtitles.backgroundtype"] == 0
    assert fake.values["subtitles.bordersize"] == 25
    assert settings[patcher._SUBTITLE_OUTLINE_FLAG] == "applied"
    assert fake.set_calls == [
        ("subtitles.backgroundtype", 0),
        ("subtitles.bordersize", 25),
    ]


def test_old_fingerprint_matches_shipped_build() -> None:
    build = ROOT / "dist" / "Kodi-POV-IL-FENtastic-test-0.1.101.zip"
    with zipfile.ZipFile(build) as archive:
        root = ElementTree.fromstring(
            archive.read("userdata/guisettings.xml"))
    shipped = {
        node.attrib.get("id"): node.text
        for node in root.findall("setting")
    }
    for setting_id, expected in patcher._SUBTITLE_STYLE_OLD.items():
        assert patcher._subtitle_value_matches(
            shipped.get(setting_id), expected), (
                setting_id, shipped.get(setting_id), expected)


def test_target_is_noop_and_marked() -> None:
    changed, fake, settings = _run(patcher._SUBTITLE_STYLE_TARGET)
    assert not changed
    assert fake.set_calls == []
    assert settings[patcher._SUBTITLE_OUTLINE_FLAG] == "applied"


def test_custom_profile_is_preserved() -> None:
    custom = dict(patcher._SUBTITLE_STYLE_OLD)
    custom["subtitles.fontname"] = "User Font"
    changed, fake, settings = _run(custom)
    assert not changed
    assert fake.set_calls == []
    assert settings[patcher._SUBTITLE_OUTLINE_FLAG] == "preserved"


def test_failure_retries_partial_state() -> None:
    changed, fake, settings = _run(
        patcher._SUBTITLE_STYLE_OLD,
        fail_setting="subtitles.bordersize")
    assert changed
    assert fake.values["subtitles.backgroundtype"] == 0
    assert fake.values["subtitles.bordersize"] == 41
    assert settings[patcher._SUBTITLE_OUTLINE_FLAG] == "pending"

    changed2, fake2, settings2 = _run(
        fake.values, marker="pending")
    assert changed2
    assert fake2.values["subtitles.backgroundtype"] == 0
    assert fake2.values["subtitles.bordersize"] == 25
    assert settings2[patcher._SUBTITLE_OUTLINE_FLAG] == "applied"


def main() -> None:
    test_old_fingerprint_matches_shipped_build()
    test_exact_old_applies()
    test_target_is_noop_and_marked()
    test_custom_profile_is_preserved()
    test_failure_retries_partial_state()
    print("PASS subtitle outline migration: apply/preserve/retry/no-op")


if __name__ == "__main__":
    main()
