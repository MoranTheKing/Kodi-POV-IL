# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcaddon, xbmcvfs
import sys
import os
import time
import json
import shutil
from acctmgr.modules import var
from acctmgr.modules import control
from acctmgr.modules import log_utils
from acctmgr.modules.db import debrid_db, torbox_db, easydebrid_db, easynews_db, offcloud_db, ext_db, trakt_db, mdblist_db, chk_auth_db

#Variables
joinPath = os.path.join
dialog = xbmcgui.Dialog()
exists = xbmcvfs.exists
execute = xbmc.executebuiltin
translatePath = xbmcvfs.translatePath
addon_path = translatePath('special://home/addons/')

#Icon Variables
amgr_icon	 = joinPath(control.iconsPath(), 'acctmgr.png')
trakt_icon	 = joinPath(control.iconsPath(), 'trakt.png')
mdb_icon	 = joinPath(control.iconsPath(), 'mdblist.png')
rd_icon		 = joinPath(control.iconsPath(), 'realdebrid.png')
pm_icon		 = joinPath(control.iconsPath(), 'premiumize.png')
ad_icon		 = joinPath(control.iconsPath(), 'alldebrid.png')
torbox_icon	 = joinPath(control.iconsPath(), 'torbox.png')
easyd_icon	 = joinPath(control.iconsPath(), 'easydebrid.png')
offcloud_icon    = joinPath(control.iconsPath(), 'offcloud.png')
easynews_icon    = joinPath(control.iconsPath(), 'easynews.png')
uhd_icon         = joinPath(control.iconsPath(), '4k.png')
fullhd_icon      = joinPath(control.iconsPath(), '1080p.png')
hd_icon          = joinPath(control.iconsPath(), '720p.png')

#HELPERS
def get_acctmgr():
	return xbmcaddon.Addon("script.module.acctmgr")

def addonInfo(key):
	try:
		return get_acctmgr().getAddonInfo(key)
	except Exception:
		log_utils.error(f"addonInfo({key}) failed")
		return ""

def addonIcon():
	return addonInfo('icon')

def addonName():
	return addonInfo('name')

def install_addon(plugin_id):
	if xbmc.getCondVisibility(f'System.HasAddon({plugin_id})'):
		return True
	execute(f'InstallAddon({plugin_id})')
	clicked = False
	start = time.time()
	timeout = 10
	while not isinstalled(plugin_id):
		if time.time() >= start + timeout:
			return False
		xbmc.sleep(500)
		if xbmc.getCondVisibility('Window.IsTopMost(yesnodialog)') and not clicked:
			execute('SendClick(yesnodialog, 11)')
			clicked = True
	return True

def isinstalled(addonid):
	query = '{ "jsonrpc": "2.0", "id": 1, "method": "Addons.GetAddonDetails", "params": { "addonid": "%s", "properties" : ["name", "thumbnail", "fanart", "enabled", "installed", "path", "dependencies"] } }' % addonid
	addonDetails = xbmc.executeJSONRPC(query)
	details_result = json.loads(addonDetails)
	if "error" in details_result:
		return False
	elif details_result['result']['addon']['installed'] == True:
		control.notification('AM Lite', 'Scraper Module Installed!', icon=amgr_icon)
		return True
	else:
		return False
    
control.set_active_monitor()

params = {}
for param in sys.argv[1:]:
	param = param.split('=')
	param_dict = dict([param])
	params = dict(params, **param_dict)

action = params.get('action')
query = params.get('query')

if action and not any(i in action for i in ['Auth', 'Revoke']):
	control.release_active_monitor()

if action is None:
	control.openSettings(query, "script.module.acctmgr")

#TRAKT
elif action == 'traktAcct':										# View account info
	from acctmgr.modules.auth import trakt
	result = trakt.Trakt().account_info_to_dialog()
	if result == -1:
		control.openSettings()

elif action == 'traktAuth':										# Authorize service
	if not control.setting('trakt.token') and exists(var.tk_sync_list):                             # Check if sync lists exists without trakt authorized
                control.delete_synclist()                                                               # Delete Trakt Sync List
	msg = 'You have not yet created a list of add-ons to authorize![CR]Would you like to create your list now?'
	if control.yesnoDialog(msg):
		from acctmgr.modules.sync import trakt_select                                           
		ok = trakt_select.tk_list().create_list()						# Create synclist
		if not ok:										# Safely exit if cancelled
			control.openSettings()
			raise SystemExit
		
		from acctmgr.modules.auth import trakt
		ok = trakt.Trakt().auth()                                                               # Authorize Trakt
		if not ok:                                                                              # Safely exit if cancelled
                        control.delete_synclist()                                                       # Delete Trakt Sync List
                        control.openSettings()
                        raise SystemExit

		get_acctmgr().setSetting("api.service", "true")						# Enable API/Patch service
		control.setSetting('api.stop', 'false')                                                 # Start API/Patch service
		xbmc.sleep(1500)

		from acctmgr.modules.sync import trakt_sync
		trakt_sync.Auth().trakt_auth(mode="auth")						# Sync add-ons (Auth mode = Remake Settings & Clear Trakt Cache)
		control.notification('Trakt', 'Sync in progress, please wait!', icon=trakt_icon)
		xbmc.sleep(1500)
		control.notification('Trakt', 'Sync Complete!', icon=trakt_icon)
		# Install TMDb Helper Trakt provider before force-closing Kodi; retry at startup on failure.
		from acctmgr.modules.sync import tmdbh_provider
		tmdbh_provider.complete_authorization_install()
		from acctmgr.modules.sync import tmdbh_choice
		tmdbh_choice.prompt_if_both()
		xbmc.sleep(3000)
		control.updates_off()                                                                   # Disable add-on auto-updates
		dialog.notification('Trakt', 'Force Closing Kodi!', trakt_icon, 3000)
		xbmc.sleep(3000)
		os._exit(1)                                                                             # Force close Kodi
	else:
                control.openSettings()
                raise SystemExit
               
elif action == 'traktReSync':                                                                           # Re-sync Trakt with installed add-ons
        from acctmgr.modules.sync import trakt_sync
        trakt_sync.Auth().trakt_auth(mode="auth")                                                       # Sync add-ons (Auth mode = Remake Settings & Clear Trakt Cache)
        control.notification('Trakt', 'Sync in progress, please wait!', icon=trakt_icon)
        xbmc.sleep(1500)
        
        control.notification('Trakt', 'Sync Complete!', icon=trakt_icon)
        # Install TMDb Helper Trakt provider before force-closing Kodi; retry at startup on failure.
        from acctmgr.modules.sync import tmdbh_provider
        tmdbh_provider.complete_authorization_install()
        from acctmgr.modules.sync import tmdbh_choice
        tmdbh_choice.prompt_if_both()
        xbmc.sleep(3000)
        dialog.notification('Trakt', 'Force Closing Kodi!', trakt_icon, 3000)
        xbmc.sleep(3000)
        os._exit(1)                                                                                     # Force close Kodi

