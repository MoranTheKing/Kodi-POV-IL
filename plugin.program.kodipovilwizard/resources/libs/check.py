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

import xbmc
import xbmcgui

import glob
import os
import re
import sys

try:
    from urllib.request import urlopen
    from urllib.request import Request
except ImportError:
    from urllib2 import urlopen
    from urllib2 import Request

from resources.libs.common.config import CONFIG


def _version_tuple(value):
    try:
        return tuple(int(part) for part in str(value).split('.') if part != '')
    except Exception:
        return (0,)


def _is_newer_version(latest, current):
    latest_tuple = _version_tuple(latest)
    current_tuple = _version_tuple(current)
    width = max(len(latest_tuple), len(current_tuple))
    latest_tuple += (0,) * (width - len(latest_tuple))
    current_tuple += (0,) * (width - len(current_tuple))
    return latest_tuple > current_tuple


def check_paths():
    from resources.libs.common import logging

    dialog = xbmcgui.Dialog()
    
    logging.log("[Path Check] Started")
    path = CONFIG.ADDON_PATH
    pathclean = CONFIG.ADDON_PATH.replace('\\','/')
    folderpath = pathclean.split('/')[-2]
    if not CONFIG.ADDON_ID == folderpath:
        dialog.ok(CONFIG.ADDONTITLE,
                      '[COLOR {0}]Please make sure that the plugin folder is the same as the add-on id.[/COLOR]'.format(CONFIG.COLOR2) + '\n' + '[COLOR {0}]Plugin ID:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR2, CONFIG.COLOR1, CONFIG.ADDON_ID) + '\n' + '[COLOR {0}]Plugin Folder:[/COLOR] [COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR2, CONFIG.COLOR1, path))
        logging.log("[Path Check] ADDON_ID and plugin folder doesnt match. {0} / {1} ".format(CONFIG.ADDON_ID, path))
    else:
        logging.log("[Path Check] Good!")


def check_build(name, ret, release_id=None):
    # KODI-POV-IL - build.txt is RETIRED. The build is no longer described by a
    # remote OpenWizard-style text file and there is NO monolithic build / gui
    # ("quickfix") zip any more: the full install and all updates go through
    # ModularUpdater (manifest.json). This shim keeps the remaining legacy
    # callers working by returning safe, static per-field values:
    #   - 'version' -> the canonical build version (BUILDVERSION_DEFAULT)
    #   - 'kodi'    -> the RUNNING Kodi major, so the build() version-mismatch
    #                  warning can never fire
    #   - 'url'/'gui'/'theme'/'minor'/'info' -> '' (nothing to download)
    #   - 'icon'/'fanart' -> the build splash, for the menus
    version = getattr(CONFIG, 'BUILDVERSION_DEFAULT', None) or getattr(CONFIG, 'BUILDVERSION', '') or '0.0.0'
    try:
        kodi = str(int(float(CONFIG.KODIV)))
    except Exception:
        kodi = '21'
    splash = getattr(CONFIG, 'BUILD_SKIN_SWITCH_IMAGE_URL', '') or ''
    fields = {
        'version': version,
        'url': '',          # no monolithic build zip
        'minor': '',
        'gui': '',          # no monolithic quickfix zip
        'kodi': kodi,       # == running Kodi -> no warning dialog
        'theme': '',        # themes retired with build.txt
        'icon': splash,
        'fanart': splash,
        'adult': 'no',
        'info': '',
        'description': getattr(CONFIG, 'ADDONTITLE', name),
    }
    if ret == 'all':
        return (name, fields['version'], fields['url'], fields['minor'], fields['gui'],
                fields['kodi'], fields['theme'], fields['icon'], fields['fanart'],
                fields['adult'], fields['info'], fields['description'])
    return fields.get(ret, '')


def check_info(name):
    from resources.libs.common import tools

    link = name.replace('\n', '').replace('\r', '').replace('\t', '')
    match = re.compile('.+?ame="(.+?)".+?xtracted="(.+?)".+?ipsize="(.+?)".+?kin="(.+?)".+?reated="(.+?)".+?rograms="(.+?)".+?ideo="(.+?)".+?usic="(.+?)".+?icture="(.+?)".+?epos="(.+?)".+?cripts="(.+?)".+?inaries="(.+?)"').findall(link)
    if len(match) > 0:
        for name, extracted, zipsize, skin, created, programs, video, music, picture, repos, scripts, binaries in match:
            return name, extracted, zipsize, skin, created, programs, video, music, picture, repos, scripts, binaries
    else:
        return False


