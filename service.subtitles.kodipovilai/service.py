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

import json
import os
import sys
import threading
import time

# `json` IS USED, AND WAS NOT IMPORTED. Two nested functions in the SubSync
# delay watch called json.dumps/json.loads with nothing named json in scope --
# a NameError, swallowed by their own `except Exception`, on every call. See
# _start_subsync_delay_watch, and tools/test_no_undefined_names.py, which is
# what found it.

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
# The legacy tile-refresh callback remains in the startup pass, but its
# producer moved to the Wizard. Keep the default explicit so the callback
# cannot raise NameError on every boot.
_TILE_REFRESH_NEEDED = [False]


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

        povil_icons = _translate_path('special://home/media/povil_icons')
        if _safe_exists(os.path.join(povil_icons, 'Connect_Services.png')):
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


REPAIRS_DONE_PROPERTY = 'kodipovil_startup_repairs_done'


_REPAIRS_STARTED = None

# Heavy work that is useful later must not compete with the first home-widget
# wave.  This matters disproportionately on 32-bit Android boxes: two field
# logs measured the subtitle engine's cold import at 13.1s and 19.7s, and the
# full patch-health tree scan at 4.5-13.2s.  Both used to start while the skin
# was opening all of its lists.  A real request still takes the fast path at
# once; only speculative/background work is delayed.
_BACKGROUND_SETTLE_32 = 45.0
_BACKGROUND_SETTLE_OTHER = 15.0


def _background_settle_seconds():
    return (_BACKGROUND_SETTLE_32 if sys.maxsize <= 2 ** 32
            else _BACKGROUND_SETTLE_OTHER)


def _background_ui_busy():
    """Best-effort gate for CPU/disk work that has no user waiting on it."""
    try:
        return bool(xbmc.getCondVisibility('Player.HasMedia')
                    or xbmc.getCondVisibility('Container.IsUpdating')
                    or xbmc.getCondVisibility('System.HasVisibleModalDialog')
                    or xbmc.getCondVisibility('System.HasActiveModalDialog'))
    except Exception:
        return False


def _publish_repairs_state(value):
    """Announce the repair pass to anyone waiting on it.

    The value is this add-on's VERSION, not a bare 'true', and that is the
    whole point. The quick update installs new files and then has to know
    that the patchers have run FROM THE NEW CODE before it drops the other
    add-ons' cached Python interpreters. A boolean cannot tell the difference
    between 'the new service finished' and 'the old service, still running
    from before the update, finished its own pass' -- and acting on the
    second is exactly how a reload lands half-applied.
    """
    try:
        import xbmcgui
        xbmcgui.Window(10000).setProperty(REPAIRS_DONE_PROPERTY, value or '')
    except Exception:
        pass


def _addon_version():
    try:
        import xbmcaddon
        return xbmcaddon.Addon().getAddonInfo('version') or ''
    except Exception:
        return ''


def _without(stamps, skin):
    """The `<skin>=<version>` stamps that are not this skin's, blanks dropped."""
    return [s for s in stamps if s and not s.startswith(skin + '=')]


def _walk_all(roots):
    """os.walk over several roots in turn, skipping the ones that are not
    there. Written out because `break` inside the caller's nested loops has to
    mean "stop scanning entirely", and chaining generators is the only shape
    that keeps that true across two roots."""
    for root in roots:
        if not os.path.isdir(root):
            continue
        for item in os.walk(root):
            yield item


def _other_addon_version(addon_id):
    """Version of SOME OTHER installed add-on, '' if it is not installed.

    Deliberately separate from _addon_version(): that one answers for us, and
    an id-taking overload of it would read at the call site like our own
    version filtered by something.
    """
    try:
        import xbmcaddon
        return xbmcaddon.Addon(addon_id).getAddonInfo('version') or ''
    except Exception:
        return ''


def _report_patcher_health():
    """Schedule the full applied-repair audit after the home has settled.

    RUNS LAST in the tuple below, and that is load-bearing: the worker is only
    scheduled AFTER the pass has finished writing to the host add-ons, so a
    repair that just applied reads as applied. Anywhere earlier and it could
    race a repair the pass had not reached yet.

    Why it exists: the loop at the end of _run_build_startup_repairs calls
    `step()` and DISCARDS the return value, and all 123 step functions return
    None anyway. An anchor that stops matching is not an exception, so it never
    reaches the WARNING branch either -- it is a silent, ordinary-looking boot.
    That is exactly how five repairs died on POV 6.08.14 with nobody the wiser
    for days. patcher_health asks the host add-ons what they actually contain
    instead of trusting any of that.

    The scan walks every Python/XML/JSON file in every patched host. On a fast
    desktop that was sub-second; on two real ARM32 logs it took 4.5-13.2s and
    overlapped the first widget wave. Detection does not need to be synchronous
    with the repair pass. It remains a full scan with the same warnings/report,
    just on an idle daemon after the startup budget. If Kodi exits first, the
    next start schedules it again.
    """
    def _worker():
        try:
            monitor = xbmc.Monitor()
            if monitor.waitForAbort(_background_settle_seconds()):
                return
            # Never steal CPU/disk from playback, a modal, or a list Kodi is
            # visibly resolving. There is no deadline: this is diagnostic and
            # the next quiet interval is strictly better than a stutter now.
            while _background_ui_busy():
                if monitor.waitForAbort(2.0):
                    return
            from resources.lib import patcher_health, kodi_utils
            started = time.time()
            st = patcher_health.run()
            kodi_utils.log(
                'patcher health: {0}; deferred scan took {1:.1f}s'.format(
                    st, time.time() - started))
        except Exception as e:
            try:
                from resources.lib import kodi_utils
                kodi_utils.log(
                    'patcher health check unavailable: {0}'.format(e),
                    level='WARNING')
            except Exception:
                pass

    try:
        threading.Thread(target=_worker, daemon=True).start()
    except Exception:
        pass


def _maybe_repair_addon_settings_integrity():
    """Recover torn source-stack settings before another add-on writes them."""
    try:
        from resources.lib import (addon_settings_integrity, kodi_utils,
                                   source_settings_reload)
    except Exception:
        return
    try:
        # If Kodi was killed inside our prior Umbrella/Coco reconstruction,
        # restore only the add-ons recorded by that cycle before doing any new
        # work. The record is written before the first disable.
        source_settings_reload.heal_interrupted_cycle()
        results = addon_settings_integrity.ensure_integrity()
        repaired = [item for item in results
                    if item.get('status', '').startswith('repaired_')]
        for item in results:
            status = item.get('status', '')
            if status in ('backup_failed', 'write_failed', 'too_large',
                          'healthy_snapshot_failed', 'error'):
                kodi_utils.log(
                    'settings recovery: {0}={1}; file left in place and the '
                    'next start will retry'.format(item.get('addon'), status),
                    level='WARNING')
            elif status == 'changed_before_install':
                kodi_utils.log(
                    'settings recovery: {0} changed while recovery was '
                    'preparing; the newer writer won and was left untouched'
                    .format(item.get('addon')), level='INFO')
        for item in repaired:
            # Counts and booleans only.  A debrid token must never enter kodi.log.
            kodi_utils.log(
                'settings recovery: {0}={1}, recovered {2} setting(s), '
                'account restored={3}'.format(
                    item.get('addon'), item.get('status'),
                    item.get('salvaged', 0),
                    bool(item.get('account_restored'))),
                level='WARNING')

        pov_repaired = any(
            item.get('addon') == 'plugin.video.pov'
            and item.get('status', '').startswith('repaired_')
            for item in results)
        if pov_repaired:
            # Kodi already tried to load the malformed file before this service
            # began, so its CAddon object still holds defaults.  The existing
            # idle-safe cycle makes it re-read the repaired values this session;
            # if the box never becomes quiet, the owed-cycle record retries at
            # the next start, where the file is already healthy.
            try:
                from resources.lib import pov_reload
                pov_reload.note_patched()
            except Exception:
                pass

        # Umbrella and Coco can also have been constructed before this service
        # replaced their malformed file. Reconstruct only a target whose file
        # was repaired, later and behind the same idle gate used by POV.
        source_settings_reload.note_repaired(
            item.get('addon') for item in repaired)

        repaired_ids = set(item.get('addon') for item in repaired)
        synced = addon_settings_integrity.sync_alldebrid_from_account_manager(
            skip_addons=repaired_ids)
        for item in synced:
            if item.get('failed'):
                kodi_utils.log(
                    'Account Manager AllDebrid re-sync did not persist for {0}'
                    .format(item.get('addon')), level='WARNING')
            elif item.get('changed'):
                kodi_utils.log(
                    'Account Manager AllDebrid re-synced to {0}'
                    .format(item.get('addon')), level='INFO')
    except Exception as exc:
        try:
            kodi_utils.log('settings integrity recovery failed: {0}'.format(exc),
                           level='WARNING')
        except Exception:
            pass


def _maybe_optimize_32bit_artwork():
    """Undo only the build's original-size image policy on 32-bit boxes."""
    try:
        from resources.lib import kodi_32bit_artwork, kodi_utils
        status = kodi_32bit_artwork.ensure_optimized()
        if status in ('invalid_xml', 'wrong_root', 'unmatched',
                      'invalid_result', 'write_failed', 'failed'):
            kodi_utils.log(
                '32-bit artwork optimisation needs attention: {0}'.format(
                    status), level='WARNING')
    except Exception as exc:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log(
                '32-bit artwork optimisation unavailable: {0}'.format(exc),
                level='WARNING')
        except Exception:
            pass


def _maybe_repair_addon_autoupdate():
    """Restore Kodi auto-updates for build-owned add-ons pinned by Kodi."""
    try:
        from resources.lib import addon_autoupdate_repair, kodi_utils
        status = addon_autoupdate_repair.ensure_repaired()
        kodi_utils.log('addon_autoupdate_repair: ' + status, level='INFO')
    except Exception as exc:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log('addon_autoupdate_repair failed: {0}'.format(exc),
                           level='WARNING')
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

    # Clear first: a stale value from the PREVIOUS service instance would
    # otherwise satisfy a waiter the moment it looked, before this pass has
    # touched anything.
    _publish_repairs_state('')

    # Stamped so the invoker guard can report how far ahead of POV's own
    # check it actually got. The 19-second margin this ordering relies on was
    # measured on ONE device; this is what turns any future field log into a
    # second measurement instead of an assumption.
    global _REPAIRS_STARTED
    _REPAIRS_STARTED = time.time()

    steps = (
        # BEFORE ANY CROSS-ADDON SETTINGS WRITE.  A torn POV settings.xml makes
        # Kodi return empty/default values and refuse every attempted repair;
        # for source search that looks exactly like a disconnected debrid and
        # ends in "No External Scrapers Enabled" / "No Results".  Recover the
        # document (and Account Manager's canonical AllDebrid token) first.
        _maybe_repair_addon_settings_integrity,
        # BEFORE EVERYTHING, because it is racing a clock we do not control.
        # POV runs its own ReuseLanguageInvokerCheck a few seconds into its
        # service start, and if the setting and addon.xml disagree it throws
        # an English "SETTING/XML mismatch" dialog at the user and offers to
        # reload the profile. They disagree after any POV self-update: POV
        # ships addon.xml with the flag ON, ours is the setting that says OFF,
        # and POV is not in our quickfix at all -- it updates itself from
        # repository.kodifitzwell, so its own addon.xml comes back.
        #
        # Measured on a reporter's device (2026-08-17):
        #     21:00:39.430  our repair pass starts
        #     21:00:59.399  POV's ReuseLanguageInvokerCheck   <- the dialog
        #     21:01:08.934  this guard finally writes, 9.4s too late
        # From ~29 steps in, it lost the race every time. From here it writes
        # around 21:00:39, about 19 seconds ahead of POV's check, so in the
        # common case POV finds the two halves already in agreement. It is a
        # WIDENED MARGIN, not a synchronisation: this pass itself starts after
        # ~35 other calls in main(), one of which (_ensure_pov_enabled) can
        # retry for up to 10 seconds, so a slow enough device can still lose.
        # The guard logs how far ahead it got, so a field log can say whether
        # the margin holds rather than leaving it assumed.
        #
        # WHICH DIRECTION IT WRITES IS NO LONGER FIXED, and this comment used
        # to say the opposite -- "it can only ever turn the flag OFF" -- which
        # was true until 0.2.507 gave the direction to the
        # `pov_fast_navigation` setting. It is still OFF for anyone who has
        # not deliberately turned that on, and OFF is still the fix for the
        # Arctic Fuse 3 native crash. What running it EARLIER buys is the same
        # either way: it settles both halves before POV's own check looks at
        # them, so POV never shows its mismatch dialog. Do not move it down on
        # the strength of the old sentence.
        _maybe_patch_pov_language_invoker,
        # Cheap XML migration. It touches only the build's exact 9999 value,
        # keeps every cached thumbnail, and affects Kodi after its next start.
        _maybe_optimize_32bit_artwork,
        _maybe_patch_idanplus_channels,
        _maybe_patch_pov_hebrew_genres,
        _maybe_patch_pov_hebrew_ui,
        _maybe_patch_mdblist_reauth,
        _maybe_seed_pov_seasons_view,
        # AF3's compact 32-bit rows read these local shortcut folders. Seed or
        # upgrade them before AF3 exposes the rows, so a fresh profile cannot
        # race the skin and momentarily render an empty personal/network/genre
        # shelf. These are small local SQLite writes/checks, never web calls.
        _maybe_patch_af3_home,
        _maybe_quiet_update_nags,
        _maybe_patch_pov_widget_crash_guard,
        _maybe_patch_umbrella_language,
        _maybe_patch_skin_watched_poster,
        _maybe_add_tonight_entry,
        _maybe_seed_recent_updates_tile,
        _maybe_fix_idanplus_youtube_id,
        _maybe_refresh_shared_sdh,
        _maybe_show_af3_first_launch_dialog,
        _maybe_repair_addon_autoupdate,
        _maybe_reload_for_tiles,
        # LAST on purpose: it reports on the pass above, so it has
        # to run after everything it reports on.
        _report_patcher_health,
    )
    # THE PACING IS A BUDGET NOW, NOT A CONSTANT PER STEP.
    #
    # The 0.25s below every step was introduced in b7ce297 ("Prevent quick
    # update startup freezes") when this tuple had TWENTY-SIX entries -- 6.5
    # seconds of yielding, which is what that change was tested at. It has 63
    # now, so the same line costs 15.75 seconds of pure sleeping on every boot
    # before a single step does any work, and nobody re-derived it as steps
    # were added. Two independent reviews measured it; one field log shows the
    # pass still running 53 seconds in.
    #
    # What the wait is FOR is not starving Kodi while the pass runs, and that
    # is a property of the total time yielded, not of the per-step figure. So
    # spread the same total the original was validated at over however many
    # steps there are. A short pass is unchanged (the cap is the old value), a
    # long one stops paying for its own length, and step 64 costs nothing.
    # THE FLOOR IS A SECOND CONSTRAINT, and it wins. Below ~130 steps the
    # budget binds and the pass yields 6.5s in total however long the tuple
    # gets. Above that the floor binds instead and the total starts growing
    # again -- which is correct, because a yield of nothing is not a yield and
    # the freeze this line exists to prevent would come back. It is also the
    # signal that the answer has stopped being "tune the constant": a pass that
    # long wants splitting, not a smaller sleep. So it says so, once, instead
    # of quietly costing seconds again the way 0.25 did.
    _pace = max(0.05, min(0.25, 6.5 / max(1, len(steps))))
    if _pace * len(steps) > 7.0:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log(
                'the startup repair pass has {0} steps and now yields {1:.1f}s '
                'in total; the per-step floor is binding, so this grows with '
                'every step added from here -- split the pass rather than '
                'shrinking the yield'.format(len(steps), _pace * len(steps)),
                level='WARNING')
        except Exception:
            pass
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
        except BaseException as e:
            # SystemExit or KeyboardInterrupt out of a step. `except Exception`
            # does not catch either, so this used to leave the pass -- and
            # everything queued behind it, including the step that puts Hebrew
            # subtitles on screen -- with NOTHING in the log: the run simply
            # stopped, indistinguishable from a hang. HANDOFF records a patcher
            # raising SystemExit as a thing that has actually happened here.
            #
            # Deliberately re-raised rather than swallowed: an aborted pass must
            # not reach _publish_repairs_state and look finished, because the
            # waiter would then reload POV against half-applied patches. The
            # only thing that changes is that it says so first.
            try:
                from resources.lib import kodi_utils
                kodi_utils.log(
                    'build startup repair {0} raised {1} and ended the whole '
                    'pass: {2}'.format(getattr(step, '__name__', 'unknown'),
                                       type(e).__name__, e),
                    level='WARNING')
            except Exception:
                pass
            raise

        try:
            if monitor and monitor.waitForAbort(_pace):
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

    # Only after every step has been through. An early return above means the
    # pass was aborted, and an aborted pass must NOT look finished -- the
    # waiter would then reload POV against half-applied patches.
    _publish_repairs_state(_addon_version())