elif action == 'traktEditSyncList':
	from acctmgr.modules.sync import trakt_select
	if not control.setting('trakt.token') and exists(var.tk_sync_list):                             # Check if sync lists exists without trakt auth
                control.delete_synclist()                                                               # Delete Trakt Sync List
	ok = trakt_select.tk_list().create_list()
	if not ok:
            control.openSettings()
            raise SystemExit
	xbmc.sleep(500)
	control.notification('Trakt', 'Sync in progress, please wait!', icon=trakt_icon)
	xbmc.sleep(2000)
	from acctmgr.modules.sync import trakt_sync
	trakt_sync.Auth().trakt_auth(mode="auth")                                                       # Sync add-ons (Auth mode = Remake Settings & Clear Trakt Cache)
	xbmc.sleep(1000)
	control.notification('Trakt', 'Sync Complete!', icon=trakt_icon)
	# Install TMDb Helper Trakt provider before force-closing Kodi; retry at startup on failure.
	from acctmgr.modules.sync import tmdbh_provider
	tmdbh_provider.complete_authorization_install()
	from acctmgr.modules.sync import tmdbh_choice
	tmdbh_choice.prompt_if_both()
	xbmc.sleep(3000)
	dialog.notification('Trakt', 'Force Closing Kodi!', trakt_icon, 3000)
	xbmc.sleep(3000)
	os._exit(1)                                                                                     # Force close Kodi
        
elif action == 'traktRevoke':                                                                           # Revoke add-ons
        control.closeAll()
        xbmc.sleep(300)
        yes = dialog.yesno('AM Lite', 'Are you sure?', 'No', 'Yes')
        if yes:
                control.setSetting('api.stop', 'true')                                                  # Stop API/Patch service
                xbmc.sleep(500)
                if exists(var.chk_fenlt):                                                               # Do NOTHING, if Fen Light is NOT installed and authorized
                        chk_auth_fenlt = chk_auth_db.chk_auth(var.fenlt_settings_db, "trakt.token")
                        if chk_auth_fenlt not in ('empty_setting', '', None):                           
                                trakt_db.revoke_trakt(var.fenlt_settings_db, 'Fen Light')               # Revoke Fen Light
                                xbmc.sleep(200)
                                control.restore_fenlt_tkclient()                                        # Restore default Trakt Client Key
                                xbmc.sleep(200)
                                control.restore_fenlt_tksecret()                                        # Restore default Trakt Secret Key
                                xbmc.sleep(200)
                                control.remake_fenlt_settings()                                         # Remake settings
                                xbmc.sleep(1000)
                if exists(var.chk_gears):                                                               # Do NOTHING, if The Gears is NOT installed and authorized
                        chk_auth_gears = chk_auth_db.chk_auth(var.gears_settings_db, "trakt.token")
                        if chk_auth_gears not in ('empty_setting', '', None):                           
                                trakt_db.revoke_trakt(var.gears_settings_db, 'The Gears')               # Revoke Gears
                                xbmc.sleep(200)
                                control.restore_gears_tkclient()                                        # Restore default Trakt Client Key
                                xbmc.sleep(200)
                                control.restore_gears_tksecret()                                        # Restore default Trakt Secret Key
                                xbmc.sleep(200)
                                control.remake_gears_settings()                                         # Remake settings
                                xbmc.sleep(1000)
                if exists(var.chk_red):                                                                 # Do NOTHING, if Red Light is NOT installed and authorized
                        chk_auth_red = chk_auth_db.chk_auth(var.red_settings_db, "trakt.token")
                        if chk_auth_red not in ('empty_setting', '', None):                           
                                trakt_db.revoke_trakt(var.red_settings_db, 'Red Light')                 # Revoke Red Light
                                xbmc.sleep(200)
                                control.restore_red_tkclient()                                          # Restore default Trakt Client Key
                                xbmc.sleep(200)
                                control.restore_red_tksecret()                                          # Restore default Trakt Secret Key
                                xbmc.sleep(200)
                                control.remake_red_settings()                                           # Remake settings
                                xbmc.sleep(1000)
                control.unpatch_all_services()                                                          # Unpatch services
                control.apply_default_trakt_api_keys()                                                  # Apply default API Keys to all add-ons
                control.delete_synclist()                                                               # Delete Trakt Sync List
                execute('RunPlugin("plugin://script.module.acctvwr/?mode=clear_tk")')                   # Revoke all add-ons with a settings.xml. Trakt Client/Secret are NOT revoked here for (POV, The Coalition, Dradis, Genocide) 
                control.updates_on()                                                                    # Enable add-on auto-updates
        else:
                control.openSettings()                                                                  # Open AM Lite settings
                
elif action == 'traktViewer':                                                                           # View authorizations
        control.closeAll()                                                                              # Required to close info dialog when opening AM Lite from programs menu
        xbmc.sleep(300)
        execute('ActivateWindow(10001,"plugin://script.module.acctvwr/?mode=trakt",return)')            # Activate view authorizations window

#MDBLIST
elif action == 'mdblistAuth':                                                                           
        from acctmgr.modules.auth.mdblist import MDBListAuth
        ok = MDBListAuth().auth()
        if not ok:                                                                                     
            raise SystemExit
        xbmc.sleep(1500)
        control.notification('MDBList', 'Sync in progress, please wait!', icon=mdb_icon)

        from acctmgr.modules.sync import mdblist_sync
        mdblist_sync.Auth().mdblist_auth()                                                              
        xbmc.sleep(200)
        control.setSetting('sync.mdb.service', 'true')                                                 
        control.notification('MDBList', 'Sync Complete!', icon=mdb_icon)
        # Authorization and synchronization are complete: install the MDBList
        # provider now, rather than waiting until the next Kodi startup.
        try:
            from acctmgr.modules.sync import tmdbh_mdblist
            tmdbh_mdblist.complete_authorization_install()
        except Exception as exc:
            xbmc.log('AM Lite [TMDb MDBList]: post-authorization setup failed: %s' % exc, xbmc.LOGERROR)
            control.setSetting('am_tmdbh_mdblist_install_pending', 'true')
            xbmcgui.Dialog().notification('AM Lite', 'TMDb Helper MDBList setup failed. Retrying next startup.', xbmcgui.NOTIFICATION_WARNING, 6500)
        from acctmgr.modules.sync import tmdbh_choice
        tmdbh_choice.prompt_if_both()
        xbmc.sleep(3000)
        control.openSettings()

elif action == 'mdblistReSync':
        control.notification('MDBList', 'Sync in progress, please wait!', icon=mdb_icon)
        xbmc.sleep(3000)
        from acctmgr.modules.sync import mdblist_sync
        control.function_monitor(mdblist_sync.Auth().mdblist_auth)
        xbmc.sleep(200)
        control.notification('MDBList', 'Sync Complete!', icon=mdb_icon)
        xbmc.sleep(3000)
        control.openSettings()
	
