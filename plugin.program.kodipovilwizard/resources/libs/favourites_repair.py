"""Favourites whose command leads nowhere any more, repointed at start-up.

The build's "שליחת לוג" tile ran POV's "Changelog & Log Utils" menu (mode=navigator.log_utils), and POV 6.11.03
has no such menu: the tile opened nothing, on every device (the owner's LG on Kodi 22, Nov 2026, the log:
"GetDirectory - Error getting plugin://plugin.video.pov/?...mode=navigator.log_utils..."). It now runs the
Wizard's own uploader (mode=uploadlog), which posts the log and shows its address and a QR.

Only that tile's command changes: its name, its picture and its place stay as the viewer has them. The file of
the profile that is loaded is repaired at every start (another profile's, when it is loaded); a file with nothing
to repair is only read.
"""
import os
import re
import tempfile

FILE = 'special://profile/favourites.xml'
UPLOADER = b'RunPlugin("plugin://plugin.program.kodipovilwizard/?mode=uploadlog")'
_DEAD = b'mode=navigator.log_utils'
_TILE = re.compile(rb'(<favourite\b[^>]*>)([^<]*mode=navigator\.log_utils[^<]*)(</favourite>)')


def repoint(content):
    """(content, how many tiles were repointed): the favourites file's bytes with every "send log" tile that
    runs the dead POV menu running the Wizard's uploader."""
    if _DEAD not in content:
        return content, 0
    return _TILE.subn(lambda match: match.group(1) + UPLOADER + match.group(3), content)


def run(path=None, log=None):
    """Repair the loaded profile's favourites.xml; returns how many tiles were repointed."""
    if path is None:
        import xbmcvfs
        path = xbmcvfs.translatePath(FILE)
    try:
        with open(path, 'rb') as handle:
            content = handle.read()
    except OSError:
        return 0
    fixed, count = repoint(content)
    if not count:
        return 0
    folder = os.path.dirname(path) or '.'
    descriptor, temporary = tempfile.mkstemp(prefix='.favourites-', dir=folder)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(fixed)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    if log:
        log('[Favourites] "send log" runs the Wizard\'s uploader now (%d tile(s); POV has no log menu)' % count)
    return count
