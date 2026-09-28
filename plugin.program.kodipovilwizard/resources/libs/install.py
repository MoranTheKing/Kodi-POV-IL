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
import xbmcaddon
import xbmcgui
import xbmcvfs

import glob
import os
import shutil

from resources.libs.common.config import CONFIG
from resources.libs.common import logging


###########################
#      Fresh Install      #
###########################

def backup_fentasticdata():
    try:
        # Verify that FENtastic + Helper addon is installed.
        isFENtasticExists = xbmc.getCondVisibility('System.HasAddon(skin.fentastic)') and xbmc.getCondVisibility('System.HasAddon(script.fentastic.helper)')
        keep_enabled = getattr(CONFIG, 'KEEPFENTASTICDATA', 'false') == 'true'
        logging.log(f"[Install/Wipe] BEFORE Wipe - Is KEEPFENTASTICDATA Enabled: {keep_enabled} | isFENtasticExists: {isFENtasticExists}")

        if keep_enabled and isFENtasticExists:

            # Helper .db files directory Path
            fentastic_helper_db_files_dir = os.path.join(os.path.abspath(CONFIG.ADDON_DATA), 'script.fentastic.helper')
            logging.log(f"[Install/Wipe] FENtastic Helper .db files SRC: {fentastic_helper_db_files_dir}")
            
            # My_Builds/fentastic_helper_db_files directory Path        
            kodi_my_builds_fentastic_helper_db_files_dir = os.path.join(os.path.abspath(CONFIG.HOME), 'My_Builds', 'fentastic_helper_db_files')
            logging.log(f"[Install/Wipe] FENtastic Helper .db files DEST: {kodi_my_builds_fentastic_helper_db_files_dir}")
            
            # Create the destination directory if it does not exist
            os.makedirs(kodi_my_builds_fentastic_helper_db_files_dir, exist_ok=True)
            
            # Copy all FENtastic helper .db files to My_Builds/fentastic_helper_db_files dir for temp location - before wipe
            if os.path.exists(fentastic_helper_db_files_dir):
                for item in os.listdir(fentastic_helper_db_files_dir):
                    if item.endswith(".db"):
                        src_path = os.path.join(fentastic_helper_db_files_dir, item)
                        dst_path = os.path.join(kodi_my_builds_fentastic_helper_db_files_dir, item)
                        shutil.copy2(src_path, dst_path)
                        logging.log(f"[Install/Wipe] Copying FENtastic helper .db file {item} to {dst_path}")

            ######################################################################################################################
            
            # FENtastic skin XMLs files directory Path
            fentastic_skin_xmls_files_dir = os.path.join(os.path.abspath(CONFIG.ADDONS), 'skin.fentastic', 'xml')
            logging.log(f"[Install/Wipe] FENtastic skin XMLs files SRC: {fentastic_skin_xmls_files_dir}")

            # My_Builds/fentastic_skin_xmls_files directory Path
            kodi_my_builds_fentastic_skin_xmls_files_dir = os.path.join(os.path.abspath(CONFIG.HOME), 'My_Builds', 'fentastic_skin_xmls_files')
            logging.log(f"[Install/Wipe] FENtastic skin XMLs files DEST: {kodi_my_builds_fentastic_skin_xmls_files_dir}")

            # Create the destination directory if it does not exist
            os.makedirs(kodi_my_builds_fentastic_skin_xmls_files_dir, exist_ok=True)

            # Copy only .xml files starting with the name "script-fentastic-" to My_Builds/fentastic_skin_xmls_files dir for temp location - before wipe
            if os.path.exists(fentastic_skin_xmls_files_dir):
                for item in os.listdir(fentastic_skin_xmls_files_dir):
                    if item.startswith("script-fentastic-") and item.endswith(".xml"):
                        src_path = os.path.join(fentastic_skin_xmls_files_dir, item)
                        dst_path = os.path.join(kodi_my_builds_fentastic_skin_xmls_files_dir, item)
                        shutil.copy2(src_path, dst_path)
                        logging.log(f"[Install/Wipe] Copying FENtastic skin XML file {item} to {dst_path}")

        else:
            logging.log("[Install/Wipe] BEFORE Wipe - Skipping Saving FENtastic Design data.")

    except Exception as e:
        logging.log(f"[Install/Wipe] BEFORE Wipe - backup_fentasticdata ERROR: {e}")


