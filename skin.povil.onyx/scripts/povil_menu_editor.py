# -*- coding: utf-8 -*-
"""The build's menu editor inside the skin (Onyx 1.0.29), for a viewer who has Onyx without the Kodi POV IL Wizard: the
bar's order, names and the viewer's own buttons, the shortcuts under each button, the rows and their order. A viewer, Nov
2026: Onyx alone gave him "only the rows" -- the full editor lived in the Wizard. povil_menu/resources/libs/ holds the
Wizard's own menu_editor.py, custom_rows.py and home_rows.py, copied by tools/skin_onyx/gen_standalone.py: one source,
never edited here.

    RunScript(special://skin/scripts/povil_menu_editor.py)                the editor
    RunScript(special://skin/scripts/povil_menu_editor.py,rows)           its rows
    RunScript(special://skin/scripts/povil_menu_editor.py,custom_rows)    the viewer's own rows and shortcuts
    RunScript(special://skin/scripts/povil_menu_editor.py,home_rows)      the order of the rows
"""
import sys

import xbmcvfs

sys.path.insert(0, xbmcvfs.translatePath('special://skin/scripts/povil_menu'))
PART = sys.argv[1] if len(sys.argv) > 1 else ''
if PART == 'custom_rows':
    from resources.libs import custom_rows
    custom_rows.choose()
elif PART == 'home_rows':
    from resources.libs import home_rows
    home_rows.choose()
else:
    from resources.libs import menu_editor
    menu_editor.choose(PART or None)
