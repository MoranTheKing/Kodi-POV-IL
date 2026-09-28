#!/usr/bin/env python3
"""Shared helpers for the Kodi POV IL build pipeline.

This is the single source of truth for:
  * discovering addon folders in the repo root,
  * parsing ``addon.xml`` (id / name / version),
  * deriving the addon *type* from its Kodi extension points.

Both ``build_addons.py`` and ``gen_manifest.py`` import from here so the
two tools can never disagree about what an addon "is".
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass

# Repo root = two levels up from this file (.github/scripts/ -> repo root).
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Folders / files that must never end up inside a packaged addon zip.
EXCLUDE_DIR_NAMES = {".git", "__pycache__", ".github", ".idea", ".vscode"}
EXCLUDE_FILE_NAMES = {".DS_Store", "Thumbs.db", ".gitattributes", ".gitignore"}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".pyd")

# Map a Kodi extension point to a coarse "type" understood by the wizard.
# Order matters: the first matching point (top to bottom) wins, so a skin
# that also declares xbmc.service is still classified as a "skin".
_EXTENSION_TYPE_PRIORITY = [
    ("xbmc.gui.skin", "skin"),
    ("xbmc.addon.repository", "repository"),
    ("xbmc.subtitle.module", "subtitle"),
    ("xbmc.metadata.scraper", "scraper"),       # prefix match (video/music/...)
    ("xbmc.python.pluginsource", "plugin"),
    ("xbmc.webinterface", "webinterface"),
    ("xbmc.python.script", "script"),
    ("xbmc.python.library", "module"),
    ("xbmc.python.module", "module"),
    ("xbmc.service", "service"),
]


@dataclass(frozen=True)
class Addon:
    """A parsed addon, as described by its ``addon.xml``."""

    id: str
    name: str
    version: str
    type: str
    path: str          # absolute path to the addon folder
    dirname: str        # the folder name (must equal id for a valid Kodi zip)

    @property
    def zip_name(self) -> str:
        return f"{self.id}-{self.version}.zip"


def _derive_type(root: ET.Element) -> str:
    """Pick a single coarse type from the addon's extension points."""
    points = [
        ext.get("point", "")
        for ext in root.findall("extension")
        if ext.get("point") and ext.get("point") != "xbmc.addon.metadata"
    ]
    for needle, label in _EXTENSION_TYPE_PRIORITY:
        for point in points:
            if point == needle or point.startswith(needle + "."):
                return label
    return "unknown"


def parse_addon_xml(addon_dir: str) -> Addon | None:
    """Parse ``<addon_dir>/addon.xml`` into an :class:`Addon`.

    Returns ``None`` when the folder has no addon.xml or the root element
    is missing the required id/version attributes.
    """
    xml_path = os.path.join(addon_dir, "addon.xml")
    if not os.path.isfile(xml_path):
        return None
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as exc:  # malformed xml -> skip, but say exactly why
        print(f"  !! MALFORMED addon.xml at {xml_path}: {exc}", file=sys.stderr)
        return None
    except OSError as exc:
        print(f"  !! could not read {xml_path}: {exc}", file=sys.stderr)
        return None
    if root.tag != "addon":
        print(f"  !! {xml_path}: root element is <{root.tag}>, expected <addon>", file=sys.stderr)
        return None
    addon_id = root.get("id")
    version = root.get("version")
    if not addon_id:
        print(f"  !! {xml_path}: <addon> is missing the required id attribute", file=sys.stderr)
        return None
    if not version:
        print(f"  !! {xml_path}: <addon id=\"{addon_id}\"> is missing the required version attribute", file=sys.stderr)
        return None
    return Addon(
        id=addon_id,
        name=root.get("name", addon_id),
        version=version,
        type=_derive_type(root),
        path=os.path.abspath(addon_dir),
        dirname=os.path.basename(os.path.normpath(addon_dir)),
    )


def discover_addons(root: str = REPO_ROOT) -> list[Addon]:
    """Find every addon folder in the repo root, sorted by id."""
    addons: list[Addon] = []
    for entry in sorted(os.listdir(root)):
        full = os.path.join(root, entry)
        if not os.path.isdir(full) or entry in EXCLUDE_DIR_NAMES or entry.startswith("."):
            continue
        addon = parse_addon_xml(full)
        if addon is not None:
            addons.append(addon)
    return sorted(addons, key=lambda a: a.id)


def addon_ids(root: str = REPO_ROOT) -> set[str]:
    return {a.id for a in discover_addons(root)}
