import xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs
import os
import sys
import importlib
from urllib.parse import parse_qsl
from resources.libs.common import logging
from resources.libs.gui import menu
from resources.libs import ext_db

#Variables
amgr = 'AM Lite'
execute = xbmc.executebuiltin
joinPath = os.path.join
exists = xbmcvfs.exists
dialog = xbmcgui.Dialog()
translatePath = xbmcvfs.translatePath
acctmgr = xbmcaddon.Addon('script.module.acctmgr')
addons = translatePath('special://home/addons/')
addon_data = translatePath('special://profile/addon_data/')
synclist_file = addon_data + translatePath('script.module.acctmgr/trakt_sync_list.json')

#External Scraper Plugin ID's
coco_plugin_id = 'script.module.cocoscrapers'
gears_plugin_id = 'script.module.gearsscrapers'
mag_plugin_id = 'script.module.magneto'
viper_plugin_id = 'script.module.viperscrapers'

#External Scraper Names (Fen Light/Fen & Forks)
coco_sc_name = 'CocoScrapers Module'
gears_sc_name = 'Gears Scrapers'
mag_sc_name = 'Magneto Module'
viper_sc_name = 'Viper Scrapers'

#External Scraper Names (Umbrella & Forks)
coco_umb_name = 'cocoScrapers'
gears_umb_name = 'gearsscrapers'
mag_umb_name = 'magneto'
viper_umb_name = 'viperscrapers'

#Remake Settings & Trakt Cache Variables
fenlt_name = 'Fen Light'
fenlt_id = 'plugin.video.fenlight'
gears_name = 'The Gears'
gears_id = 'plugin.video.gears'
red_name = 'Red Light'
red_id = 'plugin.video.redlight'

def addonInfo(key):
    return xbmcaddon.Addon('script.module.acctvwr').getAddonInfo(key)

#Icon Variables
icons_path = joinPath(addonInfo('path'), 'resources', 'icons')
amgr_icon  = joinPath(icons_path, 'acctmgr.png')
tk_icon    = joinPath(icons_path, 'trakt.png')
mdb_icon   = joinPath(icons_path, 'mdblist.png')
rd_icon    = joinPath(icons_path, 'realdebrid.png')
pm_icon    = joinPath(icons_path, 'premiumize.png')
ad_icon    = joinPath(icons_path, 'alldebrid.png')
tb_icon    = joinPath(icons_path, 'torbox.png')
ed_icon    = joinPath(icons_path, 'easydebrid.png')
oc_icon    = joinPath(icons_path, 'offcloud.png')
en_icon    = joinPath(icons_path, 'easynews.png')


#AM Lite Service Settings
ACCTMGR_AM = [
    # Trakt
    'trakt.expires', 'trakt.refresh',
    'trakt.token', 'trakt.username',
    # MDBList
    'mdblist.token', 'mdblist.refresh', 'mdblist.expires', 'mdblist.client_id', 
    'mdblist.auth_status', 'mdblist.username', 'mdblist.apikey',
    # Real-Debrid
    'realdebrid.token', 'realdebrid.username', 'realdebrid.secret',
    'realdebrid.refresh', 'realdebrid.client_id',
    # Premiumize
    'premiumize.token', 'premiumize.username', 'premiumize.secret',
    # All-Debrid
    'alldebrid.token', 'alldebrid.username', 'alldebrid.secret',
    # Torbox
    'torbox.token', 'torbox.username', 'torbox.acct_id', 'torbox.auth_status', 'torbox.enabled',
    # EasyDebrid
    'easydebrid.token', 'easydebrid.enabled',
    # OffCloud
    'offcloud.token', 'offcloud.userid', 'offcloud.enabled',
    # Easynews
    'easynews.password', 'easynews.username', 'easynews.enabled',]

#AM Lite Individual Service Settings
ACCTMGR_TK = [
    # Trakt
    'trakt.expires','trakt.refresh',
    'trakt.token', 'trakt.username',]

