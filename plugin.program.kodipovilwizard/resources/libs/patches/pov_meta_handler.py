# File : plugin.program.kodipovilwizard/resources/libs/patches/pov_meta_handler.py

import os
import threading
import sqlite3
import xbmc
import xbmcvfs

POV_ADDON_ID = 'plugin.video.pov'

def clear_blank_meta():
    """
    Triggered by the metadata.py early-return hooks when a transient API failure
    generates a blank_entry. Clears out any existing poisoned rows from the DB asynchronously.
    """
    def _clean_db():
        try:
            db_path = xbmcvfs.translatePath(f'special://profile/addon_data/{POV_ADDON_ID}/metacache.db')
            if not os.path.isfile(db_path):
                return

            # Short timeout to avoid locking the UI thread if the DB is busy
            conn = sqlite3.connect(db_path, timeout=5.0, isolation_level=None)
            cur = conn.cursor()

            # The `meta` column contains repr(dict), so we can cleanly wildcard for the boolean flag
            cur.execute("DELETE FROM metadata WHERE meta LIKE '%blank_entry%'")
            deleted = cur.rowcount

            cur.close()
            conn.close()

            if deleted > 0:
                xbmc.log(
                    f"[WIZARD] pov_meta_handler: Successfully purged {deleted} poisoned 'blank_entry' row(s) from metacache.db",
                    xbmc.LOGINFO
                )
        except Exception as e:
            xbmc.log(f"[WIZARD] pov_meta_handler SQLite Error: {e}", xbmc.LOGWARNING)

    # Dispatch to background thread
    threading.Thread(target=_clean_db, name="Wizard_MetaCacheCleaner").start()