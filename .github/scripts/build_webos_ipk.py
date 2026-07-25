#!/usr/bin/env python3
"""Patch and verify the official Kodi webOS IPK without metadata churn.

The previous release workflow extracted the entire data archive and recreated
it as the GitHub runner user.  That changed uid/gid/path metadata for every
file, and it wrote a non-webOS version string (``21.3-povil.47``) into
``appinfo.json`` while leaving two other package versions at ``21.0.0``.

This builder streams the original tar members back out with their original
TarInfo metadata and ordering.  It changes only the explicitly branded files,
adds the wizard/dependencies, and then performs an independent structural
verification of the completed IPK.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import io
import json
import re
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable
from zipfile import ZipFile, ZipInfo

from PIL import Image


APP_ID = "org.xbmc.kodi"
APP_ROOT = "usr/palm/applications/%s" % APP_ID
PACKAGE_INFO = "usr/palm/packages/%s/packageinfo.json" % APP_ID
APP_INFO = APP_ROOT + "/appinfo.json"
ADDON_MANIFEST = APP_ROOT + "/system/addon-manifest.xml"
RELEASE_MARKER = APP_ROOT + "/system/povil-release.txt"
ADDONS_ROOT = APP_ROOT + "/addons"

ADDONS_TO_ENABLE = (
    "plugin.program.kodipovilwizard",
    "script.module.requests",
    "script.module.six",
    "script.module.certifi",
    "script.module.urllib3",
    "script.module.chardet",
    "script.module.idna",
)
DEPENDENCY_IDS = ADDONS_TO_ENABLE[1:]

MEDIA_ICON_NAMES = (
    "icon16x16.png",
    "icon32x32.png",
    "icon48x48.png",
    "icon80x80.png",
    "icon120x120.png",
    "icon256x256.png",
    "vendor_icon.png",
)

TRANSFORMED_DATA_MEMBERS = {
    APP_INFO,
    PACKAGE_INFO,
    ADDON_MANIFEST,
    APP_ROOT + "/icon.png",
    APP_ROOT + "/largeIcon.png",
    APP_ROOT + "/media/applaunch_screen.png",
    APP_ROOT + "/media/splash.jpg",
    *(APP_ROOT + "/media/" + name for name in MEDIA_ICON_NAMES),
}

_WEBOS_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_RELEASE_RE = re.compile(r"^([0-9]+)\.([0-9]+)-povil\.([0-9]+)$")


@dataclass(frozen=True)
class ArMember:
    name: str
    header: bytes
    data: bytes


def release_to_webos_version(release_label: str) -> str:
    match = _RELEASE_RE.fullmatch(release_label.strip())
    if not match:
        raise ValueError(
            "release label must look like 21.3-povil.48: %r" % release_label
        )
    return ".".join(match.groups())


def read_ar(path: Path) -> list[ArMember]:
    payload = path.read_bytes()
    if not payload.startswith(b"!<arch>\n"):
        raise ValueError("%s is not an ar archive" % path)
    pos = 8
    members: list[ArMember] = []
    while pos < len(payload):
        header = payload[pos : pos + 60]
        if len(header) != 60 or header[58:60] != b"`\n":
            raise ValueError("invalid ar header at byte %d" % pos)
        pos += 60
        try:
            size = int(header[48:58].decode("ascii").strip())
        except ValueError as exc:
            raise ValueError("invalid ar member size at byte %d" % (pos - 60)) from exc
        data = payload[pos : pos + size]
        if len(data) != size:
            raise ValueError("truncated ar member at byte %d" % pos)
        pos += size
        if size & 1:
            pos += 1
        name = header[:16].decode("ascii").strip().rstrip("/")
        members.append(ArMember(name=name, header=header, data=data))
    return members


def write_ar(path: Path, members: Iterable[ArMember]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as output:
        output.write(b"!<arch>\n")
        for member in members:
            header = bytearray(member.header)
            encoded_size = ("%-10d" % len(member.data)).encode("ascii")
            if len(encoded_size) != 10:
                raise ValueError("ar member is too large: %s" % member.name)
            header[48:58] = encoded_size
            output.write(header)
            output.write(member.data)
            if len(member.data) & 1:
                output.write(b"\n")


def _normal_name(name: str) -> str:
    while name.startswith("./"):
        name = name[2:]
    return name.rstrip("/") if name != "/" else name


def _safe_relative(name: str) -> str:
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("unsafe archive path: %r" % name)
    return path.as_posix()


def _json_bytes(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _patch_control(payload: bytes, webos_version: str) -> bytes:
    text = payload.decode("utf-8")
    patched, count = re.subn(
        r"(?m)^Version:[^\r\n]*$",
        "Version: " + webos_version,
        text,
        count=1,
    )
    if count != 1:
        raise ValueError("control archive does not contain exactly one Version field")
    return patched.encode("utf-8")


def _patch_appinfo(payload: bytes, webos_version: str) -> bytes:
    data = json.loads(payload.decode("utf-8"))
    if data.get("id") != APP_ID or data.get("main") != "kodi-webos":
        raise ValueError("unexpected official appinfo.json identity")
    data["version"] = webos_version
    data["title"] = "Kodi POV IL"
    data["vendor"] = "Kodi POV IL"
    return _json_bytes(data)


def _patch_packageinfo(payload: bytes, webos_version: str) -> bytes:
    data = json.loads(payload.decode("utf-8"))
    if data.get("id") != APP_ID or data.get("app") != APP_ID:
        raise ValueError("unexpected official packageinfo.json identity")
    data["version"] = webos_version
    return _json_bytes(data)


def _patch_manifest(payload: bytes) -> bytes:
    text = payload.decode("utf-8")
    if text.count("</addons>") != 1:
        raise ValueError("addon-manifest.xml has no unique closing tag")
    for addon_id in ADDONS_TO_ENABLE:
        pattern = re.compile(
            r"<addon\b[^>]*>\s*%s\s*</addon>" % re.escape(addon_id)
        )
        if pattern.search(text):
            raise ValueError(
                "%s already ships in the official IPK; refusing to overwrite it"
                % addon_id
            )
    insertion = "".join(
        '  <addon optional="true">%s</addon>\n' % addon_id
        for addon_id in ADDONS_TO_ENABLE
    )
    return text.replace("</addons>", insertion + "</addons>").encode("utf-8")


def _read_brand_files(branding_dir: Path) -> dict[str, bytes]:
    mapping = {
        APP_ROOT + "/icon.png": branding_dir / "icon.png",
        APP_ROOT + "/largeIcon.png": branding_dir / "largeIcon.png",
        APP_ROOT + "/media/applaunch_screen.png": branding_dir / "applaunch_screen.png",
        APP_ROOT + "/media/splash.jpg": branding_dir / "source-splash.jpg",
    }
    for name in MEDIA_ICON_NAMES:
        mapping[APP_ROOT + "/media/" + name] = branding_dir / "media" / name
    output: dict[str, bytes] = {}
    for member_name, source in mapping.items():
        if not source.is_file():
            raise ValueError("missing generated branding asset: %s" % source)
        output[member_name] = source.read_bytes()
    return output


def _zip_payloads(
    wizard_zip: Path,
    build_zip: Path,
    existing_names: set[str],
) -> tuple[list[tuple[str, bytes, int]], str]:
    payloads: list[tuple[str, bytes, int]] = []

    def add_zip_member(
        archive: ZipFile,
        info: ZipInfo,
        destination: str,
    ) -> None:
        destination = _safe_relative(destination)
        if destination in existing_names:
            raise ValueError(
                "%s already ships inside the official IPK; refusing to overwrite it"
                % destination
            )
        mode = (info.external_attr >> 16) & 0o7777
        if not mode:
            mode = 0o755 if info.is_dir() else 0o644
        data = b"" if info.is_dir() else archive.read(info)
        payloads.append((destination, data, mode))
        existing_names.add(destination)

    with ZipFile(wizard_zip) as archive:
        addon_xml_name = "plugin.program.kodipovilwizard/addon.xml"
        try:
            addon_xml = archive.read(addon_xml_name).decode("utf-8")
        except KeyError as exc:
            raise ValueError("wizard zip has no %s" % addon_xml_name) from exc
        version_match = re.search(
            r'<addon\b[^>]*\bid="plugin\.program\.kodipovilwizard"[^>]*'
            r'\bversion="([^"]+)"',
            addon_xml,
        )
        if not version_match:
            raise ValueError("cannot read wizard version from addon.xml")
        wizard_version = version_match.group(1)
        for info in archive.infolist():
            # Directory entries carry no useful payload.  Skipping them lets
            # _addition_infos synthesize every missing parent with one
            # consistent webOS directory template; otherwise rstrip("/") made
            # an empty ZIP directory look like a zero-byte regular file.
            if info.is_dir():
                continue
            name = _safe_relative(info.filename.rstrip("/"))
            if not (
                name == "plugin.program.kodipovilwizard"
                or name.startswith("plugin.program.kodipovilwizard/")
            ):
                raise ValueError("unexpected wizard member: %s" % name)
            add_zip_member(archive, info, ADDONS_ROOT + "/" + name)

    allowed = tuple("addons/%s/" % addon_id for addon_id in DEPENDENCY_IDS)
    found = {addon_id: False for addon_id in DEPENDENCY_IDS}
    with ZipFile(build_zip) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            raw = info.filename.rstrip("/")
            if not raw:
                continue
            if not raw.startswith(allowed):
                continue
            name = _safe_relative(raw)
            destination = APP_ROOT + "/" + name
            add_zip_member(archive, info, destination)
            for addon_id in DEPENDENCY_IDS:
                if name == "addons/%s/addon.xml" % addon_id:
                    found[addon_id] = True
    missing = sorted(addon_id for addon_id, present in found.items() if not present)
    if missing:
        raise ValueError("build zip is missing dependency addon.xml: %s" % missing)
    return payloads, wizard_version


def _copy_metadata(template: tarfile.TarInfo, name: str) -> tarfile.TarInfo:
    info = copy.copy(template)
    info.name = name
    info.pax_headers = dict(template.pax_headers)
    return info


def _addition_infos(
    payloads: list[tuple[str, bytes, int]],
    existing_infos: dict[str, tarfile.TarInfo],
    file_template: tarfile.TarInfo,
    dir_template: tarfile.TarInfo,
) -> list[tuple[tarfile.TarInfo, bytes]]:
    additions: list[tuple[tarfile.TarInfo, bytes]] = []
    known = set(existing_infos)

    def ensure_dirs(path: str) -> None:
        parts = PurePosixPath(path).parts[:-1]
        for end in range(1, len(parts) + 1):
            directory = PurePosixPath(*parts[:end]).as_posix()
            if directory in known:
                continue
            info = _copy_metadata(dir_template, directory)
            info.type = tarfile.DIRTYPE
            info.size = 0
            info.mode = 0o755
            info.linkname = ""
            additions.append((info, b""))
            known.add(directory)

    for name, data, mode in payloads:
        ensure_dirs(name)
        if name in known:
            # Directory entries from ZIPs commonly follow a parent we already
            # synthesized.  A file collision, however, is never acceptable.
            if data:
                raise ValueError("duplicate injected webOS path: %s" % name)
            continue
        is_dir = not data and name.endswith("/")
        template = dir_template if is_dir else file_template
        info = _copy_metadata(template, name.rstrip("/"))
        info.type = tarfile.DIRTYPE if is_dir else tarfile.REGTYPE
        info.size = 0 if is_dir else len(data)
        info.mode = 0o755 if is_dir else (mode or 0o644)
        info.linkname = ""
        additions.append((info, data))
        known.add(info.name)
    return additions


def _rewrite_tar_gz(
    raw: bytes,
    transform: Callable[[str, bytes], bytes | None],
    additions_factory: Callable[
        [dict[str, tarfile.TarInfo]], list[tuple[tarfile.TarInfo, bytes]]
    ]
    | None = None,
) -> bytes:
    source_buffer = io.BytesIO(raw)
    output_buffer = io.BytesIO()
    with tarfile.open(fileobj=source_buffer, mode="r:gz") as source:
        members = source.getmembers()
        infos = {_normal_name(member.name): member for member in members}
        with gzip.GzipFile(
            filename="",
            fileobj=output_buffer,
            mode="wb",
            compresslevel=9,
            mtime=0,
        ) as gz:
            with tarfile.open(
                fileobj=gz,
                mode="w",
                # The official IPK uses GNU long-name records and has no
                # logical PAX headers.  TarFile reports read archives as PAX
                # format even in that case; writing with source.format would
                # manufacture ``path`` PAX metadata for long members and break
                # metadata identity. GNU_FORMAT keeps the original logical
                # TarInfo fields stable.
                format=tarfile.GNU_FORMAT,
            ) as output:
                for member in members:
                    info = copy.copy(member)
                    info.pax_headers = dict(member.pax_headers)
                    normalized = _normal_name(member.name)
                    if member.isfile():
                        extracted = source.extractfile(member)
                        if extracted is None:
                            raise ValueError("cannot read tar member: %s" % member.name)
                        payload = extracted.read()
                        replacement = transform(normalized, payload)
                        if replacement is not None:
                            payload = replacement
                            info.size = len(payload)
                        output.addfile(info, io.BytesIO(payload))
                    else:
                        output.addfile(info)
                if additions_factory:
                    for info, payload in additions_factory(infos):
                        output.addfile(
                            info,
                            io.BytesIO(payload) if info.isfile() else None,
                        )
    return output_buffer.getvalue()


def build_ipk(
    official_ipk: Path,
    wizard_zip: Path,
    build_zip: Path,
    branding_dir: Path,
    release_label: str,
    output_ipk: Path,
) -> tuple[str, str]:
    webos_version = release_to_webos_version(release_label)
    members = read_ar(official_ipk)
    by_name = {member.name: member for member in members}
    expected_order = ["debian-binary", "control.tar.gz", "data.tar.gz"]
    if [member.name for member in members] != expected_order:
        raise ValueError("unexpected IPK ar member order")

    control_data = _rewrite_tar_gz(
        by_name["control.tar.gz"].data,
        lambda name, payload: (
            _patch_control(payload, webos_version)
            if name == "control"
            else None
        ),
    )

    brand_files = _read_brand_files(branding_dir)
    wizard_version_holder: list[str] = []

    def additions_factory(
        infos: dict[str, tarfile.TarInfo],
    ) -> list[tuple[tarfile.TarInfo, bytes]]:
        existing_names = set(infos)
        payloads, wizard_version = _zip_payloads(
            wizard_zip,
            build_zip,
            existing_names,
        )
        wizard_version_holder.append(wizard_version)
        payloads.append((RELEASE_MARKER, (release_label + "\n").encode("utf-8"), 0o644))
        file_template = infos[APP_INFO]
        dir_template = infos[ADDONS_ROOT]
        return _addition_infos(
            payloads,
            infos,
            file_template=file_template,
            dir_template=dir_template,
        )

    def transform_data(name: str, payload: bytes) -> bytes | None:
        if name == APP_INFO:
            return _patch_appinfo(payload, webos_version)
        if name == PACKAGE_INFO:
            return _patch_packageinfo(payload, webos_version)
        if name == ADDON_MANIFEST:
            return _patch_manifest(payload)
        return brand_files.get(name)

    data_data = _rewrite_tar_gz(
        by_name["data.tar.gz"].data,
        transform_data,
        additions_factory,
    )
    if len(wizard_version_holder) != 1:
        raise AssertionError("wizard payload was not assembled exactly once")

    replacement = {
        "control.tar.gz": control_data,
        "data.tar.gz": data_data,
    }
    output_members = [
        ArMember(member.name, member.header, replacement.get(member.name, member.data))
        for member in members
    ]
    write_ar(output_ipk, output_members)
    verify_ipk(
        official_ipk=official_ipk,
        built_ipk=output_ipk,
        branding_dir=branding_dir,
        release_label=release_label,
        wizard_version=wizard_version_holder[0],
    )
    return webos_version, wizard_version_holder[0]


def _tar_payload_map(raw: bytes) -> tuple[list[tarfile.TarInfo], tarfile.TarFile]:
    archive = tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz")
    return archive.getmembers(), archive


def _metadata_tuple(info: tarfile.TarInfo) -> tuple[object, ...]:
    return (
        info.uid,
        info.gid,
        info.mode,
        info.mtime,
        info.type,
        info.linkname,
        info.uname,
        info.gname,
        info.devmajor,
        info.devminor,
        dict(info.pax_headers),
    )


def _read_json(archive: tarfile.TarFile, info: tarfile.TarInfo) -> dict[str, object]:
    extracted = archive.extractfile(info)
    if extracted is None:
        raise AssertionError("cannot read %s" % info.name)
    return json.loads(extracted.read().decode("utf-8"))


def _read_member(archive: tarfile.TarFile, info: tarfile.TarInfo) -> bytes:
    extracted = archive.extractfile(info)
    if extracted is None:
        raise AssertionError("cannot read %s" % info.name)
    return extracted.read()


def _image_size_and_digest(payload: bytes) -> tuple[tuple[int, int], str]:
    with Image.open(io.BytesIO(payload)) as image:
        rgba = image.convert("RGBA")
        digest = hashlib.sha256(
            ("%dx%d:" % rgba.size).encode("ascii") + rgba.tobytes()
        ).hexdigest()
        return image.size, digest


def verify_ipk(
    official_ipk: Path,
    built_ipk: Path,
    branding_dir: Path,
    release_label: str,
    wizard_version: str,
) -> None:
    webos_version = release_to_webos_version(release_label)
    if not _WEBOS_VERSION_RE.fullmatch(webos_version):
        raise AssertionError("invalid webOS version: %s" % webos_version)

    official_ar = read_ar(official_ipk)
    built_ar = read_ar(built_ipk)
    if [member.name for member in built_ar] != [
        "debian-binary",
        "control.tar.gz",
        "data.tar.gz",
    ]:
        raise AssertionError("built IPK member order is invalid")
    if built_ar[0].data != b"2.0\n" or built_ar[0].data != official_ar[0].data:
        raise AssertionError("debian-binary changed")

    official_by = {member.name: member for member in official_ar}
    built_by = {member.name: member for member in built_ar}

    with tarfile.open(
        fileobj=io.BytesIO(official_by["control.tar.gz"].data),
        mode="r:gz",
    ) as original_control, tarfile.open(
        fileobj=io.BytesIO(built_by["control.tar.gz"].data),
        mode="r:gz",
    ) as new_control:
        original_info = original_control.getmembers()[0]
        new_info = new_control.getmembers()[0]
        if _normal_name(original_info.name) != "control" or _normal_name(new_info.name) != "control":
            raise AssertionError("control.tar.gz layout changed")
        if _metadata_tuple(original_info) != _metadata_tuple(new_info):
            raise AssertionError("control TarInfo metadata changed")
        control_text = _read_member(new_control, new_info).decode("utf-8")
        fields = dict(
            line.split(":", 1)
            for line in control_text.splitlines()
            if ":" in line
        )
        if fields.get("Package", "").strip() != APP_ID:
            raise AssertionError("control Package id changed")
        if fields.get("Version", "").strip() != webos_version:
            raise AssertionError("control Version is inconsistent")

    with tarfile.open(
        fileobj=io.BytesIO(official_by["data.tar.gz"].data),
        mode="r:gz",
    ) as original, tarfile.open(
        fileobj=io.BytesIO(built_by["data.tar.gz"].data),
        mode="r:gz",
    ) as built:
        original_members = original.getmembers()
        built_members = built.getmembers()
        original_names = [_normal_name(member.name) for member in original_members]
        built_names = [_normal_name(member.name) for member in built_members]
        if built_names[: len(original_names)] != original_names:
            raise AssertionError("original data.tar.gz member order/path set changed")
        if len(built_names) <= len(original_names):
            raise AssertionError("wizard/dependencies were not added")

        original_map = {
            _normal_name(member.name): member for member in original_members
        }
        built_map = {_normal_name(member.name): member for member in built_members}
        for name, original_info in original_map.items():
            built_info = built_map[name]
            if _metadata_tuple(original_info) != _metadata_tuple(built_info):
                raise AssertionError("TarInfo metadata changed for %s" % name)
            if (
                original_info.isfile()
                and name not in TRANSFORMED_DATA_MEMBERS
                and _read_member(original, original_info)
                != _read_member(built, built_info)
            ):
                raise AssertionError("unchanged webOS payload bytes changed for %s" % name)

        # Compare the native executable byte-for-byte as a representative
        # high-risk unchanged member.  It also confirms its executable mode.
        executable_name = APP_ROOT + "/kodi-webos"
        original_exe = original_map[executable_name]
        built_exe = built_map[executable_name]
        if not (built_exe.mode & 0o111):
            raise AssertionError("kodi-webos lost its executable mode")
        if _read_member(original, original_exe) != _read_member(built, built_exe):
            raise AssertionError("kodi-webos bytes changed")

        appinfo = _read_json(built, built_map[APP_INFO])
        packageinfo = _read_json(built, built_map[PACKAGE_INFO])
        if appinfo.get("id") != APP_ID or packageinfo.get("id") != APP_ID:
            raise AssertionError("webOS app id changed; update-in-place would break")
        if packageinfo.get("app") != APP_ID:
            raise AssertionError("packageinfo app id changed")
        if appinfo.get("version") != webos_version:
            raise AssertionError("appinfo version is inconsistent")
        if packageinfo.get("version") != webos_version:
            raise AssertionError("packageinfo version is inconsistent")
        if appinfo.get("title") != "Kodi POV IL":
            raise AssertionError("appinfo title was not branded")

        manifest_payload = _read_member(built, built_map[ADDON_MANIFEST]).decode("utf-8")
        for addon_id in ADDONS_TO_ENABLE:
            expected = '<addon optional="true">%s</addon>' % addon_id
            if manifest_payload.count(expected) != 1:
                raise AssertionError(
                    "manifest does not contain one optional %s" % addon_id
                )
            addon_xml = ADDONS_ROOT + "/" + addon_id + "/addon.xml"
            if addon_xml not in built_map:
                raise AssertionError("missing bundled addon: %s" % addon_id)

        wizard_xml = _read_member(
            built,
            built_map[ADDONS_ROOT + "/plugin.program.kodipovilwizard/addon.xml"],
        ).decode("utf-8")
        if 'version="%s"' % wizard_version not in wizard_xml:
            raise AssertionError("bundled wizard version is inconsistent")

        marker = _read_member(built, built_map[RELEASE_MARKER]).decode("utf-8")
        if marker != release_label + "\n":
            raise AssertionError("webOS release marker is inconsistent")
        if _read_member(
            built,
            built_map[APP_ROOT + "/media/splash.jpg"],
        ) != (branding_dir / "source-splash.jpg").read_bytes():
            raise AssertionError("webOS splash.jpg is not the POV IL splash")

        expected_images = {
            APP_ROOT + "/icon.png": (branding_dir / "icon.png", (80, 80)),
            APP_ROOT + "/largeIcon.png": (
                branding_dir / "largeIcon.png",
                (130, 130),
            ),
            APP_ROOT + "/media/applaunch_screen.png": (
                branding_dir / "applaunch_screen.png",
                (1920, 1080),
            ),
        }
        for name in MEDIA_ICON_NAMES:
            source = branding_dir / "media" / name
            with Image.open(source) as expected_image:
                expected_size = expected_image.size
            expected_images[APP_ROOT + "/media/" + name] = (
                source,
                expected_size,
            )
        for member_name, (expected_path, expected_size) in expected_images.items():
            actual_size, actual_digest = _image_size_and_digest(
                _read_member(built, built_map[member_name])
            )
            expected_actual_size, expected_digest = _image_size_and_digest(
                expected_path.read_bytes()
            )
            if actual_size != expected_size or expected_actual_size != expected_size:
                raise AssertionError("wrong icon dimensions for %s" % member_name)
            if actual_digest != expected_digest:
                raise AssertionError("wrong icon pixels for %s" % member_name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build")
    build.add_argument("--official", type=Path, required=True)
    build.add_argument("--wizard", type=Path, required=True)
    build.add_argument("--build-zip", type=Path, required=True)
    build.add_argument("--branding-dir", type=Path, required=True)
    build.add_argument("--release-label", required=True)
    build.add_argument("--output", type=Path, required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--official", type=Path, required=True)
    verify.add_argument("--built", type=Path, required=True)
    verify.add_argument("--branding-dir", type=Path, required=True)
    verify.add_argument("--release-label", required=True)
    verify.add_argument("--wizard-version", required=True)

    args = parser.parse_args(argv)
    if args.command == "build":
        webos_version, wizard_version = build_ipk(
            official_ipk=args.official,
            wizard_zip=args.wizard,
            build_zip=args.build_zip,
            branding_dir=args.branding_dir,
            release_label=args.release_label,
            output_ipk=args.output,
        )
        print(
            "built %s: webOS version %s, wizard %s"
            % (args.output, webos_version, wizard_version)
        )
    else:
        verify_ipk(
            official_ipk=args.official,
            built_ipk=args.built,
            branding_dir=args.branding_dir,
            release_label=args.release_label,
            wizard_version=args.wizard_version,
        )
        print("verified %s" % args.built)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, OSError, ValueError) as exc:
        print("webOS IPK error: %s" % exc, file=sys.stderr)
        raise SystemExit(1)
