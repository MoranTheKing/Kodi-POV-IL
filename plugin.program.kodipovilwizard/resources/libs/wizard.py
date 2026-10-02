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
import xbmcplugin

import os
import sys

try:
    from urllib.parse import quote_plus
except ImportError:
    from urllib import quote_plus

from resources.libs import check
from resources.libs import db
from resources.libs import extract
from resources.libs import install
from resources.libs import skin
from resources.libs.common import logging
from resources.libs.common import tools
from resources.libs.common.config import CONFIG
from resources.libs.downloader import Downloader


class Wizard:

    def __init__(self):
        tools.ensure_folders(CONFIG.PACKAGES)
        
        self.dialog = xbmcgui.Dialog()
        self.dialogProgress = xbmcgui.DialogProgress()

    def _prompt_for_wipe(self):
        # Should we wipe first?
        if self.dialog.yesno(CONFIG.ADDONTITLE,
                           "[COLOR {0}]Do you wish to restore your".format(CONFIG.COLOR2) +'\n' + "Kodi configuration to default settings" + '\n' + "Before installing the build backup?[/COLOR]",
                           nolabel='[B][COLOR red]No[/COLOR][/B]',
                           yeslabel='[B][COLOR springgreen]Yes[/COLOR][/B]'):
            install.wipe()

    def build(self, name, over=False):
        # KODI-POV-IL - FULL INSTALL, now fully MODULAR.
        # The legacy path downloaded a monolithic build zip from build.txt, ran
        # install.wipe(), and extracted it over special://home. ALL of that is
        # gone. A "Full Install" is now a foreground ModularUpdater fresh install:
        # every addon in manifest.json + the build-config pack, with the content
        # addons provisioned via Kodi's native InstallAddon. No wipe, no
        # monolithic zip, no build.txt -- and it is guarded by the same
        # .provisioned marker, so an interrupted run resumes on the next launch.
        if not over:
            if not self.dialog.yesno(
                    CONFIG.ADDONTITLE,
                    '[COLOR {0}]האם ברצונך להתקין את '.format(CONFIG.COLOR2)
                    + '[COLOR {0}]{1}[/COLOR]?[/COLOR]'.format(CONFIG.COLOR1, name),
                    nolabel='[B][COLOR red]ביטול[/COLOR][/B]',
                    yeslabel='[B][COLOR springgreen]התקנה[/COLOR][/B]'):
                logging.log_notify(CONFIG.ADDONTITLE,
                                   '[COLOR {0}]התקנת בילד: בוטלה![/COLOR]'.format(CONFIG.COLOR2))
                return

        CONFIG.clear_setting('build')

        build_name = CONFIG.BUILDNAME_DEFAULT
        build_version = CONFIG.BUILDVERSION_DEFAULT

        from resources.libs.modular_updater import ModularUpdater
        logging.log("[Build] Full modular install of {0} v{1}".format(build_name, build_version),
                    level=xbmc.LOGINFO)

        # A user-triggered Full Install starts clean: drop the marker so the whole
        # fresh sequence runs (and so an interrupted run is resumable).
        ModularUpdater.clear_provisioned()
        from resources.libs import fresh_install
        fresh_install.begin()

        try:
            ModularUpdater(background=False).run_fresh_install()
        except Exception as err:
            logging.log("[Build] Modular fresh install failed: {0}".format(err), level=xbmc.LOGERROR)
            self.dialog.ok(CONFIG.ADDONTITLE,
                           "[COLOR {0}]התקנת הבילד נכשלה. נסה שוב.[/COLOR]".format(CONFIG.COLOR2))
            return

        xbmc.sleep(500)

        # Completion gate: the build engine must be on disk AND run_fresh_install
        # must have written the .provisioned marker (ran end-to-end). Otherwise do
        # NOT flip the build to installed -- startup resumes it next launch.
        engine_present = os.path.exists(os.path.join(CONFIG.ADDONS, 'service.subtitles.kodipovilai'))
        if not engine_present or not ModularUpdater.is_provisioned():
            logging.log("[Build] Full install did not complete (engine={0}, marker={1}); "
                        "will resume next launch.".format(engine_present, ModularUpdater.is_provisioned()),
                        level=xbmc.LOGERROR)
            self.dialog.ok(CONFIG.ADDONTITLE,
                           "[COLOR {0}]ההתקנה לא הושלמה. הפעל מחדש את קודי כדי להמשיך.[/COLOR]".format(CONFIG.COLOR2))
            return

        try:
            if not fresh_install.finalize():
                self.dialog.ok(CONFIG.ADDONTITLE, 'ההתקנה ממתינה להשלמה. אשר את הסקין או נסה שוב.')
                return
        except Exception as err:
            logging.log('[Build] finalization failed: {0}'.format(err), level=xbmc.LOGERROR)
            self.dialog.ok(CONFIG.ADDONTITLE, 'ההתקנה לא הושלמה. ניתן לנסות שוב בלי למחוק הגדרות.')
            return
        db.addon_database(CONFIG.ADDON_ID, 1)
        self.dialog.notification(CONFIG.ADDONTITLE, 'הבילד הותקן ומוכן לשימוש')

    def gui(self, name, over=False):
        # KODI-POV-IL - DEPRECATED legacy "GuiFix" quickfix installer.
        # This was a twin of the old quick_update(): it downloaded the
        # monolithic `gui` zip from build.txt and extracted it over CONFIG.HOME.
        # That path is broken/dangerous under the modular architecture (stale
        # monolithic zip overwriting the live modular build). Its menu item is
        # already commented out, but router.py still routes action=gui here, so
        # we redirect it to the safe manifest-based update instead of ever
        # touching the monolithic zip. RECOMMENDATION: delete gui() and its
        # router branch once no plugin URLs reference action=gui.
        return self.quick_update(name, auto_quick_update="false")

    #####################################################
    # KODI-RD-IL
    def quick_update(self, name, auto_quick_update="false"):
        # KODI-POV-IL - "Quick Update" (עדכון מהיר) -- REWIRED for the modular
        # (manifest.json) architecture.
        #
        # LEGACY (removed): this used to read the `gui` field of the old
        # monolithic build.txt, download a single "quickfix" build zip
        # (Kodi-POV-IL-FENtastic-quickfix-*.zip) and extract it straight over
        # CONFIG.HOME with ignore=True. Under the hybrid modular build that zip
        # is BROKEN and DANGEROUS: it is frozen on the old repo, still carries
        # the pre-migration monolithic wizard (0.1.30), and extracting it would
        # OVERWRITE the live modular wizard + addons and undo the whole
        # migration on the user's device.
        #
        # NOW: "Quick Update" is a thin, safe wrapper around ModularUpdater. It
        # diffs the live manifest.json and updates ONLY the addons whose version
        # actually moved -- no monolithic zip, no full reinstall, no wipe.
        # ModularUpdater.execute_updates handles any required restart / skin
        # reload itself, so we deliberately do NOT force-close Kodi here.
        auto = True if auto_quick_update == "true" else False

        try:
            from resources.libs.modular_updater import ModularUpdater
        except Exception as err:
            logging.log("[quick_update] ModularUpdater import failed: {0}".format(err),
                        level=xbmc.LOGERROR)
            return False

        logging.log("[quick_update] Running modular update check (auto={0})".format(auto),
                    level=xbmc.LOGINFO)
        try:
            # auto path -> silent background pass; manual menu click -> foreground
            # (shows the install-manager progress UI + an "up to date" dialog).
            result = ModularUpdater(background=auto).run_update_check()

            # KODI-POV-IL - Engine v2 Runtime Patching. Runs once the update
            # check has finished (whether or not it found anything new) so
            # a Quick Update always leaves every patch current, the same
            # guarantee the boot-cycle heal path gives -- without this,
            # patches would only ever refresh on a full Kodi restart.
            try:
                from resources.libs.patch_engine import PatchEngine
                PatchEngine().run()
            except Exception as _patch_err:
                logging.log("[quick_update] PatchEngine run failed: {0}".format(_patch_err),
                            level=xbmc.LOGERROR)

            return bool(result)
        except Exception as err:
            logging.log("[quick_update] Modular update failed: {0}".format(err),
                        level=xbmc.LOGERROR)
            return False
    #####################################################

    #####################################################
    # KODI-RD-IL
    def force_close_kodi_in_5_seconds(self, dialog_header):
        self.dialogProgress.create(f"[COLOR yellow][B]{dialog_header}[/B][/COLOR]", "[B]קודי ייסגר בעוד 5 שניות[/B]")
        for s in range(5, -1, -1):
            self.dialogProgress.update(int((5 - s) / 5.0 * 100), f"[B]קודי ייסגר בעוד {s} שניות[/B]")
            xbmc.sleep(1000)
        self.restart_kodi()
    #####################################################

    #####################################################
    # KODI-RD-IL
    def restart_kodi(self):
        # if tools.platform() == 'windows':
            # try:
                # import subprocess, xbmcvfs
                # kodi_root_path = xbmcvfs.translatePath('special://xbmc/')
                # kodi_full_path = [os.path.join(kodi_root_path, 'kodi.exe')]
                # KODI-RD-IL Custom Windows software - AppData stored in C:\Kodi + Real Debrid Israel\portable_data
                # if "Kodi + Real Debrid Israel" in kodi_root_path:
                    # kodi_full_path.append('-p')
                # subprocess.Popen(kodi_full_path, shell=True)
            # except:
                # pass
        tools.kill_kodi(over=True)
    #####################################################



    def theme(self, name, theme='', over=False):
        installtheme = False

        if not theme:
            themefile = check.check_build(name, 'theme')

            response = tools.open_url(themefile, check=True)
            if response:
                from resources.libs.gui.build_menu import BuildMenu
                themes = BuildMenu().theme_count(name, False)
                if len(themes) > 0:
                    if self.dialog.yesno(CONFIG.ADDONTITLE, "[COLOR {0}]The Build [COLOR {1}]{2}[/COLOR] comes with [COLOR {3}]{4}[/COLOR] different themes".format(CONFIG.COLOR2, CONFIG.COLOR1, name, CONFIG.COLOR1, len(themes)) + '\n' + "Would you like to install one now?[/COLOR]",
                                    yeslabel="[B][COLOR springgreen]Install Theme[/COLOR][/B]",
                                    nolabel="[B][COLOR red]Cancel Themes[/COLOR][/B]"):
                        logging.log("Theme List: {0}".format(str(themes)))
                        ret = self.dialog.select(CONFIG.ADDONTITLE, themes)
                        logging.log("Theme install selected: {0}".format(ret))
                        if not ret == -1:
                            theme = themes[ret]
                            installtheme = True
                        else:
                            logging.log_notify(CONFIG.ADDONTITLE,
                                               '[COLOR {0}]Theme Install: Cancelled![/COLOR]'.format(CONFIG.COLOR2))
                            return
                    else:
                        logging.log_notify(CONFIG.ADDONTITLE,
                                           '[COLOR {0}]Theme Install: Cancelled![/COLOR]'.format(CONFIG.COLOR2))
                        return
            else:
                logging.log_notify(CONFIG.ADDONTITLE,
                                   '[COLOR {0}]Theme Install: None Found![/COLOR]'.format(CONFIG.COLOR2))
        else:
            installtheme = self.dialog.yesno(CONFIG.ADDONTITLE, '[COLOR {0}]Would you like to install the theme:'.format(CONFIG.COLOR2) +' \n' + '[COLOR {0}]{1}[/COLOR]'.format(CONFIG.COLOR1, theme) + '\n' + 'for [COLOR {0}]{1} v{2}[/COLOR]?[/COLOR]'.format(CONFIG.COLOR1, name, check.check_build(name,'version')),yeslabel="[B][COLOR springgreen]Install Theme[/COLOR][/B]", nolabel="[B][COLOR red]Cancel Themes[/COLOR][/B]")

        if installtheme:
            themezip = check.check_theme(name, theme, 'url')
            zipname = name.replace('\\', '').replace('/', '').replace(':', '').replace('*', '').replace('?', '').replace('"', '').replace('<', '').replace('>', '').replace('|', '')

            response = tools.open_url(themezip, check=True)
            if not response:
                logging.log_notify(CONFIG.ADDONTITLE,
                                   '[COLOR {0}]Theme Install: Invalid Zip Url![/COLOR]'.format(CONFIG.COLOR2))
                return False

            self.dialogProgress.create(CONFIG.ADDONTITLE, '[COLOR {0}][B]Downloading:[/B][/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR2, CONFIG.COLOR1, zipname) +' \n' + 'Please Wait')

            lib = os.path.join(CONFIG.PACKAGES, '{0}.zip'.format(zipname))

            try:
                os.remove(lib)
            except:
                pass

            Downloader().download(themezip, lib)
            xbmc.sleep(500)

            if os.path.getsize(lib) == 0:
                try:
                    os.remove(lib)
                except:
                    pass

                return

            self.dialogProgress.update(0, '\n' + "Installing {0}".format(name))

            test1 = False
            test2 = False

            from resources.libs import skin
            from resources.libs import test
            test1 = test.test_theme(lib) if CONFIG.SKIN not in skin.DEFAULT_SKINS else False
            test2 = test.test_gui(lib) if CONFIG.SKIN not in skin.DEFAULT_SKINS else False

            if test1:
                skin.look_and_feel_data('save')
                swap = skin.skin_to_default('Theme Install')

                if not swap:
                    return False

                xbmc.sleep(500)

            title = '[COLOR {0}][B]Installing Theme:[/B][/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR2, CONFIG.COLOR1, theme)
            self.dialogProgress.update(0, title + '\n' + 'Please Wait')
            percent, errors, error = extract.all(lib, CONFIG.HOME, title=title)
            CONFIG.set_setting('buildtheme', theme)
            logging.log('INSTALLED {0}: [ERRORS:{1}]'.format(percent, errors))
            self.dialogProgress.close()

            db.force_check_updates(over=True)
            installed = db.grab_addons(lib)
            db.addon_database(installed, 1, True)

            if test2:
                skin.look_and_feel_data('save')
                skin.skin_to_default("Theme Install")
                gotoskin = CONFIG.get_setting('defaultskin')
                skin.switch_to_skin(gotoskin, "Theme Installer")
                skin.look_and_feel_data('restore')
            elif test1:
                skin.look_and_feel_data('save')
                skin.skin_to_default("Theme Install")
                gotoskin = CONFIG.get_setting('defaultskin')
                skin.switch_to_skin(gotoskin, "Theme Installer")
                skin.look_and_feel_data('restore')
            else:
                xbmc.executebuiltin("ReloadSkin()")
                xbmc.sleep(1000)
                xbmc.executebuiltin("Container.Refresh()")
        else:
            logging.log_notify(CONFIG.ADDONTITLE,
                               '[COLOR {0}]Theme Install: Cancelled![/COLOR]'.format(CONFIG.COLOR2))


def wizard(action, name, url):
    cls = Wizard()

    if action in ['fresh', 'normal']:
        cls.build(action, name)
    elif action == 'gui':
        cls.gui(name)
    elif action == 'theme':
        cls.theme(name, url)



#########################################################################################################
# KODI-RD-IL - BUILD SKIN SWITCH
def update_favourites_xml_file(gotoskin):
    """Regenerate userdata/favourites.xml for the target skin.

    KODI-POV-IL: replaces the old static copy of
    media/builds_favourites_xml/<skin>/favourites.xml with a dynamic,
    JSON-driven generation. We load favourites_generator from the
    plugin.program.orderfavourites-hebrew add-on (by file path, so there are no
    cross-add-on package-name clashes) and call generate_favourites_xml(skin),
    which builds the skin's canonical tile set from favourites_config.json AND
    merges in any custom favourites the user added.

    Graceful by design: if the generator add-on is missing or anything goes
    wrong, we log it and leave the existing favourites.xml untouched. We always
    return True so a generation hiccup never aborts the skin switch itself.
    """
    try:
        import os as _os
        import xbmcaddon
        import xbmcvfs

        try:
            addon_path = xbmcvfs.translatePath(
                xbmcaddon.Addon('plugin.program.orderfavourites-hebrew')
                .getAddonInfo('path'))
        except Exception as _addon_err:
            logging.log("DEBUG | update_favourites_xml_file | orderfavourites "
                        "add-on unavailable ({0}); leaving favourites untouched"
                        .format(_addon_err))
            return True

        module_file = _os.path.join(addon_path, 'favourites_generator.py')
        if not _os.path.isfile(module_file):
            logging.log("DEBUG | update_favourites_xml_file | generator not found "
                        "at {0}; leaving favourites untouched".format(module_file))
            return True

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'povil_favourites_generator', module_file)
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        if generator.generate_favourites_xml(gotoskin) is None:
            logging.log("DEBUG | update_favourites_xml_file | invalid existing "
                        "favourites; kept the file unchanged for skin {0}"
                        .format(gotoskin))
            return True
        logging.log("DEBUG | update_favourites_xml_file | regenerated favourites "
                    "for skin {0}".format(gotoskin))
        return True
    except Exception as e:
        logging.log("DEBUG | update_favourites_xml_file | generation failed ({0}); "
                    "leaving existing favourites.xml untouched".format(e))
        return True


