#!/usr/bin/env python3
"""Package addon folders into valid, deterministic Kodi zips.

Usage::

    python .github/scripts/build_addons.py --all
    python .github/scripts/build_addons.py plugin.video.pov skin.povil.nox

A valid Kodi addon zip contains a single top-level folder named exactly
after the addon id, with ``addon.xml`` inside it (``plugin.video.pov/addon.xml``).
Because the repo folder name already equals the addon id, we simply zip the
folder under its own name.

Zips are written to ``dist/<id>-<version>.zip`` and are **deterministic**:
file order is sorted and timestamps are fixed, so re-zipping unchanged
content yields a byte-identical archive (and therefore an identical
sha256). That lets the wizard detect a real content change even when the
version string did not move.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(__file__))
from kodi_addons import (  # noqa: E402
    EXCLUDE_DIR_NAMES,
    EXCLUDE_FILE_NAMES,
    EXCLUDE_SUFFIXES,
    REPO_ROOT,
    Addon,
    discover_addons,
)

DIST_DIR = os.path.join(REPO_ROOT, "dist")
# Fixed timestamp for reproducible archives (Y, M, D, h, m, s).
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)
_POOL_MEMBER = 'service.subtitles.kodipovilai/resources/lib/pool.py'
_POOL_BLOCK = re.compile(rb'__POOL_KEY_BEGIN__.*?__POOL_KEY_END__', re.S)


def _with_carried_pool_key(payload: bytes) -> bytes:
    """Keep the new module logic and copy only the last shipped key block."""
    source = os.environ.get('POVIL_POOL_CARRY_FILE', '').strip()
    if not source or not os.path.isfile(source):
        raise ValueError('MoranSubs release needs a verified prior pool credential')
    with open(source, 'rb') as handle:
        previous = handle.read()
    old_blocks = _POOL_BLOCK.findall(previous)
    new_blocks = _POOL_BLOCK.findall(payload)
    if len(old_blocks) != 1 or len(new_blocks) != 1:
        raise ValueError('pool credential markers missing or ambiguous')
    if b'b64decode' not in old_blocks[0] or b'b64decode' in new_blocks[0]:
        raise ValueError('pool credential source is not a shipped key block')
    result = _POOL_BLOCK.sub(lambda _match: old_blocks[0], payload, count=1)
    if _POOL_BLOCK.sub(b'', result) != _POOL_BLOCK.sub(b'', payload):
        raise ValueError('pool logic changed during credential carry')
    return result


def _is_excluded(rel_parts: list[str], filename: str) -> bool:
    if any(part in EXCLUDE_DIR_NAMES for part in rel_parts):
        return True
    if filename in EXCLUDE_FILE_NAMES:
        return True
    if filename.endswith(EXCLUDE_SUFFIXES):
        return True
    return False


def _collect_files(addon: Addon) -> list[tuple[str, str]]:
    """Return (absolute_path, arcname) pairs, sorted by arcname."""
    items: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(addon.path):
        # Prune excluded directories in-place so os.walk skips them.
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIR_NAMES)
        rel_dir = os.path.relpath(dirpath, addon.path)
        rel_parts = [] if rel_dir == "." else rel_dir.split(os.sep)
        for filename in sorted(filenames):
            if _is_excluded(rel_parts, filename):
                continue
            abs_path = os.path.join(dirpath, filename)
            # arcname is rooted at the addon id folder: "<id>/<rel>".
            arc = os.path.join(addon.dirname, *rel_parts, filename)
            items.append((abs_path, arc.replace(os.sep, "/")))
    return sorted(items, key=lambda pair: pair[1])


def build_zip(addon: Addon) -> str:
    os.makedirs(DIST_DIR, exist_ok=True)
    out_path = os.path.join(DIST_DIR, addon.zip_name)
    if os.path.exists(out_path):
        os.remove(out_path)
    files = _collect_files(addon)
    # Keep CI packages within the staged installer's explicit Kodi limits.
    # A larger future skin must fail before the manifest points users at it.
    if len(files) > 2000 or sum(os.path.getsize(path) for path, _arc in files) > 30 * 1024 * 1024:
        raise ValueError(f'{addon.id} exceeds staged installer file/size limit')
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for abs_path, arc in files:
            info = zipfile.ZipInfo(arc, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            # 0o644 file permissions, regular file.
            info.external_attr = (0o644 & 0xFFFF) << 16
            with open(abs_path, "rb") as fh:
                payload = fh.read()
            if arc == _POOL_MEMBER:
                payload = _with_carried_pool_key(payload)
            zf.writestr(info, payload)
    size = os.path.getsize(out_path)
    if size > 25 * 1024 * 1024:
        raise ValueError(f'{addon.id} ZIP exceeds staged installer compressed size limit')
    print(f"  + {addon.zip_name}  ({len(files)} files, {size:,} bytes)")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Package Kodi addon zips.")
    parser.add_argument("ids", nargs="*", help="addon ids to build")
    parser.add_argument("--all", action="store_true", help="build every addon")
    args = parser.parse_args()

    all_addons = {a.id: a for a in discover_addons()}
    if args.all or not args.ids:
        targets = list(all_addons.values())
    else:
        targets = []
        for addon_id in args.ids:
            if addon_id not in all_addons:
                print(f"  !! unknown addon id '{addon_id}' -- skipping")
                continue
            targets.append(all_addons[addon_id])

    if not targets:
        print("Nothing to build.")
        return 0

    print(f"Building {len(targets)} addon zip(s) into {DIST_DIR}:")
    for addon in sorted(targets, key=lambda a: a.id):
        build_zip(addon)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
