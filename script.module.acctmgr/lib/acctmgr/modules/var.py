import xbmc, xbmcaddon, xbmcvfs, os
from acctmgr.modules import obfuscation

amgr = 'AM Lite ERROR'
addon_id = 'script.module.acctmgr'
addon = xbmcaddon.Addon(addon_id)
translatePath = xbmcvfs.translatePath
addons = translatePath('special://home/addons/')
addon_data = translatePath('special://profile/addon_data/')
xmls = addons + translatePath('script.module.acctmgr/resources/xmls/')

# AM Lite - Trakt API Keys
client_am_obs = [33, 39, 117, 118, 119, 117, 36, 39, 115, 39, 118, 112, 36, 114, 123, 123, 115, 123, 32, 119, 117, 115, 117, 115, 39, 123, 115, 123, 116, 115, 114, 123, 117, 115, 117, 118, 117, 118, 32, 35, 38, 119, 32, 115, 113, 32, 112, 35, 117, 114, 123, 119, 123, 35, 39, 36, 112, 36, 122, 39, 119, 116, 112, 118]
secret_am_obs = [114, 114, 118, 38, 116, 118, 115, 33, 113, 119, 115, 117, 122, 33, 117, 38, 113, 33, 119, 117, 123, 122, 113, 115, 113, 123, 115, 123, 32, 39, 33, 115, 122, 115, 39, 123, 35, 115, 116, 112, 32, 33, 122, 118, 36, 115, 116, 35, 112, 39, 117, 122, 38, 33, 122, 112, 35, 113, 117, 115, 119, 114, 38, 32]
client_am_obs_str = '[33, 39, 117, 118, 119, 117, 36, 39, 115, 39, 118, 112, 36, 114, 123, 123, 115, 123, 32, 119, 117, 115, 117, 115, 39, 123, 115, 123, 116, 115, 114, 123, 117, 115, 117, 118, 117, 118, 32, 35, 38, 119, 32, 115, 113, 32, 112, 35, 117, 114, 123, 119, 123, 35, 39, 36, 112, 36, 122, 39, 119, 116, 112, 118]'
secret_am_obs_str = '[114, 114, 118, 38, 116, 118, 115, 33, 113, 119, 115, 117, 122, 33, 117, 38, 113, 33, 119, 117, 123, 122, 113, 115, 113, 123, 115, 123, 32, 39, 33, 115, 122, 115, 39, 123, 35, 115, 116, 112, 32, 33, 122, 118, 36, 115, 116, 35, 112, 39, 117, 122, 38, 33, 122, 112, 35, 113, 117, 115, 119, 114, 38, 32]'
client_am_x = 'Nw5cdEtZG14JXAhpGlgEOiQ9Rnh5cBkgGBE5MSV8fmphBjEyGCvt/75uvmoL5wXTFQQcWl2krckC+jHSFARCQw=='
secret_am_x = 'ZFlTJEhcQFgLDA0WLBUGASYDdXp/ex0gLhE5MQmwsWJuBu85xiQ5Lri8UGnGNgHTEPMeWaiqWD3xCTIeFBqQkQ=='
client_am = obfuscation.deobfuscate(client_am_obs)
secret_am = obfuscation.deobfuscate(secret_am_obs)

# Fen Light Database Paths
fenlt_path = addon_data + translatePath('plugin.video.fenlight/databases/')
fenlt_settings_db = fenlt_path + translatePath('settings.db')

# Gears Database Paths
gears_path = addon_data + translatePath('plugin.video.gears/databases/')
gears_settings_db = gears_path + translatePath('settings.db')

# Red Light Database Paths
red_path = addon_data + translatePath('plugin.video.redlight/databases/')
red_settings_db = red_path + translatePath('settings.db')

# Remake Settings & Trakt Cache Variables
fenlt_name = 'Fen Light'
fenlt_id = 'plugin.video.fenlight'
gears_name = 'The Gears'
gears_id = 'plugin.video.gears'
red_name = 'Red Light'
red_id = 'plugin.video.redlight'
fen_name = 'Fen'
fen_id = 'plugin.video.fen'
coal_name = 'The Coalition'
coal_id = 'plugin.video.coalition'

# Trakt Sync List Paths
acctmgr_datapath = translatePath('special://profile/addon_data/script.module.acctmgr/')
tk_sync_list = translatePath(os.path.join(acctmgr_datapath, 'trakt_sync_list.json'))

# Realizer Paths
realx_path = addon_data + translatePath('plugin.video.realizerx')
realx_json_path = realx_path + translatePath('rdauth.json')

# Skin Setting Paths
path_fentastic = addon_data + translatePath('skin.fentastic/settings.xml')
path_nimbus = addon_data + translatePath('skin.nimbus/settings.xml')

# External Scraper Root Paths
chk_sc_coco = addons + translatePath('script.module.cocoscrapers/')
chk_sc_gears = addons + translatePath('script.module.gearsscrapers/')
chk_sc_mag = addons + translatePath('script.module.magneto/')
chk_sc_viper = addons + translatePath('script.module.viperscrapers/')