elif action == 'mdblistRevoke':
        control.closeAll()
        xbmc.sleep(300)
        yes = dialog.yesno('AM Lite', 'Are you sure?', 'No', 'Yes')
        if yes:
                if exists(var.chk_gears):
                        chk_auth_gears = chk_auth_db.chk_auth(var.gears_settings_db, "mdblist.api_key")
                        if chk_auth_gears not in ('empty_setting', '', None):
                                mdblist_db.revoke_gears(var.gears_settings_db)
                                xbmc.sleep(200)
                                control.remake_gears_settings()
                                xbmc.sleep(1000)
                if exists(var.chk_red):
                        chk_auth_red = chk_auth_db.chk_auth(var.red_settings_db, "mdblist.token")
                        if chk_auth_red not in ('empty_setting', '', None):
                                mdblist_db.revoke_redlight(var.red_settings_db)
                                xbmc.sleep(200)
                                control.remake_red_settings()
                                xbmc.sleep(1000)
                try:
                    json_query = xbmc.executeJSONRPC(
                        '{"jsonrpc":"2.0","method":"Settings.GetSettingValue","params":{"setting":"lookandfeel.skin"},"id":1}'
                    )
                    json_query = json.loads(json_query)

                    skin_chk = ""
                    if "result" in json_query and "value" in json_query["result"]:
                        skin_chk = json_query["result"]["value"]

                    # FENtastic
                    if skin_chk == "skin.fentastic" and xbmcvfs.exists(var.chk_fentastic) and xbmcvfs.exists(var.chkset_fentastic):
                        skin = xbmcaddon.Addon("skin.fentastic")
                        current_key = skin.getSetting("mdblist_api_key")

                        if current_key:
                            xbmc.executebuiltin('Skin.Reset(mdblist_api_key)')
                            xbmc.log("AM Lite: MDBList revoked from FENtastic", xbmc.LOGINFO)

                    # Nimbus
                    elif skin_chk == "skin.nimbus" and xbmcvfs.exists(var.chk_nimbus) and xbmcvfs.exists(var.chkset_nimbus):
                        skin = xbmcaddon.Addon("skin.nimbus")
                        current_key = skin.getSetting("mdblist_api_key")

                        if current_key:
                            xbmc.executebuiltin('Skin.Reset(mdblist_api_key)')
                            xbmc.log("AM Lite: MDBList revoked from Nimbus", xbmc.LOGINFO)

                except Exception as e:
                    log_utils.error(f"Skin MDBList Revoke Failed: {e}")
                    
                try:
                    from acctmgr.modules.sync import tmdbh_mdblist
                    tmdbh_mdblist.revoke()
                except Exception as exc:
                    xbmc.log('AM Lite: TMDb MDBList revoke failed: %s' % exc, xbmc.LOGERROR)
                execute('RunPlugin("plugin://script.module.acctvwr/?mode=clear_mdb")')
                dialog.notification('MDBList', 'All Add-ons Revoked!', mdb_icon, 3000)
                xbmc.sleep(3000)
                control.openSettings()
        else:
                control.openSettings()

elif action == 'mdblistViewer':
        control.closeAll()
        xbmc.sleep(300)
        execute('ActivateWindow(10001,"plugin://script.module.acctvwr/?mode=mdblist",return)')
    
#REAL-DEBRID
elif action == 'realdebridAcct':                                                                        # View account info
	from acctmgr.modules.auth import realdebrid
	result = realdebrid.RealDebrid().account_info_to_dialog()
	if result == -1:
		control.openSettings()

elif action == 'realdebridAuth':                                                                        # Authorize service
        from acctmgr.modules.auth import realdebrid
        ok = realdebrid.RealDebrid().auth()                                                             # Authorize
        if not ok:                                                                                      # Safely exit auth process if cancelled
            raise SystemExit
        xbmc.sleep(1500)
        control.notification('Real-Debrid', 'Sync in progress, please wait!', icon=rd_icon)

        from acctmgr.modules.sync import debrid_rd
        debrid_rd.Auth().realdebrid_auth()                                                              # Sync all add-ons
        xbmc.sleep(200)
        control.setSetting('sync.rd.service', 'true')                                                   # Enable sync startup service
        control.notification('Real-Debrid', 'Sync Complete!', icon=rd_icon)
        xbmc.sleep(3000)
        control.openSettings()                                                                          # Open AM Lite settings

elif action == 'realdebridReSync':                                                                      # Re-sync Real-Debrid with installed add-ons
        control.notification('Real-Debrid', 'Sync in progress, please wait!', icon=rd_icon)
        xbmc.sleep(3000)
        from acctmgr.modules.sync import debrid_rd
        control.function_monitor(debrid_rd.Auth().realdebrid_auth)                                      # Re-sync add-ons
        xbmc.sleep(200)
        control.notification('Real-Debrid', 'Sync Complete!', icon=rd_icon)
        xbmc.sleep(3000)
        control.openSettings()
                
elif action == 'realdebridRevoke':                                                                      # Revoke add-ons
        control.closeAll()
        xbmc.sleep(300)
        yes = dialog.yesno('AM Lite', 'Are you sure?', 'No', 'Yes')
        if yes:
                if exists(var.chk_fenlt):                                                               # Do nothing if Fen Light is NOT installed and authorized
                        chk_auth_fenlt = chk_auth_db.chk_auth(var.fenlt_settings_db, "rd.token")
                        if chk_auth_fenlt not in ('empty_setting', '', None):         
                                debrid_db.revoke_rd(var.fenlt_settings_db)                              # Revoke Fen Light
                                xbmc.sleep(200)
                                control.remake_fenlt_settings()                                         # Remake settings
                                xbmc.sleep(1000)
                if exists(var.chk_gears) :                                                              # Do nothing if Gears is NOT installed and authorized
                        chk_auth_gears = chk_auth_db.chk_auth(var.gears_settings_db, "rd.token")
                        if chk_auth_gears not in ('empty_setting', '', None):         
                                debrid_db.revoke_rd(var.gears_settings_db)                              # Revoke Gears
                                xbmc.sleep(200)
                                control.remake_gears_settings()                                         # Remake settings
                                xbmc.sleep(1000)
                if exists(var.chk_red) :                                                                # Do nothing if Gears is NOT installed and authorized
                        chk_auth_red = chk_auth_db.chk_auth(var.red_settings_db, "rd.token")
                        if chk_auth_red not in ('empty_setting', '', None):         
                                debrid_db.revoke_rd(var.red_settings_db)                                # Revoke Gears
                                xbmc.sleep(200)
                                control.remake_red_settings()                                           # Remake settings
                                xbmc.sleep(1000)
                execute('RunPlugin("plugin://script.module.acctvwr/?mode=clear_rd")')                   # Revoke all add-ons with a settings.xml
                dialog.notification('Real-Debrid', 'All Add-ons Revoked!', rd_icon, 3000)
                xbmc.sleep(3000)
                control.openSettings()                                                                  # Open AM Lite settings               
        else:
                control.openSettings()

elif action == 'realdebridViewer':                                                                      # View authorizations
        control.closeAll()
        xbmc.sleep(300)
        execute('ActivateWindow(10001,"plugin://script.module.acctvwr/?mode=realdebrid",return)')       # Activate view authorizations window

#PREMIUMIZE
elif action == 'premiumizeAcct':
	from acctmgr.modules.auth import premiumize
	result = premiumize.Premiumize().account_info_to_dialog()
	if result == -1:
		control.openSettings()

elif action == 'premiumizeAuth':
        from acctmgr.modules.auth import premiumize
        ok = premiumize.Premiumize().auth()
        if not ok:
            control.openSettings()
            raise SystemExit
        xbmc.sleep(1500)
        control.notification('Premiumize', 'Sync in progress, please wait!', icon=pm_icon)

        from acctmgr.modules.sync import debrid_pm
        debrid_pm.Auth().premiumize_auth()
        xbmc.sleep(200)
        control.setSetting('sync.pm.service', 'true')
        control.notification('Premiumize', 'Sync Complete!', icon=pm_icon)
        xbmc.sleep(3000)
        control.openSettings()

elif action == 'premiumizeReSync':
        control.notification('Premiumize', 'Sync in progress, please wait!', icon=pm_icon)
        xbmc.sleep(3000)
        from acctmgr.modules.sync import debrid_pm
        control.function_monitor(debrid_pm.Auth().premiumize_auth)
        xbmc.sleep(200)
        control.notification('Premiumize', 'Sync Complete!', icon=pm_icon)
        xbmc.sleep(3000)
        control.openSettings()
	
