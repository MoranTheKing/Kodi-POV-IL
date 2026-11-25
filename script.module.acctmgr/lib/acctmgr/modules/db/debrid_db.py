# -*- coding: utf-8 -*-
import xbmc, xbmcaddon
import sqlite3
from acctmgr.modules import log_utils

###################### Create Connection ######################
def create_conn(db_file):
    try:
        return sqlite3.connect(db_file, timeout=3)
    except Exception as e:
        log_utils.error(f"Debrid_db Connect Failed: {e}")

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
        log_utils.error(f"Debrid_db Update Failed: {e}")

###################### Connect to Database & Update ###########
def connect_db(actions, settings_db):
    try:
        conn = create_conn(settings_db)
        with conn:
            update_settings(conn, actions)
    except Exception as e:
        log_utils.error(f"Debrid_db Connection Failed: {e}")

###################### Get AM Lite Settings ################
def get_rd():
    acctmgr = xbmcaddon.Addon("script.module.acctmgr")
    return {
        "username": acctmgr.getSetting("realdebrid.username") or '',
        "token": acctmgr.getSetting("realdebrid.token") or '',
        "client_id": acctmgr.getSetting("realdebrid.client_id") or '',
        "refresh": acctmgr.getSetting("realdebrid.refresh") or '',
        "secret": acctmgr.getSetting("realdebrid.secret") or '',
    }

def get_pm():
    acctmgr = xbmcaddon.Addon("script.module.acctmgr")
    return {
        "username": acctmgr.getSetting("premiumize.username") or '',
        "token": acctmgr.getSetting("premiumize.token") or '',
    }

def get_ad():
    acctmgr = xbmcaddon.Addon("script.module.acctmgr")
    return {
        "username": acctmgr.getSetting("alldebrid.username") or '',
        "token": acctmgr.getSetting("alldebrid.token") or '',
    }

######################## Real-Debrid ##########################
def auth_rd(settings_db):
    rd = get_rd()
    connect_db([
        ('true', 'rd.enabled'),
        (rd["token"], 'rd.token'),
        (rd["username"], 'rd.account_id'),
        (rd["client_id"], 'rd.client_id'),
        (rd["refresh"], 'rd.refresh'),
        (rd["secret"], 'rd.secret'),
    ], settings_db)

def enable_rd(settings_db):
    connect_db([('true', 'rd.enabled')], settings_db)

def disable_rd(settings_db):
    connect_db([('false', 'rd.enabled')], settings_db)

def revoke_rd(settings_db):
    connect_db([
        ('empty_setting', 'rd.enabled'),
        ('empty_setting', 'rd.token'),
        ('empty_setting', 'rd.account_id'),
        ('empty_setting', 'rd.client_id'),
        ('empty_setting', 'rd.refresh'),
        ('empty_setting', 'rd.secret'),
    ], settings_db)

######################## Premiumize ###########################
def auth_pm(settings_db):
    pm = get_pm()
    connect_db([
        ('true', 'pm.enabled'),
        (pm["token"], 'pm.token'),
        (pm["username"], 'pm.account_id'),
    ], settings_db)

def enable_pm(settings_db):
    connect_db([('true', 'pm.enabled')], settings_db)

def disable_pm(settings_db):
    connect_db([('false', 'pm.enabled')], settings_db)

def revoke_pm(settings_db):
    connect_db([
        ('empty_setting', 'pm.enabled'),
        ('empty_setting', 'pm.token'),
        ('empty_setting', 'pm.account_id'),
    ], settings_db)

######################## All-Debrid ###########################
def auth_ad(settings_db):
    ad = get_ad()
    connect_db([
        ('true', 'ad.enabled'),
        (ad["token"], 'ad.token'),
        (ad["username"], 'ad.account_id'),
    ], settings_db)

def enable_ad(settings_db):
    connect_db([('true', 'ad.enabled')], settings_db)

def disable_ad(settings_db):
    connect_db([('false', 'ad.enabled')], settings_db)

def revoke_ad(settings_db):
    connect_db([
        ('empty_setting', 'ad.enabled'),
        ('empty_setting', 'ad.token'),
        ('empty_setting', 'ad.account_id'),
    ], settings_db)
