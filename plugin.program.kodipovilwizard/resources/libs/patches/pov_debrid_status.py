# File: plugin.program.kodipovilwizard/resources/lib/patches/pov_debrid_status.py

import sys
import xbmc

def run(local_vars):
    """
    Dynamically neutralizes upstream generic Debrid notifications.
    This allows the custom build's Hebrew/icon-aware toasts to fire without duplicate spam.
    We monkey-patch the common locations where POV handles account notifications in memory.
    """
    try:
        patched = False

        # 1. Target potential module locations for the upstream notification routine
        modules_to_check = [
            'entry',
            'resources.lib.modules.debrid',
            'resources.lib.modules.real_debrid',
            'resources.lib.modules.premiumize',
            'resources.lib.modules.alldebrid',
            'resources.lib.modules.torbox',
            'resources.lib.modules.offcloud'
        ]

        for mod_name in modules_to_check:
            try:
                # Force module load if it exists in the environment
                __import__(mod_name)
                mod = sys.modules.get(mod_name)
                if mod and hasattr(mod, 'premAccntNotification'):
                    # Nullify the function in memory so it immediately returns
                    setattr(mod, 'premAccntNotification', lambda *args, **kwargs: None)
                    patched = True
            except Exception:
                continue

        # 2. As a fallback, check if it was integrated as a class method on POVMonitor
        try:
            from entry import POVMonitor
            if hasattr(POVMonitor, 'premAccntNotification'):
                setattr(POVMonitor, 'premAccntNotification', lambda *args, **kwargs: None)
                patched = True
        except Exception:
            pass

        if patched:
            xbmc.log("[POV Wizard] Successfully neutralized upstream Debrid expiry notifications in memory.", xbmc.LOGINFO)
        else:
            xbmc.log("[POV Wizard] Warning: Upstream premAccntNotification not found; it may have been renamed or removed.", xbmc.LOGWARNING)

    except Exception as e:
        xbmc.log(f"[POV Wizard] Error in debrid status dynamic patch: {e}", xbmc.LOGERROR)