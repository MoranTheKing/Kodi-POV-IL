# SubSync Phase S2 -- delivery-time verify & auto-retime orchestration.
#
# Called by translate.resolve() right before a Hebrew subtitle (engine human /
# community pool) is handed to Kodi. If the sub's release does NOT match the
# playing release, we try to verify/fix its timing against a timing ORACLE --
# a subtitle whose release DOES match the playing release, in ANY language
# (the aligner only reads timestamps). Verdicts are cached per
# (subtitle-content, playing-release) so each pair is computed once per
# device; S3 will share them globally via the pool /sync registry.
#
# Fail-open by design: ANY problem (no oracle, gate failed, import error)
# delivers the original file exactly as today. Never raises.

import os
import re
import json
import time
import hashlib

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None

try:
    from resources.lib import release_match
except Exception:
    release_match = None

try:
    from resources.lib import sync_align
except Exception:
    sync_align = None


_VERDICT_FILE = ('special://profile/addon_data/service.subtitles.kodipovilai/'
                 'subsync_verdicts.json')
_MAX_VERDICTS = 400
# Bump to invalidate ALL previously stored verdicts after an engine change.
# v6: offset refinement (median of deltas) supersedes the coarse 500ms bin
# -- fixes stored at bin precision (field: +1500ms should have been ~+1000)
# recompute to the refined value.
# v5: probe cues are rebased to the playback timeline (first-cluster PTS
# origin) -- UNKNOWNs judged against un-rebased references (field: +313s
# "implausible offset" on a synced sub) deserve a recompute.
# v4: the probe now unions ALL embedded tracks + bitrate-aware windows --
# UNKNOWNs stored while it sampled one sparse track (9 cues on a BDRip in the
# field) deserve a recompute.
# v13: small-shift (<1.5s) acceptance now leans on OVERLAP (>=0.85) + magnitude
# rather than the coarse vote (source-oracle min_vote lowered 0.55->0.50). Field:
# four correct small offsets ran vote 54-64% / overlap 87-90% / tight 40-45% --
# the -677ms/54% one still failed the vote floor. Recompute.
# v12: the small-shift (<1.5s) tight floor now drops to ~0.35 when BOTH vote
# (>=0.60) and overlap (>=0.85) corroborate -- different-subber subs cap ~40%
# tight even at the correct offset (field: S01E02 -436ms/64%/87%/40% was right
# but rejected at 42%). Large spurious offsets stay strict. Recompute.
# v11: the tight floor for SMALL (<1.5s) shifts is relaxed to ~0.42 when the
# overlap corroborates (>=0.85). Real subs from a different subber segment lines
# differently, capping tight ~45% even at the correct offset (field: The Flash
# Pilot ~1s-early sub, 45% tight against every oracle) -- previously rejected.
# Recompute so those small real offsets now apply.
# v10: pick_oracle now prefers an ENGLISH oracle within the same tier (the
# Hebrew candidate is translated from English, so an English reference segments
# like it and aligns tightly; a Dutch oracle gave only 45% tight on the real
# -926ms offset). Verdicts that failed the gate against a foreign oracle must
# recompute so the English oracle can be chosen.
# v9: same-source oracle alignment is pinned to identity scale + a relaxed vote
# floor (cross-language segmentation depressed a real -926ms match to 61% vote,
# and a full scale search produced a +560s FPS-fit). Verdicts that FAILED the
# gate under v8 must recompute so a genuine small offset now reaches the tight
# gate and applies.
# v8: pick_oracle now accepts SAME-SOURCE-class oracles (a BluRay sub anchors a
# BluRay REMUX even with a different group/codec). Files that found NO oracle
# under v7 -- and were left unfixed or judged only against the noisy file probe
# (field: The Flash Pilot, ~1s early, no oracle) -- must recompute so the newly
# eligible oracle can supply the real offset.
# v7: the tight-agreement gate is now REQUIRED for every non-trivial shift and
# scaled by its magnitude (a multi-second jump needs ~0.85-0.9 agreement, not
# the old flat 0.65 that only ran for sparse refs). Field: a 31-cue file-probe
# union voted -20.3s at 68% tight and de-synced an already-good sub -- any
# FIXABLE stored under the looser gate must recompute so those spurious large
# shifts are dropped.
# v3: force recompute so UNKNOWNs stored before the adaptive second pass
# get their pass-2 chance. v2: the pre-dedupe voting could store a spurious
# FIXABLE (field case:
# offset=-350s) -- those cached verdicts must never be re-applied.
# v14: validate HTTP ranges and resume interrupted probes within their budgets.
# v15: local-consistency guard + conservatively validated piecewise maps.  Old
# global FIXABLE verdicts must recompute because a dominant region could have
# hidden a differently-cut second half.
# v16: bounded adaptive scale proposals recover continuous drift when irregular
# inserted/deleted cues defeat index quantiles. Every normal acceptance gate is
# still required, so older UNKNOWNs must recompute while older fixes are rechecked.
# v17: every proposed non-identity clock must remain locally continuous; soft
# multi-track probes cannot make sub-second editorial nudges, and a newer
# subtitle selection invalidates any older background hot-swap.
# v18: actual-media cut signatures scope local verdicts; embedded tracks are
# judged independently and sparse modern tracks are never unioned into a fake
# majority, preventing shifted language tracks from moving an exact one.
# v19: repeated short edit pads can be corrected only after five disjoint
# holdouts reproduce the map and a distinct full-span text/PGS timing family
# validates it. Old UNKNOWNs must recompute; exact-cut keys prevent reuse.
_VERDICT_VERSION = 19
# Trusted tiers need no verification at delivery time (same release / same
# group+source are de-facto synced; S3+ may still cross-check them cheaply).
_STATUS_TRUSTED = 'TRUSTED'
_STATUS_NO_ORACLE = 'NO_ORACLE'
# A community sync record with a shift larger than this is only APPLIED blindly
# when a human confirmed it. A large AUTO (machine-computed) offset can be a
# poisoned share (field: a spurious -20.3s file-probe verdict reached the
# registry before the local gate was tightened); rather than jump an
# already-good sub by many seconds on one unverified auto vote, we skip the
# record and let the locally-gated deep-verify decide. Small auto offsets stay
# on the fast pool path.
_COMMUNITY_AUTO_MAX_OFFSET_MS = 6000
# Same-source oracles (BluRay/DVD) are the SAME disc master -> framerate is
# identical, so their alignment is pinned to identity scale: a full scale search
# on a cross-language oracle finds spurious FPS fits (field: scale=0.999/+560s).
# Cross-language cue segmentation also depresses the coarse vote (field: a real
# -926ms offset scored only 61%), so the vote floor is relaxed for this path --
# the graduated tight gate (sync_align) stays the real correctness guard.
_ORACLE_SOURCE_SCALES = (1.0,)
# A majority (>50%) of cues must still agree on the offset, but not more: a
# different-subber sub segments its lines differently, so the correct small
# offset ran as low as 54% vote in the field (S01E04 -677ms) -- the real
# correctness guard is the graduated tight/overlap gate, not the coarse vote.
_ORACLE_SOURCE_MIN_VOTE = 0.50


def _selection_snapshot():
    try:
        return kodi_utils.current_subtitle_selection() or {}
    except Exception:
        return {}


def _publish_selection_status(state, source='local', selection=None):
    """Update the current pick's tiny UI record; never performs network I/O."""
    try:
        if kodi_utils is not None:
            expected = selection or {}
            if not all(expected.get(k) for k in (
                    'token', 'link_hash', 'stream_hash')):
                return False
            return bool(kodi_utils.set_subtitle_sync_status(
                state, source=source,
                selection_token=expected.get('token') or '',
                link_hash=expected.get('link_hash') or '',
                stream_hash=expected.get('stream_hash') or ''))
    except Exception:
        return False
    return False


def _log(msg, level='INFO'):
    try:
        kodi_utils.log('subsync: ' + msg, level=level)
    except Exception:
        pass


def enabled():
    try:
        return (kodi_utils.get_setting('subsync_verify', 'true') or
                'true').strip().lower() != 'false'
    except Exception:
        return True


def playing_release(info):
    """The playing stream's release name (same priority order the picker's %
    uses), or '' when unknown/synthetic -- a synthesized player filename must
    never anchor verification."""
    try:
        ref = ((info.get('picked_release') or info.get('tagline')
                or info.get('label')
                or os.path.basename(info.get('filepath') or '')
                or info.get('title') or '')).strip()
        if not ref or release_match is None:
            return ''
        if release_match.is_synthetic(ref):
            return ''
        return ref
    except Exception:
        return ''


# ---- verdict cache ----------------------------------------------------------

def _verdict_path():
    try:
        import xbmcvfs
        return xbmcvfs.translatePath(_VERDICT_FILE)
    except Exception:
        return ''


def _cache_key(sub_text, playing, cut_signature=''):
    h = hashlib.sha1(sub_text.encode('utf-8', 'replace')).hexdigest()[:16]
    sig = (cut_signature or '').strip().lower()
    if re.fullmatch(r'cut1:[0-9a-f]{32}', sig):
        return h + '|' + sig
    rel = release_match.normalize(playing) if release_match else playing.lower()
    return h + '|' + rel


def _load_verdicts():
    path = _verdict_path()
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _store_verdict(key, verdict):
    path = _verdict_path()
    if not path:
        return
    try:
        data = _load_verdicts()
        data[key] = {'ts': time.time(), 'v': _VERDICT_VERSION,
                     'status': verdict.get('status'),
                     'scale': verdict.get('scale', 1.0),
                     'offset_ms': verdict.get('offset_ms', 0.0),
                     'mode': verdict.get('mode', 'global'),
                     'segments': verdict.get('segments') or [],
                     'diag': verdict.get('diag', '')}
        if len(data) > _MAX_VERDICTS:
            data = dict(sorted(data.items(),
                               key=lambda kv: kv[1].get('ts', 0),
                               reverse=True)[:_MAX_VERDICTS])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        _log('verdict store failed: %r' % e, level='WARNING')


# ---- oracle acquisition -----------------------------------------------------

def _decode_link(link):
    try:
        import urllib.parse
        return json.loads(urllib.parse.unquote(link))
    except Exception:
        return None


def _oracle_candidates(info, include_he=False):
    """Foreign-language engine candidates as [{'release', 'payload'}] -- the
    bridge's 24h result cache makes this cheap right after the picker/autosub
    built the list. Never raises.

    Hebrew is excluded by DEFAULT and that is not an oversight: this list's
    original job is to be a timing ORACLE for correcting Hebrew, so Hebrew is
    the thing being corrected and cannot also be the reference.

    `include_he=True` is for the one caller that wants the opposite -- re-timing
    an external HEBREW subtitle onto the embedded track's timeline, where
    Hebrew is the payload rather than the reference. Without the flag that
    caller silently gets zero candidates and falls through to English, which
    would deliver an ENGLISH subtitle to someone who asked for Hebrew.
    """
    out = []
    try:
        from resources.lib import subs_engine_bridge as bridge
        if not bridge.enabled():
            return out
        for c in bridge.search(info, modal_progress=False):
            if (c.get('language') or '') == 'he' and not include_he:
                continue
            # The kind filter has to widen with the language filter: Hebrew
            # results are tagged 'human_he'/'mt_he', so leaving this at
            # ('other', None) would drop every Hebrew row again one line after
            # letting it through.
            _kind = c.get('_engine_kind')
            _ok_kinds = ((None, 'other', 'human_he', 'mt_he') if include_he
                         else (None, 'other'))
            if _kind not in _ok_kinds:
                continue
            pl = _decode_link(c.get('link') or '')
            if not pl or pl.get('type') != 'engine' or pl.get('embedded'):
                continue
            rel = (pl.get('filename') or '').strip()
            if rel:
                # Keep the language so the picker can prefer an oracle that
                # SEGMENTS like the Hebrew candidate (which is almost always
                # translated from English). A same-release oracle in a different
                # language splits lines differently -> its cue onsets drift from
                # the Hebrew's, tanking the tight agreement (field: a Dutch
                # ROVERS oracle gave only 45% tight on a real -926ms offset).
                out.append({'release': rel, 'payload': pl,
                            'language': (c.get('language') or '').strip().lower()})
    except Exception as e:
        _log('oracle candidate scan failed: %r' % e, level='WARNING')
    return out


