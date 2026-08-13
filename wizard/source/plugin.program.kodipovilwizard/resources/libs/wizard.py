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
from resources.libs.common import release_version
from resources.libs.common import tools
from resources.libs.common.config import CONFIG
from resources.libs.downloader import Downloader


def _quick_update_extract_ok(result):
    """Only a complete, error-free extraction may advance the note id."""
    try:
        percent, errors, _error = result
        return int(percent) == 100 and int(errors) == 0
    except (TypeError, ValueError):
        return False


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
        # if action == 'normal':
            # if CONFIG.KEEPTRAKT == 'true':
                # from resources.libs import traktit
                # traktit.auto_update('all')
                # CONFIG.set_setting('traktnextsave', tools.get_date(days=3, formatted=True))
            # if CONFIG.KEEPDEBRID == 'true':
                # from resources.libs import debridit
                # debridit.auto_update('all')
                # CONFIG.set_setting('debridnextsave', tools.get_date(days=3, formatted=True))
            # if CONFIG.KEEPLOGIN == 'true':
                # from resources.libs import loginit
                # loginit.auto_update('all')
                # CONFIG.set_setting('loginnextsave', tools.get_date(days=3, formatted=True))

        temp_kodiv = int(CONFIG.KODIV)
        buildv = int(float(check.check_build(name, 'kodi')))

        if not temp_kodiv == buildv:
            warning = True
        else:
            warning = False

        if warning:
            yes_pressed = self.dialog.yesno("{0} - [COLOR red]WARNING!![/COLOR]".format(CONFIG.ADDONTITLE), '[COLOR {0}]There is a chance that the skin will not appear correctly'.format(CONFIG.COLOR2) + '\n' + 'When installing a {0} build on a Kodi {1} install'.format(check.check_build(name, 'kodi'), CONFIG.KODIV) + '\n' + 'Would you still like to install: [COLOR {0}]{1} v{2}[/COLOR]?[/COLOR]'.format(CONFIG.COLOR1, name, check.check_build(name, 'version')), nolabel='[B][COLOR red]No, Cancel[/COLOR][/B]', yeslabel='[B][COLOR springgreen]Yes, Install[/COLOR][/B]')
        else:
            if over:
                yes_pressed = 1
            else:
                yes_pressed = self.dialog.yesno(CONFIG.ADDONTITLE, '[COLOR {0}]האם ברצונך להוריד ולהתקין את '.format(CONFIG.COLOR2) + '[COLOR {0}]{1} v{2}[/COLOR]?[/COLOR]'.format(CONFIG.COLOR1, name, check.check_build(name,'version')), nolabel='[B][COLOR red]ביטול[/COLOR][/B]', yeslabel='[B][COLOR springgreen]התקנה[/COLOR][/B]')
        if yes_pressed:
            CONFIG.clear_setting('build')
            buildzip = check.check_build(name, 'url')
            zipname = name.replace('\\', '').replace('/', '').replace(':', '').replace('*', '').replace('?', '').replace('"', '').replace('<', '').replace('>', '').replace('|', '')

            self.dialogProgress.create(CONFIG.ADDONTITLE, '[COLOR {0}][B]Downloading:[/B][/COLOR] [COLOR {1}]{2} v{3}[/COLOR]'.format(CONFIG.COLOR2, CONFIG.COLOR1, name, check.check_build(name, 'version')) + '\n' + 'Please Wait')

            lib = os.path.join(CONFIG.MYBUILDS, '{0}.zip'.format(zipname))
            
            try:
                os.remove(lib)
            except:
                pass

            Downloader().download(buildzip, lib)
            xbmc.sleep(500)
            
            if os.path.getsize(lib) == 0:
                try:
                    os.remove(lib)
                except:
                    pass
                    
                return
                
            install.wipe()
                
            skin.look_and_feel_data('save')
            
            title = '[COLOR {0}][B]Installing:[/B][/COLOR] [COLOR {1}]{2} v{3}[/COLOR]'.format(CONFIG.COLOR2, CONFIG.COLOR1, name, check.check_build(name, 'version'))
            self.dialogProgress.update(0, title + '\n' + 'Please Wait')
            percent, errors, error = extract.all(lib, CONFIG.HOME, title=title)
            
            skin.skin_to_default('Build Install')

            if int(float(percent)) > 0:
                db.fix_metas()
                CONFIG.set_setting('buildname', name)
                CONFIG.set_setting('buildversion', check.check_build(name, 'version'))
                CONFIG.set_setting('buildtheme', '')
                CONFIG.set_setting('latestversion', check.check_build(name, 'version'))
                CONFIG.set_setting('nextbuildcheck', tools.get_date(days=CONFIG.UPDATECHECK, formatted=True))
                CONFIG.set_setting('installed', 'true')
                CONFIG.set_setting('extract', percent)
                CONFIG.set_setting('errors', errors)
                logging.log('INSTALLED {0}: [ERRORS:{1}]'.format(percent, errors))

                # try:
                    # os.remove(lib)
                # except:
                    # pass

                if int(float(errors)) > 0:
                    yes_pressed = self.dialog.yesno(CONFIG.ADDONTITLE,
                                       '[COLOR {0}][COLOR {1}]{2} v{3}[/COLOR]'.format(CONFIG.COLOR2, CONFIG.COLOR1, name, check.check_build(name, 'version')) +'\n' + 'Completed: [COLOR {0}]{1}{2}[/COLOR] [Errors:[COLOR {3}]{4}[/COLOR]]'.format(CONFIG.COLOR1, percent, '%', CONFIG.COLOR1, errors) + '\n' + 'Would you like to view the errors?[/COLOR]',
                                       nolabel='[B][COLOR red]No Thanks[/COLOR][/B]',
                                       yeslabel='[B][COLOR springgreen]View Errors[/COLOR][/B]')
                    if yes_pressed:
                        from resources.libs.gui import window
                        window.show_text_box("Viewing Build Install Errors", error)
                self.dialogProgress.close()

                from resources.libs.gui.build_menu import BuildMenu
                themecount = BuildMenu().theme_count(name)

                if themecount > 0:
                    self.theme(name)

                db.addon_database(CONFIG.ADDON_ID, 1)
                # db.force_check_updates(over=True)
                # if os.path.exists(os.path.join(CONFIG.USERDATA, '.enableall')):
                    # CONFIG.set_setting('enable_all', 'true')
                
                #########################################################################################################
                # KODI-RD-IL
                # Enable all addons in build's ZIP file.
                installed = db.grab_addons(lib)
                db.addon_database(installed, 1, True)
                try:
                    os.remove(lib)
                except:
                    pass
                
                from resources.libs.gui import window
                note_id, msg = window.split_notify(CONFIG.QUICK_UPDATE_NOTIFICATION_URL)
                if note_id:
                    # Don't show the quick update notification window after build install (first build launch notification window will show), no quick update will be installed (wizard's noteid == latest noteid from URL)
                    CONFIG.set_setting('quick_update_notedismiss', 'true')
                    CONFIG.set_setting('quick_update_noteid', note_id)
                # Show first build launch notification window
                CONFIG.set_setting('notedismiss', 'false')
                # Show first build launch build skin switch notification window
                CONFIG.set_setting('build_skin_switch_notifcation_dismiss', 'false')
                #########################################################################################################

                # self.dialog.ok(CONFIG.ADDONTITLE, "[COLOR {0}]התקנת הבילד הסתיימה. לחץ אישור/OK כדי לסגור את קודי. לאחר מכן, הפעל אותו מחדש.[/COLOR]".format(CONFIG.COLOR2))
                # tools.kill_kodi(over=True)
                self.force_close_kodi_in_5_seconds(dialog_header="התקנת הבילד הסתיימה בהצלחה")
            else:
                from resources.libs.gui import window
                window.show_text_box("Viewing Build Install Errors", error)
        else:
            logging.log_notify(CONFIG.ADDONTITLE,
                               '[COLOR {0}]התקנת בילד: בוטלה![/COLOR]'.format(CONFIG.COLOR2))

    def gui(self, name, over=False):
        if name == CONFIG.get_setting('buildname'):
            if over:
                yes_pressed = 1
            else:
                yes_pressed = self.dialog.yesno(CONFIG.ADDONTITLE,
                                   '[COLOR {0}]האם ברצונך לבצע עדכון מהיר עבור:'.format(CONFIG.COLOR2) + '\n' + '[COLOR {0}]{1}[/COLOR]?[/COLOR]'.format(CONFIG.COLOR1, name),
                                   nolabel='[B][COLOR red]ביטול[/COLOR][/B]',
                                   yeslabel='[B][COLOR springgreen]עדכון מהיר[/COLOR][/B]')
        else:
            yes_pressed = self.dialog.yesno("{0} - [COLOR red]!שים לב[/COLOR]".format(CONFIG.ADDONTITLE),
                               "[COLOR {0}][COLOR {1}]{2}[/COLOR] - הבילד עדיין לא מותקן".format(CONFIG.COLOR2, CONFIG.COLOR1, name) + '\n' + "יש קודם כל לבצע התקנה מלאה של הבילד![/COLOR]",
                               nolabel='[B][COLOR red]ביטול[/COLOR][/B]',
                               yeslabel='[B][COLOR springgreen]המשך בכל זאת[/COLOR][/B]')
        if yes_pressed:
            guizip = check.check_build(name, 'gui')
            zipname = name.replace('\\', '').replace('/', '').replace(':', '').replace('*', '').replace('?', '').replace('"', '').replace('<', '').replace('>', '').replace('|', '')

            response = tools.open_url(guizip, check=True)
            if not response:
                logging.log_notify(CONFIG.ADDONTITLE,
                                   '[COLOR {0}]לא קיים עדכון![/COLOR]'.format(CONFIG.COLOR2))
                return

            self.dialogProgress.create(CONFIG.ADDONTITLE, '[COLOR {0}][B]Downloading GuiFix:[/B][/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR2, CONFIG.COLOR1, name))

            lib = os.path.join(CONFIG.PACKAGES, '{0}_guisettings.zip'.format(zipname))
            
            try:
                os.remove(lib)
            except:
                pass

            Downloader().download(guizip, lib)
            xbmc.sleep(500)
            
            if os.path.getsize(lib) == 0:
                try:
                    os.remove(lib)
                except:
                    pass
                    
                return
            
            title = '[COLOR {0}][B]Installing:[/B][/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR2, CONFIG.COLOR1, name)
            self.dialogProgress.update(0, title + '\n' + 'Please Wait')
            extract.all(lib, CONFIG.HOME, title=title)
            self.dialogProgress.close()
            skin.skin_to_default('Build Install')
            skin.look_and_feel_data('save')
            installed = db.grab_addons(lib)
            db.addon_database(installed, 1, True)

            self.dialog.ok(CONFIG.ADDONTITLE, "[COLOR {0}]עדכון מהיר הסתיים. לחץ אישור/OK כדי לסגור את קודי. לאחר מכן, הפעל אותו מחדש.[/COLOR]".format(CONFIG.COLOR2))
            tools.kill_kodi(over=True)
        else:
            logging.log_notify(CONFIG.ADDONTITLE,
                               '[COLOR {0}]עדכון מהיר: בוטל![/COLOR]'.format(CONFIG.COLOR2))
                               
    #####################################################
    # KODI-RD-IL
    def quick_update(self, name, auto_quick_update="false",
                     expected_note_id=None):

        auto_quick_update = True if auto_quick_update=="true" else False
        
        if name == CONFIG.get_setting('buildname'):
            if auto_quick_update:
                yes_pressed = 1
            else:
                yes_pressed = self.dialog.yesno(CONFIG.ADDONTITLE,
                                   '[COLOR {0}]האם ברצונך לבצע עדכון מהיר עבור:'.format(CONFIG.COLOR2) + '\n' + '[COLOR {0}]{1}[/COLOR]?[/COLOR]'.format(CONFIG.COLOR1, name),
                                   nolabel='[B][COLOR red]ביטול[/COLOR][/B]',
                                   yeslabel='[B][COLOR springgreen]עדכון מהיר[/COLOR][/B]')
        else:
            yes_pressed = self.dialog.yesno("{0} - [COLOR red]!שים לב[/COLOR]".format(CONFIG.ADDONTITLE),
                               "[COLOR {0}][COLOR {1}]{2}[/COLOR] - הבילד עדיין לא מותקן".format(CONFIG.COLOR2, CONFIG.COLOR1, name) + '\n' + "יש קודם כל לבצע התקנה מלאה של הבילד![/COLOR]",
                               nolabel='[B][COLOR red]ביטול[/COLOR][/B]',
                               yeslabel='[B][COLOR springgreen]המשך בכל זאת[/COLOR][/B]')
        if yes_pressed:
            # Tie the manifest fetch to an immutable notification-specific path.
            # raw.githubusercontent caches build.txt for several minutes and
            # ignores query strings in its cache key; a distinct path prevents a
            # fresh notification from being paired with the previous quickfix.
            guizip = check.check_build(
                name, 'gui', release_id=expected_note_id
            )
            zipname = name.replace('\\', '').replace('/', '').replace(':', '').replace('*', '').replace('?', '').replace('"', '').replace('<', '').replace('>', '').replace('|', '')

            response = tools.open_url(guizip, check=True)
            if not response:
                logging.log_notify(CONFIG.ADDONTITLE,
                                   '[COLOR {0}]לא קיים עדכון מהיר![/COLOR]'.format(CONFIG.COLOR2))
                return False

            self.dialogProgress.create(CONFIG.ADDONTITLE, '[COLOR {0}][B]מוריד עדכון מהיר עבור:[/B][/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR2, CONFIG.COLOR1, name))
            xbmc.sleep(2500)
            self.dialogProgress.close()

            lib = os.path.join(CONFIG.PACKAGES, '{0}_quick_update.zip'.format(zipname))
            
            try:
                os.remove(lib)
            except:
                pass

            Downloader().download(guizip, lib)
            xbmc.sleep(500)
            
            if os.path.getsize(lib) == 0:
                try:
                    os.remove(lib)
                except:
                    pass
                    
                return False
            
            title = '[COLOR {0}][B]Installing:[/B][/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR2, CONFIG.COLOR1, name)
            # ignore=True bypasses extract.all's self-skip of any file
            # whose path contains CONFIG.ADDON_ID (the wizard's own id).
            # Without this, every wizard-addon file inside the quickfix
            # zip is silently skipped, so wizard updates shipped via
            # quick_update never reach disk -- Switch Skin keeps showing
            # the pre-update list, the addon DB lies about the version,
            # etc. The user-triggered manual install still has its own
            # safety prompt; this code path is the auto/manual quickfix.
            extract_result = extract.all(
                lib, CONFIG.HOME, ignore=True, title=title
            )
            if not _quick_update_extract_ok(extract_result):
                try:
                    percent, errors, extraction_error = extract_result
                except (TypeError, ValueError):
                    percent, errors, extraction_error = 0, 1, repr(
                        extract_result
                    )
                logging.log(
                    '[QUICK-UPDATE] Extraction failed '
                    '(percent={0}, errors={1}): {2}'.format(
                        percent, errors, extraction_error
                    ),
                    level=xbmc.LOGERROR,
                )
                return False
            # skin.skin_to_default('Build Install')
            # skin.look_and_feel_data('save')
            installed = db.grab_addons(lib)
            db.addon_database(installed, 1, True)

            latest_version = check.check_build(name, 'version')
            if latest_version:
                CONFIG.set_setting('buildversion', latest_version)
                CONFIG.set_setting('latestversion', latest_version)
                CONFIG.BUILDVERSION = latest_version
                CONFIG.BUILDLATEST = latest_version
                               
            if not auto_quick_update:
                CONFIG.set_setting('quick_update_notedismiss', 'false')
                # Same reasoning as the startup path: prefer applying it in
                # place. A hand-started update deserves it even more, because
                # the user is sitting in front of Kodi right now.
                outcome = self.hot_reload()
                if not outcome:
                    self.force_close_kodi_in_5_seconds(dialog_header="עדכון מהיר הסתיים בהצלחה")
                elif outcome == self.HOT_RELOAD_DEFERRED:
                    # Postponed because something is playing. Saying "applied"
                    # here would be a lie the user can catch: nothing changed
                    # on screen and nothing will until Kodi is restarted.
                    logging.log_notify(
                        CONFIG.ADDONTITLE,
                        '[COLOR {0}]העדכון הותקן ויוחל בהפעלה הבאה'
                        '[/COLOR]'.format(CONFIG.COLOR2))
                else:
                    logging.log_notify(
                        CONFIG.ADDONTITLE,
                        '[COLOR {0}]העדכון הותקן והוחל[/COLOR]'.format(
                            CONFIG.COLOR2))

            return True

            # self.dialog.ok(CONFIG.ADDONTITLE, "[COLOR {0}]עדכון מהיר הסתיים. לחץ אישור/OK כדי לסגור את קודי. לאחר מכן, הפעל אותו מחדש.[/COLOR]".format(CONFIG.COLOR2))
        else:
            logging.log_notify(CONFIG.ADDONTITLE,
                               '[COLOR {0}]עדכון מהיר: בוטל![/COLOR]'.format(CONFIG.COLOR2))
            return False
    #####################################################

    #####################################################
    # KODI-RD-IL
    #
    # HOT RELOAD -- why closing Kodi was ever needed, and why it is not.
    #
    # A quick update writes new files and the old code keeps running. That is
    # not a caching problem: plugin.video.pov, plugin.video.umbrella and our
    # own service.subtitles.kodipovilai all declare
    #
    #     <reuselanguageinvoker>true</reuselanguageinvoker>
    #
    # so Kodi keeps ONE Python interpreter alive per add-on and reuses it.
    # A module that has already been imported stays imported. Editing POV's
    # .py on disk therefore changes nothing until that interpreter is gone --
    # which is the entire reason the update used to force-close Kodi. The
    # patchers already delete the target's .pyc; memory simply beats disk.
    #
    # Disabling an add-on destroys its invoker. So the interpreters can be
    # dropped one at a time, in order, without touching Kodi:
    #
    #   1. UpdateLocalAddons() so Kodi re-reads any changed addon.xml.
    #   2. Toggle OUR service -- it restarts from the NEW code and re-runs
    #      every third-party patcher.
    #   3. WAIT for it to say it finished, and to say so with the new VERSION
    #      (see _publish_repairs_state in service.py). Reloading POV before
    #      the patchers have run against it is worse than not reloading at
    #      all: POV would come back on half-written files.
    #   4. Toggle the add-ons that were patched, so they pick the files up.
    #   5. ReloadSkin() for skin changes.
    #
    # Anything that cannot be hot-applied still falls back to the old
    # force-close. The worst case is exactly today's behaviour.
    HOT_RELOAD_SELF = 'service.subtitles.kodipovilai'
    # plugin.program.openwizard was listed here and removed: it is the name of
    # the upstream fork this wizard descends from, not an add-on installed on
    # any device, so it silently no-opped. Account Manager is
    # script.module.acctmgr, and a module has no invoker of its own to drop.
    HOT_RELOAD_TARGETS = (
        'plugin.video.pov',
        'plugin.video.umbrella',
    )
    REPAIRS_DONE_PROPERTY = 'kodipovil_startup_repairs_done'
    # Written BEFORE an add-on is disabled and cleared only once it is
    # verified back on. Anything still listed at the next Kodi start was left
    # disabled by a cycle that did not finish, and gets switched back on.
    # Without this, one failed enable is a permanently broken POV that no
    # restart repairs -- a disabled add-on stays disabled.
    PENDING_ENABLE_FILE = 'special://profile/addon_data/' \
                          'plugin.program.kodipovilwizard/pending_enable.txt'

    @staticmethod
    def _jsonrpc(method, params):
        import json
        try:
            return json.loads(xbmc.executeJSONRPC(json.dumps({
                'jsonrpc': '2.0', 'id': 1,
                'method': method, 'params': params})))
        except Exception:
            return {}

    @classmethod
    def _addon_state(cls, addon_id, resolve_absent=False):
        """True | False | 'absent' (only when asked) | None.

        'absent' AND None BOTH used to be None, and that conflation was a real
        bug: heal_disabled_addons treated "not False" as healed, so an early
        start where Kodi's JSON-RPC was not answering yet looked exactly like
        "the user uninstalled it" -- and the pending record, the only thing
        that would ever have switched the add-on back on, was deleted. The
        add-on stayed off forever. Reproduced by a validator that made every
        call raise and watched a still-disabled POV lose its record.

        WE DO NOT READ THE ERROR. Treating any `error` reply as "no such
        add-on" was the same bug wearing a different hat: JSON-RPC also
        answers with an error for a busy or internal failure -- plausible
        right after the UpdateLocalAddons() this file itself calls, while the
        add-on database is still being rebuilt -- and the add-on in question
        is installed the whole time. Reproduced with a generic -32603 and the
        record was dropped on a still-disabled add-on.

        So when the details call does not give a straight answer we ask a
        different question instead of interpreting the refusal: list every
        add-on Kodi has, enabled or not. Present in that list means installed,
        and its own flag is the state. Missing from a list we actually
        received means gone. No list means we still do not know.

        THAT LISTING IS ONLY FETCHED WHEN SOMEBODY NEEDS THE DIFFERENCE.
        Listing every installed add-on is not free -- it locks and walks Kodi's
        add-on manager, the very subsystem UpdateLocalAddons() is busy
        rebuilding -- and _enable_and_verify polls this up to 24 times per
        add-on while waiting for one to come back on. It does not care whether
        a non-answer means "gone" or "cannot tell"; both are "not on yet". So
        only the heal pass, which decides whether to DROP a record, asks for
        the difference, and it asks once per pending id per Kodi start.
        """
        result = cls._jsonrpc('Addons.GetAddonDetails', {
            'addonid': addon_id, 'properties': ['enabled']})
        try:
            return bool(result['result']['addon']['enabled'])
        except Exception:
            pass
        if not resolve_absent:
            return None
        listing = cls._jsonrpc('Addons.GetAddons',
                               {'enabled': 'all', 'properties': ['enabled']})
        try:
            addons = listing['result']['addons']
        except Exception:
            return None
        for addon in addons:
            try:
                if addon.get('addonid') != addon_id:
                    continue
            except Exception:
                continue
            enabled = addon.get('enabled')
            return None if enabled is None else bool(enabled)
        return 'absent'

    @classmethod
    def _addon_is_enabled_static(cls, addon_id):
        """True/False, or None when the add-on cannot be confirmed either way.

        None is deliberately NOT False: an id we cannot look up (uninstalled,
        or Kodi not answering) must not be treated as 'confirmed off', or the
        heal pass would keep retrying something that does not exist.
        """
        state = cls._addon_state(addon_id)
        return None if state == 'absent' else state

    @classmethod
    def _jsonrpc_ready(cls, attempts=20, wait_ms=500):
        """Wait until Kodi's JSON-RPC actually answers, up to ~10s.

        heal_disabled_addons runs from startup.py BEFORE wait_for_gui_ready(),
        whose own docstring says this script starts before the GUI exists. Every
        decision the heal makes reads a JSON-RPC reply, so asking before the
        interface is up produces silence and silence used to mean "healed".
        Ping first; if nothing answers, the heal does nothing at all and the
        record is left for the next start."""
        for _ in range(attempts):
            result = cls._jsonrpc('JSONRPC.Ping', {})
            if isinstance(result, dict) and 'result' in result:
                return True
            xbmc.sleep(wait_ms)
        return False

    def _addon_is_enabled(self, addon_id):
        return self._addon_is_enabled_static(addon_id)

    # NO SHARED RECORD and NO STICKY FLAG. Five rounds of a Window(10000)
    # count-and-deadlines scheme each broke a new way, and the sticky
    # "I have seen POV work" flag that replaced it could never be set here at
    # all: this add-on's plugin entry point declares reuselanguageinvoker=false,
    # so Kodi builds a fresh interpreter for every invocation. A guard resting
    # on process memory is dead on arrival in a process that has none.
    #
    # Just ask whether POV can be constructed. See pov_reload.py.

    @classmethod
    def _pov_cycling(cls):
        """True while POV is installed but cannot be constructed right now.

        The installed half matters here more than it does in the service. One
        of the guarded call sites is the AF3 tools row's reload BUTTON: without
        it, a user who has removed POV presses that button and nothing happens,
        every time, with only a log line to say why. A cycle disables POV, it
        never uninstalls it, so the folder on disk separates the two -- and it
        is deliberately not a JSON-RPC question, because that call answers
        "no idea" for an unknown add-on and for a busy moment alike, and the
        busy moment is the one being guarded.
        """
        try:
            import xbmcaddon
            xbmcaddon.Addon('plugin.video.pov')
            return False
        except Exception:
            pass
        # The disk check runs on a thread with a join timeout because
        # `except` covers a call that fails, not one that never returns, and
        # a stat against a dead network mount is the second kind. One of the
        # callers is a button the user just pressed.
        box = {}

        def _look():
            try:
                import xbmcvfs
                for root in ('special://home/addons/', 'special://xbmc/addons/'):
                    path = root + 'plugin.video.pov/addon.xml'
                    if xbmcvfs.exists(xbmcvfs.translatePath(path)):
                        box['v'] = True
                        return
                box['v'] = False
            except Exception:
                pass

        try:
            import threading
            t = threading.Thread(target=_look)
            t.daemon = True
            t.start()
            t.join(3.0)
        except Exception:
            return True
        # No answer -> keep guarding. On disk -> a real cycle, wait for it.
        # Not on disk -> nothing to wait for, ever.
        return box.get('v', True)

    @staticmethod
    def _wait_until_resolvable(addon_ids, timeout=30):
        """Block until every id can actually be CONSTRUCTED, or time out.

        The enabled flag is not this question. Addons.GetAddonDetails reports
        enabled the instant it is set, while xbmcaddon.Addon(id) -- the call an
        add-on's own first line makes, and the one that raises "Unknown addon
        id" in the field logs -- keeps failing for a moment afterwards. Anything
        that redraws POV-backed windows in that moment gets a screen full of
        errors.

        Thirty seconds against a measured window of under three. The caller no
        longer force-closes on a timeout -- it defers -- so this only has to be
        long enough not to defer an update that was about to work, and short
        enough not to add a silent minute to a chain that is already quiet.
        """
        try:
            import xbmcaddon
        except Exception:
            return True
        waited = 0.0
        pending = [i for i in (addon_ids or []) if i]
        while pending and waited < timeout:
            still = []
            for addon_id in pending:
                try:
                    xbmcaddon.Addon(addon_id)
                except Exception:
                    still.append(addon_id)
            if not still:
                return True
            pending = still
            try:
                xbmc.sleep(500)
            except Exception:
                return False
            waited += 0.5
        if pending:
            # NOT "reloading anyway" -- the caller acts on this now. A log
            # line that contradicts the next log line is exactly what costs an
            # hour when the next fault is diagnosed from a field log.
            logging.log('[HOT-RELOAD] still not constructible after {0:.0f}s: '
                        '{1}'.format(waited, ', '.join(pending)),
                        level=xbmc.LOGWARNING)
        return not pending

    @classmethod
    def _pending_enable_path(cls):
        import xbmcvfs
        return xbmcvfs.translatePath(cls.PENDING_ENABLE_FILE)

    @classmethod
    def _pending_enable_read(cls):
        try:
            with open(cls._pending_enable_path(), 'r', encoding='utf-8') as f:
                return [line.strip() for line in f if line.strip()]
        except Exception:
            return []

    @classmethod
    def _pending_enable_write(cls, ids):
        try:
            path = cls._pending_enable_path()
        except Exception:
            return False
        try:
            folder = os.path.dirname(path)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder)
            if not ids:
                if os.path.isfile(path):
                    os.remove(path)
                return True
            # WRITE BESIDE IT, THEN RENAME. open(path, 'w') truncates the file
            # the instant it succeeds, so a write that then fails -- a full
            # disk, a stray directory in the way -- left the record EMPTY and
            # took every other pending id down with it. That is the one file
            # standing between a failed enable and a permanently disabled
            # add-on. os.replace is atomic: either the old content survives
            # intact or the new content lands whole.
            tmp = path + '.tmp'
            # A DIRECTORY SITTING ON THE TEMP NAME BLOCKS EVERY FUTURE WRITE.
            # os.remove refuses to delete a directory, so the old cleanup left
            # it there forever and the record could never be written again on
            # that install -- silently, since every failure is swallowed.
            cls._clear_tmp(tmp)
            with open(tmp, 'w', encoding='utf-8') as f:
                f.write('\n'.join(ids))
            os.replace(tmp, path)
            return True
        except Exception:
            cls._clear_tmp(path + '.tmp')
            return False

    @staticmethod
    def _clear_tmp(tmp):
        """Remove the scratch file, whatever it turns out to be.

        rmtree rather than rmdir: a NON-EMPTY directory squatting on the temp
        name defeats rmdir, the failure is swallowed, and every future write of
        the recovery record fails forever on that install -- the same permanent
        silent block, just one shape narrower. A SYMLINK is checked first,
        because rmtree refuses to follow one (rightly -- that is how a link
        pointing somewhere real would get deleted) and would leave the same
        permanent block behind; unlinking removes the link and nothing it
        points at."""
        try:
            if os.path.islink(tmp):
                os.unlink(tmp)
            elif os.path.isdir(tmp):
                import shutil
                shutil.rmtree(tmp, ignore_errors=True)
            elif os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

    @classmethod
    def heal_disabled_addons(cls):
        """Switch back on anything a previous cycle left off.

        Runs at every Kodi start, from the wizard, BEFORE anything else needs
        those add-ons. It has to live here rather than in the service add-on,
        because the service is one of the things that can be left disabled and
        a disabled add-on cannot heal itself.
        """
        pending = cls._pending_enable_read()
        if not pending:
            return []
        if not cls._jsonrpc_ready():
            # Nothing answered. We cannot enable and we cannot check, so the
            # only safe move is to touch nothing: the record stays exactly as
            # it is and the next start tries again.
            logging.log('[HOT-RELOAD] JSON-RPC is not answering yet; leaving '
                        '{0} recorded for the next start'.format(
                            ', '.join(pending)), level=xbmc.LOGWARNING)
            return []
        healed, gone, still_off = [], [], []
        for addon_id in pending:
            try:
                cls._jsonrpc('Addons.SetAddonEnabled',
                             {'addonid': addon_id, 'enabled': True})
                # VERIFY, and keep the record unless we got a real answer.
                # Clearing the list on a failed enable is how a temporary
                # problem becomes a permanent one: the id is forgotten and
                # nothing ever tries again. Caught by a test that made every
                # enable fail and then found the add-on off with an empty list.
                state = cls._addon_state(addon_id, resolve_absent=True)
                if state is True:
                    healed.append(addon_id)
                elif state == 'absent':
                    # Kodi says there is no such add-on. It was uninstalled
                    # while pending; there is nothing left to enable, so the
                    # record goes rather than being retried forever.
                    gone.append(addon_id)
                else:
                    # False (still off) or None (no answer) -- both keep it.
                    still_off.append(addon_id)
            except Exception:
                still_off.append(addon_id)
        if not cls._pending_enable_write(still_off):
            # Harmless -- the ids stay listed and the next start re-verifies
            # them, finds them already on, and clears them then. Logged because
            # every other write in this file is checked, and a silent one here
            # would look like a gap rather than a decision.
            logging.log('[HOT-RELOAD] could not update the record after '
                        'healing; it will be re-checked at the next start',
                        level=xbmc.LOGWARNING)
        if gone:
            logging.log('[HOT-RELOAD] no longer installed, dropping from the '
                        'record: {0}'.format(', '.join(gone)),
                        level=xbmc.LOGWARNING)
        if healed:
            logging.log('[HOT-RELOAD] re-enabled after an interrupted '
                        'reload: {0}'.format(', '.join(healed)),
                        level=xbmc.LOGWARNING)
        if still_off:
            logging.log('[HOT-RELOAD] still could not enable {0}; the record '
                        'is kept so the next start tries again'.format(
                            ', '.join(still_off)), level=xbmc.LOGERROR)
        return healed

    def _enable_and_verify(self, addon_id, attempts=4):
        """Turn it back on and CHECK. Returns True only when it is on."""
        for attempt in range(attempts):
            self._jsonrpc('Addons.SetAddonEnabled',
                          {'addonid': addon_id, 'enabled': True})
            for _ in range(6):
                if self._addon_is_enabled(addon_id) is True:
                    return True
                xbmc.sleep(500)
            logging.log('[HOT-RELOAD] {0} did not come back on (attempt '
                        '{1}/{2}); retrying'.format(
                            addon_id, attempt + 1, attempts),
                        level=xbmc.LOGWARNING)
        return False

    def _cycle_addon(self, addon_id):
        """Disable then re-enable, so the reused interpreter is destroyed.

        Skipped when the add-on is missing OR when the user has it disabled
        already -- re-enabling something somebody turned off by hand is not
        ours to do, and it would be a silent settings change on every update.

        THE RE-ENABLE IS VERIFIED, not fired and forgotten. _jsonrpc swallows
        every error and returns {}, so an enable that failed looks exactly
        like one that worked -- and the cost of believing it is a user left
        with POV switched off, which no restart repairs. The id is written to
        disk BEFORE the disable so that even a crash between the two calls is
        recoverable at the next start.
        """
        if self._addon_is_enabled(addon_id) is not True:
            return False
        pending = self._pending_enable_read()
        if addon_id not in pending and not self._pending_enable_write(
                pending + [addon_id]):
            # NO RECORD, NO DISABLE. The whole safety of this cycle rests on
            # the id being on disk before the add-on goes off: that record is
            # what the next Kodi start reads to switch it back on. If it could
            # not be written, disabling anyway means a failed enable leaves the
            # add-on off with nothing tracking it -- the exact permanent
            # breakage this is here to prevent. Skipping costs a stale
            # interpreter until the next restart, which is merely the old
            # behaviour.
            logging.log('[HOT-RELOAD] could not record {0} before cycling it; '
                        'leaving it alone'.format(addon_id),
                        level=xbmc.LOGERROR)
            return False
        self._jsonrpc('Addons.SetAddonEnabled',
                      {'addonid': addon_id, 'enabled': False})
        xbmc.sleep(1500)
        if not self._enable_and_verify(addon_id):
            logging.log('[HOT-RELOAD] {0} could NOT be switched back on. It '
                        'stays recorded and will be enabled at the next Kodi '
                        'start.'.format(addon_id), level=xbmc.LOGERROR)
            return False
        remaining = [i for i in self._pending_enable_read() if i != addon_id]
        self._pending_enable_write(remaining)
        return True

    def _wait_for_repairs(self, expected_version, timeout_seconds):
        """Wait for OUR service to report a finished pass at this version."""
        window = xbmcgui.Window(10000)
        monitor = xbmc.Monitor()
        waited = 0
        while waited < timeout_seconds:
            if monitor.abortRequested():
                return False
            try:
                if window.getProperty(
                        self.REPAIRS_DONE_PROPERTY) == expected_version:
                    return True
            except Exception:
                pass
            if monitor.waitForAbort(2):
                return False
            waited += 2
        return False

    @staticmethod
    def _installed_version_on_disk(addon_id):
        """Read the version from addon.xml, NOT from xbmcaddon.

        xbmcaddon answers from Kodi's in-memory add-on database, which still
        holds the PRE-update metadata at this point. The file on disk is the
        one the quick update just wrote, and it is the version the restarted
        service will report -- so it is the only one worth waiting for.
        """
        import re
        import xbmcvfs
        try:
            path = xbmcvfs.translatePath(
                'special://home/addons/{0}/addon.xml'.format(addon_id))
            with open(path, 'r', encoding='utf-8') as handle:
                head = handle.read(4096)
            match = re.search(r'version="([^"]+)"[^>]*provider-name', head)
            if not match:
                match = re.search(
                    r'<addon[^>]*?\sversion="([^"]+)"', head, re.S)
            return match.group(1) if match else ''
        except Exception:
            return ''

    # Truthy, so `if not hot_reload()` still reads "fall back to a restart",
    # but distinguishable for a caller that wants to tell the user the truth:
    # the update is on disk and will take effect at the next start, it has NOT
    # been applied yet.
    HOT_RELOAD_DEFERRED = 'deferred'

    def hot_reload(self, expected_version=None, timeout_seconds=240):
        """Apply an installed update in place.

        True when it fully took, HOT_RELOAD_DEFERRED when it was deliberately
        postponed (both mean "do not force-close"), False when the caller
        should restart Kodi."""
        try:
            if not expected_version:
                expected_version = self._installed_version_on_disk(
                    self.HOT_RELOAD_SELF)
            if not expected_version:
                logging.log('[HOT-RELOAD] could not read the newly installed '
                            'version from disk; falling back to a restart.',
                            level=xbmc.LOGWARNING)
                return False
            # Never while something is playing. This file already refuses a
            # mere ReloadSkin() during playback; disabling the add-on that is
            # SERVING the stream is far worse. Force-closing instead would be
            # worse still, so the update simply stays on disk and takes effect
            # at the next start -- which is what happens today anyway, minus
            # the stream being killed. True means "do not force-close".
            if xbmc.getCondVisibility('Player.HasMedia'):
                logging.log('[HOT-RELOAD] something is playing; leaving the '
                            'installed update to take effect at the next '
                            'start rather than interrupting it.')
                return self.HOT_RELOAD_DEFERRED
            xbmc.executebuiltin('UpdateLocalAddons()')
            xbmc.sleep(1000)
            # Clear the marker OURSELVES before the service is cycled. The
            # service clears it too, but its first poll can land before the
            # restarted interpreter has even reached that line -- and if the
            # quickfix did not bump our own add-on version, a stale value from
            # the PREVIOUS pass matches expected_version and the wait returns
            # true before any new work has happened.
            try:
                xbmcgui.Window(10000).clearProperty(self.REPAIRS_DONE_PROPERTY)
            except Exception:
                pass
            if not self._cycle_addon(self.HOT_RELOAD_SELF):
                logging.log('[HOT-RELOAD] {0} could not be cycled; falling '
                            'back to a restart.'.format(
                                self.HOT_RELOAD_SELF), level=xbmc.LOGWARNING)
                return False
            if not self._wait_for_repairs(expected_version, timeout_seconds):
                logging.log('[HOT-RELOAD] the service did not report a '
                            'finished repair pass at version {0} within {1}s; '
                            'falling back to a restart so the update is not '
                            'left half-applied.'.format(
                                expected_version, timeout_seconds),
                            level=xbmc.LOGWARNING)
                return False
            left_off = []
            cycled = []
            for addon_id in self.HOT_RELOAD_TARGETS:
                try:
                    if self._addon_is_enabled(addon_id) is not True:
                        continue
                    if self._cycle_addon(addon_id):
                        cycled.append(addon_id)
                        logging.log('[HOT-RELOAD] reloaded ' + addon_id)
                    else:
                        left_off.append(addon_id)
                except Exception as cycle_err:
                    left_off.append(addon_id)
                    logging.log('[HOT-RELOAD] {0} could not be reloaded: '
                                '{1}'.format(addon_id, cycle_err),
                                level=xbmc.LOGWARNING)
            if left_off:
                # Report FAILURE, not success. The caller then force-closes,
                # which is exactly the recovery we want: the ids are on disk,
                # and heal_disabled_addons() switches them back on at the next
                # start. Reporting success here would leave the user with a
                # missing add-on and no restart to bring it back.
                logging.log('[HOT-RELOAD] these are still off and recorded '
                            'for the next start: {0}'.format(
                                ', '.join(left_off)), level=xbmc.LOGERROR)
                return False
            # NOT YET. Every id above has just been re-enabled, and Kodi's
            # enabled flag -- which is all _addon_is_enabled can see -- flips
            # before the add-on can actually be constructed. ReloadSkin()
            # rebuilds every window, so firing it in that gap hands the home
            # screen a set of widgets whose add-on raises "Unknown addon id",
            # which is precisely what two user logs show happening during a
            # quick update. This is the same fault the service add-on's
            # pov_reload guards against; the wizard cannot import that module,
            # so it makes the same check for itself.
            # ONLY WHAT WAS ACTUALLY CYCLED. HOT_RELOAD_TARGETS is a static
            # tuple that includes the opt-in Umbrella pilot, which most users
            # never install -- and an id that is not installed can never become
            # constructible, so waiting on the whole tuple burned the full
            # timeout on EVERY update, including the silent one at startup.
            # Measured at 20.0s for a user without Umbrella. The loop above
            # already knows which ids it cycled; those are the only ones whose
            # readiness this wait is about.
            resolvable = self._wait_until_resolvable(cycled)
            # AND POV, WHICH THIS LOOP MAY NEVER HAVE TOUCHED. Everything above
            # is bookkeeping about what THIS function did, and POV can be
            # unusable because of something else entirely. Concretely: cycling
            # HOT_RELOAD_SELF restarts the service, whose main() calls
            # pov_reload.reload_if_patched(), which starts a background thread
            # that disables POV for a second and a half. _wait_for_repairs()
            # returns when the service's synchronous repair pass ends, and that
            # pass does not wait for the thread. So the `_addon_is_enabled`
            # check at the top of the loop can read False for POV, `continue`
            # past it, leave `cycled` empty -- and an empty list is resolvable
            # instantly, by definition. ReloadSkin() then fires into the outage
            # and returns True, which the manual path turns into an on-screen
            # "העדכון הותקן והוחל". That is the original crash, with a
            # notification claiming it worked.
            #
            # So ask the live question the rest of this feature asks, instead
            # of trusting a record of our own actions. _pov_cycling() is False
            # both when POV is fine and when POV is not installed, so this
            # costs nothing in either ordinary case.
            if resolvable and Wizard._pov_cycling():
                logging.log('[HOT-RELOAD] POV is unusable and this pass did '
                            'not cycle it -- something else has it down; '
                            'waiting before touching the skin.',
                            level=xbmc.LOGWARNING)
                resolvable = self._wait_until_resolvable(
                    ['plugin.video.pov'], timeout=12)
            if not resolvable:
                # SKIP THE RELOAD, DO NOT FORCE-CLOSE. An earlier version
                # returned False here, and False makes the caller close Kodi --
                # so a device that was merely slow got an app close it never got
                # before this work, and on Android that means a manual relaunch.
                # Worse, this wait sits at the end of a chain that is already
                # silent for minutes, so the close arrives out of nowhere.
                #
                # Nothing is lost by skipping: the files are on disk, the ids
                # are recorded in pending_enable, heal_disabled_addons switches
                # them back on at the next start, and the skin picks the update
                # up then. The user gets a working Kodi now instead of a closed
                # one, which is the whole point of a hot reload.
                logging.log('[HOT-RELOAD] cycled add-ons are not constructible '
                            'yet; leaving the skin alone -- the update is '
                            'installed and shows on the next start.',
                            level=xbmc.LOGWARNING)
                # DEFERRED, NOT True. Both keep the caller from force-closing,
                # but True also means "fully took" -- and the manual path turns
                # that into an on-screen "העדכון הותקן והוחל", telling the user
                # the update has been APPLIED while they are still running the
                # old code. The log line directly above says the opposite. Of
                # the two, the notification is the one the user reads.
                return self.HOT_RELOAD_DEFERRED
            xbmc.executebuiltin('ReloadSkin()')
            logging.log('[HOT-RELOAD] update applied without closing Kodi')
            return True
        except Exception as err:
            logging.log('[HOT-RELOAD] failed, falling back to a restart: '
                        '{0}'.format(err), level=xbmc.LOGERROR)
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
    try:
        import os as _os
        import xbmcvfs
        source_favourites_xml = xbmcvfs.translatePath(f"special://home/media/builds_favourites_xml/{gotoskin}/favourites.xml")
        destination_favourites_xml = xbmcvfs.translatePath("special://userdata/favourites.xml")
        # Some skins (e.g. skin.arctic.fuse.3) drive their home menu via
        # script.skinvariables, not Kodi's favourites.xml. If we don't
        # have a favourites.xml seed for the target skin, don't fail
        # the switch -- the Kodi Favourites window will simply show
        # whatever was last there. Skin switching itself should still
        # succeed.
        if not _os.path.isfile(source_favourites_xml):
            logging.log(
                f"DEBUG | update_favourites_xml_file | "
                f"no seed at {source_favourites_xml}, leaving existing "
                f"favourites.xml in place")
            return True
        from shutil import copyfile
        copyfile(source_favourites_xml,destination_favourites_xml)
        return True
    except Exception as e:
        logging.log_notify(CONFIG.ADDONTITLE,
                           '[COLOR {0}]שגיאה בהגדרת מסך הבית![/COLOR]'.format(CONFIG.COLOR2))
        logging.log(f"DEBUG | update_favourites_xml_file | Exception: {str(e)}")
        return False
    

#####################################################
# KODI-POV-IL - ARCTIC FUSE 3 SUPPLEMENTAL INSTALL
# AF3 + its 6 deps are too big to bundle inside the
# regular build zip (font + studio assets push the
# total past GitHub's 100 MB single-file limit). So
# we ship them as 3 separate "pack" zips in dist/
# and download+extract them on demand when the user
# picks AF3 from Switch Skin. Idempotent: skips any
# pack whose payload is already present on disk.

# Per-pack URL + sentinel file. Sentinel is something
# inside the pack that proves the pack was extracted.
# If the sentinel exists, we skip the download.
AF3_PACK_BASE_URL = "https://github.com/MoranTheKing/Kodi-POV-IL/raw/main/dist"
AF3_CE_SKIN_VERSION = '6.3.2.14'
# 'addon_ids' lists every addon folder the pack ships. We register
# these in Kodi's Addons DB (enabled) whether the pack is freshly
# extracted OR already on disk from a previous switch attempt --
# this is what makes the fix retroactive for users who already
# "installed" AF3 with the old (DB-less) code and got the silent
# Estuary fallback.
AF3_PACKS = [
    {
        'name': 'Arctic Fuse 3 - מודולי קוד נדרשים',
        'url': '{0}/Kodi-POV-IL-AF3-deps-pack.zip'.format(AF3_PACK_BASE_URL),
        'filename': 'af3_deps_pack.zip',
        'sentinel': 'special://home/addons/script.module.jurialmunkey/addon.xml',
        # Force a re-extract when the installed jurialmunkey is OLDER than
        # what the pack ships. Without a version gate, _af3_pack_current()
        # returned True as soon as the addon.xml merely EXISTED -- so a user
        # who already had an old jurialmunkey (e.g. 0.2.28 from their base
        # build) was never upgraded. But the bundled TMDbHelper 6.15.6
        # requires jurialmunkey >= 0.2.35 (it imports jurialmunkey.ftools,
        # which only exists from 0.2.35), so TMDbHelper's whole service
        # crashed on startup -> AF3 widgets/ratings broke. Gating on the
        # jurialmunkey version forces the deps pack to re-extract and
        # overwrite the stale copy. Keep this in sync with the version
        # bundled in dist/Kodi-POV-IL-AF3-deps-pack.zip.
        'expected_version': '0.2.35',
        # script.skinvariables, script.texturemaker, and
        # plugin.video.themoviedb.helper all transitively depend on
        # these. Without them AF3 hangs forever on "Initialising
        # Skin..." -- skinvariables' generator fails to import
        # jurialmunkey, so the dynamically-built includes file
        # (script-skinvariables-generator-includes-.xml) never lands,
        # and AF3's Startup.xml has nothing to populate the home with.
        # First version of the AF3 install path missed these because
        # they aren't direct requires of the SKIN itself -- they're
        # only declared inside the SCRIPT dependencies' addon.xmls.
        # 139 KB total, so it's a tiny extra download.
        'addon_ids': [
            'script.module.jurialmunkey',
            'script.module.infotagger',
            'script.module.addon.signals',
            'script.module.qrcode',
        ],
    },
    {
        'name': 'Arctic Fuse 3 - סקין + תוספים נדרשים',
        'url': '{0}/Kodi-POV-IL-AF3-skin-pack.zip'.format(AF3_PACK_BASE_URL),
        'filename': 'af3_skin_pack.zip',
        'sentinel': 'special://home/addons/skin.arctic.fuse.3/addon.xml',
        'expected_version': AF3_CE_SKIN_VERSION,
        # When the version gate forces a re-extract, remove the OLD skin
        # folder first: upstream deletes/renames files between releases
        # (v3.2.14 dropped Custom_1192_HolidayTheme.xml), and Kodi loads
        # every Custom_*.xml that merely EXISTS in 1080i/ -- an overlay
        # extract would leave that zombie window (and its dead texture
        # references) alive forever. Purged AFTER the new pack downloads
        # successfully, and ONLY the addon folder -- the user's skin
        # settings live in userdata/addon_data and are never touched.
        'purge_before_extract': ['special://home/addons/skin.arctic.fuse.3/'],
        'addon_ids': [
            'skin.arctic.fuse.3',
            'script.skinvariables',
            'script.texturemaker',
            'plugin.video.themoviedb.helper',
            'resource.images.weathericons.white',
        ],
    },
    {
        'name': 'Arctic Fuse 3 - פונטים',
        'url': '{0}/Kodi-POV-IL-AF3-fonts-pack.zip'.format(AF3_PACK_BASE_URL),
        'filename': 'af3_fonts_pack.zip',
        'sentinel': 'special://home/addons/resource.font.robotocjksc/addon.xml',
        'addon_ids': ['resource.font.robotocjksc'],
    },
    {
        'name': 'Arctic Fuse 3 - אייקוני סטודיו',
        'url': '{0}/Kodi-POV-IL-AF3-studios-pack.zip'.format(AF3_PACK_BASE_URL),
        'filename': 'af3_studios_pack.zip',
        'sentinel': ('special://home/addons/'
                     'resource.images.studios.coloured/addon.xml'),
        'addon_ids': ['resource.images.studios.coloured'],
    },
]

# KODI-POV-IL - NOX skin, same on-demand pattern as AF3. The NOX skin is a
# rebranded + scrubbed Estuary MOD (~24 MB) whose home menu was remapped to
# our POV / idanplus / otaku addons. It is downloaded only when the user
# picks it from Switch Skin so it never bloats the base build. Single pack
# (fits under GitHub's 100 MB limit), unlike AF3's four. Its only hard
# dependency, script.fentastic.helper, already ships in the build.
NOX_SKIN_VERSION = '1.0.11'
NOX_PACKS = [
    {
        'name': 'סקין NOX',
        'url': '{0}/Kodi-POV-IL-NOX-skin-pack.zip'.format(AF3_PACK_BASE_URL),
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
UMBRELLA_PACK_VERSION = '6.7.81'
UMBRELLA_PACKS = [
    {
        'name': 'Umbrella + CocoScrapers',
        'url': '{0}/Kodi-POV-IL-Umbrella-pack.zip'.format(AF3_PACK_BASE_URL),
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
ACCTMGR_PACK_VERSION = '1.1.5a'
ACCTMGR_PACKS = [
    {
        'name': 'Account Manager Lite',
        'url': '{0}/Kodi-POV-IL-AcctMgr-pack.zip'.format(AF3_PACK_BASE_URL),
        'filename': 'acctmgr_pack.zip',
        'sentinel': 'special://home/addons/script.module.acctmgr/addon.xml',
        'expected_version': ACCTMGR_PACK_VERSION,
        'addon_ids': [
            'script.module.acctmgr',
            'script.module.acctvwr',
            'repository.709',
        ],
    },
]


def ensure_acctmgr_installed():
    """Download + extract the Account Manager pack on demand (same
    battle-tested path as the AF3/NOX/Umbrella packs, including the Addons-DB
    registration that makes Kodi actually see the new addons)."""
    return _ensure_packs_installed(
        ACCTMGR_PACKS,
        '[COLOR {0}][B]מוריד את Account Manager[/B][/COLOR]'.format(
            CONFIG.COLOR2),
        '[COLOR {0}][B]Account Manager מוכן לשימוש[/B][/COLOR]'.format(
            CONFIG.COLOR1))


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

    Silent when there is nothing to do: the pack's own sentinel + version gate
    inside _ensure_packs_installed means an already-current install costs a
    file check, not a 8 MB download. Never raises; the caller runs at startup
    and a failure here must not stop the rest of it."""
    try:
        if CONFIG.get_setting(ACCTMGR_AUTO_SETTING) == ACCTMGR_AUTO_DONE:
            return False
        if not CONFIG.get_setting('buildname'):
            return False            # build not installed yet -- too early
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
        logging.log('[Account Manager] auto-installed {0}'.format(
            ACCTMGR_PACK_VERSION), level=xbmc.LOGINFO)
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
        logging.log_notify(
            CONFIG.ADDONTITLE,
            '[COLOR {0}]הותקן! זמין תחת תוספים -> תוכניות -> '
            'Account Manager[/COLOR]'.format(CONFIG.COLOR1))


def ensure_umbrella_installed():
    """Download + extract the Umbrella pilot pack on demand (same
    battle-tested path as the AF3/NOX packs, including the Addons-DB
    registration that makes Kodi actually see the new addons)."""
    return _ensure_packs_installed(
        UMBRELLA_PACKS,
        '[COLOR {0}][B]מוריד את Umbrella ותלויות[/B][/COLOR]'.format(
            CONFIG.COLOR2),
        '[COLOR {0}][B]Umbrella מוכן לשימוש[/B][/COLOR]'.format(
            CONFIG.COLOR1))


def install_umbrella_pilot():
    """Opt-in flow behind the wizard menu entry: confirm, install, and tell
    the user where to find it. Deliberately does NOT touch the home screen,
    the search wiring or any default -- the pilot's whole point is zero
    impact on anyone who didn't ask for it."""
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
        logging.log_notify(
            CONFIG.ADDONTITLE,
            '[COLOR {0}]Umbrella הותקן! זמין תחת תוספים -> הרחבות וידאו'
            '[/COLOR]'.format(CONFIG.COLOR1))


def _af3_register_pack_in_db(pack):
    """Register + enable a pack's addons in Kodi's Addons DB. Safe to
    call repeatedly (INSERT OR IGNORE + UPDATE enabled). This is the
    retroactive-fix entry point: it works off the static addon_ids
    list, so it does NOT need the pack zip on disk -- which means we
    can heal users whose files were already extracted by the old
    code path."""
    try:
        db.addon_database(pack['addon_ids'], 1, True)
        logging.log(
            'DEBUG | ensure_arctic_fuse_3_installed | '
            'DB enabled (static list): {0}'.format(pack['addon_ids']))
        return True
    except Exception as e:
        logging.log(
            'DEBUG | ensure_arctic_fuse_3_installed | '
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
        'AF3 pack version too old, forcing reinstall: {0} '
        'current={1} expected>={2}'.format(
            pack['name'], current or 'missing', expected))
    return False


def ensure_arctic_fuse_3_installed():
    """Download + extract the AF3 packs on demand (see _ensure_packs_installed)."""
    return _ensure_packs_installed(
        AF3_PACKS,
        '[COLOR {0}][B]מוריד את Arctic Fuse 3 ותלויות[/B][/COLOR]'.format(
            CONFIG.COLOR2),
        '[COLOR {0}][B]Arctic Fuse 3 מוכן לשימוש[/B][/COLOR]'.format(
            CONFIG.COLOR1))


def ensure_nox_installed():
    """Download + extract the NOX skin pack on demand (see _ensure_packs_installed)."""
    return _ensure_packs_installed(
        NOX_PACKS,
        '[COLOR {0}][B]מוריד את סקין NOX[/B][/COLOR]'.format(CONFIG.COLOR2),
        '[COLOR {0}][B]סקין NOX מוכן לשימוש[/B][/COLOR]'.format(CONFIG.COLOR1))


def auto_update_active_skin_pack():
    """Refresh an on-demand skin pack (NOX or AF3) when the user is already
    ON that skin and a newer version has been published. The pack is otherwise
    only (re)installed when picked from Switch Skin, so without this an existing
    user never gets skin updates from a normal quick_update -- they had to
    switch away and back. Idempotent: the version gate (_af3_pack_current) means
    we only re-download when the on-disk skin is actually OLDER than what we now
    ship, so it does NOT re-download every boot, and it does NOT re-download when
    the user merely toggles skins. Re-extracting overwrites only the skin's addon
    files under addons/<skin id> -- never userdata/addon_data skin settings,
    so the user's favourites order and skin tweaks are preserved."""
    try:
        active = CONFIG.SKIN or ''
        if 'skin.povil.nox' in active:
            pack, ensure, label = NOX_PACKS[0], ensure_nox_installed, 'NOX'
        elif 'skin.arctic.fuse.3' in active:
            # The AF3 SKIN pack specifically (the one whose sentinel is the
            # skin's addon.xml) -- found by sentinel, not by list position,
            # so reordering AF3_PACKS can never silently break this.
            pack = next((p for p in AF3_PACKS
                         if 'skin.arctic.fuse.3' in p.get('sentinel', '')),
                        None)
            ensure, label = ensure_arctic_fuse_3_installed, 'AF3'
            if pack is None:
                return
        else:
            return
        if _af3_pack_current(pack):
            return  # on-disk version already current; no re-download
        logging.log(
            '[Skin Auto Update] {0} is active and the installed pack is behind '
            '{1}; refreshing it now.'.format(
                label, pack.get('expected_version')),
            level=xbmc.LOGINFO)
        if ensure():
            xbmc.sleep(800)
            try:
                # This runs from startup right after the quick update, so a POV
                # cycle can still be in flight. Rebuilding every window against
                # an add-on that cannot resolve is the fault this whole change
                # is about; the skin pack is already on disk either way, so it
                # simply takes effect on the next start instead.
                if Wizard._pov_cycling():
                    logging.log('[Skin Auto Update] POV is mid-cycle; not '
                                'reloading the skin now -- the pack is '
                                'installed and applies on the next start.',
                                level=xbmc.LOGWARNING)
                else:
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
    Generic over a packs list so AF3 and NOX (and any future on-demand
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
                    'AF3 pack files present, skipping download but '
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
                    '[COLOR {0}]חבילת AF3 לא זמינה: {1}[/COLOR]'.format(
                        CONFIG.COLOR2, pack['name']))
                logging.log(
                    'DEBUG | ensure_arctic_fuse_3_installed | '
                    '{0} not reachable: {1}'.format(
                        pack['name'], pack['url']))
                return False

            try:
                Downloader().download(pack['url'], lib)
            except Exception as e:
                dialog_progress.close()
                logging.log(
                    'DEBUG | ensure_arctic_fuse_3_installed | '
                    'download failed for {0}: {1}'.format(
                        pack['name'], str(e)))
                logging.log_notify(
                    CONFIG.ADDONTITLE,
                    '[COLOR {0}]כשל בהורדת חבילת AF3![/COLOR]'.format(
                        CONFIG.COLOR2))
                return False

            xbmc.sleep(300)
            if not os.path.exists(lib) or os.path.getsize(lib) == 0:
                dialog_progress.close()
                logging.log_notify(
                    CONFIG.ADDONTITLE,
                    '[COLOR {0}]חבילת AF3 ריקה: {1}[/COLOR]'.format(
                        CONFIG.COLOR2, pack['name']))
                return False

            # Purge listed folders only now, AFTER the new pack downloaded
            # and passed the size check -- so a failed download can never
            # leave the user with a deleted skin and nothing to replace it.
            for purge in pack.get('purge_before_extract', []):
                try:
                    import shutil
                    import xbmcvfs
                    purge_path = xbmcvfs.translatePath(purge)
                    if os.path.isdir(purge_path):
                        shutil.rmtree(purge_path, ignore_errors=True)
                        logging.log(
                            'DEBUG | ensure_arctic_fuse_3_installed | '
                            'purged stale folder before extract: '
                            '{0}'.format(purge))
                except Exception as e:
                    logging.log(
                        'DEBUG | ensure_arctic_fuse_3_installed | '
                        'purge failed (continuing, overlay extract): '
                        '{0}: {1}'.format(purge, str(e)))

            extract_title = (
                '[COLOR {0}][B]מתקין:[/B][/COLOR] [COLOR {1}]{2}[/COLOR]'
                .format(CONFIG.COLOR2, CONFIG.COLOR1, pack['name']))
            try:
                extract.all(lib, CONFIG.HOME, title=extract_title)
            except Exception as e:
                dialog_progress.close()
                logging.log(
                    'DEBUG | ensure_arctic_fuse_3_installed | '
                    'extract failed for {0}: {1}'.format(
                        pack['name'], str(e)))
                logging.log_notify(
                    CONFIG.ADDONTITLE,
                    '[COLOR {0}]כשל בחילוץ חבילת AF3![/COLOR]'.format(
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
        'icon': 'special://home/media/build_icons/POV/Connect_Services.png',
        'builtin': 'RunPlugin("plugin://plugin.video.pov/?mode=myservices")',
    },
    {
        'id': 'debrid_notice_settings',
        'label': 'הגדרת התראות מנוי',
        'icon': 'special://home/media/build_icons/POV/Connect_Services.png',
        'builtin': 'RunScript(service.subtitles.kodipovilai,action=debrid_notice_settings)',
    },
    {
        'id': 'pov',
        'label': 'כניסה ל-POV',
        'icon': 'special://home/media/build_icons/POV/Logo_POV_IL.png',
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
        'icon': 'special://home/media/build_icons/Wizard/fast_update_pov_il.png',
        'builtin': 'PlayMedia("plugin://plugin.program.kodipovilwizard/?mode=install&action=quick_update&name=Kodi+POV+IL+-+FENtastic&auto_quick_update=false")',
    },
    {
        'id': 'switch_skin',
        'label': 'החלף סקין',
        'icon': 'special://home/media/build_icons/Wizard/wizard_pov_il.png',
        'builtin': 'RunPlugin("plugin://plugin.program.kodipovilwizard/?mode=install&action=build_switch_skin")',
    },
    {
        'id': 'send_log',
        'label': 'שליחת לוג',
        'icon': 'special://home/media/build_icons/Twilight/Send_Log/twilight_send_log.png',
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
            'fanart': 'special://home/media/build_icons/POV/Logo_POV_IL.png',
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
            # One of these tools is a bare ReloadSkin(), reachable from the AF3
            # home tools row at any moment -- including while an update has POV
            # disabled. Predates the reload-guard work rather than being caused
            # by it, but it is a real route to the same broken home screen, and
            # the button costs nothing to hold for a moment.
            if 'ReloadSkin' in (tool.get('builtin') or '') \
                    and Wizard._pov_cycling():
                logging.log('[AF3 TOOLS] POV is mid-cycle; not reloading the '
                            'skin right now.', level=xbmc.LOGWARNING)
                return False
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
        # Arctic Fuse 3 is too big to bundle in the regular build
        # zip (font + studio asset packs blow past GitHub's 100 MB
        # per-file limit). Download + extract the supplemental packs
        # on first switch to AF3. Idempotent: skips packs already on
        # disk so re-switching is fast.
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
# KODI-RD-IL - WINDOWS + ANDROID
_LEGACY_PLATFORM_RELEASE = '21.3-povil.47'


def check_if_running_custom_kodi(kodi_custom_path):
    import xbmcvfs
    kodi_root_path = xbmcvfs.translatePath('special://xbmc/')
    return str(kodi_custom_path).lower() in str(kodi_root_path).lower()


def _marked_platform_release():
    """Return the explicit POV package release marker, or None when absent."""
    import xbmcvfs

    marker = xbmcvfs.translatePath(
        'special://xbmc/system/povil-release.txt')
    handle = None
    try:
        handle = xbmcvfs.File(marker)
        value = handle.read()
        return release_version.canonical_release_label(value)
    except Exception:
        return None
    finally:
        try:
            if handle:
                handle.close()
        except Exception:
            pass


def _installed_platform_release():
    """Return a package release for a user-initiated compatibility check.

    Releases through .47 did not carry a POV-specific marker.  The legacy
    fallback is intentionally retained for manual checks only; automatic
    startup checks skip pre-marker installations in
    ``kodi_version_update_check``.  Package .48 and later always carry the
    marker and remain eligible for future automatic package updates.
    """
    return _marked_platform_release() or _LEGACY_PLATFORM_RELEASE


def _latest_platform_release(pointer_url):
    response = tools.open_url(pointer_url)
    if not response:
        raise ValueError('release pointer is unavailable')
    return release_version.canonical_release_label(response.text)
    
# KODI-RD-IL - ANDROID
def check_if_app_installed(app_package_id):
    import xbmcvfs
    apps = xbmcvfs.listdir('androidapp://sources/apps/')[1]
    return app_package_id in apps
    
def open_google_play_store_on_specific_app(app_package_id):
    app      = 'com.android.vending'
    intent   = 'android.intent.action.VIEW'
    dataType = ''
    dataURI  = f'https://play.google.com/store/apps/details?id={app_package_id}'
    xbmc.executebuiltin(f'StartAndroidActivity("{app}", "{intent}", "{dataType}", "{dataURI}")')

# KODI-RD-IL - ANDROID
def kodi_apk_update_check(kodi_version_update_check_manual, os_type_label):
    dialog = xbmcgui.Dialog()
    try:
        latest_release = _latest_platform_release(
            CONFIG.LATEST_APK_VERSION_TEXT_FILE)
        installed_release = _installed_platform_release()
        is_new_version_available = release_version.is_newer_release(
            latest_release, installed_release)
        
        if is_new_version_available:

            yes_pressed = dialog.yesno(f"{CONFIG.ADDONTITLE} ({os_type_label})",
                               f'[COLOR yellow][B]קיים עדכון גרסה לאפליקציה שלנו![/B][/COLOR]\nגרסת האפליקציה הנוכחית: [B][COLOR red]{installed_release}[/COLOR][/B]\nגרסת האפליקציה המעודכנת: [B][COLOR limegreen]{latest_release}[/COLOR][/B]\nהאם ברצונך לעדכן את האפליקציה?',
                               nolabel='[B][COLOR red]מאוחר יותר[/COLOR][/B]',
                               yeslabel='[B][COLOR springgreen]עדכן[/COLOR][/B]')
                               
            if yes_pressed:
                yes_pressed = dialog.yesno(f"{CONFIG.ADDONTITLE} ({os_type_label})",
                                   f'[B]משתמש בסטרימר Android TV? בחר [COLOR orange]Downloader[/COLOR].\n\nמשתמש בסטרימר/מכשיר אנדרואיד רגיל? בחר [COLOR yellow]Google Chrome[/COLOR].[/B]',
                                   nolabel='[B][COLOR orange]Downloader[/COLOR][/B]',
                                   yeslabel='[B][COLOR yellow]Google Chrome[/COLOR][/B]') 
                                   
                if yes_pressed:
                    google_chrome_app_packge_id = 'com.android.chrome'
                            
                    if check_if_app_installed(google_chrome_app_packge_id):
                        # Open Google Chrome on APK_DOWNLOAD_URL.
                        app      = google_chrome_app_packge_id
                        intent   = 'android.intent.action.VIEW'
                        dataType = ''
                        dataURI  = CONFIG.APK_DOWNLOAD_URL
                        xbmc.executebuiltin(f'StartAndroidActivity("{app}", "{intent}", "{dataType}", "{dataURI}")')
                        return
                        
                    else:
                        yes_pressed = dialog.yesno(f"{CONFIG.ADDONTITLE} ({os_type_label})",
                                           '[B]אפליקציית [COLOR yellow]Google Chrome[/COLOR] אינה מותקנת.[/B]',
                                           nolabel='[B]ביטול[/B]',
                                           yeslabel='[B]הורד מהחנות[/B]')
                        if yes_pressed:
                            # Open Google Play Store on Google Chrome app.
                            open_google_play_store_on_specific_app(google_chrome_app_packge_id)
                            return
                        else:
                            return
                    
                else:
                    downloader_app_packge_id = 'com.esaba.downloader'
                    
                    msg = f"כעת תיפתח אפליקציית Downloader. יש להזין את המספר:\n[COLOR orange]{CONFIG.APK_DOWNLOADER_CODE}[/COLOR]\nולבחור את גרסת ה-APK (32/64 ביט) המתאימה למכשיר שלכם.\n[COLOR limegreen]עכשיו זה הזמן לרשום/לצלם את המספר![/COLOR]"
                    from resources.libs.gui import window
                    window.show_notification_with_extra_image(msg, 999, CONFIG.APK_DOWNLOADER_CODE_IMAGE_URL)
                    
                    # Check if Downloader app installed.
                    if check_if_app_installed(downloader_app_packge_id):
                        xbmc.executebuiltin(f'StartAndroidActivity({downloader_app_packge_id})')
                        return
                        
                    else:
                        yes_pressed = dialog.yesno(f"{CONFIG.ADDONTITLE} ({os_type_label})",
                                           '[B]אפליקציית [COLOR orange]Downloader[/COLOR] אינה מותקנת.[/B]',
                                           nolabel='[B]ביטול[/B]',
                                           yeslabel='[B]הורד מהחנות[/B]')
                        if yes_pressed:
                            # Open Google Play Store on Downloader app.
                            open_google_play_store_on_specific_app(downloader_app_packge_id)
                            return
                        else:
                            return
                
            else:
                return
                    
        elif kodi_version_update_check_manual:
            dialog.ok(f"{CONFIG.ADDONTITLE} ({os_type_label})", f'[COLOR yellow][B]לא קיים עדכון לאפליקציה![/B][/COLOR]\nגרסת האפליקציה הנוכחית: [B][COLOR limegreen]{installed_release}[/COLOR][/B]\nגרסת האפליקציה המעודכנת: [B][COLOR limegreen]{latest_release}[/COLOR][/B]')
                         
    except Exception as e:
        logging.log(f'[kodi_version_update_check] Exception: {str(e)}')
        if kodi_version_update_check_manual:
            dialog.ok(f"{CONFIG.ADDONTITLE} ({os_type_label})", f'התרחשה שגיאה:\n{str(e)}')


# KODI-RD-IL - WINDOWS
def kill_kodi_and_install_exe(exe_full_path):
    import xbmcvfs
    if not xbmcvfs.exists(exe_full_path):
        logging.log_notify(CONFIG.ADDONTITLE,
                            '[COLOR {0}]הקובץ לא נמצא![/COLOR]'.format(CONFIG.COLOR2))
        return False
    
    def kill_kodi():
        subprocess.call(
            ['taskkill', '/f', '/im', 'kodi.exe'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
    
    import subprocess
    import threading

    # os.startfile uses ShellExecute on Windows, so an installer carrying an
    # elevation manifest gets the normal UAC prompt.  Start it first; only once
    # Windows accepted the launch do we close Kodi so the setup can replace the
    # runtime files without requiring the user to kill it manually.
    os.startfile(exe_full_path)
    kodi_killer = threading.Timer(1.0, kill_kodi)
    kodi_killer.daemon = True
    kodi_killer.start()
    return True


# KODI-RD-IL - WINDOWS
def kodi_windows_update_check(kodi_version_update_check_manual, os_type_label):
    dialog = xbmcgui.Dialog()
    
    try:
        latest_release = _latest_platform_release(
            CONFIG.LATEST_WINDOWS_VERSION_TEXT_FILE)
        installed_release = _installed_platform_release()
        is_new_version_available = release_version.is_newer_release(
            latest_release, installed_release)
            
        if is_new_version_available:
            
            yes = dialog.yesno(f"{CONFIG.ADDONTITLE} ({os_type_label})",
                               f'[COLOR yellow][B]קיים עדכון גרסה לאפליקציה שלנו![/B][/COLOR]\nגרסת האפליקציה הנוכחית: [B][COLOR red]{installed_release}[/COLOR][/B]\nגרסת האפליקציה המעודכנת: [B][COLOR limegreen]{latest_release}[/COLOR][/B]\nהאם ברצונך לעדכן את האפליקציה?',
                               nolabel='[B][COLOR red]מאוחר יותר[/COLOR][/B]',
                               yeslabel='[B][COLOR springgreen]עדכן[/COLOR][/B]')
                                       
            if not yes:
                return
            
            if yes:
                direct_windows_download_url = CONFIG.WINDOWS_DOWNLOAD_URL
                
                response = tools.open_url(
                    direct_windows_download_url, check=True)
                if not response:
                    logging.log_notify(f"{CONFIG.ADDONTITLE} ({os_type_label})",
                                        '[COLOR {0}]קישור ההורדה אינו תקין![/COLOR]'.format(CONFIG.COLOR2))
                    return
                    
                # Never download the updater inside portable_data. The NSIS
                # repair installer temporarily moves that whole profile out of
                # the upstream runtime tree; Windows cannot rename a directory
                # that contains the currently-running setup executable.
                import tempfile
                destination_path = os.path.join(
                    tempfile.gettempdir(), 'Kodi-POV-IL-Updates')
                exe_file_name = os.path.basename(
                    direct_windows_download_url)
                exe_full_path = os.path.join(destination_path, exe_file_name)
                   
                progress_dialog = xbmcgui.DialogProgress() 
                progress_dialog.create(f"{CONFIG.ADDONTITLE} ({os_type_label})",
                              '[COLOR {0}][B]מוריד:[/B][/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR2, CONFIG.COLOR1, exe_file_name)
                              +'\n'+''
                              +'\n'+'נא המתן')
                
                try:
                    os.remove(exe_full_path)
                except:
                    pass
                Downloader().download(
                    direct_windows_download_url, exe_full_path)
                xbmc.sleep(100)
                progress_dialog.close()

                if (
                    not os.path.isfile(exe_full_path)
                    or os.path.getsize(exe_full_path) < 10 * 1024 * 1024
                ):
                    raise ValueError(
                        'Windows installer download is incomplete')
                    
                dialog.ok(f"{CONFIG.ADDONTITLE} ({os_type_label})", f"[B]ההורדה הסתיימה בהצלחה.\nלחץ אישור כדי לסגור את קודי ולהתחיל את ההתקנה.[/B]")
                kill_kodi_and_install_exe(exe_full_path)
                        
        elif kodi_version_update_check_manual:
            dialog.ok(f"{CONFIG.ADDONTITLE} ({os_type_label})", f'[COLOR yellow][B]לא קיים עדכון לאפליקציה![/B][/COLOR]\nגרסת האפליקציה הנוכחית: [B][COLOR limegreen]{installed_release}[/COLOR][/B]\nגרסת האפליקציה המעודכנת: [B][COLOR limegreen]{latest_release}[/COLOR][/B]')
                         
    except Exception as e:
        logging.log(f'[kodi_version_update_check] Exception: {str(e)}')
        if kodi_version_update_check_manual:
            dialog.ok(f"{CONFIG.ADDONTITLE} ({os_type_label})", f'התרחשה שגיאה:\n{str(e)}')


# xbmc.executebuiltin(f"RunPlugin(plugin://{CONFIG.ADDON_ID}/?mode=install&action=kodi_version_update_check&kodi_version_update_check_manual=False)")
def kodi_version_update_check(kodi_version_update_check_manual="false"):

    kodi_version_update_check_manual = True if kodi_version_update_check_manual=="true" else False
    os_type_label = tools.platform().capitalize()
    dialog = xbmcgui.Dialog()

    # Existing packages through .47 have no POV release marker.  A quick update
    # must not reinterpret those installs as an invitation to replace the full
    # application.  Manual checks may still use the .47 bridge, while packages
    # carrying the .48+ marker keep normal automatic update eligibility.
    if (
        not kodi_version_update_check_manual
        and _marked_platform_release() is None
    ):
        logging.log(
            '[Application Update Check] Skipping automatic package check for '
            'a legacy pre-marker installation.',
            level=xbmc.LOGINFO)
        return
        
    # Android APK
    if tools.platform() == 'android':
        ###### KODI ANDROID APK INSTALLED CHECK ###########
        if not any(check_if_running_custom_kodi(pkg) for pkg in CONFIG.APK_PACKAGE_IDS):
            if kodi_version_update_check_manual:
                dialog.ok(f"{CONFIG.ADDONTITLE} ({os_type_label})",'[B]אינך עם האפליקצייה הייעודית שלנו![/B]')
            return
        kodi_apk_update_check(kodi_version_update_check_manual, os_type_label)
    
    # Windows Software
    elif tools.platform() == 'windows':
        ###### KODI WINDOWS SOFTWARE INSTALLED CHECK ###########
        if not check_if_running_custom_kodi(CONFIG.WINDOWS_INSTALLATION_PATH):
            if kodi_version_update_check_manual:
                dialog.ok(f"{CONFIG.ADDONTITLE} ({os_type_label})",'[B]אינך עם תוכנת הקודי הייעודית שלנו![/B]')
            return
        kodi_windows_update_check(kodi_version_update_check_manual, os_type_label)
        
    else:
        dialog.ok(CONFIG.ADDONTITLE, f"[B]הפיצ'ר אינו נתמך עבור: {os_type_label}[/B]")
##########################################


##########################################
# KODI-RD-IL - REAL DEBRID SPEED TEST        
def build_speed_test():
    dialog = xbmcgui.Dialog()
    
    # Speed Test addon
    yes_pressed = dialog.yesno(CONFIG.ADDONTITLE,
                       f'[B][COLOR yellow]האם להפעיל בדיקת מהירות דרך הרחבת Speed Test או דרך האתר של ריל דבריד?[/COLOR][/B]',
                       nolabel='[B]Speed Test[/B]',
                       yeslabel='[B]Real Debrid[/B]')
                       
    if not yes_pressed:
        xbmc.executebuiltin('InstallAddon("script.speedtester")')
        xbmc.executebuiltin('RunAddon("script.speedtester")')
        
    else:       
        os_type_label = tools.platform().capitalize()
        
        # Windows
        if tools.platform() == 'windows':
            # Open the URL in default browser
            import webbrowser
            webbrowser.get().open_new_tab("https://real-debrid.com/speedtest")
            
        # Android / Android TV - through browsers apps
        elif tools.platform() == 'android':
        
            android_apps_browsers_list = ['com.android.chrome', 'com.phlox.tvwebbrowser', 'com.seraphic.openinet.pre', 'com.tcl.browser']
            installed_browser_package_id = None

            # Loop through each browser in the list
            for browser_package_id in android_apps_browsers_list:
                # Check if the browser is installed
                if check_if_app_installed(browser_package_id):
                    installed_browser_package_id = browser_package_id
                    break

            if not installed_browser_package_id:
                yes_pressed = dialog.yesno(f"{CONFIG.ADDONTITLE} ({os_type_label})",
                                   f'[B][COLOR yellow]לא מותקן דפדפן תומך!\nדפדנים נתמכים:[/COLOR]\nGoogle Chrome, TV Bro, OPEN BROWSER, BrowseHere[/B]',
                                   nolabel='[B]ביטול[/B]',
                                   yeslabel='[B]קח אותי לחנות[/B]')
                if yes_pressed:
                    # Open Google Play Store
                    xbmc.executebuiltin('StartAndroidActivity(com.android.vending)')
                    return
                return
                            
            app      = installed_browser_package_id
            intent   = 'android.intent.action.VIEW'
            dataType = ''
            dataURI  = "https://real-debrid.com/speedtest"
            xbmc.executebuiltin(f'StartAndroidActivity("{app}", "{intent}", "{dataType}", "{dataURI}")')
            return
            
        else:
            dialog.ok(CONFIG.ADDONTITLE, f"[B]פתיחת דפדפן עבור בדיקת מהירות Real Debrid אינו זמין עבור מערכת ההפעלה: {os_type_label}[/B]")
##########################################
    
