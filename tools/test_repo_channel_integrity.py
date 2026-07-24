#!/usr/bin/env python3
"""Verify the Kodi repository checksum against Git/Pages-normalized bytes."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDONS_XML = ROOT / "repo" / "addons.xml"
ADDONS_MD5 = ROOT / "repo" / "addons.xml.md5"


def _git_pages_bytes(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def main() -> None:
    published = _git_pages_bytes(ADDONS_XML.read_bytes())
    expected = hashlib.md5(published).hexdigest().encode("ascii")
    declared = ADDONS_MD5.read_bytes()

    if not re.fullmatch(rb"[0-9a-f]{32}", declared):
        raise AssertionError(
            "repo/addons.xml.md5 must be exactly 32 lowercase hex bytes "
            "with no newline"
        )
    if declared != expected:
        raise AssertionError(
            "repo checksum mismatch: LF/Git/Pages addons.xml hashes to "
            f"{expected.decode()}, declared {declared.decode()}"
        )

    print(
        "PASS repo channel: MD5(LF-normalized addons.xml) == "
        f"addons.xml.md5 == {expected.decode()}"
    )


if __name__ == "__main__":
    main()