# THE REPAIR PASS RUNS INLINE ON MAIN, ON PURPOSE. There used to be a
# _start_build_startup_repairs() here that put _run_build_startup_repairs on a
# daemon thread, and nothing ever called it -- main() calls the pass directly.
# Deleted rather than wired up, because wiring it up is not a tidy-up, it is a
# behaviour change with two dependants:
#
#   * pov_reload.wait_until_settled's bounds (30s, and 10s for an outage we did
#     not cause) were chosen BECAUSE three of its four callers are steps in this
#     inline pass, where a wait is the subtitle service not starting. Off the
#     main thread those numbers could be far more generous -- and would have to
#     be re-derived, not inherited.
#   * _publish_repairs_state / REPAIRS_DONE_PROPERTY is what the wizard's
#     hot_reload waits on before it cycles anything. Its ordering assumes the
#     pass has finished when main() moves on.
#
# Moving it is a reasonable thing to want. It is not a reasonable thing to do
# by accident, which a dead function sitting here invites.



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
#   v5 -- cue-timing repair: bound runaway cue durations. A mistyped timestamp
#         in an AI translation could leave one line frozen on screen for the
#         rest of the episode; this walk is the only mechanism that repairs an
#         ALREADY-cached translation without the user replaying that title.
#   v6: strip Arabic the AI leaked from the gender reference into a Hebrew
#       line -- see srt.strip_leaked_arabic. NOT every file here is ours: the
#       Google Translate fallback saves into this directory too, so the repair
#       is gated per file by srt.may_carry_arabic_leak.
#   v7: explicit RTL-base controls and style-run normalization.
#   v8: restore archived physical-order ellipses, dialogue marks and paired
#       closing quote/bracket punctuation before wrapping for Kodi.
CACHE_RTL_FIX_VERSION = '8'


def _maybe_repair_rtl_cache():
    """One-shot walk of cache/translated/, re-applying the current display and
    TIMING repairs to each file. Catches up translations that got cached before
    a post-processor was in place or before it handled a specific edge case.
    Marker-gated so it only runs once per CACHE_RTL_FIX_VERSION bump -- which is
    why the constant must be bumped whenever a new repair is added here, or
    every existing install skips the backfill forever."""
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
                # cache/translated/ is NOT all our own output: the Google
                # Translate fallback saves here too, marked by a '.google'
                # sidecar. srt.may_carry_arabic_leak is the one place that rule
                # lives -- see it before adding a repair path.
                body = (srt.strip_leaked_arabic(content)
                        if srt.may_carry_arabic_leak(p) else content)
                fixed = srt.clamp_cue_durations(
                    srt.fix_rtl_punctuation(
                        body, legacy_engine='auto'))
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



def _maybe_refresh_shared_sdh():
    """Warm the community-shared SDH set (Phase 3b) into the local cache from
    this background service, so the subtitle-ranking path can read it without a
    network call. use-gated + TTL-gated (at most once/day) inside refresh; a
    no-op when the pool isn't in use. Best-effort."""
    try:
        from resources.lib import sdh_pool
        sdh_pool.refresh_shared_sdh()
    except Exception:
        pass


