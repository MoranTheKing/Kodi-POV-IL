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


def auto_install_repo():
    if not os.path.exists(os.path.join(CONFIG.ADDONS, CONFIG.REPOID)):
        response = tools.open_url(CONFIG.REPOADDONXML)

        if response:
            from xml.etree import ElementTree
            
            root = ElementTree.fromstring(response.text)
            repoaddon = root.findall('addon')
            repoversion = [tag.get('version') for tag in repoaddon if tag.get('id') == CONFIG.REPOID]
            
            if repoversion:
                installzip = '{0}-{1}.zip'.format(CONFIG.REPOID, repoversion[0])
                url = CONFIG.REPOZIPURL + installzip
                repo_response = tools.open_url(url, check=True)

                if repo_response:
                    progress_dialog = xbmcgui.DialogProgress()
                    
                    progress_dialog.create(CONFIG.ADDONTITLE, 'Downloading Repo...' + '\n' + 'Please Wait')
                    tools.ensure_folders(CONFIG.PACKAGES)
                    lib = os.path.join(CONFIG.PACKAGES, installzip)

                    # Remove the old zip if there is one
                    tools.remove_file(lib)

                    from resources.libs.downloader import Downloader
                    from resources.libs import extract
                    Downloader().download(url, lib)
                    extract.all(lib, CONFIG.ADDONS)

                    try:
                        repoxml = os.path.join(CONFIG.ADDONS, CONFIG.REPOID, 'addon.xml')
                        root = ElementTree.parse(repoxml).getroot()
                        reponame = root.get('name')
                        
                        logging.log_notify("{1}".format(CONFIG.COLOR1, reponame),
                                           "[COLOR {0}]Add-on updated[/COLOR]".format(CONFIG.COLOR2),
                                           icon=os.path.join(CONFIG.ADDONS, CONFIG.REPOID, 'icon.png'))
                                           
                    except Exception as e:
                        logging.log(str(e), level=xbmc.LOGERROR)

                    # Add wizard to add-on database
                    db.addon_database(CONFIG.REPOID, 1)

                    progress_dialog.close()
                    xbmc.sleep(500)

                    logging.log("[Auto Install Repo] Successfully Installed", level=xbmc.LOGINFO)
                else:
                    logging.log_notify("[COLOR {0}]Repo Install Error[/COLOR]".format(CONFIG.COLOR1),
                                       "[COLOR {0}]Invalid URL for zip![/COLOR]".format(CONFIG.COLOR2))
                    logging.log("[Auto Install Repo] Was unable to create a working URL for repository. {0}".format(
                        url), level=xbmc.LOGERROR)
            else:
                logging.log("Invalid URL for Repo zip", level=xbmc.LOGERROR)
        else:
            logging.log_notify("[COLOR {0}]Repo Install Error[/COLOR]".format(CONFIG.COLOR1),
                               "[COLOR {0}]Invalid addon.xml file![/COLOR]".format(CONFIG.COLOR2))
            logging.log("[Auto Install Repo] Unable to read the addon.xml file.", level=xbmc.LOGERROR)
    elif not CONFIG.AUTOINSTALL == 'Yes':
        logging.log("[Auto Install Repo] Not Enabled", level=xbmc.LOGINFO)
    elif os.path.exists(os.path.join(CONFIG.ADDONS, CONFIG.REPOID)):
        logging.log("[Auto Install Repo] Repository already installed")


def show_notification():
    note_id, msg = window.split_notify(CONFIG.NOTIFICATION)
    
    if note_id:
        if note_id == CONFIG.NOTEID:
            if CONFIG.NOTEDISMISS == 'false':
                window.show_notification(msg)
            else:
                logging.log('[Notifications] No new notifications.', level=xbmc.LOGINFO)
        elif int(note_id) > int(CONFIG.NOTEID):
            logging.log('[Notifications] Showing notification {0}'
                        .format(note_id))
            CONFIG.set_setting('noteid', note_id)
            CONFIG.set_setting('notedismiss', 'false')
            window.show_notification(msg)
    else:
        logging.log('[Notifications] Notifications file at {0} not formatted correctly.'
                    .format(CONFIG.NOTIFICATION),
                    level=xbmc.LOGINFO)


# How many times one quick update may be attempted before the wizard stops
# trying it on its own. This is the backstop that makes an update loop
# impossible: an update that cannot record having run would otherwise run
# again on the next startup, force Kodi closed again, and repeat forever.
QUICK_UPDATE_MAX_TRIES = 2


def _quick_update_state_path():
    """Where the applied-quick-update record lives, beside the wizard's own
    add-on data."""
    import xbmcvfs
    return os.path.join(
        xbmcvfs.translatePath(
            'special://profile/addon_data/{0}/'.format(CONFIG.ADDON_ID)),
        'quick_update_state.json')


