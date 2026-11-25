# -*- coding: utf-8 -*-
"""Shared TMDb Helper sync-provider preference for AM Lite."""
import xbmc
import xbmcaddon
import xbmcgui
from acctmgr.modules import control, var

PREFERENCE = 'am_tmdbh_sync_provider'
HELPER = 'plugin.video.themoviedb.helper'
SYNC_KEYS = ('sync_provider_watched', 'sync_provider_watchlist',
             'sync_provider_collection', 'sync_provider_scrobbling')


def available():
    return bool(xbmc.getCondVisibility('System.HasAddon(%s)' % HELPER))


def trakt_selected():
    # The Trakt provider is only managed if TMDb Helper is in the sync list.
    from acctmgr.modules.sync import tmdbh_provider
    return bool(control.setting('trakt.token') and tmdbh_provider.selected())


def mdblist_authorized():
    return bool(control.setting('mdblist.apikey'))


def both_authorized():
    return available() and trakt_selected() and mdblist_authorized()


def current():
    """Prefer a saved choice; otherwise preserve the user's current TMDb setting."""
    stored = control.setting(PREFERENCE)
    if stored in ('trakt', 'mdblist'):
        return stored
    if available():
        try:
            active = xbmcaddon.Addon(HELPER).getSettingString('sync_provider_watched')
            if active in ('trakt', 'mdblist'):
                return active
        except Exception:
            pass
    return ''


def provider_ready(service):
    """Do not activate a provider until its credentials are installed and verified."""
    if service == 'trakt':
        from acctmgr.modules.sync import tmdbh_provider
        return (tmdbh_provider.provider_enabled() and
                control.setting(tmdbh_provider.PENDING) != 'true')
    from acctmgr.modules.sync import tmdbh_mdblist
    return (tmdbh_mdblist.enabled() and
            control.setting(tmdbh_mdblist.PENDING) != 'true')


def prompt_if_both():
    """Called only after a successful new Trakt/MDBList authorization.

    Cancellation preserves the current provider; it never reverses authorization.
    """
    if not both_authorized():
        return
    if not (provider_ready('trakt') and provider_ready('mdblist')):
        xbmc.log('AM Lite [TMDb]: Sync-provider choice deferred until both providers are ready', xbmc.LOGINFO)
        return
    current_choice = current()
    selection = xbmcgui.Dialog().select(
        'TMDb Helper - Default Sync Provider',
        ['Trakt', 'MDBList'],
        preselect=0 if current_choice == 'trakt' else 1 if current_choice == 'mdblist' else -1)
    if selection == -1:
        return
    choice = ('trakt', 'mdblist')[selection]
    control.setSetting(PREFERENCE, choice)
    configure(choice)


def preferred(service):
    """A single authorized provider owns the settings; with both, use preference."""
    if not available():
        return False
    if both_authorized():
        return current() == service
    if service == 'trakt':
        return trakt_selected()
    return mdblist_authorized()


def configure(service):
    if not preferred(service):
        return False
    addon = xbmcaddon.Addon(HELPER)
    for key in SYNC_KEYS:
        addon.setSettingString(key, service)
        if addon.getSettingString(key) != service:
            raise RuntimeError('TMDb Helper setting verification failed: ' + key)
    # Trakt supports stats, MDBList does not. Do not overwrite stats for MDBList.
    if service == 'trakt':
        addon.setSettingString('sync_provider_stats', 'trakt')
        if addon.getSettingString('sync_provider_stats') != 'trakt':
            raise RuntimeError('TMDb Helper setting verification failed: sync_provider_stats')
    return True
