# plugin.program.kodipovilwizard/resources/libs/patches/pov_mdblist_patch_logic.py
# Offloaded execution logic for MDBList patch engine injections.

_AI_MDBL_REFRESH_LOCK = 'pov_ai_mdbl_refreshing'
_ai_liked_ids_cache = [False]

def handle_401_reauth(e, path, params, json_data, method):
    """Intercepts a 401 error, attempts to acquire a GUI lock, refreshes the token, and recurses safely."""
    status = getattr(getattr(e, 'response', None), 'status_code', 0)
    if status != 401: return None
    from resources.lib.modules import kodi_utils
    if not kodi_utils.get_setting('mdblist.refresh', ''): return None

    try:
        import xbmcgui
        window = xbmcgui.Window(10000)
    except Exception:
        window = None

    before = kodi_utils.get_setting('mdblist.token')
    if window is not None:
        from resources.lib.modules.kodi_utils import sleep
        for _ in range(60):
            if window.getProperty(_AI_MDBL_REFRESH_LOCK) != 'true': break
            sleep(250)
        if kodi_utils.get_setting('mdblist.token') != before: return _retry_call(path, params, json_data, method)
        window.setProperty(_AI_MDBL_REFRESH_LOCK, 'true')
        if kodi_utils.get_setting('mdblist.token') != before:
            window.clearProperty(_AI_MDBL_REFRESH_LOCK)
            return _retry_call(path, params, json_data, method)

    try:
        from resources.lib.indexers.mdblist_api import mdbl_refresh
        mdbl_refresh()
    finally:
        if window is not None: window.clearProperty(_AI_MDBL_REFRESH_LOCK)

    if kodi_utils.get_setting('mdblist.token') != before:
        return _retry_call(path, params, json_data, method)
    return None

def _retry_call(path, params, json_data, method):
    from resources.lib.indexers.mdblist_api import session, base_url, timeout
    from resources.lib.modules import kodi_utils
    headers = None
    params = params or {}
    if not bool(kodi_utils.get_setting('mdblist.refresh')):
        params['apikey'] = kodi_utils.get_setting('mdblist.token')
    else:
        headers = {'Authorization': 'Bearer %s' % kodi_utils.get_setting('mdblist.token')}
    try:
        response = session.request(
            method or 'get',
            base_url % path,
            params=params,
            json=json_data,
            headers=headers,
            timeout=timeout
        )
        result = response.json() if 'json' in response.headers.get('Content-Type', '') else response.text
        if not response.ok: response.raise_for_status()
        if isinstance(result, list):
            result = {'items': result, 'pagination': {'has_more': response.headers.get('X-Has-More') == 'true'}}
            if response.headers.get('X-Next-Cursor'): result['pagination']['next_cursor'] = response.headers.get('X-Next-Cursor')
        return result
    except Exception:
        return None

def scrobble_stop_if_watched(action, key, media, media_id, season, episode):
    """Automatically fires the stop scrobble command purely as an additive operation."""
    if action == 'mark_as_watched' and key == 'tmdb' and media in ('movies', 'episode'):
        try:
            from resources.lib.indexers.mdblist_api import call_mdblist
            if media == 'movies':
                sd = {'movie': {'ids': {'tmdb': media_id}}, 'progress': 100.0}
            else:
                sd = {'show': {'ids': {'tmdb': media_id}, 'season': {'number': int(season), 'episode': {'number': int(episode)}}}, 'progress': 100.0}
            call_mdblist('scrobble/stop', json=sd, method='post')
        except Exception: pass

def merge_collection_to_watchlist(original_list, mediatype):
    """Mutates original_list directly by reference to attach unified collection outputs."""
    try:
        from resources.lib.indexers.mdblist_api import mdbl_collection_watchlist_items
        mk = 'movie' if mediatype in ('movie', 'movies') else 'show'
        seen = set(i.get('id') for i in original_list)
        coll = mdbl_collection_watchlist_items('mdbl_collection', 'sync/collection')[mediatype]
        for ci in coll:
            o = ci.get(mk) or {}
            ids = o.get('ids') or {}
            id_ = ids.get('tmdb')
            if not id_ or id_ in seen: continue
            seen.add(id_)
            yr = o.get('year')
            original_list.append({
                'id': id_,
                'imdb_id': ids.get('imdb'),
                'title': o.get('title'),
                'release_date': (('%d-01-01' % yr) if yr else '1900-01-01'),
                'watchlist_at': ci.get('collected_at') or ''
            })
    except Exception: pass