def _download_oracle(payload):
    try:
        from resources.lib import subs_engine_bridge as bridge
        path = bridge.download(payload)
        if path and os.path.isfile(path):
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
    except Exception as e:
        _log('oracle download failed: %r' % e, level='WARNING')
    return ''


# ---- file probe (S4): the playing file's own embedded track as reference ----

_PROBE_CACHE_FILE = ('special://profile/addon_data/'
                     'service.subtitles.kodipovilai/subsync_probe_cache.json')
_MAX_PROBE_ENTRIES = 60
# Bump when the probe's cue semantics change; older entries re-probe.
# v2: cues are rebased to the playback timeline (first-cluster origin) and
# union all non-forced tracks -- v1 entries may carry an un-rebased origin.
# v3: remote Matroska uses the debrid-safe per-subtitle Cues index reader
# (head + Cues + origin, a handful of ranged reads) instead of being skipped.
# v4: the remote reader unions every non-forced subtitle track, including
# bitmap tracks, matching the local-file probe and covering PGS-only releases.
# v5: cache entries are scoped to the hashed playback transport/content rather
# than a release label and preserve every track separately plus a cut signature.
_PROBE_CACHE_VERSION = 5
_NEGATIVE_PROBE_TTL_S = 6 * 60 * 60


def _probe_enabled():
    try:
        return (kodi_utils.get_setting('subsync_probe', 'true') or
                'true').strip().lower() != 'false'
    except Exception:
        return True


def _playing_url(info):
    """Return a local playing file suitable for automatic probing.

    Never open extra HTTP media connections alongside Kodi playback: range
    probes can exhaust a host's request/connection allowance and interrupt
    the player itself. Cached references are consulted before this gate.
    Subtitle-provider oracle downloads do not use this media path.
    """
    url = _media_url(info)
    low = (url or '').lower().split('|')[0]
    if not low:
        return ''
    if low.startswith(('http://', 'https://')):
        _log('remote media probing skipped to protect playback')
        return ''
    if os.path.isfile(url):
        return url
    return ''


def _remote_playing_url(info):
    """Direct HTTP(S) Matroska URL, stripped of Kodi's `|Header=...` suffix.

    HLS/manifests are not byte-addressable Matroska files and never enter the
    cue-index probe.  This is intentionally separate from _playing_url(), whose
    contract remains local-only for the heavier mkv_probe/audio paths.
    """
    url = _media_url(info)
    clean = (url or '').split('|')[0]
    low = clean.lower()
    if (low.startswith(('http://', 'https://'))
            and '.m3u8' not in low and 'manifest' not in low):
        return clean
    return ''


def _current_stream_url():
    """The stream Kodi is playing now, without Kodi's header suffix."""
    try:
        import xbmc
        return ((xbmc.Player().getPlayingFile() or '').split('|')[0].strip())
    except Exception:
        return ''


def _media_url(info):
    """Media URL for this operation, pinned by a queued job when available.

    A service job may outlive the film that created it.  Using Kodi's current
    URL in that case would compare the old subtitle with the next film and could
    poison both local and community timing memory.  Queued jobs inject their
    captured URL through the private key below; foreground calls still use the
    live player and then the metadata fallback.
    """
    try:
        pinned = (info.get('_subsync_stream_url') or '').split('|')[0].strip()
    except Exception:
        pinned = ''
    if pinned:
        return pinned
    current = _current_stream_url()
    if current:
        return current
    try:
        return (info.get('filepath') or '').strip()
    except Exception:
        return ''


def _transport_cache_key(info):
    """Opaque session/file key for the probe cache; never stores a URL token."""
    try:
        value = _media_url(info)
        if not value:
            return ''
        clean = value.split('|')[0].strip()
        # Local paths can be reused after replacement.  Size+mtime keep their
        # transport entry separate until the content signature is recomputed.
        if os.path.isfile(clean):
            st = os.stat(clean)
            clean = '%s|%d|%d' % (
                os.path.abspath(clean), int(st.st_size),
                int(getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9))))
        digest = hashlib.sha256(clean.encode('utf-8', 'replace')).hexdigest()
        return 'media:' + digest[:32]
    except Exception:
        return ''


def _local_cut_signature(info):
    """Cheap three-sample content identity for a local playing file."""
    path = _playing_url(info)
    if not path:
        return ''
    try:
        from resources.lib import embedded_extract
        return embedded_extract.media_cut_signature(
            path, allow_http=False,
            log=lambda m: _log('cut-id: ' + m)) or ''
    except Exception as e:
        _log('local cut-id failed: %r' % e, level='DEBUG')
        return ''


def _remote_probe_ready(max_wait_s=8.0, expected_url=''):
    """Wait in the background until playback is stable enough for tiny reads."""
    try:
        import xbmc
        player = xbmc.Player()
        deadline = time.monotonic() + max(0.0, float(max_wait_s))
        while time.monotonic() < deadline:
            if not player.isPlayingVideo():
                return False
            if expected_url and _current_stream_url() != expected_url:
                return False
            try:
                played = float(player.getTime() or 0.0)
            except Exception:
                played = 0.0
            busy = (xbmc.getCondVisibility('Player.Caching')
                    or xbmc.getCondVisibility('Player.Paused'))
            if played >= 6.0 and not busy:
                return True
            xbmc.sleep(400)
        return False
    except Exception:
        return False


def _starts_to_cues(starts):
    points = sorted({int(x) for x in (starts or []) if int(x) >= 0})
    cues = []
    for i, start in enumerate(points):
        nxt = points[i + 1] if i + 1 < len(points) else start + 3000
        cues.append({'start': start,
                     'end': start + max(600, min(3000, nxt - start - 100))})
    return cues


def _remote_reference_bundle(url):
    """Per-track video reference + cut id via compact Matroska reads only.

    This deliberately does not extract subtitle text or scan media clusters.
    The underlying reader reuses one keep-alive connection, paces requests,
    validates byte ranges and trips on provider pressure.  Failure is a silent
    miss; the selected subtitle remains untouched.
    """
    if not url or not _remote_probe_ready(expected_url=url):
        return {}
    started = time.monotonic()

    def abort():
        if time.monotonic() - started > 35.0:
            return True
        try:
            import xbmc
            return (not xbmc.Player().isPlayingVideo()
                    or _current_stream_url() != url)
        except Exception:
            return False

    try:
        from resources.lib import embedded_extract
        reader = getattr(embedded_extract, 'cue_reference_profile', None)
        if reader is not None:
            raw = reader(url, allow_http=True, abort_cb=abort,
                         log=lambda m: _log('remote-cues: ' + m)) or {}
        else:  # older in-memory module after a quick update
            starts = embedded_extract.cue_reference_times(
                url, allow_http=True, abort_cb=abort,
                log=lambda m: _log('remote-cues: ' + m))
            raw = {'starts': starts or [], 'track_starts': [],
                   'legacy_single_track': True}
    except Exception as e:
        _log('remote cue-index probe failed: %r' % e, level='WARNING')
        return {}
    cues = _starts_to_cues(raw.get('starts') or [])
    profiles = []
    for item in raw.get('track_starts') or []:
        tc = _starts_to_cues(item.get('starts') or [])
        if tc:
            profiles.append({'track': item.get('track') or {}, 'cues': tc})
    if cues:
        _log('remote-cues: %d union cues / %d independent track(s) ready'
             % (len(cues), len(profiles)))
    return {'cues': cues, 'track_cues': profiles,
            'tracks': raw.get('tracks') or [],
            'cut_signature': raw.get('cut_signature') or '',
            'bytes': raw.get('bytes') or 0,
            'requests': raw.get('requests') or 0,
            'legacy_single_track': bool(raw.get('legacy_single_track')),
            'track': {'source': 'matroska-cues-index'}}


def _remote_cue_reference(url):
    """Compatibility wrapper returning the legacy union cue list."""
    bundle = _remote_reference_bundle(url)
    cues = bundle.get('cues') or []
    return cues if len(cues) >= MIN_REMOTE_CUES else None


MIN_REMOTE_CUES = 8


def _probe_cache_path():
    try:
        import xbmcvfs
        return xbmcvfs.translatePath(_PROBE_CACHE_FILE)
    except Exception:
        return ''


_AUDIO_PROMPT = (
    'This is a short audio clip from a TV episode or movie. Identify every '
    'segment of human SPEECH (dialogue in any language, including dubbed '
    'speech). Return ONLY a JSON array, no other text, of objects with start '
    'and end in SECONDS relative to the beginning of THIS clip, e.g. '
    '[{"s": 1.24, "e": 3.41}, {"s": 5.03, "e": 7.75}]. TIMING PRECISION IS '
    'CRITICAL: "s" must be the exact moment the first word begins (two '
    'decimal places). Split segments at pauses longer than 0.7 seconds. '
    'Ignore music, effects and silence.')
# Second-pass sample positions (between the first pass points) used when a
# promising-but-unconfirmed peak needs more reference cues.
_AUDIO_PASS2_POSITIONS = (0.36, 0.62)
# Audio-VAD boundaries are softer than subtitle cues -> relaxed vote/overlap,
# BUT hard discipline everywhere else: identity scale only (a sparse VAD
# reference cannot support scale estimation -- every extra scale candidate
# multiplies the spurious-peak chance) and a narrow offset window. The field
# incident: 10 sparse cues x 15 scales x +/-10min window "found" a bogus
# offset=-350s that shifted the subs out of sight.
_AUDIO_MIN_VOTE = 0.55
_AUDIO_MIN_OVERLAP = 0.65
_AUDIO_SCALES = (1.0,)
_AUDIO_MAX_OFFSET_MS = 180000
# A container-probe reference with fewer than this many cues is treated as
# sparse (identity scale only) -- high-bitrate 2160p files can't be sampled
# densely within the byte budget.
_SPARSE_PROBE_CUES = 40


