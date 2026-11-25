# -*- coding: utf-8 -*-
import xbmc, xbmcaddon, xbmcvfs
import json
import os
import sqlite3

from sqlite3 import Error
from xml.etree import ElementTree
from resources.libs.common.config import CONFIG
from resources.libs.common import logging

# Variables
amgr = 'AM Lite ERROR'
translatePath = xbmcvfs.translatePath

# Auth cache
AUTH_CACHE = {}

# Realizer json Path
chkset_realx_json = translatePath('special://profile/addon_data/plugin.video.realizerx/rdauth.json')


ORDER = ['fenlt',
         'gears',
         'redlt',
         'umb',
         'pov',
         #'dradis',
         'genocide',
         'seren',
         'luc',
         'prism',
         'a4k',
         'madtitan',
         'shadow',
         'ghost',
         'chains',
         'homelander',
         'nightwing',
         'absolution',
         'thecrew',
         'salts',
         'scrubs',
         'gratisred',
         'otaku',
         'easyv',
         'rurl',
         'tmdbhelper',
         'trakt',
         'premx',   # Premiumize Only
         'realx',   # Real-Debrid Only
         'fentastic',
         'nimbus',
         'acctmgr']

ADDONS = {
    #FEN LIGHT
    'fenlt': {
        'name'        : 'Fen Light',
        'plugin'      : 'plugin.video.fenlight',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.fenlight'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.fenlight/resources/media/addon_icons/', 'fenlight_icon_01.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.fenlight/resources/media/', 'fenlight_fanart2.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.fenlight/databases', 'settings.db'),
        #TK
        'default_tk'  : 'trakt.token',
        'data_tk'     : [],
        #RD
        'default_rd'  : 'rd.token',
        'data_rd'     : [],
        #PM
        'default_pm'  : 'pm.token',
        'data_pm'     : [],
        #AD
        'default_ad'  : 'ad.token',
        'data_ad'     : [],
        #ED
        'default_ed'  : 'ed.token',
        'data_ed'     : [],
        #TB
        'default_tb'  : 'tb.token',
        'data_tb'     : [],
        #EN
        'default_en'  : 'easynews_password',
        'data_en'     : [],
    },

    #GEARS
    'gears': {
        'name'        : 'The Gears',
        'plugin'      : 'plugin.video.gears',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.gears'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.gears/resources/media/addon_icons/', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.gears/', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.gears/databases', 'settings.db'),
        #TK
        'default_tk'  : 'trakt.token',
        'data_tk'     : [],
        #MDB
        'default_mdb' : 'mdblist.api_key',
        'data_mdb'    : [],
        #RD
        'default_rd'  : 'rd.token',
        'data_rd'     : [],
        #PM
        'default_pm'  : 'pm.token',
        'data_pm'     : [],
        #AD
        'default_ad'  : 'ad.token',
        'data_ad'     : [],
        #ED
        'default_ed'  : 'ed.token',
        'data_ed'     : [],
        #TB
        'default_tb'  : 'tb.token',
        'data_tb'     : [],
        #OC
        #'default_oc'  : 'oc.token',
        #'data_oc'     : [],
        #EN
        'default_en'  : 'easynews_password',
        'data_en'     : [],
    },

    #RED LIGHT
    'redlt': {
        'name'        : 'Red Light',
        'plugin'      : 'plugin.video.redlight',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.redlight'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.redlight/resources/media/addon_icons/', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.redlight/resources/media/', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.redlight/databases', 'settings.db'),
        #TK
        'default_tk'  : 'trakt.token',
        'data_tk'     : [],
        #MDB
        'default_mdb' : 'mdblist.token',
        'data_mdb'    : [],
        #RD
        'default_rd'  : 'rd.token',
        'data_rd'     : [],
        #PM
        'default_pm'  : 'pm.token',
        'data_pm'     : [],
        #AD
        'default_ad'  : 'ad.token',
        'data_ad'     : [],
        #ED
        'default_ed'  : 'ed.token',
        'data_ed'     : [],
        #TB
        'default_tb'  : 'tb.token',
        'data_tb'     : [],
        #OC
        'default_oc'  : 'oc.token',
        'data_oc'     : [],
        #EN
        'default_en'  : 'easynews_password',
        'data_en'     : [],
    },
    
    #UMBRELLA
    'umb': {
        'name'        : 'Umbrella',
        'plugin'      : 'plugin.video.umbrella',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.umbrella'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.umbrella', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.umbrella', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.umbrella', 'settings.xml'),
        #TK
        'default_tk'  : 'trakt.user.token',
        'data_tk'     : ['trakt.user.token', 'trakt.user.name', 'trakt.token.expires', 'trakt.authed.clientid', 'trakt.refreshtoken', 'trakt.isauthed', 'indicators', 'trakt.scrobble', 'resume.source'],
        #MDB
        'default_mdb'  : 'mdblist.token',
        'data_mdb'     : ['mdblist.token', 'mdblist.refresh.token'],
        #RD
        'default_rd'  : 'realdebridtoken',
        'data_rd'     : ['realdebridusername', 'realdebridtoken', 'realdebrid.clientid', 'realdebridsecret', 'realdebridrefresh', 'realdebrid.enable'],
        #PM
        'default_pm'  : 'premiumizetoken',
        'data_pm'     : ['premiumizeusername', 'premiumizetoken', 'premiumize.enable'],
        #AD
        'default_ad'  : 'alldebridtoken',
        'data_ad'     : ['alldebridusername', 'alldebridtoken', 'alldebrid.enable'],
        #ED
        'default_ed'  : 'easydebridtoken',
        'data_ed'     : ['easydebridtoken', 'easydebrid.enable'],
        #TB
        'default_tb'  : 'torboxtoken',
        'data_tb'     : ['torboxtoken', 'torbox.username', 'torbox.enable'],
        #OC
        'default_oc'  : 'offcloudtoken',
        'data_oc'     : ['offcloudtoken', 'offcloud.enable', 'offcloud.username'],
        #EN
        'default_en'  : 'easynews.password',
        'data_en'     : ['easynews.password', 'easynews.user', 'easynews.enable'],
    },

    #POV
    'pov': {
        'name'        : 'POV',
        'plugin'      : 'plugin.video.pov',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.pov'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.pov', 'pov.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.pov', 'pov_fanart.png'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.pov', 'settings.xml'),
        #TK
        'default_tk'  : 'trakt.token',
        'data_tk'     : ['trakt.refresh', 'trakt.expires', 'trakt.token', 'trakt_user', 'trakt_indicators_active', 'watched_indicators'], # Trakt Client/Secret NOT required here for revoke due to default API keys being stored in the settings.xml
        #MDB
        'default_mdb'  : 'mdblist.token',
        'data_mdb'     : ['mdblist.token', 'mdblist_user', 'mdblist.refresh', 'mdblist.expires', 'mdbl_indicators_active', 'watched_indicators'],
        #RD
        'default_rd'  : 'rd.token',
        'data_rd'     : ['rd.username', 'rd.token', 'rd.client_id', 'rd.refresh', 'rd.secret', 'rd.enabled'],
        #PM
        'default_pm'  : 'pm.token',
        'data_pm'     : ['pm.account_id', 'pm.token', 'pm.enabled'],
        #AD
        'default_ad'  : 'ad.token',
        'data_ad'     : ['ad.account_id', 'ad.enabled', 'ad.token'],
        #ED
        'default_ed'  : 'eb.token',
        'data_ed'     : ['ed.token', 'ed.account_id', 'ed.enabled'],
        #TB
        'default_tb'  : 'tb.token',
        'data_tb'     : ['tb.token', 'tb.account_id', 'tb.expires', 'tb.enabled'],
        #OC
        'default_oc'  : 'oc.token',
        'data_oc'     : ['oc.token', 'oc.account_id', 'oc.enabled'],
        #EN
        'default_en'  : 'easynews_password',
        'data_en'     : ['easynews_password', 'easynews_user', 'provider.easynews'],
    },

    #LUC_KODI
    'luc': {
        'name'        : 'luc_kodi',
        'plugin'      : 'plugin.video.luc_kodi',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.luc_kodi'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.luc_kodi', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.luc_kodi', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.luc_kodi', 'settings.xml'),
        #TK
        'default_tk'  : 'trakt.token',
        'data_tk'     : ['trakt.username', 'trakt.token', 'trakt.refresh', 'trakt.expires', 'trakt.client_id', 'trakt.client_secret'],
        #MDB
        'default_mdb' : 'mdblist.token',
        'data_mdb'    : ['mdblist.token', 'mdblist.username', 'mdblist.refresh'],
        #RD
        'default_rd'  : 'realdebrid.token',
        'data_rd'     : ['realdebrid.enable', 'realdebrid.token', 'realdebrid.username', 'realdebrid.client_id', 'realdebrid.refresh', 'realdebrid.secret'],
        #PM
        'default_pm'  : 'premiumize.token',
        'data_pm'     : ['premiumize.enable', 'premiumize.token', 'premiumize.username'],
        #AD
        'default_ad'  : 'alldebrid.token',
        'data_ad'     : ['alldebrid.enable', 'alldebrid.token', 'alldebrid.username'],
        #TB
        'default_tb'  : 'torbox.token',
        'data_tb'     : ['torbox.enable', 'torbox.token', 'torbox.username'],
        #EN
        'default_en'  : 'easynews.password',
        'data_en'     : ['easynews.username', 'easynews.password', 'provider.easynews'],
    },

    #SEREN
    'seren': {
        'name'        : 'Seren',
        'plugin'      : 'plugin.video.seren',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.seren'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.seren/resources/images', 'ico-seren-3.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.seren/resources/images', 'fanart-seren-3.png'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.seren', 'settings.xml'),
        #TK
        'default_tk'  : 'trakt.auth',
        'data_tk'     : ['trakt.auth', 'trakt.refresh', 'trakt.username', 'trakt.expires', 'trakt.enabled'],
        #RD
        'default_rd'  : 'rd.auth',
        'data_rd'     : ['rd.auth', 'rd.client_id', 'rd.refresh', 'rd.secret', 'rd.username', 'realdebrid.enabled', 'realdebrid.premiumstatus'],
        #PM
        'default_pm'  : 'premiumize.token',
        'data_pm'     : ['premiumize.enabled', 'premiumize.username', 'premiumize.token', 'premiumize.premiumstatus'],
        #AD
        'default_ad'  : 'alldebrid.apikey',
        'data_ad'     : ['alldebrid.enabled', 'alldebrid.username', 'alldebrid.apikey', 'alldebrid.premiumstatus'],
    },

    #MAD TITAN SPORTS
    'madtitan': {
        'name'        : 'Mad Titan Sports',
        'plugin'      : 'plugin.video.madtitansports',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.madtitansports'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.madtitansports', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.madtitansports', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.madtitansports', 'settings.xml'),
        #TK
        'default_tk'  : 'trakt.access_token',
        'data_tk'     : ['trakt.access_token', 'trakt.refresh_token', 'trakt.user_id', 'trakt.authorize'],
    },

    #A4KSTREAMING
    'a4k': {
        'name'        : 'a4kStreaming',
        'plugin'      : 'plugin.video.a4kstreaming',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.a4kstreaming'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.a4kstreaming', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.a4kstreaming', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.a4kstreaming', 'settings.xml'),
        #TK - Migration Only
        'default_tk'  : 'trakt.clientid',
        'data_tk'     : ['trakt.clientid', 'trakt.username'],
        #PM
        'default_pm'  : 'premiumize.apikey',
        'data_pm'     : ['premiumize.apikey'],
        #AD
        'default_ad'  : 'alldebrid.apikey',
        'data_ad'     : ['alldebrid.apikey'],
    },

    #PRISM
    'prism': {
        'name'        : 'Prism',
        'plugin'      : 'plugin.video.prism',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.prism'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.prism/resources/images', 'ico-prism-4.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.prism/resources/images', 'fanart-prism-4.png'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.prism', 'settings.xml'),
        #RD
        'default_rd'  : 'rd.auth',
        'data_rd'     : ['rd.auth', 'rd.client_id', 'rd.refresh', 'rd.secret', 'rd.username', 'realdebrid.enabled', 'realdebrid.premiumstatus'],
        #PM
        'default_pm'  : 'premiumize.token',
        'data_pm'     : ['premiumize.enabled', 'premiumize.username', 'premiumize.token', 'premiumize.premiumstatus'],
        #AD
        'default_ad'  : 'alldebrid.apikey',
        'data_ad'     : ['torbox.enabled', 'alldebrid.username', 'alldebrid.apikey', 'alldebrid.premiumstatus'],
        #TB
        'default_tb'  : 'tb.token',
        'data_tb'     : ['tb.token', 'tb.username', 'torbox.enabled', 'tb.premiumstatus'],
        #OC
        'default_oc'  : 'oc.token',
        'data_oc'     : ['oc.token', 'oc.username', 'offcloud.enabled', 'oc.premiumstatus'],
    },

    #GENOCIDE
    'genocide': {
        'name'        : 'Genocide',
        'plugin'      : 'plugin.video.genocide',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.genocide'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.genocide', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.genocide', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.genocide', 'settings.xml'),
        #TK
        'default_tk'  : 'trakt.token',
        'data_tk'     : ['trakt.token', 'trakt.username', 'trakt.expires', 'trakt.refresh', 'trakt.isauthed', 'trakt_user'], # Trakt Client/Secret NOT required here for revoke due to default API keys being stored in the settings.xml
        #RD
        'default_rd'  : 'realdebrid.token',
        'data_rd'     : ['realdebrid.username', 'realdebrid.token', 'realdebrid.client_id', 'realdebrid.secret', 'realdebrid.refresh', 'realdebrid.enable'],
        #PM
        'default_pm'  : 'premiumize.token',
        'data_pm'     : ['premiumize.username', 'premiumize.token', 'premiumize.enable'],
        #AD
        'default_ad'  : 'alldebrid.token',
        'data_ad'     : ['alldebrid.username', 'alldebrid.token', 'alldebrid.enable'],
        #TB
        'default_tb'  : 'torbox.token',
        'data_tb'     : ['torbox.token', 'torbox.username', 'torbox.enable', 'torbox.expires'],
        #OC
        'default_oc'  : 'offcloud.token',
        'data_oc'     : ['offcloud.token', 'offcloud.username', 'offcloud.enable'],
        #EN
        'default_en'  : 'easynews_password',
        'data_en'     : ['easynews_password', 'easynews_user', 'provider.easynews'],
    },

    #SHADOW
    'shadow': {
        'name'        : 'Shadow',
        'plugin'      : 'plugin.video.shadow',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.shadow'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.shadow', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.shadow', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.shadow', 'settings.xml'),
        #TK
        'default_tk'  : 'trakt_access_token',
        'data_tk'     : ['trakt_expires_at', 'trakt_refresh_token', 'trakt_access_token'],
        #RD
        'default_rd'  : 'rd.auth',
        'data_rd'     : ['rd.auth', 'rd.client_id', 'rd.refresh', 'rd.secret', 'debrid_use', 'debrid_use_rd'],
        #PM
        'default_pm'  : 'premiumize.token',
        'data_pm'     : ['premiumize.token', 'debrid_use', 'debrid_use_pm'],
        #AD
        'default_ad'  : 'alldebrid.token',
        'data_ad'     : ['alldebrid.username', 'alldebrid.token', 'debrid_use_ad', 'debrid_use'],
        #TB
        'default_tb'  : 'tb.token',
        'data_tb'     : ['tb.token', 'tb.account_id', 'debrid_use_tr', 'debrid_use'],
    },

    #GHOST
    'ghost': {
        'name'        : 'Ghost',
        'plugin'      : 'plugin.video.ghost',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.ghost'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.ghost', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.ghost', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.ghost', 'settings.xml'),
        #TK
        'default_tk'  : 'trakt_access_token',
        'data_tk'     : ['trakt_expires_at', 'trakt_refresh_token', 'trakt_access_token'],
        #RD
        'default_rd'  : 'rd.auth',
        'data_rd'     : ['rd.auth', 'rd.client_id', 'rd.refresh', 'rd.secret', 'debrid_use', 'debrid_use_rd'],
        #PM
        'default_pm'  : 'premiumize.token',
        'data_pm'     : ['premiumize.token', 'debrid_use', 'debrid_use_pm'],
        #AD
        'default_ad'  : 'alldebrid.token',
        'data_ad'     : ['alldebrid.username', 'alldebrid.token', 'debrid_use_ad', 'debrid_use'],
        #TB
        'default_tb'  : 'tb.token',
        'data_tb'     : ['tb.token', 'tb.account_id', 'debrid_use_tr', 'debrid_use'],
    },

    #THE CHAINS
    'chains': {
        'name'        : 'The Chains',
        'plugin'      : 'plugin.video.thechains',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.thechains'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.thechains', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.thechains', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.thechains', 'settings.xml'),
        #TK
        'default_tk'  : 'trakt_access_token',
        'data_tk'     : ['trakt_expires_at', 'trakt_refresh_token', 'trakt_access_token'],
        #RD
        'default_rd'  : 'rd.auth',
        'data_rd'     : ['rd.auth', 'rd.client_id', 'rd.refresh', 'rd.secret', 'debrid_use', 'debrid_use_rd'],
        #PM
        'default_pm'  : 'premiumize.token',
        'data_pm'     : ['premiumize.token', 'debrid_use', 'debrid_use_pm'],
        #AD
        'default_ad'  : 'alldebrid.token',
        'data_ad'     : ['alldebrid.username', 'alldebrid.token', 'debrid_use_ad', 'debrid_use'],
        #TB
        'default_tb'  : 'tb.token',
        'data_tb'     : ['tb.token', 'tb.account_id', 'debrid_use_tr', 'debrid_use'],
    },
    
    #HOMELANDER
    'homelander': {
        'name'        : 'Homelander',
        'plugin'      : 'plugin.video.homelander',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.homelander'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.homelander', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.homelander', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.homelander', 'settings.xml'),
        #TK
        'default_tk'  : 'trakt.token',
        'data_tk'     : ['trakt.authed', 'trakt.user', 'trakt.token', 'trakt.refresh', 'trakt.client_id', 'trakt.client_secret'],
    },

    #NIGHTWING
    'nightwing': {
        'name'        : 'Nightwing',
        'plugin'      : 'plugin.video.nightwing',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.nightwing'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.nightwing', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.nightwing', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.nightwing', 'settings.xml'),
        #TK
        'default_tk'  : 'trakt.token',
        'data_tk'     : ['trakt.authed', 'trakt.user', 'trakt.token', 'trakt.refresh', 'trakt.client_id', 'trakt.client_secret'],
    },

    #ABSOLUTION
    'absolution': {
        'name'        : 'Absolution',
        'plugin'      : 'plugin.video.absolution',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.absolution'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.absolution', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.absolution', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.absolution', 'settings.xml'),
        #TK
        'default_tk'  : 'trakt.token',
        'data_tk'     : ['trakt.authed', 'trakt.user', 'trakt.token', 'trakt.refresh', 'trakt.client_id', 'trakt.client_secret'],
    },

    #THE CREW
    'thecrew': {
        'name'        : 'The Crew',
        'plugin'      : 'plugin.video.thecrew',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.thecrew'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.thecrew', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.thecrew', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.thecrew', 'settings.xml'),
        #TK
        'default_tk'  : 'trakt.token',
        'data_tk'     : ['trakt.refresh', 'trakt.token', 'trakt.user', 'trakt.expires_at', 'silent.boot'],
        #EN
        'default_en'  : 'easynews.password',
        'data_en'     : ['easynews.password', 'easynews.user'],
    },

    #SALTS
    'salts': {
        'name'        : 'SALTS',
        'plugin'      : 'plugin.video.salts',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.salts'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.salts', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.salts', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.salts', 'settings.xml'),
        #TK
        'default_tk'  : 'trakt_access_token',
        'data_tk'     : ['trakt_expires', 'trakt_refresh_token', 'trakt_access_token', 'trakt_enabled'],
        #RD
        'default_rd'  : 'realdebrid_token',
        'data_rd'     : ['realdebrid_token', 'realdebrid_refresh', 'realdebrid_expires', 'realdebrid_enabled'],
        #PM
        'default_pm'  : 'premiumize_token',
        'data_pm'     : ['premiumize_token', 'premiumize_enabled'],
        #AD
        'default_ad'  : 'alldebrid_token',
        'data_ad'     : ['alldebrid_token', 'alldebrid_enabled'],
    },

    #SCRUBS V2
    'scrubs': {
        'name'        : 'Scrubs V2',
        'plugin'      : 'plugin.video.scrubsv2',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.scrubsv2'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.scrubsv2/resources/images', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.scrubsv2/resources/images', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.scrubsv2', 'settings.xml'),
        #TK
        'default_tk'  : 'trakt.token',
        'data_tk'     : ['trakt.refresh', 'trakt.token', 'trakt.user', 'trakt.authed'],
    },

    #GRATIS RED
    'gratisred': {
        'name'        : 'Gratis Red',
        'plugin'      : 'plugin.video.gratisred',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.gratisred'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.gratisred/resources/images', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.gratisred/resources/images', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.gratisred', 'settings.xml'),
        #TK
        'default_tk'  : 'trakt.token',
        'data_tk'     : ['trakt.refresh', 'trakt.token', 'trakt.user', 'trakt.authed'],
        #MDB
        'default_mdb' : 'mdblist.token',
        'data_mdb'    : ['mdblist.token', 'mdblist.user', 'mdblist.refresh', 'indicators.alt.name', 'indicators.alt', 'bookmarks.source'],
    },

    #OTAKU
    'otaku': {
        'name'        : 'Otaku',
        'plugin'      : 'plugin.video.otaku',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.otaku'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.otaku', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.otaku', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.otaku', 'settings.xml'),
        #RD
        'default_rd'  : 'realdebrid.token',
        'data_rd'     : ['realdebrid.username', 'realdebrid.token', 'realdebrid.client_id', 'realdebrid.secret', 'realdebrid.refresh', 'realdebrid.enabled'],
        #PM
        'default_pm'  : 'premiumize.token',
        'data_pm'     : ['premiumize.username', 'premiumize.token', 'premiumize.enabled'],
        #AD
        'default_ad'  : 'alldebrid.token',
        'data_ad'     : ['alldebrid.username', 'alldebrid.token', 'alldebrid.enabled'],
        #ED
        'default_ed'  : 'eb.token',
        'data_ed'     : [],
        #TB
        'default_tb'  : 'torbox.token',
        'data_tb'     : ['torbox.token', 'torbox.username', 'torbox.enabled', 'torbox.auth.status'],
        #EN
        'default_en'  : 'easynews.password',
        'data_en'     : ['easynews.password', 'easynews.user', 'easynews.enabled'],
    },

    #EASYNEWS VIDEO
    'easyv': {
        'name'        : 'Easynews Video',
        'plugin'      : 'plugin.video.easynewsx',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.easynewsx'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.easynewsx', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.easynewsx', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.easynewsx', 'settings.xml'),
        #EN
        'default_en'  : 'general.password',
        'data_en'     : ['general.password', 'general.username'],
    },
    
    #RESOLVEURL
    'rurl': {
        'name'        : 'ResolveURL',
        'plugin'      : 'script.module.resolveurl',
        'path'        : os.path.join(CONFIG.ADDONS, 'script.module.resolveurl'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'script.module.resolveurl', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'script.module.resolveurl', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'script.module.resolveurl', 'settings.xml'),
        #RD
        'default_rd'  : 'RealDebridResolver_token',
        'data_rd'     : ['RealDebridResolver_client_id', 'RealDebridResolver_client_secret', 'RealDebridResolver_refresh', 'RealDebridResolver_token', 'RealDebridResolver_cached_only'],
        #PM
        'default_pm'  : 'PremiumizeMeResolver_token',
        'data_pm'     : ['PremiumizeMeResolver_token', 'PremiumizeMeResolver_cached_only', 'premiumize.status'],
        #AD
        'default_ad'  : 'AllDebridResolver_token',
        'data_ad'     : ['AllDebridResolver_token', 'AllDebridResolver_cached_only'],
        #TB
        'default_tb'  : 'TorBoxResolver_apikey',
        'data_tb'     : ['TorBoxResolver_apikey', 'TorBoxResolver_cached_only', 'TorBoxResolver_enabled'],
        #OC
        'default_oc'  : 'OffCloudResolver_apikey',
        'data_oc'     : ['OffCloudResolver_apikey', 'OffCloudResolver_user', 'OffCloudResolver_cached_only', 'OffCloudResolver_enabled'],
    },

    #TMDb HELPER - external Trakt & MDBList sync providers
    'tmdbhelper': {
        'name'        : 'TMDb Helper',
        'plugin'      : 'script.module.tmdbhelper.sync.trakt',
        'path'        : os.path.join(CONFIG.ADDONS, 'script.module.tmdbhelper.sync.trakt'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.themoviedb.helper', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.themoviedb.helper', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'script.module.tmdbhelper.sync.trakt', 'settings.xml'),
        'default_tk'  : 'token',
        'data_tk'     : ['token'],
        'mdb_plugin'  : 'script.module.tmdbhelper.sync.mdblist',
        'mdb_settings': os.path.join(CONFIG.ADDON_DATA, 'script.module.tmdbhelper.sync.mdblist', 'settings.xml'),
        'default_mdb' : 'apikey',
        'data_mdb'    : ['apikey'],
    },

    #TRAKT ADDON
    'trakt': {
        'name'        : 'Trakt Add-on',
        'plugin'      : 'script.trakt',
        'path'        : os.path.join(CONFIG.ADDONS, 'script.trakt'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'script.trakt', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'script.trakt', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'script.trakt', 'settings.xml'),
        #TK
        'default_tk'  : 'authorization',
        'data_tk'     : ['authorization', 'user'],
    },

    #PREMIUMIZERX
    'premx': {
        'name'        : 'Premiumizer',
        'plugin'      : 'plugin.video.premiumizerx',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.premiumizerx'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.premiumizerx', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.premiumizerx', 'fanart.jpg'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.premiumizerx', 'settings.xml'),
        #PM
        'default_pm'  : 'premiumize.token',
        'data_pm'     : ['premiumize.status', 'premiumize.token', 'premiumize.refresh'],
    },

    #REALIZERX
    'realx': {
        'name'        : 'Realizer',
        'plugin'      : 'plugin.video.realizerx',
        'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.realizerx'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.realizerx', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.realizerx', 'fanart.png'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.realizerx', 'rdauth.json'),
        #RD
        'default_rd'  : 'token',
        'data_rd'     : [],
    },

    #FENTASTIC
    'fentastic': {
        'name'        : 'FENtastic',
        'plugin'      : 'skin.fentastic',
        'path'        : os.path.join(CONFIG.ADDONS, 'skin.fentastic'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'skin.fentastic', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'skin.fentastic', 'fanart.png'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'skin.fentastic', 'settings.xml'),
        #MDB
        'default_mdb'  : 'mdblist_api_key',
        'data_mdb'     : [],
    },

    #NIMBUS
    'nimbus': {
        'name'        : 'Nimbus',
        'plugin'      : 'skin.nimbus',
        'path'        : os.path.join(CONFIG.ADDONS, 'skin.nimbus'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'skin.nimbus', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'skin.nimbus', 'fanart.png'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'skin.nimbus', 'settings.xml'),
        #MDB
        'default_mdb'  : 'mdblist_api_key',
        'data_mdb'     : [],
    },

    #ACCOUNT MANAGER - Revoke is handled in router.py
    'acctmgr': {
        'name'        : 'Account Manager Lite',
        'plugin'      : 'script.module.acctmgr',
        'path'        : os.path.join(CONFIG.ADDONS, 'script.module.acctmgr'),
        'icon'        : os.path.join(CONFIG.ADDONS, 'script.module.acctmgr', 'icon.png'),
        'fanart'      : os.path.join(CONFIG.ADDONS, 'script.module.acctmgr', 'fanart.png'),
        'settings'    : os.path.join(CONFIG.ADDON_DATA, 'script.module.acctmgr', 'settings.xml'),
        #TK
        'default_tk'  : 'trakt.token',
        'data_tk'     : [],
        #MDB
        'default_mdb'  : 'mdblist.apikey',
        'data_mdb'     : [],
        #RD
        'default_rd'  : 'realdebrid.token',
        'data_rd'     : [],
        #PM
        'default_pm'  : 'premiumize.token',
        'data_pm'     : [],
        #AD
        'default_ad'  : 'alldebrid.token',
        'data_ad'     : [],
        #ED
        'default_ed'  : 'easydebrid.token',
        'data_ed'     : [],
        #TB
        'default_tb'  : 'torbox.token',
        'data_tb'     : [],
        #OC
        'default_oc'  : 'offcloud.token',
        'data_oc'     : [],
        #EN
        'default_en'  : 'easynews.password',
        'data_en'     : [],
    },
}
            
