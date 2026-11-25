# -*- coding: utf-8 -*-
import xbmc
import xbmcaddon
import xbmcvfs
import os

from acctmgr.modules import var, control, log_utils
from acctmgr.modules.db import autoplay_db

exists = xbmcvfs.exists
copy = xbmcvfs.copy
joinPath = os.path.join

class AutoPlay:
    # Playback MAPS
    NUM_PLAYBACK_MAP = {
        var.DIR:  '1',
        var.AUTO: '2',
    }
    TF_PLAYBACK_MAP = {
        var.DIR: 'false',
        var.AUTO:  'true',
    }
    UMB_PLAYBACK_MAP = {
        var.DIR:  '0',
        var.AUTO:  '1',
    }
    OTAKU_PLAYBACK_MAP = {
        var.DIR: '1',
        var.AUTO:  '0',
    }

    def set_playback(self, mode):

        num_playback     = self.NUM_PLAYBACK_MAP.get(mode)
        tf_playback      = self.TF_PLAYBACK_MAP.get(mode)
        umb_playback   = self.UMB_PLAYBACK_MAP.get(mode)
        otaku_playback    = self.OTAKU_PLAYBACK_MAP.get(mode)

        if not all((num_playback, tf_playback, umb_playback, otaku_playback)):
            log_utils.error(f"Autoplay: Invalid mode received: {mode}")
            return

        # ===================== Copy Addon Data (settings.xml) =====================
        addons = (
            ("Homelander",  var.chk_home,   var.home_ud,    var.chkset_home,    var.home),
            ("Nightwing",   var.chk_night,  var.night_ud,   var.chkset_night,   var.night),
            ("Absolution",  var.chk_absol,  var.absol_ud,   var.chkset_absol,   var.absol),
            ("The Crew",    var.chk_crew,   var.crew_ud,    var.chkset_crew,    var.crew),
            ("SALTS",       var.chk_salts,  var.salts_ud,   var.chkset_salts,   var.salts),
            ("Scrubs V2",   var.chk_scrubs, var.scrubs_ud,  var.chkset_scrubs,  var.scrubs),
            ("Gratis Red",  var.chk_redg,   var.redg_ud,    var.chkset_redg,    var.redg),
            ("Otaku",       var.chk_otaku,  var.otaku_ud,   var.chkset_otaku,   var.otaku),
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
                        autoplay_db.apply_playback(mode)
                        xbmc.sleep(300)
                        remake_func()

            except Exception as e:
                log_utils.error(f"{addon_name} Autoplay Failed: {e}")

        # ===================== Umbrella ======================
        try:
            if exists(var.chk_umb) and exists(var.chkset_umb):
                xbmcaddon.Addon("plugin.video.umbrella").setSetting("play.mode.movie", umb_playback)
                xbmcaddon.Addon("plugin.video.umbrella").setSetting("play.mode.tv", umb_playback)
        except Exception as e:
            log_utils.error(f"Umbrella Autoplay Failed: {e}")

        # ===================== POV  =====================
        for name, plugin, chk_addon, chk_setting, remake_settings in (
            ("POV", "plugin.video.pov", var.chk_pov, var.chkset_pov, control.remake_pov_settings),
        ):
            try:
                if exists(chk_addon) and exists(chk_setting):
                    addon = xbmcaddon.Addon(plugin)
                    addon.setSetting("auto_play_movie", tf_playback)
                    addon.setSetting("auto_play_episode", tf_playback)

                    if remake_settings:
                        xbmc.sleep(200)
                        #remake_settings()

            except Exception as e:
                log_utils.error(f"{name} Autoplay Failed: {e}")

        # ================= Seren ===================
        for name, plugin, chk_addon, chk_setting in (
                ("Seren", "plugin.video.seren", var.chk_seren, var.chkset_seren),
        ):
                try:
                        if exists(chk_addon) and exists(chk_setting):
                                xbmcaddon.Addon(plugin).setSetting("general.playstyleMovie", otaku_playback)
                                xbmcaddon.Addon(plugin).setSetting("general.playstyleEpisodes", otaku_playback)
                except Exception as e:
                        log_utils.error(f"{name} Autoplay Failed: {e}")
            
        # ===================== luc_kodi ======================
        try:
            if exists(var.chk_luc) and exists(var.chkset_luc):
                xbmcaddon.Addon("plugin.video.luc_kodi").setSetting("play.mode", umb_playback)
        except Exception as e:
            log_utils.error(f"luc_kodi Autoplay Failed: {e}")

        # ===================== a4kStreaming =====================
        try:
            if exists(var.chk_a4k):
                xbmcaddon.Addon("plugin.video.a4kstreaming").setSetting("general.autoplay", tf_playback)
        except Exception as e:
            log_utils.error(f"a4kStreaming Autoplay Failed: {e}")

        # ================= Prism ===================
        for name, plugin, chk_addon, chk_setting in (
                ("Prism", "plugin.video.prism", var.chk_prism, var.chkset_prism),
        ):
                try:
                        if exists(chk_addon) and exists(chk_setting):
                                xbmcaddon.Addon(plugin).setSetting("general.playstyleMovie", otaku_playback)
                                xbmcaddon.Addon(plugin).setSetting("general.playstyleEpisodes", otaku_playback)
                except Exception as e:
                        log_utils.error(f"{name} Autoplay Failed: {e}")
            
        # =========== The Crew / Homelander / Nightwing / Jokers Absolution / Scrubs V2 / Gratis Red ===========
        for name, plugin, chk_addon, chk_setting in (
            ("Homelander",        "plugin.video.homelander", var.chk_home,  var.chkset_home),
            ("Nightwing",         "plugin.video.nightwing",  var.chk_night, var.chkset_night),
            ("Absolution",        "plugin.video.absolution", var.chk_absol, var.chkset_absol),
            ("The Crew",          "plugin.video.thecrew", var.chk_crew,  var.chkset_crew),
            ("Scrubs V2",         "plugin.video.scrubsv2", var.chk_scrubs,  var.chkset_scrubs),
            ("Gratis Red",        "plugin.video.gratisred", var.chk_redg,  var.chkset_redg),
        ):
            try:
                if exists(chk_addon) and exists(chk_setting):
                    xbmcaddon.Addon(plugin).setSetting("hosts.mode", num_playback)
            except Exception as e:
                log_utils.error(f"{name} Autoplay Failed: {e}")

        # ===================== SALTS =====================
        try:
            if exists(var.chk_salts) and exists(var.chkset_salts):
                xbmcaddon.Addon("plugin.video.salts").setSetting("auto_play", tf_playback)
        except Exception as e:
            log_utils.error(f"SALTS Autoplay Failed: {e}")

        # ===================== Otaku =====================
        try:
            if exists(var.chk_otaku) and exists(var.chkset_otaku):
                xbmcaddon.Addon("plugin.video.otaku").setSetting("general.playstyle.movie", otaku_playback)
        except Exception as e:
            log_utils.error(f"Otaku Autoplay Failed: {e}")
