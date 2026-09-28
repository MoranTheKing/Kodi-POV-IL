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
import xbmcvfs

import os

import uservar


class Config:
    def __init__(self):
        self.init_meta()
        self.init_uservars()
        self.init_paths()
        self.init_settings()

    def init_meta(self):
        self.ADDON_ID = xbmcaddon.Addon().getAddonInfo('id')
        self.ADDON = xbmcaddon.Addon(self.ADDON_ID)
        self.ADDON_NAME = self.ADDON.getAddonInfo('name')
        self.ADDON_VERSION = self.ADDON.getAddonInfo('version')
        self.ADDON_PATH = self.ADDON.getAddonInfo('path')
        self.ADDON_ICON = self.ADDON.getAddonInfo('icon')
        self.ADDON_FANART = self.ADDON.getAddonInfo('fanart')
        self.KODIV = float(xbmc.getInfoLabel("System.BuildVersion")[:4])
        self.RAM = int(xbmc.getInfoLabel("System.Memory(total)")[:-2])

    def init_uservars(self):
        # User Edit Variables
        self.ADDONTITLE = getattr(uservar, 'ADDONTITLE', 'Kodi-POV-IL Wizard')
        self.BUILDERNAME = getattr(uservar, 'BUILDERNAME', 'Kodi-POV-IL')
        self.BUILDNAME_DEFAULT = getattr(uservar, 'BUILDNAME_DEFAULT', 'Kodi-POV-IL')
        self.BUILDVERSION_DEFAULT = getattr(uservar, 'BUILDVERSION_DEFAULT', '1.0.0')
        self.EXCLUDES = getattr(uservar, 'EXCLUDES', [])
        self.UPDATECHECK = getattr(uservar, 'UPDATECHECK', 0)

        self.ADDONFILE = getattr(uservar, 'ADDONFILE', '')
        self.ADVANCEDFILE = getattr(uservar, 'ADVANCEDFILE', '')

        # Theming Menu Items
        icon_builds = getattr(uservar, 'ICONBUILDS', self.ADDON_ICON)
        self.ICONBUILDS = icon_builds if not icon_builds.endswith('://') else self.ADDON_ICON

        icon_maint = getattr(uservar, 'ICONMAINT', self.ADDON_ICON)
        self.ICONMAINT = icon_maint if not icon_maint.endswith('://') else self.ADDON_ICON

        icon_speed = getattr(uservar, 'ICONSPEED', self.ADDON_ICON)
        self.ICONSPEED = icon_speed if not icon_speed.endswith('://') else self.ADDON_ICON

        icon_addons = getattr(uservar, 'ICONADDONS', self.ADDON_ICON)
        self.ICONADDONS = icon_addons if not icon_addons.endswith('://') else self.ADDON_ICON

        icon_save = getattr(uservar, 'ICONSAVE', self.ADDON_ICON)
        self.ICONSAVE = icon_save if not icon_save.endswith('://') else self.ADDON_ICON

        icon_acctmgr = getattr(uservar, 'ICONACCTMGR', getattr(uservar, 'ICONREAL', self.ADDON_ICON))
        self.ICONACCTMGR = icon_acctmgr if not icon_acctmgr.endswith('://') else self.ADDON_ICON

        icon_contact = getattr(uservar, 'ICONCONTACT', self.ADDON_ICON)
        self.ICONCONTACT = icon_contact if not icon_contact.endswith('://') else self.ADDON_ICON

        icon_settings = getattr(uservar, 'ICONSETTINGS', self.ADDON_ICON)
        self.ICONSETTINGS = icon_settings if not icon_settings.endswith('://') else self.ADDON_ICON

        self.HIDESPACERS = getattr(uservar, 'HIDESPACERS', 'No')
        self.SPACER = getattr(uservar, 'SPACER', 'None')
        self.COLOR1 = getattr(uservar, 'COLOR1', 'gold')
        self.COLOR2 = getattr(uservar, 'COLOR2', 'white')
        self.THEME1 = getattr(uservar, 'THEME1', '')
        self.THEME2 = getattr(uservar, 'THEME2', '')
        self.THEME3 = getattr(uservar, 'THEME3', '')
        self.THEME_LIMEGREEN = getattr(uservar, 'THEME_LIMEGREEN', '')
        self.THEME_YELLOW = getattr(uservar, 'THEME_YELLOW', '')
        self.THEME4 = getattr(uservar, 'THEME4', '')
        self.THEME5 = getattr(uservar, 'THEME5', '')
        self.THEME6 = getattr(uservar, 'THEME6', '')
        self.HIDECONTACT = getattr(uservar, 'HIDECONTACT', 'No')
        self.CONTACT = getattr(uservar, 'CONTACT', '')

        contact_icon = getattr(uservar, 'CONTACTICON', self.ADDON_ICON)
        self.CONTACTICON = contact_icon if not contact_icon.endswith('://') else self.ADDON_ICON

        contact_fanart = getattr(uservar, 'CONTACTFANART', self.ADDON_FANART)
        self.CONTACTFANART = contact_fanart if not contact_fanart.endswith('://') else self.ADDON_FANART

        # Auto Update For Those With No Repo
        self.AUTOUPDATE = getattr(uservar, 'AUTOUPDATE', 'No')

        # Auto Install Repo If Not Installed
        self.AUTOINSTALL = getattr(uservar, 'AUTOINSTALL', 'No')
        self.REPOID = getattr(uservar, 'REPOID', '')
        self.REPOADDONXML = getattr(uservar, 'REPOADDONXML', '')
        self.REPOZIPURL = getattr(uservar, 'REPOZIPURL', '')

        # Notification Window
        self.ENABLE_NOTIFICATION = getattr(uservar, 'ENABLE', 'No')
        self.NOTIFICATION = getattr(uservar, 'NOTIFICATION', '')
        
        #########################################################################################################
        # KODI-RD-IL - BUILD SKIN SWITCH
        self.BUILD_SKIN_SWITCH_IMAGE_URL = getattr(uservar, 'BUILD_SKIN_SWITCH_IMAGE_URL', '')
        # KODI-POV-IL - MODULAR UPDATER (manifest-based). getattr keeps an old
        # uservar.py (without MANIFEST_URL) from crashing config init.
        self.MANIFEST_URL = getattr(uservar, 'MANIFEST_URL', 'http://')
        #########################################################################################################
        
        self.HEADERTYPE = getattr(uservar, 'HEADERTYPE', 'Text')
        self.FONTHEADER = getattr(uservar, 'FONTHEADER', 'Font14')
        self.HEADERMESSAGE = getattr(uservar, 'HEADERMESSAGE', '')
        self.HEADERIMAGE = getattr(uservar, 'HEADERIMAGE', '')
        self.FONTSETTINGS = getattr(uservar, 'FONTSETTINGS', 'Font13')
        self.BACKGROUND = getattr(uservar, 'BACKGROUND', '')
        self.BACKGROUND = self.BACKGROUND if not self.BACKGROUND == '' else self.ADDON_FANART

    def init_paths(self):
        # Static variables
        self.CLEANFREQ = ['Every Startup', 'Every Day', 'Every Three Days',
                          'Weekly', 'Monthly']
        self.LOGFILES = ['log', 'xbmc.old.log', 'kodi.log', 'kodi.old.log']
        self.DEFAULTPLUGINS = ['metadata.album.universal',
                               'metadata.artists.universal',
                               'metadata.common.fanart.tv',
                               'metadata.common.imdb.com',
                               'metadata.common.musicbrainz.org',
                               'metadata.themoviedb.org',
                               'metadata.tvdb.com',
                               'service.xbmc.versioncheck']
        self.USER_AGENT = ('Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36'
                           ' (KHTML, like Gecko) Chrome/35.0.1916.153 Safari'
                           '/537.36 SE 2.X MetaSr 1.0')
        self.DB_FILES = ['Addons', 'ADSP', 'Epg', 'MyMusic', 'MyVideos',
                         'Textures', 'TV', 'ViewModes']
        self.EXCLUDE_FILES = ['onechannelcache.db', 'saltscache.db',
                              'saltscache.db-shm', 'saltscache.db-wal',
                              'saltshd.lite.db', 'saltshd.lite.db-shm',
                              'saltshd.lite.db-wal', 'queue.db',
                              'commoncache.db', 'access.log', 'trakt.db',
                              'video_cache.db', '.gitignore', '.DS_Store',
                              'Textures13.db', 'Thumbs.db']
        self.XMLS = ['advancedsettings.xml', 'sources.xml', 'favourites.xml',
                     'profiles.xml', 'playercorefactory.xml', 'guisettings.xml']

        self.DEPENDENCIES = [
            'script.module.bottle', 'script.module.certifi',
                             'script.module.chardet', 'script.module.idna',
                             'script.module.requests', 'script.module.six',
            'script.module.urllib3'
        ]

        # Default special paths
        self.XBMC = xbmcvfs.translatePath('special://xbmc/')
        self.HOME = xbmcvfs.translatePath('special://home/')
        self.TEMP = xbmcvfs.translatePath('special://temp/')
        self.MASTERPROFILE = xbmcvfs.translatePath('special://masterprofile/')
        self.PROFILE = xbmcvfs.translatePath('special://profile/')
        self.SUBTITLES = xbmcvfs.translatePath('special://subtitles/')
        self.USERDATA = xbmcvfs.translatePath('special://userdata/')
        self.DATABASE = xbmcvfs.translatePath('special://database/')
        self.THUMBNAILS = xbmcvfs.translatePath('special://thumbnails/')
        self.RECORDINGS = xbmcvfs.translatePath('special://recordings/')
        self.SCREENSHOTS = xbmcvfs.translatePath('special://screenshots/')
        self.MUSICPLAYLISTS = xbmcvfs.translatePath('special://musicplaylists/')
        self.VIDEOPLAYLISTS = xbmcvfs.translatePath('special://videoplaylists/')
        self.CDRIPS = xbmcvfs.translatePath('special://cdrips/')
        self.SKIN = xbmcvfs.translatePath('special://skin/')
        self.LOGPATH = xbmcvfs.translatePath('special://logpath/')

        # Constructed paths
        self.ADDONS = os.path.join(self.HOME, 'addons')
        self.KODIADDONS = os.path.join(self.XBMC, 'addons')
        self.PLUGIN = os.path.join(self.ADDONS, self.ADDON_ID)
        self.PACKAGES = os.path.join(self.ADDONS, 'packages')
        self.ADDON_DATA = os.path.join(self.USERDATA, 'addon_data')
        self.PLUGIN_DATA = os.path.join(self.ADDON_DATA, self.ADDON_ID)
        self.ARCHIVE_CACHE = os.path.join(self.TEMP, 'archive_cache')
        self.ART = os.path.join(self.PLUGIN, 'resources', 'art')
        self.CUSTOM_ART = os.path.join(self.PLUGIN, 'resources', 'kodi_rd_israel_art')

        # Target addon_data paths for selective preservation
        self.ACCTMGR_DATA = os.path.join(self.ADDON_DATA, 'script.module.acctmgr')
        self.POV_DATA = os.path.join(self.ADDON_DATA, 'plugin.video.pov')
        self.UMBRELLA_DATA = os.path.join(self.ADDON_DATA, 'plugin.video.umbrella')
        self.FENTASTIC_HELPER_DATA = os.path.join(self.ADDON_DATA, 'script.fentastic.helper')

        # File paths
        self.ADVANCED = os.path.join(self.USERDATA, 'advancedsettings.xml')
        self.SOURCES = os.path.join(self.USERDATA, 'sources.xml')
        self.GUISETTINGS = os.path.join(self.USERDATA, 'guisettings.xml')
        self.FAVOURITES = os.path.join(self.USERDATA, 'favourites.xml')
        self.PROFILES = os.path.join(self.USERDATA, 'profiles.xml')
        self.WIZLOG = os.path.join(self.PLUGIN_DATA, 'wizard.log')
        self.WHITELIST = os.path.join(self.PLUGIN_DATA, 'whitelist.txt')
        
        self.EXCLUDE_DIRS = [self.ADDON_PATH,
                             os.path.join(self.HOME, 'cache'),
                             os.path.join(self.HOME, 'system'),
                             os.path.join(self.HOME, 'temp'),
                             os.path.join(self.HOME, 'My_Builds'),
                             os.path.join(self.HOME, 'cdm'),
                             os.path.join(self.ADDONS, 'temp'),
                             os.path.join(self.ADDONS, 'packages'),
                             os.path.join(self.ADDONS, 'archive_cache'),
                             os.path.join(self.USERDATA, 'Thumbnails'),
                             os.path.join(self.USERDATA, 'peripheral_data'),
                             os.path.join(self.USERDATA, 'library')]

    def init_settings(self):
        self.FIRSTRUN = self.get_setting('first_install')

        # Build variables
        self.BUILDNAME = self.get_setting('buildname')
        self.BUILDCHECK = self.get_setting('nextbuildcheck')
        self.DEFAULTSKIN = self.get_setting('defaultskin')
        self.DEFAULTNAME = self.get_setting('defaultskinname')
        self.DEFAULTIGNORE = self.get_setting('defaultskinignore')
        self.BUILDVERSION = self.get_setting('buildversion')
        self.BUILDTHEME = self.get_setting('buildtheme')
        self.BUILDLATEST = self.get_setting('latestversion')
        self.INSTALLED = self.get_setting('installed')
        self.EXTRACT = self.get_setting('extract')
        self.EXTERROR = self.get_setting('errors')
        
        # View variables
        self.SHOW20 = self.get_setting('show20')
        self.SHOW21 = self.get_setting('show21')
        self.SHOWADULT = self.get_setting('adult')
        self.SEPARATE = self.get_setting('separate')
        self.DEVELOPER = self.get_setting('developer')
        
        # Auto-Clean variables
        self.AUTOCLEANUP = self.get_setting('autoclean')
        self.AUTOCACHE = self.get_setting('clearcache')
        self.AUTOPACKAGES = self.get_setting('clearpackages')
        self.AUTOTHUMBS = self.get_setting('clearthumbs')
        self.AUTOFREQ = self.get_setting('autocleanfreq')
        self.AUTOFREQ = int(float(self.AUTOFREQ)) if str(self.AUTOFREQ).isdigit() else 0
        self.AUTONEXTRUN = self.get_setting('nextautocleanup')
        
        # Startup force addon updates
        self.FORCEUPDATEFAST_ONSTARTUP = self.get_setting('forceupdateFAST_on_startup')
        self.FORCEUPDATEFAST_ONSTARTUP_NOTIFY = self.get_setting('forceupdateFAST_on_startup_notify')
        
        # Video Cache variables
        self.INCLUDEVIDEO = self.get_setting('includevideo')
        self.INCLUDEALL = self.get_setting('includeall')
        
        # Notification variables
        self.NOTIFY = self.get_setting('notify')
        self.NOTEID = self.get_setting('noteid')
        self.NOTEDISMISS = self.get_setting('notedismiss')

        # Modern Data Preservation Toggles
        self.KEEPACCTMGR = self.get_setting('keepacctmgr')
        self.KEEPPOVDATA = self.get_setting('keeppovdata')
        self.KEEPUMBRELLADATA = self.get_setting('keepumbrelladata')
        self.KEEPFENTASTICDATA = self.get_setting('keepfentasticdata')

        # Core User Data Toggles
        self.KEEPFAVS = self.get_setting('keepfavourites')
        self.KEEPSOURCES = self.get_setting('keepsources')
        self.KEEPPROFILES = self.get_setting('keepprofiles')
        self.KEEPPLAYERCORE = self.get_setting('keepplayercore')
        self.KEEPADVANCED = self.get_setting('keepadvanced')
        self.KEEPGUISETTINGS = self.get_setting('keepguisettings')
        self.KEEPREPOS = self.get_setting('keeprepos')
        self.KEEPSUPER = self.get_setting('keepsuper')
        self.KEEPWHITELIST = self.get_setting('keepwhitelist')
        self.KEEPADDONS33DB = self.get_setting('keepaddons33db')

        # Backup variables
        backup_path = self.get_setting('path')
        self.BACKUPLOCATION = xbmcvfs.translatePath(backup_path if backup_path else self.HOME)
        self.MYBUILDS = os.path.join(self.BACKUPLOCATION, 'My_Builds')
        self.ACCTMGR_BACKUP = os.path.join(self.MYBUILDS, 'acctmgr_data')

        # Logging variables
        self.DEBUGLEVEL = self.get_setting('debuglevel')
        self.ENABLEWIZLOG = self.get_setting('wizardlog')
        self.CLEANWIZLOG = self.get_setting('autocleanwiz')
        self.CLEANWIZLOGBY = self.get_setting('wizlogcleanby')
        self.CLEANDAYS = self.get_setting('wizlogcleandays')
        self.CLEANSIZE = self.get_setting('wizlogcleansize')
        self.CLEANLINES = self.get_setting('wizlogcleanlines')
        self.MAXWIZSIZE = [100, 200, 300, 400, 500, 1000]
        self.MAXWIZLINES = [100, 200, 300, 400, 500]
        self.MAXWIZDATES = [1, 2, 3, 7]
        self.KEEPOLDLOG = self.get_setting('oldlog') == 'true'
        self.KEEPWIZLOG = self.get_setting('wizlog') == 'true'
        self.KEEPCRASHLOG = self.get_setting('crashlog') == 'true'
        self.LOGEMAIL = self.get_setting('email')
        self.NEXTCLEANDATE = self.get_setting('nextwizcleandate')

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

    def open_settings(self, id=None, cat=None, set=None, activate=False):
        offset = [(100,  200), (-100, -80)]
        if not id:
            id = self.ADDON_ID

        try:
            xbmcaddon.Addon(id).openSettings()
        except:
            import logging
            logging.log('Cannot open settings for {}'.format(id), level=xbmc.LOGERROR)
        
        use = 0 if int(self.KODIV) < 18 else 1

        if cat is not None:
            category_id = cat + offset[use][0]
            xbmc.executebuiltin(f'SetFocus({category_id})')
            if set is not None:
                setting_id = set + offset[use][1]
                xbmc.executebuiltin(f'SetFocus({setting_id})')
                
                if activate:
                    xbmc.executebuiltin(f'SendClick({setting_id})')

    def clear_setting(self, type):
        build = {'buildname': '', 'buildversion': '', 'buildtheme': '',
                 'latestversion': '', 'nextbuildcheck': '2019-01-01 00:00:00'}
        install = {'extract': '', 'errors': '', 'installed': ''}
        default = {'defaultskinignore': 'false', 'defaultskin': '',
                   'defaultskinname': ''}
        lookfeel = ['default.enablerssfeeds', 'default.font', 'default.rssedit',
                    'default.skincolors', 'default.skintheme',
                    'default.skinzoom', 'default.soundskin',
                    'default.startupwindow', 'default.stereostrength']
        if type == 'build':
            for element in build:
                self.set_setting(element, build[element])
            for element in install:
                self.set_setting(element, install[element])
            for element in default:
                self.set_setting(element, default[element])
            for element in lookfeel:
                self.set_setting(element, '')
        elif type == 'default':
            for element in default:
                self.set_setting(element, default[element])
            for element in lookfeel:
                self.set_setting(element, '')
        elif type == 'install':
            for element in install:
                self.set_setting(element, install[element])
        elif type == 'lookfeel':
            for element in lookfeel:
                self.set_setting(element, '')
        else:
            self.set_setting(type, '')


CONFIG = Config()