def _quick_update_state():
    """{'applied': int, 'tries': {note_id: int}} -- never raises."""
    state = {'applied': 0, 'tries': {}}
    try:
        import json
        with open(_quick_update_state_path(), 'r') as fh:
            raw = json.load(fh) or {}
        state['applied'] = int(raw.get('applied') or 0)
        tries = raw.get('tries') or {}
        state['tries'] = {str(k): int(v) for k, v in tries.items()}
    except Exception:
        pass
    return state


def _write_quick_update_state(state):
    """Write the record and flush it all the way to disk. Returns True only if
    it reads back, because the whole point is to know rather than to assume.

    A plain file, and not only the add-on setting, because the setting is
    written through an add-on handle at the exact moment the package we just
    extracted has replaced the wizard's own files underneath it -- and
    CONFIG.set_setting swallows every error and returns a False nobody checks.
    The write is then followed by a hard kill that deliberately skips Kodi's
    shutdown save. Lose it and the next startup sees the same number, updates
    again and kills Kodi again, which is the loop users hit."""
    try:
        import json
        path = _quick_update_state_path()
        folder = os.path.dirname(path)
        if not os.path.exists(folder):
            os.makedirs(folder)
        with open(path, 'w') as fh:
            json.dump(state, fh)
            fh.flush()
            os.fsync(fh.fileno())
        return _quick_update_state().get('applied') == state.get('applied')
    except Exception as state_err:
        logging.log(
            '[QUICK-UPDATE] Could not record update state: {0}'.format(
                state_err), level=xbmc.LOGERROR)
        return False


def quick_update_applied_id():
    """The highest quick-update number we can PROVE was applied, from either
    store. Taking the higher of the two means a working setting still counts if
    the file is missing, and vice versa."""
    best = 0
    try:
        best = max(best, int(str(CONFIG.QUICK_UPDATE_NOTEID or '0').strip() or 0))
    except (TypeError, ValueError):
        pass
    try:
        best = max(best, int(_quick_update_state().get('applied') or 0))
    except (TypeError, ValueError):
        pass
    return best


def record_quick_update_applied(note_id):
    """Record `note_id` as applied in BOTH stores. Returns True only when it can
    be read back afterwards."""
    stored = False
    try:
        CONFIG.set_setting('quick_update_noteid', str(note_id))
        CONFIG.set_setting('quick_update_notedismiss', 'false')
        CONFIG.QUICK_UPDATE_NOTEID = str(note_id)
        CONFIG.QUICK_UPDATE_NOTEDISMISS = 'false'
        stored = str(CONFIG.get_setting('quick_update_noteid') or '').strip() \
            == str(note_id)
    except Exception:
        stored = False
    state = _quick_update_state()
    state['applied'] = max(int(state.get('applied') or 0), int(note_id))
    filed = _write_quick_update_state(state)
    if not (stored or filed):
        logging.log(
            '[QUICK-UPDATE] Update {0} ran but could NOT be recorded in either '
            'the add-on setting or {1}. Not restarting: a restart that cannot '
            'remember it happened is what turns an update into a loop.'.format(
                note_id, _quick_update_state_path()), level=xbmc.LOGERROR)
        return False
    # Only now, with the update provably recorded, does the attempt counter stop
    # mattering. Clearing it any earlier hands back the one thing that bounds a
    # run of failures: a record that did not stick, followed by a counter reset,
    # is a fresh first attempt on every startup for ever.
    state['tries'] = {}
    _write_quick_update_state(state)
    try:
        CONFIG.set_setting('quick_update_tries', '')
    except Exception:
        pass
    return True


def _quick_update_tries_stored(note_id):
    """Attempts recorded in the add-on setting, as '<note id>:<count>'. Scoped
    to the id so a new release starts from zero rather than inheriting the last
    one's count."""
    raw = str(CONFIG.get_setting('quick_update_tries') or '').strip()
    key, _sep, value = raw.partition(':')
    if key.strip() != str(note_id):
        return 0
    try:
        return int(value.strip() or 0)
    except (TypeError, ValueError):
        return 0


def _count_quick_update_try(note_id):
    """Count an attempt BEFORE making it, so that an attempt which never
    returns -- Kodi force-closed mid-update, or killed by the system -- is
    counted all the same. Returns (attempts_so_far, can_remember).

    The counter is kept in BOTH stores, for the same reason the applied number
    is: a counter held only in the file this mechanism exists to work around
    cannot advance when that file is the thing that is broken, and a cap that
    cannot advance is not a cap. With the update then running on every startup,
    that is a package downloaded and extracted every launch -- no force-close,
    but not something to leave running either.

    `can_remember` is a read-back of THIS counter, not of some other value that
    happens to be writable. Checking a different key was the flaw here: the one
    used was already at the value being written for anyone with a past update
    behind them, so it read as success while the counter itself went nowhere."""
    key = str(note_id)
    state = _quick_update_state()
    tries = max(int(state['tries'].get(key) or 0),
                _quick_update_tries_stored(note_id)) + 1
    state['tries'] = {key: tries}
    filed = _write_quick_update_state(state)
    try:
        CONFIG.set_setting('quick_update_tries', '{0}:{1}'.format(key, tries))
        stamped = _quick_update_tries_stored(note_id) == tries
    except Exception:
        stamped = False
    return tries, (filed or stamped)


