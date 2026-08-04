#!/usr/bin/env python3
"""Create a quickfix by replacing only the MoranSubs add-on inside it.

The shipping rule is "copy the previous quickfix and replace only the changed
files, never rebuild from scratch", and until now the only tool for it covered
the Wizard subtree (build_wizard_quickfix.py). The add-on subtree was done by
hand each time, which is the part of the release most worth not improvising:
the quickfix is a whole build tree, and a member set that shifts by one file
is a device that loses it.

Every replacement payload is taken from the already-built and already-verified
BUILD-EDITION add-on zip, never from the worktree -- the packaging step
normalises line endings and provisions pool.py, so worktree bytes are not the
bytes that ship. Each member keeps its original ZipInfo (name, order,
timestamp, compression, attributes); only the payload changes.

Usage:
  python3 tools/build_addon_quickfix.py \
      --previous dist/Kodi-POV-IL-FENtastic-quickfix-0.1.504.zip \
      --addon-zip dist/service.subtitles.kodipovilai-build-0.2.463.zip \
      --output dist/Kodi-POV-IL-FENtastic-quickfix-0.1.505.zip
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from zipfile import ZipFile

ADDON_ID = "service.subtitles.kodipovilai"
QUICKFIX_PREFIX = f"addons/{ADDON_ID}/"
ADDON_ZIP_PREFIX = f"{ADDON_ID}/"
POOL_MEMBER = QUICKFIX_PREFIX + "resources/lib/pool.py"


def build(previous: Path, addon_zip: Path, output: Path) -> list[str]:
    with ZipFile(addon_zip) as az:
        new_payload = {
            QUICKFIX_PREFIX + info.filename[len(ADDON_ZIP_PREFIX):]:
                az.read(info)
            for info in az.infolist()
            if not info.is_dir() and info.filename.startswith(ADDON_ZIP_PREFIX)
        }
    if not new_payload:
        raise SystemExit(f"{addon_zip} has no {ADDON_ZIP_PREFIX} members")

    changed: list[str] = []
    with ZipFile(previous) as old:
        old_names = [i.filename for i in old.infolist()]
        old_addon = {n for n in old_names if n.startswith(QUICKFIX_PREFIX)
                     and not n.endswith("/")}
        missing = old_addon - set(new_payload)
        extra = set(new_payload) - old_addon
        if missing or extra:
            raise SystemExit(
                "add-on member set differs from the previous quickfix.\n"
                f"  only in quickfix: {sorted(missing)[:20]}\n"
                f"  only in new zip : {sorted(extra)[:20]}\n"
                "A quickfix must not add or drop files; if this is intended, "
                "it needs a deliberate decision, not a silent one."
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(output, "w") as new:
            for info in old.infolist():
                data = old.read(info) if not info.is_dir() else b""
                if info.filename in new_payload:
                    replacement = new_payload[info.filename]
                    if replacement != data:
                        changed.append(info.filename)
                        data = replacement
                # the ORIGINAL ZipInfo: same order, timestamp, compression and
                # attributes, so nothing but the payload can differ
                new.writestr(info, data)
    return changed


def verify(previous: Path, output: Path, changed: list[str]) -> None:
    with ZipFile(previous) as old, ZipFile(output) as new:
        oi, ni = old.infolist(), new.infolist()
        if [i.filename for i in oi] != [i.filename for i in ni]:
            raise SystemExit("member names or order changed")
        stable = ("date_time", "compress_type", "comment", "extra",
                  "create_system", "create_version", "extract_version",
                  "flag_bits", "volume", "internal_attr", "external_attr")
        actually: list[str] = []
        for a, b in zip(oi, ni):
            for attr in stable:
                if getattr(a, attr) != getattr(b, attr):
                    raise SystemExit(
                        f"ZIP metadata changed for {a.filename}: {attr}")
            if a.is_dir():
                continue
            if old.read(a) != new.read(b):
                actually.append(a.filename)
        if sorted(actually) != sorted(changed):
            raise SystemExit(
                "payload changed on files that were not part of the update:\n"
                f"  expected: {sorted(changed)}\n  actual:   {sorted(actually)}")
        if old.read(POOL_MEMBER) != new.read(POOL_MEMBER):
            raise SystemExit("pool.py changed -- the community-pool credential "
                             "must be inherited untouched")
        outside = [n for n in actually if not n.startswith(QUICKFIX_PREFIX)]
        if outside:
            raise SystemExit(f"changes outside the add-on subtree: {outside}")
        print(f"verified {len(ni)} members; {len(actually)} payload change(s), "
              "all inside the add-on subtree:")
        for n in sorted(actually):
            print("   ", n)
        print("    pool.py sha256 =",
              hashlib.sha256(new.read(POOL_MEMBER)).hexdigest())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--previous", type=Path, required=True)
    ap.add_argument("--addon-zip", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    changed = build(args.previous, args.addon_zip, args.output)
    verify(args.previous, args.output, changed)
    print(f"built {args.output} ({args.output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