# External Scraper Repo ID's
coco = 'repository.cocoscrapers'
mag = 'repository.kodifitzwell'
gears = 'repository.chainsrepo'
viper = 'repository.oldsalt'

# External Scraper Plugin ID's
coco_plugin_id = 'script.module.cocoscrapers'
gears_plugin_id = 'script.module.gearsscrapers'
mag_plugin_id = 'script.module.magneto'
viper_plugin_id = 'script.module.viperscrapers'

# External Scraper Names (Fen Light/Fen & Forks)
coco_sc_name = 'CocoScrapers Module'
gears_sc_name = 'Gears Scrapers'
mag_sc_name = 'Magneto Module'
viper_sc_name = 'Viper Scrapers'

# External Scraper Names (Umbrella & Forks)
coco_umb_name = 'cocoscrapers'
gears_umb_name = 'gearsscrapers'
mag_umb_name = 'magneto'
viper_umb_name = 'viperscrapers'

# MaxQL Variables
QL_UHD = "uhd"
QL_HD  = "hd"
QL_SD  = "sd"

# Autoplay Variables
DIR = "dir"
AUTO  = "auto"


#================================= ADD-ON ROOT PATHS =================================
# Fen Light & Forks
chk_fenlt = addons + translatePath('plugin.video.fenlight/')#--------------Fen Light
chk_gears = addons + translatePath('plugin.video.gears/')#-----------------Fork / Gears
chk_red = addons + translatePath('plugin.video.redlight/')#----------------Fork / Red Light
# Uniques
chk_umb = addons + translatePath('plugin.video.umbrella/')#----------------Umbrella
chk_seren = addons + translatePath('plugin.video.seren/')#-----------------Seren
chk_prism = addons + translatePath('plugin.video.prism/')#-----------------Prism
chk_madtitan = addons + translatePath('plugin.video.madtitansports/')
chk_a4k = addons + translatePath('plugin.video.a4kstreaming/')
chk_luc = addons + translatePath('plugin.video.luc_kodi/')#----------------luc_kodi
# Fen & Forks
chk_fen = addons + translatePath('plugin.video.fen/')#---------------------Fen
chk_pov = addons + translatePath('plugin.video.pov/')#---------------------Fork / POV
chk_coal = addons + translatePath('plugin.video.coalition/')#--------------Fork / Coalition
# Dradis & Forks
chk_dradis = addons + translatePath('plugin.video.dradis/')#---------------Dradis
chk_genocide = addons + translatePath('plugin.video.genocide/')#-----------Fork / Genocide
# Shadow & Forks
chk_shadow = addons + translatePath('plugin.video.shadow/')#---------------Shadow
chk_ghost = addons + translatePath('plugin.video.ghost/')#-----------------Fork / Ghost
chk_chains = addons + translatePath('plugin.video.thechains/')#------------Fork / The Chains
# Homelander & Forks
chk_home = addons + translatePath('plugin.video.homelander/')#-------------Homelander
chk_night = addons + translatePath('plugin.video.nightwing/')#-------------Fork / Nightwing
chk_absol = addons + translatePath('plugin.video.absolution/')#------------Fork / Jokers Absolution
# Scrubs V2 & Forks
chk_scrubs = addons + translatePath('plugin.video.scrubsv2/')#-------------Scrubs V2
chk_redg = addons + translatePath('plugin.video.gratisred/')#--------------Fork / Gratis Red
# Others
chk_crew = addons + translatePath('plugin.video.thecrew/')#----------------The Crew
chk_salts = addons + translatePath('plugin.video.salts/')#-----------------SALTS
chk_otaku = addons + translatePath('plugin.video.otaku/')#-----------------Otaku
chk_tmdbh = addons + translatePath('plugin.video.themoviedb.helper/')#-----TMDb Helper
chk_tmdbh_trakt_provider = addons + translatePath('script.module.tmdbhelper.sync.trakt/')
chk_easyv = addons + translatePath('plugin.video.easynewsx/')#-------------Easynews Video
chk_trakt = addons + translatePath('script.trakt/')#-----------------------Trakt
# Debrid Only
chk_realx = addons + translatePath('plugin.video.realizerx/')#-------------Realizer
chk_premx = addons + translatePath('plugin.video.premiumizerx/')#----------Premiumizer
chk_rurl= addons + translatePath('script.module.resolveurl/')#-------------ResolveURL
# Skins
chk_fentastic = addons + translatePath('skin.fentastic/')#-----------------FENtastic
chk_nimbus = addons + translatePath('skin.nimbus/')#-----------------------Nimbus


