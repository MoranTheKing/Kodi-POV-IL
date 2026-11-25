# -*- coding: utf-8 -*-
import xbmc, xbmcaddon, xbmcgui, xbmcvfs
import sys
import os
import re
import json
import sqlite3
import shutil
import importlib
import datetime
import textwrap
from acctmgr.modules import var
from acctmgr.modules import log_utils

#Variables
condVisibility = xbmc.getCondVisibility
execute = xbmc.executebuiltin
monitor = xbmc.Monitor()
translatePath = xbmcvfs.translatePath
joinPath = os.path.join
date = str(datetime.date.today())
dialog = xbmcgui.Dialog()
window = xbmcgui.Window(10000)
progressDialog = xbmcgui.DialogProgress()
existsPath = xbmcvfs.exists
openFile = xbmcvfs.File
makeFile = xbmcvfs.mkdir
progress_line = '%s[CR]%s[CR]%s'
char_remov = ["'", ",", ")","("]

# HELPERS
def iconsPath():
	return joinPath(addonInfo('path'), 'resources', 'icons')

def getKodiVersion():
	return int(xbmc.getInfoLabel("System.BuildVersion")[:2])

def _acctmgr():
    try:
        return xbmcaddon.Addon('script.module.acctmgr')
    except RuntimeError:
        return None

def addonInfo(id):
    addon = _acctmgr()
    if addon is None:
        return ''
    return addon.getAddonInfo(id)

def setting(id):
    addon = _acctmgr()
    if addon is None:
        return ''
    return addon.getSetting(id)

def setSetting(id, value):
    addon = _acctmgr()
    if addon is None:
        return None
    return addon.setSetting(id, value)

def setAddonSetting(addon_id, id, value):
    try:
        return xbmcaddon.Addon(addon_id).setSetting(id, value)
    except Exception:
        return None

def getLangString(id):
    addon = _acctmgr()
    if addon is None:
        return ''
    return addon.getLocalizedString(id)

def lang(language_id):
	text = getLangString(language_id)
	return text

def sleep(time):
	while time > 0 and not monitor.abortRequested():
		xbmc.sleep(min(100, time))
		time = time - 100

def addonId():
	return addonInfo('id')

def addonName():
	return 'AM Lite'

def addonVersion():
	return addonInfo('version')

def addonIcon():
	return addonInfo('icon')

def addonPath():
	try: return translatePath(addonInfo('path').decode('utf-8'))
	except: return translatePath(addonInfo('path'))

def artPath():
	return iconsPath()

def openSettings(query=None, id=addonInfo('id')):
	try:
		idle()
		execute('Addon.OpenSettings(%s)' % id)
		if query is None: return
		c, f = query.split('.')
		execute('SetFocus(%i)' % (int(c) - 100))
		execute('SetFocus(%i)' % (int(f) - 80))
	except:
		return

def idle():
	if condVisibility('Window.IsActive(busydialognocancel)'):
		return execute('Dialog.Close(busydialognocancel)')
        
def yesnoDialog(line, heading=addonInfo('name'), nolabel='', yeslabel=''):
	return dialog.yesno(heading, line, nolabel, yeslabel)

def selectDialog(list, heading=addonInfo('name')):
	return dialog.select(heading, list)

def okDialog(title=None, message=None):
	if title == 'default' or title is None: title = addonName()
	if isinstance(title, int): heading = lang(title)
	else: heading = str(title)
	if isinstance(message, int): body = lang(message)
	else: body = str(message)
	return dialog.ok(heading, body)

def closeAll():
	return execute('Dialog.Close(all, true)')

def jsondate_to_datetime(jsondate_object, resformat, remove_time=False):
	import _strptime
	from datetime import datetime
	import time
	if remove_time:
		try: datetime_object = datetime.strptime(jsondate_object, resformat).date()
		except TypeError: datetime_object = datetime(*(time.strptime(jsondate_object, resformat)[0:6])).date()
	else:
		try: datetime_object = datetime.strptime(jsondate_object, resformat)
		except TypeError: datetime_object = datetime(*(time.strptime(jsondate_object, resformat)[0:6]))
	return datetime_object

def set_active_monitor():
	window.setProperty('acctmgr.active', 'true')

def release_active_monitor():
	window.clearProperty('acctmgr.active')

def function_monitor(func, query='0.0'):
	func()
	sleep(100)
	openSettings(query)
	while not condVisibility('Window.IsVisible(addonsettings)'):
		sleep(250)
	sleep(100)
	release_active_monitor()

def refresh_debugReversed():
	if window.getProperty('acctmgr.debug.reversed') != setting('debug.reversed'):
		window.setProperty('acctmgr.debug.reversed', setting('debug.reversed'))
		execute('RunScript(script.module.acctmgr, action=tools_clearLogFile)')

def autoupdate_on():
        xbmc.executeJSONRPC('{"jsonrpc":"2.0","method":"Settings.SetSettingValue","params":{"setting":"general.addonupdates","value":0},"id":1}')
    
def updates_on():
        xbmc.executeJSONRPC('{"jsonrpc":"2.0","method":"Settings.SetSettingValue","params":{"setting":"general.addonupdates","value":0},"id":1}')
        xbmc.executebuiltin('ActivateWindowAndFocus(systemsettings)')
        xbmc.executebuiltin('Action(Back)')

def updates_off():
        xbmc.executeJSONRPC('{"jsonrpc":"2.0","method":"Settings.SetSettingValue","params":{"setting":"general.addonupdates","value":2},"id":1}')
        xbmc.executebuiltin('ActivateWindowAndFocus(systemsettings)')
        xbmc.executebuiltin('Action(Back)')
        
