# Auto-on-play Hebrew subtitle machinery (Phase C), extracted VERBATIM from
# service.py so the STANDALONE (repo-channel) service can run the exact same
# auto-search / auto-apply flow as the full build -- this is what makes
# MoranSubs function as a PRIMARY subtitle addon on a clean Kodi (like
# DarkSubs), with no build components present. service.py keeps thin
# delegators under the historical names, so the full build's behavior is
# byte-for-byte the same logic, from one source of truth.
#
# Everything here is fully guarded: any failure degrades to "no autosub this
# time" and never affects playback.

import threading
import time

try:
    import xbmc
except ImportError:
    xbmc = None


STATE = {'last_file': None, 'busy': False, 'player': None, 'snap_file': None}


def autosub_on_play():
    """Phase C auto-on-play: when the built-in engine is on, search and apply
    the best Hebrew subtitle automatically (replacing DarkSubs's autosub).
    Runs in its own thread so it never blocks Kodi's playback callback."""
    try:
        from resources.lib import kodi_utils, translate, subs_engine_bridge
    except Exception:
        return
    try:
        if not kodi_utils.get_bool('use_builtin_engine', False):
            return
        if not kodi_utils.get_bool('engine_autosub', True):
            return
        if not kodi_utils.hebrew_subtitle_wanted():
            # Correct to skip here -- this is the AUTOMATIC on-play search, and
            # fetching Hebrew for someone who asked for English would be
            # presumptuous. But it used to return in total silence, which is
            # how "auto-subs stopped working" became unexplainable: nothing in
            # the log said why. Say it once per playback.
            kodi_utils.log(
                'autosub: skipped -- Kodi\'s subtitle language preference does '
                'not name Hebrew. Add Hebrew under Settings > Player > '
                'Language > "languages to download subtitles for" to get '
                'automatic Hebrew subs.', level='INFO')
            return
    except Exception:
        return

    # Honor the one-shot 'skip_autosub' marker on Window(10000): set when the
    # item being played is already in the target language, so our auto-on-play
    # search must NOT run for it -- same guard as default.py::_handle_search. We
    # do NOT clear the prop here (the search-path guard clears it / it expires at
    # 90s), so both paths still see it fresh.
    try:
        import xbmcgui
        _sa = xbmcgui.Window(10000).getProperty('skip_autosub')
        if _sa and (time.time() - float(_sa)) < 90:
            return
    except Exception:
        pass

    # LIVE / IPTV playback (Idan Plus, PVR channels, live plugins) must never
    # trigger the Hebrew auto-search: there is no release to match and the
    # search overlay just gets in the way of channel zapping. Three guards:
    # a PVR/streaming-protocol path, a PVR channel name, and a per-addon
    # exclusion list (comma-separated plugin ids, configurable) matched
    # against both the playing plugin:// path and the window the playback
    # was started from. A fourth catches what these three miss -- an IPTV plugin
    # that resolves to a plain http:// URL -- by testing for zero duration once
    # the player has settled; it runs below, but BEFORE anything is drawn.
    # All guarded: on any doubt, autosub runs.
    try:
        _pf = (xbmc.Player().getPlayingFile() or '')
    except Exception:
        _pf = ''
    if _pf.startswith(('pvr://', 'udp://', 'rtp://', 'rtsp://')):
        return
    try:
        if (xbmc.getInfoLabel('VideoPlayer.ChannelName') or '').strip():
            return
    except Exception:
        pass
    try:
        # An EMPTY value is a deliberate user choice ("no exclusions") and is
        # respected; the default only applies when the setting can't be read.
        _raw = kodi_utils.get_setting('autosub_excluded_addons',
                                      'plugin.video.idanplus')
    except Exception:
        _raw = 'plugin.video.idanplus'
    _excluded = {x.strip().lower() for x in _raw.split(',') if x.strip()}
    if _excluded:
        _src_ids = set()
        try:
            if _pf.startswith('plugin://'):
                import urllib.parse as _up
                _src_ids.add((_up.urlparse(_pf).netloc or '').lower())
        except Exception:
            pass
        try:
            _src_ids.add((xbmc.getInfoLabel('Container.PluginName')
                          or '').strip().lower())
        except Exception:
            pass
        if _src_ids & _excluded:
            return

    # LIVE / IPTV before the busy flag is taken. This wait can run for
    # 13 seconds, and STATE['busy'] is a single global: holding it here
    # would make a live channel block autosub for whatever the user plays
    # NEXT -- onAVStarted fires once, so that item would lose autosub
    # silently and permanently. Review caught this. Nothing below needs
    # the flag, so the check runs outside it.
    # Zero duration == live. This used to run further down, AFTER the overlay
    # was already on screen, so an Idan Plus channel flashed
    # "MoranSubs — מחפש כתוביות עברית" and then silently gave up: the exact
    # field report of "the search was cancelled but the message still pops up".
    # The three guards above miss it because an IPTV plugin resolves to a plain
    # http:// URL, so the playing file is no longer a plugin:// path.
    #
    # Costs nothing on normal playback: getTotalTime() is already non-zero by
    # onAVStarted for a VOD file, so the loop exits on its first test and the
    # overlay still appears immediately.
    #
    # The grace period is 13s, not the 5s this loop used to have, and that is
    # deliberate. Sitting where it did -- below the overlay and below the
    # up-to-8s metadata wait -- a slow VOD effectively had ~13s of wall clock
    # to expose a duration before being judged live. Moving the check up
    # without widening it would have cut that to 5s and started silently
    # SKIPPING autosub on slow sources (debrid, 4K remux) to fix a cosmetic
    # flash: a bad trade, and one review caught.
    try:
        _pl_live = xbmc.Player()
        _dur_waited = 0.0
        while (_pl_live.isPlayingVideo()
               and _pl_live.getTotalTime() <= 0 and _dur_waited < 13.0):
            xbmc.sleep(250)
            _dur_waited += 0.25
        if _pl_live.isPlayingVideo() and _pl_live.getTotalTime() <= 0:
            return  # no duration after the grace period -> live stream
    except Exception:
        pass


    if STATE['busy']:
        return
    STATE['busy'] = True
    _eng_general = None
    try:
        # Show the DarkSubs-style top overlay (with live per-source counts the
        # engine fills into general.show_msg as it searches), so the user sees
        # the same "loading subtitles" screen from the start of the search --
        # not after the metadata wait below.
        try:
            subs_engine_bridge.ensure_engine_settings()
            from resources.lib.subs_engine import general as _eng_general
            _eng_general.break_all = False
            _eng_general.with_dp = False
            _eng_general.show_msg = 'MoranSubs — מחפש כתוביות עברית'
            threading.Thread(target=_eng_general.show_results,
                             args=(False,), daemon=True).start()
        except Exception:
            _eng_general = None

        # While auto-on-play drives, success/progress toasts from resolve() are
        # suppressed -- the top overlay shows status instead (exactly like
        # DarkSubs, which never toasts during autosub).
        try:
            translate.set_quiet(True)
        except Exception:
            pass

        def _final_overlay(msg, hold=5.0):
            """Show a final status line in the top overlay for ~hold seconds
            (DarkSubs shows its 'כתובית מוכנה' / 'אין כתוביות' line for ~5s
            before the overlay closes). No-op if the overlay isn't up."""
            if _eng_general is None:
                return
            try:
                _eng_general.show_msg = msg
            except Exception:
                return
            waited = 0.0
            while waited < hold:
                try:
                    if not xbmc.Player().isPlayingVideo():
                        break
                except Exception:
                    break
                xbmc.sleep(200)
                waited += 0.2

        # Right after onAVStarted the player metadata (imdb/title) often
        # isn't populated yet -- poll briefly until it is (mirrors how
        # DarkSubs waits for the video before searching).
        info = {}
        for _ in range(40):  # up to ~8s
            info = kodi_utils.current_video_info()
            have_id = (info.get('imdb_id') or info.get('tmdb_id')
                       or info.get('title'))
            # Also wait for the release name to settle: on an auto-advance to
            # the next episode the metadata transitions a moment after play,
            # and the sync-% is computed from the release name -- searching
            # (and caching) before it's ready yields 0% matches. Once we have
            # both an id/title AND a release name, proceed.
            try:
                have_release = subs_engine_bridge._release_ready(info)
            except Exception:
                have_release = True
            if have_id and have_release:
                break
            try:
                if not xbmc.Player().isPlayingVideo():
                    return
            except Exception:
                pass
            xbmc.sleep(200)

        f = info.get('filepath') or info.get('title') or ''
        # onAVStarted can fire more than once for the same file; act once.
        if f and f == STATE['last_file']:
            return
        STATE['last_file'] = f
        if not (info.get('imdb_id') or info.get('tmdb_id')
                or info.get('title')):
            return

        # Deferred live-stream check: a genuinely live stream (IPTV channel
        # played over plain http, so the protocol/plugin guards above can't
        # see it) reports NO total duration; VOD always has one. Duration can
        # lag a moment at start even for VOD, so give it a bounded grace
        # period before concluding "live". Fail-open: any doubt -> autosub.
        # Embedded Hebrew is the best, perfectly-synced subtitle -- apply it
        # FIRST whenever the file has one. The demuxer often hasn't exposed the
        # embedded streams yet this early after play, so poll while the stream
        # list is still empty (then check once for a 'heb' track). Matches how
        # DarkSubs waits for the stream list before deciding.
        try:
            _pl = xbmc.Player()
            _heb_idx = None
            _streams = []
            for _ in range(80):  # up to ~8s, but only while streams aren't listed yet
                try:
                    _streams = _pl.getAvailableSubtitleStreams() or []
                except Exception:
                    _streams = []
                if _streams:
                    _heb_idx = next(
                        (i for i, n in enumerate(_streams)
                         if (n or '').strip().lower() == 'heb'), None)
                    break  # streams listed -- decided (heb or not)
                if not _pl.isPlayingVideo():
                    break
                xbmc.sleep(100)
            # Snapshot these PLAY-START streams as the embedded baseline. This is
            # the only moment we're sure no external sub (incl. one WE load
            # below) is present, so the picker can later tell embedded from
            # external and never mistake an AI translation for "embedded Hebrew".
            try:
                subs_engine_bridge.note_playback_streams(info, _streams)
            except Exception:
                pass
            if _heb_idx is not None:
                # Through select_embedded rather than setSubtitleStream direct:
                # it does the same two calls, and it is the one place that also
                # starts the background RTL repair for an embedded HEBREW track
                # (Kodi renders those with an LTR base direction, which throws
                # the closing punctuation to the wrong end of every line). This
                # auto-on-play selection is how most users meet an embedded
                # Hebrew track at all, so leaving it on the direct call would
                # have fixed the defect everywhere except where it happens.
                subs_engine_bridge.select_embedded(_heb_idx, lang='he')
                try:
                    import json as _json
                    import urllib.parse as _up
                    _elink = _up.quote(_json.dumps(
                        {'type': 'engine', 'embedded': True,
                         'stream_index': _heb_idx}, ensure_ascii=False))
                    kodi_utils.set_current_subtitle(_elink)
                except Exception:
                    pass
                _final_overlay('[COLOR lightblue]הופעל תרגום מובנה בעברית[/COLOR]')
                return  # embedded Hebrew applied -- it's the best, we're done
        except Exception:
            pass

        # Non-modal search (the overlay above is the progress). list_candidates
        # returns everything in priority order; the first 'he' row is the best
        # Hebrew (embedded > human > pool > MT).
        cands = translate.list_candidates(info, modal_progress=False)
        # (list_candidates already queued every human Ktuvit release for the
        # background harvest; the service drainer downloads + uploads them
        # gently over time. Nothing to do here.)
        # Try the ready Hebrew candidates in priority order until one actually
        # downloads. If a source fails (e.g. Ktuvit rate-limited / "refused"),
        # skip the rest from that SAME source (they fail identically) and move
        # straight on to the next source -- OpenSubtitles / pool / Wizdom.
        he_list = [c for c in cands if c.get('language') == 'he']
        applied = False
        chosen_link = None
        chosen_name = ''
        chosen_from_cache = False
        failed_sources = set()
        for c in he_list[:12]:
            link2 = c.get('link') or ''
            try:
                pl = translate._decode_link(link2) or {}
            except Exception:
                pl = {}
            src = pl.get('source')
            if src and src in failed_sources:
                continue  # this source already failed -- don't waste time on it
            is_embedded = (pl.get('type') == 'engine' and pl.get('embedded'))
            try:
                path = translate.resolve(link2, info)
            except Exception:
                path = None
            if is_embedded:
                # resolve() switched the embedded stream and returns None -- that
                # IS success for an embedded pick.
                applied = True
                chosen_link = link2
                chosen_name = 'תרגום מובנה בעברית'
                break
            if path:
                try:
                    p = xbmc.Player()
                    if p.isPlayingVideo():
                        p.setSubtitles(path)
                        p.showSubtitles(True)
                    applied = True
                    chosen_link = link2
                    # Full subtitle name + cache note for the overlay status,
                    # exactly like DarkSubs's "כתובית מוכנה\n{name}".
                    chosen_name = (pl.get('filename')
                                   or c.get('filename') or '').strip()
                    try:
                        if pl.get('type') == 'engine':
                            chosen_from_cache = bool(
                                subs_engine_bridge.LAST_DOWNLOAD_FROM_CACHE)
                    except Exception:
                        chosen_from_cache = False
                    break
                except Exception:
                    pass
            if src:
                failed_sources.add(src)

        # No Hebrew anywhere -- not embedded, not human, not the community pool,
        # not machine-translated. ONLY in that case, auto-translate the best
        # foreign sub (the highest-match English, which list_candidates already
        # orders first) to Hebrew on play, exactly like DarkSubs's auto_translate.
        # Gated so we NEVER spend quota when a ready Hebrew sub exists:
        #   * a Gemini API key must be connected (nothing to translate with
        #     otherwise), and
        #   * the user hasn't opted out of AI (translation_mode != 'none').
        # (The legacy engine_force_translate toggle still forces it if set.)
        _have_key = bool((kodi_utils.get_setting('api_key', '') or '').strip())
        _ai_ok = (kodi_utils.get_setting('translation_mode', 'ai')
                  or 'ai') != 'none'
        _auto_ai = (_have_key and _ai_ok) or kodi_utils.get_bool(
            'engine_force_translate', False)
        if not applied and _auto_ai:
            for c in cands:
                try:
                    p2 = translate._decode_link(c.get('link') or '')
                except Exception:
                    p2 = None
                if p2 and p2.get('type') == 'engine_ai':
                    if _eng_general is not None:
                        try:
                            _eng_general.show_msg = (
                                '[COLOR lightblue]אין עברית — מתרגם ב-AI[/COLOR]')
                        except Exception:
                            pass
                    try:
                        path = translate.resolve(c.get('link'), info)
                    except Exception:
                        path = None
                    if path:
                        try:
                            pp = xbmc.Player()
                            if pp.isPlayingVideo():
                                pp.setSubtitles(path)
                                pp.showSubtitles(True)
                            applied = True
                            chosen_link = c.get('link')
                        except Exception:
                            pass
                    break

        if not applied:
            _final_overlay('[COLOR red]לא נמצאה כתובית עברית[/COLOR]', hold=4.0)
            return
        # Remember it as the current sub so the picker marks it '» נוכחית'.
        try:
            kodi_utils.set_current_subtitle(chosen_link or '')
        except Exception:
            pass
        # DarkSubs-style final status in the top overlay (full subtitle name,
        # + cache note when it came straight from the Cached_subs folder),
        # instead of a success toast.
        _status_msg = '[COLOR lightblue]כתובית מוכנה'
        if chosen_name:
            _status_msg += '\n' + chosen_name
        if chosen_from_cache:
            _status_msg += '\n(נטענה מהקאש)'
        _status_msg += '[/COLOR]'
        _final_overlay(_status_msg)
    except Exception as e:
        try:
            kodi_utils.log('autosub_on_play failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass
    finally:
        STATE['busy'] = False
        try:
            translate.set_quiet(False)
        except Exception:
            pass
        # Close the overlay (show_results exits on 'END').
        if _eng_general is not None:
            try:
                _eng_general.show_msg = 'END'
            except Exception:
                pass


def snapshot_on_play():
    """Record the file's subtitle streams at play start. NOTHING ELSE.

    This is the only producer of the play-start snapshot that
    subs_engine_bridge.embedded_candidates() needs, and the picker shows NO
    embedded row without it -- neither "[מובנה] XX" nor
    "תרגום מובנה → עברית (AI)". It used to live inside autosub_on_play, behind
    that function's engine_autosub / hebrew_subtitle_wanted / skip_autosub /
    live-stream guards, so a user who turned OFF "auto-search and apply Hebrew
    on play" silently lost every embedded row as well -- two features that have
    nothing to do with each other (field report: a user disabled autosub to stop
    a duplicate extraction and the embedded AI rows disappeared with it).

    Snapshotting is cheap and side-effect-free for playback: it polls Kodi's own
    stream list and stores it on a window property. It must therefore run
    whenever the engine is on, independent of the autosub setting.

    Kept SEPARATE from autosub_on_play rather than hoisted out of it, so the
    autosub path is untouched. note_playback_streams() is idempotent per file,
    so when both run whichever arrives first wins and the other returns.
    """
    if xbmc is None:
        return
    try:
        from resources.lib import kodi_utils, subs_engine_bridge
        if not kodi_utils.get_bool('use_builtin_engine', False):
            return          # embedded_candidates() is inert anyway
    except Exception:
        return
    try:
        player = xbmc.Player()
        # Kodi can fire onAVStarted more than once for one file, and each firing
        # would otherwise spawn another poller that may live for 30s. Skip when
        # this file ALREADY has a real snapshot -- deliberately keyed on the
        # snapshot rather than on "have we run before", so a previous attempt
        # that captured nothing (demuxer still catching up) is retried instead
        # of being locked out. Same rule as note_playback_streams: only a
        # non-empty capture counts as done.
        if subs_engine_bridge.have_playback_snapshot():
            return
        # Live/PVR has no embedded subtitle picking to do; skip the poll.
        try:
            if (player.getPlayingFile() or '').startswith(
                    ('pvr://', 'udp://', 'rtp://', 'rtsp://')):
                return
        except Exception:
            pass
        # The demuxer often has not exposed the streams this early, so poll
        # while the list is still empty. Longer than autosub_on_play's own 8s
        # wait ON PURPOSE: with autosub off this is the ONLY writer, and it
        # starts at t=0 with no preamble, whereas autosub does not begin its
        # poll until after its metadata and live-duration waits. Giving up at 8s
        # would leave a slow-to-enumerate file (4K remux over debrid) with no
        # embedded rows at all. The poll itself is a local call and exits the
        # moment streams appear or playback stops, so the ceiling costs nothing
        # on a normal file.
        streams = []
        for _ in range(300):           # up to ~30s
            try:
                streams = player.getAvailableSubtitleStreams() or []
            except Exception:
                streams = []
            if streams:
                break
            if not player.isPlayingVideo():
                return
            xbmc.sleep(100)
        # Pass the real info dict: note_playback_streams reads ids off it to
        # flag a built-in Hebrew track for the community pool, and its
        # embedded-report diagnostic reads several fields. Falling back to {}
        # (never None) keeps the .get() calls in there safe.
        try:
            info = kodi_utils.current_video_info() or {}
        except Exception:
            info = {}
        subs_engine_bridge.note_playback_streams(info, streams)
    except Exception as e:
        try:
            from resources.lib import kodi_utils
            kodi_utils.log('snapshot_on_play failed: {0}'.format(e),
                           level='DEBUG')
        except Exception:
            pass


if xbmc is not None:
    class AutoSubPlayer(xbmc.Player):
        def onAVStarted(self):
            # Always snapshot; auto-search only when the user asked for it.
            try:
                threading.Thread(target=snapshot_on_play, daemon=True).start()
            except Exception:
                pass
            try:
                from resources.lib import kodi_utils
                if not kodi_utils.get_bool('engine_autosub', True):
                    return
            except Exception:
                pass
            try:
                threading.Thread(target=autosub_on_play, daemon=True).start()
            except Exception:
                pass


def start_if_enabled():
    """Register the play-start Player listener whenever the built-in engine is
    on. The listener always snapshots the embedded streams (so the picker can
    offer embedded + embedded-AI rows) and additionally runs the Hebrew
    auto-search when `engine_autosub` is on -- that setting gates the SEARCH,
    not the snapshot. The service's existing prune loop keeps the process alive,
    so the Player callbacks fire; we just hold a reference."""
    if xbmc is None:
        return
    try:
        from resources.lib import kodi_utils
        if not kodi_utils.get_bool('use_builtin_engine', False):
            return
        autosub = kodi_utils.get_bool('engine_autosub', True)
    except Exception:
        return
    try:
        STATE['player'] = AutoSubPlayer()  # keep a ref alive
        # If a video is already playing when the service starts, kick once.
        try:
            if xbmc.Player().isPlayingVideo():
                threading.Thread(target=snapshot_on_play, daemon=True).start()
                if autosub:
                    threading.Thread(target=autosub_on_play,
                                     daemon=True).start()
        except Exception:
            pass
    except Exception:
        pass


def prewarm_engine():
    """If the built-in sources engine is enabled, import it (and ensure its
    settings) in a background thread so the first subtitle search is warm.
    Fully guarded; a failure here never affects anything."""
    try:
        from resources.lib import kodi_utils
        if not kodi_utils.get_bool('use_builtin_engine', False):
            return
    except Exception:
        return

    def _work():
        try:
            from resources.lib import subs_engine_bridge
            subs_engine_bridge.ensure_engine_settings()
            from resources.lib.subs_engine import engine  # noqa: F401
        except Exception:
            pass

    try:
        threading.Thread(target=_work, daemon=True).start()
    except Exception:
        pass
