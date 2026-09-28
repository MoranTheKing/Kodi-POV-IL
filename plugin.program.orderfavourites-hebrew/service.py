# -*- coding: utf-8 -*-
# Startup service: (re)install the build's bundled icons/fonts into the global
# Kodi media folders (special://home/media/povil_icons/ and .../Fonts/) and
# refresh favourites.xml from favourites_config.json. It OVERWRITES the bundled
# icons/fonts and the (internal-shortcut-only) favourites.xml so UI/icon updates
# reach users even when those files already exist. Fully guarded -- never raises.

try:
    from resources.lib.media_installer import install_global_media_assets
    install_global_media_assets()
except Exception:
    pass
