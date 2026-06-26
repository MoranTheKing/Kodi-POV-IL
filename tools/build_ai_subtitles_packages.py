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
    "arabic_gender.py",
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
    "google_translate.py",
    "kodi_utils.py",
    "language_detect.py",
    "local_subs.py",
    "pool.py",
    "prompt.py",
    "source_capture.py",
    "source_memory.py",
    "skin_dialog_subtitles_patcher.py",
    "skin_dialog_subtitles_row_patcher.py",
    "srt.py",
    "telemetry.py",
    "subs_engine_bridge.py",
    "subs_filename_publisher.py",
    "tmdb_helper.py",
    "translate.py",
}


SLIM_SERVICE = r'''# Clean standalone service for Kodi POV IL AI Subtitles.
#
# This file is intentionally minimal. It does not install or heal the
# Kodi POV IL build tools, does not rewrite POV menus/favourites/home nodes,
# and does not touch unrelated update state. It only keeps the AI
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


def _maybe_force_gender_ref_arabic():
    """One-shot: turn the Arabic gender reference ON for everyone (forced once,
    even if previously off; a later manual opt-out sticks). Marker-gated."""
    try:
        from resources.lib import kodi_utils
        if kodi_utils.get_setting('_gender_ref_on_v1', '') == '1':
            return
        kodi_utils.set_setting('gender_ref_arabic', 'true')
        kodi_utils.set_setting('_gender_ref_on_v1', '1')
    except Exception:
        pass


def _maybe_tune_gemini3_defaults():
    """One-shot: move existing users to the validated Gemini 3 settings --
    temperature 1.0 + thinking_level medium. Only flips values still on the old
    defaults (0.2 / disabled); a deliberate choice sticks. Marker-gated."""
    try:
        from resources.lib import kodi_utils
        if kodi_utils.get_setting('_gemini3_tune_v1', '') == '1':
            return
        try:
            t = float(kodi_utils.get_setting('temperature', '') or '0.2')
        except (TypeError, ValueError):
            t = 0.2
        if abs(t - 0.2) < 0.005:
            kodi_utils.set_setting('temperature', '1.0')
        th = (kodi_utils.get_setting('thinking_budget', '') or '0').strip().lower()
        if th in ('', '0', 'disabled'):
            kodi_utils.set_setting('thinking_budget', 'medium')
        kodi_utils.set_setting('_gemini3_tune_v1', '1')
    except Exception:
        pass


def _maybe_lower_chunk_lines():
    """One-shot: lower the translation chunk to 50 lines (block-avoidance).
    Big chunks of explicit dialogue trip Google's prompt-level block; 50-line
    chunks stay under the threshold with no loss of gender/quality. Only lowers
    old defaults (>=100 -> 50); a smaller manual choice sticks. Marker-gated."""
    try:
        from resources.lib import kodi_utils
        if kodi_utils.get_setting('_chunk_lines_50_v1', '') == '1':
            return
        try:
            cur = int(kodi_utils.get_setting('chunk_lines', '') or '100')
        except (TypeError, ValueError):
            cur = 100
        if cur >= 100:
            kodi_utils.set_setting('chunk_lines', '50')
        kodi_utils.set_setting('_chunk_lines_50_v1', '1')
    except Exception:
        pass


def _start_pool_queue_drainer(monitor):
    """Drive both pool queues from the long-lived service: gently pull queued
    Ktuvit subs from Ktuvit (process_harvest_queue) and upload queued
    contributions to Telegram (drain), throttled + retrying, surviving playback
    ending / a Kodi restart. Best-effort; never blocks."""
    try:
        import threading
        from resources.lib import pool
    except Exception:
        return

    def _loop():
        try:
            if monitor.waitForAbort(20):
                return
            while not monitor.abortRequested():
                try:
                    from resources.lib import translate
                    translate.process_harvest_queue(
                        should_cancel=monitor.abortRequested)
                except Exception:
                    pass
                left = 0
                try:
                    _sent, left = pool.drain(
                        should_cancel=monitor.abortRequested)
                except Exception:
                    left = 0
                try:
                    backlog = bool(left) or pool.harvest_queue_len() > 0
                except Exception:
                    backlog = bool(left)
                if monitor.waitForAbort(20 if backlog else 60):
                    break
        except Exception:
            pass

    try:
        threading.Thread(target=_loop, daemon=True).start()
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


def _maybe_default_builtin_engine():
    """One-shot: turn the built-in sources engine ON for existing standalone
    users too (marker-gated). New installs get it from the settings.xml default.
    A later manual opt-out STICKS -- we never force it back on."""
    try:
        from resources.lib import kodi_utils
    except Exception:
        return
    try:
        if kodi_utils.get_setting('_builtin_engine_rollout_v1', '') == '1':
            return
        if kodi_utils.get_setting('use_builtin_engine', 'false') != 'true':
            kodi_utils.set_setting('use_builtin_engine', 'true')
        if kodi_utils.get_setting('engine_autosub', 'true') == 'false':
            kodi_utils.set_setting('engine_autosub', 'true')
        kodi_utils.set_setting('_builtin_engine_rollout_v1', '1')
        kodi_utils.log('built-in engine enabled (standalone rollout v1)',
                       level='INFO')
    except Exception:
        pass


def _engine_on():
    try:
        from resources.lib import kodi_utils
        return kodi_utils.get_bool('use_builtin_engine', False)
    except Exception:
        return False


def _ensure_darksubs_enabled():
    """When the engine is ON, disable DarkSubs + All Subs Plus so only MoranSubs
    runs (reversible: turn the engine off and they come back). When OFF, ensure
    DarkSubs is enabled (the translation hook depends on it). Only writes on a
    mismatch; leaves an add-on that isn't installed alone."""
    if xbmc is None:
        return
    engine_on = _engine_on()
    try:
        from resources.lib import kodi_utils as _ku
        keep = _ku.get_bool('keep_darksubs', False)
    except Exception:
        keep = False
    desired = (not engine_on) or keep
    for addon_id in ('service.subtitles.All_Subs',
                     'service.subtitles.all_subs_plus'):
        try:
            import json as _json
            get = _json.dumps({
                'jsonrpc': '2.0', 'id': 1,
                'method': 'Addons.GetAddonDetails',
                'params': {'addonid': addon_id, 'properties': ['enabled']},
            })
            data = _json.loads(xbmc.executeJSONRPC(get) or '{}')
            addon = (data.get('result') or {}).get('addon') or {}
            if 'enabled' not in addon:
                continue
            if bool(addon.get('enabled')) == desired:
                continue
            en = _json.dumps({
                'jsonrpc': '2.0', 'id': 1,
                'method': 'Addons.SetAddonEnabled',
                'params': {'addonid': addon_id, 'enabled': desired},
            })
            xbmc.executeJSONRPC(en)
            xbmc.log('[{0}] {1} set enabled={2} (engine_on={3})'.format(
                ADDON_ID, addon_id, desired, engine_on), level=xbmc.LOGINFO)
        except Exception:
            pass


def _maybe_set_default_subtitle_service():
    """When the engine is on, make MoranSubs the default subtitle service for
    movies + TV. Only when the engine is on (we don't override otherwise)."""
    if xbmc is None or not _engine_on():
        return
    try:
        import json as _json
        for sid in ('subtitles.tv', 'subtitles.movie'):
            getq = _json.dumps({
                'jsonrpc': '2.0', 'id': 1,
                'method': 'Settings.GetSettingValue',
                'params': {'setting': sid},
            })
            cur = (_json.loads(xbmc.executeJSONRPC(getq) or '{}')
                   .get('result') or {}).get('value')
            if cur == ADDON_ID:
                continue
            setq = _json.dumps({
                'jsonrpc': '2.0', 'id': 1,
                'method': 'Settings.SetSettingValue',
                'params': {'setting': sid, 'value': ADDON_ID},
            })
            xbmc.executeJSONRPC(setq)
    except Exception:
        pass


def main():
    if xbmc is None:
        return
    if _check_first_run_marker():
        return

    _prune_once()
    _maybe_purge_temp_once()

    # Roll out / sync the built-in sources engine, then neutralise the competing
    # subtitle add-ons when it's on (reversible -- turn the engine off and they
    # come back). Mirrors the full build.
    _maybe_default_builtin_engine()
    _ensure_darksubs_enabled()
    _maybe_set_default_subtitle_service()

    if not _engine_on():
        # DarkSubs provides the sources when the engine is off: keep our hooks
        # alive. Skipped entirely when the engine is on (DarkSubs is disabled).
        _run('darksubs integration', _maybe_patch_darksubs)
        _run('darksubs download_sub patch', _maybe_patch_darksubs_download_sub)
        _run('darksubs OpenSubtitles patch', _maybe_patch_darksubs_opensubtitles)
        _run('darksubs embedded demote patch', _maybe_patch_darksubs_embedded_demote)
        _run('darksubs embedded insert patch', _maybe_patch_darksubs_embedded_insert)
        _run('darksubs subwindow demote patch', _maybe_patch_darksubs_subwindow_demote)
        _run('darksubs status diagnostics', _maybe_surface_darksubs_status)
        _run('darksubs filename fallback patch', _maybe_patch_darksubs_filename)
        _run('darksubs picker label patch', _maybe_patch_darksubs_picker_label)
        _run('darksubs picker height patch', _maybe_patch_darksubs_picker_height)
        _run('allsubs samefile patch', _maybe_patch_all_subs_samefile)
        try:
            from resources.lib import darksubs_reload
            darksubs_reload.reload_if_patched()
        except Exception:
            pass

    # Skin subtitle-dialog fixes are not DarkSubs-specific -- run regardless.
    _run('subtitle dialog filename patch', _maybe_patch_skin_dialog_subtitles)
    _run('subtitle dialog row patch', _maybe_patch_skin_dialog_subtitles_rows)

    _maybe_repair_rtl_cache()
    _maybe_default_fast_first_chunk()
    _maybe_force_gender_ref_arabic()
    _maybe_tune_gemini3_defaults()
    _maybe_lower_chunk_lines()

    global _subs_filename_publisher
    try:
        from resources.lib import subs_filename_publisher
        _subs_filename_publisher = subs_filename_publisher.SubsFilenamePublisher()
    except Exception:
        pass

    monitor = xbmc.Monitor()
    # Upload any queued community-pool contributions (e.g. mirrored Ktuvit
    # subs) from this long-lived service, throttled + retrying.
    _start_pool_queue_drainer(monitor)
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
        (dst / "default.py").write_text(
            slim_default_text((SRC / "default.py").read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        (dst / "changelog.txt").write_text(
            slim_changelog_text(
                (SRC / "changelog.txt").read_text(encoding="utf-8")),
            encoding="utf-8",
        )


def slim_default_text(text: str) -> str:
    """Remove build-only RunScript actions from the standalone addon.

    The clean subtitle addon still needs default.py for Kodi subtitle
    search/download and AI settings actions, but it must not expose build
    shortcuts such as POV service thresholds or TorBox home-tile status.
    """
    text = re.sub(
        r"\ndef _handle_open_pov_settings\(_params\):.*?(?=\ndef main\(\):)",
        "\n",
        text,
        count=1,
        flags=re.S,
    )
    text = re.sub(
        r"\n        elif action == 'open_pov_settings':\n"
        r"            _handle_open_pov_settings\(params\)"
        r"\n        elif action == 'debrid_notice_settings':\n"
        r"            _handle_debrid_notice_settings\(params\)"
        r"\n        elif action == 'torbox_status':\n"
        r"            _handle_torbox_status\(params\)",
        "",
        text,
        count=1,
    )
    text = text.replace(
        "anywhere, e.g. a Wizard button or a remote shortcut.",
        "anywhere, e.g. a remote shortcut.",
    )
    text = text.replace(
        "'באופן כללי), פתח את ה-Wizard → \"חיבור שירותים\" → TMDB '\n"
        "        'וחבר key אישי. הוא יוחל אוטומטית מאותו רגע, בלי '\n",
        "'באופן כללי), פתח את הגדרות TMDB Helper וחבר key אישי. '\n"
        "        'הוא יוחל אוטומטית מאותו רגע, בלי '\n",
    )
    return text


def slim_changelog_text(text: str) -> str:
    """Keep standalone release notes focused on subtitle-addon changes."""
    skip_terms = (
        "AF3",
        "Arctic",
        "Estuary",
        "FENtastic",
        "TorBox",
        "Premiumize",
        "Real-Debrid",
        "Real Debrid",
        "AllDebrid",
        "Kodi JSON-RPC",
        "keyboard layout",
        "Home",
        "home",
        "Wizard",
        "build",
        "Build",
        "favourites",
        "favourites.xml",
        "skin",
        "Skin",
        "POV search",
        "quickfix",
    )
    sections = re.split(r"(?=^v\d+\.\d+\.\d+\n)", text, flags=re.M)
    kept = []
    for section in sections:
        if not section.strip():
            continue
        lines = section.splitlines()
        header = lines[0]
        bullets = []
        current = []
        for line in lines[1:]:
            if line.startswith("- "):
                if current:
                    bullets.append("\n".join(current))
                current = [line]
            elif current:
                current.append(line)
        if current:
            bullets.append("\n".join(current))
        filtered = [
            bullet for bullet in bullets
            if not any(term in bullet for term in skip_terms)
        ]
        if filtered:
            kept.append(header + "\n" + "\n".join(filtered).rstrip() + "\n")
    if not kept:
        return "v{0}\n- AI subtitle addon maintenance update.\n".format(
            version())
    return "\n".join(kept).rstrip() + "\n"


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
    if len(parts) >= 2 and parts[1] == "media":
        # Bundled UI assets (e.g. the subtitle-chooser flag icons) -- skin-
        # independent so the chooser looks right on the repo-channel add-on too.
        return True
    if len(parts) >= 2 and parts[1] == "skins":
        # The self-contained WindowXMLDialog chooser (window XML + its textures).
        return True
    if len(parts) >= 2 and parts[1] == "patches":
        return parts[2:3] == ("darksubs",)
    if len(parts) >= 3 and parts[1] == "lib":
        if parts[2] == "icons":
            return True
        # The vendored sources engine: ship it in the standalone too, so the
        # repo-channel add-on can fetch subtitles on its own (sources +
        # translation in one add-on) -- not only translate what DarkSubs finds.
        if parts[2] == "subs_engine":
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
        inject_pool_secret(addon_dst)
        make_zip(addon_dst, out)
    return out


def inject_pool_secret(addon_dst: Path) -> None:
    """Bake the real pool signing secret (from $POOL_SECRET) into the shipped
    pool.py, replacing the __POOL_SECRET__ placeholder. The committed source
    keeps only the placeholder, so the real secret never lives in the public
    repo. If $POOL_SECRET is unset we leave the placeholder and warn loudly --
    the build will work but its pool access will be rejected by the Worker."""
    secret = os.environ.get("POOL_SECRET", "").strip()
    pool_py = addon_dst / "resources" / "lib" / "pool.py"
    if not pool_py.is_file():
        return
    txt = pool_py.read_text(encoding="utf-8")
    if "__POOL_SECRET__" not in txt:
        return
    if not secret:
        print("  !! WARNING: $POOL_SECRET not set -- pool signing placeholder "
              "left in place; this build CANNOT use the community pool.")
        return
    pool_py.write_text(txt.replace("__POOL_SECRET__", secret), encoding="utf-8")
    print(f"  pool secret injected ({len(secret)} chars)")


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
                "standalone zip contains build payload:\n"
                + "\n".join(bad[:50])
            )
        default_name = f"{ADDON_ID}/default.py"
        default_text = (
            zf.read(default_name).decode("utf-8", "replace")
            if default_name in names else ""
        )
        changelog_name = f"{ADDON_ID}/changelog.txt"
        changelog_text = (
            zf.read(changelog_name).decode("utf-8", "replace")
            if changelog_name in names else ""
        )
    if default_text:
        forbidden_text = (
            "torbox_status",
            "debrid_notice_settings",
            "open_pov_settings",
            "plugin.video.pov not found",
            "user/stats",
        )
        bad_text = [token for token in forbidden_text if token in default_text]
        if bad_text:
            raise RuntimeError(
                "standalone default.py contains build actions: "
                + ", ".join(bad_text)
            )
        if changelog_text:
            forbidden_changelog = (
                "TorBox",
                "Premiumize",
                "FENtastic",
                "Estuary",
                "AF3",
                "Wizard",
                "quickfix",
            )
            bad_changelog = [
                token for token in forbidden_changelog
                if token in changelog_text
            ]
            if bad_changelog:
                raise RuntimeError(
                    "standalone changelog contains build notes: "
                    + ", ".join(bad_changelog)
                )


def assert_python_compiles() -> None:
    """compile() every .py in the source addon. ast.parse() is NOT enough --
    errors like 'name X is assigned to before global declaration' only surface
    at compile() (symbol-table) time, and one such bug shipped in the engine
    bridge and silently disabled the whole sources engine. Hard-fail the build
    so it can never happen again."""
    import py_compile
    failures = []
    for path in sorted(SRC.rglob("*.py")):
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:  # noqa: PERF203
            failures.append("{0}: {1}".format(
                path.relative_to(ROOT), str(exc).splitlines()[-1]))
    if failures:
        raise SystemExit("BUILD ABORTED -- Python compile errors:\n  "
                         + "\n  ".join(failures))


def main() -> None:
    DIST.mkdir(exist_ok=True)
    assert_python_compiles()
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
