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
import shutil
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

    # Opt-in fast path for the NATIVE Kodi subtitle picker. Mirrors
    # the DarkSubs fast_first_chunk flow in _handle_translate_file:
    # deliver the English source to Kodi immediately and continue
    # translating in a separate fire-and-forget RunScript invocation
    # (the picker subprocess ends at endOfDirectory). On any internal
    # failure we fall through to the legacy slow flow below so the
    # user always gets SOMETHING.
    try:
        whole_mode = kodi_utils.get_bool('whole_subtitle_request', False)
        fast_mode = (
            kodi_utils.get_bool('fast_first_chunk', False)
            and not whole_mode
        )
    except Exception:
        fast_mode = False
    if fast_mode:
        try:
            if _try_fast_download(handle, link, info):
                return  # endOfDirectory was called inside the helper
        except Exception as _e:
            _safe_log('fast_download outer guard caught: {0}'
                      .format(_e), level='WARNING')

    # DialogProgressBG (bottom-right banner) PLUS milestone toasts.
    # The toasts at 25/50/75 % are the guaranteed-visible backup --
    # DialogProgressBG can be hidden behind a full-screen window
    # (DarkSubs MySubs, the video OSD) but toasts always layer on
    # top of everything. v0.2.42-0.2.44 tried a custom WindowDialog
    # overlay; that approach kept failing in various ways (hidden
    # behind pyxbmct, then all-black render, then thread-update
    # blackhole) so we reverted to the simple toast-driven pattern
    # that worked reliably in v0.2.41.
    progress = None
    try:
        progress = xbmcgui.DialogProgressBG()
        progress.create('MoranSubs',
                        'AI Hebrew')
    except Exception:
        progress = None

    _milestone_state = {'last': 0}

    def report(stage, total):
        try:
            pct = int(stage * 100 / max(1, total))
            if progress is not None:
                try:
                    progress.update(
                        pct, 'MoranSubs',
                        kodi_utils.localised(33001, stage, total))
                except Exception:
                    pass
            # Milestone toasts -- always visible above any window.
            milestone = (pct // 25) * 25
            if (milestone in (25, 50, 75)
                    and milestone > _milestone_state['last']):
                _milestone_state['last'] = milestone
                try:
                    kodi_utils.notify(
                        'AI: {0}% תורגם ({1}/{2} chunks)'.format(
                            milestone, stage, total),
                        time_ms=3500)
                except Exception:
                    pass
        except Exception:
            pass

    try:
        path = translate.resolve(link, info, progress_cb=report)
    except Exception as e:
        _safe_log('resolve crashed: {0}'.format(e), level='ERROR')
        path = None
    finally:
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


def _try_fast_download(handle, link, info):
    """Native-picker fast path. Returns True on success
    (endOfDirectory was called). Returns False to mean 'fall
    through to the legacy slow flow' for any case the fast path
    cannot handle (non-AI link, source missing, cache resolution
    failure).

    Pattern: two RunScript invocations with a base64-encoded
    link baton. This invocation (the picker subprocess) writes
    the English fallback SRT, hands it to Kodi via
    endOfDirectory(), then fires a fire-and-forget RunScript
    with action=bg_translate_picker that continues the Hebrew
    translation in its own process. We can't keep working in
    this subprocess because endOfDirectory ends it."""
    import base64
    try:
        from resources.lib import (kodi_utils, translate,
                                    srt as _srt, cache as _cache)
    except Exception:
        return False

    payload = translate._decode_link(link)
    if not payload or payload.get('type') != 'ai':
        # passthrough / pool entries are short -- the existing path
        # handles them fine.
        return False

    source_lang = payload.get('source_lang') or 'en'
    local_source = payload.get('local_path')
    imdb_id = (info.get('imdb_id') or '').strip()
    season  = info.get('season') or ''
    episode = info.get('episode') or ''

    # Fast path briefly shows the SOURCE SRT to the user (until the
    # first Hebrew chunk arrives). English is broadly readable in
    # our user base; Spanish / Portuguese / German / French are not.
    # For non-English sources fall through to the legacy slow path
    # so the user only ever sees Hebrew (after a longer wait).
    # Unlike the DarkSubs path where we hardcode source_lang='en',
    # here the payload carries the actual configured source language.
    if source_lang != 'en':
        return False

    source_id = translate._source_id_for_ai(payload)

    # Cache hit fast path: serve cached Hebrew immediately. The
    # cache key here matches what list_candidates uses for its
    # [CACHE] marker, so a [CACHE]-marked entry resolves with
    # zero AI work.
    if source_id:
        try:
            cached = _cache.translated_path(
                imdb_id, season, episode, source_lang,
                source_id=source_id)
            if os.path.isfile(cached):
                listitem = xbmcgui.ListItem(label=cached)
                xbmcplugin.addDirectoryItem(
                    handle=handle, url=cached,
                    listitem=listitem, isFolder=False)
                xbmcplugin.endOfDirectory(handle)
                try:
                    kodi_utils.notify(
                        'AI: כתוביות מ-cache (תרגום קודם)',
                        time_ms=3000)
                except Exception:
                    pass
                return True
        except Exception as _e:
            _safe_log('fast_download cache check failed: {0}'
                      .format(_e), level='WARNING')

    # No cache hit. Read the source SRT inline (instant -- local file
    # alongside the video or a temp file from another addon).
    src_text = None
    try:
        if local_source and os.path.isfile(local_source):
            with open(local_source, 'r', encoding='utf-8',
                      errors='replace') as f:
                src_text = f.read()
    except Exception as _e:
        _safe_log('fast_download source read failed: {0}'
                  .format(_e), level='WARNING')

    if not src_text:
        # Fall through; existing slow path will surface the error.
        return False

    # HI-strip guard mirroring translate.py:518-521. We're delivering
    # the English source as a fallback, and Hebrew chunks will land
    # later from the BG translation -- those run through the same
    # cleaner. If the cleaner ate too much we keep the raw source.
    try:
        cleaned = _srt.strip_hi_annotations(src_text)
        if cleaned and _srt.count_entries(cleaned) >= max(
                1, int(_srt.count_entries(src_text) * 0.3)):
            src_text = cleaned
    except Exception:
        pass  # use raw source on cleaner failure

    # Write English fallback to cache_dir under a deterministic name
    # so repeat clicks of the same source overwrite cleanly.
    fallback_id = source_id or 'unknown'
    fallback_path = os.path.join(
        kodi_utils.cache_dir(),
        'fast_picker_fallback_{0}.srt'.format(fallback_id))
    try:
        _tmp = fallback_path + '.aitmp'
        with open(_tmp, 'w', encoding='utf-8') as _f:
            _f.write(src_text)
        os.replace(_tmp, fallback_path)
    except OSError as _e:
        _safe_log('fast_download fallback write failed: {0}'
                  .format(_e), level='ERROR')
        return False

    # Hand the English fallback to Kodi -- the user sees subtitles
    # in seconds. endOfDirectory() ends this subprocess; the BG
    # RunScript below picks up the Hebrew translation.
    listitem = xbmcgui.ListItem(label=fallback_path)
    xbmcplugin.addDirectoryItem(
        handle=handle, url=fallback_path,
        listitem=listitem, isFolder=False)
    xbmcplugin.endOfDirectory(handle)

    try:
        kodi_utils.notify(
            'AI: כתוביות מוכנות, מתרגם ברקע', time_ms=4000)
    except Exception:
        pass

    # Fire BG translation as a separate RunScript invocation. Once
    # endOfDirectory() returns, this subprocess exits, so we hand
    # the link off in a separate process via RunScript. base64 keeps
    # the JSON-quoted link from getting mangled by RunScript's
    # comma-split parameter parsing.
    try:
        link_b64 = base64.b64encode(
            link.encode('utf-8')).decode('ascii')
        source_id_b64 = base64.b64encode(
            (source_id or '').encode('utf-8')).decode('ascii')
        xbmc.executebuiltin(
            'RunScript(service.subtitles.kodipovilai,'
            'action=bg_translate_picker,'
            'link_b64={0},source_id_b64={1})'.format(
                link_b64, source_id_b64))
    except Exception as _e:
        _safe_log('fast_download BG fire failed: {0}'.format(_e),
                  level='ERROR')
        # Subtitle was already delivered; BG didn't fire. User
        # gets English permanently for this play. Acceptable
        # degradation -- next play will still try the same fast
        # path and the cache check will short-circuit if BG
        # eventually ran on a different click.

    return True


def _handle_bg_translate_picker(params):
    """Fired by _handle_download after delivering the English
    fallback subtitle to Kodi. Calls translate.resolve() with a
    progressive_cb that writes versioned .vN.srt files and swaps
    them in via xbmc.Player().setSubtitles() as Hebrew chunks
    complete. No sentinel handshake here -- DarkSubs is not
    involved in the native-picker path."""
    import base64
    try:
        from resources.lib import kodi_utils, translate
    except Exception as e:
        _safe_log('bg_translate_picker import failed: {0}'.format(e),
                  level='ERROR')
        return

    def _b64(b):
        try:
            return base64.b64decode(
                b.encode('ascii')).decode('utf-8')
        except Exception:
            return ''

    link = _b64(params.get('link_b64', ''))
    expected_source_id = _b64(params.get('source_id_b64', ''))
    if not link:
        _safe_log('bg_translate_picker: missing link',
                  level='WARNING')
        return

    info = kodi_utils.current_video_info()

    # Set Window props upfront so chunk_ready gates pass. The
    # DarkSubs flow sets these inside the first_ready callback,
    # but here first_ready is a no-op (the English fallback was
    # already delivered to Kodi by _handle_download) -- so we
    # need to set the flags before resolve() can emit chunk_ready.
    xbmcgui.Window(10000).setProperty(
        'ai_subs.live_translate_active', '1')
    xbmcgui.Window(10000).setProperty(
        'ai_subs.live_translate_source', expected_source_id)

    _ver = {'n': 0}

    def on_phase(phase, payload):
        try:
            # We tolerate first_ready -- it's a no-op here, the
            # fallback is already on Kodi. We just guard against
            # an unexpected source_id mismatch (sanity check, should
            # never happen but cheap to verify).
            if phase == 'first_ready':
                _got = payload.get('source_id', '')
                if (expected_source_id
                        and _got != expected_source_id):
                    _safe_log(
                        'bg_translate_picker: source_id mismatch '
                        '(expected {0}, got {1})'.format(
                            expected_source_id, _got),
                        level='WARNING')
                return
            if phase == 'chunk_ready':
                # Same dual-gate as the DarkSubs path: active flag
                # AND source_id match. If the user picked a different
                # subtitle while we're translating, a stale chunk
                # from THIS translation must not clobber the new
                # pick's subtitles.
                if (xbmcgui.Window(10000).getProperty(
                        'ai_subs.live_translate_active') != '1'
                        or xbmcgui.Window(10000).getProperty(
                            'ai_subs.live_translate_source')
                        != payload['source_id']):
                    return
                # Alternating-slot write (same approach as DarkSubs
                # path). Caps Kodi subtitle-stream accumulation at 2
                # during translation instead of 1 per chunk -- user
                # reported "10/10" piling up in the picker.
                slot = 'b' if _ver.get('slot', 'b') == 'a' else 'a'
                _ver['slot'] = slot
                ver_path = os.path.join(
                    kodi_utils.cache_dir(),
                    'progressive_{0}_{1}.he.srt'.format(
                        payload['source_id'], slot))
                _tmp = ver_path + '.aitmp'
                with open(_tmp, 'w', encoding='utf-8') as _f:
                    _f.write(payload['merged_text'])
                os.replace(_tmp, ver_path)
                try:
                    if xbmc.Player().isPlayingVideo():
                        xbmc.Player().setSubtitles(ver_path)
                        xbmc.Player().showSubtitles(True)
                except Exception as _e:
                    _safe_log(
                        'bg_translate_picker setSubtitles raised: '
                        '{0}'.format(_e), level='DEBUG')
                return
            if phase == 'done':
                # Same robust canonical-swap pattern as the DarkSubs
                # path: copy canonical bytes to a fresh _final.he.srt
                # path to defeat Kodi's parse cache; don't gate on
                # isPlayingVideo (let the try/except handle a paused
                # player); only delete .vN files when the swap
                # actually landed.
                _canonical_swap_succeeded = False
                if payload.get('success'):
                    try:
                        from resources.lib import cache as _cache
                        canonical = _cache.translated_path(
                            (info.get('imdb_id') or '').strip(),
                            info.get('season') or '',
                            info.get('episode') or '',
                            'en',
                            source_id=payload['source_id'])
                        if os.path.isfile(canonical):
                            _final_path = os.path.join(
                                kodi_utils.cache_dir(),
                                'progressive_{0}_final.he.srt'.format(
                                    payload['source_id']))
                            try:
                                with open(canonical, 'rb') as _src_f:
                                    _bytes = _src_f.read()
                                _tmp_final = _final_path + '.aitmp'
                                with open(_tmp_final, 'wb') as _dst_f:
                                    _dst_f.write(_bytes)
                                os.replace(_tmp_final, _final_path)
                            except OSError as _we:
                                _safe_log(
                                    'bg_translate_picker done copy '
                                    'failed: {0}'.format(_we),
                                    level='WARNING')
                                _final_path = None
                            if _final_path:
                                try:
                                    p = xbmc.Player()
                                    p.setSubtitles(_final_path)
                                    p.showSubtitles(True)
                                    # Force-pick our newly-added
                                    # stream so Kodi doesn't auto-
                                    # revert to a pre-existing
                                    # Hebrew subtitle (user-reported
                                    # "jumps back to Hebrew" bug
                                    # when an existing he-SRT was
                                    # already loaded before picking
                                    # English for AI translation).
                                    try:
                                        _streams = p.getAvailableSubtitleStreams()
                                        if _streams:
                                            p.setSubtitleStream(
                                                len(_streams) - 1)
                                    except Exception:
                                        pass
                                    _canonical_swap_succeeded = True
                                except Exception as _se:
                                    _safe_log(
                                        'bg_translate_picker done '
                                        'setSubtitles raised: {0}'
                                        .format(_se), level='DEBUG')
                    except Exception as _e:
                        _safe_log(
                            'bg_translate_picker done canonical '
                            'swap failed: {0}'.format(_e),
                            level='DEBUG')
                # Cleanup ONLY when the canonical swap succeeded.
                if _canonical_swap_succeeded:
                    try:
                        import glob as _glob
                        # Patterns cover BOTH legacy (_v*) from
                        # pre-alternation builds AND the new _a/_b
                        # alternation slots. _final stays as the
                        # canonical stream Kodi is on.
                        _patterns = [
                            'progressive_{0}_v*.he.srt'.format(
                                payload['source_id']),
                            'progressive_{0}_a.he.srt'.format(
                                payload['source_id']),
                            'progressive_{0}_b.he.srt'.format(
                                payload['source_id']),
                        ]
                        for _pat in _patterns:
                            for _stale in _glob.glob(
                                    os.path.join(
                                        kodi_utils.cache_dir(),
                                        _pat)):
                                try:
                                    os.remove(_stale)
                                except OSError:
                                    pass
                    except Exception:
                        pass
                xbmcgui.Window(10000).clearProperty(
                    'ai_subs.live_translate_active')
                xbmcgui.Window(10000).clearProperty(
                    'ai_subs.live_translate_source')
                return
        except Exception as _e:
            _safe_log(
                'bg_translate_picker on_phase({0}) raised: '
                '{1}'.format(phase, _e), level='WARNING')

    try:
        translate.resolve(link, info, progressive_cb=on_phase)
    except Exception as e:
        _safe_log(
            'bg_translate_picker resolve crashed: {0}'.format(e),
            level='ERROR')
    finally:
        # Belt-and-suspenders -- the done phase clears these too,
        # but on a resolve() crash before done we still want the
        # active flag cleared so a follow-up pick isn't gated by
        # a stale source_id.
        try:
            xbmcgui.Window(10000).clearProperty(
                'ai_subs.live_translate_active')
            xbmcgui.Window(10000).clearProperty(
                'ai_subs.live_translate_source')
        except Exception:
            pass


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



def _handle_connect_gemini(_params):
    """Full Gemini auth flow invoked from POV's My Services menu
    (or from anywhere via RunScript). Provides two onboarding
    paths -- pair-from-phone via local HTTP server, or type the
    key directly -- and validates against Gemini's /models
    endpoint INLINE before writing to settings, so a bad key
    never lands in the addon's persistent state."""
    try:
        from resources.lib import kodi_utils, gemini, gemini_pair
    except Exception as e:
        try:
            xbmcgui.Dialog().ok('Kodi POV IL',
                                'Internal error: {0}'.format(e))
        except Exception:
            pass
        return

    current = (kodi_utils.get_setting('api_key', '') or '').strip()
    if current:
        _gemini_menu_existing(kodi_utils, gemini, gemini_pair, current)
    else:
        _gemini_menu_new(kodi_utils, gemini, gemini_pair)


def _gemini_menu_existing(kodi_utils, gemini, gemini_pair, current_key):
    """User clicked Gemini in My Services and already has a key
    set. Offer Test / Usage / Replace / Remove."""
    options = [
        '🔍 בדוק חיבור (Test connection)',
        '📊 ניצול היום (Daily usage)',
        '🔄 החלף key (Replace)',
        '❌ מחק key (Remove)',
    ]
    try:
        choice = xbmcgui.Dialog().select(
            'Gemini AI - מה לעשות?', options)
    except Exception:
        choice = -1
    if choice < 0:
        return
    if choice == 0:
        _test_key_show_result(kodi_utils, gemini, current_key)
        return
    if choice == 1:
        _show_gemini_usage()
        return
    if choice == 2:
        # Don't clear the existing key here -- if the user cancels
        # mid-flow (closes the QR dialog, dismisses the keyboard,
        # taps outside the screen) they'd lose a working key with
        # no replacement. The new key, once validated, overwrites
        # the old one via set_setting in _test_save_or_retry, so
        # replace happens atomically on success; on cancel the old
        # key stays put.
        _gemini_menu_new(kodi_utils, gemini, gemini_pair)
        return
    if choice == 3:
        confirm = xbmcgui.Dialog().yesno(
            'Kodi POV IL', 'למחוק את ה-Gemini API key?')
        if confirm:
            kodi_utils.set_setting('api_key', '')
            kodi_utils.notify('Gemini key נמחק', time_ms=3000)


def _show_gemini_usage():
    """Render the daily quota status in a Dialog().ok(). Used by
    the 'ניצול היום' menu entry and the runscript action."""
    try:
        from resources.lib import gemini_quota
    except Exception as e:
        try:
            xbmcgui.Dialog().ok('Kodi POV IL',
                                'Internal error: {0}'.format(e))
        except Exception:
            pass
        return
    try:
        body = gemini_quota.format_status_long()
    except Exception as e:
        body = 'שגיאה בקריאת הנתונים: {0}'.format(e)
    try:
        xbmcgui.Dialog().ok('Gemini AI - ניצול היום', body)
    except Exception:
        pass


def _handle_show_gemini_usage(_params):
    """RunScript entry point so the dialog can be opened from
    anywhere, e.g. a Wizard button or a remote shortcut."""
    _show_gemini_usage()


def _gemini_menu_new(kodi_utils, gemini, gemini_pair):
    """No key set yet. Let the user pick onboarding method."""
    options = [
        '📱 התאמה מטלפון / מכשיר אחר (QR + URL)',
        '⌨️ הזנת ה-key ידנית כאן',
    ]
    try:
        choice = xbmcgui.Dialog().select(
            'Gemini AI - איך להתחבר?', options)
    except Exception:
        choice = -1
    if choice < 0:
        return
    if choice == 0:
        _gemini_pair_flow(kodi_utils, gemini, gemini_pair)
        return
    if choice == 1:
        _gemini_type_flow(kodi_utils, gemini)


class _PairWindow(xbmcgui.WindowDialog):
    """Full-screen-ish dialog showing a real scannable QR image
    (fetched from qrserver.com), the URL as fallback text, and a
    countdown. The previous implementation used DialogProgress
    which is text-only -- the QR was a URL printed as text, which
    is useless for non-technical users.

    Closes on Back/Esc (cancellation) or via close() called
    externally when the main flow detects the key arrived."""

    ACTION_PREVIOUS_MENU = 10
    ACTION_NAV_BACK = 92
    ACTION_STOP = 13

    def __init__(self, *args, **kwargs):
        # WindowDialog quirk: don't pass args to super, just init state
        self.cancelled = False
        self._countdown_lbl = None

    def setup(self, qr_url, url_lines, instructions_header):
        # WindowDialog coordinate space is 1280x720 by default.
        # Layout:
        #   y=0-720    full-screen semi-opaque dark background
        #   y=30-90    title
        #   y=120-500  QR image (380x380, centered)
        #   y=520-650  instruction text + URL fallback
        #   y=670-700  countdown + cancel hint

        # Dim background so QR is readable and Kodi behind is muted.
        bg_path = ('special://home/addons/service.subtitles.kodipovilai/'
                   'resources/lib/icons/dark_bg.png')
        bg = xbmcgui.ControlImage(0, 0, 1280, 720, bg_path,
                                  colorDiffuse='EE000000', aspectRatio=2)
        self.addControl(bg)

        # Title bar
        title = xbmcgui.ControlLabel(
            340, 30, 600, 60,
            '[B][COLOR=ffd166]Gemini AI - התאמה מטלפון[/COLOR][/B]',
            alignment=2 | 4, font='font30')
        self.addControl(title)

        # QR image (large, centered) -- this is the real fix. Kodi
        # fetches the URL on first display and caches the PNG.
        qr_size = 380
        qr_x = (1280 - qr_size) // 2
        qr = xbmcgui.ControlImage(qr_x, 110, qr_size, qr_size, qr_url,
                                  aspectRatio=2)
        self.addControl(qr)

        # Instructions + URL fallback. Bigger font (font14 vs font13)
        # because some users read this from across the room before
        # typing the URL into their phone manually. The instructions
        # header is now BOLD red to draw attention to the
        # "include the yellow port" warning -- common failure mode
        # for OEM Android scanners that truncate URLs at colons.
        # We also include Android-Chrome-specific troubleshooting
        # because modern Chrome (113+) defaults to "Always use
        # secure connections" which refuses HTTP loads to private
        # IPs -- failure is silent for the user, browser just
        # spins or shows an error page. iOS doesn't do this so
        # iPhone users typically don't hit it.
        instr = xbmcgui.ControlTextBox(120, 480, 1040, 210, font='font13')
        self.addControl(instr)
        text = '[B]סרוק את ה-QR עם המצלמה של הטלפון[/B] '
        text += '(אפליקציית מצלמה רגילה — לא צריך אפליקציה מיוחדת).\n\n'
        text += ('[B][COLOR=bf7f7f]' + instructions_header
                 + ':[/COLOR][/B]\n')
        for line in url_lines:
            text += '   • ' + line + '\n'
        text += ('\n[B][COLOR=ffd166]ה-Chrome של אנדרואיד '
                 'לא נפתח?[/COLOR][/B] כבה ב-Chrome: '
                 'Settings → Privacy → "Always use secure '
                 'connections", או נסה דפדפן אחר (Firefox/Brave/'
                 'Samsung Internet). או חזור ל-Kodi ובחר "הזנה '
                 'ידנית".\n')
        text += ('[B][COLOR=ffd166]באייפון קיבלת 400?[/COLOR][/B] '
                 'הסתכל ב-fingerprint בעמוד "ה-key נשלח" וודא '
                 'שתואם בדיוק למפתח שהעתקת מ-AI Studio. אם תואם '
                 'אבל עדיין נדחה — המפתח עצמו לא תקין; צור חדש.')
        instr.setText(text)

        # Countdown / cancel hint
        self._countdown_lbl = xbmcgui.ControlLabel(
            340, 668, 600, 30, '',
            alignment=2 | 4, font='font12')
        self.addControl(self._countdown_lbl)

    def update_countdown(self, seconds_left):
        if self._countdown_lbl is None:
            return
        try:
            mm, ss = divmod(int(max(0, seconds_left)), 60)
            self._countdown_lbl.setLabel(
                '[COLOR=b7c4cf]ממתין לקבלת ה-key... '
                '({0:02d}:{1:02d} עד פג תוקף)  •  '
                'לביטול: Back[/COLOR]'.format(mm, ss))
        except Exception:
            pass

    def onAction(self, action):
        if action.getId() in (
            self.ACTION_PREVIOUS_MENU,
            self.ACTION_NAV_BACK,
            self.ACTION_STOP,
        ):
            self.cancelled = True
            self.close()


def _gemini_pair_flow(kodi_utils, gemini, gemini_pair):
    """Spin up the local pair server, show a scannable QR image in
    a custom window, poll for the submitted key, validate."""
    import time as _time
    try:
        ps = gemini_pair.PairServer()
    except Exception as e:
        xbmcgui.Dialog().ok(
            'Kodi POV IL',
            'נכשלה הפעלת שרת התאמה: {0}\n\n'
            'אפשר לחזור לתפריט ולבחור "הזנה ידנית" במקום.'
            .format(str(e)[:80]))
        return

    # Primary URL: prefer LAN IP (works for other devices on the
    # same WiFi AND on the same device's browser via localhost
    # because the pair server binds 0.0.0.0). Fall back to
    # localhost-only when LAN detection failed (e.g. cellular).
    primary = ps.url_lan or ps.url_local
    qr_url = ('https://api.qrserver.com/v1/create-qr-code/'
              '?size=380x380&qzone=1&data=' +
              _url_quote(primary))

    # The QR encodes the full URL with port -- we've verified this
    # with a real QR decoder. The text fallback below the QR is what
    # we worry about, because some Android OEM camera apps (Samsung
    # Bixby Vision, Xiaomi MIUI scanner) display the URL truncated
    # at the colon -- the user sees "http://10.0.0.5" and types
    # that, missing the port. So we render the port in a bright
    # accent colour and add an explicit note about it.
    def _highlight_port(url):
        # url is 'http://host:port' or 'http://[v6]:port' etc.
        # Find the LAST colon (port separator). If there's no port
        # we just return the URL as-is.
        if url.count(':') < 2:
            return url
        host_part, port_part = url.rsplit(':', 1)
        return '{0}[COLOR=ffd166]:{1}[/COLOR]'.format(host_part, port_part)

    # Show EVERY detected LAN IP. On devices with multiple network
    # interfaces (Android TV with WiFi+Ethernet, laptop with VPN+WiFi)
    # the single default-route IP we used to pick can be on a
    # different subnet from the user's phone -- the phone tries to
    # reach it, fails with "address not found", and the user assumes
    # the addon is broken. Listing all candidates lets them try each.
    lan_urls = ps.url_lans or []
    if lan_urls:
        url_lines = []
        if len(lan_urls) == 1:
            url_lines.append('מטלפון אחר ב-WiFi:  '
                             + _highlight_port(lan_urls[0]))
        else:
            url_lines.append('מטלפון אחר ב-WiFi (נסה כל אחת עד שאחת '
                             'תיפתח):')
            for u in lan_urls:
                url_lines.append('     • ' + _highlight_port(u))
        url_lines.append('מאותו מכשיר:  '
                         + _highlight_port(ps.url_local))
        instructions_header = (
            'או פתח את אחת מהכתובות בדפדפן (חובה כולל החלק הצהוב — '
            'הפורט)')
    else:
        url_lines = (
            'פתח בדפדפן:  ' + _highlight_port(ps.url_local),
            '(לא זוהתה כתובת LAN -- נגיש רק מאותו מכשיר)',
        )
        instructions_header = (
            'או פתח את הכתובת בדפדפן (חובה כולל החלק הצהוב — '
            'הפורט)')

    deadline = _time.time() + 300  # 5 min cap
    window = None
    try:
        window = _PairWindow()
        window.setup(qr_url, url_lines, instructions_header)
        window.show()

        while _time.time() < deadline:
            if window.cancelled:
                break
            key = ps.received_key()
            if key:
                break
            window.update_countdown(deadline - _time.time())
            xbmc.sleep(500)
    finally:
        try:
            if window:
                window.close()
                del window
        except Exception:
            pass
        ps.shutdown()

    key = ps.received_key()
    if not key:
        return  # user cancelled or timeout
    _test_save_or_retry(kodi_utils, gemini, key, retry_cb=None)


def _gemini_type_flow(kodi_utils, gemini):
    """Original typed-input flow, but with inline validation
    before save and a retry loop on failure."""
    xbmcgui.Dialog().ok(
        'Gemini AI - איך משיגים API key',
        'כדי שתרגום ה-AI יעבוד צריך API key חינמי של Gemini:\n\n'
        '1) פתח בדפדפן (במחשב/טלפון):\n'
        '   https://aistudio.google.com/apikey\n\n'
        '2) התחבר עם חשבון Google. לחץ Create API key.\n\n'
        '3) העתק את המחרוזת והדבק במסך הבא.\n\n'
        'התוכנית החינמית מאפשרת ~500 בקשות ביום של Flash Lite.')
    while True:
        try:
            key = (xbmcgui.Dialog().input('Gemini API Key:') or '').strip()
        except Exception:
            key = ''
        if not key:
            return
        ok = _test_save_or_retry(kodi_utils, gemini, key,
                                  retry_cb='loop')
        if ok != 'retry':
            return


def _test_save_or_retry(kodi_utils, gemini, api_key, retry_cb):
    """Run gemini.test_key on the supplied key. On success: save
    to settings + show success + nudge TMDB. On failure: show the
    specific reason and (if retry_cb='loop') ask whether to try
    again, returning 'retry' if yes."""
    kodi_utils.notify('Gemini: בודק...', time_ms=2000)
    err = None
    try:
        matched = gemini.test_key(api_key)
    except gemini.InvalidKey as e:
        err = 'ה-key נדחה ע"י Gemini ({0})'.format(str(e)[:80])
    except gemini.GeminiError as e:
        err = 'בדיקה נכשלה: {0}'.format(str(e)[:80])
    except Exception as e:
        err = 'שגיאה בלתי צפויה: {0}'.format(str(e)[:80])

    if err is None:
        # Success -- save the key, show confirmation. TMDB no
        # longer needs nudging: the addon ships with a bundled
        # TMDB key, so the user is fully set up the moment Gemini
        # connects.
        saved = kodi_utils.set_setting('api_key', api_key)
        if not saved:
            # Kodi silently rejected our setSetting -- happens on
            # some Kodi/Android combos where the addon UI doesn't
            # commit to settings.xml. Surface the failure instead
            # of showing a false success dialog.
            xbmcgui.Dialog().ok(
                'Gemini AI - שמירה נכשלה',
                'ה-key אומת בהצלחה מול Gemini, אבל Kodi לא שמר '
                'אותו בקובץ ההגדרות.\n\n'
                'נסה לסגור את Kodi לחלוטין ולהפעיל מחדש, ואז לחזור '
                'לכאן ולהריץ שוב את ההתאמה.')
            return 'cancel'
        xbmcgui.Dialog().ok(
            'Gemini AI',
            '✓ החיבור הצליח. מודל: {0}\n\n'
            'מוכן לתרגם. אין צורך בהגדרות נוספות.'.format(matched))
        return 'ok'

    # Failure. DON'T save. Optionally offer retry.
    if retry_cb == 'loop':
        retry = xbmcgui.Dialog().yesno(
            'Gemini AI - בדיקה נכשלה',
            err + '\n\nלנסות שוב?',
            nolabel='ביטול', yeslabel='נסה שוב')
        return 'retry' if retry else 'cancel'
    xbmcgui.Dialog().ok('Gemini AI - בדיקה נכשלה', err)
    return 'cancel'


def _test_key_show_result(kodi_utils, gemini, api_key):
    """Re-test an existing key and show the result in a dialog.
    Does NOT change the saved key either way (this is the
    "🔍 Test connection" entry point from the existing-key
    menu)."""
    kodi_utils.notify('Gemini: בודק...', time_ms=2000)
    try:
        matched = gemini.test_key(api_key)
        xbmcgui.Dialog().ok(
            'Gemini AI',
            '✓ החיבור תקין. מודל: {0}'.format(matched))
    except gemini.InvalidKey as e:
        xbmcgui.Dialog().ok(
            'Gemini AI',
            '✗ ה-key נדחה ע"י Gemini: {0}'.format(str(e)[:120]))
    except gemini.GeminiError as e:
        xbmcgui.Dialog().ok(
            'Gemini AI',
            '✗ בדיקה נכשלה: {0}'.format(str(e)[:120]))
    except Exception as e:
        xbmcgui.Dialog().ok(
            'Gemini AI',
            '✗ שגיאה בלתי צפויה: {0}'.format(str(e)[:120]))


def _url_quote(s):
    try:
        return urllib.parse.quote(s, safe='')
    except Exception:
        return s


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
    """Explain the current TMDB state. Since v0.2.13 the addon
    ships with a bundled fallback key from the upstream
    tmdbhelper project, so gender-aware translation works out of
    the box. Connecting a personal key remains optional and
    unchanged -- a user key, if present, takes precedence over
    the bundled one."""
    try:
        from resources.lib import tmdb_helper
    except Exception as e:
        xbmcgui.Dialog().ok('Kodi POV IL', 'Internal error: {0}'.format(e))
        return

    try:
        using_bundled = tmdb_helper.using_bundled_key()
    except Exception:
        using_bundled = True

    if using_bundled:
        status_line = ('✓ TMDB עובד אוטומטית (key מובנה).\n'
                       'אין צורך לעשות כלום — תרגום AI כבר יודע '
                       'לבחור צורות זכר/נקבה לפי הדמויות.\n\n')
    else:
        status_line = ('✓ נמצא TMDB API key אישי דרך תוסף TMDB '
                       'Helper. הוא בשימוש במקום ה-key המובנה.\n\n')

    body = (
        status_line +
        'תרגום AI משתמש ב-TMDB כדי לזהות את מין כל דמות (זכר / '
        'נקבה) ולבחור צורות עברית נכונות.\n\n'
        'אופציונלי: אם תרצה להשתמש ב-key משלך (למשל אם ה-key '
        'המשותף נחסם זמנית, או אם אתה משתמש ב-TMDB Helper '
        'באופן כללי), פתח את ה-Wizard → "חיבור שירותים" → TMDB '
        'וחבר key אישי. הוא יוחל אוטומטית מאותו רגע, בלי '
        'restart, וידרוס את ה-key המובנה.'
    )
    xbmcgui.Dialog().ok('Kodi POV IL — TMDB', body)



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


def _handle_pool_share_cache(_params):
    """Button handler for "share my cached translations". Confirms with the
    user, then hands the actual work to a SEPARATE detached RunScript
    (action=pool_share_cache_run) so the settings UI is freed immediately and
    the upload runs in the background -- the user can keep using Kodi while it
    paces uploads. Safe to run repeatedly: the server dedups by the Hebrew
    result hash and each file is marked once shared."""
    try:
        from resources.lib import pool, kodi_utils
    except Exception as e:
        xbmcgui.Dialog().ok('Kodi POV IL', 'Internal error: {0}'.format(e))
        return

    # Run-lock on the global home window (visible across processes) so an
    # accidental double click can't start two background runs.
    win = xbmcgui.Window(10000)
    if win.getProperty('ai_subs.pool_migrating') == '1':
        xbmcgui.Dialog().ok('Kodi POV IL', 'שיתוף המטמון כבר פועל ברקע.')
        return

    if not pool.share_enabled():
        if not xbmcgui.Dialog().yesno(
                'Kodi POV IL',
                'שיתוף למאגר הקהילתי כבוי. להפעיל אותו עכשיו ולשתף את כל '
                'התרגומים שבמטמון?'):
            return
        try:
            kodi_utils.set_setting('pool_share', 'true')
        except Exception:
            pass

    if not xbmcgui.Dialog().yesno(
            'Kodi POV IL',
            'לשתף ברקע את כל תרגומי ה-AI ששמורים אצלך במטמון אל המאגר '
            'הקהילתי?\nאפשר להמשיך להשתמש בקודי בזמן זה. פעולה חד-פעמית; '
            'כפילויות נמנעות אוטומטית.'):
        return

    # Claim the lock BEFORE firing the worker so a second click is rejected.
    win.setProperty('ai_subs.pool_migrating', '1')
    try:
        xbmc.executebuiltin(
            'RunScript(service.subtitles.kodipovilai,'
            'action=pool_share_cache_run)')
        kodi_utils.notify('שיתוף המטמון התחיל ברקע — אפשר להמשיך כרגיל',
                          time_ms=5000)
    except Exception as e:
        win.clearProperty('ai_subs.pool_migrating')
        _safe_log('pool_share_cache dispatch failed: {0}'.format(e),
                  level='ERROR')


def _handle_pool_share_cache_run(_params):
    """Background worker for the cache migration (launched detached by
    _handle_pool_share_cache). Shows a non-modal progress banner and a final
    toast -- no modal dialog, so it never interrupts the user. Releases the
    run-lock when done."""
    win = xbmcgui.Window(10000)
    try:
        from resources.lib import pool, kodi_utils
    except Exception:
        try:
            win.clearProperty('ai_subs.pool_migrating')
        except Exception:
            pass
        return

    progress = None
    try:
        progress = xbmcgui.DialogProgressBG()
        progress.create('Kodi POV IL', 'משתף תרגומים למאגר...')
    except Exception:
        progress = None

    def report(done, total):
        if progress is None:
            return
        try:
            pct = int(done * 100 / max(1, total))
            progress.update(pct, 'Kodi POV IL',
                            'משתף תרגומים למאגר ({0}/{1})'.format(done, total))
        except Exception:
            pass

    def cancelled():
        try:
            return progress is not None and progress.isFinished()
        except Exception:
            return False

    submitted = skipped = total = 0
    try:
        submitted, skipped, total = pool.share_cache(
            progress_cb=report, should_cancel=cancelled)
    except Exception as e:
        _safe_log('pool_share_cache_run crashed: {0}'.format(e),
                  level='ERROR')
    finally:
        win.clearProperty('ai_subs.pool_migrating')
        if progress is not None:
            try:
                progress.close()
            except Exception:
                pass
        try:
            kodi_utils.notify(
                'שיתוף המטמון הסתיים — נשלחו {0}, דולגו {1} (מתוך {2})'.format(
                    submitted, skipped, total),
                time_ms=6000)
        except Exception:
            pass


def _handle_remember_source_status(_params):
    """Diagnostic for the experimental "remember picked source" capture: shows
    whether the setting is on, whether POV's sources.py is patched (the capture
    hook), how many sources were recorded, and the most recent one. Helps
    confirm capture works before the auto-pick phase is built."""
    try:
        from resources.lib import (kodi_utils, source_memory,
                                    pov_remember_source_patcher)
    except Exception as e:
        xbmcgui.Dialog().ok('Kodi POV IL', 'Internal error: {0}'.format(e))
        return
    on = kodi_utils.get_bool('remember_source', False)
    try:
        patch_status = pov_remember_source_patcher.ensure_patched()
    except Exception as e:
        patch_status = 'error: ' + str(e)[:60]
    pmap = {
        'unchanged': 'מותקן ✓', 'patched': 'הותקן עכשיו ✓',
        'no_file': 'POV לא נמצא', 'unmatched': 'לא תאם את גרסת POV ✗',
        'compile_failed': 'נכשל קומפילציה ✗', 'read_failed': 'כשל קריאה',
        'write_failed': 'כשל כתיבה',
    }
    recs = source_memory.list_all()
    lines = [
        'הגדרה "זכור מקור": ' + ('דלוקה ✓' if on else 'כבויה ✗'),
        'פאצ׳ הלכידה ב-POV: ' + pmap.get(patch_status, str(patch_status)),
        'מקורות שנשמרו: ' + str(len(recs)),
        'תיקייה: ' + (source_memory.dir_path() or '?'),
    ]
    if recs:
        k, r = recs[-1]
        lines.append('')
        lines.append('אחרון שנשמר:')
        lines.append('  שם: ' + (r.get('name') or '?')[:60])
        lines.append('  hash: ' + (r.get('hash') or '-')[:16])
        lines.append('  איכות: ' + (r.get('quality') or '-') +
                     ' | ספק: ' + (r.get('provider') or '-'))
    elif on and patch_status in ('unchanged', 'patched'):
        lines.append('')
        lines.append('הכל מוכן — נגן סרט ובחר מקור, ואז בדוק שוב כאן.')
    try:
        xbmcgui.Dialog().textviewer('זכירת מקור — אבחון', '\n'.join(lines))
    except Exception:
        xbmcgui.Dialog().ok('זכירת מקור — אבחון', '\n'.join(lines))


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

    # The source SRT's basename is the subtitle's real release name (e.g.
    # "Show.2026.1080p.WEBRip.x265-GRP") -- a far better Telegram filename than
    # the video's tokenized stream path. Pass it as the pool release; the Worker
    # falls back to the TMDB title if it doesn't look like a real release.
    try:
        info['release'] = os.path.splitext(os.path.basename(in_path))[0]
    except Exception:
        pass

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
    # Same toast-milestone-driven pattern as _handle_download.
    # DialogProgressBG may be hidden behind DarkSubs's MySubs
    # picker, but the 25/50/75 % toast notifications always layer
    # above any window so the user gets clear progress feedback.
    progress = None
    try:
        progress = xbmcgui.DialogProgressBG()
        progress.create('MoranSubs',
                        'תרגום AI מתחיל...')
    except Exception:
        progress = None

    _milestone_state = {'last': 0}

    def report(stage, total):
        try:
            from resources.lib import kodi_utils as _ku
            pct = int(stage * 100 / max(1, total))
            if progress is not None:
                try:
                    progress.update(
                        pct, 'MoranSubs',
                        _ku.localised(33001, stage, total))
                except Exception:
                    pass
            milestone = (pct // 25) * 25
            if (milestone in (25, 50, 75)
                    and milestone > _milestone_state['last']):
                _milestone_state['last'] = milestone
                try:
                    _ku.notify(
                        'AI: {0}% תורגם ({1}/{2} chunks)'.format(
                            milestone, stage, total),
                        time_ms=3500)
                except Exception:
                    pass
        except Exception:
            pass

    # Opt-in fast-first-chunk: write English to disk + touch sentinel
    # as soon as resolve() has read the source, so DarkSubs releases
    # in seconds. Hebrew swaps in via Player().setSubtitles() as each
    # chunk lands. Default OFF so the legacy "wait for full Hebrew"
    # behavior is unchanged unless the user opts in.
    whole_mode = kodi_utils.get_bool('whole_subtitle_request', False)
    fast_mode = (
        kodi_utils.get_bool('fast_first_chunk', False)
        and not whole_mode
    )

    # Pre-flight: the fast path briefly shows the SOURCE SRT to the
    # user (until the first Hebrew chunk arrives). That's acceptable
    # when the source is English -- most users can skim it for the
    # 10-15 seconds it takes Hebrew to start landing. But for
    # Spanish / Portuguese / German / French sources it's just
    # disorienting characters the user can't read. Detect the actual
    # language of the source text and downgrade non-English to the
    # slow path. NOTE: the payload above hardcodes source_lang='en'
    # because the AI prompt is robust to a misidentified language,
    # so we can't trust payload['source_lang'] here -- we have to
    # peek at the bytes.
    if fast_mode:
        try:
            from resources.lib import language_detect as _ld
            _peek_lang = _ld.detect(src_text[:8000])
            if _peek_lang and _peek_lang != 'en':
                fast_mode = False
                _safe_log(
                    'translate_file: fast mode skipped (detected '
                    'src lang = {0}, not en)'.format(_peek_lang),
                    level='INFO')
        except Exception as _e:
            # Detection failure: err on the safe side and use slow.
            fast_mode = False
            _safe_log(
                'translate_file: lang detect failed, falling '
                'back to slow: {0}'.format(_e), level='WARNING')

    if not fast_mode:
        try:
            translated_path = translate.resolve(
                link, info, progress_cb=report)
        except Exception as e:
            _safe_log('translate_file: resolve crashed: {0}'.format(e),
                      level='ERROR')
        finally:
            if progress is not None:
                try:
                    progress.close()
                except Exception:
                    pass

        if not translated_path or not os.path.isfile(translated_path):
            _safe_log('translate_file: resolve returned nothing',
                      level='WARNING')
            return

        # Copy translated content to the output path DarkSubs expects.
        try:
            with open(translated_path, 'r', encoding='utf-8',
                      errors='replace') as f:
                hebrew = f.read()
            # Belt-and-suspenders: re-apply the RTL punctuation fix
            # right before delivery. resolve() does this on cache hits
            # too, but applying it again here catches the case where
            # the cache file slipped through (e.g., a write race or a
            # file the migration hasn't reached yet).
            try:
                from resources.lib import srt as _srt
                hebrew = _srt.fix_rtl_punctuation(hebrew)
            except Exception:
                pass
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
        return

    # ---- fast_first_chunk path ------------------------------------
    # progressive_cb gets called from resolve() at three phases:
    #   first_ready  -- English source is ready; write it to out_path
    #                   and touch the sentinel so DarkSubs releases
    #                   immediately. User sees subtitles in ~3s
    #                   instead of 1-3 min.
    #   chunk_ready  -- a Hebrew chunk landed; write a versioned
    #                   .vN.srt to cache_dir and swap in via
    #                   Player().setSubtitles() so the user sees
    #                   Hebrew creep in as chunks complete.
    #   done         -- translation finished (success or failure);
    #                   we clear the active-translation Window prop.
    #                   On success the canonical cache file is
    #                   already saved by resolve() so the NEXT pick
    #                   shows [CACHE]. On failure we leave the
    #                   English on disk and the progressive .vN
    #                   files for TTL prune to clean up later --
    #                   we explicitly do NOT save a partial Hebrew
    #                   file to canonical cache.
    _ver = {'n': 0, 'last_path': None}

    def on_phase(phase, payload):
        try:
            if phase == 'first_ready':
                _tmp = out_path + '.aitmp'
                with open(_tmp, 'w', encoding='utf-8') as _f:
                    _f.write(payload['fallback_text'])
                os.replace(_tmp, out_path)
                xbmcgui.Window(10000).setProperty(
                    'ai_subs.live_translate_active', '1')
                xbmcgui.Window(10000).setProperty(
                    'ai_subs.live_translate_source', payload['source_id'])
                try:
                    open(out_path + '.ai_done', 'w').close()
                except OSError as e:
                    _safe_log('translate_file fast: sentinel write '
                              'failed: {0}'.format(e), level='WARNING')
                # Belt-and-suspenders: load the fallback ourselves
                # instead of trusting DarkSubs's post-hook code to
                # do it. Reports from users on v0.2.49 showed the
                # picker closing + our toast firing but no subtitle
                # ever appearing on screen -- consistent with
                # DarkSubs's caller either filtering on Hebrew chars
                # or relying on a code path that doesn't fire on the
                # fast return. Also force subtitle display on so a
                # disabled subtitle stream from a previous playback
                # doesn't suppress us.
                #
                # Brief polling because at this exact moment Kodi may
                # still be mid-handoff -- DarkSubs's hook just
                # returned, the player might be a few hundred ms away
                # from isPlayingVideo() flipping True. Up to 3s of
                # 250ms checks gives us a reasonable shot at landing
                # the setSubtitles call without blocking the
                # remainder of translation behind it.
                try:
                    _attempts = 0
                    while _attempts < 12:
                        if xbmc.Player().isPlayingVideo():
                            xbmc.Player().setSubtitles(out_path)
                            xbmc.Player().showSubtitles(True)
                            break
                        xbmc.sleep(250)
                        _attempts += 1
                except Exception as e:
                    _safe_log(
                        'translate_file fast first_ready '
                        'setSubtitles raised: {0}'.format(e),
                        level='DEBUG')
                kodi_utils.notify('AI: כתוביות מוכנות, מתרגם ברקע',
                                  time_ms=4000)
            elif phase == 'chunk_ready':
                # Two gates: active flag AND source_id match.
                # If the user picked a different subtitle while we're
                # translating, the new pick overwrites
                # 'ai_subs.live_translate_source'. A late chunk_ready
                # from the previous translation would otherwise swap
                # the player to its own .vN file, clobbering the new
                # pick. The source_id check pins each chunk_ready to
                # its originating translation.
                if (xbmcgui.Window(10000).getProperty(
                        'ai_subs.live_translate_active') != '1'
                        or xbmcgui.Window(10000).getProperty(
                            'ai_subs.live_translate_source')
                        != payload['source_id']):
                    return  # stale or user moved on; stop swapping
                # Alternate between two slot files instead of writing
                # a fresh v1, v2, v3... per chunk. Each setSubtitles
                # call ADDS a stream to Kodi's player list -- with N
                # chunks the user saw N Hebrew entries pile up in the
                # subtitle picker (the 10/10 screenshot). Cycling
                # 'a' and 'b' caps the streams at 2 during streaming
                # (plus _final after done) instead of N.
                slot = 'b' if _ver.get('slot', 'b') == 'a' else 'a'
                _ver['slot'] = slot
                ver_path = os.path.join(
                    kodi_utils.cache_dir(),
                    'progressive_{0}_{1}.he.srt'.format(
                        payload['source_id'], slot))
                _tmp = ver_path + '.aitmp'
                with open(_tmp, 'w', encoding='utf-8') as _f:
                    _f.write(payload['merged_text'])
                os.replace(_tmp, ver_path)
                _ver['last_path'] = ver_path
                try:
                    if xbmc.Player().isPlayingVideo():
                        xbmc.Player().setSubtitles(ver_path)
                        xbmc.Player().showSubtitles(True)
                except Exception as e:
                    _safe_log(
                        'translate_file fast: setSubtitles raised: '
                        '{0}'.format(e), level='DEBUG')
            elif phase == 'done':
                # On success: swap to the FINAL canonical Hebrew so
                # the user isn't stranded on the last .vN file (which
                # may still hold English placeholders for chunks that
                # completed AFTER our final chunk_ready setSubtitles
                # call). Copy the canonical bytes to a FRESH versioned
                # path before calling setSubtitles -- Kodi caches the
                # parsed SRT per-path, so reusing the canonical path
                # directly may no-op silently on some Kodi builds.
                # The fresh `_final.he.srt` name guarantees a reload.
                _canonical_swap_succeeded = False
                if payload.get('success'):
                    try:
                        from resources.lib import cache as _cache
                        canonical = _cache.translated_path(
                            (info.get('imdb_id') or '').strip(),
                            info.get('season') or '',
                            info.get('episode') or '',
                            'en',
                            source_id=payload['source_id'])
                        if os.path.isfile(canonical):
                            _final_path = os.path.join(
                                kodi_utils.cache_dir(),
                                'progressive_{0}_final.he.srt'.format(
                                    payload['source_id']))
                            try:
                                with open(canonical, 'rb') as _src_f:
                                    _bytes = _src_f.read()
                                _tmp_final = _final_path + '.aitmp'
                                with open(_tmp_final, 'wb') as _dst_f:
                                    _dst_f.write(_bytes)
                                os.replace(_tmp_final, _final_path)
                            except OSError as _we:
                                _safe_log(
                                    'translate_file fast done copy '
                                    'failed: {0}'.format(_we),
                                    level='WARNING')
                                _final_path = None
                            if _final_path:
                                # NOT gated on isPlayingVideo -- if
                                # the user paused mid-translation,
                                # setSubtitles is still useful for
                                # the resume. try/except is the only
                                # guard we need.
                                try:
                                    p = xbmc.Player()
                                    p.setSubtitles(_final_path)
                                    p.showSubtitles(True)
                                    # Explicit stream selection: when
                                    # the user already had a Hebrew
                                    # SRT loaded BEFORE picking
                                    # English for AI translation,
                                    # Kodi's language preference can
                                    # auto-revert to the FIRST Hebrew
                                    # stream after our setSubtitles
                                    # adds a second one. Forcing the
                                    # most-recently-added stream
                                    # (always ours) pins the active
                                    # selection to the translation we
                                    # just produced.
                                    try:
                                        _streams = p.getAvailableSubtitleStreams()
                                        if _streams:
                                            p.setSubtitleStream(
                                                len(_streams) - 1)
                                    except Exception:
                                        pass
                                    _canonical_swap_succeeded = True
                                except Exception as _se:
                                    _safe_log(
                                        'translate_file fast done '
                                        'setSubtitles raised: {0}'
                                        .format(_se), level='DEBUG')
                    except Exception as _e:
                        _safe_log(
                            'translate_file fast done canonical '
                            'swap failed: {0}'.format(_e),
                            level='DEBUG')
                # Cleanup ONLY when the canonical swap succeeded. On
                # failure / abort the user's only Hebrew lives in the
                # .vN files; deleting them would strand Kodi pointing
                # at a removed file = no subtitles for the rest of
                # playback. The 180-day TTL prune sweeps them up
                # eventually if we don't.
                if _canonical_swap_succeeded:
                    try:
                        import glob as _glob
                        # Patterns cover BOTH legacy (_v*) from
                        # pre-alternation builds AND the new _a/_b
                        # alternation slots. _final stays as the
                        # canonical stream Kodi is on.
                        _patterns = [
                            'progressive_{0}_v*.he.srt'.format(
                                payload['source_id']),
                            'progressive_{0}_a.he.srt'.format(
                                payload['source_id']),
                            'progressive_{0}_b.he.srt'.format(
                                payload['source_id']),
                        ]
                        for _pat in _patterns:
                            for _stale in _glob.glob(
                                    os.path.join(
                                        kodi_utils.cache_dir(),
                                        _pat)):
                                try:
                                    os.remove(_stale)
                                except OSError:
                                    pass
                    except Exception:
                        pass
                xbmcgui.Window(10000).clearProperty(
                    'ai_subs.live_translate_active')
                xbmcgui.Window(10000).clearProperty(
                    'ai_subs.live_translate_source')
        except Exception as _e:
            _safe_log(
                'translate_file fast on_phase({0}) raised: {1}'.format(
                    phase, _e), level='WARNING')

    translated_path = None
    try:
        try:
            translated_path = translate.resolve(
                link, info, progress_cb=report,
                progressive_cb=on_phase)
        except Exception as e:
            _safe_log(
                'translate_file fast: resolve crashed: {0}'.format(e),
                level='ERROR')

        # Sentinel safety net. Two paths land us here without a
        # touched .ai_done:
        #   (1) resolve() hit an early cache return (translate.py
        #       cache-hit branches return BEFORE emitting first_ready)
        #       -- translated_path holds the cached Hebrew file.
        #   (2) first_ready threw on the fallback SRT write (disk
        #       full, permission denied) -- translated_path may
        #       still be None or, on later resolve() success, a path.
        # Either way, if no sentinel exists yet, DarkSubs would
        # poll for 300s and then give up. We avoid that by writing
        # whatever Hebrew we have to out_path and touching the
        # sentinel now.
        sentinel_path = out_path + '.ai_done'
        if not os.path.isfile(sentinel_path):
            try:
                if (translated_path
                        and os.path.isfile(translated_path)):
                    with open(translated_path, 'r',
                              encoding='utf-8',
                              errors='replace') as _f:
                        _content = _f.read()
                    try:
                        from resources.lib import srt as _srt
                        _content = _srt.fix_rtl_punctuation(_content)
                    except Exception:
                        pass
                    _tmp_out = out_path + '.aitmp'
                    with open(_tmp_out, 'w',
                              encoding='utf-8') as _f:
                        _f.write(_content)
                    os.replace(_tmp_out, out_path)
                # Touch sentinel even if we couldn't write a usable
                # output -- letting DarkSubs's hook return quickly
                # is strictly better than the 300s hang.
                open(sentinel_path, 'w').close()
            except OSError as _e:
                _safe_log(
                    'translate_file fast: post-resolve sentinel '
                    'recovery failed: {0}'.format(_e),
                    level='ERROR')
    finally:
        if progress is not None:
            try:
                progress.close()
            except Exception:
                pass
        try:
            xbmcgui.Window(10000).clearProperty(
                'ai_subs.live_translate_active')
            xbmcgui.Window(10000).clearProperty(
                'ai_subs.live_translate_source')
        except Exception:
            pass


def _handle_darksubs_status(_params):
    """User-triggered self-test of the DarkSubs hook integration.
    Pops a dialog with a checklist explaining exactly what's
    working and what isn't. Triggered by the settings-menu entry
    that calls RunPlugin/RunScript with action=darksubs_status.
    """
    try:
        from resources.lib import darksubs_hook_diagnostics
    except Exception as e:
        xbmcgui.Dialog().ok(
            'Kodi POV IL', 'Internal error: {0}'.format(e))
        return
    darksubs_hook_diagnostics.run_full_check()


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


def _handle_open_pov_settings(_params):
    """Open POV's addon settings. Used by build home-screen buttons so
    users can quickly change Premium Expires Notification thresholds."""
    try:
        xbmc.executebuiltin('Addon.OpenSettings(plugin.video.pov)')
    except Exception as e:
        xbmcgui.Dialog().ok('Kodi POV IL', 'Internal error: {0}'.format(e))


DEBRID_NOTICE_SERVICES = (
    ('Real-Debrid', 'rd.expires'),
    ('TorBox', 'tb.expires'),
    ('Premiumize', 'pm.expires'),
    ('AllDebrid', 'ad.expires'),
)

DEBRID_NOTICE_VALUES = (
    ('בכל כניסה לקודי', '0'),
    ('יום אחד לפני סיום', '1'),
    ('3 ימים לפני סיום', '3'),
    ('7 ימים לפני סיום', '7'),
    ('14 ימים לפני סיום', '14'),
    ('30 ימים לפני סיום', '30'),
    ('60 ימים לפני סיום', '60'),
    ('90 ימים לפני סיום', '90'),
    ('180 ימים לפני סיום', '180'),
    ('365 ימים לפני סיום', '365'),
)


def _pov_addon():
    try:
        return xbmcaddon.Addon('plugin.video.pov')
    except Exception:
        return None


def _format_bytes(value):
    try:
        value = float(value)
    except Exception:
        return str(value) if value not in (None, '') else ''
    units = ('B', 'KB', 'MB', 'GB', 'TB')
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    if idx == 0:
        return '{0:d} {1}'.format(int(value), units[idx])
    return '{0:.1f} {1}'.format(value, units[idx])


def _torbox_api_get(token, path, params=None):
    import requests
    url = 'https://api.torbox.app/v1/api/{0}'.format(path)
    headers = {
        'Authorization': 'Bearer {0}'.format(token),
        'User-Agent': 'Kodi POV IL',
    }
    response = requests.get(url, headers=headers, params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and 'data' in payload:
        return payload.get('data')
    return payload


def _torbox_usage_30(stats):
    if not isinstance(stats, dict):
        return None
    bandwidth = stats.get('bandwidth') or stats.get('bandwidths')
    if isinstance(bandwidth, list):
        total = 0
        found = False
        for item in bandwidth:
            if not isinstance(item, dict):
                continue
            value = item.get('bytes_downloaded')
            if value is None:
                continue
            try:
                total += int(value)
                found = True
            except Exception:
                pass
        if found:
            return total
    general = stats.get('general')
    if isinstance(general, dict):
        for key in ('bytes_downloaded', 'total_downloaded',
                    'total_data_downloaded'):
            if key in general:
                return general.get(key)
    return None


def _handle_torbox_status(_params):
    pov = _pov_addon()
    if pov is None:
        xbmcgui.Dialog().ok('TorBox', 'plugin.video.pov not found.')
        return
    token = ''
    try:
        token = pov.getSetting('tb.token') or ''
    except Exception:
        pass
    if not token:
        xbmcgui.Dialog().ok('TorBox', 'TorBox is not connected in POV.')
        return

    try:
        account_info = _torbox_api_get(token, 'user/me') or {}
        stats = _torbox_api_get(
            token, 'user/stats',
            params={
                'general': 'true',
                'bandwidth': 'true',
                'bandwidth_grouping': 'day',
            }) or {}
    except Exception as e:
        xbmcgui.Dialog().ok('TorBox', 'TorBox status failed: {0}'.format(e))
        return

    from datetime import datetime
    expires_raw = account_info.get('premium_expires_at') or ''
    expires_label = expires_raw[:10] if expires_raw else ''
    days_remaining = ''
    if expires_raw:
        try:
            expires = datetime.strptime(expires_raw, '%Y-%m-%dT%H:%M:%SZ')
            days_remaining = str((expires - datetime.today()).days)
        except Exception:
            pass

    plans = {0: 'Free', 1: 'Essential', 2: 'Pro', 3: 'Standard'}
    plan = plans.get(account_info.get('plan'), account_info.get('plan', ''))
    usage_30 = _format_bytes(_torbox_usage_30(stats)) or 'N/A'
    downloaded = account_info.get('total_downloaded', '')

    body = [
        'Days Remaining: {0}'.format(days_remaining or 'N/A'),
        'Expires: {0}'.format(expires_label or 'N/A'),
        'Account: {0}'.format(account_info.get('email', 'N/A')),
        'Username: {0}'.format(account_info.get('customer', 'N/A')),
        'Status: {0}'.format(plan or 'N/A'),
        'Downloaded: {0}'.format(downloaded if downloaded != '' else 'N/A'),
        '\u05e9\u05d9\u05de\u05d5\u05e9 30 \u05d9\u05d5\u05dd: {0}'.format(usage_30),
    ]
    text = '\n\n'.join(body)
    dialog = xbmcgui.Dialog()
    try:
        dialog.textviewer('TORBOX', text)
    except Exception:
        dialog.ok('TORBOX', text)


def _translate_path(path):
    try:
        if xbmcvfs is not None:
            return xbmcvfs.translatePath(path)
    except Exception:
        pass
    return ''


def _notice_value_label(value):
    for label, stored in DEBRID_NOTICE_VALUES:
        if str(value) == stored:
            return label
    return '{0} ימים לפני סיום'.format(value)


def _handle_debrid_notice_settings(_params):
    """Build UI for debrid expiry notification thresholds.

    POV stores the values as rd/tb/pm/ad.expires, but some POV builds do
    not expose those settings in Addon.OpenSettings(). This dialog writes
    the same POV settings directly so the startup notifier can read them.
    """
    pov = _pov_addon()
    if pov is None:
        xbmcgui.Dialog().ok(
            'התראות מנוי',
            'לא נמצא plugin.video.pov. התקן/עדכן את הבילד ונסה שוב.')
        return

    dialog = xbmcgui.Dialog()
    service_rows = []
    for label, key in DEBRID_NOTICE_SERVICES:
        try:
            current = pov.getSetting(key) or '0'
        except Exception:
            current = '0'
        service_rows.append('{0}  -  {1}'.format(
            label, _notice_value_label(current)))

    idx = dialog.select('הגדרת התראות מנוי', service_rows)
    if idx < 0:
        return

    service_label, key = DEBRID_NOTICE_SERVICES[idx]
    options = [
        '{0} ({1})'.format(label, stored)
        for label, stored in DEBRID_NOTICE_VALUES
    ]
    value_idx = dialog.select(
        'מתי להתריע עבור {0}?'.format(service_label), options)
    if value_idx < 0:
        return

    value = DEBRID_NOTICE_VALUES[value_idx][1]
    try:
        pov.setSetting(key, value)
    except Exception as e:
        xbmcgui.Dialog().ok(
            'התראות מנוי',
            'שמירת ההגדרה נכשלה: {0}'.format(e))
        return

    if value == '0':
        msg = '{0}: התראה בכל כניסה לקודי'.format(service_label)
    else:
        msg = '{0}: התראה רק כשנותרו עד {1} ימים'.format(
            service_label, value)
    try:
        from resources.lib import kodi_utils
        kodi_utils.notify(msg, title='התראות מנוי', time_ms=5000)
    except Exception:
        dialog.notification('התראות מנוי', msg, time=5000)


def _handle_engine_test(_params):
    """Diagnostic for the built-in sources engine. Runs a real search for
    the currently-playing video and reports, per provider, how many results
    came back (or the exact exception), plus the final Hebrew candidates the
    bridge would surface. This is the tool to find out WHY the engine shows
    nothing -- import failure, a provider erroring, or genuinely no Hebrew
    subs for this title."""
    try:
        from resources.lib import kodi_utils, subs_engine_bridge
    except Exception as e:
        try:
            xbmcgui.Dialog().ok('MoranSubs', 'Internal error: {0}'.format(e))
        except Exception:
            pass
        return

    lines = []
    on = kodi_utils.get_bool('use_builtin_engine', False)
    lines.append('מתג מנוע מובנה: ' + ('דלוק ✓' if on else 'כבוי ✗'))
    if not on:
        lines.append('')
        lines.append('הדלק את "השתמש במנוע המקורות המובנה" ונסה שוב.')
        _engine_test_show(lines)
        return

    info = kodi_utils.current_video_info()
    vd = subs_engine_bridge.build_video_data(info)
    lines.append('imdb: ' + (vd.get('imdb') or '-')
                 + ' | tmdb: ' + (vd.get('tmdb') or '-'))
    lines.append('כותרת: ' + (vd.get('title') or '-')[:50])
    lines.append('סוג: ' + vd.get('media_type', '-')
                 + ' | עונה/פרק: ' + str(vd.get('season') or '-')
                 + '/' + str(vd.get('episode') or '-'))
    if not (vd.get('imdb') or vd.get('tmdb') or vd.get('title')):
        lines.append('')
        lines.append('אין מטא-דאטה מהנגן. הרץ בזמן שסרט/פרק מתנגן.')

    # Try to import the engine -- the single most likely failure point.
    engine = None
    try:
        from resources.lib.subs_engine import engine as _engine
        engine = _engine
        lines.append('')
        lines.append('טעינת המנוע: ✓')
    except Exception as e:
        lines.append('')
        lines.append('טעינת המנוע נכשלה ✗:')
        lines.append('  ' + repr(e)[:200])
        _engine_test_show(lines)
        return

    # Run each ENABLED provider directly (sequential, so we can attribute
    # results/errors precisely) and report counts.
    providers = [
        ('ktuvit', 'ktuvit'), ('wizdom', 'wizdom'),
        ('telegram', 'telegram'), ('opensubtitles', 'opensubtitles'),
        ('yify', 'yify'), ('subsource', 'subsource'),
        ('subscene', 'subscene'), ('bsplayer', 'bsplayer'),
    ]
    lines.append('')
    lines.append('תוצאות לפי ספק:')
    import time as _t
    for setting_id, modname in providers:
        if not kodi_utils.get_bool(setting_id, False):
            lines.append('  {0}: (כבוי)'.format(modname))
            continue
        try:
            mod = __import__(
                'resources.lib.subs_engine.sources.' + modname,
                fromlist=[modname])
        except Exception as e:
            lines.append('  {0}: יבוא נכשל - {1}'.format(
                modname, repr(e)[:80]))
            continue
        try:
            mod.global_var = []
        except Exception:
            pass
        t0 = _t.time()
        try:
            try:
                mod.get_subs(vd)
            except TypeError:
                mod.get_subs(vd, False)
            n = len(getattr(mod, 'global_var', []) or [])
            lines.append('  {0}: {1} תוצאות ({2:.1f}s)'.format(
                modname, n, _t.time() - t0))
        except Exception as e:
            lines.append('  {0}: שגיאה - {1}'.format(
                modname, repr(e)[:80]))

    # Final: what the bridge would surface (Hebrew only, after filtering).
    try:
        cands = subs_engine_bridge.search(info)
        lines.append('')
        lines.append('כתוביות עברית שיוצגו: {0}'.format(len(cands)))
        for c in cands[:6]:
            lines.append('  • ' + (c.get('filename') or '')[:70])
    except Exception as e:
        lines.append('')
        lines.append('bridge.search נכשל: ' + repr(e)[:150])

    _engine_test_show(lines)


def _engine_test_show(lines):
    body = '\n'.join(lines)
    try:
        xbmcgui.Dialog().textviewer('בדיקת מנוע מקורות', body)
    except Exception:
        try:
            xbmcgui.Dialog().ok('בדיקת מנוע מקורות', body)
        except Exception:
            pass


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
        elif action == 'test_connection':
            _handle_test_connection(params)
        elif action == 'connect_gemini':
            _handle_connect_gemini(params)
        elif action == 'show_gemini_usage':
            _handle_show_gemini_usage(params)
        elif action == 'open_tmdb_notice':
            _handle_open_tmdb_notice(params)
        elif action == 'clear_cache':
            _handle_clear_cache(params)
        elif action == 'pool_share_cache':
            _handle_pool_share_cache(params)
        elif action == 'pool_share_cache_run':
            _handle_pool_share_cache_run(params)
        elif action == 'remember_source_status':
            _handle_remember_source_status(params)
        elif action == 'purge_temp':
            _handle_purge_temp(params)
        elif action == 'translate_file':
            _handle_translate_file(params)
        elif action == 'bg_translate_picker':
            _handle_bg_translate_picker(params)
        elif action == 'darksubs_status':
            _handle_darksubs_status(params)
        elif action == 'open_pov_settings':
            _handle_open_pov_settings(params)
        elif action == 'debrid_notice_settings':
            _handle_debrid_notice_settings(params)
        elif action == 'torbox_status':
            _handle_torbox_status(params)
        elif action == 'engine_test':
            _handle_engine_test(params)
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