elif action == 'premiumizeRevoke':
        control.closeAll()
        xbmc.sleep(300)
        yes = dialog.yesno('AM Lite', 'Are you sure?', 'No', 'Yes')
        if yes:
                if exists(var.chk_fenlt):
                        chk_auth_fenlt = chk_auth_db.chk_auth(var.fenlt_settings_db, "pm.token")
                        if chk_auth_fenlt not in ('empty_setting', '', None):
                                debrid_db.revoke_pm(var.fenlt_settings_db)                                                           
                                xbmc.sleep(200)
                                control.remake_fenlt_settings()                           
                                xbmc.sleep(1000)
                if exists(var.chk_gears):
                        chk_auth_gears = chk_auth_db.chk_auth(var.gears_settings_db, "pm.token")
                        if chk_auth_gears not in ('empty_setting', '', None):
                                debrid_db.revoke_pm(var.gears_settings_db)                                                            
                                xbmc.sleep(200)
                                control.remake_gears_settings()                           
                                xbmc.sleep(1000)
                if exists(var.chk_red):
                        chk_auth_red = chk_auth_db.chk_auth(var.red_settings_db, "pm.token")
                        if chk_auth_red not in ('empty_setting', '', None):
                                debrid_db.revoke_pm(var.red_settings_db)                                                            
                                xbmc.sleep(200)
                                control.remake_red_settings()                           
                                xbmc.sleep(1000)
                execute('RunPlugin("plugin://script.module.acctvwr/?mode=clear_pm")')
                dialog.notification('Premiumize', 'All Add-ons Revoked!', pm_icon, 3000)
                xbmc.sleep(3000)
                control.openSettings()
        else:
                control.openSettings()

elif action == 'premiumizeViewer':
        control.closeAll()
        xbmc.sleep(300)
        execute('ActivateWindow(10001,"plugin://script.module.acctvwr/?mode=premiumize",return)')

#ALL-DEBRID
elif action == 'alldebridAcct':
	from acctmgr.modules.auth import alldebrid
	result = alldebrid.AllDebrid().account_info_to_dialog()
	if result == -1:
		control.openSettings()

elif action == 'alldebridAuth':
        from acctmgr.modules.auth import alldebrid
        ok = alldebrid.AllDebrid().auth()
        if not ok:
            control.openSettings()
            raise SystemExit
        xbmc.sleep(1500)
        control.notification('All-Debrid', 'Sync in progress, please wait!', icon=ad_icon)

        from acctmgr.modules.sync import debrid_ad
        debrid_ad.Auth().alldebrid_auth()
        xbmc.sleep(200)
        control.setSetting('sync.ad.service', 'true')
        control.notification('All-Debrid', 'Sync Complete!', icon=ad_icon)
        xbmc.sleep(3000)
        control.openSettings()

elif action == 'alldebridReSync':
        control.notification('All-Debrid', 'Sync in progress, please wait!', icon=ad_icon)
        xbmc.sleep(3000)
        from acctmgr.modules.sync import debrid_ad
        control.function_monitor(debrid_ad.Auth().alldebrid_auth)
        xbmc.sleep(200)
        control.notification('All-Debrid', 'Sync Complete!', icon=ad_icon)
        xbmc.sleep(3000)
        control.openSettings()

elif action == 'alldebridRevoke':
        control.closeAll()
        xbmc.sleep(300)
        yes = dialog.yesno('AM Lite', 'Are you sure?', 'No', 'Yes')
        if yes:
                if exists(var.chk_fenlt):
                        chk_auth_fenlt = chk_auth_db.chk_auth(var.fenlt_settings_db, "ad.token")
                        if chk_auth_fenlt not in ('empty_setting', '', None):
                                debrid_db.revoke_ad(var.fenlt_settings_db)                                                           
                                xbmc.sleep(200)
                                control.remake_fenlt_settings()                           
                                xbmc.sleep(1000)
                if exists(var.chk_gears):
                        chk_auth_gears = chk_auth_db.chk_auth(var.gears_settings_db, "ad.token")
                        if chk_auth_gears not in ('empty_setting', '', None):
                                debrid_db.revoke_ad(var.gears_settings_db)                                                            
                                xbmc.sleep(200)
                                control.remake_gears_settings()                           
                                xbmc.sleep(1000)
                if exists(var.chk_red):
                        chk_auth_red = chk_auth_db.chk_auth(var.red_settings_db, "ad.token")
                        if chk_auth_red not in ('empty_setting', '', None):
                                debrid_db.revoke_ad(var.red_settings_db)                                                            
                                xbmc.sleep(200)
                                control.remake_red_settings()                           
                                xbmc.sleep(1000)
                execute('RunPlugin("plugin://script.module.acctvwr/?mode=clear_ad")')
                dialog.notification('All-Debrid', 'All Add-ons Revoked!', ad_icon, 3000)
                xbmc.sleep(3000)
                control.openSettings()
        else:
                control.openSettings()

elif action == 'alldebridViewer':
        control.closeAll()
        xbmc.sleep(300)
        execute('ActivateWindow(10001,"plugin://script.module.acctvwr/?mode=alldebrid",return)')

#EASY DEBRID
elif action == 'easydebridAuth':
        from acctmgr.modules.auth import easydebrid
        ok = easydebrid.Easydebrid().auth()
        if not ok:
            control.openSettings()
            raise SystemExit
        xbmc.sleep(1500)
        control.notification('Easy Debrid', 'Sync in progress, please wait!', icon=easyd_icon)

        from acctmgr.modules.sync import easydebrid_sync
        easydebrid_sync.Auth().easydebrid_auth()
        xbmc.sleep(200)
        control.setSetting('sync.ed.service', 'true')
        control.notification('Easy Debrid', 'Sync Complete!', icon=easyd_icon)
        xbmc.sleep(3000)
        control.openSettings()

elif action == 'easydebridReSync':
        control.notification('Easy Debrid', 'Sync in progress, please wait!', icon=easyd_icon)
        xbmc.sleep(3000)
        from acctmgr.modules.sync import easydebrid_sync
        control.function_monitor(easydebrid_sync.Auth().easydebrid_auth)
        xbmc.sleep(200)
        control.notification('Easy Debrid', 'Sync Complete!', icon=easyd_icon)
        xbmc.sleep(3000)
        control.openSettings()

elif action == 'easydebridRevoke':
        control.closeAll()
        xbmc.sleep(300)
        yes = dialog.yesno('AM Lite', 'Are you sure?', 'No', 'Yes')
        if yes:
                if exists(var.chk_fenlt):
                        chk_auth_fenlt = chk_auth_db.chk_auth(var.fenlt_settings_db, "ed.token")
                        if chk_auth_fenlt not in ('empty_setting', '', None):
                                easydebrid_db.revoke(var.fenlt_settings_db)                                                           
                                xbmc.sleep(200)
                                control.remake_fenlt_settings()                           
                                xbmc.sleep(1000)
                if exists(var.chk_gears):
                        chk_auth_gears = chk_auth_db.chk_auth(var.gears_settings_db, "ed.token")
                        if chk_auth_gears not in ('empty_setting', '', None):
                                easydebrid_db.revoke(var.gears_settings_db)                                                            
                                xbmc.sleep(200)
                                control.remake_gears_settings()                           
                                xbmc.sleep(1000)
                execute('RunPlugin("plugin://script.module.acctvwr/?mode=clear_ed")')
                dialog.notification('Easy Debrid', 'All Add-ons Revoked!', easyd_icon, 3000)
                xbmc.sleep(3000)
                control.openSettings()
        else:
                control.openSettings()
        
