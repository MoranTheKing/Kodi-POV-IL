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
POV_SETTINGS_REL = 'resources/lib/modules/settings.py'

# --- Fix G: default the Watchlist/Collection sort to "Date Added" -----------
# POV reads the personal-list sort via lists_sort_order(setting) ->
# int(get_setting('sort.%s' % setting, '0')); default 0 = Title (A-Z), 1 =
# Date Added, 2 = Release Date. Writing sort.watchlist=1 cross-addon does NOT
# stick (POV serves settings from a cached `pov_settings` window-property JSON
# that our boot-time write never invalidates -- POV isn't even running then).
# So we patch the READER instead: when the stored value is 0/empty (the default
# nobody chose), return 1 (Date Added) for watchlist/collection only, leaving
# progress/watched (which share this function) exactly as POV had them. A user
# who deliberately picks Date Added(1)/Release(2) via POV's own sort menu keeps
# it; only the never-chosen A-Z default flips to recency. Deterministic (code
# patch), independent of any setting-write persistence.
SORT_DEFAULT_MARKER = '# AI_SUBS_SORT_RECENT_DEFAULT_v1'
# POV 6.08 gave lists_sort_order a per-mediatype fork: the single return line
# became three, one per media type. The fix is the same (default Watchlist /
# Collection to date-added-desc when the user never chose a sort), so it now
# reads whichever of the three settings applies and post-processes ONE value.
# Older POV's single-line shape stays listed so a device behind on POV is still
# patched. The 6.08 block is tried first as a hedge: on today's 6.08.05 bytes
# the legacy anchor cannot match at all (its leading tab is followed by `if
# mediatype is None: `, never by `return`), but a future shape that reintroduces
# a bare-tab return alongside the fork would let the legacy anchor bite into it,
# and specific-before-general is the ordering that stays right either way.
_SORT_DEFAULT_ANCHOR_V608 = (
    "\tif mediatype is None: return int(get_setting('sort.%s' % setting, '0'))\n"
    "\tif mediatype in ('movie', 'movies'): return int(get_setting('sort.%s_movies' % setting, '0'))\n"
    "\treturn int(get_setting('sort.%s_shows' % setting, '0'))")
_SORT_DEFAULT_REPLACEMENT_V608 = (
    "\tif mediatype is None: _ai_v = get_setting('sort.%s' % setting, '0')  "
    + SORT_DEFAULT_MARKER + "\n"
    "\telif mediatype in ('movie', 'movies'): _ai_v = get_setting('sort.%s_movies' % setting, '0')\n"
    "\telse: _ai_v = get_setting('sort.%s_shows' % setting, '0')\n"
    "\ttry: _ai_v = int(_ai_v)\n"
    "\texcept Exception: _ai_v = 0\n"
    "\treturn (_ai_v or 1) if setting in ('watchlist', 'collection') else _ai_v")

_SORT_DEFAULT_ANCHOR_LEGACY = "\treturn int(get_setting('sort.%s' % setting, '0'))"
_SORT_DEFAULT_REPLACEMENT_LEGACY = (
    "\t_ai_v = get_setting('sort.%s' % setting, '0')  " + SORT_DEFAULT_MARKER + "\n"
    "\ttry: _ai_v = int(_ai_v)\n"
    "\texcept Exception: _ai_v = 0\n"
    "\treturn (_ai_v or 1) if setting in ('watchlist', 'collection') else _ai_v")

_SORT_DEFAULT_PAIRS = (
    (_SORT_DEFAULT_ANCHOR_V608, _SORT_DEFAULT_REPLACEMENT_V608),
    (_SORT_DEFAULT_ANCHOR_LEGACY, _SORT_DEFAULT_REPLACEMENT_LEGACY),
)

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
# THE TAIL OF THESE LINES IS NOT PINNED, and 6.08.14 is why. POV changed
# `kodi_utils.notification(32574)` to `kodi_utils.notify_failed()` on all three
# of these one-liners, and the literal anchors stopped matching -- the device
# log said `no mdblist_api anchors matched -- POV version differs` on every
# boot while the None-guard quietly went missing.
#
# What identifies the line is its HEAD: `if result['<key>']['movies'] +
# result['<key>']['shows'] == 0: return `. The rest is whatever POV currently
# calls to say "that failed", and is preserved verbatim rather than rewritten,
# so this survives the next rename of the notify helpers too.
_ADDLIST_HEAD = ("if result['added']['movies'] + result['added']['shows'] "
                 "== 0: return ")
