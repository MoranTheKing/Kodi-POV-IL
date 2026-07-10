#!/usr/bin/env python3
"""Publish the standalone MoranSubs add-on to the Kodi repo channel.

Run this AFTER building the packages, i.e.:

    POOL_SECRET=<secret> python3 tools/build_ai_subtitles_packages.py
    python3 tools/publish_repo_channel.py

What it does (all deterministic, NO secret needed here -- the pool credential
was already injected by the build step):

  1. Reads the current add-on version from addons/<id>/addon.xml.
  2. Requires dist/<id>-<version>.zip to already exist (the build step makes
     it, WITH the injected pool credential). Refuses to run if it is missing --
     so repo/addons.xml can never advertise a version whose zip isn't there.
  3. Sanity-checks that the zip's internal addon.xml version matches, and that
     its pool.py carries a real injected credential (not the empty placeholder)
     -- guarding against shipping a pool-broken standalone build.
  4. Copies that zip into repo/zips/<id>/.
  5. Replaces the <addon id="<id>"> ... </addon> block in repo/addons.xml with
     the current addon.xml's block (version + any metadata changes).
  6. Regenerates repo/addons.xml.md5 (32 hex chars, no trailing newline --
     matching Kodi's expectation and the existing file's format).

The repository (repository.kodipovilai) points at GitHub Pages, which the
deploy-pages workflow syncs from main -- so after this, just commit repo/ +
dist/ and push to main.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDON_ID = "service.subtitles.kodipovilai"
SRC_ADDON_XML = ROOT / "addons" / ADDON_ID / "addon.xml"
DIST = ROOT / "dist"
REPO = ROOT / "repo"
REPO_ADDONS_XML = REPO / "addons.xml"
REPO_MD5 = REPO / "addons.xml.md5"
REPO_ZIPS = REPO / "zips" / ADDON_ID


def _die(msg: str) -> "None":
    sys.stderr.write("ERROR: " + msg + "\n")
    raise SystemExit(1)


def _addon_block(addon_xml_text: str) -> str:
    """The <addon ...> ... </addon> element (drops the <?xml?> declaration)."""
    m = re.search(r"<addon\b.*</addon>", addon_xml_text, re.S)
    if not m:
        _die("could not find <addon> ... </addon> in addon.xml")
    return m.group(0)


def _version(addon_block: str) -> str:
    m = re.search(r'\bversion="([^"]+)"', addon_block)
    if not m:
        _die("could not read version from addon.xml <addon>")
    return m.group(1)


def main() -> None:
    if not SRC_ADDON_XML.is_file():
        _die("missing " + str(SRC_ADDON_XML))
    src_block = _addon_block(SRC_ADDON_XML.read_text(encoding="utf-8"))
    version = _version(src_block)

    zip_path = DIST / f"{ADDON_ID}-{version}.zip"
    if not zip_path.is_file():
        _die(
            "expected built package not found: {0}\n"
            "  Run the build first (WITH the pool secret):\n"
            "    POOL_SECRET=<secret> python3 tools/build_ai_subtitles_packages.py"
            .format(zip_path.relative_to(ROOT))
        )

    # --- sanity: the zip's own addon.xml version matches, and pool.py has a
    #     real injected credential (not the '__POOL_KEY_BEGIN__ -> return ""'
    #     placeholder that means the pool would be dead for standalone users).
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        ax = f"{ADDON_ID}/addon.xml"
        if ax not in names:
            _die("zip is missing " + ax)
        zip_ver = _version(_addon_block(zf.read(ax).decode("utf-8")))
        if zip_ver != version:
            _die("zip version {0} != addon.xml version {1}".format(
                zip_ver, version))
        pool_name = f"{ADDON_ID}/resources/lib/pool.py"
        if pool_name in names:
            pool_txt = zf.read(pool_name).decode("utf-8", "replace")
            m = re.search(
                r"__POOL_KEY_BEGIN__(.*?)__POOL_KEY_END__", pool_txt, re.S)
            if m and "return ''" in m.group(1) and "b64decode" not in m.group(1):
                _die(
                    "the built zip's pool.py has NO injected credential "
                    "(placeholder only).\n"
                    "  Rebuild with $POOL_SECRET set, or the community pool "
                    "will be dead for standalone users."
                )

    # 4) copy the zip into repo/zips/<id>/
    REPO_ZIPS.mkdir(parents=True, exist_ok=True)
    dst_zip = REPO_ZIPS / zip_path.name
    shutil.copy2(zip_path, dst_zip)

    # 5) replace the <addon id="<id>"> ... </addon> block in repo/addons.xml
    addons_text = REPO_ADDONS_XML.read_text(encoding="utf-8")
    block_re = re.compile(
        r'<addon\b[^>]*\bid="' + re.escape(ADDON_ID) + r'".*?</addon>', re.S)
    if not block_re.search(addons_text):
        _die('no <addon id="{0}"> block in {1}'.format(
            ADDON_ID, REPO_ADDONS_XML.relative_to(ROOT)))
    new_addons_text = block_re.sub(lambda _m: src_block, addons_text, count=1)
    REPO_ADDONS_XML.write_text(new_addons_text, encoding="utf-8")

    # 6) regenerate the md5 (32 hex chars, no trailing newline)
    digest = hashlib.md5(
        REPO_ADDONS_XML.read_bytes()).hexdigest()
    REPO_MD5.write_text(digest, encoding="utf-8")

    print("published standalone {0} to the repo channel:".format(version))
    print("  + {0}".format(dst_zip.relative_to(ROOT)))
    print("  ~ {0}  (addon block -> {1})".format(
        REPO_ADDONS_XML.relative_to(ROOT), version))
    print("  ~ {0}  ({1})".format(REPO_MD5.relative_to(ROOT), digest))
    print("\nNow: git add repo/ dist/ addons/{0}/ && commit && push to main "
          "(GitHub Pages syncs from main).".format(ADDON_ID))


if __name__ == "__main__":
    main()
