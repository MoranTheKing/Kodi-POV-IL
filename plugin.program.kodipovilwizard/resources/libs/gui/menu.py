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
import re

try:  # Python 3
    from urllib.parse import quote_plus
    from urllib.request import urlretrieve
except ImportError:  # Python 2
    from urllib import quote_plus
    from urllib import urlretrieve

from resources.libs.common import directory
from resources.libs.common.config import CONFIG

###########################
#      Menu Items         #
###########################

def check_for_fm():
    if not xbmc.getCondVisibility('System.HasAddon(script.kodi.android.update)'):
        from resources.libs.gui import addon_menu
        addon_menu.install_from_kodi('script.kodi.android.update')
    
    try:
        updater = xbmcaddon.Addon('script.kodi.android.update')
    except RuntimeError as e:
        return False
        
    fm = int(updater.getSetting('File_Manager'))
    apps = xbmcvfs.listdir('androidapp://sources/apps/')[1]
    
    if fm == 0 and 'com.android.documentsui' not in apps:
        dialog = xbmcgui.Dialog()
        choose = dialog.yesno(CONFIG.ADDONTITLE, 'It appears your device has no default file manager. Would you like to set one now?')
        if not choose:
            dialog.ok(CONFIG.ADDONTITLE, 'If an APK downloads, but doesn\'t open for installation, try changing your file manager in {}\'s "Install Settings".'.format(CONFIG.ADDONTITLE))
        else:
            from resources.libs import install
            install.choose_file_manager()
            
    return True


def apk_menu(url=None):
    from resources.libs.common import logging
    from resources.libs.common import tools

    if check_for_fm():
        directory.add_dir('Official Kodi APK\'s', {'mode': 'kodiapk'}, icon=CONFIG.ICONAPK, themeit=CONFIG.THEME1)
        directory.add_separator()

    response = tools.open_url(CONFIG.APKFILE)
    url_response = tools.open_url(url)

    if response:
        TEMPAPKFILE = tools.clean_text(url_response.text if url else response.text)

        if TEMPAPKFILE:
            match = re.compile('name="(.+?)".+?ection="(.+?)".+?rl="(.+?)".+?con="(.+?)".+?anart="(.+?)".+?dult="(.+?)".+?escription="(.+?)"').findall(TEMPAPKFILE)
            if len(match) > 0:
                x = 0
                for aname, section, url, icon, fanart, adult, description in match:
                    if not CONFIG.SHOWADULT == 'true' and adult.lower() == 'yes':
                        continue
                    if section.lower() == 'yes':
                        x += 1
                        directory.add_dir("[B]{0}[/B]".format(aname), {'mode': 'apk', 'name': aname, 'url': url}, description=description, icon=icon, fanart=fanart, themeit=CONFIG.THEME3)
                    else:
                        x += 1
                        directory.add_file(aname, {'mode': 'apkinstall', 'name': aname, 'url': url}, description=description, icon=icon, fanart=fanart, themeit=CONFIG.THEME2)
                    if x == 0:
                        directory.add_file("No addons added to this menu yet!", themeit=CONFIG.THEME2)
            else:
                logging.log("[APK Menu] ERROR: Invalid Format.", level=xbmc.LOGERROR)
        else:
            logging.log("[APK Menu] ERROR: URL for apk list not working.", level=xbmc.LOGERROR)
            directory.add_file('Url for txt file not valid', themeit=CONFIG.THEME3)
            directory.add_file('{0}'.format(CONFIG.APKFILE), themeit=CONFIG.THEME3)
    else:
        logging.log("[APK Menu] No APK list added.")


#########################################NET TOOLS#############################################


