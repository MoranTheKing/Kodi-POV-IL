# -*- coding: utf-8 -*-
import xbmc
import sqlite3

###################### Create Connection ######################
def create_conn(db_file):
    try:
        return sqlite3.connect(db_file)
    except Exception:
        log_utils.error("Ext_db Connect Failed")

###################### Update Settings ###########################
SQL_UPDATE = "UPDATE settings SET setting_value = ? WHERE setting_id = ?"

def update_settings(conn, pairs):
    try:
        cur = conn.cursor()
        for value, setting_id in pairs:
            cur.execute(SQL_UPDATE, (value, setting_id))
        conn.commit()
        cur.close()
    except Exception:
        log_utils.error("Ext_db Update Failed")

###################### Connect to Database & Update #####################
def connect_db(actions, settings_db):
    try:
        conn = create_conn(settings_db)
        with conn:
            update_settings(conn, actions)
    except Exception:
        log_utils.error("Ext_db Action Failed")

######################## External Providers ####################
def auth_ext(name, module, settings_db):
    connect_db([
        ('true', 'provider.external'),
        (name, 'external_scraper.name'),
        (module, 'external_scraper.module'),
    ], settings_db)