#============================= USERDATA PATHS =============================
# Uniques
umb_ud = addon_data + translatePath('plugin.video.umbrella/')
seren_ud = addon_data + translatePath('plugin.video.seren/')
prism_ud = addon_data + translatePath('plugin.video.prism/')
madtitan_ud = addon_data + translatePath('plugin.video.madtitansports/')
madtitan = addons + translatePath('plugin.video.madtitansports/')
a4k_ud = addon_data + translatePath('plugin.video.a4kstreaming/')
a4k = addons + translatePath('plugin.video.a4kstreaming/')
luc_ud = addon_data + translatePath('plugin.video.luc_kodi/')
# Fen & Forks
fen_ud = addon_data + translatePath('plugin.video.fen/')
pov_ud = addon_data + translatePath('plugin.video.pov/')
coal_ud = addon_data + translatePath('plugin.video.coalition/')
# Dradis & Forks
dradis_ud = addon_data + translatePath('plugin.video.dradis/')
gears_ud = addon_data + translatePath('plugin.video.gears/')
genocide_ud = addon_data + translatePath('plugin.video.genocide/')
# Shadow & Forks
shadow_ud = addon_data + translatePath('plugin.video.shadow/')
ghost_ud = addon_data + translatePath('plugin.video.ghost/')
chains_ud = addon_data + translatePath('plugin.video.thechains/')
# Homelander & Forks
home_ud = addon_data + translatePath('plugin.video.homelander/')
night_ud = addon_data + translatePath('plugin.video.nightwing/')
absol_ud = addon_data + translatePath('plugin.video.absolution/')
# Scrubs V2 & Forks
scrubs_ud = addon_data + translatePath('plugin.video.scrubsv2/')
redg_ud = addon_data + translatePath('plugin.video.gratisred/')
# Others
crew_ud = addon_data + translatePath('plugin.video.thecrew/')
salts_ud = addon_data + translatePath('plugin.video.salts/')
otaku_ud = addon_data + translatePath('plugin.video.otaku/')
tmdbh_ud = addon_data + translatePath('plugin.video.themoviedb.helper/')
tmdbh_trakt_provider_ud = addon_data + translatePath('script.module.tmdbhelper.sync.trakt/')
easyv_ud = addon_data + translatePath('plugin.video.easynewsx/')
trakt_ud = addon_data + translatePath('script.trakt/')
# Debrid Only
realx_ud = addon_data + translatePath('plugin.video.realizerx/')
premx_ud = addon_data + translatePath('plugin.video.premiumizerx/')
rurl_ud = addon_data + translatePath('script.module.resolveurl/')


#================================= SETTING PATHS =================================
chkset_amlite = addon_data + translatePath('script.module.acctmgr/settings.xml')
# Fen Light & Forks
chkset_fenlt = addon_data + translatePath('plugin.video.fenlight/databases/settings.db')
chkset_gears = addon_data + translatePath('plugin.video.gears/databases/settings.db')
chkset_red = addon_data + translatePath('plugin.video.redlight/databases/settings.db')
# Uniques
chkset_umb = addon_data + translatePath('plugin.video.umbrella/settings.xml')
chkset_seren = addon_data + translatePath('plugin.video.seren/settings.xml')
chkset_prism = addon_data + translatePath('plugin.video.prism/settings.xml')
chkset_madtitan = addon_data + translatePath('plugin.video.madtitansports/settings.xml')
chkset_a4k = addon_data + translatePath('plugin.video.a4kstreaming/settings.xml')
chkset_luc = addon_data + translatePath('plugin.video.luc_kodi/settings.xml')
# Fen & Forks
chkset_fen = addon_data + translatePath('plugin.video.fen/settings.xml')
chkset_pov = addon_data + translatePath('plugin.video.pov/settings.xml')
chkset_coal = addon_data + translatePath('plugin.video.coalition/settings.xml')
# Dradis & Forks
chkset_dradis = addon_data + translatePath('plugin.video.dradis/settings.xml')
chkset_genocide = addon_data + translatePath('plugin.video.genocide/settings.xml')
# Shadow & Forks
chkset_shadow = addon_data + translatePath('plugin.video.shadow/settings.xml')
chkset_ghost = addon_data + translatePath('plugin.video.ghost/settings.xml')
chkset_chains = addon_data + translatePath('plugin.video.thechains/settings.xml')
# Homelander & Forks
chkset_home = addon_data + translatePath('plugin.video.homelander/settings.xml')
chkset_night = addon_data + translatePath('plugin.video.nightwing/settings.xml')
chkset_absol = addon_data + translatePath('plugin.video.absolution/settings.xml')
# Scrubs V2 & Forks
chkset_scrubs = addon_data + translatePath('plugin.video.scrubsv2/settings.xml')
chkset_redg = addon_data + translatePath('plugin.video.gratisred/settings.xml')
# Others
chkset_crew = addon_data + translatePath('plugin.video.thecrew/settings.xml')
chkset_salts = addon_data + translatePath('plugin.video.salts/settings.xml')
chkset_otaku = addon_data + translatePath('plugin.video.otaku/settings.xml')
chkset_tmdbh = addon_data + translatePath('plugin.video.themoviedb.helper/settings.xml')
chkset_tmdbh_trakt_provider = addon_data + translatePath('script.module.tmdbhelper.sync.trakt/settings.xml')
chkset_easyv = addon_data + translatePath('plugin.video.easynewsx/settings.xml')
chkset_trakt = addon_data + translatePath('script.trakt/settings.xml')
# Debrid Only
chkset_realx = addon_data + translatePath('plugin.video.realizerx/settings.xml')
chkset_realx_json = addon_data + translatePath('plugin.video.realizerx/rdauth.json')
chkset_premx = addon_data + translatePath('plugin.video.premiumizerx/settings.xml')
chkset_rurl = addon_data + translatePath('script.module.resolveurl/settings.xml')
# Skins
chkset_fentastic = addon_data + translatePath('skin.fentastic/settings.xml')
chkset_nimbus = addon_data + translatePath('skin.nimbus/settings.xml')


