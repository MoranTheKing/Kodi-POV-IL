# Which add-on the home SEARCH button searches: POV or Umbrella.
#
# The build is POV-centric and its search has always been POV's. Umbrella
# shipped as a pilot with its own catalogue and its own scrapers, and the
# obvious next question was "can I search with Umbrella instead?". This is
# that switch -- ONE setting, honoured by every skin the build ships.
#
# WHY THE SKIN FILES ARE REWRITTEN RATHER THAN A CLICK-TIME FORWARDER.
# The tempting design is to point every skin's search button at a RunScript
# of ours that decides at click time. It makes switching instant. It also
# puts a Python process launch in front of the single most-used button in
# the build, and gives that button a way to fail that it does not have
# today. Switching provider is something a user does once; searching is
# something they do every evening. So the provider is baked into the skin
# files, and the (rare) switch pays for it with a ReloadSkin.
#
# TWO SHAPES OF SEARCH, because the skins genuinely differ:
#
#   FENtastic / Estuary / NOX -- the magnifying glass ACTIVATES A HUB and the
#     add-on takes it from there. One onclick per skin, written by
#     fentastic_search_patcher. POV's hub is navigator.search (Movies / TV /
#     People / Movies Collection); Umbrella's is tools_searchNavigator
#     (Movie search / TV search / Movie people / TV people).
#
#   Arctic Fuse 3 -- the query is TYPED IN THE SKIN and each of four result
#     rows is a plugin path built by the skin's shortcut generator from
#     search_path.xml. Switching provider means swapping four path prefixes,
#     written by af3_search_pov_patcher. Umbrella has a term-driven action
#     for all four, so AF3 keeps all four rows on either provider.
#
# Both patchers run on every Kodi startup already, so the choice survives a
# skin update that ships a fresh file, and applies to a skin the user has
# not switched to yet.
#
# Falls back to POV whenever Umbrella is not installed -- a search button
# that opens a missing add-on is worse than one that searches the other one.

POV = 'pov'
UMBRELLA = 'umbrella'
DEFAULT = POV

SETTING = 'search_provider'
UMBRELLA_ADDON_ID = 'plugin.video.umbrella'
POV_ADDON_ID = 'plugin.video.pov'

DISPLAY = {
    POV: 'POV',
    UMBRELLA: 'Umbrella',
}

# --- the hub the magnifying glass opens (FENtastic / Estuary / NOX) --------
# navigator.search / tools_searchNavigator take no extra query params, so no
# '&' escaping is needed inside the XML attribute value.
HUB_PATH = {
    POV: 'plugin://plugin.video.pov/?mode=navigator.search',
    UMBRELLA: ('plugin://plugin.video.umbrella/'
               '?action=tools_searchNavigator'),
}

HUB_ONCLICK = dict(
    (key, 'ActivateWindow(videos,{0},return)'.format(path))
    for key, path in HUB_PATH.items())

# --- AF3's four typed-search rows -----------------------------------------
# In search_path.xml '&' is written double-escaped as '&amp;amp;': the value
# is XML text that the skin's generator parses a second time. Each prefix
# ends where the encoded query is appended.
#
# Umbrella's person search goes through actorSearchMovies, which turns the
# typed name into an IMDb name-search URL and lists the people it finds --
# the closest equivalent of POV's person_search, and the only term-driven
# person action Umbrella exposes.
AF3_PREFIXES = {
    POV: {
        'Movies': ('plugin://plugin.video.pov/?mode=build_movie_list'
                   '&amp;amp;action=tmdb_movies_search&amp;amp;query='),
        'Tv': ('plugin://plugin.video.pov/?mode=build_tvshow_list'
               '&amp;amp;action=tmdb_tv_search&amp;amp;query='),
        'People': ('plugin://plugin.video.pov/?mode=person_search'
                   '&amp;amp;query='),
        'Collections': ('plugin://plugin.video.pov/?mode=build_movie_list'
                        '&amp;amp;action=tmdb_movies_search_collections'
                        '&amp;amp;query='),
    },
    UMBRELLA: {
        'Movies': ('plugin://plugin.video.umbrella/?action=movieSearchterm'
                   '&amp;amp;name='),
        'Tv': ('plugin://plugin.video.umbrella/?action=tvSearchterm'
               '&amp;amp;name='),
        'People': ('plugin://plugin.video.umbrella/?action=actorSearchMovies'
                   '&amp;amp;name='),
        'Collections': ('plugin://plugin.video.umbrella/'
                        '?action=collections_Searchterm&amp;amp;name='),
    },
}


def _log(msg, level='INFO'):
    try:
        from resources.lib import kodi_utils
        kodi_utils.log('search_provider: ' + msg, level=level)
    except Exception:
        pass


def _installed(addon_id):
    try:
        import xbmcaddon
        xbmcaddon.Addon(addon_id)
        return True
    except Exception:
        return False


def umbrella_available():
    return _installed(UMBRELLA_ADDON_ID)


