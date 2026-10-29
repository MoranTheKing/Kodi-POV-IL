"""Right-to-left rows for the Onyx skin (skin.povil.onyx).

Kodi draws a horizontal list from left to right only. For a Hebrew row the
first item has to sit on the right and the next ones to its left, so the
add-on hands the list over reversed, and the skin starts the row on its last
item (the original first one). Each reversed item carries the property
povil_rtl=1: the skin only moves to the end of a list that was reversed.

A list is reversed when:
* its URL carries povil_rtl=1 (the Onyx home rows), or
* POV or Umbrella builds it full screen (Videos window) while Onyx is the
  active skin and the add-on opens that list in one of Onyx's horizontal
  views (51, 55). Umbrella keeps its views per skin; for Onyx they start as
  51 (movies, TV shows, seasons) and 55 (episodes), as POV's do, and a view
  the user picks in Umbrella later is kept.
An episode sort (POV's season lists) gives way to the add-on's order, which
already is the episode order, so episode 1 ends up on the right. A name sort
(Idan Plus with its A-Z setting) is done here, the way Kodi does it, and then
reversed, so A (א) ends up on the right. A reversed list offers Kodi no sort
but its own order: Kodi saves the sort a user picks per list and applies it
again at every visit, and "by episode" put episode 1 back on the left
(field report, 29 Oct 2026). A list sorted any other way keeps its order and
is not marked.

install() runs first thing in the add-on's entry script, on every request.
It wraps xbmcplugin once per interpreter (Idan Plus, and POV with fast
navigation, reuse theirs) and decides again for each request, so lists
served from the build's saved copies are reversed the same way and nothing
changes for any other request or skin.
"""
import re
import sys

FLAG = 'povil_rtl=1'
SKIN = 'skin.povil.onyx'
HORIZONTAL_VIEWS = ('51', '55')
MEDIA = ('movies', 'tvshows', 'seasons', 'episodes')
UMBRELLA_VIEWS = {'movies': '51', 'tvshows': '51', 'seasons': '51', 'episodes': '55'}
SEEDED = 'povil.umbrella_views_seeded'


def _query():
    return sys.argv[2] if len(sys.argv) > 2 else ''


def _umbrella_db():
    import xbmcvfs
    return xbmcvfs.translatePath('special://profile/addon_data/plugin.video.umbrella/views.db')


def seed_umbrella_views():
    """Umbrella's views for Onyx: the showcase views, unless the user chose others."""
    import os
    import sqlite3
    path = _umbrella_db()
    if not os.path.isdir(os.path.dirname(path)):
        return False
    con = sqlite3.connect(path, timeout=2)
    try:
        con.execute('CREATE TABLE IF NOT EXISTS views (skin TEXT, view_type TEXT, view_id TEXT, UNIQUE(skin, view_type));')
        con.executemany('INSERT OR IGNORE INTO views VALUES (?, ?, ?)',
                        [(SKIN, content, view) for content, view in UMBRELLA_VIEWS.items()])
        con.commit()
    finally:
        con.close()
    return True


def _seed_umbrella_once():
    """Seed once per Kodi session and profile: widgets and playback skip the
    database. The mark holds the database's path, which differs per profile."""
    import xbmcgui
    home = xbmcgui.Window(10000)
    path = _umbrella_db()
    if home.getProperty(SEEDED) == path:
        return
    if seed_umbrella_views():
        home.setProperty(SEEDED, path)


def _pov_view_key(content, query):
    """POV's view type for this list: episode lists that are not a season's
    episodes (next episodes, in progress, calendars) use view.episodes_lists."""
    from urllib.parse import parse_qs
    mode = (parse_qs(query.lstrip('?')).get('mode') or [''])[0]
    if content == 'episodes' and mode != 'build_episode_list':
        return 'episodes_lists'
    return content


def _view_for(content, addon, query):
    if addon == 'umbrella':
        import sqlite3
        con = sqlite3.connect(_umbrella_db(), timeout=2)
        try:
            row = con.execute('SELECT view_id FROM views WHERE skin=? AND view_type=?', (SKIN, content)).fetchone()
        finally:
            con.close()
        return row[0] if row else ''
    import xbmcgui
    return xbmcgui.Window(10000).getProperty('pov_view.%s' % _pov_view_key(content, query))


def _full_screen_view(content, addon, query):
    """The add-on's own view for this list is one of Onyx's horizontal views."""
    import xbmc
    import xbmcgui
    if not addon or xbmc.getSkinDir() != SKIN or xbmcgui.getCurrentWindowId() != 10025:
        return False
    if content not in MEDIA:
        return False
    return _view_for(content, addon, query) in HORIZONTAL_VIEWS


_FORMATTING = re.compile(r'\[/?(?:B|I|LIGHT|UPPERCASE|LOWERCASE|CAPITALIZE)\]|\[COLOR [^\]]*\]|\[/COLOR\]', re.I)


def _name_key(listitem, ignore_the=False):
    """Kodi's name sort: formatting ignored, case folded, numbers by value
    (and a leading "The" ignored for SORT_METHOD_LABEL_IGNORE_THE)."""
    try:
        name = listitem.getLabel()
    except Exception:
        name = ''
    name = _FORMATTING.sub('', name or '').strip().casefold()
    if ignore_the and name.startswith('the '):
        name = name[4:]
    return [(0, int(part), '') if part.isdecimal() else (1, 0, part) for part in re.split(r'(\d+)', name) if part]