def pre_search_check(params):
    """Intercepts bad state searches, generates navigation GUI for history."""
    if not params.get('search_title') and not params.get('ai_prompt'):
        _mdbl_search_screen(params)
        return None
    if params.get('ai_prompt') and not params.get('search_title'):
        from resources.lib.modules import kodi_utils
        query = kodi_utils.dialog.input('POV')
        if not query:
            import sys, xbmcplugin
            xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=False)
            return None
        try:
            from resources.lib.menus.history import add_to_search_history
            add_to_search_history(query, 'mdbl_list_queries')
        except Exception: pass
        return {'search_title': query}
    return {}

def _mdbl_search_screen(params):
    import sys
    from resources.lib.modules import kodi_utils
    handle = int(sys.argv[1])
    default_icon = kodi_utils.media_path('mdblist.png')
    fanart = kodi_utils.get_addoninfo('fanart')

    kodi_utils.add_dir(handle, {'mode': 'build_mdbl_list.search_mdbl_lists', 'ai_prompt': '1'}, '[B]New Search...[/B]', iconImage=default_icon)

    try:
        from resources.lib.caches.main_cache import MainCache
        rows = MainCache().get('mdbl_list_queries') or []
    except Exception:
        rows = []

    items = []
    for q in rows:
        try:
            li = kodi_utils.make_listitem()
            li.setLabel('[I]%s[/I]' % q)
            li.setArt({'icon': default_icon, 'poster': default_icon, 'thumb': default_icon, 'fanart': fanart, 'banner': default_icon})
            li.addContextMenuItems([
                (kodi_utils.local_string(32698), 'RunPlugin(%s)' % kodi_utils.build_url({'mode': 'remove_from_history', 'setting_id': 'mdbl_list_queries', 'query': q})),
                (kodi_utils.local_string(32699), 'RunPlugin(%s)' % kodi_utils.build_url({'mode': 'clear_search_history', 'setting_id': 'mdbl_list_queries', 'query': q}))
            ])
            items.append((kodi_utils.build_url({'mode': 'build_mdbl_list.search_mdbl_lists', 'search_title': q}), li, True))
        except Exception: pass

    if items: kodi_utils.add_items(handle, items)
    kodi_utils.set_category(handle, params.get('name') or 'MDBList')
    kodi_utils.set_content(handle, '')
    kodi_utils.end_directory(handle)
    kodi_utils.set_view_mode('view.main', '')

def append_like_menu(cm_append, list_type, list_id):
    """Intelligently appends Context menu Like/Unlike logic matching native POV traits."""
    if list_type in ('my_lists', 'external'):
        return
    from resources.lib.modules import kodi_utils
    like_str = kodi_utils.local_string(32776)
    unlike_str = kodi_utils.local_string(32783)

    liked = _get_liked_ids()
    if list_type == 'liked_lists' or (liked and str(list_id) in liked):
        cm_append((unlike_str, 'RunPlugin(%s)' % kodi_utils.build_url({'mode': 'mdblist.mdbl_unlike_a_list', 'list_id': list_id})))
    else:
        cm_append((like_str, 'RunPlugin(%s)' % kodi_utils.build_url({'mode': 'mdblist.mdbl_like_a_list', 'list_id': list_id})))

    if liked is None:
        cm_append((unlike_str, 'RunPlugin(%s)' % kodi_utils.build_url({'mode': 'mdblist.mdbl_unlike_a_list', 'list_id': list_id})))

