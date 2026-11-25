import xbmc, xbmcaddon, xbmcvfs
import os
from pathlib import Path

addon = xbmcaddon.Addon("script.module.acctmgr")
setting = addon.getSetting
joinPath = os.path.join
translatePath = xbmcvfs.translatePath

class Config:
    def __init__(self):
        self.init_meta()
        self.init_vars()
        self.init_paths()
        self.init_settings()

    def init_meta(self):
        self.ADDON_ID = xbmcaddon.Addon().getAddonInfo('id')
        self.ADDON = xbmcaddon.Addon(self.ADDON_ID)
        self.ADDON_NAME = self.ADDON.getAddonInfo('name')
        self.ADDON_VERSION = self.ADDON.getAddonInfo('version')
        self.ADDON_PATH = self.ADDON.getAddonInfo('path')
        self.ADDON_ICON = self.ADDON.getAddonInfo('icon')
        self.ADDON_SEP_ICON = joinPath(joinPath(xbmcaddon.Addon('script.module.acctvwr').getAddonInfo('path'), 'resources', 'icons'), 'separator.png')
        self.ADDON_FANART = self.ADDON.getAddonInfo('fanart')
        self.ICON = self.ADDON.getAddonInfo('icon')

    def init_vars(self):
        self.ADDONTITLE = 'AM Lite'
        self.HIDESPACERS = 'No'
        self.SPACER = '-'
        self.COLOR1 = 'gray'
        self.COLOR2 = 'white'
        self.THEME1 = u'[COLOR {color1}]{{}}[/COLOR]'.format(color1=self.COLOR1)
        self.THEME2 = u'[COLOR {color2}]{{}}[/COLOR]'.format(color2=self.COLOR2)       

    def init_paths(self):
        # Default special paths
        self.XBMC = translatePath('special://xbmc/')
        self.HOME = translatePath('special://home/')
        self.USERDATA = translatePath('special://profile/')
        self.LOGPATH = translatePath('special://logpath/')

        # Constructed paths
        self.ADDONS = joinPath(self.HOME, 'addons')
        self.KODIADDONS = joinPath(self.XBMC, 'addons')
        self.PLUGIN = joinPath(self.ADDONS, self.ADDON_ID)
        self.ADDON_DATA = joinPath(self.USERDATA, 'addon_data')
        self.PLUGIN_DATA = joinPath(self.ADDON_DATA, self.ADDON_ID)
        self.LOGINFOLD = joinPath(self.PLUGIN_DATA, 'login')
        
    def init_settings(self):
        # Logging variables
        self.DEBUGLEVEL = self.get_setting('debuglevel')
        self.KEEPOLDLOG = self.get_setting('oldlog') == 'true'
        self.KEEPCRASHLOG = self.get_setting('crashlog') == 'true'

    def get_setting(self, key, id=xbmcaddon.Addon().getAddonInfo('id')):
        try:
            return xbmcaddon.Addon(id).getSetting(key)
        except:
            return False

    def set_setting(self, key, value, id=xbmcaddon.Addon().getAddonInfo('id')):
        try:
            return xbmcaddon.Addon(id).setSetting(key, value)
        except:
            return False
            
CONFIG = Config()