_ADDCOLL_HEAD = ("if result['updated']['movies'] + result['updated']['shows'] "
                 "== 0: return ")


def _guard_none(content, head):
    """Prepend `not result or` to the one-liner starting with `head`.

    Returns (content, changed). Idempotent: the guarded line no longer starts
    with the bare head, because `if not result or ...` does.
    """
    at = content.find('\t' + head)
    if at < 0:
        at = content.find('\n' + head)
        if at < 0:
            return content, False
        at += 1
    else:
        at += 1
    end = content.find('\n', at)
    if end < 0:
        return content, False
    line = content[at:end]
    if line.startswith('if not result or'):
        return content, False
    guarded = ('if not result or ' + line[len('if '):] + '  '
               + NONE_GUARD_MARKER)
    return content[:at] + guarded + content[end:], True

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

# --- Fix F: merge the Collection into the Watchlist view --------------------
# The user's MDBList content is split: titles added via the manager go to the
# Watchlist, while a Trakt import lands in the Collection ("Recently Added" on
# mdblist.com). They want ONE "My Movies / My Series (MDBList)" list showing both,
# newest first -- not a second pair of tiles. So we patch mdblist_watchlist() to
# append the Collection items (deduped by tmdb id) to the watchlist list, shaped
# like watchlist rows (id/imdb_id/title + release_date from year for the unaired
# filter + watchlist_at from collected_at for the recency sort). POV's existing
# unaired-filter + sort then run over the merged list, so with the recently-added
# sort (Fix in ensure_lists_sort_recent) the newest addition from EITHER list
# leads. Reuses POV's cached 'mdbl_collection' object (no extra API cost). Fail-
# open: any error leaves the watchlist exactly as POV built it. Injected before
# the unique unaired-filter line so the merged rows are filtered+sorted too.
MERGE_MARKER = '# AI_SUBS_MDBL_MERGE_COLLECTION_v1'
_MERGE_ANCHOR = '\tif not settings.show_unaired_watchlist():'
_MERGE_INJECT = (
    '\t' + MERGE_MARKER + '\n'
    '\ttry:\n'
    "\t\t_ai_mk = 'movie' if mediatype in ('movie', 'movies') else 'show'\n"
    '\t\t_ai_seen = set(i.get(\'id\') for i in original_list)\n'
    "\t\t_ai_coll = mdbl_collection_watchlist_items('mdbl_collection', 'sync/collection')[mediatype]\n"
    '\t\tfor _ai_ci in _ai_coll:\n'
    '\t\t\t_ai_o = _ai_ci.get(_ai_mk) or {}\n'
    "\t\t\t_ai_ids = _ai_o.get('ids') or {}\n"
    "\t\t\t_ai_id = _ai_ids.get('tmdb')\n"
    '\t\t\tif not _ai_id or _ai_id in _ai_seen: continue\n'
    '\t\t\t_ai_seen.add(_ai_id)\n'
    "\t\t\t_ai_yr = _ai_o.get('year')\n"
    "\t\t\toriginal_list.append({'id': _ai_id, 'imdb_id': _ai_ids.get('imdb'), "
    "'title': _ai_o.get('title'), 'release_date': "
    "(('%d-01-01' % _ai_yr) if _ai_yr else '1900-01-01'), "
    "'watchlist_at': _ai_ci.get('collected_at') or ''})\n"
    '\texcept Exception: pass\n')

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


# Our own addon setting that records the one-time list-sort migration ran, so we
# never fight a user who later changes the sort via POV's in-list "sort by" menu.
SORT_RECENT_MARKER = '_lists_sort_recent_v1'


