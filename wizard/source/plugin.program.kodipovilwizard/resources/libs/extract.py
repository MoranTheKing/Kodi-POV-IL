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

import os
import sys
import zlib
try:  # Python 3
    import zipfile
except ImportError:  # Python 2
    from resources.libs import zipfile

from resources.libs.common.config import CONFIG
from resources.libs.common import logging
from resources.libs.common import tools
from resources.libs.common import custom_save_data_config
from resources.libs import install


                       
########################################################################################################################################################

# KODI RD ISRAEL - Custom Save Data Config
# try:

    # is_first_install = 'true' if CONFIG.get_setting('installed') in ('false', 'ignored') else 'false'

    # logging.log("################################", level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY BEFORE: IS FIRST INSTALL: " + is_first_install, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY BEFORE: CONFIG.KEEPTRAKT: " + CONFIG.KEEPTRAKT, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY BEFORE: CONFIG.KEEPDEBRID: " + CONFIG.KEEPDEBRID, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY BEFORE: CONFIG.KEEPLOGIN: " + CONFIG.KEEPLOGIN, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY BEFORE: CONFIG.KEEPFENDATA: " + CONFIG.KEEPFENDATA, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY BEFORE: CONFIG.KEEPTWILIGHTDATA: " + CONFIG.KEEPTWILIGHTDATA, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY BEFORE: CONFIG.KEEPFENTASTICDATA: " + CONFIG.KEEPFENTASTICDATA, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY BEFORE: CONFIG.KEEPFAVS: " + CONFIG.KEEPFAVS, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY BEFORE: CONFIG.KEEPSOURCES: " + CONFIG.KEEPSOURCES, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY BEFORE: CONFIG.KEEPADVANCED: " + CONFIG.KEEPADVANCED, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY BEFORE: CONFIG.KEEPPROFILES: " + CONFIG.KEEPPROFILES, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY BEFORE: CONFIG.KEEPPLAYERCORE: " + CONFIG.KEEPPLAYERCORE, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY BEFORE: CONFIG.KEEPGUISETTINGS: " + CONFIG.KEEPGUISETTINGS, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY BEFORE: CONFIG.KEEPREPOS: " + CONFIG.KEEPREPOS, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY BEFORE: CONFIG.KEEPSUPER: " + CONFIG.KEEPSUPER, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY BEFORE: CONFIG.KEEPWHITELIST: " + CONFIG.KEEPWHITELIST, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY BEFORE: CONFIG.KEEPADDONS33DB: " + CONFIG.KEEPADDONS33DB, level=xbmc.LOGINFO)

    # Delete whitelist.txt if CONFIG.KEEPWHITELIST is false to avoid addons deletion.
    # if CONFIG.KEEPWHITELIST == 'false':
        # custom_save_data_config.delete_addons_whitelist_file()
        
    # Set variables value from JSON file + addons whitelist, only if NOT first install.    
    # if CONFIG.USE_GITHUB_CUSTOM_SAVE_DATA_CONFIG == 'true':
        # logging.log("CONFIG.USE_GITHUB_CUSTOM_SAVE_DATA_CONFIG is: " + CONFIG.USE_GITHUB_CUSTOM_SAVE_DATA_CONFIG + ". Checking if not first install..", level=xbmc.LOGINFO)
        
        # if is_first_install == 'true':
            # logging.log("Looks like first install. Skipping custom_save_data_config..", level=xbmc.LOGINFO)
        # else:
            # logging.log("Not first install. Starting custom_save_data_config..", level=xbmc.LOGINFO)
            # custom_save_data_config.main()
            
    # else:
        # logging.log("CONFIG.USE_GITHUB_CUSTOM_SAVE_DATA_CONFIG is: " + CONFIG.USE_GITHUB_CUSTOM_SAVE_DATA_CONFIG + ". Skipping..", level=xbmc.LOGINFO)

    # logging.log("################################", level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY AFTER: IS FIRST INSTALL: " + is_first_install, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY AFTER: CONFIG.KEEPTRAKT: " + CONFIG.KEEPTRAKT, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY AFTER: CONFIG.KEEPDEBRID: " + CONFIG.KEEPDEBRID, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY AFTER: CONFIG.KEEPLOGIN: " + CONFIG.KEEPLOGIN, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY AFTER: CONFIG.KEEPFENDATA: " + CONFIG.KEEPFENDATA, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY AFTER: CONFIG.KEEPTWILIGHTDATA: " + CONFIG.KEEPTWILIGHTDATA, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY AFTER: CONFIG.KEEPFENTASTICDATA: " + CONFIG.KEEPFENTASTICDATA, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY AFTER: CONFIG.KEEPFAVS: " + CONFIG.KEEPFAVS, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY AFTER: CONFIG.KEEPSOURCES: " + CONFIG.KEEPSOURCES, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY AFTER: CONFIG.KEEPADVANCED: " + CONFIG.KEEPADVANCED, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY AFTER: CONFIG.KEEPPROFILES: " + CONFIG.KEEPPROFILES, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY AFTER: CONFIG.KEEPPLAYERCORE: " + CONFIG.KEEPPLAYERCORE, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY AFTER: CONFIG.KEEPGUISETTINGS: " + CONFIG.KEEPGUISETTINGS, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY AFTER: CONFIG.KEEPREPOS: " + CONFIG.KEEPREPOS, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY AFTER: CONFIG.KEEPSUPER: " + CONFIG.KEEPSUPER, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY AFTER: CONFIG.KEEPWHITELIST: " + CONFIG.KEEPWHITELIST, level=xbmc.LOGINFO)
    # logging.log("EXTRACT.PY AFTER: CONFIG.KEEPADDONS33DB: " + CONFIG.KEEPADDONS33DB, level=xbmc.LOGINFO)
    # logging.log("################################", level=xbmc.LOGINFO)
    