def _pinned(listitem):
    """Where the add-on pinned an item (SpecialSort: top / bottom), if anywhere."""
    try:
        return (listitem.getProperty('SpecialSort') or '').lower()
    except Exception:
        return ''


def _wrap(xbmcplugin, state):
    original = {name: getattr(xbmcplugin, name) for name in
                ('addDirectoryItem', 'addDirectoryItems', 'addSortMethod', 'endOfDirectory', 'setContent')}
    own_order = {getattr(xbmcplugin, n, None) for n in ('SORT_METHOD_UNSORTED', 'SORT_METHOD_NONE')} - {None}
    unsorted = getattr(xbmcplugin, 'SORT_METHOD_UNSORTED', None)
    episode_sort = getattr(xbmcplugin, 'SORT_METHOD_EPISODE', None)
    by_name = {getattr(xbmcplugin, n, None) for n in ('SORT_METHOD_LABEL', 'SORT_METHOD_LABEL_IGNORE_THE')} - {None}
    ignore_the = getattr(xbmcplugin, 'SORT_METHOD_LABEL_IGNORE_THE', None)

    def _keep(url, listitem, is_folder):
        state['items'].append((url, listitem, bool(is_folder)))

    def addDirectoryItem(handle, url=None, listitem=None, isFolder=False, totalItems=0, **kwargs):
        if not state['active']:
            return original['addDirectoryItem'](handle, url, listitem, isFolder, totalItems, **kwargs)
        _keep(url if url is not None else kwargs.get('url'),
              listitem if listitem is not None else kwargs.get('listitem'),
              kwargs.get('isFolder', isFolder))
        return True

    def addDirectoryItems(handle, items=None, totalItems=0, **kwargs):
        if not state['active']:
            return original['addDirectoryItems'](handle, items, totalItems, **kwargs)
        for entry in (items if items is not None else kwargs.get('items') or []):
            _keep(entry[0], entry[1], entry[2] if len(entry) > 2 else False)
        return True

    def addSortMethod(handle, sortMethod=None, *args, **kwargs):
        if not state['active']:
            return original['addSortMethod'](handle, sortMethod, *args, **kwargs)
        state['sorts'].append((sortMethod if sortMethod is not None else kwargs.pop('sortMethod', None), args, kwargs))
        return None

    def setContent(handle, content):
        state['content'] = content
        return original['setContent'](handle, content)

    def endOfDirectory(handle, succeeded=True, updateListing=False, cacheToDisc=True):
        if not state['active']:
            return original['endOfDirectory'](handle, succeeded, updateListing, cacheToDisc)
        items, sorts = state['items'], state['sorts']
        state.update(active=False, items=[], sorts=[])
        first = sorts[0][0] if sorts else None
        reverse = False
        if succeeded and items and (first is None or first in own_order or first == episode_sort or first in by_name):
            reverse = state['flagged']
            if not reverse:
                try:
                    reverse = _full_screen_view(state['content'], state['addon'], state['query'])
                except Exception:
                    reverse = False
        if reverse and first in by_name:
            try:
                # items the add-on pinned (a next page) keep their end
                ends = {'top': [], 'bottom': []}
                middle = []
                for entry in items:
                    ends.get(_pinned(entry[1]), middle).append(entry)
                drop_the = first == ignore_the
                middle = sorted(middle, key=lambda entry: _name_key(entry[1], drop_the))
                items = ends['top'] + middle + ends['bottom']
            except Exception:
                reverse = False      # never lose a list over a name: the add-on's own order
        if reverse:
            items.reverse()
            for _url, listitem, _folder in items:
                try:
                    listitem.setProperty('povil_rtl', '1')
                    # Kodi would move a pinned item (Umbrella's next page:
                    # SpecialSort=bottom) back to the end, the row's first place
                    listitem.setProperty('SpecialSort', '')
                except Exception:
                    pass
            # Only the list's own (reversed) order: a sort saved for this list
            # (Kodi keeps the one a user picked) then has nothing to re-apply.
            sorts = [(unsorted, (), {})] if unsorted is not None else []
        for method, args, kwargs in sorts:
            original['addSortMethod'](handle, method, *args, **kwargs)
        if items:
            original['addDirectoryItems'](handle, items, len(items))
        return original['endOfDirectory'](handle, succeeded, updateListing, cacheToDisc)

    xbmcplugin.addDirectoryItem = addDirectoryItem
    xbmcplugin.addDirectoryItems = addDirectoryItems
    xbmcplugin.addSortMethod = addSortMethod
    xbmcplugin.setContent = setContent
    xbmcplugin.endOfDirectory = endOfDirectory


def install(pov=False, umbrella=False):
    """Decide for this request; wrap xbmcplugin the first time only."""
    try:
        import xbmc
        import xbmcplugin
    except ImportError:
        return False
    state = getattr(xbmcplugin, '_povil_rtl_state', None)
    if state is None:
        state = {}
        _wrap(xbmcplugin, state)
        xbmcplugin._povil_rtl_state = state
    query = _query()
    addon = 'umbrella' if umbrella else ('pov' if pov else '')
    flagged = FLAG in query
    onyx = xbmc.getSkinDir() == SKIN
    state.update(items=[], sorts=[], content='', query=query, addon=addon, flagged=flagged,
                 active=flagged or bool(addon and onyx))
    if umbrella and onyx:
        try:
            _seed_umbrella_once()
        except Exception:
            pass
    return state['active']
