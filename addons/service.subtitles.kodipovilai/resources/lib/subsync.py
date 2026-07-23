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
_VERDICT_VERSION = 13
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


def _cache_key(sub_text, playing):
    h = hashlib.sha1(sub_text.encode('utf-8', 'replace')).hexdigest()[:16]
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


def _oracle_candidates(info):
    """Foreign-language engine candidates as [{'release', 'payload'}] -- the
    bridge's 24h result cache makes this cheap right after the picker/autosub
    built the list. Never raises."""
    out = []
    try:
        from resources.lib import subs_engine_bridge as bridge
        if not bridge.enabled():
            return out
        for c in bridge.search(info, modal_progress=False):
            if (c.get('language') or '') == 'he':
                continue
            if c.get('_engine_kind') not in (None, 'other'):
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
_PROBE_CACHE_VERSION = 2


def _probe_enabled():
    try:
        return (kodi_utils.get_setting('subsync_probe', 'true') or
                'true').strip().lower() != 'false'
    except Exception:
        return True


def _playing_url(info):
    """The URL/path of the file being played -- a direct http(s) stream
    (debrid) or a local file. '' when unavailable or not probeable (HLS,
    plugin:// etc.)."""
    url = ''
    try:
        import xbmc
        url = xbmc.Player().getPlayingFile() or ''
    except Exception:
        url = ''
    if not url:
        url = (info.get('filepath') or '').strip()
    low = (url or '').lower().split('|')[0]
    if not low:
        return ''
    if low.startswith(('http://', 'https://')):
        if '.m3u8' in low or 'manifest' in low:
            return ''
        return url.split('|')[0]
    if os.path.isfile(url):
        return url
    return ''


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
            return None
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


def _probe_reference_cues(info, playing):
    """Embedded-track cue times for the PLAYING file (S4 container probe),
    cached per release so the ranged reads happen once. None when the probe
    is disabled/unavailable/found nothing."""
    if not _probe_enabled():
        return None
    rel_key = (release_match.normalize(playing)
               if release_match else (playing or '').lower())
    cpath = _probe_cache_path()
    data = {}
    if cpath and os.path.isfile(cpath):
        try:
            with open(cpath, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
        except Exception:
            data = {}
        ent = data.get(rel_key)
        if ent is not None and ent.get('pv') != _PROBE_CACHE_VERSION:
            ent = None   # stored by an older probe engine -- re-probe
        if ent and isinstance(ent.get('cues'), list) and ent['cues']:
            _log('probe: cache hit for %r (%d cues)'
                 % (rel_key, len(ent['cues'])))
            return ent['cues']
        if ent is not None and not ent.get('cues'):
            return None   # remembered "nothing there" -- don't re-probe
    url = _playing_url(info)
    if not url:
        _log('probe: no probeable playing url')
        return None
    try:
        from resources.lib import mkv_probe
    except Exception:
        return None
    res = mkv_probe.subtitle_reference(url, log=lambda m: _log('probe: ' + m))
    cues = (res or {}).get('cues') or None
    try:
        if cpath:
            data[rel_key] = {'ts': time.time(), 'cues': cues or [],
                             'pv': _PROBE_CACHE_VERSION,
                             'track': (res or {}).get('track') or {}}
            if len(data) > _MAX_PROBE_ENTRIES:
                data = dict(sorted(data.items(),
                                   key=lambda kv: kv[1].get('ts', 0),
                                   reverse=True)[:_MAX_PROBE_ENTRIES])
            os.makedirs(os.path.dirname(cpath), exist_ok=True)
            tmp = cpath + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f)
            os.replace(tmp, cpath)
    except Exception as e:
        _log('probe cache store failed: %r' % e, level='WARNING')
    return cues


# ---- main entry -------------------------------------------------------------

