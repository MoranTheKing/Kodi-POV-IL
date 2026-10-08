# -*- coding: utf-8 -*-
"""
Widget Rendering Budget Wrapper
Engine v2 encapsulated logic for limiting metadata payload computations when rendering POV on the home screen.
"""

def _native_order(params):
    """Keep complete candidates when the skin sorts the result before limiting.

    AF3 stores sorting outside the plugin URL. Read the active profile's row
    definition, so a custom rating/title/random/reverse sort is never reduced
    to the provider's first items. Unknown rows keep their native full worker.
    """
    if any(params.get(key, '') not in ('', 'default', 'none')
           for key in ('sortby', 'widget_sortby')):
        return False
    if params.get('sortorder', '') not in ('', 'ascending'):
        return False
    import xbmc
    if xbmc.getSkinDir() != 'skin.arctic.fuse.3':
        return True
    import json
    import xbmcvfs
    from urllib.parse import parse_qsl, urlparse
    ignored = ('name', 'iconImage', 'widget_limit')
    requested = {key: str(value) for key, value in params.items() if key not in ignored}
    path = xbmcvfs.translatePath('special://profile/addon_data/script.skinvariables/nodes/'
                                'skin.arctic.fuse.3/skinvariables-shortcut-homewidgets.json')
    try:
        with open(path, encoding='utf-8') as handle:
            rows = json.load(handle)
        matches = []
        for row in rows:
            route = urlparse(row.get('path', '').replace('&amp;', '&'))
            if route.netloc != 'plugin.video.pov':
                continue
            values = {key: value for key, value in parse_qsl(route.query) if key not in ignored}
            if values == requested:
                matches.append(row)
        return bool(matches) and all(
            row.get('widget_sortby', '') in ('', 'default', 'none') and
            row.get('widget_sortorder', '') in ('', False, None, 'false')
            for row in matches)
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def wrap_worker(instance, original_worker):
    """
    Wraps the native POV worker closure/method to chunk list items based on the 'widget_limit' param.
    If backfilling is necessary (e.g., due to hidden watched items), the wrapper doubles the chunk.
    """

    # An explicit home-row limit bounds metadata even when watched titles are
    # visible. Missing metadata and hidden watched titles are both backfilled.
    # Normal directories carry no row limit and retain their complete page.
    if not getattr(instance, 'is_widget', False):
        return original_worker

    try:
        widget_limit = int(instance.params.get('widget_limit', 0) or 0)
    except (TypeError, ValueError):
        widget_limit = 0

    if widget_limit <= 0 or not getattr(instance, 'list', []):
        return original_worker

    if not _native_order(instance.params):
        return original_worker

    # Child publication filters by classification after the native worker.
    # It needs the complete candidate page, including unrated/blocked titles.
    try:
        import profile_age_guard
        policy = (profile_age_guard.work_policy(instance.params)
                  if hasattr(profile_age_guard, 'work_policy') else profile_age_guard.active_policy())
        if policy is not None:
            return original_worker
    except (ImportError, OSError, ValueError):
        return original_worker

    original_source = instance.list
    target_count = min(widget_limit, 50, len(original_source))

    def _budgeted_worker():
        current_count = target_count
        try:
            while True:
                # Constrain the target scope
                instance.list = original_source[:current_count]
                instance.items = []
                instance.append = instance.items.append

                # Execute native generation for the constrained subset
                result_items = original_worker()

                # Check if we hit our target or exhausted the available source items
                if len(result_items) >= target_count or current_count >= len(original_source):
                    break

                # Backfill logic (if items were omitted, fetch a larger subset dynamically)
                current_count = min(
                    len(original_source),
                    max(current_count * 2, current_count + target_count - len(result_items))
                )

            # Return bounded list output
            return result_items[:target_count]

        finally:
            # Restore state ensuring no permanent data mutation exists in POV object
            instance.list = original_source

    return _budgeted_worker
def _preview_art(instance, rows):
    """Use HD thumbnails for the High preset; explicit Original stays intact."""
    resolutions = getattr(instance, 'meta_user_info', {}).get('image_resolution', {})
    if resolutions.get('still') != 'original' or resolutions.get('poster') != 'w780':
        return rows
    for row in rows:
        item = row[1]
        thumb = item.getArt('thumb')
        for prefix in ('https://image.tmdb.org/t/p/original/', 'http://image.tmdb.org/t/p/original/'):
            if thumb.startswith(prefix):
                item.setArt({'thumb': prefix.replace('/original/', '/w1280/') + thumb[len(prefix):]})
                break
    return rows


def wrap_next_episode_worker(instance, original_worker):
    """Bound the default recent-history preview without changing native order.

    Last-played timestamps exist before metadata is fetched. Other sorts,
    airing-today promotion require the full native worker. Unaired entries are
    backfilled until enough aired episodes exist, preserving native priority.
    Child filtering also needs the full candidate set to avoid short safe rows.
    Opening the normal next-episode directory has no widget limit and is intact.
    """
    opts = getattr(instance, 'nextep_settings', {})
    source = getattr(instance, 'list', [])
    if (not getattr(instance, 'is_widget', False) or
            not getattr(instance, 'list_type', '').startswith('next_episode') or
            opts.get('sort_key') != 'pov_last_played' or
            opts.get('sort_airing_today_to_top') or
            not source):
        return original_worker
    try:
        limit = int(instance.params.get('widget_limit', 0))
        fallback = instance.resinsert
        if limit <= 0 or not isinstance(fallback, str) or any(
                not isinstance(row, dict) or not isinstance(row.get('last_played', fallback), str)
                for row in source):
            return original_worker
        import profile_age_guard
        policy = (profile_age_guard.work_policy(instance.params)
                  if hasattr(profile_age_guard, 'work_policy') else profile_age_guard.active_policy())
        if policy is not None:
            return original_worker
    except (ValueError, TypeError, AttributeError, ImportError):
        return original_worker
    ordered = sorted(source, key=lambda row: row.get('last_played', fallback),
                     reverse=opts.get('sort_direction', True))
    target = min(limit, 50, len(source))

    def budgeted():
        count = target
        try:
            while True:
                instance.list = ordered[:count]
                instance.items = []
                instance.append = instance.items.append
                result = original_worker()
                eligible = (sum(row[1].getProperty('pov_unaired') != 'true' for row in result)
                            if opts.get('include_unaired') else len(result))
                if eligible >= target or count >= len(source):
                    return _preview_art(instance, result[:target])
                # Completed/unavailable shows can produce no next episode.
                count = min(len(source), max(count * 2, count + target - eligible))
        finally:
            instance.list = source
    return budgeted
