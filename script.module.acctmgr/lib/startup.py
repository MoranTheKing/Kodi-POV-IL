# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcaddon, xbmcvfs
import os
import re
import time
import json
import hashlib
import requests

from acctmgr.modules import var
from acctmgr.modules import control
from acctmgr.modules import log_utils

MONITOR = xbmc.Monitor()

def abort_requested():
	return MONITOR.abortRequested()

def am_masters():  # AM Lite token variables
	mdb_master_token = control.setting("mdblist.apikey")
	rd_master_token = control.setting("realdebrid.token")
	pm_master_token = control.setting("premiumize.token")
	ad_master_token = control.setting("alldebrid.token")
	tb_master_token = control.setting("torbox.token")
	oc_master_token = control.setting("offcloud.token")
	en_master_user = control.setting("easynews.username")
	en_master_pass = control.setting("easynews.password")

	return mdb_master_token, rd_master_token, pm_master_token, ad_master_token, tb_master_token, oc_master_token, en_master_user, en_master_pass

def ScraperCheck(): # Check for installed scraper packages and update AML settings accordingly
	for addon_id, setting_id in (
		('script.module.cocoscrapers',   "ext.provider_coco"),
                ('script.module.gearsscrapers',  "ext.provider_gears"),
		('script.module.magneto',        "ext.provider_mag"),
		('script.module.viperscrapers',  "ext.provider_vip"),
	):
		value = 'true' if xbmc.getCondVisibility(f'System.HasAddon({addon_id})') else 'false'
		control.setSetting(setting_id, value)

def am_trakt_startup_begin(): # Mark Trakt startup as NOT ready immediately on every Kodi startup.
	try:
		control.setSetting("am_trakt_ready", "false")
		control.setSetting("am_last_prepare", "0")
		xbmc.log('AM Lite: Trakt startup state set to NOT READY', xbmc.LOGINFO)
	except Exception:
		log_utils.error("AM Lite Trakt startup begin FAILED")

def am_trakt_startup_complete(): # Mark Trakt startup as READY only after refresh/sync has completed safely.
	try:
		control.setSetting("am_last_prepare", str(int(time.time())))
		control.setSetting("am_trakt_ready", "true")
		xbmc.log('AM Lite: Trakt startup state set to READY', xbmc.LOGINFO)
	except Exception:
		log_utils.error("AM Lite Trakt startup complete FAILED")

def am_trakt_startup_fail(): # Leave startup state as NOT ready when refresh/sync fails.
	try:
		control.setSetting("am_trakt_ready", "false")
		control.setSetting("am_last_prepare", "0")
		xbmc.log('AM Lite: Trakt startup FAILED - remaining NOT READY', xbmc.LOGINFO)
	except Exception:
		log_utils.error("AM Lite Trakt startup fail FAILED")

def startup_wait(timeout=30): # Wait until Kodi finishes loading addons/services
	start = time.time()

	while not abort_requested():
		if time.time() - start > timeout:
			break
		if MONITOR.waitForAbort(0.5):
			break

def get_trakt_token(): # Read current AM Lite token
	try:
		return control.setting('trakt.token') or ''
	except Exception:
		return ''

def ensure_defaults(): # Check if Trakt is authed. If not, ensure API keys/services are set to default.
	try:
		token = get_trakt_token()
		if not token:
			xbmc.log('AM Lite: No Trakt auth found - resetting services to defaults', xbmc.LOGINFO)
			control.unpatch_all_services()
			#control.apply_default_trakt_api_keys_db() # NO LONGER USED (See control.py)
			control.apply_default_trakt_api_keys()
			return False
		return True
	except Exception:
		log_utils.error("AM Lite ensure_defaults at startup FAILED")
		return False
	
def get_trakt_expires(): # Read trakt expires
	try:
		raw = control.setting('trakt.expires') or '0'
		expires = int(float(raw))
	except Exception:
		expires = 0

	now = int(time.time())

	if expires > 2000000000000:
		expires = int(expires / 1000)

	if 0 < expires < 1000000000:
		expires = now + expires

	if expires > 0:
		control.setSetting('trakt.expires', str(expires))

	return expires
def get_trakt_refresh_window(): # Set Trakt refresh window based on token lifetime
	try:
		expires_in = int(float(control.setting('trakt.expires_in') or 0))
	except Exception:
		expires_in = 0

	if expires_in > 86400:
		return 86400 # Use 24hr refresh window for longer-lived tokens

	return 4500 # Use 1.25hr refresh window for 24hr/legacy tokens


