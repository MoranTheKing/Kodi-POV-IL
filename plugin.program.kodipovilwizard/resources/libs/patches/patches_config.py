# -*- coding: utf-8 -*-

# Registry schema for Engine v2 patches
PATCH_CONFIG = [
    {'id': 'pov_merged_personal_pagination', 'name': 'Merged personal lists paginate after ordering', 'description': 'Defer only the local slice for the build personal-list merge; native routes are unchanged.', 'addon_id': 'plugin.video.pov', 'enabled': True, 'target_file': 'resources/lib/modules/utils.py', 'marker': '# WIZARD_POV_MERGED_PERSONAL_PAGINATION_v1', 'anchor': '\tif not item_list: return item_list, page', 'action': 'prepend_before', 'hook': "\tif page == 'povil_merge_all': return item_list, 1\n"},
    {'id': 'pov_trakt_personal_newest', 'name': 'trakt personal lists newest first', 'description': 'Sort personal items before pagination; keep public and liked lists unchanged.', 'addon_id': 'plugin.video.pov', 'enabled': True, 'target_file': 'resources/lib/indexers/trakt_api.py', 'marker': '# WIZARD_POV_TRAKT_PERSONAL_NEWEST_v1', 'anchor': '\treturn trakt_cache.cache_trakt_object(_get_trakt_paginated_list, string, url)', 'action': 'prepend_before', 'hook': "\ttry:\n\t\timport sys, xbmcvfs\n\t\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n\t\tif p not in sys.path: sys.path.append(p)\n\t\timport pov_mdblist_patch_logic\n\t\tif list_type == 'my_lists':\n\t\t\treturn pov_mdblist_patch_logic.newest_personal_items(trakt_cache.cache_trakt_object(_get_trakt_paginated_list, string, url))\n\texcept Exception: pass\n"},
    {'id': 'pov_mdblist_personal_newest', 'name': 'mdblist personal lists newest first', 'description': 'Sort personal items before pagination; keep public and liked lists unchanged.', 'addon_id': 'plugin.video.pov', 'enabled': True, 'target_file': 'resources/lib/indexers/mdblist_api.py', 'marker': '# WIZARD_POV_MDBLIST_PERSONAL_NEWEST_v1', 'anchor': "\treturn mdbl_cache.cache_mdbl_object(_get_mdbl_paginated_list, string, url)['items']", 'action': 'prepend_before', 'hook': "\ttry:\n\t\timport sys, xbmcvfs\n\t\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n\t\tif p not in sys.path: sys.path.append(p)\n\t\timport pov_mdblist_patch_logic\n\t\tif list_type == 'my_lists':\n\t\t\turl = pov_mdblist_patch_logic.personal_mdbl_url(url + '&povil_personal=1')\n\t\t\treturn mdbl_cache.cache_mdbl_object(_get_mdbl_paginated_list, string + '_newest_v1', url)['items']\n\texcept Exception: pass\n"},
    {'id': 'pov_hebrew_interface', 'name': 'Persistent Hebrew POV interface', 'addon_id': 'plugin.video.pov', 'enabled': True, 'target_file': 'resources/lib/modules/kodi_utils.py', 'marker': '# WIZARD_POV_HEBREW_INTERFACE_v1', 'anchor': '\ttry: _string = int(string)', 'action': 'prepend_before', 'hook': "\ttry:\n\t\timport sys, xbmcvfs\n\t\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n\t\tif p not in sys.path: sys.path.append(p)\n\t\tfrom pov_ui_labels import hebrew_label\n\t\t_hebrew_label = hebrew_label(string)\n\t\tif _hebrew_label is not None: return _hebrew_label\n\texcept Exception: pass\n"},
    {'id': 'pov_local_favorites_recent', 'name': 'Newest local favorites first', 'addon_id': 'plugin.video.pov', 'enabled': True, 'target_file': 'resources/lib/indexers/local_api.py', 'marker': '# WIZARD_POV_LOCAL_FAVORITES_RECENT_v1', 'anchor': "\tpath = 'SELECT tmdb_id, title FROM favorites WHERE db_type = ?'", 'action': 'prepend_before', 'hook': "\tdata = call_local('SELECT tmdb_id, title FROM favorites WHERE db_type = ? ORDER BY rowid DESC', (mediatype,))\n\tif page_no == 'all': return data\n\treturn [{'media_id': str(i['tmdb_id']), 'title': i['title']} for i in data], 1\n"},
    {
        "id": "pov_cache_empty_prevention",
        "name": "POV Empty Cache Prevention",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/caches/main_cache.py",
        "marker": "# WIZARD_POV_CACHE_EMPTY_v1",
        "anchor": "\tmaincache.set(string, result, expiration)",
        "action": "prepend_before",
        "hook": (
            "\tif not result:\n"
            "\t\timport sys, xbmcvfs;\n"
            "\t\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "\t\tsys.path.append(p) if p not in sys.path else None;\n"
            "\t\timport pov_cache_handler;\n"
            "\t\tpov_cache_handler.handle_empty(string);\n"
            "\t\treturn result\n"
        )
    },
    {
        "id": "pov_debrid_unbound_guard",
        "name": "Debrid Unbound Locals Guard",
        "description": "Initializes files and torrent_id at the top of the function to prevent UnboundLocalError in the except block.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/modules/debrid.py",
        "marker": "# WIZARD_POV_DEBRID_RESOLVE_GUARD_v2",
        "anchor": "from modules.source_utils import supported_video_extensions, seas_ep_filter, extras_filter",
        "action": "prepend_before",
        "hook": (
            "\tfiles = None; torrent_id = None\n"
        )
    },
    {
    	"id": "wizard_pov_visibility_mgr_navigator",
    	"name": "Dynamic Visibility Manager (Widget Folders)",
    	"description": "Shadows the shortcut-folder contents in memory and hides personal Trakt/TMDB/MDBList rows when the service is not connected (also injects the MDBList row when connected). Never writes navigator.db; any failure leaves the list untouched.",
    	"addon_id": "plugin.video.pov",
    	"enabled": True,
    	"target_file": "resources/lib/menus/navigator.py",
    	"marker": "# WIZARD_POV_VISIBILITY_MGR_v2",
    	"anchor": "\t\tcontents = nc.get_shortcut_folder_contents(list_name)",
    	"action": "append_after",
    	"hook": (
    		"\t\timport sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); "
    		"sys.path.append(p) if p not in sys.path else None; import pov_visibility_mgr; contents = pov_visibility_mgr.filter_navigator_list(contents, list_name)"
    	)
    },
    {
        "id": "pov_genre_icons_rewrite",
        "name": "POV Distinct Genre Icons",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/menus/navigator.py",
        "marker": "# WIZARD_POV_GENRE_ICONS_v2",
        "anchor": "\t\t\tself._add_item({'mode': mode, 'action': action, 'genre_id': value[0], 'name': genre}, 'genres.png', list_name=list_name)",
        "action": "prepend_before",
        "hook": (
            "\t\t\t# WIZARD: Loop bypass to inject distinct genre icon\n"
            "\t\t\tfrom xbmcvfs import translatePath\n"
            "\t\t\t_icon_path = translatePath('special://home/media/povil_icons/%s' % value[1])\n"
            "\t\t\tself._add_item({'mode': mode, 'action': action, 'genre_id': value[0], 'name': genre}, _icon_path, list_name=list_name)\n"
            "\t\t\tcontinue\n"
        )
    },
    {
        "id": "pov_shortcut_absolute_paths",
        "name": "POV Shortcut Folder Absolute Paths",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/menus/navigator.py",
        "marker": "# WIZARD_POV_SHORTCUT_PATHS_v2",
        "anchor": "\t\t\t\t\ticon = item_get('iconImage') if item_get('network_id', '') != '' else '%s%s' % (icon_path, item_get('iconImage'))",
        "action": "append_after",
        "hook": (
            "\t\t\t\t\t# WIZARD: Variable shadow for absolute path hardening\n"
            "\t\t\t\t\tif icon and str(item_get('iconImage') or '').startswith(('special://', 'http', 'resource://')):\n"
            "\t\t\t\t\t\ticon = item_get('iconImage')\n"
        )
    },
    {
        "id": "pov_shortcut_fanart_shadow",
        "name": "POV Shortcut Fanart Shadow Fix",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/menus/navigator.py",
        "marker": "# WIZARD_POV_FANART_SHADOW_v3",
        "anchor": "\t\t\t\t\tlistitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': icon})",
        "action": "append_after",
        "hook": (
            "\t\t\t\t\t# WIZARD: Sequential property override to preserve fanart\n"
            "\t\t\t\t\tif 'genres/' in str(item_get('iconImage') or ''):\n"
            "\t\t\t\t\t\tlistitem.setArt({'fanart': icon})\n"
        )
    },
    {
        "id": "pov_anime_trakt_strings",
        "name": "POV Anime Trakt Strings Translation",
        "description": "Translates hardcoded English strings in Trakt lists to Hebrew.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/menus/navigator.py",
        "marker": "# WIZARD_POV_ANIME_TRAKT_STRINGS_v2",
        "anchor": "\t\tcal_str, ani_str, drp_str = 'Trakt Calendar', 'Anime Calendar', 'Dropped TV Shows'",
        "action": "append_after",
        "hook": (
            "\t\t# WIZARD: Variable shadowing to translate hardcoded Anime strings\n"
            "\t\tani_str, drp_str = 'לוח שידורי אנימה', 'סדרות שנזנחו'\n"
        )
    },
    {
        "id": "pov_anime_years_breadcrumbs",
        "name": "POV Anime Years Breadcrumbs Translation",
        "description": "Translates dynamic breadcrumb titles for Anime Years.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/menus/navigator.py",
        "marker": "# WIZARD_POV_ANIME_YEARS_BREADCRUMBS_v2",
        "anchor": "\t\t\tlist_name = 'ANIME %s: %s %s' % (lst_ins.upper(), str(i), ls(32460))",
        "action": "append_after",
        "hook": (
            "\t\t\t# WIZARD: Variable shadowing for Hebrew breadcrumb\n"
            "\t\t\tlist_name = '%s: %s' % (('סרטי אנימה' if menu_type == 'movie' else 'סדרות אנימה'), str(i))\n"
        )
    },
    {
        "id": "pov_anime_genres_breadcrumbs",
        "name": "POV Anime Genres Breadcrumbs Translation",
        "description": "Translates dynamic breadcrumb titles for Anime Genres.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/menus/navigator.py",
        "marker": "# WIZARD_POV_ANIME_GENRES_BREADCRUMBS_v2",
        "anchor": "\t\t\tlist_name = 'ANIME %s: %s %s' % (lst_ins.upper(), genre, ls(32470))",
        "action": "append_after",
        "hook": (
            "\t\t\t# WIZARD: Variable shadowing for Hebrew breadcrumb\n"
            "\t\t\tlist_name = '%s: %s' % (('סרטי אנימה' if menu_type == 'movie' else 'סדרות אנימה'), genre)\n"
        )
    },
    {
        "id": "pov_genre_dict_main_loop_translation",
        "name": "POV Genre Dict Main Loop Translation",
        "description": "Translates genre dictionary keys in-memory before looping (covers both genres and anime_genres).",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/menus/navigator.py",
        "marker": "# WIZARD_POV_GENRE_DICT_MAIN_LOOP_v2",
        "anchor": "\t\tfor genre, value in sorted(genre_list.items()):",
        "action": "prepend_before",
        "hook": (
            "\t\t# WIZARD: Translate genre dict keys to Hebrew in memory\n"
            "\t\timport sys, xbmcvfs\n"
            "\t\t_p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "\t\tsys.path.append(_p) if _p not in sys.path else None\n"
            "\t\timport pov_translations\n"
            "\t\tgenre_list = pov_translations.translate_genres(genre_list)\n"
        )
    },
    {
        "id": "pov_genre_dict_multiselect_translation",
        "name": "POV Genre Dict Multiselect Translation",
        "description": "Translates genre dictionary keys in-memory inside the multiselect dialog view.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/menus/navigator.py",
        "marker": "# WIZARD_POV_GENRE_DICT_MULTISELECT_v2",
        "anchor": "\t\tgenre_list = dict(sorted(json.loads(genre_list).items()))",
        "action": "append_after",
        "hook": (
            "\t\t# WIZARD: Translate genre dict keys to Hebrew in multiselect memory\n"
            "\t\timport sys, xbmcvfs\n"
            "\t\t_p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "\t\tsys.path.append(_p) if _p not in sys.path else None\n"
            "\t\timport pov_translations\n"
            "\t\tgenre_list = pov_translations.translate_genres(genre_list)\n"
        )
    },
    {
        "id": "pov_tmdb_timeout_widen",
        "name": "POV TMDB Timeout Widen",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/tmdb_api.py",
        "marker": "# WIZARD_POV_TMDB_TIMEOUT_v3",
        "anchor": "timeout = 3.05",
        "alternatives": [{"anchor": "timeout = 5"}],
        "action": "append_after",
        "hook": (
            "timeout = 15.05  # WIZARD: Widened for mobile per-item fetch reliability\n"
        )
    },
    {
        "id": "pov_movie_networks_providers_fix",
        "name": "POV Movie Networks Providers Fix",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/tmdb_api.py",
        "marker": "# WIZARD_POV_MOVIE_NETWORKS_v4",
        "anchor": "\turl += '&sort_by=popularity.desc&certification_country=US&with_companies=%s' % network_id",
        "action": "append_after",
        "hook": (
            "\t# Shadow variable to override 'with_companies' to 'watch_providers'\n"
            "\turl = '%s/3/discover/movie?language=en-US&region=US&page=%s' % (base_url, page_no)\n"
            "\turl += '&sort_by=popularity.desc&certification_country=US&with_watch_providers=%s&watch_region=US&with_watch_monetization_types=flatrate' % network_id\n"
        )
    },
    {
        "id": "pov_movie_meta_blank_guard",
        "name": "POV Movie Meta Blank Guard",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/metadata.py",
        "marker": "# WIZARD_POV_MOVIE_META_GUARD_v3",
        "anchor": "\t\t\tmetacache_set('movie', id_type, meta, EXPIRES_2_DAYS)",
        "action": "prepend_before",
        "hook": (
            "\t\t\t# WIZARD: Bypass cache persistence and purge poisoned DB rows\n"
            "\t\t\timport sys, xbmcvfs;\n"
            "\t\t\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "\t\t\tsys.path.append(p) if p not in sys.path else None;\n"
            "\t\t\timport pov_meta_handler;\n"
            "\t\t\tpov_meta_handler.clear_blank_meta();\n"
            "\t\t\treturn meta\n"
        )
    },
    {
        "id": "pov_tvshow_meta_blank_guard",
        "name": "POV TVShow Meta Blank Guard",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/metadata.py",
        "marker": "# WIZARD_POV_TVSHOW_META_GUARD_v3",
        "anchor": "\t\t\tmetacache_set('tvshow', id_type, meta, EXPIRES_2_DAYS)",
        "action": "prepend_before",
        "hook": (
            "\t\t\t# WIZARD: Bypass cache persistence and purge poisoned DB rows\n"
            "\t\t\timport sys, xbmcvfs;\n"
            "\t\t\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "\t\t\tsys.path.append(p) if p not in sys.path else None;\n"
            "\t\t\timport pov_meta_handler;\n"
            "\t\t\tpov_meta_handler.clear_blank_meta();\n"
            "\t\t\treturn meta\n"
        )
    },
    {
        "id": "pov_repeat_timer_resiliency",
        "name": "RepeatTimer Crash Prevention",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/modules/myservices.py",
        "marker": "# WIZARD_POV_REPEAT_TIMER_v1",
        "anchor": "\t\t\tself.function(*self.args, **self.kwargs)",
        "action": "prepend_before",
        "hook": (
            "try:\n"
            "    self.function(*self.args, **self.kwargs)\n"
            "except Exception:\n"
            "    pass\n"
            "continue"
        )
    },
    {
        "id": "pov_acctmgr_integration",
        "name": "POV Account Manager & Services Integration",
        "description": "Intercepts POV's My Services to route Debrid/Trakt to Account Manager and inject Gemini AI UI.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/modules/myservices.py",
        "marker": "# WIZARD_POV_SERVICES_ACCTMGR_v2",
        "anchor": "class RepeatTimer(Timer):",
        "action": "prepend_before",
        "hook": (
            "import sys, xbmcvfs\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "sys.path.append(p) if p not in sys.path else None\n"
            "import pov_myservices\n"
            "authorize = pov_myservices.get_authorize_override(authorize)\n"
            "\n"
        )
    },
    {
        "id": "pov_torbox_api_user_stats",
        "name": "TorBox Stats API Addition",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/torbox_api.py",
        "marker": "# WIZARD_POV_TORBOX_API_STATS_v3",
        "anchor": "\tdef torrent_info(self, request_id, path='torrents'):",
        "action": "prepend_before",
        "hook": (
            "\tdef user_stats(self):\n"
            "\t\tparams = {'general': 'true', 'bandwidth': 'true', 'bandwidth_grouping': 'day'}\n"
            "\t\tif hasattr(self, 'api'): return self.api('get', '/v1/api/user/stats', params=params)\n"
            "\t\turl = 'user/stats'\n"
            "\t\treturn self._get(url, params=params)\n\n"
        )
    },
    {
        "id": "pov_torbox_usage_ui",
        "name": "TorBox Usage UI",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/debrids/tb_cloud.py",
        "marker": "# WIZARD_POV_TORBOX_USAGE_UI_v3",
        "anchor": "\t\t\tappend('[B]Downloaded[/B]: %s' % account_info['total_downloaded'])",
        "action": "append_after",
        "hook": (
            "\t\t\timport sys, xbmcvfs\n"
            "\t\t\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "\t\t\tsys.path.append(p) if p not in sys.path else None\n"
            "\t\t\timport pov_torbox_usage\n"
            "\t\t\tkodi_utils.hide_busy_dialog()\n"
            "\t\t\treturn pov_torbox_usage.show_textviewer_and_exit(self, account_info)\n"
        )
    },
    {
        "id": "pov_trakt_empty_cache_fix",
        "name": "Trakt Empty Cache Prevention",
        "description": "Prevents transient empty Trakt API responses from being permanently cached.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/caches/trakt_cache.py",
        "marker": "# WIZARD_POV_TRAKT_EMPTY_CACHE_v3",  # Bumped marker version due to anchor change
        "anchor": "dbcur.execute(TC_BASE_SET, (string, json.dumps(result)))",
        "action": "prepend_before",
        "hook": (
        "\timport sys, xbmcvfs\n"
        "\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
        "\tsys.path.append(p) if p not in sys.path else None\n"
        "\timport pov_trakt_cache\n"
        "\tif pov_trakt_cache.is_empty_result(result, string): return result\n"
        )
    },
    {
        "id": "pov_trakt_table_clear_guard",
        "name": "Trakt Cache Table Creation Guard",
        "description": "Ensures trakt_data table exists before the clear loop, preventing silent deletion failures.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/caches/trakt_cache.py",
        "marker": "# WIZARD_POV_TRAKT_TABLE_CLEAR_v3",
        "anchor": "def clear_all_trakt_cache_data(refresh=True):",
        "action": "append_after",
        "hook": (
        "# WIZARD: Ensure trakt_data table exists before clearing cache\n"
        "\ttry:\n"
        "\t\tTraktCache().dbcur.execute('CREATE TABLE IF NOT EXISTS trakt_data (id TEXT UNIQUE, data TEXT)')\n"
        "\texcept Exception: pass\n"
        )
    },
    {
        "id": "wizard_pov_view_mode_fix",
        "name": "Persistent View Mode Patcher",
        "description": "Fixes the intermittent bug where navigating to a new page resets the view to a plain list instead of the user's chosen view.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/modules/kodi_utils.py",
        "marker": "# WIZARD_POV_VIEW_MODE_FIX_v2",
        "anchor": "for _ in range(60):",
        "action": "prepend_before",
        "hook": (
            "import sys, xbmcvfs\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "sys.path.append(p) if p not in sys.path else None\n"
            "import pov_view_mode\n"
            "pov_view_mode.force_view(view_id, content)\n"
            "return\n"
        )
    },
    {
        "id": "pov_addon_window_import",
        "name": "POV Addon Window Patcher (Import Scope)",
        "description": "Waits out Kodi's unknown-addon window on import to prevent background service death.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/modules/kodi_utils.py",
        "marker": "# WIZARD_POV_ADDON_WINDOW_IMPORT_v2",
        "anchor": "from xbmcaddon import Addon",
        "action": "append_after",
        "hook": (
            "import sys, xbmcvfs\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "sys.path.append(p) if p not in sys.path else None\n"
            "import pov_addon_window\n"
            "pov_addon_window.wait_for_window()"
        )
    },
    {
        "id": "pov_addon_window_func",
        "name": "POV Addon Window Patcher (Function Scope)",
        "description": "Shadows addon() to retry fetching the addon object during the restart window.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/modules/kodi_utils.py",
        "marker": "# WIZARD_POV_ADDON_WINDOW_FUNC_v2",
        "anchor": "def addon_installed(addon_id):",
        "action": "prepend_before",
        "hook": (
            "def addon(addon_id='plugin.video.pov'):\n"
            "\timport sys, xbmcvfs\n"
            "\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "\tsys.path.append(p) if p not in sys.path else None\n"
            "\timport pov_addon_window\n"
            "\treturn pov_addon_window.safe_addon(addon_id)\n\n"
        )
    },
    {
        "id": "wizard_pov_widget_refresh",
        "name": "Home Widget Refresh Ping (retired)",
        "description": "Retired after the Container.Refresh -> UpdateLibrary ping caused a field native crash on Trakt add; stock Container.Refresh remains.",
        "addon_id": "plugin.video.pov",
        "enabled": False,
        "target_file": "resources/lib/modules/kodi_utils.py",
        "marker": "# WIZARD_POV_WIDGET_REFRESH_v2",
        "anchor": "return execute_builtin('Container.Refresh')",
        "action": "prepend_before",
        "hook": (
            "import sys, xbmcvfs\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "sys.path.append(p) if p not in sys.path else None\n"
            "import kodi_widget_refresh\n"
            "kodi_widget_refresh.ping()\n"
        )
    },
    {
        "id": "wizard_pov_combined_discover",
        "name": "Unified Discover Builder",
        "description": "Injects a unified Movie+TV search and trending data source for skin integrations like AF3.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/menus/tmdb.py",
        "marker": "# WIZARD_POV_COMBINED_DISCOVER_v3",
        "anchor": "return tmdb_api.list_details(self.list_id)",
        "action": "prepend_before",
        "hook": (
            "import sys, xbmcvfs\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "sys.path.append(p) if p not in sys.path else None\n"
            "import pov_combined_discover\n"
            "_pov_res = pov_combined_discover.handle_fetch(self.params)\n"
            "if _pov_res is not None: return _pov_res\n"
        )
    },
    {
        "id": "pov_network_id_fix",
        "name": "POV Movie Streaming Tile Fix",
        "description": "Shadows tmdb_movies_networks mapping to prevent Kodi hanging on streaming tiles.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/menus/movies.py",
        "marker": "# WIZARD_POV_NETWORK_ID_FIX_v2",
        "anchor": "\ttmdb_special_key_dict = {'tmdb_movies_networks': 'company', 'tmdb_movies_year': 'year', 'tmdb_moviesanime_year': 'year'}",
        "action": "append_after",
        "hook": (
            "\ttmdb_special_key_dict['tmdb_movies_networks'] = 'network_id'"
        )
    },
    {
      "id": "wizard_pov_logger_enable_movies",
      "name": "Content Logger Enable (Movies)",
      "description": "Installs the exception tracer before run() builds any items.",
      "addon_id": "plugin.video.pov",
      "enabled": False,
      "target_file": "resources/lib/menus/movies.py",
      "marker": "# WIZARD_POV_LOGGER_ENABLE_MOVIES_v2",
      "anchor": "\t\t\tparams_get = self.params.get",
      "action": "prepend_before",
      "hook": (
        "import sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); "
        "sys.path.append(p) if p not in sys.path else None; import pov_content_logger; pov_content_logger.enable()"
      )
    },
    {
      "id": "wizard_pov_logger_disable_movies",
      "name": "Content Logger Disable (Movies)",
      "description": "Tears down the exception tracer once run() finishes.",
      "addon_id": "plugin.video.pov",
      "enabled": False,
      "target_file": "resources/lib/menus/movies.py",
      "marker": "# WIZARD_POV_LOGGER_DISABLE_MOVIES_v2",
      "anchor": "\t\tkodi_utils.set_view_mode(view_type, content_type, self.is_widget)",
      "action": "append_after",
      "hook": (
        "import sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); "
        "sys.path.append(p) if p not in sys.path else None; import pov_content_logger; pov_content_logger.disable()"
      )
    },
    {
      "id": "wizard_pov_logger_enable_tvshows",
      "name": "Content Logger Enable (TV Shows)",
      "description": "Installs the exception tracer before run() builds any items.",
      "addon_id": "plugin.video.pov",
      "enabled": False,
      "target_file": "resources/lib/menus/tvshows.py",
      "marker": "# WIZARD_POV_LOGGER_ENABLE_TVSHOWS_v2",
      "anchor": "\t\t\tparams_get = self.params.get",
      "action": "prepend_before",
      "hook": (
        "import sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); "
        "sys.path.append(p) if p not in sys.path else None; import pov_content_logger; pov_content_logger.enable()"
      )
    },
    {
      "id": "wizard_pov_logger_disable_tvshows",
      "name": "Content Logger Disable (TV Shows)",
      "description": "Tears down the exception tracer once run() finishes.",
      "addon_id": "plugin.video.pov",
      "enabled": False,
      "target_file": "resources/lib/menus/tvshows.py",
      "marker": "# WIZARD_POV_LOGGER_DISABLE_TVSHOWS_v2",
      "anchor": "\t\tkodi_utils.set_view_mode(view_type, content_type, self.is_widget)",
      "action": "append_after",
      "hook": (
        "import sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); "
        "sys.path.append(p) if p not in sys.path else None; import pov_content_logger; pov_content_logger.disable()"
      )
    },
    {
      "id": "wizard_pov_logger_enable_episodes",
      "name": "Content Logger Enable (Episodes)",
      "description": "Installs the exception tracer before run() builds any items.",
      "addon_id": "plugin.video.pov",
      "enabled": False,
      "target_file": "resources/lib/menus/episodes.py",
      "marker": "# WIZARD_POV_LOGGER_ENABLE_EPISODES_v3",
      "anchor": "\tparams_get = self.params.get",
      "action": "prepend_before",
      "hook": (
        "import sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); "
        "sys.path.append(p) if p not in sys.path else None; import pov_content_logger; pov_content_logger.enable()"
      )
    },
    {
      "id": "wizard_pov_logger_disable_episodes",
      "name": "Content Logger Disable (Episodes)",
      "description": "Tears down the exception tracer once run() finishes (episodes.py's run() ends at the focus_index line, not set_view_mode).",
      "addon_id": "plugin.video.pov",
      "enabled": False,
      "target_file": "resources/lib/menus/episodes.py",
      "marker": "# WIZARD_POV_LOGGER_DISABLE_EPISODES_v3",
      "anchor": "\tif index: kodi_utils.focus_index(index)",
      "action": "append_after",
      "hook": (
        "import sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); "
        "sys.path.append(p) if p not in sys.path else None; import pov_content_logger; pov_content_logger.disable()"
      )
    },
    {
      "id": "wizard_pov_my_lists_movies",
      "name": "My Lists Dispatch Hook (Movies)",
      "description": "Populates self.list for tmdb_my_movies / trakt_my_movies by merging TMDB favorites+watchlist or Trakt collection+watchlist+favorites, before POV's own dispatch chain runs (and no-ops for every other action).",
      "addon_id": "plugin.video.pov",
      "enabled": True,
      "target_file": "resources/lib/menus/movies.py",
      "marker": "# WIZARD_POV_MY_LISTS_MOVIES_v3",
      "anchor": "\t\t\texcept ValueError: page_no = params_get('new_page')",
      "action": "append_after",
      "hook": (
        "import sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); "
        "sys.path.append(p) if p not in sys.path else None; import pov_my_lists; pov_my_lists.maybe_populate_movies(self, page_no)"
      )
    },
    {
      "id": "wizard_pov_my_lists_tvshows",
      "name": "My Lists Dispatch Hook (TV Shows)",
      "description": "Populates self.list for tmdb_my_tvshows / trakt_my_tvshows by merging TMDB favorites+watchlist or Trakt collection+watchlist+favorites, before POV's own dispatch chain runs (and no-ops for every other action).",
      "addon_id": "plugin.video.pov",
      "enabled": True,
      "target_file": "resources/lib/menus/tvshows.py",
      "marker": "# WIZARD_POV_MY_LISTS_TVSHOWS_v3",
      "anchor": "\t\t\texcept ValueError: page_no = params_get('new_page')",
      "action": "append_after",
      "hook": (
        "import sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); "
        "sys.path.append(p) if p not in sys.path else None; import pov_my_lists; pov_my_lists.maybe_populate_tvshows(self, page_no)"
      )
    },
    {
        "id": "pov_debrid_status",
        "name": "Debrid Expiry Notification Override",
        "description": "Dynamically disables POV's upstream generic debrid notification in memory to prevent duplication with the custom build's Hebrew UI toasts.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/service.py",
        "marker": "# WIZARD_POV_DEBRID_STATUS_v2",
        "anchor": "\t__import__('entry').SettingsMonitor()()",
        "action": "prepend_before",
        "hook": (
            "import sys, xbmcvfs;\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "sys.path.append(p) if p not in sys.path else None;\n"
            "import pov_debrid_status;\n"
            "pov_debrid_status.run(locals())\n"
        )
    },
    {
        "id": "pov_custom_debrid_toasts",
        "name": "Custom Debrid Startup Toasts",
        "description": "Fires Hebrew-localized, icon-aware Debrid subscription status notifications when Kodi starts, replacing the generic upstream toasts.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/service.py",
        "marker": "# WIZARD_POV_CUSTOM_DEBRID_TOASTS_v2",
        "anchor": "\t__import__('entry').SettingsMonitor()()",
        "action": "prepend_before",
        "hook": (
            "\timport sys, xbmcvfs, threading;\n"
            "\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "\tsys.path.append(p) if p not in sys.path else None;\n"
            "\timport pov_custom_debrid_toasts;\n"
            "\tthreading.Thread(target=pov_custom_debrid_toasts.run, args=(locals(),)).start()\n"
        )
    },
    {
        "id": "wizard_fav_refresh_manage",
        "name": "Favorites Refresh (List Manager)",
        "description": "Forces the UI container to refresh immediately when adding a title to TMDB/Trakt/MDBList, preventing stale views.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/list_helper.py",
        "marker": "# WIZARD_FAV_REFRESH_MANAGE_v2",
        "anchor": "return self.execute_toggle(choice, action_add)",
        "action": "prepend_before",
        "hook": (
            "import sys, xbmcvfs;\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "sys.path.append(p) if p not in sys.path else None;\n"
            "import pov_fav_refresh_manage;\n"
            "return pov_fav_refresh_manage.run(locals())"
        )
    },
    {
        "id": "wizard_fav_refresh_dialog",
        "name": "Favorites Refresh (Local Dialogs)",
        "description": "Forces the UI container to refresh immediately when adding/removing a title to POV-local favorites, preventing stale views. Guards against search crashes.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/modules/dialogs.py",
        "marker": "# WIZARD_FAV_REFRESH_DIALOG_v3",
        "anchor": "if refresh: container_refresh()",
        "action": "prepend_before",
        "hook": (
            "\trefresh = 'search' not in (__import__('xbmc').getInfoLabel('Container.FolderPath') or '').lower()\n"
        )
    },
    {
        "id": "pov_ad_unbound_guard",
        "name": "POV AllDebrid Unbound Guard",
        "description": "Prevents crash in except block by ensuring torrent_id is bound.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/alldebrid_api.py",
        "marker": "# WIZARD_POV_AD_UNBOUND_GUARD_v2",
        "anchor": "from modules.source_utils import supported_video_extensions",
        "action": "append_after",
        "hook": (
            "torrent_id = None\n"
            "import sys, xbmcvfs\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "sys.path.append(p) if p not in sys.path else None\n"
            "import pov_debrid_guardian\n"
            "pov_debrid_guardian.log_guard_active('alldebrid')"
        )
    },
    {
        "id": "pov_rd_unbound_guard",
        "name": "POV RealDebrid Unbound Guard",
        "description": "Prevents crash in except block by ensuring torrent_id is bound.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/realdebrid_api.py",
        "marker": "# WIZARD_POV_RD_UNBOUND_GUARD_v2",
        "anchor": "from modules.source_utils import supported_video_extensions",
        "action": "append_after",
        "hook": (
            "torrent_id = None\n"
            "import sys, xbmcvfs\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "sys.path.append(p) if p not in sys.path else None\n"
            "import pov_debrid_guardian\n"
            "pov_debrid_guardian.log_guard_active('realdebrid')"
        )
    },
    {
        "id": "pov_tb_unbound_guard",
        "name": "POV TorBox Unbound Guard",
        "description": "Prevents crash in except block by ensuring path and torrent_id are bound.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/torbox_api.py",
        "marker": "# WIZARD_POV_TB_UNBOUND_GUARD_v2",
        "anchor": "from modules.source_utils import supported_video_extensions",
        "action": "append_after",
        "hook": (
            "\t\tpath = None\n"
            "\t\ttorrent_id = None\n"
            "\t\timport sys, xbmcvfs\n"
            "\t\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "\t\tsys.path.append(p) if p not in sys.path else None\n"
            "\t\timport pov_debrid_guardian\n"
            "\t\tpov_debrid_guardian.log_guard_active('torbox')\n"
        )
    },
    {
        "id": "pov_torbox_url_fix_indexers",
        "name": "POV TorBox Malformed URL Fix (Indexers)",
        "addon_id": "plugin.video.pov", "enabled": True,
        "target_file": "resources/lib/indexers/torbox_api.py",
        "marker": "# WIZARD_POV_TORBOX_URL_FIX_v4",
        "anchor": "if user_ip: params['user_ip'] = user_ip",
        "action": "append_after",
        "hook": "import sys, xbmcvfs\np = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\nif p not in sys.path: sys.path.append(p)\nimport pov_torbox_url_fix\nraw = self.api('get', path, params=params) if hasattr(self, 'api') else self._get(path, params=params)\nreturn pov_torbox_url_fix.safe_url(raw)"
    },
    {
        "id": "pov_ad_error_log",
        "name": "POV AllDebrid Error Log",
        "description": "Logs AllDebrid HTTP 200 soft-errors before POV swallows them.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/alldebrid_api.py",
        "marker": "# WIZARD_POV_AD_ERROR_LOG_v3",
        "anchor": "response = response.json() if 'json' in response.headers.get('Content-Type', '') else response",
        "alternatives": [{"anchor": "response = response.json()"}],
        "action": "append_after",
        "hook": (
            "import sys, xbmcvfs\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "sys.path.append(p) if p not in sys.path else None\n"
            "import pov_debrid_guardian\n"
            "pov_debrid_guardian.log_debrid_error('alldebrid', response, locals().get('path', ''))"
        )
    },
    {
        "id": "pov_tb_error_log",
        "name": "POV TorBox Error Log",
        "description": "Logs TorBox HTTP 200 soft-errors before POV swallows them.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/torbox_api.py",
        "marker": "# WIZARD_POV_TB_ERROR_LOG_v3",
        "anchor": "response = response.json() if 'json' in response.headers.get('Content-Type', '') else response",
        "alternatives": [{"anchor": "response = response.json()"}],
        "action": "append_after",
        "hook": (
            "\t\timport sys, xbmcvfs\n"
            "\t\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "\t\tsys.path.append(p) if p not in sys.path else None\n"
            "\t\timport pov_debrid_guardian\n"
            "\t\tpov_debrid_guardian.log_debrid_error('torbox', response, locals().get('path', ''))\n"
        )
    },
    {
        "id": "pov_pm_error_log",
        "name": "POV Premiumize Error Log",
        "description": "Logs Premiumize HTTP 200 soft-errors before POV swallows them.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/premiumize_api.py",
        "marker": "# WIZARD_POV_PM_ERROR_LOG_v3",
        "anchor": "result = self._post(url, data)",
        "alternatives": [{"anchor": "return response.json()", "action": "prepend_before",
                         "hook": "import sys, xbmcvfs\np = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\nif p not in sys.path: sys.path.append(p)\nimport pov_debrid_guardian\npov_debrid_guardian.log_debrid_error('premiumize', response.json(), path)"}],
        "action": "append_after",
        "hook": (
            "import sys, xbmcvfs\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "sys.path.append(p) if p not in sys.path else None\n"
            "import pov_debrid_guardian\n"
            "pov_debrid_guardian.log_debrid_error('premiumize', result, locals().get('url', ''))"
        )
    },
    {
        "id": "pov_debrid_timeout",
        "name": "Debrid Timeout Resiliency",
        "description": "Prevents source erasure when a debrid provider times out by injecting unconfirmed tuples.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/modules/sources.py",
        "marker": "# WIZARD_POV_DEBRID_TIMEOUT_v3",
        "anchor": "self.monitor(threads, debrid_format, True)",
        "action": "append_after",
        "hook": (
            "\t\t\timport sys, xbmcvfs\n"
            "\t\t\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "\t\t\tif p not in sys.path: sys.path.append(p)\n"
            "\t\t\timport pov_debrid_timeout\n"
            "\t\t\tpov_debrid_timeout.run(self, threads, torrent_sources)\n"
        )
    },
    {
        "id": "pov_provider_rank",
        "name": "Unknown Provider Crash Guard",
        "description": "Intercepts sort ranking to prevent KeyErrors on unregistered 3rd party providers.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/modules/sources.py",
        "marker": "# WIZARD_POV_PROVIDER_RANK_v2",
        "anchor": "return self.source.provider_sort_ranks[account_type] or 11",
        "action": "prepend_before",
        "hook": "return self.source.provider_sort_ranks.get(account_type) or 11\n"
    },
    {
        "id": "pov_heb_prewarm",
        "name": "Hebrew Subtitles Prewarm",
        "description": "Triggers background subtitle cache pre-warming concurrently with video scraping.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/modules/sources.py",
        "marker": "# WIZARD_POV_HEB_PREWARM_v2",
        "anchor": "results = self.get_sources()",
        "action": "prepend_before",
        "hook": (
            "import sys, xbmcvfs;\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "sys.path.append(p) if p not in sys.path else None;\n"
            "import pov_prewarm;\n"
            "pov_prewarm.run(self.meta)\n"
        )
    },
    {
        "id": "pov_playback_capture",
        "name": "Source Name Stash & Playback Capture",
        "description": "Stashes played source names into Window properties and captures source for re-selection.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/modules/sources.py",
        "marker": "# WIZARD_POV_PLAYBACK_CAPTURE_v4",
        "anchor": "return POVPlayer().run(link, self.meta, progress_media)",
        "alternatives": [{"anchor": "return POVPlayer().run(link, item.get('name'), self.meta, progress_media)"}],
        "action": "prepend_before",
        "hook": (
            "\timport sys, xbmcvfs;\n"
            "\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "\tsys.path.append(p) if p not in sys.path else None;\n"
            "\timport pov_source_remember;\n"
            "\tpov_source_remember.run_capture(self, item, link)\n"
        )
    },
    {
        "id": "pov_reorder_sources",
        "name": "Remember Source Auto-Pick Reorder",
        "description": "Moves previously picked sources to the top of the UI list with a visual marker.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/modules/sources.py",
        "marker": "# WIZARD_POV_REORDER_SOURCES_v3",
        "anchor": "window_style = results_xml_style()",
        "action": "prepend_before",
        "hook": (
            "\timport sys, xbmcvfs;\n"
            "\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "\tsys.path.append(p) if p not in sys.path else None;\n"
            "\timport pov_source_remember;\n"
            "\tpov_source_remember.run_reorder(self, results)\n"
        )
    },
    {
        "id": "pov_legacy_scrapers",
        "name": "Legacy Internal Scrapers Support",
        "description": "Restores loading of 3rd-party scrapers from the old resources/lib/scrapers/ directory without import failures.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/modules/sources.py",
        "marker": "# WIZARD_POV_LEGACY_SCRAPERS_v3",
        "anchor": "for loader, module_name, is_pkg in pkgutil.iter_modules([source_path]):",
        "action": "prepend_before",
        "hook": (
            "\t\timport sys, xbmcvfs\n"
            "\t\t_p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "\t\tif _p not in sys.path: sys.path.append(_p)\n"
            "\t\timport pov_legacy_scrapers\n"
            "\t\tpov_legacy_scrapers.run(self, source_path, append, prescrape)\n"
        )
    },
    {
        "id": "pov_resolve_diag",
        "name": "Debrid Resolve Diagnostics",
        "description": "Expands opaque selected_files exceptions to include file counts and filter rejection details.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/modules/debrid.py",
        "marker": "# WIZARD_POV_RESOLVE_DIAG_v2",
        "anchor": "if not selected_files: raise Exception('selected_files failed')",
        "action": "prepend_before",
        "hook": (
            "import sys, xbmcvfs;\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "sys.path.append(p) if p not in sys.path else None;\n"
            "import pov_resolve_diag;\n"
            "pov_resolve_diag.run(self, files, selected_files)\n"
        )
    },
    {
        "id": "pov_debrid_error_guard",
        "name": "Debrid Timeout Error Guard",
        "description": "Safely wraps direct provider cache checks, returning a tuple on timeout to preserve checked states.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/modules/debrid.py",
        "marker": "# WIZARD_POV_DEBRID_ERROR_GUARD_v2",
        "anchor": "if self.debrid in ('rd', 'realdebrid'):",
        "action": "prepend_before",
        "hook": (
            "import sys, xbmcvfs;\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "sys.path.append(p) if p not in sys.path else None;\n"
            "import pov_debrid_error_guard;\n"
            "_wiz_res = pov_debrid_error_guard.run(self, unchecked_hashes);\n"
            "if _wiz_res is not None: return _wiz_res\n"
        )
    },
    {
        "id": "pov_trakt_reauth_recovery",
        "name": "Trakt 401 Reauth Recovery",
        "description": "Intercepts Trakt 401 Unauthorized errors and safely refreshes token instead of dropping syncs for 30 mins.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/trakt_api.py",
        "marker": "# WIZARD_POV_TRAKT_REAUTH_v2",
        "anchor": "def trakt_sync_activities(force_update=False, init_callback=None, monitor=None):",
        "action": "prepend_before",
        "hook": (
            "import sys, xbmcvfs\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "sys.path.append(p) if p not in sys.path else None\n"
            "import pov_trakt_reauth\n"
            "pov_trakt_reauth.run(sys.modules[__name__])\n"
        )
    },
    {
        "id": "pov_http_lazy_tmdb",
        "name": "TMDb HTTP Lazy Import",
        "description": "Defers requests module initialization on cold boot to speed up widgets.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/tmdb_api.py",
        "marker": "# WIZARD_POV_HTTP_LAZY_TMDB_v3",
        "anchor": "import requests",
        "alternatives": [{"anchor": "from session import session, HTTPAdapter, Retry", "superseded": True}],
        "action": "prepend_before",
        "hook": (
            "import sys, xbmcvfs\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "sys.path.append(p) if p not in sys.path else None\n"
            "import pov_http_lazy\n"
            "pov_http_lazy.run()\n"
        )
    },
    {
        "id": "pov_http_lazy_trakt",
        "name": "Trakt HTTP Lazy Import",
        "description": "Defers requests module initialization on cold boot to speed up widgets.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/trakt_api.py",
        "marker": "# WIZARD_POV_HTTP_LAZY_TRAKT_v3",
        "anchor": "import requests",
        "alternatives": [{"anchor": "from session import session, HTTPAdapter, Retry", "superseded": True}],
        "action": "prepend_before",
        "hook": (
            "import sys, xbmcvfs\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "sys.path.append(p) if p not in sys.path else None\n"
            "import pov_http_lazy\n"
            "pov_http_lazy.run()\n"
        )
    },
    {
        "id": "pov_source_quality_fix",
        "name": "POV Source Quality Badge Fix",
        "description": "Corrects SD badges for sources that are actually HD/4K based on release names and re-sorts them.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/windows/sources.py",
        "marker": "# WIZARD_POV_SOURCE_QUALITY_v2",
        "anchor": "for count, item in enumerate(self.results, 1):",
        "action": "prepend_before",
        "hook": (
            "import sys, xbmcvfs;\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "sys.path.append(p) if p not in sys.path else None;\n"
            "import pov_source_quality_v2;\n"
            "pov_source_quality_v2.run(locals())"
        )
    },
    {
        "id": "pov_subtitle_match_percent",
        "name": "POV Subtitle Match Percentage",
        "description": "Prepends Hebrew subtitle match percentage to the source size label.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/windows/sources.py",
        "marker": "# WIZARD_POV_SUB_MATCH_v2",
        "anchor": "set_property('tikiskins.size_label', get('size_label', 'N/A'))",
        "action": "append_after",
        "hook": (
            "import sys, xbmcvfs;\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "sys.path.append(p) if p not in sys.path else None;\n"
            "import pov_sub_match_v2;\n"
            "pov_sub_match_v2.run(locals())"
        )
    },
    {
        "id": "pov_subtitle_match_refresh",
        "name": "POV Late Subtitle Badges",
        "addon_id": "plugin.video.pov", "enabled": True,
        "target_file": "resources/lib/windows/sources.py",
        "marker": "# WIZARD_POV_SUB_MATCH_REFRESH_v1",
        "anchor": "self.win.addItems(self.item_list)",
        "action": "append_after",
        "hook": "import sys, xbmcvfs\np = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\nif p not in sys.path: sys.path.append(p)\nimport pov_sub_match_v2\npov_sub_match_v2.refresh_when_ready(self)"
    },
    {
        "id": "pov_navigator_read_fix",
        "name": "POV Navigator DB Parse Interceptor",
        "description": "Intercepts jsloads on navigator cache to fallback to AST literal evaluation for legacy repr-formatted DB rows.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/caches/navigator_cache.py",
        "marker": "# WIZARD_POV_NAV_READ_FIX_v2",
        "anchor": "navigator_cache = NavigatorCache()",
        "action": "append_after",
        "hook": (
            "import sys, xbmcvfs;\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "sys.path.append(p) if p not in sys.path else None;\n"
            "import pov_nav_read_fix;\n"
            "pov_nav_read_fix.run(navigator_cache)"
        )
    },
    {
        "id": "pov_aiostreams_credentials_fix",
        "name": "POV AIOStreams Credentials Guard",
        "description": "Prevents AIOStreams from swallowing all scrapes when enabled but missing user credentials.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/modules/settings.py",
        "marker": "# WIZARD_POV_AIOSTREAMS_FIX_v4",
        "anchor": "\tsettings.extend(item[1] for item in (",
        "action": "prepend_before",
        "hook": (
            "\timport sys, xbmcvfs\n"
            "\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "\tif p not in sys.path: sys.path.append(p)\n"
            "\timport pov_aiostreams_fix\n"
            "\tsettings = pov_aiostreams_fix.enforce_credentials(settings)\n"
            "\timport pov_legacy_scrapers\n"
            "\tsettings = pov_legacy_scrapers.enabled_settings(settings)"
        )
    },
    {
        "id": "mdblist_api_redact_and_reauth_prep",
        "name": "MDBList API Redact Log",
        "description": "Redacts API keys in logs via exception class shadowing.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/mdblist_api.py",
        "marker": "# WIZARD_POV_MDBL_REAUTH_PREP_v2",
        "anchor": "\t\tlogger('mdblist error', str(e))",
        "action": "prepend_before",
        "hook": (
            "\t\t_orig_e = e; e = type('RedactedE', (Exception,), {'__str__': lambda s: __import__('re').sub(r'apikey=[^&\\s]+', 'apikey=***', str(_orig_e)), 'response': getattr(_orig_e, 'response', None)})();\n"
        )
    },
    {
        "id": "mdblist_api_reauth_retry",
        "name": "MDBList API 401 Reauth Retry",
        "description": "Transparently recovers from expired MDBList tokens on 401.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/mdblist_api.py",
        "marker": "# WIZARD_POV_MDBL_REAUTH_RETRY_v3",
        "anchor": "\t\tlogger('mdblist error', str(e))",
        "action": "append_after",
        "hook": (
            "\t\timport sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); sys.path.append(p) if p not in sys.path else None; import pov_mdblist_patch_logic;\n"
            "\t\t_ai_retry = pov_mdblist_patch_logic.handle_401_reauth(_orig_e, path, params, json, method, locals().get('response'));\n"
            "\t\tif _ai_retry is not None: return _ai_retry\n"
        )
    },
    {
        "id": "mdblist_cache_verified_reads",
        "name": "MDBList cache verified reads",
        "description": "Do not cache failed reads; recover legacy empty caches without changing account data.",
        "addon_id": "plugin.video.pov", "enabled": True,
        "target_file": "resources/lib/caches/mdbl_cache.py",
        "marker": "# WIZARD_POV_MDBL_CACHE_READS_v1",
        "anchor": "\tdbcur = MDBLCache().dbcur",
        "action": "prepend_before",
        "hook": "\timport sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); sys.path.append(p) if p not in sys.path else None; import pov_mdblist_patch_logic\n\treturn pov_mdblist_patch_logic.cache_list(function, string, url)\n"
    },
    {
        "id": "mdblist_response_pagination",
        "name": "MDBList bucketed response pagination",
        "description": "Preserve pagination headers for collection and watchlist JSON objects as well as native arrays.",
        "addon_id": "plugin.video.pov", "enabled": True,
        "target_file": "resources/lib/indexers/mdblist_api.py",
        "marker": "# WIZARD_POV_MDBL_RESPONSE_PAGES_v1",
        "anchor": "\t\tif isinstance(result, list):", "action": "prepend_before",
        "hook": "\t\timport sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); sys.path.append(p) if p not in sys.path else None; import pov_mdblist_patch_logic\n\t\tresult = pov_mdblist_patch_logic.list_response_pagination(result, response)\n"
    },
    {
        "id": "mdblist_complete_pagination",
        "name": "MDBList complete pagination",
        "description": "Reject unavailable or incomplete pages rather than reporting an empty list.",
        "addon_id": "plugin.video.pov", "enabled": True,
        "target_file": "resources/lib/indexers/mdblist_api.py",
        "marker": "# WIZARD_POV_MDBL_PAGES_v1",
        "anchor": "\tparams = {'limit': 1000}", "action": "prepend_before",
        "hook": "\timport sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); sys.path.append(p) if p not in sys.path else None; import pov_mdblist_patch_logic\n\treturn pov_mdblist_patch_logic.paginated_list(url, MAX_LIST_ITEMS)\n"
    },
    {
        "id": "mdblist_manager_read_failure",
        "name": "MDBList manager read failure",
        "description": "Keep failed authorization out of the add/remove selection flow.",
        "addon_id": "plugin.video.pov", "enabled": True,
        "target_file": "resources/lib/menus/mdblist.py",
        "marker": "# WIZARD_POV_MDBL_MANAGER_READ_v1",
        "anchor": "class MdbListManager(list_helper.BaseListManager):", "action": "append_after",
        "hook": "# Guard only MDBList reads; keep native mutations.\n\tdef manage(self):\n\t\timport sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); sys.path.append(p) if p not in sys.path else None; import pov_mdblist_patch_logic\n\t\ttry: return super().manage()\n\t\texcept pov_mdblist_patch_logic.MDBListUnavailable:\n\t\t\treturn pov_mdblist_patch_logic.notify_unavailable()\n\n"
    },
    {
        "id": "mdblist_api_scrobble_stop",
        "name": "MDBList Watch Scrobble Fix",
        "description": "Clears MDBList paused state when marking as watched.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/mdblist_api.py",
        "marker": "# WIZARD_POV_MDBL_SCROBBLE_STOP_v2",
        "anchor": "\tsuccess = result[result_key][success_key] > 0",
        "action": "append_after",
        "hook": (
            "\timport sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); sys.path.append(p) if p not in sys.path else None; import pov_mdblist_patch_logic;\n"
            "\tpov_mdblist_patch_logic.scrobble_stop_if_watched(action, key, media, media_id, season, episode)\n"
        )
    },
    {
        "id": "mdblist_activity_failed_read",
        "name": "MDBList failed activity read",
        "description": "Preserve watched and progress data when authorization or the network fails.",
        "addon_id": "plugin.video.pov", "enabled": True,
        "target_file": "resources/lib/indexers/mdblist_api.py",
        "marker": "# WIZARD_POV_MDBL_ACTIVITY_READ_v1",
        "anchor": "\t\tlogger('mdblist error', str(latest))", "action": "append_after",
        "hook": "\t\treturn 'failed'\n"
    },
    {
        "id": "mdblist_api_add_to_list_guard",
        "name": "MDBList Add to List Guard",
        "description": "Prevents crash on 404 when adding to list.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/mdblist_api.py",
        "marker": "# WIZARD_POV_MDBL_ADD_LIST_GUARD_v2",
        "anchor": "\tif result['added']['movies'] + result['added']['shows'] == 0: return kodi_utils.notify_failed()",
        "action": "prepend_before",
        "hook": "\tif not result: return kodi_utils.notify_failed()\n"
    },
    {
        "id": "mdblist_api_add_to_coll_guard",
        "name": "MDBList Add to Collection Guard",
        "description": "Prevents crash on 404 when adding to collection.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/mdblist_api.py",
        "marker": "# WIZARD_POV_MDBL_ADD_COLL_GUARD_v2",
        "anchor": "\tif result['updated']['movies'] + result['updated']['shows'] == 0: return kodi_utils.notify_failed()",
        "action": "prepend_before",
        "hook": "\tif not result: return kodi_utils.notify_failed()\n"
    },
    {
        "id": "mdblist_api_sync_guard",
        "name": "MDBList Sync Tuple Crash Fix",
        "description": "Prevents reset_activity tuple indices string crash.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/mdblist_api.py",
        "marker": "# WIZARD_POV_MDBL_SYNC_GUARD_v2",
        "anchor": "\tcached = mdbl_cache.reset_activity(latest)",
        "action": "append_after",
        "hook": (
            "\tif not isinstance(cached, dict) or not isinstance(latest, dict):\n"
            "\t\ttry: mdbl_cache.clear_all_mdbl_cache_data(refresh=False)\n"
            "\t\texcept: pass\n"
            "\t\treturn 'failed'\n"
        )
    },
    {
        "id": "mdblist_api_merge_collection",
        "name": "MDBList Merge Collection to Watchlist",
        "description": "Injects Trakt Collection items into the Watchlist view.",
        "addon_id": "plugin.video.pov",
        "enabled": False,
        "target_file": "resources/lib/indexers/mdblist_api.py",
        "marker": "# WIZARD_POV_MDBL_MERGE_COLLECTION_v2",
        "anchor": "\tif not settings.show_unaired_watchlist():",
        "action": "prepend_before",
        "hook": (
            "\timport sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); sys.path.append(p) if p not in sys.path else None; import pov_mdblist_patch_logic;\n"
            "\tpov_mdblist_patch_logic.merge_collection_to_watchlist(original_list, mediatype)\n"
        )
    },
    {
        "id": "mdblist_api_like_routes",
        "name": "MDBList Like API Routes",
        "description": "Injects missing MDBList like/unlike context menu logic routes.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/mdblist_api.py",
        "marker": "# WIZARD_POV_MDBL_LIKE_ROUTES_v2",
        "anchor": "def delete_mdbl_list(params):",
        "action": "prepend_before",
        "hook": (
            "def mdbl_like_a_list(params):\n"
            "\timport sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); sys.path.append(p) if p not in sys.path else None; import pov_mdblist_patch_logic; pov_mdblist_patch_logic.like_a_list(params)\n\n"
            "def mdbl_unlike_a_list(params):\n"
            "\timport sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); sys.path.append(p) if p not in sys.path else None; import pov_mdblist_patch_logic; pov_mdblist_patch_logic.unlike_a_list(params)\n\n"
        )
    },
    {
        "id": "mdblist_api_account_heal",
        "name": "MDBList Account State Heal",
        "description": "Repairs broken MDBList OAuth states by recovering missing usernames.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/indexers/mdblist_api.py",
        "marker": "# WIZARD_POV_MDBL_ACCOUNT_HEAL_v2",
        "anchor": "\tif not get_setting('mdblist_user', ''): return 'no account'",
        "action": "prepend_before",
        "hook": (
            "\timport sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); sys.path.append(p) if p not in sys.path else None; import pov_mdblist_patch_logic;\n"
            "\tpov_mdblist_patch_logic.heal_mdblist_account_if_needed()\n"
        )
    },
    {
        "id": "mdblist_menu_manager_watchlist",
        "name": "MDBList Manager Watchlist Only",
        "description": "Hides collection to prevent crashes and stabilize Hebrew IDs.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/menus/mdblist.py",
        "marker": "# WIZARD_POV_MDBL_WATCHLIST_ONLY_v2",
        "anchor": "\t\tchoices = [(i.lower(), i, '', self.icon) for i in (watchl_str, coll_str)]",
        "action": "append_after",
        "hook": "\t\tchoices = [('watchlist', watchl_str, '', self.icon)]\n"
    },
    {
        "id": "mdblist_menu_pre_search",
        "name": "MDBList Search History & Flow",
        "description": "Adds intermediate search screens and fixes blank cancellation flow.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/menus/mdblist.py",
        "marker": "# WIZARD_POV_MDBL_PRE_SEARCH_v2",
        "anchor": "\treturn SearchMdblLists(params).build()",
        "action": "prepend_before",
        "hook": (
            "\timport sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); sys.path.append(p) if p not in sys.path else None; import pov_mdblist_patch_logic;\n"
            "\t_ai_params = pov_mdblist_patch_logic.pre_search_check(params)\n"
            "\tif _ai_params is None: return\n"
            "\tparams.update(_ai_params)\n"
        )
    },
    {
        "id": "mdblist_menu_like_append",
        "name": "MDBList Like Menu Option",
        "description": "Appends Like/Unlike to MDBList context menus natively.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/menus/mdblist.py",
        "marker": "# WIZARD_POV_MDBL_MENU_LIKE_v2",
        "anchor": "\t\t\t\tcm_append((add2menu_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.add_external', 'name': name, 'iconImage': 'mdblist.png'})))",
        "action": "prepend_before",
        "hook": (
            "\t\t\t\timport sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); sys.path.append(p) if p not in sys.path else None; import pov_mdblist_patch_logic;\n"
            "\t\t\t\tpov_mdblist_patch_logic.append_like_menu(cm_append, list_type, list_id)\n"
        )
    },
    {
        "id": "pov_mdblist_sort_default",
        "name": "MDBList Watchlist/Collection Sort Default",
        "description": "Uses newest-added ordering for watchlists and collections; preserves release-date sorting.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/modules/settings.py",
        "marker": "# WIZARD_POV_MDBL_SORT_DEFAULT_v2",
        "anchor": "def metadata_user_info():",
        "action": "prepend_before",
        "hook": (
            "_orig_lists_sort_order = lists_sort_order\n"
            "def lists_sort_order(setting, mediatype=None):\n"
            "\timport sys, xbmcvfs; p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/'); sys.path.append(p) if p not in sys.path else None; import pov_mdblist_patch_logic;\n"
            "\treturn pov_mdblist_patch_logic.lists_sort_order_override(_orig_lists_sort_order, setting, mediatype)\n\n"
        )
    },
    {
        "id": "pov_cache_schema_repair",
        "name": "POV Cache Schema DB Patcher",
        "description": "Rebuilds transposed SQLite cache columns dynamically and migrates legacy databases.",
        "addon_id": "plugin.video.pov",
        "enabled": False,
        "target_file": "resources/lib/modules/cache.py",
        "marker": "# WIZARD_POV_CACHE_SCHEMA_v2",
        "anchor": "\tif not kodi_utils.path_exists(databases_path): kodi_utils.make_directory(databases_path)",
        "action": "prepend_before",
        "hook": (
            "\timport sys, xbmcvfs\n"
            "\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/')\n"
            "\tsys.path.append(p) if p not in sys.path else None\n"
            "\timport pov_cache_schema\n"
            "\tpov_cache_schema.run()\n"
        )
    },
    {
        "id": "pov_widget_budget_movies",
        "name": "POV Widget Rendering Budget (Movies)",
        "description": "Limits the scope of background metadata tasks for movies when rendering on the home screen to optimize speeds.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/menus/movies.py",
        "marker": "# WIZARD_POV_WIDGET_BUDGET_MOVIES_v2",
        "anchor": "kodi_utils.add_items(__handle__, worker())",
        "action": "prepend_before",
        "hook": (
            "\t\t\timport sys, xbmcvfs;\n"
            "\t\t\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "\t\t\tsys.path.append(p) if p not in sys.path else None;\n"
            "\t\t\timport pov_widget_budget;\n"
            "\t\t\tworker = pov_widget_budget.wrap_worker(self, worker)"
        )
    },
    {
        "id": "pov_widget_budget_tvshows",
        "name": "POV Widget Rendering Budget (TV Shows)",
        "description": "Limits the scope of background metadata tasks for TV Shows when rendering on the home screen to optimize speeds.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/menus/tvshows.py",
        "marker": "# WIZARD_POV_WIDGET_BUDGET_TVSHOWS_v2",
        "anchor": "kodi_utils.add_items(__handle__, self.worker())",
        "action": "prepend_before",
        "hook": (
            "\t\t\timport sys, xbmcvfs;\n"
            "\t\t\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "\t\t\tsys.path.append(p) if p not in sys.path else None;\n"
            "\t\t\timport pov_widget_budget;\n"
            "\t\t\tself.worker = pov_widget_budget.wrap_worker(self, self.worker)"
        )
    },
    {
        "id": "pov_bookmark_refresh_order",
        "name": "Fix Bookmark UI Refresh Race Condition",
        "description": "Reorders playback stopping behavior so network syncs complete before the UI refreshes, preventing empty directories.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/caches/watched_cache.py",
        "marker": "# WIZARD_POV_BOOKMARK_REFRESH_LAST_v2",
        "anchor": "if refresh == 'true': kodi_utils.widget_refresh() if kodi_utils.external_browse() else kodi_utils.container_refresh()",
        "action": "prepend_before",
        "hook": (
            "\t\timport sys, xbmcvfs;\n"
            "\t\tp = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "\t\tsys.path.append(p) if p not in sys.path else None;\n"
            "\t\timport bookmark_refresh_order;\n"
            "\t\tbookmark_refresh_order.run(locals(), globals());\n"
            "\t\treturn\n"
        )
    },
    {
        "id": "pov_watched_lazy_mock_v2",
        "name": "Lazy Import Watch Cache (Mock Setup)",
        "description": "Intercepts and mocks heavy API module loads in memory before they are parsed.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/caches/watched_cache.py",
        "marker": "# WIZARD_POV_WATCHED_LAZY_MOCK_v2",
        "anchor": "from caches.mdbl_cache import clear_mdbl_collection_watchlist_data",
        "action": "prepend_before",
        "hook": (
            "import sys, xbmcvfs;\n"
            "p = xbmcvfs.translatePath('special://home/addons/plugin.program.kodipovilwizard/resources/libs/patches/');\n"
            "sys.path.append(p) if p not in sys.path else None;\n"
            "import pov_watched_lazy_imports;\n"
            "pov_watched_lazy_imports.mock_modules();\n"
        )
    },
    {
        "id": "pov_watched_lazy_proxy_v2",
        "name": "Lazy Import Watch Cache (Proxy Shadows)",
        "description": "Shadows dummy globals with functional proxies and restores native import behaviors.",
        "addon_id": "plugin.video.pov",
        "enabled": True,
        "target_file": "resources/lib/caches/watched_cache.py",
        "marker": "# WIZARD_POV_WATCHED_LAZY_PROXY_v2",
        "anchor": "from indexers.trakt_api import trakt_watched_unwatched, trakt_progress, trakt_get_hidden_items, trakt_official_status",
        "action": "append_after",
        "hook": (
            "import pov_watched_lazy_imports;\n"
            "pov_watched_lazy_imports.apply_proxies(globals());\n"
        )
    }
]
