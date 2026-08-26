# POV 6.08.14 indexes a dict with [0], and every AllDebrid playback fails.
#
# THE REPORT, 2026-08-26: "POV still does not work for anyone on AllDebrid",
# plus "no results on films and episodes that must have sources". Two field
# logs say the same thing, dozens of times each, once per source tried:
#
#     >> resolve_external_sources exception <<: 0
#        {'debrid': 'alldebrid', 'cache_provider': 'Unchecked alldebrid',
#         'hash': 'ed07a28e...', 'package': 'season', ...}
#
# An exception whose entire message is `0` is a KeyError with the key 0 -- a
# dict subscripted as if it were a list. It is one line, and it is new:
#
#     indexers/alldebrid_api.py  torrent_info()
#       6.08.13   result = result['magnets']
#       6.08.14   result = result['magnets'][0]     <-- added
#
# Same endpoint in both (`v4.1/magnet/status`), same params (`{'id': ...}`).
# Queried WITH an id, AllDebrid returns `magnets` as a single object; queried
# without one -- which is what 6.08.14's new `user_cloud()` does -- it returns
# a list. The `[0]` is right for the listing call and wrong for this one, and
# it landed on this one.
#
# WHY IT TAKES OUT PLAYBACK ENTIRELY. torrent_info() is called from
# parse_magnet_pack(), which is what resolve_external_sources() uses to turn a
# magnet into a playable file. It raises before any file is chosen, POV logs
# and returns None, and the player moves to the next source -- which fails the
# same way. That is exactly the "it goes through every source and plays
# nothing" people described, and to a user it is indistinguishable from having
# no sources at all.
#
# THE SAME LINE APPEARS TWICE IN THAT FILE AND ONLY ONE IS WRONG.
# create_transfer() calls `v4/magnet/upload`, which really does return a list
# because you may upload several magnets at once; it carried `[0]` in 6.08.13
# too and is untouched here. This patch matches the whole torrent_info body,
# not the line, so it cannot land on the other one.
#
# THE REPLACEMENT DOES NOT SIMPLY REVERT IT. Reverting to 6.08.13's
# `result['magnets']` would break the day AllDebrid starts returning a list
# here, or the day POV routes a listing call through this function -- and
# `user_folder()` already calls torrent_info() with a folder id, which is a
# shape nobody here can test. So the fix accepts both: use what the API
# returned, and index it only if it is a list. That is correct under either
# response and needs no further guess about which one AllDebrid sends.
#
# NOT REPORTED UPSTREAM FROM HERE. POV's author will fix this; the patch is
# marker-gated and reverts cleanly, so when 6.08.15 lands with its own repair
# the anchor stops matching and this quietly stops applying.

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


POV_ADDON_ID = 'plugin.video.pov'

MARKER = '# AI_SUBS_POV_AD_STATUS_v1'
_MARKER_ANY = '# AI_SUBS_POV_AD_STATUS_v'

# 6.08.14 moved the debrid clients from debrids/ to indexers/. Both are tried,
# newest layout first, because both are live in the field right now.
CANDIDATE_RELS = (
    'resources/lib/indexers/alldebrid_api.py',
    'resources/lib/debrids/alldebrid_api.py',
)

# The whole method, so the identical line in create_transfer() cannot match.
ANCHOR = (
    "\tdef torrent_info(self, transfer_id):\n"
    "\t\turl = 'v4.1/magnet/status'\n"
    "\t\tparams = {'id': transfer_id}\n"
    "\t\tresult = self._get(url, params)\n"
    "\t\tresult = result['magnets'][0]\n"
    "\t\treturn result"
)

REPLACEMENT = (
    "\tdef torrent_info(self, transfer_id):  " + MARKER + "\n"
    "\t\turl = 'v4.1/magnet/status'\n"
    "\t\tparams = {'id': transfer_id}\n"
    "\t\tresult = self._get(url, params)\n"
    "\t\tresult = result['magnets']\n"
    "\t\tif isinstance(result, list): result = result[0] if result else {}\n"
    "\t\treturn result"
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_alldebrid_status_fix: ' + msg, level=level)
    except Exception:
        pass


def _client_path():
    """AllDebrid's client, in whichever folder this POV keeps it."""
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    for rel in CANDIDATE_RELS:
        p = os.path.join(base, *rel.split('/'))
        if os.path.isfile(p):
            return p
    return ''


def _drop_pyc(path):
    """A stale .pyc would keep the broken method alive after the rewrite."""
    stem = os.path.basename(path)[:-3] + '.'
    cache = os.path.join(os.path.dirname(path), '__pycache__')
    try:
        for name in os.listdir(cache):
            if name.startswith(stem) and name.endswith('.pyc'):
                os.remove(os.path.join(cache, name))
    except Exception:
        pass


def ensure_patched():
    """Idempotent. Never raises.

    'no_pov' | 'unchanged' | 'patched' | 'unmatched' | 'read_failed'
    | 'compile_failed' | 'write_failed'
    """
    path = _client_path()
    if not path:
        return 'no_pov'
    try:
        with open(path, encoding='utf-8', newline='') as fh:
            content = fh.read()
    except Exception as exc:
        _log('read failed: {0}'.format(exc), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'unchanged'
    if _MARKER_ANY in content:
        # An older version of ours. Nothing to do until there is a v2 to
        # migrate to; guessing at a block we no longer describe corrupts POV.
        _log('carries an older version of this patch; leaving it alone',
             level='WARNING')
        return 'unchanged'

    eol = '\r\n' if '\r\n' in content[:8192] else '\n'
    fit = (lambda t: t.replace('\n', eol)) if eol != '\n' else (lambda t: t)
    anchor = fit(ANCHOR)
    if content.count(anchor) != 1:
        # Either POV fixed it (6.08.13's shape, or a 6.08.15 repair) or the
        # file is one we do not recognise. Both mean: leave POV alone.
        if "result['magnets'][0]" not in content:
            return 'unmatched'
        _log('alldebrid_api.py is not the shape this repairs '
             '({0} match(es)); leaving it alone'.format(content.count(anchor)),
             level='WARNING')
        return 'unmatched'

    new_content = content.replace(anchor, fit(REPLACEMENT), 1)
    try:
        compile(new_content.replace('\r\n', '\n'), path, 'exec')
    except SyntaxError as exc:
        _log('patched content would not compile -- skipping ({0})'.format(exc),
             level='WARNING')
        return 'compile_failed'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as fh:
            fh.write(new_content)
        os.replace(tmp, path)
    except Exception as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(exc), level='WARNING')
        return 'write_failed'
    _drop_pyc(path)
    _log('AllDebrid magnet status no longer indexes a dict with [0]; '
         'playback through AllDebrid works again at the next POV invocation')
    return 'patched'
