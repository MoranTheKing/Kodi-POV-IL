# Self-healing patcher for plugin.video.pov's indexers/mdblist_api.py. Two
# independent, marker-gated fixes for POV's MDBList watched/progress sync (only
# reached when the user makes MDBList their Watched Status Provider):
#
#  A) API KEY LEAKED TO kodi.log:
#     call_mdblist() logs `logger('mdblist error', str(e))`. For a requests
#     HTTPError, str(e) is "... for url: https://api.mdblist.com/...?apikey=<KEY>"
#     -- the user's full MDBList key lands in the log verbatim. Fix: scrub the
#     apikey value out of the logged string with an inline regex. Substring
#     replace on `'mdblist error', str(e)`, so it works whether POV calls
#     `logger(...)` or `kodi_utils.logger(...)`.
#
#  B) "MARK AS WATCHED" DOESN'T CLEAR THE PAUSED STATE / DOESN'T COUNT:
#     on mark-watched POV posts sync/watched (adds to the watched *list*) and
#     then tries to clear the resume via `scrobble/clear` with {'id': resume_id}
#     -- which 404s (stale/mismatched id), so the title stays PAUSED on MDBList
#     and never shows in Watch Stats (those are scrobble-based). Fix: right after
#     the sync/watched call, additionally POST `scrobble/stop` at progress 100 by
#     tmdb id. Per MDBList's API, a stop at >=80% marks the item watched AND
#     finalizes (clears) the active scrobble session -- so this both clears the
#     paused state and registers the watch, using an id POV always has. Guarded
#     to the tmdb pass and to movies/episodes; never touches the separate
#     "remove from continue watching" (erase-bookmark) path, so nothing gets
#     marked watched that the user only wanted un-resumed.
#
# NOTE: POV's mdblist_api.py changes heavily between POV versions. These anchors
# match POV 6.x (which has the scrobble/clear path that produced the 404). On a
# version whose anchors moved, the patch is a safe no-op (returns 'unmatched').
# Marker-gated, compile()-checked before writing, atomic, .pyc invalidated.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
MDBLIST_API_REL = 'resources/lib/indexers/mdblist_api.py'
MENUS_MDBLIST_REL = 'resources/lib/menus/mdblist.py'

REDACT_MARKER = '# AI_SUBS_MDBL_REDACT_v1'
SCROBBLE_MARKER = '# AI_SUBS_MDBL_SCROBBLE_STOP_v1'
NONE_GUARD_MARKER = '# AI_SUBS_MDBL_NONE_GUARD_v1'
MANAGER_MARKER = '# AI_SUBS_MDBL_WATCHLIST_ONLY_v2'

# --- Fix C: don't crash the manager when an add/remove returns None ---------
# call_mdblist() returns None on any error (e.g. a 404); POV then does
# result['added']/result['updated'] -> TypeError: 'NoneType' object is not
# subscriptable, which crashes the whole MdbListManager. Guard both add paths.
# (Self-idempotent: the guarded line no longer contains the raw anchor.)
# Match the FULL one-liner (incl. the inline `return`) so the marker lands at the
# end of the line, not before the return (which would comment the return out).
_ADDLIST_ANCHOR = "if result['added']['movies'] + result['added']['shows'] == 0: return kodi_utils.notification(32574)"
_ADDLIST_GUARDED = "if not result or result['added']['movies'] + result['added']['shows'] == 0: return kodi_utils.notification(32574)  " + NONE_GUARD_MARKER
_ADDCOLL_ANCHOR = "if result['updated']['movies'] + result['updated']['shows'] == 0: return kodi_utils.notification(32574)"
_ADDCOLL_GUARDED = "if not result or result['updated']['movies'] + result['updated']['shows'] == 0: return kodi_utils.notification(32574)  " + NONE_GUARD_MARKER

