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

    # Make sure DarkSubs's machine-translate hook is in place. The
    # service runs this on Kodi startup too, but doing it here as
    # well catches the case where DarkSubs was installed (or
    # updated) AFTER Kodi started -- the patch goes in immediately,
    # without needing a reboot. Idempotent.
    try:
        from resources.lib import dark_subs_integration
        dark_subs_integration.maybe_patch_darksubs()
    except Exception as e:
        _safe_log('darksubs patch skipped: {0}'.format(e),
                  level='DEBUG')

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
    # Check whether DarkSubs is installed -- if it is, Wyzie is
    # redundant for most users and we should say so up front so they
    # don't waste time signing up.
    has_darksubs = False
    try:
        import xbmcaddon as _xa
        _xa.Addon('service.subtitles.All_Subs')
        has_darksubs = True
    except Exception:
        pass
    try:
        if has_darksubs:
            msg = (
                'שים לב: יש לך תוסף DarkSubs מותקן, '
                'אז Wyzie בעצם לא נחוץ - לחיצה על כתובית באנגלית '
                '(או כל שפה לא-עברית) ב-DarkSubs כבר מפעילה את '
                'התרגום AI אוטומטית.\n\nאם בכל זאת אתה רוצה key '
                '(למשל למקור אונליין נוסף מתוך התוסף שלי, בלי '
                'לעבור דרך DarkSubs):\n{0}\n\n1000 בקשות ביום, חינם.'
            ).format(url)
        else:
            msg = (
                'פתח בדפדפן:\n{0}\n\nתקבל API key חינמי '
                '(1000 בקשות/יום). העתק לשדה Wyzie API Key '
                'בהגדרות.\n\n(אופציונלי - אם תתקין בעתיד את '
                'התוסף DarkSubs, תוכל לוותר על Wyzie לגמרי.)'
            ).format(url)
        xbmcgui.Dialog().ok('Kodi POV IL', msg)
    except Exception:
        pass
    try:
        xbmc.executebuiltin('System.Exec("xdg-open {0}")'.format(url))
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
        # Test-connection is the canonical "I've adopted this addon"
        # moment; make sure DarkSubs's hook is in place right now so
        # the next subtitle pick already routes through our AI.
        try:
            from resources.lib import dark_subs_integration
            dark_subs_integration.maybe_patch_darksubs()
        except Exception:
            pass
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


def _handle_open_tmdb_notice(_params):
    """Explain that the gender-aware translation needs TMDB metadata
    via tmdbhelper, and that the user should connect TMDB through
    'Connect Services' in the wizard. Tries to open the wizard
    services screen automatically; if that fails, just shows the
    explanation."""
    try:
        from resources.lib import kodi_utils, tmdb_helper
    except Exception as e:
        xbmcgui.Dialog().ok('Kodi POV IL', 'Internal error: {0}'.format(e))
        return

    # Tell the user the current state -- have they wired it up?
    has_key = False
    try:
        has_key = bool(tmdb_helper._get_tmdb_key())
    except Exception:
        pass

    if has_key:
        status_line = ('✓ נמצא TMDB API key דרך תוסף TMDB Helper. '
                       'התרגום ידע לבחור צורות זכר/נקבה לפי הדמות.\n\n')
    else:
        status_line = ('✗ עדיין לא הוגדר TMDB API key.\n\n')

    body = (
        status_line +
        'תרגום AI משתמש ב-TMDB כדי לדעת מי שחקן כל דמות (זכר / '
        'נקבה), וככה לבחור צורות עברית נכונות לפי המגדר. בלי TMDB '
        'התרגום עדיין יעבוד אבל הזכר/נקבה יהיו ניחוש מהקשר בלבד.\n\n'
        'איך מחברים? פתח את ה-Wizard של POV IL → "Connect Services" '
        '(חיבור שירותים) → TMDB. תוסף ה-TMDB Helper כבר מותקן '
        'בבילד, רק צריך לאשר.'
    )
    xbmcgui.Dialog().ok('Kodi POV IL — TMDB', body)


def _handle_test_wyzie_connection(_params):
    """User clicked 'Test Wyzie connection' in settings. Mirrors
    _handle_test_connection for Gemini."""
    try:
        from resources.lib import kodi_utils, wyzie
    except Exception as e:
        xbmcgui.Dialog().ok('Kodi POV IL', 'Internal error: {0}'.format(e))
        return

    key = kodi_utils.get_setting('wyzie_api_key', '')
    if not (key or '').strip():
        xbmcgui.Dialog().ok(
            'Kodi POV IL',
            'לא הוגדר Wyzie API key. לחץ על "השג מפתח Wyzie" '
            'בהגדרות וקבל אחד חינמי (1000 בקשות ליום).')
        return

    result = wyzie.test_key(key)
    if result.get('ok'):
        xbmcgui.Dialog().ok('Kodi POV IL',
                            '✓ Wyzie: ' + result.get('message', 'OK'))
    else:
        xbmcgui.Dialog().ok('Kodi POV IL',
                            '✗ Wyzie: ' + result.get('message', 'נכשל'))


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