#####################################################
# KODI-POV-IL - ON-DEMAND SKIN INSTALL
# Two of the build's selectable skins are installed ONLY when the user picks
# them from Switch Skin, so they never bloat the base build and are NEVER
# force-pushed to every device during fresh installs or background OTA:
#
#   * Arctic Fuse 3 (skin.arctic.fuse.3) -- installed NATIVELY via Kodi's
#     InstallAddon from repository.jurialmunkey (shipped in our manifest, so it
#     lands on every device for dependency resolution). Kodi pulls the skin +
#     ALL its dependencies (tmdbhelper, skinvariables, texturemaker,
#     script.module.jurialmunkey, fonts, studio/weather icons...) from upstream
#     at mutually-compatible versions, and they keep updating from their own
#     repos. This replaces the old four static "pack" zips (deps/skin/fonts/
#     studios) -- no hardcoded dist links, no version-pinned bundles.
#
#   * NOX (skin.povil.nox) -- a rebranded + scrubbed Estuary MOD that is NOT on
#     any public repo, so it is still shipped as a single on-demand pack zip in
#     dist/ and downloaded+extracted on first switch (see _ensure_packs_installed).

# KODI-POV-IL - NOX skin. A rebranded + scrubbed Estuary MOD (~24 MB) whose home
# menu was remapped to our POV / idanplus / otaku addons. It is NOT on any public
# repo, so (unlike AF3) it cannot be resolved natively -- it is shipped as a
# single on-demand pack zip in dist/ and downloaded only when the user picks it
# from Switch Skin, so it never bloats the base build. Its only hard dependency,
# script.fentastic.helper, already ships in the build.
NOX_PACK_BASE_URL = "https://github.com/MoranTheKing/Kodi-POV-IL/raw/main/dist"
NOX_SKIN_VERSION = '1.0.10'
NOX_PACKS = [
    {
        'name': 'סקין NOX',
        'url': '{0}/Kodi-POV-IL-NOX-skin-pack.zip'.format(NOX_PACK_BASE_URL),
        'filename': 'nox_skin_pack.zip',
        'sentinel': 'special://home/addons/skin.povil.nox/addon.xml',
        'expected_version': NOX_SKIN_VERSION,
        'addon_ids': ['skin.povil.nox'],
    },
]