#============================== DEFAULT SETTINGS XML's ==============================
# Shadow & Forks
shadow = xmls + translatePath('plugin.video.shadow/settings.xml')
ghost = xmls + translatePath('plugin.video.ghost/settings.xml')
chains = xmls + translatePath('plugin.video.thechains/settings.xml')
# Homelander & Forks
home = xmls + translatePath('plugin.video.homelander/settings.xml')
night = xmls + translatePath('plugin.video.nightwing/settings.xml')
absol = xmls + translatePath('plugin.video.absolution/settings.xml')
# Scrubs V2 & Forks
scrubs = xmls + translatePath('plugin.video.scrubsv2/settings.xml')
redg = xmls + translatePath('plugin.video.gratisred/settings.xml')
# Others
crew = xmls + translatePath('plugin.video.thecrew/settings.xml')
salts = xmls + translatePath('plugin.video.salts/settings.xml')
otaku = xmls + translatePath('plugin.video.otaku/settings.xml')
easyv = xmls + translatePath('plugin.video.easynewsx/settings.xml')
tmdbh = xmls + translatePath('plugin.video.themoviedb.helper/settings.xml')
trakt = xmls + translatePath('script.trakt/settings.xml')
# Debrid Only
realx = xmls + translatePath('plugin.video.realizerx/settings.xml')
realx_json = xmls + translatePath('plugin.video.realizerx/rdauth.json')
premx = xmls + translatePath('plugin.video.premiumizerx/settings.xml')
rurl = xmls + translatePath('script.module.resolveurl/settings.xml')


#================================== SERVICE PATHS ===================================
# Fen Light & Forks
path_fenlt_service = addons + translatePath('plugin.video.fenlight/resources/lib/service.py')
path_gears_service = addons + translatePath('plugin.video.gears/resources/lib/service.py')
path_red_service = addons + translatePath('plugin.video.redlight/resources/lib/service.py')
# Uniques
path_umb_service = addons + translatePath('plugin.video.umbrella/service.py')
path_seren_service = addons + translatePath('plugin.video.seren/service.py')
path_luc_service = addons + translatePath('plugin.video.luc_kodi/service.py')
# Fen & Forks
path_fen_service = addons + translatePath('plugin.video.fen/resources/lib/service.py')
path_pov_service = addons + translatePath('plugin.video.pov/resources/lib/service.py')
path_coal_service = addons + translatePath('plugin.video.coalition/resources/lib/service.py')
# Dradis & Forks
path_dradis_service = addons + translatePath('plugin.video.dradis/service.py')
path_genocide_service = addons + translatePath('plugin.video.genocide/service.py')
# Homelander & Forks
path_home_service = addons + translatePath('plugin.video.homelander/service.py')
path_night_service = addons + translatePath('plugin.video.nightwing/service.py')
path_absol_service = addons + translatePath('plugin.video.absolution/service.py')
# Scrubs V2 & Forks
path_scrubs_service = addons + translatePath('plugin.video.scrubsv2/service.py')
path_redg_service = addons + translatePath('plugin.video.gratisred/service.py')
# Others
path_crew_service = addons + translatePath('plugin.video.thecrew/service.py')
path_salts_service = addons + translatePath('plugin.video.salts/service.py')
path_scrubs_service = addons + translatePath('plugin.video.scrubsv2/service.py')
path_tmdbh_trakt_recovery = chk_tmdbh_trakt_provider + translatePath('resources/lib/tmdbhelper_sync_trakt/api/recovery.py')
path_trakt_service = addons + translatePath('script.trakt/resources/lib/service.py')


#============================= DEFAULT TRAKT API KEY PATHS =============================
# Uniques
path_umb = addons + translatePath('plugin.video.umbrella/resources/lib/modules/trakt.py')
path_seren = addons + translatePath('plugin.video.seren/resources/lib/indexers/trakt.py')
# Fen & Forks
path_fen = addons + translatePath('plugin.video.fen/resources/lib/apis/trakt_api.py')
# Shadow & Forks
path_shadow = addons + translatePath('plugin.video.shadow/resources/menus.py')
path_ghost = addons + translatePath('plugin.video.ghost/resources/modules/general.py')
path_chains = addons + translatePath('plugin.video.thechains/resources/menus.py')
# Scrubs V2 & Forks
path_scrubs = addons + translatePath('plugin.video.scrubsv2/resources/lib/modules/trakt.py')
path_redg = addons + translatePath('plugin.video.gratisred/resources/lib/modules/trakt.py')
# Others
path_crew = addons + translatePath('script.module.thecrew/lib/resources/lib/modules/keys.py')
path_salts = addons + translatePath('plugin.video.salts/salts_lib/trakt_api.py')
path_scrubs = addons + translatePath('plugin.video.scrubsv2/resources/lib/modules/trakt.py')
path_tmdbh_trakt_keys = chk_tmdbh_trakt_provider + translatePath('resources/lib/tmdbhelper_sync_trakt/api/keys.py')
path_trakt = addons + translatePath('script.trakt/resources/lib/traktapi.py')


