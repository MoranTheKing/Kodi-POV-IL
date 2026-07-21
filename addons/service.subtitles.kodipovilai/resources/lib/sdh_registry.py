# Local registry of content-detected SDH releases (Phase 3).
#
# WHY: a subtitle's SDH-ness can be read from its TEXT (dense bracketed sound
# cues / speaker labels / music glyphs -- srt.is_sdh_content), but the text is
# only available AFTER download, while the subtitle LIST is ranked from metadata
# only. So when we translate a source we classify it once and remember the
# releases that turned out to be SDH; the next time the same release is ranked,
# _is_sdh_ext consults this registry and can prefer + label it -- without having
# to download it first.
#
# This is a purely LOCAL, best-effort HINT: it is never authoritative (a
# whole-token release marker still wins first in _is_sdh_ext -- the provider's
# is_hi flag is no longer trusted at all, it produced false SDH labels), it only
# ever records releases classified SDH (never a negative),
# it is capped, and every operation fails open. A future Phase 3b could share
# this via a pool-backed registry so users benefit from each other's downloads.

import json

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

_PATH = ('special://profile/addon_data/service.subtitles.kodipovilai/'
         'sdh_registry.json')
_CAP = 800   # keep the file tiny; drop excess on write


def _translate(path):
    return xbmcvfs.translatePath(path) if xbmcvfs else path


def _load():
    """Return the registry as a dict {key: 1}. Fail-open to {}."""
    if xbmcvfs is None:
        return {}
    try:
        p = _translate(_PATH)
        if not xbmcvfs.exists(p):
            return {}
        with xbmcvfs.File(p) as f:
            raw = f.read()
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data):
    """Atomically write the registry (tmp + rename). Best-effort."""
    if xbmcvfs is None:
        return False
    try:
        if len(data) > _CAP:
            # Drop arbitrary excess -- this is a hint cache, exact retention
            # doesn't matter. dict preserves insertion order, so this keeps
            # the most recently added keys.
            data = dict(list(data.items())[-_CAP:])
        tmp = _translate(_PATH + '.tmp')
        f = xbmcvfs.File(tmp, 'w')
        try:
            ok = f.write(json.dumps(data, ensure_ascii=False))
        finally:
            f.close()
        if not ok:
            return False
        dst = _translate(_PATH)
        if xbmcvfs.rename(tmp, dst):
            return True
        # backend won't overwrite -> replace
        xbmcvfs.delete(dst)
        return bool(xbmcvfs.rename(tmp, dst))
    except Exception:
        return False


def _norm(key):
    return (key or '').strip().lower()


def is_known_sdh(key):
    """True iff `key` was previously recorded as content-detected SDH.
    Never raises."""
    k = _norm(key)
    if not k:
        return False
    try:
        return k in _load()
    except Exception:
        return False


def record_sdh(key):
    """Record `key` as a content-detected SDH release (idempotent). No-op on an
    empty key or if already present. Never raises."""
    k = _norm(key)
    if not k:
        return False
    try:
        data = _load()
        if k in data:
            return True
        data[k] = 1
        return _save(data)
    except Exception:
        return False