def trakt_refresh(): # Refresh Trakt token if expired or near expiry
	token = get_trakt_token()
	if not token:
		xbmc.log('AM Lite: No Trakt token present - skipping refresh', xbmc.LOGINFO)
		return 'missing'

	now = int(time.time())
	expires = get_trakt_expires()
	refresh_window = get_trakt_refresh_window()

	if expires > 0 and now < (expires - refresh_window): # Skip refresh if token is still valid outside refresh window
		return 'valid'

	xbmc.log('AM Lite: Trakt token expired or near expiry - refreshing', xbmc.LOGINFO)

	try:
		from acctmgr.modules.auth import trakt
		if not trakt.Trakt().refresh_token():
			xbmc.log('AM Lite: Trakt token refresh returned failure', xbmc.LOGERROR)
			return 'failed'
	except Exception:
		log_utils.error("Trakt token refresh FAILED")
		return 'failed'

	if MONITOR.waitForAbort(1.5): # Allow Kodi to flush updated settings
		return 'failed'

	new_token = get_trakt_token()
	new_expires = get_trakt_expires()

	if not new_token:
		xbmc.log('AM Lite: Trakt refresh completed but token is still blank', xbmc.LOGERROR)
		return 'failed'

	if new_expires > 0 and int(time.time()) >= (new_expires - 1800):
		xbmc.log('AM Lite: Trakt refresh completed but expiry is still invalid/near expiry', xbmc.LOGERROR)
		return 'failed'

	xbmc.log('AM Lite: Trakt token refreshed successfully', xbmc.LOGINFO)
	return 'refreshed'

def trakt_sync_pending(): # Persistent retry state survives Kodi restarts
	return control.setting('am_trakt_sync_pending') == 'true'


def set_trakt_sync_pending(pending):
	control.setSetting('am_trakt_sync_pending', 'true' if pending else 'false')


def startup_tk_sync(mode="refresh"): # Sync Trakt tokens to add-ons
	if not get_trakt_token():
		xbmc.log('AM Lite: Trakt sync skipped - no master token present', xbmc.LOGINFO)
		return False

	set_trakt_sync_pending(True)
	try:
		from acctmgr.modules.sync import trakt_sync
		if trakt_sync.Auth().trakt_auth(mode=mode) is not True:
			xbmc.log('AM Lite: Trakt add-on synchronization incomplete', xbmc.LOGERROR)
			return False
		set_trakt_sync_pending(False)
		xbmc.log('AM Lite: Trakt token synced to add-ons', xbmc.LOGINFO)
		return True
	except Exception:
		log_utils.error("Trakt sync FAILED")
		return False

def TraktStartup():
        
	# Startup flow:
	# 1. Force NOT ready
	# 2. Refresh immediately if needed
	# 3. Wait for Kodi startup when token is valid
	# 4. Sync only when safe
	# 5. Mark READY only when safe

	am_trakt_startup_begin()

	if not ensure_defaults(): # If Trakt NOT authed, end Trakt startup flow
		am_trakt_startup_complete()
		return

	now = int(time.time())
	expires = get_trakt_expires()
	refresh_window = get_trakt_refresh_window()
	refresh_needed = expires <= 0 or now >= (expires - refresh_window)

	if refresh_needed:
		status = trakt_refresh()
	else:
		startup_wait()
		status = trakt_refresh()

	if status == 'failed':
		xbmc.log('AM Lite: Startup refresh failed - leaving Trakt NOT READY', xbmc.LOGERROR)
		am_trakt_startup_fail()
		return

	if status == 'refreshed':
		sync_ok = startup_tk_sync(mode="refresh")
	elif status == 'valid':
		sync_ok = startup_tk_sync(mode="repair" if trakt_sync_pending() else "startup")
	elif status == 'missing':
		sync_ok = True
	else:
		sync_ok = False

	if not sync_ok:
		xbmc.log('AM Lite: Startup sync failed - leaving Trakt NOT READY', xbmc.LOGERROR)
		am_trakt_startup_fail()
		return

	am_trakt_startup_complete()
        