ACCTMGR_MDB = [
    # MDBList
    'mdblist.token', 'mdblist.refresh', 'mdblist.expires', 'mdblist.client_id',
    'mdblist.auth_status', 'mdblist.username', 'mdblist.apikey',]

ACCTMGR_RD = [
    # Real-Debrid
    'realdebrid.token', 'realdebrid.username', 'realdebrid.secret',
    'realdebrid.refresh', 'realdebrid.client_id',]

ACCTMGR_PM = [
    # Premiumize
    'premiumize.token', 'premiumize.username', 'premiumize.secret',]

ACCTMGR_AD = [
    # All-Debrid
    'alldebrid.token', 'alldebrid.username', 'alldebrid.secret',]

ACCTMGR_TB = [
    # Torbox
    'torbox.token', 'torbox.username', 'torbox.acct_id', 'torbox.auth_status', 'torbox.enabled',]

ACCTMGR_ED = [
    # EasyDebrid
    'easydebrid.token', 'easydebrid.enabled',]

ACCTMGR_OC = [
    # OffCloud
    'offcloud.token', 'offcloud.userid', 'offcloud.enabled',]

ACCTMGR_EN= [
    # Easynews
    'easynews.password', 'easynews.username', 'easynews.enabled',]

#HELPERS
def get_setting(key):
    return acctmgr.getSetting(key)

def set_setting(key, setting):
    return acctmgr.setSetting(key, setting)

def clear_acctmgr_settings(keys):   # Clear AM Lite settings
    try:
        am = xbmcaddon.Addon('script.module.acctmgr')
        for k in keys:
            am.setSetting(k, '')
    except Exception as e:
        xbmc.log(f'{amgr}: Failed to live-clear acctmgr settings: {e}', xbmc.LOGINFO)

def remake_settings(plugin_id, name):   # Fen Light & Forks
    try:
        try:
            add_on = xbmcaddon.Addon(plugin_id)
        except Exception as e:
            xbmc.log(f'{amgr}: {name} not installed, skipping settings remake {e}', xbmc.LOGINFO)
            return

        addon_root = add_on.getAddonInfo('path')
        if addon_root not in sys.path:
            sys.path.append(addon_root)

        lib_path = joinPath(addon_root, 'resources', 'lib')
        if lib_path not in sys.path:
            sys.path.append(lib_path)

        try:
            settings_cache = importlib.import_module('caches.settings_cache')
        except Exception as e:
            xbmc.log(f'{amgr}: {name} settings_cache import failed {e}', xbmc.LOGERROR)
            return

        if not hasattr(settings_cache, 'sync_settings'):
            xbmc.log(f'{amgr}: {name} settings remade', xbmc.LOGINFO)
            return

        settings_cache.sync_settings()
        xbmc.log(f'{amgr}: {name} settings remade', xbmc.LOGINFO)
        
    except Exception as e:
        xbmc.log(f'{amgr}: Failed to remake {name} settings {e}', xbmc.LOGERROR)
        
