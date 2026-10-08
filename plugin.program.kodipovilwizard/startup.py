################################################################################
#      Copyright (C) 2019 drinfernoo                                           #
#                                                                              #
#  This Program is free software; you can redistribute it and/or modify        #
#  it under the terms of the GNU General Public License as published by        #
#  the Free Software Foundation; either version 2, or (at your option)         #
#  any later version.                                                          #
#                                                                              #
#  This Program is distributed in the hope that it will be useful,             #
#  but WITHOUT ANY WARRANTY; without even the implied warranty of              #
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the                #
#  GNU General Public License for more details.                                #
#                                                                              #
#  You should have received a copy of the GNU General Public License           #
#  along with XBMC; see the file COPYING.  If not, write to                    #
#  the Free Software Foundation, 675 Mass Ave, Cambridge, MA 02139, USA.       #
#  http://www.gnu.org/copyleft/gpl.html                                        #
################################################################################

import xbmc
import xbmcgui

import time
from datetime import datetime
from datetime import timedelta

import os
import sys

try:  # Python 3
    from urllib.parse import quote_plus
except ImportError:  # Python 2
    from urllib import quote_plus

from resources.libs.common.config import CONFIG
from resources.libs import clear
from resources.libs import check
from resources.libs import db
from resources.libs.gui import window
from resources.libs.common import logging
from resources.libs.common import tools
from resources.libs import skin
from resources.libs import update


def show_notification():
    note_id, msg = window.split_notify(CONFIG.NOTIFICATION)
    if note_id:
        try:
            remote_id = int(note_id)
            current_id = int(CONFIG.NOTEID or 0)
        except (TypeError, ValueError):
            logging.log('[Notifications] Invalid note ID: {0}'.format(note_id),
                        level=xbmc.LOGINFO)
            return
        if remote_id == current_id:
            if CONFIG.NOTEDISMISS == 'false':
                window.show_notification(msg)
            else:
                logging.log('[Notifications] No new notifications.', level=xbmc.LOGINFO)
        elif remote_id > current_id:
            logging.log('[Notifications] Showing notification {0}'
                        .format(note_id))
            CONFIG.set_setting('noteid', note_id)
            CONFIG.set_setting('notedismiss', 'false')
            window.show_notification(msg)
    else:
        logging.log('[Notifications] Notifications file at {0} not formatted correctly.'
                    .format(CONFIG.NOTIFICATION),
                    level=xbmc.LOGINFO)


# Polite Hebrew wait message shown for the whole provisioning run.
PROVISION_WAIT_MSG_HE = 'אנא המתינו עד להשלמת ההתקנה וטעינת מסך הבית.'


def _make_provisioning_banner():
    """Create a persistent, NON-MODAL top banner for the entire fresh-install /
    provisioning run.

    A ``DialogProgressBG`` renders in Kodi's top-right corner and -- unlike a
    modal dialog or a transient notification -- STAYS VISIBLE behind every
    subsequent install dialog / first-run popup until we explicitly close it (or
    Kodi shuts down at the end of setup). It never grabs focus or input, so there
    is NO global watchdog and nothing to fight. Returns the dialog object, which
    the caller MUST keep a reference to (letting it be garbage-collected would
    close it), or ``None`` if it could not be created.
    """
    try:
        banner = xbmcgui.DialogProgressBG()
        banner.create(CONFIG.ADDONTITLE, PROVISION_WAIT_MSG_HE)
        # Indeterminate-ish: keep it near 0 so it never auto-completes/closes.
        banner.update(1, CONFIG.ADDONTITLE, PROVISION_WAIT_MSG_HE)
        return banner
    except Exception:
        return None


def _close_provisioning_banner(banner):
    try:
        if banner is not None:
            banner.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# First-boot stabilizer (race shield)
# ---------------------------------------------------------------------------
# THE RACE: the very first boot after a fresh install / modular update is chaos.
# FENtastic spins up instantly and fires a burst of PARALLEL widget directory
# queries at plugin.video.pov (popular movies, trending TV, ...) at the exact
# moment POV's own background service (Main/Sync Monitor) is registering and
# creating/migrating its databases for the first time. POV is not yet
# responsive, so the queries fail with "Unable to find plugin plugin.video.pov"
# / XFILE::CDirectory::GetDirectory, and Kodi's skin-variable evaluation engine
# can hard-DEADLOCK against the Python interpreter that is mid-addon-init -> a
# freeze/crash. The SECOND boot is always clean because POV finished initialising
# before the skin asked it anything.
#
# THE SHIELD: reproduce that "clean second boot" ON the first boot. A one-shot
# marker (armed at the end of a successful install, same pattern as
# .provisioned) tells the next boot to: hold briefly with a USER-VISIBLE
# countdown banner while POV warms up, then UpdateLocalAddons + ReloadSkin so the
# home widgets re-evaluate against a now-ready POV. It is fully guarded and the
# marker is ALWAYS cleared (finally), so a failure can never trap Kodi in a
# stabilize loop or a black screen. It is non-intrusive: no skin patching, no
# global watchdog, no modal that can steal input.
FIRST_BOOT_MARKER = 'kodipovil.first_boot_stabilize'
FIRST_BOOT_WARMUP_DEFAULT = 25  # seconds (bounded; overridable via setting)


