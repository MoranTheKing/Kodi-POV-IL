import xbmc, xbmcaddon, xbmcvfs
import os
import sqlite3

from sqlite3 import Error
from xml.etree import ElementTree
from resources.libs.common.config import CONFIG
from resources.libs.common import logging

#Variables
amgr = 'AM Lite ERROR'
translatePath = xbmcvfs.translatePath

# Database Paths
fenlt_settings_db = translatePath('special://profile/addon_data/plugin.video.fenlight/databases/settings.db')
gears_settings_db = translatePath('special://profile/addon_data/plugin.video.gears/databases/settings.db')
red_settings_db = translatePath('special://profile/addon_data/plugin.video.redlight/databases/settings.db')


ORDER = ['fenlt',
         'gears',
         'redlt',
         #'fen',
         'umb']

EXTID = {
    'fenlt': {
        'name'     : 'Fen Light',
        'plugin'   : 'plugin.video.fenlight',
        'path'     : os.path.join(CONFIG.ADDONS, 'plugin.video.fenlight'),
        'icon'     : os.path.join(CONFIG.ADDONS, 'plugin.video.fenlight/resources/media/addon_icons/', 'fenlight_icon_01.png'),
        'fanart'   : os.path.join(CONFIG.ADDONS, 'plugin.video.fenlight/resources/media/', 'fenlight_fanart2.jpg'),
        'settings' : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.fenlight/databases', 'settings.db'),
        'default'  : '',
        'data'     : []},
    'gears': {
        'name'     : 'The Gears',
        'plugin'   : 'plugin.video.gears',
        'path'     : os.path.join(CONFIG.ADDONS, 'plugin.video.gears'),
        'icon'     : os.path.join(CONFIG.ADDONS, 'plugin.video.gears/resources/media/addon_icons/', 'icon.png'),
        'fanart'   : os.path.join(CONFIG.ADDONS, 'plugin.video.gears/', 'fanart.jpg'),
        'settings' : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.gears/databases', 'settings.db'),
        'default'  : '',
        'data'     : []},
    'redlt': {
        'name'     : 'Red Light',
        'plugin'   : 'plugin.video.redlight',
        'path'     : os.path.join(CONFIG.ADDONS, 'plugin.video.redlight'),
        'icon'     : os.path.join(CONFIG.ADDONS, 'plugin.video.redlight/resources/media/addon_icons/', 'icon.png'),
        'fanart'   : os.path.join(CONFIG.ADDONS, 'plugin.video.redlight/resources/media/', 'fanart.jpg'),
        'settings' : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.redlight/databases', 'settings.db'),
        'default'  : '',
        'data'     : []},
    #'fen': {
        #'name'     : 'Fen',
        #'plugin'   : 'plugin.video.fen',
        #'path'     : os.path.join(CONFIG.ADDONS, 'plugin.video.fen'),
        #'icon'     : os.path.join(CONFIG.ADDONS, 'plugin.video.fen/resources/media/', 'fen_icon.png'),
        #'fanart'   : os.path.join(CONFIG.ADDONS, 'plugin.video.fen/resources/media/', 'fen_fanart.png'),
        #'settings' : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.fen', 'settings.xml'),
        #'default'  : 'external_scraper.module',
        #'data'     : ['external_scraper.module', 'external_scraper.name', 'provider.external']},
    'umb': {
        'name'     : 'Umbrella',
        'plugin'   : 'plugin.video.umbrella',
        'path'     : os.path.join(CONFIG.ADDONS, 'plugin.video.umbrella'),
        'icon'     : os.path.join(CONFIG.ADDONS, 'plugin.video.umbrella', 'icon.png'),
        'fanart'   : os.path.join(CONFIG.ADDONS, 'plugin.video.umbrella', 'fanart.jpg'),
        'settings' : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.umbrella', 'settings.xml'),
        'default'  : 'external_provider.module',
        'data'     : ['external_provider.module', 'external_provider.name', 'provider.external.enabled']}
}

def create_conn(db_file):
    try:
        return sqlite3.connect(db_file)
    except Exception as e:
        xbmc.log(f'{amgr}: Debrid DB Connect Failed: {e}', xbmc.LOGINFO)
        return None

def get_addon_by_id(id):
    try:
        return xbmcaddon.Addon(id=id)
    except Exception:
        return None

def settings(who):
    user = None
    user = EXTID[who]['name']
    return user

