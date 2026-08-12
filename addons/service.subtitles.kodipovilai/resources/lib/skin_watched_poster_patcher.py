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

# THE SECOND REPORT, the opposite of the first: "in this view it ticks
# EVERYTHING -- films and series I have never watched, and never marked."
#
# HOW WE KNOW IT IS THIS LINE. The same user says the tick is correct in the
# default Poster view. Poster draws through WallWatchedIconVar, which is gated
# on Integer.IsGreater(ListItem.Playcount,0) -- so if it is right there, the
# playcount is right, and the data is not the problem. A view that ticks
# unwatched items is therefore a view that never looks at the playcount. There
# is exactly one such variable in this skin:
#
#   <variable name="ListWatchedIconVar">
#       ...
#       <value condition="!String.IsEmpty(ListItem.Overlay)">$INFO[ListItem.Overlay]</value>
#
# "has any overlay at all" is not "is watched". It is used by the List, Wide
# List and Banner views and by nothing else, which matches a report about one
# specific view rather than the whole skin.
#
# THE PLAYCOUNT DECIDES, because that is the source the view that works uses.
# Two lines replace the one:
#
#   watched per the playcount            -> the tick, same texture as before
#   any overlay that is not about watching -> unchanged ($INFO as before)
#
# So a RAR, a ZIP, a locked source or an HD badge -- which this same variable
# also draws, in the file manager -- keeps its icon exactly as it is today.
# What stops being drawn is only an overlay claiming "watched" on an item
# whose playcount says otherwise, and an "unwatched" overlay, which pointed at
# a texture this skin does not even ship. That contradiction is the bug: one
# view calls an item watched while the other, reading the playcount, correctly
# does not.
LIST_OLD = ('<value condition="!String.IsEmpty(ListItem.Overlay)">'
            '$INFO[ListItem.Overlay]</value>')
LIST_NEW = (
    LIST_MARKER + '{eol}{indent}'
    '<value condition="Integer.IsGreater(ListItem.Playcount,0)">'
    'OverlayWatched.png</value>{eol}{indent}'
    '<value condition="!String.IsEmpty(ListItem.Overlay) + '
    '!String.IsEqual(ListItem.Overlay,OverlayWatched.png) + '
    '!String.IsEqual(ListItem.Overlay,OverlayUnwatched.png)">'
    '$INFO[ListItem.Overlay]</value>')

# The variable the line has to be inside. Bounded on purpose: the same
# `!String.IsEmpty(ListItem.Overlay)` test appears in other variables in this
# file (the PVR ones), and those are not ours to change.
LIST_VARIABLES = {
    'skin.fentastic': {
        'rel': 'xml/Variables.xml',
        'variable': 'ListWatchedIconVar',
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


def _variable_block(content, name):
    """(start, end) of one <variable name="..."> ... </variable>, or None."""
    opener = '<variable name="%s">' % name
    start = content.find(opener)
    if start == -1:
        return None
    end = content.find('</variable>', start)
    if end == -1:
        return None
    return start, end + len('</variable>')


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

    bounds = _variable_block(content, recipe['variable'])
    if bounds is None:
        _log('{0}: no {1} variable in {2}; leaving it alone'.format(
            skin_id, recipe['variable'], recipe['rel']), level='WARNING')
        return 'unmatched'
    start, end = bounds
    block = content[start:end]
    # Exactly one, or we do not know which one the report is about. The same
    # test appears in this file's PVR variables, which is why the search is
    # bounded to this block in the first place.
    if block.count(LIST_OLD) != 1:
        _log('{0}: expected one watched-overlay line in {1}, found {2} -- the '
             'skin has changed; leaving it alone'.format(
                 skin_id, recipe['variable'], block.count(LIST_OLD)),
             level='WARNING')
        return 'unmatched'

    eol = _eol(content)
    # Reuse the file's own indentation for the line we are replacing, so the
    # two lines that take its place sit exactly where it did.
    line_start = block.rfind('\n', 0, block.find(LIST_OLD)) + 1
    indent = block[line_start:block.find(LIST_OLD)]
    new_block = block.replace(
        LIST_OLD, LIST_NEW.format(eol=eol, indent=indent))
    new_content = content[:start] + new_block + content[end:]

    # THE BLOCK, NOT THE FILE. Variables.xml is not valid XML to a strict
    # parser -- it carries raw & inside skin expressions, which Kodi's own
    # parser accepts and ElementTree does not -- so parsing the whole file
    # would fail on every install and this fix would never apply anywhere.
    # Everything outside the block is byte-identical to what was already
    # there, so checking the one piece we rewrote is the check that means
    # something.
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

    _log('{0}: the list views now tick only what was actually watched'.format(
        skin_id))
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
    for skin_id, recipe in LIST_VARIABLES.items():
        key = skin_id + ':list'
        try:
            out[key] = _patch_list_one(skin_id, recipe)
        except Exception as e:
            out[key] = 'failed'
            _log('{0}: {1}'.format(key, e), level='WARNING')
    return out


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
    bounds = _variable_block(content, recipe['variable'])
    if bounds is None:
        return 'failed'
    start, end = bounds
    block = content[start:end]
    line_start = block.rfind('\n', 0, block.find(LIST_MARKER)) + 1
    indent = block[line_start:block.find(LIST_MARKER)]
    restored = block.replace(LIST_NEW.format(eol=eol, indent=indent), LIST_OLD)
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