def process(info, path, delivered_release):
    """Verify (and when confidently possible, FIX) the timing of the Hebrew
    sub at `path` against the playing release. Returns (final_path, verdict)
    where verdict is a dict with at least {'status'} plus 'applied': True when
    a retimed copy was written and returned, or (path, None) when SubSync did
    not run (disabled / no anchor / unreadable file). Fail-open, never raises."""
    try:
        if sync_align is None or release_match is None or not enabled():
            return path, None
        if not path or not os.path.isfile(path):
            return path, None
        playing = playing_release(info)
        if not playing:
            return path, None

        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
        except OSError:
            return path, None
        if not text.strip():
            return path, None
        key = _cache_key(text, playing)

        # Trusted tier -> synced by release identity; nothing to do (still
        # recorded so a manual-delay fix on it feeds the community registry).
        rel = (delivered_release or '').strip()
        if rel:
            _pct, tier, _ = release_match.score(playing, rel)
            if tier in release_match.AUTO_OK_TIERS:
                _record_delivery(info, playing, key, 1.0, 0.0)
                return path, {'status': _STATUS_TRUSTED, 'tier': tier}

        cached = _load_verdicts().get(key)
        if cached and cached.get('v') != _VERDICT_VERSION:
            cached = None   # stored by an older engine -- recompute
        if cached:
            status = cached.get('status')
            if status == sync_align.STATUS_FIXABLE:
                fixed = sync_align.retime(text, cached.get('scale', 1.0),
                                          cached.get('offset_ms', 0.0))
                out = _write_fixed(path, fixed)
                if out:
                    # Quiet on repeat plays: the fix was announced ONCE when it
                    # was first computed; from then on it just works silently.
                    _log('cached FIXABLE applied: ' + cached.get('diag', ''))
                    _record_delivery(info, playing, key,
                                     cached.get('scale', 1.0),
                                     cached.get('offset_ms', 0.0))
                    return out, {'status': status, 'applied': True,
                                 'offset_ms': cached.get('offset_ms', 0.0),
                                 'scale': cached.get('scale', 1.0),
                                 'diag': cached.get('diag', ''), 'cached': True}
            if status in (sync_align.STATUS_CONFIRMED,
                          sync_align.STATUS_UNKNOWN):
                _record_delivery(info, playing, key, 1.0, 0.0)
                return path, {'status': status, 'cached': True,
                              'diag': cached.get('diag', '')}

        # COMMUNITY registry (S3): a verdict some other device (or a human
        # delay-fix) already established for this exact (subtitle, release)
        # pair -- served inside the pool /lookup the picker already made, so
        # this is a dict lookup, not a request. First hit on THIS device gets
        # the one gentle toast; it's stored locally so repeats are silent.
        cv = _community_verdict(info, key, playing)
        if cv is not None:
            status = cv.get('status')
            if status == sync_align.STATUS_FIXABLE:
                fixed = sync_align.retime(text, cv.get('scale', 1.0),
                                          cv.get('offset_ms', 0.0))
                out = _write_fixed(path, fixed)
                if out:
                    _store_verdict(key, cv)
                    _log('community FIXABLE applied: ' + cv.get('diag', ''))
                    verdict = dict(cv, applied=True, community=True)
                    _record_delivery(info, playing, key,
                                     cv.get('scale', 1.0),
                                     cv.get('offset_ms', 0.0))
                    _announce(verdict, fresh=True)
                    return out, verdict
            elif status == sync_align.STATUS_CONFIRMED:
                _store_verdict(key, cv)
                _log('community CONFIRMED: ' + cv.get('diag', ''))
                _record_delivery(info, playing, key, 1.0, 0.0)
                return path, dict(cv, community=True)

        # DEEP verification needed (oracle download / file probe / audio) --
        # NEVER inline: it can take 10-30s and used to hold the autosub
        # "searching subtitles" overlay up (and the picker spinner) the whole
        # time. Hand the job to the long-lived service (same disk-queue
        # pattern as the he_warm drainer), deliver the ORIGINAL file now, and
        # let the worker swap in a fixed copy when (and only when) it proves
        # one -- self-healing delivery, per the plan's latency budget.
        _mark_pending(key)
        _record_delivery(info, playing, key, 1.0, 0.0)
        if _enqueue_deep(info, path, rel, playing, key):
            return path, {'status': 'PENDING'}
        # Queue unwritable (rare) -- fall back to the old synchronous path.
        out, verdict = _deep_verify(info, path, text, rel, playing, key)
        _announce(verdict, fresh=True)
        return out, verdict
    except Exception as e:
        _log('process failed (fail-open): %r' % e, level='WARNING')
        return path, None