# KODI-POV-IL - UMBRELLA PILOT (opt-in, on-demand). Umbrella + CocoScrapers
# plus BOTH of their official repository addons, so once installed they keep
# updating straight from their developers -- the same trust model POV has via
# repository.kodifitzwell. Nothing here runs unless the user explicitly picks
# the wizard menu entry; no tile, no search wiring, no change for anyone else.
# Reuses NOX_PACK_BASE_URL: it is the same dist/ release folder, just a
# different zip in it -- there is only one pack host for this build.
UMBRELLA_PACK_VERSION = '6.7.85'
UMBRELLA_PACKS = [
    {
        'name': 'Umbrella + CocoScrapers',
        'url': '{0}/Kodi-POV-IL-Umbrella-pack.zip'.format(NOX_PACK_BASE_URL),
        'filename': 'umbrella_pack.zip',
        'sentinel': 'special://home/addons/plugin.video.umbrella/addon.xml',
        'expected_version': UMBRELLA_PACK_VERSION,
        'addon_ids': [
            'plugin.video.umbrella',
            'script.module.cocoscrapers',
            'repository.umbrella',
            'repository.cocoscrapers',
        ],
    },
]


# KODI-POV-IL - ACCOUNT MANAGER LITE PILOT (opt-in, on-demand). One place to
# authorise Real-Debrid / Premiumize / AllDebrid / TorBox / OffCloud /
# EasyDebrid / Easynews / Trakt / MDBList, which it then pushes into every
# supported add-on it finds installed -- POV and Umbrella both among them, and
# re-pushed at every Kodi startup, so an add-on installed LATER picks the
# accounts up on the next boot. Ships with script.module.acctvwr (a hard
# dependency of acctmgr, in no repo the build already carries) and with the
# developer's own repository, so from here on he is its update channel, not us.

def _acctmgr_was_removed():
    """True when Account Manager's settings are on disk but the add-on is not.

    Kodi's uninstall removes addons/<id>/ and leaves
    userdata/addon_data/<id>/ alone, so this is "it was here and somebody
    took it away" as distinct from "it was never here".
    """
    try:
        import xbmcvfs
        if _addon_on_disk('script.module.acctmgr'):
            return False
        data = xbmcvfs.translatePath(
            'special://profile/addon_data/script.module.acctmgr')
        if not xbmcvfs.exists(data):
            return False
        dirs, files = xbmcvfs.listdir(data)
        return bool(dirs or files)
    except Exception:
        return False


def ensure_acctmgr_installed():
    """Install Account Manager ON DEMAND via Kodi's native InstallAddon.

    Replaces the legacy static monolithic zip extraction. Once the target repository
    is available, this will safely download and resolve dependencies for
    script.module.acctmgr through Kodi's internal provisioning system.
    """
    if xbmc.getCondVisibility('System.HasAddon(script.module.acctmgr)'):
        return True
    try:
        from resources.libs.modular_updater import ModularUpdater
        ModularUpdater(background=False).post_install_provisioning(
            per_addon_timeout=60, ids=['script.module.acctmgr'])
    except Exception as err:
        logging.log('[Account Manager] native install failed: {0}'.format(err), level=xbmc.LOGERROR)
    return xbmc.getCondVisibility('System.HasAddon(script.module.acctmgr)')


ACCTMGR_AUTO_SETTING = 'acctmgr_auto'
# What the marker records: "this device has had Account Manager put on it by
# us, once". Deliberately NOT the pack version. Keying it on the version looks
# tidier and is wrong: the next time ACCTMGR_PACK_VERSION is bumped, every
# device whose marker holds the old version stops matching and gets a forced
# reinstall -- INCLUDING somebody who removed Account Manager on purpose in
# the meantime, which is the one thing this promises not to do. Keeping it
# current is not this function's job anyway: Account Manager updates itself
# from its developer's own repository, and the wizard menu still has a manual
# reinstall for anyone who wants one.
ACCTMGR_AUTO_DONE = 'installed'