def _handle_translate_file(params):
    """Translate an SRT file to Hebrew on disk.

    Invoked by the DarkSubs engine.py hook via RunScript when the
    user picks a non-Hebrew subtitle from DarkSubs and has a Gemini
    key set. Reads input, translates, writes output, then touches
    a `.ai_done` sentinel next to the output so DarkSubs knows to
    pick it up instead of falling through to Google Translate.

    Params (base64-encoded so they survive RunScript's parameter
    parsing intact -- paths can contain commas, parens, quotes):
      input_b64  : path to source SRT
      output_b64 : path to write Hebrew SRT
    """
    import base64
    try:
        from resources.lib import kodi_utils, translate, srt
    except Exception as e:
        _safe_log('translate_file: import failed: {0}'.format(e),
                  level='ERROR')
        return

    def _decode(b):
        try:
            return base64.b64decode(b.encode('ascii')).decode('utf-8')
        except Exception:
            return ''

    in_path = _decode(params.get('input_b64', ''))
    out_path = _decode(params.get('output_b64', ''))
    if not in_path or not out_path:
        _safe_log('translate_file: missing input/output paths',
                  level='WARNING')
        return
    if not os.path.isfile(in_path):
        _safe_log(
            'translate_file: input not found: {0}'.format(in_path),
            level='WARNING')
        return

    # Read source SRT.
    try:
        with open(in_path, 'r', encoding='utf-8', errors='replace') as f:
            src_text = f.read()
    except OSError as e:
        _safe_log('translate_file: read failed: {0}'.format(e),
                  level='ERROR')
        return

    if not src_text.strip():
        _safe_log('translate_file: source empty', level='WARNING')
        return

    # We don't have video info here (the hook is running inside
    # DarkSubs's process), so synthesize what we can. Cast metadata
    # and proper title come from VideoPlayer InfoLabels if the
    # video is currently playing; otherwise we degrade gracefully.
    info = kodi_utils.current_video_info()

    # Reuse the core orchestration: translate via a temp link payload
    # that points at the source file we already have. resolve() does
    # its own caching, chunking, Gemini calls, etc.
    import json
    import urllib.parse
    payload = {
        'type': 'ai',
        'source_lang': 'en',  # DarkSubs's auto_translate only fires
                              # on non-Hebrew; English is by far the
                              # common case and the prompt is robust
                              # to a misidentified source language.
        'local_path': in_path,
    }
    link = urllib.parse.quote(
        json.dumps(payload, ensure_ascii=False))

    translated_path = None
    try:
        translated_path = translate.resolve(link, info)
    except Exception as e:
        _safe_log('translate_file: resolve crashed: {0}'.format(e),
                  level='ERROR')

    if not translated_path or not os.path.isfile(translated_path):
        _safe_log('translate_file: resolve returned nothing',
                  level='WARNING')
        return

    # Copy translated content to the output path DarkSubs expects.
    try:
        with open(translated_path, 'r', encoding='utf-8',
                  errors='replace') as f:
            hebrew = f.read()
        # Write atomically: temp file in same dir, then rename. This
        # avoids a half-written file being picked up by the hook.
        tmp_out = out_path + '.aitmp'
        with open(tmp_out, 'w', encoding='utf-8') as f:
            f.write(hebrew)
        os.replace(tmp_out, out_path)
    except OSError as e:
        _safe_log('translate_file: write failed: {0}'.format(e),
                  level='ERROR')
        return

    # Touch the sentinel last -- the hook polls for it. Only after
    # the output is complete on disk.
    try:
        open(out_path + '.ai_done', 'w').close()
    except OSError as e:
        _safe_log('translate_file: sentinel write failed: {0}'
                  .format(e), level='WARNING')


def _handle_purge_temp(_params):
    """Wipe ALL .srt files in special://temp/. Used to clear out
    stale subtitle leftovers from previous movies that Kodi keeps
    in temp and would otherwise leak into the next movie's
    subtitle search dialog."""
    try:
        from resources.lib import local_subs
    except Exception as e:
        xbmcgui.Dialog().ok('Kodi POV IL', 'Internal error: {0}'.format(e))
        return
    n = local_subs.purge_temp_subs()
    xbmcgui.Dialog().ok(
        'Kodi POV IL',
        'נמחקו {0} קבצי כתוביות מ-temp.'.format(n))


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
        elif action == 'test_wyzie_connection':
            _handle_test_wyzie_connection(params)
        elif action == 'open_tmdb_notice':
            _handle_open_tmdb_notice(params)
        elif action == 'clear_cache':
            _handle_clear_cache(params)
        elif action == 'purge_temp':
            _handle_purge_temp(params)
        elif action == 'translate_file':
            _handle_translate_file(params)
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
