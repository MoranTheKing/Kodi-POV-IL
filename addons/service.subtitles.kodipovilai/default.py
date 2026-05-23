# Kodi subtitle service entry point.
#
# Kodi launches this with action=search or action=download in the
# query string. For search, we hand back a list of available subs
# via ListItem objects. For download, we return the path of an SRT
# file on disk via a single ListItem with the file path.
#
# Everything we do here is wrapped in try/except: a crash in this
# script is invisible to the user except as "no subtitles found",
# but it would leak stack traces into kodi.log. We catch and log
# gracefully so the rest of Kodi keeps running.

import os
import sys
import urllib.parse

try:
    import xbmc
    import xbmcaddon
    import xbmcgui
    import xbmcplugin
    import xbmcvfs
except ImportError:
    # Allow `python -m default --action=search` for local debug.
    xbmc = xbmcaddon = xbmcgui = xbmcplugin = xbmcvfs = None

# We import lazily inside handlers so a bad import path doesn't
# prevent the plugin from registering at all.

ADDON_ID = 'service.subtitles.kodipovilai'


def _parse_query():
    """Pull params from the query string Kodi handed us.

    Two invocation styles share this script:
      plugin: sys.argv = [url, handle, '?action=download&link=...']
      runscript: sys.argv = [path, 'action=test_connection', ...]

    We sniff which one we're in by looking at argv[0] -- plugin
    invocations start with 'plugin://'. For runscript we fold each
    'key=value' arg into the params dict.
    """
    out = {}
    if not sys.argv:
        return out

    argv0 = sys.argv[0] or ''
    if argv0.startswith('plugin://'):
        if len(sys.argv) >= 3:
            q = sys.argv[2] or ''
            if q.startswith('?'):
                q = q[1:]
            for k, v in urllib.parse.parse_qsl(q, keep_blank_values=True):
                out[k] = v
        return out

    # RunScript: each remaining arg is "key=value" (or just "key").
    for a in sys.argv[1:]:
        if not a:
            continue
        if '=' in a:
            k, v = a.split('=', 1)
            out[k.strip()] = v.strip()
        else:
            out[a.strip()] = '1'
    return out


def _safe_log(msg, level='INFO'):
    try:
        from resources.lib import kodi_utils
        kodi_utils.log(msg, level=level)
    except Exception:
        try:
            if xbmc:
                xbmc.log('[{0}] {1}'.format(ADDON_ID, msg), xbmc.LOGINFO)
        except Exception:
            pass


def _handle_search(handle, params):
    """List available subtitles. Kodi calls this when the user opens
    the subtitle search dialog."""
    from resources.lib import kodi_utils, translate

    info = kodi_utils.current_video_info()
    _safe_log('search: ' + repr({k: v for k, v in info.items() if v}))

    try:
        candidates = translate.list_candidates(info)
    except Exception as e:
        _safe_log('list_candidates crashed: {0}'.format(e), level='ERROR')
        candidates = []

    for c in candidates:
        try:
            label = c.get('filename', 'AI Hebrew')
            listitem = xbmcgui.ListItem(label=c.get('language', 'he'),
                                        label2=label)
            listitem.setArt({'icon': str(c.get('rating', '3')),
                             'thumb': c.get('language', 'he')})
            listitem.setProperty('sync', c.get('sync', 'false'))
            listitem.setProperty('hearing_imp',
                                 'true' if c.get('is_hi') else 'false')
            url = ('plugin://{0}/?action=download&link={1}'
                   .format(ADDON_ID,
                           urllib.parse.quote(c.get('link', ''), safe='')))
            xbmcplugin.addDirectoryItem(handle=handle, url=url,
                                        listitem=listitem,
                                        isFolder=False)
        except Exception as e:
            _safe_log('addDirectoryItem failed: {0}'.format(e),
                      level='WARNING')

    xbmcplugin.endOfDirectory(handle)


def _handle_download(handle, params):
    """User picked one of our entries -- deliver the SRT path."""
    from resources.lib import kodi_utils, translate

    link = params.get('link', '')
    info = kodi_utils.current_video_info()

    progress = None
    try:
        progress = xbmcgui.DialogProgressBG()
        progress.create('Kodi POV IL', 'AI Hebrew')
    except Exception:
        progress = None

    def report(stage, total):
        if not progress:
            return
        try:
            pct = int(stage * 100 / max(1, total))
            progress.update(pct, 'Kodi POV IL',
                            kodi_utils.localised(33001, stage, total))
        except Exception:
            pass

    try:
        path = translate.resolve(link, info, progress_cb=report)
    except Exception as e:
        _safe_log('resolve crashed: {0}'.format(e), level='ERROR')
        path = None

    if progress is not None:
        try:
            progress.close()
        except Exception:
            pass

    if path and os.path.isfile(path):
        listitem = xbmcgui.ListItem(label=path)
        xbmcplugin.addDirectoryItem(handle=handle, url=path,
                                    listitem=listitem,
                                    isFolder=False)
    xbmcplugin.endOfDirectory(handle)


