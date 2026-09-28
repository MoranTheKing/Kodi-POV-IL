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