def delete_synclist():
        if os.path.exists(var.tk_sync_list):
                try:
                        os.unlink(var.tk_sync_list)
                except FileNotFoundError:
                        pass

# NOTIFICATIONS        
def suppress_notifications(kodi_utils):
    original = getattr(kodi_utils, 'notification', None)
    kodi_utils.notification = lambda *args, **kwargs: None
    return original
     
def notification(title=None, message=None, icon=None, time=3000, sound=False):
	if title == 'default' or title is None: title = addonName()
	if isinstance(title, int): heading = lang(title)
	else: heading = str(title)
	if isinstance(message, int): body = lang(message)
	else: body = str(message)
	if icon is None or icon == '' or icon == 'default': icon = addonIcon()
	elif icon == 'INFO': icon = xbmcgui.NOTIFICATION_INFO
	elif icon == 'WARNING': icon = xbmcgui.NOTIFICATION_WARNING
	elif icon == 'ERROR': icon = xbmcgui.NOTIFICATION_ERROR
	dialog.notification(heading, body, icon, time, sound=sound)

# COPY ADDON DATA (If required, copy the add-ons default settings.xml)
def copy_addon_settings(name, chk_addon, ud_path, chk_setting, base_path):
    try:
        if not xbmcvfs.exists(chk_addon):
            return

        if not xbmcvfs.exists(ud_path):
            try:
                xbmcvfs.mkdirs(ud_path)
            except Exception:
                os.mkdir(ud_path)

        if not xbmcvfs.exists(chk_setting):
            xbmcvfs.copy(base_path, chk_setting)

    except Exception as e:
        log_utils.error(f"{name} copy addon settings.xml failed: {e}")

# PLUGIN HELPERS - REMAKE SETTINGS / RESTORE DEFAULT TRAKT API KEYS
def run_plugin_action(url, label=None):
    try:
        xbmc.executebuiltin(f'RunPlugin("{url}")')
        if label:
            xbmc.log(f"AM Lite: Ran {label}", xbmc.LOGINFO)
        return True
    except Exception as e:
        log_utils.error(f"Failed to run {label or url}: {e}")
        return False

# Fen Light
def remake_fenlt_settings():
    return run_plugin_action(
        'plugin://plugin.video.fenlight/?mode=sync_settings&silent=true&isFolder=false',
        'Fen Light settings remake'
    )

def restore_fenlt_tkclient():
    return run_plugin_action(
        'plugin://plugin.video.fenlight/?mode=settings_manager.restore_setting_default&setting_id=trakt.client&silent=true',
        'Fen Light Trakt Client restore'
    )

def restore_fenlt_tksecret():
    return run_plugin_action(
        'plugin://plugin.video.fenlight/?mode=settings_manager.restore_setting_default&setting_id=trakt.secret&silent=true',
        'Fen Light Trakt Secret restore'
    )

# The Gears
def remake_gears_settings():
    return run_plugin_action(
        'plugin://plugin.video.gears/?mode=sync_settings&silent=true&isFolder=false',
        'The Gears settings remake'
    )

def restore_gears_tkclient():
    return run_plugin_action(
        'plugin://plugin.video.gears/?mode=settings_manager.restore_setting_default&setting_id=trakt.client&silent=true',
        'The Gears Trakt Client restore'
    )

def restore_gears_tksecret():
    return run_plugin_action(
        'plugin://plugin.video.gears/?mode=settings_manager.restore_setting_default&setting_id=trakt.secret&silent=true',
        'The Gears Trakt Secret restore'
    )

# Red Light
def remake_red_settings():
    return run_plugin_action(
        'plugin://plugin.video.redlight/?mode=sync_settings&silent=true&isFolder=false',
        'Red Light settings remake'
    )

def restore_red_tkclient():
    return run_plugin_action(
        'plugin://plugin.video.redlight/?mode=settings_manager.restore_setting_default&setting_id=trakt.client&silent=true',
        'Red Light Trakt Client restore'
    )

def restore_red_tksecret():
    return run_plugin_action(
        'plugin://plugin.video.redlight/?mode=settings_manager.restore_setting_default&setting_id=trakt.secret&silent=true',
        'Red Light Trakt Secret restore'
    )

# Others
def remake_coal_settings():
    return run_plugin_action(
        'plugin://plugin.video.coalition/?mode=clean_settings_window_properties&name=Clean+Settings+Cache&isFolder=false',
        'The Coalition settings remake'
    )

def remake_pov_settings():
    return run_plugin_action(
        'plugin://plugin.video.pov/?mode=clean_settings_window_properties&name=Clean+Settings+Cache&isFolder=false',
        'POV settings remake'
    )

