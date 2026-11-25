# -*- coding: utf-8 -*-
import xbmc, xbmcaddon
import sqlite3
from acctmgr.modules import log_utils

###################### Create Connection ######################
def create_conn(db_file):
    try:
        return sqlite3.connect(db_file, timeout=3)
    except Exception as e:
        log_utils.error(f"Offcloud_db Connect Failed: {e}")

###################### Update Settings ########################
SQL_UPDATE = "UPDATE settings SET setting_value = ? WHERE setting_id = ?"

def update_settings(conn, pairs):
    try:
        cur = conn.cursor()
        for value, setting_id in pairs:
            cur.execute(SQL_UPDATE, (value, setting_id))
        conn.commit()
        cur.close()
    except Exception as e:
        log_utils.error(f"Offcloud_db Update Failed: {e}")

###################### Connect to Database & Update ###########
def connect_db(actions, settings_db):
    try:
        conn = create_conn(settings_db)
        with conn:
            update_settings(conn, actions)
    except Exception as e:
        log_utils.error(f"Offcloud_db Connection Failed: {e}")

###################### Get AM Lite Settings ################
def get():
	acctmgr = xbmcaddon.Addon("script.module.acctmgr")
	return (
		acctmgr.getSetting("offcloud.token") or '',
		acctmgr.getSetting("offcloud.userid") or '',
	)

#################### Auth Offcloud ##################
def auth(settings_db):
	token, user_id = get()
	connect_db([
		('true', 'oc.enabled'),
		(token, 'oc.token'),
		(user_id, 'oc.account_id'),
	], settings_db)

######################## Revoke Offcloud ############
def revoke(settings_db):
    connect_db([
        ('false', 'oc.enabled'),
        ('empty_setting', 'oc.token'),
        ('empty_setting', 'oc.account_id'),
    ], settings_db)