# xbmc.executebuiltin(f"RunPlugin(plugin://{CONFIG.ADDON_ID}/?mode=install&action=quick_update&name={quote_plus(CONFIG.BUILDNAME)}&auto_quick_update=true)")
def auto_quick_update():

    note_id, msg = window.split_notify(CONFIG.QUICK_UPDATE_NOTIFICATION_URL)

    if not note_id:
        return

    note_id = str(note_id).strip()
    current_number = quick_update_applied_id()
    current_note_id = str(current_number)
    logging.log(
        '[QUICK-UPDATE] note_id={0} | applied={1} (setting={2}, file={3})'.format(
            note_id, current_number, CONFIG.QUICK_UPDATE_NOTEID,
            _quick_update_state().get('applied')
        )
    )

    try:
        remote_number = int(note_id)
    except (TypeError, ValueError):
        logging.log(
            '[QUICK-UPDATE] Invalid note id (remote={0}, stored={1}); '
            'leaving state unchanged.'.format(note_id, current_note_id),
            level=xbmc.LOGERROR,
        )
        return

    if remote_number == current_number:
        if CONFIG.QUICK_UPDATE_NOTEDISMISS == 'false':
            window.show_notification(msg, source="quick_update_notification")
        return

    if remote_number < current_number:
        return

    # Count the attempt BEFORE making it. An update that force-closes Kodi and
    # then cannot record that it ran would otherwise be attempted again on the
    # next startup, and again after that, with no end -- the loop users hit. A
    # counter written up front is counted even when the attempt never returns,
    # so after a couple of goes the wizard stops driving it and simply says so.
    tries, can_remember = _count_quick_update_try(remote_number)
    if not can_remember:
        logging.log(
            '[QUICK-UPDATE] Neither the add-on setting nor {0} can be written, '
            'so this update could not be recorded as done and would be run '
            'again on every startup. Not running it -- showing the '
            'notification instead.'.format(_quick_update_state_path()),
            level=xbmc.LOGERROR)
        window.show_notification(msg, source="quick_update_notification")
        return
    if tries > QUICK_UPDATE_MAX_TRIES:
        logging.log(
            '[QUICK-UPDATE] Update {0} has already been attempted {1} time(s) '
            'without being recorded as done. Not attempting it again '
            'automatically -- showing the notification instead.'.format(
                note_id, tries - 1), level=xbmc.LOGERROR)
        window.show_notification(msg, source="quick_update_notification")
        return

    logging.log(
        '[QUICK-UPDATE] Starting quick update number {0} (attempt {1})'.format(
            note_id, tries)
    )
    from resources.libs.wizard import Wizard
    wizard = Wizard()
    try:
        quick_update_status = wizard.quick_update(
            name=CONFIG.BUILDNAME,
            auto_quick_update="true",
            expected_note_id=note_id,
        )
    except Exception as update_err:
        logging.log(
            '[QUICK-UPDATE] Update {0} failed before completion; keeping '
            'stored note id {1} so the next startup retries: {2}'.format(
                note_id, current_note_id, update_err
            ),
            level=xbmc.LOGERROR,
        )
        return

    if not quick_update_status:
        logging.log(
            '[QUICK-UPDATE] Update {0} did not complete; keeping stored '
            'note id {1} so the next startup retries.'.format(
                note_id, current_note_id
            ),
            level=xbmc.LOGERROR,
        )
        return

    # Commit the delivery state only AFTER the package completed. The old
    # order wrote the new id before download/extract; one transient failure
    # permanently suppressed every retry for that release.
    #
    # ...and only restart once that record is PROVEN to have stuck. Restarting
    # without it is precisely what makes a loop: the files are in place, Kodi is
    # force-closed, and the next startup finds the same number waiting and does
    # it all again. If it cannot be recorded, the update is still installed --
    # it simply takes effect the next time Kodi starts on its own.
    if not record_quick_update_applied(note_id):
        return
    # Try to apply it without throwing the user out of Kodi first. This is
    # not cosmetic: the old flow force-closed on EVERY update, and Android --
    # where most of these devices are -- has no way to bring Kodi back, so
    # every release cost every user a manual relaunch. See Wizard.hot_reload
    # for why a restart was needed at all (reuselanguageinvoker) and what
    # replaces it. A hot reload that does not fully take falls straight back
    # to the old behaviour, so the worst case is unchanged.
    try:
        if wizard.hot_reload():
            logging.log(
                '[QUICK-UPDATE] Update {0} applied in place; no restart '
                'needed.'.format(note_id))
            return
    except Exception as reload_err:
        logging.log(
            '[QUICK-UPDATE] Hot reload raised, restarting instead: '
            '{0}'.format(reload_err), level=xbmc.LOGWARNING)
    wizard.force_close_kodi_in_5_seconds(
        dialog_header="עדכון מהיר הסתיים בהצלחה"
    )