def ensure_acctmgr_for_everyone():
    """Put Account Manager on every device -- existing installs included --
    exactly once.

    Why it stopped being opt-in: the build's "חיבור שירותים" screen now routes
    its debrid and Trakt rows through Account Manager, so one authorisation
    reaches every add-on instead of POV alone. On a device without it those
    same rows quietly fall back to authorising POV only. The screen looks
    identical either way, which is precisely why the difference must not be
    left to chance.

    ONCE per device, recorded in a wizard setting. A user who then uninstalls
    Account Manager on purpose is not fought with at every boot -- that is
    their call, and the screen still works without it.

    Silent when there is nothing to do. Never raises; the caller runs at
    startup and a failure here must not stop the rest of it."""
    try:
        if CONFIG.get_setting(ACCTMGR_AUTO_SETTING) == ACCTMGR_AUTO_DONE:
            return False
        if not CONFIG.get_setting('buildname'):
            return False            # build not installed yet -- too early

        # Check if the user deliberately removed it
        if _acctmgr_was_removed():
            logging.log(
                '[Account Manager] settings from a previous install are here but the '
                'add-on is not; treating that as a deliberate removal and not '
                'installing it again', level=xbmc.LOGINFO)
            CONFIG.set_setting(ACCTMGR_AUTO_SETTING, ACCTMGR_AUTO_DONE)
            return False

        ok = ensure_acctmgr_installed()
        if not ok:
            # No marker: a device that was offline (or where the pack host was
            # down) tries again on the next boot instead of never again.
            logging.log(
                '[Account Manager] auto-install did not complete; will retry '
                'on the next startup', level=xbmc.LOGINFO)
            return False
        CONFIG.set_setting(ACCTMGR_AUTO_SETTING, ACCTMGR_AUTO_DONE)
        xbmc.sleep(500)
        try:
            xbmc.executebuiltin('UpdateLocalAddons')
        except Exception:
            pass
        logging.log('[Account Manager] auto-installed successfully', level=xbmc.LOGINFO)
        return True
    except Exception as e:
        logging.log('[Account Manager] auto-install failed: {0}'.format(e),
                    level=xbmc.LOGERROR)
        return False


def install_acctmgr_pilot():
    """Manual (re)install behind the wizard menu entry. Account Manager now
    arrives by itself on every device (ensure_acctmgr_for_everyone), so this
    is the repair path for somebody who removed it or whose auto-install never
    completed. It changes nothing by itself: installing it does not touch a
    single existing setting, because it only writes an account into an add-on
    once the user has actually authorised that account inside it."""
    dialog = xbmcgui.Dialog()
    yes_pressed = dialog.yesno(
        CONFIG.ADDONTITLE,
        '[B]להתקין מחדש את [COLOR gold]Account Manager[/COLOR]?[/B]\n'
        'מחברים את חשבונות הדבריד פעם אחת במקום אחד, והוא מעביר אותם '
        'לכל התוספים המותקנים - גם POV וגם Umbrella. עד שתחברו חשבון, '
        'שום הגדרה קיימת לא משתנה.',
        nolabel='[B][COLOR red]ביטול[/COLOR][/B]',
        yeslabel='[B][COLOR springgreen]התקן[/COLOR][/B]')
    if not yes_pressed:
        return
    if ensure_acctmgr_installed():
        xbmc.sleep(500)
        try:
            xbmc.executebuiltin('UpdateLocalAddons')
        except Exception:
            pass

        # Record it here too so manual and auto paths leave the same mark
        try:
            CONFIG.set_setting(ACCTMGR_AUTO_SETTING, ACCTMGR_AUTO_DONE)
        except Exception:
            pass

        logging.log_notify(
            CONFIG.ADDONTITLE,
            '[COLOR {0}]הותקן! זמין תחת תוספים -> תוכניות -> '
            'Account Manager[/COLOR]'.format(CONFIG.COLOR1))


def ensure_umbrella_installed():
    """Download + extract the Umbrella pilot pack on demand (same
    battle-tested path as the NOX/AcctMgr packs, including the Addons-DB
    registration that makes Kodi actually see the new addons)."""
    return _ensure_packs_installed(
        UMBRELLA_PACKS,
        '[COLOR {0}][B]מוריד את Umbrella ותלויות[/B][/COLOR]'.format(
            CONFIG.COLOR2),
        '[COLOR {0}][B]Umbrella מוכן לשימוש[/B][/COLOR]'.format(
            CONFIG.COLOR1))


# KODI-POV-IL - UMBRELLA FOR EVERYONE. Same marker-once pattern as Account
# Manager above; see ensure_acctmgr_for_everyone for the reasoning behind each
# guard, which is identical here.
UMBRELLA_AUTO_SETTING = 'umbrella_auto'
UMBRELLA_AUTO_DONE = 'installed'


def _umbrella_was_removed():
    """True when Umbrella's settings are on disk but the add-on is not.

    Kodi's uninstall removes addons/<id>/ and leaves
    userdata/addon_data/<id>/ alone, so this is "it was here and somebody
    took it away" as distinct from "it was never here". Deliberately narrow:
    an EMPTY addon_data directory does not count, because Kodi creates one
    the first time almost anything asks for a setting.
    """
    try:
        import xbmcvfs
        if _addon_on_disk('plugin.video.umbrella'):
            return False
        data = xbmcvfs.translatePath(
            'special://profile/addon_data/plugin.video.umbrella')
        if not xbmcvfs.exists(data):
            return False
        dirs, files = xbmcvfs.listdir(data)
        return bool(dirs or files)
    except Exception:
        return False


def ensure_umbrella_for_everyone():
    """Put Umbrella and CocoScrapers on every device, existing installs
    included, exactly once.

    Why it stopped being a pilot: half the build already assumes it. The home
    screen has Umbrella tiles, the search wiring has an Umbrella branch, the
    account manager pushes debrid accounts into it, and a dozen patchers in
    the AI add-on exist only to make it behave in Hebrew. On a device without
    it, every one of those quietly does nothing -- and the screen looks the
    same either way, which is exactly why the difference must not be left to
    whether somebody found a menu entry.

    ONCE per device, recorded in a wizard setting. Somebody who then removes
    Umbrella on purpose is not fought with at every boot.

    THE PACK CARRIES ITS OWN REPOSITORIES (repository.umbrella and
    repository.cocoscrapers), so from the moment this runs the developers are
    the update channel, not us -- which is the point. We are not taking on
    shipping Umbrella releases; we are making sure the first one is there.

    Silent when there is nothing to do: the sentinel + version gate inside
    _ensure_packs_installed turns an already-current install into a file
    check rather than an 11 MB download. Never raises."""
    try:
        if CONFIG.get_setting(UMBRELLA_AUTO_SETTING) == UMBRELLA_AUTO_DONE:
            return False
        if not CONFIG.get_setting('buildname'):
            return False            # build not installed yet -- too early
        # SOMEBODY WHO ALREADY SAID NO. Umbrella has been available behind a
        # menu entry (install_umbrella_pilot) for several releases, and that
        # entry never wrote this setting -- so a user who installed it there
        # and then deliberately removed it looks exactly like a user who never
        # had it, and this function would put it back. That is the one thing
        # the docstring above promises it will not do.
        #
        # What tells them apart is what an uninstall leaves behind: the add-on
        # directory goes, its addon_data does not. Files gone plus settings
        # present is somebody who had it and got rid of it, and the answer is
        # to record that and never ask again -- not to reinstall.
        if _umbrella_was_removed():
            logging.log(
                '[Umbrella] settings from a previous install are here but the '
                'add-on is not; treating that as a deliberate removal and not '
                'installing it again', level=xbmc.LOGINFO)
            CONFIG.set_setting(UMBRELLA_AUTO_SETTING, UMBRELLA_AUTO_DONE)
            return False
        ok = ensure_umbrella_installed()
        if not ok:
            # No marker: a device that was offline (or where the pack host was
            # down) tries again on the next boot instead of never again.
            logging.log(
                '[Umbrella] auto-install did not complete; will retry on the '
                'next startup', level=xbmc.LOGINFO)
            return False
        CONFIG.set_setting(UMBRELLA_AUTO_SETTING, UMBRELLA_AUTO_DONE)
        xbmc.sleep(500)
        try:
            xbmc.executebuiltin('UpdateLocalAddons')
        except Exception:
            pass
        logging.log('[Umbrella] auto-installed {0}'.format(
            UMBRELLA_PACK_VERSION), level=xbmc.LOGINFO)
        return True
    except Exception as e:
        logging.log('[Umbrella] auto-install failed: {0}'.format(e),
                    level=xbmc.LOGERROR)
        return False