elif action == 'easydebridViewer':
        control.closeAll()
        xbmc.sleep(300)
        execute('ActivateWindow(10001,"plugin://script.module.acctvwr/?mode=easydebrid",return)')
        
#TORBOX
elif action == 'torboxAcct':										# View account info
	from acctmgr.modules.auth import torbox
	result = torbox.Torbox().account_info_to_dialog()
	if result == -1:
		control.openSettings()

elif action == 'torboxAuth':
        from acctmgr.modules.auth import torbox
        ok = torbox.Torbox().auth()
        if not ok:
            control.openSettings()
            raise SystemExit
        xbmc.sleep(1500)
        control.notification('TorBox', 'Sync in progress, please wait!', icon=torbox_icon)

        from acctmgr.modules.sync import torbox_sync
        torbox_sync.Auth().torbox_auth()
        xbmc.sleep(200)
        control.setSetting('sync.tb.service', 'true')
        control.notification('TorBox', 'Sync Complete!', icon=torbox_icon)
        xbmc.sleep(3000)
        control.openSettings()
	
elif action == 'torboxReSync':
        control.notification('TorBox', 'Sync in progress, please wait!', icon=torbox_icon)
        xbmc.sleep(3000)
        from acctmgr.modules.sync import torbox_sync
        control.function_monitor(torbox_sync.Auth().torbox_auth)
        xbmc.sleep(200)
        control.notification('TorBox', 'Sync Complete!', icon=torbox_icon)
        xbmc.sleep(3000)
        control.openSettings()

elif action == 'torboxRevoke':
        control.closeAll()
        xbmc.sleep(300)
        yes = dialog.yesno('AM Lite', 'Are you sure?', 'No', 'Yes')
        if yes:
                if exists(var.chk_fenlt):
                        chk_auth_fenlt = chk_auth_db.chk_auth(var.fenlt_settings_db, "tb.token")
                        if chk_auth_fenlt not in ('empty_setting', '', None):
                                torbox_db.revoke(var.fenlt_settings_db)                                                           
                                xbmc.sleep(200)
                                control.remake_fenlt_settings()                           
                                xbmc.sleep(1000)
                if exists(var.chk_gears):
                        chk_auth_gears = chk_auth_db.chk_auth(var.gears_settings_db, "tb.token")
                        if chk_auth_gears not in ('empty_setting', '', None):
                                torbox_db.revoke(var.gears_settings_db)                                                            
                                xbmc.sleep(200)
                                control.remake_gears_settings()                           
                                xbmc.sleep(1000)
                if exists(var.chk_red):
                        chk_auth_red = chk_auth_db.chk_auth(var.red_settings_db, "tb.token")
                        if chk_auth_red not in ('empty_setting', '', None):
                                torbox_db.revoke(var.red_settings_db)                                                            
                                xbmc.sleep(200)
                                control.remake_red_settings()                           
                                xbmc.sleep(1000)
                execute('RunPlugin("plugin://script.module.acctvwr/?mode=clear_tb")')
                dialog.notification('TorBox', 'All Add-ons Revoked!', torbox_icon, 3000)
                xbmc.sleep(3000)
                control.openSettings()
        else:
                control.openSettings()
        
elif action == 'torboxViewer':
        control.closeAll()
        xbmc.sleep(300)
        execute('ActivateWindow(10001,"plugin://script.module.acctvwr/?mode=torbox",return)')
                
#OFFCLOUD
elif action == 'offcloudAuth':
        from acctmgr.modules.auth import offcloud
        ok = offcloud.Offcloud().auth()
        if not ok:
            control.openSettings()
            raise SystemExit
        xbmc.sleep(1500)
        control.notification('OffCloud', 'Sync in progress, please wait!', icon=offcloud_icon)

        from acctmgr.modules.sync import offcloud_sync
        offcloud_sync.Auth().offcloud_auth()
        xbmc.sleep(200)
        control.setSetting('sync.oc.service', 'true')
        control.notification('OffCloud', 'Sync Complete!', icon=offcloud_icon)
        xbmc.sleep(3000)
        control.openSettings()

elif action == 'offcloudReSync':
        control.notification('OffCloud', 'Sync in progress, please wait!', icon=offcloud_icon)
        xbmc.sleep(3000)
        from acctmgr.modules.sync import offcloud_sync
        control.function_monitor(offcloud_sync.Auth().offcloud_auth)
        xbmc.sleep(200)
        control.notification('OffCloud', 'Sync Complete!', icon=offcloud_icon)
        xbmc.sleep(3000)
        control.openSettings()

elif action == 'offcloudRevoke':
        control.closeAll()
        xbmc.sleep(300)
        yes = dialog.yesno('AM Lite', 'Are you sure?', 'No', 'Yes')
        if yes:
                if exists(var.chk_fenlt):
                        chk_auth_fenlt = chk_auth_db.chk_auth(var.fenlt_settings_db, "oc.token")
                        if chk_auth_fenlt not in ('empty_setting', '', None):
                                offcloud_db.revoke(var.fenlt_settings_db)                                                           
                                xbmc.sleep(200)
                                control.remake_fenlt_settings()                           
                                xbmc.sleep(1000)
                if exists(var.chk_gears):
                        chk_auth_gears = chk_auth_db.chk_auth(var.gears_settings_db, "oc.token")
                        if chk_auth_gears not in ('empty_setting', '', None):
                                offcloud_db.revoke(var.gears_settings_db)                                                            
                                xbmc.sleep(200)
                                control.remake_gears_settings()                           
                                xbmc.sleep(1000)
                execute('RunPlugin("plugin://script.module.acctvwr/?mode=clear_oc")')
                dialog.notification('OffCloud', 'All Add-ons Revoked!', offcloud_icon, 3000)
                xbmc.sleep(3000)
                control.openSettings()
        else:
                control.openSettings()
        
elif action == 'offcloudViewer':
        control.closeAll()
        xbmc.sleep(300)
        execute('ActivateWindow(10001,"plugin://script.module.acctvwr/?mode=offcloud",return)')

#EASYNEWS
elif action == 'easynewsAuth':
        from acctmgr.modules.auth import easynews
        ok = easynews.Easynews().auth()
        if not ok:
            control.openSettings()
            raise SystemExit
        xbmc.sleep(1500)
        control.notification('Easynews', 'Sync in progress, please wait!', icon=easynews_icon)

        from acctmgr.modules.sync import easynews_sync
        easynews_sync.Auth().easynews_auth()
        xbmc.sleep(200)
        control.setSetting('sync.en.service', 'true')
        control.notification('Easynews', 'Sync Complete!', icon=easynews_icon)
        xbmc.sleep(3000)
        control.openSettings()

elif action == 'easynewsReSync':
        control.notification('Easynews', 'Sync in progress, please wait!', icon=easynews_icon)
        xbmc.sleep(3000)
        from acctmgr.modules.sync import easynews_sync
        control.function_monitor(easynews_sync.Auth().easynews_auth)
        xbmc.sleep(200)
        control.notification('Easynews', 'Sync Complete!', icon=easynews_icon)
        xbmc.sleep(3000)
        control.openSettings()