def ensure_lists_sort_recent():
    """Default POV's personal-list sort to 'recently added' (newest first).

    POV lists the Watchlist / Collection views (MDBList, Trakt AND TMDB, plus the
    combined 'My Movies/My Series' rows that read them) via two settings:
    `sort.watchlist` and `sort.collection`, each 0=title A-Z, 1=date-added desc,
    2=release date. The default is 0 (alphabetical) -- which is why a title added
    today can appear in the middle/end instead of first. We flip both to 1 ONCE
    (guarded by our own addon marker) so the newest addition leads; a later manual
    change through POV's own 'sort by' menu is then respected forever. Only
    upgrades the default value (0/empty) -- never overrides a deliberate non-
    default choice. Skin-independent (this is POV's data layer), so it applies on
    every skin. Safe no-op without POV."""
    if kodi_utils is None:
        return 'no_kodi'
    try:
        if (kodi_utils.get_setting(SORT_RECENT_MARKER, '') or '') == 'done':
            return 'already'
    except Exception:
        return 'read_failed'
    try:
        import xbmcaddon
        pov = xbmcaddon.Addon('plugin.video.pov')
    except Exception:
        return 'no_pov'
    changed = []
    try:
        for key in ('sort.watchlist', 'sort.collection'):
            cur = (pov.getSetting(key) or '').strip()
            # Only raise the DEFAULT (empty/'0' = alphabetical). Respect a user who
            # deliberately picked release-date ('2') or already recently-added.
            if cur in ('', '0'):
                pov.setSetting(key, '1')
                changed.append(key)
    except Exception:
        return 'write_failed'
    # Stamp the marker so this runs exactly once. If the marker write can't persist
    # we still return 'set' -- worst case it re-applies next boot, which is
    # idempotent (cur becomes '1' -> skipped), never a fight.
    try:
        kodi_utils.set_setting(SORT_RECENT_MARKER, 'done')
    except Exception:
        pass
    if changed:
        _log('defaulted list sort to recently-added ({0})'.format(
            ', '.join(changed)), level='INFO')
        return 'set'
    return 'ok'


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
    except Exception as e:
        _log('read failed for {0}: {1}'.format(path, e), level='WARNING')
        return 'read_failed'

    already_redact = _REDACT_DONE in content
    already_scrobble = SCROBBLE_MARKER in content
    already_guard = NONE_GUARD_MARKER in content
    already_sync = SYNC_GUARD_MARKER in content
    already_merge = MERGE_MARKER in content
    if (already_redact and already_scrobble and already_guard
            and already_sync and already_merge):
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
        new_content, _did_addlist = _guard_none(new_content, _ADDLIST_HEAD)
        if _did_addlist:
            applied.append('none_guard_list')
        new_content, _did_addcoll = _guard_none(new_content, _ADDCOLL_HEAD)
        if _did_addcoll:
            applied.append('none_guard_coll')

    # Fix E -- guard mdbl_sync_activities against a corrupt cached value.
    if not already_sync and _SYNC_ANCHOR in new_content:
        new_content = new_content.replace(
            _SYNC_ANCHOR, _SYNC_ANCHOR + _SYNC_INJECT, 1)
        applied.append('sync_guard')

    # Fix F -- merge the Collection into the Watchlist view (insert before anchor).
    if not already_merge and _MERGE_ANCHOR in new_content:
        new_content = new_content.replace(
            _MERGE_ANCHOR, _MERGE_INJECT + _MERGE_ANCHOR, 1)
        applied.append('merge_collection')

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


def ensure_sort_default_patched():
    """Fix G: default the Watchlist/Collection sort to Date Added (recency) by
    patching POV's modules/settings.py lists_sort_order(). Same return codes as
    ensure_patched. Skin-independent; deterministic (a code patch, so it doesn't
    depend on any cross-addon setting write persisting)."""
    if xbmcvfs is None:
        return 'no_pov'
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return 'no_pov'
    path = os.path.join(base, POV_SETTINGS_REL)
    if not os.path.isfile(path):
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        _log('read failed for {0}: {1}'.format(path, e), level='WARNING')
        return 'read_failed'
    if SORT_DEFAULT_MARKER in content:
        return 'already_patched'
    anchor = replacement = None
    for _anchor, _replacement in _SORT_DEFAULT_PAIRS:
        if _anchor in content:
            anchor, replacement = _anchor, _replacement
            break
    if anchor is None:
        _log('modules/settings lists_sort_order anchor not found -- POV version '
             'differs; leaving file alone', level='WARNING')
        return 'unmatched'
    new_content = content.replace(anchor, replacement, 1)
    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('sort-default patch would not compile -- skipping ({0})'.format(e),
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
            if fn.startswith('settings.') and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache_dir, fn))
                except OSError:
                    pass
    _log('patched modules/settings (watchlist/collection sort -> recency default)',
         level='INFO')
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
    except Exception as e:
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