def _handle_manualsearch(handle, params):
    # Kodi sometimes invokes manualsearch when the user types a
    # query in the search dialog. We treat it the same as search;
    # the title/year still flow through getInfoLabel.
    _handle_search(handle, params)


# ---- RunScript handlers (settings buttons) --------------------------

def _handle_open_aistudio(_params):
    """Open the AI Studio key-creation page in the user's browser
    when they tap "Get a free Gemini API key" in settings."""
    url = 'https://aistudio.google.com/apikey'
    try:
        xbmc.executebuiltin('System.Exec("xdg-open {0}")'.format(url))
    except Exception:
        pass
    # Always show a fallback dialog with the URL so users on
    # platforms without a usable browser (Fire TV, Shield) can copy
    # it down manually.
    try:
        from resources.lib import kodi_utils
        xbmcgui.Dialog().ok(
            'Kodi POV IL',
            'פתח בדפדפן:\n{0}\n\nצור API key (חינמי), העתק, '
            'והדבק בשדה "Gemini API Key" בהגדרות.'.format(url),
        )
    except Exception:
        pass


def _handle_open_wyzie_signup(_params):
    """User clicked 'Claim a free Wyzie key' in settings."""
    url = 'https://store.wyzie.io/redeem'
    try:
        xbmc.executebuiltin('System.Exec("xdg-open {0}")'.format(url))
    except Exception:
        pass
    try:
        xbmcgui.Dialog().ok(
            'Kodi POV IL',
            'פתח בדפדפן:\n{0}\n\nתקבל API key חינמי (1000 בקשות/יום). '
            'העתק לשדה Wyzie API Key בהגדרות.'.format(url),
        )
    except Exception:
        pass


def _handle_test_connection(_params):
    """User clicked "Test connection" in settings."""
    try:
        from resources.lib import kodi_utils, gemini
    except Exception as e:
        xbmcgui.Dialog().ok('Kodi POV IL', 'Internal error: {0}'.format(e))
        return

    api_key = kodi_utils.get_setting('api_key', '')
    model   = kodi_utils.get_setting('model', 'gemini-3.1-flash-lite') \
              or 'gemini-3.1-flash-lite'

    if not api_key:
        xbmcgui.Dialog().ok('Kodi POV IL', kodi_utils.localised(33002))
        return

    try:
        matched = gemini.test_key(api_key, model=model)
        xbmcgui.Dialog().ok('Kodi POV IL',
                            kodi_utils.localised(33003, matched))
    except gemini.InvalidKey as e:
        xbmcgui.Dialog().ok('Kodi POV IL',
                            kodi_utils.localised(33004, str(e)[:120]))
    except gemini.GeminiError as e:
        xbmcgui.Dialog().ok('Kodi POV IL',
                            kodi_utils.localised(33004, str(e)[:120]))
    except Exception as e:
        xbmcgui.Dialog().ok('Kodi POV IL',
                            kodi_utils.localised(33004, str(e)[:120]))


def _handle_clear_cache(_params):
    """Wipe all cached translations + metadata."""
    try:
        from resources.lib import cache, kodi_utils
    except Exception as e:
        xbmcgui.Dialog().ok('Kodi POV IL', 'Internal error: {0}'.format(e))
        return
    confirm = xbmcgui.Dialog().yesno(
        'Kodi POV IL',
        'נקה את כל ה-cache של התרגומים?\n(תרגומים עתידיים יתבצעו מחדש.)',
    )
    if not confirm:
        return
    n = cache.clear_all()
    xbmcgui.Dialog().ok('Kodi POV IL', kodi_utils.localised(33007, n))


def main():
    if xbmc is None:
        _safe_log('default.py invoked outside Kodi -- nothing to do',
                  level='WARNING')
        return

    try:
        handle = int(sys.argv[1]) if len(sys.argv) > 1 else -1
    except (ValueError, TypeError):
        handle = -1

    params = _parse_query()
    action = (params.get('action') or 'search').lower()

    try:
        if action == 'search':
            _handle_search(handle, params)
        elif action == 'manualsearch':
            _handle_manualsearch(handle, params)
        elif action == 'download':
            _handle_download(handle, params)
        elif action == 'open_aistudio':
            _handle_open_aistudio(params)
        elif action == 'open_wyzie_signup':
            _handle_open_wyzie_signup(params)
        elif action == 'test_connection':
            _handle_test_connection(params)
        elif action == 'clear_cache':
            _handle_clear_cache(params)
        else:
            _safe_log('unknown action: ' + action, level='WARNING')
            if handle >= 0:
                xbmcplugin.endOfDirectory(handle)
    except Exception as e:
        _safe_log('main crashed: {0}'.format(e), level='ERROR')
        try:
            if handle >= 0:
                xbmcplugin.endOfDirectory(handle)
        except Exception:
            pass


if __name__ == '__main__':
    main()
