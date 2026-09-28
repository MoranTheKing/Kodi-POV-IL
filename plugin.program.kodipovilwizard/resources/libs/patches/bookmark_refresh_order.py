# File: plugin.program.kodipovilwizard/resources/libs/patches/bookmark_refresh_order.py

import xbmc

def run(local_vars, global_vars):
    """
    Executes the bookmark save operations in the correct order:
    1. Network Trakt/MDBList sync (cache invalidation).
    2. UI Container/Widget Refresh.
    """
    try:
        watched_indicators = local_vars.get('watched_indicators')
        refresh = local_vars.get('refresh')
        kodi_utils = global_vars.get('kodi_utils')

        # 1. Progress Write (Execute BEFORE UI refresh to prevent race conditions)
        if watched_indicators in (1, 2):
            func_name = 'mdbl_progress' if watched_indicators == 2 else 'trakt_progress'
            progress_func = global_vars.get(func_name)

            if progress_func:
                progress_func(
                    'set_progress',
                    local_vars.get('mediatype'),
                    local_vars.get('tmdb_id'),
                    local_vars.get('resume_point'),
                    local_vars.get('season'),
                    local_vars.get('episode'),
                    refresh=True
                )

        # 2. Container/Widget Refresh (Execute AFTER progress sync completes)
        if refresh == 'true' and kodi_utils:
            if kodi_utils.external_browse():
                kodi_utils.widget_refresh()
            else:
                kodi_utils.container_refresh()

    except Exception as e:
        xbmc.log(f"[WIZARD-PATCH] Error in bookmark_refresh_order logic: {e}", xbmc.LOGWARNING)