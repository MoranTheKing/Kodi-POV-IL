# plugin.program.kodipovilwizard/resources/libs/patches/pov_mdblist_patch_logic.py
# Offloaded execution logic for MDBList patch engine injections.

_AI_MDBL_REFRESH_LOCK = 'pov_ai_mdbl_refreshing'
_ai_liked_ids_cache = [False]

def _call_mdblist(path, **kwargs):
    from indexers.mdblist_api import call_mdblist, base_url
    if '%s' not in base_url: path = '/' + path.lstrip('/')
    return call_mdblist(path, **kwargs)


def handle_401_reauth(e, path, params, json_data, method):
    """Intercepts a 401 error, attempts to acquire a GUI lock, refreshes the token, and recurses safely."""
    status = getattr(getattr(e, 'response', None), 'status_code', 0)
    if status != 401: return None
    from modules import kodi_utils
    if not kodi_utils.get_setting('mdblist.refresh', ''): return None

    try:
        import xbmcgui
        window = xbmcgui.Window(10000)
    except Exception:
        window = None

    before = kodi_utils.get_setting('mdblist.token')
    if window is not None:
        from modules.kodi_utils import sleep
        for _ in range(60):
            if window.getProperty(_AI_MDBL_REFRESH_LOCK) != 'true': break
            sleep(250)
        if kodi_utils.get_setting('mdblist.token') != before: return _retry_call(path, params, json_data, method)
        window.setProperty(_AI_MDBL_REFRESH_LOCK, 'true')
        if kodi_utils.get_setting('mdblist.token') != before:
            window.clearProperty(_AI_MDBL_REFRESH_LOCK)
            return _retry_call(path, params, json_data, method)

    try:
        from indexers.mdblist_api import mdbl_refresh
        mdbl_refresh()
    finally:
        if window is not None: window.clearProperty(_AI_MDBL_REFRESH_LOCK)

    if kodi_utils.get_setting('mdblist.token') != before:
        return _retry_call(path, params, json_data, method)
    return None

def _retry_call(path, params, json_data, method):
    from indexers.mdblist_api import session, base_url, timeout
    from modules import kodi_utils
    headers = None
    params = params or {}
    if not bool(kodi_utils.get_setting('mdblist.refresh')):
        params['apikey'] = kodi_utils.get_setting('mdblist.token')
    else:
        headers = {'Authorization': 'Bearer %s' % kodi_utils.get_setting('mdblist.token')}
    try:
        response = session.request(
            method or 'get',
            (base_url % path if '%s' in base_url else base_url + '/' + path.lstrip('/')),
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
            from indexers.mdblist_api import call_mdblist
            if media == 'movies':
                sd = {'movie': {'ids': {'tmdb': media_id}}, 'progress': 100.0}
            else:
                sd = {'show': {'ids': {'tmdb': media_id}, 'season': {'number': int(season), 'episode': {'number': int(episode)}}}, 'progress': 100.0}
            _call_mdblist('scrobble/stop', json=sd, method='post')
        except Exception: pass

def merge_collection_to_watchlist(original_list, mediatype):
    """Mutates original_list directly by reference to attach unified collection outputs."""
    try:
        from indexers.mdblist_api import mdbl_collection_watchlist_items
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
        from modules import kodi_utils
        query = kodi_utils.dialog.input('POV')
        if not query:
            import sys, xbmcplugin
            xbmcplugin.endOfDirectory(int(sys.argv[1]), succeeded=False)
            return None
        try:
            from menus.history import add_to_search_history
            add_to_search_history(query, 'mdbl_list_queries')
        except Exception: pass
        return {'search_title': query}
    return {}

def _mdbl_search_screen(params):
    import sys
    from modules import kodi_utils
    handle = int(sys.argv[1])
    default_icon = kodi_utils.media_path('mdblist.png')
    fanart = kodi_utils.get_addoninfo('fanart')

    kodi_utils.add_dir(handle, {'mode': 'build_mdbl_list.search_mdbl_lists', 'ai_prompt': '1'}, '[B]New Search...[/B]', iconImage=default_icon)

    try:
        from caches.main_cache import MainCache
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
    from modules import kodi_utils
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
            from caches import mdbl_cache
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
    from modules import kodi_utils
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
    from indexers.mdblist_api import call_mdblist
    from caches import mdbl_cache
    from modules import kodi_utils
    list_id = params['list_id']
    result = _call_mdblist('lists/%s/like' % list_id, method='put')
    if result is None: return kodi_utils.notification(32574)
    mdbl_cache.clear_mdbl_list_data('liked_lists')
    _ai_liked_ids_cache[0] = False
    kodi_utils.notification(32576)
    _ai_refresh_after_like()

def unlike_a_list(params):
    from indexers.mdblist_api import call_mdblist
    from caches import mdbl_cache
    from modules import kodi_utils
    list_id = params['list_id']
    result = _call_mdblist('lists/%s/like' % list_id, method='delete')
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


def newest_personal_items(items):
    """Order a copy by addition time, never mutate a provider's cached list."""
    from datetime import datetime, timezone
    def added(item):
        for key in ('listed_at', 'watchlisted_at', 'watchlist_at', 'collected_at', 'last_collected_at', 'added'):
            value = item.get(key) if isinstance(item, dict) else None
            if value in (None, ''): continue
            try:
                date = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
                if date.tzinfo is None: date = date.replace(tzinfo=timezone.utc)
                return date.timestamp()
            except (ValueError, TypeError, OverflowError): pass
        return float('-inf')
    return sorted(items, key=added, reverse=True) if isinstance(items, list) else items


def personal_mdbl_url(url, enabled=True):
    """Use the documented server sort before cursor pagination; strip UI flag."""
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    personal = any(k == 'povil_personal' and v == '1' for k, v in query)
    if not any(k == 'povil_personal' for k, v in query): return url
    query = [(k, v) for k, v in query if k != 'povil_personal']
    if personal and enabled:
        query = [(k, v) for k, v in query if k not in ('sort', 'order')]
        query.extend((('sort', 'added'), ('order', 'desc')))
    return urlunsplit(parts._replace(query=urlencode(query)))


def is_own_trakt_url(url, username):
    from urllib.parse import urlsplit, unquote
    parts = [unquote(p).casefold() for p in urlsplit(url).path.split('/') if p]
    return (len(parts) >= 4 and parts[0] == 'users' and parts[2] == 'lists'
            and parts[1] in ('me', str(username or '').strip().casefold()))


def umbrella_personal_sort(owner, setting, get_setting, url=None):
    """Default personal views use newest first; explicit sorting stays native."""
    if str(get_setting('sort.%s.type' % setting) or '0') != '0': return False
    personal = setting.endswith(('.watchlist', '.collection'))
    if url is not None:
        personal = is_own_trakt_url(url, get_setting('trakt.user.name'))
    if not personal: return False
    owner.list = newest_personal_items(owner.list)
    return True


def heal_mdblist_account_if_needed():
    """
    Repairs the 'No MDBList Account Active' state.
    If the API token exists but the username is missing, it dynamically fetches
    the username from MDBList and populates the local Kodi settings.
    """
    from modules import kodi_utils

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
