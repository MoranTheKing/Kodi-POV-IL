"""Regression test for cross-chunk source-context indexing.

Run: python tools/test_translation_context_index.py
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "addons" / "service.subtitles.kodipovilai" / "resources" / "lib"
sys.path.insert(0, str(LIB))

# translate imports Kodi modules at module load.  Its context helper itself is
# pure, so lightweight stubs keep this regression runnable outside Kodi.
xbmc = types.ModuleType("xbmc")
xbmc.LOGDEBUG = 0
xbmc.LOGINFO = 1
xbmc.LOGWARNING = 2
xbmc.LOGERROR = 3
sys.modules["xbmc"] = xbmc
for name in ("xbmcaddon", "xbmcgui", "xbmcvfs"):
    sys.modules.setdefault(name, types.ModuleType(name))

resources = types.ModuleType("resources")
resources.__path__ = [str(LIB.parent)]
lib_package = types.ModuleType("resources.lib")
lib_package.__path__ = [str(LIB)]
sys.modules["resources"] = resources
sys.modules["resources.lib"] = lib_package

spec = importlib.util.spec_from_file_location(
    "resources.lib.translate", LIB / "translate.py"
)
translate = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["resources.lib.translate"] = translate
spec.loader.exec_module(translate)


def cue(number: int, text: str) -> str:
    return (
        f"{number}\n"
        f"00:00:{number:02d},000 --> 00:00:{number + 1:02d},000\n"
        f"{text}"
    )


chunks = [
    [cue(i, f"first-{i}") for i in range(1, 8)],
    [cue(i, f"second-{i}") for i in range(8, 11)],
    [cue(i, f"third-{i}") for i in range(11, 13)],
]

context = translate._build_prev_context_by_idx(chunks, 5)
assert 1 not in context, context
assert context[2] == ["first-3", "first-4", "first-5", "first-6", "first-7"], context
assert context[3] == ["second-8", "second-9", "second-10"], context
assert translate._build_prev_context_by_idx(chunks, 0) == {}

print("ok - chunk 1 has no context; later 1-based workers receive only the previous source tail")
