#!/usr/bin/env python3
"""Reject a MoranSubs tree/zip that refers to local modules it does not ship.

The modular-build candidate removed five Python files that its service and
picker still import.  Most callers swallow ImportError, so a package can look
healthy while features silently disappear.  Run this on the source tree and
again on the exact ZIP intended for release.

    python tools/test_local_addon_imports.py
    python tools/test_local_addon_imports.py --addon-root PATH
    python tools/test_local_addon_imports.py --zip PATH
"""

from __future__ import annotations

import argparse
import ast
import sys
import warnings
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADDON = ROOT / "addons" / "service.subtitles.kodipovilai"


def _source_tree(addon_root: Path) -> dict[str, str]:
    return {
        path.relative_to(addon_root).as_posix(): path.read_text(
            encoding="utf-8-sig", errors="replace"
        )
        for path in addon_root.rglob("*.py")
    }


def _zip_tree(archive: Path) -> dict[str, str]:
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        roots = [
            name[: -len("addon.xml")]
            for name in names
            if name.endswith("addon.xml")
            and name.count("/") <= 1
        ]
        if len(roots) != 1:
            raise ValueError("expected exactly one top-level addon.xml")
        prefix = roots[0]
        return {
            name[len(prefix) :]: bundle.read(name).decode("utf-8-sig", "replace")
            for name in names
            if name.startswith(prefix) and name.endswith(".py")
        }


def _exports(source: str) -> set[str]:
    """Names supplied by resources.lib itself, as opposed to submodules."""
    if not source:
        return set()
    tree = ast.parse(source)
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
    return names


def missing_imports(sources: dict[str, str]) -> list[str]:
    prefix = "resources/lib/"
    modules = {
        path[len(prefix) : -3]
        for path in sources
        if path.startswith(prefix) and path.endswith(".py")
        and "/" not in path[len(prefix) :]
    }
    packages = {
        path[len(prefix) : -len("/__init__.py")]
        for path in sources
        if path.startswith(prefix) and path.endswith("/__init__.py")
        and "/" not in path[len(prefix) : -len("/__init__.py")]
    }
    available = modules | packages | _exports(sources.get(prefix + "__init__.py", ""))
    failures = []
    for path, source in sorted(sources.items()):
        try:
            with warnings.catch_warnings():
                # Vendored Python regex literals raise SyntaxWarning on the
                # host's Python 3.12; they are unrelated to module closure.
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(source, filename=path)
        except SyntaxError as exc:
            failures.append(f"{path}:{exc.lineno}: Python syntax error: {exc.msg}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "resources.lib":
                for alias in node.names:
                    if alias.name != "*" and alias.name not in available:
                        failures.append(f"{path}:{node.lineno}: resources.lib.{alias.name}")
            elif (isinstance(node, ast.ImportFrom) and node.level == 1
                  and path.startswith(prefix)
                  and "/" not in path[len(prefix):]):
                # A top-level lib module can import a peer as ``from . import x``
                # or ``from .x import y``.  These are just as easy to strand
                # during a cleanup as absolute imports.
                candidates = ([alias.name for alias in node.names]
                              if not node.module else [node.module.split(".")[0]])
                for name in candidates:
                    if name != "*" and name not in available:
                        failures.append(f"{path}:{node.lineno}: resources.lib.{name}")
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("resources.lib."):
                name = node.module[len("resources.lib.") :].split(".")[0]
                if name not in available:
                    failures.append(f"{path}:{node.lineno}: resources.lib.{name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("resources.lib."):
                        name = alias.name[len("resources.lib.") :].split(".")[0]
                        if name not in available:
                            failures.append(f"{path}:{node.lineno}: resources.lib.{name}")
    return sorted(set(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--addon-root", type=Path, default=DEFAULT_ADDON)
    group.add_argument("--zip", dest="archive", type=Path)
    args = parser.parse_args()

    # A real missing runtime import must fail this gate.  This proof guards
    # against accidentally turning the check into an always-green file count.
    fixture = {
        "default.py": "from resources.lib import present, removed\n",
        "resources/lib/__init__.py": "",
        "resources/lib/present.py": "VALUE = True\n",
    }
    assert missing_imports(fixture) == ["default.py:1: resources.lib.removed"]
    fixture["resources/lib/consumer.py"] = "from . import removed\n"
    assert missing_imports(fixture) == [
        "default.py:1: resources.lib.removed",
        "resources/lib/consumer.py:1: resources.lib.removed",
    ]

    try:
        sources = _zip_tree(args.archive) if args.archive else _source_tree(args.addon_root)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"FAIL: cannot inspect addon: {exc}")
        return 1
    failures = missing_imports(sources)
    if failures:
        print(f"FAIL: {len(failures)} missing local import(s) in {len(sources)} Python files")
        for failure in failures:
            print("  " + failure)
        return 1
    print(f"ok: {len(sources)} Python files; all resources.lib imports resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
