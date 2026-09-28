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
import xbmcvfs

import os
import shutil
import zipfile

from resources.libs.common.config import CONFIG
from resources.libs.common import logging
from resources.libs.common import tools


def _copy_folder_contents(src, dst, overwrite, dialog):
    """Helper method to recursively copy folder contents while checking for overwrites."""
    if not os.path.exists(dst):
        os.makedirs(dst)
    files = os.listdir(src)
    for item in files:
        src_file = os.path.join(src, item)
        dst_file = os.path.join(dst, item)
        
        if os.path.isfile(src_file):
            if os.path.exists(dst_file):
                if overwrite == 1:
                    os.remove(dst_file)
                else:
                    if not dialog.yesno(CONFIG.ADDONTITLE,
                                        f"[COLOR {CONFIG.COLOR2}]Would you like to replace the current [COLOR {CONFIG.COLOR1}]{item}[/COLOR] file?[/COLOR]",
                                        yeslabel="[B][COLOR springgreen]Yes Replace[/COLOR][/B]",
                                        nolabel="[B][COLOR red]No Skip[/COLOR][/B]"):
                        continue
                    else:
                        os.remove(dst_file)
            shutil.copy(src_file, dst_file)
        elif os.path.isdir(src_file):
            _copy_folder_contents(src_file, dst_file, overwrite, dialog)


def import_save_data():
    dialog = xbmcgui.Dialog()

    TEMP = os.path.join(CONFIG.PLUGIN_DATA, 'temp')
    if not os.path.exists(TEMP):
        os.makedirs(TEMP)
        
    source = dialog.browse(1, f'[COLOR {CONFIG.COLOR2}]Select the location of the SaveData.zip[/COLOR]',
                           'files', '.zip', False, False, CONFIG.HOME)
                           
    if not source or not source.endswith('.zip'):
        logging.log_notify(CONFIG.ADDONTITLE, f"[COLOR {CONFIG.COLOR2}]Import Data Error/Cancelled![/COLOR]")
        return
        
    source = xbmcvfs.translatePath(source)
    tempfile = xbmcvfs.translatePath(os.path.join(CONFIG.MYBUILDS, 'SaveData.zip'))
    
    if not tempfile == source:
        xbmcvfs.copy(source, tempfile)

    from resources.libs import extract
    if not extract.all(xbmcvfs.translatePath(tempfile), TEMP):
        logging.log("Error trying to extract the zip file!")
        logging.log_notify(CONFIG.ADDONTITLE, f"[COLOR {CONFIG.COLOR2}]Import Data Error![/COLOR]")
        return

    acctmgr = os.path.join(TEMP, 'acctmgr')
    pov = os.path.join(TEMP, 'pov')
    umbrella = os.path.join(TEMP, 'umbrella')
    fentastic = os.path.join(TEMP, 'fentastic')
    xmls = os.path.join(TEMP, 'xmls')
    databases = os.path.join(TEMP, 'databases')

    x = 0
    overwrite = dialog.yesno(CONFIG.ADDONTITLE,
                             f"[COLOR {CONFIG.COLOR2}]Would you rather we overwrite all Save Data files or ask you for each file being imported?[/COLOR]",
                             yeslabel="[B][COLOR springgreen]Overwrite All[/COLOR][/B]",
                             nolabel="[B][COLOR red]No Ask[/COLOR][/B]")
    
    if os.path.exists(acctmgr):
        x += 1
        _copy_folder_contents(acctmgr, os.path.join(CONFIG.ADDON_DATA, 'script.module.acctmgr'), overwrite, dialog)
        
    if os.path.exists(pov):
        x += 1
        _copy_folder_contents(pov, os.path.join(CONFIG.ADDON_DATA, 'plugin.video.pov', 'databases'), overwrite, dialog)

    if os.path.exists(umbrella):
        x += 1
        _copy_folder_contents(umbrella, os.path.join(CONFIG.ADDON_DATA, 'plugin.video.umbrella', 'databases'), overwrite, dialog)
        
    if os.path.exists(fentastic):
        x += 1
        _copy_folder_contents(fentastic, os.path.join(CONFIG.ADDON_DATA, 'script.fentastic.helper'), overwrite, dialog)

    if os.path.exists(xmls):
        x += 1
        _copy_folder_contents(xmls, CONFIG.USERDATA, overwrite, dialog)
        
    if os.path.exists(databases):
        x += 1
        _copy_folder_contents(databases, os.path.join(CONFIG.USERDATA, 'Database'), overwrite, dialog)

    # Clean Up
    tools.clean_house(TEMP)
    tools.remove_folder(TEMP)
    
    if not tempfile == source:
        xbmcvfs.delete(tempfile)
        
    if x == 0:
        logging.log_notify(CONFIG.ADDONTITLE, f"[COLOR {CONFIG.COLOR2}]Save Data Import Failed (No data found)[/COLOR]")
    else:
        logging.log_notify(CONFIG.ADDONTITLE, f"[COLOR {CONFIG.COLOR2}]Save Data Import Complete[/COLOR]")