def sync_quickfix_build_version():
    try:
        if CONFIG.get_setting('buildname') != CONFIG.BUILDNAME_DEFAULT:
            return

        latest_version = check.check_build(CONFIG.BUILDNAME_DEFAULT, 'version')
        if not latest_version:
            return

        if CONFIG.get_setting('buildversion') == latest_version:
            if CONFIG.get_setting('latestversion') != latest_version:
                CONFIG.set_setting('latestversion', latest_version)
            return

        CONFIG.set_setting('buildversion', latest_version)
        CONFIG.set_setting('latestversion', latest_version)
        CONFIG.BUILDVERSION = latest_version
        CONFIG.BUILDLATEST = latest_version
        logging.log(
            "[QUICK-UPDATE] Synced buildversion/latestversion to {0} "
            "to prevent full-build prompts; quick_update remains the update path.".format(latest_version),
            level=xbmc.LOGINFO,
        )
    except Exception as sync_err:
        logging.log(
            "[QUICK-UPDATE] Failed to sync quickfix build version: {0}".format(sync_err),
            level=xbmc.LOGERROR,
        )


def fresh_build_auto_install_if_needed():
    """Hydrate a clean profile with the full build once.

    Existing users already have buildname set and stay on the safe quick_update
    path. A fresh APK/IPK/Windows/wizard profile needs the full build extracted
    once so guisettings, FENtastic settings, favourites, and addon DB rows exist.
    """
    if CONFIG.get_setting('buildname'):
        return False
    if CONFIG.get_setting('installed') == 'true':
        return False
    # Pre-seeded installs (e.g. the Windows installer extracts the full
    # build into portable_data before the first launch) already have the
    # build on disk -- re-downloading it here would extract over a live
    # profile for nothing. Let the auto-set-buildname block below adopt
    # the existing install instead.
    if os.path.exists(os.path.join(CONFIG.ADDONS, 'plugin.video.pov')):
        logging.log(
            "[Fresh Build Auto Install] plugin.video.pov already on disk; "
            "skipping hydration and letting auto-set-buildname adopt it.",
            level=xbmc.LOGINFO,
        )
        return False

    build_name = CONFIG.BUILDNAME_DEFAULT
    build_version = CONFIG.BUILDVERSION_DEFAULT
    try:
        build_url = check.check_build(build_name, 'url')
        remote_version = check.check_build(build_name, 'version')
        if remote_version:
            build_version = remote_version
    except Exception as err:
        logging.log(
            "[Fresh Build Auto Install] Failed reading build.txt: {0}".format(err),
            level=xbmc.LOGERROR,
        )
        return False

    if not build_url:
        return False

    if CONFIG.get_setting('fresh_build_auto_install_done') == build_version:
        return False

    try:
        from resources.libs.downloader import Downloader
        from resources.libs import extract

        tools.ensure_folders(CONFIG.PACKAGES)
        zipname = build_name.replace('\\', '').replace('/', '').replace(':', '').replace('*', '').replace('?', '').replace('"', '').replace('<', '').replace('>', '').replace('|', '')
        lib = os.path.join(CONFIG.PACKAGES, '{0}_fresh_install.zip'.format(zipname))
        tools.remove_file(lib)

        logging.log(
            "[Fresh Build Auto Install] Installing {0} v{1}".format(
                build_name, build_version
            ),
            level=xbmc.LOGINFO,
        )
        Downloader().download(build_url, lib)
        xbmc.sleep(500)

        if not os.path.exists(lib) or os.path.getsize(lib) == 0:
            tools.remove_file(lib)
            return False

        title = '[COLOR {0}][B]Installing:[/B][/COLOR] [COLOR {1}]{2}[/COLOR]'.format(
            CONFIG.COLOR2, CONFIG.COLOR1, build_name
        )
        percent, errors, error = extract.all(lib, CONFIG.HOME, ignore=True, title=title)
        if int(float(percent)) <= 0:
            logging.log(
                "[Fresh Build Auto Install] Extract failed: {0}".format(error),
                level=xbmc.LOGERROR,
            )
            return False

        installed = db.grab_addons(lib)
        db.addon_database(installed, 1, True)
        db.addon_database(CONFIG.ADDON_ID, 1)
        db.fix_metas()

        CONFIG.set_setting('buildname', build_name)
        CONFIG.set_setting('installed', 'true')
        CONFIG.set_setting('buildversion', build_version)
        CONFIG.set_setting('latestversion', build_version)
        CONFIG.set_setting('nextbuildcheck', tools.get_date(days=CONFIG.UPDATECHECK, formatted=True))
        CONFIG.set_setting('extract', percent)
        CONFIG.set_setting('errors', errors)
        CONFIG.set_setting('fresh_build_auto_install_done', build_version)

        CONFIG.BUILDNAME = build_name
        CONFIG.BUILDVERSION = build_version
        CONFIG.BUILDLATEST = build_version
        CONFIG.INSTALLED = 'true'

        tools.remove_file(lib)

        from resources.libs.gui import window as _window
        note_id, _msg = _window.split_notify(CONFIG.QUICK_UPDATE_NOTIFICATION_URL)
        if note_id:
            # A fresh install already carries the current package, so stamp the
            # number down as applied -- otherwise the very first startup after
            # it quick-updates to what it just installed. Through the same
            # durable record as the quick-update path: this write is followed by
            # the same hard kill, and losing it here is how a brand new install
            # ends up updating and restarting on every launch.
            record_quick_update_applied(str(note_id).strip())
            CONFIG.set_setting('quick_update_notedismiss', 'true')
            CONFIG.QUICK_UPDATE_NOTEDISMISS = 'true'

        from resources.libs.wizard import Wizard
        Wizard().force_close_kodi_in_5_seconds(
            dialog_header="Kodi POV IL build installed"
        )
        return True
    except Exception as err:
        logging.log(
            "[Fresh Build Auto Install] Failed: {0}".format(err),
            level=xbmc.LOGERROR,
        )
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
            gui_xml = check.check_build(CONFIG.BUILDNAME, 'gui')

            response = tools.open_url(gui_xml, check=True)
            if not response:
                logging.log("[Build Installed Check] Guifix was set to http://", level=xbmc.LOGINFO)
                dialog.ok(CONFIG.ADDONTITLE,
                          "[COLOR {0}]It looks like the skin settings was not applied to the build.".format(CONFIG.COLOR2)
                          +'\n'+"Sadly no gui fix was attached to the build"
                          +'\n'+"You will need to reinstall the build and make sure to do a force close[/COLOR]")
            else:
                yes = dialog.yesno(CONFIG.ADDONTITLE,
                                       '{0} was not installed correctly!'.format(CONFIG.BUILDNAME)
                                       +'\n'+'It looks like the skin settings was not applied to the build.'
                                       +'\n'+'Would you like to apply the GuiFix?',
                                       nolabel='[B]No, Cancel[/B]', yeslabel='[B]Apply Fix[/B]')
                if yes:
                    xbmc.executebuiltin("PlayMedia(plugin://{0}/?mode=install&name={1}&url=gui)".format(CONFIG.ADDON_ID,
                                                                                                        quote_plus(CONFIG.BUILDNAME)))
                    logging.log("[Build Installed Check] Guifix attempting to install")
                else:
                    logging.log('[Build Installed Check] Guifix url working but cancelled: {0}'.format(gui_xml),
                                level=xbmc.LOGINFO)
    else:
        logging.log('[Build Installed Check] Install seems to be completed correctly', level=xbmc.LOGINFO)
        
    if CONFIG.get_setting('installed') == 'true':
        if CONFIG.get_setting('keeptrakt') == 'true':
            from resources.libs import traktit
            logging.log('[Build Installed Check] Restoring Trakt Data', level=xbmc.LOGINFO)
            traktit.trakt_it('restore', 'all')
        if CONFIG.get_setting('keepdebrid') == 'true':
            from resources.libs import debridit
            logging.log('[Build Installed Check] Restoring Real Debrid Data', level=xbmc.LOGINFO)
            debridit.debrid_it('restore', 'all')
        if CONFIG.get_setting('keeplogin') == 'true':
            from resources.libs import loginit
            logging.log('[Build Installed Check] Restoring Login Data', level=xbmc.LOGINFO)
            loginit.login_it('restore', 'all')

        CONFIG.clear_setting('install')