def SyncManager():  # Auto-sync credentials with recently installed/supported addons

	mdb_master_token, rd_master_token, pm_master_token, ad_master_token, tb_master_token, oc_master_token, en_master_user, en_master_pass = am_masters()

	try:
		if control.setting('sync.mdb.service')=='true' and mdb_master_token:
			from acctmgr.modules.sync import mdblist_sync
			mdblist_sync.Auth().mdblist_auth()
	except Exception:
		log_utils.error("Startup MDBList Startup Sync FAILED")
		
	try:
		if control.setting('sync.rd.service')=='true' and rd_master_token:
			from acctmgr.modules.sync import debrid_rd
			debrid_rd.Auth().realdebrid_auth()
	except Exception:
		log_utils.error("Startup Real-Debrid Startup Sync FAILED")
	
	try:
		if control.setting('sync.pm.service')=='true' and pm_master_token:
			from acctmgr.modules.sync import debrid_pm
			debrid_pm.Auth().premiumize_auth()
	except Exception:
		log_utils.error("Startup Premiumize Startup Sync FAILED")

	try:
		if control.setting('sync.ad.service')=='true' and ad_master_token:
			from acctmgr.modules.sync import debrid_ad 
			debrid_ad.Auth().alldebrid_auth()
	except Exception:
		log_utils.error("Startup All-Debrid Startup Sync FAILED")

	'''try:	
		if control.setting('sync.ed.service')=='true' and ed_master_token:
			from acctmgr.modules.sync import easydebrid_sync
			easydebrid_sync.Auth().easydebrid_auth()
	except Exception:
		log_utils.error("Startup Easy-Debrid Startup Sync FAILED")'''

	try:	
		if control.setting('sync.tb.service')=='true' and tb_master_token:
			from acctmgr.modules.sync import torbox_sync
			torbox_sync.Auth().torbox_auth()
	except Exception:
		log_utils.error("Startup Torbox Startup Sync FAILED")

	try:	
		if control.setting('sync.oc.service')=='true' and oc_master_token:
			from acctmgr.modules.sync import offcloud_sync
			offcloud_sync.Auth().offcloud_auth()
	except Exception:
		log_utils.error("Startup OffCloud Startup Sync FAILED")

	try:	
		if control.setting('sync.en.service')=='true' and en_master_user and en_master_pass:
			from acctmgr.modules.sync import easynews_sync
			easynews_sync.Auth().easynews_auth()
	except Exception:
		log_utils.error("Startup Easynews Startup Sync FAILED")
		
def compute_file_hash(path): # Compute a simple hash of a file's contents to detect changes
	if not os.path.exists(path):
		return None
	try:
		with open(path, "rb") as f:
			return hashlib.md5(f.read()).hexdigest()
	except Exception as e:
		xbmc.log(f"APIManager: Error hashing {path} - {e}", xbmc.LOGERROR)
		return None

def run_addon_updates():  # Start add-on update check
	control.autoupdate_on() # Enable auto-updates
	xbmc.sleep(1500)
	xbmc.executebuiltin('UpdateAddonRepos()')  # Update repos/add-ons
	
def StartupManager():  # Compare and restore Trakt API keys / Run add-on updates
	start_time = time.time()
	api_timeout = start_time + 300  # Run Startup Manager for 5 min
	addon_updates_started = False
	addon_updates_seen = False
	addon_updates_finished = False
	quiet_cycles = 0

	last_hashes = {}  # Track last state of each add-on service
	service_paths = [
		var.path_fenlt_service,
		var.path_gears_service,
                var.path_red_service,
		var.path_umb_service,
		#var.path_seren_service,
		var.path_luc_service,
		#var.path_fen_service,
		var.path_pov_service,
		#var.path_coal_service,
		#var.path_dradis_service,
		var.path_genocide_service,
		var.path_home_service,
		var.path_night_service,
		var.path_absol_service,
		var.path_crew_service,
		var.path_salts_service,
		var.path_scrubs_service,
                var.path_redg_service,
		var.path_tmdbh_trakt_keys,
		var.path_trakt_service,
	]

	while not abort_requested() and time.time() <= api_timeout:
		if control.setting('api.service') == 'true' and get_trakt_token(): # Start API check
			if control.setting('api.stop') == 'true':
				control.setSetting('api.stop', 'false')
				break

			changed = False
			for path in service_paths:
				current_hash = compute_file_hash(path)
				if last_hashes.get(path) != current_hash:
					last_hashes[path] = current_hash
					changed = True

			if changed:  # Only start sync if a service file has changed
				from acctmgr.modules.sync import api_sync
				try:
					api_sync.check_api()
				except Exception as e:
					xbmc.log(f"APIManager: api_sync.check_api failed - {e}", xbmc.LOGERROR)

		if not addon_updates_started and get_trakt_token(): # Start add-on updates
			run_addon_updates()
			addon_updates_started = True

		if addon_updates_started and not addon_updates_finished:
			update_count = xbmc.getInfoLabel('System.AddonUpdateCount') # Count updates

			try:
				update_count = int(update_count or 0)
			except Exception:
				update_count = 0

			if update_count > 0:
				addon_updates_seen = True
				quiet_cycles = 0
			elif addon_updates_seen:
				quiet_cycles += 1

			if addon_updates_seen and quiet_cycles >= 6: # After count reaches 0 wait before exiting
				addon_updates_finished = True

		if MONITOR.waitForAbort(0.5):  # Run every 500ms
			break
				