# except Exception: 
    # pass
    
########################################################################################################################################################


def preserve_widget_layout(_out, file, ignore):
    """True if this archive member is a FENtastic home-widget file that must
    be left alone.

    `file` is the member name already split on '/'. Kept as a named function
    so it can be tested directly instead of being restated somewhere else.

    The home widgets are rendered from script-fentastic-widget_*.xml, which
    FENtastic's widget editor rewrites from the user's saved skin settings.
    Overwriting them on every quickfix reverted the home to our default until
    the user next touched a widget, so a quick update leaves them alone.

    TWO conditions, and both matter:

      ignore is not None
        A deliberate (re)install -- Theme Install, Install Skin, a Restore the
        user chose not to wipe first -- passes ignore=None and MUST lay down
        the defaults it was asked to install. Preserving a stale layout there
        would be the opposite of what the user asked for.

      the file is already on disk
        The fresh-build auto-install in startup.py passes ignore=True too, to
        bypass the skip of the wizard's own files -- so on a brand-new install
        the first condition alone skipped all five, and there was nothing to
        preserve: they simply never arrived. The skin then failed every widget
        include ("Skin has invalid include: MovieWidgets") and Movies, TV shows
        and Idan+ came up empty. A quick update could not repair it either,
        for the same reason. Nothing is preserved by refusing to write a file
        that is not there.
    """
    return (ignore is not None
            and file[0] == 'addons' and len(file) >= 4
            and file[1] == 'skin.fentastic' and file[2] == 'xml'
            and file[-1].startswith('script-fentastic-widget_')
            and os.path.isfile(os.path.join(_out, *file)))


def already_on_disk(item, _out):
    """True when the file on disk is byte-for-byte what the archive holds.

    WHY THIS EXISTS. A quickfix is a complete snapshot of the build, so every
    update rewrote all 1,969 members -- 1,330 of them (23.6 MB) inside
    addons/skin.fentastic, the skin that is LOADED AND RENDERING the progress
    dialog while its own files are replaced underneath it. Across five
    consecutive releases the skin changed in NONE of them: a typical release
    moves 2-6 files out of 1,968. We were writing 44 MB to change five files,
    and Kodi was force-closing partway through, over and over, on real
    devices. Not writing a file that is already correct removes that window
    entirely rather than making it smaller.

    HOW IT COMPARES. Size, then the archive's own CRC32 of the UNCOMPRESSED
    data, which zipfile reads from the central directory -- so nothing is
    decompressed to make this decision. Size alone would be worthless here:
    the failure mode that matters is a file whose content changed while its
    length did not, and the CRC is what catches it.

    IT IS DELIBERATELY ONE-SIDED. Every uncertainty -- a missing file, an
    unreadable one, a directory entry, any exception at all -- answers False,
    and the member is written. A file is skipped ONLY when its bytes are
    already exactly right. That is what makes it safe for a device several
    updates behind: it compares against THAT DEVICE'S disk, not against the
    previous release, so anything it is missing differs and is written.
    """
    name = item.filename
    # The SAME sanitisation zipfile.extract performs on the member name --
    # it drops empty, '.' and '..' components before joining. Filtering only
    # the empty ones meant a member containing '..' was CHECKED at one path
    # and WRITTEN at another, so a stray file sitting at the unsanitised path
    # could mark it "already correct" and the real target never got written.
    # No archive we build has such a name (all of dist/ was scanned: zero),
    # but extract.all also serves restore-from-backup and install-from-URL,
    # where the zip is not ours.
    parts = [p for p in name.split('/')
             if p not in ('', os.path.curdir, os.path.pardir)]
    path = os.path.join(_out, *parts) if parts else _out
    try:
        if name.endswith('/'):
            # A directory entry that already IS a directory. Extracting it
            # only re-asserts that, so skipping is exactly equivalent -- and
            # without this the summary below would report 198 phantom
            # "writes" on an update that changed five files. If something
            # else occupies the path, say False and let extract report it.
            return os.path.isdir(path)
        if not os.path.isfile(path):
            return False
        if os.path.getsize(path) != item.file_size:
            return False
        crc = 0
        with open(path, 'rb') as fh:
            while True:
                chunk = fh.read(262144)
                if not chunk:
                    break
                crc = zlib.crc32(chunk, crc)
        return (crc & 0xffffffff) == (item.CRC & 0xffffffff)
    except Exception:
        return False


