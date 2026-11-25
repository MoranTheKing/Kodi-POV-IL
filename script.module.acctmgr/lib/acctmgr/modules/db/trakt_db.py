# -*- coding: utf-8 -*-
import xbmc, xbmcaddon
import sqlite3
from acctmgr.modules import var
from acctmgr.modules import log_utils

###################### Create Connection ######################
def create_conn(db_file):
	try:
		return sqlite3.connect(db_file, timeout=3)
	except Exception as e:
		log_utils.error(f"Trakt_db Connect Failed: {e}")

###################### Update Settings ########################
SQL_UPDATE = "UPDATE settings SET setting_value = ? WHERE setting_id = ?"

def update_settings(conn, pairs):
	try:
		cur = conn.cursor()
		for value, setting_id in pairs:
			cur.execute(SQL_UPDATE, (value, setting_id))
			if cur.rowcount != 1:
				raise RuntimeError(f"Missing or duplicate Trakt setting: {setting_id}")
		conn.commit()
		for value, setting_id in pairs:
			cur.execute("SELECT setting_value FROM settings WHERE setting_id = ?", (setting_id,))
			row = cur.fetchone()
			if row is None or str(row[0]) != str(value):
				raise RuntimeError(f"Trakt setting verification failed: {setting_id}")
		return True
	except Exception as e:
		conn.rollback()
		log_utils.error(f"Trakt_db Update Failed: {e}")
		return False
	finally:
		if 'cur' in locals():
			cur.close()

###################### Connect to Database & Update ###########
def connect_db(actions, settings_db):
	conn = None
	try:
		conn = create_conn(settings_db)
		if conn is None:
			return False
		return update_settings(conn, actions)
	except Exception as e:
		log_utils.error(f"Trakt_db Action Failed: {e}")
		return False
	finally:
		if conn is not None:
			conn.close()

###################### Get AM Lite Settings ################
def get():
	acctmgr = xbmcaddon.Addon("script.module.acctmgr")
	return {
		"client":   var.client_am,
		"secret":   var.secret_am,
		"token":    acctmgr.getSetting("trakt.token") or '',
		"username": acctmgr.getSetting("trakt.username") or '',
		"refresh":  '1',
		"expires":  acctmgr.getSetting("trakt.expires") or '',
	}

#################### Auth Trakt ####################
def auth(settings_db):
	tk = get()
	return connect_db([
		(tk["client"],   'trakt.client'),
		(tk["secret"],   'trakt.secret'),
		(tk["token"],    'trakt.token'),
		(tk["username"], 'trakt.user'),
		(tk["refresh"],  'trakt.refresh'),
		(tk["expires"],  'trakt.expires'),
		(1,              'watched_indicators'),
		('Trakt',        'watched_indicators_name'),
	], settings_db)

#################### Revoke Trakt ####################
def revoke_trakt(settings_db, addon_name):
    connect_db([
        ('empty_setting', 'trakt.client'),
        ('empty_setting', 'trakt.secret'),
        ('empty_setting', 'trakt.token'),
        ('empty_setting', 'trakt.user'),
        ('empty_setting', 'trakt.refresh'),
        ('empty_setting', 'trakt.expires'),
        (0,               'watched_indicators'),
        (addon_name,      'watched_indicators_name'),
    ], settings_db)