def restore_fentasticdata():
    try:
        # Verify that FENtastic + Helper addon is installed.
        isFENtasticExists = xbmc.getCondVisibility('System.HasAddon(skin.fentastic)') and xbmc.getCondVisibility('System.HasAddon(script.fentastic.helper)')
        keep_enabled = getattr(CONFIG, 'KEEPFENTASTICDATA', 'false') == 'true'
        logging.log(f"[Install/Wipe] AFTER Wipe - Is KEEPFENTASTICDATA Enabled: {keep_enabled} | isFENtasticExists: {isFENtasticExists}")

        # AFTER WIPE
        if keep_enabled and isFENtasticExists:

            # Helper .db files directory Path
            fentastic_helper_db_files_dir = os.path.join(os.path.abspath(CONFIG.ADDON_DATA), 'script.fentastic.helper')

            # My_Builds/fentastic_helper_db_files directory Path
            kodi_my_builds_fentastic_helper_db_files_dir = os.path.join(os.path.abspath(CONFIG.HOME), 'My_Builds', 'fentastic_helper_db_files')

            if os.path.exists(kodi_my_builds_fentastic_helper_db_files_dir):
                # Create userdata/addons_data/script.fentastic.helper directory (doesn't exist after wipe)
                os.makedirs(fentastic_helper_db_files_dir, exist_ok=True)

                # Move all FENtastic helper .db files from My_Builds/fentastic_helper_db_files to FENtastic helper databases dir
                for item in os.listdir(kodi_my_builds_fentastic_helper_db_files_dir):
                    src_path = os.path.join(kodi_my_builds_fentastic_helper_db_files_dir, item)
                    dst_path = os.path.join(fentastic_helper_db_files_dir, item)
                    shutil.move(src_path, dst_path)
                    logging.log(f"[Install/Wipe] Moving FENtastic Helper {item} file to {dst_path}")

                # Remove empty My_Builds/fentastic_helper_db_files dir after .db files move.
                if not os.listdir(kodi_my_builds_fentastic_helper_db_files_dir):
                    os.rmdir(kodi_my_builds_fentastic_helper_db_files_dir)
                    logging.log(f"[Install/Wipe] Deleting unnecessary {kodi_my_builds_fentastic_helper_db_files_dir} directory.")

            ######################################################################################################################

            # FENtastic skin XMLs files directory Path
            fentastic_skin_xmls_files_dir = os.path.join(os.path.abspath(CONFIG.ADDONS), 'skin.fentastic', 'xml')
            logging.log(f"[Install/Wipe] FENtastic skin XMLs files SRC: {fentastic_skin_xmls_files_dir}")

            # My_Builds/fentastic_skin_xmls_files directory Path
            kodi_my_builds_fentastic_skin_xmls_files_dir = os.path.join(os.path.abspath(CONFIG.HOME), 'My_Builds', 'fentastic_skin_xmls_files')
            logging.log(f"[Install/Wipe] FENtastic skin XMLs files DEST: {kodi_my_builds_fentastic_skin_xmls_files_dir}")

            if os.path.exists(kodi_my_builds_fentastic_skin_xmls_files_dir):
                # Create the destination directory if it does not exist
                os.makedirs(fentastic_skin_xmls_files_dir, exist_ok=True)

                # Move all FENtastic Skin .xml files from My_Builds/fentastic_skin_xmls_files to FENtastic Skin XMLs dir
                for item in os.listdir(kodi_my_builds_fentastic_skin_xmls_files_dir):
                    src_path = os.path.join(kodi_my_builds_fentastic_skin_xmls_files_dir, item)
                    dst_path = os.path.join(fentastic_skin_xmls_files_dir, item)
                    shutil.move(src_path, dst_path)
                    logging.log(f"[Install/Wipe] Moving FENtastic Skin XML file {item} to {dst_path}")

                # Remove empty My_Builds/fentastic_skin_xmls_files dir after .xml files move.
                if not os.listdir(kodi_my_builds_fentastic_skin_xmls_files_dir):
                    os.rmdir(kodi_my_builds_fentastic_skin_xmls_files_dir)
                    logging.log(f"[Install/Wipe] Deleting unnecessary {kodi_my_builds_fentastic_skin_xmls_files_dir} directory.")

        else:
            logging.log("[Install/Wipe] AFTER Wipe - Skipping Saving FENtastic Design data.")

    except Exception as e:
        logging.log(f"[Install/Wipe] AFTER Wipe - restore_fentasticdata ERROR: {e}")


