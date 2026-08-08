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
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ADDON_ID = "service.subtitles.kodipovilai"
QUICKFIX_PREFIX = f"addons/{ADDON_ID}/"
ADDON_ZIP_PREFIX = f"{ADDON_ID}/"
POOL_MEMBER = QUICKFIX_PREFIX + "resources/lib/pool.py"


def build(previous: Path, addon_zip: Path, output: Path,
          allow_add: list[str] | None = None) -> list[str]:
    allow_add = sorted(set(allow_add or []))
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
        if missing or sorted(extra) != allow_add:
            raise SystemExit(
                "add-on member set differs from the previous quickfix.\n"
                f"  only in quickfix: {sorted(missing)[:20]}\n"
                f"  only in new zip : {sorted(extra)[:20]}\n"
                f"  --allow-add     : {allow_add[:20]}\n"
                "A quickfix must not add or drop files; a genuinely new file "
                "must be named explicitly with --allow-add, so the decision "
                "is deliberate, never silent."
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
            for name in allow_add:
                # a NEW member, appended last with fixed metadata so the
                # build is deterministic (same convention as the Wizard
                # packager: zeroed DOS epoch, plain 0644 file bits)
                info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = ZIP_DEFLATED
                new.writestr(info, new_payload[name])
                changed.append(name)
    return changed


def verify(previous: Path, output: Path, changed: list[str],
           allow_add: list[str] | None = None) -> None:
    allow_add = sorted(set(allow_add or []))
    with ZipFile(previous) as old, ZipFile(output) as new:
        oi, ni = old.infolist(), new.infolist()
        expected_names = [i.filename for i in oi] + allow_add
        if [i.filename for i in ni] != expected_names:
            raise SystemExit("member names or order changed")
        for info in ni[len(oi):]:
            # appended members carry the fixed deterministic metadata
            if (info.date_time != (1980, 1, 1, 0, 0, 0)
                    or info.external_attr != 0o100644 << 16):
                raise SystemExit(
                    f"added member has drifting metadata: {info.filename}")
            if not info.filename.startswith(QUICKFIX_PREFIX):
                raise SystemExit(
                    f"added member outside the add-on subtree: {info.filename}")
        ni = ni[:len(oi)]
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
        for name in allow_add:
            if not new.read(name):
                raise SystemExit(f"added member is empty: {name}")
            actually.append(name)
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
    ap.add_argument("--allow-add", action="append", default=[],
                    metavar="MEMBER",
                    help="quickfix member path a NEW file is allowed to add "
                         "(repeatable); anything unlisted still aborts")
    args = ap.parse_args()
    changed = build(args.previous, args.addon_zip, args.output,
                    args.allow_add)
    verify(args.previous, args.output, changed, args.allow_add)
    print(f"built {args.output} ({args.output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