def _first_boot_marker_path():
    return os.path.join(CONFIG.USERDATA, FIRST_BOOT_MARKER)


def arm_first_boot_stabilize():
    """Drop the one-shot marker so the NEXT boot runs the stabilizer. Called at
    the end of a successful install."""
    try:
        with open(_first_boot_marker_path(), 'w') as fh:
            fh.write('1')
        logging.log('[FirstBoot] armed stabilizer marker', level=xbmc.LOGINFO)
    except Exception as e:
        logging.log('[FirstBoot] could not arm marker: {0}'.format(e), level=xbmc.LOGWARNING)


def _first_boot_warmup_seconds():
    """Warm-up budget, overridable by the optional wizard setting
    'first_boot_warmup_seconds' (clamped to a sane 5..120s). Falls back to the
    default when unset/invalid -- so it works whether or not the setting is
    declared."""
    try:
        raw = CONFIG.get_setting('first_boot_warmup_seconds')
        v = int(raw) if raw not in (None, '', False) else 0
        if 5 <= v <= 120:
            return v
    except Exception:
        pass
    return FIRST_BOOT_WARMUP_DEFAULT


def first_boot_stabilize_if_needed():
    """If the one-shot marker is present, warm POV up (bounded, with a live
    countdown banner) then UpdateLocalAddons + ReloadSkin so FENtastic's home
    widgets load against a ready POV instead of a half-initialised one.

    Returns True if the stabilizer ran. NEVER raises. Pending work survives
    until the required add-ons are ready."""
    try:
        if not os.path.exists(_first_boot_marker_path()):
            return False
    except Exception:
        return False

    banner = None
    completed = False
    try:
        total = _first_boot_warmup_seconds()
        header = CONFIG.ADDONTITLE
        pov_id = 'plugin.video.pov'
        # POV gets AT LEAST this long even if HasAddon flips true early -- the
        # addon being "present" is not the same as its DB setup being finished.
        min_warm = max(5, int(total * 0.4))

        try:
            banner = xbmcgui.DialogProgressBG()
            banner.create(header, 'מסיים אתחול ראשוני של הבילד, נא להמתין...')
        except Exception:
            banner = None

        monitor = xbmc.Monitor()
        logging.log('[FirstBoot] stabilizing: warming POV for up to {0}s'.format(total),
                    level=xbmc.LOGINFO)
        pov_present = False
        for elapsed in range(total):
            if monitor.abortRequested():
                break
            remaining = total - elapsed
            pct = int((elapsed + 1) / float(total) * 100)
            if banner is not None:
                try:
                    banner.update(
                        pct, header,
                        'מסיים אתחול ראשוני של הבילד... עוד {0} שניות'.format(remaining))
                except Exception:
                    pass
            try:
                pov_present = bool(xbmc.getCondVisibility('System.HasAddon({0})'.format(pov_id)))
            except Exception:
                pov_present = False
            # Early finish once POV is present AND it has had its minimum warm-up,
            # plus one extra beat for in-flight DB writes to settle.
            if pov_present and elapsed >= min_warm:
                if monitor.waitForAbort(2):
                    break
                break
            if monitor.waitForAbort(1):
                break

        if monitor.abortRequested() or not pov_present:
            logging.log('[FirstBoot] core not ready; retaining retry marker', level=xbmc.LOGWARNING)
            return False

        # POV is warm -> force a clean skin reload so home widgets re-query a
        # responsive POV. Guarded individually so one failing builtin can't abort
        # the rest.
        try:
            xbmc.executebuiltin('UpdateLocalAddons')
        except Exception:
            pass
        if not monitor.waitForAbort(1):
            try:
                xbmc.executebuiltin('ReloadSkin()')
            except Exception:
                pass
            # Let the skin finish redrawing before any first-launch modal below.
            monitor.waitForAbort(3)
        if monitor.abortRequested():
            return False
        completed = True
        logging.log('[FirstBoot] stabilizer completed', level=xbmc.LOGINFO)
        return True
    except Exception as e:
        logging.log('[FirstBoot] stabilizer error: {0}'.format(e), level=xbmc.LOGERROR)
        return False
    finally:
        # Clear only after success; incomplete provisioning retries next startup.
        try:
            mp = _first_boot_marker_path()
            if completed and os.path.exists(mp):
                os.remove(mp)
        except Exception:
            pass
        if banner is not None:
            try:
                banner.close()
            except Exception:
                pass