def install_umbrella_pilot():
    """Manual (re)install behind the wizard menu entry.

    Umbrella now arrives by itself on every device
    (ensure_umbrella_for_everyone), so this is the repair path for somebody
    who removed it, or whose auto-install never completed because the device
    was offline at the wrong moment. It still touches nothing else: no home
    screen change, no default, no existing setting."""
    dialog = xbmcgui.Dialog()
    yes_pressed = dialog.yesno(
        CONFIG.ADDONTITLE,
        '[B]להתקין את [COLOR gold]Umbrella[/COLOR] (ניסיוני)?[/B]\n'
        'תוסף תוכן נוסף שפועל לצד POV, עם חיפוש ומקורות משלו, '
        'ומתעדכן ישירות מהמפתחים שלו. לא משנה שום דבר קיים בבילד.',
        nolabel='[B][COLOR red]ביטול[/COLOR][/B]',
        yeslabel='[B][COLOR springgreen]התקן[/COLOR][/B]')
    if not yes_pressed:
        return
    if ensure_umbrella_installed():
        xbmc.sleep(500)
        try:
            xbmc.executebuiltin('UpdateLocalAddons')
        except Exception:
            pass
        # RECORDED HERE TOO, so that from now on the automatic install and
        # the manual one leave the same mark. Without it, anybody using this
        # entry stays in the population _umbrella_was_removed has to guess
        # about.
        try:
            CONFIG.set_setting(UMBRELLA_AUTO_SETTING, UMBRELLA_AUTO_DONE)
        except Exception:
            pass
        logging.log_notify(
            CONFIG.ADDONTITLE,
            '[COLOR {0}]Umbrella הותקן! זמין תחת תוספים -> הרחבות וידאו'
            '[/COLOR]'.format(CONFIG.COLOR1))


def _addon_on_disk(addon_id):
    """True when addons/<id>/addon.xml is really there. Never raises."""
    try:
        import xbmcvfs
        return xbmcvfs.exists(xbmcvfs.translatePath(
            'special://home/addons/{0}/addon.xml'.format(addon_id)))
    except Exception:
        return False


def _af3_register_pack_in_db(pack):
    """Register + enable a pack's addons in Kodi's Addons DB. Safe to
    call repeatedly (INSERT OR IGNORE + UPDATE enabled). It needs no pack
    zip on disk, which is what lets it heal users whose files were already
    extracted by an older code path.

    IT DOES NEED THE FILES. This used to register the whole static
    addon_ids list unconditionally, trusting that the "already current"
    fast path above (_af3_pack_current) only skips the download after
    checking every file was really there. It didn't -- it checked ONE
    sentinel file. A device with only the sentinel present and the rest of
    the pack's addons entirely absent got every one of them written into
    Kodi's DB as installed and enabled, this function reported success, the
    caller wrote the "done" marker, and the device was never corrected
    again. Telling Kodi an add-on exists when it does not is worse than
    telling it nothing -- Kodi then resolves dependencies against a lie.

    So: register what is actually on disk, and REPORT FAILURE for anything
    that is not, so the caller does not mark the job done."""
    wanted = list(pack.get('addon_ids') or ())
    present = [addon_id for addon_id in wanted if _addon_on_disk(addon_id)]
    absent = [addon_id for addon_id in wanted if addon_id not in present]
    if absent:
        logging.log(
            'DEBUG | _ensure_packs_installed | '
            'NOT registering {0} -- not on disk: {1}'.format(
                pack['name'], absent))
    if not present:
        return False
    try:
        db.addon_database(present, 1, True)
        logging.log(
            'DEBUG | _ensure_packs_installed | '
            'DB enabled: {0}'.format(present))
        return not absent
    except Exception as e:
        logging.log(
            'DEBUG | _ensure_packs_installed | '
            'DB enable failed for {0}: {1}'.format(
                pack['name'], str(e)))
        return False


def _af3_pack_installed(sentinel):
    try:
        import xbmcvfs
        return xbmcvfs.exists(xbmcvfs.translatePath(sentinel))
    except Exception:
        return False


def _af3_read_addon_version(addon_xml):
    try:
        import re
        import xbmcvfs
        path = xbmcvfs.translatePath(addon_xml)
        with open(path, 'r', encoding='utf-8') as fh:
            text = fh.read(600)
        # IMPORTANT: skip the XML declaration's version (<?xml version="1.0"?>)
        # and read the <addon> tag's version instead. Anchoring on 'version='
        # alone matches the declaration first, so every addon looked like
        # "1.0" -- which made the deps-pack version gate think a stale
        # jurialmunkey 0.2.28 was already current (1.0 >= 0.2.35) and skip the
        # upgrade. Search from the '<addon' tag so we get the real version.
        anchor = text.find('<addon')
        search_from = anchor if anchor >= 0 else 0
        match = re.search(r'\bversion="([^"]+)"', text[search_from:])
        return match.group(1) if match else ''
    except Exception:
        return ''


def _version_tuple(ver):
    """Best-effort numeric version tuple for comparison. Non-numeric
    parts degrade to 0 so a malformed version never raises."""
    parts = []
    for chunk in str(ver).split('.'):
        num = ''.join(ch for ch in chunk if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts)


def _af3_pack_current(pack):
    if not _af3_pack_installed(pack['sentinel']):
        return False
    # THE SENTINEL VOUCHES FOR ITSELF, NOT FOR THE WHOLE PACK. Checking only
    # the sentinel file and skipping the download for everything else is how
    # a device ends up with the sentinel present, the rest of the pack's
    # addons absent, and nothing that will ever repair it: registration
    # (_af3_register_pack_in_db) correctly refuses to vouch for files that
    # aren't there, but this fast path would then keep skipping the
    # re-download on every subsequent boot for the exact same reason.
    # Correctly-reported failure that never self-corrects is still never
    # self-correcting -- so every addon_id in the pack has to actually be on
    # disk before we call it current.
    missing = [addon_id for addon_id in (pack.get('addon_ids') or ())
               if not _addon_on_disk(addon_id)]
    if missing:
        logging.log(
            'skin/content pack is incomplete, forcing reinstall: {0} '
            'missing={1}'.format(pack['name'], missing))
        return False
    expected = pack.get('expected_version')
    if not expected:
        return True
    current = _af3_read_addon_version(pack['sentinel'])
    # "Current" means installed >= expected. A newer installed version is
    # fine (don't force a needless downgrade/re-extract); only an OLDER or
    # missing version triggers a reinstall. Falls back to exact-match if
    # either version can't be parsed.
    try:
        if _version_tuple(current) >= _version_tuple(expected):
            return True
    except Exception:
        if current == expected:
            return True
    logging.log(
        'skin pack version too old, forcing reinstall: {0} '
        'current={1} expected>={2}'.format(
            pack['name'], current or 'missing', expected))
    return False


AF3_SKIN_ID = 'skin.arctic.fuse.3'


def ensure_arctic_fuse_3_installed():
    """Install Arctic Fuse 3 ON DEMAND via Kodi's native InstallAddon.

    Replaces the old four static "pack" zips. The AF3 skin and ALL of its
    dependencies (script.module.jurialmunkey, plugin.video.themoviedb.helper,
    script.skinvariables, script.texturemaker, the fonts / studio / weather
    resource addons, ...) are resolved natively from repository.jurialmunkey
    (shipped in our manifest, so it is already on the device) plus the official
    Kodi repo, at mutually-compatible upstream versions. They then keep updating
    from their own repos -- no version-pinned bundle to maintain.

    Reuses the provisioning watchdog (auto-confirms the native dependency
    Yes/No dialog, closes stray first-run popups) so the install is hands-off.
    Returns True once AF3 is present. Idempotent: a no-op if already installed.
    """
    if xbmc.getCondVisibility('System.HasAddon({0})'.format(AF3_SKIN_ID)):
        return True
    try:
        from resources.libs.modular_updater import ModularUpdater
        # Longer timeout than the content-addon default: the AF3 skin + tmdbhelper
        # + font/studio resources are a sizeable native download.
        ModularUpdater(background=False).post_install_provisioning(
            per_addon_timeout=240, ids=[AF3_SKIN_ID])
    except Exception as err:
        logging.log('[AF3] native install failed: {0}'.format(err), level=xbmc.LOGERROR)
    return xbmc.getCondVisibility('System.HasAddon({0})'.format(AF3_SKIN_ID))