def check_theme(name, theme, ret):
    # KODI-POV-IL - build themes were a build.txt feature and are retired.
    return False


def check_wizard(ret):
    # KODI-POV-IL - the wizard no longer self-updates from build.txt; it is
    # updated like any other addon through ModularUpdater (manifest.json).
    # Returning False keeps the legacy AUTOUPDATE menu / update.wizard_update()
    # callers as safe no-ops.
    return False


def check_build_update():
    # KODI-POV-IL - RETIRED. The legacy build.txt full-build update check is
    # gone; addon + config updates are handled by ModularUpdater (manifest.json)
    # on every startup. Kept as a no-op so any stray caller is harmless.
    return


def check_skin():
    from resources.libs.common import logging
    from resources.libs.common import tools

    dialog = xbmcgui.Dialog()
    
    logging.log("[Build Check] Invalid Skin Check Start")
    
    gotoskin = False
    if not CONFIG.DEFAULTSKIN == '':
        if os.path.exists(os.path.join(CONFIG.ADDONS, CONFIG.DEFAULTSKIN)):
            if dialog.yesno(CONFIG.ADDONTITLE,
                                "[COLOR {0}]It seems that the skin has been set back to [COLOR {1}]{2}[/COLOR]".format(CONFIG.COLOR2, CONFIG.COLOR1, CONFIG.SKIN[5:].title()) + '\n' + "Would you like to set the skin back to:[/COLOR]" + '\n' + '[COLOR {0}]{1}[/COLOR]'.format(CONFIG.COLOR1, CONFIG.DEFAULTNAME)):
                gotoskin = CONFIG.DEFAULTSKIN
                gotoname = CONFIG.DEFAULTNAME
            else:
                logging.log("Skin was not reset")
                CONFIG.set_setting('defaultskinignore', 'true')
                gotoskin = False
        else:
            CONFIG.set_setting('defaultskin', '')
            CONFIG.set_setting('defaultskinname', '')
            CONFIG.DEFAULTSKIN = ''
            CONFIG.DEFAULTNAME = ''
    if CONFIG.DEFAULTSKIN == '':
        skinname = []
        skinlist = []
        for folder in glob.glob(os.path.join(CONFIG.ADDONS, 'skin.*/')):
            xml = "{0}/addon.xml".format(folder)
            if os.path.exists(xml):
                g = tools.read_from_file(xml).replace('\n', '').replace('\r', '').replace('\t', '')
                match = tools.parse_dom(g, 'addon', ret='id')
                match2 = tools.parse_dom(g, 'addon', ret='name')
                logging.log("{0}: {1}".format(folder, str(match[0])))
                if len(match) > 0:
                    skinlist.append(str(match[0]))
                    skinname.append(str(match2[0]))
                else:
                    logging.log("ID not found for {0}".format(folder))
            else:
                logging.log("ID not found for {0}".format(folder))
        if len(skinlist) > 0:
            if len(skinlist) > 1:
                if dialog.yesno(CONFIG.ADDONTITLE,
                                    "[COLOR {0}]It seems that the skin has been set back to [COLOR {1}]{2}[/COLOR]".format(CONFIG.COLOR2, CONFIG.COLOR1, CONFIG.SKIN[5:].title()) + '\n' + "Would you like to view a list of avaliable skins?[/COLOR]"):
                    choice = dialog.select("Select skin to switch to!", skinname)
                    if choice == -1:
                        logging.log("Skin was not reset")
                        CONFIG.set_setting('defaultskinignore', 'true')
                    else:
                        gotoskin = skinlist[choice]
                        gotoname = skinname[choice]
                else:
                    logging.log("Skin was not reset")
                    CONFIG.set_setting('defaultskinignore', 'true')
            else:
                if dialog.yesno(CONFIG.ADDONTITLE,
                                    "[COLOR {0}]It seems that the skin has been set back to [COLOR {1}]{2}[/COLOR]".format(CONFIG.COLOR2, CONFIG.COLOR1, CONFIG.SKIN[5:].title()) + '\n' + "Would you like to set the skin back to:[/COLOR]" + '\n' + '[COLOR {0}]{1}[/COLOR]'.format(CONFIG.COLOR1, skinname[0])):
                    gotoskin = skinlist[0]
                    gotoname = skinname[0]
                else:
                    logging.log("Skin was not reset")
                    CONFIG.set_setting('defaultskinignore', 'true')
        else:
            logging.log("No skins found in addons folder.")
            CONFIG.set_setting('defaultskinignore', 'true')
            gotoskin = False
    if gotoskin:
        from resources.libs import skin

        if skin.switch_to_skin(gotoskin):
            skin.look_and_feel_data('restore')
    logging.log("[Build Check] Invalid Skin Check End")


