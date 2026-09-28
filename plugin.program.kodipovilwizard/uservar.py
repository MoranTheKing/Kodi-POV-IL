import xbmcaddon

import os

#########################################################
#         Global Variables - DON'T EDIT!!!              #
#########################################################
ADDON_ID = xbmcaddon.Addon().getAddonInfo('id')
PATH = xbmcaddon.Addon().getAddonInfo('path')
ART = os.path.join(PATH, 'resources', 'media')
CUSTOM_ART = os.path.join(PATH, 'resources', 'kodi_rd_israel_art')
#########################################################

#########################################################
#        User Edit Variables                            #
#########################################################
ADDONTITLE = '[COLOR yellow]Kodi POV IL Wizard[/COLOR]'
BUILDERNAME = '[COLOR yellow]Kodi POV IL[/COLOR]'
# KODI-POV-IL - Canonical build NAME. Used by startup.py to populate the
# 'buildname' setting on APK installs where the user never went through a
# wizard-driven Fresh Install (so the setting is empty), and as the single build
# label shown in the Builds menu. Must match the manifest's build name.
BUILDNAME_DEFAULT = 'Kodi POV IL - FENtastic'
# KODI-POV-IL - Canonical build VERSION. This is the single source of truth for
# the build version under the modular architecture: it is what check.check_build
# reports, what Fresh Install / the .provisioned marker pin into the
# 'buildversion' setting, and what the Builds menu displays. (It no longer has
# anything to do with a monolithic build zip -- those are gone.)
BUILDVERSION_DEFAULT = '0.1.45'
EXCLUDES = [ADDON_ID]
# KODI-POV-IL - build.txt / BUILDFILE has been DELETED. The build is now
# described entirely by manifest.json (MANIFEST_URL, below); the full install and
# all updates go through ModularUpdater. There is no monolithic build / quickfix
# zip and no remote build descriptor any more.
# How often you would like it to check for build updates in days
# 0 being every startup of kodi
UPDATECHECK = 0
# Text File with apk info in it.  Leave as 'http://' to ignore
APKFILE = 'http://'

#########################################################
# KODI-RD-IL - BUILD SKIN SWITCH
BUILD_SKIN_SWITCH_IMAGE_URL = 'https://github.com/MoranTheKing/Kodi-POV-IL/raw/main/wizard/assets/build_menu_screenshots/pov_il_splash.jpg'
# KODI-POV-IL - MODULAR UPDATER (Phase 2/3, manifest-based; replaces the
# legacy text-file quick_update). Raw manifest.json produced by the new
# Monorepo CI pipeline. The wizard polls this on startup and updates only
# the addons whose version moved.
MANIFEST_URL = 'https://raw.githubusercontent.com/MoranTheKing/Kodi-POV-IL/main/manifest.json'

#########################################################

ADDONFILE = 'http://'
# Text File for advanced settings.  Leave as 'http://' to ignore
ADVANCEDFILE = 'http://'
#########################################################

#########################################################
#        Theming Menu Items                             #
#########################################################
# If you want to use locally stored icons the place them in the Resources/Art/
# folder of the wizard then use os.path.join(ART, 'imagename.png')
# do not place quotes around os.path.join
# Example:  ICONMAINT     = os.path.join(ART, 'mainticon.png')
#           ICONSETTINGS  = 'https://www.yourhost.com/repo/wizard/settings.png'
# Leave as http:// for default icon
ICONBUILDS = os.path.join(CUSTOM_ART, 'wizard.jpg')
ICONMAINT = os.path.join(CUSTOM_ART, 'wizard.jpg')
ICONSPEED = os.path.join(CUSTOM_ART, 'wizard.jpg')
ICONAPK = os.path.join(CUSTOM_ART, 'wizard.jpg')
ICONADDONS = os.path.join(CUSTOM_ART, 'wizard.jpg')
ICONSAVE = os.path.join(CUSTOM_ART, 'wizard.jpg')
ICONTRAKT = os.path.join(CUSTOM_ART, 'wizard.jpg')
ICONREAL = os.path.join(CUSTOM_ART, 'wizard.jpg')
ICONLOGIN = os.path.join(CUSTOM_ART, 'wizard.jpg')
ICONCONTACT = os.path.join(CUSTOM_ART, 'wizard.jpg')
ICONSETTINGS = os.path.join(CUSTOM_ART, 'wizard.jpg')
# Hide the section separators 'Yes' or 'No'
HIDESPACERS = 'No'
# Character used in separator
SPACER = '='

