#!/usr/bin/env python3
"""Assemble the opt-in Account Manager Lite pack.

Same shape as the Umbrella pilot pack: the third-party add-ons plus THEIR
repository add-on, so that once a user opts in, the pack stops being an
update channel -- AM Lite updates straight from its developer, exactly the
way POV updates from repository.kodifitzwell. We ship the bytes once; we do
not fork them and we do not maintain them.

Contents:
  script.module.acctmgr   -- Account Manager Lite (the thing itself)
  script.module.acctvwr   -- Account Viewer, a HARD dependency declared in
                             acctmgr's addon.xml; Kodi refuses to enable
                             acctmgr without it, and it is not in any repo
                             the build already carries
  repository.709          -- the developer's repo, so updates flow from him

Every source zip is taken verbatim from the developer's own repository
(github.com/Zaxxon709/zaxxon), and this tool refuses to build if a zip's
top-level folder does not equal the add-on id inside it: Kodi silently
ignores a repository whose folder name and id disagree, which is the exact
trap the Umbrella pack had to work around.

Usage:
  python3 tools/build_acctmgr_pack.py --source-dir <dir with the 3 zips>
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "Kodi-POV-IL-AcctMgr-pack.zip"

# Build artefacts and OS litter that upstream happens to have zipped up. The
# "verbatim" rule is about SOURCE bytes -- we neither fork nor edit a single
# line of the developer's code -- and stale bytecode is not source. Upstream
# ships ~90 .pyc files compiled for two interpreter versions; none of them is
# anything Kodi needs, and an unfiltered pack is how a .git or a .DS_Store
# ends up shipped the next time an upstream zip is a little untidy.
EXCLUDE_DIRS = ('__pycache__', '.git', '.github', '.svn')
EXCLUDE_NAMES = ('.DS_Store', 'Thumbs.db', 'desktop.ini')
EXCLUDE_SUFFIXES = ('.pyc', '.pyo')

# (add-on id, filename glob in the source dir)
MEMBERS = (
    ("script.module.acctmgr", "script.module.acctmgr-*.zip"),
    ("script.module.acctvwr", "script.module.acctvwr-*.zip"),
    ("repository.709", "repository.709-*.zip"),
)


def _addon_id(addon_xml: bytes) -> str:
    m = re.search(br'<addon\s+[^>]*id="([^"]+)"', addon_xml)
    if not m:
        raise SystemExit("addon.xml has no id attribute")
    return m.group(1).decode("utf-8")


def _addon_version(addon_xml: bytes) -> str:
    m = re.search(br'<addon\s+[^>]*version="([^"]+)"', addon_xml)
    return m.group(1).decode("utf-8") if m else "?"


def build(source_dir: Path, output: Path) -> None:
    staging = Path(tempfile.mkdtemp(prefix="acctmgr-pack-"))
    try:
        addons = staging / "addons"
        addons.mkdir()
        report = []
        for expected_id, pattern in MEMBERS:
            matches = sorted(source_dir.glob(pattern))
            if len(matches) != 1:
                raise SystemExit(
                    f"expected exactly one {pattern} in {source_dir}, "
                    f"found {len(matches)}")
            src = matches[0]
            with ZipFile(src) as z:
                tops = {n.split("/")[0] for n in z.namelist() if "/" in n}
                if tops != {expected_id}:
                    raise SystemExit(
                        f"{src.name}: top-level folder(s) {sorted(tops)} "
                        f"!= add-on id {expected_id}; Kodi would ignore it")
                xml = z.read(f"{expected_id}/addon.xml")
                real_id = _addon_id(xml)
                if real_id != expected_id:
                    raise SystemExit(
                        f"{src.name}: addon.xml id {real_id} != folder "
                        f"{expected_id}")
                z.extractall(addons)
            report.append((expected_id, _addon_version(xml), src.name,
                           hashlib.sha256(src.read_bytes()).hexdigest()))

        output.parent.mkdir(parents=True, exist_ok=True)
        paths = []
        skipped = 0
        for dirpath, dirnames, filenames in os.walk(staging):
            pruned = [d for d in dirnames if d in EXCLUDE_DIRS]
            for d in pruned:
                skipped += sum(len(f) for _, _, f in os.walk(
                    Path(dirpath) / d))
            dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
            for name in sorted(filenames):
                if name in EXCLUDE_NAMES or name.endswith(EXCLUDE_SUFFIXES):
                    skipped += 1
                    continue
                paths.append(Path(dirpath) / name)
        with ZipFile(output, "w", ZIP_DEFLATED) as out:
            for p in paths:
                out.write(p, p.relative_to(staging).as_posix())

        for addon_id, version, src_name, digest in report:
            print(f"  {addon_id} {version}  <- {src_name}")
            print(f"      source sha256 {digest}")
        print(f"built {output} ({output.stat().st_size} bytes, "
              f"{len(paths)} files, {skipped} build artefact(s) left out)")
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", required=True, type=Path,
                    help="directory holding the three upstream zips")
    ap.add_argument("--output", type=Path, default=OUTPUT)
    args = ap.parse_args()
    build(args.source_dir, args.output)


if __name__ == "__main__":
    main()