def _is_existing_pre_modular_build():
    """Recognize a legacy installation without relying on new-only markers."""
    # A failed fresh install may already have copied POV. A persistent
    # in-progress marker distinguishes that case from a genuine old build.
    if os.path.isfile(os.path.join(CONFIG.USERDATA,
                                   'kodipovil.modular_install_started')):
        return False
    # The old quickfix bridge writes this marker even for APK users whose
    # Wizard never recorded buildname/installed. A half-completed modular
    # fresh install has no bridge marker and must still resume provisioning.
    bridge_marker = os.path.isfile(os.path.join(
        CONFIG.USERDATA, 'kodipovil.legacy_migration'))
    recorded_legacy = (CONFIG.get_setting('buildname') and
                       CONFIG.get_setting('installed') == 'true')
    return bool(
        (recorded_legacy or bridge_marker)
        and os.path.isfile(os.path.join(
            CONFIG.ADDONS, 'service.subtitles.kodipovilai', 'addon.xml'))
        and os.path.isfile(os.path.join(
            CONFIG.ADDONS, 'plugin.video.pov', 'addon.xml'))
    )


def fresh_build_auto_install_if_needed():
    """Hydrate (or RESUME) the modular build install.

    Gated on the persistent .provisioned marker rather than buildname/installed,
    so a setup the user force-closed mid-provisioning (addons half-installed,
    config.zip never applied) is RESUMED on the next launch instead of being left
    permanently broken. run_fresh_install() is idempotent -- present addons are
    skipped, the config pack self-applies once -- and it writes the marker only
    after the WHOLE sequence completes.
    """
    # The updater writes .provisioned before startup finishes the build flags,
    # media assets and first-boot setup. If Kodi dies in that interval, finish
    # this tail on the next boot instead of treating the install as complete.
    provision_marker = os.path.join(CONFIG.USERDATA, 'kodipovil.provisioned')
    in_progress_marker = os.path.join(CONFIG.USERDATA,
                                      'kodipovil.modular_install_started')
    resume_finalization = (os.path.isfile(provision_marker) and
                           os.path.isfile(in_progress_marker))
    if resume_finalization and not os.path.isfile(os.path.join(
            CONFIG.USERDATA, 'kodipovil.fresh_gui_defaults.xml')):
        resume_finalization = False
    if os.path.isfile(provision_marker) and not os.path.isfile(in_progress_marker):
        return False

    # 2. Migration from the public, pre-modular build: those devices have
    #    buildname/installed and POV on disk, but CANNOT have the new
    #    config_applied_version or .provisioned markers. Requiring either new
    #    marker here misclassifies an existing user's profile as a fresh
    #    install and can replace their configuration. Missing optional content
    #    addons are healed later by OTA; they do not justify a reinstall.
    if not resume_finalization and _is_existing_pre_modular_build():
        logging.log(
            "[Fresh Build Auto Install] Existing pre-modular build detected; "
            "stamping .provisioned marker without reinstalling userdata.",
            level=xbmc.LOGINFO)
        try:
            with open(provision_marker, 'w', encoding='utf-8') as fh:
                fh.write(str(CONFIG.get_setting('buildversion') or
                             CONFIG.BUILDVERSION_DEFAULT))
            bridge_marker = os.path.join(CONFIG.USERDATA,
                                         'kodipovil.legacy_migration')
            if os.path.isfile(bridge_marker):
                os.remove(bridge_marker)
        except Exception as exc:
            logging.log('[Fresh Build Auto Install] could not write migration '
                        'marker: {0}'.format(exc), level=xbmc.LOGERROR)
        return False

    # 3. Marker absent AND setup incomplete -> (re)run the modular fresh install
    #    to FINISH the job. Covers a brand-new device AND a force-closed setup
    #    (pov may already be on disk, but config and/or other addons never
    #    landed -- exactly the case that used to break the build permanently).
    build_name = CONFIG.BUILDNAME_DEFAULT
    build_version = CONFIG.BUILDVERSION_DEFAULT
    from resources.libs.modular_updater import ModularUpdater

    if not resume_finalization:
        try:
            with open(in_progress_marker, 'w', encoding='utf-8') as fh:
                fh.write('1\n')
        except OSError as exc:
            logging.log('[Fresh Build Auto Install] cannot persist resume marker: '
                        '{0}'.format(exc), level=xbmc.LOGERROR)
            return False

    # Persistent "please wait" banner for the whole provisioning. Stays at the top
    # of Kodi, surviving every install dialog/popup, until setup ends (Kodi
    # closes) or we bail to resume next launch.
    wait_banner = _make_provisioning_banner()
    try:
        tools.ensure_folders(CONFIG.PACKAGES)
        logging.log(
            "[Fresh Build Auto Install] Modular fresh install / resume of {0} v{1}".format(
                build_name, build_version), level=xbmc.LOGINFO)

        if resume_finalization:
            logging.log('[Fresh Build Auto Install] resuming post-provision '
                        'finalization.', level=xbmc.LOGINFO)
        else:
            # A transient repository/download failure can recover while the
            # installer remains open; don't require several manual restarts.
            from resources.libs import fresh_install
            ready, issues = fresh_install.provision()
            if not ready:
                _close_provisioning_banner(wait_banner)
                xbmcgui.Dialog().ok(CONFIG.ADDONTITLE, fresh_install.failure_message(issues))
                return False

        # Sanity gate: the build engine must be on disk AND run_fresh_install
        # must have written the .provisioned marker (i.e. it ran to completion
        # and was NOT force-closed mid-provisioning). If either is missing, leave
        # the flags untouched so the next launch resumes.
        if not os.path.exists(os.path.join(CONFIG.ADDONS, 'service.subtitles.kodipovilai')):
            logging.log(
                "[Fresh Build Auto Install] build engine missing after install; "
                "will resume next launch.", level=xbmc.LOGERROR)
            _close_provisioning_banner(wait_banner)
            return False
        if not ModularUpdater.is_provisioned():
            logging.log(
                "[Fresh Build Auto Install] provisioning did not complete (marker "
                "absent); will resume next launch.", level=xbmc.LOGWARNING)
            _close_provisioning_banner(wait_banner)
            return False

        from resources.libs import fresh_install
        completed = fresh_install.finalize()
        _close_provisioning_banner(wait_banner)
        return completed
    except Exception as err:
        logging.log(
            "[Fresh Build Auto Install] Failed: {0}".format(err),
            level=xbmc.LOGERROR,
        )
        _close_provisioning_banner(wait_banner)
        return False