# REMAKE TRAKT CACHE
def remake_trakt_cache(plugin_id, name):
    main_conn = None
    trakt_conn = None

    try:
        try:
            addon = xbmcaddon.Addon(plugin_id)
        except Exception:
            log_utils.error(f"{name} not installed, skipping Trakt cache clear")
            return False

        profile_path = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
        db_dir = os.path.join(profile_path, 'databases')
        trakt_db = os.path.join(db_dir, 'traktcache.db')
        main_db = os.path.join(db_dir, 'maincache.db')

        if not os.path.exists(db_dir):
            log_utils.error(f"{name} databases folder not found")
            return False

        if os.path.exists(main_db):
            main_conn = sqlite3.connect(main_db)
            main_cur = main_conn.cursor()
            main_cur.execute("DELETE FROM maincache WHERE id LIKE ?", ('trakt_lists_with_media_%',))
            main_conn.commit()
            try:
                main_cur.execute("VACUUM")
            except Exception:
                pass

        if os.path.exists(trakt_db):
            trakt_conn = sqlite3.connect(trakt_db)
            trakt_cur = trakt_conn.cursor()

            for table in ('progress', 'watched', 'watched_status'):
                trakt_cur.execute(f"DELETE FROM {table}")

            trakt_cur.execute(
                "DELETE FROM trakt_data WHERE id NOT LIKE ?",
                ('trakt_list_custom_sort_%',)
            )

            trakt_conn.commit()
            try:
                trakt_cur.execute("VACUUM")
            except Exception:
                pass

        xbmc.log(f'AM Lite: {name} Trakt cache cleared', xbmc.LOGINFO)
        return True

    except Exception as e:
        log_utils.error(f"Failed to clear {name} Trakt cache: {e}")
        return False

    finally:
        try:
            if main_conn:
                main_conn.close()
        except Exception:
            pass

        try:
            if trakt_conn:
                trakt_conn.close()
        except Exception:
            pass


def remake_fenlt_trakt_cache():  # Fen Light
    return remake_trakt_cache('plugin.video.fenlight', 'Fen Light')

def remake_gears_trakt_cache():  # The Gears
    return remake_trakt_cache('plugin.video.gears', 'The Gears')

def remake_redlt_trakt_cache():  # Red Light
    return remake_trakt_cache('plugin.video.redlight', 'Red Light')


# FEN & THE COALITION TRAKT CACHE
def remake_simple_trakt_cache(plugin_id, name, trakt_db_name='traktcache4.db'):
    conn = None

    try:
        try:
            addon = xbmcaddon.Addon(plugin_id)
        except Exception:
            log_utils.error(f"{name} not installed, skipping Trakt cache clear")
            return False

        trakt_db = xbmcvfs.translatePath(addon.getAddonInfo('profile') + trakt_db_name)

        if not xbmcvfs.exists(trakt_db):
            log_utils.error(f"{name} {trakt_db_name} not found")
            return False

        conn = sqlite3.connect(trakt_db)
        cur = conn.cursor()

        cur.execute("PRAGMA synchronous = OFF")
        cur.execute("PRAGMA journal_mode = OFF")

        for table in ('trakt_data', 'progress', 'watched_status'):
            cur.execute(f'DELETE FROM {table}')

        conn.commit()

        try:
            cur.execute("VACUUM")
        except Exception:
            pass

        xbmc.log(f'AM Lite: {name} Trakt cache cleared', xbmc.LOGINFO)
        return True

    except Exception as e:
        log_utils.error(f"Failed to clear {name} Trakt cache: {e}")
        return False

    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def remake_fen_trakt_cache():
    return remake_simple_trakt_cache('plugin.video.fen', 'Fen')

def remake_coal_trakt_cache():
    return remake_simple_trakt_cache('plugin.video.coalition', 'The Coalition')


# POV TRAKT CACHE
def remake_pov_trakt_cache():
    conn = None

    try:
        try:
            addon = xbmcaddon.Addon('plugin.video.pov')
        except Exception:
            log_utils.error("POV not installed, skipping Trakt cache clear")
            return False

        trakt_db = xbmcvfs.translatePath(addon.getAddonInfo('profile') + 'traktcache.db')

        if not xbmcvfs.exists(trakt_db):
            log_utils.error("POV trakt.db not found")
            return False

        conn = sqlite3.connect(trakt_db)
        cur = conn.cursor()

        cur.execute("PRAGMA synchronous = OFF")
        cur.execute("PRAGMA journal_mode = OFF")

        for table in ('trakt_data', 'progress', 'watched_status'):
            cur.execute(f'DELETE FROM {table}')

        conn.commit()

        try:
            cur.execute("VACUUM")
        except Exception:
            pass

        xbmc.log('AM Lite: POV Trakt cache cleared', xbmc.LOGINFO)
        return True

    except Exception as e:
        log_utils.error(f"Failed to clear POV Trakt cache: {e}")
        return False

    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass

# INSTALL TMDB HELPER PLAYERS
def install_tmdbh_players():
	dialog = xbmcgui.Dialog()
	amgr_icon = joinPath(iconsPath(), 'acctmgr.png')
	src = xbmcvfs.translatePath('special://home/addons/script.module.acctmgr/resources/players/')
	players_path = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.themoviedb.helper/players/')
	reconfigured_path = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.themoviedb.helper/reconfigured_players/')

	if xbmcvfs.exists(players_path):
		dst = players_path
	else:
		dst = reconfigured_path
		if not xbmcvfs.exists(dst):
			xbmcvfs.mkdirs(dst)

	player_files = (
		('Fen Light', 'plugin.video.fenlight', 'fenlight.json'),
		('The Gears', 'plugin.video.gears', 'gears.json'),
		('Red Light', 'plugin.video.redlight', 'redlight.json'),
		('Umbrella', 'plugin.video.umbrella', 'umbrella.json'),
		('POV', 'plugin.video.pov', 'pov.json'),
		('Seren', 'plugin.video.seren', 'seren.json'),
        ('Prism', 'plugin.video.prism', 'prism.json'),
        ('Luc_Kodi', 'plugin.video.luc_kodi', 'luc_kodi.json'),
		('Genocide', 'plugin.video.genocide', 'genocide.json'),
		('Shadow', 'plugin.video.shadow', 'shadow.json'),
		('Ghost', 'plugin.video.ghost', 'ghost.json'),
		('Homelander', 'plugin.video.homelander', 'homelander.json'),
		('Nightwing', 'plugin.video.nightwing', 'nightwing.json'),
		('Jokers Absolution', 'plugin.video.absolution', 'absolution.json'),
		('The Crew', 'plugin.video.thecrew', 'thecrew.json'),
		('Scrubs V2', 'plugin.video.scrubsv2', 'scrubsv2.json'),
		('Gratis Red', 'plugin.video.gratisred', 'gratisred.json'),
		('IMDb Trailers', 'plugin.video.imdb.trailers', 'imdbtrailers.json'),
		('Magneto (AIO Streams)', 'script.module.magneto', 'magneto.json'),
	)

	players = []

	for label, addon_id, file_name in player_files:
		if not xbmc.getCondVisibility('System.HasAddon(%s)' % addon_id):
			continue

		src_file = os.path.join(src, file_name)
		dst_file = os.path.join(dst, file_name)

		if xbmcvfs.exists(dst_file):
			continue

		if not xbmcvfs.exists(src_file):
			xbmc.log('AM Lite: Missing TMDb Helper player file %s' % file_name, xbmc.LOGWARNING)
			continue

		players.append({'label': label, 'file_name': file_name, 'src': src_file, 'dst': dst_file})

	if not players:
		notification('AM Lite', 'No available players to install!', icon=amgr_icon)
		return False

	labels = ['Install All Players'] + [i['label'] for i in players]
	selected = dialog.multiselect('Choose Players to Install', labels)

	if selected is None:
		return False

	if 0 in selected:
		selected_players = players
	else:
		selected_players = [players[index - 1] for index in selected]

	copied = 0

	for player in selected_players:
		try:
			if xbmcvfs.copy(player['src'], player['dst']):
				copied += 1
			else:
				shutil.copy2(player['src'], player['dst'])
				copied += 1

		except Exception as e:
			xbmc.log('AM Lite: Failed copying TMDb Helper player %s - %s' % (player['file_name'], e), xbmc.LOGERROR)

	notification('AM Lite', 'Installed %s player(s)' % copied, icon=amgr_icon)

	return copied > 0

# DELETE TMDB HELPER PLAYERS
def delete_tmdbh_players():
	dialog = xbmcgui.Dialog()
	amgr_icon = joinPath(iconsPath(), 'acctmgr.png')
	players_path = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.themoviedb.helper/players/')
	reconfigured_path = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.themoviedb.helper/reconfigured_players/')

	if xbmcvfs.exists(players_path):
		dst = players_path
	else:
		dst = reconfigured_path

	player_files = (
		('Fen Light', 'fenlight.json'),
		('The Gears', 'gears.json'),
		('Red Light', 'redlight.json'),
		('Umbrella', 'umbrella.json'),
		('POV', 'pov.json'),
		('Seren', 'seren.json'),
        ('Prism', 'prism.json'),
        ('Luc_Kodi', 'luc_kodi.json'),
		('Genocide', 'genocide.json'),
		('Shadow', 'shadow.json'),
		('Ghost', 'ghost.json'),
		('Homelander', 'homelander.json'),
		('Nightwing', 'nightwing.json'),
		('Jokers Absolution', 'absolution.json'),
		('The Crew', 'thecrew.json'),
		('Scrubs V2', 'scrubsv2.json'),
		('Gratis Red', 'gratisred.json'),
		('IMDb Trailers', 'imdbtrailers.json'),
		('Magneto (AIO Streams)', 'magneto.json'),
	)

	players = []

	for label, file_name in player_files:
		dst_file = os.path.join(dst, file_name)

		if not xbmcvfs.exists(dst_file):
			continue

		players.append({'label': label, 'file_name': file_name, 'dst': dst_file})

	if not players:
		notification('AM Lite', 'No available players to uninstall!', icon=amgr_icon)
		return False

	labels = ['Uninstall All Players'] + [i['label'] for i in players]
	selected = dialog.multiselect('Choose Players to Uninstall', labels)

	if selected is None:
		return False

	if 0 in selected:
		if not dialog.yesno('AM Lite', 'Uninstall all TMDb Helper players?'):
			return False

		selected_players = players
	else:
		selected_players = [players[index - 1] for index in selected]

		if not dialog.yesno('AM Lite', 'Uninstall %s selected player(s)?' % len(selected_players)):
			return False

	deleted = 0

	for player in selected_players:
		try:
			if xbmcvfs.delete(player['dst']):
				deleted += 1
		except Exception as e:
			xbmc.log('AM Lite: Failed deleting TMDb Helper player %s - %s' % (player['file_name'], e), xbmc.LOGERROR)

	notification('AM Lite', 'Uninstalled %s player(s)' % deleted, icon=amgr_icon)

	return deleted > 0

