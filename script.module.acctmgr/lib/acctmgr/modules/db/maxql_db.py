# -*- coding: utf-8 -*-
import sqlite3
from acctmgr.modules import log_utils, var

###################### Create Connection ######################
def create_conn(db_file):
    try:
        return sqlite3.connect(db_file, timeout=3)
    except Exception as e:
        log_utils.error(f"QualitySync_db Connect Failed: {e}")

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
        log_utils.error(f"QualitySync_db Update Failed: {e}")

###################### Connect to Database & Update ###########
def connect_db(actions, settings_db):
    try:
        conn = create_conn(settings_db)
        if not conn:
            return
        with conn:
            update_settings(conn, actions)
    except Exception as e:
        log_utils.error(f"QualitySync_db Connection Failed: {e}")

#################### Quality Profiles #########################
QUALITY_MAP = {
    var.QL_UHD: 'SD, 720p, 1080p, 4K',
    var.QL_HD:  'SD, 720p, 1080p',
    var.QL_SD:  'SD, 720p',
}

#################### Addon Definitions #########################
ADDONS = {
    "fenlight": {
        "db": var.fenlt_settings_db,
        "settings": (
            'results_quality_movie',
            'results_quality_episode',
            'autoplay_quality_movie',
            'autoplay_quality_episode',
        ),
        "log": "Fen Light",
    },
    "gears": {
        "db": var.gears_settings_db,
        "settings": (
            'results_quality_movie',
            'results_quality_episode',
            'autoplay_quality_movie',
            'autoplay_quality_episode',
        ),
        "log": "Gears",
    },
    "red": {
        "db": var.red_settings_db,
        "settings": (
            'results_quality_movie',
            'results_quality_episode',
            'autoplay_quality_movie',
            'autoplay_quality_episode',
        ),
        "log": "Red Light",
    },
}

#################### Apply Quality #########################
def apply_quality(mode):

    quality = QUALITY_MAP.get(mode)
    if not quality:
        log_utils.error(f"QualitySync: Invalid mode received: {mode}")
        return False

    for addon, meta in ADDONS.items():
        try:
            actions = [(quality, setting_id) for setting_id in meta["settings"]]
            connect_db(actions, meta["db"])
        except Exception as e:
            log_utils.error(f"{meta['log']} MaxQL Failed: {e}")

    return True
