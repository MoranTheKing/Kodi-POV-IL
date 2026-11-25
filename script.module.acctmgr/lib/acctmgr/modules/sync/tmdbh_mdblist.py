# -*- coding: utf-8 -*-
import json
import os
import shutil
import xbmcvfs
import time
import xbmc
import xbmcaddon
import xbmcgui
from acctmgr.modules import control, var

PROVIDER = 'script.module.tmdbhelper.sync.mdblist'
PENDING = 'am_tmdbh_mdblist_install_pending'
SYNC_KEYS = ('sync_provider_watched', 'sync_provider_watchlist',
             'sync_provider_collection', 'sync_provider_scrobbling')


def log(message, error=False):
    xbmc.log('AM Lite [TMDb MDBList]: ' + message,
             xbmc.LOGERROR if error else xbmc.LOGINFO)


def installed():
    return bool(xbmc.getCondVisibility('System.HasAddon(%s)' % PROVIDER))


def enabled():
    if not installed():
        return False
    try:
        request = {'jsonrpc': '2.0', 'id': 1, 'method': 'Addons.GetAddonDetails',
                   'params': {'addonid': PROVIDER, 'properties': ['enabled']}}
        response = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
        return response['result']['addon']['enabled'] is True
    except (KeyError, TypeError, ValueError):
        return False


def notify(message, error=False):
    icon = xbmcaddon.Addon('script.module.acctmgr').getAddonInfo('icon')
    xbmcgui.Dialog().notification('AM Lite', message, icon, 3000)


def install_addon(timeout=60):
    if installed():
        return True
    from acctmgr.modules.sync import tmdbh_repository
    tmdbh_repository.ensure_repository()
    xbmc.executebuiltin('InstallAddon(%s)' % PROVIDER)
    clicked = False
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if installed():
            return True
        if xbmc.getCondVisibility('Window.IsTopMost(yesnodialog)') and not clicked:
            xbmc.executebuiltin('SendClick(yesnodialog, 11)')
            clicked = True
        if xbmc.getCondVisibility('Window.IsTopMost(okdialog)'):
            xbmc.executebuiltin('SendClick(okdialog, 11)')
            return False
        xbmc.sleep(500)
    return False


def ensure_settings():
    source = os.path.join(xbmcaddon.Addon('script.module.acctmgr').getAddonInfo('path'), 'resources', 'xmls', PROVIDER, 'settings.xml')
    destination = xbmcvfs.translatePath(
        'special://profile/addon_data/%s/settings.xml' % PROVIDER)
    if os.path.isfile(destination):
        return True
    try:
        if not os.path.isfile(source):
            raise FileNotFoundError(source)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copyfile(source, destination)
        log('Created missing provider settings.xml from bundled template')
        return True
    except Exception as exc:
        log('Could not prepare MDBList provider settings: %s' % exc, True)
        return False


def set_key(key):
    if not enabled():
        raise RuntimeError('MDBList provider not installed/enabled')
    addon = xbmcaddon.Addon(PROVIDER)
    addon.setSettingString('apikey', key)
    if addon.getSettingString('apikey') != key:
        raise RuntimeError('MDBList provider API key verification failed')


def configure_helper():
    from acctmgr.modules.sync import tmdbh_choice
    tmdbh_choice.configure('mdblist')


def sync(key=None):
    if not xbmc.getCondVisibility('System.HasAddon(plugin.video.themoviedb.helper)'):
        return
    key = key if key is not None else control.setting('mdblist.apikey')
    if not key:
        return
    if not ensure_settings():
        control.setSetting(PENDING, 'true')
        return
    if enabled():
        try:
            set_key(key)
            configure_helper()
            control.setSetting(PENDING, 'false')
            log('Provider API key synchronized immediately')
            return
        except Exception as exc:
            log('Immediate sync failed: %s' % exc, True)
    control.setSetting(PENDING, 'true')
    log('MDBList provider setup queued for next Kodi startup')



def complete_authorization_install():
    if not xbmc.getCondVisibility('System.HasAddon(plugin.video.themoviedb.helper)'):
        return
    key = control.setting('mdblist.apikey')
    if not key:
        return
    if enabled():
        # Already synchronized by sync() during the authorization process.
        return
    control.setSetting(PENDING, 'true')
    startup_install()


def startup_install():
    #Attempt once per startup; failed attempts remain pending for next startup.
    if not xbmc.getCondVisibility('System.HasAddon(plugin.video.themoviedb.helper)'):
        return
    key = control.setting('mdblist.apikey')
    if not key:
        return
    if not installed() and control.setting(PENDING) != 'true':
        return
    try:
        if not ensure_settings():
            raise RuntimeError('Provider settings template unavailable')
        if not installed():
            notify('Installing TMDb Helper MDBList provider...')
            if not install_addon():
                raise RuntimeError('Provider installation failed or timed out')
        if installed() and not enabled():
            log('MDBList provider disabled; attempting to enable it')
            xbmc.executebuiltin('EnableAddon(%s)' % PROVIDER, wait=True)
        if not enabled():
            raise RuntimeError('MDBList provider not installed/enabled; retry at next startup')
        set_key(key)
        configure_helper()
        control.setSetting(PENDING, 'false')
        log('Provider installed and API key verified')
    except Exception as exc:
        control.setSetting(PENDING, 'true')
        log('Setup failed: %s' % exc, True)
        notify('TMDb Helper MDBList setup failed. Retrying next startup.', True)


def revoke():
    control.setSetting(PENDING, 'false')
    if installed():
        xbmcaddon.Addon(PROVIDER).setSettingString('apikey', '')
