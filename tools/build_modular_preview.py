#!/usr/bin/env python3
"""Build a local, non-published modular preview from the current live sources.

This is migration stage 1: package MoranSubs and the Wizard independently,
without switching build.txt, changing installed devices, or changing URLs.
The output manifest intentionally has no download URLs and must not be used as
an OTA feed.  It proves package closure before any installer work begins.

    python tools/build_modular_preview.py [--output DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from test_local_addon_imports import _zip_tree, missing_imports


ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    ROOT / "addons" / "service.subtitles.kodipovilai",
    ROOT / "wizard" / "source" / "plugin.program.kodipovilwizard",
)
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def _package(source: Path, output: Path) -> dict:
    addon_xml = source / "addon.xml"
    addon = ET.parse(addon_xml).getroot()
    addon_id = addon.get("id")
    version = addon.get("version")
    if not addon_id or not version or source.name != addon_id:
        raise ValueError(f"bad addon identity/version in {addon_xml}")

    files = sorted(
        path for path in source.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in (".pyc", ".pyo")
    )
    if not files:
        raise ValueError(f"empty addon tree: {source}")
    target = output / f"{addon_id}-{version}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as bundle:
        for path in files:
            rel = f"{addon_id}/{path.relative_to(source).as_posix()}"
            info = zipfile.ZipInfo(rel, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED,
                            compresslevel=6)

    with zipfile.ZipFile(target) as bundle:
        bad_member = bundle.testzip()
        if bad_member:
            raise ValueError(f"CRC mismatch: {bad_member}")
        archive_files = {name for name in bundle.namelist() if not name.endswith("/")}
        if len(archive_files) != len(files):
            raise ValueError(f"file count mismatch in {target}")
        packaged_xml = ET.fromstring(bundle.read(f"{addon_id}/addon.xml"))
        if packaged_xml.get("id") != addon_id or packaged_xml.get("version") != version:
            raise ValueError(f"addon.xml mismatch in {target}")
    if addon_id == "service.subtitles.kodipovilai":
        failures = missing_imports(_zip_tree(target))
        if failures:
            raise ValueError("missing imports in packaged MoranSubs:\n" +
                             "\n".join(failures))

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return {
        "id": addon_id,
        "version": version,
        "filename": target.name,
        "files": len(files),
        "size": target.stat().st_size,
        "sha256": digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT.parent / "modular-preview-stage1")
    args = parser.parse_args()
    output = args.output.resolve()
    for source in SOURCES:
        if source.resolve() == output or source.resolve() in output.parents:
            parser.error("output cannot be inside an addon source tree")
    output.mkdir(parents=True, exist_ok=True)

    packages = [_package(source, output) for source in SOURCES]
    manifest = {
        "schema": 1,
        "status": "local-preview-only",
        "source_repo": "MoranTheKing/Kodi-POV-IL",
        "addons": {row["id"]: row for row in packages},
    }
    manifest_path = output / "manifest.preview.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    for row in packages:
        print(f"{row['id']} {row['version']}: {row['files']} files, "
              f"{row['size']} bytes, sha256={row['sha256']}")
    print(f"LOCAL PREVIEW ONLY: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