def check_sources():
    from resources.libs.common import logging
    from resources.libs.common import tools

    dialog = xbmcgui.Dialog()
    progress_dialog = xbmcgui.DialogProgress()
    
    if not os.path.exists(CONFIG.SOURCES):
        logging.log_notify(CONFIG.ADDONTITLE,
                           "[COLOR {0}]No sources.xml File Found![/COLOR]".format(CONFIG.COLOR2))
        return False
    x = 0
    bad = []
    remove = []
    a = tools.read_from_file(CONFIG.SOURCES)
    temp = a.replace('\r', '').replace('\n', '').replace('\t', '')
    match = re.compile('<files>.+?</files>').findall(temp)

    if len(match) > 0:
        match2 = re.compile('<source>.+?<name>(.+?)</name>.+?<path pathversion="1">(.+?)</path>.+?<allowsharing>(.+?)</allowsharing>.+?</source>').findall(match[0])
        progress_dialog.create(CONFIG.ADDONTITLE, "[COLOR {0}]Scanning Sources for Broken links[/COLOR]".format(CONFIG.COLOR2))
        for name, path, sharing in match2:
            x += 1
            perc = int(tools.percentage(x, len(match2)))
            progress_dialog.update(perc,
                          '' + '\n' + "[COLOR {0}]Checking [COLOR {1}]{2}[/COLOR]:[/COLOR]".format(CONFIG.COLOR2, CONFIG.COLOR1, name) + '\n' + "[COLOR {0}]{1}[/COLOR]".format(CONFIG.COLOR1, path))
                          
            working = tools.open_url(path, check=True)
            if not working:
                bad.append([name, path, sharing, working])

        logging.log("Bad Sources: {0}".format(len(bad)))
        if len(bad) > 0:
            choice = dialog.yesno(CONFIG.ADDONTITLE, "[COLOR {0}]{1}[/COLOR][COLOR {2}] Source(s) have been found Broken".format(CONFIG.COLOR1, len(bad), CONFIG.COLOR2) + '\n' + "Would you like to Remove all or choose one by one?[/COLOR]",
                                      yeslabel="[B][COLOR springgreen]Remove All[/COLOR][/B]",
                                      nolabel="[B][COLOR red]Choose to Delete[/COLOR][/B]")
            if choice == 1:
                remove = bad
            else:
                for name, path, sharing, working in bad:
                    logging.log("{0} sources: {1}, {2}".format(name, path, working))
                    if dialog.yesno(CONFIG.ADDONTITLE,
                                        "[COLOR {0}]{1}[/COLOR][COLOR {2}] was reported as non working".format(CONFIG.COLOR1, name, CONFIG.COLOR2) + '\n' + "[COLOR {0}]{1}[/COLOR]".format(CONFIG.COLOR1, path) + '\n' + "[COLOR {0}]{1}[/COLOR]".format(CONFIG.COLOR1, working),
                                        yeslabel="[B][COLOR springgreen]Remove Source[/COLOR][/B]",
                                        nolabel="[B][COLOR red]Keep Source[/COLOR][/B]"):
                        remove.append([name, path, sharing, working])
                        logging.log("Removing Source {0}".format(name))
                    else:
                        logging.log("Source {0} was not removed".format(name))
            if len(remove) > 0:
                for name, path, sharing, working in remove:
                    a = a.replace('\n<source>\n<name>{0}</name>\n<path pathversion="1">{1}</path>\n<allowsharing>{2}</allowsharing>\n</source>'.format(name, path, sharing), '')
                    logging.log("Removing Source {0}".format(name))

                tools.write_to_file(CONFIG.SOURCES, str(a))
                alive = len(match) - len(bad)
                kept = len(bad) - len(remove)
                removed = len(remove)
                dialog.ok(CONFIG.ADDONTITLE,
                              "[COLOR {0}]Checking sources for broken paths has been completed".format(CONFIG.COLOR2) + '\n' + "Working: [COLOR {0}]{1}[/COLOR] | Kept: [COLOR {2}]{3}[/COLOR] | Removed: [COLOR {4}]{5}[/COLOR][/COLOR]".format(CONFIG.COLOR2, CONFIG.COLOR1, alive, CONFIG.COLOR1, kept, CONFIG.COLOR1, removed))
            else:
                logging.log("No Bad Sources to be removed.")
        else:
            logging.log_notify(CONFIG.ADDONTITLE,
                               "[COLOR {0}]All Sources Are Working[/COLOR]".format(CONFIG.COLOR2))
    else:
        logging.log("No Sources Found")


