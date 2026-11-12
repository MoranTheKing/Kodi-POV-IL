# MoranSubs by MoranTheKing - https://github.com/MoranTheKing/Kodi-POV-IL
# SPDX-License-Identifier: GPL-3.0-or-later (additional terms: LICENSE.txt)
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


STATE = {'last_file': None, 'busy': False, 'player': None, 'snap_file': None,
         'active_file': '', 'run_id': 0}
_STATE_LOCK = threading.Lock()

# 'ask' (ai_when_no_hebrew): a yes/no over the playing video that closes
# itself, as a 'no', after this many milliseconds. It never pauses playback.
_ASK_AI_CLOSE_MS = 10000

# The top overlay's status line once a subtitle is on screen, by the state of
# its timing at that moment ...
_LOADED_HEADINGS = {
    'checking': 'כתובית נטענה · בודק סנכרון',
    'confirmed': 'כתובית מסונכרנת',
    'fixed': 'כתובית סונכרנה אוטומטית',
    'unverified': 'כתובית נטענה · התזמון טרם אומת',
}
# ... and once a check that was still running at that moment has ended.
_CHECKED_HEADINGS = {
    'confirmed': 'כתובית מסונכרנת',
    'fixed': 'כתובית סונכרנה אוטומטית',
    'unverified': 'כתובית נטענה · הסנכרון לא אומת',
}
# A status line stays this long (seconds) ...
_OVERLAY_LINE_SECONDS = 5.0
# ... and "checking" stays until the check ends, this long at most.  A check
# that ends later still announces a fix with its own toast.
_SYNC_CHECK_OVERLAY_CAP = 25.0
# A status that reads empty this many times in a row is gone; one empty read
# can be a player call that failed once.
_STATUS_GONE_READS = 3


def _wait_for_sync_check(read_state, still_ours, sleep,
                         cap=_SYNC_CHECK_OVERLAY_CAP, step=0.2):
    """Wait while the timing check of the subtitle on screen is running.

    Returns (state, waited).  state is what the check ended in ('confirmed',
    'fixed' or 'unverified'); '' when the cap passed or the status is no
    longer there; None when still_ours() said the overlay does not belong to
    this run any more (another pick, another film, a stop).  waited counts
    the steps slept, not the clock.
    """
    steps = max(1, int(round(cap / step)))
    gone = 0
    for done in range(steps + 1):        # one more read after the last sleep
        if not still_ours():
            return None, done * step
        state = read_state()
        if state in _CHECKED_HEADINGS:
            return state, done * step
        if state == 'checking':
            gone = 0
        else:
            # No status: it left with the pick it belonged to (still_ours()
            # says so on the next round), or this one read failed.
            gone += 1
            if gone >= _STATUS_GONE_READS:
                return '', done * step
        if done < steps:
            sleep(step)
    return '', steps * step


def _toasts_on(kodi_utils):
    """The viewer's switch for subtitle toasts (kodi_utils.notify obeys it)."""
    try:
        return (kodi_utils.get_setting('subs_notifications', 'true')
                or 'true').strip().lower() != 'false'
    except Exception:
        return True


def ai_when_no_hebrew(kodi_utils):
    """'auto' | 'ask' | 'manual': what the automatic subtitle does when there
    is no Hebrew at all. A user's per-video choice since 0.3.74: a translation
    costs requests, and the best foreign subtitle may not fit this release's
    timing -- another link with built-in Hebrew may be the better pick."""
    try:
        v = (kodi_utils.get_setting('ai_when_no_hebrew', 'auto') or 'auto').strip().lower()
    except Exception:
        v = 'auto'
    return v if v in ('auto', 'ask', 'manual') else 'auto'


# AI rows the list shows as Hebrew -- the translation of the video's own
# foreign track, of a foreign file beside it -- are translations too
_AI_ROW_TYPES = ('embedded_ai', 'ai')


