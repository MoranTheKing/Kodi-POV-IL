#!/usr/bin/env python3
"""Exercise the migration contract without opening a real Kodi profile."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / "wizard" / "source" / "plugin.program.kodipovilwizard"
          / "resources" / "libs" / "build_config_migration.py")
spec = importlib.util.spec_from_file_location("build_config_migration", MODULE)
assert spec and spec.loader
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


OLD = """<settings version="2">
<setting id="meta_language" default="true">he</setting>
<setting id="skin_style">dark</setting>
<setting id="trakt.token">old-build-placeholder</setting>
<setting id="obsolete">old</setting>
</settings>"""
INSTALLED = """<settings version="2">
<setting id="meta_language" default="true">he</setting>
<setting id="skin_style">light</setting>
<setting id="trakt.token">my-real-token</setting>
<setting id="user_only">keep me</setting>
<setting id="obsolete">custom old value</setting>
</settings>"""
NEW = """<settings version="2">
<setting id="meta_language">iw</setting>
<setting id="skin_style">blue</setting>
<setting id="trakt.token">new-build-placeholder</setting>
<setting id="new_feature">enabled</setting>
</settings>"""


merged, counts = migration.merge_settings_xml(
    OLD, INSTALLED, NEW, protected_ids={"trakt.token"})
root = ET.fromstring(merged)
values = {item.get("id"): item.text for item in root.findall("setting")}
assert root.get("version") == "2"
assert values == {
    "meta_language": "iw",       # unchanged old build default can advance
    "skin_style": "light",       # user selection wins
    "trakt.token": "my-real-token",  # credential never overwritten
    "user_only": "keep me",     # no build ownership
    "obsolete": "custom old value",  # deletion does not remove user data
    "new_feature": "enabled",   # genuinely new setting is added
}, values
assert counts == {"updated": 1, "added": 1, "unchanged": 0,
                  "preserved": 1, "protected": 1}
assert "my-real-token" in INSTALLED and "my-real-token" not in NEW

# A value absent from the known old baseline belongs to the user, even when
# the new build happens to define an ID with the same name.
merged, counts = migration.merge_settings_xml(
    "<settings/>", '<settings><setting id="x">personal</setting></settings>',
    '<settings><setting id="x">build</setting></settings>', protected_ids=set())
assert ET.fromstring(merged).find('setting').text == "personal"
assert counts["preserved"] == 1

# Invalid/ambiguous input must stop the migration, not be interpreted as an
# empty settings file that allows the build to replace a user's profile.
for bad in ("", "not XML", "<settings><setting id='x'/><setting id='x'/></settings>"):
    try:
        migration.merge_settings_xml(OLD, bad, NEW, protected_ids=set())
    except ValueError:
        pass
    else:
        raise AssertionError("invalid installed settings were accepted")

print("ok: three-way settings migration preserves user values and fails closed")
