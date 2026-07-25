#!/usr/bin/env python3
"""Create a quickfix by changing only the bundled Wizard subtree."""

from __future__ import annotations

import argparse
import copy
import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
WIZARD_PREFIX = "addons/plugin.program.kodipovilwizard/"
WIZARD_ZIP_PREFIX = "plugin.program.kodipovilwizard/"
FIXED_TIMESTAMP = (2026, 7, 25, 0, 0, 0)
POOL_MEMBER = "addons/service.subtitles.kodipovilai/resources/lib/pool.py"


def _wizard_zip_members(wizard_zip: Path) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    with ZipFile(wizard_zip) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if not info.filename.startswith(WIZARD_ZIP_PREFIX):
                raise ValueError(
                    "unexpected Wizard ZIP member: %s" % info.filename
                )
            relative = info.filename[len(WIZARD_ZIP_PREFIX) :]
            if not relative:
                raise ValueError("empty Wizard ZIP member")
            members[WIZARD_PREFIX + relative] = archive.read(info)
    return members


def _new_info(name: str, is_dir: bool) -> ZipInfo:
    normalized = name.rstrip("/") + "/" if is_dir else name
    info = ZipInfo(normalized, date_time=FIXED_TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.create_system = 3
    mode = 0o40755 if is_dir else 0o100644
    info.external_attr = (mode << 16) | (0x10 if is_dir else 0)
    return info


def _copy_info(info: ZipInfo) -> ZipInfo:
    copied = copy.copy(info)
    # Python recalculates these fields while writing.
    copied.CRC = 0
    copied.compress_size = 0
    copied.file_size = 0
    copied.header_offset = 0
    return copied


def build(
    previous: Path,
    output: Path,
    wizard_zip: Path,
    wizard_version: str,
) -> None:
    wizard_files = _wizard_zip_members(wizard_zip)
    with ZipFile(previous) as old:
        old_infos = old.infolist()
        old_names = [info.filename for info in old_infos]
        if len(old_names) != len(set(old_names)):
            raise ValueError("previous quickfix contains duplicate members")
        old_wizard_infos = {
            info.filename: info
            for info in old_infos
            if info.filename.startswith(WIZARD_PREFIX)
        }
        if not old_wizard_infos:
            raise ValueError("previous quickfix has no bundled Wizard")
        old_wizard_dirs = {
            name
            for name, info in old_wizard_infos.items()
            if info.is_dir()
        }
        expected_wizard = {
            **{name: None for name in old_wizard_dirs},
            **wizard_files,
        }
        first_wizard_index = min(
            index
            for index, info in enumerate(old_infos)
            if info.filename.startswith(WIZARD_PREFIX)
        )

        ordered_wizard_names = [
            info.filename
            for info in old_infos
            if info.filename.startswith(WIZARD_PREFIX)
            and info.filename in expected_wizard
        ]
        ordered_wizard_names.extend(
            sorted(set(expected_wizard) - set(ordered_wizard_names))
        )

        output.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(
            output,
            mode="w",
            compression=ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
        ) as new:
            injected = False
            for index, info in enumerate(old_infos):
                if index == first_wizard_index:
                    for name in ordered_wizard_names:
                        payload = expected_wizard[name]
                        template = old_wizard_infos.get(name)
                        out_info = (
                            _copy_info(template)
                            if template is not None
                            else _new_info(name, payload is None)
                        )
                        new.writestr(
                            out_info,
                            b"" if payload is None else payload,
                            compresslevel=9,
                        )
                    injected = True
                if info.filename.startswith(WIZARD_PREFIX):
                    continue
                new.writestr(
                    _copy_info(info),
                    old.read(info),
                    compresslevel=9,
                )
            if not injected:
                raise AssertionError("Wizard subtree was not injected")

    verify(previous, output, wizard_zip, wizard_version)


def verify(
    previous: Path,
    output: Path,
    wizard_zip: Path,
    wizard_version: str,
) -> None:
    wizard_files = _wizard_zip_members(wizard_zip)
    with ZipFile(previous) as old, ZipFile(output) as new:
        old_wizard_dirs = {
            info.filename
            for info in old.infolist()
            if info.filename.startswith(WIZARD_PREFIX) and info.is_dir()
        }
        expected_wizard: dict[str, bytes | None] = {
            **{name: None for name in old_wizard_dirs},
            **wizard_files,
        }
        old_non_wizard = {
            info.filename: info
            for info in old.infolist()
            if not info.filename.startswith(WIZARD_PREFIX)
        }
        new_infos = new.infolist()
        new_names = [info.filename for info in new_infos]
        if len(new_names) != len(set(new_names)):
            raise AssertionError("new quickfix contains duplicate members")
        if {
            name for name in new_names if name.startswith(WIZARD_PREFIX)
        } != set(expected_wizard):
            raise AssertionError(
                "new quickfix Wizard subtree differs from the Wizard ZIP"
            )
        if {
            name for name in new_names if not name.startswith(WIZARD_PREFIX)
        } != set(old_non_wizard):
            raise AssertionError("non-Wizard quickfix member set changed")

        new_by_name = {info.filename: info for info in new_infos}
        for name, old_info in old_non_wizard.items():
            new_info = new_by_name[name]
            if old.read(old_info) != new.read(new_info):
                raise AssertionError("non-Wizard payload changed: %s" % name)
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
                        "non-Wizard ZIP metadata changed for %s: %s"
                        % (name, attribute)
                    )

        for name, payload in expected_wizard.items():
            expected = b"" if payload is None else payload
            if new.read(name) != expected:
                raise AssertionError(
                    "quickfix Wizard payload differs from Wizard ZIP: %s" % name
                )

        addon_xml = new.read(WIZARD_PREFIX + "addon.xml").decode("utf-8")
        if 'version="%s"' % wizard_version not in addon_xml:
            raise AssertionError("quickfix carries the wrong Wizard version")
        if old.read(POOL_MEMBER) != new.read(POOL_MEMBER):
            raise AssertionError("pool.py changed while building Wizard quickfix")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wizard-zip", type=Path, required=True)
    parser.add_argument("--wizard-version", required=True)
    args = parser.parse_args()
    build(
        args.previous,
        args.output,
        args.wizard_zip,
        args.wizard_version,
    )
    with ZipFile(args.output) as archive:
        pool_sha = hashlib.sha256(archive.read(POOL_MEMBER)).hexdigest()
        print(
            "built %s (%d bytes); pool.py sha256=%s"
            % (args.output, args.output.stat().st_size, pool_sha)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
