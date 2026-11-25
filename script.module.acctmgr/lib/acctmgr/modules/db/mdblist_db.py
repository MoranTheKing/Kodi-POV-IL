# -*- coding: utf-8 -*-
import sqlite3
from acctmgr.modules import log_utils

###################### Create Connection ######################
def create_conn(db_file):
	try:
		return sqlite3.connect(db_file, timeout=3)
	except Exception as e:
		log_utils.error(f"MDBList_db Connect Failed: {e}")

###################### Update Settings ########################
SQL_UPDATE = "UPDATE settings SET setting_value = ? WHERE setting_id = ?"

def update_settings(conn, settings):
	try:
		cur = conn.cursor()
		for setting_id, value in settings.items():
			cur.execute(SQL_UPDATE, (value, setting_id))
		conn.commit()
		cur.close()
	except Exception as e:
		log_utils.error(f"MDBList_db Update Failed: {e}")

###################### Connect to Database & Update ###########
def update(settings_db, settings):
	try:
		conn = create_conn(settings_db)
		if conn is None:
			return
		with conn:
			update_settings(conn, settings)
	except Exception as e:
		log_utils.error(f"MDBList_db Action Failed: {e}")

#################### Revoke MDBList ####################
def revoke_redlight(settings_db):
	update(settings_db, {
		'mdblist.token': '0',
		'mdblist.user': 'empty_setting',
		'mdblist.refresh': '0',
		'mdblist.cm_menu_migrated': 'false',
	})

def revoke_gears(settings_db):
	update(settings_db, {
		'mdblist.api_key': '',
		'mdblist.user': 'empty_setting',
	})