# --- Fix D: Watchlist-only list manager (menus/mdblist.py) ------------------
# POV's list manager offers Watchlist + Collection. We drop Collection here for
# two reasons:
#   1) It's meaningless for a streaming build -- MDBList "Collection" marks media
#      you OWN, which never applies here; Watchlist is the useful list.
#   2) POV's post-add Collection sync (add_to_collection -> mdbl_sync_activities)
#      crashes on some POV builds with "tuple indices must be integers" (a
#      version-specific bug where reset_activity() hands a raw DB tuple to code
#      expecting a dict). That crash path varies by POV version and can't be
#      anchored reliably (Fix E guards the one layout we have cached, but not
#      every build). Removing the Collection button removes the trigger for good.
# POV builds the choice id from the LOCALISED label originally; a Hebrew UI also
# broke routing (id became "קולקציה"). Both concerns vanish with a single stable
# 'watchlist' choice whose DISPLAY label stays the Hebrew watchl_str. POV's
# get_default_choices still appends its own 'dropped' toggle for tv shows, and
# all downstream code routes by choice-id substring (never by position), so a
# one-item list is safe.
_MANAGER_REPLACEMENT = (
    "choices = [('watchlist', watchl_str, '', self.icon)]  " + MANAGER_MARKER)
# Two upgrade sources: a fresh POV (original localised-id anchor) and a device
# already carrying the 0.2.429 two-choice stable-id patch.
_MANAGER_ANCHOR_ORIG = (
    "choices = [(i.lower(), i, '', self.icon) for i in (watchl_str, coll_str)]")
_MANAGER_ANCHOR_V1 = (
    "choices = [('watchlist', watchl_str, '', self.icon), "
    "('collection', coll_str, '', self.icon)]  # AI_SUBS_MDBL_STABLE_IDS_v1")

# --- Fix E: guard mdbl_sync_activities against a corrupt cached value -------
# POV's reset_activity() returns the raw DB row (a tuple) instead of a dict when
# the cached 'mdbl_get_activity' row can't be eval'd back to a dict -- and it
# skips its own self-heal write in that case. mdbl_sync_activities then does
# latest[key] / cached[key] -> "tuple indices must be integers, not str" and
# crashes every caller (the periodic monitor, and add_to_collection's post-add
# refresh -> the Collection button). Guard right after the assignment: if either
# side isn't a dict, purge the mdbl cache (regenerates clean next time) and bail.
# Uses clear_all_mdbl_cache_data, which the function already calls above.
SYNC_GUARD_MARKER = '# AI_SUBS_MDBL_SYNC_GUARD_v1'
_SYNC_ANCHOR = '\tcached = mdbl_cache.reset_activity(latest)'
_SYNC_INJECT = (
    '\n\t' + SYNC_GUARD_MARKER + '\n'
    '\tif not isinstance(cached, dict) or not isinstance(latest, dict):\n'
    '\t\ttry: mdbl_cache.clear_all_mdbl_cache_data(refresh=False)\n'
    '\t\texcept Exception: pass\n'
    "\t\treturn 'failed'")

# --- Fix A: redact the apikey in the error log ---------------------------
_REDACT_ANCHOR = "'mdblist error', str(e)"
_REDACT_REPLACEMENT = (
    "'mdblist error', "
    "__import__('re').sub(r'apikey=[^&\\s]+', 'apikey=***', str(e))")
# Distinctive slice of the replacement -> idempotency check.
_REDACT_DONE = "__import__('re').sub(r'apikey="

