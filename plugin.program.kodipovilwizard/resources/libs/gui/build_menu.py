################################################################################
#      Copyright (C) 2019 drinfernoo                                           #
#                                                                              #
#  This Program is free software; you can redistribute it and/or modify        #
#  it under the terms of the GNU General Public License as published by        #
#  the Free Software Foundation; either version 2, or (at your option)         #
#  any later version.                                                          #
#                                                                              #
#  This Program is distributed in the hope that it will be useful,             #
#  but WITHOUT ANY WARRANTY; without even the implied warranty of              #
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the                #
#  GNU General Public License for more details.                                #
#                                                                              #
#  You should have received a copy of the GNU General Public License           #
#  along with XBMC; see the file COPYING.  If not, write to                    #
#  the Free Software Foundation, 675 Mass Ave, Cambridge, MA 02139, USA.       #
#  http://www.gnu.org/copyleft/gpl.html                                        #
################################################################################

import re

try:  # Python 3
    from urllib.parse import quote_plus
except ImportError:  # Python 2
    from urllib import quote_plus

from resources.libs import check
from resources.libs.common import directory
from resources.libs.common import tools
from resources.libs.common.config import CONFIG


class BuildMenu:

    def _list_all(self, match, kodiv=None):
        from resources.libs import test

        for name, version, url, gui, kodi, theme, icon, fanart, adult, description in match:
            if not CONFIG.SHOWADULT == 'true' and adult.lower() == 'yes':
                continue
            if not CONFIG.DEVELOPER == 'true' and test.str_test(name):
                continue

            if not kodiv or kodiv == int(float(kodi)):
                menu = self.create_install_menu(name)
                if float(kodi) == 21.0:
                    directory.add_dir('{0} (v{1})'.format(name, version), {'mode': 'viewbuild', 'name': name}, description=description, fanart=fanart, icon=icon, menu=menu, themeit=CONFIG.THEME_YELLOW)
                    directory.add_separator()
                elif float(kodi) == 20.0:
                    directory.add_dir('{0} (v{1})'.format(name, version), {'mode': 'viewbuild', 'name': name}, description=description, fanart=fanart, icon=icon, menu=menu, themeit=CONFIG.THEME_YELLOW)
                    directory.add_separator()
                else:
                    directory.add_dir('{0} (v{1})'.format(name, version), {'mode': 'viewbuild', 'name': name}, description=description, fanart=fanart, icon=icon, menu=menu, themeit=CONFIG.THEME2)
                    directory.add_separator()
                

    def theme_count(self, name, count=True):
        from resources.libs import check
        from resources.libs.common import tools

        themefile = check.check_build(name, 'theme')

        response = tools.open_url(themefile)

        if not response:
            return False

        themetext = response.text
        link = tools.clean_text(themetext)
        match = re.compile('name="(.+?)"').findall(link)

        if len(match) == 0:
            return False

        themes = []
        for item in match:
            themes.append(item)
            
        if len(themes) > 0:
            if count:
                return len(themes)
            else:
                return themes
        else:
            return False

    def get_listing(self):
        # KODI-POV-IL - build.txt is retired, so there is no remote build list to
        # scrape. There is exactly ONE build now, fully described by manifest.json
        # + static constants, so go straight to its view.
        self.view_build(CONFIG.BUILDNAME_DEFAULT)

    def view_build(self, name):
        # KODI-POV-IL - single modular build view. The "Full Install" button runs
        # ModularUpdater.run_fresh_install() (no monolithic zip / no wipe); the
        # update button runs the manifest-based quick_update. Themes + the old
        # build.txt scraping are gone.
        version = check.check_build(name, 'version')
        icon = check.check_build(name, 'icon')
        fanart = check.check_build(name, 'fanart')
        description = check.check_build(name, 'description')

        build = '{0} (v{1})'.format(name, version)
        if CONFIG.BUILDNAME == name and CONFIG.BUILDVERSION:
            build = '{0} [COLOR springgreen][מותקן v{1}][/COLOR]'.format(build, CONFIG.BUILDVERSION)
        directory.add_file(build, description=description, fanart=fanart, icon=icon, themeit=CONFIG.THEME4)

        directory.add_separator('עדכון')
        directory.add_file('למשתמשים קיימים: הבילד מתעדכן אוטומטית. אין צורך בהתקנה מלאה.',
                           description=description, fanart=fanart, icon=icon, themeit=CONFIG.THEME4)
        directory.add_file('לחץ כאן לבדיקת עדכונים (עדכון מהיר)',
                           {'mode': 'install', 'action': 'quick_update', 'name': name,
                            'auto_quick_update': 'false'},
                           description=description, fanart=fanart, icon=icon, themeit=CONFIG.THEME1)

        directory.add_separator('התקנה חדשה / השלמת התקנה')
        directory.add_file('התקנת הבילד — אינה נדרשת לעדכון גרסה',
                           {'mode': 'install', 'action': 'build', 'name': name},
                           description=description, fanart=fanart, icon=icon, themeit=CONFIG.THEME1)

        directory.add_separator()
        directory.add_dir('תפריט שמירת נתונים', {'mode': 'savedata'}, icon=CONFIG.ICONSAVE, themeit=CONFIG.THEME3)
        directory.add_file('מידע על הבילד', {'mode': 'buildinfo', 'name': name},
                           description=description, fanart=fanart, icon=icon, themeit=CONFIG.THEME3)

    def build_info(self, name):
        from resources.libs import check
        from resources.libs.gui import window

        # KODI-POV-IL - static build info (build.txt + its extended info file are
        # retired). Version comes from manifest.json / static constants.
        version = check.check_build(name, 'version')
        kodi = check.check_build(name, 'kodi')
        description = check.check_build(name, 'description')

        msg = "[COLOR {0}]Build Name:[/COLOR] [COLOR {1}]{2}[/COLOR][CR]".format(CONFIG.COLOR2, CONFIG.COLOR1, name)
        msg += "[COLOR {0}]Build Version:[/COLOR] [COLOR {1}]{2}[/COLOR][CR]".format(CONFIG.COLOR2, CONFIG.COLOR1, version)
        msg += "[COLOR {0}]Kodi Version:[/COLOR] [COLOR {1}]{2}[/COLOR][CR]".format(CONFIG.COLOR2, CONFIG.COLOR1, kodi)
        msg += "[COLOR {0}]Description:[/COLOR] [COLOR {1}]{2}[/COLOR][CR]".format(CONFIG.COLOR2, CONFIG.COLOR1, description)

        window.show_text_box("Viewing Build Info: {0}".format(name), msg)

    def create_install_menu(self, name):
        menu_items = []

        buildname = quote_plus(name)
        menu_items.append((CONFIG.THEME2.format(name), 'RunAddon({0}, ?mode=viewbuild&name={1})'.format(CONFIG.ADDON_ID, buildname)))
        menu_items.append((CONFIG.THEME3.format('Fresh Install'), 'RunPlugin(plugin://{0}/?mode=install&name={1}&url=fresh)'.format(CONFIG.ADDON_ID, buildname)))
        menu_items.append((CONFIG.THEME3.format('Normal Install'), 'RunPlugin(plugin://{0}/?mode=install&name={1}&url=normal)'.format(CONFIG.ADDON_ID, buildname)))
        menu_items.append((CONFIG.THEME3.format('Apply guiFix'), 'RunPlugin(plugin://{0}/?mode=install&name={1}&url=gui)'.format(CONFIG.ADDON_ID, buildname)))
        menu_items.append((CONFIG.THEME3.format('Build Information'), 'RunPlugin(plugin://{0}/?mode=buildinfo&name={1})'.format(CONFIG.ADDON_ID, buildname)))
        menu_items.append((CONFIG.THEME2.format('{0} Settings'.format(CONFIG.ADDONTITLE)), 'RunPlugin(plugin://{0}/?mode=settings)'.format(CONFIG.ADDON_ID)))

        return menu_items