def installed_build_check():
    dialog = xbmcgui.Dialog()

    if not CONFIG.EXTRACT == '100' and CONFIG.EXTERROR > 0:
        logging.log("[Build Installed Check] Build was extracted {0}/100 with [ERRORS: {1}]".format(CONFIG.EXTRACT,
                                                                                                    CONFIG.EXTERROR),
                    level=xbmc.LOGINFO)
        yes = dialog.yesno(CONFIG.ADDONTITLE,
                           '[COLOR {0}]{2}[/COLOR] [COLOR {1}]was not installed correctly![/COLOR]'.format(CONFIG.COLOR1,
                                                                                                   CONFIG.COLOR2,
                                                                                                   CONFIG.BUILDNAME)
                           +'\n'+('Installed: [COLOR {0}]{1}[/COLOR] / '
                            'Error Count: [COLOR {2}]{3}[/COLOR]').format(CONFIG.COLOR1, CONFIG.EXTRACT, CONFIG.COLOR1,
                                                                          CONFIG.EXTERROR)
                           +'\n'+'Would you like to try again?[/COLOR]', nolabel='[B]No Thanks![/B]',
                           yeslabel='[B]Retry Install[/B]')
        CONFIG.clear_setting('build')
        if yes:
            xbmc.executebuiltin("PlayMedia(plugin://{0}/?mode=install&name={1}&url=fresh)".format(CONFIG.ADDON_ID,
                                                                                                  quote_plus(CONFIG.BUILDNAME)))
            logging.log("[Build Installed Check] Fresh Install Re-activated", level=xbmc.LOGINFO)
        else:
            logging.log("[Build Installed Check] Reinstall Ignored")
    elif CONFIG.SKIN in ['skin.confluence', 'skin.estuary', 'skin.estouchy']:
        logging.log("[Build Installed Check] Incorrect skin: {0}".format(CONFIG.SKIN), level=xbmc.LOGINFO)
        defaults = CONFIG.get_setting('defaultskin')
        if not defaults == '':
            if os.path.exists(os.path.join(CONFIG.ADDONS, defaults)):
                if skin.skin_to_default(defaults):
                    skin.look_and_feel_data('restore')
        if not CONFIG.SKIN == defaults and not CONFIG.BUILDNAME == "":
            # KODI-POV-IL - the build skin was reset to a stock Kodi skin. The
            # legacy monolithic "GuiFix" zip recovery is gone; instead force the
            # modular updater to RE-APPLY the build-config pack on the next OTA
            # pass (it re-seeds the build skin + look) by clearing the
            # applied-config marker. Silent and non-destructive.
            logging.log("[Build Installed Check] Build skin reset to {0}; clearing "
                        "config marker so ModularUpdater re-applies the build config."
                        .format(CONFIG.SKIN), level=xbmc.LOGWARNING)
            CONFIG.set_setting('config_applied_version', '')
    else:
        logging.log('[Build Installed Check] Install seems to be completed correctly', level=xbmc.LOGINFO)
        
    if CONFIG.get_setting('installed') == 'true':
        CONFIG.clear_setting('install')