def _ask_ai_translation(google=False):
    """'ask': True only on an explicit yes. 'No' has the focus: an OK meant
    for the player must not spend requests."""
    try:
        import xbmcgui
        args = ('אין כתובית עברית',
                'לא נמצאה כתובית עברית לסרטון הזה. {0}[CR]'
                '(נסגר מעצמו תוך 10 שניות)'.format(
                    'לתרגם ב-Google Translate?' if google else 'לתרגם ב-AI?'))
        kw = {'nolabel': 'לא', 'yeslabel': 'לתרגם', 'autoclose': _ASK_AI_CLOSE_MS}
        try:
            return bool(xbmcgui.Dialog().yesno(
                *args, defaultbutton=xbmcgui.DLG_YESNO_NO_BTN, **kw))
        except (TypeError, AttributeError):
            return bool(xbmcgui.Dialog().yesno(*args, **kw))   # Kodi 19
    except Exception:
        return False


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
        # The ITEM's path, not only the playing file: a plugin that resolves
        # to a stream (Idan Plus does, live and VOD alike) leaves
        # getPlayingFile() on the plain https:// URL, and Container.PluginName
        # is empty when playback starts from a home widget, a favourite or a
        # JSON-RPC Player.Open -- so neither caught Kan, which then got the
        # search overlay and an AI-translation toast. Player.Filenameandpath
        # keeps the plugin:// path the item was started from.
        _paths = [_pf]
        for _label in ('Player.Filenameandpath', 'Player.FolderPath'):
            try:
                _paths.append(xbmc.getInfoLabel(_label) or '')
            except Exception:
                pass
        try:
            import urllib.parse as _up
            for _path in _paths:
                if _path.startswith('plugin://'):
                    _src_ids.add((_up.urlparse(_path).netloc or '').lower())
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


    try:
        _playback_file = xbmc.Player().getPlayingFile() or ''
    except Exception:
        _playback_file = ''
    with _STATE_LOCK:
        # A previous film can spend minutes in Gemini retries. Its worker must
        # not make the next film silently miss its one onAVStarted event.
        if STATE['busy'] and STATE['active_file'] == _playback_file:
            return
        STATE['run_id'] += 1
        _run_id = STATE['run_id']
        STATE['active_file'] = _playback_file
        STATE['busy'] = True
    _eng_general = None
    try:
        # Ownership starts as the selection token present when auto-on-play
        # began. Once autosub claims a candidate it advances to that exact
        # token/link/stream snapshot. Any manual pick changes the token and
        # permanently aborts this run instead of being overwritten by a later
        # fallback candidate.
        try:
            _initial_selection_token = (
                kodi_utils.get_subtitle_selection_token() or '')
        except Exception:
            _initial_selection_token = ''
        _run_owner = {'selection': None}

        def _autosub_owns_player():
            with _STATE_LOCK:
                if STATE['run_id'] != _run_id:
                    return False
            try:
                if _playback_file and (
                        xbmc.Player().getPlayingFile() or '') != _playback_file:
                    return False
            except Exception:
                return False
            owned = _run_owner.get('selection')
            try:
                if owned:
                    return bool(kodi_utils.subtitle_selection_matches(
                        owned.get('token') or '',
                        owned.get('link_hash') or '',
                        owned.get('stream_hash') or ''))
                return ((kodi_utils.get_subtitle_selection_token() or '')
                        == _initial_selection_token)
            except Exception:
                return False

        def _claim_candidate(candidate_link):
            if not _autosub_owns_player():
                return {}
            try:
                kodi_utils.set_current_subtitle(candidate_link)
                claimed = kodi_utils.current_subtitle_selection(
                    expected_link=candidate_link)
                if not kodi_utils.subtitle_selection_matches(
                        claimed.get('token') or '',
                        claimed.get('link_hash') or '',
                        claimed.get('stream_hash') or ''):
                    return {}
                _run_owner['selection'] = dict(claimed)
                return claimed
            except Exception:
                return {}

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
            if _eng_general is None or not _autosub_owns_player():
                return
            try:
                _eng_general.show_msg = msg
            except Exception:
                return
            waited = 0.0
            while waited < hold:
                if not _autosub_owns_player():
                    break
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
            if not _autosub_owns_player():
                return
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
        if not _autosub_owns_player():
            return
        if not (info.get('imdb_id') or info.get('tmdb_id')
                or info.get('title')):
            return
        # onAVStarted can fire more than once for the same file. Claim only a
        # usable metadata snapshot, atomically with the playback generation.
        with _STATE_LOCK:
            if STATE['run_id'] != _run_id:
                return
            if f and f == STATE['last_file']:
                return
            STATE['last_file'] = f

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
                if not _autosub_owns_player():
                    return
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
                # This poll has run to completion. Seal even an empty result
                # before we append an external subtitle, otherwise the parallel
                # snapshot poller can mistake our own file for an embedded one.
                subs_engine_bridge.note_playback_streams(
                    info, _streams, final=True)
            except Exception:
                pass
            if _heb_idx is not None:
                try:
                    import json as _json
                    import urllib.parse as _up
                    _elink = _up.quote(_json.dumps(
                        {'type': 'engine', 'embedded': True,
                         'stream_index': _heb_idx}, ensure_ascii=False))
                except Exception:
                    _elink = ''
                _selection = _claim_candidate(_elink) if _elink else {}
                if not _selection or not _autosub_owns_player():
                    return
                # Bare calls, deliberately: a Player-API failure raises into the
                # except below, which skips the overlay and the return, so
                # execution falls through to the real subtitle search. Routing
                # these through something that swallows its own exceptions and
                # returns a bool would announce a subtitle that is not on
                # screen and lose that recovery -- unless the caller checks the
                # bool, which is a second thing to get right for no gain.
                _pl.setSubtitleStream(_heb_idx)
                _pl.showSubtitles(True)
                try:
                    if not _autosub_owns_player():
                        return
                    kodi_utils.set_subtitle_sync_status(
                        'confirmed', source='embedded',
                        selection_token=_selection.get('token') or '',
                        link_hash=_selection.get('link_hash') or '',
                        stream_hash=_selection.get('stream_hash') or '')
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
        if not _autosub_owns_player():
            return
        # (list_candidates already queued every human Ktuvit release for the
        # background harvest; the service drainer downloads + uploads them
        # gently over time. Nothing to do here.)
        try:
            from resources.lib import subsync
            # Begin the exact-file cue read only for a genuinely uncertain
            # multi-human choice.  It runs alongside the normal first subtitle
            # download; the deep verifier reuses the same read if it is still
            # in flight.  The initial application never waits for this thread.
            # Its own guard: a prefetch problem must never cost the ranking or
            # the alternatives below.
            try:
                subsync.prefetch_autosub_reference(info, cands)
            except Exception:
                pass
            cands = subsync.rank_ready_candidates(info, cands)
            _human_fallbacks = subsync.diverse_human_alternatives(
                cands, info=info)
        except Exception:
            _human_fallbacks = []
        # Try the ready Hebrew candidates in priority order until one actually
        # downloads. If a source fails (e.g. Ktuvit rate-limited / "refused"),
        # skip the rest from that SAME source (they fail identically) and move
        # straight on to the next source -- OpenSubtitles / pool / Wizdom.
        he_list = [c for c in cands if c.get('language') == 'he']
        # 0.3.74: outside 'auto' every AI translation waits for the user --
        # one question a video, asked when the first one is reached
        _have_key = bool((kodi_utils.get_setting('api_key', '') or '').strip())
        _mode = (kodi_utils.get_setting('translation_mode', 'ai') or 'ai')
        _ai_ok = _mode != 'none'
        _when = ai_when_no_hebrew(kodi_utils)
        _ai_offered = False      # an AI translation the user can pick instead
        _ai_answer = []          # the user's answer, once asked

        def _is_ai_row(row):
            try:
                return (translate._decode_link(row.get('link') or '')
                        or {}).get('type') in _AI_ROW_TYPES
            except Exception:
                return False

        def _ai_allowed():
            if _when == 'auto':
                return True
            if _when == 'manual' or not (_have_key and _ai_ok):
                return False
            if not _ai_answer:
                if _eng_general is not None:
                    try:
                        _eng_general.show_msg = (
                            '[COLOR lightblue]אין כתובית עברית — לתרגם?[/COLOR]')
                    except Exception:
                        pass
                _ai_answer.append(_ask_ai_translation(google=_mode == 'google'))
                if (_ai_answer[0] and _eng_general is not None
                        and _autosub_owns_player()):
                    try:
                        _eng_general.show_msg = (
                            '[COLOR lightblue]מתרגם ב-AI[/COLOR]')
                    except Exception:
                        pass
            return _ai_answer[0]

        if _when != 'auto':
            # every real Hebrew subtitle is tried before any translation
            he_list = ([c for c in he_list if not _is_ai_row(c)]
                       + [c for c in he_list if _is_ai_row(c)])
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
            if pl.get('type') == 'embedded_sync':
                # "עברית מסונכרנת למובנה" is a CHOICE, never automatic. It
                # delivers a different translation from the one inside the file,
                # which is the whole reason it is offered as a row rather than
                # applied for you -- and resolving it costs a 45s alignment that
                # reads the debrid token, where auto-on-play is supposed to be
                # immediate.
                #
                # It is reachable from here, which is not obvious: the fast path
                # above only matches a stream labelled exactly 'heb', while
                # embedded_candidates() normalises 'Hebrew'/'HE'/'iw' too. So a
                # file whose Hebrew track is spelled any other way falls through
                # to this loop, and the row sorts to the FRONT of he_list --
                # first pick, by default, on an ordinary install.
                continue
            if _when != 'auto' and pl.get('type') in _AI_ROW_TYPES:
                _ai_offered = True
                if not _autosub_owns_player():
                    return
                _allowed = _ai_allowed()
                if not _autosub_owns_player():
                    return
                if not _allowed:
                    continue
            is_embedded = (pl.get('type') == 'engine' and pl.get('embedded'))
            if not _autosub_owns_player():
                return
            try:
                # Associate foreground/background SubSync state with this
                # candidate before resolve() can enqueue its service job.
                selection = _claim_candidate(link2)
                if not selection:
                    return
                path = translate.resolve(
                    link2, info, selection=selection,
                    fallback_links=[link for link in _human_fallbacks
                                    if link != link2])
            except Exception:
                path = None
            if not _autosub_owns_player():
                return
            if is_embedded:
                # resolve() switched the embedded stream and returns None -- that
                # IS success for an embedded pick.
                status = kodi_utils.get_subtitle_sync_status(link2)
                if (status.get('state') == 'confirmed'
                        and kodi_utils.subtitle_selection_matches(
                            selection.get('token') or '',
                            selection.get('link_hash') or '',
                            selection.get('stream_hash') or '')):
                    applied = True
                    chosen_link = link2
                    chosen_name = 'תרגום מובנה בעברית'
                    break
            if (path and kodi_utils.subtitle_selection_matches(
                    selection.get('token') or '',
                    selection.get('link_hash') or '',
                    selection.get('stream_hash') or '')):
                try:
                    if not kodi_utils.apply_subtitle_file(
                            path, selection=selection):
                        if not _autosub_owns_player():
                            return
                        continue
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
        # 0.3.74: outside 'auto' the user's answer decides (asked once)
        if _when == 'auto':
            _auto_ai = (_have_key and _ai_ok) or kodi_utils.get_bool(
                'engine_force_translate', False)
        else:
            _auto_ai = False
            _eng_ai = False
            if not applied:
                for c in cands:
                    try:
                        p2 = translate._decode_link(c.get('link') or '')
                    except Exception:
                        p2 = None
                    if p2 and p2.get('type') == 'engine_ai':
                        _eng_ai = True
                        break
            if _eng_ai:
                _ai_offered = True
                if not _autosub_owns_player():
                    return
                _auto_ai = _ai_allowed()
                if not _autosub_owns_player():
                    return
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
                        ai_link = c.get('link') or ''
                        selection = _claim_candidate(ai_link)
                        if not selection:
                            return
                        path = translate.resolve(
                            ai_link, info, selection=selection)
                    except Exception:
                        path = None
                    if not _autosub_owns_player():
                        return
                    if (path and kodi_utils.subtitle_selection_matches(
                            selection.get('token') or '',
                            selection.get('link_hash') or '',
                            selection.get('stream_hash') or '')):
                        try:
                            if not kodi_utils.apply_subtitle_file(
                                    path, selection=selection):
                                if not _autosub_owns_player():
                                    return
                                continue
                            applied = True
                            chosen_link = c.get('link')
                        except Exception:
                            pass
                    break

        if not applied:
            if not _autosub_owns_player():
                return
            try:
                kodi_utils.set_current_subtitle('')
            except Exception:
                pass
            if (_ai_offered and _when != 'auto' and _have_key and _ai_ok
                    and _ai_answer[:1] != [True]):
                # left to the user: say where the translation is
                _final_overlay('[COLOR red]לא נמצאה כתובית עברית[/COLOR]\n'
                               '[COLOR lightblue]תרגום AI זמין ברשימת הכתוביות[/COLOR]',
                               hold=5.0)
            else:
                _final_overlay('[COLOR red]לא נמצאה כתובית עברית[/COLOR]', hold=4.0)
            return
        # The winning candidate was already claimed before resolve. Rewriting
        # it here would let an old autosub run steal ownership back from a
        # manual pick that happened during delivery.
        if not _autosub_owns_player():
            return
        # A pooled AI translation, or the one it just made: its gender
        # proofread in a job of its own (proofread_later picks what qualifies;
        # `selection` is the applied candidate's claim).
        try:
            translate.proofread_later(chosen_link, selection)
        except Exception:
            pass
        # DarkSubs-style final status in the top overlay (full subtitle name,
        # + cache note when it came straight from the Cached_subs folder),
        # instead of a success toast.
        # This first delivery can be provisional while exact-cut timing is
        # checked in the background. Never call it "ready" or "synced" before
        # the current selection actually has that verdict; the later worker
        # may still replace it with a proven alternative.
        try:
            _sync_state = (kodi_utils.get_subtitle_sync_status(
                chosen_link) or {}).get('state')
        except Exception:
            _sync_state = ''
        def _status_line(heading):
            line = '[COLOR lightblue]' + heading
            if chosen_name:
                line += '\n' + chosen_name
            if chosen_from_cache:
                line += '\n(נטענה מהקאש)'
            return line + '[/COLOR]'

        if _sync_state != 'checking' or _eng_general is None:
            _final_overlay(_status_line(
                _LOADED_HEADINGS.get(_sync_state, 'כתובית נטענה')))
            return
        # The check is still running, and a subtitle made for another cut can
        # be seconds off until its fix arrives.  The line used to leave after
        # five seconds whatever the check was doing (measured: gone 5.5 s
        # after the picture started, the fix at 9.5 s), so a viewer looking at
        # an unsynced subtitle had nothing saying that anything was still
        # happening.  It now stays until the check ends, then says how.
        _checking_line = _status_line(_LOADED_HEADINGS['checking'])
        if not _autosub_owns_player():
            return          # a stale run never writes into the next overlay
        try:
            _eng_general.show_msg = _checking_line
        except Exception:
            return

        def _check_state():
            try:
                return (kodi_utils.get_subtitle_sync_status(chosen_link)
                        or {}).get('state') or ''
            except Exception:
                return ''

        def _overlay_ours():
            try:
                return bool(_autosub_owns_player()
                            and xbmc.Player().isPlayingVideo())
            except Exception:
                return False

        _end_state, _waited = _wait_for_sync_check(
            _check_state, _overlay_ours,
            lambda seconds: xbmc.sleep(int(seconds * 1000)))
        try:
            kodi_utils.log('autosub overlay: timing check %s after %.1fs' % (
                ('ended ' + _end_state) if _end_state
                else 'left to another pick or a stop' if _end_state is None
                else 'not followed further',
                _waited))
        except Exception:
            pass
        if _end_state == 'fixed' and _toasts_on(kodi_utils):
            # SubSync's own "synced automatically" toast is on screen now;
            # the same words in the overlay beside it would be noise.
            return
        if _end_state:
            _final_overlay(_status_line(_CHECKED_HEADINGS[_end_state]))
        elif _end_state == '' and _waited < _OVERLAY_LINE_SECONDS:
            # no result to show: the line still gets its usual time
            _final_overlay(_checking_line,
                           hold=_OVERLAY_LINE_SECONDS - _waited)
    except Exception as e:
        try:
            kodi_utils.log('autosub_on_play failed: {0}'.format(e),
                           level='WARNING')
        except Exception:
            pass
    finally:
        with _STATE_LOCK:
            _still_active = STATE['run_id'] == _run_id
            if _still_active:
                STATE['busy'] = False
                STATE['active_file'] = ''
        if _still_active:
            try:
                translate.set_quiet(False)
            except Exception:
                pass
        # A stale film must never close the next film's overlay.
        if _still_active and _eng_general is not None:
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
        subs_engine_bridge.note_playback_streams(info, streams, final=True)
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
