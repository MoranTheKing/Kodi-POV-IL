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

import os
import re

from resources.libs.common.config import CONFIG


def wizard_update():
    # KODI-POV-IL - the wizard is updated like any other addon through
    # ModularUpdater (manifest.json); the legacy build.txt self-update is gone.
    # The 'wizardupdate' menu mode now just runs a manifest update check.
    from resources.libs.common import logging
    try:
        from resources.libs.modular_updater import ModularUpdater
        ModularUpdater(background=False).run_update_check()
    except Exception as err:
        logging.log("[Wizard Update] modular update failed: {0}".format(err), level=xbmc.LOGERROR)


def addon_updates(do=None):
    setting = '"general.addonupdates"'
    if do == 'set':
        query = '{{"jsonrpc":"2.0", "method":"Settings.GetSettingValue","params":{{"setting":{0}}}, "id":1}}'.format(setting)
        response = xbmc.executeJSONRPC(query)
        match = re.compile('{"value":(.+?)}').findall(response)
        if len(match) > 0:
            default = match[0]
        else:
            default = 0
        CONFIG.set_setting('default.addonupdate', str(default))
        query = '{{"jsonrpc":"2.0", "method":"Settings.SetSettingValue","params":{{"setting":{0},"value":{1}}}, "id":1}}'.format(setting, '2')
        response = xbmc.executeJSONRPC(query)
    elif do == 'reset':
        try:
            value = int(float(CONFIG.get_setting('default.addonupdate')))
        except:
            value = 0
        if value not in [0, 1, 2]:
            value = 0
        query = '{{"jsonrpc":"2.0", "method":"Settings.SetSettingValue","params":{{"setting":{0},"value":{1}}}, "id":1}}'.format(setting, value)
        response = xbmc.executeJSONRPC(query)
        
        
def toggle_addon_updates():
    from resources.libs.common import logging
    
    setting = '"general.addonupdates"'
    selected = 0
    options = ['Install updates automatically', 'Notify, but don\'t install updates', 'Never check for updates']
    set_query = '{{"jsonrpc":"2.0", "method":"Settings.SetSettingValue","params":{{"setting":"general.addonupdates","value":{0}}}, "id":1}}'
    
    dialog = xbmcgui.Dialog()
    
    selected = dialog.select(CONFIG.ADDONTITLE, options)
            
    logging.log_notify(CONFIG.ADDONTITLE, 'Updates changed to "{0}"'.format(options[selected]))
    xbmc.executeJSONRPC(set_query.format(selected))
