"""The viewer's place in a POV film or episode, kept while it plays.

POV keeps a place (its resume point) only when a playback ends the ordinary way: its player saves it
at the stop. A Kodi that is closed, crashes or loses its power mid-way -- a TV switched off, a box
pulled from the wall, the LG's Kodi 22 crashing -- saves nothing, and the title is missing from
"המשך צפייה" (a viewer, Nov 2026: "I left a series in the middle of an episode, and it is not in
continue watching -- not with the series, not with the episodes").

So the place is saved while it plays as well: every SAVE_S seconds into POV's own resume points
(the build's default), every REMOTE_S seconds to Trakt or MDBList where the viewer keeps the watch
status there -- the very calls POV makes at the stop, without its full sync. Only between POV's own
limits (5% .. 80%): below them POV keeps no place, above them it marks the title watched; and not
while paused (the place does not move). The ordinary stop still saves the final place over these.

The patch pov_periodic_bookmark (patches_config.py) calls tick() from POV's playback loop, about
once a second.
"""
import time

SAVE_S = 60
REMOTE_S = 180


def tick(player, ws, settings, clock=time.monotonic):
    """One look from POV's playback loop: save the place when it is time. Never raises."""
    try:
        now = clock()
        if getattr(player, '_povil_saved_at', None) is None:
            player._povil_saved_at, player._povil_saved_time = now, None
            return
        indicators = settings.watched_indicators()
        if now - player._povil_saved_at < (REMOTE_S if indicators in (1, 2) else SAVE_S):
            return
        player._povil_saved_at = now
        if player.media_marked or not (player.set_resume <= player.current_point < player.set_watched):
            return
        if player.curr_time == player._povil_saved_time:
            return                  # paused: the place did not move
        player._povil_saved_time = player.curr_time
        if indicators in (1, 2):
            send = ws.mdbl_progress if indicators == 2 else ws.trakt_progress
            percent = round((float(player.curr_time) - 5) / float(player.total_time) * 100, 1)
            send('set_progress', player.mediatype, player.tmdb_id, percent, player.season, player.episode, refresh=False)
        else:
            ws.set_bookmark(player.mediatype, player.tmdb_id, player.curr_time, player.total_time, player.title,
                            player.season, player.episode, refresh='false')
    except Exception:
        pass
