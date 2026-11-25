# -*- coding: utf-8 -*-
import xbmc
import xbmcaddon
import xbmcvfs
import os

from acctmgr.modules import var, control, log_utils
from acctmgr.modules.db import maxql_db

exists = xbmcvfs.exists
copy = xbmcvfs.copy
joinPath = os.path.join

class MaxQL:
    # QUALITY MAPS
    NUMERIC_QUALITY_MAP = {
        var.QL_UHD: '0',
        var.QL_HD:  '1',
        var.QL_SD:  '2',
    }
    FEN_QUALITY_MAP = {
        var.QL_UHD: 'SD, 720p, 1080p, 4K',
        var.QL_HD:  'SD, 720p, 1080p',
        var.QL_SD:  'SD, 720p',
    }
    SHADOW_QUALITY_MAP = {
        var.QL_UHD: '2',
        var.QL_HD:  '1',
        var.QL_SD:  '0',
    }
    OTAKU_QUALITY_MAP = {
        var.QL_UHD: '4',
        var.QL_HD:  '3',
        var.QL_SD:  '2',
    }
    CREW_QUALITY_MAP = {
        var.QL_UHD: '0',
        var.QL_HD:  '2',
        var.QL_SD:  '3',
    }
    SALTS_QUALITY_MAP = {
        var.QL_UHD: '4K',
        var.QL_HD:  '1080p',
        var.QL_SD:  '720p',
    }
    '''GENESIS_QUALITY_MAP = {
        var.QL_UHD: '2',
        var.QL_HD:  '0',
        var.QL_SD:  '1',
    }'''

    def set_res(self, mode):

        num_quality     = self.NUMERIC_QUALITY_MAP.get(mode)
        fen_quality     = self.FEN_QUALITY_MAP.get(mode)
        shadow_quality  = self.SHADOW_QUALITY_MAP.get(mode)
        otaku_quality   = self.OTAKU_QUALITY_MAP.get(mode)
        crew_quality    = self.CREW_QUALITY_MAP.get(mode)
        salts_quality    = self.SALTS_QUALITY_MAP.get(mode)
        #genesis_quality    = self.GENESIS_QUALITY_MAP.get(mode)

        if not all((num_quality, fen_quality, shadow_quality, otaku_quality, crew_quality, salts_quality)):
            log_utils.error(f"MaxQL: Invalid mode received: {mode}")
            return

        # ===================== Copy Addon Data (settings.xml) =====================
        addons = (
            ("Shadow",      var.chk_shadow, var.shadow_ud,  var.chkset_shadow,  var.shadow),
            ("Ghost",       var.chk_ghost,  var.ghost_ud,   var.chkset_ghost,   var.ghost),
            ("Homelander",  var.chk_home,   var.home_ud,    var.chkset_home,    var.home),
            ("Nightwing",   var.chk_night,  var.night_ud,   var.chkset_night,   var.night),
            ("Absolution",  var.chk_absol,  var.absol_ud,   var.chkset_absol,   var.absol),
            ("The Crew",    var.chk_crew,   var.crew_ud,    var.chkset_crew,    var.crew),
            ("SALTS",       var.chk_salts,  var.salts_ud,   var.chkset_salts,   var.salts),
            ("Scrubs V2",   var.chk_scrubs, var.scrubs_ud,  var.chkset_scrubs,  var.scrubs),
            ("Gratis Red",  var.chk_redg,   var.redg_ud,    var.chkset_redg,    var.redg),
            ("Otaku",       var.chk_otaku,  var.otaku_ud,   var.chkset_otaku,   var.otaku),
            ("a4kStreaming", var.chk_a4k, var.a4k_ud, var.chkset_a4k, var.a4k),
        )

        for name, chk_addon, ud_path, chk_setting, base_path in addons:
            control.copy_addon_settings(
                name,
                chk_addon,
                ud_path,
                chk_setting,
                base_path
            )

        # ======================= Fen Light / The Gears / Red Light =======================
        addons = (
            ("Fen Light", var.chk_fenlt, var.chkset_fenlt, control.remake_fenlt_settings),
            ("Gears", var.chk_gears, var.chkset_gears, control.remake_gears_settings),
            ("Red Light", var.chk_red, var.chkset_red, control.remake_red_settings),
        )

        for addon_name, chk_path, chkset_path, remake_func in addons:
            try:
                if exists(chk_path):

                    if not exists(chkset_path):
                        remake_func()
                        xbmc.sleep(500)

                    if exists(chkset_path):
                        maxql_db.apply_quality(mode)
                        xbmc.sleep(300)
                        remake_func()

            except Exception as e:
                log_utils.error(f"{addon_name} MaxQL Failed: {e}")


        # ===================== Umbrella ======================
        try:
            if exists(var.chk_umb) and exists(var.chkset_umb):
                xbmcaddon.Addon("plugin.video.umbrella").setSetting("hosts.quality", num_quality)
        except Exception as e:
            log_utils.error(f"Umbrella MaxQL Failed: {e}")


        # ===================== POV =====================
        for name, plugin, chk_addon, chk_setting, remake_settings in (
            ("POV", "plugin.video.pov", var.chk_pov, var.chkset_pov, control.remake_pov_settings),
        ):
            try:
                if exists(chk_addon) and exists(chk_setting):
                    addon = xbmcaddon.Addon(plugin)
                    addon.setSetting("results_quality_movie", fen_quality)
                    addon.setSetting("results_quality_episode", fen_quality)

                    if remake_settings:
                        xbmc.sleep(200)
                        #remake_settings()

            except Exception as e:
                log_utils.error(f"{name} MaxQL Failed: {e}")


        # ===================== Dradis / Genocide =====================
        for name, plugin, chk_addon, chk_setting in (
            #("Dradis",   "plugin.video.dradis",   var.chk_dradis,   var.chkset_dradis),
            ("Genocide", "plugin.video.genocide", var.chk_genocide, var.chkset_genocide),
        ):
            try:
                if exists(chk_addon) and exists(chk_setting):
                    xbmcaddon.Addon(plugin).setSetting("hosts.quality", num_quality)
            except Exception as e:
                log_utils.error(f"{name} MaxQL Failed: {e}")


        # ================= Seren ===================
        for name, plugin, chk_addon, chk_setting in (
                ("Seren", "plugin.video.seren", var.chk_seren, var.chkset_seren),
        ):
                try:
                        if exists(chk_addon) and exists(chk_setting):
                                xbmcaddon.Addon(plugin).setSetting("general.maxResolution", num_quality)
                except Exception as e:
                        log_utils.error(f"{name} MaxQL Failed: {e}")
            
        # ===================== luc_kodi =====================
        for name, plugin, chk_addon, chk_setting in (
            ("luc_kodi", "plugin.video.luc_kodi", var.chk_luc, var.chkset_luc),
        ):
            try:
                if exists(chk_addon) and exists(chk_setting):
                    xbmcaddon.Addon(plugin).setSetting("hosts.quality", num_quality)
            except Exception as e:
                log_utils.error(f"{name} MaxQL Failed: {e}")


        # ===================== a4kStreaming =====================
        try:
            if exists(var.chk_a4k):
                a4k_quality = {var.QL_UHD: '3', var.QL_HD: '2', var.QL_SD: '1'}.get(mode)
                if a4k_quality is not None:
                    xbmcaddon.Addon("plugin.video.a4kstreaming").setSetting("general.max_quality", a4k_quality)
        except Exception as e:
            log_utils.error(f"a4kStreaming MaxQL Failed: {e}")

        # ================= Prism ===================
        for name, plugin, chk_addon, chk_setting in (
                ("Prism", "plugin.video.prism", var.chk_prism, var.chkset_prism),
        ):
                try:
                        if exists(chk_addon) and exists(chk_setting):
                                xbmcaddon.Addon(plugin).setSetting("general.maxResolution", num_quality)
                except Exception as e:
                        log_utils.error(f"{name} MaxQL Failed: {e}")
            
        # ===================== Shadow / Ghost =====================
        for name, plugin, chk_addon, chk_setting in (
            ("Shadow", "plugin.video.shadow", var.chk_shadow, var.chkset_shadow),
            ("Ghost",  "plugin.video.ghost",  var.chk_ghost,  var.chkset_ghost),
        ):
            try:
                if exists(chk_addon) and exists(chk_setting):
                    addon = xbmcaddon.Addon(plugin)
                    addon.setSetting("max_q", shadow_quality)
                    addon.setSetting("max_q_tv", shadow_quality)
            except Exception as e:
                log_utils.error(f"{name} MaxQL Failed: {e}")


        # =========== Homelander / Nightwing / Jokers Absolution ===========
        for name, plugin, chk_addon, chk_setting in (
            ("Homelander",        "plugin.video.homelander", var.chk_home,  var.chkset_home),
            ("Nightwing",         "plugin.video.nightwing",  var.chk_night, var.chkset_night),
            ("Jokers Absolution", "plugin.video.absolution", var.chk_absol, var.chkset_absol),
        ):
            try:
                if exists(chk_addon) and exists(chk_setting):
                    xbmcaddon.Addon(plugin).setSetting("hosts.quality", num_quality)
            except Exception as e:
                log_utils.error(f"{name} MaxQL Failed: {e}")


        # ===================== The Crew =====================
        try:
            if exists(var.chk_crew) and exists(var.chkset_crew):
                xbmcaddon.Addon("plugin.video.thecrew").setSetting("quality.max", crew_quality)
        except Exception as e:
            log_utils.error(f"The Crew MaxQL Failed: {e}")


        # ===================== SALTS =====================
        try:
            if exists(var.chk_salts) and exists(var.chkset_salts):
                xbmcaddon.Addon("plugin.video.salts").setSetting("min_quality", salts_quality)
        except Exception as e:
            log_utils.error(f"SALTS MaxQL Failed: {e}")

        # ===================== Scrubs V2 =====================
        try:
            if exists(var.chk_scrubs) and exists(var.chkset_scrubs):
                xbmcaddon.Addon("plugin.video.scrubsv2").setSetting("quality.max", num_quality)
        except Exception as e:
            log_utils.error(f"Scrubs V2 MaxQL Failed: {e}")


        # ===================== Gratis Red =====================
        try:
            if exists(var.chk_redg) and exists(var.chkset_redg):
                xbmcaddon.Addon("plugin.video.gratisred").setSetting("quality.max", num_quality)
        except Exception as e:
            log_utils.error(f"Gratis Red MaxQL Failed: {e}")
        # ===================== Otaku =====================
        try:
            if exists(var.chk_otaku) and exists(var.chkset_otaku):
                xbmcaddon.Addon("plugin.video.otaku").setSetting("general.maxResolution", otaku_quality)
        except Exception as e:
            log_utils.error(f"Otaku MaxQL Failed: {e}")