def backup_db_files(addon_id, keep_setting, dest_folder_name):
    """
    Helper function to backup only the 'databases' folder of an addon.
    Prevents backing up the entire addon_data folder to avoid settings.xml conflicts.
    """
    try:
        is_exists = xbmc.getCondVisibility(f'System.HasAddon({addon_id})')
        keep_enabled = getattr(CONFIG, keep_setting, 'false') == 'true'
        logging.log(f"[Install/Wipe] BEFORE Wipe - Is {keep_setting} Enabled: {keep_enabled} | {addon_id} Exists: {is_exists}")

        if keep_enabled and is_exists:
            db_files_dir = os.path.join(os.path.abspath(CONFIG.ADDON_DATA), addon_id, 'databases')
            dest_dir = os.path.join(os.path.abspath(CONFIG.HOME), 'My_Builds', dest_folder_name)

            os.makedirs(dest_dir, exist_ok=True)

            if os.path.exists(db_files_dir):
                for item in os.listdir(db_files_dir):
                    if item.endswith('.db'):
                        src_path = os.path.join(db_files_dir, item)
                        dst_path = os.path.join(dest_dir, item)
                        shutil.copy2(src_path, dst_path)
                        logging.log(f"[Install/Wipe] Copying {addon_id} DB file {item} to {dst_path}")
        else:
            logging.log(f"[Install/Wipe] BEFORE Wipe - Skipping Saving {addon_id} Data.")
    except Exception as e:
        logging.log(f"[Install/Wipe] BEFORE Wipe - backup {addon_id} ERROR: {e}")


def restore_db_files(addon_id, keep_setting, src_folder_name):
    """
    Helper function to restore only the 'databases' folder of an addon.
    """
    try:
        is_exists = xbmc.getCondVisibility(f'System.HasAddon({addon_id})')
        keep_enabled = getattr(CONFIG, keep_setting, 'false') == 'true'

        if keep_enabled and is_exists:
            db_files_dir = os.path.join(os.path.abspath(CONFIG.ADDON_DATA), addon_id, 'databases')
            src_dir = os.path.join(os.path.abspath(CONFIG.HOME), 'My_Builds', src_folder_name)

            if os.path.exists(src_dir):
                os.makedirs(db_files_dir, exist_ok=True)
                for item in os.listdir(src_dir):
                    if item.endswith('.db'):
                        src_path = os.path.join(src_dir, item)
                        dst_path = os.path.join(db_files_dir, item)
                        shutil.move(src_path, dst_path)
                        logging.log(f"[Install/Wipe] Moving {addon_id} DB file {item} to {dst_path}")

                if not os.listdir(src_dir):
                    os.rmdir(src_dir)
                    logging.log(f"[Install/Wipe] Deleting unnecessary {src_dir} directory.")
        else:
            logging.log(f"[Install/Wipe] AFTER Wipe - Skipping Saving {addon_id} Data.")
    except Exception as e:
        logging.log(f"[Install/Wipe] AFTER Wipe - restore {addon_id} ERROR: {e}")


def backup_povdata():
    backup_db_files('plugin.video.pov', 'KEEPPOVDATA', 'pov_db_files')

def restore_povdata():
    restore_db_files('plugin.video.pov', 'KEEPPOVDATA', 'pov_db_files')

def backup_umbrelladata():
    backup_db_files('plugin.video.umbrella', 'KEEPUMBRELLADATA', 'umbrella_db_files')

def restore_umbrelladata():
    restore_db_files('plugin.video.umbrella', 'KEEPUMBRELLADATA', 'umbrella_db_files')


