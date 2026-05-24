# Track Gemini Flash Lite daily request usage.
#
# Free-tier gemini-3.1-flash-lite is capped around 500 requests/day
# and resets at UTC midnight. We persist a count in hidden addon
# settings and surface it in two places: appended to the
# end-of-translation toast, and as a dedicated "ניצול היום"
# entry in the My Services -> Gemini menu.
#
# Scope is intentionally narrow -- only gemini-3.1-flash-lite is
# counted, because that is the only model the user asked to track
# and the only one whose free-tier number we are confident about.
# Other models silently no-op through note_request().
#
# Every public function is defensive: failures inside this module
# must never break translation. Callers wrap us in try/except too,
# as belt-and-braces.

import datetime

try:
    from resources.lib import kodi_utils
except Exception:
    try:
        from . import kodi_utils
    except Exception:
        kodi_utils = None


MODEL_TRACKED = 'gemini-3.1-flash-lite'
DAILY_LIMIT = 500

SETTING_COUNT = '_usage_count'
SETTING_DATE  = '_usage_date_utc'


def _today_utc():
    return datetime.datetime.utcnow().strftime('%Y-%m-%d')


def is_tracked(model):
    if not model:
        return False
    m = model.lower().strip()
    # Only the exact 3.1 Flash Lite id -- not 2.5 flash-lite, not
    # flash (without lite). Keeps the displayed number meaningful.
    return m == MODEL_TRACKED


def note_request(model):
    """Record one successful Gemini call. No-op if `model` isn't
    the one we track or if Kodi storage is unavailable."""
    try:
        if not is_tracked(model) or kodi_utils is None:
            return
        today = _today_utc()
        last = (kodi_utils.get_setting(SETTING_DATE, '') or '').strip()
        if last != today:
            count = 1
        else:
            count = kodi_utils.get_int(SETTING_COUNT, 0) + 1
        kodi_utils.set_setting(SETTING_COUNT, str(count))
        kodi_utils.set_setting(SETTING_DATE, today)
    except Exception:
        pass


def get_today_usage():
    """Return {count, limit, percent, remaining, date, model}.
    Always returns a dict; on storage failure, count is 0."""
    today = _today_utc()
    count = 0
    try:
        if kodi_utils is not None:
            last = (kodi_utils.get_setting(SETTING_DATE, '') or '').strip()
            if last == today:
                count = max(0, kodi_utils.get_int(SETTING_COUNT, 0))
    except Exception:
        count = 0
    limit = DAILY_LIMIT
    pct = int(round(100.0 * count / limit)) if limit else 0
    remaining = max(0, limit - count)
    return {
        'count': count,
        'limit': limit,
        'percent': pct,
        'remaining': remaining,
        'date': today,
        'model': MODEL_TRACKED,
    }


def format_status_short():
    """Compact one-liner for the post-translation toast."""
    u = get_today_usage()
    return '{0}/{1} ביום'.format(u['count'], u['limit'])


def format_status_long():
    """Multi-line text for a Dialog().ok() panel."""
    u = get_today_usage()
    return (
        'מודל: {model}\n'
        'נוצלו היום: {count} מתוך {limit} ({percent}%)\n'
        'נותרו עד איפוס: {remaining}\n\n'
        'איפוס המכסה: חצות UTC (~02:00 בישראל).\n'
        'הספירה היא מקומית למכשיר הזה, ורק עבור '
        'gemini-3.1-flash-lite. מודלים אחרים לא נספרים.'
    ).format(**u)