def stop_if_duplicate():
    NOW = time.time()
    temp = CONFIG.get_setting('time_started')
    
    if temp:
        if temp > NOW - (60 * 2):
            logging.log('Killing Start Up Script')
            sys.exit()
            
    logging.log("{0}".format(NOW))
    CONFIG.set_setting('time_started', NOW)
    xbmc.sleep(1000)
    
    if not CONFIG.get_setting('time_started') == NOW:
        logging.log('Killing Start Up Script')
        sys.exit()
    else:
        logging.log('Continuing Start Up Script')


def check_for_video():
    while xbmc.Player().isPlayingVideo():
        xbmc.sleep(1000)


def wait_for_gui_ready(timeout=90):
    """This script is an xbmc.service with start="startup", so it runs
    before Kodi's GUI/Home window exists. Showing a modal dialog
    (doModal) that early deadlocks Kodi: it loads for a few seconds and
    then hangs, and only a force-stop recovers -- after which the
    one-shot dismiss flags are already set, so the next launch is fine.
    That exactly matches the "hang once after every install/quick
    update" symptom. Wait for the Home window to be live before any
    first-launch dialog. Bounded by a timeout so we never wait forever
    (e.g. headless/odd boots); returns True only if Home actually came
    up."""
    logging.log('[GUI Ready] entering Home wait', level=xbmc.LOGINFO)
    try:
        monitor = xbmc.Monitor()
        waited = 0
        login_checked = False
        while waited < timeout:
            home_visible = xbmc.getCondVisibility('Window.IsVisible(home)')
            if home_visible:
                # Home is already visible. A timed Kodi sleep here can be
                # starved for tens of seconds while AF3 renders widgets;
                # advancing lets the background update run immediately.
                logging.log('[GUI Ready] Home visible after {0}s'.format(waited),
                            level=xbmc.LOGINFO)
                return True
            if not login_checked and xbmc.getCondVisibility('Window.IsActive(loginscreen)'):
                login_checked = True
                from resources.libs import build_profiles
                build_profiles.resume_single_login()
            if monitor.waitForAbort(1):
                return False
            waited += 1
        logging.log(
            '[GUI Ready] Home window not visible after {0}s; '
            'continuing without the wait.'.format(timeout),
            level=xbmc.LOGWARNING)
        return False
    except Exception as gui_err:
        logging.log('[GUI Ready] wait failed: {0}'.format(gui_err),
                    level=xbmc.LOGERROR)
        return False


# Don't run the script while video is playing :)
xbmc.executebuiltin('RunScript({})'.format(os.path.join(CONFIG.ADDON_PATH, 'profile_service.py')))
check_for_video()
# A native secondary profile does not include build addon_data/favourites.
# Repair missing defaults before interpreting it as a fresh APK installation.
try:
    from resources.libs import build_profiles
    build_profiles.install_login_hooks()
    build_profiles.repair_active()
    if not build_profiles.prepare_first_login():
        logging.log('[Profiles] add-on registration incomplete; retrying next startup', level=xbmc.LOGWARNING)
except Exception as profile_err:
    logging.log('[Profiles] active repair failed: {}'.format(type(profile_err).__name__), level=xbmc.LOGERROR)
# Ensure that any needed folders are created
tools.ensure_folders()

# Ensure that the wizard's name matches its folder
check.check_paths()
    
