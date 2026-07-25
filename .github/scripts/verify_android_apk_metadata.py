#!/usr/bin/env python3
"""Verify final Android package metadata with ``aapt dump badging``."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def _quoted_field(line: str, field: str) -> str:
    match = re.search(r"(?:^|[ \t])%s='([^']*)'" % re.escape(field), line)
    if not match:
        raise ValueError("missing %s in aapt package line" % field)
    return match.group(1)


def parse_badging(output: str) -> dict[str, object]:
    lines = output.splitlines()
    try:
        package_line = next(line for line in lines if line.startswith("package:"))
        label_line = next(
            line for line in lines if line.startswith("application-label:")
        )
        native_line = next(line for line in lines if line.startswith("native-code:"))
    except StopIteration as exc:
        raise ValueError("aapt badging output is missing required metadata") from exc

    label_match = re.fullmatch(r"application-label:'([^']*)'", label_line)
    if not label_match:
        raise ValueError("cannot parse application-label from aapt output")

    return {
        "package_id": _quoted_field(package_line, "name"),
        "version_code": _quoted_field(package_line, "versionCode"),
        "version_name": _quoted_field(package_line, "versionName"),
        "app_name": label_match.group(1),
        "native_codes": tuple(re.findall(r"'([^']+)'", native_line)),
    }


def verify_metadata(
    actual: dict[str, object],
    *,
    package_id: str,
    version_code: str,
    version_name: str,
    app_name: str,
    native_code: str,
) -> None:
    expected = {
        "package_id": package_id,
        "version_code": version_code,
        "version_name": version_name,
        "app_name": app_name,
        "native_codes": (native_code,),
    }
    mismatches = [
        "%s=%r (expected %r)" % (key, actual.get(key), value)
        for key, value in expected.items()
        if actual.get(key) != value
    ]
    if mismatches:
        raise ValueError("; ".join(mismatches))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aapt", default="aapt")
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--version-code", required=True)
    parser.add_argument("--version-name", required=True)
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--native-code", required=True)
    args = parser.parse_args(argv)

    result = subprocess.run(
        [args.aapt, "dump", "badging", str(args.apk)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise ValueError(
            "aapt failed with exit code %d: %s"
            % (result.returncode, result.stderr.strip())
        )
    actual = parse_badging(result.stdout)
    verify_metadata(
        actual,
        package_id=args.package_id,
        version_code=args.version_code,
        version_name=args.version_name,
        app_name=args.app_name,
        native_code=args.native_code,
    )
    print(
        "FINAL APK METADATA OK: %s code=%s name=%s abi=%s"
        % (
            args.package_id,
            args.version_code,
            args.version_name,
            args.native_code,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print("Android APK metadata error: %s" % exc, file=sys.stderr)
        raise SystemExit(1)
