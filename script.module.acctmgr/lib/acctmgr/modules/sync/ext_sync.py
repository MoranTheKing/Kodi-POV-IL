# -*- coding: utf-8 -*-
import xbmc, xbmcaddon, xbmcvfs
import os

from acctmgr.modules import var
from acctmgr.modules import control
from acctmgr.modules import log_utils
from acctmgr.modules.db import ext_db
from acctmgr.modules.db import chk_auth_db

# Variables
exists = xbmcvfs.exists
char_remov = ["'", ",", ")", "("]

FEN_SUPPORTED_SCRAPERS = {var.coco_plugin_id,var.viper_plugin_id,}

def auth_external(scraper_id, display_sc_name, display_umb_name, chk_scraper, log_name):

    # ========================= Fen Light / The Gears / Red Light =========================
    addons = (
        ("Fen Light", var.chk_fenlt, var.chkset_fenlt, var.fenlt_settings_db, control.remake_fenlt_settings),
        ("Gears", var.chk_gears, var.chkset_gears, var.gears_settings_db, control.remake_gears_settings),
        ("Red Light", var.chk_red, var.chkset_red, var.red_settings_db, control.remake_red_settings),
    )

    for addon_name, chk_path, chkset_path, settings_db, remake_func in addons:
        try:
            if exists(chk_path) and exists(chk_scraper):

                if not exists(chkset_path):
                    remake_func()
                    xbmc.sleep(500)

                if exists(chkset_path):
                    chk_auth = chk_auth_db.chk_auth(settings_db, "external_scraper.module")

                    if chk_auth != scraper_id:
                        ext_db.auth(display_sc_name, scraper_id, settings_db)
                        xbmc.sleep(300)
                        remake_func()

        except Exception as e:
            log_utils.error(f"{addon_name} {log_name} External Provider Failed: {e}")

    '''# ========================= Fen =========================
    try:
        if (scraper_id in FEN_SUPPORTED_SCRAPERS and exists(var.chk_fen) and exists(var.chkset_fen) and exists(chk_scraper)):
            addon = xbmcaddon.Addon("plugin.video.fen")
            chk_auth = addon.getSetting("external_scraper.module")

            if chk_auth != scraper_id:
                for k, v in {
                    "provider.external": "true",
                    "external_scraper.name": display_sc_name,
                    "external_scraper.module": scraper_id,
                }.items():
                    addon.setSetting(k, v)
    except Exception:
        log_utils.error(f"Fen {log_name} External Provider Failed")'''

    # ========================= Umbrella =========================
    try:
        if exists(var.chk_umb) and exists(var.chkset_umb) and exists(chk_scraper):
            addon = xbmcaddon.Addon("plugin.video.umbrella")
            chk_auth = addon.getSetting("external_provider.module")
            if chk_auth != scraper_id:
                for k, v in {
                    "provider.external.enabled": "true",
                    "umbrella.externalWarning": "true",
                    "external_provider.name": display_umb_name,
                    "external_provider.module": scraper_id,
                }.items():
                    addon.setSetting(k, v)
    except Exception as e:
        log_utils.error(f"Umbrella {log_name} External Provider Failed: {e}")


# AUTH HELPERS
def Auth_Coco():
    auth_external(
        scraper_id=var.coco_plugin_id,
        display_sc_name=var.coco_sc_name,
        display_umb_name=var.coco_umb_name,
        chk_scraper=var.chk_sc_coco,
        log_name="CocoScrapers"
    )

def Auth_Gears():
    auth_external(
        scraper_id=var.gears_plugin_id,
        display_sc_name=var.gears_sc_name,
        display_umb_name=var.gears_umb_name,
        chk_scraper=var.chk_sc_gears,
        log_name="GearsScrapers"
    )

def Auth_Mag():
    auth_external(
        scraper_id=var.mag_plugin_id,
        display_sc_name=var.mag_sc_name,
        display_umb_name=var.mag_umb_name,
        chk_scraper=var.chk_sc_mag,
        log_name="Magneto Scrapers"
    )

def Auth_Viper():
    auth_external(
        scraper_id=var.viper_plugin_id,
        display_sc_name=var.viper_sc_name,
        display_umb_name=var.viper_umb_name,
        chk_scraper=var.chk_sc_viper,
        log_name="Viper Scrapers"
    )
