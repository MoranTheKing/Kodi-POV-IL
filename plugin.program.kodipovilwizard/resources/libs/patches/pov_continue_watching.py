"""Persistent explicit exclusions and verified, bounded dropped-list reads.

Watched history and bookmarks are never deleted to hide a show. Snapshots
contain only the active account's successfully read dropped list, not history
or credentials; a failed read cannot turn it into an apparently empty list.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time

TTL = 300
READ_BUDGET = 5
_pending = set()
_pending_lock = threading.Lock()


class HiddenUnavailable(Exception):
    def __init__(self, status=0, retry_after=60):
        super().__init__('Dropped list unavailable')
        self.status = status
        self.retry_after = retry_after


class _UnknownHidden(set):
    # A first failed read gives no evidence that any show is allowed back.
    # Existing watched/progress data stays intact and the next read can retry.
    def __contains__(self, item):
        return True


def _id(value):
    if isinstance(value, bool):
        raise ValueError('invalid show id')
    result = int(value)
    if result <= 0 or str(value).strip() != str(result):
        raise ValueError('invalid show id')
    return result


def _identity(provider):
    from modules import kodi_utils
    token = kodi_utils.get_setting(provider + '.token') or ''
    user = kodi_utils.get_setting('trakt_user' if provider == 'trakt' else 'mdblist_user') or ''
    if not token:
        raise HiddenUnavailable(401)
    # Stable named accounts survive OAuth token rotation. Unnamed connections
    # use the token digest, so a different account never inherits exclusions.
    value = provider + '\0' + ('user:' + user.casefold() if user else 'token:' + token)
    return hashlib.sha256(value.encode('utf8')).hexdigest()


def _path(provider):
    from modules import kodi_utils
    return kodi_utils.translate_path(kodi_utils.databases_path + 'povil_dropped_' + provider + '.json')


def _load(path, identity):
    try:
        with open(path, encoding='utf8') as source:
            state = json.load(source)
        if (state.get('version') != 1 or state.get('identity') != identity
                or not isinstance(state.get('items'), list)):
            return {}
        state['items'] = [_id(item) for item in state['items']]
        if type(state.get('complete')) is not bool:
            return {}
        for key in ('checked', 'retry_at'):
            if not isinstance(state.get(key), (int, float)):
                return {}
        return state
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def _save(path, state):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.dropped-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as target:
            json.dump(state, target, separators=(',', ':'))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _lock(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path + '.lock.db', timeout=.1)
    try:
        connection.execute('BEGIN IMMEDIATE')
        yield
    finally:
        connection.rollback()
        connection.close()


def _refresh(path, identity, reader, now=None):
    now = time.time() if now is None else now
    try:
        with _lock(path):
            state = _load(path, identity)
            if state.get('retry_at', 0) > now:
                return state
            if state.get('complete') and now - state.get('checked', 0) < TTL:
                return state
            try:
                items = sorted({_id(item) for item in reader()})
                state = dict(version=1, identity=identity, items=items,
                             complete=True, checked=now, retry_at=0)
            except HiddenUnavailable as error:
                state = dict(version=1, identity=identity, items=state.get('items', []),
                             complete=state.get('complete', False), checked=state.get('checked', 0),
                             retry_at=now + max(30, error.retry_after))
            _save(path, state)
            return state
    except (OSError, sqlite3.Error):
        return _load(path, identity)


def snapshot(path, identity, reader, background=True, now=None):
    """Valid empty lists are cached; failed/partial lists never replace them."""
    now = time.time() if now is None else now
    state = _load(path, identity)
    if state.get('complete'):
        if state.get('retry_at', 0) > now or now - state.get('checked', 0) < TTL:
            return set(state['items'])
        if background:
            key = (path, identity)
            with _pending_lock:
                if key not in _pending:
                    _pending.add(key)
                    def run():
                        try:
                            _refresh(path, identity, reader)
                        finally:
                            with _pending_lock:
                                _pending.discard(key)
                    threading.Thread(target=run).start()
            return set(state['items'])
    state = _refresh(path, identity, reader, now)
    if state.get('complete'):
        return set(state['items'])
    raise HiddenUnavailable(retry_after=max(30, state.get('retry_at', now + 60) - now))


def _retry_after(headers):
    value = headers.get('Retry-After', '60')
    try:
        return max(30, float(value))
    except (ValueError, TypeError):
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return max(30, (stamp - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 60


def _read_remote(provider, identity):
    """Use native HTTP types/auth; no automatic 429 retries or Retry-After sleep.

