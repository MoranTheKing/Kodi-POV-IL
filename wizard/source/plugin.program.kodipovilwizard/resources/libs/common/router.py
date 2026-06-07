import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

import sys

try:  # Python 3
    from urllib.parse import parse_qsl
except ImportError:  # Python 2
    from urlparse import parse_qsl

from resources.libs.common.config import CONFIG
from resources.libs.common import logging
from resources.libs.common import tools
from resources.libs.gui import menu

advanced_settings_mode = 'advanced_settings'
addon_installer_mode = 'addons'


class Router:
    def __init__(self):
        self.route = None
        self.params = {}
        tools.ensure_folders()

    def _log_params(self, paramstring):
        _url = sys.argv[0]

        self.params = dict(parse_qsl(paramstring))

        logstring = '{0}: '.format(_url)
        for param in self.params:
            logstring += '[ {0}: {1} ] '.format(param, self.params[param])

        logging.log(logstring, level=xbmc.LOGDEBUG)

        return self.params

    def _build_switch_skin_jsonrpc(self):
        from resources.libs import skin as skin_lib
        from resources.libs.wizard import Wizard
        from resources.libs.wizard import ensure_arctic_fuse_3_installed
        from resources.libs.wizard import update_favourites_xml_file
        from resources.libs.gui import window

        if not CONFIG.get_setting('buildname'):
            logging.log_notify(CONFIG.ADDONTITLE,
                               '[COLOR {0}]לא מותקן בילד![/COLOR]'.format(CONFIG.COLOR2))
            return

        msg = 'הסקינים הקיימים בבילד:\n1. סקין Estuary\n2. סקין FENtastic\n3. סקין Arctic Fuse 3'
        window.show_notification_with_extra_image(msg, 888, CONFIG.BUILD_SKIN_SWITCH_IMAGE_URL)

        skin_mapping = {
            'סקין Estuary - מראה פשוט עם כפתורים': 'skin.estuary',
            'סקין FENtastic - יפהפה': 'skin.fentastic',
            'סקין Arctic Fuse 3 - מודרני (ניסיוני)': 'skin.arctic.fuse.3'
        }

        current_skin = skin_lib._get_old('lookandfeel.skin') or CONFIG.SKIN
        current_skin_name = next(
            (skin_name for skin_name, skin_addon_name in skin_mapping.items()
             if skin_addon_name == current_skin),
            'סקין לא מזוהה')
        skins_list = [
            skin_name for skin_name, skin_addon_name in skin_mapping.items()
            if skin_addon_name != current_skin
        ]

        dialog = xbmcgui.Dialog()
        gotoskin_index_number = dialog.select(
            '[B]סקין נוכחי: [COLOR gold]{0}[/COLOR][/B]'.format(current_skin_name),
            skins_list)
        if gotoskin_index_number == -1:
            return

        selected_skin = skins_list[gotoskin_index_number]
        gotoskin = skin_mapping[selected_skin]

        yes_pressed = dialog.yesno(
            CONFIG.ADDONTITLE,
            '[B][COLOR {0}]האם ברצונך להחליף סקין ל:\n[COLOR {1}]{2}[/COLOR]?[/COLOR][/B]'.format(
                CONFIG.COLOR2, CONFIG.COLOR1, selected_skin),
            nolabel='[B][COLOR red]ביטול[/COLOR][/B]',
            yeslabel='[B][COLOR springgreen]החלף סקין[/COLOR][/B]')
        if not yes_pressed:
            return

        if gotoskin == 'skin.arctic.fuse.3':
            if not ensure_arctic_fuse_3_installed():
                logging.log_notify(CONFIG.ADDONTITLE,
                                   '[COLOR {0}]Arctic Fuse 3 לא הותקן - מבטל[/COLOR]'.format(CONFIG.COLOR2))
                return

        dialog_progress = xbmcgui.DialogProgress()
        dialog_text = '[COLOR {0}][B]מחליף סקין ומגדיר את מסך הבית של:[/B][/COLOR]\n[COLOR {1}][B]{2}[/B][/COLOR]'.format(
            CONFIG.COLOR2, CONFIG.COLOR1, selected_skin)
        dialog_progress.create(CONFIG.ADDONTITLE, dialog_text)
        for s in range(3, -1, -1):
            dialog_progress.update(int((3 - s) / 3.0 * 100), dialog_text)
            xbmc.sleep(1000)

        if not skin_lib.switch_to_skin(gotoskin, 'Build Skin Switch'):
            dialog_progress.close()
            return

        xbmc.sleep(500)

        if not update_favourites_xml_file(gotoskin):
            dialog_progress.close()
            return

        dialog_progress.close()
        Wizard().force_close_kodi_in_5_seconds(dialog_header='סקין הוחלף בהצלחה!')

    def dispatch(self, handle, paramstring):
        self._log_params(paramstring)

        mode = self.params['mode'] if 'mode' in self.params else None
        url = self.params['url'] if 'url' in self.params else None
        name = self.params['name'] if 'name' in self.params else None
        action = self.params['action'] if 'action' in self.params else None
        #####################################################
        # KODI-RD-IL
        auto_quick_update = self.params['auto_quick_update'] if 'auto_quick_update' in self.params else None
        kodi_version_update_check_manual = self.params['kodi_version_update_check_manual'] if 'kodi_version_update_check_manual' in self.params else None
        #####################################################

        # MAIN MENU
        if mode is None:
            from resources.libs.gui.main_menu import MainMenu
            MainMenu().get_listing()
            self._finish(handle)

        # SETTINGS
        elif mode == 'settings':  # OpenWizard settings
            CONFIG.open_settings(name)
            xbmc.executebuiltin('Container.Refresh()')
        elif mode == 'opensettings':  # Open other addons' settings
            settings_id = eval(url.upper() + 'ID')[name]['plugin']
            CONFIG.open_settings(settings_id)
            xbmc.executebuiltin('Container.Refresh()')
        elif mode == 'togglesetting':  # Toggle a setting
            CONFIG.set_setting(name, 'false' if CONFIG.get_setting(name) == 'true' else 'true')
            xbmc.executebuiltin('Container.Refresh()')

        # MENU SECTIONS
        elif mode == 'builds':  # Builds
            from resources.libs.gui.build_menu import BuildMenu
            BuildMenu().get_listing()
            self._finish(handle)
        elif mode == 'viewbuild':  # Builds -> "Your Build"
            from resources.libs.gui.build_menu import BuildMenu
            BuildMenu().view_build(name)
            self._finish(handle)
        elif mode == 'buildinfo':  # Builds -> Build Info
            from resources.libs.gui.build_menu import BuildMenu
            BuildMenu().build_info(name)
        elif mode == 'buildpreview':  # Builds -> Build Preview
            from resources.libs.gui.build_menu import BuildMenu
            BuildMenu().build_video(name)
        elif mode == 'install':  # Builds -> Fresh Install/Standard Install/Apply guifix
            from resources.libs.wizard import Wizard

            over = self.params.get('over', 'false') == 'true'
            if action == 'build':
                Wizard().build(name, over=over)
            elif action == 'gui':
                Wizard().gui(name)
            #####################################################
            # KODI-RD-IL
            elif action == 'quick_update':
                Wizard().quick_update(name, auto_quick_update)
            # KODI-RD-IL
            elif action == 'build_switch_skin':
                self._build_switch_skin_jsonrpc()
            elif action == 'install_af3_ce':
                from resources.libs.wizard import ensure_arctic_fuse_3_installed
                ensure_arctic_fuse_3_installed()
            elif action == 'af3_tools':
                from resources.libs.wizard import af3_tools_menu
                af3_tools_menu()
            elif action == 'af3_tool':
                from resources.libs.wizard import af3_tool_action
                af3_tool_action(self.params.get('tool', ''))
            # KODI-RD-IL
            elif action == 'kodi_version_update_check':
                from resources.libs.wizard import kodi_version_update_check
                kodi_version_update_check(kodi_version_update_check_manual)
            #####################################################
            elif action == 'theme':  # Builds -> "Your Build" -> "Your Theme"
                Wizard().theme(name, url)

        elif mode == 'maint':  # Maintenance + Maintenance -> any "Tools" section
            from resources.libs.gui.maintenance_menu import MaintenanceMenu

            if name == 'clean':
                MaintenanceMenu().clean_menu()
            elif name == 'addon':
                MaintenanceMenu().addon_menu()
            elif name == 'misc':
                MaintenanceMenu().misc_menu()
            elif name == 'backup':
                MaintenanceMenu().backup_menu()
            elif name == 'tweaks':
                MaintenanceMenu().tweaks_menu()
            elif name == 'logging':
                MaintenanceMenu().logging_menu()
            elif name is None:
                MaintenanceMenu().get_listing()
                
            self._finish(handle)

        elif mode == 'enableaddons':  # Maintenance - > Addon Tools -> Enable/Disable Addons
            menu.enable_addons()
            self._finish(handle)
        elif mode == 'enableall':
            menu.enable_addons(all=True)
        elif mode == 'toggleaddon':
            from resources.libs import db
            db.toggle_addon(name, url)
            xbmc.executebuiltin('Container.Refresh()')
        elif mode == 'forceupdate':
            from resources.libs import db
            db.force_check_updates(auto=action)
        ############KODI-RD-IL##############
        elif mode == 'forceupdateFAST':
            from resources.libs import db
            db.forceUpdate()
        ####################################
        elif mode == 'togglecache':
            from resources.libs import clear
            clear.toggle_cache(name)
            xbmc.executebuiltin('Container.Refresh()')
        elif mode == 'changefreq':  # Maintenance - Auto Clean Frequency
            menu.change_freq()
            xbmc.executebuiltin('Container.Refresh()')
        elif mode == 'systeminfo':  # Maintenance -> System Tweaks/Fixes -> System Information
            menu.system_info()
            self._finish(handle)
        elif mode == 'nettools':  # Maintenance -> Misc Maintenance -> Network Tools
            menu.net_tools()
            self._finish(handle)
        elif mode == 'runspeedtest':  # Maintenance -> Misc Maintenance -> Network Tools -> Speed Test -> Run Speed Test
            menu.run_speed_test()
            xbmc.executebuiltin('Container.Refresh()')
        elif mode == 'clearspeedtest':  # Maintenance -> Misc Maintenance -> Network Tools -> Speed Test -> Clear Results
            menu.clear_speed_test()
            xbmc.executebuiltin('Container.Refresh()')
        elif mode == 'viewspeedtest':  # Maintenance -> Misc Maintenance -> Network Tools -> Speed Test -> any previous test
            menu.view_speed_test(name)
            xbmc.executebuiltin('Container.Refresh()')
        elif mode == 'viewIP':  # Maintenance -> Misc Maintenance -> Network Tools -> View IP Address & MAC Address
            menu.view_ip()
            self._finish(handle)
        elif mode == 'speedtest': 
            xbmc.executebuiltin('InstallAddon("script.speedtester")')
            xbmc.executebuiltin('RunAddon("script.speedtester")')
        ############KODI-RD-IL##############
        elif mode == 'build_speed_test': # KODI-RD-IL Real Debrid Speed Test
            from resources.libs.wizard import build_speed_test
            build_speed_test()
        ####################################
        elif mode == 'apk':  # APK Installer
            menu.apk_menu(url)
            self._finish(handle)
        elif mode == 'kodiapk':  # APK Installer -> Official Kodi APK's
            xbmc.executebuiltin('RunScript(script.kodi.android.update)')
        elif mode == 'fmchoose':
            from resources.libs import install
            install.choose_file_manager()
        elif mode == 'apkinstall':
            from resources.libs import install
            install.install_apk(name, url)
        elif mode == 'removeaddondata':  # Maintenance - > Addon Tools -> Remove Addon Data
            menu.remove_addon_data_menu()
            self._finish(handle)
        elif mode == 'savedata':  # Save Data + Builds -> Save Data Menu
            menu.save_menu()
            self._finish(handle)
        elif mode == 'youtube':  # "YouTube Section"
            menu.youtube_menu(url)
            self._finish(handle)
        elif mode == 'viewVideo':  # View  Video
            from resources.libs import yt
            yt.play_video(url)
        elif mode == 'trakt':  # Save Data -> Keep Trakt Data
            menu.trakt_menu()
            self._finish(handle)
        elif mode == 'realdebrid':  # Save Data -> Keep Debrid
            menu.debrid_menu()
