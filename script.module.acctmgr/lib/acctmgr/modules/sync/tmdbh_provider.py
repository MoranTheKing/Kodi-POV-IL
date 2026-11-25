# -*- coding: utf-8 -*-
import json
import xbmcgui
import os
import re
import time
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon
import xbmcvfs

from acctmgr.modules import var, control

PROVIDER = 'script.module.tmdbhelper.sync.trakt'
PENDING = 'am_tmdbh_trakt_install_pending'
LAST_ATTEMPT = 'am_tmdbh_trakt_install_attempt'
INSTALL_TIMEOUT = 60
SYNC_KEYS = ('sync_provider_watched', 'sync_provider_watchlist',
             'sync_provider_collection', 'sync_provider_scrobbling',
             'sync_provider_stats')
GUARD_OLD = 'return bool(self.token.refresh_token and not self.force_login)'
GUARD_NEW = "return bool(self.token.refresh_token and self.token.refresh_token != '1' and not self.force_login)  # AM Lite sentinel guard"


def log(kind, message, error=False):
    xbmc.log('AM Lite [TMDb Trakt %s]: %s' % (kind, message),
             xbmc.LOGERROR if error else xbmc.LOGINFO)


def selected():
    try:
        with open(var.tk_sync_list, 'r', encoding='utf-8') as stream:
            return 'TMDb Helper' in json.load(stream).get('addon_list', []) and xbmcvfs.exists(var.chk_tmdbh)
    except (OSError, ValueError, TypeError):
        return False


def installed():
    return xbmc.getCondVisibility('System.HasAddon(%s)' % PROVIDER)


def provider_enabled():
    if not installed():
        return False
    try:
        result = xbmc.executeJSONRPC(json.dumps({'jsonrpc': '2.0', 'method': 'Addons.GetAddonDetails',
            'params': {'addonid': PROVIDER, 'properties': ['enabled']}, 'id': 1}))
        return json.loads(result)['result']['addon']['enabled'] is True
    except (KeyError, TypeError, ValueError) as exc:
        log('verify', 'Unable to check enabled state: %s' % exc, True)
        return False


def notify_install(message, error=False):
    try:
        icon = xbmcaddon.Addon('script.module.acctmgr').getAddonInfo('icon')
        xbmcgui.Dialog().notification('AM Lite', message, icon, 6500)
    except Exception as exc:
        log('notification', 'Unable to display notification: %s' % exc, True)


def install_addon():
    if installed():
        return True
    log('install', 'Requesting installation of %s' % PROVIDER)
    from acctmgr.modules.sync import tmdbh_repository
    tmdbh_repository.ensure_repository()
    xbmc.executebuiltin('InstallAddon(%s)' % PROVIDER)
    clicked_yes = False
    start = time.monotonic()
    while time.monotonic() - start < INSTALL_TIMEOUT:
        if installed():
            return True
        if xbmc.getCondVisibility('Window.IsTopMost(yesnodialog)') and not clicked_yes:
            xbmc.executebuiltin('SendClick(yesnodialog, 11)')
            clicked_yes = True
            log('install', 'Automatically confirmed provider installation')
        if xbmc.getCondVisibility('Window.IsTopMost(okdialog)'):
            xbmc.executebuiltin('SendClick(okdialog, 11)')
            log('install', 'Installation failed; dismissed Kodi dialog', True)
            return False
        xbmc.sleep(500)
    log('install', 'Provider installation timed out after %d seconds' % INSTALL_TIMEOUT, True)
    return False


def recovery_file():
    return var.path_tmdbh_trakt_recovery


def apply_guard():
    path = recovery_file()
    if not os.path.isfile(path):
        raise RuntimeError('Provider recovery.py not found')
    with open(path, 'r', encoding='utf-8') as stream:
        source = stream.read()
    if GUARD_NEW in source:
        return
    if source.count(GUARD_OLD) != 1:
        raise RuntimeError('Provider recovery code changed; patch not applied')
    replacement = source.replace(GUARD_OLD, GUARD_NEW, 1)
    with open(path, 'w', encoding='utf-8') as stream:
        stream.write(replacement)
    log('patch', 'Refresh sentinel guard applied')