def check_repos():
    from resources.libs.common import logging
    from resources.libs.common import tools

    progress_dialog = xbmcgui.DialogProgress()
    
    progress_dialog.create(CONFIG.ADDONTITLE, '[COLOR {0}]Checking Repositories...[/COLOR]'.format(CONFIG.COLOR2))
    badrepos = []
    xbmc.executebuiltin('UpdateAddonRepos')
    repolist = glob.glob(os.path.join(CONFIG.ADDONS, 'repo*'))
    if len(repolist) == 0:
        progress_dialog.close()
        logging.log_notify(CONFIG.ADDONTITLE,
                           "[COLOR {0}]No Repositories Found![/COLOR]".format(CONFIG.COLOR2))
        return
    sleeptime = len(repolist)
    start = 0
    while start < sleeptime:
        start += 1
        if progress_dialog.iscanceled():
            break
        perc = int(tools.percentage(start, sleeptime))
        progress_dialog.update(perc,
                      '\n' + '[COLOR {0}]Checking: [/COLOR][COLOR {1}]{2}[/COLOR]'.format(CONFIG.COLOR2, CONFIG.COLOR1, repolist[start-1].replace(CONFIG.ADDONS, '')[1:]))
        xbmc.sleep(1000)
    if progress_dialog.iscanceled():
        progress_dialog.close()
        logging.log_notify(CONFIG.ADDONTITLE,
                           "[COLOR {0}]Enabling Addons Cancelled[/COLOR]".format(CONFIG.COLOR2))
        sys.exit()
    progress_dialog.close()
    logfile = logging.grab_log()
    fails = re.compile('CRepositoryUpdateJob(.+?)failed').findall(logfile)
    for item in fails:
        logging.log("Bad Repository: {0} ".format(item))
        brokenrepo = item.replace('[', '').replace(']', '').replace(' ', '').replace('/', '').replace('\\', '')
        if brokenrepo not in badrepos:
            badrepos.append(brokenrepo)
    if len(badrepos) > 0:
        msg = "[COLOR {0}]Below is a list of Repositories that did not resolve.  This does not mean that they are Depreciated, sometimes hosts go down for a short period of time.  Please do serveral scans of your repository list before removing a repository just to make sure it is broken.[/COLOR][CR][CR][COLOR {1}]".format(CONFIG.COLOR2, CONFIG.COLOR1)
        msg += '[CR]'.join(badrepos)
        msg += '[/COLOR]'
        window.show_text_box("Viewing Broken Repositories", msg)
    else:
        logging.log_notify(CONFIG.ADDONTITLE,
                           "[COLOR {0}]All Repositories Working![/COLOR]".format(CONFIG.COLOR2))


def build_count():
    # KODI-POV-IL - exactly one build now (no build.txt listing). Reported as a
    # single build on the running Kodi major so the legacy Builds menu still
    # renders one entry. (total, count20, count21, adultcount, hidden)
    return 1, 0, 0, 0, 0