# AUTO UPDATE WIZARD
if CONFIG.AUTOUPDATE == 'Yes':
    logging.log("[Auto Update Wizard] Started", level=xbmc.LOGINFO)
    update.wizard_update()
else:
    logging.log("[Auto Update Wizard] Not Enabled", level=xbmc.LOGINFO)

# KODI-RD-IL - Auto force addon updates on Kodi startup
if getattr(CONFIG, 'FORCEUPDATEFAST_ONSTARTUP', 'false') == "true":
    db.forceUpdate(startup=True)

# KODI-POV-IL - Clean APK/IPK/Windows/wizard first launch hydration.
# This is intentionally before notifications and quick_update: a clean profile
# first needs the full build (userdata + FENtastic + favourites) extracted.
# Apply installed POV fixes before the GUI-ready/modal-dialog wait. On slow
# skins that wait can consume its full 90-second budget; source selection must
# not spend that period using unpatched POV after an upstream self-update.
# The later pass still repeats after a modular update replaces add-on files.
if os.path.isfile(os.path.join(CONFIG.ADDONS, 'plugin.video.pov', 'addon.xml')):
    try:
        from resources.libs.patch_engine import PatchEngine
        PatchEngine().run()
    except Exception as _early_patch_err:
        logging.log('[PatchEngine] Early boot run failed: {0}'.format(
            _early_patch_err), level=xbmc.LOGERROR)

if not os.path.isfile(os.path.join(CONFIG.USERDATA, 'kodipovil.provisioned')):
    logging.log('[Modular migration] pre-marker state: buildname={0}, '
                'installed={1}, pov={2}'.format(
                    bool(CONFIG.get_setting('buildname')),
                    CONFIG.get_setting('installed') == 'true',
                    os.path.isfile(os.path.join(CONFIG.ADDONS,
                                                'plugin.video.pov', 'addon.xml'))),
                level=xbmc.LOGINFO)

fresh_build_auto_install_if_needed()
if os.path.isfile(os.path.join(CONFIG.USERDATA, 'kodipovil.modular_install_started')):
    # Incomplete setup must not proceed to normal notifications or claim ready.
    logging.log('[FreshInstall] setup remains pending', level=xbmc.LOGWARNING)
    sys.exit()

# Everything below can pop a modal dialog (build first-launch notification,
# skin-switch notification, quick-update prompt). Because this is a
# start="startup" service those modals can fire before Kodi's GUI exists
# and deadlock the boot -- the "hangs once after install/quick update,
# force-stop to recover" symptom. Block here until Home is actually live
# (bounded) so every dialog below has a real parent window.
if not wait_for_gui_ready():
    logging.log('[Startup] GUI unavailable; deferring dialogs', level=xbmc.LOGWARNING)
    sys.exit()

try:
    build_profiles.repair_single_login()
    build_profiles.prepare_inactive()
    profile_defaults = os.path.join(CONFIG.USERDATA, 'kodipovil.profile_gui_defaults.xml')
    if not build_profiles.is_master() and os.path.isfile(profile_defaults):
        from resources.libs import fresh_install
        if fresh_install.apply_live_defaults(defaults_path=profile_defaults):
            from resources.libs import build_skin
            if build_skin.refresh_home() and fresh_install.live_favourites_ready():
                build_profiles.profile_store.write_missing(CONFIG.USERDATA, 'kodipovil.profile_home_ready', b'1')
                os.remove(profile_defaults)
    elif not build_profiles.is_master():
        from resources.libs import build_skin, fresh_install
        if not os.path.isfile(os.path.join(CONFIG.USERDATA, 'kodipovil.profile_home_ready')) and build_skin.refresh_home() and fresh_install.live_favourites_ready():
            build_profiles.profile_store.write_missing(CONFIG.USERDATA, 'kodipovil.profile_home_ready', b'1')
except Exception as profile_err:
    logging.log('[Profiles] login repair failed: {}'.format(type(profile_err).__name__), level=xbmc.LOGERROR)

if not build_profiles.is_master() and not os.path.isfile(os.path.join(CONFIG.USERDATA, 'kodipovil.profile_home_ready')):
    # Keep normal boot dialogs deferred until the live home is verified.
    logging.log('[Profiles] home completion pending; deferring dialogs', level=xbmc.LOGINFO)
    sys.exit()

# FIRST-BOOT STABILIZER (race shield). Runs ONLY when the one-shot marker from a
# just-completed install is present. Warms POV up (user-visible countdown) and
# ReloadSkin()s so the FENtastic home widgets load against a ready POV instead of
# racing its first-run DB setup -> the "first boot freeze". No-op on every normal
# boot. Must run BEFORE the first-launch notification/contact modals below.
first_boot_stabilize_if_needed()