def ensure_nox_installed():
    """Download + extract the NOX skin pack on demand (see _ensure_packs_installed)."""
    return _ensure_packs_installed(
        NOX_PACKS,
        '[COLOR {0}][B]מוריד את סקין NOX[/B][/COLOR]'.format(CONFIG.COLOR2),
        '[COLOR {0}][B]סקין NOX מוכן לשימוש[/B][/COLOR]'.format(CONFIG.COLOR1))


def auto_update_active_skin_pack():
    """Refresh an on-demand skin pack (currently NOX) when the user is already
    ON that skin and a newer version has been published. The pack is otherwise
    only (re)installed when picked from Switch Skin, so without this an existing
    NOX user never gets skin updates from a normal quick_update -- they had to
    switch away and back. Idempotent: the version gate (_af3_pack_current) means
    we only re-download when the on-disk skin is actually OLDER than what we now
    ship, so it does NOT re-download every boot, and it does NOT re-download when
    the user merely toggles skins. Re-extracting overwrites only the skin's addon
    files under addons/skin.povil.nox -- never userdata/addon_data skin settings,
    so the user's favourites order and skin tweaks are preserved."""
    try:
        active = CONFIG.SKIN or ''
        if 'skin.povil.nox' not in active:
            return
        pack = NOX_PACKS[0]
        if _af3_pack_current(pack):
            return  # on-disk version already current; no re-download
        logging.log(
            '[Skin Auto Update] NOX is active and the installed pack is behind '
            '{0}; refreshing it now.'.format(pack.get('expected_version')),
            level=xbmc.LOGINFO)
        if ensure_nox_installed():
            xbmc.sleep(800)
            try:
                xbmc.executebuiltin('ReloadSkin()')
            except Exception:
                pass
    except Exception as e:
        logging.log('[Skin Auto Update] failed: {0}'.format(e),
                    level=xbmc.LOGERROR)


def _ensure_packs_installed(packs, downloading_label, ready_label):
    """Download + extract any supplemental skin packs that aren't already
    on disk. Returns True if all packs are present at the end; False if any
    failed. Best-effort: shows a progress dialog with per-pack labels;
    on failure, surfaces a Hebrew notification and bails.

    Reuses the wizard's existing Downloader + extract.all machinery
    -- the same code that powers quick_update and Fresh Install --
    so progress / cancel / error reporting all behave the same way.
    Generic over a packs list so NOX (and any future on-demand
    skin) share one battle-tested install path, including the critical
    Addons-DB register step that prevents the silent Estuary fallback."""
    try:
        all_ok = True
        dialog_progress = xbmcgui.DialogProgress()
        dialog_progress.create(CONFIG.ADDONTITLE, downloading_label)

        for i, pack in enumerate(packs, start=1):
            if dialog_progress.iscanceled():
                dialog_progress.close()
                return False

            label = '[COLOR {0}][B]{1}/{2}[/B][/COLOR] - {3}'.format(
                CONFIG.COLOR1, i, len(packs), pack['name'])
            dialog_progress.update(
                int((i - 1) / len(packs) * 100), label)

            if _af3_pack_current(pack):
                # Files already on disk (this user switched to AF3
                # before, possibly with the old DB-less code). Skip the
                # 50-60 MB re-download/extract -- but STILL re-register
                # in the Addons DB so the retroactive fix lands. This is
                # the path that heals everyone already stuck on the
                # Estuary fallback.
                logging.log(
                    'skin pack files present, skipping download but '
                    're-registering in DB: {0}'.format(pack['name']))
                if not _af3_register_pack_in_db(pack):
                    all_ok = False
                continue

            lib = os.path.join(CONFIG.PACKAGES, pack['filename'])
            try:
                if os.path.exists(lib):
                    os.remove(lib)
            except Exception:
                pass

            response = tools.open_url(pack['url'], check=True)
            if not response:
                dialog_progress.close()
                logging.log_notify(
                    CONFIG.ADDONTITLE,
                    '[COLOR {0}]חבילת הסקין לא זמינה: {1}[/COLOR]'.format(
                        CONFIG.COLOR2, pack['name']))
                logging.log(
                    'DEBUG | _ensure_packs_installed | '
                    '{0} not reachable: {1}'.format(
                        pack['name'], pack['url']))
                return False

            try:
                Downloader().download(pack['url'], lib)
            except Exception as e:
                dialog_progress.close()
                logging.log(
                    'DEBUG | _ensure_packs_installed | '
                    'download failed for {0}: {1}'.format(
                        pack['name'], str(e)))
                logging.log_notify(
                    CONFIG.ADDONTITLE,
                    '[COLOR {0}]כשל בהורדת חבילת הסקין![/COLOR]'.format(
                        CONFIG.COLOR2))
                return False

            xbmc.sleep(300)
            if not os.path.exists(lib) or os.path.getsize(lib) == 0:
                dialog_progress.close()
                logging.log_notify(
                    CONFIG.ADDONTITLE,
                    '[COLOR {0}]חבילת הסקין ריקה: {1}[/COLOR]'.format(
                        CONFIG.COLOR2, pack['name']))
                return False

            extract_title = (
                '[COLOR {0}][B]מתקין:[/B][/COLOR] [COLOR {1}]{2}[/COLOR]'
                .format(CONFIG.COLOR2, CONFIG.COLOR1, pack['name']))
            try:
                extract.all(lib, CONFIG.HOME, title=extract_title)
            except Exception as e:
                dialog_progress.close()
                logging.log(
                    'DEBUG | _ensure_packs_installed | '
                    'extract failed for {0}: {1}'.format(
                        pack['name'], str(e)))
                logging.log_notify(
                    CONFIG.ADDONTITLE,
                    '[COLOR {0}]כשל בחילוץ חבילת הסקין![/COLOR]'.format(
                        CONFIG.COLOR2))
                all_ok = False

            # CRITICAL: register every addon in this pack in Kodi's
            # Addons DB and mark it enabled. extract.all only writes
            # files to disk -- it does NOT tell Kodi the addons exist.
            # Without this, AF3 and its dependencies (skinvariables,
            # texturemaker, tmdbhelper, the two resource.* addons, the
            # weather icons, the cjk font) sit on disk but are 'not
            # installed' from Kodi's POV. When the skin is then set to
            # AF3, Kodi finds the dependencies unmet, refuses to load
            # the skin, and SILENTLY FALLS BACK TO skin.estuary -- the
            # "it says switched but I get the simple skin" bug. This
            # mirrors what quick_update / Fresh Install do after their
            # own extract.all calls.
            if not _af3_register_pack_in_db(pack):
                all_ok = False

            try:
                os.remove(lib)
            except Exception:
                pass

        # Force Kodi to scan the freshly-extracted addon folders so the
        # dependency graph is satisfiable in THIS session as well as
        # after the restart. Without the scan, the addon manager's
        # in-memory view is stale and the skin load on next boot can
        # still race the DB read on some Android builds.
        try:
            xbmc.executebuiltin('UpdateLocalAddons')
            xbmc.sleep(2500)
        except Exception:
            pass

        dialog_progress.update(100, ready_label)
        xbmc.sleep(800)
        dialog_progress.close()
        return all_ok

    except Exception as e:
        try:
            dialog_progress.close()
        except Exception:
            pass
        logging.log(
            'DEBUG | _ensure_packs_installed | '
            'unexpected exception: {0}'.format(str(e)))
        logging.log_notify(
            CONFIG.ADDONTITLE,
            '[COLOR {0}]שגיאה בהתקנת חבילת סקין[/COLOR]'.format(
                CONFIG.COLOR2))
        return False