The small dropped-list read has its own client. Other API requests, mutations,
provider adapters, cookies and retry policies remain untouched.
"""
    from modules import kodi_utils
    from session import TimeoutSession, HTTPAdapter
    from indexers import trakt_api, mdblist_api
    api = trakt_api if provider == 'trakt' else mdblist_api
    client = TimeoutSession()
    client.mount(api.base_url, HTTPAdapter(max_retries=0))
    start = time.monotonic()
    try:
        params = {'limit': 250, 'page': 1} if provider == 'trakt' else {'limit': 1000}
        url = '/users/hidden/dropped?type=show' if provider == 'trakt' else '/sync/dropped'
        ids, cursors, refreshed = set(), set(), False
        while True:
            remaining = READ_BUDGET - (time.monotonic() - start)
            if remaining <= 0:
                raise HiddenUnavailable()
            headers = {'Content-Type': 'application/json'}
            token = kodi_utils.get_setting(provider + '.token') or ''
            values = dict(params)
            if provider == 'trakt':
                headers.update({'trakt-api-key': api.READ_TOKEN, 'trakt-api-version': '2',
                                'Authorization': 'Bearer ' + token})
            elif kodi_utils.get_setting('mdblist.refresh'):
                headers['Authorization'] = 'Bearer ' + token
            else:
                values['apikey'] = token
            try:
                response = client.request('get', api.base_url + url, params=values,
                                          headers=headers, timeout=(min(2, remaining), min(3, remaining)))
            except Exception:
                raise HiddenUnavailable() from None
            if response.status_code == 401 and not refreshed:
                refreshed = True
                before = token
                if provider == 'trakt':
                    api.trakt_refresh()
                else:
                    api.mdbl_refresh()
                if kodi_utils.get_setting(provider + '.token') != before:
                    continue
            if not response.ok:
                raise HiddenUnavailable(response.status_code, _retry_after(response.headers))
            try:
                data = response.json()
                if provider == 'trakt':
                    if not isinstance(data, list):
                        raise ValueError()
                    rows = data
                    pages = int(response.headers['X-Pagination-Page-Count'])
                    empty = params['page'] == 1 and pages == 0 and not rows
                    if (pages < params['page'] and not empty) or pages > 1000:
                        raise ValueError()
                    more = params['page'] < pages
                else:
                    from pov_mdblist_patch_logic import list_response_pagination
                    if isinstance(data, list):
                        if response.headers.get('X-Has-More') not in ('true', 'false'):
                            raise ValueError()
                        data = {'shows': data, 'pagination': {
                            'has_more': response.headers.get('X-Has-More') == 'true',
                            'next_cursor': response.headers.get('X-Next-Cursor')}}
                    data = list_response_pagination(data, response)
                    rows = data['shows']
                    if not isinstance(rows, list):
                        raise ValueError()
                    paging = data['pagination']
                    if 'has_more' in paging:
                        more = paging['has_more']
                        if type(more) is not bool:
                            raise ValueError()
                    elif 'next_cursor' in paging:
                        more = bool(paging['next_cursor'])
                    else:
                        more = paging['total'] != paging.get('offset', 0) + len(rows)
                    cursor = paging.get('next_cursor')
                    if more and (not isinstance(cursor, str) or not cursor or cursor in cursors):
                        raise ValueError()
                    if not more and cursor:
                        raise ValueError()
                for row in rows:
                    ids.add(_id(row['show']['ids']['tmdb']))
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                raise HiddenUnavailable() from None
            if not more:
                if _identity(provider) != identity:
                    raise HiddenUnavailable()
                return ids
            if provider == 'trakt':
                params['page'] += 1
            else:
                cursors.add(cursor)
                params['cursor'] = cursor
    finally:
        client.close()


def _notice(provider):
    from modules import kodi_utils
    kodi_utils.logger('continue watching', provider + ' dropped read unavailable; exclusions preserved')
    try:
        import xbmcgui
        window = xbmcgui.Window(10000)
        key = 'povil.dropped.notice.' + provider
        now = time.time()
        if now - float(window.getProperty(key) or '0') < 60:
            return
        window.setProperty(key, str(now))
        kodi_utils.notification('רשימת ההמשך אינה זמינה כרגע. ההסרות שלך נשמרו.')
    except Exception:
        pass


def remote_hidden(provider):
    identity = _identity(provider)
    try:
        def reader():
            try:
                return _read_remote(provider, identity)
            except HiddenUnavailable:
                raise
            except Exception:
                raise HiddenUnavailable() from None
        return snapshot(_path(provider), identity, reader)
    except HiddenUnavailable:
        _notice(provider)
        raise


def invalidate(provider):
    try:
        path, identity = _path(provider), _identity(provider)
        with _lock(path):
            state = _load(path, identity)
            if state:
                state['checked'] = 0
                _save(path, state)
    except (OSError, sqlite3.Error, HiddenUnavailable):
        pass


def dropped_info(native, indicator):
    from indexers.local_api import local_droplist
    hidden = {_id(row['tmdb_id']) for row in local_droplist(None, 'tvshow', 'all')}
    if indicator in (1, 2):
        try:
            hidden.update(remote_hidden('trakt' if indicator == 1 else 'mdblist'))
        except HiddenUnavailable:
            return _UnknownHidden(hidden)
    return hidden


def filter_episode_sources(menu):
    # Also cover optional watchlist additions and partially watched bookmarks;
    # the native last-watched query alone cannot filter these extra sources.
    if not (menu.list_type.startswith('next_episode') or menu.list_type == 'in_progress'):
        return
    hidden = dropped_info({}, menu.watched_indicators)
    rows = []
    for row in menu.list:
        try:
            if _id(row['media_ids']['tmdb']) not in hidden:
                rows.append(row)
        except (TypeError, ValueError, KeyError):
            continue
    menu.list = rows


def append_episode_actions(scope, build_url=None, run_plugin=None):
    menu = scope['self']
    build_url = build_url or scope['build_url']
    run_plugin = run_plugin or scope['run_plugin']
    if int(scope['season'] or 0) > 0 and not scope['unaired']:
        params = dict(mode='mark_as_watched_unwatched_season', action='mark_as_watched',
                      year=scope['year'], tmdb_id=scope['tmdb_id'], tvdb_id=scope['tvdb_id'],
                      season=scope['season'], title=scope['title'])
        scope['cm_append']((menu.cm_sort['mark'], '[B]סמן את העונה כנצפתה (%s)[/B]' % menu.watched_title,
                            run_plugin % build_url(params)))
    if menu.list_type.startswith('next_episode') or menu.list_type == 'in_progress':
        params = dict(mode='dropped_choice', mediatype='tvshow',
                      tmdb_id=scope['tmdb_id'], title=scope['title'])
        # Explicit removal is available even if optional provider CM groups
        # were disabled. It hides a show; it does not mark unwatched episodes.
        scope['cm_append']((1, '[B]הסר מהמשך צפייה[/B]',
                            run_plugin % build_url(params)))


def dropped_choice(params, native):
    from indexers.local_api import local_droplist, add_to_sync, remove_from_sync
    from modules import kodi_utils
    mediatype, tmdb_id, title = params['mediatype'], _id(params['tmdb_id']), params['title']
    current = {_id(row['tmdb_id']) for row in local_droplist(None, mediatype, 'all')}
    remove = tmdb_id in current
    text = ('להחזיר להמשך צפייה?' if remove else 'להסיר מהמשך צפייה?') + '[CR]' + title
    if not native['confirm_dialog'](text=text):
        return
    mutation = remove_from_sync if remove else add_to_sync
    ok = mutation('dropped', mediatype, tmdb_id, title)
    if ok:
        kodi_utils.notify_success()
        kodi_utils.widget_refresh()
        if not kodi_utils.external_browse():
            kodi_utils.container_refresh()
    else:
        kodi_utils.notify_error()
    return ok


def remote_toggle(native, provider, action, mediatype, media_id, list_type):
    """Verify the native cloud write before changing its exclusion snapshot."""
    from modules import kodi_utils
    from indexers.local_api import call_local, local_droplist
    if mediatype not in ('show', 'shows', 'tvshow') or list_type != 'dropped':
        return kodi_utils.notify_error()
    try:
        # Native manager passes the TMDb ID in `action` and IMDb in media_id.
        # Prefer the known TMDb ID rather than missing or mismatched IMDb data.
        tmdb_id = _id(action if action not in ('hide', 'unhide') else media_id)
        identity = _identity(provider)
        hidden = remote_hidden(provider)
        local = {_id(row['tmdb_id']) for row in local_droplist(None, 'tvshow', 'all')}
        if action not in ('hide', 'unhide'):
            action = 'unhide' if tmdb_id in hidden or tmdb_id in local else 'hide'
        path = ('/users/hidden/dropped' if provider == 'trakt' else '/sync/dropped')
        if action == 'unhide':
            path += '/remove'
        data = {'shows': [{'ids': {'tmdb': tmdb_id}}]}
        if provider == 'trakt':
            result = native['call_trakt'](path, data=data)
        else:
            result = native['call_mdblist'](path, json=data, method='post')
        keys = ('added', 'updated') if action == 'hide' else ('deleted', 'removed')
        not_found = result.get('not_found', {}) if isinstance(result, dict) else None
        if (not isinstance(result, dict) or not any(
                isinstance(result.get(key), dict) and type(result[key].get('shows')) is int
                and result[key]['shows'] >= 0 for key in keys)
                or not isinstance(not_found, dict) or not_found.get('shows')
                or _identity(provider) != identity):
            return kodi_utils.notify_error()
        if action == 'hide':
            call_local('INSERT OR IGNORE INTO dropped VALUES (?, ?, ?)',
                       ('tvshow', str(tmdb_id), str(tmdb_id)))
            hidden.add(tmdb_id)
        else:
            call_local('DELETE FROM dropped WHERE db_type=? AND tmdb_id=?', ('tvshow', str(tmdb_id)))
            hidden.discard(tmdb_id)
        from caches import trakt_cache, mdbl_cache
        if provider == 'trakt':
            trakt_cache.clear_trakt_hidden_data('dropped')
        else:
            mdbl_cache.clear_mdbl_hidden_data('dropped')
        with _lock(_path(provider)):
            _save(_path(provider), dict(version=1, identity=identity, complete=True,
                items=sorted(hidden), checked=time.time(), retry_at=0))
        kodi_utils.notify_success()
        kodi_utils.widget_refresh()
        if not kodi_utils.external_browse():
            kodi_utils.container_refresh()
        return True
    except (OSError, ValueError, TypeError, sqlite3.Error, HiddenUnavailable):
        return kodi_utils.notify_error()