# SHOW NOTIFICATIONS
from resources.libs.patches import profile_age_guard
if profile_age_guard.active_policy() is None and CONFIG.ENABLE_NOTIFICATION == 'Yes' and (CONFIG.get_setting('buildname') or
        os.path.isfile(os.path.join(CONFIG.ADDONS, 'plugin.video.pov', 'addon.xml'))):
    show_notification()
else:
    logging.log('[Notifications] Not Enabled', level=xbmc.LOGINFO)
    
######################################
# KODI-RD-IL - FIRST BUILD LAUNCH BUILD SKIN SWITCH NOTIFICATION
logging.log('[Startup] first-launch notice gate: buildname={0}, dismissed={1}'.format(
    bool(CONFIG.get_setting('buildname')),
    CONFIG.get_setting('build_skin_switch_notifcation_dismiss')),
    level=xbmc.LOGINFO)
if CONFIG.get_setting('buildname') and CONFIG.get_setting('build_skin_switch_notifcation_dismiss') == 'false':
    window.show_contact(CONFIG.CONTACT)
    CONFIG.set_setting('build_skin_switch_notifcation_dismiss', 'true')
    msg = f"על מנת להחליף סקין יש ללחוץ: כפתור כיבוי --> החלף סקין.\nהסקינים הקיימים בבילד:\n1. סקין Estuary\n2. סקין FENtastic\n3. סקין Arctic Fuse 3\n4. סקין NOX"
    window.show_notification_with_extra_image(msg, 888, CONFIG.BUILD_SKIN_SWITCH_IMAGE_URL)
#####################################

logging.log('[Startup] first-launch notice gate complete', level=xbmc.LOGINFO)

