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
LIST_MARKER = '<!-- AI_SUBS_WATCHED_LIST_v1 -->'

# THE SECOND REPORT, the opposite of the first: "in this one view it ticks
# EVERYTHING -- films and series I have never watched. Every other view is
# fine, and the default Poster view is perfect."
#
# WHICH VIEW. The user reads it as "סמלילי אלבומים". No skin file declares
# that name, because the skin does not name this view at all: View_630's
# container is a <control type="fixedlist" id="630"> with NO <viewtype>
# element, so Kodi falls back to its own label for that container kind --
# string 541, "Album icons". (Same table gives 20021 "Poster", the view the
# same user says is correct, which is the cross-check.)
#
# WHAT DRAWS THE TICK THERE. View_630_AdvancedList and its wide twin build
# their rows from ViewTypeBaseLayout_, and nothing else in the skin uses that
# include. It takes its watched icon from
#
#     <texture>$VAR[ListPVRRecordingsIconVar]</texture>
#
# -- the PVR RECORDINGS variable, borrowed for a video list. Its third rule is
#
#     <value condition="!String.IsEmpty(ListItem.Overlay)">OverlayWatched.png</value>
#
# a hardcoded tick for ANY non-empty overlay. POV and Umbrella set an overlay
# on unwatched items too (4 = unwatched, 5 = watched), so "has an overlay"
# is true for every row and every row gets the tick. That is why it is this
# view alone: every other view reads a variable that actually tests watched.
#
# THE FIX is to read the same variable the working views read --
# WallWatchedIconVar, gated on Integer.IsGreater(ListItem.Playcount,0) -- so
# this view and the Poster view can no longer disagree. The PVR variable
# itself is left exactly as it is: PVR recordings really do mean watched by
# their overlay, and that is not our screen to change.
LIST_VARIABLES = {
    'skin.fentastic': {
        'rel': 'xml/Includes_Layouts.xml',
        'include': 'ViewTypeBaseLayout_',
        'from_var': 'ListPVRRecordingsIconVar',
        'to_var': 'WallWatchedIconVar',
        'expected': 2,   # itemlayout + focusedlayout
    },
}

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

    # A nested <include> inside one of these blocks would end the non-greedy
    # match early, and the tick would be inserted INSIDE the include element
    # instead of after it. That is still well-formed XML -- so the parse below
    # would pass it -- but a <control> is not a legal child of
    # <include content="...">, which takes <param> only, so Kodi drops it and
    # the fix becomes a silent no-op. The block count would not change either,
    # so nothing else here would notice. The skin ships only <param> children
    # today; this is what keeps a future release from breaking us quietly.
    for block in pattern.findall(content):
        if '<include' in block[len('<include content="%s">'
                                  % recipe['include']):]:
            _log('{0}: a {1} block now nests another <include>; the insertion '
                 'point is no longer unambiguous -- leaving it alone'.format(
                     skin_id, recipe['include']), level='WARNING')
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


def _fragment_parses(fragment):
    """True when this piece of skin XML is well formed.

    Bare & is escaped first, because a skin expression is full of them and
    they are legal to Kodi. Everything else -- an unclosed tag, a stray angle
    bracket, a broken attribute -- still fails, which is what we are checking
    for."""
    try:
        import xml.etree.ElementTree as ET
        safe = re.sub(r'&(?!(?:[a-zA-Z][a-zA-Z0-9]*|#[0-9]+|#x[0-9a-fA-F]+);)',
                      '&amp;', fragment)
        ET.fromstring(safe)
        return True
    except Exception:
        return False


def _include_block(content, name):
    """(start, end) of one <include name="..."> ... </include>, or None.

    Bounded on purpose: the replacement below must not reach a PVR window that
    legitimately uses the same variable elsewhere in this file.

    NESTING IS COUNTED. A skin layout is full of <include>Something</include>
    references, so stopping at the first closing tag cuts the block in half --
    which is exactly what happened first time round, and the fragment parse
    below caught it. Depth counting, with self-closing <include ... /> not
    counted as an opener."""
    opener = '<include name="%s">' % name
    start = content.find(opener)
    if start == -1:
        return None
    depth = 0
    for match in re.finditer(r'<include\b[^>]*?(/?)>|</include>',
                             content[start:]):
        token = match.group(0)
        if token == '</include>':
            depth -= 1
            if depth == 0:
                return start, start + match.end()
        elif not match.group(1):
            depth += 1
    return None


