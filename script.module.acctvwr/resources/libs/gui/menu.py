import xbmc, xbmcaddon, xbmcvfs
import json
import os
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus
from urllib.request import urlretrieve

from resources.libs import acct_vwr
from resources.libs.common import directory
from resources.libs.common.config import CONFIG

# Variables
translatePath = xbmcvfs.translatePath
addons = translatePath('special://home/addons/')
addon_id = 'script.module.acctmgr'

# Scraper Variables
coco_plugin_id = 'script.module.cocoscrapers'
gears_plugin_id = 'script.module.gearsscrapers'
mag_plugin_id = 'script.module.magneto'
viper_plugin_id = 'script.module.viperscrapers'

# Helpers
def get_active_skin():
    try:
        json_query = xbmc.executeJSONRPC(
            '{"jsonrpc":"2.0","method":"Settings.GetSettingValue","params":{"setting":"lookandfeel.skin"},"id":1}'
        )
        json_query = json.loads(json_query)
        return json_query.get('result', {}).get('value', '')
    except Exception:
        return ''

def get_fenlight_name(plugin, name):
    if plugin != 'plugin.video.fenlight':
        return name

    try:
        addon_xml = os.path.join(addons, plugin, 'addon.xml')
        addon_name = ET.parse(addon_xml).getroot().get('name', '')
        return 'Fen Light+' if '+' in addon_name else 'Fen Light'
    except Exception:
        return name
    