elif action == 'easynewsRevoke':
        control.closeAll()
        xbmc.sleep(300)
        yes = dialog.yesno('AM Lite', 'Are you sure?', 'No', 'Yes')
        if yes:
                if exists(var.chk_fenlt):
                        easynews_db.revoke(var.fenlt_settings_db)                                                           
                        xbmc.sleep(200)
                        control.remake_fenlt_settings()                           
                        xbmc.sleep(1000)
                if exists(var.chk_gears):
                        easynews_db.revoke(var.gears_settings_db)                                                            
                        xbmc.sleep(200)
                        control.remake_gears_settings()                           
                        xbmc.sleep(1000)
                if exists(var.chk_red):
                        easynews_db.revoke(var.red_settings_db)                                                            
                        xbmc.sleep(200)
                        control.remake_red_settings()                           
                        xbmc.sleep(1000)
                execute('RunPlugin("plugin://script.module.acctvwr/?mode=clear_en")')
                dialog.notification('Easynews', 'All Add-ons Revoked!', easynews_icon, 3000)
                xbmc.sleep(3000)
                control.openSettings()
        else:
                control.openSettings()
        
elif action == 'easynewsViewer':
        control.closeAll()
        xbmc.sleep(300)
        execute('ActivateWindow(10001,"plugin://script.module.acctvwr/?mode=easynews",return)')
             
#REVOKE ALL SERVICES
elif action == 'allRevoke':
        token_keys = (
                'trakt.token',
                'mdblist.apikey',
                'mdblist.token',
                'realdebrid.token',
                'premiumize.token',
                'alldebrid.token',
                'torbox.token',
                'easydebrid.token',
                'offcloud.token',
                'easynews.username',
                'easynews.password'
        )

        has_any_auth = any((control.setting(k) or '') != '' for k in token_keys)

        if not has_any_auth:
                dialog.ok('AM Lite', 'No services are authorized. You have no data to revoke!')
                raise SystemExit

        yes = dialog.yesno(
                'AM Lite',
                'WARNING! This will completely wipe all settings applied by AM Lite. Would you like to proceed?',
                nolabel='Cancel',
                yeslabel='Proceed'
        )
        if not yes:
                raise SystemExit

        trakt_authed = bool(control.setting('trakt.token'))
        
        def revoke_all_for_addon(settings_db, addon_name=None):
                if control.setting('mdblist.token') and addon_name == 'Red Light':
                        mdblist_db.revoke_redlight(settings_db)

                if control.setting('mdblist.apikey') and addon_name == 'The Gears':
                        mdblist_db.revoke_gears(settings_db)

                if trakt_authed and addon_name:
                        trakt_db.revoke_trakt(settings_db, addon_name)

                if trakt_authed and addon_name == 'Fen Light':
                        control.restore_fenlt_tkclient()
                        xbmc.sleep(200)
                        control.restore_fenlt_tksecret()
                        xbmc.sleep(200)
                        control.remake_fenlt_settings()
                        xbmc.sleep(500)

                elif trakt_authed and addon_name == 'The Gears':
                        control.restore_gears_tkclient()
                        xbmc.sleep(200)
                        control.restore_gears_tksecret()
                        xbmc.sleep(200)
                        control.remake_gears_settings()
                        xbmc.sleep(500)

                elif trakt_authed and addon_name == 'Red Light':
                        control.restore_red_tkclient()
                        xbmc.sleep(200)
                        control.restore_red_tksecret()
                        xbmc.sleep(200)
                        control.remake_red_settings()
                        xbmc.sleep(500)
                        
                if control.setting('realdebrid.token'):
                        debrid_db.revoke_rd(settings_db)
                        
                if control.setting('premiumize.token'):
                        debrid_db.revoke_pm(settings_db)
                        
                if control.setting('alldebrid.token'):
                        debrid_db.revoke_ad(settings_db)
                        
                if control.setting('torbox.token'):
                        torbox_db.revoke(settings_db)
                        
                if control.setting('easydebrid.token'):
                        easydebrid_db.revoke(settings_db)
                        
                if control.setting('offcloud.token'):
                        offcloud_db.revoke(settings_db)
                        
                if control.setting('easynews.username') or control.setting('easynews.password'):
                        easynews_db.revoke(settings_db)

        control.setSetting('api.stop', 'true')
        xbmc.sleep(500)
        control.closeAll()
        xbmc.sleep(300)

        # Revoke Fen Light / The Gears / Red Light
        addons = (
                (var.chk_fenlt, var.fenlt_settings_db, var.fenlt_name),
                (var.chk_gears, var.gears_settings_db, var.gears_name),
                (var.chk_red, var.red_settings_db, var.red_name),
        )

        for chk, settings_db, addon_name in addons:
                if exists(chk):
                        revoke_all_for_addon(settings_db, addon_name)
                        xbmc.sleep(200)

        if control.setting('trakt.token'):
                control.unpatch_all_services()
                control.apply_default_trakt_api_keys() # Apply default API keys to all add-ons
                control.delete_synclist()
                control.updates_on()

        execute('RunPlugin("plugin://script.module.acctvwr/?mode=wipeclean")')  # Trakt Client/Secret are NOT revoked for (POV, The Coalition, Dradis, Genocide)