def remove_guard():
    path = recovery_file()
    if not os.path.isfile(path):
        return
    with open(path, 'r', encoding='utf-8') as stream:
        source = stream.read()
    if GUARD_NEW in source:
        with open(path, 'w', encoding='utf-8') as stream:
            stream.write(source.replace(GUARD_NEW, GUARD_OLD, 1))
        log('patch', 'Refresh guard restored')


def _client_assignment(source):
    matches = list(re.finditer(r"(?m)^(CLIENT_ID[ \t]*=[ \t]*)(['\"])([a-fA-F0-9]{64})\2", source))
    if len(matches) != 1:
        raise RuntimeError('Provider keys.py CLIENT_ID format changed')
    return matches[0]


def _replace_client(path, source, match, value):
    new_source = source[:match.start(3)] + value + source[match.end(3):]
    temporary = path + '.am_tmp'
    with open(temporary, 'w', encoding='utf-8') as stream:
        stream.write(new_source)
    os.replace(temporary, path)


def apply_api_key():
    #Patch provider Client ID only after it is installed
    path = var.path_tmdbh_trakt_keys
    if not os.path.isfile(path):
        raise RuntimeError('Provider keys.py not found')
    with open(path, 'r', encoding='utf-8') as stream:
        source = stream.read()
    match = _client_assignment(source)
    current = match.group(3)
    if current == var.client_am:
        return False
    if current != var.tmdbh_client:
        raise RuntimeError('Unexpected provider Client ID; refusing to overwrite')
    _replace_client(path, source, match, var.client_am)
    log('patch', 'AM Lite Trakt Client ID applied')
    return True


def restore_api_key():
    #Restore provider default key from var.py
    path = var.path_tmdbh_trakt_keys
    if not os.path.isfile(path):
        return False
    with open(path, 'r', encoding='utf-8') as stream:
        source = stream.read()
    match = _client_assignment(source)
    current = match.group(3)
    if current == var.tmdbh_client:
        return False
    if current != var.client_am:
        raise RuntimeError('Unexpected provider Client ID; refusing to restore')
    _replace_client(path, source, match, var.tmdbh_client)
    log('patch', 'Provider default Trakt Client ID restored')
    return True


def token_data():
    token = control.setting('trakt.token')
    expires = int(float(control.setting('trakt.expires') or 0))
    duration = int(float(control.setting('trakt.expires_in') or 0))
    if not token or expires <= 0 or duration <= 0:
        raise RuntimeError('Missing AM Lite master token or expiration metadata')
    return json.dumps({'access_token': token, 'token_type': 'bearer',
        'expires_in': duration, 'refresh_token': '1',
        'scope': 'public offline_access', 'created_at': expires - duration}, separators=(',', ':'))


def prepare_settings():
    path = xbmcvfs.translatePath('special://profile/addon_data/%s/settings.xml' % PROVIDER)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.isfile(path):
        tree = ET.parse(path)
        root = tree.getroot()
    else:
        root = ET.Element('settings', {'version': '2'})
        tree = ET.ElementTree(root)
    if root.get('version') == '2':
        # Kodi's persisted settings.xml uses a flat list, unlike resources/settings.xml.
        setting = root.find("setting[@id='token']")
        if setting is None:
            setting = ET.SubElement(root, 'setting', {'id': 'token'})
        setting.text = token_data()
    else:
        setting = root.find("setting[@id='token']")
        if setting is None:
            setting = ET.SubElement(root, 'setting', {'id': 'token'})
        setting.text = token_data()
    tmp = path + '.am_tmp'
    tree.write(tmp, encoding='utf-8', xml_declaration=True)
    os.replace(tmp, path)
    log('sync', 'Provider token settings prepared')