def _list_pattern(recipe):
    return re.compile(
        r'(<texture[^>]*>)\$VAR\[%s\](</texture>)' % re.escape(
            recipe['from_var']))


def _patch_list_one(skin_id, recipe):
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

    if LIST_MARKER in content:
        return 'already_patched'

    bounds = _include_block(content, recipe['include'])
    if bounds is None:
        _log('{0}: no {1} include in {2}; leaving it alone'.format(
            skin_id, recipe['include'], recipe['rel']), level='WARNING')
        return 'unmatched'
    start, end = bounds
    block = content[start:end]
    pattern = _list_pattern(recipe)
    found = len(pattern.findall(block))
    if found != recipe['expected']:
        _log('{0}: expected {1} {2} textures in {3}, found {4} -- the skin has '
             'changed; leaving it alone'.format(
                 skin_id, recipe['expected'], recipe['from_var'],
                 recipe['include'], found), level='WARNING')
        return 'unmatched'

    eol = _eol(content)

    def _swap(match):
        # Keep the texture tag exactly as it was, colordiffuse and all -- only
        # the variable it reads changes. The marker goes on its own line above
        # it so the edit is findable and reversible.
        line_start = block.rfind('\n', 0, match.start()) + 1
        indent = block[line_start:match.start()]
        return '%s%s%s%s$VAR[%s]%s' % (
            LIST_MARKER, eol, indent, match.group(1), recipe['to_var'],
            match.group(2))

    new_block = pattern.sub(_swap, block)
    new_content = content[:start] + new_block + content[end:]

    # THE BLOCK, NOT THE FILE. These skin XMLs are not valid XML to a strict
    # parser -- they carry raw & inside skin expressions, which Kodi accepts
    # and ElementTree does not -- so parsing the whole file would fail on every
    # install and this fix would never apply anywhere. Everything outside the
    # block is byte-identical, so the one piece we rewrote is the piece worth
    # checking.
    if not _fragment_parses(new_block):
        _log('{0}: patched block would not parse -- skipping'.format(skin_id),
             level='WARNING')
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

    _log('{0}: the advanced list views now tick only what was actually '
         'watched'.format(skin_id))
    return 'patched'


def _revert_list_one(skin_id, recipe):
    path = _skin_path(skin_id, recipe['rel'])
    if not path:
        return 'no_skin'
    try:
        with open(path, 'r', encoding='utf-8', newline='') as handle:
            content = handle.read()
    except OSError:
        return 'failed'
    if LIST_MARKER not in content:
        return 'not_patched'
    eol = _eol(content)
    bounds = _include_block(content, recipe['include'])
    if bounds is None:
        return 'failed'
    start, end = bounds
    block = content[start:end]
    restored = re.sub(
        r'%s%s[ \t]*(<texture[^>]*>)\$VAR\[%s\](</texture>)' % (
            re.escape(LIST_MARKER), re.escape(eol),
            re.escape(recipe['to_var'])),
        lambda m: '%s$VAR[%s]%s' % (m.group(1), recipe['from_var'],
                                    m.group(2)),
        block)
    if LIST_MARKER in restored:
        # Somebody edited inside our replacement. Guessing what to remove from
        # a file the whole UI is drawn from is worse than leaving it.
        _log('{0}: revert found the block no longer as we left it -- '
             'refusing'.format(skin_id), level='WARNING')
        return 'failed'
    new_content = content[:start] + restored + content[end:]
    if not _fragment_parses(restored):
        return 'failed'
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as handle:
            handle.write(new_content)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return 'failed'
    return 'reverted'


def ensure_patched():
    """Patch every skin we have a verified recipe for. Returns {skin: status}."""
    out = {}
    for skin_id, recipe in RECIPES.items():
        try:
            out[skin_id] = _patch_one(skin_id, recipe)
        except Exception as e:
            out[skin_id] = 'failed'
            _log('{0}: {1}'.format(skin_id, e), level='WARNING')
    for skin_id, recipe in LIST_VARIABLES.items():
        key = skin_id + ':list'
        try:
            out[key] = _patch_list_one(skin_id, recipe)
        except Exception as e:
            out[key] = 'failed'
            _log('{0}: {1}'.format(key, e), level='WARNING')
    return out


def revert():
    """Undo, for a device that needs the skin exactly as shipped."""
    out = {}
    for skin_id, recipe in LIST_VARIABLES.items():
        try:
            out[skin_id + ':list'] = _revert_list_one(skin_id, recipe)
        except Exception:
            out[skin_id + ':list'] = 'failed'
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
