# File: plugin.program.kodipovilwizard/resources/lib/patches/pov_fav_refresh_manage.py

import xbmc

def run(local_vars):
    """
    Executes the list toggle logic and forces a container refresh (if safe).
    Returns the toggle result to properly satisfy the BaseListManager.manage() exit flow.
    Includes a safety guard to prevent crashes when executing from a Search results container.
    """
    try:
        self_obj = local_vars.get('self')
        choice = local_vars.get('choice')
        action_add = local_vars.get('action_add')

        # Pull kodi_utils safely from the upstream locals
        kodi_utils = local_vars.get('kodi_utils')

        # 1. Execute the original upstream toggle logic safely
        toggle_result = self_obj.execute_toggle(choice, action_add)

        # 2. GUARD: Do not refresh if the current container is a search result.
        # Re-fetching a search query re-entrantly from a toggle crashes the screen.
        folder_path = xbmc.getInfoLabel('Container.FolderPath') or ''

        if 'search' not in folder_path.lower():
            if kodi_utils:
                kodi_utils.container_refresh()

        return toggle_result

    except Exception as e:
        xbmc.log(f"[Wizard Addon] Error in pov_fav_refresh_manage: {e}", xbmc.LOGERROR)
        return None