# You can edit these however you want, just make sure that you have a %s in each of the
# THEME's so it grabs the text from the menu item
COLOR1 = 'blue'
COLOR2 = 'yellow'
COLOR_LIMEGREEN = 'limegreen'
COLOR_YELLOW = 'yellow'
COLOR_WHITE = 'white'
# Primary menu items   / {0} is the menu item and is required
THEME1 = u'[COLOR {color1}][I][COLOR {color1}][B]Kodi POV IL[/B][/COLOR][COLOR {color2}][COLOR {color1}] - [/I][/COLOR] [COLOR {color2}]{{}}[/COLOR]'.format(color1=COLOR1, color2=COLOR2)
# Build Names          / {0} is the menu item and is required
THEME2 = u'[COLOR {color1}]{{}}[/COLOR]'.format(color1=COLOR1)
# Alternate items      / {0} is the menu item and is required
THEME3 = u'[COLOR {color1}]{{}}[/COLOR]'.format(color1=COLOR1)
# LIMEGREEN Alternate items      / {0} is the menu item and is required
THEME_LIMEGREEN = u'[COLOR {color1}]{{}}[/COLOR]'.format(color1=COLOR_LIMEGREEN)
# YELLOW Alternate items      / {0} is the menu item and is required
THEME_YELLOW = u'[COLOR {color1}]{{}}[/COLOR]'.format(color1=COLOR_YELLOW)
# Current Build Header / {0} is the menu item and is required
THEME4 = u'[COLOR {color1}]בילד נוכחי:[/COLOR] [COLOR {color2}]{{}}[/COLOR]'.format(color1=COLOR1, color2=COLOR2)
# Current Theme Header / {0} is the menu item and is required
THEME5 = u'[COLOR {color1}]Current Theme:[/COLOR] [COLOR {color2}]{{}}[/COLOR]'.format(color1=COLOR1, color2=COLOR2)
# KODI_RD_ISRAEL Custom Theme for COLOR_WHITE text usage (window.py - def show_dialog)
THEME6 = u'[COLOR {COLOR_WHITE}]{{}}[/COLOR]'.format(COLOR_WHITE=COLOR_WHITE)

# Message for Contact Page
# Enable 'Contact' menu item 'Yes' hide or 'No' dont hide
HIDECONTACT = 'No'
# You can add \n to do line breaks
CONTACT = 'ברוכים הבאים! תודה שבחרתם בבילד שלנו.\n\nכדי שתוכלו ליהנות מחוויית צפייה מושלמת,\nלהישאר תמיד מעודכנים בגרסאות האחרונות\nולקבל תמיכה טכנית מהירה לכל שאלה –\nהצטרפו לקהילה הרשמית שלנו!\n\nסרקו את קוד ה-QR באמצעות המכשיר הנייד שלכם והצטרפו אלינו לקהילה בטלגרם.'
# Images used for the contact window.  http:// for default icon and fanart
CONTACTICON = os.path.join(ART, 'qricon.jpg')
CONTACTFANART = 'http://'
#########################################################

#########################################################
#        Auto Update For Those With No Repo             #
#########################################################
# Enable Auto Update 'Yes' or 'No'
AUTOUPDATE = 'No'
#########################################################

#########################################################
#        Auto Install Repo If Not Installed             #
#########################################################
# Enable Auto Install 'Yes' or 'No'
AUTOINSTALL = 'No'
# Addon ID for the repository
REPOID = 'spaceholder'
# Url to Addons.xml file in your repo folder(this is so we can get the latest version)
REPOADDONXML = 'https://'
# Url to folder zip is located in
REPOZIPURL = 'https://'
#########################################################

#########################################################
#        Notification Window                            #
#########################################################
# Enable Notification screen Yes or No
ENABLE = 'No'
# Url to notification file
NOTIFICATION = 'https://raw.githubusercontent.com/MoranTheKing/Kodi-POV-IL/main/wizard/assets/notification_files/build_first_launch.txt'
# Use either 'Text' or 'Image'
HEADERTYPE = 'Image'
# Font size of header
FONTHEADER = 'Font14'
HEADERMESSAGE = ''
# url to image if using Image 424x180
HEADERIMAGE = os.path.join(CUSTOM_ART, 'kodi_rd_il_icon.png')
# Font for Notification Window
FONTSETTINGS = 'Font13'
# Background for Notification Window
BACKGROUND = 'http://'
#########################################################
