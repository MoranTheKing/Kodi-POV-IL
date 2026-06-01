# One-shot first-launch dialog for Arctic Fuse 3.
#
# When a user switches to skin.arctic.fuse.3 for the first time
# (either via the wizard's Switch Skin dialog or Kodi's own Interface
# settings), AF3 boots with no Trakt or TMDb connection. The hub
# population is barren until the user opens POV's Connect Services
# menu and authorises Trakt + TMDb. New users don't know this; the
# barren UI looks like a broken skin.
#
# This patcher detects "AF3 is the active skin AND we've never shown
# the dialog before", then pops a single Hebrew dialog offering to
# open POV's Connect Services on the user's behalf. The choice is
# recorded in our addon's settings so we never bother the same user
# twice -- unless they hit "Remind me later", which deliberately
# leaves the marker unset.
#
# IMPORTANT: We do NOT attempt to run Trakt's or TMDb's OAuth flow
# ourselves. We just open POV's Connect Services dialog (which POV
# owns and maintains). The user clicks the service they want; POV
# handles the rest.

try:
    import xbmc
    import xbmcgui
except ImportError:
    xbmc = None
    xbmcgui = None


AF3_SKIN_ID = 'skin.arctic.fuse.3'
DONE_SETTING = 'af3_first_launch_dialog_done'

# POV's Connect Services entry-point (same URL as the home tile in
# our FENtastic favourites.xml). RunPlugin so the call returns
# without blocking the service.
_POV_CONNECT_SERVICES = (
    'RunPlugin("plugin://plugin.video.pov/?mode=myservices")')


def _current_skin_id():
    if xbmc is None:
        return ''
    try:
        return xbmc.getSkinDir() or ''
    except Exception:
        return ''


def _already_done():
    """True if we've already shown the dialog (or the user said
    'no thanks'). Read from our addon settings; returns False on any
    error so a corrupted settings file doesn't permanently silence
    the dialog -- worst case we re-show it once."""
    try:
        from resources.lib import kodi_utils
        return kodi_utils.get_bool(DONE_SETTING, default=False)
    except Exception:
        return False


def _mark_done():
    try:
        from resources.lib import kodi_utils
        kodi_utils.set_setting(DONE_SETTING, 'true')
    except Exception:
        pass


def _log(msg, level='INFO'):
    try:
        from resources.lib import kodi_utils
        kodi_utils.log('af3_first_launch: ' + msg, level=level)
    except Exception:
        try:
            xbmc.log('[service.subtitles.kodipovilai] '
                     'af3_first_launch: ' + msg, level=xbmc.LOGINFO)
        except Exception:
            pass


def _open_connect_services():
    """Fire POV's Connect Services dialog. Best-effort; if POV isn't
    installed we don't crash."""
    try:
        xbmc.executebuiltin(_POV_CONNECT_SERVICES)
    except Exception as e:
        _log('failed to open POV Connect Services: {0}'.format(e),
             level='WARNING')


def maybe_show():
    """One-shot: if AF3 is active and the dialog hasn't been shown,
    show it. Records the choice (except for 'remind later') so this
    is idempotent + cheap to call every startup.

    Returns one of:
      'not_af3'        -- some other skin is active; no-op
      'already_done'   -- marker set; no-op
      'remind_later'   -- user picked remind later; marker NOT set
      'just_trakt'     -- opened Connect Services, marker set
      'just_tmdb'      -- opened Connect Services, marker set
      'connect_both'   -- opened Connect Services, marker set
      'no_thanks'      -- marker set, no dialog opened
      'cancelled'      -- user dismissed the dialog (ESC); marker
                          NOT set so we re-prompt next launch
      'error'          -- caught exception; marker NOT set
    """
    if xbmc is None or xbmcgui is None:
        return 'not_af3'

    skin = _current_skin_id()
    if skin != AF3_SKIN_ID:
        return 'not_af3'

    if _already_done():
        return 'already_done'

    try:
        # Give Kodi a beat to finish skin load + python plugins
        # before stealing focus with a dialog.
        try:
            monitor = xbmc.Monitor()
            monitor.waitForAbort(3)
        except Exception:
            pass

        # Bail if Kodi is on its way down.
        try:
            if xbmc.Monitor().abortRequested():
                return 'error'
        except Exception:
            pass

        title = '[B]Arctic Fuse 3 - חיבור שירותים[/B]'
        body = (
            '[B]ברוכים הבאים לסקין Arctic Fuse 3![/B]\n\n'
            'הסקין הזה ממלא את מסך הבית מתוך נתוני '
            '[COLOR orange]Trakt[/COLOR] ו-[COLOR orange]TMDb[/COLOR]. '
            'בלי חיבור לשירותים האלה, המסך יישאר ריק.\n\n'
            'איך תרצו להתחבר?')

        options = [
            '[B][COLOR springgreen]חבר את שניהם[/COLOR][/B] '
            '(Trakt + TMDb) - מומלץ',
            '[B]חבר רק Trakt[/B]',
            '[B]חבר רק TMDb[/B]',
            '[B][COLOR yellow]הזכר לי בפעם הבאה[/COLOR][/B]',
            '[B][COLOR red]לא, תודה[/COLOR][/B]',
        ]

        dialog = xbmcgui.Dialog()
        choice = dialog.select(title, options)

        if choice == -1:  # ESC / cancel
            _log('user cancelled (ESC); will re-prompt next launch')
            return 'cancelled'

        if choice == 0:  # Connect both
            _log('user chose: connect both')
            _open_connect_services()
            _mark_done()
            return 'connect_both'

        if choice == 1:  # Just Trakt
            _log('user chose: just Trakt')
            _open_connect_services()
            _mark_done()
            return 'just_trakt'

        if choice == 2:  # Just TMDb
            _log('user chose: just TMDb')
            _open_connect_services()
            _mark_done()
            return 'just_tmdb'

        if choice == 3:  # Remind me later
            _log('user chose: remind later; will re-prompt next launch')
            return 'remind_later'

        if choice == 4:  # No thanks
            _log('user chose: no thanks; will not prompt again')
            _mark_done()
            return 'no_thanks'

        return 'cancelled'

    except Exception as e:
        _log('error: {0}'.format(e), level='WARNING')
        return 'error'
