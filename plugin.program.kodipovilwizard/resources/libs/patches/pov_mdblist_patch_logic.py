# plugin.program.kodipovilwizard/resources/libs/patches/pov_mdblist_patch_logic.py
# Offloaded execution logic for MDBList patch engine injections.

_AI_MDBL_REFRESH_LOCK = 'pov_ai_mdbl_refreshing'
_ai_liked_ids_cache = [False]
_refresh_mutex = __import__('threading').Lock()
_last_failure = [0]


class MDBListUnavailable(Exception):
    """A failed read must not become a cached, apparently empty list."""


def record_failure(response=None):
    _last_failure[0] = getattr(response, 'status_code', 0) or 0


def notify_unavailable():
    import time
    from modules import kodi_utils
    try:
        import xbmcgui
        window = xbmcgui.Window(10000)
        now = time.time()
        if now - float(window.getProperty('povil.mdbl.error_notice') or 0) < 15:
            return
        window.setProperty('povil.mdbl.error_notice', str(now))
    except Exception:
        pass
    if _last_failure[0] == 401:
        text = 'MDBList: החיבור אינו תקף. יש לחבר מחדש דרך חיבור שירותים.'
    elif _last_failure[0] == 403:
        text = 'MDBList: אין הרשאה לפעולה. בדוק את הרשאות החיבור.'
    elif _last_failure[0] == 429:
        text = 'MDBList: הגעת למגבלת הבקשות. נסה שוב מאוחר יותר.'
    else:
        text = 'MDBList: הרשימה לא נטענה. נסה שוב; הרשימות שלך לא נמחקו.'
    kodi_utils.notification(text)


def cache_list(function, string, url):
    """Keep native keys/invalidation; invalidate poisoned legacy reads once.

    The epoch also isolates account changes. Do not touch watched/progress
    tables, and never store failed or incomplete responses.
    """
    import hashlib, json
    from caches import mdbl_cache
    from modules import kodi_utils
    def valid(data):
        key = ('items' if string in ('mdbl_my_lists', 'mdbl_external')
               else 'lists' if string == 'mdbl_liked_lists' else None)
        if key:
            return isinstance(data, dict) and isinstance(data.get(key), list)
        return isinstance(data, (dict, list))
    def epoch():
        token = kodi_utils.get_setting('mdblist.token') or ''
        return 'v3:' + hashlib.sha256(token.encode('utf-8')).hexdigest()
    def prepare(cur):
        value = epoch()
        cur.execute(mdbl_cache.MC_BASE_GET, ('povil_mdbl_cache_epoch',))
        row = cur.fetchone()
        if not row or row[0] != value:
            cur.execute('DELETE FROM mdbl_data')
            cur.execute(mdbl_cache.MC_BASE_SET, ('povil_mdbl_cache_epoch', value))
        return value
    cur = mdbl_cache.MDBLCache().dbcur
    prepare(cur)
    cur.execute(mdbl_cache.MC_BASE_GET, (string,))
    row = cur.fetchone()
    if row:
        try:
            data = json.loads(row[0])
            if valid(data):
                return data
        except (ValueError, TypeError):
            pass
    result = function(url)
    if not valid(result):
        raise MDBListUnavailable('MDBList read failed')
    # A refresh during the request changes the token/epoch.
    prepare(cur)
    cur.execute(mdbl_cache.MC_BASE_SET, (string, json.dumps(result)))
    return result


def list_response_pagination(result, response):
    """Keep pagination headers for bucketed JSON, as native POV does for arrays.

    MDBList documents next_cursor (including null at the end) for collection
    and watched history, and X-Has-More for list responses. has_more is not a
    required JSON field. Do not guess that an unknown response is complete.
    """
    if not isinstance(result, dict) or not any(
            isinstance(result.get(key), list) for key in ('movies', 'shows', 'episodes', 'items')):
        return result
    headers = response.headers
    more = headers.get('X-Has-More')
    cursor = headers.get('X-Next-Cursor')
    if more is None and cursor is None:
        return result
    result = dict(result)
    pagination = result.get('pagination', {})
    if not isinstance(pagination, dict):
        raise MDBListUnavailable('MDBList pagination invalid')
    pagination = dict(pagination)
    if more is not None:
        more = str(more).strip().lower()
        if more not in ('true', 'false'):
            raise MDBListUnavailable('MDBList pagination header invalid')
        more = more == 'true'
        if 'has_more' in pagination and pagination['has_more'] is not more:
            raise MDBListUnavailable('MDBList pagination conflict')
        pagination['has_more'] = more
    if cursor:
        if 'next_cursor' in pagination and pagination['next_cursor'] != cursor:
            raise MDBListUnavailable('MDBList cursor conflict')
        pagination['next_cursor'] = cursor
    result['pagination'] = pagination
    return result