#================================ DEFAULT TRAKT API KEYS ==============================
umb_client_obs = [122, 117, 39, 113, 36, 114, 119, 119, 36, 33, 118, 38, 122, 36, 33, 36, 38, 123, 116, 39, 116, 115, 35, 118, 117, 118, 116, 113, 113, 112, 117, 33, 35, 122, 117, 117, 33, 119, 115, 39, 122, 119, 123, 117, 32, 118, 118, 122, 39, 115, 113, 112, 116, 115, 115, 33, 119, 35, 116, 117, 117, 32, 115, 113]
umb_secret_obs = [118, 35, 115, 123, 119, 117, 35, 119, 112, 38, 119, 36, 39, 32, 123, 122, 36, 35, 36, 38, 39, 119, 113, 115, 123, 113, 39, 119, 115, 36, 116, 123, 112, 36, 35, 123, 32, 38, 33, 38, 114, 33, 33, 115, 113, 33, 36, 118, 118, 35, 119, 39, 113, 123, 123, 117, 119, 119, 113, 123, 39, 38, 36, 114]

pov_client_obs = [116, 32, 33, 112, 123, 115, 112, 118, 33, 113, 38, 123, 118, 116, 116, 39, 114, 116, 35, 113, 39, 38, 115, 123, 35, 117, 32, 119, 123, 117, 116, 36, 33, 32, 112, 122, 113, 115, 115, 114, 114, 122, 118, 114, 115, 39, 115, 33, 39, 114, 118, 33, 36, 114, 122, 115, 123, 116, 36, 122, 32, 115, 116, 35]
pov_secret_obs = [123, 123, 118, 117, 122, 122, 118, 112, 32, 115, 117, 38, 118, 118, 38, 117, 35, 33, 33, 35, 36, 39, 36, 118, 119, 33, 116, 33, 115, 32, 32, 32, 35, 112, 113, 119, 117, 123, 112, 117, 119, 113, 33, 115, 123, 119, 114, 116, 123, 35, 39, 115, 118, 123, 119, 123, 119, 33, 38, 113, 35, 123, 115, 123]

dradis_client_obs = [115, 123, 38, 118, 35, 114, 122, 36, 116, 116, 114, 115, 38, 112, 33, 119, 38, 117, 123, 115, 38, 114, 118, 115, 35, 123, 36, 36, 35, 38, 38, 113, 33, 39, 112, 116, 33, 114, 113, 122, 119, 114, 114, 114, 117, 114, 113, 123, 117, 39, 32, 113, 115, 119, 32, 117, 118, 32, 119, 35, 117, 119, 119, 114]
dradis_secret_obs = [113, 39, 39, 122, 116, 122, 32, 35, 33, 32, 36, 123, 39, 38, 32, 35, 123, 38, 38, 115, 115, 35, 115, 32, 112, 116, 32, 115, 35, 32, 39, 118, 36, 119, 32, 122, 115, 38, 114, 36, 114, 38, 123, 114, 32, 38, 113, 114, 35, 33, 119, 113, 39, 115, 112, 117, 35, 36, 114, 122, 32, 39, 113, 123]

seren_client_obs = [114, 33, 123, 35, 113, 114, 122, 115, 123, 39, 118, 35, 36, 116, 36, 36, 35, 36, 113, 32, 123, 119, 118, 33, 32, 39, 35, 39, 123, 32, 119, 118, 118, 123, 123, 114, 122, 122, 119, 115, 113, 122, 116, 113, 33, 114, 113, 33, 114, 112, 123, 115, 115, 38, 39, 114, 114, 35, 33, 112, 38, 39, 117, 123]
seren_secret_obs = [32, 36, 114, 112, 118, 115, 117, 36, 112, 117, 32, 119, 115, 118, 33, 39, 39, 116, 35, 122, 38, 115, 113, 119, 36, 112, 38, 38, 33, 112, 116, 115, 35, 115, 119, 39, 39, 33, 36, 32, 116, 39, 38, 116, 112, 122, 123, 33, 113, 116, 112, 113, 123, 122, 112, 116, 38, 33, 38, 38, 115, 122, 118, 112]