def backup_acctmgrdata():
    """
    Backs up the entire addon_data folder for Account Manager Lite.
    """
    try:
        addon_id = 'script.module.acctmgr'
        is_exists = xbmc.getCondVisibility(f'System.HasAddon({addon_id})')
        keep_enabled = getattr(CONFIG, 'KEEPACCTMGR', 'false') == 'true'
        logging.log(f"[Install/Wipe] BEFORE Wipe - Is KEEPACCTMGR Enabled: {keep_enabled} | {addon_id} Exists: {is_exists}")

        if keep_enabled and is_exists:
            addon_data_dir = os.path.join(os.path.abspath(CONFIG.ADDON_DATA), addon_id)
            dest_dir = os.path.join(os.path.abspath(CONFIG.HOME), 'My_Builds', 'acctmgr_data')

            if os.path.exists(dest_dir):
                shutil.rmtree(dest_dir, ignore_errors=True)

            if os.path.exists(addon_data_dir):
                shutil.copytree(addon_data_dir, dest_dir)
                logging.log(f"[Install/Wipe] Copied entire {addon_id} directory to {dest_dir}")
        else:
            logging.log(f"[Install/Wipe] BEFORE Wipe - Skipping Saving {addon_id} Data.")
    except Exception as e:
        logging.log(f"[Install/Wipe] BEFORE Wipe - backup_acctmgrdata ERROR: {e}")


def restore_acctmgrdata():
    """
    Restores the entire addon_data folder for Account Manager Lite.
    """
    try:
        addon_id = 'script.module.acctmgr'
        is_exists = xbmc.getCondVisibility(f'System.HasAddon({addon_id})')
        keep_enabled = getattr(CONFIG, 'KEEPACCTMGR', 'false') == 'true'

        if keep_enabled and is_exists:
            addon_data_dir = os.path.join(os.path.abspath(CONFIG.ADDON_DATA), addon_id)
            src_dir = os.path.join(os.path.abspath(CONFIG.HOME), 'My_Builds', 'acctmgr_data')

            if os.path.exists(src_dir):
                if os.path.exists(addon_data_dir):
                    shutil.rmtree(addon_data_dir, ignore_errors=True)
                shutil.move(src_dir, addon_data_dir)
                logging.log(f"[Install/Wipe] Moved entire {addon_id} directory back to {addon_data_dir}")
        else:
            logging.log(f"[Install/Wipe] AFTER Wipe - Skipping Saving {addon_id} Data.")
    except Exception as e:
        logging.log(f"[Install/Wipe] AFTER Wipe - restore_acctmgrdata ERROR: {e}")