# RESTORE DEFAULT API KEYS - ***NO LONGER IN USE - Default keys are now restored via add-on builtin***
def apply_default_trakt_api_keys_db(): # Restore default API keys for settings.db
    services = (
        ("Fen Light", var.fenlt_settings_db, var.chains_client, var.chains_secret),
        ("The Gears", var.gears_settings_db, var.chains_client, var.chains_secret),
        ("Red Light", var.red_settings_db, var.chains_client, var.chains_secret),
    )

    results = []

    for name, settings_db, default_client, default_secret in services:
        conn = None

        try:
            if not xbmcvfs.exists(settings_db):
                xbmc.log(f"AM Lite: restore default API keys [{name}]: not found", xbmc.LOGWARNING)
                results.append((name, False, "not found"))
                continue

            conn = sqlite3.connect(settings_db, timeout=3)
            cur = conn.cursor()

            cur.execute(
                "SELECT setting_id, setting_value FROM settings WHERE setting_id IN (?, ?)",
                ("trakt.client", "trakt.secret")
            )

            current = dict(cur.fetchall())

            current_client = current.get("trakt.client", "")
            current_secret = current.get("trakt.secret", "")

            if current_client == default_client and current_secret == default_secret:
                xbmc.log(f"AM Lite: restore default API keys [{name}]: no changes needed", xbmc.LOGINFO)
                results.append((name, True, "no changes needed"))
                cur.close()
                continue

            cur.execute(
                "UPDATE settings SET setting_value = ? WHERE setting_id = ?",
                (default_client, "trakt.client")
            )
            cur.execute(
                "UPDATE settings SET setting_value = ? WHERE setting_id = ?",
                (default_secret, "trakt.secret")
            )

            conn.commit()
            cur.close()

            xbmc.log(f"AM Lite: restore default API keys [{name}]: restored", xbmc.LOGINFO)
            results.append((name, True, "restored"))

        except Exception as e:
            xbmc.log(f"AM Lite: restore default API keys [{name}]: FAILED ({e})", xbmc.LOGERROR)
            results.append((name, False, str(e)))

        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

    return results

# Seren: detect either known key pair; restore by installed add-on version.
def patch_seren_trakt_keys(restore=False):
	try:
		version = xbmcaddon.Addon('plugin.video.seren').getAddonInfo('version')
		client, secret = ((var.seren_client, var.seren_secret) if version == '3.0.1'
			else (var.seren_fork_client, var.seren_fork_secret))
		with open(var.path_seren, 'r', encoding='utf-8') as f:
			data = f.read()
		if restore:
			if var.client_am not in data and var.secret_am not in data:
				return True, 'Seren keys already restored'
			if var.client_am not in data or var.secret_am not in data:
				return False, 'Seren AM Lite key pair incomplete'
			new_data = data.replace(var.client_am, client).replace(var.secret_am, secret)
		else:
			if var.client_am in data and var.secret_am in data:
				return True, 'Seren already patched'
			if var.client_am in data or var.secret_am in data:
				return False, 'Seren AM Lite key pair incomplete'
			pairs = ((var.seren_client, var.seren_secret), (var.seren_fork_client, var.seren_fork_secret))
			matches = [(c, s) for c, s in pairs if c in data and s in data]
			if len(matches) != 1:
				return False, 'Seren key pair unknown or ambiguous'
			c, s = matches[0]
			new_data = data.replace(c, var.client_am).replace(s, var.secret_am)
		if new_data != data:
			with open(var.path_seren, 'w', encoding='utf-8') as f:
				f.write(new_data)
		return True, 'Seren Trakt keys ' + ('restored' if restore else 'patched')
	except Exception as e:
		return False, 'Seren key operation failed: ' + str(e)