# Helpers
def get_addon_by_id(id):
    try:
        return xbmcaddon.Addon(id=id)
    except Exception:
        return None

def addon_installed(who):
    info = ADDONS.get(who)
    if not info:
        return False

    plugin_id = info.get('plugin')
    if not plugin_id:
        return False

    try:
        if who == 'tmdbhelper':
            return (get_addon_by_id(plugin_id) is not None
                    or get_addon_by_id(info['mdb_plugin']) is not None)
        return get_addon_by_id(plugin_id) is not None
    except Exception:
        return False

def is_authorized_value(val):
    return bool(val) and str(val).strip().lower() not in ('', '0', 'none', 'null', 'empty_setting') # Added '0' due to Fen/Forks default setting being 0

def open_settings(who, service=None):  # Open add-on settings / skin settings
    info = ADDONS.get(who)
    if not info:
        return

    try:
        # Skins
        if who in ('fentastic', 'nimbus'):
            xbmc.executebuiltin('ActivateWindowAndFocus(skinsettings)')
            return

        # Use the selected TMDb Helper sync module for Trakt/MDBList.
        plugin_id = (info.get('mdb_plugin') if who == 'tmdbhelper' and service == 'mdb'
                     else info.get('plugin'))
        addon = get_addon_by_id(plugin_id)
        if addon:
            addon.openSettings()

    except Exception as e:
        xbmc.log(f"{amgr}: open_settings failed [{who}] - {e}", xbmc.LOGERROR)