def open_settings(who):
    addonid = get_addon_by_id(EXTID[who]['plugin'])
    if addonid:
        addonid.openSettings()
    
def addon_installed(who):
    info = EXTID.get(who)
    if not info:
        return False

    plugin_id = info.get('plugin')
    addon_path = info.get('path', '')

    try:
        addon = get_addon_by_id(plugin_id)
        if addon:
            return True

        if addon_path and xbmcvfs.exists(addon_path):
            xbmc.log(f"{amgr}: path exists but addon id failed [{plugin_id}]", xbmc.LOGINFO)

        return False

    except Exception as e:
        xbmc.log(f"{amgr}: addon_installed failed [{who}] - {e}", xbmc.LOGINFO)
        return False
    
def chk_auth(settings_db):
    try:
        # Create database connection
        conn = create_conn(settings_db)
        with conn:
            cur = conn.cursor()
            cur.execute('''SELECT setting_value FROM settings WHERE setting_id = ?''', ('external_scraper.module',)) #Get setting to compare
            auth = cur.fetchone()
            raw_user = auth[0].strip() if auth and auth[0] else ""
            if raw_user.lower() in ("", "none", "null", "empty_setting"):
                user = None
            else:
                user = raw_user
            cur.close()
        return user
    except Exception as e:
        xbmc.log(f'{amgr}: EXTIT Chk Auth Failed!: {e}', xbmc.LOGINFO)
        pass
            
def ext_user(who):
    user = None
    if EXTID[who]:
        name = EXTID[who]['name']

        if not addon_installed(who):
            return None

        if name == 'Fen Light':
            user = chk_auth(fenlt_settings_db)

        elif name == 'The Gears':
            user = chk_auth(gears_settings_db)

        elif name == 'Red Light':
            user = chk_auth(red_settings_db)

        else:
            try:
                addon_current = get_addon_by_id(EXTID[who]['plugin'])
                if not addon_current:
                    return None

                raw_user = addon_current.getSetting(EXTID[who]['default'])

                if raw_user and raw_user.strip().lower() not in ("", "none", "null", "empty_setting"):
                    user = raw_user
            except Exception as e:
                xbmc.log(f'{amgr}: EXTIT default Failed!: {e}', xbmc.LOGINFO)

    return user

def ext_it(do, who):
    if not os.path.exists(CONFIG.ADDON_DATA):
        os.makedirs(CONFIG.ADDON_DATA)

    if who == 'all':
        for log in ORDER:
            if addon_installed(log):
                try:
                    addonid = get_addon_by_id(EXTID[log]['plugin'])
                    if not addonid:
                        xbmc.log(f'{amgr}: EXTIT skip [{EXTID[log]["plugin"]}] - addon id not available', xbmc.LOGINFO)
                        continue

                    wipe_ext(do, log)
                except Exception as e:
                    xbmc.log(f'{amgr}: EXTIT failed [{log}]: {e}', xbmc.LOGINFO)
            else:
                logging.log('[Ext Providers Info] {0}({1}) is not installed'.format(
                    EXTID[log]['name'], EXTID[log]['plugin']), level=xbmc.LOGERROR)
    else:
        if EXTID[who]:
            if addon_installed(who):
                wipe_ext(do, who)
            else:
                xbmc.log(f'{amgr}: EXTIT skip [{EXTID[who]["plugin"]}] - addon not installed', xbmc.LOGINFO)
        else:
            logging.log('[Ext Providers Info] Invalid Entry: {0}'.format(who), level=xbmc.LOGERROR)
            
'''def wipe_ext(do, who):
    settings = EXTID[who]['settings']
    data = EXTID[who]['data']
    name = EXTID[who]['name']

    if do == 'wipeaddon':
        logging.log('{0} SETTINGS: {1}'.format(name, settings))
        if who in ('fenlt', 'gears'):
            return   # Never wipe these
        else:
            if os.path.exists(settings):
                try:
                    tree = ElementTree.parse(settings)
                    root = tree.getroot()
                    
                    for setting in root.findall('setting'):
                        if setting.attrib['id'] in data:
                            logging.log('Removing Setting: {0}'.format(setting.attrib))
                            root.remove(setting)
                                
                    tree.write(settings)
                    
                except Exception as e:
                    logging.log("[Ecxt Providers Info] Unable to Clear Addon {0} ({1})".format(who, str(e)), level=xbmc.LOGERROR)'''