def apply_default_trakt_api_keys(): # Restore default API keys for python files and settings.xml
    results = []

    if xbmcvfs.exists(var.chk_seren):
        ok, msg = patch_seren_trakt_keys(restore=True)
        results.append(('Seren', ok, msg))
        xbmc.log('AM Lite: ' + msg, xbmc.LOGINFO if ok else xbmc.LOGERROR)

    # Restore default keys in python files
    file_targets = (
        (var.chk_umb,           var.path_umb,     var.umb_client,            var.umb_secret,            "Umbrella",     var.client_am,            var.secret_am),
        (var.chk_shadow,        var.path_shadow,  var.shadow_client,         var.shadow_secret,         "Shadow",       var.client_am,            var.secret_am),
        (var.chk_ghost,         var.path_ghost,   var.ghost_client,          var.ghost_secret,          "Ghost",        var.client_am,            var.secret_am),
        (var.chk_chains,        var.path_chains,  var.thechains_client,      var.thechains_secret,      "The Chains",   var.client_am,            var.secret_am),
        (var.chk_crew,          var.path_crew,    var.crew_client,           var.crew_secret,           "The Crew",     var.client_am_x,          var.secret_am_x),
        (var.chk_salts,         var.path_salts,   var.salts_client,          var.salts_secret,          "SALTS",        var.client_am,            var.secret_am),
        (var.chk_scrubs,        var.path_scrubs,  var.scrubs_client,         var.scrubs_secret,         "Scrubs V2",    var.client_am,            var.secret_am),
        (var.chk_redg,          var.path_redg,    var.redg_client,           var.redg_secret,           "Gratis Red",   var.client_am,            var.secret_am),

        (var.chk_trakt,         var.path_trakt,   var.trakt_client_obs_str,  var.trakt_secret_obs_str,  "Trakt",        var.client_am_obs_str,    var.secret_am_obs_str),
    )

    for chk_path, path, default_client, default_secret, name, current_client, current_secret in file_targets:
        try:
            if not xbmcvfs.exists(chk_path):
                xbmc.log(f"AM Lite: restore default API keys [{name}]: addon not found", xbmc.LOGINFO)
                results.append((name, False, "addon not found"))
                continue

            else:
                if not xbmcvfs.exists(path):
                        xbmc.log(f"AM Lite: restore default API keys [{name}]: file not found -> {path}", xbmc.LOGINFO)
                        results.append((name, False, "file not found"))
                        continue

            with open(path, "r", encoding="utf-8") as f:
                data = f.read()

            original_data = data

            if current_client in data:
                data = data.replace(current_client, default_client)

            if current_secret in data:
                data = data.replace(current_secret, default_secret)

            if data != original_data:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(data)

                xbmc.log(f"AM Lite: restore default API keys [{name}]: restored", xbmc.LOGINFO)
                results.append((name, True, "restored"))
            else:
                xbmc.log(f"AM Lite: restore default API keys [{name}]: no changes needed", xbmc.LOGINFO)
                results.append((name, False, "no changes needed"))

        except Exception as e:
            xbmc.log(f"AM Lite: restore default API keys [{name}]: ERROR {e}", xbmc.LOGINFO)
            results.append((name, False, str(e)))

    # External TMDb Helper Trakt provider: one CLIENT_ID, no client secret.
    try:
        from acctmgr.modules.sync import tmdbh_provider
        restored = tmdbh_provider.restore_api_key()
        tmdbh_provider.remove_guard()
        results.append(('TMDb Helper Trakt provider', True, 'restored' if restored else 'no changes needed'))
    except Exception as exc:
        xbmc.log('AM Lite: TMDb Helper provider key restore failed: %s' % exc, xbmc.LOGERROR)
        results.append(('TMDb Helper Trakt provider', False, str(exc)))

    # Restore default keys in settings.xml only if AM Lite keys are currently applied
    settings_targets = (
        ("plugin.video.luc_kodi",   var.chk_luc,       var.luc_client,    var.luc_secret,    "luc_kodi"),
        ("plugin.video.madtitansports", var.chk_madtitan, var.madtitan_client, var.madtitan_secret, "Mad Titan Sports"),
        ("plugin.video.pov",        var.chk_pov,       var.pov_client,    var.pov_secret,    "POV"),
        #("plugin.video.dradis",     var.chk_dradis,    var.dradis_client, var.dradis_secret, "Dradis"),
        ("plugin.video.genocide",   var.chk_genocide,  var.chains_client, var.chains_secret, "Genocide"),
    )

    for addon_id, chk_path, default_client, default_secret, name in settings_targets:
        try:
            if not xbmcvfs.exists(chk_path):
                xbmc.log(f"AM Lite: restore default API keys [{name}]: addon not found", xbmc.LOGINFO)
                results.append((name, False, "addon not found"))
                continue

            addon = xbmcaddon.Addon(addon_id)
            current_client = addon.getSetting("trakt.client_id")
            current_secret = addon.getSetting("trakt.client_secret")

            if current_client == str(var.client_am) and current_secret == str(var.secret_am):
                setAddonSetting(addon_id, "trakt.client_id", str(default_client))
                setAddonSetting(addon_id, "trakt.client_secret", str(default_secret))

                xbmc.log(f"AM Lite: restore default API keys [{name}]: restored default keys", xbmc.LOGINFO)
                results.append((name, True, "settings restored"))
            else:
                xbmc.log(f"AM Lite: restore default API keys [{name}]: no changes needed", xbmc.LOGINFO)
                results.append((name, False, "no changes needed"))

        except Exception as e:
            xbmc.log(f"AM Lite: restore default API keys [{name}]: ERROR {e}", xbmc.LOGINFO)
            results.append((name, False, str(e)))
    return results

# SERVICE PATCH HELPERS
def find_def_block(lines, func_name): # Find the first line of a function's body and its indentation
    pattern = rf"^[ \t]*def\s+{func_name}\s*\(.*\)\s*:"
    for i, line in enumerate(lines):
        if re.match(pattern, line):
            base_indent = line[:len(line) - len(line.lstrip(" \t"))]
            # Find first executable line inside function
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines):
                child_indent = lines[j][:len(lines[j]) - len(lines[j].lstrip(" \t"))]
                return j, child_indent
            # fallback 4-space indent
            return i + 1, base_indent + "    "
    return None, None

def prepare_snippet_for_indent(data, startup_snippet, indent):
    indent_unit = indent_unit_from_context(indent, data)
    normalized = convert_snippet_indent(normalize_snippet(startup_snippet), indent_unit)
    return indent_block(normalized, indent)

def indent_unit_from_context(indent, data):
    if "\t" in indent:
        return "\t"

    if indent:
        return "    "

    return detect_indent_unit(data)

def find_bottom_call(lines, patterns):
    for i in range(len(lines) - 1, -1, -1):
        raw = lines[i]
        stripped = raw.strip()

        if not stripped:
            continue

        # Only match true top-level statements
        if raw[:len(raw) - len(raw.lstrip(" \t"))] != "":
            continue

        for pattern in patterns:
            if re.fullmatch(pattern, stripped):
                return i

    return None

def find_name_main_block(lines):
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.fullmatch(r"if\s+__name__\s*==\s*['\"]__main__['\"]\s*:", stripped):
            base_indent = line_indent(line)

            # Look ahead for the first meaningful line inside the block
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1

            if j < len(lines):
                child_indent = line_indent(lines[j])

                # If the next meaningful line is actually indented, use that exact style
                if len(child_indent) > len(base_indent):
                    return j, child_indent

            # Fallback only if block body is empty or malformed
            if "\t" in base_indent:
                return i + 1, base_indent + "\t"

            return i + 1, base_indent + "    "

    return None, None

def find_import_insertion_index(lines):
    insert_at = 0
    in_docstring = False
    doc_delim = None
    seen_imports = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        if not seen_imports and (
            stripped.startswith("#!") or
            (stripped.startswith("#") and "coding" in stripped) or
            stripped == ""
        ):
            insert_at = i + 1
            continue

        if not seen_imports and not in_docstring and (stripped.startswith('"""') or stripped.startswith("'''")):
            delim = '"""' if stripped.startswith('"""') else "'''"
            insert_at = i + 1

            if stripped.count(delim) >= 2 and len(stripped) > 3:
                continue

            in_docstring = True
            doc_delim = delim
            continue

        if in_docstring:
            insert_at = i + 1
            if doc_delim in stripped:
                in_docstring = False
                doc_delim = None
            continue

        if not seen_imports and stripped.startswith("#"):
            insert_at = i + 1
            continue

        if re.match(r"^(import\s+.+|from\s+.+\s+import\s+.+)$", stripped):
            seen_imports = True
            insert_at = i + 1
            continue

        if seen_imports and stripped == "":
            insert_at = i + 1
            continue

        break

    return insert_at

