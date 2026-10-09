#!/usr/bin/env python3
"""Print the addon ids that changed between two git commits.

Usage::

    python .github/scripts/list_changed.py all
    python .github/scripts/list_changed.py diff <before_sha> <after_sha>

In ``all`` mode (manual / seed runs) every addon id is printed.
In ``diff`` mode the script runs ``git diff --name-only`` and keeps the
top-level path components that correspond to a real addon folder. If the
``before`` sha is missing/unknown (first push, force-push, shallow clone),
it falls back to building everything so we never publish a stale release.

Output: one addon id per line, sorted, to stdout.
"""

from __future__ import annotations

import os
import json
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from kodi_addons import REPO_ROOT, discover_addons  # noqa: E402

_ZERO_SHA = "0000000000000000000000000000000000000000"


def _git_changed_paths(before: str, after: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{before}", f"{after}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return [line for line in result.stdout.splitlines() if line.strip()]


def unpublished_addons(addons, manifest_path=None):
    """Recover source versions left unpublished by a previous partial run."""
    try:
        with open(manifest_path or os.path.join(REPO_ROOT, 'manifest.json'), encoding='utf-8') as source:
            entries = json.load(source)['addons']
        if not isinstance(entries, dict):
            raise ValueError('Malformed addon manifest')
    except (OSError, ValueError, KeyError, TypeError):
        return {addon.id for addon in addons}
    pending = set()
    for addon in addons:
        previous = entries.get(addon.id)
        if (not isinstance(previous, dict) or previous.get('version') != addon.version
                or not previous.get('size') or not previous.get('sha256')):
            pending.add(addon.id)
    return pending


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    addons = discover_addons()
    known = {addon.id for addon in addons}

    if mode != "diff":
        for addon_id in sorted(known):
            print(addon_id)
        return 0

    before = sys.argv[2] if len(sys.argv) > 2 else ""
    after = sys.argv[3] if len(sys.argv) > 3 else "HEAD"

    if not before or before == _ZERO_SHA:
        # No usable baseline -> rebuild everything.
        for addon_id in sorted(known):
            print(addon_id)
        return 0

    try:
        paths = _git_changed_paths(before, after)
    except RuntimeError as exc:
        sys.stderr.write(f"git diff failed ({exc}); rebuilding all addons\n")
        for addon_id in sorted(known):
            print(addon_id)
        return 0

    changed: set[str] = unpublished_addons(addons)
    for path in paths:
        top = path.split("/", 1)[0]
        if top in known:
            changed.add(top)

    for addon_id in sorted(changed):
        print(addon_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
