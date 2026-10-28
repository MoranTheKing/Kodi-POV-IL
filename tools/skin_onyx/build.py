# -*- coding: utf-8 -*-
"""Regenerate every generated part of skin.povil.onyx, in order.

    python build.py            (from tools/skin_onyx)

Home.xml + Includes_POVIL_Home.xml + RTL timers, the views, then the OSD
(its variables are appended to Includes_POVIL_Home.xml, so it runs last).
Textures and fonts are separate: gen_textures.py, gen_icons.py, gen_fonts.py.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKIN = os.path.normpath(os.path.join(HERE, '..', '..', 'skin.povil.onyx'))
for script in ('gen_strings.py', 'patch_onyx.py', 'gen_home.py', 'gen_views.py', 'gen_osd.py', 'gen_info.py', 'gen_dialogs.py'):
    subprocess.run([sys.executable, os.path.join(HERE, script), SKIN], cwd=HERE, check=True)