######################################
# KODI-RD-IL - Auto-set buildname for APK installs where the user
# never ran a wizard-driven Fresh Install. Without this the empty
# 'buildname' setting silently disables the entire auto_quick_update
# path below, so existing APK users would never receive quickfix
# updates. Detect that POV is on disk (so the build really is
# installed, just not registered with the wizard) and populate the
# settings the wizard's update gates check.
try:
    if (not CONFIG.get_setting('buildname') and
            not os.path.isfile(os.path.join(
                CONFIG.USERDATA, 'kodipovil.modular_install_started'))):
        pov_addon_dir = os.path.join(CONFIG.ADDONS, 'plugin.video.pov')
        if os.path.exists(pov_addon_dir):
            CONFIG.set_setting('buildname', CONFIG.BUILDNAME_DEFAULT)
            CONFIG.set_setting('installed', 'true')
            # The skin-switch first-launch notification would otherwise
            # fire on the next startup now that buildname is set. The
            # user has been using the build for a while, so suppress it.
            CONFIG.set_setting('build_skin_switch_notifcation_dismiss', 'true')

            # CRITICAL: also set buildversion. Without this,
            # check.check_build_update sees an empty buildversion and
            # treats every published version as "newer", which fires
            # a Fresh-Install dialog whose default action overwrites
            # the user's entire userdata (wiping Real-Debrid, Trakt
            # and other connected-services state -- happened to the
            # first test user). Try to fetch the current published
            # version from build.txt; fall back to the constant baked
            # into uservar.py.
            current_version = CONFIG.BUILDVERSION_DEFAULT
            try:
                v = check.check_build(CONFIG.BUILDNAME_DEFAULT, 'version')
                if v:
                    current_version = v
            except Exception:
                pass
            CONFIG.set_setting('buildversion', current_version)
            CONFIG.set_setting('latestversion', current_version)

            # Belt-and-suspenders: also push the next build-update
            # check 30 days into the future. Even if buildversion
            # ends up wrong, this gives us a long window to ship a
            # quickfix before any "update available" dialog fires.
            future_check = (datetime.now() + timedelta(days=30)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            CONFIG.set_setting('nextbuildcheck', future_check)

            # Refresh the in-memory cache so other startup steps see
            # the new values immediately.
            CONFIG.BUILDNAME = CONFIG.BUILDNAME_DEFAULT
            CONFIG.BUILDVERSION = current_version
            CONFIG.BUILDLATEST = current_version
            CONFIG.INSTALLED = 'true'
            CONFIG.BUILDCHECK = future_check

            logging.log(
                "[Auto-Set Buildname] APK install detected (plugin.video.pov "
                "present, buildname was empty). Set buildname='{0}', "
                "installed='true', buildversion='{1}', "
                "nextbuildcheck='{2}'.".format(
                    CONFIG.BUILDNAME_DEFAULT, current_version, future_check
                ),
                level=xbmc.LOGINFO,
            )
except Exception as _autoset_err:
    try:
        logging.log(
            "[Auto-Set Buildname] Failed (continuing): {0}".format(_autoset_err),
            level=xbmc.LOGERROR,
        )
    except Exception:
        pass
######################################

######################################
# KODI-POV-IL - MODULAR OTA UPDATE + STRICT MANIFEST ENFORCEMENT.
# Polls manifest.json and updates addons whose version moved (silent background;
# only a Wizard or active-skin update forces a restart). Then heal_missing_addons
# does the bulletproof part: it physically verifies System.HasAddon(id) for EVERY
# required addon in the manifest + every content addon, and silently installs any
# that are missing -- e.g. a YouTube that timed out during a previous provisioning
# pass and was skipped. This is what makes a half-provisioned build self-complete
# on the very next launch instead of staying broken.
try:
    # Heal the current layout before network provisioning can delay startup.
    from resources.libs import fentastic_widgets
    fentastic_widgets.repair()
except Exception as _early_widget_error:
    logging.log('[FENtastic widgets] early repair deferred: ' + type(_early_widget_error).__name__,
                level=xbmc.LOGWARNING)

if CONFIG.get_setting('buildname'):
    logging.log('[Startup] entering modular update gate', level=xbmc.LOGINFO)
    try:
        from resources.libs.patches import pov_source_remember
        pov_source_remember.migrate_legacy_preference()
    except Exception as _remember_migration_error:
        logging.log('[Source Remember] preference migration failed: {0}'.format(
            _remember_migration_error), level=xbmc.LOGWARNING)
    try:
        from resources.libs.modular_updater import ModularUpdater
        _mu = ModularUpdater(background=True)
        _mu.run_update_check()        # version bumps for installed addons + config
        _mu.heal_missing_addons()     # strict HasAddon enforcement -> install missing

    except Exception as _modular_err:
        logging.log("[ModularUpdater] Startup check failed: {0}".format(_modular_err),
                    level=xbmc.LOGERROR)
    # Repair installed add-ons even when the manifest server is unavailable or
    # the updater raises. An upstream POV update can erase these hooks while
    # the network is down; patching must not depend on OTA success.
    try:
        from resources.libs.patch_engine import PatchEngine
        PatchEngine().run()
    except Exception as _patch_err:
        logging.log("[PatchEngine] Boot-cycle run failed: {0}".format(_patch_err),
                    level=xbmc.LOGERROR)
######################################

# KOD-RD-IL - New Kodi ANDROID/WINDOWS version check on startup
try:
    from resources.libs import fentastic_widgets
    fentastic_widgets.repair()
except Exception as _widget_repair_error:
    logging.log('[FENtastic widgets] repair deferred: {}'.format(_widget_repair_error),
                level=xbmc.LOGWARNING)

if tools.platform() in ['android', 'windows'] and CONFIG.get_setting('buildname'):
    from resources.libs.wizard import kodi_version_update_check
    kodi_version_update_check()
######################################

# INSTALLED BUILD CHECK
if CONFIG.get_setting('installed') == 'true':
    logging.log("[Build Installed Check] Started", level=xbmc.LOGINFO)
    installed_build_check()
else:
    logging.log("[Build Installed Check] Not Enabled", level=xbmc.LOGINFO)

# KODI-POV-IL - Auto-refresh the on-demand NOX skin pack for users who are
# already ON it. On-demand skins are normally only (re)installed from Switch
# Skin; this makes a published NOX update reach existing NOX users on their
# next quick_update + restart, exactly like the other skins, without them
# having to toggle skins. Version-gated, so it never re-downloads needlessly.
try:
    if CONFIG.get_setting('buildname'):
        from resources.libs import wizard as _wiz_skin
        _wiz_skin.auto_update_active_skin_pack()
except Exception as _skin_upd_err:
    logging.log("[Skin Auto Update] startup hook failed: {0}".format(_skin_upd_err),
                level=xbmc.LOGERROR)

# The normal startup patch pass is not enough if Kodi updates POV later in
# this same session. A separate small interpreter watches host identities.
try:
    xbmc.executebuiltin('RunScript({})'.format(os.path.join(
        CONFIG.ADDON_PATH, 'host_patch_service.py')))
except Exception as _host_watch_error:
    logging.log('[Host patch watch] start failed: {}'.format(_host_watch_error),
                level=xbmc.LOGWARNING)