def sync():
    if not selected():
        control.setSetting(PENDING, 'false')
        return
    token = token_data()
    from acctmgr.modules.sync import tmdbh_choice
    if installed():
        if not provider_enabled():
            control.setSetting(PENDING, 'true')
            log('install', 'Provider disabled; queued startup enable')
        else:
            # The provider is already available: synchronize immediately and
            # apply AM Lite's API key and refresh protection during authorization.
            provider = xbmcaddon.Addon(PROVIDER)
            provider.setSettingString('token', token)
            if provider.getSettingString('token') != token:
                raise RuntimeError('Provider token verification failed')
            # Keep the startup task pending until both patches succeed.
            control.setSetting(PENDING, 'true')
            apply_guard()
            apply_api_key()
            tmdbh_choice.configure('trakt')
            control.setSetting(PENDING, 'false')
            log('sync', 'Provider token verified; API key and refresh guard applied')
            return
    prepare_settings()
    control.setSetting(PENDING, 'true')
    log('install', 'Provider installation deferred to next Kodi startup')


def startup_install():
    if not selected():
        control.setSetting(PENDING, 'false')
        return
    if not control.setting('trakt.token'):
        return
    if control.setting(PENDING) != 'true' and not installed():
        return
    try:
        if not installed():
            control.setSetting(LAST_ATTEMPT, str(int(time.time())))
            notify_install('Installing TMDb Helper Trakt provider...')
            if not install_addon():
                raise RuntimeError('Provider installation failed or timed out')
        if installed() and not provider_enabled():
            xbmc.executebuiltin('EnableAddon(%s)' % PROVIDER, wait=True)
        if not provider_enabled():
            raise RuntimeError('Provider not installed/enabled; retry at next startup')
        from acctmgr.modules.sync import tmdbh_choice
        apply_guard()
        if not control.setting('trakt.token'):
            raise RuntimeError('AM Lite Trakt authorization missing')
        apply_api_key()
        # Refresh settings after install; Kodi may initialize defaults during installation.
        if control.setting('trakt.token'):
            provider = xbmcaddon.Addon(PROVIDER)
            expected = token_data()
            provider.setSettingString('token', expected)
            if provider.getSettingString('token') != expected:
                raise RuntimeError('Provider token verification failed')
        tmdbh_choice.configure('trakt')
        control.setSetting(PENDING, 'false')
        control.setSetting(LAST_ATTEMPT, '0')
        log('install', 'Provider installed, patched and verified')
    except Exception as exc:
        control.setSetting(PENDING, 'true')
        log('install', str(exc), True)
        notify_install('TMDb Helper Trakt setup failed. Retrying next startup.', True)



def complete_authorization_install():
    #Install the selected Trakt provider
    if not selected() or not control.setting('trakt.token'):
        return
    try:
        startup_install()
    except Exception as exc:
        control.setSetting(PENDING, 'true')
        log('install', 'Post-authorization setup failed: %s' % exc, True)
        notify_install('TMDb Helper Trakt setup failed. Retrying next startup.', True)

def revoke():
    control.setSetting(PENDING, 'false')
    control.setSetting(LAST_ATTEMPT, '0')
    try:
        if installed():
            # Do not revoke the OAuth token here: the master token may already be revoked.
            xbmcaddon.Addon(PROVIDER).setSettingString('token', '')
            remove_guard()
            restore_api_key()
        else:
            path = xbmcvfs.translatePath('special://profile/addon_data/%s/settings.xml' % PROVIDER)
            if os.path.isfile(path):
                tree = ET.parse(path)
                for setting in tree.getroot().iter('setting'):
                    if setting.get('id') == 'token':
                        setting.text = ''
                        value = setting.find('value')
                        if value is not None:
                            value.text = ''
                tree.write(path, encoding='utf-8', xml_declaration=True)
    except Exception as exc:
        log('revoke', str(exc), True)