# Alternate Seren fork Trakt API keys (Diggz and minhgi forks)
seren_fork_client_obs = [112, 116, 118, 36, 122, 39, 33, 38, 115, 118, 33, 122, 117, 123, 39, 113, 117, 112, 119, 118, 122, 33, 116, 115, 119, 118, 119, 36, 115, 38, 112, 117, 36, 36, 119, 116, 36, 33, 33, 36, 33, 114, 118, 113, 33, 118, 36, 35, 112, 35, 118, 123, 113, 118, 116, 38, 36, 118, 32, 116, 39, 113, 116, 36]
seren_fork_secret_obs = [118, 113, 119, 123, 115, 117, 32, 117, 118, 122, 38, 114, 116, 119, 39, 112, 116, 117, 122, 116, 36, 119, 36, 123, 35, 36, 112, 114, 38, 115, 112, 117, 123, 112, 116, 123, 39, 32, 112, 119, 35, 35, 115, 116, 38, 119, 115, 36, 118, 35, 36, 115, 118, 39, 39, 113, 115, 115, 38, 114, 112, 118, 117, 33]

luc_client_obs = [32, 118, 112, 113, 118, 35, 119, 117, 114, 39, 112, 35, 36, 122, 122, 35, 114, 118, 112, 33, 122, 117, 113, 33, 116, 112, 123, 36, 33, 39, 33, 119, 39, 117, 117, 39, 118, 39, 122, 32, 119, 38, 123, 115, 117, 119, 117, 39, 122, 122, 114, 35, 119, 115, 36, 116, 116, 122, 122, 36, 38, 115, 118, 38]
luc_secret_obs = [119, 115, 39, 118, 114, 39, 32, 32, 117, 35, 39, 39, 33, 112, 118, 33, 32, 119, 38, 122, 117, 113, 114, 122, 39, 113, 114, 113, 117, 112, 123, 112, 116, 118, 39, 36, 115, 123, 112, 32, 113, 116, 39, 115, 122, 122, 116, 112, 122, 112, 32, 39, 38, 38, 36, 122, 35, 114, 32, 113, 36, 116, 33, 115]

fen_client_obs = [116, 118, 119, 32, 114, 36, 118, 116, 38, 36, 112, 123, 38, 112, 117, 39, 116, 113, 33, 118, 35, 122, 38, 119, 36, 36, 36, 115, 119, 122, 39, 38, 38, 114, 32, 39, 36, 114, 35, 116, 35, 119, 38, 113, 112, 36, 33, 115, 112, 33, 115, 32, 122, 112, 113, 122, 122, 32, 39, 113, 119, 115, 35, 36]
fen_secret_obs = [118, 112, 112, 35, 112, 122, 112, 39, 36, 119, 36, 39, 118, 32, 119, 33, 118, 117, 32, 33, 116, 114, 118, 112, 119, 33, 114, 114, 123, 35, 33, 113, 114, 118, 117, 39, 32, 38, 115, 114, 35, 117, 36, 116, 35, 36, 117, 123, 114, 113, 114, 113, 122, 117, 119, 118, 115, 123, 36, 115, 122, 36, 123, 122]

shadow_client_obs = [122, 39, 38, 119, 118, 119, 33, 114, 32, 117, 36, 123, 112, 33, 33, 112, 116, 38, 115, 39, 33, 38, 116, 113, 112, 116, 123, 123, 119, 33, 116, 33, 36, 114, 114, 119, 113, 32, 38, 117, 119, 123, 116, 35, 123, 122, 39, 123, 116, 112, 35, 118, 117, 112, 32, 39, 39, 116, 113, 112, 117, 118, 39, 116]
shadow_secret_obs = [115, 39, 33, 118, 36, 113, 117, 39, 119, 117, 118, 113, 39, 113, 114, 122, 116, 35, 32, 35, 33, 39, 114, 33, 122, 113, 118, 118, 118, 33, 112, 119, 38, 123, 32, 116, 119, 119, 38, 115, 38, 117, 117, 32, 117, 123, 113, 122, 114, 116, 32, 112, 33, 122, 112, 114, 119, 35, 119, 115, 114, 118, 112, 116]

ghost_client_obs = [35, 118, 39, 117, 115, 116, 32, 118, 32, 112, 112, 32, 116, 112, 39, 119, 123, 32, 123, 39, 114, 123, 118, 119, 118, 118, 113, 119, 33, 122, 117, 115, 114, 32, 116, 119, 114, 32, 113, 115, 118, 113, 38, 33, 33, 39, 119, 119, 113, 38, 112, 119, 112, 32, 116, 35, 116, 116, 32, 35, 116, 114, 33, 122]
ghost_secret_obs = [33, 116, 38, 123, 35, 32, 35, 117, 112, 112, 115, 118, 35, 115, 33, 35, 113, 33, 116, 38, 118, 119, 38, 114, 113, 119, 115, 39, 119, 123, 36, 112, 115, 32, 32, 39, 118, 113, 38, 36, 123, 32, 32, 35, 33, 117, 33, 119, 32, 117, 118, 114, 114, 122, 123, 113, 117, 123, 36, 122, 33, 119, 33, 38]

