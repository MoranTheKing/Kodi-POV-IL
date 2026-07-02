# Self-healing patch of the home SEARCH button.
#
# WHY: This is a POV-centric build. On the "beautiful" skin (AF3) the
# search row resolves to POV search. On the "simple" skins shipped with
# the build -- skin.fentastic and skin.estuary -- the home search icon
# instead opens a generic search dialog/helper, so to reach POV's
# "חיפוש / Search" node (SEARCH: Movies / TV Shows / People / Movies
# Collection) the user has to drill manually through Search -> video
# add-ons -> POV -> search. Users expect the search button to land on
# that POV node directly, on whichever skin they use.
#
# WHAT: Each skin's Home.xml defines the search icon as an IconButton
# include with a control_id + onclick param pair. Estuary needs to be
# repointed to the POV search node:
#   ActivateWindow(videos,plugin://plugin.video.pov/?mode=navigator.search,return)
# (POV's router maps navigator.search -> Navigator(params).search(),
# which builds exactly that 4-item node.)
#
# BOTH skins are now repointed to the POV search node: users asked for the
# magnifying glass to offer more than movie+show (actor, director, movies
# collection) uniformly across skins, and navigator.search is exactly that
# 4-item hub. (Previously FENtastic was left on its own movie+show search.)
#
#   * skin.fentastic: the icon is defined three times, gated by skin
#     settings (only one renders at a time):
#       control 804 (NoSearchResultsWindow)       -> ActivateWindow(1107)
#       control 805 (DefaultSearchWindowBehavior) -> helper search_input
#       control 806 (default)                     -> helper open_search_window
#   * skin.estuary: a single bottom-bar search icon:
#       control 801                               -> ActivateWindow(1107)
#
# The patch is gated on the current onclick value (idempotent: if it
# already points at POV search we skip), tolerates whitespace/attribute
# spacing, and is reversible (ensure_unpatched restores the skin
# defaults). Each skin is handled independently against its own Home.xml,
# so switching skins keeps working. If a skin ever restructures these
# buttons so a control id / onclick pair isn't found, we simply skip that
# one -- the search button keeps working with the upstream behavior. A
# skin that isn't installed has no Home.xml and is a no-op.

import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


# The POV search node. navigator.search has no extra query params, so no
# '&' escaping is needed inside the XML attribute value.
POV_SEARCH_ONCLICK = (
    'ActivateWindow(videos,'
    'plugin://plugin.video.pov/?mode=navigator.search,return)')

# NOX also has a main-menu "חיפוש" hub item that points at POV's TV-only
# search-history; repoint it to the full search hub too. Matched by the exact
# encoded path (unique in the file), keeping the ActivateWindow(...) wrapper.
NOX_MAIN_MENU = ('special://home/addons/skin.povil.nox/xml/'
                 'Custom_nox_main_menu.xml')
_NOX_OLD_SEARCH = ('plugin://plugin.video.pov/?mode=search_history'
                   '&amp;action=tvshow'
                   '&amp;iconImage=https%3A%2F%2Fi.imgur.com%2FxYTdX3O.png')
_NOX_NEW_SEARCH = 'plugin://plugin.video.pov/?mode=navigator.search'

# Per-skin search-button definitions. For each skin: the search-icon
# control_id(s) -> the skin's default onclick (used for ensure_unpatched).
_SEARCH_SKINS = (
    ('skin.fentastic', 'Home.xml', {
        '804': 'ActivateWindow(1107)',
        '805': 'RunScript(script.fentastic.helper,mode=search_input)',
        '806': 'RunScript(script.fentastic.helper,mode=open_search_window)',
    }),
    ('skin.estuary', 'Home.xml', {
        '801': 'ActivateWindow(1107)',
    }),
    # NOX uses the same search control ids but its own Home file. One of 806
    # has the default onclick sitting AFTER an XML comment, so _onclick_re
    # tolerates a comment between control_id and onclick.
    ('skin.povil.nox', 'Home_nox.xml', {
        '804': 'ActivateWindow(1107)',
        '805': 'RunScript(script.fentastic.helper,mode=search_input)',
        '806': 'ActivateWindow(1107)',
    }),
)


def _home_xml(skin_addon_id, filename):
    return 'special://home/addons/' + skin_addon_id + '/xml/' + filename


def _log(msg, level='INFO'):
    if kodi_utils is not None:
        try:
            kodi_utils.log('fentastic_search_patcher: ' + msg, level=level)
        except Exception:
            pass


def _translate(path):
    return xbmcvfs.translatePath(path) if xbmcvfs else path


