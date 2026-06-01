# Bulletproof publisher of `subs.player_filename` -- the Window(10000)
# property DarkSubs natively reads into Tagline_From_Fen. By the time
# our `xbmc.Player` subclass's onAVStarted() fires, the player has
# the current title/season/episode/quality info-labels populated, so
# we can synthesise a release-style filename and publish it
# unconditionally.
#
# Why bother when we already have pov_source_name_patcher?
#   POV declares <reuselanguageinvoker>true</reuselanguageinvoker> in
#   its addon.xml, which means Kodi keeps the Python interpreter (and
#   imported modules) in memory across plugin invocations. The
#   sources.py file we rewrote on disk only gets picked up after a
#   FULL Kodi restart -- not after quick_update + addon reload. So
#   on the first playback after the user upgrades, POV's _process()
#   may still be running the old in-memory code that never writes
#   subs.player_filename, and the subtitle dialog still shows the
#   UUID.
#
# This publisher runs in OUR addon's service process, which is
# orthogonal to POV's interpreter state. onAVStarted fires for EVERY
# playback, including POV's, the moment the AV stream starts. We
# read whatever POV's window properties expose (if its patch is
# active) and fall back to VideoPlayer / ListItem info-labels so we
# always have a value to publish.
#
# This also benefits non-POV playbacks: any addon that plays a video
# whose URL ends in an opaque hash (rare outside debrid CDNs) gets
# the same treatment.

import re

try:
    import xbmc
    import xbmcgui
except Exception:
    xbmc = None
    xbmcgui = None


_VIDEO_EXTS = ('.mkv', '.mp4', '.avi', '.m4v', '.mov', '.webm',
               '.ts', '.m2ts')
_RELEASE_TOKENS = ('1080p', '720p', '2160p', '480p', 'bluray',
                   'webrip', 'web-dl', 'hdtv', 'x264', 'x265',
                   'hevc', 'remux', 'amzn', 'nflx', 'dsnp',
                   'atvp', 'hmax')


def _looks_like_hash(name):
    """Same heuristic as the DarkSubs patcher's helper: True iff
    `name` has no recognisable release-name tokens. Used to detect
    UUIDs returned by CDNs that strip the filename from the URL."""
    if not name:
        return True
    lower = name.lower()
    for ext in _VIDEO_EXTS:
        if lower.endswith(ext):
            return False
    for tok in _RELEASE_TOKENS:
        if tok in lower:
            return False
    if re.search(r's\d{1,2}e\d{1,3}', lower):
        return False
    hex_chars = sum(1 for c in name if c in '0123456789abcdefABCDEF-')
    return hex_chars / max(len(name), 1) > 0.80


def _synthesise_from_info_labels():
    """Build a release-style filename `Title.SxxExx.QUALITYp.mkv`
    from VideoPlayer / ListItem info-labels. Returns '' if we can't
    even get a title (e.g. early in playback startup before Kodi
    has populated the labels)."""
    if xbmc is None:
        return ''
    title = (xbmc.getInfoLabel('VideoPlayer.Title') or
             xbmc.getInfoLabel('VideoPlayer.OriginalTitle') or
             xbmc.getInfoLabel('ListItem.OriginalTitle') or
             xbmc.getInfoLabel('ListItem.Title'))
    if not title:
        return ''
    season = (xbmc.getInfoLabel('VideoPlayer.Season') or
              xbmc.getInfoLabel('ListItem.Season'))
    episode = (xbmc.getInfoLabel('VideoPlayer.Episode') or
               xbmc.getInfoLabel('ListItem.Episode'))
    year = (xbmc.getInfoLabel('VideoPlayer.Year') or
            xbmc.getInfoLabel('ListItem.Year'))
    quality = xbmc.getInfoLabel('VideoPlayer.VideoResolution')
    parts = [title.replace(' ', '.')]
    try:
        s, e = int(season), int(episode)
        parts.append('S{0:02d}E{1:02d}'.format(s, e))
    except (ValueError, TypeError):
        if year:
            parts.append(str(year))
    if quality and quality.isdigit():
        parts.append(quality + 'p')
    return '.'.join(parts) + '.mkv'


def _pick_best_name(window):
    """Choose the best available release name in priority order.
    Returns '' if nothing usable is available yet."""
    # 1) POV's pov_source_name_patcher writes this with the exact
    #    release name from the source-select dialog. Best signal.
    name = window.getProperty('pov_picked_source_name') or ''
    if name:
        return name
    # 2) Some other addon may have already written subs.player_filename
    #    -- preserve it if it looks meaningful.
    existing = window.getProperty('subs.player_filename') or ''
    if existing and not _looks_like_hash(existing):
        return existing
    # 3) Last resort: synthesise from info-labels.
    return _synthesise_from_info_labels()


class SubsFilenamePublisher(xbmc.Player if xbmc else object):
    """xbmc.Player subclass that publishes `subs.player_filename`
    on every onAVStarted. Held by service.main() for the lifetime
    of the Kodi run."""

    def __init__(self):
        if xbmc is not None:
            xbmc.Player.__init__(self)

    def onAVStarted(self):  # pylint: disable=invalid-name
        try:
            self._publish()
        except Exception:
            # Never let a publisher hiccup break playback or the
            # subtitle dialog -- the user can still pick subtitles
            # by hand if our auto-rename fails.
            pass

    def onPlayBackStarted(self):  # pylint: disable=invalid-name
        # Some Kodi 19 builds fire onPlayBackStarted earlier than
        # onAVStarted; publish on both to be safe. Idempotent on
        # the property side.
        try:
            self._publish()
        except Exception:
            pass

    def _publish(self):
        if xbmcgui is None:
            return
        w = xbmcgui.Window(10000)
        name = _pick_best_name(w)
        if not name:
            return
        # Mirror to both properties so:
        #  - subs.player_filename → DarkSubs Tagline_From_Fen, AND
        #    the FENtastic DialogSubtitles patched header.
        #  - pov_picked_source_name → still consumed by our
        #    darksubs_filename_fallback_patcher's URL guard. Only
        #    set if not already set (avoid clobbering POV's value).
        w.setProperty('subs.player_filename', name)
        if not w.getProperty('pov_picked_source_name'):
            w.setProperty('pov_picked_source_name', name)
            try:
                cu = xbmc.Player().getPlayingFile() or ''
            except Exception:
                cu = ''
            w.setProperty('pov_picked_source_url', cu)
