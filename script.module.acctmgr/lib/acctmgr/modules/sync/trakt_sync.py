# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcaddon, xbmcvfs
import os
import time
import json

from acctmgr.modules import var
from acctmgr.modules import control
from acctmgr.modules import log_utils
from acctmgr.modules.db import chk_auth_db
from acctmgr.modules.db import trakt_db

# Variables
joinPath = os.path.join
exists = xbmcvfs.exists
translatePath = xbmcvfs.translatePath
addon_id = xbmcaddon.Addon().getAddonInfo('id')
addon = xbmcaddon.Addon(addon_id)
addoninfo = addon.getAddonInfo

# Sync Helpers
def set_verified_setting(addon, key, value):
	addon.setSetting(key, str(value))
	if addon.getSetting(key) != str(value):
		raise RuntimeError(f"Trakt setting verification failed: {key}")

def refresh_sync(mode, chk_auth, token):
    if mode in ("auth", "repair"):
        return True
    return chk_auth != str(token)

def authorize(mode):
    return mode == "auth"

class Auth:
    def am_trakt(self):
        acctmgr = xbmcaddon.Addon("script.module.acctmgr")
        your_token = acctmgr.getSetting("trakt.token")
        your_username = acctmgr.getSetting("trakt.username")
        your_refresh = '1'
        your_expires = acctmgr.getSetting("trakt.expires")
        try:
            your_expires_int = int(float(your_expires or 0))
        except Exception as e:
            log_utils.error(f"Error converting trakt.expires: {e}")
            your_expires_int = 0
        return your_token, your_username, your_refresh, str(your_expires_int)

    def trakt_auth(self, mode="refresh"):
        your_token, your_username, your_refresh, your_expires = self.am_trakt()
        master_token = your_token
        your_expires_in = xbmcaddon.Addon("script.module.acctmgr").getSetting("trakt.expires_in")
        self._sync_failures = []

        if not exists(var.tk_sync_list):
            log_utils.error("Trakt sync list missing")
            return False

        try:
            with open(var.tk_sync_list, "r") as synclist:
                current = json.load(synclist)["addon_list"]
        except Exception as e:
            log_utils.error(f"Error reading sync list: {e}")
            return False

        # ===================== Copy Addon Data (settings.xml) =====================
        addons = (
            ("Shadow",                  var.chk_shadow, var.shadow_ud,  var.chkset_shadow,  var.shadow),
            ("Ghost",                   var.chk_ghost,  var.ghost_ud,   var.chkset_ghost,   var.ghost),
            ("The Chains",              var.chk_chains, var.chains_ud,  var.chkset_chains,  var.chains),
            ("Homelander",              var.chk_home,   var.home_ud,    var.chkset_home,    var.home),
            ("Nightwing",               var.chk_night,  var.night_ud,   var.chkset_night,   var.night),
            ("Absolution",              var.chk_absol,  var.absol_ud,   var.chkset_absol,   var.absol),
            ("The Crew",                var.chk_crew,   var.crew_ud,    var.chkset_crew,    var.crew),
            ("SALTS",                   var.chk_salts,  var.salts_ud,   var.chkset_salts,   var.salts),
            ("Scrubs V2",               var.chk_scrubs, var.scrubs_ud,  var.chkset_scrubs,  var.scrubs),
            ("Gratis Red",              var.chk_redg,   var.redg_ud,    var.chkset_redg,    var.redg),
            ("TMDb Helper",             var.chk_tmdbh,  var.tmdbh_ud,   var.chkset_tmdbh,   var.tmdbh),
            ("Trakt",                   var.chk_trakt,  var.trakt_ud,   var.chkset_trakt,   var.trakt),
            ("Mad Titan Sports",        var.chk_madtitan, var.madtitan_ud, var.chkset_madtitan, var.madtitan),
            ("a4kStreaming",            var.chk_a4k, var.a4k_ud, var.chkset_a4k, var.a4k),
        )

        for name, chk_addon, ud_path, chk_setting, base_path in addons:
            try:
                control.copy_addon_settings(name, chk_addon, ud_path, chk_setting, base_path)
            except Exception as e:
                self._sync_failures.append(f"{name} settings copy: {e}")
                log_utils.error(f"Error copying settings for {name}: {e}")
                
        # ========================= Fen Light / The Gears / Red Light =========================
        # ========================== API Keys applied to settings.db ==========================

        addons = (
            ("Fen Light", "Fen Light", var.chk_fenlt, var.chkset_fenlt, var.fenlt_settings_db, control.remake_fenlt_settings, var.path_fenlt_service, control.remake_fenlt_trakt_cache),
            ("The Gears", "The Gears", var.chk_gears, var.chkset_gears, var.gears_settings_db, control.remake_gears_settings, var.path_gears_service, control.remake_gears_trakt_cache),
            ("Red Light", "Red Light", var.chk_red, var.chkset_red, var.red_settings_db, control.remake_red_settings, var.path_red_service, control.remake_redlt_trakt_cache),
        )

        for current_name, addon_name, chk_path, chkset_path, settings_db, remake_settings_func, service_path, remake_cache_func in addons:
            try:
                if current_name in current and exists(chk_path):

                    if not exists(chkset_path):
                        remake_settings_func()
                        xbmc.sleep(500)

                    if exists(chkset_path):
                        chk_auth = chk_auth_db.chk_auth(settings_db, "trakt.token")

                        if refresh_sync(mode, chk_auth, master_token):
                            if not trakt_db.auth(settings_db):
                                raise RuntimeError(f"{current_name} database Trakt write failed")
                            remake_settings_func()

                            patched, msg = control.startup_patch(service_path, addon_name=addon_name)
                            if not patched:
                                raise RuntimeError(f"{addon_name} startup patch failed, msg={msg}")

                            if authorize(mode):
                                xbmc.sleep(300)
                                remake_cache_func()
                    else:
                        raise RuntimeError(f"{current_name} settings database unavailable")

            except Exception as e:
                self._sync_failures.append(str(e))
                log_utils.error(f"{current_name} Trakt Failed: {e}")

        # ========================= Mad Titan Sports =========================
        try:
            if "Mad Titan Sports" in current and exists(var.chk_madtitan):
                addon = xbmcaddon.Addon("plugin.video.madtitansports")
                chk_auth = addon.getSetting("trakt.access_token")
                if refresh_sync(mode, chk_auth, master_token):
                    for k, v in {
                        "trakt.client_id": var.client_am,
                        "trakt.client_secret": var.secret_am,
                        "trakt.access_token": your_token,
                        "trakt.refresh_token": your_refresh,
                        "trakt.user_id": your_username,
                        "trakt.authorize": "Authorized",
                    }.items():
                        set_verified_setting(addon, k, v)
        except Exception as e:
            self._sync_failures.append(str(e))
            log_utils.error(f"Mad Titan Sports Trakt Failed: {e}")

        # ========================= a4kStreaming (Migration Only) =========================
        try:
            if "a4kStreaming" in current and exists(var.chk_a4k):
                addon = xbmcaddon.Addon("plugin.video.a4kstreaming")
                for key, value in {
                    "trakt.clientid": var.client_am,
                    "trakt.username": your_username,
                }.items():
                    if addon.getSetting(key) != str(value):
                        set_verified_setting(addon, key, value)
        except Exception as e:
            self._sync_failures.append(str(e))
            log_utils.error(f"a4kStreaming Trakt Migration Failed: {e}")

        # ========================= Umbrella =========================
        try:
            if "Umbrella" in current and exists(var.chk_umb) and exists(var.chkset_umb):
                addon = xbmcaddon.Addon("plugin.video.umbrella")
                chk_auth = addon.getSetting("trakt.user.token")
                if refresh_sync(mode, chk_auth, master_token):
                    with open(var.path_umb, "r") as f:
                        data = f.read()

                    patched_keys = False
                    if var.umb_client in data or var.umb_secret in data:
                        data = data.replace(var.umb_client, var.client_am).replace(var.umb_secret, var.secret_am)
                        with open(var.path_umb, "w") as f:
                            f.write(data)
                        patched_keys = True
                    elif var.client_am in data and var.secret_am in data:
                        patched_keys = True

                    if not patched_keys:
                        raise RuntimeError("Umbrella Trakt keys NOT patched")

                    patched, msg = control.startup_patch(var.path_umb_service, addon_name="Umbrella")
                    if not patched:
                        raise RuntimeError(f"Umbrella startup patch failed, msg={msg}")

                    for k, v in {
                        "trakt.user.name": your_username,
                        "trakt.user.token": your_token,
                        "trakt.refreshtoken": your_refresh,
                        "trakt.token.expires": your_expires,
                        "trakt.authed.clientid": var.client_am,
                        "indicators": "Trakt",
                        "trakt.isauthed": "true",
                        "trakt.scrobble": "true",
                        "indicators.alt": "1",
                        "scrobble.source": "1",
                        "resume.source": "1",
                    }.items():
                        set_verified_setting(addon, k, v)
        except Exception as e:
            self._sync_failures.append(str(e))
            log_utils.error(f"Umbrella Trakt Failed: {e}")

        # ========================== POV ==========================
        # ============ API Keys applied to settings.xml ===========
        try:
            if "POV" in current and exists(var.chk_pov) and exists(var.chkset_pov):
                addon = xbmcaddon.Addon("plugin.video.pov")
                chk_auth = addon.getSetting("trakt.token")
                if refresh_sync(mode, chk_auth, master_token):
                    patched, msg = control.startup_patch(var.path_pov_service)
                    if not patched:
                        raise RuntimeError(f"POV startup patch failed, msg={msg}")
                    for k, v in {
                        "trakt.client_id": var.client_am,
                        "trakt.client_secret": var.secret_am,
                        "trakt.token": your_token,
                        "trakt_user": your_username,
                        "trakt.refresh": your_refresh,
                        "trakt.expires": your_expires,
                        "trakt_indicators_active": "true",
                        "watched_indicators": "1",
                    }.items():
                        set_verified_setting(addon, k, v)
                    #control.remake_pov_settings()
                    xbmc.sleep(500)
                    control.remake_pov_trakt_cache()
        except Exception as e:
            self._sync_failures.append(str(e))
            log_utils.error(f"POV Trakt Failed: {e}")
            
        # =================== Dradis / Genocide ===================
        # ============ API Keys applied to settings.xml ===========
        addons = [
            #("Dradis",        "plugin.video.dradis",    var.chk_dradis, var.chkset_dradis, var.path_dradis_service),
            ("Genocide",      "plugin.video.genocide",  var.chk_genocide, var.chkset_genocide, var.path_genocide_service),
        ]
        for name, plugin, chk_addon, chk_setting, path_service in addons:
            try:
                if name in current and exists(chk_addon) and exists(chk_setting):
                    addon = xbmcaddon.Addon(plugin)
                    chk_auth = addon.getSetting("trakt.token")
                    if refresh_sync(mode, chk_auth, master_token):
                        patched, msg = control.startup_patch(path_service)
                        if not patched:
                            raise RuntimeError(f"{name} startup patch failed, msg={msg}")
                        expires = int(time.time() + (8 * 86400))
                        for k, v in {
                            "trakt.client_id": var.client_am,
                            "trakt.client_secret": var.secret_am,
                            "trakt.username": your_username,
                            "trakt.token": your_token,
                            "trakt.refresh": your_refresh,
                            "trakt.expires": str(expires),
                            "trakt.isauthed": "true",
                        }.items():
                            set_verified_setting(addon, k, v)
            except Exception as e:
                self._sync_failures.append(str(e))
                log_utils.error(f"{name} Trakt Failed: {e}")

        # ========================= Seren =========================
        try:
            if "Seren" in current and exists(var.chk_seren) and exists(var.chkset_seren):
                addon = xbmcaddon.Addon("plugin.video.seren")
                chk_auth = addon.getSetting("trakt.auth")
                if refresh_sync(mode, chk_auth, master_token):
                    patched_keys, key_msg = control.patch_seren_trakt_keys()
                    if not patched_keys:
                        log_utils.log(key_msg, level=log_utils.LOGERROR)
                        raise RuntimeError(key_msg)

                    patched, msg = control.startup_patch(var.path_seren_service)
                    if not patched:
                        raise RuntimeError(f"Seren startup patch failed, msg={msg}")

                    your_expires_str = str(int(float(your_expires)))
                    for k, v in {
                        "trakt.auth": your_token,
                        "trakt.username": your_username,
                        "trakt.refresh": your_refresh,
                        "trakt.expires": your_expires_str,
                        "trakt.enabled": "true",
                    }.items():
                        set_verified_setting(addon, k, v)
        except Exception as e:
            self._sync_failures.append(str(e))
            log_utils.error(f"Seren Trakt Failed: {e}")

        # ========================= luc_kodi =========================
        # ============ API Keys applied to settings.xml ===========
        try:
            if "Luc_Kodi" in current and exists(var.chk_luc) and exists(var.chkset_luc):
                addon = xbmcaddon.Addon("plugin.video.luc_kodi")
                chk_auth = addon.getSetting("trakt.token")
                if refresh_sync(mode, chk_auth, master_token):
                    patched, msg = control.startup_patch(var.path_luc_service)
                    if not patched:
                        raise RuntimeError(f"luc_kodi startup patch failed, msg={msg}")
                    for k, v in {
                        "trakt.username": your_username,
                        "trakt.token": your_token,
                        "trakt.refresh": your_refresh,
                        "trakt.expires": your_expires,
                        "trakt.client_id": var.client_am,
                        "trakt.client_secret": var.secret_am,
                    }.items():
                        set_verified_setting(addon, k, v)
        except Exception as e:
            self._sync_failures.append(str(e))
            log_utils.error(f"luc_kodi Trakt Failed: {e}")

        # ========================= Shadow / Ghost =========================
        # ==================================================================
        # ============== Start-up Service Patch NOT Required ===============
        addons = [
            ("Shadow", "plugin.video.shadow", var.chk_shadow, var.shadow_ud, var.chkset_shadow, var.shadow),
            ("Ghost",  "plugin.video.ghost",  var.chk_ghost,  var.ghost_ud,  var.chkset_ghost,  var.ghost),
            ("The Chains",  "plugin.video.thechains",  var.chk_chains,  var.chains_ud,  var.chkset_chains,  var.chains), 
        ]

        for name, plugin, chk_addon, ud_path, chk_setting, base_path in addons:
            try:
                if name in current and exists(chk_addon):
                    addon = xbmcaddon.Addon(plugin)
                    chk_auth = addon.getSetting("trakt_access_token")

                    if refresh_sync(mode, chk_auth, master_token):
                        for k, v in {
                            "trakt_access_token": your_token,
                            "trakt_refresh_token": your_refresh,
                            "trakt_expires_at": your_expires,
                        }.items():
                            set_verified_setting(addon, k, v)

                        if name == "Shadow":
                            path = var.path_shadow
                            old_client = var.shadow_client
                            old_secret = var.shadow_secret
                        elif name == "Ghost":
                            path = var.path_ghost
                            old_client = var.ghost_client
                            old_secret = var.ghost_secret
                        elif name == "The Chains":
                            path = var.path_chains
                            old_client = var.thechains_client
                            old_secret = var.thechains_secret

                        try:
                            with open(path, "r", encoding="utf-8") as f:
                                data = f.read()

                            patched = False
                            if old_client in data or old_secret in data:
                                data = data.replace(old_client, var.client_am).replace(old_secret, var.secret_am)
                                with open(path, "w", encoding="utf-8") as f:
                                    f.write(data)
                                patched = True
                            elif var.client_am in data and var.secret_am in data:
                                patched = True

                            if not patched:
                                raise RuntimeError(f"{name}: Trakt keys NOT patched")

                        except Exception as e:
                            raise RuntimeError(f"{name} Trakt API keys patch failed: {e}") from e

            except Exception as e:
                self._sync_failures.append(str(e))
                log_utils.error(f"{name} Trakt Failed: {e}")


        # ============= Homelander / Nightwing / Jokers Absolution =============
        # =================== API Keys applied to settings.xml =================
        addons = [
            ("Homelander",        "plugin.video.homelander", var.chk_home,  var.home_ud,  var.chkset_home,  var.home, var.path_home_service),
            ("Nightwing",         "plugin.video.nightwing",  var.chk_night, var.night_ud, var.chkset_night, var.night, var.path_night_service),
            ("Absolution",        "plugin.video.absolution", var.chk_absol, var.absol_ud, var.chkset_absol, var.absol, var.path_absol_service),
        ]

        for name, plugin, chk_addon, ud_path, chk_setting, base_path, path_service in addons:
            try:
                if name in current and exists(chk_addon):
                    addon = xbmcaddon.Addon(plugin)
                    chk_auth = addon.getSetting("trakt.token")
                    if refresh_sync(mode, chk_auth, master_token):
                        patched, msg = control.startup_patch(path_service)
                        if not patched:
                            raise RuntimeError(f"{name} startup patch failed, msg={msg}")
                        for k, v in {
                            "trakt.user": your_username,
                            "trakt.token": your_token,
                            "trakt.refresh": your_refresh,
                            "trakt.authed": "yes",
                            "trakt.client_id": var.client_am,
                            "trakt.client_secret": var.secret_am,
                        }.items():
                            set_verified_setting(addon, k, v)
            except Exception as e:
                self._sync_failures.append(str(e))
                log_utils.error(f"{name} Trakt Failed: {e}")

        # ========================= The Crew =========================
        try:
            if "The Crew" in current:
                if exists(var.chk_crew) and exists(var.chkset_crew):
                    addon = xbmcaddon.Addon("plugin.video.thecrew")
                    chk_auth = addon.getSetting("trakt.token")
                    if refresh_sync(mode, chk_auth, master_token):
                        with open(var.path_crew, "r") as f:
                            data = f.read()

                        patched_keys = False
                        if var.crew_client in data or var.crew_secret in data:
                            data = data.replace(var.crew_client, var.client_am_x).replace(var.crew_secret, var.secret_am_x)
                            with open(var.path_crew, "w") as f:
                                f.write(data)
                            patched_keys = True

                        elif var.client_am_x in data and var.secret_am_x in data:
                            patched_keys = True

                        if not patched_keys:
                            raise RuntimeError("The Crew Trakt keys NOT patched")

                        patched, msg = control.startup_patch(var.path_crew_service)
                        if not patched:
                            raise RuntimeError(f"The Crew startup patch failed, msg={msg}")

                        for k, v in {
                            "trakt.user": your_username,
                            "trakt.token": your_token,
                            "trakt.refresh": your_refresh,
                            "trakt.expires_at": your_expires,
                            "silent.boot": "true",
                        }.items():
                            set_verified_setting(addon, k, v)
        except Exception as e:
            self._sync_failures.append(str(e))
            log_utils.error(f"The Crew Trakt Failed: {e}")

        # ========================= SALTS =========================
        try:
            if "SALTS" in current:
                if exists(var.chk_salts) and exists(var.chkset_salts):
                    addon = xbmcaddon.Addon("plugin.video.salts")
                    chk_auth = addon.getSetting("trakt_access_token")
                    if refresh_sync(mode, chk_auth, master_token):
                        with open(var.path_salts, "r") as f:
                            data = f.read()

                        patched_keys = False
                        if var.salts_client in data or var.salts_secret in data:
                            data = data.replace(var.salts_client, var.client_am).replace(var.salts_secret, var.secret_am)
                            with open(var.path_salts, "w") as f:
                                f.write(data)
                            patched_keys = True
                        elif var.client_am in data and var.secret_am in data:
                            patched_keys = True

                        if not patched_keys:
                            raise RuntimeError("SALTS Trakt keys NOT patched")

                        patched, msg = control.startup_patch(var.path_salts_service)
                        if not patched:
                            raise RuntimeError(f"SALTS startup patch failed, msg={msg}")

                        for k, v in {
                            "trakt_access_token": your_token,
                            "trakt_refresh_token": your_refresh,
                            "trakt_expires": your_expires,
                            "trakt_enabled": "true",
                        }.items():
                            set_verified_setting(addon, k, v)
        except Exception as e:
            self._sync_failures.append(str(e))
            log_utils.error(f"SALTS Trakt Failed: {e}")

        # ========================= Scrubs V2 =========================
        try:
            if "Scrubs V2" in current:
                if exists(var.chk_scrubs) and exists(var.chkset_scrubs):
                    addon = xbmcaddon.Addon("plugin.video.scrubsv2")
                    chk_auth = addon.getSetting("trakt.token")
                    if refresh_sync(mode, chk_auth, master_token):
                        with open(var.path_scrubs, "r") as f:
                            data = f.read()

                        patched_keys = False
                        if var.scrubs_client in data or var.scrubs_secret in data:
                            data = data.replace(var.scrubs_client, var.client_am).replace(var.scrubs_secret, var.secret_am)
                            with open(var.path_scrubs, "w") as f:
                                f.write(data)
                            patched_keys = True
                        elif var.client_am in data and var.secret_am in data:
                            patched_keys = True

                        if not patched_keys:
                            raise RuntimeError("Scrubs V2 Trakt keys NOT patched")

                        patched, msg = control.startup_patch(var.path_scrubs_service)
                        if not patched:
                            raise RuntimeError(f"Scrubs V2 startup patch failed, msg={msg}")

                        for k, v in {
                            "trakt.user": your_username,
                            "trakt.token": your_token,
                            "trakt.refresh": your_refresh,
                            "trakt.authed": "yes",
                        }.items():
                            set_verified_setting(addon, k, v)
        except Exception as e:
            self._sync_failures.append(str(e))
            log_utils.error(f"Scrubs V2 Trakt Failed: {e}")

        # ========================= Gratis Red =========================
        try:
            if "Gratis Red" in current:
                if exists(var.chk_redg) and exists(var.chkset_redg):
                    addon = xbmcaddon.Addon("plugin.video.gratisred")
                    chk_auth = addon.getSetting("trakt.token")
                    if refresh_sync(mode, chk_auth, master_token):
                        with open(var.path_redg, "r") as f:
                            data = f.read()

                        patched_keys = False
                        if var.redg_client in data or var.redg_secret in data:
                            data = data.replace(var.redg_client, var.client_am).replace(var.redg_secret, var.secret_am)
                            with open(var.path_redg, "w") as f:
                                f.write(data)
                            patched_keys = True
                        elif var.client_am in data and var.secret_am in data:
                            patched_keys = True

                        if not patched_keys:
                            raise RuntimeError("Gratis Red Trakt keys NOT patched")

                        patched, msg = control.startup_patch(var.path_redg_service)
                        if not patched:
                            raise RuntimeError(f"Gratis Red startup patch failed, msg={msg}")

                        for k, v in {
                            "trakt.user": your_username,
                            "trakt.token": your_token,
                            "trakt.refresh": your_refresh,
                            "trakt.authed": "yes",
                        }.items():
                            set_verified_setting(addon, k, v)
        except Exception as e:
            self._sync_failures.append(str(e))
            log_utils.error(f"Gratis Red Trakt Failed: {e}")

        # ========================= TMDb Helper (external Trakt provider) =========================
        try:
            if "TMDb Helper" in current and exists(var.chk_tmdbh):
                from acctmgr.modules.sync import tmdbh_provider
                tmdbh_provider.sync()
        except Exception as e:
            self._sync_failures.append("TMDb Helper provider sync: %s" % e)
            log_utils.error("TMDb Helper provider sync failed: %s" % e)

        # ========================= Trakt Addon =========================
        try:
            if "Trakt Addon" in current and exists(var.chk_trakt) and exists(var.chkset_trakt):
                addon = xbmcaddon.Addon("script.trakt")
                chk_auth = addon.getSetting("authorization")
                try:
                    chk_auth = json.loads(chk_auth).get("access_token", "")
                except (ValueError, TypeError, AttributeError):
                    chk_auth = ""

                if refresh_sync(mode, chk_auth, master_token):
                    with open(var.path_trakt, "r") as f:
                        data = f.read()

                    patched_keys = False
                    if var.trakt_client_obs_str in data or var.trakt_secret_obs_str in data:
                        data = data.replace(var.trakt_client_obs_str, var.client_am_obs_str).replace(var.trakt_secret_obs_str, var.secret_am_obs_str)
                        with open(var.path_trakt, "w") as f:
                            f.write(data)
                        patched_keys = True
                    elif var.client_am_obs_str in data and var.secret_am_obs_str in data:
                        patched_keys = True

                    if not patched_keys:
                        raise RuntimeError("Trakt Addon Trakt keys NOT patched")

                    patched, msg = control.startup_patch(var.path_trakt_service)
                    if not patched:
                        raise RuntimeError(f"Trakt Add-on startup patch failed, msg={msg}")

                    expires_int = int(float(your_expires or 0))
                    expires_in_int = int(float(your_expires_in or 0))
                    if expires_int <= 0 or expires_in_int <= 0:
                        raise RuntimeError("AM Lite Trakt expiration values unavailable")
                    created_at = expires_int - expires_in_int
                    trakt_data = (
                        '{"access_token":"%s","token_type":"bearer",'
                        '"expires_in":%s,"refresh_token":"%s",'
                        '"scope":"public","created_at":%s}'
                        % (your_token, expires_in_int, your_refresh, created_at)
                    )

                    set_verified_setting(addon, "user", your_username)
                    set_verified_setting(addon, "authorization", trakt_data)
        except Exception as e:
            self._sync_failures.append(str(e))
            log_utils.error(f"Trakt Addon Trakt Failed: {e}")

        if self._sync_failures:
            log_utils.error(f"Trakt sync incomplete: {len(self._sync_failures)} add-on operation(s) failed")
            return False
        return True
