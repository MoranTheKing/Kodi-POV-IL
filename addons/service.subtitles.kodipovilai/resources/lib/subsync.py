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
# Trusted tiers need no verification at delivery time (same release / same
# group+source are de-facto synced; S3+ may still cross-check them cheaply).
_STATUS_TRUSTED = 'TRUSTED'
_STATUS_NO_ORACLE = 'NO_ORACLE'


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
        data[key] = {'ts': time.time(),
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
                out.append({'release': rel, 'payload': pl})
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

        # Trusted tier -> synced by release identity; nothing to do.
        rel = (delivered_release or '').strip()
        if rel:
            _pct, tier, _ = release_match.score(playing, rel)
            if tier in release_match.AUTO_OK_TIERS:
                return path, {'status': _STATUS_TRUSTED, 'tier': tier}

        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
        except OSError:
            return path, None
        if not text.strip():
            return path, None

        key = _cache_key(text, playing)
        cached = _load_verdicts().get(key)
        if cached:
            status = cached.get('status')
            if status == sync_align.STATUS_FIXABLE:
                fixed = sync_align.retime(text, cached.get('scale', 1.0),
                                          cached.get('offset_ms', 0.0))
                out = _write_fixed(path, fixed)
                if out:
                    _log('cached FIXABLE applied: ' + cached.get('diag', ''))
                    return out, {'status': status, 'applied': True,
                                 'offset_ms': cached.get('offset_ms', 0.0),
                                 'scale': cached.get('scale', 1.0),
                                 'diag': cached.get('diag', ''), 'cached': True}
            if status in (sync_align.STATUS_CONFIRMED,
                          sync_align.STATUS_UNKNOWN):
                return path, {'status': status, 'cached': True,
                              'diag': cached.get('diag', '')}

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
            fixed_text, verdict = sync_align.verify_and_fix(oracle_text, text)
            _log('verdict for %r vs oracle %r [%s]: %s'
                 % (rel or '?', oracle['release'], tier, verdict['diag']))
        else:
            # S4 fallback: no release-matched sub anywhere (or its download
            # failed) -> the playing FILE's own embedded track as the timing
            # reference. Covers releases no subtitle DB knows (ColdFilm-style
            # re-encodes); anchored to the actual file = strongest anchor.
            ref_cues = _probe_reference_cues(info, playing)
            if not ref_cues:
                return path, {'status': _STATUS_NO_ORACLE}
            verdict = sync_align.verify_cues(ref_cues, text)
            _log('verdict for %r vs FILE PROBE (%d ref cues): %s'
                 % (rel or '?', len(ref_cues), verdict['diag']))
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

        if verdict['status'] == sync_align.STATUS_FIXABLE:
            out = _write_fixed(path, fixed_text)
            if out:
                return out, dict(verdict, applied=True)
        return path, verdict
    except Exception as e:
        _log('process failed (fail-open): %r' % e, level='WARNING')
        return path, None


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
