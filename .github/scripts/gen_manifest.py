#!/usr/bin/env python3
"""Generate ``manifest.json`` describing every addon in the repo.

The manifest is what the wizard (Phase 2) reads to decide, per-addon,
whether an update is available and where to download it. It is rebuilt on
every CI run from the live ``addon.xml`` files, so it always reflects the
source of truth in the repo.

Per addon we record:
  id, name, version, type, filename, zip (download URL), size, sha256, updated

``size`` / ``sha256`` / ``updated`` are taken from the freshly built zip in
``dist/`` when present. For addons that were *not* rebuilt this run, those
values are carried over from the previous ``manifest.json`` (matched by id
**and** version) so the manifest stays complete and accurate.

Environment:
  REPO          owner/repo            (default: MoranTheKing/Kodi-POV-IL)
  RELEASE_TAG   rolling release tag   (default: addons-latest)
  MANIFEST_OUT  output path           (default: <repo>/manifest.json)
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from kodi_addons import REPO_ROOT, discover_addons  # noqa: E402
import build_config  # noqa: E402

REPO = os.environ.get("REPO", "MoranTheKing/Kodi-POV-IL")
RELEASE_TAG = os.environ.get("RELEASE_TAG", "addons-latest")
MANIFEST_OUT = os.environ.get("MANIFEST_OUT", os.path.join(REPO_ROOT, "manifest.json"))
DIST_DIR = os.path.join(REPO_ROOT, "dist")
MANIFEST_VERSION = 1
POV_HOST_MIGRATION = os.path.join(REPO_ROOT, '.github', 'pov-host-migration.json')


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _download_url(filename: str) -> str:
    return f"https://github.com/{REPO}/releases/download/{RELEASE_TAG}/{filename}"


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_previous() -> dict:
    if not os.path.isfile(MANIFEST_OUT):
        return {}
    try:
        with open(MANIFEST_OUT, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("addons", {}) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def _load_previous_config() -> dict:
    if not os.path.isfile(MANIFEST_OUT):
        return {}
    try:
        with open(MANIFEST_OUT, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("config", {}) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def _config_entry(now: str) -> dict:
    """Build the manifest 'config' block describing the build-config zip.

    Mirrors the addon entries: size/sha256/updated come from the freshly
    built dist/config-<version>.zip when present, otherwise they are carried
    over from the previous manifest as long as the version still matches.
    """
    version = build_config.read_config_version()
    filename = build_config.config_zip_name(version)
    dist_zip = os.path.join(DIST_DIR, filename)
    entry = {
        "config_version": version,
        "filename": filename,
        "zip": _download_url(filename),
        "size": None,
        "sha256": None,
        "updated": now,
    }
    if os.path.isfile(dist_zip):
        entry["size"] = os.path.getsize(dist_zip)
        entry["sha256"] = _sha256(dist_zip)
        entry["updated"] = now
    else:
        prev = _load_previous_config()
        if prev and prev.get("config_version") == version:
            entry["size"] = prev.get("size")
            entry["sha256"] = prev.get("sha256")
            entry["updated"] = prev.get("updated", now)
    return entry


def _pov_host_migration() -> dict:
    """Keep the independently verified official POV host pin across CI runs."""
    with open(POV_HOST_MIGRATION, 'r', encoding='utf-8') as source:
        entry = json.load(source)
    expected = ('id', 'version', 'filename', 'zip', 'size', 'sha256')
    if (set(entry) != set(expected) or entry['id'] != 'plugin.video.pov' or
            not re.fullmatch(r'[0-9]+(?:\.[0-9]+)+', str(entry['version'])) or
            entry['filename'] != 'plugin.video.pov-{}.zip'.format(entry['version']) or
            entry['zip'] not in tuple('https://{}.github.io/repo/plugin.video.pov/'.format(host)
                                     + entry['filename'] for host in ('kodifitzwell', 'kodiyashimaru')) or
            not isinstance(entry['size'], int) or not 0 < entry['size'] <= 25 * 1024 * 1024 or
            not re.fullmatch(r'[0-9a-f]{64}', str(entry['sha256']))):
        raise ValueError('invalid pinned official POV migration package')
    return entry


def main() -> int:
    addons = discover_addons()
    previous = _load_previous()
    now = _now_iso()

    entries: dict[str, dict] = {}
    for addon in addons:
        filename = addon.zip_name
        dist_zip = os.path.join(DIST_DIR, filename)
        entry = {
            "id": addon.id,
            "name": addon.name,
            "version": addon.version,
            "type": addon.type,
            "filename": filename,
            "zip": _download_url(filename),
            "size": None,
            "sha256": None,
            "updated": now,
        }

        if os.path.isfile(dist_zip):
            # Built this run -> authoritative values.
            entry["size"] = os.path.getsize(dist_zip)
            entry["sha256"] = _sha256(dist_zip)
            entry["updated"] = now
        else:
            # Not rebuilt -> carry over only if id + version still match.
            prev = previous.get(addon.id)
            if prev and prev.get("version") == addon.version:
                entry["size"] = prev.get("size")
                entry["sha256"] = prev.get("sha256")
                entry["updated"] = prev.get("updated", now)

        entries[addon.id] = entry

    # REFUSE TO OUTPUT NULL. An entry with a null size/sha256 means we have
    # neither a freshly built zip NOR a matching previous entry to carry over --
    # i.e. the addon's addon.xml version was bumped but that version's zip was
    # never published. The manifest's `zip` URL for it would 404 and the wizard
    # install would fail (this is exactly what happened to
    # service.subtitles.kodipovilai 0.2.262). Rather than silently ship a broken
    # manifest, fail loudly with the exact cause and DON'T overwrite the last
    # good manifest.
    broken = {
        aid: e for aid, e in entries.items()
        if e.get("size") is None or e.get("sha256") is None
    }
    if broken:
        print("ERROR: refusing to write manifest.json -- the following addons "
              "have no published zip (null size/sha256):", file=sys.stderr)
        for aid, e in sorted(broken.items()):
            built = os.path.isfile(os.path.join(DIST_DIR, e["filename"]))
            print(
                f"  !! {aid} v{e['version']}: expected '{e['filename']}' "
                f"but it was {'built but unreadable' if built else 'NOT built this run'} "
                f"and no previous manifest entry matched that version. "
                f"-> rebuild this addon (touch/bump its folder so CI repackages it).",
                file=sys.stderr,
            )
        return 1

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "name": "Kodi POV IL Build",
        "repo": REPO,
        "release_tag": RELEASE_TAG,
        "generated": now,
        "manifest_url": (
            f"https://raw.githubusercontent.com/{REPO}/main/manifest.json"
        ),
        "pov_host_migration": _pov_host_migration(),
        "config": _config_entry(now),
        "addons": entries,
    }

    cfg = manifest["config"]
    if not cfg.get("size") or not cfg.get("sha256"):
        print("ERROR: refusing to write manifest.json -- config {0} has no "
              "built ZIP or matching previous verified entry".format(
                  cfg.get("config_version")), file=sys.stderr)
        return 1

    with open(MANIFEST_OUT, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")

    cfg_marker = "built" if os.path.isfile(os.path.join(DIST_DIR, cfg["filename"])) else "carry"
    print(f"Wrote {MANIFEST_OUT} with {len(entries)} addons + config:")
    print(f"  * config{'':<28} {cfg['config_version']:<10} {'config':<11} [{cfg_marker}]")
    for addon_id, entry in sorted(entries.items()):
        marker = "built" if os.path.isfile(os.path.join(DIST_DIR, entry["filename"])) else "carry"
        print(f"  - {addon_id:<35} {entry['version']:<10} {entry['type']:<11} [{marker}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