# --- Fix B: scrobble/stop@100 on mark-watched ----------------------------
# Anchor = the line immediately after the sync/watched POST (unique in the file;
# `result = call_mdblist(...)` itself appears 3x, so we can't use that).
_SCROBBLE_ANCHOR = '\tsuccess = result[result_key][success_key] > 0'
_SCROBBLE_INJECT = (
    '\t' + SCROBBLE_MARKER + '\n'
    "\tif action == 'mark_as_watched' and key == 'tmdb' and media in ('movies', 'episode'):\n"
    '\t\ttry:\n'
    "\t\t\tif media == 'movies': _ai_sd = {'movie': {'ids': {'tmdb': media_id}}, 'progress': 100.0}\n"
    "\t\t\telse: _ai_sd = {'show': {'ids': {'tmdb': media_id}, 'season': {'number': int(season), 'episode': {'number': int(episode)}}}, 'progress': 100.0}\n"
    "\t\t\tcall_mdblist('scrobble/stop', json=_ai_sd, method='post')\n"
    '\t\texcept Exception: pass\n'
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_mdblist_patcher: ' + msg, level=level)
    except Exception:
        pass


def heal_mdblist_account():
    """Repair the 'No MDBList Account Active' state.

    POV keys the ENTIRE MDBList account on `mdblist_user`, not on the token:
    mdbl_sync_activities() bails with 'no account' when it's empty, the list
    manager (setting_key='mdblist_user') shows "no results", and the sync
    monitor aborts -- while direct scrobbling still works because that only
    needs `mdblist.token`. A connect that couldn't capture the username (a
    transient /user error at connect time, or the ambiguous save-anyway path)
    leaves the token set but `mdblist_user` blank, silently disabling
    everything account-scoped.

    Heal: if the token is present but `mdblist_user` is empty, fetch the
    username from MDBList's /user endpoint and store it (+ re-assert the
    indicator flag). One HTTP call, only while actually broken; safe no-op once
    healed or when nothing is connected. Returns a short status string."""
    try:
        import xbmcaddon
        pov = xbmcaddon.Addon('plugin.video.pov')
    except Exception:
        return 'no_pov'
    try:
        token = (pov.getSetting('mdblist.token') or '').strip()
        user = (pov.getSetting('mdblist_user') or '').strip()
    except Exception:
        return 'read_failed'
    if not token or user:
        return 'ok'                      # nothing connected, or already healthy
    try:
        import json
        import urllib.parse
        import urllib.request
        url = ('https://api.mdblist.com/user?apikey='
               + urllib.parse.quote(token, safe=''))
        req = urllib.request.Request(url, headers={'User-Agent': 'kodi-pov-il'})
        # Short timeout: this runs in the sequential boot-repair loop, so a
        # hung api.mdblist.com must not stall startup (matches POV's own 5.05s).
        with urllib.request.urlopen(req, timeout=5) as resp:
            if getattr(resp, 'status', 200) != 200:
                return 'fetch_failed'
            data = json.loads(resp.read().decode('utf-8', 'replace'))
        username = str((data or {}).get('username') or '').strip()
    except Exception:
        return 'fetch_failed'            # transient -> retry next boot
    if not username:
        return 'no_username'
    try:
        # Write the gate value (mdblist_user) LAST: if the first write fails,
        # mdblist_user stays empty so the next boot simply retries.
        pov.setSetting('mdbl_indicators_active', 'true')
        pov.setSetting('mdblist_user', username)
        healed = (pov.getSetting('mdblist_user') or '').strip() == username
    except Exception:
        return 'write_failed'
    if healed:
        _log('healed empty mdblist_user -> account now active', level='INFO')
        return 'healed'
    return 'write_failed'


def _mdblist_api_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, MDBLIST_API_REL)
    return p if os.path.isfile(p) else ''