def build_update_check():
    response = tools.open_url(CONFIG.BUILDFILE, check=True)

    if not response:
        logging.log("[Build Check] Not a valid URL for Build File: {0}".format(CONFIG.BUILDFILE), level=xbmc.LOGINFO)
    elif not CONFIG.BUILDNAME == '':
        # if CONFIG.SKIN in ['skin.confluence', 'skin.estuary', 'skin.estouchy'] and not CONFIG.DEFAULTIGNORE == 'true':
            # check.check_skin()

        logging.log("[Build Check] Build Installed: Checking Updates", level=xbmc.LOGINFO)
        check.check_build_update()

    CONFIG.set_setting('nextbuildcheck', tools.get_date(days=CONFIG.UPDATECHECK, formatted=True))


def save_trakt():
    current_time = time.mktime(time.strptime(tools.get_date(formatted=True), "%Y-%m-%d %H:%M:%S"))
    next_save = time.mktime(time.strptime(CONFIG.get_setting('traktnextsave'), "%Y-%m-%d %H:%M:%S"))
    
    if next_save <= current_time:
        from resources.libs import traktit
        logging.log("[Trakt Data] Saving all Data", level=xbmc.LOGINFO)
        traktit.auto_update('all')
        CONFIG.set_setting('traktnextsave', tools.get_date(days=3, formatted=True))
    else:
        logging.log("[Trakt Data] Next Auto Save isn't until: {0} / TODAY is: {1}".format(CONFIG.get_setting('traktnextsave'),
                                                                                          tools.get_date(formatted=True)),
                    level=xbmc.LOGINFO)