def all(_in, _out, ignore=None, title=None, progress_dialog_bg=False):
    #####################################################
    # KODI-RD-IL
    # progress_dialog = xbmcgui.DialogProgress()
    progress_dialog = xbmcgui.DialogProgressBG() if progress_dialog_bg else xbmcgui.DialogProgress()
    #####################################################
    progress_dialog.create(CONFIG.ADDONTITLE, "Extracting Content")
    
    # return all_with_progress(_in, _out, progress_dialog, ignore, title)
    return all_with_progress(_in, _out, progress_dialog, ignore, title, progress_dialog_bg)


# def all_with_progress(_in, _out, dp, ignore, title):
def all_with_progress(_in, _out, dp, ignore, title, progress_dialog_bg):
    from resources.libs import whitelist

    count = 0
    errors = 0
    error = ''
    update = 0
    size = 0
    excludes = []
    unchanged = 0
    written = 0
    last_prog = -1

    try:
        zin = zipfile.ZipFile(_in,  'r', allowZip64=True)
    except Exception as e:
        errors += 1
        error += '%s\n' % e
        logging.log('Error Checking Zip: {0}'.format(str(e)), level=xbmc.LOGERROR)
        return update, errors, error

    white_list = whitelist.whitelist('read')
    for item in white_list:
        try:
            name, id, fold = item
        except:
            pass
        excludes.append(fold)

    nFiles = float(len(zin.namelist()))
    zipsize = tools.convert_size(sum([item.file_size for item in zin.infolist()]))

    zipit = str(_in).replace('\\', '/').split('/')
    title = title if title else zipit[-1].replace('.zip', '')

    for item in zin.infolist():

        # Counted BEFORE the ASCII gate, not after. `nFiles` counts every
        # member, so a member rejected here used to advance nFiles without
        # advancing count -- harmless while the dialog was redrawn every
        # iteration, but the redraw is now gated on the percentage moving and
        # on `count == nFiles` for the final frame, and that equality could
        # then never be reached: the bar stopped at 98% and stayed there.
        # dist/Kodi-POV-IL-AF3-skin-pack.zip really does carry six non-ASCII
        # names. Counting them also puts them in the summary's "skipped by
        # rule", which is what they are.
        count += 1

        try:
            str(item.filename).encode('ascii')
        except UnicodeDecodeError:
            logging.log("[ASCII Check] Illegal character found in file: {0}".format(item.filename))
            continue
        except UnicodeEncodeError:
            logging.log("[ASCII Check] Illegal character found in file: {0}".format(item.filename))
            continue

        prog = int(count / nFiles * 100)
        size += item.file_size
        file = str(item.filename).split('/')
        skip = False
        
        line1 = '{0} [COLOR {1}][B][Errors:{2}][/B][/COLOR]'.format(title,
                                                                    CONFIG.COLOR2,
                                                                    errors)
        line2 = '[COLOR {0}][B]File:[/B][/COLOR] [COLOR {1}]{2}/{3}[/COLOR] '.format(CONFIG.COLOR2,
                                                                                     CONFIG.COLOR1,
                                                                                     count,
                                                                                     int(nFiles))
        line2 += '[COLOR {0}][B]Size:[/B][/COLOR] [COLOR {1}]{2}/{3}[/COLOR]'.format(CONFIG.COLOR2,
                                                                                     CONFIG.COLOR1,
                                                                                     tools.convert_size(size),
                                                                                     zipsize)
        line3 = '[COLOR {0}]{1}[/COLOR]'.format(CONFIG.COLOR1, item.filename)
        
        if item.filename == 'userdata/sources.xml' and CONFIG.KEEPSOURCES == 'true':
            skip = True
        elif item.filename == 'userdata/favourites.xml' and CONFIG.KEEPFAVS == 'true':
            skip = True
        elif item.filename == 'userdata/profiles.xml' and CONFIG.KEEPPROFILES == 'true':
            skip = True
        elif item.filename == 'userdata/guisettings.xml' and CONFIG.KEEPGUISETTINGS == 'true':
            skip = True
        elif item.filename == 'userdata/playercorefactory.xml' and CONFIG.KEEPPLAYERCORE == 'true':
            skip = True
        elif item.filename == 'userdata/advancedsettings.xml' and CONFIG.KEEPADVANCED == 'true':
            skip = True
        # KODI RD ISRAEL - Skip Addons33.db if CONFIG.KEEPADDONS33DB is enabled.
        elif item.filename == 'userdata/Database/Addons33.db' and CONFIG.KEEPADDONS33DB == 'true':
            logging.log("KODI RD ISRAEL - EXTRACT.PY: Skipping Addons33.db - CONFIG.KEEPADDONS33DB is: {0}".format(CONFIG.KEEPADDONS33DB))
            skip = True
        elif file[0] == 'addons' and file[1] in excludes:
            skip = True
        elif file[0] == 'userdata' and file[1] == 'addon_data' and file[2] in excludes:
            skip = True
        elif preserve_widget_layout(_out, file, ignore):
            skip = True
        elif file[-1] in CONFIG.LOGFILES:
            skip = True
        elif file[-1] in CONFIG.EXCLUDE_FILES:
            skip = True
        elif file[-1].endswith('.csv'):
            skip = True
        elif not str(item.filename).find('plugin.program.super.favourites') == -1 and CONFIG.KEEPSUPER == 'true':
            skip = True
        elif not str(item.filename).find(CONFIG.ADDON_ID) == -1 and ignore is None:
            skip = True
        if skip:
            logging.log("Skipping: {0}".format(item.filename))
        elif already_on_disk(item, _out):
            # Deliberately NOT logged per file. At ~1,960 identical members an
            # update it would be the log, and the one line that matters -- the
            # summary below -- would be unfindable inside it.
            unchanged += 1
        else:
            try:
                zin.extract(item, _out)
                written += 1
            except Exception as e:
                errormsg = "[COLOR {0}]File:[/COLOR] [COLOR {1}]{2}[/COLOR]\n".format(CONFIG.COLOR2,
                                                                                      CONFIG.COLOR1,
                                                                                      file[-1])
                errormsg += "[COLOR {0}]Folder:[/COLOR] [COLOR {1}]{2}[/COLOR]\n".format(CONFIG.COLOR2,
                                                                                         CONFIG.COLOR1,
                                                                                         item.filename.replace(file[-1], ''))
                errormsg += "[COLOR {0}]Error:[/COLOR] [COLOR {1}]{2}[/COLOR]\n\n".format(CONFIG.COLOR2,
                                                                                          CONFIG.COLOR1,
                                                                                          str(e).replace('\\\\', '\\')
                                                                                          .replace("'{0}'"
                                                                                          .format(item.filename), ''))
                errors += 1
                error += errormsg
                logging.log('Error Extracting: {0}({1})'.format(item.filename, str(e)), level=xbmc.LOGERROR)
                pass
        # Redraw only when the percentage actually moves: at most 101 updates
        # instead of one per member. Every one of those is a full dialog
        # render BY THE SKIN whose files this loop is replacing, and now that
        # most members are skipped the loop runs fast enough to issue them
        # faster than the GUI can service them.
        if prog != last_prog or count == int(nFiles):
            last_prog = prog
            dp.update(prog, line1 + '\n' + line2 + '\n' + line3)
    #####################################################
    # KODI-RD-IL
        # Cancellation is still read every iteration -- it is cheap, and
        # throttling it would make Cancel feel broken.
        if not progress_dialog_bg:
            if dp.iscanceled():
                break

    if not progress_dialog_bg:
        if dp.iscanceled():
            dp.close()
            logging.log_notify(CONFIG.ADDONTITLE,
                               "[COLOR {0}]Extract Cancelled[/COLOR]".format(CONFIG.COLOR2))
            sys.exit()
    #####################################################
        
    # The one line worth finding in the log afterwards. "written" is the whole
    # story of an update: it should be a handful on a current device and large
    # on one that is several releases behind, and if it is ever large on a
    # device that just updated, this comparison has stopped working.
    logging.log('[EXTRACT] {0}: {1} written, {2} already current, {3} skipped '
                'by rule, {4} error(s)'.format(
                    title, written, unchanged,
                    count - written - unchanged - errors, errors))

    # KODI_RD_ISRAEL
    install.restore_fentasticdata()

    return prog, errors, error