def ensure_patched():
    """Idempotent. Returns one of:
    'no_pov' | 'no_file' | 'already_patched' | 'unmatched'
    | 'read_failed' | 'compile_failed' | 'write_failed' | 'patched'."""
    path = _mdblist_api_path()
    if not path:
        return 'no_pov' if xbmcvfs is None else 'no_file'

    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed for {0}: {1}'.format(path, e), level='WARNING')
        return 'read_failed'

    already_redact = _REDACT_DONE in content
    already_scrobble = SCROBBLE_MARKER in content
    already_guard = NONE_GUARD_MARKER in content
    already_sync = SYNC_GUARD_MARKER in content
    if already_redact and already_scrobble and already_guard and already_sync:
        return 'already_patched'

    new_content = content
    applied = []

    # Fix A -- redact apikey in the error log.
    if not already_redact and _REDACT_ANCHOR in new_content:
        new_content = new_content.replace(
            _REDACT_ANCHOR, _REDACT_REPLACEMENT, 1)
        applied.append('redact')

    # Fix B -- scrobble/stop@100 on mark-watched (insert before the anchor).
    if not already_scrobble and _SCROBBLE_ANCHOR in new_content:
        new_content = new_content.replace(
            _SCROBBLE_ANCHOR, _SCROBBLE_INJECT + _SCROBBLE_ANCHOR, 1)
        applied.append('scrobble')

    # Fix C -- None-guard add_to_list / add_to_collection (no crash on a 404).
    if not already_guard:
        if _ADDLIST_ANCHOR in new_content:
            new_content = new_content.replace(_ADDLIST_ANCHOR, _ADDLIST_GUARDED, 1)
            applied.append('none_guard_list')
        if _ADDCOLL_ANCHOR in new_content:
            new_content = new_content.replace(_ADDCOLL_ANCHOR, _ADDCOLL_GUARDED, 1)
            applied.append('none_guard_coll')

    # Fix E -- guard mdbl_sync_activities against a corrupt cached value.
    if not already_sync and _SYNC_ANCHOR in new_content:
        new_content = new_content.replace(
            _SYNC_ANCHOR, _SYNC_ANCHOR + _SYNC_INJECT, 1)
        applied.append('sync_guard')

    if not applied:
        _log('no mdblist_api anchors matched -- POV version differs; '
             'leaving file alone', level='WARNING')
        return 'unmatched'

    # SAFETY: never write a file that doesn't compile.
    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'

    tmp_path = path + '.aitmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp_path, path)
    except OSError as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        _log('write failed for {0}: {1}'.format(path, e), level='WARNING')
        return 'write_failed'

    # Drop stale .pyc so Python recompiles on next import.
    pycache_dir = os.path.join(os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache_dir):
        for fn in os.listdir(pycache_dir):
            if fn.startswith('mdblist_api.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache_dir, fn))
                except OSError:
                    pass

    _log('patched mdblist_api ({0})'.format(', '.join(applied)), level='INFO')
    return 'patched'


def ensure_manager_patched():
    """Stable-id fix for menus/mdblist.py get_default_choices (Watchlist /
    Collection routing under a Hebrew UI). Same return codes as ensure_patched."""
    if xbmcvfs is None:
        return 'no_pov'
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return 'no_pov'
    path = os.path.join(base, MENUS_MDBLIST_REL)
    if not os.path.isfile(path):
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed for {0}: {1}'.format(path, e), level='WARNING')
        return 'read_failed'
    if MANAGER_MARKER in content:
        return 'already_patched'
    if _MANAGER_ANCHOR_ORIG in content:
        anchor = _MANAGER_ANCHOR_ORIG
    elif _MANAGER_ANCHOR_V1 in content:
        anchor = _MANAGER_ANCHOR_V1            # upgrade a 0.2.429 two-choice patch
    else:
        _log('menus/mdblist get_default_choices anchor not found -- POV version '
             'differs; leaving file alone', level='WARNING')
        return 'unmatched'
    new_content = content.replace(anchor, _MANAGER_REPLACEMENT, 1)
    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('manager patch would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'
    tmp_path = path + '.aitmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp_path, path)
    except OSError as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        _log('write failed for {0}: {1}'.format(path, e), level='WARNING')
        return 'write_failed'
    pycache_dir = os.path.join(os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache_dir):
        for fn in os.listdir(pycache_dir):
            if fn.startswith('mdblist.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache_dir, fn))
                except OSError:
                    pass
    _log('patched menus/mdblist (stable Watchlist/Collection ids)', level='INFO')
    return 'patched'