salts_client_obs = [118, 112, 39, 32, 35, 116, 123, 35, 115, 122, 117, 123, 119, 35, 39, 118, 122, 36, 33, 119, 38, 116, 38, 32, 38, 38, 123, 123, 113, 123, 116, 39, 123, 39, 113, 122, 123, 118, 38, 33, 118, 36, 115, 122, 123, 113, 114, 39, 116, 115, 122, 117, 38, 113, 116, 33, 122, 32, 118, 113, 118, 116, 38, 113]
salts_secret_obs = [39, 119, 32, 33, 117, 39, 112, 114, 116, 116, 114, 39, 117, 113, 116, 112, 112, 113, 118, 118, 39, 32, 36, 123, 113, 33, 112, 119, 114, 35, 122, 36, 33, 112, 122, 115, 118, 35, 122, 36, 117, 33, 112, 32, 114, 122, 112, 32, 38, 39, 39, 119, 115, 119, 118, 119, 38, 119, 36, 117, 115, 123, 116, 123]
                                                   
scrubs_client_obs = [116, 113, 33, 119, 113, 39, 38, 33, 112, 123, 123, 32, 117, 35, 114, 119, 33, 33, 116, 39, 35, 112, 112, 117, 112, 39, 122, 35, 122, 118, 39, 115, 113, 35, 35, 38, 39, 114, 116, 117, 33, 115, 122, 35, 117, 123, 118, 113, 116, 112, 35, 32, 123, 35, 118, 35, 122, 118, 39, 35, 36, 32, 115, 116]
scrubs_secret_obs = [123, 115, 116, 113, 39, 32, 38, 35, 123, 38, 113, 113, 35, 33, 38, 114, 116, 33, 117, 118, 38, 114, 115, 117, 39, 122, 116, 115, 118, 114, 118, 32, 117, 112, 115, 112, 39, 39, 113, 118, 116, 117, 119, 39, 114, 123, 39, 117, 113, 113, 116, 119, 38, 117, 119, 113, 116, 32, 122, 118, 39, 35, 32, 116]

redg_client_obs = [113, 113, 39, 35, 116, 32, 36, 35, 112, 32, 114, 116, 33, 123, 33, 36, 35, 113, 39, 118, 114, 122, 36, 33, 116, 32, 118, 33, 33, 113, 114, 118, 122, 118, 36, 113, 115, 32, 123, 114, 117, 113, 113, 38, 36, 113, 119, 114, 122, 36, 38, 114, 123, 33, 39, 119, 115, 112, 36, 118, 117, 123, 122, 112]
redg_secret_obs = [118, 35, 112, 123, 118, 35, 36, 38, 35, 32, 123, 119, 122, 123, 118, 32, 39, 123, 117, 117, 38, 33, 117, 123, 33, 123, 117, 115, 119, 112, 112, 118, 38, 33, 122, 117, 35, 118, 35, 122, 122, 38, 117, 118, 123, 118, 118, 119, 114, 117, 123, 118, 119, 33, 35, 119, 122, 32, 36, 117, 115, 123, 32, 112]

# Chains API Keys - Coalition / Gears / Genocide
chains_client_obs = [115, 123, 122, 118, 123, 123, 114, 123, 35, 114, 36, 122, 33, 123, 38, 33, 116, 113, 112, 32, 33, 119, 36, 119, 33, 117, 33, 33, 35, 36, 38, 115, 123, 36, 113, 39, 118, 119, 112, 39, 112, 39, 118, 118, 36, 39, 39, 114, 119, 32, 122, 113, 36, 38, 119, 38, 33, 115, 39, 117, 117, 116, 117, 119]
chains_secret_obs = [32, 119, 36, 33, 38, 117, 33, 32, 119, 38, 123, 32, 32, 123, 116, 113, 117, 122, 118, 38, 115, 115, 32, 32, 36, 122, 119, 113, 119, 32, 33, 114, 38, 112, 119, 38, 118, 116, 112, 112, 119, 114, 115, 116, 115, 123, 115, 39, 32, 118, 122, 39, 119, 114, 117, 123, 112, 38, 112, 115, 119, 119, 33, 114]

thechains_client_obs = [123, 115, 39, 39, 114, 115, 112, 119, 123, 39, 119, 122, 114, 36, 114, 39, 36, 122, 113, 39, 118, 35, 36, 112, 113, 38, 32, 117, 38, 123, 123, 116, 117, 116, 33, 117, 36, 115, 118, 39, 112, 36, 36, 123, 113, 33, 113, 38, 115, 115, 113, 118, 119, 32, 117, 39, 38, 117, 113, 118, 119, 116, 33, 117]
thechains_secret_obs = [112, 113, 117, 114, 38, 114, 118, 112, 119, 39, 118, 114, 35, 119, 112, 118, 122, 35, 38, 36, 117, 35, 113, 35, 113, 118, 113, 39, 113, 112, 117, 35, 116, 122, 117, 116, 36, 119, 112, 113, 38, 38, 117, 39, 123, 118, 39, 39, 117, 117, 117, 35, 118, 123, 32, 119, 112, 39, 114, 116, 33, 116, 112, 36]

tmdbh_client_obs = [39, 116, 36, 38, 39, 116, 115, 117, 113, 35, 38, 36, 113, 33, 116, 35, 36, 122, 36, 38, 115, 32, 114, 116, 123, 118, 32, 123, 32, 122, 118, 38, 117, 33, 119, 115, 123, 33, 39, 36, 33, 112, 118, 118, 122, 112, 113, 115, 114, 39, 115, 38, 39, 114, 116, 33, 116, 35, 32, 39, 119, 118, 116, 117]

