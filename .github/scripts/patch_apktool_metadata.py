#!/usr/bin/env python3
"""Patch the version metadata that apktool writes back into an APK.

Apktool removes ``android:versionCode`` and ``android:versionName`` from its
decoded AndroidManifest.xml and stores them under ``versionInfo`` in
apktool.yml.  Editing only the decoded manifest is therefore a no-op: apktool
restores the upstream values during the next build.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


VERSION_CODE_RE = re.compile(r"(?m)^([ \t]*versionCode:[ \t]*).*$")
VERSION_NAME_RE = re.compile(r"(?m)^([ \t]*versionName:[ \t]*).*$")
SAFE_VERSION_NAME_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]*")


def _replace_one(text: str, pattern: re.Pattern[str], value: str, label: str) -> str:
    updated, count = pattern.subn(lambda match: match.group(1) + value, text)
    if count != 1:
        raise ValueError(
            "apktool.yml must contain exactly one %s entry; found %d"
            % (label, count)
        )
    return updated


def patch_apktool_metadata(
    path: Path,
    version_code: str,
    version_name: str,
) -> None:
    if not re.fullmatch(r"[1-9][0-9]*", version_code):
        raise ValueError("versionCode must be a positive integer")
    if not SAFE_VERSION_NAME_RE.fullmatch(version_name):
        raise ValueError("versionName is not a safe plain YAML scalar")

    text = path.read_text(encoding="utf-8")
    text = _replace_one(text, VERSION_CODE_RE, version_code, "versionCode")
    text = _replace_one(text, VERSION_NAME_RE, version_name, "versionName")
    path.write_text(text, encoding="utf-8")

    persisted = path.read_text(encoding="utf-8")
    if not re.search(
        r"(?m)^[ \t]*versionCode:[ \t]*%s[ \t]*$"
        % re.escape(version_code),
        persisted,
    ):
        raise ValueError("versionCode did not persist in apktool.yml")
    if not re.search(
        r"(?m)^[ \t]*versionName:[ \t]*%s[ \t]*$"
        % re.escape(version_name),
        persisted,
    ):
        raise ValueError("versionName did not persist in apktool.yml")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("apktool_yml", type=Path)
    parser.add_argument("version_code")
    parser.add_argument("version_name")
    args = parser.parse_args(argv)

    patch_apktool_metadata(
        args.apktool_yml,
        args.version_code,
        args.version_name,
    )
    print(
        "APKTOOL VERSION METADATA OK: versionCode=%s versionName=%s"
        % (args.version_code, args.version_name)
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print("apktool metadata error: %s" % exc, file=sys.stderr)
        raise SystemExit(1)
