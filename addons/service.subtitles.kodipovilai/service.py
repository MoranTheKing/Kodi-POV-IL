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
import time

try:
    import xbmc
except ImportError:
    xbmc = None

ADDON_ID = 'service.subtitles.kodipovilai'
FIRST_RUN_MARKER = '.disable_on_first_run'


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
CACHE_RTL_FIX_VERSION = '3'


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
    except Exception as e:
        try:
            kodi_utils.log(
                'build_icons_patcher failed: {0}'.format(e),
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

    # Self-healing DarkSubs hook injection. Runs every startup so
    # if upstream DarkSubs updates and overwrites our hook, it
    # comes back automatically on next Kodi launch.
    _maybe_patch_darksubs()

    # Stash POV's picked release name (from the source-select dialog)
    # in a Window(10000) property before play() so DarkSubs can use
    # it as the filename for subtitle matching. Solves both the
    # TorBox UUID-as-title problem AND raises the % match across all
    # debrid services to ~85-95% (the full release name has the
    # encoder/source/group tokens that subtitle releases carry).
    _maybe_patch_pov_source_name()

    # Self-healing DarkSubs get_playing_filename() patch. Prefers
    # the picked release name set by the pov_source_name_patcher
    # above. Falls back to synthesising a release-name-style filename
    # from VideoPlayer info-labels when no POV property is available
    # AND the basename looks like an opaque hash (TorBox CDN behaviour).
    _maybe_patch_darksubs_filename()

    # Remove the v0.1.5-v0.1.7 misplaced injection into the wizard's
    # login_menu (the right menu was POV's, not the wizard's).
    _maybe_cleanup_wizard()

    # POV's own "My Services" menu -- THE correct place. Inject
    # Gemini + Wyzie entries here on every startup; idempotent.
    _maybe_patch_pov_services()

    # Resilient device-flow auth polling -- wraps POV's RepeatTimer
    # so a single failed poll doesn't silently kill the whole auth
    # thread for Trakt / RD / TorBox / PM / AD.
    _maybe_patch_pov_repeat_timer()

    # Fix the home-screen Favorites tile typo in POV's bundled
    # navigator.db (one-shot, idempotent). See function docstring
    # for the gory details.
    _maybe_fix_pov_favourites_typo()

    # PR #98 context-menu cleanup -- force-sync POV's movies.py /
    # tvshows.py / episodes.py to the canonical versions bundled
    # in this addon so existing-install users get the change via
    # quickfix instead of needing a full build reinstall.
    _maybe_patch_pov_menus()

    # PR #99 personal-area widget -- rewrite the FENtastic widget's
    # two "personal area" lists in POV's navigator.db so they lead
    # with TMDB Favorites; rewrite the widget XML header so it no
    # longer says "(must connect to Trakt)"; migrate the home-screen
    # Trakt-collection tiles in userdata/favourites.xml to TMDB
    # Favorites equivalents. Each one is surgical and only touches
    # rows/lines/files that match the shipped baseline -- user
    # customizations are left alone.
    _maybe_patch_pov_personal_area()
    _maybe_patch_fentastic_widgets()
    # Install the TMDB-branded home-tile icons before the
    # favourites_xml patcher rewrites the thumb paths, otherwise
    # the TMDB tile would briefly point at a missing file.
    _maybe_install_build_icons()
    _maybe_patch_favourites_xml()

    # v0.2.9 tried patching FENtastic's notification widget but
    # it broke things; this cleans up the leftover patch on disk
    # for anyone who got that version.
    _maybe_unpatch_fentastic_notification()

    # One-shot RTL punctuation repair of any cached translations
    # that were written before the post-processor caught their
    # specific edge case. Marker-gated so it only runs once.
    _maybe_repair_rtl_cache()

    monitor = xbmc.Monitor()
    # 24h between passes. waitForAbort returns True when Kodi is
    # shutting down, so we just need to loop until that fires.
    interval_seconds = 24 * 3600
    while not monitor.abortRequested():
        if monitor.waitForAbort(interval_seconds):
            break
        _prune_once()


# Kodi loads xbmc.service scripts by executing the module body, not by
# spawning them as `python service.py`, so __name__ is the module name
# here -- the `if __name__ == '__main__':` guard would skip main()
# entirely. Call it directly.
main()
