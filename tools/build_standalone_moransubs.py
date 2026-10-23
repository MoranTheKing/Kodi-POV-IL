#!/usr/bin/env python3
"""Build the repo-channel ("standalone") MoranSubs from the build's own tree.

    python tools/build_standalone_moransubs.py --pool-from <a shipped MoranSubs zip>

Why (23 Oct 2026): the standalone was built by build_ai_subtitles_packages.py
from the legacy addons/ tree, which stopped at 0.2.568 on 16 Oct. Everything
since -- the gender work, the quota fallback, the subtitle sources -- went
into service.subtitles.kodipovilai/ (0.3.x, delivered by the Wizard), so
people who installed MoranSubs alone from the site stayed a week and a whole
minor version behind.

This packages the SAME tree the build ships, minus what only the build uses:
  * service.py is the build's own: every step that touches POV, Umbrella, a
    skin's buttons and settings or the build's state already runs only when
    the build is detected (service._is_kodi_pov_il_build).
  * resources/lib: the subtitle modules only (the legacy list plus the 0.3
    additions the translation needs); no pov_/af3_/umbrella_/mdblist_/nox_
    patchers, no subtitle chooser, no Wizard healers.
  * default.py: the build-only actions are cut out by syntax tree.
  * changelog.txt: build-only bullets dropped (legacy rules).
  * pool.py: inherited byte for byte from a shipped zip with the same pool.py
    logic (the legacy rule; refuses otherwise).
The legacy safety checks run on the result (no build payload, no build
actions in default.py, no host names in the changelog), and every .py must
compile. Outputs dist/service.subtitles.kodipovilai-<version>.zip and
-latest.zip; publish them with tools/publish_repo_channel.py --modular.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import py_compile
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON_ID = "service.subtitles.kodipovilai"
SRC = ROOT / ADDON_ID
DIST = ROOT / "dist"


def _legacy():
    spec = importlib.util.spec_from_file_location(
        "build_ai_subtitles_packages", ROOT / "tools" / "build_ai_subtitles_packages.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


legacy = _legacy()

# The legacy standalone list, minus files the 0.3 tree no longer has, plus the
# modules translate.py / arabic_gender.py import in 0.3 (import closure of the
# legacy list, Oct 2026). he_sub_match stays out on purpose, as before: every
# import of it is guarded and it only feeds the build's POV badge.
STANDALONE_LIB_FILES = (
    {name for name in legacy.STANDALONE_LIB_FILES if (SRC / "resources" / "lib" / name).is_file()}
    | {"gender_guard.py", "he_person_gender.py", "script_residual.py",
       "sdh_pool.py", "sdh_registry.py", "srt_wire.py"}
)

# default.py actions only the build has, and the helpers only they use.
BUILD_ACTIONS = ("prepare_build_skin", "tonight", "open_pov_settings",
                 "debrid_notice_settings", "torbox_status")
BUILD_HANDLERS = ("_handle_prepare_build_skin", "_handle_open_pov_settings",
                  "_handle_debrid_notice_settings", "_handle_torbox_status",
                  "_pov_addon", "_format_bytes", "_torbox_api_get",
                  "_torbox_usage_30", "_notice_value_label")

# Changelog bullets naming the build's subtitle chooser button (subs_chooser
# is not shipped) stay out of the standalone changelog.
MODULAR_SKIP_TERMS = ("בחירת כתוביות",)


def include(rel: Path) -> bool:
    parts = rel.parts
    if len(parts) == 3 and parts[:2] == ("resources", "lib"):
        return parts[2] in STANDALONE_LIB_FILES
    if len(parts) >= 3 and parts[:2] == ("resources", "lib") and parts[2] not in ("subs_engine", "icons"):
        return False
    saved = legacy.STANDALONE_LIB_FILES
    try:
        legacy.STANDALONE_LIB_FILES = STANDALONE_LIB_FILES
        return legacy.include_standalone(rel)
    finally:
        legacy.STANDALONE_LIB_FILES = saved


def slim_default(text: str) -> str:
    """default.py without the build-only actions and their helpers."""
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    cut = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in BUILD_HANDLERS:
            start = node.lineno - 1 - len(node.decorator_list)
            cut.append((start, node.end_lineno))
    main = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"]
    if len(main) != 1:
        raise RuntimeError("default.py: no single main()")
    found = set()
    for node in ast.walk(main[0]):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
                and test.left.id == "action" and len(test.comparators) == 1
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value in BUILD_ACTIONS):
            found.add(test.comparators[0].value)
            # `if a: X elif b: Y` -- drop this test and its body; the next
            # branch (node.orelse[0]) moves up. The chain's first `if` keeps
            # its keyword, so cut from the `if`/`elif` line to the line before
            # the next branch and rename that branch when it was the first.
            first_line = node.lineno - 1
            nxt = node.orelse[0] if node.orelse else None
            end = (nxt.lineno - 1) if nxt is not None else node.end_lineno
            cut.append((first_line, end))
            if nxt is not None and lines[first_line].lstrip().startswith("if "):
                lines[nxt.lineno - 1] = lines[nxt.lineno - 1].replace("elif ", "if ", 1)
    missing = set(BUILD_ACTIONS) - found
    if missing:
        raise RuntimeError("default.py: build actions not found: %s" % sorted(missing))
    for start, end in sorted(cut, reverse=True):
        del lines[start:end]
    out = "".join(lines)
    for old, new in (
            ("anywhere, e.g. a Wizard button or a remote shortcut.",
             "anywhere, e.g. a remote shortcut."),
            ("'באופן כללי), פתח את ה-Wizard → \"חיבור שירותים\" → TMDB '\n"
             "        'וחבר key אישי. הוא יוחל אוטומטית מאותו רגע, בלי '\n",
             "'באופן כללי), פתח את הגדרות TMDB Helper וחבר key אישי. '\n"
             "        'הוא יוחל אוטומטית מאותו רגע, בלי '\n")):
        if out.count(old.replace("\n", _eol(text))) != 1:
            raise RuntimeError("default.py: text to replace not found: %r" % old[:40])
        out = out.replace(old.replace("\n", _eol(text)), new.replace("\n", _eol(text)))
    tree = ast.parse(out)
    defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    used = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id.startswith("_handle_")}
    if used - defined:
        raise RuntimeError("default.py: handlers called but not defined: %s" % sorted(used - defined))
    return out


def _eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _repository_eol(rel: Path) -> bytes:
    try:
        blob = subprocess.check_output(["git", "show", "HEAD:" + (Path(ADDON_ID) / rel).as_posix()],
                                       cwd=ROOT, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return b"\n"
    return b"\r\n" if b"\r\n" in blob else b"\n"


def normalize(addon_dst: Path) -> None:
    """The legacy normalize_staged_text, against this tree's blobs."""
    for path in addon_dst.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in legacy._TEXT_SUFFIXES:
            continue
        raw = path.read_bytes()
        if b"\0" in raw:
            continue
        canonical = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        if _repository_eol(path.relative_to(addon_dst)) == b"\r\n":
            canonical = canonical.replace(b"\n", b"\r\n")
        if canonical != raw:
            path.write_bytes(canonical)