def stored():
    """What the user chose, unfiltered. '' when never chosen."""
    try:
        from resources.lib import kodi_utils
        return (kodi_utils.get_setting(SETTING, '') or '').strip().lower()
    except Exception:
        return ''


def current():
    """The provider to actually wire up. Umbrella only when it is really
    installed: a search button that opens a missing add-on is worse than one
    that searches the other one."""
    value = stored()
    if value == UMBRELLA and umbrella_available():
        return UMBRELLA
    return POV


def hub_onclick():
    return HUB_ONCLICK[current()]


def hub_path():
    """The bare plugin path, for the one place (NOX's main menu) that embeds
    it inside an ActivateWindow of the skin's own making."""
    return HUB_PATH[current()]


def all_hub_paths():
    """Every provider's hub path. The NOX rewrite has to recognise whichever
    one is in the file today in order to replace it, not just the one it
    originally shipped."""
    return tuple(HUB_PATH.values())


def af3_prefixes():
    return AF3_PREFIXES[current()]


def set_provider(value):
    """Record the choice. Returns True when it actually changed."""
    value = value if value in (POV, UMBRELLA) else DEFAULT
    if stored() == value:
        return False
    try:
        from resources.lib import kodi_utils
        kodi_utils.set_setting(SETTING, value)
    except Exception as e:
        _log('could not store the choice: {0}'.format(e), 'WARNING')
        return False
    return True


def apply_to_skins():
    """Rewrite every skin's search wiring for the CURRENT provider and, if the
    user is looking at one of them right now, reload so they see it.

    Returns a (statuses, reloaded) tuple. Never raises: this runs from a
    settings click and from startup, and neither may be taken down by one
    skin whose files moved."""
    statuses = {}
    try:
        from resources.lib import fentastic_search_patcher
        statuses['hub'] = fentastic_search_patcher.ensure_patched()
    except Exception as e:
        statuses['hub'] = 'failed'
        _log('hub skins failed: {0}'.format(e), 'WARNING')
    try:
        from resources.lib import af3_search_pov_patcher
        statuses['af3'] = af3_search_pov_patcher.ensure_patched()
    except Exception as e:
        statuses['af3'] = 'failed'
        _log('AF3 failed: {0}'.format(e), 'WARNING')

    reloaded = False
    changed = 'patched' in statuses.values()
    if changed:
        reloaded = _refresh_active_skin(statuses.get('af3') == 'patched')
    _log('applied provider={0} statuses={1} reloaded={2}'.format(
        current(), statuses, reloaded))
    return statuses, reloaded


def _active_skin():
    try:
        import xbmc
        return xbmc.getSkinDir() or ''
    except Exception:
        return ''


def _refresh_active_skin(af3_changed):
    """A skin only re-reads its XML on a reload, so the new search target does
    not appear until then. Reload ONLY when the user is actually on a skin we
    just rewrote -- reloading a skin we did not touch is a visible flash for
    no reason. AF3 additionally has to regenerate its shortcut includes before
    the reload, which af3_home_patcher already knows how to do."""
    skin = _active_skin()
    hub_skins = ('skin.fentastic', 'skin.estuary', 'skin.povil.nox')
    try:
        import xbmc
    except Exception:
        return False
    # Every branch below rebuilds windows, and POV widgets live on the home
    # screen of all four skins -- so this guard belongs before the branch, not
    # inside one of them. Estuary, NOX and Arctic Fuse 3 were exposed to the
    # same fault as FENtastic; only the code path differed.
    # DO NOT WAIT HERE. Alone among the reload sites, this one is on a direct
    # user click -- the settings dialog's provider switch -- so a 30-second
    # block would look like the build had frozen, with no busy indicator. Skip
    # instead: the provider is already written to disk and the skin files
    # already rewritten before this runs, and the caller's dialog says the
    # change takes effect after a restart when this returns False. Nothing is
    # lost, and the click stays instant.
    cycling = False
    try:
        from resources.lib import pov_reload
        cycling = pov_reload.is_cycling()
    except Exception:
        cycling = False
    if cycling:
        _log('POV is cycling; not reloading the skin now. The provider is '
             'already stored and applied to the skin files, so it takes '
             'effect on the next start.', 'WARNING')
        return False
    if af3_changed and skin == 'skin.arctic.fuse.3':
        try:
            from resources.lib import af3_home_patcher
            # RETURN WHAT IT SAYS, do not assume it worked. This call site was
            # written when _rebuild_af3_shortcuts() returned None either way, so
            # discarding it was harmless; it now returns False when it defers a
            # rebuild, and reporting True regardless tells the settings dialog
            # the switch took effect when the AF3 search rows still hold the old
            # provider -- and the dialog then does NOT show its "restart for
            # this to apply" message, so the user has no way to know.
            return bool(af3_home_patcher._rebuild_af3_shortcuts())
        except Exception as e:
            _log('AF3 rebuild failed: {0}'.format(e), 'WARNING')
            return False
    if skin in hub_skins:
        try:
            xbmc.executebuiltin('ReloadSkin()')
            return True
        except Exception as e:
            _log('ReloadSkin failed: {0}'.format(e), 'WARNING')
    return False