def save_debrid():
    current_time = time.mktime(time.strptime(tools.get_date(formatted=True), "%Y-%m-%d %H:%M:%S"))
    next_save = time.mktime(time.strptime(CONFIG.get_setting('debridnextsave'), "%Y-%m-%d %H:%M:%S"))
    
    if next_save <= current_time:
        from resources.libs import debridit
        logging.log("[Debrid Data] Saving all Data", level=xbmc.LOGINFO)
        debridit.auto_update('all')
        CONFIG.set_setting('debridnextsave', tools.get_date(days=3, formatted=True))
    else:
        logging.log("[Debrid Data] Next Auto Save isn't until: {0} / TODAY is: {1}".format(CONFIG.get_setting('debridnextsave'),
                                                                                           tools.get_date(formatted=True)),
                    level=xbmc.LOGINFO)


def save_login():
    current_time = time.mktime(time.strptime(tools.get_date(formatted=True), "%Y-%m-%d %H:%M:%S"))
    next_save = time.mktime(time.strptime(CONFIG.get_setting('loginnextsave'), "%Y-%m-%d %H:%M:%S"))
    
    if next_save <= current_time:
        from resources.libs import loginit
        logging.log("[Login Info] Saving all Data", level=xbmc.LOGINFO)
        loginit.auto_update('all')
        CONFIG.set_setting('loginnextsave', tools.get_date(days=3, formatted=True))
    else:
        logging.log("[Login Info] Next Auto Save isn't until: {0} / TODAY is: {1}".format(CONFIG.get_setting('loginnextsave'),
                                                                                          tools.get_date(formatted=True)),
                    level=xbmc.LOGINFO)


def auto_clean():
    service = False
    days = [tools.get_date(formatted=True), tools.get_date(days=1, formatted=True), tools.get_date(days=3, formatted=True), tools.get_date(days=7, formatted=True),
            tools.get_date(days=30, formatted=True)]

    freq = int(CONFIG.AUTOFREQ)
    next_cleanup = time.mktime(time.strptime(CONFIG.NEXTCLEANDATE, "%Y-%m-%d %H:%M:%S"))

    if next_cleanup <= tools.get_date() or freq == 0:
        service = True
        next_run = days[freq]
        CONFIG.set_setting('nextautocleanup', next_run)
    else:
        logging.log("[Auto Clean Up] Next Clean Up {0}".format(CONFIG.NEXTCLEANDATE),
                    level=xbmc.LOGINFO)
    if service:
        if CONFIG.AUTOCACHE == 'true':
            logging.log('[Auto Clean Up] Cache: On', level=xbmc.LOGINFO)
            clear.clear_cache(True)
        else:
            logging.log('[Auto Clean Up] Cache: Off', level=xbmc.LOGINFO)
        if CONFIG.AUTOTHUMBS == 'true':
            logging.log('[Auto Clean Up] Old Thumbs: On', level=xbmc.LOGINFO)
            clear.old_thumbs()
        else:
            logging.log('[Auto Clean Up] Old Thumbs: Off', level=xbmc.LOGINFO)
        if CONFIG.AUTOPACKAGES == 'true':
            logging.log('[Auto Clean Up] Packages: On', level=xbmc.LOGINFO)
            clear.clear_packages_startup()
        else:
            logging.log('[Auto Clean Up] Packages: Off', level=xbmc.LOGINFO)


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
    try:
        monitor = xbmc.Monitor()
        waited = 0
        while waited < timeout:
            if xbmc.getCondVisibility('Window.IsVisible(home)'):
                # Home is up; give the skin a moment to finish drawing
                # before we layer a modal on top of it.
                xbmc.sleep(750)
                return True
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
check_for_video()
# FIRST, before anything can need them: switch back on anything a previous
# hot reload left disabled. A disabled add-on cannot heal itself, and a
# disabled add-on stays disabled across restarts -- so if a cycle was cut
# short (enable call failed, Kodi killed between the two calls), this is the
# only thing standing between the user and a permanently missing POV.
try:
    from resources.libs.wizard import Wizard as _HealWizard
    _HealWizard.heal_disabled_addons()
except Exception as _heal_err:
    logging.log('[HOT-RELOAD] heal pass failed: {0}'.format(_heal_err),
                level=xbmc.LOGWARNING)
# Ensure that any needed folders are created
tools.ensure_folders()
# Stop this script if it's been run more than once
# if CONFIG.KODIV < 18:
    # stop_if_duplicate()
# Ensure that the wizard's name matches its folder
check.check_paths()
    
# AUTO UPDATE WIZARD
if CONFIG.AUTOUPDATE == 'Yes':
    logging.log("[Auto Update Wizard] Started", level=xbmc.LOGINFO)
    update.wizard_update()
else:
    logging.log("[Auto Update Wizard] Not Enabled", level=xbmc.LOGINFO)

