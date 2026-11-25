# -*- coding: utf-8 -*-
import xbmc, xbmcaddon, xbmcgui
import xbmcvfs
import os

from acctmgr.modules import var
from acctmgr.modules import control
from acctmgr.modules import log_utils
from acctmgr.modules.db import chk_auth_db
from acctmgr.modules.db import easynews_db

# Variables
exists = xbmcvfs.exists

class Auth:
    def easynews_auth(self):

        # ========================= AM Lite Variables =========================
        acctmgr = xbmcaddon.Addon("script.module.acctmgr")
        your_username = acctmgr.getSetting("easynews.username")
        your_password = acctmgr.getSetting("easynews.password")
        master_user = your_username
        master_pass = your_password

        # =================== Copy Addon Data (settings.xml) ==================
        addons = [
            ("The Crew",       var.chk_crew,   var.crew_ud,    var.chkset_crew,    var.crew),
            ("Otaku",          var.chk_otaku,  var.otaku_ud,   var.chkset_otaku,   var.otaku),
            ("Easynews Video", var.chk_easyv,  var.easyv_ud,  var.chkset_easyv,  var.easyv),
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
            ("The Gears", var.chk_gears, var.chkset_gears, var.gears_settings_db, control.remake_gears_settings),
            ("Red Light", var.chk_red, var.chkset_red, var.red_settings_db, control.remake_red_settings),
        )

        for addon_name, chk_path, chkset_path, settings_db, remake_func in addons:
            try:
                if exists(chk_path):

                    if not exists(chkset_path):
                        remake_func()
                        xbmc.sleep(500)

                    if exists(chkset_path):
                        chk_auth_user = chk_auth_db.chk_auth(settings_db, "easynews_user")
                        chk_auth_pass = chk_auth_db.chk_auth(settings_db, "easynews_password")

                        if chk_auth_user != master_user or chk_auth_pass != master_pass:
                            easynews_db.auth(settings_db)
                            xbmc.sleep(300)
                            remake_func()

            except Exception as e:
                log_utils.error(f"{addon_name} Easynews Failed: {e}")

        # ========================= Umbrella =========================
        try:
            if exists(var.chk_umb) and exists(var.chkset_umb):
                addon = xbmcaddon.Addon("plugin.video.umbrella")
                chk_auth_user = addon.getSetting("easynews.user")
                chk_auth_pass = addon.getSetting("easynews.password")
                if chk_auth_user != master_user or chk_auth_pass != master_pass:
                    for k, v in {
                        "easynews.user": your_username,
                        "easynews.password": your_password,
                        "easynews.enable": "true",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"Umbrella Easynews Failed: {e}")

        # ========================= POV =========================
        for addon_id, chk_addon, chk_settings, label, remake_settings in (
            ("plugin.video.pov", var.chk_pov, var.chkset_pov, "POV", control.remake_pov_settings),
        ):
            try:
                if exists(chk_addon) and exists(chk_settings):
                    addon = xbmcaddon.Addon(addon_id)

                    chk_auth_user = addon.getSetting("easynews_user")
                    chk_auth_pass = addon.getSetting("easynews_password")

                    if chk_auth_user != master_user or chk_auth_pass != master_pass:
                        settings = {
                            "easynews_user":     your_username,
                            "easynews_password": your_password,
                            "provider.easynews": "true",
                        }

                        for k, v in settings.items():
                            addon.setSetting(k, v)

                        if remake_settings:
                            xbmc.sleep(200)
                            #remake_settings()

            except Exception as e:
                log_utils.error(f"{label} Easynews Failed: {e}")

        # ========================= Dradis / Genocide =========================
        addons = [
            #("Dradis",   "plugin.video.dradis",   var.chk_dradis,   var.chkset_dradis),
            ("Genocide", "plugin.video.genocide", var.chk_genocide, var.chkset_genocide),
        ]

        for name, plugin, chk_addon, chk_setting in addons:
            try:
                if exists(chk_addon) and exists(chk_setting):
                    addon = xbmcaddon.Addon(plugin)
                    chk_auth_user = addon.getSetting("easynews.username")
                    chk_auth_pass = addon.getSetting("easynews.password")
                    if chk_auth_user != master_user or chk_auth_pass != master_pass:
                        for k, v in {
                            "easynews_user": your_username,
                            "easynews_password": your_password,
                            "provider.easynews": "true",
                        }.items():
                            addon.setSetting(k, v)
            except Exception as e:
                log_utils.error(f"{name} Easynews Failed: {e}")

        # ========================= luc_kodi =========================
        try:
            if exists(var.chk_luc) and exists(var.chkset_luc):
                addon = xbmcaddon.Addon("plugin.video.luc_kodi")
                chk_auth_user = addon.getSetting("easynews.username")
                chk_auth_pass = addon.getSetting("easynews.password")
                if chk_auth_user != master_user or chk_auth_pass != master_pass:
                    for k, v in {
                        "provider.easynews": "true",
                        "easynews.username": your_username,
                        "easynews.password": your_password,
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"luc_kodi Easynews Failed: {e}")

        # ========================= The Crew =========================
        try:
            if exists(var.chk_crew) and exists(var.chkset_crew):
                addon = xbmcaddon.Addon("plugin.video.thecrew")
                chk_auth_user = addon.getSetting("easynews.user")
                chk_auth_pass = addon.getSetting("easynews.password")
                if chk_auth_user != master_user or chk_auth_pass != master_pass:
                    for k, v in {
                        "easynews.user": your_username,
                        "easynews.password": your_password,
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"The Crew Easynews Failed: {e}")

        # ========================= Otaku =========================
        try:
            if exists(var.chk_otaku) and exists(var.chkset_otaku):
                addon = xbmcaddon.Addon("plugin.video.otaku")
                chk_auth_user = addon.getSetting("easynews.user")
                chk_auth_pass = addon.getSetting("easynews.password")
                if chk_auth_user != master_user or chk_auth_pass != master_pass:
                    for k, v in {
                        "easynews.user": your_username,
                        "easynews.password": your_password,
                        "easynews.enabled": "true",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"Otaku Easynews Failed: {e}")

        # ========================= Easynews Video =========================
        try:
            if exists(var.chk_easyv) and exists(var.chkset_easyv):
                addon = xbmcaddon.Addon("plugin.video.easynewsx")
                chk_auth_user = addon.getSetting("general.username")
                chk_auth_pass = addon.getSetting("general.password")
                if chk_auth_user != master_user or chk_auth_pass != master_pass:
                    for k, v in {
                        "general.username": your_username,
                        "general.password": your_password,
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"Easynews Video Addon Failed: {e}")
