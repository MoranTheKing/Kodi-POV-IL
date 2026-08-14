#!/usr/bin/env python3
"""Every setting id we read or write should be declared in settings.xml.

CONSISTENCY, NOT PERSISTENCE. An earlier version of this docstring said Kodi
drops a write to an undeclared id. It does not: CAddon::UpdateSetting creates
a hidden CSettingString through AddSettingWithoutDefinition, SaveSettings
serialises it with no "was this declared" filter, and CAddonSettings::Load
recreates it on the way back in. HANDOFF.md had already settled this from
Kodi's own source, and this test was written without reading it. What DOES
get dropped is a setSetting into ANOTHER add-on for an id that add-on has not
declared -- a different code path, and the reason Account Manager's writes
into Umbrella are no-ops.

So this test is house style: it keeps every id findable in one place, so the
next person auditing "what does this add-on store?" gets a complete answer
from the schema instead of from a grep. That is worth having. It is not
guarding against data loss, and it should not be cited as if it were.

KNOWN GAPS, because a test that overstates its coverage is worse than none:
it only sees ids passed as inline string literals, so the very common idiom
here -- DONE_SETTING = '_x_v1' then set_setting(DONE_SETTING, ...) -- is
invisible to it, which today hides 7 of the ids this file checks. It also
only knows our kodi_utils helpers, not the Addon().getSetting/setSetting
convention that resources/lib/subs_engine uses. Both are worth closing.

Run with no arguments; exits non-zero on the first undeclared id.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addons" / "service.subtitles.kodipovilai"
SETTINGS = ADDON / "resources" / "settings.xml"

# The helpers in kodi_utils that take a setting id as their first argument.
READERS = {"get_setting", "set_setting", "get_bool", "get_int", "get_float"}

# Ids that belong to OTHER add-ons. We reach those through
# addon_settings_safe.apply(), never through our own settings.xml, so they are
# not ours to declare.
FOREIGN_PREFIXES = ("general.", "provider.", "external_provider.", "sources.",
                    "scrapers.", "imdb.", "library.", "check_for_update",
                    "trakt_", "mdblist.", "tmdb.")

# Source we ship INTO another add-on. These files run inside POV, against
# POV's kodi_utils and POV's settings.xml, so an id here is POV's business.
FOREIGN_TREES = ("pov_overrides", "pov_repair", "pov_native_menus")

# READ ONLY, AND DELIBERATELY NOT DECLARED. Each of these is read with a
# default and never written, so an undeclared id costs nothing: getSetting
# returns empty and the caller's own default applies, which is the value the
# code wants anyway. Declaring them would put retired knobs back into the
# schema for no gain. The rule this test enforces is about ids we WRITE, where
# a value that never reaches disk is a promise that is never kept. If any of
# these ever gains a set_setting call, delete it from here and declare it.
READ_ONLY_DEFAULTS = {
    "he_match_ktuvit", "he_embedded_report",
    "subsync_verify", "subsync_probe", "subsync_audio",
    "gemini_rpm", "prev_context_lines",
}


def declared_ids():
    tree = ElementTree.parse(SETTINGS)
    return {s.get("id") for s in tree.iter("setting") if s.get("id")}


def used_ids():
    """(id, file, line) for every literal setting id passed to a helper."""
    found = []
    for path in sorted(ADDON.rglob("*.py")):
        if any(part in FOREIGN_TREES for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            print("FAIL cannot parse {0}: {1}".format(path, exc))
            sys.exit(1)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name not in READERS:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.append((first.value, path.relative_to(ROOT), node.lineno))
    return found


def main():
    declared = declared_ids()
    missing = []
    for setting_id, path, line in used_ids():
        if not setting_id or setting_id.startswith(FOREIGN_PREFIXES):
            continue
        if setting_id in READ_ONLY_DEFAULTS:
            continue
        if setting_id not in declared:
            missing.append((setting_id, path, line))
    if missing:
        print("FAIL settings.xml does not declare {0} id(s) the code uses:"
              .format(len(missing)))
        for setting_id, path, line in missing:
            print("  {0}  ({1}:{2})".format(setting_id, path, line))
        print("Undeclared ids still persist, so this is a tidiness failure "
              "rather than a data-loss one: declare them so the schema stays "
              "the single place that answers what this add-on stores.")
        return 1
    print("PASS every setting id this test can SEE is declared ({0} declared "
          "ids). See KNOWN GAPS above: literals only, our helpers only."
          .format(len(declared)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
