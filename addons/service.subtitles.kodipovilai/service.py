# Background daemon: prune the translation cache on Kodi start, then
# again every 24h while Kodi is running. Lightweight -- one stat
# pass over a small directory and we're done. Exits if Kodi tells
# us to shut down via Monitor.abortRequested().
#
# Everything is wrapped in try/except so a bug here can't take
# the rest of Kodi down with it.
#
# First-run disable: if a `.disable_on_first_run` marker file is
# present in the addon's directory (placed there by the rollout-1
# quick_update patch), this daemon disables itself the moment it
# wakes up and removes the marker. That way existing users get the
# addon installed but inactive, so they can review before opting in.
# Fresh Install builds never ship the marker, so they rely on Kodi's
# default "new user addons start disabled" behaviour.

import os
import threading
import time

try:
    import xbmc
except ImportError:
    xbmc = None

ADDON_ID = 'service.subtitles.kodipovilai'
FIRST_RUN_MARKER = '.disable_on_first_run'

# Strong reference to the SubsFilenamePublisher player monitor,
# kept alive for the lifetime of the service. xbmc.Player subclasses
# stop receiving callbacks when garbage-collected, so this MUST not
# be a local variable.
_subs_filename_publisher = None

BUILD_WIZARD_ID = 'plugin.program.kodipovilwizard'
BUILD_MARKER = 'build_mode.json'
BUILD_MARKER_TEXT = 'Kodi POV IL'
_BUILD_MODE_CACHE = None
_BUILD_SELF_HEAL_THREAD = None


def _translate_path(path):
    try:
        import xbmcvfs
        return xbmcvfs.translatePath(path)
    except Exception:
        return ''


def _safe_exists(path):
    try:
        return bool(path) and os.path.exists(path)
    except Exception:
        return False


def _safe_read(path, limit=200000):
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read(limit)
    except Exception:
        return ''


def _has_build_marker():
    marker_paths = (
        'special://profile/addon_data/{0}/{1}'.format(ADDON_ID, BUILD_MARKER),
        'special://profile/addon_data/{0}/{1}'.format(BUILD_WIZARD_ID, BUILD_MARKER),
    )
    for marker in marker_paths:
        text = _safe_read(_translate_path(marker))
        if BUILD_MARKER_TEXT in text or 'managed_by_build' in text:
            return True
    return False


def _is_kodi_pov_il_build():
    """Return True when this profile is managed by the Kodi POV IL build."""
    global _BUILD_MODE_CACHE
    if _BUILD_MODE_CACHE is not None:
        return _BUILD_MODE_CACHE

    detected = False
    try:
        if _has_build_marker():
            detected = True

        wizard_addon = _translate_path(
            'special://home/addons/{0}/addon.xml'.format(BUILD_WIZARD_ID))
        if _safe_exists(wizard_addon):
            detected = True

        wizard_settings = _translate_path(
            'special://profile/addon_data/{0}/settings.xml'.format(
                BUILD_WIZARD_ID))
        settings_text = _safe_read(wizard_settings)
        if 'Kodi POV IL' in settings_text or 'FENtastic' in settings_text:
            detected = True

        wizard_uservar = _translate_path(
            'special://home/addons/{0}/uservar.py'.format(BUILD_WIZARD_ID))
        uservar_text = _safe_read(wizard_uservar)
        if 'Kodi POV IL' in uservar_text or 'FENtastic' in uservar_text:
            detected = True

        build_icons = _translate_path('special://home/media/build_icons')
        if _safe_exists(os.path.join(build_icons, 'Twilight')):
            detected = True
    except Exception:
        detected = False

    _BUILD_MODE_CACHE = bool(detected)
    return _BUILD_MODE_CACHE