def _get_liked_ids():
    if _ai_liked_ids_cache[0] is False:
        try:
            import json
            from resources.lib.caches import mdbl_cache
            cur = mdbl_cache.MDBLCache().dbcur
            cur.execute(mdbl_cache.MC_BASE_GET, ('mdbl_liked_lists',))
            row = cur.fetchone()
            data = json.loads(row[0]) if row else None
            lists = data.get('lists') if isinstance(data, dict) else None
            _ai_liked_ids_cache[0] = set(str(i.get('id')) for i in lists if i.get('id') is not None) if isinstance(lists, list) else None
        except Exception:
            _ai_liked_ids_cache[0] = None
    return _ai_liked_ids_cache[0]

def _ai_refresh_after_like():
    import xbmc
    from urllib.parse import quote_plus
    from resources.lib.modules import kodi_utils
    path = xbmc.getInfoLabel('Container.FolderPath') or ''
    unsafe = False
    target = None
    if 'search_mdbl_lists' in path and 'search_title=' not in path:
        unsafe = True
        title = xbmc.getInfoLabel('Container.PluginCategory') or ''
        if title.strip():
            sep = '&' if '?' in path else '?'
            target = '%s%ssearch_title=%s' % (path, sep, quote_plus(title))
    try:
        if target: kodi_utils.execute_builtin('Container.Refresh(%s)' % target)
        elif not unsafe: kodi_utils.container_refresh()
    except Exception: pass

def like_a_list(params):
    from resources.lib.indexers.mdblist_api import call_mdblist
    from resources.lib.caches import mdbl_cache
    from resources.lib.modules import kodi_utils
    list_id = params['list_id']
    result = call_mdblist('lists/%s/like' % list_id, method='put')
    if result is None: return kodi_utils.notification(32574)
    mdbl_cache.clear_mdbl_list_data('liked_lists')
    _ai_liked_ids_cache[0] = False
    kodi_utils.notification(32576)
    _ai_refresh_after_like()

def unlike_a_list(params):
    from resources.lib.indexers.mdblist_api import call_mdblist
    from resources.lib.caches import mdbl_cache
    from resources.lib.modules import kodi_utils
    list_id = params['list_id']
    result = call_mdblist('lists/%s/like' % list_id, method='delete')
    if result is None: return kodi_utils.notification(32574)
    mdbl_cache.clear_mdbl_list_data('liked_lists')
    _ai_liked_ids_cache[0] = False
    kodi_utils.notification(32576)
    _ai_refresh_after_like()


def lists_sort_order_override(orig_func, setting, mediatype):
    """
    Intercepts the settings read for list sorting.
    If the sort order is 0 (Default A-Z) and the list is a watchlist or collection,
    we override the runtime state to 1 (Recently Added).
    Deliberate user choices (e.g., 2 = Release Date) are respected.
    """
    try:
        val = orig_func(setting, mediatype)
        if val == 0 and setting in ('watchlist', 'collection'):
            return 1
        return val
    except Exception:
        # Fail-safe fallback to Recency
        return 1


def heal_mdblist_account_if_needed():
    """
    Repairs the 'No MDBList Account Active' state.
    If the API token exists but the username is missing, it dynamically fetches
    the username from MDBList and populates the local Kodi settings.
    """
    from resources.lib.modules import kodi_utils

    token = (kodi_utils.get_setting('mdblist.token') or '').strip()
    user = (kodi_utils.get_setting('mdblist_user') or '').strip()

    # Only execute if broken (token exists, but user string is empty)
    if token and not user:
        try:
            import json
            import urllib.request
            import urllib.parse

            url = 'https://api.mdblist.com/user?apikey=' + urllib.parse.quote(token, safe='')
            req = urllib.request.Request(url, headers={'User-Agent': 'kodi-pov-il'})

            # Short timeout to prevent stalling boot
            with urllib.request.urlopen(req, timeout=5) as resp:
                if getattr(resp, 'status', 200) == 200:
                    data = json.loads(resp.read().decode('utf-8', 'replace'))
                    username = str((data or {}).get('username') or '').strip()

                    if username:
                        kodi_utils.set_setting('mdbl_indicators_active', 'true')
                        kodi_utils.set_setting('mdblist_user', username)
        except Exception:
            pass # Fail gracefully; the native check will simply return 'no account' as it originally did.