def _add_folder_to_zip(zipf, source_path, zip_path_prefix):
    """Helper method to recursively add a folder to the zip structure."""
    if os.path.exists(source_path):
        for base, dirs, files in os.walk(source_path):
            for file in files:
                fn = os.path.join(base, file)
                rel_path = os.path.relpath(fn, source_path)
                zipf.write(fn, os.path.join(zip_path_prefix, rel_path), zipfile.ZIP_DEFLATED)


def export_save_data():
    dialog = xbmcgui.Dialog()

    source = dialog.browse(3, f'[COLOR {CONFIG.COLOR2}]Select where you wish to export the SaveData zip?[/COLOR]',
                           'files', '', False, True, CONFIG.HOME)
    if not source:
        return
        
    source = xbmcvfs.translatePath(source)
    tempzip = os.path.join(source, 'SaveData.zip')
    
    zipf = zipfile.ZipFile(tempzip, mode='w', allowZip64=True)
    
    # Account Manager Lite
    if getattr(CONFIG, 'KEEPACCTMGR', 'false') == 'true':
        _add_folder_to_zip(zipf, os.path.join(CONFIG.ADDON_DATA, 'script.module.acctmgr'), 'acctmgr')
        
    # POV Databases
    if getattr(CONFIG, 'KEEPPOVDATA', 'false') == 'true':
        _add_folder_to_zip(zipf, os.path.join(CONFIG.ADDON_DATA, 'plugin.video.pov', 'databases'), 'pov')
        
    # Umbrella Databases
    if getattr(CONFIG, 'KEEPUMBRELLADATA', 'false') == 'true':
        _add_folder_to_zip(zipf, os.path.join(CONFIG.ADDON_DATA, 'plugin.video.umbrella', 'databases'), 'umbrella')
        
    # FENtastic Helper Databases
    if getattr(CONFIG, 'KEEPFENTASTICDATA', 'false') == 'true':
        _add_folder_to_zip(zipf, os.path.join(CONFIG.ADDON_DATA, 'script.fentastic.helper'), 'fentastic')
        
    # Kodi Core XMLs
    xml_map = {
        'advancedsettings.xml': getattr(CONFIG, 'KEEPADVANCED', 'false'),
        'sources.xml': getattr(CONFIG, 'KEEPSOURCES', 'false'),
        'favourites.xml': getattr(CONFIG, 'KEEPFAVS', 'false'),
        'profiles.xml': getattr(CONFIG, 'KEEPPROFILES', 'false'),
        'playercorefactory.xml': getattr(CONFIG, 'KEEPPLAYERCORE', 'false'),
        'guisettings.xml': getattr(CONFIG, 'KEEPGUISETTINGS', 'false')
    }
    
    for item, keep in xml_map.items():
        if keep == 'true':
            file_path = os.path.join(CONFIG.USERDATA, item)
            if os.path.exists(file_path):
                zipf.write(file_path, os.path.join('xmls', item), zipfile.ZIP_DEFLATED)
                
    # Addons33.db
    if getattr(CONFIG, 'KEEPADDONS33DB', 'false') == 'true':
        file_path = os.path.join(CONFIG.USERDATA, 'Database', 'Addons33.db')
        if os.path.exists(file_path):
            zipf.write(file_path, os.path.join('databases', 'Addons33.db'), zipfile.ZIP_DEFLATED)

    zipf.close()
    
    dialog.ok(CONFIG.ADDONTITLE,
              f"[COLOR {CONFIG.COLOR2}]Save data has been backed up to:[/COLOR]"
              f"\n[COLOR {CONFIG.COLOR1}]{tempzip}[/COLOR]")