def indent_block(text, indent):
    return "".join((indent + line) if line.strip() else line for line in text.splitlines(True))

def line_indent(line):
    return line[:len(line) - len(line.lstrip(" \t"))]

def normalize_snippet(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.strip("\n") + "\n"
    return text

def detect_indent_unit(data):
    for line in data.splitlines():
        if not line.strip():
            continue

        leading = line[:len(line) - len(line.lstrip(" \t"))]
        if not leading:
            continue

        if "\t" in leading:
            return "\t"

        if " " in leading:
            return "    "

    return "    "

def convert_snippet_indent(snippet, target_indent):
    snippet = snippet.replace("\r\n", "\n").replace("\r", "\n")
    snippet = textwrap.dedent(snippet)

    converted = []

    for raw_line in snippet.splitlines(True):
        if raw_line.endswith("\r\n"):
            content = raw_line[:-2]
            newline = "\r\n"
        elif raw_line.endswith("\n"):
            content = raw_line[:-1]
            newline = "\n"
        else:
            content = raw_line
            newline = ""

        if not content.strip():
            converted.append(newline)
            continue

        stripped = content.lstrip(" \t")
        leading = content[:len(content) - len(stripped)]

        expanded = leading.replace("\t", "    ")
        depth = len(expanded) // 4

        converted.append((target_indent * depth) + stripped + newline)

    return "".join(converted)

def validate_startup_snippet(startup_snippet):
    try:
        test_code = "if True:\n" + indent_block(
            convert_snippet_indent(normalize_snippet(startup_snippet), "    "),
            "    "
        )
        compile(test_code, "<startup_snippet>", "exec")
        return True, "ok"
    except Exception as e:
        return False, str(e)

def find_startup_patch_block(data):
    begin_re = re.compile(
        r'^[ \t]*# ----- AM Lite Trakt startup sync patch BEGIN -----[ \t]*\r?\n',
        re.MULTILINE
    )
    end_re = re.compile(
        r'^[ \t]*# ----- AM Lite Trakt startup sync patch END -----[ \t]*\r?\n?',
        re.MULTILINE
    )

    begin_match = begin_re.search(data)
    if not begin_match:
        return None, None

    end_match = end_re.search(data, begin_match.end())
    if not end_match:
        return None, None

    start_idx = begin_match.start()
    end_idx = end_match.end()

    if data.startswith("\r\n", end_idx):
        end_idx += 2
    elif end_idx < len(data) and data[end_idx] in ("\n", "\r"):
        end_idx += 1

    return start_idx, end_idx

def cleanup_blank_lines(data):
    newline = "\r\n" if "\r\n" in data else "\n"
    normalized = data.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.replace("\n", newline)

def fix_name_main_runner_indentation(data):
    lines = data.splitlines(True)

    for i in range(len(lines) - 1):
        if re.match(r"^[ \t]*if\s+__name__\s*==\s*['\"]__main__['\"]\s*:\s*$", lines[i]):
            j = i + 1

            while j < len(lines) and lines[j].strip() == "":
                j += 1

            if j >= len(lines):
                break

            if not lines[j].startswith((" ", "\t")):
                base_indent = line_indent(lines[i])

                if "\t" in base_indent:
                    lines[j] = base_indent + "\t" + lines[j]
                else:
                    lines[j] = base_indent + "    " + lines[j]

    return "".join(lines)

# PATCH SERVICES
def startup_patch(path, addon_name=None):
    try:
        from acctmgr.modules.obfuscation import startup_snippet, startup_marker

        ok, msg = validate_startup_snippet(startup_snippet)
        if not ok:
            return False, "startup_snippet invalid: %s" % msg

        with open(path, "r", encoding="utf-8") as f:
            data = f.read()

        if startup_marker in data:
            return True, "already patched"

        # Pass addon_name so inject_startup_snippet can handle Umbrella, The Gears, Fen Light, Red Light
        new_data = inject_startup_snippet(data, startup_snippet, addon_name)

        if new_data == data:
            return False, "insert failed"

        try:
            compile(new_data, path, "exec")
        except Exception as e:
            return False, "compile failed: %s" % e

        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new_data)

        with open(path, "r", encoding="utf-8") as f:
            verify = f.read()

        if startup_marker in verify:
            return True, "patched"

        return False, "verification failed"

    except Exception as e:
        return False, str(e)

def startup_unpatch(path):
    try:
        from acctmgr.modules.obfuscation import startup_marker

        with open(path, "r", encoding="utf-8") as f:
            data = f.read()

        if startup_marker not in data:
            return True, "already original"

        start_idx, end_idx = find_startup_patch_block(data)
        if start_idx is None or end_idx is None:
            return False, "remove failed"

        new_data = data[:start_idx] + data[end_idx:]
        new_data = cleanup_blank_lines(new_data)
        new_data = fix_name_main_runner_indentation(new_data)

        if new_data == data:
            return False, "remove failed"

        try:
            compile(new_data, path, "exec")
        except Exception as e:
            return False, "compile failed: %s" % e

        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new_data)

        with open(path, "r", encoding="utf-8") as f:
            verify = f.read()

        if startup_marker not in verify:
            return True, "restored"

        return False, "verification failed"

    except Exception as e:
        return False, str(e)

