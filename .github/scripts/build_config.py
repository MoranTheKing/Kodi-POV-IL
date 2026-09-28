#!/usr/bin/env python3
"""Package the build-config (``userdata/``) into a versioned, deterministic zip.

Option 3 of the modular build design: the build's *identity* (active skin,
locale, subtitle config, FENtastic look, favourites, sources, advanced
settings) is shipped as data -- separately from the addon code zips -- so a
fresh install can be fully configured WITHOUT a monolithic build zip, and an
update can be applied at the value/id level WITHOUT clobbering the user's own
keys, widgets, and tweaks.

The version comes from ``userdata/config_policy.json`` -> ``config_version``.
Bump that whenever any file under ``userdata/`` changes; that version bump is
what makes the wizard detect and apply the new config (mirrors how an
``addon.xml`` version bump drives an addon update).

The zip root mirrors the ``userdata/`` folder (``guisettings.xml``,
``addon_data/skin.fentastic/settings.xml``, ``config_policy.json`` ...). The
wizard extracts it to a temp dir and applies each file per the bundled
policy. Output: ``dist/config-<version>.zip`` (deterministic: sorted order +
fixed timestamps -> identical content yields an identical sha256).
"""

from __future__ import annotations

import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(__file__))
from kodi_addons import (  # noqa: E402
    EXCLUDE_DIR_NAMES,
    EXCLUDE_FILE_NAMES,
    EXCLUDE_SUFFIXES,
    REPO_ROOT,
)

CONFIG_DIR = os.path.join(REPO_ROOT, "userdata")
POLICY_PATH = os.path.join(CONFIG_DIR, "config_policy.json")
DIST_DIR = os.path.join(REPO_ROOT, "dist")
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def read_config_version() -> str:
    with open(POLICY_PATH, "r", encoding="utf-8") as fh:
        policy = json.load(fh)
    version = str(policy.get("config_version", "")).strip()
    if not version:
        raise SystemExit("config_policy.json is missing 'config_version'")
    return version


def config_zip_name(version: str | None = None) -> str:
    return f"config-{version or read_config_version()}.zip"


def _collect_files() -> list[tuple[str, str]]:
    """Return (absolute_path, arcname) pairs under userdata/, sorted."""
    items: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(CONFIG_DIR):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIR_NAMES)
        rel_dir = os.path.relpath(dirpath, CONFIG_DIR)
        rel_parts = [] if rel_dir == "." else rel_dir.split(os.sep)
        for filename in sorted(filenames):
            if filename in EXCLUDE_FILE_NAMES or filename.endswith(EXCLUDE_SUFFIXES):
                continue
            # Docs are for the repo, not the shipped pack.
            if filename.lower().endswith('.md'):
                continue
            abs_path = os.path.join(dirpath, filename)
            arc = os.path.join(*rel_parts, filename) if rel_parts else filename
            items.append((abs_path, arc.replace(os.sep, "/")))
    return sorted(items, key=lambda pair: pair[1])


def build() -> str:
    version = read_config_version()
    os.makedirs(DIST_DIR, exist_ok=True)
    out_path = os.path.join(DIST_DIR, config_zip_name(version))
    if os.path.exists(out_path):
        os.remove(out_path)
    files = _collect_files()
    if not files:
        raise SystemExit(f"No files found under {CONFIG_DIR}")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for abs_path, arc in files:
            info = zipfile.ZipInfo(arc, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o644 & 0xFFFF) << 16
            with open(abs_path, "rb") as fh:
                zf.writestr(info, fh.read())
    size = os.path.getsize(out_path)
    print(f"  + {config_zip_name(version)}  ({len(files)} files, {size:,} bytes)")
    return out_path


if __name__ == "__main__":
    build()