def wipe():
    from resources.libs import db
    from resources.libs.common import logging
    from resources.libs import skin
    from resources.libs.common import tools
    from resources.libs import update

    # Modern Database Backups
    backup_povdata()
    backup_umbrelladata()
    backup_acctmgrdata()
    backup_fentasticdata()

    exclude_dirs = getattr(CONFIG, 'EXCLUDES', [])
    exclude_dirs.append('My_Builds')

    # Protect ADDONS themselves from being wiped so we don't have to re-download them.
    # Note: this also saves addon_data folder in-place which we explicitly manage for db backups.
    if getattr(CONFIG, 'KEEPACCTMGR', 'false') == 'true':
        exclude_dirs.append('script.module.acctmgr')
    if getattr(CONFIG, 'KEEPPOVDATA', 'false') == 'true':
        exclude_dirs.append('plugin.video.pov')
    if getattr(CONFIG, 'KEEPUMBRELLADATA', 'false') == 'true':
        exclude_dirs.append('plugin.video.umbrella')

    progress_dialog = xbmcgui.DialogProgress()

    skin.skin_to_default('Fresh Install')

    update.addon_updates('set')
    xbmcPath = os.path.abspath(CONFIG.HOME)
    progress_dialog.create(CONFIG.ADDONTITLE, "[COLOR {0}]Calculating files and folders".format(CONFIG.COLOR2) + '\n' + '\n' + 'Please Wait![/COLOR]')
    total_files = sum([len(files) for r, d, files in os.walk(xbmcPath)])
    del_file = 0
    progress_dialog.update(0, "[COLOR {0}]Gathering Excludes list.[/COLOR]".format(CONFIG.COLOR2))

    if getattr(CONFIG, 'KEEPREPOS', 'false') == 'true':
        repos = glob.glob(os.path.join(CONFIG.ADDONS, 'repo*/'))
        for item in repos:
            repofolder = os.path.split(item[:-1])[1]
            if not repofolder == exclude_dirs:
                exclude_dirs.append(repofolder)

    if getattr(CONFIG, 'KEEPSUPER', 'false') == 'true':
        exclude_dirs.append('plugin.program.super.favourites')

    if getattr(CONFIG, 'KEEPWHITELIST', 'false') == 'true':
        from resources.libs import whitelist

        whitelist_list = whitelist.whitelist('read')
        if len(whitelist_list) > 0:
            for item in whitelist_list:
                try:
                    name, id, fold = item
                except:
                    pass

                depends = db.depends_list(fold)
                for plug in depends:
                    if plug not in exclude_dirs:
                        exclude_dirs.append(plug)
                    depends2 = db.depends_list(plug)
                    for plug2 in depends2:
                        if plug2 not in exclude_dirs:
                            exclude_dirs.append(plug2)
                if fold not in exclude_dirs:
                    exclude_dirs.append(fold)

    for item in getattr(CONFIG, 'DEPENDENCIES', []):
        exclude_dirs.append(item)

    progress_dialog.update(0, "[COLOR {0}]Clearing out files and folders:".format(CONFIG.COLOR2))
    latestAddonDB = db.latest_db('Addons')
    for root, dirs, files in os.walk(xbmcPath, topdown=True):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for name in files:
            del_file += 1
            fold = root.replace('/', '\\').split('\\')
            x = len(fold)-1
            if name == 'sources.xml' and fold[-1] == 'userdata' and getattr(CONFIG, 'KEEPSOURCES', 'false') == 'true':
                logging.log("Keep sources.xml: {0}".format(os.path.join(root, name)))
            elif name == 'favourites.xml' and fold[-1] == 'userdata' and getattr(CONFIG, 'KEEPFAVS', 'false') == 'true':
                logging.log("Keep favourites.xml: {0}".format(os.path.join(root, name)))
            elif name == 'profiles.xml' and fold[-1] == 'userdata' and getattr(CONFIG, 'KEEPPROFILES', 'false') == 'true':
                logging.log("Keep profiles.xml: {0}".format(os.path.join(root, name)))
            elif name == 'playercorefactory.xml' and fold[-1] == 'userdata' and getattr(CONFIG, 'KEEPPLAYERCORE', 'false') == 'true':
                logging.log("Keep playercorefactory.xml: {0}".format(os.path.join(root, name)))
            elif name == 'guisettings.xml' and fold[-1] == 'userdata' and getattr(CONFIG, 'KEEPGUISETTINGS', 'false') == 'true':
                logging.log("Keep guisettings.xml: {0}".format(os.path.join(root, name)))
            elif name == 'advancedsettings.xml' and fold[-1] == 'userdata' and getattr(CONFIG, 'KEEPADVANCED', 'false') == 'true':
                logging.log("Keep advancedsettings.xml: {0}".format(os.path.join(root, name)))
            elif name == 'Addons33.db' and fold[-1] == 'Database' and fold[-2] == 'userdata' and getattr(CONFIG, 'KEEPADDONS33DB', 'false') == 'true':
                logging.log("Keep Addons33.db: {0} - CONFIG.KEEPADDONS33DB is: {1}".format(os.path.join(root, name), getattr(CONFIG, 'KEEPADDONS33DB', 'false')))
            elif name in getattr(CONFIG, 'LOGFILES', []):
                logging.log("Keep Log File: {0}".format(name))
            elif name.endswith('.db'):
                try:
                    if name == latestAddonDB:
                        logging.log("Ignoring {0} on Kodi {1}".format(name, tools.kodi_version()))
                    else:
                        os.remove(os.path.join(root, name))
                except Exception as e:
                    if not name.startswith('Textures13'):
                        logging.log('Failed to delete, Purging DB')
                        logging.log("-> {0}".format(str(e)))
                        db.purge_db_file(os.path.join(root, name))
            else:
                progress_dialog.update(int(tools.percentage(del_file, total_files)), '\n' + '[COLOR {0}]File: [/COLOR][COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR2, CONFIG.COLOR1, name))
                try:
                    os.remove(os.path.join(root, name))
                except Exception as e:
                    logging.log("Error removing {0}".format(os.path.join(root, name)))
                    logging.log("-> / {0}".format(str(e)))
        if progress_dialog.iscanceled():
            progress_dialog.close()
            logging.log_notify(CONFIG.ADDONTITLE,
                               "[COLOR {0}]Fresh Start Cancelled[/COLOR]".format(CONFIG.COLOR2))
            return False

    for root, dirs, files in os.walk(xbmcPath, topdown=True):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for name in dirs:
            progress_dialog.update(100, '\n' + 'Cleaning Up Empty Folder: [COLOR {0}]{1}[/COLOR]'.format(CONFIG.COLOR1, name))
            if name not in ["Database", "userdata", "temp", "addons", "addon_data"]:
                shutil.rmtree(os.path.join(root, name), ignore_errors=True, onerror=None)
        if progress_dialog.iscanceled():
            progress_dialog.close()
            logging.log_notify(CONFIG.ADDONTITLE,
                               "[COLOR {0}]Fresh Start Cancelled[/COLOR]".format(CONFIG.COLOR2))
            return False

    progress_dialog.close()
    CONFIG.clear_setting('build')

    # Restore Modern Backups
    restore_povdata()
    restore_umbrelladata()
    restore_acctmgrdata()
    # restore_fentasticdata() - Runs in extract.py instead to overlay on top of new skin extraction


def fresh_start(install=None, over=False):
    from resources.libs.common import logging
    from resources.libs.common import tools

    dialog = xbmcgui.Dialog()

    if over:
        yes_pressed = 1

    elif install == 'restore':
        yes_pressed = dialog.yesno(CONFIG.ADDONTITLE,
                                       "[COLOR {0}]Do you wish to restore your".format(CONFIG.COLOR2)
                                       +'\n'+"Kodi configuration to default settings"
                                       +'\n'+"Before installing the local backup?[/COLOR]",
                                       nolabel='[B][COLOR red]No, Cancel[/COLOR][/B]',
                                       yeslabel='[B][COLOR springgreen]Continue[/COLOR][/B]')
    elif install:
        yes_pressed = dialog.yesno(CONFIG.ADDONTITLE, "[COLOR {0}]Do you wish to restore your".format(CONFIG.COLOR2)
                                       +'\n'+"Kodi configuration to default settings"
                                       +'\n'+"Before installing [COLOR {0}]{1}[/COLOR]?".format(CONFIG.COLOR1, install),
                                       nolabel='[B][COLOR red]No, Cancel[/COLOR][/B]',
                                       yeslabel='[B][COLOR springgreen]Continue[/COLOR][/B]')
    else:
        yes_pressed = dialog.yesno(CONFIG.ADDONTITLE, "[COLOR {0}]Do you wish to restore your".format(CONFIG.COLOR2) +' \n' + "Kodi configuration to default settings?[/COLOR]", nolabel='[B][COLOR red]No, Cancel[/COLOR][/B]', yeslabel='[B][COLOR springgreen]Continue[/COLOR][/B]')

    if yes_pressed:
        wipe()

        if over:
            return True
        elif install == 'restore':
            return True
        elif install:
            from resources.libs.wizard import Wizard
            Wizard().build('normal', install, over=True)
        else:
            dialog.ok(CONFIG.ADDONTITLE, "[COLOR {0}]To save changes you now need to force close Kodi, Press OK to force close Kodi[/COLOR]".format(CONFIG.COLOR2))
            from resources.libs import update
            update.addon_updates('reset')
            tools.kill_kodi(over=True)
    else:
        if not install == 'restore':
            logging.log_notify(CONFIG.ADDONTITLE,
                               '[COLOR {0}]Fresh Install: Cancelled![/COLOR]'.format(CONFIG.COLOR2))
            xbmc.executebuiltin('Container.Refresh()')