def inject_startup_snippet(data, startup_snippet, addon_name=None):
    lines = data.splitlines(True)

    # Special handling for Umbrella, Fen Light, Red Light and The Gears
    if addon_name:
        addon_name_lower = addon_name.lower()
        if addon_name_lower == "umbrella":
            idx, indent = find_def_block(lines, "main")
        elif addon_name_lower == "fen light":
            idx, indent = find_def_block(lines, "startServices")
        elif addon_name_lower == "red light":
            idx, indent = find_def_block(lines, "startServices")
        elif addon_name_lower == "the gears":
            idx, indent = find_def_block(lines, "startServices")
        else:
            idx = indent = None

        if idx is not None:
            snippet = prepare_snippet_for_indent(data, startup_snippet, indent)
            return "".join(lines[:idx]) + snippet + "".join(lines[idx:])

    # Fallback to existing logic for all other add-ons
    # 1) Insert above bottom top-level main()
    idx = find_bottom_call(lines, [r"main\s*\(\s*\)"])
    if idx is not None:
        indent = line_indent(lines[idx])
        snippet = prepare_snippet_for_indent(data, startup_snippet, indent)
        return "".join(lines[:idx]) + snippet + "".join(lines[idx:])

    # 2) Insert above bottom top-level *.waitForAbort()
    idx = find_bottom_call(lines, [r"[A-Za-z_][A-Za-z0-9_\.]*\s*\(\s*\)\.waitForAbort\s*\(\s*\)"])
    if idx is not None:
        indent = line_indent(lines[idx])
        snippet = prepare_snippet_for_indent(data, startup_snippet, indent)
        return "".join(lines[:idx]) + snippet + "".join(lines[idx:])

    # 3) Insert above bottom top-level *.run()
    idx = find_bottom_call(lines, [r"[A-Za-z_][A-Za-z0-9_\.]*\s*\(\s*\)\.run\s*\(\s*\)"])
    if idx is not None:
        indent = line_indent(lines[idx])
        snippet = prepare_snippet_for_indent(data, startup_snippet, indent)
        return "".join(lines[:idx]) + snippet + "".join(lines[idx:])

    # 4) Insert inside if __name__ == '__main__'
    idx, indent = find_name_main_block(lines)
    if idx is not None:
        snippet = prepare_snippet_for_indent(data, startup_snippet, indent)
        return "".join(lines[:idx]) + snippet + "".join(lines[idx:])

    # 5) Fallback: after imports
    idx = find_import_insertion_index(lines)
    indent_unit = detect_indent_unit(data)
    normalized = convert_snippet_indent(normalize_snippet(startup_snippet), indent_unit)
    prefix = "" if idx == 0 else "\n"
    return "".join(lines[:idx]) + prefix + normalized + "".join(lines[idx:])

# UNPATCH SERVICES
def unpatch_all_services():
    services = (
        # Fen Light & Forks
        ("Fen Light", var.chk_fenlt, var.path_fenlt_service),
        ("The Gears", var.chk_gears, var.path_gears_service),
        ("Red Light", var.chk_red, var.path_red_service),
        
        # Uniques
        ("Umbrella", var.chk_umb, var.path_umb_service),
        ("Seren", var.chk_seren, var.path_seren_service),
        ("luc_kodi", var.chk_luc, var.path_luc_service),
        
        # Fen & Forks
        ("POV", var.chk_pov, var.path_pov_service),
        
        # Dradis & Forks
        #("Dradis", var.chk_dradis, var.path_dradis_service),
        ("Genocide", var.chk_genocide, var.path_genocide_service),
        
        # Homelander & Forks
        ("Homelander", var.chk_home, var.path_home_service),
        ("Nightwing", var.chk_night, var.path_night_service),
        ("Jokers Absolution", var.chk_absol, var.path_absol_service),
        
        #Scrubs V2 & Forks
        ("Scrubs V2", var.chk_scrubs, var.path_scrubs_service),
        ("Gratis Red", var.chk_redg, var.path_redg_service),
        
        # Others
        ("The Crew", var.chk_crew, var.path_crew_service),
        ("SALTS", var.chk_salts, var.path_salts_service),
        ("Trakt Add-on", var.chk_trakt, var.path_trakt_service),
    )

    results = []

    for name, chk_path, path in services:
        try:
            if not xbmcvfs.exists(chk_path):
                xbmc.log(f"AM Lite: restore default service [{name}]: addon not found", xbmc.LOGINFO)
                results.append((name, False, "addon not found"))
                continue
        
            else:
                    if not xbmcvfs.exists(path):
                        xbmc.log(f"AM Lite: restore default service [{name}]: not found", xbmc.LOGWARNING)
                        results.append((name, path, False, "not found"))
                        continue

            patched, msg = startup_unpatch(path)
            msg_l = msg.lower() if msg else ""

            if msg_l in ("already original", "no change", "no changes needed"):
                xbmc.log(f"AM Lite: restore default service [{name}]: no changes needed", xbmc.LOGINFO)
            elif patched:
                xbmc.log(f"AM Lite: restore default service [{name}]: restored ({msg})", xbmc.LOGINFO)
            else:
                xbmc.log(f"AM Lite: restore default service [{name}]: FAILED ({msg})", xbmc.LOGERROR)

            results.append((name, path, patched, msg))

        except Exception as e:
            xbmc.log(f"AM Lite: restore default service [{name}]: EXCEPTION {e}", xbmc.LOGERROR)
            results.append((name, path, False, str(e)))

    return results