#ROUTER        
class Router:
    def __init__(self):
        self.route = None
        self.params = {}

    def _log_params(self, paramstring):
        _url = sys.argv[0]

        self.params = dict(parse_qsl(paramstring))

        logstring = '{0}: '.format(_url)
        for param in self.params:
            logstring += '[ {0}: {1} ] '.format(param, self.params[param])

        logging.log(logstring, level=xbmc.LOGDEBUG)

        return self.params

    def dispatch(self, handle, paramstring):
        self._log_params(paramstring)

        mode = self.params['mode'] if 'mode' in self.params else None
        name = self.params['name'] if 'name' in self.params else None
        
        from resources.libs import acct_vwr, extit, jsonit
        
        #VIEW AUTHORIZATION MENUS
        if mode is None:
            self._finish(handle)

        elif mode == 'trakt':
            menu.trakt_menu()   # Open menu
            self._finish(handle)

        elif mode == 'mdblist':
            menu.mdblist_menu()
            self._finish(handle)
            
        elif mode == 'realdebrid':
            menu.debrid_menu()
            self._finish(handle)

        elif mode == 'premiumize':
            menu.premiumize_menu()
            self._finish(handle)

        elif mode == 'alldebrid':
            menu.alldebrid_menu()
            self._finish(handle)

        elif mode == 'torbox':
            menu.torbox_menu()
            self._finish(handle)

        elif mode == 'easydebrid':
            menu.easydebrid_menu()
            self._finish(handle)
            
        elif mode == 'offcloud':
            menu.offcloud_menu()
            self._finish(handle)

        elif mode == 'easynews':
            menu.easynews_menu()
            self._finish(handle)

        elif mode == 'extscrapers':
            menu.ext_menu()
            self._finish(handle)

        #OPEN ADDON SETTINGS
        elif mode == 'opensettings_tk':
            from resources.libs import acct_vwr
            acct_vwr.open_settings(name, service='tk') # Open Trakt provider settings
            xbmc.executebuiltin('Container.Refresh()')

        elif mode == 'opensettings_mdb':
            from resources.libs import acct_vwr
            acct_vwr.open_settings(name, service='mdb')
            xbmc.executebuiltin('Container.Refresh()')
            
        elif mode == 'opensettings_rd':
            from resources.libs import acct_vwr
            acct_vwr.open_settings(name)
            execute('Container.Refresh()')

        elif mode == 'opensettings_pm':
            from resources.libs import acct_vwr
            acct_vwr.open_settings(name)
            execute('Container.Refresh()')

        elif mode == 'opensettings_ad':
            from resources.libs import acct_vwr
            acct_vwr.open_settings(name)
            execute('Container.Refresh()')

        elif mode == 'opensettings_ed':
            from resources.libs import acct_vwr
            acct_vwr.open_settings(name)
            xbmc.executebuiltin('Container.Refresh()')
            
        elif mode == 'opensettings_tb':
            from resources.libs import acct_vwr
            acct_vwr.open_settings(name)
            xbmc.executebuiltin('Container.Refresh()')

        elif mode == 'opensettings_oc':
            from resources.libs import acct_vwr
            acct_vwr.open_settings(name)
            xbmc.executebuiltin('Container.Refresh()')

        elif mode == 'opensettings_en':
            from resources.libs import acct_vwr
            acct_vwr.open_settings(name)
            xbmc.executebuiltin('Container.Refresh()')

        elif mode == 'opensettings_ext':
            from resources.libs import extit
            extit.open_settings(name)
            execute('Container.Refresh()')

        elif mode == 'opensettings_fenlt':
            xbmc.executebuiltin('PlayMedia(plugin://plugin.video.fenlight/?mode=open_settings)')    # Open Fen Light settings
            execute('Container.Refresh()')

        elif mode == 'opensettings_gears':
            xbmc.executebuiltin('PlayMedia(plugin://plugin.video.gears/?mode=open_settings)')       # Open Gears settings
            execute('Container.Refresh()')

        elif mode == 'opensettings_red':
            xbmc.executebuiltin('PlayMedia(plugin://plugin.video.redlight/?mode=open_settings)')    # Open Red Light settings
            execute('Container.Refresh()')
           
        #TRAKT REVOKE
        elif mode == 'clear_tk':                                                                    # Clear All Addon Trakt Data
            acct_vwr.addon_it('wipeaddon', 'all', services=('tk',), force=True)                     # Revoke all add-ons with a settings.xml
            set_setting("api.service", "false")                                                     # Disable Trakt API service
            set_setting("sync.tk.service", "false")                                                 # Disable Trakt Auto-sync service
            clear_acctmgr_settings(ACCTMGR_TK)                                                      # Revoke AM Lite
            dialog.notification('Trakt', 'All Add-ons Revoked!', tk_icon, 3000)
            xbmc.sleep(3000)
            dialog.notification('Trakt', 'Force Closing Kodi!', tk_icon, 3000)
            xbmc.sleep(3000)
            os._exit(1)                                                                             # Force close Kodi

        #MDBLIST REVOKE
        elif mode == 'clear_mdb':                                        
            acct_vwr.addon_it('wipeaddon', 'all', services=('mdb',), force=True)
            set_setting("sync.mdb.service", "false")
            clear_acctmgr_settings(ACCTMGR_MDB)
            
        #REAL-DEBRID REVOKE
        elif mode == 'clear_rd':                                        
            acct_vwr.addon_it('wipeaddon', 'all', services=('rd',), force=True)
            set_setting("sync.rd.service", "false")
            clear_acctmgr_settings(ACCTMGR_RD)
            jsonit.realizer_rvk()    

        #PREMIUMIZE REVOKE
        elif mode == 'clear_pm':                                        
            acct_vwr.addon_it('wipeaddon', 'all', services=('pm',), force=True)
            set_setting("sync.pm.service", "false")
            clear_acctmgr_settings(ACCTMGR_PM)

        #ALL-DEBRID REVOKE
        elif mode == 'clear_ad':                                        
            acct_vwr.addon_it('wipeaddon', 'all', services=('ad',), force=True)
            set_setting("sync.ad.service", "false")
            clear_acctmgr_settings(ACCTMGR_AD)

        #EASY DEBRID REVOKE
        elif mode == 'clear_ed':                                        
            acct_vwr.addon_it('wipeaddon', 'all', services=('ed',), force=True)
            set_setting("sync.ed.service", "false")
            clear_acctmgr_settings(ACCTMGR_ED)
            
        #TORBOX DATA REVOKE
        elif mode == 'clear_tb':                                        
            acct_vwr.addon_it('wipeaddon', 'all', services=('tb',), force=True)
            set_setting("sync.tb.service", "false")
            clear_acctmgr_settings(ACCTMGR_TB)
            
        #OFFCLOUD REVOKE
        elif mode == 'clear_oc':                                        
            acct_vwr.addon_it('wipeaddon', 'all', services=('oc',), force=True)
            set_setting("sync.oc.service", "false")
            clear_acctmgr_settings(ACCTMGR_OC)

        #EASYNEWS REVOKE
        elif mode == 'clear_en':                                        
            acct_vwr.addon_it('wipeaddon', 'all', services=('en',), force=True)
            set_setting("sync.en.service", "false")
            clear_acctmgr_settings(ACCTMGR_EN)

        #EXTERNAL PROVIDERS - CHANGE SCRAPER PACKAGE
        elif mode == 'fenlt_scrapers':  # Fen Light
            fenlt_path = addon_data + translatePath('plugin.video.fenlight/databases/')
            settings_db = fenlt_path + translatePath('settings.db')
            scrapers = [
                ('Coco Scrapers', coco_plugin_id, coco_sc_name, coco_plugin_id),
                ('Gears Scrapers', gears_plugin_id, gears_sc_name, gears_plugin_id),
                ('Magneto Scrapers', mag_plugin_id, mag_sc_name, mag_plugin_id),
                ('Viper Scrapers', viper_plugin_id, viper_sc_name, viper_plugin_id),
            ]

            installed = []
            for label, addon_id, disp_name, module_id in scrapers:
                if xbmc.getCondVisibility(f'System.HasAddon({addon_id})'):
                    installed.append((label, disp_name, module_id))

            if not installed:
                dialog.notification('AM Lite', 'No scraper modules are installed!', icon=amgr_icon)
                raise SystemExit

            labels = [name for name, _, _ in installed]

            selection = dialog.select('Choose scraper package', labels)
            if selection == -1:
                raise SystemExit

            selected_label, selected_disp, selected_module = installed[selection]
            ext_db.auth_ext(selected_disp, selected_module, settings_db)
            execute('Dialog.Close(all,true)')
            xbmc.sleep(200)
            remake_settings(fenlt_id, fenlt_name)  
            xbmc.executebuiltin('Container.Refresh()')

        elif mode == 'gears_scrapers':  # Gears
            gears_path = addon_data + translatePath('plugin.video.gears/databases/')
            settings_db = gears_path + translatePath('settings.db')
            scrapers = [
                ('Coco Scrapers', coco_plugin_id, coco_sc_name, coco_plugin_id),
                ('Gears Scrapers', gears_plugin_id, gears_sc_name, gears_plugin_id),
                ('Magneto Scrapers', mag_plugin_id, mag_sc_name, mag_plugin_id),
                ('Viper Scrapers', viper_plugin_id, viper_sc_name, viper_plugin_id),
            ]

            installed = []
            for label, addon_id, disp_name, module_id in scrapers:
                if xbmc.getCondVisibility(f'System.HasAddon({addon_id})'):
                    installed.append((label, disp_name, module_id))

            if not installed:
                dialog.notification('AM Lite', 'No scraper modules are installed!', icon=amgr_icon)
                raise SystemExit

            labels = [name for name, _, _ in installed]

            selection = dialog.select('Choose scraper package', labels)
            if selection == -1:
                raise SystemExit

            selected_label, selected_disp, selected_module = installed[selection]
            ext_db.auth_ext(selected_disp, selected_module, settings_db)
            execute('Dialog.Close(all,true)')
            xbmc.sleep(200)
            remake_settings(gears_id, gears_name)  
            xbmc.executebuiltin('Container.Refresh()')

        elif mode == 'red_scrapers':  # Red Light
            red_path = addon_data + translatePath('plugin.video.redlight/databases/')
            settings_db = red_path + translatePath('settings.db')
            scrapers = [
                ('Coco Scrapers', coco_plugin_id, coco_sc_name, coco_plugin_id),
                ('Gears Scrapers', gears_plugin_id, gears_sc_name, gears_plugin_id),
                ('Magneto Scrapers', mag_plugin_id, mag_sc_name, mag_plugin_id),
                ('Viper Scrapers', viper_plugin_id, viper_sc_name, viper_plugin_id),
            ]

            installed = []
            for label, addon_id, disp_name, module_id in scrapers:
                if xbmc.getCondVisibility(f'System.HasAddon({addon_id})'):
                    installed.append((label, disp_name, module_id))

            if not installed:
                dialog.notification('AM Lite', 'No scraper modules are installed!', icon=amgr_icon)
                raise SystemExit

            labels = [name for name, _, _ in installed]

            selection = dialog.select('Choose scraper package', labels)
            if selection == -1:
                raise SystemExit

            selected_label, selected_disp, selected_module = installed[selection]
            ext_db.auth_ext(selected_disp, selected_module, settings_db)
            execute('Dialog.Close(all,true)')
            xbmc.sleep(200)
            remake_settings(red_id, red_name)  
            xbmc.executebuiltin('Container.Refresh()')

        elif mode == 'fen_scrapers':    # Fen
            scrapers = [
                ('Coco Scrapers', coco_plugin_id, coco_sc_name, coco_plugin_id),
                #('Gears Scrapers', gears_plugin_id, gears_sc_name, gears_plugin_id),
                #('Magneto Scrapers', mag_plugin_id, mag_sc_name, mag_plugin_id),
                ('Viper Scrapers', viper_plugin_id, viper_sc_name, viper_plugin_id),
            ]

            installed = []
            for name, addon_id, disp_name, module_id in scrapers:
                if xbmc.getCondVisibility(f'System.HasAddon({addon_id})'):
                    installed.append((name, addon_id, disp_name, module_id))

            if not installed:
                dialog.notification('AM Lite', 'No scraper modules are installed!', icon=amgr_icon)
                raise SystemExit

            labels = [name for name, _, _, _ in installed]

            selection = dialog.select('Choose scraper package', labels)
            if selection == -1:
                raise SystemExit

            selected_name, selected_id, display_name, module_id = installed[selection]

            addon = xbmcaddon.Addon("plugin.video.fen")
            for k, v in {
                "provider.external": "true",
                "external_scraper.name": display_name,
                "external_scraper.module": module_id,
            }.items():
                addon.setSetting(k, v)
            xbmc.executebuiltin('Container.Refresh()')

        elif mode == 'umb_scrapers':    # Umbrella
            scrapers = [
                ('Coco Scrapers', coco_plugin_id, coco_umb_name, coco_plugin_id),
                ('Gears Scrapers', gears_plugin_id, gears_umb_name, gears_plugin_id),
                ('Magneto Scrapers', mag_plugin_id, mag_umb_name, mag_plugin_id),
                ('Viper Scrapers', viper_plugin_id, viper_umb_name, viper_plugin_id),
            ]

            installed = []
            for name, addon_id, prov_name, module_id in scrapers:
                if xbmc.getCondVisibility(f'System.HasAddon({addon_id})'):
                    installed.append((name, addon_id, prov_name, module_id))

            if not installed:
                dialog.notification('AM Lite', 'No scraper modules are installed!', icon=amgr_icon)
                raise SystemExit

            labels = [name for name, _, _, _ in installed]

            selection = dialog.select('Choose scraper package', labels)
            if selection == -1:
                raise SystemExit

            selected_name, selected_id, provider_name, module_id = installed[selection]

            addon = xbmcaddon.Addon("plugin.video.umbrella")
            for k, v in {
                "provider.external.enabled": "true",
                "umbrella.externalWarning": "true",
                "external_provider.name": provider_name,
                "external_provider.module": module_id,
            }.items():
                addon.setSetting(k, v)
            xbmc.executebuiltin('Container.Refresh()')
                 
        #REVOKE ALL SERVICES
        elif mode == 'wipeclean':   # Revoke all services and restore default add-on settings
            #Revoke MDBList
            try:
                if get_setting("mdblist.apikey") not in (None, ""):
                    acct_vwr.addon_it('wipeaddon', 'all', services=('mdb',), force=True)
                    xbmc.sleep(500)
                    set_setting("sync.mdb.service", "false")
                    dialog.notification('MDBList', 'MDBList Revoked!', mdb_icon, 3000)
                    xbmc.sleep(1000)
            except Exception as e:
                xbmc.log(f'{amgr}: Wipeclean MDBList failed: {e}', xbmc.LOGERROR)

            #Revoke Real-Debrid
            try:
                if get_setting("realdebrid.token") not in (None, ""):
                    acct_vwr.addon_it('wipeaddon', 'all', services=('rd',), force=True)
                    xbmc.sleep(500)
                    set_setting("sync.rd.service", "false")
                    jsonit.realizer_rvk()
                    dialog.notification('Real-Debrid', 'Real-Debrid Revoked!', rd_icon, 3000)
                    xbmc.sleep(1000)
            except Exception as e:
                xbmc.log(f'{amgr}: Wipeclean Real-Debrid failed: {e}', xbmc.LOGERROR)

            #Revoke Premiumize
            try:
                if get_setting("premiumize.token") not in (None, ""):
                    acct_vwr.addon_it('wipeaddon', 'all', services=('pm',), force=True)
                    xbmc.sleep(500)
                    set_setting("sync.pm.service", "false")
                    dialog.notification('Premiumize', 'Premiumize Revoked!', pm_icon, 3000)
                    xbmc.sleep(1000)
            except Exception as e:
                xbmc.log(f'{amgr}: Wipeclean Premiumize failed: {e}', xbmc.LOGERROR)

            #Revoke All-Debrid
            try:
                if get_setting("alldebrid.token") not in (None, ""):
                    acct_vwr.addon_it('wipeaddon', 'all', services=('ad',), force=True)
                    xbmc.sleep(500)
                    set_setting("sync.ad.service", "false")
                    dialog.notification('All-Debrid', 'All-Debrid Revoked!', ad_icon, 3000)
                    xbmc.sleep(1000)
            except Exception as e:
                xbmc.log(f'{amgr}: Wipeclean All-Debrid failed: {e}', xbmc.LOGERROR)

            #Revoke Easy Debrid
            try:
                if get_setting("easydebrid.token") not in (None, ""):
                    acct_vwr.addon_it('wipeaddon', 'all', services=('ed',), force=True)
                    xbmc.sleep(500)
                    for k, v in {
                        "sync.ed.service": "false",
                        "easydebrid.enabled": "false"
                    }.items():
                        acctmgr.setSetting(k, v)
                    dialog.notification('EasyDebrid', 'Easydebrid Revoked!', ed_icon, 3000)
                    xbmc.sleep(1000)
            except Exception as e:
                xbmc.log(f'{amgr}: Wipeclean EasyDebrid failed: {e}', xbmc.LOGERROR)

            #Revoke TorBox
            try:
                if get_setting("torbox.token") not in (None, ""):
                    acct_vwr.addon_it('wipeaddon', 'all', services=('tb',), force=True)
                    xbmc.sleep(500)
                    for k, v in {
                        "sync.tb.service": "false",
                        "torbox.enabled": "false"
                    }.items():
                        acctmgr.setSetting(k, v)
                    dialog.notification('TorBox', 'Torbox Revoked!', tb_icon, 3000)
                    xbmc.sleep(1000)
            except Exception as e:
                xbmc.log(f'{amgr}: Wipeclean TorBox failed: {e}', xbmc.LOGERROR)

            #Revoke OffCloud
            try:
                if get_setting("offcloud.token") not in (None, ""):
                    acct_vwr.addon_it('wipeaddon', 'all', services=('oc',), force=True)
                    xbmc.sleep(500)
                    for k, v in {
                        "sync.oc.service": "false",
                        "offcloud.enabled": "false"
                    }.items():
                        acctmgr.setSetting(k, v)
                    dialog.notification('OffCloud', 'Offcloud Revoked!', oc_icon, 3000)
                    xbmc.sleep(1000)
            except Exception as e:
                xbmc.log(f'{amgr}: Wipeclean OffCloud failed: {e}', xbmc.LOGERROR)

            #Revoke Easynews
            try:
                if (get_setting("easynews.username") not in (None, "") and
                    get_setting("easynews.password") not in (None, "")):
                    acct_vwr.addon_it('wipeaddon', 'all', services=('en',), force=True)
                    xbmc.sleep(500)
                    for k, v in {
                        "sync.en.service": "false",
                        "easynews.enabled": "false"
                    }.items():
                        acctmgr.setSetting(k, v)
                    dialog.notification('EasyNews', 'Easynews Revoked!', en_icon, 3000)
                    xbmc.sleep(1000)
            except Exception as e:
                xbmc.log(f'{amgr}: Wipeclean Easynews failed: {e}', xbmc.LOGERROR)

            #Revoke Trakt
            if get_setting("trakt.token"):                                              # Check if Trakt is authorized
                acct_vwr.addon_it('wipeaddon', 'all', services=('tk',), force=True)     # Revoke all add-ons with a settings.xml
                set_setting("api.service", "false")                                     # Disable Trakt API service
                set_setting("sync.tk.service", "false")                                 # Disable Trakt Auto-sync service
                xbmc.sleep(200)
                clear_acctmgr_settings(ACCTMGR_AM)                                      # Revoke AM Lite
                dialog.notification('Trakt', 'Trakt Revoked!', tk_icon, 3000)
                xbmc.sleep(1500)
                dialog.notification('Trakt', 'Force Closing Kodi!', tk_icon, 3000)
                xbmc.sleep(3000)
                os._exit(1) 
            else:
                clear_acctmgr_settings(ACCTMGR_AM)
                dialog.notification('AM Lite', 'All Data Cleared!', amgr_icon, 3000)

    def _finish(self, handle):
        from resources.libs.common import directory
        directory.set_view()
        xbmcplugin.setContent(handle, 'files')
        xbmcplugin.endOfDirectory(handle, succeeded=True, updateListing=True, cacheToDisc=False)
