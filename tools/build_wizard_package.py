#!/usr/bin/env python3
"""Build and verify the Kodi POV IL Wizard ZIP from its canonical source."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "wizard/source/plugin.program.kodipovilwizard"
DIST = ROOT / "dist"
WIZARD_PAGE = ROOT / "wizard"
# THE SAME RULE AS THE BUILD TOOL, imported rather than re-derived.
#
# Four review rounds hardened build_full_build._unsafe_member -- `..`, a
# backslash, `".. "`, fullwidth Unicode -- and none of it applied here, while
# `pure.is_absolute() or ".." in pure.parts` stayed as it was. A review put
# all three of the first escapes through both: refused by one, accepted
# silently by the other.
#
# And THIS is the zip that matters most for that: build-apk.yml unpacks the
# wizard package with `unzip -o` -- Info-ZIP, a real non-Python extractor --
# straight into the APK's assets. The build zip only ever meets Python's
# zipfile. The weaker guard was in front of the stronger extractor.
#
# The threat model is milder (this zip is built from first-party, reviewed
# source rather than an upstream download), which is why it went unnoticed --
# not a reason for the two to disagree.
try:
    from build_full_build import _unsafe_member
except ImportError:                       # run from another directory
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from build_full_build import _unsafe_member


PREFIX = "plugin.program.kodipovilwizard/"


def source_files() -> list[Path]:
    files = []
    for path in SOURCE.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(SOURCE)
        if "__pycache__" in relative.parts or path.suffix in (".pyc", ".pyo"):
            continue
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(SOURCE).as_posix())


def addon_version() -> str:
    text = (SOURCE / "addon.xml").read_text(encoding="utf-8")
    match = re.search(
        r'<addon\b[^>]*\bid="plugin\.program\.kodipovilwizard"'
        r'[^>]*\bversion="([^"]+)"',
        text,
    )
    if not match:
        raise ValueError("cannot read Wizard version from addon.xml")
    return match.group(1)


def _git_blob(path: Path) -> bytes:
    relative = path.relative_to(ROOT).as_posix()
    # Apply Git's clean filter for this path without staging the worktree.
    hashed = subprocess.run(
        ["git", "hash-object", "-w", "--path", relative, "--stdin"],
        cwd=ROOT,
        input=path.read_bytes(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout.decode("ascii").strip()
    return subprocess.run(
        ["git", "cat-file", "blob", hashed],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout


def _member_set(values, label: str) -> set[str]:
    if not isinstance(values, list) or not all(
        isinstance(value, str) for value in values
    ):
        raise ValueError("%s must be a JSON string array" % label)
    members = set(values)
    if len(members) != len(values):
        raise ValueError("%s contains duplicate paths" % label)
    for name in members:
        pure = PurePosixPath(name)
        if (
            pure.is_absolute()
            or ".." in pure.parts
            or _unsafe_member(name)
            or not name.startswith(PREFIX)
        ):
            raise ValueError("unsafe %s path: %s" % (label, name))
    return members


def _release_plan(
    previous: Path,
    manifest: Path,
    version: str,
) -> tuple[set[str], set[str], str]:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("release manifest root must be a JSON object")
    required = {
        "version",
        "previous_version",
        "previous_sha256",
        "output_sha256",
        "replace",
        "add",
    }
    if set(data) != required:
        raise ValueError(
            "release manifest keys differ; missing=%r extra=%r"
            % (sorted(required - set(data)), sorted(set(data) - required))
        )
    if data["version"] != version:
        raise ValueError(
            "release manifest version is %r, requested %r"
            % (data["version"], version)
        )
    previous_sha = hashlib.sha256(previous.read_bytes()).hexdigest()
    if previous_sha != str(data["previous_sha256"]).lower():
        raise ValueError(
            "previous Wizard SHA-256 mismatch: %s != %s"
            % (previous_sha, data["previous_sha256"])
        )
    output_sha = str(data["output_sha256"]).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", output_sha):
        raise ValueError("output_sha256 is not a lowercase SHA-256")

    replace = _member_set(data["replace"], "replace")
    add = _member_set(data["add"], "add")
    if replace & add:
        raise ValueError("release manifest replace/add paths overlap")

    with ZipFile(previous) as old:
        old_names = set(old.namelist())
        if not replace <= old_names:
            raise ValueError(
                "planned replacements absent from previous Wizard: %r"
                % sorted(replace - old_names)
            )
        if add & old_names:
            raise ValueError(
                "planned additions already exist in previous Wizard: %r"
                % sorted(add & old_names)
            )
        old_xml = old.read(PREFIX + "addon.xml").decode("utf-8")
        if 'version="%s"' % data["previous_version"] not in old_xml:
            raise ValueError("previous Wizard version does not match manifest")

    source_names = {
        PREFIX + path.relative_to(SOURCE).as_posix() for path in source_files()
    }
    touched = replace | add
    if not touched <= source_names:
        raise ValueError(
            "release manifest paths absent from source: %r"
            % sorted(touched - source_names)
        )
    return replace, add, output_sha


def _replacement_payloads(
    touched: set[str],
) -> dict[str, bytes | None]:
    payloads: dict[str, bytes | None] = {}
    for path in source_files():
        name = PREFIX + path.relative_to(SOURCE).as_posix()
        if name in touched:
            payloads[name] = _git_blob(path)
        else:
            payloads[name] = None
    return payloads


def build(
    previous: Path,
    manifest: Path,
    version: str,
) -> tuple[Path, Path]:
    if addon_version() != version:
        raise ValueError(
            "addon.xml version is %s, requested %s" % (addon_version(), version)
        )
    output = DIST / ("plugin.program.kodipovilwizard-%s.zip" % version)
    latest = DIST / "plugin.program.kodipovilwizard-latest.zip"
    page_output = WIZARD_PAGE / output.name
    page_latest = WIZARD_PAGE / latest.name
    replace, add, expected_sha = _release_plan(previous, manifest, version)
    changed = replace | add
    payloads = _replacement_payloads(changed)
    with ZipFile(previous) as old:
        old_infos = old.infolist()
        old_names = {info.filename for info in old_infos}
        if not old_names <= set(payloads):
            raise ValueError(
                "previous Wizard has members absent from source: %r"
                % sorted(old_names - set(payloads))
            )
        if set(payloads) - old_names != add:
            raise ValueError(
                "source/previous additions differ from release manifest: %r"
                % sorted((set(payloads) - old_names) ^ add)
            )
        with ZipFile(
            output,
            mode="w",
            compression=ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for info in old_infos:
                data = (
                    payloads[info.filename]
                    if info.filename in changed
                    else old.read(info)
                )
                if data is None:
                    raise AssertionError(
                        "changed Wizard payload is empty: %s" % info.filename
                    )
                archive.writestr(info, data, compresslevel=9)
            for name in sorted(set(payloads) - old_names):
                data = payloads[name]
                if data is None:
                    raise AssertionError(
                        "new Wizard path was not classified as changed: %s" % name
                    )
                # Git does not carry file mtimes. Give newly added members stable
                # metadata so rebuilding the same source is byte-reproducible.
                info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = ZIP_DEFLATED
                archive.writestr(
                    info,
                    data,
                    compress_type=ZIP_DEFLATED,
                    compresslevel=9,
                )
    verify(previous, manifest, output, version)
    actual_sha = hashlib.sha256(output.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        raise AssertionError(
            "Wizard output SHA-256 mismatch: %s != %s"
            % (actual_sha, expected_sha)
        )
    for published in (latest, page_output, page_latest):
        shutil.copyfile(output, published)
        if output.read_bytes() != published.read_bytes():
            raise AssertionError(
                "published Wizard ZIP is not byte-identical: %s" % published
            )
    return output, latest


def verify(
    previous: Path,
    manifest: Path,
    path: Path,
    version: str,
) -> None:
    replace, add, expected_sha = _release_plan(previous, manifest, version)
    changed = replace | add
    expected = _replacement_payloads(changed)
    with ZipFile(previous) as old, ZipFile(path) as archive:
        old_by_name = {info.filename: info for info in old.infolist()}
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise AssertionError("Wizard ZIP has duplicate paths")
        if set(names) != set(expected):
            missing = sorted(set(expected) - set(names))
            extra = sorted(set(names) - set(expected))
            raise AssertionError(
                "Wizard ZIP/source mismatch; missing=%r extra=%r"
                % (missing, extra)
            )
        new_by_name = {info.filename: info for info in archive.infolist()}
        for name, canonical in expected.items():
            pure = PurePosixPath(name)
            if (pure.is_absolute() or ".." in pure.parts
                    or _unsafe_member(name)):
                raise AssertionError("unsafe Wizard ZIP path: %s" % name)
            if name in changed:
                if canonical is None:
                    raise AssertionError(
                        "changed Wizard payload has no canonical bytes: %s" % name
                    )
                if archive.read(name) != canonical:
                    raise AssertionError(
                        "changed Wizard payload is not the canonical Git blob: %s"
                        % name
                    )
            else:
                if name not in old_by_name:
                    raise AssertionError(
                        "unchanged source file is unexpectedly new: %s" % name
                    )
                if archive.read(name) != old.read(name):
                    raise AssertionError(
                        "unchanged Wizard payload drifted from previous ZIP: %s"
                        % name
                    )
                old_info = old_by_name[name]
                new_info = new_by_name[name]
                stable_meta = (
                    "date_time",
                    "compress_type",
                    "comment",
                    "extra",
                    "create_system",
                    "create_version",
                    "extract_version",
                    "flag_bits",
                    "volume",
                    "internal_attr",
                    "external_attr",
                )
                for attribute in stable_meta:
                    if getattr(old_info, attribute) != getattr(new_info, attribute):
                        raise AssertionError(
                            "unchanged Wizard metadata drifted for %s: %s"
                            % (name, attribute)
                        )
        xml = archive.read(PREFIX + "addon.xml").decode("utf-8")
        if 'version="%s"' % version not in xml:
            raise AssertionError("Wizard ZIP addon.xml version is inconsistent")
    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        raise AssertionError(
            "verified Wizard SHA-256 mismatch: %s != %s"
            % (actual_sha, expected_sha)
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    output, latest = build(args.previous, args.manifest, args.version)
    print(
        "built %s (%s), latest sha256=%s"
        % (
            output,
            output.stat().st_size,
            hashlib.sha256(latest.read_bytes()).hexdigest(),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
