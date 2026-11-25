# -*- coding: utf-8 -*-
import xbmc, xbmcaddon
import sqlite3
from acctmgr.modules import log_utils

char_remov = ["'", ",", ")", "("]

###################### Create Connection ######################
def create_conn(db_file):
    try:
        return sqlite3.connect(db_file, timeout=3)
    except Exception as e:
        log_utils.error(f"chk_auth_db Connect Failed: {e}")

#################### Fetch Token ####################
def chk_auth(settings_db, token):
    conn = create_conn(settings_db)
    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT setting_value FROM settings WHERE setting_id = ?", (token,))
        chk_auth = str(cursor.fetchone())
        cursor.close()
    for char in char_remov:
        chk_auth = chk_auth.replace(char, "")
    return chk_auth
