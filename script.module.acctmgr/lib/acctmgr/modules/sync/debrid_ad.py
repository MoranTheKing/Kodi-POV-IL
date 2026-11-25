# -*- coding: utf-8 -*-
import xbmc, xbmcaddon, xbmcvfs
import sys
import os

from acctmgr.modules import control
from acctmgr.modules import var
from acctmgr.modules import log_utils
from acctmgr.modules.db import chk_auth_db
from acctmgr.modules.db import debrid_db

# Variables
joinPath = os.path.join
exists = xbmcvfs.exists
char_remov = ["'", ",", ")", "("]

class Auth:
    def alldebrid_auth(self):

        # ============================ AM Lite Variables =============================
        acctmgr = xbmcaddon.Addon("script.module.acctmgr")
        your_ad_username = acctmgr.getSetting("alldebrid.username")
        your_ad_token = acctmgr.getSetting("alldebrid.token")
        ad_master_token = your_ad_token

        # =================== Copy Addon Data (settings.xml) ==================
        addons = [
            ("Shadow",        var.chk_shadow,  var.shadow_ud,  var.chkset_shadow,  var.shadow),
            ("Ghost",         var.chk_ghost,   var.ghost_ud,   var.chkset_ghost,   var.ghost),
            ("The Chains",    var.chk_chains,  var.chains_ud,  var.chkset_chains,  var.chains),
            ("SALTS",         var.chk_salts,   var.salts_ud,   var.chkset_salts,   var.salts),
            ("Otaku",         var.chk_otaku,   var.otaku_ud,   var.chkset_otaku,   var.otaku),
            ("a4kStreaming", var.chk_a4k, var.a4k_ud, var.chkset_a4k, var.a4k),
            ("ResolveURL",    var.chk_rurl,    var.rurl_ud,    var.chkset_rurl,    var.rurl),
        ]

        for name, chk_addon, ud_path, chk_setting, base_path in addons:
            control.copy_addon_settings(
                name,
                chk_addon,
                ud_path,
                chk_setting,
                base_path
            )
            
        # ========================= Fen Light / The Gears / Red Light =========================
        addons = (
            ("Fen Light", var.chk_fenlt, var.chkset_fenlt, var.fenlt_settings_db, control.remake_fenlt_settings),
            ("Gears", var.chk_gears, var.chkset_gears, var.gears_settings_db, control.remake_gears_settings),
            ("Red Light", var.chk_red, var.chkset_red, var.red_settings_db, control.remake_red_settings),
        )

        for addon_name, chk_path, chkset_path, settings_db, remake_func in addons:
            try:
                if exists(chk_path):

                    if not exists(chkset_path):
                        remake_func()
                        xbmc.sleep(500)

                    if exists(chkset_path):
                        chk_auth = chk_auth_db.chk_auth(settings_db, "ad.token")

                        if chk_auth != ad_master_token:
                            debrid_db.auth_ad(settings_db)

                            chk_auth_pm = chk_auth_db.chk_auth(settings_db, "pm.token")
                            if chk_auth_pm not in ('empty_setting', '', None):
                                debrid_db.enable_pm(settings_db)
                            else:
                                debrid_db.disable_pm(settings_db)

                            chk_auth_rd = chk_auth_db.chk_auth(settings_db, "rd.token")
                            if chk_auth_rd not in ('empty_setting', '', None):
                                debrid_db.enable_rd(settings_db)
                            else:
                                debrid_db.disable_rd(settings_db)

                            xbmc.sleep(200)
                            remake_func()

            except Exception as e:
                log_utils.error(f"{addon_name} All-Debrid Failed: {e}")

        # ========================= a4kStreaming =========================
        try:
            if exists(var.chk_a4k):
                addon = xbmcaddon.Addon("plugin.video.a4kstreaming")
                if addon.getSetting("alldebrid.apikey") != ad_master_token:
                    addon.setSetting("alldebrid.apikey", your_ad_token)
        except Exception as e:
            log_utils.error(f"a4kStreaming alldebrid Failed: {e}")

        # ========================= Umbrella =========================
        try:
            if exists(var.chk_umb) and exists(var.chkset_umb):
                addon = xbmcaddon.Addon("plugin.video.umbrella")
                chk_auth = addon.getSetting("alldebridtoken")
                chk_auth_rd = addon.getSetting("realdebridtoken")
                chk_auth_pm = addon.getSetting("premiumizetoken")
                if chk_auth != ad_master_token:
                    for k, v in {
                        "alldebridusername": your_ad_username,
                        "alldebridtoken": your_ad_token,
                        "alldebrid.enable": "true",
                        "realdebrid.enable": "true" if chk_auth_rd else "false",
                        "premiumize.enable": "true" if chk_auth_pm else "false",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"Umbrella All-Debrid Failed: {e}")

        # ========================= POV =========================
        for addon_id, chk_addon, chk_settings, label, remake_settings in (
            ("plugin.video.pov", var.chk_pov, var.chkset_pov, "POV", control.remake_pov_settings),
        ):
            try:
                if exists(chk_addon) and exists(chk_settings):
                    addon = xbmcaddon.Addon(addon_id)

                    chk_auth    = addon.getSetting("ad.token")
                    chk_auth_rd = addon.getSetting("rd.token")
                    chk_auth_pm = addon.getSetting("pm.token")

                    if chk_auth != ad_master_token:
                        settings = {
                            "ad.account_id": your_ad_username,
                            "ad.token": your_ad_token,
                            "ad.enabled": "true",
                            "rd.enabled": "true" if chk_auth_rd else "false",
                            "pm.enabled": "true" if chk_auth_pm else "false",
                        }

                        for k, v in settings.items():
                            addon.setSetting(k, v)
                            
                        if remake_settings:
                            xbmc.sleep(200)
                            #remake_settings()

            except Exception as e:
                log_utils.error(f"{label} All-Debrid Failed: {e}")

        # =============== Dradis / Genocide ===============
        addons = [
            #("Dradis",   "plugin.video.dradis",   var.chk_dradis,   var.chkset_dradis),
            ("Genocide", "plugin.video.genocide", var.chk_genocide, var.chkset_genocide),
        ]

        for name, plugin, chk_addon, chk_setting in addons:
            try:
                if exists(chk_addon) and exists(chk_setting):
                    addon = xbmcaddon.Addon(plugin)
                    chk_auth = addon.getSetting("alldebrid.token")
                    if chk_auth != ad_master_token:
                        for k, v in {
                            "alldebrid.username": your_ad_username,
                            "alldebrid.token": your_ad_token,
                            "alldebrid.enable": "true",
                        }.items():
                            addon.setSetting(k, v)
            except Exception as e:
                log_utils.error(f"{name} All-Debrid Failed: {e}")

        # ================= Seren ===================
        for name, plugin, chk_addon, chk_setting in (
                ("Seren", "plugin.video.seren", var.chk_seren, var.chkset_seren),
        ):
                try:
                        if exists(chk_addon) and exists(chk_setting):
                                addon = xbmcaddon.Addon(plugin)
                                chk_auth = addon.getSetting("alldebrid.apikey")
                                chk_auth_rd = addon.getSetting("rd.auth")
                                chk_auth_pm = addon.getSetting("premiumize.token")
                                if chk_auth != ad_master_token:
                                        for k, v in {
                                                "alldebrid.username": your_ad_username,
                                                "alldebrid.apikey": your_ad_token,
                                                "alldebrid.premiumstatus": "Premium",
                                                "alldebrid.enabled": "true",
                                                "realdebrid.enabled": "true" if chk_auth_rd else "false",
                                                "premiumize.enabled": "true" if chk_auth_pm else "false",
                                        }.items():
                                                addon.setSetting(k, v)
                except Exception:
                        log_utils.error(f"{name} All-Debrid Failed")
            
        # ========================= luc_kodi =========================
        try:
            if exists(var.chk_luc) and exists(var.chkset_luc):
                addon = xbmcaddon.Addon("plugin.video.luc_kodi")
                chk_auth = addon.getSetting("alldebrid.token")
                if chk_auth != ad_master_token:
                    for k, v in {
                        "alldebrid.enable": "true",
                        "alldebrid.token": your_ad_token,
                        "alldebrid.username": your_ad_username,
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"luc_kodi All-Debrid Failed: {e}")

        # ================= Prism ===================
        for name, plugin, chk_addon, chk_setting in (
                ("Prism", "plugin.video.prism", var.chk_prism, var.chkset_prism),
        ):
                try:
                        if exists(chk_addon) and exists(chk_setting):
                                addon = xbmcaddon.Addon(plugin)
                                chk_auth = addon.getSetting("alldebrid.apikey")
                                chk_auth_rd = addon.getSetting("rd.auth")
                                chk_auth_pm = addon.getSetting("premiumize.token")
                                if chk_auth != ad_master_token:
                                        for k, v in {
                                                "alldebrid.username": your_ad_username,
                                                "alldebrid.apikey": your_ad_token,
                                                "alldebrid.premiumstatus": "Premium",
                                                "alldebrid.enabled": "true",
                                                "realdebrid.enabled": "true" if chk_auth_rd else "false",
                                                "premiumize.enabled": "true" if chk_auth_pm else "false",
                                        }.items():
                                                addon.setSetting(k, v)
                except Exception:
                        log_utils.error(f"{name} All-Debrid Failed")
            
        # =============== Shadow / Ghost / The Chains ===============
        addons = [
            ("Shadow",     "plugin.video.shadow",    var.chk_shadow,  var.shadow_ud,  var.chkset_shadow,  var.shadow),
            ("Ghost",      "plugin.video.ghost",     var.chk_ghost,   var.ghost_ud,   var.chkset_ghost,   var.ghost),
            ("The Chains", "plugin.video.thechains", var.chk_chains,  var.chains_ud,  var.chkset_chains,  var.chains),
        ]

        for name, plugin, chk_addon, ud_path, chk_setting, base_path in addons:
            try:
                if exists(chk_addon):
                    addon = xbmcaddon.Addon(plugin)
                    chk_auth = addon.getSetting("alldebrid.token")
                    chk_auth_rd = addon.getSetting("rd.auth")
                    chk_auth_pm = addon.getSetting("premiumize.token")
                    if chk_auth != ad_master_token:
                        for k, v in {
                            "debrid_use": "true",
                            "debrid_use_ad": "true",
                            "alldebrid.username": your_ad_username,
                            "alldebrid.token": your_ad_token,
                            "debrid_use_rd": "true" if chk_auth_rd else "false",
                            "debrid_use_pm": "true" if chk_auth_pm else "false",
                        }.items():
                            addon.setSetting(k, v)
            except Exception as e:
                log_utils.error(f"{name} All-Debrid Failed: {e}")

        # ========================= SALTS =========================
        try:
            if exists(var.chk_salts):
                addon = xbmcaddon.Addon("plugin.video.salts")
                chk_auth = addon.getSetting("alldebrid_token")
                if chk_auth != ad_master_token:
                    for k, v in {
                        "alldebrid_token": your_ad_token,
                        "alldebrid_enabled": "true",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"SALTS All-Debrid Failed: {e}")

        # ========================= Otaku =========================
        try:
            if exists(var.chk_otaku):
                addon = xbmcaddon.Addon("plugin.video.otaku")
                chk_auth = addon.getSetting("alldebrid.token")
                if chk_auth != ad_master_token:
                    for k, v in {
                        "alldebrid.username": your_ad_username,
                        "alldebrid.token": your_ad_token,
                        "alldebrid.enabled": "true",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"Otaku All-Debrid Failed: {e}")

        # ========================= ResolveURL =========================
        try:
            if exists(var.chk_rurl):
                addon = xbmcaddon.Addon("script.module.resolveurl")
                chk_auth = addon.getSetting("AllDebridResolver_token")
                if chk_auth != ad_master_token:
                    for k, v in {
                        "AllDebridResolver_token": your_ad_token,
                        "AllDebridResolver_cached_only": "true",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"ResolveURL All-Debrid Failed: {e}")
