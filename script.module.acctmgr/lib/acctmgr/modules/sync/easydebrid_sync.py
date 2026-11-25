# -*- coding: utf-8 -*-
import xbmc, xbmcaddon, xbmcgui, xbmcvfs
import os

from acctmgr.modules import var
from acctmgr.modules import control
from acctmgr.modules import log_utils
from acctmgr.modules.db import chk_auth_db
from acctmgr.modules.db import easydebrid_db

# Variables
exists = xbmcvfs.exists

class Auth:
    def easydebrid_auth(self):

        # ========================= AM Lite Variables =========================
        acctmgr = xbmcaddon.Addon("script.module.acctmgr")
        your_token = acctmgr.getSetting("easydebrid.token")
        your_acct_id = acctmgr.getSetting("easydebrid.acct_id")
        master_token = your_token

        # ========================= Fen Light =========================
        try:
            if exists(var.chk_fenlt):
                if not exists(var.chkset_fenlt):
                    control.remake_fenlt_settings()
                    xbmc.sleep(500)
                    
                if exists(var.chkset_fenlt):
                    settings_db = var.fenlt_settings_db
                    chk_auth = chk_auth_db.chk_auth(settings_db, "ed.token")

                    if chk_auth != master_token:
                        easydebrid_db.auth(settings_db)
                        xbmc.sleep(300)
                        control.remake_fenlt_settings()
        except Exception as e:
            log_utils.error(f"Fen Light Easy Debrid Failed: {e}")

        # ========================= Gears =========================
        try:
            if exists(var.chk_gears):
                if not exists(var.chkset_gears):
                    control.remake_gears_settings()
                    xbmc.sleep(500)
                if exists(var.chkset_fenlt):
                    settings_db = var.gears_settings_db
                    chk_auth = chk_auth_db.chk_auth(settings_db, "ed.token")

                    if chk_auth != master_token:
                        easydebrid_db.auth(settings_db)
                        xbmc.sleep(300)
                        control.remake_gears_settings()
        except Exception as e:
            log_utils.error(f"Gears Easy Debrid Failed: {e}")
            
        # ========================= Umbrella =========================
        try:
            if exists(var.chk_umb) and exists(var.chkset_umb):
                addon = xbmcaddon.Addon("plugin.video.umbrella")
                chk_auth = addon.getSetting("easydebridtoken")
                if chk_auth != master_token:
                    for k, v in {
                        "easydebridtoken": your_token,
                        "easydebrid.enable": "true",
                    }.items():
                        addon.setSetting(k, v)
        except Exception as e:
            log_utils.error(f"Umbrella Easy Debrid Failed: {e}")

        # ========================= POV =========================
        try:
            if exists(var.chk_pov) and exists(var.chkset_pov):
                addon = xbmcaddon.Addon("plugin.video.pov")
                chk_auth = addon.getSetting("ed.token")
                if chk_auth != master_token:
                    for k, v in {
                        "ed.token": your_token,
                        "ed.account_id": your_acct_id,
                        "ed.enabled": "true",
                    }.items():
                        addon.setSetting(k, v)
                    xbmc.sleep(200)
                    #control.remake_pov_settings
        except Exception as e:
            log_utils.error(f"POV Easy Debrid Failed: {e}")
