# -*- coding: utf-8 -*-
"""
Widget Rendering Budget Wrapper
Engine v2 encapsulated logic for limiting metadata payload computations when rendering POV on the home screen.
"""

def wrap_worker(instance, original_worker):
    """
    Wraps the native POV worker closure/method to chunk list items based on the 'widget_limit' param.
    If backfilling is necessary (e.g., due to hidden watched items), the wrapper doubles the chunk.
    """

    # Preserve POV's full-page behaviour if widget_hide_watched is False to avoid short rows.
    if not getattr(instance, 'is_widget', False) or getattr(instance, 'widget_hide_watched', False) is False:
        return original_worker

    try:
        widget_limit = int(instance.params.get('widget_limit', 0) or 0)
    except (TypeError, ValueError):
        widget_limit = 0

    if widget_limit <= 0 or not getattr(instance, 'list', []):
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
        if profile_age_guard.active_policy() is not None:
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