def AddonCheckUpdate(): # AM Lite Update Notification
	if abort_requested():
		return

	if control.setting('check_for_update') == 'true':
		xbmc.log('AM Lite: Addon checking available updates', xbmc.LOGINFO)
		try:
			repo_xml = requests.get('https://raw.githubusercontent.com/Zaxxon709/zaxxon/main/zips/script.module.acctmgr/addon.xml',timeout=10)

			if abort_requested():
				return

			if repo_xml.status_code != 200:
				return xbmc.log('AM Lite: Could not connect to remote repo XML: status code = %s' % repo_xml.status_code,xbmc.LOGINFO)

			match = re.search(r'<addon\s+[^>]*id=["\']script\.module\.acctmgr["\'][^>]*version=["\']([^"\']+)["\']',repo_xml.text,re.I)

			if not match:
				return xbmc.log('AM Lite: Could not find version in remote addon.xml',xbmc.LOGINFO)

			repo_version = match.group(1)
			local_version = control.addonVersion()

			def check_version_numbers(current, new):
				current = [int(x) for x in current.split('.') if x.isdigit()]
				new = [int(x) for x in new.split('.') if x.isdigit()]

				length = max(len(current), len(new))
				current += [0] * (length - len(current))
				new += [0] * (length - len(new))

				return new > current

			if check_version_numbers(local_version, repo_version):
				while control.condVisibility('Library.IsScanningVideo') and not abort_requested():
					if MONITOR.waitForAbort(1):
						return

				if abort_requested():
					return

				xbmc.log('AM Lite: A newer version is available. Installed Version: v%s' % local_version,xbmc.LOGINFO)

				control.notification(message=control.lang(32072) % repo_version,time=5000)

			return xbmc.log('AM Lite: Addon update check complete',xbmc.LOGINFO)
		except Exception:
			log_utils.error("Addon update check failed")

def trakt_refresh_monitor(interval=120): # Trakt background monitor loop to refresh/sync Trakt when needed. Checks every 2 minutes
	xbmc.log('AM Lite: Starting Trakt refresh monitor loop', xbmc.LOGINFO)

	while not abort_requested():
		try:
			token = get_trakt_token()

			if token:
				status = trakt_refresh()

				if status == 'refreshed':
					xbmc.log('AM Lite: Background Trakt refresh succeeded - syncing add-ons', xbmc.LOGINFO)
					if not startup_tk_sync(mode="refresh"):
						xbmc.log('AM Lite: Background Trakt sync failed after refresh; retry scheduled', xbmc.LOGERROR)
				elif status == 'valid' and trakt_sync_pending():
					xbmc.log('AM Lite: Retrying incomplete Trakt synchronization without refreshing token', xbmc.LOGINFO)
					if startup_tk_sync(mode="repair"):
						am_trakt_startup_complete()
				elif status == 'failed':
					xbmc.log('AM Lite: Background Trakt refresh failed', xbmc.LOGERROR)
		except Exception:
			log_utils.error("AM Lite Trakt refresh monitor FAILED")

		if MONITOR.waitForAbort(interval):
			break

	xbmc.log('AM Lite: Trakt refresh monitor loop stopped', xbmc.LOGINFO)

# START SERVICES
#if not abort_requested():
        #ScraperCheck()
if not abort_requested():
	TraktStartup()
if not abort_requested():
    try:
        from acctmgr.modules.sync import tmdbh_provider
        tmdbh_provider.startup_install()
    except Exception as exc:
        xbmc.log('AM Lite [TMDb Trakt install]: startup handler failed: %s' % exc, xbmc.LOGERROR)
if not abort_requested():
    try:
        from acctmgr.modules.sync import tmdbh_mdblist
        tmdbh_mdblist.startup_install()
    except Exception as exc:
        xbmc.log('AM Lite [TMDb MDBList install]: %s' % exc, xbmc.LOGERROR)
if not abort_requested():
	SyncManager()
if not abort_requested():
	StartupManager()
if not abort_requested():
	AddonCheckUpdate()
if not abort_requested():
	trakt_refresh_monitor()
