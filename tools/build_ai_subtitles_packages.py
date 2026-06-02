#!/usr/bin/env python3
"""Build Kodi POV IL AI subtitles addon packages.

Outputs:
- service.subtitles.kodipovilai-<version>.zip
- service.subtitles.kodipovilai-latest.zip
  Clean standalone addon: AI subtitles + DarkSubs/OpenSubtitles only.

- service.subtitles.kodipovilai-build-<version>.zip
- service.subtitles.kodipovilai-build-latest.zip
  Full build-edition addon, including build/Wizard self-healers.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDON_ID = "service.subtitles.kodipovilai"
SRC = ROOT / "addons" / ADDON_ID
DIST = ROOT / "dist"


STANDALONE_LIB_FILES = {
    "__init__.py",
    "all_subs_samefile_patcher.py",
    "cache.py",
    "dark_subs_integration.py",
    "darksubs_download_sub_patcher.py",
    "darksubs_embedded_demote_patcher.py",
    "darksubs_embedded_insert_patcher.py",
    "darksubs_filename_fallback_patcher.py",
    "darksubs_hook_diagnostics.py",
    "darksubs_opensubtitles_patcher.py",
    "darksubs_patcher.py",
    "darksubs_picker_height_patcher.py",
    "darksubs_picker_label_patcher.py",
    "darksubs_reload.py",
    "darksubs_subwindow_demote_patcher.py",
    "gemini.py",
    "gemini_pair.py",
    "gemini_quota.py",
    "kodi_utils.py",
    "language_detect.py",
    "local_subs.py",
    "prompt.py",
    "skin_dialog_subtitles_patcher.py",
    "skin_dialog_subtitles_row_patcher.py",
    "srt.py",
    "subs_filename_publisher.py",
    "tmdb_helper.py",
    "translate.py",
    "wyzie.py",
}


SLIM_SERVICE = r'''# Clean standalone service for Kodi POV IL AI Subtitles.
#
# This file is intentionally minimal. It does not install or heal the
# Kodi POV IL Wizard, does not rewrite POV menus/favourites/home nodes,
# and does not touch build quick-update state. It only keeps the AI
# subtitle flow and required DarkSubs/OpenSubtitles integration alive.

import os

try:
    import xbmc
except ImportError:
    xbmc = None

ADDON_ID = 'service.subtitles.kodipovilai'
FIRST_RUN_MARKER = '.disable_on_first_run'
_subs_filename_publisher = None
TEMP_PURGE_VERSION = '2'
CACHE_RTL_FIX_VERSION = '4'


def _check_first_run_marker():
    if xbmc is None:
        return False
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        marker = os.path.join(here, FIRST_RUN_MARKER)
        if not os.path.isfile(marker):
            return False
        try:
            os.remove(marker)
        except OSError:
            pass
        try:
            import json as _json
            xbmc.executeJSONRPC(_json.dumps({
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'Addons.SetAddonEnabled',
                'params': {'addonid': ADDON_ID, 'enabled': False},
            }))
        except Exception:
            try:
                xbmc.executebuiltin('DisableAddon(' + ADDON_ID + ')')
            except Exception:
                pass
        return True
    except Exception:
        return False


def _prune_once():
    try:
        from resources.lib import cache, kodi_utils
        removed, freed = cache.prune()
        if removed:
            kodi_utils.log(
                'Cache prune: {0} files removed, {1:.1f} MB freed'.format(
                    removed, freed / (1024.0 * 1024.0)),
                level='INFO')
        else:
            kodi_utils.log('Cache prune: nothing to remove', level='DEBUG')
    except Exception:
        pass


def _maybe_purge_temp_once():
    try:
        from resources.lib import kodi_utils
    except Exception:
        return
    try:
        if kodi_utils.get_setting('_temp_purge_done', '') == TEMP_PURGE_VERSION:
            return
        temp_dir = kodi_utils.translate_path('special://temp/')
        if temp_dir and os.path.isdir(temp_dir):
            for fn in os.listdir(temp_dir):
                if fn.lower().endswith(('.srt', '.sub', '.ass', '.ssa', '.vtt')):
                    try:
                        os.remove(os.path.join(temp_dir, fn))
                    except OSError:
                        pass
        kodi_utils.set_setting('_temp_purge_done', TEMP_PURGE_VERSION)
    except Exception:
        pass


def _maybe_repair_rtl_cache():
    try:
        from resources.lib import kodi_utils, srt
    except Exception:
        return
    try:
        if kodi_utils.get_setting('_rtl_fix_done', '') == CACHE_RTL_FIX_VERSION:
            return
        translated_dir = os.path.join(kodi_utils.cache_dir(), 'translated')
        if os.path.isdir(translated_dir):
            for fn in os.listdir(translated_dir):
                if not fn.endswith('.srt'):
                    continue
                p = os.path.join(translated_dir, fn)
                try:
                    with open(p, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()
                    fixed = srt.fix_rtl_punctuation(content)
                    if fixed != content:
                        tmp = p + '.aitmp'
                        with open(tmp, 'w', encoding='utf-8') as f:
                            f.write(fixed)
                        os.replace(tmp, p)
                except OSError:
                    pass
        kodi_utils.set_setting('_rtl_fix_done', CACHE_RTL_FIX_VERSION)
    except Exception:
        pass


def _maybe_default_fast_first_chunk():
    try:
        from resources.lib import kodi_utils
        if kodi_utils.get_setting('_fast_first_chunk_default_done', '') == '1':
            return
        if kodi_utils.get_setting('fast_first_chunk', '') in ('', 'false'):
            kodi_utils.set_setting('fast_first_chunk', 'true')
        kodi_utils.set_setting('_fast_first_chunk_default_done', '1')
    except Exception:
        pass


def _run(label, func):
    try:
        func()
    except Exception as e:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log('{0} failed: {1}'.format(label, e), level='WARNING')
        except Exception:
            pass


def _maybe_patch_darksubs():
    from resources.lib import dark_subs_integration
    dark_subs_integration.maybe_patch_darksubs()


def _maybe_patch_darksubs_download_sub():
    from resources.lib import darksubs_download_sub_patcher
    darksubs_download_sub_patcher.ensure_patched()


def _maybe_patch_darksubs_opensubtitles():
    from resources.lib import darksubs_opensubtitles_patcher
    darksubs_opensubtitles_patcher.ensure_patched()


def _maybe_patch_darksubs_embedded_demote():
    from resources.lib import darksubs_embedded_demote_patcher
    status = darksubs_embedded_demote_patcher.ensure_patched()
    if status == 'patched':
        from resources.lib import darksubs_reload
        darksubs_reload.note_patched()


def _maybe_patch_darksubs_embedded_insert():
    from resources.lib import darksubs_embedded_insert_patcher
    status = darksubs_embedded_insert_patcher.ensure_patched()
    if status == 'patched':
        from resources.lib import darksubs_reload
        darksubs_reload.note_patched()


def _maybe_patch_darksubs_subwindow_demote():
    from resources.lib import darksubs_subwindow_demote_patcher
    status = darksubs_subwindow_demote_patcher.ensure_patched()
    if status == 'patched':
        from resources.lib import darksubs_reload
        darksubs_reload.note_patched()


def _maybe_surface_darksubs_status():
    from resources.lib import darksubs_hook_diagnostics
    darksubs_hook_diagnostics.surface_status_if_problem()


def _maybe_patch_darksubs_filename():
    from resources.lib import darksubs_filename_fallback_patcher
    darksubs_filename_fallback_patcher.ensure_patched()


def _maybe_patch_skin_dialog_subtitles():
    from resources.lib import skin_dialog_subtitles_patcher
    skin_dialog_subtitles_patcher.ensure_patched()


def _maybe_patch_skin_dialog_subtitles_rows():
    from resources.lib import skin_dialog_subtitles_row_patcher
    skin_dialog_subtitles_row_patcher.ensure_patched()


def _maybe_patch_darksubs_picker_label():
    from resources.lib import darksubs_picker_label_patcher
    darksubs_picker_label_patcher.ensure_patched()


def _maybe_patch_darksubs_picker_height():
    from resources.lib import darksubs_picker_height_patcher
    darksubs_picker_height_patcher.ensure_patched()


def _maybe_patch_all_subs_samefile():
    from resources.lib import all_subs_samefile_patcher
    all_subs_samefile_patcher.ensure_patched()


def main():
    if xbmc is None:
        return
    if _check_first_run_marker():
        return

    _prune_once()
    _maybe_purge_temp_once()

    _run('darksubs integration', _maybe_patch_darksubs)
    _run('darksubs download_sub patch', _maybe_patch_darksubs_download_sub)
    _run('darksubs OpenSubtitles patch', _maybe_patch_darksubs_opensubtitles)
    _run('darksubs embedded demote patch', _maybe_patch_darksubs_embedded_demote)
    _run('darksubs embedded insert patch', _maybe_patch_darksubs_embedded_insert)
    _run('darksubs subwindow demote patch', _maybe_patch_darksubs_subwindow_demote)
    _run('darksubs status diagnostics', _maybe_surface_darksubs_status)
    _run('darksubs filename fallback patch', _maybe_patch_darksubs_filename)
    _run('subtitle dialog filename patch', _maybe_patch_skin_dialog_subtitles)
    _run('subtitle dialog row patch', _maybe_patch_skin_dialog_subtitles_rows)
    _run('darksubs picker label patch', _maybe_patch_darksubs_picker_label)
    _run('darksubs picker height patch', _maybe_patch_darksubs_picker_height)
    _run('allsubs samefile patch', _maybe_patch_all_subs_samefile)

    try:
        from resources.lib import darksubs_reload
        darksubs_reload.reload_if_patched()
    except Exception:
        pass

    _maybe_repair_rtl_cache()
    _maybe_default_fast_first_chunk()

    global _subs_filename_publisher
    try:
        from resources.lib import subs_filename_publisher
        _subs_filename_publisher = subs_filename_publisher.SubsFilenamePublisher()
    except Exception:
        pass

    monitor = xbmc.Monitor()
    while not monitor.abortRequested():
        if monitor.waitForAbort(24 * 3600):
            break
        _prune_once()


main()
'''


def version() -> str:
    text = (SRC / "addon.xml").read_text(encoding="utf-8")
    match = re.search(
        r'<addon\b[^>]*\bid="' + re.escape(ADDON_ID) +
        r'"[^>]*\bversion="([^"]+)"',
        text,
        re.S,
    )
    if not match:
        raise RuntimeError("addon.xml version not found")
    return match.group(1)


def should_skip_common(path: Path) -> bool:
    parts = set(path.parts)
    name = path.name
    return (
        "__pycache__" in parts
        or name.endswith((".pyc", ".pyo"))
        or name == ".DS_Store"
    )


def copy_common(dst: Path, standalone: bool) -> None:
    for path in SRC.rglob("*"):
        if path.is_dir() or should_skip_common(path):
            continue
        rel = path.relative_to(SRC)
        if standalone and not include_standalone(rel):
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    if standalone:
        (dst / "service.py").write_text(SLIM_SERVICE, encoding="utf-8")


def include_standalone(rel: Path) -> bool:
    parts = rel.parts
    if parts[0] in {
        "addon.xml",
        "changelog.txt",
        "default.py",
        "icon.png",
        "LICENSE.txt",
        "service.py",
    }:
        return True
    if parts[:1] != ("resources",):
        return False
    if rel == Path("resources/settings.xml"):
        return True
    if len(parts) >= 2 and parts[1] == "language":
        return True
    if len(parts) >= 2 and parts[1] == "patches":
        return parts[2:3] == ("darksubs",)
    if len(parts) >= 3 and parts[1] == "lib":
        if parts[2] == "icons":
            return True
        if len(parts) == 3 and parts[2] in STANDALONE_LIB_FILES:
            return True
    return False


def make_zip(src_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src_dir.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(src_dir.parent).as_posix()
            zf.write(path, rel)


def build_one(name: str, standalone: bool) -> Path:
    ver = version()
    out = DIST / f"{name}-{ver}.zip"
    with tempfile.TemporaryDirectory(prefix=f"{name}-") as tmp:
        tmp_path = Path(tmp)
        addon_dst = tmp_path / ADDON_ID
        copy_common(addon_dst, standalone=standalone)
        make_zip(addon_dst, out)
    return out


def assert_no_standalone_build_payload(zip_path: Path) -> None:
    forbidden = (
        "staged_wizard.zip",
        "wizard_self_healer.py",
        "wizard_patcher.py",
        "af3_",
        "brand_",
        "favourites_",
        "pov_",
        "media_assets/",
        "resources/fixtures/",
    )
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    bad = [n for n in names if any(token in n for token in forbidden)]
    if bad:
        raise RuntimeError(
            "standalone zip contains build payload:\n" + "\n".join(bad[:50])
        )


def main() -> None:
    DIST.mkdir(exist_ok=True)
    standalone = build_one("service.subtitles.kodipovilai", standalone=True)
    build = build_one("service.subtitles.kodipovilai-build", standalone=False)
    assert_no_standalone_build_payload(standalone)

    shutil.copy2(standalone, DIST / "service.subtitles.kodipovilai-latest.zip")
    shutil.copy2(build, DIST / "service.subtitles.kodipovilai-build-latest.zip")

    for path in (
        standalone,
        DIST / "service.subtitles.kodipovilai-latest.zip",
        build,
        DIST / "service.subtitles.kodipovilai-build-latest.zip",
    ):
        print(f"{path.relative_to(ROOT)} {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