def paginated_list(url, max_items=250000):
    """Accept complete valid pages only, including genuinely empty lists."""
    items = {'movies': [], 'shows': [], 'episodes': [], 'items': []}
    params, cursors, received = {'limit': 1000}, set(), 0
    for _ in range(max_items // params['limit']):
        result = _call_mdblist(url, params=dict(params))
        if not isinstance(result, dict):
            raise MDBListUnavailable('MDBList page unavailable')
        pagination = result.get('pagination')
        if not isinstance(pagination, dict):
            raise MDBListUnavailable('MDBList pagination unavailable')
        if not any(isinstance(result.get(key), list) for key in items):
            raise MDBListUnavailable('MDBList items unavailable')
        for key in items:
            if key in result:
                if not isinstance(result[key], list):
                    raise MDBListUnavailable('MDBList items invalid')
                items[key].extend(result[key])
        # A legacy terminal page can omit next_cursor but still give an exact
        # total/offset. Only those counts can prove completion without a flag.
        page_count = sum(len(result[key]) for key in ('movies', 'shows', 'seasons', 'episodes', 'items')
                         if isinstance(result.get(key), list))
        received += page_count
        total, offset = pagination.get('total'), pagination.get('offset')
        end = offset + page_count if type(offset) is int and offset >= 0 else received
        cursor = pagination.get('next_cursor')
        if cursor is not None and not isinstance(cursor, str):
            raise MDBListUnavailable('MDBList cursor invalid')
        if 'has_more' in pagination:
            more = pagination['has_more']
            if not isinstance(more, bool) or (not more and cursor):
                raise MDBListUnavailable('MDBList pagination invalid')
        elif 'next_cursor' in pagination:
            more = bool(cursor)
        elif type(total) is int and total >= 0 and total == end:
            more = False
        else:
            raise MDBListUnavailable('MDBList pagination unavailable')
        if not more:
            if type(total) is int and total > end:
                raise MDBListUnavailable('MDBList pagination incomplete')
            return items
        if not cursor or cursor in cursors:
            raise MDBListUnavailable('MDBList cursor invalid')
        cursors.add(cursor)
        params['cursor'] = cursor
    raise MDBListUnavailable('MDBList pagination incomplete')

def _call_mdblist(path, **kwargs):
    from indexers.mdblist_api import call_mdblist, base_url
    if '%s' not in base_url: path = '/' + path.lstrip('/')
    return call_mdblist(path, **kwargs)


def handle_401_reauth(e, path, params, json_data, method, response=None):
    """Recover one failed request; never recursively retry or steal a busy lock."""
    import hashlib, time
    response = response if response is not None else getattr(e, 'response', None)
    record_failure(response)
    status = getattr(response, 'status_code', 0)
    if status != 401: return None
    from modules import kodi_utils
    if not kodi_utils.get_setting('mdblist.refresh', ''): return None

    try:
        import xbmcgui
        window = xbmcgui.Window(10000)
    except Exception:
        window = None

    before = kodi_utils.get_setting('mdblist.token')
    failure_key = 'povil.mdbl.refresh_failed.' + hashlib.sha256((before or '').encode('utf-8')).hexdigest()[:16]
    if window is not None:
        if time.time() - float(window.getProperty(failure_key) or 0) < 60:
            return None
        from modules.kodi_utils import sleep
        for _ in range(60):
            if window.getProperty(_AI_MDBL_REFRESH_LOCK) != 'true': break
            sleep(250)
        if kodi_utils.get_setting('mdblist.token') != before: return _retry_call(path, params, json_data, method)
        if window.getProperty(_AI_MDBL_REFRESH_LOCK) == 'true': return None
        window.setProperty(_AI_MDBL_REFRESH_LOCK, 'true')
        if kodi_utils.get_setting('mdblist.token') != before:
            window.clearProperty(_AI_MDBL_REFRESH_LOCK)
            return _retry_call(path, params, json_data, method)

    try:
        with _refresh_mutex:
            if kodi_utils.get_setting('mdblist.token') == before:
                from indexers.mdblist_api import mdbl_refresh
                mdbl_refresh()
    finally:
        if window is not None: window.clearProperty(_AI_MDBL_REFRESH_LOCK)

    if kodi_utils.get_setting('mdblist.token') != before:
        return _retry_call(path, params, json_data, method)
    if window is not None: window.setProperty(failure_key, str(time.time()))
    return None

def _retry_call(path, params, json_data, method):
    from indexers.mdblist_api import session, base_url, timeout
    from modules import kodi_utils
    headers = None
    params = dict(params or {})
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
        if not response.ok:
            record_failure(response)
            return None
        result = list_response_pagination(result, response)
        _last_failure[0] = 0
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
            data = _call_mdblist('/user')
            username = str((data or {}).get('username') or '').strip()
            if username:
                kodi_utils.set_setting('mdbl_indicators_active', 'true')
                kodi_utils.set_setting('mdblist_user', username)
        except Exception:
            pass # Fail gracefully; the native check will simply return 'no account' as it originally did.
