# Track Gemini free-tier daily request usage, per model.
#
# Free-tier daily request caps differ a lot by model family, so the
# number we display has to follow the selected model:
#   * gemini-3.5-flash-lite / 3.1-flash-lite / 2.5-flash-lite -> ~500 requests/day
#   * gemini-3.8-flash / 3.7-flash / 3.6-flash / 3.5-flash / 3.1-flash /
#     2.5-flash (regular Flash) -> only ~20 requests/day (a very tight free
#     cap; regular Flash on the free tier is really a paid-key model).
# The count resets at UTC midnight. We persist it in hidden addon
# settings alongside the model it belongs to, and surface it in two
# places: appended to the end-of-translation toast, and as a dedicated
# "ניצול היום" entry in the My Services -> Gemini menu.
#
# Only free Flash / Flash-Lite models are tracked -- other models
# silently no-op through note_request(), because their free number
# would be either meaningless (paid-only) or something we can't state
# with confidence.
#
# Every public function is defensive: failures inside this module
# must never break translation. Callers wrap us in try/except too,
# as belt-and-braces.

import datetime
import threading

try:
    from resources.lib import kodi_utils
except Exception:
    try:
        from . import kodi_utils
    except Exception:
        kodi_utils = None


# Conservative free-tier daily request ceilings, keyed by lowercased
# model id. We sit at or under each model's real free RPD so the
# displayed number warns a touch early rather than surprising the user
# with a hard daily 429. The counter is informational only -- it never
# blocks translation. Keep this in sync with the model dropdown in
# settings.xml AND translate._gemini_free_rpm_cap() when adding a model.
MODEL_LIMITS = {
    'gemini-3.5-flash-lite': 500,
    'gemini-3.1-flash-lite': 500,
    'gemini-2.5-flash-lite': 500,
    'gemini-3.8-flash':      20,
    # 3.7 stays listed although the picker no longer offers it. A stored id
    # outlives a dropdown: a device that has not yet run the 3.8 migration, or
    # whose settings were restored from a backup, still asks this table for a
    # number, and dropping the row would silently hand it the 500/day
    # Flash-Lite fallback -- 25x the real free cap, on the one model where the
    # cap is tightest. Google lists 3.8 and 3.7 on identical limits.
    'gemini-3.7-flash':      20,
    'gemini-3.6-flash':      20,
    'gemini-3.5-flash':      20,
    'gemini-3.1-flash':      20,
    'gemini-2.5-flash':      20,
}
# Fallback limit + legacy default model (used when no model was stored
# yet, e.g. right after upgrading from the single-model version).
DEFAULT_LIMIT = 500
MODEL_TRACKED = 'gemini-3.5-flash-lite'

SETTING_COUNT = '_usage_count'
SETTING_DATE  = '_usage_date_utc'
SETTING_MODEL = '_usage_model'

# Serialise the read-modify-write in note_request(): two overlapping jobs on
# DIFFERENT models could otherwise interleave and stomp the shared counter.
_LOCK = threading.Lock()


def _today_utc():
    return datetime.datetime.utcnow().strftime('%Y-%m-%d')


def _norm(model):
    return (model or '').lower().strip()


def is_tracked(model):
    """True only for the free Flash / Flash-Lite models we count."""
    return _norm(model) in MODEL_LIMITS


def _limit_for(model):
    return MODEL_LIMITS.get(_norm(model), DEFAULT_LIMIT)


def _stored_model():
    """The model the persisted count belongs to. Missing (fresh upgrade)
    is treated as the legacy default so an existing Flash-Lite count is
    not reset for no reason."""
    try:
        if kodi_utils is not None:
            return (kodi_utils.get_setting(SETTING_MODEL, '') or '').strip() \
                or MODEL_TRACKED
    except Exception:
        pass
    return MODEL_TRACKED


def note_request(model):
    """Record one successful Gemini call. No-op if `model` isn't a
    tracked free model or if Kodi storage is unavailable. The count is
    scoped to (day, model): switching model or crossing UTC midnight
    starts a fresh count so the two families never conflate."""
    try:
        if not is_tracked(model) or kodi_utils is None:
            return
        model = _norm(model)
        today = _today_utc()
        with _LOCK:
            last_date = (kodi_utils.get_setting(SETTING_DATE, '') or '').strip()
            last_model = _stored_model()
            if last_date != today or last_model != model:
                count = 1
            else:
                count = kodi_utils.get_int(SETTING_COUNT, 0) + 1
            kodi_utils.set_setting(SETTING_COUNT, str(count))
            kodi_utils.set_setting(SETTING_DATE, today)
            kodi_utils.set_setting(SETTING_MODEL, model)
    except Exception:
        pass


def get_today_usage(model=None):
    """Return {count, limit, percent, remaining, date, model}. Always
    returns a dict; on storage failure, count is 0. `model` defaults to
    whichever model the stored count belongs to, so the limit shown
    matches the model that was actually used."""
    today = _today_utc()
    count = 0
    stored = _stored_model()
    target = _norm(model) or stored
    try:
        if kodi_utils is not None:
            last = (kodi_utils.get_setting(SETTING_DATE, '') or '').strip()
            # The stored count belongs to `target` only if the stored slot is
            # both today's AND for that same model; a different (or stale-date)
            # slot means `target` has had 0 requests today.
            if last == today and stored == target:
                count = max(0, kodi_utils.get_int(SETTING_COUNT, 0))
    except Exception:
        count = 0
    limit = _limit_for(target)
    pct = int(round(100.0 * count / limit)) if limit else 0
    remaining = max(0, limit - count)
    return {
        'count': count,
        'limit': limit,
        'percent': pct,
        'remaining': remaining,
        'date': today,
        'model': target,
    }


def format_status_short(model=None):
    """Compact one-liner for the post-translation toast."""
    u = get_today_usage(model)
    return '{0}/{1} ביום'.format(u['count'], u['limit'])


def format_status_long(model=None):
    """Multi-line text for a Dialog().ok() panel."""
    u = get_today_usage(model)
    note = ''
    if u['limit'] <= 50:
        # Regular Flash on the free tier: a handful of requests a day,
        # not enough for a full movie -- make that explicit.
        note = ('\n\nשים לב: ל-Flash הרגיל יש מכסה יומית נמוכה מאוד בחינם, '
                'שלרוב לא מספיקה אפילו לסרט אחד. הוא מתאים בעיקר למשתמשי '
                'Gemini API בתשלום (הדליקו את "מצב מהיר" בהגדרות).')
    return (
        'מודל: {model}\n'
        'נוצלו היום: {count} מתוך {limit} ({percent}%)\n'
        'נותרו עד איפוס: {remaining}\n\n'
        'איפוס המכסה: חצות UTC (~02:00 בישראל).\n'
        'הספירה מקומית למכשיר הזה ונספרת רק עבור מודלים חינמיים '
        '(Flash / Flash-Lite).'
    ).format(**u) + note
