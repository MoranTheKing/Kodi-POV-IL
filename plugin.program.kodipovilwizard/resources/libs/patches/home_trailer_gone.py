"""The home's trailer is gone before another add-on starts its player (Wizard 0.5.6).

Onyx plays a title's trailer behind the home's hero (resources/libs/trailers.py). A viewer who
presses the title while its trailer runs starts a film over it. POV's and Umbrella's players set
"nothing has happened yet", tell Kodi to play and wait for Kodi's first word about a playback --
and the first word used to be the TRAILER's "stopped": they took their own film for over before it
began, and it played with no resume point saved and no watched mark (review, Nov 2026; POV
modules/player.py, the lines after self.play).

Both already call the Wizard right before they start (profile_age_guard.permit_play). There the
trailer is stopped and waited for, so its "stopped" has been said before the add-on starts
listening. Only the trailer is ever stopped: the address of what plays must be the one the trailer
desk wrote in Window(home).Property(povil.tr.file).

Two things seen in the QA Kodi shape the code:
  * the stop is Kodi's built-in, never Python's Player.stop(): that call waits, holding Python,
    while Kodi asks the YouTube add-on's server (Python too) about the stream -- 40 s of a frozen
    screen, measured; the built-in returns at once and the same stop takes 0.02 s;
  * a trailer that is still OPENING is not stopped but waited for (the desk empties the property
    when it is over): Kodi's screen waits for a player that is told to stop while it opens.
"""
FILE = 'povil.tr.file'
OPEN_WAIT_S = 6.0   # how long a trailer that is still opening is waited for
GONE_WAIT_S = 2.0   # how long a stopped trailer may take to be gone
SETTLE_MS = 150     # Kodi's word about the stop reaches the add-on's player object while it sleeps
STEP_MS = 50


def before_play(xbmc=None, xbmcgui=None):
    """Returns True when a trailer was playing and has been stopped."""
    if xbmc is None:
        import xbmc
    if xbmcgui is None:
        import xbmcgui
    home = xbmcgui.Window(10000)
    player = xbmc.Player()
    waited = 0
    while True:
        ours = home.getProperty(FILE)
        if not ours:
            return False            # no trailer, or it is over
        try:
            playing = player.isPlaying()
            if playing and player.getPlayingFile() != ours:
                return False        # something else has the player: not this module's to touch
        except Exception:
            playing = False
        if playing:
            break
        # the trailer was handed to the player and shows no picture yet
        if waited >= OPEN_WAIT_S * 1000:
            return False
        xbmc.sleep(STEP_MS)
        waited += STEP_MS
    xbmc.executebuiltin('PlayerControl(Stop)')
    waited = 0
    while waited < GONE_WAIT_S * 1000:
        xbmc.sleep(STEP_MS)
        waited += STEP_MS
        try:
            if not player.isPlaying():
                break
        except Exception:
            break
    xbmc.sleep(SETTLE_MS)
    return True
