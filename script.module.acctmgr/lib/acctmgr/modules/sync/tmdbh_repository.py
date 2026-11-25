# -*- coding: utf-8 -*-
"""Prepare Jurialmunkey's repository before installing TMDb Helper providers."""
import json
import os
import shutil
import time

import xbmc
import xbmcaddon
import xbmcvfs

REPOSITORY = 'repository.jurialmunkey'


def _installed():
    return bool(xbmc.getCondVisibility('System.HasAddon(%s)' % REPOSITORY))


def _enabled():
    if not _installed():
        return False
    try:
        query = {'jsonrpc': '2.0', 'id': 1, 'method': 'Addons.GetAddonDetails',
                 'params': {'addonid': REPOSITORY, 'properties': ['enabled']}}
        response = json.loads(xbmc.executeJSONRPC(json.dumps(query)))
        return response['result']['addon']['enabled'] is True
    except (KeyError, TypeError, ValueError):
        return False


def _confirm_repository_prompt(clicked):
    if not clicked and xbmc.getCondVisibility('Window.IsTopMost(yesnodialog)'):
        xbmc.executebuiltin('SendClick(yesnodialog, 11)')
        xbmc.log('AM Lite [TMDb Repo]: Confirmed repository installation prompt',
                 xbmc.LOGINFO)
        return True
    return clicked


def ensure_repository(timeout=30):
    #Install and enable the bundled repository when needed.
    if _enabled():
        return True

    copied = False
    if not _installed():
        addon_path = xbmcvfs.translatePath(
            xbmcaddon.Addon('script.module.acctmgr').getAddonInfo('path'))
        source = os.path.join(addon_path, 'resources', 'xmls', REPOSITORY)
        destination = os.path.join(xbmcvfs.translatePath('special://home/addons'),
                                   REPOSITORY)
        if not os.path.isdir(destination):
            if not os.path.isfile(os.path.join(source, 'addon.xml')):
                raise RuntimeError('Bundled %s repository is missing' % REPOSITORY)
            shutil.copytree(source, destination)
            copied = True
            xbmc.log('AM Lite [TMDb Repo]: Copied bundled repository', xbmc.LOGINFO)
        # Register a repository that exists on disk but is not known to Kodi.
        xbmc.executebuiltin('UpdateLocalAddons')

    deadline = time.monotonic() + timeout
    clicked = False
    while not _installed() and time.monotonic() < deadline:
        # Only auto-confirm while registering a previously unrecognized repo.
        clicked = _confirm_repository_prompt(clicked)
        xbmc.sleep(250)
    if not _installed():
        raise RuntimeError('%s not recognized by Kodi' % REPOSITORY)

    if not _enabled():
        xbmc.executebuiltin('EnableAddon(%s)' % REPOSITORY)
        while not _enabled() and time.monotonic() < deadline:
            if copied or clicked:
                clicked = _confirm_repository_prompt(clicked)
            xbmc.sleep(250)
    if not _enabled():
        raise RuntimeError('%s could not be enabled' % REPOSITORY)

    xbmc.executebuiltin('UpdateAddonRepos')
    xbmc.sleep(2000)
    return True