def _community_verdict(info, key, playing):
    """A community /sync record for this (subtitle, release) pair, converted
    to a local-verdict dict -- or None. Never raises, never blocks (the map
    was stashed by the picker's pool lookup; at worst ONE throttled lookup)."""
    try:
        from resources.lib import pool as _pool
        sm = _pool.sync_map(info)
        if not sm:
            return None
        sub_hash = key.split('|', 1)[0]
        ent = sm.get(sub_hash + '|' + _pool.worker_norm_release(playing))
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


def _record_delivery(info, playing, key, scale, offset_ms):
    """Remember what we just delivered (and any applied fix), so the service's
    delay watcher can turn the viewer's manual subtitle-delay into a HUMAN
    community sync report -- the anchor of last resort."""
    try:
        import xbmcgui
        payload = {
            'key': key, 'playing': playing, 'ts': time.time(),
            'scale': float(scale or 1.0),
            'offset': float(offset_ms or 0.0),
            'info': {k: info.get(k) for k in _INFO_KEYS
                     if isinstance(info.get(k), (str, int, float, bool))},
        }
        xbmcgui.Window(10000).setProperty(
            _DELIVERED_PROP, json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass


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
        key = record.get('key') or ''
        playing = (record.get('playing') or '').strip()
        if not key or not playing:
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
                    'info': record.get('info') or {}}
        if watched_s >= 900 and abs(d) < 0.05:
            if base_scale == 1.0 and abs(base_off) < 1.0:
                return {'sub_hash': sub_hash, 'release': playing,
                        'scale': 1.0, 'offset_ms': 0.0,
                        'status': 'CONFIRMED', 'origin': 'human',
                        'info': record.get('info') or {}}
            # Zero manual delay on an APPLIED fix = a human vote that the fix
            # is right (agrees with the stored record -> just bumps votes).
            return {'sub_hash': sub_hash, 'release': playing,
                    'scale': base_scale, 'offset_ms': base_off,
                    'status': 'FIXABLE', 'origin': 'human',
                    'info': record.get('info') or {}}
        return None
    except Exception:
        return None