def net_tools():
    # 1. Real Debrid Speed Test
    directory.add_dir('Real Debrid בדיקת מהירות', {'mode': 'rd_speedtest'}, icon=CONFIG.ICONSPEED, themeit=CONFIG.THEME1)

    # 2. Kodi Speed Test
    directory.add_dir('Speed Test', {'mode': 'standard_speedtest'}, icon=CONFIG.ICONSPEED, themeit=CONFIG.THEME1)

    if CONFIG.HIDESPACERS == 'No':
        directory.add_separator()

    # 3. View IP
    if CONFIG.HIDESPACERS == 'No':
        directory.add_separator()
    directory.add_dir('View IP & MAC Address Details', {'mode': 'viewIP'}, icon=CONFIG.ICONSPEED, themeit=CONFIG.THEME1)

def get_external_ip_info():
    import json
    import urllib.request
    from resources.libs.common import logging

    info = {
        'ip': 'Unknown',
        'city': 'Unknown',
        'state': 'Unknown',
        'country': 'Unknown',
        'isp': 'Unknown'
    }

    try:
        req = urllib.request.Request('http://ip-api.com/json', headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            geo = json.loads(response.read().decode('utf-8'))

        if geo.get('status') == 'success':
            info['ip'] = geo.get('query', 'Unknown')
            info['isp'] = geo.get('isp', 'Unknown')
            info['city'] = geo.get('city', 'Unknown')
            info['country'] = geo.get('country', 'Unknown')
            info['state'] = geo.get('regionName', 'Unknown')
    except Exception as e:
        logging.log(f"External IP Check Failed: {e}")

    return info


def view_ip():
    from resources.libs.common import tools

    # 1. Get Local IP and MAC using Kodi Built-ins
    inter_ip = tools.get_info_label('Network.IPAddress') or 'Unknown'
    mac = tools.get_info_label('Network.MacAddress') or 'Unknown'

    # 2. Get External IP and Geo-location
    geo = get_external_ip_info()

    # 3. Draw the menu
    directory.add_file(f'[COLOR {CONFIG.COLOR1}]MAC:[/COLOR] [COLOR {CONFIG.COLOR2}]{mac}[/COLOR]', icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file(f'[COLOR {CONFIG.COLOR1}]Internal IP:[/COLOR] [COLOR {CONFIG.COLOR2}]{inter_ip}[/COLOR]', icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file(f'[COLOR {CONFIG.COLOR1}]External IP:[/COLOR] [COLOR {CONFIG.COLOR2}]{geo["ip"]}[/COLOR]', icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file(f'[COLOR {CONFIG.COLOR1}]City:[/COLOR] [COLOR {CONFIG.COLOR2}]{geo["city"]}[/COLOR]', icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file(f'[COLOR {CONFIG.COLOR1}]State:[/COLOR] [COLOR {CONFIG.COLOR2}]{geo["state"]}[/COLOR]', icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file(f'[COLOR {CONFIG.COLOR1}]Country:[/COLOR] [COLOR {CONFIG.COLOR2}]{geo["country"]}[/COLOR]', icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file(f'[COLOR {CONFIG.COLOR1}]ISP:[/COLOR] [COLOR {CONFIG.COLOR2}]{geo["isp"]}[/COLOR]', icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)


def system_info():
    import os, glob, re
    from resources.libs.common import logging
    from resources.libs.common import tools

    infoLabel = ['System.FriendlyName', 'System.BuildVersion', 'System.CpuUsage', 'System.ScreenMode',
                 'Network.IPAddress', 'Network.MacAddress', 'System.Uptime', 'System.TotalUptime', 'System.FreeSpace',
                 'System.UsedSpace', 'System.TotalSpace', 'System.Memory(free)', 'System.Memory(used)',
                 'System.Memory(total)']
    data = []
    x = 0
    for info in infoLabel:
        temp = tools.get_info_label(info)
        y = 0
        while temp == "Busy" and y < 10:
            temp = tools.get_info_label(info)
            y += 1
            logging.log("{0} sleep {1}".format(info, str(y)))
            xbmc.sleep(200)
        data.append(temp)
        x += 1
    storage_free = data[8] if 'Una' in data[8] else tools.convert_size(int(float(data[8][:-8])) * 1024 * 1024)
    storage_used = data[9] if 'Una' in data[9] else tools.convert_size(int(float(data[9][:-8])) * 1024 * 1024)
    storage_total = data[10] if 'Una' in data[10] else tools.convert_size(int(float(data[10][:-8])) * 1024 * 1024)
    ram_free = tools.convert_size(int(float(data[11][:-2])) * 1024 * 1024)
    ram_used = tools.convert_size(int(float(data[12][:-2])) * 1024 * 1024)
    ram_total = tools.convert_size(int(float(data[13][:-2])) * 1024 * 1024)

    picture = []
    music = []
    video = []
    programs = []
    repos = []
    scripts = []
    skins = []

    fold = glob.glob(os.path.join(CONFIG.ADDONS, '*/'))
    for folder in sorted(fold, key = lambda x: x):
        foldername = os.path.split(folder[:-1])[1]
        if foldername == 'packages': continue
        xml = os.path.join(folder, 'addon.xml')
        if os.path.exists(xml):
            prov = re.compile("<provides>(.+?)</provides>").findall(tools.read_from_file(xml))
            if len(prov) == 0:
                if foldername.startswith('skin'):
                    skins.append(foldername)
                elif foldername.startswith('repo'):
                    repos.append(foldername)
                else:
                    scripts.append(foldername)
            elif not (prov[0]).find('executable') == -1:
                programs.append(foldername)
            elif not (prov[0]).find('video') == -1:
                video.append(foldername)
            elif not (prov[0]).find('audio') == -1:
                music.append(foldername)
            elif not (prov[0]).find('image') == -1:
                picture.append(foldername)

    directory.add_file('[B]Media Center Info:[/B]', icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Name:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, data[0]), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME3)
    directory.add_file('[COLOR {0}]Version:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, data[1]), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME3)
    directory.add_file('[COLOR {0}]Platform:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, tools.platform().title()), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME3)
    directory.add_file('[COLOR {0}]CPU Usage:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, data[2]), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME3)
    directory.add_file('[COLOR {0}]Screen Mode:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, data[3]), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME3)

    directory.add_file('[B]Uptime:[/B]', icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Current Uptime:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, data[6]), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Total Uptime:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, data[7]), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)

    directory.add_file('[B]Local Storage:[/B]', icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Used Storage:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, storage_used), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Free Storage:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, storage_free), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Total Storage:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, storage_total), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)

    directory.add_file('[B]Ram Usage:[/B]', icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Used Memory:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, ram_free), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Free Memory:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, ram_used), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Total Memory:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, ram_total), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)

    # --- REPLACED SPEEDTEST.PY LOGIC WITH LIGHTWEIGHT WEB CALL ---
    inter_ip = data[4] if data[4] else 'Unknown'
    mac = data[5] if data[5] else 'Unknown'
    geo = get_external_ip_info()
    # -------------------------------------------------------------

    directory.add_file('[B]Network:[/B]', icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Mac:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, mac), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Internal IP: [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, inter_ip), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]External IP:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, geo['ip']), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]City:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, geo['city']), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]State:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, geo['state']), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Country:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, geo['country']), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]ISP:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, geo['isp']), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)

    totalcount = len(picture) + len(music) + len(video) + len(programs) + len(scripts) + len(skins) + len(repos)
    directory.add_file('[B]Addons([COLOR {0}]{1}[/COLOR]):[/B]'.format(CONFIG.COLOR1, totalcount), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Video Addons:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, str(len(video))), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Program Addons:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, str(len(programs))), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Music Addons:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, str(len(music))), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Picture Addons:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, str(len(picture))), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Repositories:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, str(len(repos))), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Skins:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, str(len(skins))), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)
    directory.add_file('[COLOR {0}]Scripts/Modules:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.COLOR2, str(len(scripts))), icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME2)


def save_menu():
    from resources.libs.common import logging
    
    on = '[COLOR springgreen]ON[/COLOR]'
    off = '[COLOR red]OFF[/COLOR]'

    # Check new config keys (defaulting to false if not set yet)
    acctmgrdata = 'true' if getattr(CONFIG, 'KEEPACCTMGR', 'false') == 'true' else 'false'
    povdata = 'true' if getattr(CONFIG, 'KEEPPOVDATA', 'false') == 'true' else 'false'
    umbrelladata = 'true' if getattr(CONFIG, 'KEEPUMBRELLADATA', 'false') == 'true' else 'false'

    fentasticdata = 'true' if getattr(CONFIG, 'KEEPFENTASTICDATA', 'false') == 'true' else 'false'
    favourites = 'true' if getattr(CONFIG, 'KEEPFAVS', 'false') == 'true' else 'false'
    sources = 'true' if getattr(CONFIG, 'KEEPSOURCES', 'false') == 'true' else 'false'
    guisettings = 'true' if getattr(CONFIG, 'KEEPGUISETTINGS', 'false') == 'true' else 'false'
    repos = 'true' if getattr(CONFIG, 'KEEPREPOS', 'false') == 'true' else 'false'
    whitelist = 'true' if getattr(CONFIG, 'KEEPWHITELIST', 'false') == 'true' else 'false'
    addons33db = 'true' if getattr(CONFIG, 'KEEPADDONS33DB', 'false') == 'true' else 'false'

    directory.add_file('- לחץ להפעלה או ביטול של ההגדרה -', themeit=CONFIG.THEME3)

    # New Targeted Backup Toggles
    directory.add_file('Account Manager Lite שמירת נתוני: {0}'.format(acctmgrdata.replace('true', on).replace('false', off)), {'mode': 'togglesetting', 'name': 'keepacctmgr'}, icon=CONFIG.ICONSAVE, themeit=CONFIG.THEME1)
    directory.add_file('POV שמירת נתוני: {0}'.format(povdata.replace('true', on).replace('false', off)), {'mode': 'togglesetting', 'name': 'keeppovdata'}, icon=CONFIG.ICONSAVE, themeit=CONFIG.THEME1)
    directory.add_file('Umbrella שמירת נתוני: {0}'.format(umbrelladata.replace('true', on).replace('false', off)), {'mode': 'togglesetting', 'name': 'keepumbrelladata'}, icon=CONFIG.ICONSAVE, themeit=CONFIG.THEME1)

    # Core Backup Toggles
    directory.add_file('FENtastic שמירת עיצוב סקין: {0}'.format(fentasticdata.replace('true', on).replace('false', off)), {'mode': 'togglesetting', 'name': 'keepfentasticdata'}, icon=CONFIG.ICONSAVE, themeit=CONFIG.THEME1)
    directory.add_file('שמירת הגדרות קודי פנימיות: {0}'.format(guisettings.replace('true', on).replace('false', off)), {'mode': 'togglesetting', 'name': 'keepguisettings'}, icon=CONFIG.ICONSAVE, themeit=CONFIG.THEME1)
    directory.add_file('Favourites.xml שמירת מועדפים קודי: {0}'.format(favourites.replace('true', on).replace('false', off)), {'mode': 'togglesetting', 'name': 'keepfavourites'}, icon=CONFIG.ICONSAVE, themeit=CONFIG.THEME1)
    directory.add_file('Sources.xml שמירת: {0}'.format(sources.replace('true', on).replace('false', off)), {'mode': 'togglesetting', 'name': 'keepsources'}, icon=CONFIG.ICONSAVE, themeit=CONFIG.THEME1)
    directory.add_file('שמירת מאגרי הרחבות: {0}'.format(repos.replace('true', on).replace('false', off)), {'mode': 'togglesetting', 'name': 'keeprepos'}, icon=CONFIG.ICONSAVE, themeit=CONFIG.THEME1)
    directory.add_file('שמירת הרחבות מותקנות: {0}'.format(whitelist.replace('true', on).replace('false', off)), {'mode': 'togglesetting', 'name': 'keepwhitelist'}, icon=CONFIG.ICONSAVE, themeit=CONFIG.THEME1)

    if whitelist == 'true':
        directory.add_file('עריכת רשימת הרחבות לשמירה', {'mode': 'whitelist', 'name': 'edit'}, icon=CONFIG.ICONSAVE, themeit=CONFIG.THEME1)
        directory.add_file('צפיה ברשימת הרחבות שמורות', {'mode': 'whitelist', 'name': 'view'}, icon=CONFIG.ICONSAVE, themeit=CONFIG.THEME1)
        directory.add_file('ניקוי רשימת הרחבות שמורות', {'mode': 'whitelist', 'name': 'clear'}, icon=CONFIG.ICONSAVE, themeit=CONFIG.THEME1)
        directory.add_file('ייבוא רשימת הרחבות לשמירה', {'mode': 'whitelist', 'name': 'import'}, icon=CONFIG.ICONSAVE, themeit=CONFIG.THEME1)
        directory.add_file('ייצוא רשימת הרחבות שמורות', {'mode': 'whitelist', 'name': 'export'}, icon=CONFIG.ICONSAVE, themeit=CONFIG.THEME1)

    directory.add_file('Addons33.db שמירת: {0}'.format(addons33db.replace('true', on).replace('false', off)), {'mode': 'togglesetting', 'name': 'keepaddons33db'}, icon=CONFIG.ICONSAVE, themeit=CONFIG.THEME1)

def acctmgr_menu():
    """Generates a dedicated Account Manager submenu."""
    directory.add_file('[B]הפעלת (Account Manager)[/B]', {'mode': 'run_acctmgr'}, icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME1)
    directory.add_separator()

    # Authorize
    directory.add_file('Authorize Trakt', {'mode': 'run_acctmgr', 'action': 'traktAuth'}, icon=CONFIG.ICONTRAKT, themeit=CONFIG.THEME1)
    directory.add_file('Authorize Real-Debrid', {'mode': 'run_acctmgr', 'action': 'realdebridAuth'}, icon=CONFIG.ICONDEBRID, themeit=CONFIG.THEME1)
    directory.add_file('Authorize TorBox', {'mode': 'run_acctmgr', 'action': 'torboxAuth'}, icon=CONFIG.ICONDEBRID, themeit=CONFIG.THEME1)
    directory.add_file('Authorize All-Debrid', {'mode': 'run_acctmgr', 'action': 'alldebridAuth'}, icon=CONFIG.ICONDEBRID, themeit=CONFIG.THEME1)

    directory.add_separator()

    # ReSync
    directory.add_file('ReSync Trakt', {'mode': 'run_acctmgr', 'action': 'traktReSync'}, icon=CONFIG.ICONTRAKT, themeit=CONFIG.THEME1)
    directory.add_file('ReSync TorBox', {'mode': 'run_acctmgr', 'action': 'torboxReSync'}, icon=CONFIG.ICONDEBRID, themeit=CONFIG.THEME1)

    directory.add_separator()

    # Revoke
    directory.add_file('[COLOR red]Revoke All Services[/COLOR]', {'mode': 'run_acctmgr', 'action': 'allRevoke'}, icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME1)

def enable_addons(all=False):
    from resources.libs.common import tools
    
    from xml.etree import ElementTree

    fold = glob.glob(os.path.join(CONFIG.ADDONS, '*/'))
    addonnames = []
    addonids = []
    for folder in sorted(fold, key=lambda x: x):
        foldername = os.path.split(folder[:-1])[1]
        if foldername in CONFIG.EXCLUDES:
            continue
        elif foldername in CONFIG.DEFAULTPLUGINS:
            continue
        elif foldername == 'packages':
            continue
        xml = os.path.join(folder, 'addon.xml')
        if os.path.exists(xml):
            root = ElementTree.parse(xml).getroot()
            addonid = root.get('id')
            addonname = root.get('name')
            addonids.append(addonid)
            addonnames.append(addonname)
    if not all:
        if len(addonids) == 0:
            directory.add_file("No Addons Found to Enable or Disable.", icon=CONFIG.ICONMAINT)
        else:
            directory.add_file("[I][B][COLOR red]!!Notice: Disabling Some Addons Can Cause Issues!![/COLOR][/B][/I]", icon=CONFIG.ICONMAINT)
            directory.add_dir('Enable All Addons', {'mode': 'enableall'}, icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME3)
            for i in range(0, len(addonids)):
                folder = os.path.join(CONFIG.ADDONS, addonids[i])
                icon = os.path.join(folder, 'icon.png') if os.path.exists(os.path.join(folder, 'icon.png')) else CONFIG.ADDON_ICON
                fanart = os.path.join(folder, 'fanart.jpg') if os.path.exists(os.path.join(folder, 'fanart.jpg')) else CONFIG.ADDON_FANART
                if tools.get_addon_info(addonids[i], 'name'):
                    state = "[COLOR springgreen][Enabled][/COLOR]"
                    goto = "false"
                else:
                    state = "[COLOR red][Disabled][/COLOR]"
                    goto = "true"

                directory.add_file("{0} {1}".format(state, addonnames[i]), {'mode': 'toggleaddon', 'name': addonids[i], 'url': goto}, icon=icon, fanart=fanart)
    else:
        from resources.libs import db
        for addonid in addonids:
            db.toggle_addon(addonid, 'true')
        xbmc.executebuiltin('Container.Refresh()')


def remove_addon_data_menu():
    if os.path.exists(CONFIG.ADDON_DATA):
        directory.add_file('[COLOR red][B][REMOVE][/B][/COLOR] All Addon_Data', {'mode': 'removedata', 'name': 'all'}, themeit=CONFIG.THEME2)
        directory.add_file('[COLOR red][B][REMOVE][/B][/COLOR] All Addon_Data for Uninstalled Addons', {'mode': 'removedata', 'name': 'uninstalled'}, themeit=CONFIG.THEME2)
        directory.add_file('[COLOR red][B][REMOVE][/B][/COLOR] All Empty Folders in Addon_Data', {'mode': 'removedata', 'name': 'empty'}, themeit=CONFIG.THEME2)
        directory.add_file('[COLOR red][B][REMOVE][/B][/COLOR] {0} Addon_Data'.format(CONFIG.ADDONTITLE), {'mode': 'resetaddon'}, themeit=CONFIG.THEME2)
        directory.add_separator(themeit=CONFIG.THEME3)
        fold = glob.glob(os.path.join(CONFIG.ADDON_DATA, '*/'))
        for folder in sorted(fold, key = lambda x: x):
            foldername = folder.replace(CONFIG.ADDON_DATA, '').replace('\\', '').replace('/', '')
            icon = os.path.join(folder.replace(CONFIG.ADDON_DATA, CONFIG.ADDONS), 'icon.png')
            fanart = os.path.join(folder.replace(CONFIG.ADDON_DATA, CONFIG.ADDONS), 'fanart.jpg')
            folderdisplay = foldername
            replace = {'audio.': '[COLOR orange][AUDIO] [/COLOR]', 'metadata.': '[COLOR cyan][METADATA] [/COLOR]',
                       'module.': '[COLOR orange][MODULE] [/COLOR]', 'plugin.': '[COLOR blue][PLUGIN] [/COLOR]',
                       'program.': '[COLOR orange][PROGRAM] [/COLOR]', 'repository.': '[COLOR gold][REPO] [/COLOR]',
                       'script.': '[COLOR springgreen][SCRIPT] [/COLOR]',
                       'service.': '[COLOR springgreen][SERVICE] [/COLOR]', 'skin.': '[COLOR dodgerblue][SKIN] [/COLOR]',
                       'video.': '[COLOR orange][VIDEO] [/COLOR]', 'weather.': '[COLOR yellow][WEATHER] [/COLOR]'}
            for rep in replace:
                folderdisplay = folderdisplay.replace(rep, replace[rep])
            if foldername in CONFIG.EXCLUDES:
                folderdisplay = '[COLOR springgreen][B][PROTECTED][/B][/COLOR] {0}'.format(folderdisplay)
            else:
                folderdisplay = '[COLOR red][B][REMOVE][/B][/COLOR] {0}'.format(folderdisplay)
            directory.add_file(' {0}'.format(folderdisplay), {'mode': 'removedata', 'name': foldername}, icon=icon, fanart=fanart, themeit=CONFIG.THEME2)
    else:
        directory.add_file('No Addon data folder found.', themeit=CONFIG.THEME3)


def change_freq():
    from resources.libs.common import logging

    dialog = xbmcgui.Dialog()

    change = dialog.select("[COLOR {0}]How often would you list to Auto Clean on Startup?[/COLOR]".format(CONFIG.COLOR2), CONFIG.CLEANFREQ)
    if not change == -1:
        CONFIG.set_setting('autocleanfreq', str(change))
        logging.log_notify('[COLOR {0}]Auto Clean Up[/COLOR]'.format(CONFIG.COLOR1),
                           '[COLOR {0}]Frequency Now {1}[/COLOR]'.format(CONFIG.COLOR2, CONFIG.CLEANFREQ[change]))


def developer():
    directory.add_file('Test Notifications', {'mode': 'testnotify'}, themeit=CONFIG.THEME1)
    directory.add_file('Test Update', {'mode': 'testupdate'}, themeit=CONFIG.THEME1)
    directory.add_file('Test Build Prompt', {'mode': 'testbuildprompt'}, themeit=CONFIG.THEME1)
    directory.add_file('Test Save Data Settings', {'mode': 'testsavedata'}, themeit=CONFIG.THEME1)
    directory.add_file('Test Binary Detection', {'mode': 'binarycheck'}, themeit=CONFIG.THEME1)
    directory.add_dir('Patch Manager', {'mode': 'patchmanager'}, themeit=CONFIG.THEME1)



def patch_manager_menu():
    from resources.libs.common import directory
    from resources.libs.common.config import CONFIG
    import xbmcaddon

    try:
        from resources.libs.patches.patches_config import PATCH_CONFIG
    except ImportError:
        PATCH_CONFIG = []

    if not PATCH_CONFIG:
        directory.add_file('No patches configured.', themeit=CONFIG.THEME3)
        return

    addon_obj = xbmcaddon.Addon()

    for patch in PATCH_CONFIG:
        patch_id = patch.get('id', 'unknown')
        patch_name = patch.get('name', patch_id)
        desc = patch.get('description', '')
        addon_id = patch.get('addon_id', 'plugin.video.pov')
        target_file = patch.get('target_file', 'unknown')

        override = addon_obj.getSetting('patch_enabled_' + patch_id)
        if override == 'true':
            is_enabled = True
        elif override == 'false':
            is_enabled = False
        else:
            is_enabled = patch.get('enabled', True)

        if is_enabled:
            status_str = '[COLOR springgreen][ON][/COLOR]'
        else:
            status_str = '[COLOR red][OFF][/COLOR]'

        label = '{0} {1}'.format(status_str, patch_name)
        plot = '{0}\nTarget: {1}/{2}'.format(desc, addon_id, target_file)

        query = {'mode': 'togglepatch', 'name': patch_id}
        directory.add_file(label, query, description=plot, icon=CONFIG.ICONMAINT, themeit=CONFIG.THEME1)