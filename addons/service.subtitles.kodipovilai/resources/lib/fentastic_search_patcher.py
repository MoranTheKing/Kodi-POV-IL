# Self-healing patch of FENtastic's Home.xml so the home SEARCH button
# opens POV's search node directly, instead of FENtastic's own search
# dialog/window.
#
# WHY: This is a POV-centric build. On the "beautiful" skin (AF3) the
# search row resolves to POV search. After a user switches to the
# "simple" skin (skin.fentastic), the home search icon instead runs
# FENtastic's native search helper (a keyboard/search-provider window),
# so to reach POV's "חיפוש / Search" node (SEARCH: Movies / TV Shows /
# People / Movies Collection) the user has to drill manually through
# Search -> video add-ons -> POV -> search. Users expect the search
# button to land on that POV node directly.
#
# WHAT: FENtastic's Home.xml defines the search icon three times, gated
# by skin settings (only one renders at a time):
#   * control 804  (NoSearchResultsWindow)         -> ActivateWindow(1107)
#   * control 805  (DefaultSearchWindowBehavior)   -> helper search_input
#   * control 806  (default)                       -> helper open_search_window
# We repoint all three onclicks to the POV search node so the search
# button works regardless of the user's skin setting:
#   ActivateWindow(videos,plugin://plugin.video.pov/?mode=navigator.search,return)
# (POV's router maps navigator.search -> Navigator(params).search(),
# which builds exactly that 4-item node.)
#
# The patch is gated on the current onclick value (idempotent: if it
# already points at POV search we skip), tolerates whitespace/attribute
# spacing, and is reversible (ensure_unpatched restores the FENtastic
# defaults). If FENtastic ever restructures these buttons so a control
# id / onclick pair isn't found, we simply skip that one -- the search
# button keeps working with the upstream behavior.

import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


SKIN_ADDON_ID = 'skin.fentastic'
HOME_XML = 'special://home/addons/' + SKIN_ADDON_ID + '/xml/Home.xml'

# The POV search node. navigator.search has no extra query params, so no
# '&' escaping is needed inside the XML attribute value.
POV_SEARCH_ONCLICK = (
    'ActivateWindow(videos,'
    'plugin://plugin.video.pov/?mode=navigator.search,return)')

# control_id -> the FENtastic default onclick (used for ensure_unpatched).
_SEARCH_BUTTONS = {
    '804': 'ActivateWindow(1107)',
    '805': 'RunScript(script.fentastic.helper,mode=search_input)',
    '806': 'RunScript(script.fentastic.helper,mode=open_search_window)',
}


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
    that immediately precedes it (804/805/806 are unique to the search
    buttons), tolerating whitespace and attribute spacing."""
    return re.compile(
        r'(<param\s+name="control_id"\s+value="' + control_id +
        r'"\s*/>\s*<param\s+name="onclick"\s+value=")'
        r'([^"]*)'
        r'("\s*/>)')


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


def _apply(target_onclick_for):
    """Generic apply: target_onclick_for(control_id) -> desired onclick.
    Returns 'patched' / 'unchanged' / 'no_target' / 'failed'."""
    if xbmcvfs is None:
        return 'failed'
    if not _exists(HOME_XML):
        return 'no_target'
    try:
        content = _read(HOME_XML)
    except Exception as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'failed'

    new_content = content
    any_changed = False
    for cid in _SEARCH_BUTTONS:
        new_content, ch = _set_onclick(
            new_content, cid, target_onclick_for(cid))
        any_changed = any_changed or ch

    if not any_changed:
        return 'unchanged'
    try:
        _write(HOME_XML, new_content)
    except Exception as e:
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'failed'
    return 'patched'


def ensure_patched():
    """Repoint the home search button(s) to the POV search node."""
    status = _apply(lambda cid: POV_SEARCH_ONCLICK)
    if status == 'patched':
        _log('home search button now opens POV search node')
    return status


def ensure_unpatched():
    """Restore FENtastic's default home search onclicks. Best-effort;
    used if we ever want to back the change out."""
    return _apply(lambda cid: _SEARCH_BUTTONS[cid])