def chk_sql_auth(db, key, return_value=False): # Check if a setting exists. If True, return the actual value
    if not key:
        return '' if return_value else False

    try:
        conn = sqlite3.connect(db, timeout=3)
        cur = conn.cursor()
        cur.execute(
            "SELECT setting_value FROM settings WHERE setting_id = ?", (key,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        value = row[0] if row else ''
        if return_value:
            return value
        return is_authorized_value(value)
    except Exception:
        return '' if return_value else False
      
def load_am_lite_tokens(): # Load AM Lite tokens for all services
    path = xbmcvfs.translatePath('special://profile/addon_data/script.module.acctmgr/settings.xml')
    tokens = { 'tk': {}, 'rd': {}, 'mdb': {}, 'pm': {}, 'ad': {}, 'ed': {}, 'tb': {}, 'oc': {}, 'en': {} }

    if os.path.exists(path):
        try:
            tree = ElementTree.parse(path)
            root = tree.getroot()

            # Define which keys belong to which service
            service_keys = {
                'tk': ['trakt.token'],
                'rd': ['realdebrid.token'],
                'mdb': ['mdblist.token', 'mdblist.apikey'],
                'pm': ['premiumize.token'],
                'ad': ['alldebrid.token'],
                'ed': ['easydebrid.token'],
                'tb': ['torbox.token'],
                'oc': ['offcloud.token'],
                'en': ['easynews.password'],
            }

            for setting in root.findall('setting'):
                key = setting.attrib.get('id')
                value = setting.text or ''
                for service, keys in service_keys.items():
                    if key in keys:
                        tokens[service][key] = value

        except Exception:
            xbmc.log('AM Lite: Failed to read service tokens from settings.xml', xbmc.LOGERROR)

    return tokens

AM_LITE_TOKENS = load_am_lite_tokens()

# Service-specific token dictionaries
TK_TOKENS  = {}
RD_TOKENS  = {}
MDB_TOKENS = {}
PM_TOKENS  = {}
AD_TOKENS  = {}
ED_TOKENS  = {}
TB_TOKENS  = {}
OC_TOKENS  = {}
EN_TOKENS  = {}

SERVICE_MAP = {
    'tk':  TK_TOKENS,
    'rd':  RD_TOKENS,
    'mdb': MDB_TOKENS,
    'pm':  PM_TOKENS,
    'ad':  AD_TOKENS,
    'ed':  ED_TOKENS,
    'tb':  TB_TOKENS,
    'oc':  OC_TOKENS,
    'en':  EN_TOKENS,
}

# Populate tokens for each add-on and service using default keys
for addon_id, info in ADDONS.items():
    settings_path = info.get('settings')
    if not settings_path or not os.path.exists(settings_path):
        if addon_id != 'tmdbhelper' or not os.path.exists(info.get('mdb_settings', '')):
            continue

    # Load key/value pairs from the add-on settings
    kv = {}
    if settings_path.endswith('.db'): # Add-ons setting Databases
        conn = sqlite3.connect(settings_path)
        cur = conn.cursor()
        cur.execute("SELECT setting_id, setting_value FROM settings")
        rows = cur.fetchall()
        conn.close()
        kv = {r[0]: r[1] for r in rows}

    elif settings_path.endswith('.xml') and os.path.isfile(settings_path): # Add-ons using settings.xml
        tree = ElementTree.parse(settings_path)
        root = tree.getroot()
        kv = {s.attrib.get('id'): s.text or '' for s in root.findall('setting')}

    elif settings_path.endswith('.json'): # Add-ons using json
        with open(settings_path) as f:
            kv = json.load(f)

    # Only store default key per service
    for service, dict_ref in SERVICE_MAP.items():
        default_key = info.get(f'default_{service}')
        if default_key:
            service_kv = kv
            if addon_id == 'tmdbhelper' and service == 'mdb':
                service_kv = {}
                mdb_path = info['mdb_settings']
                if os.path.isfile(mdb_path):
                    try:
                        mdb_root = ElementTree.parse(mdb_path).getroot()
                        service_kv = {s.attrib.get('id'): s.text or '' for s in mdb_root.findall('setting')}
                    except Exception as exc:
                        xbmc.log(f'{amgr}: MDBList provider read failed: {exc}', xbmc.LOGERROR)
            val = service_kv.get(default_key, '')

            # Handle JSON blob add-ons
            if addon_id in ('tmdbhelper', 'trakt') and service == 'tk' and val:
                try:
                    val_unescaped = val.replace('&quot;', '"')
                    val = json.loads(val_unescaped).get('access_token','')
                except Exception:
                    val = ''

            dict_ref[addon_id] = {default_key: val}

# Check Authorization
def _addon_user_service(addon_id, service, token_dict):
    info = ADDONS.get(addon_id, {})
    default_key = info.get(f'default_{service}')
    if not default_key:
        return False

    if service == 'mdb':
        am_key = 'mdblist.apikey' if 'api_key' in default_key or 'apikey' in default_key else 'mdblist.token'
    else:
        acctmgr_info = ADDONS.get('acctmgr', {})
        am_key = acctmgr_info.get(f'default_{service}')
    if not am_key:
        return False

    addon_val = token_dict.get(addon_id, {}).get(default_key, '')
    am_val = AM_LITE_TOKENS.get(service, {}).get(am_key, '')

    return is_authorized_value(addon_val) and str(addon_val).strip() == str(am_val).strip()


# Return TRUE if add-on tokens match AM Lite, else return FALSE
def addon_user_trakt(addon_id):
    # a4kStreaming uses Trakt for migration only; it has no OAuth token.
    if addon_id == 'a4k':
        try:
            a4k = get_addon_by_id('plugin.video.a4kstreaming')
            acctmgr = get_addon_by_id('script.module.acctmgr')
            if not a4k or not acctmgr:
                return False
            username = a4k.getSetting('trakt.username').strip()
            client_id = a4k.getSetting('trakt.clientid').strip()
            return (is_authorized_value(acctmgr.getSetting('trakt.token'))
                    and is_authorized_value(username)
                    and is_authorized_value(client_id)
                    and username == acctmgr.getSetting('trakt.username').strip())
        except Exception:
            return False
    return _addon_user_service(addon_id, 'tk', TK_TOKENS)

def addon_user_rd(addon_id):
    return _addon_user_service(addon_id, 'rd', RD_TOKENS)

def addon_user_mdb(addon_id):
    return _addon_user_service(addon_id, 'mdb', MDB_TOKENS)

def addon_user_pm(addon_id):
    return _addon_user_service(addon_id, 'pm', PM_TOKENS)

def addon_user_ad(addon_id):
    return _addon_user_service(addon_id, 'ad', AD_TOKENS)

def addon_user_ed(addon_id):
    return _addon_user_service(addon_id, 'ed', ED_TOKENS)

def addon_user_tb(addon_id):
    return _addon_user_service(addon_id, 'tb', TB_TOKENS)

def addon_user_oc(addon_id):
    return _addon_user_service(addon_id, 'oc', OC_TOKENS)

def addon_user_en(addon_id):
    return _addon_user_service(addon_id, 'en', EN_TOKENS)

# Revoke Handler
def addon_it(do, who='all', services=('tk','mdb','rd','pm','ad','ed','tb','oc','en'), force=True):
    #do: 'wipeaddon'
    #who: addon key or 'all'
    #Force: ignore token match and wipe all

    if who == 'all':
        targets = ORDER
    else:
        targets = (who,)

    for addon in targets:
        if addon not in ADDONS:
            continue

        # Skip uninstalled addons unless managed
        if addon not in ('fenlt', 'gears', 'redlt', 'realx', 'fentastic', 'nimbus', 'acctmgr') and not addon_installed(addon):
            xbmc.log(f"AM Lite: Skip revoke [{addon}] - addon not installed", xbmc.LOGINFO)
            continue

        for service in services:
            if addon == 'tmdbhelper' and service == 'mdb' and not get_addon_by_id('script.module.tmdbhelper.sync.mdblist'):
                continue
            check_func = globals().get(f'addon_user_{service}')
            if force or (check_func and check_func(addon)):
                wipe_addons(do, addon, service)

# Revoke Add-ons
def wipe_addons(do, who, service):
    info = ADDONS.get(who)
    if not info:
        return

    settings = info.get('mdb_settings') if who == 'tmdbhelper' and service == 'mdb' else info.get('settings', '')
    data = info.get(f'data_{service}', [])

    # Skip the below list of add-ons
    if who in ('fenlt', 'gears', 'redlt', 'fentastic', 'nimbus', 'acctmgr'):
        return

    if not settings:
        xbmc.log(f"{amgr}: wipe_addons skipped [{who}] - no settings path", xbmc.LOGINFO)
        return

    try:
        if settings.endswith('.json'):
            if os.path.exists(settings):
                with open(settings, 'w') as f:
                    f.write('{}')
            return

        if not os.path.exists(settings):
            xbmc.log(f"{amgr}: wipe_addons skipped [{who}] - settings not found", xbmc.LOGINFO)
            return

        if os.path.getsize(settings) == 0:
            xbmc.log(f"{amgr}: wipe_addons skipped [{who}] - settings file is empty", xbmc.LOGINFO)
            return

        tree = ElementTree.parse(settings)
        root = tree.getroot()

        removed = False
        for setting in list(root.findall('setting')):
            if setting.attrib.get('id') in data:
                root.remove(setting)
                removed = True

        if removed:
            tree.write(settings)

    except Exception as e:
        xbmc.log(f"{amgr}: wipe_addons failed [{who}/{service}] - {e}", xbmc.LOGERROR)

'''
#DRADIS
'dradis': {
    'name'        : 'Dradis',
    'plugin'      : 'plugin.video.dradis',
    'path'        : os.path.join(CONFIG.ADDONS, 'plugin.video.dradis'),
    'icon'        : os.path.join(CONFIG.ADDONS, 'plugin.video.dradis', 'icon.png'),
    'fanart'      : os.path.join(CONFIG.ADDONS, 'plugin.video.dradis', 'fanart.jpg'),
    'settings'    : os.path.join(CONFIG.ADDON_DATA, 'plugin.video.dradis', 'settings.xml'),
    #TK
    'default_tk'  : 'trakt.token',
    'data_tk'     : ['trakt.token', 'trakt.username', 'trakt.expires', 'trakt.refresh', 'trakt.isauthed', 'trakt_user'], # Trakt Client/Secret NOT required here for revoke due to default API keys being stored in the settings.xml
    #MDB
    'default_mdb'  : 'mdblist.token',
    'data_mdb'     : ['mdblist.token', 'mdblist.username'],
    #RD
    'default_rd'  : 'realdebrid.token',
    'data_rd'     : ['realdebrid.username', 'realdebrid.token', 'realdebrid.client_id', 'realdebrid.secret', 'realdebrid.refresh', 'realdebrid.enable'],
    #PM
    'default_pm'  : 'premiumize.token',
    'data_pm'     : ['premiumize.username', 'premiumize.token', 'premiumize.enable'],
    #AD
    'default_ad'  : 'alldebrid.token',
    'data_ad'     : ['alldebrid.username', 'alldebrid.token', 'alldebrid.enable'],
    #TB
    'default_tb'  : 'torbox.token',
    'data_tb'     : ['torbox.token', 'torbox.username', 'torbox.enable', 'torbox.expires'],
    #OC
    'default_oc'  : 'offcloud.token',
    'data_oc'     : ['offcloud.token', 'offcloud.username', 'offcloud.enable'],
    #EN
    'default_en'  : 'easynews_password',
    'data_en'     : ['easynews_password', 'easynews_user', 'provider.easynews'],
},
'''
