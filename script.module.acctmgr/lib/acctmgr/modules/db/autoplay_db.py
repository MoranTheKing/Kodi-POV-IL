# -*- coding: utf-8 -*-
import sqlite3
from acctmgr.modules import log_utils, var

###################### Create Connection ######################
def create_conn(db_file):
    try:
        return sqlite3.connect(db_file, timeout=3)
    except Exception as e:
        log_utils.error(f"Autoplay Sync_db Connect Failed: {e}")

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
        log_utils.error(f"Autoplay Sync_db Update Failed: {e}")

###################### Connect to Database & Update ###########
def connect_db(actions, settings_db):
    try:
        conn = create_conn(settings_db)
        if not conn:
            return
        with conn:
            update_settings(conn, actions)
    except Exception as e:
        log_utils.error(f"Autoplay Sync_db Connection Failed: {e}")

#################### Autoplay Profiles #########################
PLAYBACK_MAP = {
    var.DIR: 'false',
    var.AUTO:  'true',
}

#################### Addon Definitions #########################
ADDONS = {
    "fenlight": {
        "db": var.fenlt_settings_db,
        "settings": (
            'auto_play_movie',
            'auto_play_episode',
        ),
        "log": "Fen Light",
    },
    "gears": {
        "db": var.gears_settings_db,
        "settings": (
            'auto_play_movie',
            'auto_play_episode',
        ),
        "log": "The Gears",
    },
    "red": {
        "db": var.red_settings_db,
        "settings": (
            'auto_play_movie',
            'auto_play_episode',
        ),
        "log": "Red Light",
    },
}

#################### Apply Autoplay #########################
def apply_playback(mode):

    playback = PLAYBACK_MAP.get(mode)
    if not playback:
        log_utils.error(f"AutoplaySync: Invalid mode received: {mode}")
        return False

    for addon, meta in ADDONS.items():
        try:
            actions = [(playback, setting_id) for setting_id in meta["settings"]]
            connect_db(actions, meta["db"])
        except Exception as e:
            log_utils.error(f"{meta['log']} Autoplay Failed: {e}")

    return True
