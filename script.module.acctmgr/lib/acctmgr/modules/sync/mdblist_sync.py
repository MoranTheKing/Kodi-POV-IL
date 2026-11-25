# -*- coding: utf-8 -*-
import xbmc, xbmcaddon, xbmcvfs
import json

from acctmgr.modules import control
from acctmgr.modules import var
from acctmgr.modules import log_utils
from acctmgr.modules.db import mdblist_db

exists = xbmcvfs.exists
ACCTMGR_ID = "script.module.acctmgr"

OAUTH = 'oauth'
APIKEY = 'apikey'


def _addon_target(addon_id, label, chk_addon, chk_settings, token_key, **kw):
    t = {
        'id': addon_id, 'label': label, 'type': 'addon',
        'chk_addon': chk_addon, 'chk_settings': chk_settings,
        'token_key': token_key,
        'user_key': None, 'refresh_key': None, 'expires_key': None,
        'indicators_act': None, 'wtch_indicators': None, 'remake_settings': None,
		'db_path': None, 'db_extra': None, 'extra': None,
    }
    t.update(kw)
    t['auth'] = OAUTH if t['refresh_key'] else APIKEY
    return t


def _skin_target(skin_id, label, chk_addon, chk_settings, path):
    return {
        'id': skin_id, 'label': label, 'type': 'skin', 'auth': APIKEY,
        'chk_addon': chk_addon, 'chk_settings': chk_settings, 'path': path,
    }


def get_targets():
	addons = [
		("plugin.video.gears",             "The Gears", var.chk_gears, var.chkset_gears, "mdblist.api_key", {"user_key": "mdblist.user", "db_path": var.gears_settings_db, "remake_settings": getattr(control, 'remake_gears_settings', None)}),
		("plugin.video.redlight",          "Red Light", var.chk_red,   var.chkset_red,   "mdblist.token",  {"refresh_key": "mdblist.refresh", "user_key": "mdblist.user", "db_path": var.red_settings_db, "db_extra": {"mdblist.cm_menu_migrated": "true"}, "remake_settings": getattr(control, 'remake_red_settings', None)}),
		("plugin.video.umbrella",          "Umbrella",  var.chk_umb,   var.chkset_umb,   "mdblist.token",  {"refresh_key": "mdblist.refresh.token"}),
		#("plugin.video.dradis",            "Dradis",    var.chk_dradis, var.chkset_dradis, "mdblist.token",  {"refresh_key": "mdblist.refresh", "user_key": "mdblist.username", "expires_key": "mdblist.expires"}),
		("plugin.video.pov",               "POV",       var.chk_pov,    var.chkset_pov,   "mdblist.token",  {"refresh_key": "mdblist.refresh", "user_key": "mdblist_user", "expires_key": "mdblist.expires", "indicators_act": "mdbl_indicators_active", "wtch_indicators": "watched_indicators", "remake_settings": getattr(control, 'remake_pov_settings', None)}),
		("plugin.video.luc_kodi",          "luc_kodi",  var.chk_luc,   var.chkset_luc,   "mdblist.token",  {"refresh_key": "mdblist.refresh", "user_key": "mdblist.username"}),
		("plugin.video.gratisred",         "Gratis Red", var.chk_redg,  var.chkset_redg,  "mdblist.token",  {"refresh_key": "mdblist.refresh", "user_key": "mdblist.user", "extra": {"indicators.alt.name": "MDBList", "indicators.alt": "3", "bookmarks.source": "3"}}),
	]

	skins = [
		("skin.fentastic", "FENtastic", var.chk_fentastic, var.chkset_fentastic, var.path_fentastic),
		("skin.nimbus",    "Nimbus",    var.chk_nimbus,    var.chkset_nimbus,    var.path_nimbus),
	]

	targets = [_addon_target(aid, lbl, chk, chk_s, tk, **kw) for aid, lbl, chk, chk_s, tk, kw in addons]
	targets.extend(_skin_target(sid, lbl, chk, chk_s, p) for sid, lbl, chk, chk_s, p in skins)

	return targets


def _active_skin():
    try:
        query = json.loads(xbmc.executeJSONRPC(
            '{"jsonrpc":"2.0","method":"Settings.GetSettingValue","params":{"setting":"lookandfeel.skin"},"id":1}'
        ))
        return (query.get("result") or {}).get("value") or ""
    except Exception as e:
        log_utils.error(f"MDBList active skin lookup failed: {e}")
        return ""