#EXTERNAL PROVIDERS
elif action == 'extInstall':
        for plugin_id, setting_id in (
            (var.coco_plugin_id,  "ext.provider_coco"),
            (var.gears_plugin_id,  "ext.provider_gears"),
            (var.mag_plugin_id,   "ext.provider_mag"),
            (var.viper_plugin_id, "ext.provider_vip"),
        ):
            value = 'true' if xbmc.getCondVisibility(f'System.HasAddon({plugin_id})') else 'false'
            get_acctmgr().setSetting(setting_id, value)
            
        scrapers = [('Coco Scrapers', var.coco_plugin_id),('Gears Scrapers', var.gears_plugin_id),('Magneto Scrapers', var.mag_plugin_id),('Viper Scrapers', var.viper_plugin_id),]

        not_installed = []
        for name, plugin_id in scrapers:
            if not xbmc.getCondVisibility(f'System.HasAddon({plugin_id})'):
                not_installed.append((name, plugin_id))

        if not not_installed:
            dialog.notification('AM Lite', 'All supported scraper modules are installed!', icon=amgr_icon)
            xbmc.sleep(2000)
            control.openSettings()
            raise SystemExit

        labels = [name for name, _ in not_installed]

        selection = dialog.select('Choose Scraper Package', labels)
        if selection == -1:
            control.openSettings()
            raise SystemExit

        mapping = {'Coco Scrapers': 0,'Gears Scrapers': 1,'Magneto Scrapers': 2,'Viper Scrapers': 3,}
        
        selected_name, selected_id = not_installed[selection]
        
        selection = mapping[selected_name]
        
        if selection==0:
                scrapers = control.yesnoDialog('Are you sure?', heading=addonInfo('name'), nolabel='No', yeslabel='Yes' )
                if scrapers:
                        shutil.copytree(os.path.join(var.xmls, var.coco), os.path.join(addon_path, var.coco), dirs_exist_ok=True)
                        execute('UpdateLocalAddons')
                        clicked = False
                        execute('EnableAddon(repository.cocoscrapers)')
                        if xbmc.getCondVisibility('Window.IsTopMost(yesnodialog)') and not clicked:
                                execute('SendClick(yesnodialog, 11)')
                                clicked = True
                        xbmc.sleep(3000)
                        if not install_addon(var.coco_plugin_id):
                                control.notification('AM Lite', 'CocoScrapers failed to install!', icon=amgr_icon)
                                sys.exit()
                        else:
                                sync = control.yesnoDialog('How would you like to proceed?\n1. Sync this scraper package to all add-ons\n2. Configure add-ons manually?', heading=addonInfo('name'), nolabel='Configure', yeslabel='Sync' )
                                if sync:
                                        from acctmgr.modules.sync import ext_sync
                                        get_acctmgr().setSetting("ext.provider_coco", "true")
                                        control.notification('AM Lite', 'Sync in progress, please wait!', icon=amgr_icon)
                                        xbmc.sleep(1000)
                                        ext_sync.Auth_Coco()
                                        control.notification('AM Lite', 'Sync Complete!', icon=amgr_icon)
                                        xbmc.sleep(2000)
                                        control.openSettings()
                                else:
                                        get_acctmgr().setSetting("ext.provider_coco", "true")
                                        xbmc.sleep(300)
                                        control.closeAll()
                                        xbmc.sleep(300)
                                        execute('ActivateWindow(10001,"plugin://script.module.acctvwr/?mode=extscrapers",return)')
                else:
                        control.closeAll()
                        xbmc.sleep(200)
                        control.openSettings()
        if selection==1:
                scrapers = control.yesnoDialog('Are you sure?', heading=addonInfo('name'), nolabel='No', yeslabel='Yes' )
                if scrapers:
                        shutil.copytree(os.path.join(var.xmls, var.gears), os.path.join(addon_path, var.gears), dirs_exist_ok=True)
                        execute('UpdateLocalAddons')
                        clicked = False
                        execute('EnableAddon(repository.chainsrepo)')
                        if xbmc.getCondVisibility('Window.IsTopMost(yesnodialog)') and not clicked:
                                execute('SendClick(yesnodialog, 11)')
                                clicked = True
                        xbmc.sleep(3000)
                        if not install_addon(var.gears_plugin_id):
                                control.notification('AM Lite', 'GearsScrapers failed to install!', icon=amgr_icon)
                                xbmc.sleep(2000)
                                control.openSettings()
                                sys.exit()
                        else:
                                sync = control.yesnoDialog('How would you like to proceed?\n1. Sync this scraper package to all add-ons\n2. Configure add-ons manually?', heading=addonInfo('name'), nolabel='Configure', yeslabel='Sync' )
                                if sync:
                                        from acctmgr.modules.sync import ext_sync
                                        get_acctmgr().setSetting("ext.provider_gears", "true")
                                        control.notification('AM Lite', 'Sync in progress, please wait!', icon=amgr_icon)
                                        xbmc.sleep(1000)
                                        ext_sync.Auth_Gears()
                                        control.notification('AM Lite', 'Sync Complete!', icon=amgr_icon)
                                        xbmc.sleep(2000)
                                        control.openSettings()
                                else:
                                        get_acctmgr().setSetting("ext.provider_gears", "true")
                                        xbmc.sleep(300)
                                        control.closeAll()
                                        xbmc.sleep(300)
                                        execute('ActivateWindow(10001,"plugin://script.module.acctvwr/?mode=extscrapers",return)')
                else:
                        control.closeAll()
                        xbmc.sleep(200)
                        control.openSettings()
        elif selection==2:
                scrapers = control.yesnoDialog('Are you sure?', heading=addonInfo('name'), nolabel='No', yeslabel='Yes' )
                if scrapers:
                        shutil.copytree(os.path.join(var.xmls, var.mag), os.path.join(addon_path, var.mag), dirs_exist_ok=True)
                        execute('UpdateLocalAddons')
                        clicked = False
                        execute('EnableAddon(repository.kodifitzwell)')
                        if xbmc.getCondVisibility('Window.IsTopMost(yesnodialog)') and not clicked:
                                execute('SendClick(yesnodialog, 11)')
                                clicked = True
                        xbmc.sleep(3000)
                        if not install_addon(var.mag_plugin_id):
                                control.notification('AM Lite', 'Magneto Scrapers failed to install!', icon=amgr_icon)
                                xbmc.sleep(2000)
                                control.openSettings()
                                sys.exit()
                        else:
                                sync = control.yesnoDialog('How would you like to proceed?\n1. Sync this scraper package to all add-ons\n2. Configure add-ons manually?', heading=addonInfo('name'), nolabel='Configure', yeslabel='Sync' )
                                if sync:
                                        from acctmgr.modules.sync import ext_sync
                                        get_acctmgr().setSetting("ext.provider_mag", "true")
                                        control.notification('AM Lite', 'Sync in progress, please wait!', icon=amgr_icon)
                                        xbmc.sleep(1000)
                                        ext_sync.Auth_Mag()
                                        control.notification('AM Lite', 'Sync Complete!', icon=amgr_icon)
                                        xbmc.sleep(2000)
                                        control.openSettings()
                                else:
                                        get_acctmgr().setSetting("ext.provider_mag", "true")
                                        xbmc.sleep(300)
                                        control.closeAll()
                                        xbmc.sleep(300)
                                        execute('ActivateWindow(10001,"plugin://script.module.acctvwr/?mode=extscrapers",return)')
                else:
                        control.closeAll()
                        xbmc.sleep(200)
                        control.openSettings()
        elif selection==3:
                scrapers = control.yesnoDialog('Are you sure?', heading=addonInfo('name'), nolabel='No', yeslabel='Yes' )
                if scrapers:
                        shutil.copytree(os.path.join(var.xmls, var.viper), os.path.join(addon_path, var.viper), dirs_exist_ok=True)
                        execute('UpdateLocalAddons')
                        clicked = False
                        execute('EnableAddon(repository.oldsalt)')
                        if xbmc.getCondVisibility('Window.IsTopMost(yesnodialog)') and not clicked:
                                execute('SendClick(yesnodialog, 11)')
                                clicked = True
                        xbmc.sleep(3000)
                        if not install_addon(var.viper_plugin_id):
                                control.notification('AM Lite', 'Viper Scrapers failed to install!', icon=amgr_icon)
                                xbmc.sleep(2000)
                                control.openSettings()
                                sys.exit()
                        else:
                                sync = control.yesnoDialog('How would you like to proceed?\n1. Sync this scraper package to all add-ons\n2. Configure add-ons manually?', heading=addonInfo('name'), nolabel='Configure', yeslabel='Sync' )
                                if sync:
                                        from acctmgr.modules.sync import ext_sync
                                        get_acctmgr().setSetting("ext.provider_vip", "true")
                                        control.notification('AM Lite', 'Sync in progress, please wait!', icon=amgr_icon)
                                        xbmc.sleep(8000)
                                        ext_sync.Auth_Viper()
                                        control.notification('AM Lite', 'Sync Complete!', icon=amgr_icon)
                                        xbmc.sleep(2000)
                                        control.openSettings()
                                else:
                                        get_acctmgr().setSetting("ext.provider_vip", "true")
                                        xbmc.sleep(300)
                                        control.closeAll()
                                        xbmc.sleep(300)
                                        execute('ActivateWindow(10001,"plugin://script.module.acctvwr/?mode=extscrapers",return)')
                else:
                        control.closeAll()
                        xbmc.sleep(200)
                        control.openSettings()
        else:
                sys.exit()

