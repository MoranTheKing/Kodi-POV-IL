import os
import threading
import sqlite3
import xbmc
import xbmcvfs

POV_ADDON_ID = 'plugin.video.pov'

def _clean_db(cache_string):
    """
    Background task to purge a specific stuck empty row from the DB.
    Flattened to prevent closure/scope leakage.
    """
    db_path = xbmcvfs.translatePath(f'special://profile/addon_data/{POV_ADDON_ID}/maincache.db')
    if not os.path.isfile(db_path):
        return

    try:
        # Context manager ensures connection closes even on exception
        with sqlite3.connect(db_path, timeout=5.0, isolation_level=None) as conn:
            cur = conn.cursor()

            # STRICT FIX: Delete ONLY the exact empty string.
            # Removed destructive wildcard (LIKE) wipes.
            cur.execute("DELETE FROM maincache WHERE id = ?", (cache_string,))
            deleted = cur.rowcount
            cur.close()

        if deleted > 0:
            xbmc.log(
                f"[WIZARD] pov_cache_handler: Purged stuck empty record from maincache (ID: {cache_string})",
                xbmc.LOGINFO
            )
    except Exception as e:
        xbmc.log(f"[WIZARD] pov_cache_handler Error: {e}", xbmc.LOGWARNING)

def handle_empty(cache_string):
    """
    Triggered via hook from POV's cache_object() ONLY when an API call returns empty.
    Spawns a background thread to maintain high UI responsiveness.
    """
    # STRICT FIX: Pass variable explicitly via args tuple. No dynamic closures.
    threading.Thread(
        target=_clean_db,
        args=(cache_string,),
        name="Wizard_POVCacheCleaner"
    ).start()