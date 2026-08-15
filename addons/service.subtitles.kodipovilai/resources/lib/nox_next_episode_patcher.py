# Fix the NOX fullscreen-OSD "next episode" button.
#
# The NOX skin (skin.povil.nox) OSD has a "הפרק הבא" button next to the
# change-source button. It fired:
#   RunPlugin(plugin://plugin.video.pov/?mode=play_media&mediatype=episode
#             &tmdb_id=$INFO[VideoPlayer.UniqueID(tmdb)]&season=..&episode=..&next=1)
# The old POV honoured `next=1` and played the NEXT episode. POV 6.07 dropped
# that: play_media no longer understands `next` (it computes the next episode
# internally from full meta a skin button can't supply), so the button errors
# instead of playing the next episode.
#
# Fix: repoint the button to POV's working "Next Episode" list
# (mode=build_next_episode), which 6.07 routes correctly. One extra tap, but no
# error. Marker-free/idempotent: detects the already-repointed onclick and the
# stale-call regex; no-op if neither is present (POV/skin changed it).

import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


NOX_SKIN_ID = 'skin.povil.nox'
OSD_REL_PATH = 'xml/VideoOSD.xml'

# The stale next=1 RunPlugin call (only this button carries &next=1).
_OLD_RE = re.compile(
    r'RunPlugin\(plugin://plugin\.video\.pov/\?mode=play_media.*?&amp;next=1\)',
    re.DOTALL)
# What we replace it with (POV's working next-episode list).
_NEW = ('ActivateWindow(Videos,&quot;plugin://plugin.video.pov/'
        '?mode=build_next_episode&amp;name=32483'
        '&amp;iconImage=next_episodes&quot;,return)')
# Sentinel proving we already repointed this button.
_DONE_TOKEN = 'mode=build_next_episode&amp;name=32483&amp;iconImage=next_episodes'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('nox_next_episode_patcher: ' + msg, level=level)
    except Exception:
        pass


def _osd_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/' + NOX_SKIN_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, OSD_REL_PATH.replace('/', os.sep))
    return p if os.path.isfile(p) else ''


def ensure_patched():
    """Returns 'patched' | 'already_patched' | 'no_nox' | 'no_file'
    | 'unmatched' | 'read_failed' | 'write_failed'."""
    path = _osd_path()
    if not path:
        return 'no_nox' if xbmcvfs is None else 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    if _DONE_TOKEN in content:
        return 'already_patched'
    if not _OLD_RE.search(content):
        _log('OSD next=1 button not found -- skin/POV changed it; leaving alone',
             level='WARNING')
        return 'unmatched'

    new_content = _OLD_RE.sub(_NEW, content, count=1)

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'

    _log('repointed NOX OSD next-episode button to build_next_episode',
         level='INFO')
    return 'patched'
