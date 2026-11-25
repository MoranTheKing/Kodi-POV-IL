# -*- coding: utf-8 -*-
import xbmc, xbmcaddon, xbmcvfs
import os

from acctmgr.modules import control
from acctmgr.modules import var
from acctmgr.modules import log_utils
from acctmgr.modules.db import chk_auth_db
from acctmgr.modules.db import debrid_db

# Variables
joinPath = os.path.join
exists = xbmcvfs.exists

class Auth:
    def premiumize_auth(self):

        # ========================= AM Lite Variables =========================
        acctmgr = xbmcaddon.Addon("script.module.acctmgr")
        your_pm_username = acctmgr.getSetting("premiumize.username")
        your_pm_token = acctmgr.getSetting("premiumize.token")
        pm_master_token = your_pm_token

        # =================== Copy Addon Data (settings.xml) ==================
        addons = [
            ("Shadow",        var.chk_shadow, var.shadow_ud,  var.chkset_shadow,  var.shadow),
            ("Ghost",         var.chk_ghost,  var.ghost_ud,   var.chkset_ghost,   var.ghost),
            ("The Chains",    var.chk_chains, var.chains_ud,  var.chkset_chains,  var.chains),
            ("SALTS",         var.chk_salts,  var.salts_ud,   var.chkset_salts,   var.salts),
            ("Otaku",         var.chk_otaku,  var.otaku_ud,   var.chkset_otaku,   var.otaku),
            ("a4kStreaming", var.chk_a4k, var.a4k_ud, var.chkset_a4k, var.a4k),
            ("ResolveURL",    var.chk_rurl,   var.rurl_ud,    var.chkset_rurl,    var.rurl),
            ("Realizer",      var.chk_realx,  var.realx_ud,   var.chkset_realx,   var.realx),
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
                        chk_auth = chk_auth_db.chk_auth(settings_db, "pm.token")

                        if chk_auth != pm_master_token:
                            debrid_db.auth_pm(settings_db)

                            chk_auth_rd = chk_auth_db.chk_auth(settings_db, "rd.token")
                            if chk_auth_rd not in ('empty_setting', '', None):
                                debrid_db.enable_rd(settings_db)
                            else:
                                debrid_db.disable_rd(settings_db)

                            chk_auth_ad = chk_auth_db.chk_auth(settings_db, "ad.token")
                            if chk_auth_ad not in ('empty_setting', '', None):
                                debrid_db.enable_ad(settings_db)
                            else:
                                debrid_db.disable_ad(settings_db)

                            xbmc.sleep(200)
                            remake_func()

            except Exception as e:
                log_utils.error(f"{addon_name} Premiumize Failed: {e}")
            
        # ========================= a4kStreaming =========================
        try:
            if exists(var.chk_a4k):
                addon = xbmcaddon.Addon("plugin.video.a4kstreaming")
                if addon.getSetting("premiumize.apikey") != pm_master_token:
                    addon.setSetting("premiumize.apikey", your_pm_token)
        except Exception as e:
            log_utils.error(f"a4kStreaming premiumize Failed: {e}")

        # ========================= Umbrella =========================
        try:
            if exists(var.chk_umb) and exists(var.chkset_umb):
                addon = xbmcaddon.Addon("plugin.video.umbrella")
                chk_auth = addon.getSetting("premiumizetoken")
                chk_auth_rd = addon.getSetting("realdebridtoken")
                chk_auth_ad = addon.getSetting("alldebridtoken")
                if chk_auth != pm_master_token:
                    for k, v in {
                        "premiumizeusername": your_pm_username,
                        "premiumizetoken": your_pm_token,
                        "premiumize.enable": "true",
                        "realdebrid.enable": "true" if chk_auth_rd else "false",
                        "alldebrid.enable": "true" if chk_auth_ad else "false",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"Umbrella Premiumize Failed: {e}")
            
        # ========================= POV  =========================
        for addon_id, chk_addon, chk_settings, label, remake_settings in (
            ("plugin.video.pov",        var.chk_pov,  var.chkset_pov,  "POV", control.remake_pov_settings),
        ):
            try:
                if exists(chk_addon) and exists(chk_settings):
                    addon = xbmcaddon.Addon(addon_id)

                    chk_auth_pm = addon.getSetting("pm.token")
                    chk_auth_rd = addon.getSetting("rd.token")
                    chk_auth_ad = addon.getSetting("ad.token")

                    if chk_auth_pm != pm_master_token:
                        settings = {
                            "pm.account_id": your_pm_username,
                            "pm.token": your_pm_token,
                            "pm.enabled": "true",
                            "rd.enabled": "true" if chk_auth_rd else "false",
                            "ad.enabled": "true" if chk_auth_ad else "false",
                        }

                        for k, v in settings.items():
                            addon.setSetting(k, v)
                        if remake_settings:
                            xbmc.sleep(200)
                            #remake_settings()

            except Exception as e:
                log_utils.error(f"{label} Premiumize Failed: {e}")

        # =============== Dradis / Genocide ===============
        addons = [
            #("Dradis",   "plugin.video.dradis",   var.chk_dradis,   var.chkset_dradis),
            ("Genocide", "plugin.video.genocide", var.chk_genocide, var.chkset_genocide),
        ]

        for name, plugin, chk_addon, chk_setting in addons:
            try:
                if exists(chk_addon) and exists(chk_setting):
                    addon = xbmcaddon.Addon(plugin)
                    chk_auth = addon.getSetting("premiumize.token")
                    if chk_auth != pm_master_token:
                        for k, v in {
                            "premiumize.username": your_pm_username,
                            "premiumize.token": your_pm_token,
                            "premiumize.enable": "true",
                        }.items():
                            addon.setSetting(k, v)
            except Exception as e:
                log_utils.error(f"{name} Premiumize Failed: {e}")

        # ================= Seren ===================
        for name, plugin, chk_addon, chk_setting in (
                ("Seren", "plugin.video.seren", var.chk_seren, var.chkset_seren),
        ):
                try:
                        if exists(chk_addon) and exists(chk_setting):
                                addon = xbmcaddon.Addon(plugin)
                                chk_auth = addon.getSetting("premiumize.token")
                                chk_auth_rd = addon.getSetting("rd.auth")
                                chk_auth_ad = addon.getSetting("alldebrid.apikey")
                                if chk_auth != pm_master_token:
                                        for k, v in {
                                                "premiumize.username": your_pm_username,
                                                "premiumize.token": your_pm_token,
                                                "premiumize.premiumstatus": "Premium",
                                                "premiumize.enabled": "true",
                                                "realdebrid.enabled": "true" if chk_auth_rd else "false",
                                                "alldebrid.enabled": "true" if chk_auth_ad else "false",
                                        }.items():
                                                addon.setSetting(k, v)
                except Exception as e:
                        log_utils.error(f"{name} Premiumize Failed")
            
        # ========================= luc_kodi =========================
        try:
            if exists(var.chk_luc) and exists(var.chkset_luc):
                addon = xbmcaddon.Addon("plugin.video.luc_kodi")
                chk_auth = addon.getSetting("premiumize.token")
                if chk_auth != pm_master_token:
                    for k, v in {
                        "premiumize.enable": "true",
                        "premiumize.token": your_pm_token,
                        "premiumize.username": your_pm_username,
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"luc_kodi Premiumize Failed: {e}")

        # ================= Prism ===================
        for name, plugin, chk_addon, chk_setting in (
                ("Prism", "plugin.video.prism", var.chk_prism, var.chkset_prism),
        ):
                try:
                        if exists(chk_addon) and exists(chk_setting):
                                addon = xbmcaddon.Addon(plugin)
                                chk_auth = addon.getSetting("premiumize.token")
                                chk_auth_rd = addon.getSetting("rd.auth")
                                chk_auth_ad = addon.getSetting("alldebrid.apikey")
                                if chk_auth != pm_master_token:
                                        for k, v in {
                                                "premiumize.username": your_pm_username,
                                                "premiumize.token": your_pm_token,
                                                "premiumize.premiumstatus": "Premium",
                                                "premiumize.enabled": "true",
                                                "realdebrid.enabled": "true" if chk_auth_rd else "false",
                                                "alldebrid.enabled": "true" if chk_auth_ad else "false",
                                        }.items():
                                                addon.setSetting(k, v)
                except Exception as e:
                        log_utils.error(f"{name} Premiumize Failed")
            
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
                    chk_auth = addon.getSetting("premiumize.token")
                    chk_auth_rd = addon.getSetting("rd.auth")
                    chk_auth_ad = addon.getSetting("alldebrid.token")
                    if chk_auth != pm_master_token:
                        for k, v in {
                            "debrid_use": "true",
                            "debrid_use_pm": "true",
                            "premiumize.token": your_pm_token,
                            "debrid_use_rd": "true" if chk_auth_rd else "false",
                            "debrid_use_ad": "true" if chk_auth_ad else "false",
                        }.items():
                            addon.setSetting(k, v)
            except Exception as e:
                log_utils.error(f"{name} Premiumize Failed: {e}")

        # ========================= SALTS =========================
        try:
            if exists(var.chk_salts):
                addon = xbmcaddon.Addon("plugin.video.salts")
                chk_auth = addon.getSetting("premiumize_token")
                if chk_auth != pm_master_token:
                    for k, v in {
                        "premiumize_token": your_pm_token,
                        "premiumize_enabled": "true",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"SALTS Premiumize Failed: {e}")

        # ========================= Otaku =========================
        try:
            if exists(var.chk_otaku):
                addon = xbmcaddon.Addon("plugin.video.otaku")
                chk_auth = addon.getSetting("premiumize.token")
                if chk_auth != pm_master_token:
                    for k, v in {
                        "premiumize.username": your_pm_username,
                        "premiumize.token": your_pm_token,
                        "premiumize.enabled": "true",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"Otaku Premiumize Failed: {e}")

        # ========================= ResolveURL =========================
        try:
            if exists(var.chk_rurl):
                addon = xbmcaddon.Addon("script.module.resolveurl")
                chk_auth = addon.getSetting("PremiumizeMeResolver_token")
                if chk_auth != pm_master_token:
                    for k, v in {
                        "PremiumizeMeResolver_token": your_pm_token,
                        "PremiumizeMeResolver_cached_only": "true",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"ResolveURL Premiumize Failed: {e}")
        # ========================= Premiumizer =========================
        try:
            if exists(var.chk_premx):
                addon = xbmcaddon.Addon("plugin.video.premiumizerx")
                chk_auth = addon.getSetting("premiumize.token")
                if chk_auth != pm_master_token:
                    for k, v in {
                        "premiumize.status": "Authorized",
                        "premiumize.token": your_pm_token,
                        "premiumize.refresh": "315360000",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"Premiumizer Auth Failed: {e}")