def version() -> str:
    m = re.search(r'<addon\b[^>]*\bversion="([^"]+)"', (SRC / "addon.xml").read_text(encoding="utf-8"), re.S)
    if not m:
        raise RuntimeError("addon.xml version not found")
    return m.group(1)


def stage(addon_dst: Path) -> None:
    for path in SRC.rglob("*"):
        if path.is_dir() or legacy.should_skip_common(path):
            continue
        rel = path.relative_to(SRC)
        if not include(rel):
            continue
        target = addon_dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    (addon_dst / "default.py").write_text(
        slim_default((SRC / "default.py").read_text(encoding="utf-8")), encoding="utf-8")
    # slim_changelog_text heads a release with no standalone bullet with the
    # version it reads from the legacy tree; this package is this tree's.
    # MODULAR_SKIP_TERMS: this tree's own build-only features, which the
    # legacy list predates.
    saved = legacy.SRC, legacy.STANDALONE_SKIP_TERMS
    try:
        legacy.SRC = SRC
        legacy.STANDALONE_SKIP_TERMS = saved[1] + MODULAR_SKIP_TERMS
        changelog = legacy.slim_changelog_text((SRC / "changelog.txt").read_text(encoding="utf-8"))
    finally:
        legacy.SRC, legacy.STANDALONE_SKIP_TERMS = saved
    (addon_dst / "changelog.txt").write_text(changelog, encoding="utf-8")


def compile_all(addon_dst: Path) -> None:
    failures = []
    for path in sorted(addon_dst.rglob("*.py")):
        try:
            py_compile.compile(str(path), doraise=True, cfile=str(path) + "c.tmp")
        except py_compile.PyCompileError as exc:
            failures.append("{0}: {1}".format(path.relative_to(addon_dst), str(exc).splitlines()[-1]))
        finally:
            tmp = Path(str(path) + "c.tmp")
            if tmp.exists():
                tmp.unlink()
    if failures:
        raise SystemExit("standalone build aborted -- Python compile errors:\n  " + "\n  ".join(failures))


def build(pool_from: Path) -> Path:
    DIST.mkdir(exist_ok=True)
    ver = version()
    out = DIST / f"{ADDON_ID}-{ver}.zip"
    with tempfile.TemporaryDirectory(prefix=f"{ADDON_ID}-standalone-") as tmp:
        addon_dst = Path(tmp) / ADDON_ID
        stage(addon_dst)
        normalize(addon_dst)
        if not legacy.inherit_pool_credential(addon_dst, pool_from):
            raise SystemExit("no usable --pool-from zip: %s" % pool_from)
        compile_all(addon_dst)
        # Zip and check outside dist/, so a rejected package never replaces
        # (or sits next to) the last good one.
        staged = Path(tmp) / out.name
        legacy.make_zip(addon_dst, staged)
        legacy.assert_no_standalone_build_payload(staged)
        shutil.copy2(staged, out)
    shutil.copy2(out, DIST / f"{ADDON_ID}-latest.zip")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pool-from", type=Path, required=True,
                        help="a shipped MoranSubs zip with the same pool.py logic")
    args = parser.parse_args()
    out = build(args.pool_from)
    print(f"{out.relative_to(ROOT)} {out.stat().st_size} bytes (+ {ADDON_ID}-latest.zip)")


if __name__ == "__main__":
    main()
