# -*- coding: utf-8 -*-
import xbmc, xbmcaddon, xbmcgui
import xbmcvfs
import os

from acctmgr.modules import var
from acctmgr.modules import control
from acctmgr.modules import log_utils
from acctmgr.modules.db import chk_auth_db
from acctmgr.modules.db import offcloud_db

# Variables
exists = xbmcvfs.exists

class Auth:
    def offcloud_auth(self):

        # ========================= AM Lite Variables =========================
        acctmgr = xbmcaddon.Addon("script.module.acctmgr")
        your_username = acctmgr.getSetting("offcloud.userid")
        your_token = acctmgr.getSetting("offcloud.token")
        master_token = your_token

        # ========================= Red Light =========================
        try:
            if exists(var.chk_red):
                if not exists(var.chkset_red):
                    control.remake_red_settings()
                    xbmc.sleep(500)

                if exists(var.chkset_red):
                    settings_db = var.red_settings_db
                    chk_auth = chk_auth_db.chk_auth(settings_db, "oc.token")

                    if chk_auth != master_token:
                        offcloud_db.auth(settings_db)
                        xbmc.sleep(300)
                        control.remake_red_settings()
        except Exception as e:
            log_utils.error("Red Light OffCloud Failed")


        # ========================= Umbrella =========================
        try:
            if exists(var.chk_umb) and exists(var.chkset_umb):
                addon = xbmcaddon.Addon("plugin.video.umbrella")
                chk_auth = addon.getSetting("offcloudtoken")
                if chk_auth != master_token:
                    for k, v in {
                        "offcloud.username": your_username,
                        "offcloudtoken": your_token,
                        "offcloud.enable": "true",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error("Umbrella OffCloud Failed")

        # ========================= POV =========================
        try:
            if exists(var.chk_pov) and exists(var.chkset_pov):
                addon = xbmcaddon.Addon("plugin.video.pov")
                chk_auth = addon.getSetting("oc.token")
                if chk_auth != master_token:
                    for k, v in {
                        "oc.account_id": your_username,
                        "oc.token": your_token,
                        "oc.enabled": "true",
                    }.items():
                        addon.setSetting(k, v)
                    xbmc.sleep(200)
                    #control.remake_pov_settings
        except Exception as e:
            log_utils.error(f"POV OffCloud Failed: {e}")

        # ========================= Dradis / Genocide =========================
        addons = [
            #("Dradis",   "plugin.video.dradis",   var.chk_dradis,   var.chkset_dradis),
            ("Genocide", "plugin.video.genocide", var.chk_genocide, var.chkset_genocide),
        ]

        for name, plugin, chk_addon, chk_setting in addons:
            try:
                if exists(chk_addon) and exists(chk_setting):
                    addon = xbmcaddon.Addon(plugin)
                    chk_auth = addon.getSetting("offcloud.token")
                    if chk_auth != master_token:
                        for k, v in {
                            "offcloud.username": your_username,
                            "offcloud.token": your_token,
                            "offcloud.enabled": "true",
                        }.items():
                            addon.setSetting(k, v)
            except Exception as e:
                log_utils.error(f"{name} OffCloud Failed: {e}")
                
        # ========================= Prism =========================
        try:
            if exists(var.chk_prism) and exists(var.chkset_prism):
                addon = xbmcaddon.Addon("plugin.video.prism")
                chk_auth = addon.getSetting("oc.username")
                if chk_auth != your_username:
                    for k, v in {
                        "offcloud.enabled": "true",
                        "oc.token": your_token,
                        "oc.username": your_username,
                        "oc.premiumstatus": "Premium",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"Prism OffCloud Failed: {e}")
            
        # ========================= ResolveURL =========================
        try:
            if exists(var.chk_rurl):
                addon = xbmcaddon.Addon("script.module.resolveurl")
                chk_auth = addon.getSetting("OffCloudResolver_apikey")
                if chk_auth != master_token:
                    for k, v in {
                        "OffCloudResolver_apikey": your_token,
                        "OffCloudResolver_user": your_username,
                        "OffCloudResolver_enabled": "true",
                        "OffCloudResolver_cached_only": "true",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"ResolveURL TorBox Failed: {e}")