# KODI-RD-IL - Auto force addon updates on Kodi startup
if CONFIG.FORCEUPDATEFAST_ONSTARTUP == "true": db.forceUpdate()

# KODI-POV-IL - Clean APK/IPK/Windows/wizard first launch hydration.
# This is intentionally before notifications and quick_update: a clean profile
# first needs the full build (userdata + FENtastic + favourites) extracted.
if fresh_build_auto_install_if_needed():
    sys.exit()

# Everything below can pop a modal dialog (build first-launch notification,
# skin-switch notification, quick-update prompt). Because this is a
# start="startup" service those modals can fire before Kodi's GUI exists
# and deadlock the boot -- the "hangs once after install/quick update,
# force-stop to recover" symptom. Block here until Home is actually live
# (bounded) so every dialog below has a real parent window.
wait_for_gui_ready()

# SHOW NOTIFICATIONS
if CONFIG.ENABLE_NOTIFICATION == 'Yes' and CONFIG.get_setting('buildname'):
    show_notification()
else:
    logging.log('[Notifications] Not Enabled', level=xbmc.LOGINFO)
    
######################################
# KODI-RD-IL - FIRST BUILD LAUNCH BUILD SKIN SWITCH NOTIFICATION
if CONFIG.get_setting('buildname') and CONFIG.get_setting('build_skin_switch_notifcation_dismiss') == 'false':
    CONFIG.set_setting('build_skin_switch_notifcation_dismiss', 'true')
    msg = f"על מנת להחליף סקין יש ללחוץ: כפתור כיבוי --> החלף סקין.\nהסקינים הקיימים בבילד:\n1. סקין Estuary\n2. סקין FENtastic\n3. סקין Arctic Fuse 3\n4. סקין NOX"
    window.show_notification_with_extra_image(msg, 888, CONFIG.BUILD_SKIN_SWITCH_IMAGE_URL)
#####################################

######################################
# KODI-RD-IL - Auto-set buildname for APK installs where the user
# never ran a wizard-driven Fresh Install. Without this the empty
# 'buildname' setting silently disables the entire auto_quick_update
# path below, so existing APK users would never receive quickfix
# updates. Detect that POV is on disk (so the build really is
# installed, just not registered with the wizard) and populate the
# settings the wizard's update gates check.
try:
    if not CONFIG.get_setting('buildname'):
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
# KODI-RD-IL - AUTO QUICK UPDATE
if CONFIG.get_setting('buildname'):
    sync_quickfix_build_version()
    auto_quick_update()
######################################
    
# KOD-RD-IL - New Kodi ANDROID/WINDOWS version check on startup
# xbmc.executebuiltin(f"RunPlugin(plugin://{CONFIG.ADDON_ID}/?mode=install&action=kodi_version_update_check&kodi_version_update_check_manual=false)")
if tools.platform() in ['android', 'windows'] and CONFIG.get_setting('buildname'):
    from resources.libs.wizard import kodi_version_update_check
    kodi_version_update_check()
######################################

# BUILD UPDATE CHECK
buildcheck = CONFIG.get_setting('nextbuildcheck')
if CONFIG.get_setting('buildname'):
    current_time = time.time()
    epoch_check = time.mktime(time.strptime(buildcheck, "%Y-%m-%d %H:%M:%S"))
    
    if current_time >= epoch_check:
        logging.log("[Build Update Check] Started", level=xbmc.LOGINFO)
        build_update_check()
else:
    logging.log("[Build Update Check] Next Check: {0}".format(buildcheck), level=xbmc.LOGINFO)

# KODI-RD-IL - BUILD INSTALL ON STARTUP
if tools.open_url(CONFIG.BUILDFILE, check=True) and CONFIG.get_setting('installed') == 'false':
    logging.log("[Current Build Check] Build Not Installed", level=xbmc.LOGINFO)
    CONFIG.set_setting('nextbuildcheck', tools.get_date(days=CONFIG.UPDATECHECK, formatted=True))
    CONFIG.set_setting('installed', 'ignored')
    
    # Taken from build_menu.py - get_listing()
    import re
    response = tools.open_url(CONFIG.BUILDFILE)
    link = tools.clean_text(response.text)
        
    total, *_ = check.build_count()
    match = re.compile('name="(.+?)".+?ersion="(.+?)".+?rl="(.+?)".+?ui="(.+?)".+?odi="(.+?)".+?heme="(.+?)".+?con="(.+?)".+?anart="(.+?)".+?dult="(.+?)".+?escription="(.+?)"').findall(link)
    
    # Open the wizard's Builds menu in the UI so the user can hit
    # "Fresh Install" themselves. We previously tried auto-installing
    # via Wizard().build(over=True) and then via RunPlugin(...&over=true),
    # but on Android the service / queued plugin invocation kept dying
    # somewhere between download and full install -- Kodi exited after
    # the 45 MB download and the build state never settled. The manual
    # UI click path (Add-ons -> Kodi POV IL Wizard -> Builds -> Fresh
    # Install) works reliably, so we delegate to it.
    url = 'plugin://{0}/?mode=builds'.format(CONFIG.ADDON_ID)
    xbmc.executebuiltin('ActivateWindow(Programs, {0}, return)'.format(url))