def _deep_verify(info, path, text, rel, playing, key):
    """The slow anchors: oracle sub -> file probe -> audio. Stores the verdict
    and returns (final_path, verdict). Runs in the SERVICE worker (or the rare
    synchronous fallback). Never raises."""
    try:
        # Need an oracle: best release-matched foreign sub for THIS release.
        cands = _oracle_candidates(info)
        oracle, tier = (sync_align.pick_oracle(cands, playing)
                        if cands else (None, ''))
        if oracle is None:
            # Diagnostic: show the closest candidates + their tier so a field
            # log tells us WHY nothing anchored (genuinely no matching release
            # vs a scorer gap). Also stamps the addon version so we can tell a
            # stale interpreter from a real miss.
            try:
                import xbmcaddon as _xa
                _ver = _xa.Addon().getAddonInfo('version')
            except Exception:
                _ver = '?'
            try:
                scored = sorted(
                    ((release_match.match_pct(playing, c['release']),
                      release_match.match_tier(playing, c['release']),
                      c['release']) for c in cands), reverse=True)[:5]
                top = '; '.join('%d%%/%s %r' % s for s in scored) or '-'
            except Exception:
                top = '?'
            _log('no oracle for release %r (%d foreign candidates, v%s); '
                 'closest: %s' % (playing, len(cands), _ver, top))
            oracle_text = ''
        else:
            oracle_text = _download_oracle(oracle['payload'])

        if oracle_text.strip():
            # A same-source (BluRay/DVD) oracle is the same disc master: pin the
            # alignment to identity scale and relax the coarse vote floor (see
            # the constants) so a real small offset a cross-language oracle
            # depressed to ~61% vote can still reach -- and be judged by -- the
            # graduated tight gate, instead of being dropped outright.
            okw = {}
            if tier == release_match.TIER_SOURCE:
                okw = {'scales': _ORACLE_SOURCE_SCALES,
                       'min_vote': _ORACLE_SOURCE_MIN_VOTE}
            fixed_text, verdict = sync_align.verify_and_fix(
                oracle_text, text, **okw)
            _log('verdict for %r vs oracle %r [%s]: %s'
                 % (rel or '?', oracle['release'], tier, verdict['diag']))
        else:
            # S4 fallback: no release-matched sub anywhere (or its download
            # failed) -> the playing FILE's own embedded track as the timing
            # reference. Covers releases no subtitle DB knows (ColdFilm-style
            # re-encodes); anchored to the actual file = strongest anchor.
            ref_kind = 'FILE PROBE'
            ref_cues = _probe_reference_cues(info, playing)
            # A SPARSE container-probe reference (high-bitrate 2160p files
            # yield few cues within the byte budget) has the same limitation
            # as an audio-VAD reference: it cannot support scale estimation.
            # Restrict to identity scale + a bounded window so a handful of
            # points can't be fit to a spurious FPS stretch (field: 16 cues
            # -> bogus scale=1.0427/-77s that failed the tight check). A dense
            # reference keeps the full scale search.
            if ref_cues and len(ref_cues) < _SPARSE_PROBE_CUES:
                gate_kw = {'scales': _AUDIO_SCALES,
                           'max_offset_ms': _AUDIO_MAX_OFFSET_MS}
            else:
                gate_kw = {}
            if not ref_cues:
                # S5 last resort: the file has no embedded subtitle track at
                # all (dubbed re-encodes) -> speech intervals from its AUDIO,
                # timestamped by Gemini. Relaxed gate (VAD boundaries are
                # softer than subtitle cues).
                ref_cues = _audio_probe_reference(info, playing)
                ref_kind = 'AUDIO PROBE'
                gate_kw = {'min_vote': _AUDIO_MIN_VOTE,
                           'min_overlap': _AUDIO_MIN_OVERLAP,
                           'scales': _AUDIO_SCALES,
                           'max_offset_ms': _AUDIO_MAX_OFFSET_MS}
            if not ref_cues:
                return path, {'status': _STATUS_NO_ORACLE}
            verdict = sync_align.verify_cues(ref_cues, text, **gate_kw)
            _log('verdict for %r vs %s (%d ref cues): %s'
                 % (rel or '?', ref_kind, len(ref_cues), verdict['diag']))
            # Adaptive second pass: a STRONG coarse peak that failed only the
            # tight check may just lack reference points -- sample two more
            # audio positions ONCE, merge, and re-judge.
            if (ref_kind == 'AUDIO PROBE'
                    and verdict['status'] == sync_align.STATUS_UNKNOWN
                    and 'tight check FAILED' in verdict.get('diag', '')
                    and verdict.get('vote', 0) >= 0.8):
                more = _audio_probe_reference(info, playing,
                                              second_pass=True)
                if more and len(more) > len(ref_cues):
                    verdict = sync_align.verify_cues(more, text, **gate_kw)
                    _log('verdict (pass 2, %d ref cues): %s'
                         % (len(more), verdict['diag']))
            fixed_text = None
            if verdict['status'] == sync_align.STATUS_FIXABLE:
                try:
                    fixed_text = sync_align.retime(
                        text, verdict['scale'], verdict['offset_ms'])
                except Exception:
                    fixed_text = None
                if not (fixed_text and fixed_text.strip()):
                    verdict = dict(verdict,
                                   status=sync_align.STATUS_UNKNOWN)

        _store_verdict(key, verdict)

        # S3: share the freshly-computed verdict with the community registry
        # (fire-and-forget, share-gated, once -- the verdict cache guarantees
        # this pair never recomputes, so it never re-reports either).
        try:
            if verdict['status'] in (sync_align.STATUS_CONFIRMED,
                                     sync_align.STATUS_FIXABLE):
                from resources.lib import pool as _pool
                _pool.report_sync(info, key.split('|', 1)[0], playing,
                                  verdict.get('scale', 1.0),
                                  verdict.get('offset_ms', 0.0),
                                  verdict['status'], origin='auto')
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


def _mark_pending(key):
    """Remember which (sub, release) pair we delivered un-verified, so the
    worker only swaps if the user hasn't picked something else meanwhile."""
    try:
        import xbmcgui
        xbmcgui.Window(10000).setProperty(
            _PENDING_PROP, json.dumps({'key': key, 'ts': time.time()}))
    except Exception:
        pass


def _pending_key():
    try:
        import xbmcgui
        raw = xbmcgui.Window(10000).getProperty(_PENDING_PROP) or ''
        return (json.loads(raw) or {}).get('key', '') if raw else ''
    except Exception:
        return ''


