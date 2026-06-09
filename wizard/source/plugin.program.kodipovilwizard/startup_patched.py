# -*- coding: utf-8 -*-
"""Kodi POV IL startup wrapper.

Runs small runtime patches that must affect already-installed files, then imports
OpenWizard's original startup.py so the normal startup flow continues unchanged.
"""

try:
    from resources.libs import fentastic_player_switch_patcher
    fentastic_player_switch_patcher.safe_ensure_patched()
except Exception:
    # Never block Kodi/Wizard startup because of a cosmetic skin patch.
    pass

# Importing startup executes the original service logic.
import startup  # noqa: F401,E402