trakt_client_obs_str = '[123, 39, 116, 119, 33, 117, 32, 32, 118, 35, 119, 32, 117, 122, 116, 35, 119, 32, 119, 38, 36, 113, 39, 117, 113, 117, 115, 33, 113, 32, 33, 38, 36, 35, 114, 114, 39, 112, 116, 35, 118, 123, 114, 117, 122, 39, 35, 112, 114, 112, 122, 122, 38, 116, 115, 116, 36, 39, 122, 113, 38, 122, 118, 38]'
trakt_secret_obs_str = '[35, 32, 33, 116, 36, 33, 123, 119, 119, 118, 114, 118, 123, 123, 38, 114, 113, 114, 122, 39, 119, 117, 32, 33, 112, 117, 39, 33, 35, 36, 123, 35, 38, 39, 33, 117, 36, 123, 38, 118, 114, 35, 122, 123, 112, 116, 36, 113, 117, 123, 118, 115, 36, 36, 119, 117, 123, 123, 32, 35, 119, 35, 32, 113]'


madtitan_client_obs = [35, 36, 116, 35, 119, 123, 32, 118, 39, 35, 38, 38, 112, 32, 119, 114, 33, 115, 33, 38, 123, 123, 35, 114, 112, 122, 115, 35, 33, 123, 39, 32, 33, 39, 32, 115, 117, 112, 116, 35, 36, 114, 116, 33, 39, 36, 123, 122, 116, 115, 38, 115, 39, 112, 115, 113, 33, 35, 38, 36, 116, 116, 36, 35]
madtitan_secret_obs = [122, 35, 117, 33, 32, 116, 112, 39, 118, 116, 122, 35, 35, 115, 113, 117, 36, 35, 32, 123, 35, 35, 32, 39, 123, 119, 32, 116, 39, 122, 118, 119, 119, 33, 118, 33, 118, 115, 32, 119, 122, 118, 118, 119, 38, 39, 115, 123, 122, 122, 119, 39, 32, 115, 117, 115, 117, 118, 33, 116, 118, 32, 123, 119]

#================ TRAKT API KEY VARIABLES ================
madtitan_client = obfuscation.deobfuscate(madtitan_client_obs)
madtitan_secret = obfuscation.deobfuscate(madtitan_secret_obs)
umb_client = obfuscation.deobfuscate(umb_client_obs)
umb_secret = obfuscation.deobfuscate(umb_secret_obs)

pov_client = obfuscation.deobfuscate(pov_client_obs)
pov_secret = obfuscation.deobfuscate(pov_secret_obs)

dradis_client = obfuscation.deobfuscate(dradis_client_obs)
dradis_secret = obfuscation.deobfuscate(dradis_secret_obs)

seren_client = obfuscation.deobfuscate(seren_client_obs)
seren_secret = obfuscation.deobfuscate(seren_secret_obs)

# Alternate Seren fork Trakt API credentials
seren_fork_client = obfuscation.deobfuscate(seren_fork_client_obs)
seren_fork_secret = obfuscation.deobfuscate(seren_fork_secret_obs)

luc_client = obfuscation.deobfuscate(luc_client_obs)
luc_secret = obfuscation.deobfuscate(luc_secret_obs)

fen_client = obfuscation.deobfuscate(fen_client_obs)
fen_secret = obfuscation.deobfuscate(fen_secret_obs)

shadow_client = obfuscation.deobfuscate(shadow_client_obs)
shadow_secret = obfuscation.deobfuscate(shadow_secret_obs)

ghost_client = obfuscation.deobfuscate(ghost_client_obs)
ghost_secret = obfuscation.deobfuscate(ghost_secret_obs)

crew_client = 'YFFRKk8MHw4KXFlpKlt8TSw9R0h1QCMgHDjyMQl/tGSz0TI5FPo5/Gm8Urs1++rR5w8QVlpbrczzFd8ZCNRHQA=='
crew_secret = 'bFkGdklSSAwKc1oUVwosMhYDd3t3fhkRLwjyKDqxYWGyAjM2yvvvLW9tbWk0CwHRFvYdXlZXWTgGCygcxQFGRg=='

salts_client = obfuscation.deobfuscate(salts_client_obs)
salts_secret = obfuscation.deobfuscate(salts_secret_obs)

scrubs_client = obfuscation.deobfuscate(scrubs_client_obs)
scrubs_secret = obfuscation.deobfuscate(scrubs_secret_obs)

redg_client = obfuscation.deobfuscate(redg_client_obs)
redg_secret = obfuscation.deobfuscate(redg_secret_obs)

chains_client = obfuscation.deobfuscate(chains_client_obs)
chains_secret = obfuscation.deobfuscate(chains_secret_obs)

thechains_client = obfuscation.deobfuscate(thechains_client_obs)
thechains_secret = obfuscation.deobfuscate(thechains_secret_obs)

tmdbh_client = obfuscation.deobfuscate(tmdbh_client_obs)