def detect_installed():
    #Scan for installed targets and return (oauth_targets, apikey_targets)
    oauth, apikey = [], []
    skin = None
    for t in get_targets():
        try:
            if t['type'] == 'skin':
                if skin is None:
                    skin = _active_skin()
                if skin != t['id']:
                    continue
            if not (exists(t['chk_addon']) and exists(t['chk_settings'])):
                continue
            (oauth if t['auth'] == OAUTH else apikey).append(t)
        except Exception as e:
            log_utils.error(f"{t.get('label')} MDBList detection failed: {e}")
    # TMDb Helper requires an external MDBList provider; include it even before installation.
    if exists(var.chk_tmdbh):
        apikey.append({"id": "script.module.tmdbhelper.sync.mdblist", "label": "TMDb Helper", "type": "addon", "auth": APIKEY, "chk_addon": var.chk_tmdbh, "chk_settings": "", "token_key": "apikey", "user_key": None, "refresh_key": None, "db_path": None, "remake_settings": None, "tmdbh_external": True})
    return oauth, apikey


def read_credentials(acctmgr=None):
    #Read stored MDBList credentials, separating OAuth tokens from API keys.
    acctmgr = acctmgr or xbmcaddon.Addon(ACCTMGR_ID)
    get = acctmgr.getSetting
    creds = {
        'username': get("mdblist.username"),
        'token': get("mdblist.token"),
        'refresh': get("mdblist.refresh"),
        'expires': get("mdblist.expires"),
        'apikey': get("mdblist.apikey"),
    }
    # Separate legacy OAuth access token improperly saved in the apikey field.
    if not creds['token'] and creds['refresh'] and creds['apikey']:
        creds['token'], creds['apikey'] = creds['apikey'], ''
    return creds


class Auth:
    def mdblist_auth(self):
        """Push stored credentials to all installed targets."""
        creds = read_credentials()
        oauth_targets, apikey_targets = detect_installed()

        for t in oauth_targets:
            self._sync_oauth(t, creds)

        for t in apikey_targets:
            if t.get("tmdbh_external"):
                from acctmgr.modules.sync import tmdbh_mdblist
                tmdbh_mdblist.sync(creds["apikey"])
            else:
                self._sync_apikey(t, creds)

    def _sync_oauth(self, t, creds):
        token, refresh = creds['token'], creds['refresh']
        if not token or not refresh:
            log_utils.log(f"{t['label']}: no MDBList OAuth token stored - skipped",
                          __name__, log_utils.LOGDEBUG)
            return
        try:
            if t.get('db_path'):
                settings = {t['token_key']: token, t['refresh_key']: refresh}
                if t['user_key'] and creds['username']:
                    settings[t['user_key']] = creds['username']
                if t.get('db_extra'):
                    settings.update(t['db_extra'])
                mdblist_db.update(t['db_path'], settings)
                if t.get('remake_settings'):
                    xbmc.sleep(200)
                    t['remake_settings']()
                return

            addon = xbmcaddon.Addon(t['id'])

            settings = {t['token_key']: token, t['refresh_key']: refresh}

            if t['user_key'] and creds['username']:
                settings[t['user_key']] = creds['username']

            if t['expires_key'] and creds['expires']:
                settings[t['expires_key']] = creds['expires']

            if t['indicators_act']:
                settings[t['indicators_act']] = "true"

            if t['wtch_indicators']:
                settings[t['wtch_indicators']] = "2"

            if t['extra']:
                settings.update(t['extra'])

            for k, v in settings.items():
                addon.setSetting(k, v)

            if t['remake_settings']:
                xbmc.sleep(200)
                #t['remake_settings']()

        except Exception as e:
            log_utils.error(f"{t['label']} MDBList Failed: {e}")

    def _sync_apikey(self, t, creds):
        key = creds['apikey']
        if not key:
            log_utils.log(f"{t['label']}: no MDBList API key stored - skipped",
                          __name__, log_utils.LOGDEBUG)
            return
        try:
            if t.get('db_path'):
                settings = {t['token_key']: key}
                if t['user_key'] and creds['username']:
                    settings[t['user_key']] = creds['username']
                if t.get('db_extra'):
                    settings.update(t['db_extra'])
                mdblist_db.update(t['db_path'], settings)
                if t.get('remake_settings'):
                    xbmc.sleep(200)
                    t['remake_settings']()
                return

            if t['type'] == 'skin':
                with open(t['path'], "r", encoding="utf-8") as f:
                    data = f.read()
                if key not in data:
                    xbmc.executebuiltin('Skin.SetString(mdblist_api_key,{})'.format(key))
                return

            addon = xbmcaddon.Addon(t['id'])
            if addon.getSetting(t['token_key']) == key:
                return
            addon.setSetting(t['token_key'], key)

        except Exception as e:
            log_utils.error(f"{t['label']} MDBList Failed: {e}")