else:
    logging.log("[Current Build Check] Build Installed: {0}".format(CONFIG.BUILDNAME), level=xbmc.LOGINFO)


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

# KODI-POV-IL - Account Manager for everyone, once per device. The build's
# "חיבור שירותים" screen now authorises the debrid and Trakt accounts through
# it, so one connect reaches every add-on instead of POV alone; without it
# installed those rows silently fall back to POV-only. Existing users get it
# on their next startup, fresh installs on their first. Guarded by its own
# marker setting, so it never runs twice and never fights a user who removed
# it on purpose.
try:
    from resources.libs import wizard as _wiz_am
    _wiz_am.ensure_acctmgr_for_everyone()
except Exception as _am_err:
    logging.log("[Account Manager] startup hook failed: {0}".format(_am_err),
                level=xbmc.LOGERROR)

# SAVE TRAKT
if CONFIG.get_setting('keeptrakt') == 'true':
    logging.log("[Trakt Data] Started", level=xbmc.LOGINFO)
    save_trakt()
else:
    logging.log("[Trakt Data] Not Enabled", level=xbmc.LOGINFO)

# SAVE DEBRID
if CONFIG.get_setting('keepdebrid') == 'true':
    logging.log("[Debrid Data] Started", level=xbmc.LOGINFO)
    save_debrid()
else:
    logging.log("[Debrid Data] Not Enabled", level=xbmc.LOGINFO)
###############################
###################UNUSED####################

######################################
# KODI-RD-IL - COMMENTED - NOT NEEDED:
# FIRST RUN SETTINGS
# if CONFIG.get_setting('first_install') == 'true':
    # logging.log("[First Run] Showing Save Data Settings", level=xbmc.LOGINFO)
    # window.show_save_data_settings()
# else:
    # logging.log("[First Run] Skipping Save Data Settings", level=xbmc.LOGINFO)
######################################

# KODI-RD-IL - COMMENTED - NOT NEEDED:
# BUILD INSTALL PROMPT
# if tools.open_url(CONFIG.BUILDFILE, check=True) and CONFIG.get_setting('installed') == 'false':
    # logging.log("[Current Build Check] Build Not Installed", level=xbmc.LOGINFO)
    # window.show_build_prompt()
# else:
    # logging.log("[Current Build Check] Build Installed: {0}".format(CONFIG.BUILDNAME), level=xbmc.LOGINFO)
######################################
    
# SAVE LOGIN
# if CONFIG.get_setting('keeplogin') == 'true':
    # logging.log("[Login Info] Started", level=xbmc.LOGINFO)
    # save_login()
# else:
    # logging.log("[Login Info] Not Enabled", level=xbmc.LOGINFO)

# AUTO INSTALL REPO
# if CONFIG.AUTOINSTALL == 'Yes':
    # logging.log("[Auto Install Repo] Started", level=xbmc.LOGINFO)
    # auto_install_repo()
# else:
    # logging.log("[Auto Install Repo] Not Enabled", level=xbmc.LOGINFO)

# ENABLE ALL ADDONS AFTER INSTALL
# if CONFIG.get_setting('enable_all') == 'true':
    # logging.log("[Post Install] Enabling all Add-ons", level=xbmc.LOGINFO)
    # from resources.libs.gui import menu
    # menu.enable_addons(all=True)
    # if os.path.exists(os.path.join(CONFIG.USERDATA, '.enableall')):
        # logging.log("[Post Install] .enableall file found in userdata. Deleting..", level=xbmc.LOGINFO)
        # import xbmcvfs
        # xbmcvfs.delete(os.path.join(CONFIG.USERDATA, '.enableall'))
    # xbmc.executebuiltin('UpdateLocalAddons')
    # xbmc.executebuiltin('UpdateAddonRepos')
    # db.force_check_updates(auto=True)
    # CONFIG.set_setting('enable_all', 'false')
    # xbmc.executebuiltin("ReloadSkin()")
    # tools.reload_profile(xbmc.getInfoLabel('System.ProfileName'))

# REINSTALL ELIGIBLE BINARIES
# binarytxt = os.path.join(CONFIG.USERDATA, 'build_binaries.txt')
# if os.path.exists(binarytxt):
    # logging.log("[Binary Detection] Reinstalling Eligible Binary Addons", level=xbmc.LOGINFO)
    # from resources.libs import restore
    # restore.restore('binaries')
# else:
    # logging.log("[Binary Detection] Eligible Binary Addons to Reinstall", level=xbmc.LOGINFO)

# AUTO CLEAN
# if CONFIG.get_setting('autoclean') == 'true':
    # logging.log("[Auto Clean Up] Started", level=xbmc.LOGINFO)
    # auto_clean()
# else:
    # logging.log('[Auto Clean Up] Not Enabled', level=xbmc.LOGINFO)
    