elif action == 'extReSync':
        options = []
        actions = []

        # Menu
        if xbmcvfs.exists(var.chk_sc_coco):
                options.append('Coco Scrapers')
                actions.append('coco')
        if xbmcvfs.exists(var.chk_sc_gears):
                options.append('Gears Scrapers')
                actions.append('gears')
        if xbmcvfs.exists(var.chk_sc_mag):
                options.append('Magneto Scrapers')
                actions.append('mag')
        if xbmcvfs.exists(var.chk_sc_viper):
                options.append('Viper Scrapers')
                actions.append('viper')
                
        if not options:
                control.notification('AM Lite', 'No external scrapers installed!', icon=amgr_icon)
                raise SystemExit

        # Select Scraper Package
        choice = dialog.select('Select Scraper Package to Sync', options)
        if choice == -1:
                control.openSettings()
                raise SystemExit

        selected = actions[choice]
        from acctmgr.modules.sync import ext_sync

        # Coco Scrapers
        if selected == 'coco':
                get_acctmgr().setSetting("ext.provider_coco", "true")
                control.notification('AM Lite', 'Sync in progress, please wait!', icon=amgr_icon)
                xbmc.sleep(1500)
                ext_sync.Auth_Coco()
                xbmc.sleep(500)
                control.notification('AM Lite', 'Sync Complete!', icon=amgr_icon)
                xbmc.sleep(3000)
                control.openSettings()

        # Gears Scrapers
        elif selected == 'gears':
                get_acctmgr().setSetting("ext.provider_gears", "true")
                control.notification('AM Lite', 'Sync in progress, please wait!', icon=amgr_icon)
                xbmc.sleep(1500)
                ext_sync.Auth_Gears()
                xbmc.sleep(500)
                control.notification('AM Lite', 'Sync Complete!', icon=amgr_icon)
                xbmc.sleep(3000)
                control.openSettings()

        # Magneto Scrapers
        elif selected == 'mag':
                get_acctmgr().setSetting("ext.provider_mag", "true")
                control.notification('AM Lite', 'Sync in progress, please wait!', icon=amgr_icon)
                xbmc.sleep(1500)
                ext_sync.Auth_Mag()
                xbmc.sleep(500)
                control.notification('AM Lite', 'Sync Complete!', icon=amgr_icon)
                xbmc.sleep(3000)
                control.openSettings()

        # Viper Scrapers
        elif selected == 'viper':
                get_acctmgr().setSetting("ext.provider_vip", "true")
                control.notification('AM Lite', 'Sync in progress, please wait!', icon=amgr_icon)
                xbmc.sleep(1500)
                ext_sync.Auth_Viper()
                xbmc.sleep(500)
                control.notification('AM Lite', 'Sync Complete!', icon=amgr_icon)
                xbmc.sleep(3000)
                control.openSettings()
                
elif action == 'extViewer':
	if not any((exists(var.chk_fenlt), exists(var.chk_gears), exists(var.chk_umb), exists(var.chk_red))):
                control.notification('AM Lite', 'No supported add-ons installed!', icon=amgr_icon)
                raise SystemExit
	control.closeAll()
	xbmc.sleep(300)
	execute('ActivateWindow(Videos,"plugin://script.module.acctvwr/?mode=extscrapers",return)')

#MAXQL
elif action == 'setUHD':
        from acctmgr.modules.sync.maxql_sync import MaxQL
        MaxQL().set_res(var.QL_UHD)
        xbmc.sleep(500)
        control.notification('AM Lite', '4K Max Resolution Set!', icon=uhd_icon)
        xbmc.sleep(3000)
        control.openSettings()

elif action == 'setHD':
        from acctmgr.modules.sync.maxql_sync import MaxQL
        MaxQL().set_res(var.QL_HD)
        xbmc.sleep(500)
        control.notification('AM Lite', '1080P Max Resolution Set!', icon=fullhd_icon)
        xbmc.sleep(3000)
        control.openSettings()

elif action == 'setSD':
        from acctmgr.modules.sync.maxql_sync import MaxQL
        MaxQL().set_res(var.QL_SD)
        xbmc.sleep(500)
        control.notification('AM Lite', 'SD-720P Max Resolution Set!', icon=hd_icon)
        xbmc.sleep(3000)
        control.openSettings()

#AUTOPLAY
elif action == 'setDIR':
        from acctmgr.modules.sync.autoplay_sync import AutoPlay
        AutoPlay().set_playback(var.DIR)
        xbmc.sleep(500)
        control.notification('AM Lite', 'Source Select Set!', icon=amgr_icon)
        xbmc.sleep(3000)
        control.openSettings()

elif action == 'setAUTO':
        from acctmgr.modules.sync.autoplay_sync import AutoPlay
        AutoPlay().set_playback(var.AUTO)
        xbmc.sleep(500)
        control.notification('AM Lite', 'Autoplay Set!', icon=amgr_icon)
        xbmc.sleep(3000)
        control.openSettings()

#TMDB HELPER PLAYERS (Install)
elif action == 'setPLAYER':
        if not xbmcvfs.exists(var.chk_tmdbh):
                control.notification('AM Lite', 'TMdb Helper is NOT installed!', icon=amgr_icon)
                raise SystemExit
        from acctmgr.modules.auth import tmdbh_players
        tmdbh_players.install_tmdbh_players()
        xbmc.sleep(500)
        control.openSettings()

#TMDB HELPER PLAYERS (Remove)
elif action == 'delPLAYER':
        if not xbmcvfs.exists(var.chk_tmdbh):
                control.notification('AM Lite', 'TMdb Helper is NOT installed!', icon=amgr_icon)
                raise SystemExit
        from acctmgr.modules.auth import tmdbh_players
        tmdbh_players.delete_tmdbh_players()
        xbmc.sleep(500)
        control.openSettings()
        
#VIEW SUPPORTED ADD-ONS
elif action == 'ShowSupported_Trakt':
	from acctmgr.modules import changelog
	changelog.get_supported_trakt()

elif action == 'ShowSupported_MDBList':
	from acctmgr.modules import changelog
	changelog.get_supported_mdblist()
	
elif action == 'ShowSupported_Debrid':
	from acctmgr.modules import changelog
	changelog.get_supported_debrid()

elif action == 'ShowSupported_Easydebrid':
	from acctmgr.modules import changelog
	changelog.get_supported_easydebrid()
	
elif action == 'ShowSupported_Torbox':
	from acctmgr.modules import changelog
	changelog.get_supported_torbox()
	
elif action == 'ShowSupported_Offcloud':
	from acctmgr.modules import changelog
	changelog.get_supported_offcloud()

elif action == 'ShowSupported_Easynews':
	from acctmgr.modules import changelog
	changelog.get_supported_easynews()

elif action == 'ShowSupported_Ext_Scrapers':
	from acctmgr.modules import changelog
	changelog.get_supported_ext()

elif action == 'ShowSupported_Ext_Addons':
	from acctmgr.modules import changelog
	changelog.get_supported_ext_addons()

elif action == 'ShowSupported_MaxQL':
	from acctmgr.modules import changelog
	changelog.get_supported_maxql()

elif action == 'ShowSupported_Autoplay':
	from acctmgr.modules import changelog
	changelog.get_supported_autoplay()

#VIEW CHANGELOG	
elif action == 'ShowChangelog':
	from acctmgr.modules import changelog
	changelog.get_changelog()

#VIEW HELP
elif action == 'ShowHelp':
	from acctmgr.help import help
	help.get(params.get('name'))

elif action == 'ShowHelpLogin':
	from acctmgr.help import help
	help.get_login()

elif action == 'ShowHelpRestore':
	from acctmgr.help import help
	help.get_restore()

#LOG TOOLS
elif action == 'clearLogFile':
	from acctmgr.modules import log_utils
	cleared = log_utils.clear_logFile()
	if cleared == 'canceled': pass
	elif cleared: control.notification(message='Log File Successfully Cleared!')
	else: control.notification(message='Error clearing Log File, see kodi.log for more info')

elif action == 'viewLogFile':
	from acctmgr.modules import log_utils
	log_utils.view_LogFile()

elif action == 'uploadLogFile':
	from acctmgr.modules import log_utils
	log_utils.upload_LogFile()