def _audio_probe_reference(info, playing, second_pass=False):
    """LAST-RESORT reference (S5): speech intervals from the playing file's
    own AUDIO, timestamped by Gemini (user's existing key). Only reached when
    there is no matching sub in any DB AND no embedded subtitle track. AAC
    audio only (Gemini accepts it as-is after ADTS wrap; AC3/DTS cannot be
    sent or decoded on device). Cached per release. None when unavailable.
    second_pass=True samples ADDITIONAL positions and MERGES with the cached
    cues (used once when a promising peak failed the tight check for lack of
    reference points); it marks the cache so it never repeats."""
    try:
        if (kodi_utils.get_setting('subsync_audio', 'true') or
                'true').strip().lower() == 'false':
            return None
        api_key = (kodi_utils.get_setting('api_key', '') or '').strip()
        if not api_key:
            return None
        rel_key = ((release_match.normalize(playing) if release_match
                    else (playing or '').lower()) + '|audio')
        cpath = _probe_cache_path()
        data = {}
        prior = []
        if cpath and os.path.isfile(cpath):
            try:
                with open(cpath, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
            ent = data.get(rel_key)
            if ent is not None and ent.get('pv') != _PROBE_CACHE_VERSION:
                ent = None   # older engine (un-rebased origin) -- redo
            if ent is not None:
                prior = ent.get('cues') or []
                if not second_pass:
                    _log('audio: cache %s for %r'
                         % ('hit (%d cues)' % len(prior) if prior
                            else 'negative', rel_key))
                    return prior or None
                if ent.get('pass2'):
                    return prior or None   # already extended once -- done
        url = _playing_url(info)
        if not url:
            return prior or None
        try:
            from resources.lib import mkv_probe
            from resources.lib import gemini
        except Exception:
            return None
        segs = mkv_probe.audio_segments(
            url,
            positions=(_AUDIO_PASS2_POSITIONS if second_pass
                       else (0.22, 0.50, 0.78)),
            log=lambda m: _log('audio: ' + m))
        cues = []
        api_failed = False
        if segs:
            model = (kodi_utils.get_setting('model', '') or
                     'gemini-3.5-flash-lite')
            for seg in segs[:3]:
                try:
                    txt = gemini.generate_media(
                        api_key, model, _AUDIO_PROMPT, seg['data'],
                        'audio/aac', timeout=60)
                except Exception as e:
                    # Quota/key/network failure is TRANSIENT: stop burning
                    # further calls now, and do NOT cache a negative below --
                    # tomorrow's refreshed quota should get a fresh chance.
                    _log('audio: gemini failed: %r' % e, level='WARNING')
                    api_failed = True
                    break
                m = re.search(r'\[.*\]', txt or '', re.DOTALL)
                if not m:
                    continue
                try:
                    items = json.loads(m.group(0))
                except Exception:
                    continue
                for it in items or []:
                    try:
                        s = float(it.get('s')) * 1000.0 + seg['start_ms']
                        e = float(it.get('e')) * 1000.0 + seg['start_ms']
                        if e > s:
                            cues.append({'start': int(s), 'end': int(e)})
                    except Exception:
                        continue
            _log('audio: %d speech cues from %d segment(s)'
                 % (len(cues), len(segs)))
        if api_failed and not cues:
            return None   # transient -- no negative cache, retry next time
        if second_pass:
            # MERGE with the first-pass cues (dedupe by start time).
            seen = set(c['start'] for c in prior)
            merged = list(prior)
            for c in cues:
                if c['start'] not in seen:
                    seen.add(c['start'])
                    merged.append(c)
            merged.sort(key=lambda c: c['start'])
            cues = merged
        try:
            if cpath:
                data[rel_key] = {'ts': time.time(), 'cues': cues,
                                 'pv': _PROBE_CACHE_VERSION}
                if second_pass:
                    data[rel_key]['pass2'] = True
                if len(data) > _MAX_PROBE_ENTRIES:
                    data = dict(sorted(data.items(),
                                       key=lambda kv: kv[1].get('ts', 0),
                                       reverse=True)[:_MAX_PROBE_ENTRIES])
                os.makedirs(os.path.dirname(cpath), exist_ok=True)
                tmp = cpath + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(data, f)
                os.replace(tmp, cpath)
        except Exception:
            pass
        return cues or None
    except Exception as e:
        _log('audio reference failed: %r' % e, level='WARNING')
        return None


def _read_probe_cache():
    path = _probe_cache_path()
    if not path or not os.path.isfile(path):
        return path, {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return path, (json.load(f) or {})
    except Exception:
        return path, {}


def _write_probe_cache(cache_key, bundle):
    """Atomically merge one media profile into the bounded probe cache."""
    if not cache_key or not isinstance(bundle, dict):
        return False
    cpath, data = _read_probe_cache()
    if not cpath:
        return False
    try:
        data[cache_key] = bundle
        if len(data) > _MAX_PROBE_ENTRIES:
            data = dict(sorted(data.items(),
                               key=lambda kv: kv[1].get('ts', 0),
                               reverse=True)[:_MAX_PROBE_ENTRIES])
        os.makedirs(os.path.dirname(cpath), exist_ok=True)
        tmp = cpath + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        os.replace(tmp, cpath)
        return True
    except Exception as e:
        _log('probe cache store failed: %r' % e, level='WARNING')
        return False


def _known_cut_signature(info, playing=''):
    """Known exact-media id without any network request.

    Local files are sampled directly (192 KiB total).  A remote id is returned
    only after this exact hashed stream URL was already probed during the
    current/previous delivery; a same release name can never borrow it.
    """
    local = _local_cut_signature(info)
    if local:
        return local
    cache_key = _transport_cache_key(info)
    if not cache_key:
        return ''
    _path, data = _read_probe_cache()
    ent = data.get(cache_key)
    if not isinstance(ent, dict) or ent.get('pv') != _PROBE_CACHE_VERSION:
        return ''
    sig = (ent.get('cut_signature') or '').strip().lower()
    return sig if re.fullmatch(r'cut1:[0-9a-f]{32}', sig) else ''


def _learn_cut_signature(info):
    """Learn a remote media id with only three 64 KiB content samples.

    This is for a subtitle already trusted by release name: there is no reason
    to parse Matroska Cues or inspect timing merely to namespace a future manual
    correction.  It runs in the service process, after playback is stable, and
    aborts if Kodi changes streams or the provider applies pressure.
    """
    known = _known_cut_signature(info)
    if known:
        return known
    if not _probe_enabled():
        return ''
    url = _remote_playing_url(info)
    if not url or not _remote_probe_ready(expected_url=url):
        return ''
    started = time.monotonic()

    def abort():
        if time.monotonic() - started > 15.0:
            return True
        try:
            import xbmc
            return (not xbmc.Player().isPlayingVideo()
                    or _current_stream_url() != url)
        except Exception:
            return True

    try:
        from resources.lib import embedded_extract
        sig = embedded_extract.media_cut_signature(
            url, allow_http=True, abort_cb=abort,
            log=lambda m: _log('cut-id: ' + m)) or ''
    except Exception as e:
        _log('remote cut-id failed: %r' % e, level='DEBUG')
        return ''
    sig = sig.strip().lower()
    if not re.fullmatch(r'cut1:[0-9a-f]{32}', sig):
        return ''
    cache_key = _transport_cache_key(info)
    _path, data = _read_probe_cache()
    old = data.get(cache_key) if cache_key else None
    if not isinstance(old, dict) or old.get('pv') != _PROBE_CACHE_VERSION:
        old = {}
    bundle = dict(old)
    bundle.update({'ts': time.time(), 'pv': _PROBE_CACHE_VERSION,
                   'cut_signature': sig})
    bundle.setdefault('cues', [])
    bundle.setdefault('track_cues', [])
    bundle.setdefault('tracks', [])
    bundle.setdefault('timing_attempted', False)
    _write_probe_cache(cache_key, bundle)
    return sig


def _probe_reference_bundle(info, playing):
    """Actual playing-file reference, with independent track timelines.

    The disk cache is keyed by an opaque transport identity, never merely the
    release label.  Its content signature then scopes timing verdicts and human
    corrections to the exact media bytes.
    """
    if not _probe_enabled():
        return {}
    cache_key = _transport_cache_key(info)
    cpath, data = _read_probe_cache()
    ent = data.get(cache_key) if cache_key else None
    if ent is not None and ent.get('pv') != _PROBE_CACHE_VERSION:
        ent = None
    if ent:
        has_ref = isinstance(ent.get('cues'), list) and bool(ent.get('cues'))
        has_sig = bool(ent.get('cut_signature'))
        if has_ref:
            _log('probe: media cache hit (%d cues, %d track(s), cut=%s)'
                 % (len(ent.get('cues') or []),
                    len(ent.get('track_cues') or []),
                    'yes' if has_sig else 'no'))
            return ent
    if (ent is not None and not ent.get('cues')
            and ent.get('timing_attempted', True)):
        # No timeline may mean "no embedded subtitles" or transient provider
        # pressure.  Keep the useful cut id, but retry the timing read after the
        # normal negative TTL instead of letting signature success freeze a cue
        # miss forever.
        if time.time() - float(ent.get('ts') or 0) < _NEGATIVE_PROBE_TTL_S:
            return ent if ent.get('cut_signature') else {}

    local_url = _playing_url(info)
    if local_url:
        try:
            from resources.lib import mkv_probe
            res = mkv_probe.subtitle_reference(
                local_url, log=lambda m: _log('probe: ' + m)) or {}
        except Exception:
            res = {}
        res['cut_signature'] = _local_cut_signature(info)
    else:
        remote_url = _remote_playing_url(info)
        if not remote_url:
            _log('probe: no probeable playing url')
            return {}
        res = _remote_reference_bundle(remote_url)

    bundle = {
        'ts': time.time(), 'pv': _PROBE_CACHE_VERSION,
        'cues': res.get('cues') or [],
        'track_cues': res.get('track_cues') or [],
        'tracks': res.get('tracks') or [],
        'track': res.get('track') or {},
        'cut_signature': (res.get('cut_signature') or
                          ((ent or {}).get('cut_signature') or '')),
        'bytes': int(res.get('bytes') or 0),
        'legacy_single_track': bool(res.get('legacy_single_track')),
        'timing_attempted': True,
    }
    if cpath and cache_key:
        _write_probe_cache(cache_key, bundle)
    return bundle


def _probe_reference_cues(info, playing):
    """Compatibility wrapper returning the all-track union cue list."""
    return _probe_reference_bundle(info, playing).get('cues') or None


def _cached_reference_bundle(info):
    """Return a proven media-scoped reference without I/O beyond one JSON read."""
    cache_key = _transport_cache_key(info)
    if not cache_key:
        return {}
    _path, data = _read_probe_cache()
    ent = data.get(cache_key)
    if (not isinstance(ent, dict)
            or ent.get('pv') != _PROBE_CACHE_VERSION
            or not ent.get('cues')):
        return {}
    return ent


def _ready_candidate_text(info, candidate):
    """Canonical subtitle text already on disk; never starts a download."""
    try:
        payload = _decode_link(candidate.get('link') or '') or {}
        kind = payload.get('type')
        path = ''
        if kind == 'passthrough':
            path = payload.get('path') or ''
        elif kind == 'engine' and not payload.get('embedded'):
            from resources.lib import subs_engine_bridge as bridge
            path = bridge.cached_source(payload) or ''
        elif kind == 'pool':
            from resources.lib import translate
            body, _sid = translate._pool_source_text(
                info, payload.get('hash'), cache_only=True)
            return body or '', payload
        if path and os.path.isfile(path):
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read(), payload
    except Exception:
        pass
    return '', {}


def _is_human_hebrew_candidate(payload):
    kind = payload.get('type')
    if kind == 'passthrough':
        return True
    if kind == 'pool':
        return (payload.get('pool_kind') or 'ai') == 'ktuvit'
    if kind == 'engine' and not payload.get('embedded'):
        lang = payload.get('language') or ''
        return ('Hebrew' in lang and 'MachineTranslated' not in lang)
    return False


def rank_ready_candidates(info, candidates, max_candidates=4):
    """Conservatively promote a proven-synced cached human Hebrew candidate.

    This is used only by autosub.  It never fetches candidates, never changes
    the manual picker and never elevates AI over human translation.  A promotion
    happens only when the candidate is CONFIRMED against the exact playing-file
    profile and the current first choice is either already cached and worse, or
    lacks an exact/same-release identity.  Any doubt preserves provider order.
    """
    try:
        if (kodi_utils.get_setting('subsync_autorank', 'true') or
                'true').strip().lower() == 'false':
            return candidates
        bundle = _cached_reference_bundle(info)
        if not bundle:
            return candidates
        playing = playing_release(info)
        if not playing:
            return candidates
        rows = list(candidates or [])
        human_indexes = []
        checked = []
        for index, candidate in enumerate(rows):
            text, payload = _ready_candidate_text(info, candidate)
            listed_lang = (candidate.get('language') or '').strip().lower()
            if (listed_lang not in ('he', 'heb', 'hebrew')
                    or not _is_human_hebrew_candidate(payload)):
                continue
            human_indexes.append(index)
            if text and len(checked) < max(1, int(max_candidates)):
                verdict, label, count = _verify_file_bundle(bundle, text)
                checked.append({'index': index, 'candidate': candidate,
                                'payload': payload, 'verdict': verdict or {},
                                'label': label, 'count': count})
        if len(checked) < 2 or not human_indexes:
            return candidates
        confirmed = [x for x in checked
                     if x['verdict'].get('status')
                     == sync_align.STATUS_CONFIRMED]
        if not confirmed:
            return candidates
        chosen = max(confirmed, key=lambda x: (
            float(x['verdict'].get('overlap') or 0.0),
            float(x['verdict'].get('vote') or 0.0), x['count']))
        first_index = human_indexes[0]
        if chosen['index'] == first_index:
            return candidates
        first_checked = next((x for x in checked
                              if x['index'] == first_index), None)
        if first_checked is None:
            # Do not demote a not-yet-downloaded exact/same-release subtitle.
            first_payload = _decode_link(rows[first_index].get('link') or '') or {}
            first_release = (first_payload.get('filename') or
                             rows[first_index].get('filename') or '')
            _pct, tier, _diag = release_match.score(playing, first_release)
            if tier in release_match.AUTO_OK_TIERS:
                return candidates
        elif (first_checked['verdict'].get('status')
              == sync_align.STATUS_CONFIRMED):
            return candidates
        picked = rows.pop(chosen['index'])
        # Removing an earlier index shifts the insertion point by one.
        insert_at = first_index - (1 if chosen['index'] < first_index else 0)
        rows.insert(insert_at, picked)
        _log('autosub timing-rank: promoted cached human candidate %r (%s, '
             '%d cues)' % (picked.get('filename') or '?', chosen['label'],
                           chosen['count']))
        return rows
    except Exception as e:
        _log('autosub timing-rank skipped: %r' % e, level='DEBUG')
        return candidates


# ---- main entry -------------------------------------------------------------

def process(info, path, delivered_release, selection=None):
    """Verify (and when confidently possible, FIX) the timing of the Hebrew
    sub at `path` against the playing release. Returns (final_path, verdict)
    where verdict is a dict with at least {'status'} plus 'applied': True when
    a retimed copy was written and returned, or (path, None) when SubSync did
    not run (disabled / no anchor / unreadable file). Fail-open, never raises."""
    try:
        # The caller snapshots the selected candidate when resolve() starts.
        # A download/AI translation may finish much later; by then another
        # subtitle may be current. Never cancel, label, learn from or queue the
        # old result against that newer selection.
        selection = (_selection_snapshot()
                     if selection is None else selection)
        if not _selection_matches(selection):
            return path, None
        if sync_align is None or release_match is None or not enabled():
            return path, None
        if not path or not os.path.isfile(path):
            return path, None
        playing = playing_release(info)
        if not playing:
            kodi_utils.stage_subtitle_delivery(
                path, selection=selection,
                status='unverified', source='no-release')
            return path, None

        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
        except Exception:
            return path, None
        if not text.strip():
            return path, None
        cut_signature = _known_cut_signature(info, playing)
        key = _cache_key(text, playing, cut_signature)

        # Trusted tier -> synced by release identity; nothing to do (still
        # recorded so a manual-delay fix on it feeds the community registry).
        rel = (delivered_release or '').strip()
        if rel:
            _pct, tier, _ = release_match.score(playing, rel)
            if tier in release_match.AUTO_OK_TIERS:
                _record_delivery(info, playing, key, 1.0, 0.0,
                                 cut_signature=cut_signature,
                                 selection=selection)
                # Trusted timing needs no verification, but a remote first play
                # still needs its tiny content id so a later manual delay is
                # learned for this cut only.  Do that in the service worker.
                if not cut_signature and _remote_playing_url(info):
                    marked = _mark_pending(key, selection=selection)
                    if (marked and not _enqueue_deep(
                            info, path, rel, playing, key,
                            identity_only=True, selection=selection)):
                        _log('identity job queue unavailable', level='DEBUG')
                kodi_utils.stage_subtitle_delivery(
                    path, selection=selection,
                    status='confirmed', source='release')
                return path, {'status': _STATUS_TRUSTED, 'tier': tier}

        cached = _load_verdicts().get(key)
        if cached and cached.get('v') != _VERDICT_VERSION:
            cached = None   # stored by an older engine -- recompute
        if cached:
            status = cached.get('status')
            if status == sync_align.STATUS_FIXABLE:
                try:
                    fixed = sync_align.apply_verdict(text, cached)
                except Exception as e:
                    _log('cached FIXABLE failed structural recheck: %r' % e,
                         level='WARNING')
                    fixed = ''
                out = _write_fixed(path, fixed)
                if out:
                    # Quiet on repeat plays: the fix was announced ONCE when it
                    # was first computed; from then on it just works silently.
                    _log('cached FIXABLE applied: ' + cached.get('diag', ''))
                    if cached.get('mode', 'global') == 'global':
                        _record_delivery(info, playing, key,
                                         cached.get('scale', 1.0),
                                         cached.get('offset_ms', 0.0),
                                         cut_signature=cut_signature,
                                         selection=selection)
                    else:
                        # A scalar manual-delay record cannot describe a
                        # subtitle corrected by several timeline regions.
                        # Remove the original zero/global record immediately,
                        # before the delay watcher can learn or share it.
                        _clear_delivery(selection=selection)
                    kodi_utils.stage_subtitle_sync_fix(
                        out, selection=selection, source='cache')
                    return out, {'status': status, 'applied': True,
                                 'offset_ms': cached.get('offset_ms', 0.0),
                                 'scale': cached.get('scale', 1.0),
                                 'mode': cached.get('mode', 'global'),
                                 'segments': cached.get('segments') or [],
                                 'diag': cached.get('diag', ''), 'cached': True}
            if status in (sync_align.STATUS_CONFIRMED,
                          sync_align.STATUS_UNKNOWN):
                _record_delivery(info, playing, key, 1.0, 0.0,
                                 cut_signature=cut_signature,
                                 selection=selection)
                kodi_utils.stage_subtitle_delivery(
                    path, selection=selection,
                    status=('confirmed'
                            if status == sync_align.STATUS_CONFIRMED
                            else 'unverified'),
                    source='cache')
                return path, {'status': status, 'cached': True,
                              'diag': cached.get('diag', '')}

        # COMMUNITY registry (S3): a verdict some other device (or a human
        # delay-fix) already established for this exact (subtitle, release)
        # pair -- served inside the pool /lookup the picker already made, so
        # this is a dict lookup, not a request. First hit on THIS device gets
        # the one gentle toast; it's stored locally so repeats are silent.
        # A remote first play has no exact cut id yet.  Do not apply the old
        # release-only community record blindly; the background verifier will
        # fingerprint the actual file and consult/store the scoped namespace.
        cv = (None if (_remote_playing_url(info) and not cut_signature) else
              _community_verdict(info, key, playing,
                                 cut_signature=cut_signature))
        if cv is not None:
            status = cv.get('status')
            if status == sync_align.STATUS_FIXABLE:
                try:
                    fixed = sync_align.apply_verdict(text, cv)
                except Exception:
                    fixed = ''
                out = _write_fixed(path, fixed)
                if out:
                    _store_verdict(key, cv)
                    _log('community FIXABLE applied: ' + cv.get('diag', ''))
                    verdict = dict(cv, applied=True, community=True)
                    if cv.get('mode', 'global') == 'global':
                        _record_delivery(info, playing, key,
                                         cv.get('scale', 1.0),
                                         cv.get('offset_ms', 0.0),
                                         cut_signature=cut_signature,
                                         selection=selection)
                    else:
                        _clear_delivery(selection=selection)
                    kodi_utils.stage_subtitle_sync_fix(
                        out, selection=selection, source='community',
                        notice=_fix_notice(verdict))
                    return out, verdict
            elif status == sync_align.STATUS_CONFIRMED:
                _store_verdict(key, cv)
                _log('community CONFIRMED: ' + cv.get('diag', ''))
                _record_delivery(info, playing, key, 1.0, 0.0,
                                 cut_signature=cut_signature,
                                 selection=selection)
                kodi_utils.stage_subtitle_delivery(
                    path, selection=selection,
                    status='confirmed', source='community')
                return path, dict(cv, community=True)

        # DEEP verification needed (oracle download / file probe / audio) --
        # NEVER inline: it can take 10-30s and used to hold the autosub
        # "searching subtitles" overlay up (and the picker spinner) the whole
        # time. Hand the job to the long-lived service (same disk-queue
        # pattern as the he_warm drainer), deliver the ORIGINAL file now, and
        # let the worker swap in a fixed copy when (and only when) it proves
        # one -- self-healing delivery, per the plan's latency budget.
        marked = _mark_pending(key, selection=selection)
        delivery_staged = bool(
            marked and kodi_utils.stage_subtitle_delivery(
                path, selection=selection))
        # Publish before the job file becomes visible to the service. A fast
        # worker can only replace "checking" with its result, never have this
        # foreground path overwrite a verdict that has already completed.
        if delivery_staged:
            _publish_selection_status(
                'checking', 'local', selection=selection)
        _record_delivery(info, playing, key, 1.0, 0.0,
                         cut_signature=cut_signature, selection=selection)
        if (delivery_staged and _enqueue_deep(
                info, path, rel, playing, key, selection=selection)):
            return path, {'status': 'PENDING'}
        # Remove only this selection's half-created coordination records. A
        # newer pick has another token and cannot be disturbed here.
        try:
            kodi_utils.clear_subtitle_delivery(path, selection=selection)
        except Exception:
            pass
        _clear_job_pending({
            'key': key,
            'selection_token': selection.get('token') or '',
            'selection_hash': selection.get('link_hash') or '',
            'stream_hash': selection.get('stream_hash') or '',
        })
        # Queue unwritable (rare): keep playback responsive and the chosen
        # subtitle untouched.  Deep verification can include provider and media
        # reads; doing it synchronously here would bring the old 10-30s picker
        # freeze back precisely when the background service is unavailable.
        kodi_utils.stage_subtitle_delivery(
            path, selection=selection,
            status='unverified', source='queue')
        _log('deep verify deferred: service queue unavailable', level='WARNING')
        return path, {'status': 'DEFERRED'}
    except Exception as e:
        _log('process failed (fail-open): %r' % e, level='WARNING')
        return path, None


def _sync_registry_release(playing, cut_signature=''):
    """Backward-compatible exact-cut namespace for the existing Worker key."""
    sig = (cut_signature or '').strip().lower()
    if re.fullmatch(r'cut1:[0-9a-f]{32}', sig):
        return '%s POVILCUT %s' % (playing, sig.split(':', 1)[1])
    return playing


def _community_verdict(info, key, playing, cut_signature=''):
    """A community /sync record for this (subtitle, release) pair, converted
    to a local-verdict dict -- or None. Never raises, never blocks (the map
    was stashed by the picker's pool lookup; at worst ONE throttled lookup)."""
    try:
        from resources.lib import pool as _pool
        sm = _pool.sync_map(info)
        if not sm:
            return None
        sub_hash = key.split('|', 1)[0]
        registry_release = _sync_registry_release(playing, cut_signature)
        ent = sm.get(sub_hash + '|' +
                     _pool.worker_norm_release(registry_release))
        if not isinstance(ent, dict):
            return None
        scale = float(ent.get('s') or 1.0)
        off = float(ent.get('o') or 0.0)
        st = ent.get('st')
        human = int(ent.get('h') or 0)
        diag = 'community record (votes=%s human=%s)' % (
            ent.get('n', 1), human)
        if st == 'CONFIRMED' or (scale == 1.0
                                 and abs(off) <= sync_align.CONFIRM_OFFSET_MS):
            return {'status': sync_align.STATUS_CONFIRMED, 'scale': 1.0,
                    'offset_ms': 0.0, 'diag': diag}
        if not (sync_align.SCALE_MIN <= scale <= sync_align.SCALE_MAX):
            return None
        if abs(off) > sync_align.MAX_PLAUSIBLE_OFFSET_MS:
            return None
        # Don't blindly jump a sub by many seconds on one unverified AUTO vote
        # (poisoned-record guard) -- fall through to the locally-gated
        # deep-verify instead. Human-confirmed records apply at any magnitude.
        if abs(off) > _COMMUNITY_AUTO_MAX_OFFSET_MS and human < 1:
            _log('community record skipped (large auto offset %+dms, no human '
                 'confirmation) -- deferring to local verify' % int(off),
                 level='DEBUG')
            return None
        return {'status': sync_align.STATUS_FIXABLE, 'scale': scale,
                'offset_ms': off, 'diag': diag}
    except Exception as e:
        _log('community verdict failed: %r' % e, level='DEBUG')
        return None


_DELIVERED_PROP = 'subsync.delivered'


def _delivery_prop(selection=None):
    expected = selection or {}
    token = expected.get('token') or expected.get('selection_token') or ''
    if not token:
        try:
            token = kodi_utils.get_subtitle_selection_token() or ''
        except Exception:
            token = ''
    return _DELIVERED_PROP + ('.' + token if token else '')


def _clear_delivery(selection=None):
    """Discard scalar delay-learning state after a non-global delivery."""
    try:
        if selection and not _selection_matches(selection):
            return False
        import xbmcgui
        win = xbmcgui.Window(10000)
        win.clearProperty(_delivery_prop(selection))
        # A pre-token record cannot belong to a newer token-scoped selection.
        win.clearProperty(_DELIVERED_PROP)
        return True
    except Exception:
        return False


def _record_delivery(info, playing, key, scale, offset_ms,
                     cut_signature='', mode='global', selection=None):
    """Remember what we just delivered (and any applied fix), so the service's
    delay watcher can turn the viewer's manual subtitle-delay into a HUMAN
    community sync report -- the anchor of last resort."""
    try:
        import xbmcgui
        expected = selection or {}
        if expected and not kodi_utils.subtitle_selection_matches(
                expected.get('token') or '',
                expected.get('link_hash') or '',
                expected.get('stream_hash') or ''):
            return False
        payload = {
            'key': key, 'playing': playing, 'ts': time.time(),
            'scale': float(scale or 1.0),
            'offset': float(offset_ms or 0.0),
            'mode': (mode or '').strip().lower(),
            'cut_signature': (cut_signature or '').strip().lower(),
            'selection_token': expected.get('token') or '',
            'selection_hash': expected.get('link_hash') or '',
            'stream_hash': expected.get('stream_hash') or '',
            'info': {k: info.get(k) for k in _INFO_KEYS
                     if isinstance(info.get(k), (str, int, float, bool))},
        }
        win = xbmcgui.Window(10000)
        raw = json.dumps(payload, ensure_ascii=False)
        prop = _delivery_prop(expected)
        win.setProperty(prop, raw)
        if expected and not kodi_utils.subtitle_selection_matches(
                expected.get('token') or '',
                expected.get('link_hash') or '',
                expected.get('stream_hash') or ''):
            if win.getProperty(prop) == raw:
                win.clearProperty(prop)
            return False
        return True
    except Exception:
        return False


def current_delivery_record():
    """Return delay-learning state only for the exact live selection/cut."""
    try:
        import xbmcgui
        selection = _selection_snapshot()
        if not _selection_matches(selection):
            return None
        win = xbmcgui.Window(10000)
        raw = win.getProperty(_delivery_prop(selection)) or ''
        if not raw:
            # One-session migration from the previous global property.
            raw = win.getProperty(_DELIVERED_PROP) or ''
        record = json.loads(raw) if raw else None
        if not isinstance(record, dict):
            return None
        token = record.get('selection_token') or ''
        link_hash = record.get('selection_hash') or ''
        stream_hash = record.get('stream_hash') or ''
        if token or link_hash or stream_hash:
            if (token != selection.get('token')
                    or link_hash != selection.get('link_hash')
                    or stream_hash != selection.get('stream_hash')):
                return None
        return record
    except Exception:
        return None


def clear_delivery_record(record):
    """Remove only the token-scoped record the delay watcher just consumed."""
    try:
        import xbmcgui
        win = xbmcgui.Window(10000)
        prop = _delivery_prop(record or {})
        raw = win.getProperty(prop) or ''
        current = json.loads(raw) if raw else {}
        if (current.get('key') == (record or {}).get('key')
                and float(current.get('ts') or 0)
                == float((record or {}).get('ts') or 0)):
            win.clearProperty(prop)
            return True
        # Clear only the legacy singleton when it is the exact same record.
        legacy = win.getProperty(_DELIVERED_PROP) or ''
        old = json.loads(legacy) if legacy else {}
        if (old.get('key') == (record or {}).get('key')
                and float(old.get('ts') or 0)
                == float((record or {}).get('ts') or 0)):
            win.clearProperty(_DELIVERED_PROP)
            return True
    except Exception:
        pass
    return False


def finalize_delay_session(record, delay_s, watched_s):
    """Decide whether a finished viewing session yields a HUMAN sync report.
    Returns the report dict for pool.report_sync, or None.
      - settled manual delay >= 0.4s after >= 5 min watched -> FIXABLE
        (combined with whatever fix was already applied at delivery);
      - zero delay after >= 15 min watched -> a confirming vote for the
        delivered timing.
    Pure function (no Kodi imports) so it is unit-testable."""
    try:
        if not record or watched_s < 300:
            return None
        # Human delay is one scalar.  It can refine a global transform, but it
        # must never flatten a multi-region correction into one offset or
        # publish that lossy value to the community registry.  Missing mode is
        # rejected too: current deliveries always write it, so absence means a
        # stale record from an older engine.
        if record.get('mode') != 'global':
            return None
        key = record.get('key') or ''
        playing = (record.get('playing') or '').strip()
        if not key or not playing:
            return None
        cut_signature = (record.get('cut_signature') or '').strip().lower()
        if (not re.fullmatch(r'cut1:[0-9a-f]{32}', cut_signature)
                or not key.endswith('|' + cut_signature)):
            # A release name is not a media identity.  If the tiny fingerprint
            # could not be obtained, keep the viewer's delay private rather than
            # teaching another cut a correction that may be wrong for it.
            return None
        sub_hash = key.split('|', 1)[0]
        base_scale = float(record.get('scale') or 1.0)
        base_off = float(record.get('offset') or 0.0)
        d = float(delay_s or 0.0)
        if abs(d) >= 0.4:
            # Kodi delay d shows subs d seconds LATER; our fix map is
            # t' = (t - offset)/scale, so the user's correction folds in as
            # offset' = offset - d*1000*scale (measured on the sub timeline).
            off = base_off - d * 1000.0 * base_scale
            if abs(off) > 240000:
                return None
            return {'sub_hash': sub_hash, 'release': playing,
                    'scale': base_scale, 'offset_ms': off,
                    'status': 'FIXABLE', 'origin': 'human',
                    'mode': 'global',
                    'cache_key': key,
                    'cut_signature': cut_signature,
                    'info': record.get('info') or {}}
        if watched_s >= 900 and abs(d) < 0.05:
            if base_scale == 1.0 and abs(base_off) < 1.0:
                return {'sub_hash': sub_hash, 'release': playing,
                        'scale': 1.0, 'offset_ms': 0.0,
                        'status': 'CONFIRMED', 'origin': 'human',
                        'mode': 'global',
                        'cache_key': key,
                        'cut_signature': cut_signature,
                        'info': record.get('info') or {}}
            # Zero manual delay on an APPLIED fix = a human vote that the fix
            # is right (agrees with the stored record -> just bumps votes).
            return {'sub_hash': sub_hash, 'release': playing,
                    'scale': base_scale, 'offset_ms': base_off,
                    'status': 'FIXABLE', 'origin': 'human',
                    'mode': 'global',
                    'cache_key': key,
                    'cut_signature': cut_signature,
                    'info': record.get('info') or {}}
        return None
    except Exception:
        return None


def store_human_verdict(report):
    """Persist a viewer-confirmed correction under its exact local cut key.

    The existing Worker schema remains unchanged; both its release field and
    this local key are namespaced with the content signature so another cut
    carrying the same release label cannot inherit the correction.
    """
    try:
        if (report or {}).get('mode') != 'global':
            return False
        key = (report or {}).get('cache_key') or ''
        sig = ((report or {}).get('cut_signature') or '').strip().lower()
        if not key or not re.fullmatch(r'cut1:[0-9a-f]{32}', sig):
            return False
        if not key.endswith('|' + sig):
            return False
        status = (report or {}).get('status')
        if status not in (sync_align.STATUS_CONFIRMED,
                           sync_align.STATUS_FIXABLE):
            return False
        verdict = {
            'status': status,
            'scale': float((report or {}).get('scale') or 1.0),
            'offset_ms': float((report or {}).get('offset_ms') or 0.0),
            'mode': 'global',
            'diag': 'human-confirmed exact media cut',
        }
        _store_verdict(key, verdict)
        return True
    except Exception:
        return False


def _guard_soft_probe_shift(verdict, ref_kind):
    """Refuse a sub-second nudge supported only by soft media-probe timing.

    Subtitle tracks share the container clock, but each language/subber may
    intentionally lead or trail speech by several hundred milliseconds. A
    multi-track union can therefore outvote a candidate that is byte-for-byte
    aligned with one real track. Keep those small editorial differences as-is;
    large offsets, standard/non-standard clock drift and piecewise fixes still
    go through the normal gates.
    """
    if (not verdict or ref_kind not in ('FILE PROBE', 'AUDIO PROBE')
            or verdict.get('status') != sync_align.STATUS_FIXABLE
            or verdict.get('mode', 'global') != 'global'):
        return verdict
    try:
        scale = float(verdict.get('scale') or 1.0)
        offset = float(verdict.get('offset_ms') or 0.0)
    except (TypeError, ValueError):
        return verdict
    if abs(scale - 1.0) > 0.0002 or abs(offset) >= _SOFT_PROBE_SHIFT_MS:
        return verdict
    guarded = dict(verdict)
    guarded.update({
        'status': sync_align.STATUS_UNKNOWN,
        'reason': 'soft_probe_shift',
        'diag': ('soft probe shift preserved unchanged (%s %+dms; %s)'
                 % (ref_kind, int(offset), verdict.get('diag', ''))),
    })
    return guarded


def _probe_gate_kwargs(cues):
    if cues and len(cues) < _SPARSE_PROBE_CUES:
        return {'scales': _AUDIO_SCALES,
                'max_offset_ms': _AUDIO_MAX_OFFSET_MS}
    return {}


def _track_language_rank(track):
    lang = (track.get('lang') or '').strip().lower()[:3]
    if lang in ('he', 'heb', 'iw'):
        return 0
    if lang in ('en', 'eng'):
        return 1
    return 2


def _verdict_strength(item):
    verdict = item.get('verdict') or {}
    return (
        1 if verdict.get('status') == sync_align.STATUS_CONFIRMED else 0,
        float(verdict.get('overlap') or 0.0),
        float(verdict.get('vote') or 0.0),
        float(verdict.get('unique') or 0.0),
        -_track_language_rank(item.get('track') or {}),
        len(item.get('cues') or []),
    )


def _maps_agree(left, right):
    """Whether two independently accepted track corrections corroborate."""
    if (left.get('mode', 'global') != 'global'
            or right.get('mode', 'global') != 'global'):
        # Piecewise maps are too rich to merge by a loose scalar comparison.
        return (left.get('mode') == right.get('mode')
                and left.get('segments') == right.get('segments'))
    try:
        return (abs(float(left.get('scale') or 1.0)
                    - float(right.get('scale') or 1.0)) <= 0.0005
                and abs(float(left.get('offset_ms') or 0.0)
                        - float(right.get('offset_ms') or 0.0)) <= 800.0)
    except Exception:
        return False


def _track_codec_family(track):
    codec = (track.get('codec') or '').strip().upper()
    if 'PGS' in codec or 'HDMV' in codec:
        return 'pgs'
    if codec.startswith('S_TEXT') or 'UTF' in codec or 'ASS' in codec:
        return 'text'
    return 'other'


def _track_span(profile):
    cues = profile.get('cues') or []
    if not cues:
        return 0.0
    return max(0.0, float(cues[-1]['end']) - float(cues[0]['start']))


def _onset_coverage(source, target, tolerance_ms=250.0):
    """Fraction of source onsets with a nearby target onset (linear scan)."""
    left = sorted(float(cue['start']) for cue in source or [])
    right = sorted(float(cue['start']) for cue in target or [])
    if not left or not right:
        return 0.0
    matched = 0
    cursor = 0
    for value in left:
        while (cursor + 1 < len(right)
               and abs(right[cursor + 1] - value)
               <= abs(right[cursor] - value)):
            cursor += 1
        if abs(right[cursor] - value) <= float(tolerance_ms):
            matched += 1
    return matched / float(len(left))


def _timing_profiles_distinct(left, right):
    """Reject a codec conversion that merely copies the same cue onsets.

    Codec labels alone are not independent evidence: a text stream can be
    rendered to PGS without changing its timing.  Real Flash text/PGS families
    differ editorially; a converted duplicate has >=90% onset coverage in both
    directions and must not unlock a rewrite.
    """
    left_cues = (left or {}).get('cues') or []
    right_cues = (right or {}).get('cues') or []
    return not (_onset_coverage(left_cues, right_cues) >= 0.90
                and _onset_coverage(right_cues, left_cues) >= 0.90)


def _validated_micro_piecewise(profiles, text):
    """Prove repeated short edits without counting duplicate tracks twice.

    Matroska Cues entries for several language tracks can be near-identical, so
    "two tracks agree" is not independent evidence.  Learn from exactly one
    preferred non-SDH English text timeline, demand 4/5 out-of-sample folds,
    then freeze the map and validate it against one PGS codec family.  Other
    PGS language tracks may veto a regression but never add votes.
    """
    planner = getattr(sync_align, 'micro_piecewise_proposal', None)
    validator = getattr(sync_align, 'validate_micro_piecewise', None)
    family_judge = getattr(sync_align, 'evaluate_piecewise_family', None)
    if planner is None or validator is None or family_judge is None:
        return None
    text_tracks = []
    pgs_tracks = []
    for profile in profiles or []:
        track = profile.get('track') or {}
        family = _track_codec_family(track)
        if family == 'pgs':
            pgs_tracks.append(profile)
        if (family == 'text' and not track.get('forced')
                and _track_language_rank(track) == 1):
            text_tracks.append(profile)
    if not text_tracks or not pgs_tracks:
        return None

    try:
        candidate_cues = sync_align.dialogue_cues(
            sync_align.parse_srt(text))
        candidate_span = (float(candidate_cues[-1]['end'])
                          - float(candidate_cues[0]['start']))
    except Exception:
        candidate_span = 0.0

    def complete_family(items):
        """Ignore a short/forced excerpt before ranking preferred tracks."""
        max_span = max([_track_span(item) for item in items] + [0.0])
        floor = 0.90 * max(max_span, candidate_span)
        return [item for item in items if _track_span(item) >= floor]

    text_tracks = complete_family(text_tracks)
    pgs_tracks = complete_family(pgs_tracks)
    if not text_tracks or not pgs_tracks:
        return None

    def primary_key(profile):
        track = profile.get('track') or {}
        name = (track.get('name') or '').lower()
        is_sdh = bool(track.get('hearing_impaired')) or 'sdh' in name or 'hi' == name
        return (0 if is_sdh else 1, _track_span(profile),
                len(profile.get('cues') or []))

    primary = max(text_tracks, key=primary_key)
    try:
        proposal = planner(primary.get('cues') or [], text)
        verdict = validator(primary.get('cues') or [], text, proposal)
    except Exception:
        verdict = None
    if verdict is None:
        return None

    # Prefer English PGS, then the broadest non-forced PGS representative. One
    # passing representative establishes the codec family; duplicates do not.
    pgs_tracks = sorted(pgs_tracks, key=lambda profile: (
        1 if _track_language_rank(profile.get('track') or {}) == 1 else 0,
        0 if (profile.get('track') or {}).get('forced') else 1,
        _track_span(profile), len(profile.get('cues') or [])), reverse=True)
    family_result = None
    family_profile = None
    for profile in pgs_tracks:
        if not _timing_profiles_distinct(primary, profile):
            continue
        try:
            metrics = family_judge(profile.get('cues') or [], text, verdict)
        except Exception:
            metrics = None
        # A strong pre-existing match that the frozen map damages is a veto,
        # even when another duplicate PGS track happens to pass.
        if (metrics and metrics.get('before_score', 0.0) >= 0.78
                and metrics.get('after_score', 0.0)
                < metrics.get('before_score', 0.0) - 0.03):
            return None
        if family_result is None and metrics and metrics.get('accepted'):
            family_result, family_profile = metrics, profile
    if family_result is None:
        return None

    primary_track = primary.get('track') or {}
    family_track = family_profile.get('track') or {}
    verdict = dict(verdict)
    verdict.update({
        'timing_family_count': 2,
        'timing_families': ['text', 'pgs'],
        'validation_primary_track': '#%s/%s' % (
            primary_track.get('num', '?'), primary_track.get('lang', '?')),
        'validation_family_track': '#%s/%s' % (
            family_track.get('num', '?'), family_track.get('lang', '?')),
        'diag': ('%s; frozen map validated on PGS family '
                 '(score %.3f->%.3f overlap=%.0f%% unique=%.0f%%)'
                 % (verdict.get('diag', ''),
                    family_result['before_score'],
                    family_result['after_score'],
                    family_result['after_overlap'] * 100,
                    family_result['after_unique'] * 100)),
    })
    return {'track': primary_track, 'cues': primary.get('cues') or [],
            'verdict': verdict}


def _verify_file_bundle(bundle, text):
    """Judge independent embedded tracks; abstain when they are all too sparse.

    A CONFIRMED track wins over a shifted track because it proves the candidate
    already matches one real timeline in the playing file.  Conflicting accepted
    corrections abstain.  A legacy single-track reader remains compatible, but
    modern multi-track timelines are never merged into evidence they did not
    possess separately.
    Returns ``(verdict, label, cue_count)``.
    """
    raw_profiles = []
    for profile in (bundle or {}).get('track_cues') or []:
        cues = profile.get('cues') or []
        if len(cues) < MIN_REMOTE_CUES:
            continue
        raw_profiles.append({'track': profile.get('track') or {},
                             'cues': cues})

    # The short-edit planner is cheap (identity clock, local windows only),
    # whereas a full arbitrary-scale search on every language track is costly
    # on 32-bit Kodi.  Try the independently corroborated path first.  Before
    # accepting it, every track gets an identity-only veto: a truly CONFIRMED
    # track proves that no rewrite is needed, and any competing flat FIXABLE
    # sends us through the complete conflict-aware path below.
    validated_piecewise = _validated_micro_piecewise(raw_profiles, text)
    if validated_piecewise is not None:
        quick = []
        for profile in raw_profiles:
            cues = profile.get('cues') or []
            kwargs = dict(_probe_gate_kwargs(cues))
            kwargs.update({'scales': (1.0,), 'allow_piecewise': False})
            try:
                verdict = sync_align.verify_cues(cues, text, **kwargs)
            except Exception:
                continue
            if verdict.get('status') in (sync_align.STATUS_CONFIRMED,
                                          sync_align.STATUS_FIXABLE):
                quick.append({'track': profile.get('track') or {},
                              'cues': cues, 'verdict': verdict})
        exact = [item for item in quick
                 if item['verdict'].get('status')
                 == sync_align.STATUS_CONFIRMED]
        if exact:
            chosen = max(exact, key=_verdict_strength)
            verdict = _guard_soft_probe_shift(
                chosen['verdict'], 'FILE PROBE')
            track = chosen.get('track') or {}
            return (verdict, 'FILE TRACK #%s %s' % (
                track.get('num', '?'), track.get('lang') or '?'),
                    len(chosen.get('cues') or []))
        if not quick:
            verdict = _guard_soft_probe_shift(
                validated_piecewise['verdict'], 'FILE PROBE')
            track = validated_piecewise.get('track') or {}
            label = 'FILE TRACK VALIDATED #%s %s' % (
                track.get('num', '?'), track.get('lang') or '?')
            return (verdict, label,
                    len(validated_piecewise.get('cues') or []))

    profiles = []
    for profile in raw_profiles:
        cues = profile.get('cues') or []
        try:
            verdict = sync_align.verify_cues(
                cues, text, **_probe_gate_kwargs(cues))
        except Exception:
            continue
        profiles.append({'track': profile.get('track') or {},
                         'cues': cues, 'verdict': verdict})

    accepted = [p for p in profiles
                if p['verdict'].get('status') in (
                    sync_align.STATUS_CONFIRMED,
                    sync_align.STATUS_FIXABLE)]
    confirmed = [p for p in accepted
                 if p['verdict'].get('status')
                 == sync_align.STATUS_CONFIRMED]
    if confirmed:
        chosen = max(confirmed, key=_verdict_strength)
    elif accepted:
        chosen = max(accepted, key=_verdict_strength)
        conflicts = [p for p in accepted
                     if not _maps_agree(chosen['verdict'], p['verdict'])]
        if conflicts:
            summary = ', '.join(
                '#%s/%s %+dms' % (
                    (p.get('track') or {}).get('num', '?'),
                    (p.get('track') or {}).get('lang', '?'),
                    int((p.get('verdict') or {}).get('offset_ms') or 0))
                for p in accepted)
            return ({'status': sync_align.STATUS_UNKNOWN,
                     'scale': 1.0, 'offset_ms': 0.0,
                     'reason': 'embedded_track_conflict',
                     'diag': 'independent embedded tracks disagree: ' + summary},
                    'FILE TRACK CONFLICT', 0)
    elif profiles:
        # At least one real track had enough evidence and all refused.  A union
        # must not manufacture confidence that no constituent track possessed.
        chosen = max(profiles, key=_verdict_strength)
    elif (bundle or {}).get('legacy_single_track'):
        union = (bundle or {}).get('cues') or []
        if len(union) < MIN_REMOTE_CUES:
            return None, 'FILE PROBE', 0
        verdict = sync_align.verify_cues(
            union, text, **_probe_gate_kwargs(union))
        verdict = _guard_soft_probe_shift(verdict, 'FILE PROBE')
        return verdict, 'FILE LEGACY TRACK', len(union)
    else:
        # Several individually sparse tracks are not evidence for one shared
        # timeline.  Unioning them can fabricate a confident majority from
        # unrelated editorial lead/lag, so the safe answer is to abstain.
        return None, 'FILE TRACKS TOO SPARSE', 0

    verdict = _guard_soft_probe_shift(chosen['verdict'], 'FILE PROBE')
    track = chosen.get('track') or {}
    label = 'FILE TRACK #%s %s' % (track.get('num', '?'),
                                   track.get('lang') or '?')
    return verdict, label, len(chosen.get('cues') or [])


def _deep_verify(info, path, text, rel, playing, key):
    """Cross-check the actual file, exact-cut memory, oracle, then local audio.

    The playing file is stronger than a release name, so it is evaluated first.
    Its content id also unlocks an exact-cut local/community verdict before any
    subtitle-provider download. Runs in the service worker; never raises.
    """
    try:
        pinned = (info.get('_subsync_stream_url') or '').strip()
        if pinned and _current_stream_url() != pinned:
            return path, None

        # Profile the actual media first. Besides being the strongest timing
        # anchor, this produces the content id used by all learning below.
        bundle = _probe_reference_bundle(info, playing)
        if pinned and _current_stream_url() != pinned:
            _log('deep verify discarded: playback changed during media probe')
            return path, None
        cut_signature = (bundle.get('cut_signature') or '').strip().lower()
        if not re.fullmatch(r'cut1:[0-9a-f]{32}', cut_signature):
            # A useful cue profile can survive optional signature-range
            # pressure. Retry only the tiny identity reader rather than throwing
            # away the timing evidence or caching it under a release-only key.
            cut_signature = _learn_cut_signature(info)
            if not re.fullmatch(r'cut1:[0-9a-f]{32}', cut_signature or ''):
                cut_signature = ''
        final_key = _cache_key(text, playing, cut_signature)
        accepted = (sync_align.STATUS_CONFIRMED, sync_align.STATUS_FIXABLE)

        # The first foreground pass may not have known the remote content id.
        # Once the profile reveals it, reuse an exact local verdict immediately.
        exact_cached = _load_verdicts().get(final_key) if cut_signature else None
        if exact_cached and exact_cached.get('v') == _VERDICT_VERSION:
            status = exact_cached.get('status')
            result = dict(exact_cached, cut_signature=cut_signature,
                          cache_key=final_key, cached=True)
            if status == sync_align.STATUS_FIXABLE:
                try:
                    fixed = sync_align.apply_verdict(text, exact_cached)
                except Exception:
                    fixed = ''
                out = _write_fixed(path, fixed)
                if out:
                    return out, dict(result, applied=True)
            if status in (sync_align.STATUS_CONFIRMED,
                          sync_align.STATUS_UNKNOWN):
                return path, result

        # Same idea for shared learning.  Never consult a release-only record
        # here: it may belong to another cut with the same release label.
        community = (_community_verdict(
            info, final_key, playing, cut_signature=cut_signature)
                     if cut_signature else None)
        if community:
            status = community.get('status')
            result = dict(community, cut_signature=cut_signature,
                          cache_key=final_key, community=True)
            if status == sync_align.STATUS_FIXABLE:
                try:
                    fixed = sync_align.apply_verdict(text, community)
                except Exception:
                    fixed = ''
                out = _write_fixed(path, fixed)
                if out:
                    _store_verdict(final_key, community)
                    return out, dict(result, applied=True)
            elif status == sync_align.STATUS_CONFIRMED:
                _store_verdict(final_key, community)
                return path, result

        file_verdict, ref_kind, ref_count = _verify_file_bundle(bundle, text)
        if file_verdict:
            _log('verdict for %r vs %s (%d ref cues): %s'
                 % (rel or '?', ref_kind, ref_count,
                    file_verdict.get('diag', '?')))

        fixed_text = None
        if file_verdict and file_verdict.get('status') in accepted:
            verdict = file_verdict
        else:
            # The file could not decide, so only now pay for a provider oracle.
            cands = _oracle_candidates(info)
            oracle, tier = (sync_align.pick_oracle(cands, playing)
                            if cands else (None, ''))
            oracle_verdict = None
            oracle_fixed = None
            if oracle is not None:
                oracle_text = _download_oracle(oracle['payload'])
                if oracle_text.strip():
                    okw = {}
                    if tier == release_match.TIER_SOURCE:
                        okw = {'scales': _ORACLE_SOURCE_SCALES,
                               'min_vote': _ORACLE_SOURCE_MIN_VOTE}
                    oracle_fixed, oracle_verdict = sync_align.verify_and_fix(
                        oracle_text, text, **okw)
                    _log('verdict for %r vs oracle %r [%s]: %s'
                         % (rel or '?', oracle['release'], tier,
                            oracle_verdict['diag']))
            else:
                try:
                    scored = sorted(
                        ((release_match.match_pct(playing, c['release']),
                          release_match.match_tier(playing, c['release']),
                          c['release']) for c in cands), reverse=True)[:5]
                    top = '; '.join('%d%%/%s %r' % s for s in scored) or '-'
                except Exception:
                    top = '?'
                _log('no oracle for release %r (%d foreign candidates); '
                     'closest: %s' % (playing, len(cands), top))
            if oracle_verdict and oracle_verdict.get('status') in accepted:
                verdict = oracle_verdict
                fixed_text = oracle_fixed
            else:
                verdict = file_verdict or oracle_verdict

        # With no usable embedded timeline, local AAC speech remains the final
        # fallback.  Remote audio is deliberately not opened: the proven-safe
        # remote path is the tiny cue/signature reader above.
        if (file_verdict is None
                and (verdict is None or verdict.get('status') not in accepted)):
            ref_cues = _audio_probe_reference(info, playing)
            if ref_cues:
                gate_kw = {'min_vote': _AUDIO_MIN_VOTE,
                           'min_overlap': _AUDIO_MIN_OVERLAP,
                           'scales': _AUDIO_SCALES,
                           'max_offset_ms': _AUDIO_MAX_OFFSET_MS}
                verdict = sync_align.verify_cues(ref_cues, text, **gate_kw)
                _log('verdict for %r vs AUDIO PROBE (%d ref cues): %s'
                     % (rel or '?', len(ref_cues), verdict['diag']))
                if (verdict['status'] == sync_align.STATUS_UNKNOWN
                        and 'tight check FAILED' in verdict.get('diag', '')
                        and verdict.get('vote', 0) >= 0.8):
                    more = _audio_probe_reference(info, playing,
                                                  second_pass=True)
                    if more and len(more) > len(ref_cues):
                        verdict = sync_align.verify_cues(
                            more, text, **gate_kw)
                        _log('audio verdict (pass 2, %d cues): %s'
                             % (len(more), verdict['diag']))
                verdict = _guard_soft_probe_shift(verdict, 'AUDIO PROBE')

        if verdict is None:
            return path, {'status': _STATUS_NO_ORACLE,
                          'cut_signature': cut_signature,
                          'cache_key': final_key}

        if verdict.get('status') == sync_align.STATUS_FIXABLE and not fixed_text:
            try:
                fixed_text = sync_align.apply_verdict(text, verdict)
            except Exception:
                fixed_text = None
            if not (fixed_text and fixed_text.strip()):
                verdict = dict(verdict, status=sync_align.STATUS_UNKNOWN)

        if pinned and _current_stream_url() != pinned:
            _log('deep verify discarded: playback changed before commit')
            return path, None
        verdict = dict(verdict, cut_signature=cut_signature,
                       cache_key=final_key)
        if cut_signature:
            _store_verdict(final_key, verdict)

        # Reuse the existing Worker protocol by namespacing its release key with
        # the content signature.  Old clients keep their legacy records; new
        # clients never apply one cut's vote to another cut with the same name.
        try:
            if (cut_signature and verdict['status'] in accepted
                    and verdict.get('mode', 'global') == 'global'):
                from resources.lib import pool as _pool
                _pool.report_sync(
                    info, final_key.split('|', 1)[0],
                    _sync_registry_release(playing, cut_signature),
                    verdict.get('scale', 1.0),
                    verdict.get('offset_ms', 0.0), verdict['status'],
                    origin='auto')
        except Exception:
            pass

        if verdict['status'] == sync_align.STATUS_FIXABLE:
            out = _write_fixed(path, fixed_text)
            if out:
                return out, dict(verdict, applied=True)
        return path, verdict
    except Exception as e:
        _log('deep verify failed (fail-open): %r' % e, level='WARNING')
        return path, None


# ---- background worker plumbing (service-side) -------------------------------

_QUEUE_DIR = ('special://profile/addon_data/service.subtitles.kodipovilai/'
              'subsync_queue')
_PENDING_PROP = 'subsync.pending'
_JOB_FRESH_S = 120
# Embedded subtitle tracks are an excellent video-timeline anchor for large
# offsets and clock drift, but different language/subber tracks routinely lead
# or trail the same spoken line by several hundred milliseconds. Never let that
# editorial variation nudge a subtitle that may already be correct. Release-
# matched subtitle oracles retain their existing small-offset behaviour.
_SOFT_PROBE_SHIFT_MS = 1000

# Keys that must survive the JSON round-trip for bridge.search /
# playing_release to work in the service process.
_INFO_KEYS = ('imdb_id', 'tmdb_id', 'season', 'episode', 'title', 'tvshow',
              'tvshowtitle', 'year', 'filepath', 'picked_release', 'tagline',
              'label', 'media_type', 'is_episode')


def _queue_dir():
    try:
        import xbmcvfs
        return xbmcvfs.translatePath(_QUEUE_DIR)
    except Exception:
        return ''


def _selection_matches(selection):
    expected = selection or {}
    try:
        return bool(expected.get('token') and expected.get('link_hash')
                    and expected.get('stream_hash')
                    and kodi_utils.subtitle_selection_matches(
                        expected.get('token'), expected.get('link_hash'),
                        expected.get('stream_hash')))
    except Exception:
        return False


def _pending_prop(selection=None):
    """Per-selection marker name, so concurrent picks cannot overwrite it."""
    expected = selection or {}
    token = expected.get('token') or ''
    if not token:
        try:
            token = kodi_utils.get_subtitle_selection_token() or ''
        except Exception:
            token = ''
    return _PENDING_PROP + ('.' + token if token else '')


def _mark_pending(key, selection=None):
    """Remember which (sub, release) pair we delivered un-verified, so the
    worker only swaps if the user hasn't picked something else meanwhile."""
    try:
        import xbmcgui
        expected = (_selection_snapshot()
                    if selection is None else selection)
        if not _selection_matches(expected):
            return False
        payload = {
            'key': key, 'ts': time.time(),
            'selection_token': expected.get('token') or '',
            'selection_hash': expected.get('link_hash') or '',
            'stream_hash': expected.get('stream_hash') or '',
        }
        win = xbmcgui.Window(10000)
        raw = json.dumps(payload, separators=(',', ':'))
        prop = _pending_prop(expected)
        win.setProperty(prop, raw)
        if not _selection_matches(expected):
            if win.getProperty(prop) == raw:
                win.clearProperty(prop)
            return False
        return True
    except Exception:
        return False


def cancel_pending():
    """Invalidate an older background job after a new subtitle selection.

    The old job may still finish and cache its verdict, but it must not hot-swap
    over a newer TRUSTED, cached or embedded subtitle on the same stream.
    """
    try:
        import xbmcgui
        win = xbmcgui.Window(10000)
        win.clearProperty(_pending_prop())
        win.clearProperty(_PENDING_PROP)  # pre-token release residue
    except Exception:
        pass


def _pending_record(selection=None):
    try:
        import xbmcgui
        raw = xbmcgui.Window(10000).getProperty(
            _pending_prop(selection)) or ''
        return (json.loads(raw) or {}) if raw else {}
    except Exception:
        return {}


def _pending_key():
    return _pending_record().get('key', '')


def _clear_job_pending(job):
    """Clear only this job's token-scoped marker; never another selection's."""
    try:
        import xbmcgui
        expected = {
            'token': job.get('selection_token') or '',
            'link_hash': job.get('selection_hash') or '',
            'stream_hash': job.get('stream_hash') or '',
        }
        prop = _pending_prop(expected)
        win = xbmcgui.Window(10000)
        raw = win.getProperty(prop) or ''
        record = json.loads(raw) if raw else {}
        if (record.get('key') == job.get('key')
                and record.get('selection_token') == expected['token']
                and record.get('selection_hash') == expected['link_hash']
                and record.get('stream_hash') == expected['stream_hash']):
            win.clearProperty(prop)
            return True
    except Exception:
        pass
    return False


def _enqueue_deep(info, path, rel, playing, key, identity_only=False,
                  selection=None):
    """Drop a deep-verify job for the service drainer. True on success."""
    d = _queue_dir()
    if not d:
        return False
    try:
        expected = (_selection_snapshot()
                    if selection is None else selection)
        if not _selection_matches(expected):
            return False
        os.makedirs(d, exist_ok=True)
        # The readable prefix alone used to collide when two long release keys
        # differed after character 80.  A full-key digest makes the queue name
        # unambiguous; identity-only and full verification are separate jobs so
        # a cheap trusted-subtitle task can never swallow a later timing task.
        job_identity = (key + ('|identity' if identity_only else '|verify')
                        + '|' + (expected.get('token') or ''))
        prefix = re.sub(r'[^0-9A-Za-z]+', '_', key)[:48] or 'job'
        safe = prefix + '_' + hashlib.sha1(
            job_identity.encode('utf-8', 'replace')).hexdigest()[:16]
        jpath = os.path.join(d, safe + '.json')
        try:
            if (os.path.isfile(jpath)
                    and time.time() - os.path.getmtime(jpath) < _JOB_FRESH_S):
                return True   # identical job already queued
        except OSError:
            pass
        job = {
            'key': key, 'path': path, 'release': rel, 'playing': playing,
            'identity_only': bool(identity_only),
            'ts': time.time(),
            'selection_token': expected.get('token') or '',
            'selection_hash': expected.get('link_hash') or '',
            'stream_hash': expected.get('stream_hash') or '',
            # Capture the actual stream identity at delivery time.  Metadata's
            # filepath is optional and may be absent; without this value a
            # later background result must never hot-swap into another video.
            'stream_url': _current_stream_url(),
            'info': {k: info.get(k) for k in _INFO_KEYS
                     if isinstance(info.get(k), (str, int, float, bool))},
        }
        tmp = jpath + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(job, f, ensure_ascii=False)
        # Last gate before the job becomes visible to the service. A newer
        # selection may have landed while this small file was being written.
        if not _selection_matches(expected):
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
        os.replace(tmp, jpath)
        _log('deep job enqueued for %r' % key)
        return True
    except Exception as e:
        _log('enqueue failed: %r' % e, level='WARNING')
        return False


def _announce(verdict, fresh, offset_hint=None, selection=None):
    """The ONE gentle toast policy: speak ONLY when a timing fix was actually
    APPLIED to the subtitle -- that's the single event the user can feel and
    wants to know about ("synced automatically"). Everything else is SILENT:
    a sub that couldn't be verified is delivered exactly as-is (fail-open), so
    there is nothing to tell the user -- a "couldn't verify" toast on an
    already-synced subtitle is pure noise and reads as a failure when nothing
    failed. (Most toasts in this build were deliberately silenced after user
    complaints; this stays in that spirit.) One toast per (sub,release) pair,
    ever -- fresh applied fixes only."""
    try:
        if not fresh or not verdict:
            return
        if selection is not None and not _selection_matches(selection):
            return
        if (verdict.get('status') == sync_align.STATUS_FIXABLE
                and verdict.get('applied')):
            off = float(offset_hint if offset_hint is not None
                        else verdict.get('offset_ms') or 0.0)
            scale = float(verdict.get('scale') or 1.0)
            if verdict.get('mode', 'global') == 'global' and scale == 1.0 and off:
                msg = 'הכתובית סונכרנה אוטומטית ({0:+.1f} שנ׳)'.format(
                    -off / 1000.0)
            else:
                msg = 'הכתובית סונכרנה אוטומטית'
            kodi_utils.notify(msg, time_ms=5000)
    except Exception:
        pass


def _fix_notice(verdict, offset_hint=None):
    try:
        off = float(offset_hint if offset_hint is not None
                    else verdict.get('offset_ms') or 0.0)
        scale = float(verdict.get('scale') or 1.0)
        if verdict.get('mode', 'global') == 'global' and scale == 1.0 and off:
            return 'הכתובית סונכרנה אוטומטית ({0:+.1f} שנ׳)'.format(
                -off / 1000.0)
    except Exception:
        pass
    return 'הכתובית סונכרנה אוטומטית'


def _job_matches_current(job):
    """Prove a background result still belongs to the visible stream/pick."""
    try:
        expected = {
            'token': job.get('selection_token') or '',
            'link_hash': job.get('selection_hash') or '',
            'stream_hash': job.get('stream_hash') or '',
        }
        pending = _pending_record(expected)
        # Old pre-token jobs may still be on disk after an update. They can be
        # computed/cached, but can never hot-swap or label a live selection.
        if not all(expected.values()):
            return False
        if (pending.get('key') != job.get('key')
                or pending.get('selection_token') != expected['token']
                or pending.get('selection_hash') != expected['link_hash']
                or pending.get('stream_hash') != expected['stream_hash']):
            return False
        return (_selection_matches(expected) and
                _job_stream_is_current(job))
    except Exception:
        return False


def _job_stream_is_current(job):
    """Prove only stream identity, independent of the subtitle selection."""
    try:
        import xbmc
        player = xbmc.Player()
        if not player.isPlaying():
            return False
        cur_url = _current_stream_url()
        job_url = (job.get('stream_url') or '').split('|')[0].strip()
        # Require the exact captured stream URL.  Some providers use one path
        # for every title and put the content identity in `?file=`/`?id=`;
        # dropping the query could therefore cross films.
        return bool(cur_url and job_url and cur_url == job_url)
    except Exception:
        return False


def _job_selection(job):
    return {
        'token': job.get('selection_token') or '',
        'link_hash': job.get('selection_hash') or '',
        'stream_hash': job.get('stream_hash') or '',
    }


def _wait_for_delivery_ack(job, timeout_ms=3000):
    """Wait until Kodi has registered/pinned the foreground subtitle.

    The service can claim a queue file before the picker callback delivers its
    original SRT. Swapping a correction first lets that later callback overwrite
    it while the UI falsely says FIXED. This bounded gate establishes the only
    safe order: original visibly selected, then verify/replace in background.
    """
    selection = _job_selection(job)
    path = job.get('path') or ''
    if not path or not all(selection.values()):
        return False
    try:
        import xbmc
        steps = max(1, min(120, int(max(0, timeout_ms) / 50) + 1))
        for attempt in range(steps):
            if not _job_matches_current(job):
                return False
            if kodi_utils.subtitle_delivery_is_applied(
                    path, selection=selection):
                return True
            if attempt + 1 < steps:
                xbmc.sleep(50)
    except Exception:
        return False
    return False


def _swap_if_current(job, fixed_path, verdict):
    """Swap the playing subtitle to the fixed copy -- ONLY if the user is
    still watching the same stream and hasn't picked a different subtitle
    since we delivered (the pending marker still names our job)."""
    try:
        import xbmc
        if not _job_matches_current(job):
            _log('swap skipped: selection or stream changed meanwhile')
            return False
        player = xbmc.Player()
        if not player.isPlaying():
            return False
        try:
            before = len(player.getAvailableSubtitleStreams() or [])
        except Exception:
            # Kodi gave us no positive observation channel. Applying remains
            # fail-open, but do not claim FIXED without proof of registration.
            before = -1
        player.setSubtitles(fixed_path)
        try:
            player.showSubtitles(True)
        except Exception:
            pass
        if before < 0:
            _log('fixed subtitle handed to Kodi; registration unobservable',
                 level='WARNING')
            return False
        for _ in range(20):  # setSubtitles posts asynchronously; wait <= 1s.
            xbmc.sleep(50)
            if not _job_matches_current(job):
                _log('swap confirmation abandoned: selection changed')
                return False
            try:
                streams = player.getAvailableSubtitleStreams() or []
            except Exception:
                return False
            if len(streams) > before:
                try:
                    player.setSubtitleStream(len(streams) - 1)
                except Exception:
                    _log('fixed subtitle registered but could not be selected',
                         level='WARNING')
                    return False
                if not _job_matches_current(job):
                    return False
                _log('fixed subtitle swapped in-place: ' + fixed_path)
                return True
        _log('fixed subtitle registration was not observed', level='WARNING')
        return False
    except Exception as e:
        _log('swap failed: %r' % e, level='WARNING')
        return False


def run_deep_job(job):
    """Service-side execution of one queued deep-verify job. Computes the
    verdict, and on FIXABLE swaps the playing subtitle in place. One gentle
    toast per pair, ever (see _announce). Never raises."""
    try:
        key = job.get('key') or ''
        path = job.get('path') or ''
        job_selection = _job_selection(job)

        def _finish_unverified(source):
            if (not job.get('identity_only')
                    and _job_matches_current(job)):
                _publish_selection_status(
                    'unverified', source, selection=job_selection)

        if not key or not path or not os.path.isfile(path):
            _finish_unverified('missing')
            return
        if not _job_stream_is_current(job):
            _log('deep job discarded: captured stream is no longer playing')
            return
        info = dict(job.get('info') or {})
        info['_subsync_stream_url'] = (
            (job.get('stream_url') or '').split('|')[0].strip())
        playing = job.get('playing') or ''
        # A release-exact subtitle needs no timing work.  Its tiny background
        # job exists solely to learn the content-derived cut id, so a later
        # manual delay is never shared with another cut carrying the same name.
        # It does not contact subtitle providers, Gemini or the timing oracle.
        if job.get('identity_only'):
            cut_signature = _learn_cut_signature(info)
            if (cut_signature and _job_matches_current(job)):
                try:
                    with open(path, 'r', encoding='utf-8', errors='replace') as f:
                        text = f.read()
                except Exception:
                    text = ''
                if text.strip():
                    exact_key = _cache_key(text, playing, cut_signature)
                    _record_delivery(info, playing, exact_key, 1.0, 0.0,
                                     cut_signature=cut_signature,
                                     selection=job_selection)
            return
        # The foreground picker/chooser still owns the first application. Never
        # let this faster service thread apply a corrected copy before Kodi has
        # visibly registered and selected that original delivery.
        if not _wait_for_delivery_ack(job):
            _finish_unverified('delivery')
            _log('deep job deferred: foreground subtitle delivery unconfirmed',
                 level='WARNING')
            return
        # Someone may have computed it while the job sat in the queue.
        cached = _load_verdicts().get(key)
        if (cached and cached.get('v') == _VERDICT_VERSION
                and cached.get('status') in (
                    sync_align.STATUS_CONFIRMED, sync_align.STATUS_UNKNOWN)):
            if _job_matches_current(job):
                if cached.get('status') == sync_align.STATUS_CONFIRMED:
                    _publish_selection_status(
                        'confirmed', 'cache', selection=job_selection)
                else:
                    _publish_selection_status(
                        'unverified', 'cache', selection=job_selection)
            return
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
        except Exception:
            _finish_unverified('read-error')
            return
        if not text.strip():
            _finish_unverified('empty')
            return
        rel = job.get('release') or ''
        out, verdict = _deep_verify(info, path, text, rel, playing, key)
        if not verdict:
            _finish_unverified('no-result')
            return
        swapped = False
        current = _job_matches_current(job)
        if (verdict.get('status') == sync_align.STATUS_FIXABLE
                and verdict.get('applied') and out and out != path):
            swapped = _swap_if_current(job, out, verdict)
            if swapped:
                # Refresh the delivery record with the APPLIED fix, so a later
                # manual delay on top of it folds into the human report right.
                if verdict.get('mode', 'global') == 'global':
                    _record_delivery(info, playing,
                                     verdict.get('cache_key') or key,
                                     verdict.get('scale', 1.0),
                                     verdict.get('offset_ms', 0.0),
                                     cut_signature=(
                                         verdict.get('cut_signature') or ''),
                                     selection=job_selection)
                else:
                    # The foreground path recorded the untouched subtitle as a
                    # global zero while verification ran.  Once a piecewise
                    # copy is swapped in, that stale scalar must disappear.
                    _clear_delivery(selection=job_selection)
        if current and not swapped:
            # The original subtitle is still on screen.  Refresh only its exact
            # cut identity (not an unapplied proposed shift), so any later manual
            # delay learns safely even after an UNKNOWN/CONFIRMED result.
            _record_delivery(info, playing,
                             verdict.get('cache_key') or key,
                             1.0, 0.0,
                             cut_signature=(
                                 verdict.get('cut_signature') or ''),
                             selection=job_selection)
            _publish_selection_status(
                'confirmed' if verdict.get('status')
                == sync_align.STATUS_CONFIRMED else 'unverified',
                'local', selection=job_selection)
        # Announce ONLY an actual in-place swap the user can see. A verdict
        # that couldn't be verified changes nothing on screen -> stay silent.
        if swapped:
            if _publish_selection_status(
                    'fixed', 'local', selection=job_selection):
                if _selection_matches(job_selection):
                    _announce(dict(verdict, applied=True), fresh=True,
                              selection=job_selection)
    except Exception as e:
        try:
            if _job_matches_current(job):
                _publish_selection_status(
                    'unverified', 'error', selection={
                        'token': job.get('selection_token') or '',
                        'link_hash': job.get('selection_hash') or '',
                        'stream_hash': job.get('stream_hash') or '',
                    })
        except Exception:
            pass
        _log('deep job failed: %r' % e, level='WARNING')


def drain_queue_once():
    """Pick up and run every queued deep job. Called by the service loop."""
    d = _queue_dir()
    if not d or not os.path.isdir(d):
        return 0
    ran = 0
    try:
        for fn in sorted(os.listdir(d)):
            if not fn.endswith('.json'):
                continue
            jpath = os.path.join(d, fn)
            job = None
            try:
                with open(jpath, 'r', encoding='utf-8') as f:
                    job = json.load(f)
            except Exception:
                job = None
            try:
                os.remove(jpath)   # claim before running
            except OSError:
                pass
            if job:
                try:
                    run_deep_job(job)
                finally:
                    if not job.get('identity_only'):
                        try:
                            kodi_utils.clear_subtitle_delivery(
                                job.get('path') or '',
                                selection=_job_selection(job))
                        except Exception:
                            pass
                    _clear_job_pending(job)
                ran += 1
    except Exception:
        pass
    return ran


def _write_fixed(orig_path, fixed_text):
    if not fixed_text or not fixed_text.strip():
        return ''
    try:
        base = os.path.basename(orig_path)
        for ext in ('.he.srt', '.srt'):
            if base.lower().endswith(ext):
                base = base[:-len(ext)]
                break
        # Kodi and subtitle add-ons reuse generic names such as
        # TempSubtitle.he.srt across titles. A basename-only output let a later
        # job overwrite the fixed file cached for another film. Content-address
        # the delivery copy so concurrent/history entries cannot collide.
        import hashlib
        digest = hashlib.sha1(
            fixed_text.encode('utf-8', 'replace')).hexdigest()[:12]
        out = os.path.join(
            kodi_utils.cache_dir(),
            '{0}.{1}.synced.he.srt'.format(base, digest))
        tmp = out + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(fixed_text)
        os.replace(tmp, out)
        return out
    except Exception as e:
        _log('write fixed failed: %r' % e, level='WARNING')
        return ''


def status_line(verdict):
    """Short Hebrew status for the overlay/toast, or '' for silent verdicts
    (quiet-by-default policy: only a CHANGE is announced)."""
    if not verdict:
        return ''
    st = verdict.get('status')
    if st == sync_align.STATUS_FIXABLE and verdict.get('applied'):
        off = float(verdict.get('offset_ms') or 0.0)
        scale = float(verdict.get('scale') or 1.0)
        if verdict.get('mode', 'global') == 'global' and scale == 1.0 and off:
            return 'הכתובית סונכרנה אוטומטית ({0:+.1f} שנ׳)'.format(-off / 1000.0)
        return 'הכתובית סונכרנה אוטומטית'
    return ''