AF3_TOOLS = [
    {
        'id': 'connect_services',
        'label': 'חיבור שירותים',
        'icon': 'special://home/media/povil_icons/Connect_Services.png',
        'builtin': 'RunPlugin("plugin://plugin.video.pov/?mode=myservices")',
    },
    {
        'id': 'debrid_notice_settings',
        'label': 'הגדרת התראות מנוי',
        'icon': 'special://home/media/povil_icons/Connect_Services.png',
        'builtin': 'RunScript(service.subtitles.kodipovilai,action=debrid_notice_settings)',
    },
    {
        'id': 'pov',
        'label': 'כניסה ל-POV',
        'icon': 'special://home/media/povil_icons/Logo_POV_IL.png',
        'builtin': 'RunAddon("plugin.video.pov")',
    },
    {
        'id': 'ai_settings',
        'label': 'הגדרות תרגום AI',
        'icon': 'special://home/addons/service.subtitles.kodipovilai/icon.png',
        'builtin': 'Addon.OpenSettings(service.subtitles.kodipovilai)',
    },
    {
        'id': 'quick_update',
        'label': 'עדכון מהיר',
        'icon': 'special://home/media/povil_icons/fast_update_pov_il.png',
        'builtin': 'PlayMedia("plugin://plugin.program.kodipovilwizard/?mode=install&action=quick_update&name=Kodi+POV+IL+-+FENtastic&auto_quick_update=false")',
    },
    {
        'id': 'switch_skin',
        'label': 'החלף סקין',
        'icon': 'special://home/media/povil_icons/wizard_pov_il.png',
        'builtin': 'RunPlugin("plugin://plugin.program.kodipovilwizard/?mode=install&action=build_switch_skin")',
    },
    {
        'id': 'send_log',
        'label': 'שליחת לוג',
        'icon': 'special://home/media/povil_icons/twilight_send_log.png',
        'builtin': 'ActivateWindow(10025,"plugin://plugin.video.pov/?mode=navigator.log_utils&name=Changelog%20%26%20Log%20Utils",return)',
    },
    {
        'id': 'reload_skin',
        'label': 'טעינת סקין מחדש',
        'icon': 'special://skin/extras/icons/refresh.png',
        'builtin': 'ReloadSkin()',
    },
    {
        'id': 'settings',
        'label': 'הגדרות Kodi',
        'icon': 'special://skin/extras/icons/settings.png',
        'builtin': 'ActivateWindow(settings)',
    },
    {
        'id': 'quit',
        'label': 'יציאה',
        'icon': 'special://skin/extras/icons/power.png',
        'builtin': 'Quit()',
    },
]


def _plugin_url(action, **kwargs):
    query = ['mode=install', 'action={0}'.format(quote_plus(action))]
    for key, value in kwargs.items():
        query.append('{0}={1}'.format(key, quote_plus(value)))
    return 'plugin://{0}/?{1}'.format(CONFIG.ADDON_ID, '&'.join(query))


def af3_tools_menu():
    """Touch-friendly AF3 tools row. The skin power menu is easy to
    miss on phones, so AF3 home widgets can show this directory as
    large cards."""
    try:
        handle = int(sys.argv[1])
    except Exception:
        handle = -1
    items = []
    for tool in AF3_TOOLS:
        li = xbmcgui.ListItem(tool['label'])
        li.setArt({
            'icon': tool['icon'],
            'thumb': tool['icon'],
            'poster': tool['icon'],
            'fanart': 'special://home/media/povil_icons/Logo_POV_IL.png',
        })
        li.setProperty('IsPlayable', 'false')
        url = _plugin_url('af3_tool', tool=tool['id'])
        items.append((url, li, False))
    if handle >= 0:
        xbmcplugin.addDirectoryItems(handle, items, len(items))
        xbmcplugin.setContent(handle, 'files')
        xbmcplugin.endOfDirectory(handle, cacheToDisc=False)


def af3_tool_action(tool_id):
    for tool in AF3_TOOLS:
        if tool['id'] == tool_id:
            xbmc.executebuiltin(tool['builtin'])
            return True
    return False


def switch_skin_in_gui_settings(gotoskin):
    try:
        import xbmcvfs
        guisettings_file_path = xbmcvfs.translatePath("special://userdata/guisettings.xml")
        import xml.etree.ElementTree as ET
        tree = ET.parse(guisettings_file_path)
        root = tree.getroot()
        # Find the setting with id="lookandfeel.skin"
        for setting in root.iter('setting'):
            if setting.get('id') == 'lookandfeel.skin':
                # Remove default attribute, if present
                if 'default' in setting.attrib:
                    del setting.attrib['default']
                # Change the value to gotoskin
                setting.text = gotoskin
        # Write the modified tree back to the file
        tree.write(guisettings_file_path)
        return True
    except Exception as e:
        logging.log_notify(CONFIG.ADDONTITLE,
                           '[COLOR {0}]שגיאה בהחלפת סקין![/COLOR]'.format(CONFIG.COLOR2))
        logging.log(f"DEBUG | switch_skin_in_gui_settings | Exception: {str(e)}")
        return False

def build_switch_skin():

    if not CONFIG.get_setting('buildname'):
        logging.log_notify(CONFIG.ADDONTITLE,
                           '[COLOR {0}]לא מותקן בילד![/COLOR]'.format(CONFIG.COLOR2))
        return


    from resources.libs.gui import window
    msg = f"הסקינים הקיימים בבילד:\n1. סקין Estuary\n2. סקין FENtastic\n3. סקין Arctic Fuse 3\n4. סקין NOX"
    window.show_notification_with_extra_image(msg, 888, CONFIG.BUILD_SKIN_SWITCH_IMAGE_URL)

    skin_mapping = {
        'סקין Estuary - מראה פשוט עם כפתורים': 'skin.estuary',
        'סקין FENtastic - יפהפה': 'skin.fentastic',
        'סקין Arctic Fuse 3 - מודרני (ניסיוני)': 'skin.arctic.fuse.3',
        'סקין NOX - עברית מלאה (ניסיוני)': 'skin.povil.nox'
    }

    # Get the name of the current active skin. If the user manually
    # switched to a skin not in our mapping (e.g. via Kodi's own
    # Settings -> Interface -> Skin), `next()` without a default
    # would raise StopIteration and crash the whole wizard. Default
    # to a generic Hebrew label so the dialog still renders and the
    # user can pick a known skin to recover.
    current_skin_name = next(
        (skin_name for skin_name, skin_addon_name in
         skin_mapping.items() if skin_addon_name in CONFIG.SKIN),
        'סקין לא מזוהה'
    )

    # Filter out the current active skin from the list
    skins_list = [skin_name for skin_name, skin_addon_name in skin_mapping.items() if skin_addon_name not in CONFIG.SKIN]

    # Create a dialog window
    dialog = xbmcgui.Dialog()
    gotoskin_index_number = dialog.select(f"[B]סקין נוכחי: [COLOR gold]{current_skin_name}[/COLOR][/B]", skins_list)

    if gotoskin_index_number == -1:  # User cancelled the menu
        return

    selected_skin = skins_list[gotoskin_index_number]
    gotoskin = skin_mapping[selected_skin]

    yes_pressed = dialog.yesno(CONFIG.ADDONTITLE,
                       '[B][COLOR {0}]האם ברצונך להחליף סקין ל:'.format(CONFIG.COLOR2) + '\n' + '[COLOR {0}]{1}[/COLOR]?[/COLOR][/B]'.format(CONFIG.COLOR1, selected_skin),
                       nolabel='[B][COLOR red]ביטול[/COLOR][/B]',
                       yeslabel='[B][COLOR springgreen]החלף סקין[/COLOR][/B]')

    if yes_pressed:
        # Arctic Fuse 3 is installed ON DEMAND, natively, from
        # repository.jurialmunkey (Kodi resolves the skin + all its deps) the
        # first time the user switches to it. Idempotent: a no-op once present.
        if gotoskin == 'skin.arctic.fuse.3':
            if not ensure_arctic_fuse_3_installed():
                logging.log_notify(
                    CONFIG.ADDONTITLE,
                    '[COLOR {0}]Arctic Fuse 3 לא הותקן - מבטל[/COLOR]'.format(
                        CONFIG.COLOR2))
                return
        # NOX is also too big to bundle in the base build; download +
        # extract it on first switch, identical to the AF3 path.
        elif gotoskin == 'skin.povil.nox':
            if not ensure_nox_installed():
                logging.log_notify(
                    CONFIG.ADDONTITLE,
                    '[COLOR {0}]סקין NOX לא הותקן - מבטל[/COLOR]'.format(
                        CONFIG.COLOR2))
                return

        dialogProgress = xbmcgui.DialogProgress()
        dialog_text = '[COLOR {0}][B]מחליף סקין ומגדיר את מסך הבית של:[/B][/COLOR]\n[COLOR {1}][B]{2}[/B][/COLOR]'.format(CONFIG.COLOR2, CONFIG.COLOR1, selected_skin)
        dialogProgress.create(CONFIG.ADDONTITLE, dialog_text)
        for s in range(3, -1, -1):
            dialogProgress.update(int((3 - s) / 3.0 * 100), dialog_text)
            xbmc.sleep(1000)

        # guisettings.xml | Configure lookandfeel.skin setting
        if not switch_skin_in_gui_settings(gotoskin): return

        xbmc.sleep(500)

        # favourites.xml | Switch to selected build's skin favourites.xml
        if not update_favourites_xml_file(gotoskin): return

        dialogProgress.close()
        Wizard().force_close_kodi_in_5_seconds(dialog_header="סקין הוחלף בהצלחה!")
    else:
        return

