# File: plugin.program.kodipovilwizard/resources/lib/patches/pov_view_mode.py

import xbmc

def force_view(view_id, content):
    """
    Waits for the Kodi container content to settle (up to 10s), then aggressively
    applies the requested view mode repeatedly for ~1 second to prevent Kodi's
    delayed default view renderer from clobbering the user's choice.
    """
    if not view_id:
        return

    try:
        settled = -1
        # Loop up to 200 times x 50ms = 10 seconds maximum wait time.
        for _n in range(200):
            # Check if the container has finished loading the target content type
            if xbmc.getInfoLabel('Container.Content') == content:
                if settled < 0:
                    settled = _n

                # Apply the view mode.
                xbmc.executebuiltin('Container.SetViewMode(%s)' % view_id)

                # Continue reapplying it for exactly 20 ticks (~1 second) after settling.
                # This guarantees we win the race condition against Kodi's default skin loader.
                if _n - settled >= 20:
                    break
            else:
                # CRITICAL: Reset the timer if the container state flips temporarily.
                # This prevents false-positive matches during page-forward transitions
                # where the outgoing and incoming containers share the same content type.
                settled = -1

            xbmc.sleep(50)

    except Exception as e:
        xbmc.log(f"POV WIZARD PATCH ERROR (force_view): {e}", xbmc.LOGERROR)