def trakt_menu():
    for trakt in acct_vwr.ORDER:
        # Filter only addons that support Trakt
        if not acct_vwr.ADDONS[trakt].get('default_tk'):
            continue
        if not xbmc.getCondVisibility('System.HasAddon({0})'.format(acct_vwr.ADDONS[trakt]['plugin'])):
            pass
        else:
            if xbmc.getCondVisibility('System.HasAddon({0})'.format(acct_vwr.ADDONS[trakt]['plugin'])):
                name = acct_vwr.ADDONS[trakt]['name']
                name = get_fenlight_name(acct_vwr.ADDONS[trakt]['plugin'], name)
                path = acct_vwr.ADDONS[trakt]['path']
                auser = acct_vwr.addon_user_trakt(trakt)
                icon = acct_vwr.ADDONS[trakt]['icon'] if os.path.exists(path) else CONFIG.ICON
                fanart = acct_vwr.ADDONS[trakt]['fanart'] if os.path.exists(path) else CONFIG.ADDON_FANART
                menu = create_addon_data_menu('Trakt', trakt)
                menu.append((CONFIG.THEME1.format('{0} Settings'.format(name)),
                             'RunPlugin(plugin://{0}/?mode=opensettings&name={1}&url=trakt)'.format(CONFIG.ADDON_ID, trakt)))

                if not auser:
                    directory.add_file('{0} - [COLOR red]Not Authorized[/COLOR]'.format(name), {'name': trakt}, icon=icon, description='Your Trakt Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                else:
                    directory.add_file('{0} - [COLOR springgreen]Authorized[/COLOR]'.format(name), {'name': trakt}, icon=icon, description='Your Trakt Authorizations', fanart=fanart, themeit=CONFIG.THEME2)

                if acct_vwr.ADDONS[trakt]['plugin'] == 'plugin.video.fenlight':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_fenlt', 'name': 'Fen Light'}, icon=icon, fanart=fanart, menu=menu)
                elif name == 'The Gears':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_gears', 'name': 'The Gears'}, icon=icon, fanart=fanart, menu=menu)
                elif name == 'Red Light':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_red', 'name': 'Red Light'}, icon=icon, fanart=fanart, menu=menu)
                else:
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_tk', 'name': trakt}, icon=icon, fanart=fanart, menu=menu)
                directory.add_separator()

def mdblist_menu():
    active_skin = get_active_skin()

    for mdblist in acct_vwr.ORDER:
        # Filter only addons that support MDBList
        if not acct_vwr.ADDONS[mdblist].get('default_mdb'):
            continue

        # Only show the current active skin
        if mdblist == 'fentastic' and active_skin != 'skin.fentastic':
            continue
        if mdblist == 'nimbus' and active_skin != 'skin.nimbus':
            continue

        mdb_plugin = acct_vwr.ADDONS[mdblist].get('mdb_plugin', acct_vwr.ADDONS[mdblist]['plugin'])
        if not xbmc.getCondVisibility('System.HasAddon({0})'.format(mdb_plugin)):
            pass
        else:
            if xbmc.getCondVisibility('System.HasAddon({0})'.format(mdb_plugin)):
                name = acct_vwr.ADDONS[mdblist]['name']
                path = os.path.join(addons, mdb_plugin) if mdblist == 'tmdbhelper' else acct_vwr.ADDONS[mdblist]['path']
                auser = acct_vwr.addon_user_mdb(mdblist)
                icon = acct_vwr.ADDONS[mdblist]['icon'] if os.path.exists(path) else CONFIG.ICON
                fanart = acct_vwr.ADDONS[mdblist]['fanart'] if os.path.exists(path) else CONFIG.ADDON_FANART
                menu = create_addon_data_menu('MDBList', mdblist)
                menu.append((CONFIG.THEME1.format('{0} Settings'.format(name)),
                             'RunPlugin(plugin://{0}/?mode=opensettings&name={1}&url=mdblist)'.format(CONFIG.ADDON_ID, mdblist)))

                if not auser:
                    directory.add_file('{0} - [COLOR red]Not Authorized[/COLOR]'.format(name), {'name': mdblist}, icon=icon, description='Your MDBList Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                else:
                    directory.add_file('{0} - [COLOR springgreen]Authorized[/COLOR]'.format(name), {'name': mdblist}, icon=icon, description='Your MDBList Authorizations', fanart=fanart, themeit=CONFIG.THEME2)

                directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_mdb', 'name': mdblist}, icon=icon, fanart=fanart, menu=menu)
                directory.add_separator()

def debrid_menu():
    for debrid in acct_vwr.ORDER:
        # Filter only addons that support Real-Debrid
        if not acct_vwr.ADDONS[debrid].get('default_rd'):
            continue
        if not xbmc.getCondVisibility('System.HasAddon({0})'.format(acct_vwr.ADDONS[debrid]['plugin'])):
            pass
        else:
            if xbmc.getCondVisibility('System.HasAddon({0})'.format(acct_vwr.ADDONS[debrid]['plugin'])):
                name = acct_vwr.ADDONS[debrid]['name']
                name = get_fenlight_name(acct_vwr.ADDONS[debrid]['plugin'], name)
                path = acct_vwr.ADDONS[debrid]['path']
                auser = acct_vwr.addon_user_rd(debrid)
                icon = acct_vwr.ADDONS[debrid]['icon'] if os.path.exists(path) else CONFIG.ICON
                fanart = acct_vwr.ADDONS[debrid]['fanart'] if os.path.exists(path) else CONFIG.ADDON_FANART
                menu = create_addon_data_menu('Debrid', debrid)
                menu.append((CONFIG.THEME1.format('{0} Settings'.format(name)),
                             'RunPlugin(plugin://{0}/?mode=opensettings&name={1}&url=debrid)'.format(CONFIG.ADDON_ID, debrid)))

                if not auser:
                    directory.add_file('{0} - [COLOR red]Not Authorized[/COLOR]'.format(name), {'name': debrid}, icon=icon, description='Your Real-Debrid Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                else:
                    directory.add_file('{0} - [COLOR springgreen]Authorized[/COLOR]'.format(name), {'name': debrid}, icon=icon, description='Your Real-Debrid Authorizations', fanart=fanart, themeit=CONFIG.THEME2)

                if acct_vwr.ADDONS[debrid]['plugin'] == 'plugin.video.fenlight':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_fenlt', 'name': 'Fen Light'}, icon=icon, fanart=fanart, menu=menu)
                elif name == 'The Gears':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_gears', 'name': 'The Gears'}, icon=icon, fanart=fanart, menu=menu)
                elif name == 'Red Light':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_red', 'name': 'Red Light'}, icon=icon, fanart=fanart, menu=menu)
                else:
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_rd', 'name': debrid}, icon=icon, fanart=fanart, menu=menu)
                directory.add_separator()

def premiumize_menu():
    from resources.libs import acct_vwr
    for debrid in acct_vwr.ORDER:
        # Filter only addons that support Premiumize
        if not acct_vwr.ADDONS[debrid].get('default_pm'):
            continue
        if not xbmc.getCondVisibility('System.HasAddon({0})'.format(acct_vwr.ADDONS[debrid]['plugin'])):
            pass
        else:
            if xbmc.getCondVisibility('System.HasAddon({0})'.format(acct_vwr.ADDONS[debrid]['plugin'])):
                name = acct_vwr.ADDONS[debrid]['name']
                name = get_fenlight_name(acct_vwr.ADDONS[debrid]['plugin'], name)
                path = acct_vwr.ADDONS[debrid]['path']
                auser = acct_vwr.addon_user_pm(debrid)
                icon = acct_vwr.ADDONS[debrid]['icon'] if os.path.exists(path) else CONFIG.ICON
                fanart = acct_vwr.ADDONS[debrid]['fanart'] if os.path.exists(path) else CONFIG.ADDON_FANART
                menu = create_addon_data_menu('Debrid', debrid)
                menu.append((CONFIG.THEME1.format('{0} Settings'.format(name)),
                             'RunPlugin(plugin://{0}/?mode=opensettings&name={1}&url=debrid)'.format(CONFIG.ADDON_ID, debrid)))

                if not auser:
                    directory.add_file('{0} - [COLOR red]Not Authorized[/COLOR]'.format(name), {'name': debrid}, icon=icon, description='Your Premiumize Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                else:
                    directory.add_file('{0} - [COLOR springgreen]Authorized[/COLOR]'.format(name), {'name': debrid}, icon=icon, description='Your Premiumize Authorizations', fanart=fanart, themeit=CONFIG.THEME2)

                if acct_vwr.ADDONS[debrid]['plugin'] == 'plugin.video.fenlight':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_fenlt', 'name': 'Fen Light'}, icon=icon, fanart=fanart, menu=menu)
                elif name == 'The Gears':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_gears', 'name': 'The Gears'}, icon=icon, fanart=fanart, menu=menu)
                elif name == 'Red Light':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_red', 'name': 'Red Light'}, icon=icon, fanart=fanart, menu=menu)
                else:
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_pm', 'name': debrid}, icon=icon, fanart=fanart, menu=menu)
                directory.add_separator()

def alldebrid_menu():
    from resources.libs import acct_vwr
    for debrid in acct_vwr.ORDER:
        # Filter only addons that support All-Debrid
        if not acct_vwr.ADDONS[debrid].get('default_ad'):
            continue
        if not xbmc.getCondVisibility('System.HasAddon({0})'.format(acct_vwr.ADDONS[debrid]['plugin'])):
            pass
        else:
            if xbmc.getCondVisibility('System.HasAddon({0})'.format(acct_vwr.ADDONS[debrid]['plugin'])):
                name = acct_vwr.ADDONS[debrid]['name']
                name = get_fenlight_name(acct_vwr.ADDONS[debrid]['plugin'], name)
                path = acct_vwr.ADDONS[debrid]['path']
                auser = acct_vwr.addon_user_ad(debrid)
                icon = acct_vwr.ADDONS[debrid]['icon'] if os.path.exists(path) else CONFIG.ICON
                fanart = acct_vwr.ADDONS[debrid]['fanart'] if os.path.exists(path) else CONFIG.ADDON_FANART
                menu = create_addon_data_menu('Debrid', debrid)
                menu.append((CONFIG.THEME1.format('{0} Settings'.format(name)),
                             'RunPlugin(plugin://{0}/?mode=opensettings&name={1}&url=debrid)'.format(CONFIG.ADDON_ID, debrid)))

                if not auser:
                    directory.add_file('{0} - [COLOR red]Not Authorized[/COLOR]'.format(name), {'name': debrid}, icon=icon, description='Your All-Debrid Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                else:
                    directory.add_file('{0} - [COLOR springgreen]Authorized[/COLOR]'.format(name), {'name': debrid}, icon=icon, description='Your All-Debrid Authorizations', fanart=fanart, themeit=CONFIG.THEME2)

                if acct_vwr.ADDONS[debrid]['plugin'] == 'plugin.video.fenlight':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_fenlt', 'name': 'Fen Light'}, icon=icon, fanart=fanart, menu=menu)
                elif name == 'The Gears':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_gears', 'name': 'The Gears'}, icon=icon, fanart=fanart, menu=menu)
                elif name == 'Red Light':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_red', 'name': 'Red Light'}, icon=icon, fanart=fanart, menu=menu)
                else:
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_ad', 'name': debrid}, icon=icon, fanart=fanart, menu=menu)
                directory.add_separator()

def easydebrid_menu():
    for ed in acct_vwr.ORDER:
        # Filter only addons that support Easy Debrid
        if not acct_vwr.ADDONS[ed].get('default_ed'):
            continue
        if not xbmc.getCondVisibility('System.HasAddon({0})'.format(acct_vwr.ADDONS[ed]['plugin'])):
            pass
        else:
            if xbmc.getCondVisibility('System.HasAddon({0})'.format(acct_vwr.ADDONS[ed]['plugin'])):
                name = acct_vwr.ADDONS[ed]['name']
                path = acct_vwr.ADDONS[ed]['path']
                auser = acct_vwr.addon_user_ed(ed)
                icon = acct_vwr.ADDONS[ed]['icon'] if os.path.exists(path) else CONFIG.ICON
                fanart = acct_vwr.ADDONS[ed]['fanart'] if os.path.exists(path) else CONFIG.ADDON_FANART
                menu = create_addon_data_menu('Easy Debrid', ed)
                menu.append((CONFIG.THEME1.format('{0} Settings'.format(name)), 'RunPlugin(plugin://{0}/?mode=opensettings&name={1}&url=ed)'.format(CONFIG.ADDON_ID, ed)))

                if not auser:
                    directory.add_file('{0} - [COLOR red]Not Authorized[/COLOR]'.format(name), {'name': ed}, icon=icon, description='Your Easy Debrid Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                else:
                    directory.add_file('{0} - [COLOR springgreen]Authorized[/COLOR]'.format(name), {'name': ed}, icon=icon, description='Your Easy Debrid Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                if name == 'Fen Light':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_fenlt', 'name': 'Fen Light'}, icon=icon, fanart=fanart, menu=menu)
                elif name == 'The Gears':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_gears', 'name': 'The Gears'}, icon=icon, fanart=fanart, menu=menu)
                else:
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_ed', 'name': ed}, icon=icon, fanart=fanart, menu=menu)
                directory.add_separator()
                
def torbox_menu():
    for tb in acct_vwr.ORDER:
        # Filter only addons that support Torbox
        if not acct_vwr.ADDONS[tb].get('default_tb'):
            continue
        if not xbmc.getCondVisibility('System.HasAddon({0})'.format(acct_vwr.ADDONS[tb]['plugin'])):
            pass
        else:
            if xbmc.getCondVisibility('System.HasAddon({0})'.format(acct_vwr.ADDONS[tb]['plugin'])):
                name = acct_vwr.ADDONS[tb]['name']
                name = get_fenlight_name(acct_vwr.ADDONS[tb]['plugin'], name)
                path = acct_vwr.ADDONS[tb]['path']
                auser = acct_vwr.addon_user_tb(tb)
                icon = acct_vwr.ADDONS[tb]['icon'] if os.path.exists(path) else CONFIG.ICON
                fanart = acct_vwr.ADDONS[tb]['fanart'] if os.path.exists(path) else CONFIG.ADDON_FANART
                menu = create_addon_data_menu('TorBox', tb)
                menu.append((CONFIG.THEME1.format('{0} Settings'.format(name)), 'RunPlugin(plugin://{0}/?mode=opensettings&name={1}&url=tb)'.format(CONFIG.ADDON_ID, tb)))

                if not auser:
                    directory.add_file('{0} - [COLOR red]Not Authorized[/COLOR]'.format(name), {'name': tb}, icon=icon, description='Your TorBox Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                else:
                    directory.add_file('{0} - [COLOR springgreen]Authorized[/COLOR]'.format(name), {'name': tb}, icon=icon, description='Your TorBox Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                if acct_vwr.ADDONS[tb]['plugin'] == 'plugin.video.fenlight':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_fenlt', 'name': 'Fen Light'}, icon=icon, fanart=fanart, menu=menu)
                elif name == 'The Gears':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_gears', 'name': 'The Gears'}, icon=icon, fanart=fanart, menu=menu)
                elif name == 'Red Light':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_red', 'name': 'Red Light'}, icon=icon, fanart=fanart, menu=menu)
                else:
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_tb', 'name': tb}, icon=icon, fanart=fanart, menu=menu)
                directory.add_separator()
                
def offcloud_menu():
    for oc in acct_vwr.ORDER:
        # Filter only addons that support OffCloud
        if not acct_vwr.ADDONS[oc].get('default_oc'):
            continue
        if not xbmc.getCondVisibility('System.HasAddon({0})'.format(acct_vwr.ADDONS[oc]['plugin'])):
            pass
        else:
            if xbmc.getCondVisibility('System.HasAddon({0})'.format(acct_vwr.ADDONS[oc]['plugin'])):
                name = acct_vwr.ADDONS[oc]['name']
                path = acct_vwr.ADDONS[oc]['path']
                auser = acct_vwr.addon_user_oc(oc)
                icon = acct_vwr.ADDONS[oc]['icon'] if os.path.exists(path) else CONFIG.ICON
                fanart = acct_vwr.ADDONS[oc]['fanart'] if os.path.exists(path) else CONFIG.ADDON_FANART
                menu = create_addon_data_menu('OffCloud', oc)
                menu.append((CONFIG.THEME1.format('{0} Settings'.format(name)), 'RunPlugin(plugin://{0}/?mode=opensettings&name={1}&url=oc)'.format(CONFIG.ADDON_ID, oc)))

                if not auser:
                    directory.add_file('{0} - [COLOR red]Not Authorized[/COLOR]'.format(name), {'name': oc}, icon=icon, description='Your Offcloud Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                else:
                    directory.add_file('{0} - [COLOR springgreen]Authorized[/COLOR]'.format(name), {'name': oc}, icon=icon, description='Your Offcloud Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                if name == 'Red Light':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_red', 'name': 'Red Light'}, icon=icon, fanart=fanart, menu=menu)
                #elif name == 'The Gears':
                    #directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_gears', 'name': 'The Gears'}, icon=icon, fanart=fanart, menu=menu)
                else:
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_oc', 'name': oc}, icon=icon, fanart=fanart, menu=menu)
                directory.add_separator()

def easynews_menu():
    for easy in acct_vwr.ORDER:
        # Filter only addons that support Easynews
        if not acct_vwr.ADDONS[easy].get('default_en'):
            continue
        if not xbmc.getCondVisibility('System.HasAddon({0})'.format(acct_vwr.ADDONS[easy]['plugin'])):
            pass
        else:
            if xbmc.getCondVisibility('System.HasAddon({0})'.format(acct_vwr.ADDONS[easy]['plugin'])):
                name = acct_vwr.ADDONS[easy]['name']
                name = get_fenlight_name(acct_vwr.ADDONS[easy]['plugin'], name)
                path = acct_vwr.ADDONS[easy]['path']
                auser = acct_vwr.addon_user_en(easy)
                icon = acct_vwr.ADDONS[easy]['icon'] if os.path.exists(path) else CONFIG.ICON
                fanart = acct_vwr.ADDONS[easy]['fanart'] if os.path.exists(path) else CONFIG.ADDON_FANART
                menu = create_addon_data_menu('OffCloud', easy)
                menu.append((CONFIG.THEME1.format('{0} Settings'.format(name)), 'RunPlugin(plugin://{0}/?mode=opensettings&name={1}&url=easy)'.format(CONFIG.ADDON_ID, easy)))

                if not auser:
                    directory.add_file('{0} - [COLOR red]Not Authorized[/COLOR]'.format(name), {'name': easy}, icon=icon, description='Your Easynews Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                else:
                    directory.add_file('{0} - [COLOR springgreen]Authorized[/COLOR]'.format(name), {'name': easy}, icon=icon, description='Your Easynews Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                if acct_vwr.ADDONS[easy]['plugin'] == 'plugin.video.fenlight':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_fenlt', 'name': 'Fen Light'}, icon=icon, fanart=fanart, menu=menu)
                elif name == 'The Gears':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_gears', 'name': 'The Gears'}, icon=icon, fanart=fanart, menu=menu)
                elif name == 'Red Light':
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_red', 'name': 'Red Light'}, icon=icon, fanart=fanart, menu=menu)
                else:
                    directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_en', 'name': easy}, icon=icon, fanart=fanart, menu=menu)
                directory.add_separator()

def ext_menu():
    from resources.libs import extit

    for ext in extit.ORDER:
        if not xbmc.getCondVisibility('System.HasAddon({0})'.format(extit.EXTID[ext]['plugin'])):
            pass
        else:
            if xbmc.getCondVisibility('System.HasAddon({0})'.format(extit.EXTID[ext]['plugin'])):
                name = extit.EXTID[ext]['name']
                path = extit.EXTID[ext]['path']
                auser = extit.ext_user(ext)
                icon = extit.EXTID[ext]['icon'] if os.path.exists(path) else CONFIG.ICON
                fanart = extit.EXTID[ext]['fanart'] if os.path.exists(path) else CONFIG.ADDON_FANART
                menu = create_addon_data_menu('External Providers', ext)
                menu.append((CONFIG.THEME1.format('{0} Settings'.format(name)), 'RunPlugin(plugin://{0}/?mode=opensettings&name={1}&url=ext)'.format(CONFIG.ADDON_ID, ext)))

                if not auser:
                    directory.add_file('{0} - [COLOR red]No Scraper Synced[/COLOR]'.format(name), {'name': ext}, icon=icon, description='Your External Provider Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                elif 'coco' in str(auser).lower():
                    if name == 'Fen':
                        directory.add_file('{0} - [COLOR springgreen]Coco Scrapers Synced[/COLOR]'.format(name), {'name': ext}, icon=icon, description='Your External Provider Authorizations\n\nGears Scrapers - Not Supported\nMagento Scrapers - Not Supported', fanart=fanart, themeit=CONFIG.THEME2)
                    else:
                        directory.add_file('{0} - [COLOR springgreen]Coco Scrapers Synced[/COLOR]'.format(name), {'name': ext}, icon=icon, description='Your External Provider Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                elif 'gears' in str(auser).lower():
                    directory.add_file('{0} - [COLOR springgreen]Gears Scrapers Synced[/COLOR]'.format(name), {'name': ext}, icon=icon, description='Your External Provider Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                elif 'magneto' in str(auser).lower():
                    directory.add_file('{0} - [COLOR springgreen]Magneto Scrapers Synced[/COLOR]'.format(name), {'name': ext}, icon=icon, description='Your External Provider Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                elif 'viper' in str(auser).lower():
                    if name == 'Fen':
                        directory.add_file('{0} - [COLOR springgreen]Viper Scrapers Synced[/COLOR]'.format(name), {'name': ext}, icon=icon, description='Your External Provider Authorizations\n\nGears Scrapers - Not Supported\nMagento Scrapers - Not Supported', fanart=fanart, themeit=CONFIG.THEME2)
                    else:
                        directory.add_file('{0} - [COLOR springgreen]Viper Scrapers Synced[/COLOR]'.format(name), {'name': ext}, icon=icon, description='Your External Provider Authorizations', fanart=fanart, themeit=CONFIG.THEME2)
                if name == 'Fen Light':
                    if any(xbmc.getCondVisibility(f'System.HasAddon({addon_id})') for addon_id in (coco_plugin_id, gears_plugin_id, mag_plugin_id, viper_plugin_id)):
                        directory.add_file('[COLOR goldenrod]Change [COLOR gold]Scraper[/COLOR] Package[/COLOR]', {'mode': 'fenlt_scrapers', 'name': ext}, icon=icon, description='Change External Scraper Package', fanart=fanart, menu=menu)
                        directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_fenlt', 'name': 'Fen Light'}, icon=icon, description='Open add-on settings menu', fanart=fanart, menu=menu)
                    else:
                        directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_fenlt', 'name': 'Fen Light'}, icon=icon, description='Open add-on settings menu', fanart=fanart, menu=menu)
                elif name == 'The Gears':
                    if any(xbmc.getCondVisibility(f'System.HasAddon({addon_id})') for addon_id in (coco_plugin_id, gears_plugin_id, mag_plugin_id, viper_plugin_id)):
                        directory.add_file('[COLOR goldenrod]Change [COLOR gold]Scraper[/COLOR] Package[/COLOR]', {'mode': 'gears_scrapers', 'name': ext}, icon=icon, description='Change External Scraper Package', fanart=fanart, menu=menu)
                        directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_gears', 'name': 'Gears'}, icon=icon, description='Open add-on settings menu', fanart=fanart, menu=menu)
                    else:
                        directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_gears', 'name': 'Gears'}, icon=icon, description='Open add-on settings menu', fanart=fanart, menu=menu)
                elif name == 'Red Light':
                    if any(xbmc.getCondVisibility(f'System.HasAddon({addon_id})') for addon_id in (coco_plugin_id, gears_plugin_id, mag_plugin_id, viper_plugin_id)):
                        directory.add_file('[COLOR goldenrod]Change [COLOR gold]Scraper[/COLOR] Package[/COLOR]', {'mode': 'red_scrapers', 'name': ext}, icon=icon, description='Change External Scraper Package', fanart=fanart, menu=menu)
                        directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_red', 'name': 'Red Light'}, icon=icon, description='Open add-on settings menu', fanart=fanart, menu=menu)
                    else:
                        directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_red', 'name': 'Red Light'}, icon=icon, description='Open add-on settings menu', fanart=fanart, menu=menu)
                #elif name == 'Fen':
                    #if any(xbmc.getCondVisibility(f'System.HasAddon({addon_id})') for addon_id in (coco_plugin_id, gears_plugin_id, mag_plugin_id, viper_plugin_id)):
                        #directory.add_file('[COLOR goldenrod]Change [COLOR gold]Scraper[/COLOR] Package[/COLOR]', {'mode': 'fen_scrapers', 'name': ext}, icon=icon, description='Change External Scraper Package', fanart=fanart, menu=menu)
                        #directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_ext', 'name': ext}, icon=icon, description='Open add-on settings menu', fanart=fanart, menu=menu)
                    #else:
                        #directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_ext', 'name': ext}, icon=icon, description='Open add-on settings menu', fanart=fanart, menu=menu)
                elif name == 'Umbrella':
                    if any(xbmc.getCondVisibility(f'System.HasAddon({addon_id})') for addon_id in (coco_plugin_id, gears_plugin_id, mag_plugin_id, viper_plugin_id)):
                        directory.add_file('[COLOR goldenrod]Change [COLOR gold]Scraper[/COLOR] Package[/COLOR]', {'mode': 'umb_scrapers', 'name': ext}, icon=icon, description='Change External Scraper Package', fanart=fanart, menu=menu)
                        directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_ext', 'name': ext}, icon=icon, description='Open add-on settings menu', fanart=fanart, menu=menu)
                    else:
                        directory.add_file('[COLOR blue]Open [COLOR dodgerblue]{0}[/COLOR] Settings[/COLOR]'.format(name), {'mode': 'opensettings_ext', 'name': ext}, icon=icon, description='Open add-on settings menu', fanart=fanart, menu=menu)
                directory.add_separator()

def create_addon_data_menu(add='', name=''):
    menu_items = []
    menu_items.append((CONFIG.THEME1.format(name.title()), ' '))
    return menu_items
