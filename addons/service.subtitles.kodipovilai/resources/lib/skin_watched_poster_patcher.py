# Draw the watched tick in the Poster view, which is the build's default.
#
# THE REPORT. "There is no tick on the poster." Checked in every other view --
# List, Shift, Wall, InfoWall, WideWall, WideInfoWall -- and the tick is there
# in all of them. Only the default view is missing it, in POV and in Umbrella
# alike, for movies and for seasons.
#
# WHAT IT IS NOT. Not the watched data: POV computes it in ONE place
# (menus/movies.py -> get_watched_status_movie) and that same function feeds
# the home widget, which does show the tick. Not a cache either -- a full Kodi
# restart changed nothing. And not a POV/Umbrella difference: the skin draws
# every video list, whichever add-on produced it.
#
# WHAT IT IS. skin.fentastic's Poster view builds its tiles from
# `InfoWallMovieLayout`, and that include has no watched control at all. The
# control exists only in `BigInfoWallMovieLayout`, which the other views use.
# So the tick was never drawn in Poster view, in any list, ever.
#
# WHY THE CONTROL GOES IN THE VIEW AND NOT IN THE SHARED LAYOUT. Adding it to
# `InfoWallMovieLayout` would be one edit instead of four -- and would draw a
# SECOND tick in every view that already has one, because several of them
# stack both layouts. The blast radius has to stay on the screen that was
# reported.
#
# skin.povil.nox is deliberately NOT patched: its Poster view already carries
# the control and shows the tick correctly (verified against the maintainer's
# own screenshots). A skin with no verified recipe here is left alone rather
# than patched on a guess -- a wrong coordinate ships a tick floating over
# somebody's artwork on every device.

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


MARKER = '<!-- AI_SUBS_WATCHED_POSTER_v1 -->'

# The include whose closing tag we insert after, and the position of the tick
# inside that tile. Both are per skin: the poster in skin.fentastic's tile is
# 235x324 starting at top=-10, so 12/270 sits inside its bottom-left corner.
RECIPES = {
    'skin.fentastic': {
        'rel': 'xml/View_51_Poster.xml',
        'include': 'InfoWallMovieLayout',
        'left': 12,
        'top': 270,
        'expected': 4,   # two itemlayouts + two focusedlayouts
    },
}


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('skin_watched_poster_patcher: ' + msg, level=level)
    except Exception:
        pass


def _skin_path(skin_id, rel):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/' + skin_id + '/')
    except Exception:
        return ''
    path = os.path.join(base, *rel.split('/'))
    return path if os.path.isfile(path) else ''


def _control(recipe, eol):
    lines = [
        MARKER,
        '<control type="image">',
        '\t<left>%d</left>' % recipe['left'],
        '\t<top>%d</top>' % recipe['top'],
        '\t<width>32</width>',
        '\t<height>32</height>',
        # The same variable every other view in this skin uses, so the tick
        # matches them exactly -- including resume and collection states, and
        # including whatever the skin's own theme does to it. Reimplementing
        # the condition here would drift from the rest of the skin the first
        # time upstream touches it.
        '\t<texture>$VAR[WallWatchedIconVar]</texture>',
        '</control>',
    ]
    indent = '\t\t\t\t\t\t'
    return eol + eol.join(indent + line for line in lines)


def _eol(content):
    return '\r\n' if '\r\n' in content else '\n'


def _patch_one(skin_id, recipe):
    """'patched' | 'already_patched' | 'no_skin' | 'unmatched'
    | 'parse_failed' | 'read_failed' | 'write_failed'."""
    path = _skin_path(skin_id, recipe['rel'])
    if not path:
        return 'no_skin'
    try:
        with open(path, 'r', encoding='utf-8', newline='') as handle:
            content = handle.read()
    except OSError as e:
        _log('{0}: read failed: {1}'.format(skin_id, e), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'already_patched'

    eol = _eol(content)
    pattern = re.compile(
        r'(<include content="%s">.*?</include>)' % re.escape(recipe['include']),
        re.S)
    found = len(pattern.findall(content))
    if found != recipe['expected']:
        # Upstream moved something. Report and leave the skin exactly as it
        # is: a half-patched view is a broken screen for every user of this
        # skin, and the tick is worth less than that.
        _log('{0}: expected {1} {2} blocks in {3}, found {4} -- the skin has '
             'changed; leaving it alone'.format(
                 skin_id, recipe['expected'], recipe['include'],
                 recipe['rel'], found), level='WARNING')
        return 'unmatched'

    control = _control(recipe, eol)
    new_content = pattern.sub(lambda m: m.group(1) + control, content)

    try:
        # Kodi silently refuses to load a skin file it cannot parse, and the
        # user gets an empty screen with nothing in the log pointing here.
        # Parsing before writing is what keeps a bad edit from ever reaching
        # the disk.
        import xml.etree.ElementTree as ET
        ET.fromstring(new_content)
    except Exception as e:
        _log('{0}: patched XML would not parse -- skipping ({1})'.format(
            skin_id, e), level='WARNING')
        return 'parse_failed'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as handle:
            handle.write(new_content)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('{0}: write failed: {1}'.format(skin_id, e), level='WARNING')
        return 'write_failed'

    _log('{0}: the Poster view now draws the watched tick'.format(skin_id))
    return 'patched'


def ensure_patched():
    """Patch every skin we have a verified recipe for. Returns {skin: status}."""
    out = {}
    for skin_id, recipe in RECIPES.items():
        try:
            out[skin_id] = _patch_one(skin_id, recipe)
        except Exception as e:
            out[skin_id] = 'failed'
            _log('{0}: {1}'.format(skin_id, e), level='WARNING')
    return out


def revert():
    """Undo, for a device that needs the skin exactly as shipped."""
    out = {}
    for skin_id, recipe in RECIPES.items():
        path = _skin_path(skin_id, recipe['rel'])
        if not path:
            out[skin_id] = 'no_skin'
            continue
        try:
            with open(path, 'r', encoding='utf-8', newline='') as handle:
                content = handle.read()
        except OSError:
            out[skin_id] = 'failed'
            continue
        if MARKER not in content:
            out[skin_id] = 'not_patched'
            continue
        eol = _eol(content)
        stripped = content.replace(_control(recipe, eol), '')
        if MARKER in stripped:
            # Somebody edited inside our block. Removing what is left would
            # be guesswork on a file the whole UI is drawn from.
            _log('{0}: revert found the block no longer as we left it -- '
                 'refusing'.format(skin_id), level='WARNING')
            out[skin_id] = 'failed'
            continue
        try:
            import xml.etree.ElementTree as ET
            ET.fromstring(stripped)
        except Exception:
            out[skin_id] = 'failed'
            continue
        tmp = path + '.aitmp'
        try:
            with open(tmp, 'w', encoding='utf-8', newline='') as handle:
                handle.write(stripped)
            os.replace(tmp, path)
            out[skin_id] = 'reverted'
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            out[skin_id] = 'failed'
    return out