##########################################
# KODI-RD-IL - UPDATE CHECK

def parse_version(ver_str):
    """Converts '21.0-Omega' or '21.0.1' into a tuple of integers like (21, 0)."""
    import re
    match = re.search(r'^(\d+(?:\.\d+)+)', ver_str)
    if match:
        return tuple(map(int, match.group(1).split('.')))
    return (0, 0)

def get_current_kodi_version():
    """Extracts the numeric float version (e.g., 21.0) from the running Kodi instance."""
    import re
    import xbmc
    build_version = xbmc.getInfoLabel('System.BuildVersion')
    return parse_version(build_version)

def get_latest_official_kodi_version():
    """Fetches the latest official Kodi release version from the Kodi GitHub API."""
    import json
    import urllib.request as urllib_req

    try:
        url = "https://api.github.com/repos/xbmc/xbmc/releases/latest"
        req = urllib_req.Request(url, headers={'User-Agent': 'Kodi-POV-IL-Wizard'})
        with urllib_req.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            tag_name = data.get('tag_name', '')
            return parse_version(tag_name)
    except Exception as e:
        from resources.libs.common import logging
        logging.log(f"DEBUG | get_latest_official_kodi_version | Failed: {str(e)}")

    return None

def kodi_version_update_check(kodi_version_update_check_manual="false"):
    kodi_version_update_check_manual = True if kodi_version_update_check_manual == "true" else False
    os_type_label = tools.platform().capitalize()
    dialog = xbmcgui.Dialog()

    try:
        current_version = get_current_kodi_version()
        latest_version = get_latest_official_kodi_version()
        current_str = ".".join(map(str, current_version))
        latest_str = ".".join(map(str, latest_version))

        if not latest_version:
            if kodi_version_update_check_manual:
                dialog.ok(f"{CONFIG.ADDONTITLE} ({os_type_label})",
                          "[COLOR yellow][B]לא הצלחנו לבדוק את הגרסה העדכנית.[/B][/COLOR]\nנסה שוב מאוחר יותר.")
            return

        if latest_version > current_version:
            dialog.ok(f"{CONFIG.ADDONTITLE} ({os_type_label})",
                      f'[COLOR yellow][B]קיים עדכון רשמי ל-Kodi![/B][/COLOR]\n\n'
                      f'גרסה נוכחית: [B][COLOR red]{current_str}[/COLOR][/B]\n'
                      f'גרסה מעודכנת: [B][COLOR limegreen]{latest_str}[/COLOR][/B]\n\n'
                      f'הבילד שלנו מותאם לרוץ על Kodi נקי והעדכני ביותר.\n'
                      f'אנא עדכן את קודי דרך החנות הרשמית במכשירך או אתר Kodi.tv.')

        elif kodi_version_update_check_manual:
            dialog.ok(f"{CONFIG.ADDONTITLE} ({os_type_label})",
                      f'[COLOR limegreen][B]קודי (Kodi) מעודכן לגרסה האחרונה![/B][/COLOR]\n\n'
                      f'גרסה נוכחית: [B]{current_str}[/B]')

    except Exception as e:
        from resources.libs.common import logging
        logging.log(f'[kodi_version_update_check] Exception: {str(e)}')
        if kodi_version_update_check_manual:
            dialog.ok(f"{CONFIG.ADDONTITLE} ({os_type_label})", f'התרחשה שגיאה:\n{str(e)}')

# KODI-RD-IL - ANDROID
# Required helper for the real_debrid_speedtest android browsers check
def check_if_app_installed(app_package_id):
    import xbmcvfs
    try:
        apps = xbmcvfs.listdir('androidapp://sources/apps/')[1]
        return app_package_id in apps
    except Exception:
        return False
##########################################


##########################################
# KODI-RD-IL - NETWORK TOOLS FUNCTIONS

def standard_speedtest():
    """Launches the standard Kodi speed test addon, installs it if missing."""
    # Check if the addon is already installed
    if not xbmc.getCondVisibility('System.HasAddon(script.speedtester)'):
        xbmc.executebuiltin('InstallAddon("script.speedtester")')

    # Run the addon
    xbmc.executebuiltin('RunAddon("script.speedtester")')


def real_debrid_speedtest():
    """Opens the default system browser or supported Android browser to Real Debrid speedtest."""
    os_type_label = tools.platform().capitalize()

    # Windows platform
    if tools.platform() == 'windows':
        import webbrowser
        webbrowser.get().open_new_tab("https://real-debrid.com/speedtest")

    # Android / Android TV platform
    elif tools.platform() == 'android':
        android_apps_browsers_list = ['com.android.chrome', 'com.phlox.tvwebbrowser', 'com.seraphic.openinet.pre', 'com.tcl.browser']
        installed_browser_package_id = None

        # Check for installed browsers from the supported list
        for browser_package_id in android_apps_browsers_list:
            if check_if_app_installed(browser_package_id):
                installed_browser_package_id = browser_package_id
                break

        # If no supported browser found, prompt user to visit Play Store
        if not installed_browser_package_id:
            dialog = xbmcgui.Dialog()
            yes_pressed = dialog.yesno(f"{CONFIG.ADDONTITLE} ({os_type_label})",
                               f'[B][COLOR yellow]לא מותקן דפדפן תומך!\nדפדפנים נתמכים:[/COLOR]\nGoogle Chrome, TV Bro, OPEN BROWSER, BrowseHere[/B]',
                               nolabel='[B]ביטול[/B]',
                               yeslabel='[B]קח אותי לחנות[/B]')
            if yes_pressed:
                xbmc.executebuiltin('StartAndroidActivity(com.android.vending)')
            return

        # Launch browser with the specified URL
        app      = installed_browser_package_id
        intent   = 'android.intent.action.VIEW'
        dataType = ''
        dataURI  = "https://real-debrid.com/speedtest"
        xbmc.executebuiltin(f'StartAndroidActivity("{app}", "{intent}", "{dataType}", "{dataURI}")')

    # Unsupported OS
    else:
        dialog = xbmcgui.Dialog()
        dialog.ok(CONFIG.ADDONTITLE, f"[B]פתיחת דפדפן עבור בדיקת מהירות Real Debrid אינה זמינה עבור מערכת ההפעלה: {os_type_label}[/B]")


def speedtest_dialog():
    """Displays a choice dialog for legacy buttons or favorites.xml shortcuts."""
    dialog = xbmcgui.Dialog()
    yes_pressed = dialog.yesno(CONFIG.ADDONTITLE,
                       f'[B][COLOR yellow]האם להפעיל בדיקת מהירות דרך הרחבת Speed Test או דרך האתר של ריל דבריד?[/COLOR][/B]',
                       nolabel='[B]Speed Test[/B]',
                       yeslabel='[B]Real Debrid[/B]')

    if not yes_pressed:
        standard_speedtest()
    else:
        real_debrid_speedtest()
#############################################