def _enqueue_deep(info, path, rel, playing, key):
    """Drop a deep-verify job for the service drainer. True on success."""
    d = _queue_dir()
    if not d:
        return False
    try:
        os.makedirs(d, exist_ok=True)
        safe = re.sub(r'[^0-9A-Za-z]+', '_', key)[:80] or 'job'
        jpath = os.path.join(d, safe + '.json')
        try:
            if (os.path.isfile(jpath)
                    and time.time() - os.path.getmtime(jpath) < _JOB_FRESH_S):
                return True   # identical job already queued
        except OSError:
            pass
        job = {
            'key': key, 'path': path, 'release': rel, 'playing': playing,
            'ts': time.time(),
            'info': {k: info.get(k) for k in _INFO_KEYS
                     if isinstance(info.get(k), (str, int, float, bool))},
        }
        tmp = jpath + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(job, f, ensure_ascii=False)
        os.replace(tmp, jpath)
        _log('deep job enqueued for %r' % key)
        return True
    except Exception as e:
        _log('enqueue failed: %r' % e, level='WARNING')
        return False


def _announce(verdict, fresh, offset_hint=None):
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
        if (verdict.get('status') == sync_align.STATUS_FIXABLE
                and verdict.get('applied')):
            off = float(offset_hint if offset_hint is not None
                        else verdict.get('offset_ms') or 0.0)
            scale = float(verdict.get('scale') or 1.0)
            if scale == 1.0 and off:
                msg = 'הכתובית סונכרנה אוטומטית ({0:+.1f} שנ׳)'.format(
                    -off / 1000.0)
            else:
                msg = 'הכתובית סונכרנה אוטומטית'
            kodi_utils.notify(msg, time_ms=5000)
    except Exception:
        pass


def _swap_if_current(job, fixed_path, verdict):
    """Swap the playing subtitle to the fixed copy -- ONLY if the user is
    still watching the same stream and hasn't picked a different subtitle
    since we delivered (the pending marker still names our job)."""
    try:
        import xbmc
        if _pending_key() != job.get('key'):
            _log('swap skipped: user picked something else meanwhile')
            return False
        player = xbmc.Player()
        if not player.isPlaying():
            return False
        try:
            cur_url = (player.getPlayingFile() or '').split('|')[0]
        except Exception:
            cur_url = ''
        job_url = (job.get('info', {}).get('filepath') or '')
        # Same stream check is best-effort: tokens rotate between plays, so
        # compare only when both sides exist.
        if cur_url and job_url and cur_url.split('?')[0] != job_url.split('|')[0].split('?')[0]:
            _log('swap skipped: different stream playing')
            return False
        player.setSubtitles(fixed_path)
        try:
            import xbmcgui
            xbmcgui.Window(10000).clearProperty(_PENDING_PROP)
        except Exception:
            pass
        _log('fixed subtitle swapped in-place: ' + fixed_path)
        return True
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
        if not key or not path or not os.path.isfile(path):
            return
        # Someone may have computed it while the job sat in the queue.
        cached = _load_verdicts().get(key)
        if cached and cached.get('v') == _VERDICT_VERSION:
            return
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
        except OSError:
            return
        if not text.strip():
            return
        info = job.get('info') or {}
        playing = job.get('playing') or ''
        rel = job.get('release') or ''
        out, verdict = _deep_verify(info, path, text, rel, playing, key)
        if not verdict:
            return
        swapped = False
        if (verdict.get('status') == sync_align.STATUS_FIXABLE
                and verdict.get('applied') and out and out != path):
            swapped = _swap_if_current(job, out, verdict)
            if swapped:
                # Refresh the delivery record with the APPLIED fix, so a later
                # manual delay on top of it folds into the human report right.
                _record_delivery(info, playing, key,
                                 verdict.get('scale', 1.0),
                                 verdict.get('offset_ms', 0.0))
        # Announce ONLY an actual in-place swap the user can see. A verdict
        # that couldn't be verified changes nothing on screen -> stay silent.
        if swapped:
            _announce(dict(verdict, applied=True), fresh=True)
    except Exception as e:
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
                run_deep_job(job)
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
        out = os.path.join(kodi_utils.cache_dir(), base + '.synced.he.srt')
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
        if scale == 1.0 and off:
            return 'הכתובית סונכרנה אוטומטית ({0:+.1f} שנ׳)'.format(-off / 1000.0)
        return 'הכתובית סונכרנה אוטומטית'
    return ''