def _exists(path):
    try:
        return xbmcvfs.exists(_translate(path)) if xbmcvfs else False
    except Exception:
        return False


def _read(path):
    with xbmcvfs.File(_translate(path)) as f:
        return f.read()


def _write(path, content):
    f = xbmcvfs.File(_translate(path), 'w')
    try:
        f.write(content)
    finally:
        f.close()


def _onclick_re(control_id):
    """Match a search IconButton's onclick by pinning it to the control_id
    that immediately precedes it (the search control ids are unique to the
    search button), tolerating whitespace and attribute spacing."""
    return re.compile(
        r'(<param\s+name="control_id"\s+value="' + control_id +
        r'"\s*/>\s*(?:<!--.*?-->\s*)?<param\s+name="onclick"\s+value=")'
        r'([^"]*)'
        r'("\s*/>)',
        re.DOTALL)


def _set_onclick(content, control_id, new_onclick):
    """Return (content, changed) with the given control's onclick set."""
    pat = _onclick_re(control_id)

    changed = {'v': False}

    def _sub(m):
        if m.group(2) == new_onclick:
            return m.group(0)
        changed['v'] = True
        return m.group(1) + new_onclick + m.group(3)

    new_content = pat.sub(_sub, content, count=1)
    return new_content, changed['v']


def _apply_skin(skin_addon_id, filename, buttons, target_onclick_for):
    """Apply to one skin's home file. target_onclick_for(control_id) ->
    desired onclick. Returns 'patched' / 'unchanged' / 'no_target' /
    'failed'."""
    if xbmcvfs is None:
        return 'failed'
    home_xml = _home_xml(skin_addon_id, filename)
    if not _exists(home_xml):
        return 'no_target'
    try:
        content = _read(home_xml)
    except Exception as e:
        _log('{0}: read failed: {1}'.format(skin_addon_id, e),
             level='WARNING')
        return 'failed'

    new_content = content
    any_changed = False
    for cid in buttons:
        new_content, ch = _set_onclick(
            new_content, cid, target_onclick_for(cid))
        any_changed = any_changed or ch

    if not any_changed:
        return 'unchanged'
    try:
        _write(home_xml, new_content)
    except Exception as e:
        _log('{0}: write failed: {1}'.format(skin_addon_id, e),
             level='WARNING')
        return 'failed'
    return 'patched'


def _apply(target_onclick_for_factory):
    """Apply across all known skins. target_onclick_for_factory(buttons)
    returns a target_onclick_for(control_id) callable. Returns 'patched'
    if any skin changed, else the most informative aggregate status."""
    statuses = []
    for skin_addon_id, filename, buttons in _SEARCH_SKINS:
        statuses.append(_apply_skin(
            skin_addon_id, filename, buttons,
            target_onclick_for_factory(buttons)))
    if 'patched' in statuses:
        return 'patched'
    if 'unchanged' in statuses:
        return 'unchanged'
    if 'failed' in statuses:
        return 'failed'
    return 'no_target'


def _repoint_nox_main_menu():
    """Repoint NOX's main-menu search item to the full POV search hub.
    Returns 'patched' / 'unchanged' / 'no_target' / 'failed'."""
    if xbmcvfs is None:
        return 'failed'
    if not _exists(NOX_MAIN_MENU):
        return 'no_target'
    try:
        content = _read(NOX_MAIN_MENU)
    except Exception as e:
        _log('nox main-menu read failed: {0}'.format(e), level='WARNING')
        return 'failed'
    if _NOX_OLD_SEARCH not in content:
        return 'unchanged'
    try:
        _write(NOX_MAIN_MENU, content.replace(_NOX_OLD_SEARCH, _NOX_NEW_SEARCH))
    except Exception as e:
        _log('nox main-menu write failed: {0}'.format(e), level='WARNING')
        return 'failed'
    return 'patched'


def ensure_patched():
    """Repoint the home search icon to POV's full search hub
    (navigator.search: Movies / TV Shows / People / Movies Collection) on
    FENtastic, Estuary and NOX -- plus NOX's main-menu search item -- so every
    skin's magnifying glass offers the same richer set of search options, not
    just movie+show."""
    def _target_factory(buttons):
        def _target(cid):
            return POV_SEARCH_ONCLICK
        return _target

    status = _apply(_target_factory)
    nox_menu = _repoint_nox_main_menu()
    if status == 'patched' or nox_menu == 'patched':
        _log('search buttons repointed to POV full search hub')
        return 'patched'
    return status


def ensure_unpatched():
    """Restore each skin's default home search onclick(s). Best-effort;
    used if we ever want to back the change out."""
    return _apply(lambda buttons: (lambda cid: buttons[cid]))