def _maybe_patch_idanplus_channels():
    """Heal + harden Idan Plus (plugin.video.idanplus) channel loading.

    A corrupt/partial displayChannels.json makes idanplus read its channel
    map as a list and crash ("'list' object has no attribute 'items'"), so
    no channel loads or plays and the addon can't self-repair. We move a
    corrupt file aside (idanplus then rebuilds it from the remote list) and,
    best-effort, harden common.py so a future corruption degrades to a
    rebuild instead of a crash. No-op when idanplus isn't installed;
    idempotent + safe every startup."""
    try:
        from resources.lib import idanplus_channels_patcher, kodi_utils
    except Exception:
        return
    try:
        status = idanplus_channels_patcher.ensure_patched()
        if status != 'no_target':
            kodi_utils.log(
                'idanplus_channels_patcher: {0}'.format(status),
                level='INFO')
    except Exception as e:
        try:
            kodi_utils.log(
                'idanplus_channels_patcher run failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


# ---------------------------------------------------------------------------
# One switch that stops this add-on touching plugin.video.pov at all.
#
# We rewrite about twenty of POV's own source files on every startup. That is a
# standing bet that POV's internals still look the way they did when each patch
# was written, and POV updates itself from its own repository whenever its
# author publishes -- so the bet can be lost at any time, on the user's device,
# with no warning and no error: the patch still applies, and something
# downstream quietly stops working. When that happens the first thing anyone
# needs is a way to find out whether it was us, in one step, without a rebuild
# and without guesswork.
#
# Turning this on makes every POV patcher a no-op from the next start. It does
# not undo edits already on disk -- but POV rewrites its own files whenever it
# updates, so reinstalling POV from its repository restores a clean copy
# immediately, and with this on it stays clean.
# ---------------------------------------------------------------------------
POV_PATCHING_OFF_SETTING = '_pov_patching_off'
_POV_SKIP_LOGGED = False


def _skip_pov_patchers():
    """True when POV patching is switched off. Says so once per start, so the
    reason a device is behaving differently is in its log."""
    try:
        from resources.lib import kodi_utils
        off = (kodi_utils.get_setting(POV_PATCHING_OFF_SETTING, '')
               or '').strip().lower() == 'true'
    except Exception:
        return False
    if not off:
        return False
    global _POV_SKIP_LOGGED
    if not _POV_SKIP_LOGGED:
        _POV_SKIP_LOGGED = True
        try:
            from resources.lib import kodi_utils
            kodi_utils.log(
                'POV patching is switched OFF in settings -- leaving '
                'plugin.video.pov exactly as its own author shipped it. '
                'Reinstall POV from its repository to drop any edits already '
                'on disk.', level='WARNING')
        except Exception:
            pass
    return True

def _maybe_patch_skin_watched_poster():
    """Make the watched tick tell the truth: draw it in the Poster view, which
    never had one, and stop the list views drawing it on everything.

    Both halves are the same bug seen from opposite sides, and both are fixed
    against the same source of truth -- the playcount -- so the two views can
    no longer disagree about whether something was watched.

    Deliberately NOT behind _skip_pov_patchers(): that switch exists to take
    POV out of the loop while a POV problem is being isolated, and this edits
    a skin. Gating it there would silently disable a repair that has nothing
    to do with the add-on being isolated.
    """
    try:
        from resources.lib import skin_watched_poster_patcher, kodi_utils
    except Exception:
        return
    try:
        results = skin_watched_poster_patcher.ensure_patched()
        patched = [k for k, v in results.items() if v == 'patched']
        if patched:
            kodi_utils.log(
                'skin_watched_poster_patcher: watched marks corrected in '
                '{0}'.format(', '.join(patched)), level='INFO')
        broken = [k for k, v in results.items()
                  if v in ('unmatched', 'parse_failed', 'write_failed')]
        if broken:
            kodi_utils.log(
                'skin_watched_poster_patcher: left alone: '
                '{0}'.format(', '.join(broken)), level='WARNING')
    except Exception as e:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log(
                'skin_watched_poster_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass



def _tile_reload_worker():
    """Do ONE skin reload so freshly-cache-dropped tiles re-cache from disk. The
    home focus is snapshotted + restored (via pov_reload) so the menu doesn't snap
    to the first tile if the user was already navigating. No-op while playing."""
    try:
        import xbmc
        if xbmc.getCondVisibility('Player.HasMedia'):
            return
        # Wait out any POV cycle FIRST. This function has always imported
        # pov_reload -- for the focus snapshot -- and never asked it the one
        # question that matters: rebuilding every window while POV cannot be
        # constructed is what breaks the home screen. It applies to every skin,
        # since unlike the other reload sites this one has no skin guard at all.
        settled, saved = True, None
        try:
            from resources.lib import pov_reload
            settled = pov_reload.wait_until_settled()
            if settled:
                saved = pov_reload._capture_home_focus()
        except Exception:
            settled, saved = True, None
        if not settled:
            return
        xbmc.executebuiltin('ReloadSkin()')
        try:
            xbmc.sleep(1200)
        except Exception:
            pass
        if saved:
            try:
                from resources.lib import pov_reload
                pov_reload._restore_home_focus(saved)
            except Exception:
                pass
    except Exception:
        pass


def _maybe_reload_for_tiles():
    """LAST startup step: if build_icons_patcher dropped stale tile textures this
    boot (a TILE_REFRESH_GEN bump, or a FORCE_SYNC tile whose bytes changed), do
    one skin reload so the fresh home-tile art shows now rather than only on the
    next restart -- the cache entries are already gone, ReloadSkin re-caches them
    from disk. Runs on a BACKGROUND thread: the reload + bounded focus-restore
    (~1-11s) must not block the rest of main() (autosub listener registration,
    etc.). Gen-triggered reloads are one-off per generation (marker-gated in the
    patcher, and only after the marker actually persisted)."""
    if not _TILE_REFRESH_NEEDED[0]:
        return
    _TILE_REFRESH_NEEDED[0] = False
    try:
        import threading
        threading.Thread(target=_tile_reload_worker,
                         name='pov-tile-reload', daemon=True).start()
    except Exception:
        # Couldn't spawn a thread -> run inline (still fully guarded).
        _tile_reload_worker()

def _maybe_patch_pov_hebrew_genres():
    """Translate POV's genre menu labels to Hebrew (all skins). POV's genre
    names come from the dict keys of modules/meta_lists.py; a POV self-update
    reverted them to English everywhere. This rewrites each key to Hebrew
    while keeping the [tmdb_id, icon] value, so genres show in Hebrew again
    without changing what each genre loads. Compile-checked, idempotent."""
    if _skip_pov_patchers():
        return
    try:
        from resources.lib import pov_hebrew_genres_patcher, kodi_utils
    except Exception:
        return
    try:
        status = pov_hebrew_genres_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'pov_hebrew_genres_patcher: genre labels set to Hebrew',
                level='INFO')
        elif status in ('no_pov', 'no_file', 'already_patched'):
            pass
        else:
            kodi_utils.log(
                'pov_hebrew_genres_patcher: ' + status, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_hebrew_genres_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass

def _maybe_patch_pov_scraper_settings():
    """One-time tune of POV's scraper settings for the build: keep pre-release
    (CAM/SCR/TELE) and 3D results ON (the build owner wants them), and turn the
    default-ON provider.piratebay OFF (build owner's instruction, 2026-08-15 --
    it had been turned on here for source counts). Applied once per marker
    version, only where the value still differs, so a user who later changes
    any of these keeps their choice."""
    if _skip_pov_patchers():
        return
    try:
        from resources.lib import pov_scraper_settings_patcher, kodi_utils
    except Exception:
        return
    try:
        status = pov_scraper_settings_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'pov_scraper_settings_patcher: pre-release/3D on, piratebay '
                'off, and the scraper/debrid timeout at POV '
                "6.08's own default", level='INFO')
        elif status in ('already', 'no_pov', 'unchanged'):
            pass
        else:
            kodi_utils.log(
                'pov_scraper_settings_patcher: ' + status, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_scraper_settings_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_pov_hebrew_ui():
    """Hebrew-ise POV's own in-app UI strings (resume dialog + search hub),
    which are English because POV ships only en_gb. Sets the Hebrew msgstr on
    the relevant ids in POV's strings.po. Idempotent, self-healing."""
    if _skip_pov_patchers():
        return
    try:
        from resources.lib import pov_hebrew_ui_patcher, kodi_utils
    except Exception:
        return
    try:
        status = pov_hebrew_ui_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'pov_hebrew_ui_patcher: POV UI strings set to Hebrew',
                level='INFO')
        elif status in ('no_pov', 'no_file', 'already_patched'):
            pass
        else:
            kodi_utils.log(
                'pov_hebrew_ui_patcher: ' + status, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_hebrew_ui_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_seed_recent_updates_tile():
    """Put the "10 העדכונים האחרונים" tile on the home screen, once ever.

    Deliberately runs right after the personal-tiles restore, so it looks at a
    favourites.xml that has already been repaired if it needed repairing --
    otherwise a mid-repair file could be read as "no closing tag" and the offer
    would be silently skipped for that boot.
    """
    try:
        from resources.lib import recent_updates_tile_patcher, kodi_utils
    except Exception:
        return
    try:
        status = recent_updates_tile_patcher.ensure_patched()
        if status not in ('already_seen', 'no_kodi', 'no_favourites'):
            kodi_utils.log('recent_updates_tile_patcher: {0}'.format(status),
                           level='INFO')
    except Exception as e:
        try:
            kodi_utils.log('recent_updates_tile_patcher failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _maybe_add_tonight_entry():
    try:
        from resources.lib.tonight.entrypoints import ensure
        ensure()
    except Exception:
        pass  # An optional home shortcut must not interrupt startup repairs.


def _maybe_fix_idanplus_youtube_id():
    """Idan Plus hands YouTube the word "watch" instead of a video id.

    A field log showed five YouTube player clients each refusing the same
    request with "This video is unavailable", and the id in every one of them
    was the literal string 'watch'. GetYouTube reads the id out of the URL
    PATH and truncates at '?', which is exactly where it lives in the ordinary
    youtube.com/watch?v= form.

    And the add-on builds that url itself: Kan's mobile API returns a BARE id
    and kan.py wraps it into watch?v= before handing it over, so GetYouTube
    fails to unwrap its own construction. This is not a regression and not
    something Kan changed -- every Kan item of that type has always failed.

    The injected line only fires where the add-on produced something that
    cannot be a YouTube id (eleven characters of YouTube's own charset), which
    is the signature of the failure, so no url it already resolved correctly
    can reach it. And when Idan Plus fixes this itself, the anchor stops
    matching, nothing is touched, and the log says so once per boot -- which
    is the signal to retire the patcher. Two cleverer mechanisms for deciding
    WHY the shape changed were tried and both failed review; the module
    records what they were and how.

    DELIBERATELY NOT behind _skip_pov_patchers(). That switch says to leave
    plugin.video.pov as its author shipped it; this writes to
    plugin.video.idanplus, a different add-on, and gating it on the POV switch
    would silently tie two unrelated decisions together.
    """
    try:
        from resources.lib import idanplus_youtube_id_patcher, kodi_utils
        st = idanplus_youtube_id_patcher.ensure_patched()
        if st in ('unmatched', 'compile_failed', 'write_failed',
                  'revert_failed', 'read_failed'):
            kodi_utils.log(
                'idanplus_youtube_id_patcher: ' + st, level='WARNING')
    except Exception as e:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log(
                'idanplus_youtube_id_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_mdblist_reauth():
    """Let an expired MDBList token heal itself instead of being reconnected.

    POV refreshes only on a clock check and treats a 401 as just another
    network error, so a token the server stops accepting is permanent: every
    call fails, the sync monitor backs off half an hour, and the account has
    to be authorised again by hand. Umbrella then compounds it with a dialog
    telling the user to re-authenticate in a screen this build does not use.

    Trakt has the identical defect in the file next door, and a field log
    showed it failing in the same breath as the MDBList one recovered, so it
    gets the same treatment. See the modules."""
    # The switch guards the POV half ONLY. Written as an early return over
    # both halves first, which silently took Umbrella's fix down with it --
    # the switch's own text promises to stop changes to plugin.video.pov and
    # says nothing about any other add-on, and turning it on to isolate a POV
    # problem must not change Umbrella's behaviour as a side effect.

    try:
        from resources.lib import umbrella_mdblist_token_patcher, kodi_utils
        st = umbrella_mdblist_token_patcher.ensure_patched()
        if st in ('unmatched', 'compile_failed', 'write_failed'):
            kodi_utils.log(
                'umbrella_mdblist_token_patcher: ' + st, level='WARNING')
    except Exception as e:
        try:
            # Re-imported: if the import above is what raised, `kodi_utils` is
            # unbound here and the handler would raise instead of logging.
            from resources.lib import kodi_utils
            kodi_utils.log(
                'umbrella_mdblist_token_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass
    try:
        from resources.lib import umbrella_mdblist_sync_patcher, kodi_utils
        st = umbrella_mdblist_sync_patcher.ensure_patched()
        if st in ('unmatched', 'compile_failed', 'write_failed',
                  'revert_failed'):
            kodi_utils.log(
                'umbrella_mdblist_sync_patcher: ' + st, level='WARNING')
    except Exception as e:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log(
                'umbrella_mdblist_sync_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_seed_pov_seasons_view():
    """Open POV's season list in a view that draws a poster.

    Reported as "per-season posters only work in NOX". They work everywhere;
    the screen was a text list with no poster in the layout at all. Writes
    POV's own views.db -- the same row POV's Set View writes -- once per skin,
    over whatever is there, and then never again. See the module."""
    if _skip_pov_patchers():
        return
    try:
        from resources.lib import pov_seasons_view_seed, kodi_utils
    except Exception:
        return
    try:
        st = pov_seasons_view_seed.ensure_seeded()
        if st == 'failed':
            kodi_utils.log('pov_seasons_view_seed: failed', level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_seasons_view_seed failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass

def _maybe_quiet_update_nags():
    """Switch off the self-update check in Umbrella and Account Manager Lite.

    Both nag at every start about a version the build pins deliberately, and
    neither offers a way to take it -- taking it would strip the patches that
    make them work here. Settings only, once each, and only while the value
    is still the one they shipped."""
    try:
        from resources.lib import update_nag_patcher, kodi_utils
    except Exception:
        return
    try:
        status = update_nag_patcher.ensure_quiet()
        if status == 'patched':
            kodi_utils.log(
                'update_nag_patcher: self-update notifications switched off',
                level='INFO')
        elif status == 'write_failed':
            kodi_utils.log('update_nag_patcher: ' + status, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'update_nag_patcher run failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass



def _maybe_patch_pov_widget_crash_guard():
    """Stop the "add to Trakt -> refresh widgets -> Kodi native crash".
    POV's SyncMonitor, when `trakt.sync_refresh_widgets` is ON, fires
    UpdateLibrary(video,special://skin/foo) after a Trakt/MDBList sync; every
    home widget then reloads at once, spawning concurrent POV router.py
    invocations that share POV's reuselanguageinvoker interpreter and corrupt
    CPython dict internals (SystemError: dictobject.c:1756) -> the app dies.
    Confirmed from a field crash log. We force that single setting OFF (only
    when it is actually on); widgets then refresh on the next navigation
    instead of in a crash-inducing burst. No source files touched."""
    if _skip_pov_patchers():
        return
    try:
        from resources.lib import pov_widget_crash_guard, kodi_utils
    except Exception:
        return
    try:
        status = pov_widget_crash_guard.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'pov_widget_crash_guard: disabled POV trakt.sync_refresh_'
                'widgets (was ON -- prevents the add-to-Trakt native crash)',
                level='INFO')
        elif status in ('read_failed', 'write_failed'):
            kodi_utils.log(
                'pov_widget_crash_guard: ' + status, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_widget_crash_guard run failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass

def _maybe_patch_pov_language_invoker():
    """Hold POV's reuse-language-invoker flag where this device wants it.

    BY DEFAULT that is OFF, which closes the crash class the two guards above
    only narrow. Both of them remove a TRIGGER for "many POV invocations at
    once"; this removes what makes that burst fatal. POV ships
    <reuselanguageinvoker>true</reuselanguageinvoker>, so concurrent
    invocations share one Python interpreter and corrupt CPython's internals
    (a NULL refcount write inside python3.8.dll in the 2026-08-14 minidump,
    on a thread the Kodi log identifies as POV's). With the flag off, each
    invocation gets its own interpreter and the same burst is merely slower.

    SLOWER TURNED OUT TO BE MEASURABLE, so since 0.2.507 the direction is the
    `pov_fast_navigation` setting rather than a constant -- off out of the
    box, so this step does exactly what it always did unless somebody has
    deliberately asked for the speed back. The module header carries the
    measurement and the reason the obvious "narrow it to Arctic Fuse 3"
    shortcut is wrong.

    POV keeps this flag in TWO places -- a hidden `reuse_language_invoker`
    setting and its own addon.xml -- and runs a service that rewrites the xml
    from the setting, so the module writes both, setting first. Effective from
    the next Kodi start: Kodi has already read addon.xml by the time this pass
    runs. See the module header for why we do not force it live."""
    if _skip_pov_patchers():
        return
    try:
        from resources.lib import pov_language_invoker_guard, kodi_utils
    except Exception:
        return
    try:
        # Read the direction ONCE, here, and hand the same value to the write
        # and to the line that reports it. Reading it again for the log would
        # be a second answer to a question the module's own docstring calls
        # load-bearing, spent on prose.
        try:
            _dir = pov_language_invoker_guard._wanted()
        except Exception:
            _dir = None      # ensure_patched then decides for itself
        status = pov_language_invoker_guard.ensure_patched(_dir)
        try:
            _since = ('%.2fs into the repair pass'
                      % (time.time() - _REPAIRS_STARTED)
                      if _REPAIRS_STARTED else 'pass start not stamped')
        except Exception:
            _since = 'unknown'
        if status == 'patched':
            kodi_utils.log(
                'pov_language_invoker_guard: reuse-language-invoker set to '
                '%s (setting + addon.xml) at %s -- %s. Kodi read POV\'s '
                'addon.xml while building its add-on list, long before this '
                'pass ran, so the value it is RUNNING on is still the old one '
                'this session. POV notices that within a few seconds and '
                'offers a profile reload, which applies it without a second '
                'restart; declining just defers it to the next start. This '
                'number is the margin we beat POV\'s check by'
                % (_dir, _since, pov_language_invoker_guard.describe(_dir)),
                level='INFO')
        elif status == 'setting_only':
            kodi_utils.log(
                'pov_language_invoker_guard: setting written, addon.xml was '
                'not -- POV reconciles it from the setting on its next start',
                level='WARNING')
        elif status in ('unreadable', 'no_tag', 'write_failed'):
            kodi_utils.log(
                'pov_language_invoker_guard: ' + status, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'pov_language_invoker_guard run failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass


def _maybe_patch_umbrella_language():
    """Umbrella (the opt-in pilot addon) ships its strings only in the
    LEGACY language layout (resources/language/English/), so on a
    Hebrew-interface Kodi every settings label resolves to an empty
    string -- blank categories, blank labels. Mirror the English po into
    the modern resource.language.en_gb folder Kodi actually looks for.
    Additive-only and self-healing: an Umbrella self-update replaces the
    addon folder, and this re-applies on the next startup. Instant no-op
    for everyone who never installed the pilot."""
    try:
        from resources.lib import umbrella_language_patcher, kodi_utils
    except Exception:
        return
    try:
        status = umbrella_language_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'umbrella_language_patcher: modern en_gb strings installed',
                level='INFO')
        elif status in ('read_failed', 'write_failed'):
            kodi_utils.log(
                'umbrella_language_patcher: ' + status, level='WARNING')
        # Hebrew for the menus themselves. Additive: we create the he_il
        # folder Umbrella does not ship, so their updates keep applying and a
        # string we did not translate simply falls back to English.
        try:
            from resources.lib import umbrella_hebrew_ui_patcher
            if umbrella_hebrew_ui_patcher.ensure_patched() == 'patched':
                kodi_utils.log(
                    'umbrella_hebrew_ui_patcher: Hebrew menu strings '
                    'installed', level='INFO')
        except Exception:
            pass
        # ORDER IS LOAD-BEARING: the metadata language must move BEFORE the
        # content filters are re-evaluated. api.language drives both, and
        # Hebrew with the filters still on asks for titles ORIGINALLY MADE in
        # Hebrew -- which empties every list.
        lang = umbrella_language_patcher.ensure_api_language()
        if lang == 'patched':
            kodi_utils.log(
                'umbrella_language_patcher: metadata language set to Hebrew',
                level='INFO')
        # Second, unrelated half: Umbrella's two language CONTENT FILTERS
        # empty every list when its API language is not English.
        filt = umbrella_language_patcher.ensure_content_filters_sane()
        if filt == 'patched':
            kodi_utils.log(
                'umbrella_language_patcher: language content filters cleared',
                level='INFO')
    except Exception as e:
        try:
            kodi_utils.log(
                'umbrella_language_patcher run failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass
    # Account Manager Lite (the other opt-in pilot) trips over the same
    # locale-folder fallback, and the labels it loses are Authorize,
    # Username, Password and API Key -- the controls a user has to press to
    # connect an account. No-op for anyone who never installed it.
    try:
        from resources.lib import legacy_lang_mirror
        if legacy_lang_mirror.mirror('script.module.acctmgr') == 'patched':
            kodi_utils.log(
                'legacy_lang_mirror: Account Manager Lite labels will render',
                level='INFO')
    except Exception:
        pass
    # Wiring + subtitle-matching hook for the same optional add-on.
    try:
        from resources.lib import umbrella_setup_patcher
        prov = umbrella_setup_patcher.ensure_external_provider()
        if prov == 'patched':
            kodi_utils.log(
                'umbrella_setup_patcher: CocoScrapers wired as the external '
                'provider', level='INFO')
        elif prov == 'repaired':
            kodi_utils.log(
                'umbrella_setup_patcher: incomplete CocoScrapers wiring '
                'repaired', level='WARNING')
        cps = umbrella_setup_patcher.ensure_coco_providers()
        if cps == 'patched':
            kodi_utils.log(
                'umbrella_setup_patcher: extra CocoScrapers providers enabled',
                level='INFO')
        dfl = umbrella_setup_patcher.ensure_umbrella_defaults()
        if dfl == 'patched':
            kodi_utils.log(
                'umbrella_setup_patcher: Umbrella defaults applied',
                level='INFO')
        hook = umbrella_setup_patcher.ensure_source_name_published()
        if hook == 'patched':
            kodi_utils.log(
                'umbrella_setup_patcher: picked-source release name is now '
                'published for subtitle matching', level='INFO')
        elif hook in ('unmatched', 'compile_failed', 'write_failed'):
            kodi_utils.log(
                'umbrella_setup_patcher: ' + hook, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'umbrella_setup_patcher run failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass
    # The Hebrew-subtitle match badge in Umbrella's OWN source window -- the
    # same brain (he_sub_match) that already feeds POV's, so a title warmed
    # from one add-on shows its badge immediately in the other. Separate from
    # the block above because it patches a different Umbrella file and must
    # not be lost if the wiring above raises.
    try:
        from resources.lib import umbrella_subtitle_match_patcher
        st = umbrella_subtitle_match_patcher.ensure_patched()
        if st == 'patched':
            kodi_utils.log(
                'umbrella_subtitle_match_patcher: Hebrew match % added to '
                "Umbrella's source window", level='INFO')
        elif st in ('unmatched', 'compile_failed', 'write_failed',
                    'read_failed'):
            kodi_utils.log(
                'umbrella_subtitle_match_patcher: ' + st, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'umbrella_subtitle_match_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass
    # Kodi's own "playback failed" after a deliberate back-out of the source
    # list. It is a 20-second timer on consecutive unresolved plays, not a
    # report about this playback -- see kodi_playlist_timeout_patcher.
    try:
        from resources.lib import kodi_playlist_timeout_patcher
        st = kodi_playlist_timeout_patcher.ensure_patched()
        if st in ('patched', 'created'):
            kodi_utils.log(
                'kodi_playlist_timeout_patcher: ' + st, level='INFO')
        elif st in ('unmatched', 'bad_xml', 'write_failed', 'read_failed'):
            kodi_utils.log(
                'kodi_playlist_timeout_patcher: ' + st, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'kodi_playlist_timeout_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass
    # Keep Umbrella on whatever MDBList and Trakt authorisations POV currently
    # holds. POV owns the refreshing -- only its client_id can -- so this is
    # what carries a refreshed token across to Umbrella, and what covers a
    # user who authorised before this existed.
    #
    # MDBLIST FIRST, AND THE ORDER IS LOAD-BEARING. Both mirrors claim the
    # same two Umbrella settings (indicators.alt / scrobble.source) and the
    # claim is one-shot per key, so whichever runs first while they are still
    # at the shipped Local wins permanently. This build prefers MDBList, and
    # the keeper loop in _start_service_mirror_keeper runs them in this same
    # order for the same reason -- if you change one, change both.
    try:
        from resources.lib import mdblist_umbrella_mirror
        st = mdblist_umbrella_mirror.mirror()
        if st == 'mirrored':
            kodi_utils.log(
                'mdblist_umbrella_mirror: Umbrella now shares POV\'s MDBList '
                'authorisation', level='INFO')
        elif st == 'write_failed':
            kodi_utils.log(
                'mdblist_umbrella_mirror: ' + st, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'mdblist_umbrella_mirror failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass
    try:
        from resources.lib import trakt_umbrella_mirror
        st = trakt_umbrella_mirror.mirror()
        if st == 'mirrored':
            kodi_utils.log(
                'trakt_umbrella_mirror: Umbrella now shares POV\'s Trakt '
                'authorisation', level='INFO')
        elif st in ('write_failed', 'incomplete'):
            kodi_utils.log('trakt_umbrella_mirror: ' + st, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'trakt_umbrella_mirror failed: {0}'.format(e), level='WARNING')
        except Exception:
            pass
    # Searching Umbrella in Hebrew found nothing: the percent-encoded query
    # made Umbrella's own api_key substitution raise, so the request was
    # never sent. See umbrella_tmdb_apikey_patcher for the full account.
    try:
        from resources.lib import umbrella_tmdb_apikey_patcher
        st = umbrella_tmdb_apikey_patcher.ensure_patched()
        if st == 'patched':
            kodi_utils.log(
                'umbrella_tmdb_apikey_patcher: non-ASCII search repaired',
                level='INFO')
        elif st in ('unmatched', 'compile_failed', 'write_failed',
                    'read_failed'):
            kodi_utils.log(
                'umbrella_tmdb_apikey_patcher: ' + st, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'umbrella_tmdb_apikey_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass
    try:
        from resources.lib import umbrella_setup_patcher
        st = umbrella_setup_patcher.ensure_personal_list_order()
        if st in ('patched', 'unmatched', 'write_failed'):
            kodi_utils.log('umbrella personal list order: ' + st)
    except Exception as e:
        kodi_utils.log('umbrella personal list order failed: ' + str(e), level='WARNING')

    # Two source-flow repairs: fire the Hebrew-availability warm at the START
    # of the scrape so the badge is there on the FIRST entry rather than the
    # second, and stop Kodi announcing "playback failed" when the user simply
    # backed out of the source list.
    try:
        from resources.lib import umbrella_source_ux_patcher
        st = umbrella_source_ux_patcher.ensure_patched()
        if st == 'patched':
            kodi_utils.log(
                'umbrella_source_ux_patcher: prewarm + quiet cancel applied',
                level='INFO')
        elif st in ('unmatched', 'compile_failed', 'write_failed',
                    'read_failed'):
            kodi_utils.log(
                'umbrella_source_ux_patcher: ' + st, level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'umbrella_source_ux_patcher failed: {0}'.format(e),
                level='WARNING')
        except Exception:
            pass





# The auto-on-play machinery (state, the on-play search/apply flow, and the
# Player listener) lives in resources/lib/autosub_service.py -- extracted
# VERBATIM so the standalone (repo-channel) service runs the exact same code.


def _start_service_mirror_keeper(monitor):
    """Keep Umbrella on whatever MDBList and Trakt authorisations POV holds.

    The startup mirror covers most of it, but POV refreshes its token
    silently in the background -- with its own client_id, the only one that
    can -- and a set-top box stays on for days. Once POV rotates the token,
    the copy Umbrella reads from disk is stale, so the next Umbrella session
    authenticates with a dead token. Umbrella also fixes its Authorization
    header at module-import time and reuses its interpreter, so there is no
    way to hand it a new token mid-session; what matters is that the value on
    disk is right BEFORE it next imports.

    A periodic re-mirror is two settings reads and writes only on a change,
    so it costs nothing to run often. Deliberately NOT a patch to POV's own
    mdbl_refresh(): another injection into somebody else's file, to achieve
    what a cheap poll already achieves, is surface area for no gain.

    Every minute, not every quarter of an hour, and that is what makes a
    fresh connect land. MDBList gets an instant push -- POV's Connect
    Services row fires our mirror the moment it returns -- but Trakt has no
    such hook, and wiring one means wrapping another class on the screen
    that takes the whole of Connect Services down if it raises. A minute of
    lag is worth more than that risk. In the steady state a pass is a
    handful of getSetting calls and no writes at all.

    MDBLIST BEFORE TRAKT, and the startup pass in _maybe_patch_umbrella_
    language uses the same order for the same reason: both claim the same
    two watch-source settings, once, and first past the post wins."""
    try:
        from resources.lib import mdblist_umbrella_mirror
    except Exception:
        return
    try:
        from resources.lib import trakt_umbrella_mirror
    except Exception:
        trakt_umbrella_mirror = None
    try:
        from resources.lib import pov_seasons_view_seed
    except Exception:
        pov_seasons_view_seed = None
    try:
        from resources.lib import umbrella_watch_prompt
    except Exception:
        umbrella_watch_prompt = None

    def _loop():
        try:
            if monitor.waitForAbort(90):   # let startup settle first
                return
            while not monitor.abortRequested():
                try:
                    mdblist_umbrella_mirror.mirror()
                except Exception:
                    pass
                if trakt_umbrella_mirror is not None:
                    try:
                        trakt_umbrella_mirror.mirror()
                    except Exception:
                        pass
                # Same tick, and here because this is the only periodic hook
                # we have: Kodi changes skin without a restart, and POV's
                # seasons view id means a different layout in each skin.
                #
                # _skip_pov_patchers() is checked HERE, not only on the
                # startup pass. This is the one job in this loop that writes
                # inside POV's own profile, and the switch exists so somebody
                # can rule this build out in one step -- a thread that carries
                # on writing to POV ninety seconds later would make the switch
                # a lie.
                # Deliberately in the keeper and not in the startup steps:
                # it can put a dialog on screen, and boot is already crowded
                # with them. By the first tick the splash is long gone.
                if umbrella_watch_prompt is not None:
                    try:
                        umbrella_watch_prompt.maybe_ask_async()
                    except Exception:
                        pass
                if pov_seasons_view_seed is not None:
                    try:
                        # Inside the try, not in the `if`: this is the only
                        # call in the loop body that sat outside one, and an
                        # exception here would take the whole keeper thread
                        # down -- both mirrors with it -- for the rest of the
                        # session, through an outer catch that logs nothing.
                        if not _skip_pov_patchers():
                            pov_seasons_view_seed.ensure_seeded()
                    except Exception:
                        pass
                if monitor.waitForAbort(60):
                    break
        except Exception:
            pass

    try:
        threading.Thread(target=_loop, daemon=True).start()
    except Exception:
        pass


def _start_pool_queue_drainer(monitor):
    """Drive both pool queues from the long-lived service:
      1. process_harvest_queue() -- gently pull a couple of queued Ktuvit subs
         from Ktuvit (throttled, retrying) and feed them into the upload queue.
         This is what eventually mirrors EVERY release of a title without
         hammering Ktuvit or depending on the user staying on the video.
      2. drain() -- upload queued contributions to Telegram, one at a time with
         a throttle so a burst can't trip the bot's rate limit.
    Both survive playback ending / a Kodi restart (the queues are on disk).
    Backlog -> short interval; idle -> longer. Best-effort; never blocks."""
    try:
        from resources.lib import pool
    except Exception:
        return

    def _loop():
        try:
            if monitor.waitForAbort(20):   # let startup settle first
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
                # Backlog -> come back soon (keeps the gentle harvest moving);
                # empty -> idle, but still promptly so a manual pick uploads
                # within ~a minute.
                if monitor.waitForAbort(20 if backlog else 60):
                    break
        except Exception:
            pass

    try:
        threading.Thread(target=_loop, daemon=True).start()
    except Exception:
        pass


def _start_he_warm_drainer(monitor):
    """Drain the Hebrew-availability warm queue from this long-lived service.

    POV's source window (a SEPARATE, short-lived interpreter) can't run the warm
    itself -- OpenSubtitles/Ktuvit need MoranSubs's own addon context + API keys.
    It used to kick a fresh interpreter via RunScript, but booting one (~3s) was
    slower than POV's ~2s scrape, so the "HEB NN%" badge only showed on the 2nd/
    3rd entry. Instead, prewarm() now drops a tiny JSON job on disk; we pick it up
    here within a fraction of a second and run the (parallelized) warm in the
    already-imported service process, so the cache is ready by the time the source
    dialog opens -> % on the FIRST entry. Best-effort; never blocks."""
    try:
        import json
        from resources.lib import he_sub_match as _hsm
    except Exception:
        return

    def _preimport_engine():
        """Pay the cold import once, outside the initial widget budget."""
        try:
            import time as _t
            _pt0 = _t.time()
            from resources.lib import subs_engine_bridge as _b
            _b.ensure_engine_settings()
            from resources.lib.subs_engine.sources import opensubtitles as _o  # noqa: F401
            from resources.lib.subs_engine.sources import ktuvit as _k  # noqa: F401
            _hsm._dbg('drainer engine pre-imported in {0:.1f}s after startup '
                      'settled'.format(_t.time() - _pt0))
        except Exception as e:
            _hsm._dbg('drainer engine pre-import failed: ' + repr(e))

    def _loop():
        try:
            if monitor.waitForAbort(0.5):   # tiny settle, then poll fast
                return
            preload_at = time.time() + _background_settle_seconds()
            engine_ready = False
            while not monitor.abortRequested():
                picked_up = False
                try:
                    d = _hsm._warm_queue_dir()
                    if d and os.path.isdir(d):
                        for fn in sorted(os.listdir(d)):
                            if monitor.abortRequested():
                                return
                            if not fn.endswith('.json'):
                                continue
                            path = os.path.join(d, fn)
                            info = None
                            age = -1.0
                            try:
                                import time as _t
                                age = _t.time() - os.path.getmtime(path)
                            except OSError:
                                pass
                            try:
                                with open(path, 'r', encoding='utf-8') as f:
                                    info = json.load(f)
                            except Exception:
                                info = None
                            # Claim the job (delete first) so a slow/failed warm
                            # can't make us reprocess it in a tight loop.
                            try:
                                os.remove(path)
                            except OSError:
                                pass
                            if info:
                                picked_up = True
                                _hsm._dbg('drainer picked up {0} (queued {1:.1f}s ago)'.format(
                                    (info.get('mk') or fn), age))
                                try:
                                    # A user is waiting, so do not impose the
                                    # speculative-preload delay. run_warm imports
                                    # the engine lazily and starts immediately.
                                    _hsm.run_warm(info)
                                    engine_ready = True
                                except Exception:
                                    pass
                except Exception:
                    pass
                # With no real title waiting, import only after the home-widget
                # wave and only while Kodi is quiet. This preserves first-title
                # HEB availability: a title queued before the deadline bypasses
                # this gate above instead of waiting for it.
                if (not engine_ready and not picked_up
                        and time.time() >= preload_at
                        and not _background_ui_busy()):
                    _preimport_engine()
                    engine_ready = True
                # Sub-second poll so prewarm -> warm start is nearly immediate.
                if monitor.waitForAbort(0.2):
                    break
        except Exception:
            pass

    try:
        threading.Thread(target=_loop, daemon=True).start()
    except Exception:
        pass


def _start_subsync_drainer(monitor):
    """Drain the SubSync deep-verify queue (see subsync._enqueue_deep) in this
    long-lived service. Jobs are rare (once per new subtitle+release pair) and
    each can take 10-30s (oracle download / container probe / Gemini audio),
    which is exactly why they must not run inline in resolve(). Best-effort."""
    def _loop():
        try:
            if monitor.waitForAbort(1.0):
                return
            from resources.lib import subsync as _ss
            while not monitor.abortRequested():
                try:
                    _ss.drain_queue_once()
                except Exception:
                    pass
                if monitor.waitForAbort(1.0):
                    break
        except Exception as exc:
            try:
                from resources.lib import kodi_utils
                kodi_utils.log('subsync drainer stopped: {0}'.format(exc),
                               level='WARNING')
            except Exception:
                pass

    try:
        threading.Thread(target=_loop, daemon=True).start()
    except Exception:
        pass


def _start_subsync_delay_watch(monitor):
    """The HUMAN sync anchor (SubSync S3): while a MoranSubs-delivered
    subtitle plays, sample the user's manual subtitle delay (JSON-RPC); when
    playback ends, a settled non-zero delay becomes a community FIXABLE
    report, and a long zero-delay watch becomes a CONFIRMED vote -- both via
    pool.report_sync (share-gated, fire-and-forget). One report per
    (subtitle, release) pair per Kodi session. This is what resolves files no
    algorithm can anchor (dubbed re-encodes with no subs anywhere)."""
    def _delay_now():
        try:
            raw = xbmc.executeJSONRPC(json.dumps({
                'jsonrpc': '2.0', 'id': 1,
                'method': 'Player.GetProperties',
                'params': {'playerid': 1,
                           'properties': ['subtitledelay']}}))
            return float((json.loads(raw).get('result') or {})
                         .get('subtitledelay') or 0.0)
        except Exception:
            return 0.0

    def _loop():
        try:
            if monitor.waitForAbort(2.0):
                return
            from resources.lib import subsync as _ss
            from resources.lib import pool as _pool
            from resources.lib import kodi_utils
            import xbmcgui
            active, watched, last_delay = None, 0, 0.0
            reported = set()
            while not monitor.abortRequested():
                try:
                    playing = False
                    try:
                        playing = xbmc.Player().isPlayingVideo()
                    except Exception:
                        playing = False
                    if playing:
                        rec = _ss.current_delivery_record()
                        if rec and (active is None
                                    or rec.get('key') != active.get('key')
                                    or float(rec.get('ts') or 0)
                                    != float(active.get('ts') or 0)):
                            active, watched, last_delay = rec, 0, 0.0
                        elif not rec:
                            # A piecewise correction deliberately disables
                            # scalar delay learning. Do not keep accumulating
                            # watch time against the subtitle it replaced.
                            active, watched, last_delay = None, 0, 0.0
                        if active is not None:
                            watched += 10
                            last_delay = _delay_now()
                    elif active is not None:
                        akey = active.get('key') or ''
                        if akey and akey not in reported:
                            rep = _ss.finalize_delay_session(
                                active, last_delay, watched)
                            if rep:
                                # Remember the viewer's correction locally only
                                # for the exact content-derived media cut.  The
                                # existing community report below stays backward
                                # compatible by namespacing the Worker's existing
                                # release field with that same signature.
                                _ss.store_human_verdict(rep)
                                _pool.report_sync(
                                    rep.get('info') or {}, rep['sub_hash'],
                                    _ss._sync_registry_release(
                                        rep['release'],
                                        rep.get('cut_signature') or ''),
                                    rep['scale'],
                                    rep['offset_ms'], rep['status'],
                                    origin='human')
                                reported.add(akey)
                                kodi_utils.log(
                                    'subsync delay-watch: human report '
                                    '({0}, {1:+.0f}ms, watched {2}s)'.format(
                                        rep['status'], rep['offset_ms'],
                                        watched), level='INFO')
                        _ss.clear_delivery_record(active)
                        active, watched, last_delay = None, 0, 0.0
                except Exception:
                    pass
                if monitor.waitForAbort(10.0):
                    break
        except Exception:
            pass

    try:
        threading.Thread(target=_loop, daemon=True).start()
    except Exception:
        pass


def _maybe_start_autosub_player():
    """Register the play-start listener (autosub_service holds the Player
    reference in its module STATE, which outlives this call).

    It always snapshots the file's embedded subtitle streams -- the picker's
    "[מובנה] XX" and "תרגום מובנה → עברית (AI)" rows are built from that
    snapshot -- and auto-searches Hebrew only when engine_autosub is on."""
    try:
        from resources.lib import autosub_service
        autosub_service.start_if_enabled()
    except Exception:
        pass


def _maybe_prewarm_engine():
    try:
        from resources.lib import autosub_service
        autosub_service.prewarm_engine()
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


def _maybe_patch_nox_osd_collision():
    """Shrink NOX's right-side OSD buttons back to their pre-change-source total
    width, so adding "החלף מקור" no longer pushes "הפרק הבא" left into the central
    play controls (the overlap that only showed during playback). No-op when NOX
    isn't installed or the buttons aren't at their known original widths. Marker-
    gated + XML-parse-checked."""
    try:
        from resources.lib import nox_osd_collision_patcher, kodi_utils
    except Exception:
        return
    try:
        status = nox_osd_collision_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'nox_osd_collision_patcher: NOX OSD buttons re-sized so '
                '"הפרק הבא" no longer collides with the play controls',
                level='INFO')
            _maybe_reload_nox_skin()
        elif status in ('parse_failed', 'write_failed', 'read_failed'):
            kodi_utils.log('nox_osd_collision_patcher: ' + status,
                           level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log('nox_osd_collision_patcher failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _maybe_patch_nox_next_episode():
    """Repoint NOX's fullscreen-OSD "next episode" button from POV's dropped
    play_media&next=1 call to POV's working next-episode list. No-op when NOX
    isn't installed or the button was already repointed / changed upstream."""
    try:
        from resources.lib import nox_next_episode_patcher, kodi_utils
    except Exception:
        return
    try:
        status = nox_next_episode_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'nox_next_episode_patcher: OSD next-episode button repointed',
                level='INFO')
            _maybe_reload_nox_skin()
        elif status in ('write_failed', 'read_failed', 'unmatched'):
            kodi_utils.log('nox_next_episode_patcher: ' + status,
                           level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log('nox_next_episode_patcher failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _maybe_reload_nox_skin():
    """Skin XML is read at skin load, so a freshly-applied NOX OSD patch only
    shows after a reload. Reload once when NOX is the active skin. Otherwise the
    button simply appears on the next Kodi restart."""
    try:
        import xbmc
    except Exception:
        return
    try:
        if xbmc.getSkinDir() != 'skin.povil.nox':
            return
        xbmc.executebuiltin('ReloadSkin()')
    except Exception:
        pass


def _maybe_patch_choose_subs_buttons():
    """Wire the player's subtitle button to MoranSubs's chooser window:
    rewire FENtastic + Estuary (they pointed at the disabled DarkSubs) and
    rewire NOX's existing subtitles button (id 70046, which only opened
    ActivateWindow(2118)). NOX is rewired -- NOT given a new button -- because an
    added button widened the right-aligned OSD group and pushed "החלף מקור" into
    the play controls. All skin-gated, XML-parse-checked, self-healing. A reload
    is done only when the patched skin is the active one."""
    # FENtastic + Estuary: rewire the existing DarkSubs button to our chooser.
    try:
        from resources.lib import choose_subs_rewire_patcher, kodi_utils
        import xbmc
        results = choose_subs_rewire_patcher.ensure_patched()
        active = ''
        try:
            active = xbmc.getSkinDir()
        except Exception:
            active = ''
        # Keys are "skin_id:file"; reload once if the ACTIVE skin got patched.
        active_patched = False
        for key, status in (results or {}).items():
            skin_id = key.split(':', 1)[0]
            if status == 'patched':
                kodi_utils.log('choose_subs_rewire_patcher: rewired {0} to '
                               'MoranSubs chooser'.format(key), level='INFO')
                if skin_id == active:
                    active_patched = True
            elif status in ('parse_failed', 'write_failed', 'read_failed'):
                kodi_utils.log('choose_subs_rewire_patcher: {0} -> {1}'.format(
                    key, status), level='WARNING')
        if active_patched:
            try:
                _reload_skin_if_safe()
            except Exception:
                pass
    except Exception as e:
        try:
            kodi_utils.log('choose_subs_rewire_patcher failed: {0}'
                           .format(e), level='WARNING')
        except Exception:
            pass
    # NOX: rewire the existing subtitles button (no new button -> no collision).
    try:
        from resources.lib import nox_choose_subs_patcher, kodi_utils
        status = nox_choose_subs_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log('nox_choose_subs_patcher: NOX subtitles button '
                           'rewired to MoranSubs chooser', level='INFO')
            _maybe_reload_nox_skin()
        elif status in ('unmatched', 'parse_failed', 'write_failed',
                        'read_failed'):
            kodi_utils.log('nox_choose_subs_patcher: ' + status,
                           level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log('nox_choose_subs_patcher failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _maybe_patch_change_source_pause():
    """Make the player's "החלף מקור" (change source) button pause the video
    before opening the source-selection screen -- it used to pause but started
    playing through in the background. Injects a Player.Playing-gated
    PlayerControl(Play) onclick before the existing change-source onclick in
    NOX, Estuary, and FENtastic. Marker-gated, XML-parse-checked, self-healing.
    Must run AFTER the change-source button patchers so Estuary's inserted
    button exists. Reloads only the active skin if it was patched."""
    try:
        from resources.lib import change_source_pause_patcher, kodi_utils
        import xbmc
        results = change_source_pause_patcher.ensure_patched()
        active = ''
        try:
            active = xbmc.getSkinDir()
        except Exception:
            active = ''
        # Keys are "skin_id:file"; reload once if the ACTIVE skin got patched.
        active_patched = False
        for key, status in (results or {}).items():
            skin_id = key.split(':', 1)[0]
            if status == 'patched':
                kodi_utils.log('change_source_pause_patcher: {0} change-source '
                               'now pauses before opening sources'.format(
                                   key), level='INFO')
                if skin_id == active:
                    active_patched = True
            elif status in ('parse_failed', 'write_failed', 'read_failed'):
                kodi_utils.log('change_source_pause_patcher: {0} -> {1}'.format(
                    key, status), level='WARNING')
        if active_patched:
            try:
                _reload_skin_if_safe()
            except Exception:
                pass
    except Exception as e:
        try:
            kodi_utils.log('change_source_pause_patcher failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _reload_skin_if_safe():
    """ReloadSkin() -- but NEVER while the home window is showing. All our
    reloads here refresh player-OSD XML (VideoOSD.xml on Estuary/FENtastic/NOX)
    after a fresh patch. ReloadSkin() rebuilds every window, and on Estuary/
    FENtastic the home menu is a fixedlist (defaultcontrol 9000, focusposition=0)
    that then snaps focus to the FIRST tile -- the "home jumps to tile 1 after an
    update" bug. Kodi loads VideoOSD.xml fresh on the next OSD open regardless, so
    skipping the reload while on home costs nothing and removes the focus jump.
    (If we're not on home when a patch lands, reload normally.)"""
    try:
        import xbmc
        if xbmc.getCondVisibility('Window.IsVisible(home)'):
            return
        # Not while POV is being cycled: ReloadSkin() rebuilds every window,
        # and any POV-backed one raises "Unknown addon id" until the cycle
        # finishes. Skipping outright is fine here -- unlike the widget
        # patcher's reload, this one only refreshes player-OSD XML, which Kodi
        # re-reads on the next OSD open anyway.
        cycling = False
        try:
            from resources.lib import pov_reload
            cycling = pov_reload.is_cycling()
        except Exception:
            cycling = False
        if cycling:
            return
        xbmc.executebuiltin("ReloadSkin()")
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
def _maybe_patch_hub_search():
    """Restore the search button on Estuary, FENtastic and NOX at boot.

    The provider picker also calls this patcher after a choice; startup must
    cover the default POV choice and skin updates before the first click.
    """
    try:
        from resources.lib import fentastic_search_patcher, kodi_utils
        status = fentastic_search_patcher.ensure_patched()
        if status not in ('patched', 'unchanged', 'no_target'):
            kodi_utils.log('hub search patcher: {0}'.format(status), level='WARNING')
    except Exception as exc:
        try:
            kodi_utils.log('hub search patcher failed: {0}'.format(exc),
                           level='WARNING')
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


def _maybe_migrate_embedded_translation_mode():
    """One-shot bridge from the two hidden booleans to the explained mode list."""
    try:
        from resources.lib import kodi_utils
        mode = kodi_utils.embedded_translation_mode()
        kodi_utils.log(
            'embedded translation mode ready: {0}'.format(mode), level='INFO')
    except Exception as e:
        try:
            kodi_utils.log(
                'embedded mode migration failed: {0}'.format(e),
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


def _maybe_force_gender_ref_arabic():
    """One-shot: turn the Arabic-gender-reference setting (gender_ref_arabic) ON
    for EVERYONE -- including users who previously had it off. It tested clean
    (gender accuracy ~27% -> ~90%+, no quality regression, full fallback when no
    Arabic aligns), so we want it on by default for the whole base.

    Unlike the gentle pool migration this forces 'true' unconditionally (not just
    when still on the old default). It is still marker-gated so it fires ONCE:
    if a user deliberately turns it off afterwards, that choice sticks and we
    don't re-enable on the next startup."""
    try:
        from resources.lib import kodi_utils
    except Exception:
        return
    try:
        if kodi_utils.get_setting('_gender_ref_on_v1', '') == '1':
            return
        kodi_utils.set_setting('gender_ref_arabic', 'true')
        kodi_utils.set_setting('_gender_ref_on_v1', '1')
        kodi_utils.log('Arabic gender reference enabled for everyone '
                       '(migration v1)', level='INFO')
    except Exception as e:
        try:
            kodi_utils.log('gender_ref_arabic force-on migration failed: '
                           '{0}'.format(e), level='WARNING')
        except Exception:
            pass


def _maybe_tune_gemini3_defaults():
    """One-shot: move existing users to the validated Gemini 3 translation
    settings -- temperature 1.0 (Google's recommended default; 0.2 was our old
    default and degrades Gemini 3 reasoning) and thinking_level MEDIUM (the old
    'disabled'/0 left it at the expensive HIGH default, which truncates and
    garbles long chunks). Only flips values still on the OLD defaults, so a user
    who deliberately picked something else keeps it. Marker-gated -> fires once;
    a later manual change sticks."""
    try:
        from resources.lib import kodi_utils
    except Exception:
        return
    try:
        if kodi_utils.get_setting('_gemini3_tune_v1', '') == '1':
            return
        # temperature: bump 0.2 (old default) -> 1.0; leave any other choice.
        try:
            t = float(kodi_utils.get_setting('temperature', '') or '0.2')
        except (TypeError, ValueError):
            t = 0.2
        if abs(t - 0.2) < 0.005:
            kodi_utils.set_setting('temperature', '1.0')
        # thinking: '' / '0' / 'disabled' (old default -> HIGH) -> 'medium'.
        th = (kodi_utils.get_setting('thinking_budget', '') or '0').strip().lower()
        if th in ('', '0', 'disabled'):
            kodi_utils.set_setting('thinking_budget', 'medium')
        kodi_utils.set_setting('_gemini3_tune_v1', '1')
        kodi_utils.log('Gemini 3 defaults tuned (temp 1.0 + thinking medium, '
                       'migration v1)', level='INFO')
    except Exception as e:
        try:
            kodi_utils.log('gemini3 tune migration failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _maybe_bump_gemini_model():
    """One-shot: move existing users off the superseded default Gemini models to
    their newer, same-quota successors -- gemini-3.1-flash-lite -> 3.5-flash-lite
    (the free 500/day default) and 3.5-flash / 3.6-flash -> 3.8-flash (the paid
    regular-Flash pick; it was 3.7 until Google superseded that too, and this
    map points at the CURRENT pick rather than at a model the picker no longer
    offers -- landing a device on a dropped id and relying on the next
    migration to move it again is a correctness argument that depends on the
    order two functions happen to be called in). Both are drop-in upgrades (identical free-tier quota,
    better quality), so we rewrite the STORED model once. Only those two exact
    old ids are bumped; any other deliberate choice (3.1-flash, 2.5-*) is left
    alone, and an empty setting is left empty (translate falls back to the new
    default). Marker-gated -> fires once; a later manual pick sticks."""
    try:
        from resources.lib import kodi_utils
    except Exception:
        return
    try:
        # v2, NOT v1. The v1 marker is already '1' on every device that took
        # the 3.5 -> 3.6 bump, so reusing it would make this migration a no-op
        # for exactly the users who need it -- the ones already on 3.6. A new
        # id per bump is the only thing that makes a once-only migration
        # repeatable across releases.
        if kodi_utils.get_setting('_gemini_model_bump_v2', '') == '1':
            return
        cur = (kodi_utils.get_setting('model', '') or '').strip()
        new = {'gemini-3.1-flash-lite': 'gemini-3.5-flash-lite',
               'gemini-3.5-flash': 'gemini-3.8-flash',
               'gemini-3.6-flash': 'gemini-3.8-flash'}.get(cur)
        if new:
            kodi_utils.set_setting('model', new)
            kodi_utils.log('Gemini model bumped {0} -> {1} (migration v2)'.format(
                cur, new), level='INFO')
        kodi_utils.set_setting('_gemini_model_bump_v2', '1')
    except Exception as e:
        try:
            kodi_utils.log('gemini model bump migration failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _maybe_bump_gemini_model_38():
    """One-shot: move existing users off gemini-3.7-flash to gemini-3.8-flash.

    Google shipped 3.8 Flash as the current regular-Flash model and reclassified
    3.7 as "previous-generation"; the two sit on identical rate limits in every
    table on Google's own page (same TPM, same TPD, same free RPD), so this is a
    drop-in upgrade exactly like the 3.5/3.6 -> 3.7 bump before it. 3.7 keeps
    working, so nothing here is urgent -- but the picker no longer offers it,
    and leaving a stored id the list cannot show is how a settings screen ends
    up displaying a blank model.

    A NEW marker id, never a reused one: `_gemini_model_bump_v2` is already '1'
    on every device that took the previous bump, so reusing it would no-op this
    migration for precisely the users who need it. That mistake is written up in
    _maybe_bump_gemini_model() above; this is the same rule applied again.

    RETIRED, not "everything newer". The set below is every regular-Flash id
    the picker no longer offers. 3.6 and 3.5 Flash are in it because they were
    v2's job and v2 only fires once: a device that already ran v2 has left them,
    but listing them here means this migration is correct on its own rather than
    correct only because it happens to run after v2 in the same boot. Ordering
    is a fact about one file; a complete set is a fact about the migration.

    Every choice the picker still shows -- 3.5-flash-lite, 3.1-flash, either
    2.5 -- is a deliberate pick and is left alone, and an empty setting stays
    empty so translate.py's own default applies."""
    try:
        from resources.lib import kodi_utils
    except Exception:
        return
    try:
        if kodi_utils.get_setting('_gemini_model_bump_v3', '') == '1':
            return
        retired = ('gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash')
        cur = (kodi_utils.get_setting('model', '') or '').strip()
        if cur in retired:
            kodi_utils.set_setting('model', 'gemini-3.8-flash')
            kodi_utils.log('Gemini model bumped {0} -> gemini-3.8-flash '
                           '(migration v3)'.format(cur), level='INFO')
        kodi_utils.set_setting('_gemini_model_bump_v3', '1')
    except Exception as e:
        try:
            kodi_utils.log('gemini 3.8 model bump migration failed: {0}'
                           .format(e), level='WARNING')
        except Exception:
            pass


def _maybe_lower_chunk_lines():
    """One-shot: move existing users to the smaller 50-line translation chunk.
    Live testing showed big chunks (100+) of graphically-explicit dialogue trip
    Google's prompt-level PROHIBITED_CONTENT block, while 50-line chunks stay
    under the threshold and translate cleanly -- with NO loss of gender accuracy
    or quality (the Arabic gender oracle is per-entry and the cast/context carry
    the rest). Only lowers values still at the OLD defaults (>=100 -> 50); a user
    who deliberately picked something smaller keeps it. Marker-gated -> once."""
    try:
        from resources.lib import kodi_utils
    except Exception:
        return
    try:
        if kodi_utils.get_setting('_chunk_lines_50_v1', '') == '1':
            return
        try:
            cur = int(kodi_utils.get_setting('chunk_lines', '') or '100')
        except (TypeError, ValueError):
            cur = 100
        if cur >= 100:
            kodi_utils.set_setting('chunk_lines', '50')
            kodi_utils.log('chunk_lines lowered {0} -> 50 (block-avoidance '
                           'migration v1)'.format(cur), level='INFO')
        kodi_utils.set_setting('_chunk_lines_50_v1', '1')
    except Exception as e:
        try:
            kodi_utils.log('chunk_lines migration failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _maybe_enable_osd_autoclose():
    """Turn on the skin's built-in OSD auto-close (4s) so the player bars hide
    after a few seconds instead of staying until Back.

    THIS USED TO NAME ONE SKIN. It gated on `getSkinDir() != 'skin.fentastic'`
    and returned otherwise, so it only ever reached FENtastic users -- while
    skin.povil.nox ships the identical feature (same `OSDAutoClose` /
    `OSDAutoCloseTime` settings, same Timers.xml `autoclosevideoosd` timer),
    also off by default. Every Nox user has had the bar stay up since the
    feature shipped, and that is what the report was.

    So it detects the CAPABILITY instead of matching a name: if the active
    skin's own XML declares OSDAutoClose, it supports it. AF3 and Estuary do
    not and are skipped without a list saying so.

    Seeding is recorded IN THE SKIN's settings, not ours. That matters both
    ways: the mark is per-skin for free, so switching to a skin that has never
    been seeded seeds it; and if a skin is reinstalled or its settings are
    reset, our mark disappears with them and the default is re-seeded. A
    deliberate opt-out AFTER seeding is left alone, because the mark is still
    there. An add-on-side marker could do neither -- which is how one lost
    write became permanent.

    The one population the skin-side mark cannot describe is the users the OLD
    migration already reached: FENtastic users carrying `_fen_osd_autoclose_v1`
    have been seeded, but on the add-on side, where the new code cannot see it.
    Treating them as unseeded would re-enable the setting for anyone who turned
    it back off on purpose, so that marker is read once and converted into the
    skin-side mark WITHOUT rewriting the values. It is the same promise the old
    marker made, kept in the new place.

    The mark is a skin BOOL, and that is not a stylistic choice. Kodi keeps
    skin bools and skin strings in two separate maps (CSkinInfo::m_bools and
    m_strings, each with its own name->id table), and `Skin.HasSetting` is
    wired to the bool one. A mark written with Skin.SetString is invisible to
    it -- the guard would read false forever and this migration would re-force
    the values on EVERY boot, which is the opposite of leaving an opt-out
    alone. _maybe_default_nox_poster_rating pairs them correctly; so does this.
    """
    try:
        from resources.lib import kodi_utils
        import xbmc
        import xbmcvfs
    except Exception:
        return
    try:
        skin = xbmc.getSkinDir() or ''
        if not skin:
            return
        if xbmc.getCondVisibility('Skin.HasSetting(AISubsOsdSeeded)'):
            return  # already seeded for this skin; respect what it is now
        if (skin == 'skin.fentastic'
                and kodi_utils.get_setting('_fen_osd_autoclose_v1', '') == '1'):
            # Already seeded by the old add-on-side migration. Carry the mark
            # over and touch nothing: whatever the value is now is the user's.
            xbmc.executebuiltin('Skin.SetBool(AISubsOsdSeeded)')
            return
        # A skin that does NOT have the feature never gets a skin-side mark --
        # there is nothing to mark -- so without this it is re-scanned on every
        # single boot, forever. Remember the answer per skin VERSION, so a skin
        # update that adds the feature is still picked up (one scan per skin
        # release, not one per boot).
        stamp = '%s=%s' % (skin, _other_addon_version(skin))
        no_feature = (kodi_utils.get_setting('_osd_autoclose_nofeature', '')
                      or '').split(',')
        if stamp in no_feature:
            return
        # Both roots, the same pair pov_reload and the wizard already walk: a
        # skin shipped INSIDE Kodi lives under special://xbmc, not
        # special://home, and looking in one place only means such a skin can
        # never be detected on any boot. Estuary happens not to have the
        # feature, so today this costs nothing -- but "we never looked" and
        # "it isn't there" were the same answer, which is how the whole bug
        # started.
        roots = [xbmcvfs.translatePath(r + skin + '/')
                 for r in ('special://home/addons/', 'special://xbmc/addons/')]
        supports = False
        scanned = 0
        for base, dirs, files in _walk_all(roots):
            # A skin's art outweighs its XML by orders of magnitude and holds
            # none of it. Pruning these keeps the walk to the markup, which
            # matters because a skin WITHOUT the feature never gets a mark and
            # is therefore re-scanned on every single start.
            dirs[:] = [d for d in dirs if d.lower() not in
                       ('media', 'themes', 'fonts', 'backgrounds', 'extras',
                        'colors', 'sounds', '.git')]
            for fn in files:
                if not fn.endswith('.xml'):
                    continue
                try:
                    with open(os.path.join(base, fn), encoding='utf-8',
                              errors='replace') as fh:
                        scanned += 1
                        if 'OSDAutoClose' in fh.read():
                            supports = True
                            break
                except OSError:
                    continue
            if supports:
                break
        others = _without(no_feature, skin)
        if not supports:
            # Only cache a negative we actually MEASURED. Zero files read means
            # the walk found nothing to read -- a skin installed somewhere
            # neither root covers, or one we could not open -- not that the
            # skin lacks the feature. A cached "no" from an empty walk would
            # be permanent for that skin version; leaving it uncached only
            # costs another look on the next start.
            if scanned:
                # Capped, and a stale stamp for this same skin is dropped, so
                # a skin that is updated often does not fill the list with its
                # own past versions.
                kodi_utils.set_setting('_osd_autoclose_nofeature',
                                       ','.join(others[-9:] + [stamp]))
            return  # this skin has no such feature -- nothing to turn on
        if others != [s for s in no_feature if s]:
            # This skin was recorded as featureless and now HAS the feature --
            # a skin update added it. Drop the obsolete entry instead of
            # letting it age out: the cache holds ten, and stale entries push
            # live ones out, which costs the rescans the cache exists to
            # prevent.
            kodi_utils.set_setting('_osd_autoclose_nofeature',
                                   ','.join(others))
        xbmc.executebuiltin('Skin.SetBool(OSDAutoClose)')
        xbmc.executebuiltin('Skin.SetString(OSDAutoCloseTime,4)')
        # executebuiltin queues; the read below can otherwise race the write
        # and report a failure that did not happen. Same 150ms the NOX rating
        # rollout settled on next door.
        xbmc.sleep(150)
        # Only claim it once the skin actually reports the setting: a write
        # issued while the skin is still loading can be lost, and marking
        # regardless is what made a single lost write permanent.
        if not xbmc.getCondVisibility('Skin.HasSetting(OSDAutoClose)'):
            kodi_utils.log(
                'OSD auto-close: %s did not take the setting, will retry on '
                'the next start' % skin, level='WARNING')
            return
        xbmc.executebuiltin('Skin.SetBool(AISubsOsdSeeded)')
        kodi_utils.log('OSD auto-close enabled (4s) for %s' % skin,
                       level='INFO')
    except Exception as e:
        try:
            kodi_utils.log('OSD auto-close seeding failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass




def _maybe_force_pool_share():
    """One-shot rollout: turn community-pool SHARING on for EVERYONE, to grow the
    shared Hebrew pool as fast as possible. With pool_share on, every human
    Ktuvit Hebrew sub for a played title is mirrored to the pool in the
    background (the harvest), and AI translations are shared too -- so the pool
    fills for all users. Force-enabled once via a fresh marker (overriding a
    prior opt-out); a later MANUAL opt-out AFTER this run sticks. New installs
    already default on via settings.xml. Build-edition only (the slim standalone
    has its own service)."""
    try:
        from resources.lib import kodi_utils
        if kodi_utils.get_setting('_pool_share_force_v1', '') == '1':
            return
        kodi_utils.set_setting('pool_share', 'true')
        kodi_utils.set_setting('_pool_share_force_v1', '1')
        kodi_utils.log('pool_share force-enabled for everyone (rollout v1)',
                       level='INFO')
    except Exception as e:
        try:
            kodi_utils.log('pool_share force migration failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _maybe_default_nox_poster_rating():
    """One-shot rollout: FORCE the NOX skin's rating/score circle ON for posters
    so the content score shows on artwork -- for EVERYONE, the first time NOX is
    the active skin after this update. The rating is considered an important
    default, so this run also re-enables it for users who had previously turned
    it off (it sets 'circle_rating' and clears the mutually-exclusive
    'circle_none' / 'circle_userrating'). Marker-gated by a FRESH version (v2),
    so it re-applies exactly once even for users who already passed the earlier
    v1 default -- and a later MANUAL opt-out AFTER this run sticks again (we
    never force it back on on subsequent startups).

    Skin settings can only be read/written for the ACTIVE skin (Skin.HasSetting
    / Skin.SetBool / Skin.Reset target whatever skin is loaded), so this no-ops
    on every startup until NOX is actually the active skin -- then it applies
    and marks itself done. We confirm the bool actually took before marking
    done, so a write that didn't persist is retried on a later startup. No-op
    for users who never run NOX (the marker is simply never set)."""
    try:
        import xbmc
        from resources.lib import kodi_utils
    except Exception:
        return
    try:
        if kodi_utils.get_setting('_nox_poster_rating_default_v2', '') == '1':
            return
        # Only meaningful while NOX is the active skin -- otherwise the
        # Skin.* condition/builtin would read/write the wrong skin. Try again
        # on a later startup (cheap, marker stays unset).
        if xbmc.getSkinDir() != 'skin.povil.nox':
            return
        # Force the rating circle ON (override a prior 'off'/'user rating'
        # choice this once). circle_rating / circle_userrating / circle_none
        # are mutually exclusive, so clear the other two and set rating.
        xbmc.executebuiltin('Skin.Reset(circle_none)')
        xbmc.executebuiltin('Skin.Reset(circle_userrating)')
        xbmc.executebuiltin('Skin.SetBool(circle_rating)')
        xbmc.sleep(150)
        # Only mark done once the setting is actually present, so a write that
        # failed to take is retried next startup instead of being lost.
        if xbmc.getCondVisibility('Skin.HasSetting(circle_rating)'):
            kodi_utils.set_setting('_nox_poster_rating_default_v2', '1')
            kodi_utils.log('NOX poster rating circle force-enabled for '
                           'everyone (rollout v2)', level='INFO')
    except Exception as e:
        try:
            kodi_utils.log('NOX poster rating default migration failed: {0}'
                           .format(e), level='WARNING')
        except Exception:
            pass


def _maybe_reenable_ktuvit():
    """Ktuvit is working again -> turn the source back ON for everyone, ONCE
    (marker _ktuvit_on_v4). Marker-gated, so a user who turns it OFF again AFTER
    this keeps it off -- we never force it back on on later startups. (Fresh
    marker so it runs once even for users who got the earlier off/on toggles.)"""
    try:
        from resources.lib import kodi_utils
        if kodi_utils.get_setting('_ktuvit_on_v4', '') == '1':
            return
        kodi_utils.set_setting('ktuvit', 'true')
        kodi_utils.set_setting('_ktuvit_on_v4', '1')
        kodi_utils.log('Ktuvit source re-enabled (on v4)', level='INFO')
    except Exception:
        pass


def _maybe_default_builtin_engine():
    """One-shot rollout: move EVERYONE from DarkSubs to MoranSubs's own built-in
    engine. Turns use_builtin_engine ON exactly once (and seeds engine_autosub
    ON so auto-search-and-apply works like DarkSubs did). Marker-gated, so a
    later manual opt-out STICKS -- if the user turns the engine (or autosub) off
    afterwards we never force it back on, on this or any future startup.

    Must run BEFORE _maybe_set_default_subtitle_service() and the _engine_on
    read in main(), so the rest of THIS startup already treats the engine as on
    (MoranSubs default).

    Build-edition only: the standalone repo-channel addon ships SLIM_SERVICE
    (no engine code), so it never runs this and stays on the OFF default."""
    try:
        from resources.lib import kodi_utils
    except Exception:
        return
    try:
        if kodi_utils.get_setting('_builtin_engine_rollout_v2', '') == '1':
            return
        # Flip the master engine toggle on (covers users still on the old
        # default 'false', AND users where it drifted off so DarkSubs came back
        # with no translation -- re-forced once via the v2 marker).
        if kodi_utils.get_setting('use_builtin_engine', 'false') != 'true':
            kodi_utils.set_setting('use_builtin_engine', 'true')
        # Auto-search & apply on play, like DarkSubs's autosub. Defaults to
        # 'true' already (and was hidden while the engine was off), so this is
        # normally a no-op; flip only if a tester explicitly turned it off.
        if kodi_utils.get_setting('engine_autosub', 'true') == 'false':
            kodi_utils.set_setting('engine_autosub', 'true')
        kodi_utils.set_setting('_builtin_engine_rollout_v2', '1')
        kodi_utils.log('built-in engine enabled for everyone (rollout v2)',
                       level='INFO')
    except Exception as e:
        try:
            kodi_utils.log('builtin engine rollout failed: {0}'.format(e),
                           level='WARNING')
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
        EXCEPTION: if the user turned on `keep_darksubs`, leave DarkSubs ENABLED
        even with the engine on, so they keep "regular" Hebrew subtitle search
        alongside the AI -- and it stays enabled across restarts/updates.

    Cheap, idempotent, runs early every startup; only writes on a mismatch."""
    if xbmc is None:
        return
    try:
        from resources.lib import kodi_utils
        engine_on = kodi_utils.get_bool('use_builtin_engine', False)
        keep = kodi_utils.get_bool('keep_darksubs', False)
    except Exception:
        engine_on = False
        keep = False
    desired = (not engine_on) or keep
    # Both competing Hebrew subtitle add-ons get the same treatment: enabled
    # when the engine is off (default), disabled when the engine is on (so only
    # MoranSubs runs -- no duplicate/competing searches).
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
                continue  # not installed / unknown -> leave alone
            if bool(addon.get('enabled')) == desired:
                continue  # already in the desired state
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


def _point_subtitle_button(engine_on):
    """Make the skins' player "Choose subtitles" button open the right thing.

    The build skins ship the button gated two ways:
      * Estuary / FENtastic(VideoOsd3): Skin.HasSetting(ChooseSubtitlesButtonOpensKodiWindow)
      * FENtastic(VideoOsd1):           Skin.String(subtitlesearch) == kodisubtitle|darksubs
    When the engine is ON, DarkSubs is disabled, so the DarkSubs branch is a
    dead button. Set both skin settings to the "Kodi native subtitle window"
    side (it runs MoranSubs as the default service). When OFF, restore DarkSubs.
    Only touches the ACTIVE skin; cheap; safe if the setting doesn't exist."""
    if xbmc is None:
        return
    try:
        if engine_on:
            xbmc.executebuiltin('Skin.SetBool(ChooseSubtitlesButtonOpensKodiWindow)')
            xbmc.executebuiltin('Skin.SetString(subtitlesearch,kodisubtitle)')
        else:
            xbmc.executebuiltin('Skin.Reset(ChooseSubtitlesButtonOpensKodiWindow)')
            xbmc.executebuiltin('Skin.SetString(subtitlesearch,darksubs)')
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
    """Switch POV back on if OUR OWN CYCLE left it off. Not otherwise.

    POV is THE content add-on: installed but disabled means every home row and
    every "My Movies/My Shows" tile is empty and nothing plays, on all skins.
    pov_reload retries inside its own cycle, but a cycle that is interrupted --
    the box is switched off mid-update, the process is killed -- leaves POV off
    with nothing to bring it back. This is that net.

    IT USED TO HEAL UNCONDITIONALLY, AND THAT WAS A SILENT SETTINGS CHANGE.
    "POV is off" has two causes and this could not tell them apart, so it
    treated the user's own choice as damage and undid it. Worse, it undid it
    invisibly and early: hot_reload's first act is to cycle this service, so a
    fresh main() -- and this function with it -- runs to completion before the
    wizard's own POV checks are ever reached. A user who switched POV off found
    it back on after any update, with nothing on screen and nothing in the log
    to say why. The wizard's _cycle_addon refuses to do exactly this, in as many
    words: "re-enabling something somebody turned off by hand is not ours to
    do". This now honours the same rule.

    So it acts only on evidence. pov_reload writes a record before it disables
    POV and clears it only once POV can be constructed again; that record, and
    the wizard's pending_enable list for the add-ons IT cycles, are the only
    things that make a disabled POV ours to fix.
    """
    if xbmc is None:
        return
    try:
        from resources.lib import pov_reload
        ours = pov_reload.cycle_left_pov_off()
    except Exception:
        ours = False
    if not ours:
        return
    try:
        import json as _json
        # WAIT FOR JSON-RPC. This runs early in startup, and a single
        # unanswered call used to be indistinguishable from "POV is fine" --
        # no exception, no log, no retry until the next full restart. The
        # wizard's own heal polls for readiness for the same reason.
        get = _json.dumps({
            'jsonrpc': '2.0', 'id': 1,
            'method': 'Addons.GetAddonDetails',
            'params': {'addonid': 'plugin.video.pov',
                       'properties': ['enabled']},
        })
        addon = {}
        monitor = xbmc.Monitor()
        for attempt in range(20):
            data = _json.loads(xbmc.executeJSONRPC(get) or '{}')
            addon = (data.get('result') or {}).get('addon') or {}
            if 'enabled' in addon:
                break
            if monitor.waitForAbort(0.5):
                return
        if 'enabled' not in addon:
            # Still no answer. The record stays, so the next start tries again.
            xbmc.log('[' + ADDON_ID + '] POV is recorded as left off by our '
                     'cycle, but Kodi is not answering yet; keeping the record',
                     level=xbmc.LOGWARNING)
            return
        if addon.get('enabled'):
            # Somebody already switched it back on. Nothing to do, and the
            # record has served its purpose.
            pov_reload.clear_cycle_record()
            return
        en = _json.dumps({
            'jsonrpc': '2.0', 'id': 1,
            'method': 'Addons.SetAddonEnabled',
            'params': {'addonid': 'plugin.video.pov', 'enabled': True},
        })
        xbmc.executeJSONRPC(en)
        data = _json.loads(xbmc.executeJSONRPC(get) or '{}')
        back = ((data.get('result') or {}).get('addon') or {}).get('enabled')
        if back:
            pov_reload.clear_cycle_record()
            xbmc.log('[' + ADDON_ID + '] re-enabled POV after an interrupted '
                     'cycle of ours', level=xbmc.LOGINFO)
        else:
            # KEEP THE RECORD ON A FAILED ENABLE. Clearing it here is how a
            # temporary problem becomes a permanent one: the evidence goes and
            # nothing ever tries again.
            xbmc.log('[' + ADDON_ID + '] POV would not switch back on; the '
                     'record stays for the next start', level=xbmc.LOGWARNING)
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


def _maybe_revert_pov_always_resume():
    """One-shot: undo our earlier always-resume override. A prior migration set
    POV "Automatically Resume Playback" to Always (auto_resume=1) for one-click
    continue -- but that makes POV resume even when the user explicitly picks
    "Play from start" from the context menu (it jumps back to the stop point).
    Set the two auto_resume settings back to POV's default (0 = ask), so the
    resume prompt appears AND "Play from start" really starts from 0. Marker-
    gated; only reverts a value still on OUR forced '1', so a later manual
    choice (e.g. a user who genuinely wants Always) sticks."""
    if xbmc is None:
        return
    try:
        from resources.lib import kodi_utils
        import xbmcaddon
    except Exception:
        return
    try:
        if kodi_utils.get_setting('_pov_resume_revert_v1', '') == '1':
            return
        try:
            pov = xbmcaddon.Addon('plugin.video.pov')
        except Exception:
            return  # POV not installed (standalone AI install) -> retry later
        for key in ('auto_resume_movie', 'auto_resume_episode'):
            try:
                if (pov.getSetting(key) or '').strip() == '1':
                    pov.setSetting(key, '0')
            except Exception:
                pass
        kodi_utils.set_setting('_pov_resume_revert_v1', '1')
        kodi_utils.log('POV always-resume reverted to ask '
                       '("Play from start" fix)', level='INFO')
    except Exception as e:
        try:
            kodi_utils.log('POV resume revert failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass


def _maybe_patch_darksubs_embedded_demote():
    """Self-healing patch of DarkSubs's engine.py so embedded ('[LOC]')
    subtitle entries sink to the BOTTOM of their language group instead
    of floating to the top on their hard-coded 101% sync. On this
    build the embedded track can't be AI-translated (DarkSubs
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

def _maybe_patch_fentastic_simpleplayer_source():
    """Add the 'החלף מקור' (change source) button to FENtastic's SIMPLE player
    OSD (Includes_VideoOsd3.xml) -- the only player variant that shipped without
    one. Inserted into the auto-laid-out action grouplist (no overlap), reusing
    the skin's own __ChooseSourceOsd__ behaviour. Skin-gated, XML-parse-checked,
    self-healing. No-op when FENtastic isn't installed."""
    try:
        from resources.lib import (
            fentastic_simpleplayer_source_patcher, kodi_utils)
    except Exception:
        return
    try:
        status = fentastic_simpleplayer_source_patcher.ensure_patched()
        if status == 'patched':
            kodi_utils.log(
                'fentastic_simpleplayer_source_patcher: change-source button '
                'added to the simple player OSD', level='INFO')
        elif status in ('unmatched', 'compile_failed', 'write_failed',
                        'read_failed'):
            kodi_utils.log(
                'fentastic_simpleplayer_source_patcher: ' + status,
                level='WARNING')
    except Exception as e:
        try:
            kodi_utils.log(
                'fentastic_simpleplayer_source_patcher failed: {0}'.format(e),
                level='WARNING')
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
        _reload_skin_if_safe()
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

    # Start the Hebrew-availability warm drainer FIRST -- before the seconds of
    # build startup repairs below. Otherwise the drainer thread isn't spawned yet
    # when the user plays something right after boot, so the first title's warm
    # sits queued for several seconds and misses the source window's first-entry
    # wait. It's a cheap idle poll until a job appears.
    try:
        _start_he_warm_drainer(xbmc.Monitor())
    except Exception:
        pass

    # SubSync deep-verify worker: resolve() delivers the subtitle IMMEDIATELY
    # and queues the slow verification (oracle download / file probe / audio)
    # here, so the autosub overlay / picker never waits on it; on a proven fix
    # the worker swaps the playing subtitle in place (subsync.run_deep_job).
    try:
        _start_subsync_drainer(xbmc.Monitor())
    except Exception:
        pass

    # SubSync S3 human anchor: watch the viewer's manual subtitle delay and
    # turn a settled fix / a long clean watch into a community sync report.
    try:
        _start_subsync_delay_watch(xbmc.Monitor())
    except Exception:
        pass

    # Initial prune.
    _prune_once()
    _prune_source_memory_once()

    build_mode = _is_kodi_pov_il_build()
    if build_mode:
        _ensure_build_marker()

    # Grow the shared Hebrew pool: force community-pool sharing ON for everyone
    # once (a later manual opt-out sticks). Must run before the harvest/drainer
    # below so it mirrors Ktuvit subs to the pool already this session.
    _maybe_force_pool_share()

    # ROLLOUT: switch everyone to MoranSubs's built-in engine (one-shot, marker-
    # gated). Must run before _ensure_darksubs_enabled() so that when it flips
    # the engine on, DarkSubs is disabled THIS startup. A later manual opt-out
    # sticks (marker prevents re-forcing).
    _maybe_default_builtin_engine()
    _ensure_darksubs_enabled()
    # Only patch/reload DarkSubs when it is enabled. The built-in engine turns
    # it off unless the viewer explicitly chose to keep it alongside MoranSubs.
    try:
        from resources.lib import kodi_utils as _ku
        _engine_on = _ku.get_bool('use_builtin_engine', False)
        _darksubs_active = not _engine_on or _ku.get_bool('keep_darksubs', False)
    except Exception:
        _engine_on, _darksubs_active = False, True
    if _darksubs_active:
        _maybe_patch_darksubs()
        _maybe_patch_darksubs_download_sub()
        _maybe_patch_darksubs_opensubtitles()
        _maybe_patch_darksubs_embedded_demote()
        _maybe_patch_darksubs_embedded_insert()
        _maybe_patch_darksubs_subwindow_demote()
        _maybe_surface_darksubs_status()

    # Ktuvit is back -> re-enable the source for everyone once (a later manual
    # opt-out sticks).
    _maybe_reenable_ktuvit()

    # When the engine is on, make MoranSubs the default subtitle service so it
    # opens/searches first in the dialog.
    _maybe_set_default_subtitle_service()

    # Same safety net for POV: our pov_reload cycle (for remember_source) could
    # have left POV disabled on a slow box, which empties every home row + tile
    # and breaks playback on ALL skins. Bring it back if it's installed and off.
    _ensure_pov_enabled()

    # Keep the default search target correct even before a user opens the
    # POV/Umbrella picker, and heal skin XML after an upstream skin update.
    _maybe_patch_hub_search()

    # Heal the FENtastic player choice only if it's empty (prevents the
    # "player with nothing" bug) -- never overrides a value the user picked.
    # The quickfix no longer ships the skin settings file, so this is what
    # guarantees a valid default without reverting manual choices on update.
    _maybe_default_fentastic_player()

    # When the built-in engine is ON, DarkSubs is intentionally DISABLED
    # (Phase C). In that case we must NOT touch DarkSubs at all: patching it
    # and its reload cycle (disable+enable) would re-enable it -- fighting the
    # disable -- and run its code while disabled, which throws
    # "Unknown addon id 'service.subtitles.All_Subs'". So the entire DarkSubs
    # integration block is skipped when the engine is on. (Existing users with
    # the engine OFF are unaffected: DarkSubs stays enabled + patched as before.)
    # Point the skins' player "Choose subtitles" button at the right target.
    # The build skins gate it: it opens DarkSubs's picker unless the skin
    # setting says to open Kodi's native subtitle window. With the engine on,
    # DarkSubs is DISABLED -- so the DarkSubs button does nothing ("doesn't
    # work"). Flip the skin settings so the button opens the NATIVE Kodi
    # subtitle dialog (which now runs MoranSubs). Reverts to DarkSubs when the
    # engine is off. Affects the active skin (Estuary / FENtastic).
    _point_subtitle_button(_engine_on)


    # Pre-warm the built-in sources engine (only when the user enabled it) so
    # the first subtitle search doesn't pay the heavy import cost inline.
    _maybe_prewarm_engine()

    if _darksubs_active:
        _maybe_patch_darksubs_filename()

    # Fix the subtitle-picker dialog HEADER (rendered by Kodi from
    # the skin's DialogSubtitles.xml) to prefer our subs.player_filename
    # property over the built-in Player.Filename. Without this, even
    # if our other patchers set the property, the dialog title still
    # shows the URL basename / UUID.
    _maybe_patch_skin_dialog_subtitles()

    if _darksubs_active:
        _maybe_patch_darksubs_picker_label()
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

    # That change-source button widened NOX's right-aligned OSD group, pushing
    # "הפרק הבא" left into the play controls during playback. Re-size the right-
    # group buttons back to their original total width to clear it. Runs AFTER
    # the change-source patcher so the button exists. Skin-gated, XML-checked.
    _maybe_patch_nox_osd_collision()

    # Repoint NOX's OSD "next episode" button: it used POV's old
    # play_media&next=1 (dropped in POV 6.07, so it errored). Point it at POV's
    # working next-episode list instead. Skin-gated, idempotent.
    _maybe_patch_nox_next_episode()

    # Turn NOX's rating/score circle ON for posters by default (one-shot, only
    # while NOX is the active skin; a later manual change sticks).
    _maybe_default_nox_poster_rating()

    _maybe_patch_estuary_change_source()
    _maybe_patch_fentastic_simpleplayer_source()

    # Point the player's subtitle button at MoranSubs's own chooser window
    # (FENtastic + Estuary pointed at the now-disabled DarkSubs; NOX's existing
    # subtitles button is rewired in place, not duplicated, to avoid widening
    # its OSD group). Skin-gated, XML-parse-checked, self-healing.
    _maybe_patch_choose_subs_buttons()

    # Make "החלף מקור" pause before opening the source screen (it regressed to
    # playing through in the background). Runs AFTER the change-source button
    # patchers above so Estuary's inserted button is present to patch.
    _maybe_patch_change_source_pause()

    if _darksubs_active:
        _maybe_patch_all_subs_samefile()
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


    if build_mode:
        # CONTAINED HERE, NOT IN THE LOOP. The pass re-raises a BaseException
        # from a step on purpose, so that _publish_repairs_state is not
        # reached and the pass never looks finished. That is right. What was
        # wrong is where it landed: nothing on this path catches it, so a
        # single misbehaving repair step took main() down with it -- and
        # everything BELOW this line is what actually puts Hebrew subtitles on
        # screen. SubsFilenamePublisher, the autoplay listener, the pool
        # drainer and the maintenance loop are not related to any repair, and
        # none of them ran for the rest of that session.
        #
        # HANDOFF records a patcher raising SystemExit as something that has
        # actually happened here, so this is not hypothetical. Both properties
        # are kept: the pass still does not publish, and the service still
        # starts.
        try:
            _run_build_startup_repairs()
        except BaseException as e:
            try:
                from resources.lib import kodi_utils
                kodi_utils.log(
                    'the startup repair pass ended early ({0}: {1}); the '
                    'subtitle service is starting anyway and the repairs are '
                    'not recorded as done'.format(type(e).__name__, e),
                    level='WARNING')
            except Exception:
                pass

    # Same idea for POV: if we patched its sources.py and the user opted into
    # remember-source, cycle POV (deferred, idle-only) so it re-imports the
    # patched code this session. No-op unless a patcher armed it.
    #
    # ARMED HERE, AFTER THE BUILD REPAIRS, AND THAT POSITION IS THE POINT.
    # Arming raises a flag that pov_reload.wait_until_settled() blocks on, and
    # three of its four callers are steps INSIDE _run_build_startup_repairs --
    # run inline on this thread, each with a 30s budget that is not shared. So
    # arming first meant every one of them could spend its budget waiting for a
    # cycle that had not started, come back False, leave its work undone, and
    # cost the subtitle service half a minute apiece for the privilege. That was
    # survivable while the cycle waited only for the home window to appear; it
    # is not now that it waits for the home screen to SETTLE.
    #
    # Arming last also closes a gap that was always there: note_patched() calls
    # made by anything running after this line were simply never seen, because
    # nothing asks again.
    try:
        from resources.lib import pov_reload
        pov_reload.reload_if_patched()
    except Exception:
        pass

    # If malformed Umbrella/Coco settings were repaired on disk, reconstruct
    # their CAddon objects this session after the POV cycle has settled. The
    # worker touches enabled add-ons only and records every disable first.
    try:
        from resources.lib import source_settings_reload
        source_settings_reload.reload_if_repaired()
    except Exception:
        pass

    # One-shot RTL punctuation repair of any cached translations
    # that were written before the post-processor caught their
    # specific edge case. Marker-gated so it only runs once.
    _maybe_unpatch_fentastic_notification()
    _maybe_repair_rtl_cache()

    # One-shot: flip `fast_first_chunk` default from off -> on for
    # existing users on the old default. Marker-gated.
    _maybe_default_fast_first_chunk()

    # Preserve the legacy embedded toggles, then make the explained mode selector
    # canonical. Runs for both build and standalone installations.
    _maybe_migrate_embedded_translation_mode()

    # One-shot: turn the community pool ON (pull + share) for existing users
    # still on the old default-off. New installs get it via settings.xml
    # defaults. Marker-gated so a later manual opt-out sticks.
    _maybe_default_pool_on()

    # One-shot: turn the Arabic-gender-reference setting ON for everyone (it
    # tested clean and lifts gender accuracy a lot). Forced once; a later manual
    # opt-out sticks. Marker-gated.
    _maybe_force_gender_ref_arabic()

    # One-shot: move existing users to the validated Gemini 3 translation
    # settings (temperature 1.0 + thinking medium). Marker-gated; respects a
    # deliberate manual choice.
    _maybe_tune_gemini3_defaults()
    # One-shot: bump the superseded default models to their same-quota
    # successors (3.1-flash-lite -> 3.5-flash-lite, 3.5/3.6-flash -> 3.8-flash).
    _maybe_bump_gemini_model()
    # And again for 3.8, which replaced 3.7 in the picker. Runs after the line
    # above so a device still on 3.5-flash lands on 3.8 in ONE boot rather than
    # two; it does not DEPEND on that order, because its retired set covers the
    # older ids as well.
    _maybe_bump_gemini_model_38()
    # Lower chunk size to 50 (block-avoidance), one-shot for existing installs.
    _maybe_lower_chunk_lines()

    # One-shot per skin: enable the active skin's own OSD auto-close (4s) so the
    # player bars hide after a few idle seconds. Detected from the skin's XML,
    # not from a list of skin names -- Nox ships the same feature FENtastic does
    # and was missed by the old name check.
    _maybe_enable_osd_autoclose()

    # One-shot: enable POV Auto Play + Always-Resume so "Continue Watching" is
    # one click (no source dialog, resumes where you stopped). Marker-gated.
    _maybe_default_pov_autoplay()

    # One-shot fix: undo the 0.2.158 mistake that forced POV Auto Play on
    # (it skipped the source dialog even on first watch). Restores the dialog.
    _maybe_revert_pov_autoplay()

    # One-shot: undo our forced always-resume so "Play from start" really starts
    # from 0 (it was resuming to the stop point). Marker-gated.
    _maybe_revert_pov_always_resume()

    # One-shot first-launch dialog for Arctic Fuse 3. Skin-gated +
    # marker-gated so it only fires for users who have actually
    # switched to AF3 (via the wizard's Switch Skin dialog or Kodi's
    # own Interface settings) and haven't been prompted before. POV's
    # Connect Services is opened on the user's behalf for the
    # service(s) they pick. Best-effort: this addon doesn't own AF3's
    # OAuth flows -- POV does.
    # POV's modular debrid hook handles the build's startup status popups.

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

    # Drain the persistent pool upload queue here, on the long-lived service.
    # Shared Ktuvit subtitles are queued to disk the moment they're downloaded
    # (so they survive the user leaving the video or restarting Kodi) and
    # uploaded from this thread one at a time with a throttle -- never bursting
    # past Telegram's bot rate limit. Best-effort; never blocks.
    _start_service_mirror_keeper(monitor)
    _start_pool_queue_drainer(monitor)
    # (the Hebrew warm drainer was already started at the top of main(), before
    # the build startup repairs, so it's alive for the first play of the session)

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
try:
    from resources.lib import modular_service_handoff
    _modular_service_yield = modular_service_handoff.maybe_yield()
except Exception:
    _modular_service_yield = False
if not _modular_service_yield:
    main()