def _ensure_build_marker():
    if not _is_kodi_pov_il_build():
        return
    try:
        import xbmcvfs
        base = _translate_path('special://profile/addon_data/{0}/'.format(
            ADDON_ID))
        if not base:
            return
        try:
            xbmcvfs.mkdirs(base)
        except Exception:
            try:
                os.makedirs(base, exist_ok=True)
            except Exception:
                pass
        marker = os.path.join(base, BUILD_MARKER)
        if _safe_exists(marker):
            return
        content = ('{\n'
                   '  "build": "Kodi POV IL",\n'
                   '  "managed_by_build": true,\n'
                   '  "source": "auto-detected"\n'
                   '}\n')
        with open(marker, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception:
        pass


def _run_build_startup_repairs():
    """Run build-only UI/POV repairs early in Kodi startup.

    These repairs are idempotent and should settle the skin/menus before
    the user starts navigating. Slow steps are still logged individually
    so a future post-quick-update freeze can be traced to a concrete
    patcher instead of becoming guesswork.
    """
    try:
        monitor = xbmc.Monitor()
    except Exception:
        monitor = None

    steps = (
        _maybe_patch_hebrew_build_ui,
        _maybe_patch_brand_assets,
        _maybe_install_build_icons,
        _maybe_patch_brand_favourites,
        _maybe_patch_pov_genre_icons,
        _maybe_patch_pov_genre_menu_icons,
        _maybe_patch_pov_combined_discover,
        _maybe_patch_af3_home,
        _maybe_cleanup_wizard,
        _maybe_patch_pov_repeat_timer,
        _maybe_patch_pov_favorites_refresh,
        _maybe_run_fav_diagnostic,
        _maybe_fix_pov_favourites_typo,
        _maybe_patch_pov_menus,
        _maybe_patch_pov_personal_area,
        _maybe_patch_fentastic_widgets,
        _maybe_patch_favourites_xml,
        _maybe_patch_favourites_personal_tiles,
        _maybe_patch_pov_torbox_usage,
        _maybe_patch_pov_cache_empty,
        _maybe_patch_pov_trakt_cache_empty,
        _maybe_patch_pov_meta_blank,
        _maybe_patch_pov_build_content_logger,
        _maybe_patch_pov_debrid_status,
        _maybe_show_af3_first_launch_dialog,
        _maybe_show_debrid_status,
    )
    for step in steps:
        try:
            if monitor and monitor.abortRequested():
                return
        except Exception:
            pass

        started = time.time()
        try:
            step()
        except Exception as e:
            try:
                from resources.lib import kodi_utils
                kodi_utils.log(
                    'build startup repair {0} failed: {1}'.format(
                        getattr(step, '__name__', 'unknown'), e),
                    level='WARNING')
            except Exception:
                pass

        try:
            if monitor and monitor.waitForAbort(0.25):
                return
        except Exception:
            pass
        if time.time() - started > 4:
            try:
                from resources.lib import kodi_utils
                kodi_utils.log(
                    'build startup repair {0} took {1:.1f}s'.format(
                        getattr(step, '__name__', 'unknown'),
                        time.time() - started),
                    level='WARNING')
            except Exception:
                pass


def _start_build_startup_repairs():
    global _BUILD_SELF_HEAL_THREAD
    try:
        if _BUILD_SELF_HEAL_THREAD and _BUILD_SELF_HEAL_THREAD.is_alive():
            return
    except Exception:
        pass

    try:
        _BUILD_SELF_HEAL_THREAD = threading.Thread(
            target=_run_build_startup_repairs,
            name='KodiPovIlBuildStartupRepairs')
        _BUILD_SELF_HEAL_THREAD.daemon = True
        _BUILD_SELF_HEAL_THREAD.start()
    except Exception as e:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log(
                'build startup repair thread failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass



def _check_first_run_marker():
    """Return True iff we self-disabled (caller should exit)."""
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
            # If we can't delete the marker we still disable, but
            # we'll trip again next launch. Acceptable -- worst case
            # the user has to re-enable twice.
            pass
        try:
            xbmc.log(
                '[' + ADDON_ID + '] first-run marker found; '
                'self-disabling so user can review before opting in',
                level=xbmc.LOGINFO,
            )
        except Exception:
            pass
        # JSON-RPC is the canonical Kodi 19+ way to flip addon state.
        # executebuiltin('DisableAddon(...)') exists but is flakier
        # across Kodi versions, so we use it as a fallback only.
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
        # Never let the first-run check itself crash the service.
        return False


def _prune_source_memory_once():
    """Cap the remembered-sources store so it can never grow unbounded over
    years of watching. Records are tiny (~340 bytes each); this keeps the most
    recent ~2000 and drops older ones (a dropped title just shows the source
    dialog again next time). Independent of the translation-cache prune so one
    failing doesn't skip the other."""
    try:
        from resources.lib import source_memory, kodi_utils
        n = source_memory.prune()
        if n:
            kodi_utils.log(
                'source_memory prune: {0} old record(s) removed'.format(n),
                level='INFO')
    except Exception as e:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log('source_memory prune failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


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
    except Exception as e:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log('Cache prune failed: {0}'.format(e),
                           level='ERROR')
        except Exception:
            pass


# Version tag of the "purge old temp subs once on next startup"
# rollout. When it changes, the service does a one-shot purge of
# .srt files in special://temp/ to evict the cross-movie leftovers
# that the previous list_candidates would surface as Hebrew
# passthrough for the wrong title.
# Bumped to 2: v1 didn't actually fire for the first user
# (suspected: the _temp_purge_done setting wasn't declared in
# settings.xml so the value didn't persist). v2 declares it AND
# re-runs once.
TEMP_PURGE_VERSION = '2'

# Version tag of the "re-apply fix_rtl_punctuation to every cached
# translated SRT" rollout. Translations cached before v0.1.6 didn't
# get the post-processor run on them, and even later caches may
# have slipped through if the regex didn't catch a specific edge.
# Bump this whenever fix_rtl_punctuation gains coverage and we want
# existing caches to benefit without the user manually clearing.
# Bump when fix_rtl_punctuation gains coverage that needs to flow
# through to already-cached translations.
#   v1 -- initial post-processor, simple-text leading-punct only
#   v2 -- HTML-tag-wrapped and dialogue-dash variants
#   v3 -- direction flipped: default is now 'reverse' (move punct
#         to line start) since the original 'auto' direction was
#         based on a wrong assumption about Kodi's BiDi behaviour
#   v4 -- reverse-mode dialogue dash fix: move leading "- " to the
#         logical line end so Kodi renders it on the right side.
CACHE_RTL_FIX_VERSION = '4'


def _maybe_repair_rtl_cache():
    """One-shot walk of cache/translated/, re-applying the current
    fix_rtl_punctuation() to each file. Catches up translations
    that got cached before the post-processor was in place or before
    it handled a specific edge case. Marker-gated so it only runs
    once per CACHE_RTL_FIX_VERSION bump."""
    try:
        from resources.lib import kodi_utils, srt
    except Exception:
        return
    try:
        if kodi_utils.get_setting('_rtl_fix_done', '') == \
                CACHE_RTL_FIX_VERSION:
            return
        translated_dir = os.path.join(
            kodi_utils.cache_dir(), 'translated')
        n_scanned = n_repaired = 0
        if os.path.isdir(translated_dir):
            for fn in os.listdir(translated_dir):
                if not fn.endswith('.srt'):
                    continue
                p = os.path.join(translated_dir, fn)
                n_scanned += 1
                try:
                    with open(p, 'r', encoding='utf-8',
                              errors='replace') as f:
                        content = f.read()
                except OSError:
                    continue
                fixed = srt.fix_rtl_punctuation(content)
                if fixed == content:
                    continue
                tmp = p + '.aitmp'
                try:
                    with open(tmp, 'w', encoding='utf-8') as f:
                        f.write(fixed)
                    os.replace(tmp, p)
                    n_repaired += 1
                except OSError:
                    try: os.remove(tmp)
                    except OSError: pass
        kodi_utils.set_setting('_rtl_fix_done', CACHE_RTL_FIX_VERSION)
        kodi_utils.log(
            'RTL cache repair v{0}: scanned {1}, repaired {2}'.format(
                CACHE_RTL_FIX_VERSION, n_scanned, n_repaired),
            level='INFO')
    except Exception as e:
        try:
            kodi_utils.log(
                'RTL cache repair failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_unpatch_fentastic_notification():
    """v0.2.9 patched FENtastic's DialogNotification.xml to swap
    the message control from fadelabel to wraplabel, trying to
    work around a BiDi-deaf marquee that scrolls Hebrew the wrong
    way. It produced regressions in the user's UI (empty
    notifications + buggy subtitle picker), so v0.2.10 reverts
    the patch and never re-applies it. For users who got v0.2.9
    on disk, this restores the upstream FENtastic file on next
    Kodi startup. Idempotent + safe to call every startup."""
    try:
        from resources.lib import fentastic_patcher
    except Exception:
        return
    try:
        fentastic_patcher.ensure_unpatched()
    except Exception:
        pass


def _maybe_fix_pov_favourites_typo():
    """One-shot rewrite of POV's bundled navigator.db so the
    Favorites tile on the home screen points at the method POV
    actually defines (navigator.favorites, US spelling). The
    shipped DB has 'navigator.favourites' (UK spelling, with 'u')
    which doesn't match POV's method name, so the plugin invocation
    returns None, never calls endOfDirectory(), and Kodi kills the
    script after its 5-second timeout -- experienced by the user
    as "click Favorites, Kodi freezes for ~a minute, bounces back
    to home". Idempotent + defensive; future installs ship a
    corrected DB so this patcher is belt-and-braces."""
    try:
        from resources.lib import pov_navigator_patcher, kodi_utils
    except Exception:
        return
    try:
        status = pov_navigator_patcher.maybe_fix_favourites_typo()
        if status == 'fixed':
            kodi_utils.log(
                'pov_navigator_patcher: rewrote favourites typo '
                'in navigator.db', level='INFO')
        elif status == 'failed':
            kodi_utils.log(
                'pov_navigator_patcher: skipped (will retry next '
                'startup)', level='WARNING')
        # 'unchanged' / 'no_db' -- silent; the common steady state
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_navigator_patcher run failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_pov_menus():
    """Force-sync POV's three context-menu builders (movies.py,
    tvshows.py, episodes.py) to the canonical versions bundled in
    this addon. Same self-healing pattern as pov_services_patcher
    but using a whole-file copy instead of marker-inject, since
    PR #98 replaces an existing block rather than appending one.
    """
    try:
        from resources.lib import pov_menus_patcher, kodi_utils
    except Exception:
        return
    try:
        results = pov_menus_patcher.ensure_patched()
        patched = [k for k, v in results.items() if v == 'patched']
        if patched:
            kodi_utils.log(
                'pov_menus_patcher: synced {0} on startup'.format(
                    ', '.join(patched)), level='INFO')
        failed = [k for k, v in results.items()
                  if v in ('failed', 'no_target', 'no_source')]
        if failed:
            kodi_utils.log(
                'pov_menus_patcher: skipped {0}'.format(
                    ', '.join(failed)), level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_menus_patcher run failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass



def _maybe_cleanup_standalone_build_patches():
    """Best-effort cleanup for users who installed only the subtitle addon."""
    if _is_kodi_pov_il_build():
        return
    try:
        from resources.lib import standalone_cleanup, kodi_utils
    except Exception:
        return
    try:
        status = standalone_cleanup.ensure_cleaned()
        if status not in ('already_done', 'no_db'):
            kodi_utils.log(
                'standalone_cleanup: {0}'.format(status),
                level='INFO')
    except Exception as e:
        try:
            kodi_utils.log(
                'standalone_cleanup failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_pov_personal_area():
    """Rewrite POV's navigator.db personal-area rows so the
    FENtastic widget on the movies/shows pages leads with TMDB
    Favorites instead of Trakt Collection. Only rewrites rows
    that match the shipped baseline byte-for-byte (any user
    customization aborts the rewrite cleanly).
    """
    try:
        from resources.lib import pov_navigator_patcher, kodi_utils
    except Exception:
        return
    try:
        results = pov_navigator_patcher.maybe_fix_personal_area_lists()
        # results is either {'_status': '...'} or {row_name: status}
        if isinstance(results, dict) and '_status' not in results:
            fixed = [k for k, v in results.items() if v == 'fixed']
            if fixed:
                kodi_utils.log(
                    'pov_navigator_patcher: rewrote personal-area '
                    'rows: {0}'.format(', '.join(fixed)),
                    level='INFO')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_navigator_patcher (personal area) failed: '
                '{0}'.format(e), level='WARNING')
        except Exception:
            pass


def _maybe_patch_fentastic_widgets():
    """Drop the "(must connect to Trakt)" subtitle from the
    FENtastic personal-area widget header on movies/shows pages.
    """
    try:
        from resources.lib import fentastic_widget_patcher, kodi_utils
    except Exception:
        return
    try:
        results = fentastic_widget_patcher.ensure_patched()
        patched = [k for k, v in results.items() if v == 'patched']
        if patched:
            kodi_utils.log(
                'fentastic_widget_patcher: updated header in '
                '{0}'.format(', '.join(patched)), level='INFO')
    except Exception as e:
        try:
            kodi_utils.log(
                'fentastic_widget_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_fentastic_search():
    """Repoint the "simple" skins' home SEARCH button to POV's search node
    so pressing search lands directly on SEARCH: Movies / TV Shows / People
    / Movies Collection, instead of the skin's own search dialog. Covers
    skin.fentastic and skin.estuary; a skin that isn't installed has no
    Home.xml and is a no-op. Idempotent + self-healing each startup."""
    try:
        from resources.lib import fentastic_search_patcher, kodi_utils
    except Exception:
        return
    try:
        status = fentastic_search_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'fentastic_search_patcher: search buttons adjusted per skin',
                level='INFO')
    except Exception as e:
        try:
            kodi_utils.log(
                'fentastic_search_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_install_build_icons():
    """Install the bundled TMDB-branded home-tile icons under
    media/build_icons/ so the favourites_xml_patcher can point at
    them. Idempotent -- skips files that already exist."""
    try:
        from resources.lib import build_icons_patcher, kodi_utils
    except Exception:
        return
    try:
        result = build_icons_patcher.ensure_installed()
        if isinstance(result, dict) and result.get('installed'):
            kodi_utils.log(
                'build_icons_patcher: installed {0}'.format(
                    ', '.join(result['installed'])), level='INFO')
        if isinstance(result, dict) and result.get('updated'):
            kodi_utils.log(
                'build_icons_patcher: updated {0}'.format(
                    ', '.join(result['updated'])), level='INFO')
    except Exception as e:
        try:
            kodi_utils.log(
                'build_icons_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_brand_assets():
    """Replace legacy Real-Debrid/KODI build branding with POV IL branding."""
    try:
        from resources.lib import brand_assets_patcher, kodi_utils
    except Exception:
        return
    try:
        result = brand_assets_patcher.ensure_patched()
        if isinstance(result, dict):
            updated = [k for k, v in result.items() if v == 'updated']
            if updated:
                kodi_utils.log(
                    'brand_assets_patcher: updated {0}'.format(
                        ', '.join(updated)), level='INFO')
    except Exception as e:
        try:
            kodi_utils.log(
                'brand_assets_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_brand_favourites():
    """Move home favourites to cache-busting POV IL icon filenames."""
    try:
        from resources.lib import brand_favourites_patcher, kodi_utils
    except Exception:
        return
    try:
        status = brand_favourites_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'brand_favourites_patcher: updated home icon paths',
                level='INFO')
    except Exception as e:
        try:
            kodi_utils.log(
                'brand_favourites_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_hebrew_build_ui():
    """Keep Wizard-installed build profiles on the intended Hebrew UI."""
    try:
        from resources.lib import hebrew_build_ui_patcher, kodi_utils
    except Exception:
        return
    try:
        status = hebrew_build_ui_patcher.ensure_patched()
        if status != 'already_ok':
            kodi_utils.log(
                'hebrew_build_ui_patcher: {0}'.format(status),
                level='INFO')
    except Exception as e:
        try:
            kodi_utils.log(
                'hebrew_build_ui_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_pov_genre_icons():
    """Re-icon POV's genre navigator rows to the stable
    media/build_icons/Genres/ set we ship (AF3 cached shortcut rows)."""
    try:
        from resources.lib import af3_home_patcher, kodi_utils
    except Exception:
        return
    try:
        if af3_home_patcher._patch_pov_genre_icons():
            kodi_utils.log(
                'pov genre icons: repointed navigator rows to '
                'build_icons/Genres', level='INFO')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov genre icons patch failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_pov_genre_menu_icons():
    """THE real genre-icon fix for BOTH skins: patch POV's
    menus/navigator.py genres()/anime_genres() so each genre uses its own
    icon (value[1]) instead of the single generic 'genres.png'. Both
    FENtastic and AF3 open genres via mode=navigator.genres, so this one
    change gives every genre a distinct icon everywhere. Also installs our
    line-art genre PNGs into POV's media/genres/."""
    try:
        from resources.lib import pov_genre_icons_patcher, kodi_utils
    except Exception:
        return
    try:
        status = pov_genre_icons_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'pov_genre_icons_patcher: per-genre icons enabled in '
                'navigator.py', level='INFO')
        elif status in ('no_pov', 'no_file', 'already_patched'):
            pass
        else:
            kodi_utils.log(
                'pov_genre_icons_patcher: ' + status, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_genre_icons_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_pov_combined_discover():
    """Add a unified movie+tv data source to POV (tmdb_search_multi /
    tmdb_trending_all + a build_tmdb_list branch) so AF3's Discover grid
    can show movies AND tv together, ranked by popularity. Reuses POV's
    existing mixed-media merge/sort/render path. Marker-gated, idempotent,
    re-applied each boot."""
    try:
        from resources.lib import pov_combined_discover_patcher, kodi_utils
    except Exception:
        return
    try:
        status = pov_combined_discover_patcher.ensure_patched()
        if isinstance(status, str) and '=patched' in status:
            kodi_utils.log(
                'pov_combined_discover_patcher: unified discover data '
                'source added to POV (' + status + ')', level='INFO')
        elif status == 'no_pov':
            pass
        else:
            kodi_utils.log(
                'pov_combined_discover_patcher: ' + str(status),
                level='INFO')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_combined_discover_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_favourites_xml():
    """Migrate the two Trakt-collection home tiles to TMDB
    Favorites equivalents in userdata/favourites.xml. Surgical --
    only touches lines that match the shipped baseline.
    """
    try:
        from resources.lib import favourites_xml_patcher, kodi_utils
    except Exception:
        return
    try:
        status = favourites_xml_patcher.ensure_patched()
        if status.startswith('patched'):
            kodi_utils.log(
                'favourites_xml_patcher: ' + status, level='INFO')
        elif status in ('write_failed', 'read_failed'):
            kodi_utils.log(
                'favourites_xml_patcher skipped: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'favourites_xml_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_favourites_personal_tiles():
    """Restore the 6 personal home tiles ("הסרטים שלי / הסדרות שלי"
    in TMDB / Trakt / POV variants) when they're missing from
    userdata/favourites.xml. Triggered when the user switched skin to
    AF3 and back to FENtastic, which caused the wizard to overwrite
    their 32-tile install default with the 11-tile skin seed --
    wiping the personal tiles. The patcher appends the missing tiles
    from a bundled canonical fixture so the user gets their tiles
    back on the next boot."""
    try:
        from resources.lib import (
            favourites_personal_tiles_patcher, kodi_utils)
    except Exception:
        return
    try:
        status = favourites_personal_tiles_patcher.ensure_patched()
        if status in ('restored', 'restored_full', 'fixed',
                      'restored_and_fixed', 'marked', 'marked_and_fixed'):
            kodi_utils.log(
                'favourites_personal_tiles_patcher: {0}'.format(status),
                level='INFO')
        elif status in ('no_kodi', 'no_favourites', 'no_fixture',
                        'already_complete', 'user_removed_tiles'):
            pass  # quiet steady-state
        else:
            kodi_utils.log(
                'favourites_personal_tiles_patcher: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'favourites_personal_tiles_patcher failed: '
                '{0}'.format(e), level='WARNING')
        except Exception:
            pass


def _maybe_patch_pov_cache_empty():
    """Patch POV's caches/main_cache.py so cache_object() refuses to
    store empty API results in the 24-hour cache. Fixes the
    real-user bug where adding to TMDB favorites via the in-app
    context menu succeeds on themoviedb.org but the "My Movies
    (TMDB)" tile keeps showing "No results" until the cache row
    naturally expires. Also one-shot-clears any tmdblist_* /
    trakt_* rows already sitting empty in maincache.db."""
    try:
        from resources.lib import (
            pov_cache_empty_patcher, kodi_utils)
    except Exception:
        return
    try:
        status = pov_cache_empty_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'pov_cache_empty_patcher: cache_object now skips '
                'empty results; stale list rows cleared',
                level='INFO')
        elif status in ('no_pov', 'no_file', 'already_patched'):
            pass  # quiet steady-state
        else:
            kodi_utils.log(
                'pov_cache_empty_patcher: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_cache_empty_patcher failed: '
                '{0}'.format(e), level='WARNING')
        except Exception:
            pass


def _maybe_patch_pov_torbox_usage():
    """Build-only patch: add TorBox 30-day usage to POV account status."""
    try:
        from resources.lib import (
            pov_torbox_usage_patcher, kodi_utils)
    except Exception:
        return
    try:
        status = pov_torbox_usage_patcher.ensure_patched()
        if status.startswith('patched'):
            kodi_utils.log(
                'pov_torbox_usage_patcher: ' + status, level='INFO')
        elif status in ('already_complete', 'no_kodi'):
            pass
        else:
            kodi_utils.log(
                'pov_torbox_usage_patcher: ' + status, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_torbox_usage_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_pov_trakt_cache_empty():
    """Patch POV's caches/trakt_cache.py so cache_trakt_object()
    refuses to store empty results. Companion to _maybe_patch_pov_
    cache_empty (which only handles main_cache.py). Trakt's cache is
    in a SEPARATE database (trakt.db) and -- critically -- has NO
    expiration, so a single transient empty caches forever until an
    explicit clear. Fixes the "My Movies (Trakt) tile shows empty
    even though trakt.tv has the items" symptom that survived the
    first PR's main_cache patch."""
    try:
        from resources.lib import (
            pov_trakt_cache_empty_patcher, kodi_utils)
    except Exception:
        return
    try:
        status = pov_trakt_cache_empty_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'pov_trakt_cache_empty_patcher: cache_trakt_object '
                'now skips empty results; stale Trakt list rows '
                'cleared', level='INFO')
        elif status in ('no_pov', 'no_file', 'already_patched'):
            pass  # quiet steady-state
        else:
            kodi_utils.log(
                'pov_trakt_cache_empty_patcher: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_trakt_cache_empty_patcher failed: '
                '{0}'.format(e), level='WARNING')
        except Exception:
            pass


def _maybe_patch_pov_build_content_logger():
    """Instrument POV's per-item list builders (menus/movies.py +
    tvshows.py) so the SWALLOWED exception that empties favorites lists
    is logged. We proved auth/fetch/db/meta are all fine yet the list
    renders empty in ~218ms -- meaning build_movie_content raises in the
    live Kodi context and its bare `except: pass` eats it. This turns
    that into a POV_BUILD_ITEM_ERROR log line with the real exception."""
    try:
        from resources.lib import (
            pov_build_content_logger_patcher, kodi_utils)
    except Exception:
        return
    try:
        status = pov_build_content_logger_patcher.ensure_patched()
        if 'patched' in status and 'already' not in status:
            kodi_utils.log(
                'pov_build_content_logger_patcher: ' + status,
                level='INFO')
        elif status in ('no_pov',):
            pass
        else:
            kodi_utils.log(
                'pov_build_content_logger_patcher: ' + status,
                level='INFO')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_build_content_logger_patcher failed: '
                '{0}'.format(e), level='WARNING')
        except Exception:
            pass


def _maybe_patch_pov_meta_blank():
    """Patch POV's indexers/metadata.py so a transient per-item
    metadata fetch failure (movie_details timeout/blip) doesn't persist
    a blank_entry into metacache.db for 2 days. Third sibling to the
    main_cache and trakt_cache empty patchers -- those fix the LIST
    caches; this fixes the PER-ITEM meta cache, the one neither touched.
    Fixes the diagnosed bug where favorites ARE saved (watched.db has
    the rows, auth valid) but both POV-local and TMDB favorites tiles
    show 0 in BOTH skins because the items' metadata is cached blank.
    Also one-shot-clears already-poisoned blank_entry rows so existing
    favorites recover immediately."""
    try:
        from resources.lib import (
            pov_meta_blank_patcher, kodi_utils)
    except Exception:
        return
    try:
        status = pov_meta_blank_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'pov_meta_blank_patcher: movie_meta/tvshow_meta no '
                'longer persist transient blank_entry; poisoned rows '
                'cleared', level='INFO')
        elif status in ('no_pov', 'no_file', 'already_patched'):
            pass  # quiet steady-state
        else:
            kodi_utils.log(
                'pov_meta_blank_patcher: ' + status, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_meta_blank_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_pov_repeat_timer():
    """Wrap POV's myservices.py RepeatTimer.run() in try/except so
    auth-polling threads survive single-iteration failures. Without
    this, transient errors (network blip, malformed response, etc.)
    kill the polling thread silently and the user's auth dialog
    for Trakt / RD / TorBox / PM / AD hangs forever after they
    authorize on the website."""
    try:
        from resources.lib import pov_repeat_timer_patcher, kodi_utils
    except Exception:
        return
    try:
        status = pov_repeat_timer_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'pov_repeat_timer_patcher: applied auth polling '
                'try/except wrap', level='INFO')
        elif status in ('unmatched', 'write_failed', 'read_failed'):
            kodi_utils.log(
                'pov_repeat_timer_patcher: ' + status, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_repeat_timer_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_run_fav_diagnostic():
    """One-shot diagnostic for the 'Add to My List shows 0 results' bug:
    reads (never writes) POV's TMDB/Trakt auth state, the POV-local
    favorites DB, and the TMDB/Trakt list caches, then logs + writes a
    file + pops a textviewer the user can screenshot. Gated so it runs
    once per DIAG_VERSION."""
    try:
        from resources.lib import pov_favorites_diagnostic, kodi_utils
    except Exception:
        return
    try:
        status = pov_favorites_diagnostic.run()
        kodi_utils.log('pov_favorites_diagnostic: ' + str(status),
                       level='INFO')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_favorites_diagnostic run failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_pov_favorites_refresh():
    """Make POV's dialogs.py refresh the open container when an item is
    ADDED to a list, not only when removed. Without this, adding a title
    to "My Movies"/"My Shows" (TMDB Favorites/Watchlist, a custom list,
    or POV-local favorites) shows the "added" toast but the item only
    appears after navigating away and back -- removing already refreshes
    instantly. Self-healing: re-applies every startup if POV wiped the
    marker; skips silently if the upstream shape changed."""
    try:
        from resources.lib import pov_favorites_refresh_patcher, kodi_utils
    except Exception:
        return
    try:
        status = pov_favorites_refresh_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'pov_favorites_refresh_patcher: container now refreshes '
                'on add too', level='INFO')
        elif status in ('unmatched', 'write_failed', 'read_failed'):
            kodi_utils.log(
                'pov_favorites_refresh_patcher: ' + status, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_favorites_refresh_patcher run failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_pov_services():
    """Inject Gemini AI + Wyzie entries into the POV plugin's
    "My Services" menu (the one at /myservices in plugin.video.pov).
    Same self-healing pattern as the wizard patcher -- POV's menu
    has a hardcoded tuple of services with no extension point, so
    we patch the source file on disk and re-inject on every Kodi
    startup if the marker is missing."""
    try:
        from resources.lib import pov_services_patcher, kodi_utils
    except Exception:
        return
    try:
        status = pov_services_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'pov_services_patcher (re)injected on startup',
                level='INFO')
        elif status in ('unmatched', 'write_failed', 'read_failed'):
            kodi_utils.log(
                'pov_services_patcher skipped: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_services_patcher run failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_cleanup_wizard():
    """Clean up the (incorrect) wizard "Connect Services" injection
    that v0.1.5-v0.1.7 of this addon shipped. The right menu was
    plugin.video.pov's My Services (handled separately by
    pov_services_patcher); the wizard injection was misplaced and
    we don't want stale rows lingering in the wizard's login_menu
    UI after the user upgrades."""
    try:
        from resources.lib import wizard_patcher
    except Exception:
        return
    try:
        wizard_patcher.ensure_unpatched()
    except Exception:
        pass


def _maybe_patch_darksubs():
    """Self-healing patch of DarkSubs's machine_translate_subs so
    that when a user with a Gemini key picks a non-Hebrew subtitle
    from DarkSubs, the translation goes through our AI instead of
    Google/Bing/Yandex. Idempotent, safe to re-run on every Kodi
    startup -- if upstream DarkSubs updates and overwrites the
    injected hook, this puts it back."""
    try:
        from resources.lib import dark_subs_integration, kodi_utils
    except Exception:
        return
    try:
        status = dark_subs_integration.maybe_patch_darksubs()
        if status == 'patched':
            kodi_utils.log('DarkSubs hook (re)injected on startup',
                           level='INFO')
        elif status in ('unmatched', 'write_failed', 'read_failed',
                        'failed'):
            kodi_utils.log(
                'DarkSubs hook injection skipped: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log('DarkSubs patch run failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _maybe_patch_darksubs_download_sub():
    """Self-healing patch of DarkSubs's download_sub() elif so the
    AI hook (in machine_translate_subs, see _maybe_patch_darksubs)
    also fires when the user has DarkSubs's `auto_translate` setting
    turned OFF. Without this, picking a non-Hebrew subtitle manually
    leaves the original English on screen -- the AI hook never gets
    a chance to run because machine_translate_subs is never called.
    User-reported on CoreELEC: explicitly turned auto_translate off
    because they didn't want DarkSubs's Google fallback, expected
    AI to still pick up manual selections."""
    try:
        from resources.lib import darksubs_download_sub_patcher, \
            kodi_utils
    except Exception:
        return
    try:
        status = darksubs_download_sub_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'darksubs_download_sub_patcher: rewrote elif so AI '
                'fires with auto_translate=OFF', level='INFO')
        elif status in ('unmatched', 'write_failed', 'read_failed'):
            kodi_utils.log(
                'darksubs_download_sub_patcher: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log(
                'darksubs_download_sub_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_darksubs_opensubtitles():
    """Self-healing OpenSubtitles provider fix for DarkSubs.

    This runs in both build and standalone AI-addon installs. It only
    copies DarkSubs's OpenSubtitles provider + local API-key fallback, so
    standalone installs do not receive build UI/menu/list changes.
    """
    try:
        from resources.lib import darksubs_opensubtitles_patcher, \
            kodi_utils
    except Exception:
        return
    try:
        status = darksubs_opensubtitles_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'darksubs_opensubtitles_patcher: OpenSubtitles provider '
                'updated', level='INFO')
        elif status == 'failed':
            kodi_utils.log(
                'darksubs_opensubtitles_patcher: failed',
                level='WARNING')
    except Exception as e:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log(
                'darksubs_opensubtitles_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_darksubs_embedded_demote():
    """Self-healing patch of DarkSubs's engine.py so embedded ('[LOC]')
    subtitle entries sink to the BOTTOM of their language group instead
    of floating to the top on their hard-coded 101% sync. On this
    streaming build the embedded track can't be AI-translated (DarkSubs
    short-circuits embedded picks with setSubtitleStream before our
    hook runs), so demoting it makes an external, AI-translatable
    English source the natural first pick."""
    try:
        from resources.lib import darksubs_embedded_demote_patcher, \
            kodi_utils
    except Exception:
        return
    try:
        status = darksubs_embedded_demote_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'darksubs_embedded_demote_patcher: [LOC] embedded '
                'entries now sort to the bottom of their group',
                level='INFO')
            try:
                from resources.lib import darksubs_reload
                darksubs_reload.note_patched()
            except Exception:
                pass
        elif status in ('unmatched', 'write_failed', 'read_failed'):
            kodi_utils.log(
                'darksubs_embedded_demote_patcher: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log(
                'darksubs_embedded_demote_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_darksubs_embedded_insert():
    """THE root-cause fix for embedded English on top. DarkSubs's
    autosub.py inserts the embedded English entry at "right after the
    last Hebrew subtitle", i.e. ABOVE the real English subs -- and it
    does this AFTER engine.sort_subtitles, which is why the engine/picker
    demotes never moved it. This patches autosub.py to insert embedded
    English at the END of the list instead."""
    try:
        from resources.lib import darksubs_embedded_insert_patcher, \
            kodi_utils
    except Exception:
        return
    try:
        status = darksubs_embedded_insert_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'darksubs_embedded_insert_patcher: embedded English now '
                'inserted at the bottom of the list', level='INFO')
            try:
                from resources.lib import darksubs_reload
                darksubs_reload.note_patched()
            except Exception:
                pass
        elif status in ('unmatched', 'write_failed', 'read_failed'):
            kodi_utils.log(
                'darksubs_embedded_insert_patcher: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log(
                'darksubs_embedded_insert_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_darksubs_subwindow_demote():
    """Final-point embedded-English demote: patch DarkSubs's picker
    dialog sub_window.py so the embedded 'תרגום מובנה אנגלית' ([LOC])
    row sinks to the bottom of the list right before it's drawn --
    independent of engine.sort_subtitles ordering (which didn't move it
    on the user's device). Reorders the display list and the parallel
    download list in lockstep so picking still downloads the right sub;
    a genuine embedded Hebrew track stays on top."""
    try:
        from resources.lib import darksubs_subwindow_demote_patcher, \
            kodi_utils
    except Exception:
        return
    try:
        status = darksubs_subwindow_demote_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'darksubs_subwindow_demote_patcher: embedded English now '
                'sinks to the bottom of the picker', level='INFO')
            try:
                from resources.lib import darksubs_reload
                darksubs_reload.note_patched()
            except Exception:
                pass
        elif status in ('unmatched', 'write_failed', 'read_failed'):
            kodi_utils.log(
                'darksubs_subwindow_demote_patcher: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log(
                'darksubs_subwindow_demote_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_surface_darksubs_status():
    """Run the DarkSubs hook diagnostic at startup. If the integration
    has an actionable problem (e.g. signature mismatch, read-only
    filesystem -- CoreELEC has shown up in user reports), pop a
    Hebrew toast pointing the user at the settings 'Test DarkSubs
    integration' entry. Only once per failure-class-version so we
    don't spam on every boot."""
    try:
        from resources.lib import darksubs_hook_diagnostics
    except Exception:
        return
    try:
        darksubs_hook_diagnostics.surface_status_if_problem()
    except Exception as e:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log(
                'darksubs_hook_diagnostics.surface_status_if_problem '
                'failed: {0}'.format(e), level='WARNING')
        except Exception:
            pass


def _maybe_patch_pov_remember_source():
    """PHASE 1 (capture only) of "remember the source the user picked": patch
    POV's sources.py to record the chosen source per media (gated by our
    `remember_source` setting, OFF by default). The patcher compile-checks the
    result before writing, so it can never break POV playback."""
    try:
        from resources.lib import pov_remember_source_patcher, kodi_utils
    except Exception:
        return
    try:
        status = pov_remember_source_patcher.ensure_patched()
        if status in ('patched', 'unmatched', 'compile_failed',
                      'write_failed', 'read_failed'):
            kodi_utils.log('pov_remember_source_patcher: ' + status,
                           level=('INFO' if status == 'patched' else 'WARNING'))
        # If we just changed POV's sources.py AND the user opted in, cycle POV
        # so its reuse-language-invoker interpreter re-imports the patched code
        # this session (otherwise it only applies a restart later). Gated by the
        # setting so users with the feature off never get POV cycled.
        if status == 'patched' and kodi_utils.get_bool('remember_source', False):
            try:
                from resources.lib import pov_reload
                pov_reload.note_patched()
            except Exception:
                pass
    except Exception as e:
        try:
            kodi_utils.log('pov_remember_source_patcher failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


_AUTOSUB_STATE = {'last_file': None, 'busy': False, 'player': None}


def _autosub_on_play():
    """Phase C auto-on-play: when the built-in engine is on, search and apply
    the best Hebrew subtitle automatically (replacing DarkSubs's autosub).
    Runs in its own thread so it never blocks Kodi's playback callback."""
    try:
        from resources.lib import kodi_utils, translate
    except Exception:
        return
    try:
        if not kodi_utils.get_bool('use_builtin_engine', False):
            return
        if not kodi_utils.get_bool('engine_autosub', True):
            return
        if not kodi_utils.hebrew_subtitle_wanted():
            return
    except Exception:
        return

    if _AUTOSUB_STATE['busy']:
        return
    _AUTOSUB_STATE['busy'] = True
    progress = None
    try:
        # Right after onAVStarted the player metadata (imdb/title) often
        # isn't populated yet -- poll briefly until it is (mirrors how
        # DarkSubs waits for the video before searching).
        info = {}
        for _ in range(30):  # up to ~6s
            info = kodi_utils.current_video_info()
            if (info.get('imdb_id') or info.get('tmdb_id')
                    or info.get('title')):
                break
            try:
                if not xbmc.Player().isPlayingVideo():
                    return
            except Exception:
                pass
            xbmc.sleep(200)

        f = info.get('filepath') or info.get('title') or ''
        # onAVStarted can fire more than once for the same file; act once.
        if f and f == _AUTOSUB_STATE['last_file']:
            return
        _AUTOSUB_STATE['last_file'] = f
        if not (info.get('imdb_id') or info.get('tmdb_id')
                or info.get('title')):
            return

        try:
            progress = xbmcgui.DialogProgressBG()
            progress.create('MoranSubs', 'מחפש כתוביות עברית...')
        except Exception:
            progress = None

        # Non-modal search (the bottom banner above is our progress).
        # list_candidates returns everything in priority order; the first
        # 'he' row is the best Hebrew (embedded > human > pool > MT).
        cands = translate.list_candidates(info, modal_progress=False)
        he = next((c for c in cands if c.get('language') == 'he'), None)
        if not he:
            try:
                kodi_utils.notify('MoranSubs: לא נמצאה כתובית עברית',
                                  time_ms=3000)
            except Exception:
                pass
            return
        path = translate.resolve(he['link'], info)
        # Embedded picks switch the stream inside resolve() and return None;
        # external/pool picks return a file path to load.
        if path:
            try:
                p = xbmc.Player()
                if p.isPlayingVideo():
                    p.setSubtitles(path)
                    p.showSubtitles(True)
            except Exception:
                pass
        try:
            kodi_utils.notify('MoranSubs: הוחלה כתובית עברית', time_ms=3000)
        except Exception:
            pass
    except Exception as e:
        try:
            kodi_utils.log('autosub_on_play failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass
    finally:
        _AUTOSUB_STATE['busy'] = False
        if progress is not None:
            try:
                progress.close()
            except Exception:
                pass


if xbmc is not None:
    class _AutoSubPlayer(xbmc.Player):
        def onAVStarted(self):
            try:
                threading.Thread(target=_autosub_on_play, daemon=True).start()
            except Exception:
                pass


def _maybe_start_autosub_player():
    """Register a Player listener so we can auto-search + auto-apply Hebrew on
    play, but ONLY when the engine is on and autosub is enabled. The service's
    existing prune loop keeps the process alive, so the Player callbacks fire;
    we just hold a reference. When off, does nothing (behavior unchanged)."""
    if xbmc is None:
        return
    try:
        from resources.lib import kodi_utils
        if not kodi_utils.get_bool('use_builtin_engine', False):
            return
        if not kodi_utils.get_bool('engine_autosub', True):
            return
    except Exception:
        return
    try:
        _AUTOSUB_STATE['player'] = _AutoSubPlayer()  # keep a ref alive
        # If a video is already playing when the service starts, kick once.
        try:
            if xbmc.Player().isPlayingVideo():
                threading.Thread(target=_autosub_on_play, daemon=True).start()
        except Exception:
            pass
    except Exception:
        pass


def _maybe_prewarm_engine():
    """If the built-in sources engine is enabled, import it (and ensure its
    settings) in a background thread so the first subtitle search is warm.
    Fully guarded; a failure here never affects anything."""
    try:
        from resources.lib import kodi_utils
        if not kodi_utils.get_bool('use_builtin_engine', False):
            return
    except Exception:
        return

    def _work():
        try:
            from resources.lib import subs_engine_bridge
            subs_engine_bridge.ensure_engine_settings()
            from resources.lib.subs_engine import engine  # noqa: F401
        except Exception:
            pass

    try:
        threading.Thread(target=_work, daemon=True).start()
    except Exception:
        pass


def _maybe_patch_pov_subtitle_match():
    """Show a Hebrew-subtitle match % under each source in POV's source-results
    window (gated by `show_subtitle_match`, default on). Patches POV's
    windows/sources.py to prepend a coloured '<NN>% עברית' to each row's
    size_label -- a property rendered first in the info line of every layout, so
    it shows on every skin with no skin-XML changes. The patcher compile-checks
    before writing, so it can never break the source window / playback."""
    try:
        from resources.lib import pov_subtitle_match_patcher, kodi_utils
    except Exception:
        return
    try:
        status = pov_subtitle_match_patcher.ensure_patched()
        if status in ('patched', 'unmatched', 'compile_failed',
                      'write_failed', 'read_failed'):
            kodi_utils.log('pov_subtitle_match_patcher: ' + status,
                           level=('INFO' if status == 'patched' else 'WARNING'))
        # Cycle POV so its reuse-language-invoker interpreter re-imports the
        # patched window this session (the runtime gate in he_sub_match means a
        # user who turns the feature off just sees no badge).
        if status == 'patched':
            try:
                from resources.lib import pov_reload
                pov_reload.note_patched()
            except Exception:
                pass
    except Exception as e:
        try:
            kodi_utils.log('pov_subtitle_match_patcher failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _maybe_patch_pov_source_name():
    """Self-healing patch of POV's sources.py so that when POV picks
    a source from the source-select dialog (the one with cached/
    uncached/quality flags), it stashes the picked release name +
    URL in a Window(10000) property right before yielding the link
    to the player. DarkSubs (separate addon) reads the property and
    uses the real release name -- complete with encoder/source/group
    tokens -- as the filename for subtitle matching, instead of
    whatever opaque basename the debrid CDN URL happens to have.
    Without this, TorBox playbacks get 0% on every subtitle (URL is
    a UUID) and the user sees the UUID as the dialog title -- they
    can't even visually compare it to subtitle release names to pick
    one manually. With this, the dialog title shows the real release
    name and the percentages reflect actual sync quality."""
    try:
        from resources.lib import pov_source_name_patcher, kodi_utils
    except Exception:
        return
    try:
        status = pov_source_name_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'pov_source_name_patcher: applied source-name '
                'window-property stash', level='INFO')
        elif status in ('unmatched', 'write_failed', 'read_failed'):
            kodi_utils.log(
                'pov_source_name_patcher: ' + status, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_source_name_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_darksubs_filename():
    """Self-healing patch of DarkSubs's get_playing_filename so that
    when the played URL has an opaque hash basename (TorBox CDN
    behaviour: https://store-N.torbox.app/<uuid>?token=...), DarkSubs
    falls back to a synthetic release-name-style filename built from
    VideoPlayer/ListItem info-labels. Without this, DarkSubs's
    percentage matcher tokenises the UUID, gets 0% overlap with every
    subtitle in the list, and the user picks subtitles blind. Real
    Debrid / AllDebrid URLs already include the release filename in
    the path so they are unaffected. Idempotent + defensive."""
    try:
        from resources.lib import darksubs_filename_fallback_patcher, \
            kodi_utils
    except Exception:
        return
    try:
        status = darksubs_filename_fallback_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'darksubs_filename_fallback_patcher: applied '
                'hash-filename fallback', level='INFO')
        elif status in ('unmatched', 'write_failed', 'read_failed'):
            kodi_utils.log(
                'darksubs_filename_fallback_patcher: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'darksubs_filename_fallback_patcher failed: '
                '{0}'.format(e), level='WARNING')
        except Exception:
            pass


def _maybe_patch_skin_dialog_subtitles():
    """Self-healing patch of the ACTIVE skin's DialogSubtitles.xml
    so the subtitle-picker dialog HEADER prefers our window property
    `subs.player_filename` (set by POV's source picker AND/OR our
    own SubsFilenamePublisher player monitor) over the built-in
    `Player.Filename`. Without this, the header shows the UUID
    basename of TorBox CDN URLs even when our property is set --
    because Kodi's DialogSubtitles XML resolves Player.Filename
    directly from the player URL, not from any addon-settable
    state. Patching the skin's XML makes the header read our
    property first.

    This patcher auto-detects the active skin via xbmc.getSkinDir()
    and works against FENtastic, Arctic Zephyr (any variant),
    Estuary, Aeon Nox -- any skin whose DialogSubtitles.xml has a
    `<control type="label">…$INFO[Player.Filename]…</control>`
    element. Users who chose a non-FENtastic skin previously saw
    the UUID gibberish in the header even on the latest addon
    version because the old FENtastic-only patcher returned
    'no_file' for them.

    Self-migrates the old FENtastic-specific v1 inject so users
    upgrading don't end up with stale v1 dual-control blocks
    sitting next to the new v2 ones."""
    try:
        from resources.lib import skin_dialog_subtitles_patcher, \
            kodi_utils
    except Exception:
        return
    try:
        status = skin_dialog_subtitles_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'skin_dialog_subtitles_patcher: dialog header now '
                'prefers subs.player_filename', level='INFO')
        elif status in ('unmatched', 'write_failed', 'read_failed',
                        'no_target'):
            kodi_utils.log(
                'skin_dialog_subtitles_patcher: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'skin_dialog_subtitles_patcher failed: '
                '{0}'.format(e), level='WARNING')
        except Exception:
            pass


def _maybe_patch_nox_change_source():
    """Add a 'החלף מקור' (change source) button to the NOX skin's player OSD
    (skin.povil.nox/xml/VideoOSD.xml). NOX shipped without one, so a bad source
    mid-playback left users stuck with no way to pick another. No-op when NOX
    isn't installed. Marker-gated + XML-parse-checked so it can never corrupt
    the skin / black-screen the player."""
    try:
        from resources.lib import nox_change_source_patcher, kodi_utils
    except Exception:
        return
    try:
        status = nox_change_source_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'nox_change_source_patcher: change-source button added to '
                'NOX OSD', level='INFO')
            _maybe_reload_nox_skin()
        elif status in ('unmatched', 'parse_failed', 'write_failed',
                        'read_failed'):
            kodi_utils.log('nox_change_source_patcher: ' + status,
                           level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log('nox_change_source_patcher failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _maybe_reload_nox_skin():
    """Skin XML is read at skin load, so a freshly-applied NOX OSD patch only
    shows after a reload. Reload once -- but only when NOX is the active skin
    AND the wizard's quick-update notice isn't on screen (reloading would close
    it). Otherwise the button simply appears on the next Kodi restart."""
    try:
        import xbmc
        import xbmcaddon
    except Exception:
        return
    try:
        if xbmc.getSkinDir() != 'skin.povil.nox':
            return
        try:
            wiz = xbmcaddon.Addon('plugin.program.kodipovilwizard')
            if (wiz.getSetting('quick_update_notedismiss') == 'false'
                    and wiz.getSetting('quick_update_noteid')):
                return
        except Exception:
            pass
        xbmc.executebuiltin('ReloadSkin()')
    except Exception:
        pass


def _maybe_patch_estuary_change_source():
    """Add a 'החלף מקור' (change source) button to the Estuary skin's player OSD
    (skin.estuary/xml/VideoOSD.xml). The build's Estuary shipped without one
    (only a stale commented-out attempt that used the wrong POV param), so a bad
    source mid-playback left users stuck. No-op when Estuary isn't installed.
    Marker-gated + XML-parse-checked so it can never corrupt the skin / black-
    screen the player."""
    try:
        from resources.lib import estuary_change_source_patcher, kodi_utils
    except Exception:
        return
    try:
        status = estuary_change_source_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'estuary_change_source_patcher: change-source button added to '
                'Estuary OSD', level='INFO')
            _maybe_reload_estuary_skin()
        elif status in ('unmatched', 'parse_failed', 'write_failed',
                        'read_failed'):
            kodi_utils.log('estuary_change_source_patcher: ' + status,
                           level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'estuary_change_source_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_reload_estuary_skin():
    """Reload once so a freshly-applied Estuary OSD patch shows this session --
    only when Estuary is the active skin AND the wizard's quick-update notice
    isn't on screen. Otherwise the button appears on the next Kodi restart."""
    try:
        import xbmc
        import xbmcaddon
    except Exception:
        return
    try:
        if xbmc.getSkinDir() != 'skin.estuary':
            return
        try:
            wiz = xbmcaddon.Addon('plugin.program.kodipovilwizard')
            if (wiz.getSetting('quick_update_notedismiss') == 'false'
                    and wiz.getSetting('quick_update_noteid')):
                return
        except Exception:
            pass
        xbmc.executebuiltin('ReloadSkin()')
    except Exception:
        pass


def _maybe_patch_darksubs_picker_label():
    """Self-healing patch of DarkSubs's custom picker dialog XML so
    long release-name labels in each row marquee-scroll horizontally
    instead of getting cut off mid-wrap. Idempotent via marker; only
    touches `<control type="label">` blocks that reference
    ListItem.Label / ListItem.Label2 (the per-row provider + release
    name).

    NOTE (post-#157 retrospective): DarkSubs ships no
    resources/skins/ folder at all -- the picker is a pyxbmct dialog
    built in Python (resources/modules/sub_window.py). This patcher
    is kept around for self-healing (no-op when there's no skins
    folder) and to cover any future DarkSubs version that does add
    skin XMLs. The actual fix for the wrap-clip issue lives in
    _maybe_patch_darksubs_picker_height() below."""
    try:
        from resources.lib import darksubs_picker_label_patcher, \
            kodi_utils
    except Exception:
        return
    try:
        status = darksubs_picker_label_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'darksubs_picker_label_patcher: row labels now '
                'marquee-scroll instead of truncating',
                level='INFO')
        elif status in ('no_darksubs', 'already_patched',
                        'nothing_to_patch'):
            pass  # quiet steady-state
        else:
            kodi_utils.log(
                'darksubs_picker_label_patcher: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'darksubs_picker_label_patcher failed: '
                '{0}'.format(e), level='WARNING')
        except Exception:
            pass


def _maybe_patch_skin_dialog_subtitles_rows():
    """Self-healing patch of the ACTIVE skin's DialogSubtitles.xml
    so the per-row layout in the subtitle picker is tall enough for
    long release names to display both wrapped lines without
    clipping. Idempotent (marker-gated). Bumps itemlayout +
    focusedlayout heights by +40 px and any inner textbox control
    referencing $INFO[ListItem.Label2] by the same."""
    try:
        from resources.lib import (
            skin_dialog_subtitles_row_patcher, kodi_utils)
    except Exception:
        return
    try:
        status = skin_dialog_subtitles_row_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'skin_dialog_subtitles_row_patcher: row height '
                'bumped so wrapped release names display fully',
                level='INFO')
        elif status in ('no_skin', 'no_file', 'no_target',
                        'already_patched'):
            pass  # quiet steady-state
        else:
            kodi_utils.log(
                'skin_dialog_subtitles_row_patcher: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'skin_dialog_subtitles_row_patcher failed: '
                '{0}'.format(e), level='WARNING')
        except Exception:
            pass


def _maybe_heal_wizard():
    """One-shot recovery for users stuck on a pre-0.1.10 wizard.
    The wizard's quick_update extract.all silently skips the wizard's
    own files, so wizard updates shipped via quickfix never reached
    disk. Users who already received the broken quick_update (PR #161
    AF3 ship + PR #162 wizard-bundle ship) are stranded on the old
    wizard.py. This rides the AI subs quickfix path (different addon
    id, not skipped), detects the stuck wizard via a sentinel check,
    downloads the latest wizard zip from GitHub, and writes it over
    the installed wizard's addon dir. Toasts the user to restart.
    Self-disarms via a marker once the installed wizard.py is on
    0.1.10+ -- after that the normal quick_update flow takes over."""
    try:
        from resources.lib import wizard_self_healer, kodi_utils
    except Exception:
        return
    try:
        status = wizard_self_healer.ensure_healed()
        # v3: always log the return code (was 'quiet steady-state'
        # in v2, which made remote diagnosis impossible -- a real
        # user log showed zero healer traces and we had to deduce
        # 'no_wizard' from absence-of-logs alone).
        kodi_utils.log(
            'wizard_self_healer status: ' + status,
            level=('WARNING' if status in (
                'no_staged_zip', 'bad_zip', 'write_failed') else 'INFO'),
        )
    except Exception as e:
        try:
            kodi_utils.log(
                'wizard_self_healer failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_af3_dialog_subtitles():
    """Self-healing patch of Arctic Fuse 3's Dialog_DialogSubtitles.xml
    so the subtitle picker dialog HEADER prefers our window property
    `subs.player_filename` over the built-in `Player.FileName`. AF3's
    structure differs from FENtastic/Estuary (the layout lives in a
    secondary file referenced by `<include>DialogSubtitles</include>`,
    not in DialogSubtitles.xml directly), so the generic header
    patcher bails with 'no_target'. This dedicated AF3 patcher injects
    a `<variable>` with conditional fallback semantics + swaps the
    param-label to reference it. No-op if AF3 isn't installed."""
    try:
        from resources.lib import (
            af3_dialog_subtitles_patcher, kodi_utils)
    except Exception:
        return
    try:
        status = af3_dialog_subtitles_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'af3_dialog_subtitles_patcher: header label now '
                'prefers subs.player_filename with fallback to '
                'Player.FileName', level='INFO')
        elif status in ('no_af3', 'no_file', 'already_patched'):
            pass  # quiet steady-state -- AF3 not installed yet or
                  # patch already in place
        else:
            kodi_utils.log(
                'af3_dialog_subtitles_patcher: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'af3_dialog_subtitles_patcher failed: '
                '{0}'.format(e), level='WARNING')
        except Exception:
            pass


def _maybe_patch_all_subs_samefile():
    """Self-healing patch of service.subtitles.all_subs_plus/service.py
    so that setLanguageSettings() can survive shutil.SameFileError on
    Windows (NTFS junction / hardlink). The unpatched AllSubs raises
    SameFileError at module-load time, which kills autosub.py before
    Kodi even shows the home screen -- user-visible Python error every
    boot, AllSubs functionality fully broken. We wrap each of the six
    shutil.copy(src, dst) call sites inside setLanguageSettings in a
    try/except shutil.SameFileError that silently absorbs the error
    (intended behaviour: the destination is byte-identical to the
    source already, so the copy is a no-op). Marker-gated, idempotent,
    no-op on platforms where AllSubs isn't installed."""
    try:
        from resources.lib import (
            all_subs_samefile_patcher, kodi_utils)
    except Exception:
        return
    try:
        status = all_subs_samefile_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'all_subs_samefile_patcher: setLanguageSettings '
                'now absorbs SameFileError on Windows', level='INFO')
        elif status in ('no_addon', 'no_file', 'already_patched'):
            pass  # quiet steady-state -- AllSubs not installed or
                  # patch already in place
        else:
            kodi_utils.log(
                'all_subs_samefile_patcher: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'all_subs_samefile_patcher failed: '
                '{0}'.format(e), level='WARNING')
        except Exception:
            pass


def _maybe_patch_af3_home():
    """Seed Arctic Fuse 3 with POV/FENtastic-style home widgets.

    AF3's default home widgets are Kodi-library smart playlists, which
    are empty in this streaming build and show "No Results" on fresh
    installs. This writes script.skinvariables' per-user node JSON so
    the AF3 home screen opens directly into POV rows: new movies,
    trending shows, continue watching, personal lists, genres, AI
    settings, and working wizard/power-menu actions."""
    try:
        from resources.lib import af3_home_patcher, kodi_utils
    except Exception:
        return
    try:
        status = af3_home_patcher.ensure_patched()
        if status in ('patched', 'patched_rebuilt'):
            kodi_utils.log(
                'af3_home_patcher: seeded POV home nodes ({0})'
                .format(status),
                level='INFO')
        elif status in ('no_af3', 'already_patched'):
            pass
        else:
            kodi_utils.log('af3_home_patcher: ' + status,
                           level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log('af3_home_patcher failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _maybe_patch_darksubs_picker_height():
    """Self-healing patch of DarkSubs's sub_window.py so the picker's
    per-row height is doubled. The default pyxbmct.List _itemHeight
    of 27 px fits only one line; long release names wrap to a second
    line that the row clips, hiding the release group at the end
    (the part the user actually needs to identify the file). 60 px
    fits both lines cleanly."""
    try:
        from resources.lib import darksubs_picker_height_patcher, \
            kodi_utils
    except Exception:
        return
    try:
        status = darksubs_picker_height_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'darksubs_picker_height_patcher: row height bumped '
                'so wrapped release names display fully',
                level='INFO')
        elif status in ('no_darksubs', 'already_patched'):
            pass  # quiet steady-state
        else:
            kodi_utils.log(
                'darksubs_picker_height_patcher: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'darksubs_picker_height_patcher failed: '
                '{0}'.format(e), level='WARNING')
        except Exception:
            pass


def _maybe_purge_temp_once():
    try:
        from resources.lib import local_subs, kodi_utils
    except Exception:
        return
    try:
        seen = kodi_utils.get_setting('_temp_purge_done', '')
        if seen == TEMP_PURGE_VERSION:
            return
        n = local_subs.purge_temp_subs()
        kodi_utils.set_setting('_temp_purge_done', TEMP_PURGE_VERSION)
        kodi_utils.log(
            'One-shot temp purge: removed {0} .srt files'.format(n),
            level='INFO')
    except Exception as e:
        try:
            kodi_utils.log('Temp purge failed: {0}'.format(e),
                           level='ERROR')
        except Exception:
            pass


def _maybe_show_af3_first_launch_dialog():
    """One-shot: if Arctic Fuse 3 is the active skin and we've never
    shown the first-launch dialog before, prompt the user to connect
    Trakt + TMDb via POV's Connect Services. AF3 needs both to
    populate its hubs; without them the home screen is empty and
    new users assume the skin is broken.

    Runs once per profile; the marker lives in our addon's settings.
    Has its own internal "remind me later" path that intentionally
    doesn't set the marker, so the user gets re-prompted next launch.

    Skin-gated -- a no-op on FENtastic / Estuary / any other skin --
    so existing-build users aren't disturbed when this addon ships
    via quickfix."""
    try:
        from resources.lib import af3_first_launch, kodi_utils
    except Exception:
        return
    try:
        status = af3_first_launch.maybe_show()
        if status not in ('not_af3', 'already_done'):
            try:
                kodi_utils.log(
                    'af3_first_launch dialog status: {0}'.format(status),
                    level='INFO')
            except Exception:
                pass
    except Exception as e:
        try:
            kodi_utils.log(
                'af3_first_launch failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_show_debrid_status():
    """Build-only premium debrid subscription toasts on Kodi startup.

    This intentionally lives outside POV so it applies consistently in
    Estuary, FENtastic and Arctic Fuse 3, while the build_mode gate keeps
    standalone AI-subtitle installs from changing user navigation/state.
    """
    try:
        from resources.lib import debrid_status_notifier, kodi_utils
    except Exception:
        return
    try:
        status = debrid_status_notifier.maybe_notify()
        if status.startswith('shown:'):
            kodi_utils.log('Debrid startup subscription status shown: {0}'
                           .format(status.split(':', 1)[1]),
                           level='INFO')
        elif status not in ('no_pov', 'nothing_to_show', 'already_shown'):
            kodi_utils.log('Debrid startup status: {0}'.format(status),
                           level='INFO')
    except Exception as e:
        try:
            kodi_utils.log('Debrid startup status failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _maybe_patch_pov_debrid_status():
    """Build-only: make POV's premium-expiry settings suitable for
    our Hebrew/icon-aware startup toasts and prevent duplicate generic
    POV expiry notifications."""
    try:
        from resources.lib import pov_debrid_status_patcher, kodi_utils
    except Exception:
        return
    try:
        status = pov_debrid_status_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log('POV debrid status settings patched',
                           level='INFO')
    except Exception as e:
        try:
            kodi_utils.log('POV debrid status patch failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _maybe_default_fast_first_chunk():
    """One-shot: flip `fast_first_chunk` from the old default-off to
    the new default-on for existing users. Gated by a marker so it
    fires once per install; if the user later turns it off manually
    we don't re-flip on subsequent startups."""
    try:
        from resources.lib import kodi_utils
    except Exception:
        return
    try:
        if kodi_utils.get_setting(
                '_fast_first_chunk_default_v2', '') == '1':
            return
        # Only flip users currently on the old default 'false' --
        # leaves any explicit 'true' alone.
        if kodi_utils.get_setting('fast_first_chunk',
                                  'false') == 'false':
            kodi_utils.set_setting('fast_first_chunk', 'true')
            kodi_utils.log(
                'fast_first_chunk flipped to True (default v2 '
                'migration)', level='INFO')
        kodi_utils.set_setting('_fast_first_chunk_default_v2', '1')
    except Exception as e:
        try:
            kodi_utils.log(
                'fast_first_chunk migration failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_default_pool_on():
    """One-shot: turn the community pool ON (both pull and share) for existing
    users who are still on the old default-off. Gated by a marker so it fires
    once per install; if the user later turns either toggle off manually we
    don't re-enable on subsequent startups. New installs get it on via the
    settings.xml defaults; this covers everyone who installed before the
    default flip."""
    try:
        from resources.lib import kodi_utils
    except Exception:
        return
    try:
        if kodi_utils.get_setting('_pool_default_on_v1', '') == '1':
            return
        # Only flip toggles still on the old default 'false'; leave an explicit
        # choice (already 'true') alone.
        for key in ('pool_use', 'pool_share'):
            if kodi_utils.get_setting(key, 'false') == 'false':
                kodi_utils.set_setting(key, 'true')
        kodi_utils.set_setting('_pool_default_on_v1', '1')
        kodi_utils.log('community pool enabled by default (migration v1)',
                       level='INFO')
    except Exception as e:
        try:
            kodi_utils.log('pool default-on migration failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _maybe_default_remember_source():
    """One-shot: turn "remember picked source" ON for existing users still on
    the old default-off (the feature is now on by default for everyone). Flips
    a stored 'false' to 'true' once, marker-gated, so a later manual opt-out
    sticks. New installs get it via the settings.xml default. Runs BEFORE the
    POV patcher so the patcher sees the setting on and reloads POV this session."""
    try:
        from resources.lib import kodi_utils
    except Exception:
        return
    try:
        if kodi_utils.get_setting('_remember_source_default_v1', '') == '1':
            return
        if kodi_utils.get_setting('remember_source', 'false') == 'false':
            kodi_utils.set_setting('remember_source', 'true')
        kodi_utils.set_setting('_remember_source_default_v1', '1')
        kodi_utils.log('remember_source enabled by default (migration v1)',
                       level='INFO')
    except Exception as e:
        try:
            kodi_utils.log('remember_source default migration failed: {0}'
                           .format(e), level='WARNING')
        except Exception:
            pass


def _ensure_darksubs_enabled():
    """Sync DarkSubs (service.subtitles.All_Subs) enabled-state to the inverse
    of the built-in engine toggle (Phase C):

      * use_builtin_engine OFF (default) -> ensure DarkSubs ENABLED. The whole
        subtitle flow + AI-translation hook depends on it, so an installed-but-
        disabled DarkSubs means no subtitles at all -- recover it.
      * use_builtin_engine ON -> ensure DarkSubs DISABLED, so only MoranSubs
        runs (no double search, no competing results -- this is what makes the
        engine as fast as DarkSubs is on its own). MoranSubs then provides the
        sourcing, the auto-on-play, and the AI translation itself.

    Cheap, idempotent, runs early every startup; only writes on a mismatch."""
    if xbmc is None:
        return
    try:
        from resources.lib import kodi_utils
        engine_on = kodi_utils.get_bool('use_builtin_engine', False)
    except Exception:
        engine_on = False
    desired = not engine_on
    try:
        import json as _json
        get = _json.dumps({
            'jsonrpc': '2.0', 'id': 1,
            'method': 'Addons.GetAddonDetails',
            'params': {'addonid': 'service.subtitles.All_Subs',
                       'properties': ['enabled']},
        })
        data = _json.loads(xbmc.executeJSONRPC(get) or '{}')
        addon = (data.get('result') or {}).get('addon') or {}
        if 'enabled' not in addon:
            return  # not installed / unknown -> leave alone
        if bool(addon.get('enabled')) == desired:
            return  # already in the desired state
        en = _json.dumps({
            'jsonrpc': '2.0', 'id': 1,
            'method': 'Addons.SetAddonEnabled',
            'params': {'addonid': 'service.subtitles.All_Subs',
                       'enabled': desired},
        })
        xbmc.executeJSONRPC(en)
        xbmc.log('[{0}] DarkSubs set enabled={1} (engine_on={2})'.format(
            ADDON_ID, desired, engine_on), level=xbmc.LOGINFO)
    except Exception:
        pass


def _maybe_set_default_subtitle_service():
    """When the engine is on, make MoranSubs the default subtitle service for
    movies + TV, so Kodi auto-runs it and pre-selects it when the subtitle
    dialog opens (the services list order itself is fixed by Kodi, but the
    default is what opens/searches first). Only writes on a mismatch; only
    when the engine is on (we don't override the user's choice otherwise)."""
    if xbmc is None:
        return
    try:
        from resources.lib import kodi_utils
        if not kodi_utils.get_bool('use_builtin_engine', False):
            return
    except Exception:
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
        xbmc.log('[{0}] set as default subtitle service (engine on)'
                 .format(ADDON_ID), level=xbmc.LOGINFO)
    except Exception:
        pass


def _ensure_pov_enabled():
    """Recover plugin.video.pov if it was left disabled -- e.g. our pov_reload
    cycle (disable+enable to re-import the patched sources.py after enabling
    remember_source) lost the re-enable race on a slow box, or any other reason.
    POV is THE content addon: if it's installed but disabled, every home row and
    every "My Movies/My Shows" tile is empty and nothing plays -- on ALL skins.
    pov_reload retries within its own cycle, but if that ultimately failed there
    was previously nothing to bring POV back on a later boot. This is that net:
    cheap, idempotent, runs early every startup, only acts when POV is installed
    AND currently disabled."""
    if xbmc is None:
        return
    try:
        import json as _json
        get = _json.dumps({
            'jsonrpc': '2.0', 'id': 1,
            'method': 'Addons.GetAddonDetails',
            'params': {'addonid': 'plugin.video.pov',
                       'properties': ['enabled']},
        })
        data = _json.loads(xbmc.executeJSONRPC(get) or '{}')
        addon = (data.get('result') or {}).get('addon') or {}
        if 'enabled' not in addon:
            return  # not installed / unknown -> leave alone
        if addon.get('enabled'):
            return  # already enabled -> nothing to do
        en = _json.dumps({
            'jsonrpc': '2.0', 'id': 1,
            'method': 'Addons.SetAddonEnabled',
            'params': {'addonid': 'plugin.video.pov', 'enabled': True},
        })
        xbmc.executeJSONRPC(en)
        xbmc.log('[' + ADDON_ID + '] re-enabled POV (it was disabled)',
                 level=xbmc.LOGINFO)
    except Exception:
        pass


def _maybe_default_fentastic_player():
    """Heal the FENtastic player choice ONLY when it's unset.

    The build ships a default __chooseplayer=__netflixplayer so a fresh install
    never lands on a "player with nothing" (an empty string matches no player
    include in the skin -> no controls). But the quickfix must NOT keep
    re-asserting that default, or it reverts the user's manual player choice on
    every update (reported: "I switch to the simple player and the next update
    puts me back on Netflix"). So we no longer ship the skin settings file in
    the quickfix; instead we set a valid default HERE only when the value is
    empty -- and never touch a value the user picked. FENtastic-only (the
    setting is a FENtastic skin string; other skins handle players themselves).
    Uses the skin API (not a file write) so it can't fight Kodi's in-memory
    skin-settings cache."""
    if xbmc is None:
        return
    try:
        if xbmc.getSkinDir() != 'skin.fentastic':
            return
        cur = (xbmc.getInfoLabel('Skin.String(__chooseplayer)') or '').strip()
        if cur:
            return  # user (or a prior default) already set one -> respect it
        xbmc.executebuiltin('Skin.SetString(__chooseplayer,__netflixplayer)')
        xbmc.log('[' + ADDON_ID + '] set default __chooseplayer (was empty)',
                 level=xbmc.LOGINFO)
    except Exception:
        pass


def _maybe_default_pov_autoplay():
    """One-shot: set POV "Automatically Resume Playback" to Always, so picking
    up an in-progress item resumes from where you stopped (no resume/start-over
    prompt). Marker-gated; only flips settings still on POV's old default, so a
    later manual change sticks. Does NOT enable Auto Play -- the source/servers
    dialog must still appear so the user chooses the source. Touches ONLY the
    two auto_resume settings; never Trakt/debrid/anything else."""
    if xbmc is None:
        return
    try:
        from resources.lib import kodi_utils
        import xbmcaddon
    except Exception:
        return
    try:
        if kodi_utils.get_setting('_pov_autoplay_default_v1', '') == '1':
            return
        try:
            pov = xbmcaddon.Addon('plugin.video.pov')
        except Exception:
            return  # POV not installed (standalone AI install) -> retry later
        def _flip(key, oldval, newval):
            try:
                if (pov.getSetting(key) or '').strip().lower() == oldval:
                    pov.setSetting(key, newval)
            except Exception:
                pass
        # Automatically Resume Playback: 0=Never, 1=Always, 2=Autoplay Only.
        # NOTE: we deliberately do NOT touch auto_play_* -- the source dialog
        # must keep showing so the user picks the source themselves.
        _flip('auto_resume_movie', '0', '1')
        _flip('auto_resume_episode', '0', '1')
        kodi_utils.set_setting('_pov_autoplay_default_v1', '1')
        kodi_utils.log('POV always-resume default applied (v1)', level='INFO')
    except Exception as e:
        try:
            kodi_utils.log('POV resume default migration failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _maybe_revert_pov_autoplay():
    """One-shot fix: an earlier build (0.2.158) wrongly turned POV Auto Play ON
    by default, which skipped the source/servers dialog even on first watch.
    Turn it back OFF so the dialog always shows. Marker-gated; sets the value
    back to POV's own default (false). Users who genuinely want Auto Play can
    re-enable it in POV settings."""
    if xbmc is None:
        return
    try:
        from resources.lib import kodi_utils
        import xbmcaddon
    except Exception:
        return
    try:
        if kodi_utils.get_setting('_pov_autoplay_revert_v2', '') == '1':
            return
        try:
            pov = xbmcaddon.Addon('plugin.video.pov')
        except Exception:
            return
        for key in ('auto_play_movie', 'auto_play_episode'):
            try:
                if (pov.getSetting(key) or '').strip().lower() == 'true':
                    pov.setSetting(key, 'false')
            except Exception:
                pass
        kodi_utils.set_setting('_pov_autoplay_revert_v2', '1')
        kodi_utils.log('POV Auto Play reverted to off (v2)', level='INFO')
    except Exception as e:
        try:
            kodi_utils.log('POV autoplay revert failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def main():
    if xbmc is None:
        return

    # First-run handshake: if a quick_update patch dropped the
    # disable marker, opt the user back out so they can review
    # before activating. The marker is consumed on first read so
    # subsequent enables behave normally.
    if _check_first_run_marker():
        return

    # Initial prune.
    _prune_once()
    _prune_source_memory_once()

    build_mode = _is_kodi_pov_il_build()
    if build_mode:
        _ensure_build_marker()
    else:
        _maybe_cleanup_standalone_build_patches()

    # Recover users stuck on a pre-0.1.10 wizard (see function
    # docstring for the extract.all self-skip bug). Runs before
    # the other patchers because if the heal succeeds the user
    # will restart Kodi anyway, and we don't want to spend cycles
    # patching things they'll re-run on the next boot.
    _maybe_heal_wizard()

    # Enable "remember picked source" by default (one-shot) BEFORE the POV
    # patcher runs, so the patcher sees it on and reloads POV this session.
    _maybe_default_remember_source()

    # Recover DarkSubs first if a previous reload cycle left it disabled after
    # a quick update -- otherwise no subtitles and no AI translation fire at
    # all. Runs before the patchers (which patch its files on disk regardless).
    _ensure_darksubs_enabled()

    # When the engine is on, make MoranSubs the default subtitle service so it
    # opens/searches first in the dialog.
    _maybe_set_default_subtitle_service()

    # Same safety net for POV: our pov_reload cycle (for remember_source) could
    # have left POV disabled on a slow box, which empties every home row + tile
    # and breaks playback on ALL skins. Bring it back if it's installed and off.
    _ensure_pov_enabled()

    # Heal the FENtastic player choice only if it's empty (prevents the
    # "player with nothing" bug) -- never overrides a value the user picked.
    # The quickfix no longer ships the skin settings file, so this is what
    # guarantees a valid default without reverting manual choices on update.
    _maybe_default_fentastic_player()

    # Self-healing DarkSubs hook injection. Runs every startup so
    # if upstream DarkSubs updates and overwrites our hook, it
    # comes back automatically on next Kodi launch.
    _maybe_patch_darksubs()

    # Companion patch: extends download_sub's elif so the hook above
    # ALSO gets a chance to run when DarkSubs's auto_translate
    # setting is OFF (user manually picks a non-Hebrew sub). Without
    # this, the v3 hook only ever fires when auto_translate=true.
    _maybe_patch_darksubs_download_sub()

    # OpenSubtitles provider/key-list fix. Runs for standalone AI-addon
    # installs too, but touches only DarkSubs's OpenSubtitles source file
    # and local key fallback.
    _maybe_patch_darksubs_opensubtitles()

    # Push embedded ('[LOC]') subtitle entries to the bottom of their
    # language group. They carry a hard-coded 101% sync that otherwise
    # floats them to the top, and they can't be AI-translated (DarkSubs
    # short-circuits embedded picks before our hook runs) -- so we want
    # the external, translatable English source to be the first pick.
    _maybe_patch_darksubs_embedded_demote()
    # ROOT-CAUSE fix: autosub.py inserts embedded English right after the
    # Hebrew group (above real English). Make it insert at the end.
    _maybe_patch_darksubs_embedded_insert()
    # Belt-and-braces: also demote at the picker dialog itself, the last
    # point before display, so embedded English can't slip back to the
    # top regardless of engine ordering.
    _maybe_patch_darksubs_subwindow_demote()

    # Now that the hook injection has had its shot, run a structural
    # check end-to-end and pop a toast if something is broken (e.g.
    # DarkSubs signature changed, engine.py not writable on CoreELEC,
    # API key missing). Without this, hook failures cascade silently
    # into "AI subs not working" with no signal to the user. Only
    # toasts once per failure-class. Skipped when the built-in engine is
    # on (DarkSubs is intentionally disabled then -- no false alarm).
    try:
        from resources.lib import kodi_utils as _ku
        _engine_on = _ku.get_bool('use_builtin_engine', False)
    except Exception:
        _engine_on = False
    if not _engine_on:
        _maybe_surface_darksubs_status()

    # Stash POV's picked release name (from the source-select dialog)
    # in a Window(10000) property before play() so DarkSubs can use
    # it as the filename for subtitle matching. Solves both the
    # TorBox UUID-as-title problem AND raises the % match across all
    # debrid services to ~85-95% (the full release name has the
    # encoder/source/group tokens that subtitle releases carry).
    _maybe_patch_pov_source_name()

    # PHASE 1 capture for "remember the source the user picked" (gated by the
    # remember_source setting, OFF by default; compile-checked so it can't
    # break POV playback).
    _maybe_patch_pov_remember_source()

    # Hebrew-subtitle match % under each source in POV's source-results window
    # (skin-agnostic: prepends to a property shown in every layout). Gated by
    # show_subtitle_match (default on); compile-checked so it can't break POV.
    _maybe_patch_pov_subtitle_match()

    # Pre-warm the built-in sources engine (only when the user enabled it) so
    # the first subtitle search doesn't pay the heavy import cost inline.
    _maybe_prewarm_engine()

    # Self-healing DarkSubs get_playing_filename() patch. Prefers
    # the picked release name set by the pov_source_name_patcher
    # above. Falls back to synthesising a release-name-style filename
    # from VideoPlayer info-labels when no POV property is available
    # AND the basename looks like an opaque hash (TorBox CDN behaviour).
    _maybe_patch_darksubs_filename()

    # Fix the subtitle-picker dialog HEADER (rendered by Kodi from
    # the skin's DialogSubtitles.xml) to prefer our subs.player_filename
    # property over the built-in Player.Filename. Without this, even
    # if our other patchers set the property, the dialog title still
    # shows the URL basename / UUID.
    _maybe_patch_skin_dialog_subtitles()

    # Patch DarkSubs's custom picker XML so long release-name labels
    # in each row marquee-scroll instead of getting clipped mid-wrap.
    # (No-op when DarkSubs has no skins folder, which it doesn't on
    # current builds -- the real fix for that case is the height
    # patcher below.)
    _maybe_patch_darksubs_picker_label()

    # Bump DarkSubs's pyxbmct picker row height so wrapped release
    # names display fully. (For the alternate flow where DarkSubs's
    # standalone MySubs dialog is opened directly. Most users won't
    # see this dialog -- it's a Python-built pyxbmct.List inside
    # DarkSubs's sub_window.py.)
    _maybe_patch_darksubs_picker_height()

    # The picker users actually see when they hit "Choose subtitles"
    # is Kodi's NATIVE DialogSubtitles, rendered by the active skin
    # (FENtastic in this build). DarkSubs is just one of the listed
    # services. The row layout (height, label/textbox dimensions)
    # is in skin.fentastic/xml/DialogSubtitles.xml. We bump
    # itemlayout/focusedlayout heights (and the inner Label2
    # textbox heights) so two wrapped lines of font12 fit without
    # clipping the bottom of the second line.
    _maybe_patch_skin_dialog_subtitles_rows()

    # Arctic Fuse 3 ships its subtitle dialog layout in a separate
    # file (Dialog_DialogSubtitles.xml) referenced via a named
    # include. The generic skin header patcher above won't find
    # $INFO[Player.FileName] there because it's wrapped in a
    # <param> rather than a <control type="label">. Dedicated AF3
    # patcher handles that file -- skin-gated, no-op when AF3 isn't
    # installed.
    _maybe_patch_af3_dialog_subtitles()

    # Add a "change source" button to the NOX skin's player OSD -- NOX
    # shipped without one, so a bad source mid-playback was a dead end.
    # Skin-gated (no-op unless skin.povil.nox is installed), XML-checked.
    _maybe_patch_nox_change_source()

    # Same for the Estuary skin (skin.estuary) -- it also shipped without a
    # change-source button. Skin-gated, XML-parse-checked.
    _maybe_patch_estuary_change_source()

    # AllSubs Plus crashes at import on Windows when shutil.copy hits a
    # NTFS junction/hardlink (SameFileError). Patch its 6 copy lines in
    # setLanguageSettings to absorb that specific exception so the
    # addon survives to actually serve subtitles.
    _maybe_patch_all_subs_samefile()

    # DarkSubs has reuselanguageinvoker=true and runs autosub.py as a
    # persistent xbmc.service, so editing its .py files on disk does NOT
    # take effect until its interpreter is torn down. If any DarkSubs
    # source patch changed a file this run, cycle the addon (disable+
    # enable) so it re-imports the patched source -- otherwise the
    # embedded-subtitle ordering (and every other DarkSubs source patch)
    # stays stale for the whole session.
    try:
        from resources.lib import darksubs_reload
        darksubs_reload.reload_if_patched()
    except Exception:
        pass

    # Same idea for POV: if we patched its sources.py and the user opted into
    # remember-source, cycle POV (deferred, idle-only) so it re-imports the
    # patched code this session. No-op unless armed above.
    try:
        from resources.lib import pov_reload
        pov_reload.reload_if_patched()
    except Exception:
        pass

    # POV's own "My Services" menu -- THE correct place. Inject
    # Gemini + Wyzie entries here on every startup; idempotent.
    _maybe_patch_pov_services()

    # Safe for standalone installs: this only repoints FENtastic/Estuary's
    # home search button to POV's own search node, so users do not get the
    # English skin-helper search menu. It does not touch favourites, lists,
    # caches, auth state, or skin home widgets.
    _maybe_patch_fentastic_search()

    if build_mode:
        _run_build_startup_repairs()

    # v0.2.9 tried patching FENtastic's notification widget but
    # it broke things; this cleans up the leftover patch on disk
    # for anyone who got that version.
    _maybe_unpatch_fentastic_notification()

    # One-shot RTL punctuation repair of any cached translations
    # that were written before the post-processor caught their
    # specific edge case. Marker-gated so it only runs once.
    _maybe_repair_rtl_cache()

    # One-shot: flip `fast_first_chunk` default from off -> on for
    # existing users on the old default. Marker-gated.
    _maybe_default_fast_first_chunk()

    # One-shot: turn the community pool ON (pull + share) for existing users
    # still on the old default-off. New installs get it via settings.xml
    # defaults. Marker-gated so a later manual opt-out sticks.
    _maybe_default_pool_on()

    # One-shot: enable POV Auto Play + Always-Resume so "Continue Watching" is
    # one click (no source dialog, resumes where you stopped). Marker-gated.
    _maybe_default_pov_autoplay()

    # One-shot fix: undo the 0.2.158 mistake that forced POV Auto Play on
    # (it skipped the source dialog even on first watch). Restores the dialog.
    _maybe_revert_pov_autoplay()

    # One-shot first-launch dialog for Arctic Fuse 3. Skin-gated +
    # marker-gated so it only fires for users who have actually
    # switched to AF3 (via the wizard's Switch Skin dialog or Kodi's
    # own Interface settings) and haven't been prompted before. POV's
    # Connect Services is opened on the user's behalf for the
    # service(s) they pick. Best-effort: this addon doesn't own AF3's
    # OAuth flows -- POV does.
    # Build debrid-status popups are also handled by the startup repair pass.

    # Spin up the SubsFilenamePublisher player monitor. It needs to
    # outlive this function's local scope -- xbmc.Player subclasses
    # only receive callbacks while a strong reference exists. Pinning
    # it to the module is sufficient since `main` runs for the
    # lifetime of the service.
    global _subs_filename_publisher  # noqa: PLW0603
    try:
        from resources.lib import subs_filename_publisher
        _subs_filename_publisher = \
            subs_filename_publisher.SubsFilenamePublisher()
    except Exception as e:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log(
                'SubsFilenamePublisher init failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass

    # Phase C: register the auto-on-play Hebrew listener (gated; only when the
    # built-in engine + autosub are on). The loop below keeps us alive.
    _maybe_start_autosub_player()

    monitor = xbmc.Monitor()
    # 24h between passes. waitForAbort returns True when Kodi is
    # shutting down, so we just need to loop until that fires.
    interval_seconds = 24 * 3600
    while not monitor.abortRequested():
        if monitor.waitForAbort(interval_seconds):
            break
        _prune_once()
        _prune_source_memory_once()


# Kodi loads xbmc.service scripts by executing the module body, not by
# spawning them as `python service.py`, so __name__ is the module name
# here -- the `if __name__ == '__main__':` guard would skip main()
# entirely. Call it directly.
main()
