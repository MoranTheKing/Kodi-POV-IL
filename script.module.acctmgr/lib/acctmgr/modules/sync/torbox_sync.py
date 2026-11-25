# -*- coding: utf-8 -*-
import xbmc, xbmcaddon, xbmcgui, xbmcvfs
import os

from acctmgr.modules import var
from acctmgr.modules import control
from acctmgr.modules import log_utils
from acctmgr.modules.db import torbox_db
from acctmgr.modules.db import chk_auth_db
from acctmgr.modules.db import torbox_db

# Variables
joinPath = os.path.join
exists = xbmcvfs.exists

class Auth:
    def torbox_auth(self):

        # ========================= AM Lite Variables =========================
        acctmgr = xbmcaddon.Addon("script.module.acctmgr")
        your_token = acctmgr.getSetting("torbox.token")
        your_acct_id = acctmgr.getSetting("torbox.acct_id")
        your_username = acctmgr.getSetting("torbox.username")
        your_auth_status = acctmgr.getSetting("torbox.auth_status")
        your_expires = acctmgr.getSetting("torbox.auth_expires")
        master_token = your_token

        # =================== Copy Addon Data (settings.xml) ==================
        addons = [
            ("Shadow",        var.chk_shadow, var.shadow_ud,  var.chkset_shadow,  var.shadow),
            ("Ghost",         var.chk_ghost,  var.ghost_ud,   var.chkset_ghost,   var.ghost),
            ("The Chains",    var.chk_chains, var.chains_ud,  var.chkset_chains,  var.chains),
            ("SALTS",         var.chk_salts,  var.salts_ud,   var.chkset_salts,   var.salts),
            ("Otaku",         var.chk_otaku,  var.otaku_ud,   var.chkset_otaku,   var.otaku),
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
                        chk_auth = chk_auth_db.chk_auth(settings_db, "tb.token")

                        if chk_auth != master_token:
                            torbox_db.auth(settings_db)
                            xbmc.sleep(300)
                            remake_func()

            except Exception as e:
                log_utils.error(f"{addon_name} TorBox Failed: {e}")
            
        # ========================= Umbrella =========================
        try:
            if exists(var.chk_umb) and exists(var.chkset_umb):
                addon = xbmcaddon.Addon("plugin.video.umbrella")
                chk_auth = addon.getSetting("torboxtoken")
                if chk_auth != master_token:
                    for k, v in {
                        "torboxtoken": your_token,
                        "torbox.username": your_acct_id,
                        "torbox.enable": "true",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"Umbrella TorBox Failed: {e}")

        # ========================= POV =========================
        try:
            if exists(var.chk_pov) and exists(var.chkset_pov):
                addon = xbmcaddon.Addon("plugin.video.pov")
                chk_auth = addon.getSetting("tb.token")
                if chk_auth != master_token:
                    for k, v in {
                        "tb.token": your_token,
                        "tb.account_id": your_acct_id,
                        "tb.enabled": "true",
                        "tb.expires": "0",
                    }.items():
                        addon.setSetting(k, v)
                    xbmc.sleep(200)
                    #control.remake_pov_settings()
        except Exception as e:
            log_utils.error(f"POV TorBox Failed: {e}")

        # =============== Dradis / Genocide ===============
        addons = [
            #("Dradis",   "plugin.video.dradis",   var.chk_dradis,   var.chkset_dradis),
            ("Genocide", "plugin.video.genocide", var.chk_genocide, var.chkset_genocide),
        ]

        for name, plugin, chk_addon, chk_setting in addons:
            try:
                if exists(chk_addon) and exists(chk_setting):
                    addon = xbmcaddon.Addon(plugin)
                    chk_auth = addon.getSetting("torbox.token")
                    if chk_auth != master_token:
                        for k, v in {
                            "torbox.token": your_token,
                            "torbox.username": your_acct_id,
                            "torbox.enable": "true",
                            "torbox.expires": "0",
                        }.items():
                            addon.setSetting(k, v)
            except Exception as e:
                log_utils.error(f"{name} TorBox Failed: {e}")

        # ========================= luc_kodi =========================
        try:
            if exists(var.chk_luc) and exists(var.chkset_luc):
                addon = xbmcaddon.Addon("plugin.video.luc_kodi")
                chk_auth = addon.getSetting("torbox.token")
                if chk_auth != master_token:
                    for k, v in {
                        "torbox.enable": "true",
                        "torbox.token": your_token,
                        "torbox.username": your_acct_id,
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"luc_kodi TorBox Failed: {e}")

        # ========================= Prism =========================
        try:
            if exists(var.chk_prism) and exists(var.chkset_prism):
                addon = xbmcaddon.Addon("plugin.video.prism")
                chk_auth = addon.getSetting("tb.token")
                if chk_auth != your_acct_id:
                    for k, v in {
                        "torbox.enabled": "true",
                        "tb.token": your_token,
                        "tb.username": your_username,
                        "tb.premiumstatus": your_auth_status,
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"Prism TorBox Failed: {e}")

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
                    chk_auth = addon.getSetting("torbox.token")
                    if chk_auth != master_token:
                        for k, v in {
                            "tb.token": your_token,
                            "tb.account_id": your_acct_id,
                            "debrid_use": 'true',
                            "debrid_use_tr": 'true',
                        }.items():
                            addon.setSetting(k, v)
            except Exception as e:
                log_utils.error(f"{name} TorBox Failed: {e}")

        # ========================= SALTS =========================
        try:
            if exists(var.chk_salts):
                addon = xbmcaddon.Addon("plugin.video.salts")
                chk_auth = addon.getSetting("torbox_token")
                if chk_auth != master_token:
                    for k, v in {
                        "torbox_token": your_token,
                        "torbox_enabled": "true",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"SALTS TorBox Failed: {e}")

        # ========================= Otaku =========================
        try:
            if exists(var.chk_otaku):
                addon = xbmcaddon.Addon("plugin.video.otaku")
                chk_auth = addon.getSetting("torbox.token")
                if chk_auth != master_token:
                    for k, v in {
                        "torbox.username": your_acct_id,
                        "torbox.token": your_token,
                        "torbox.auth.status": your_auth_status,
                        "torbox.enabled": "true",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"Otaku TorBox Failed: {e}")

        # ========================= ResolveURL =========================
        try:
            if exists(var.chk_rurl):
                addon = xbmcaddon.Addon("script.module.resolveurl")
                chk_auth = addon.getSetting("TorBoxResolver_apikey")
                if chk_auth != master_token:
                    for k, v in {
                        "TorBoxResolver_apikey": your_token,
                        "TorBoxResolver_enabled": "true",
                        "TorBoxResolver_cached_only": "true",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"ResolveURL TorBox Failed: {e}")
