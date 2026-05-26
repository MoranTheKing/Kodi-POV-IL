# Surface the state of the DarkSubs hook injection to the user so a
# silent failure doesn't masquerade as "AI subs not working". Two
# entry points:
#
#   1. surface_status_if_problem(): called once per Kodi startup from
#      service.py. If the patch failed for an actionable reason
#      (engine.py not found, signature mismatch, write/permission
#      error) AND we haven't already nagged the user about this
#      specific failure-state-version, pop a Hebrew toast pointing at
#      the addon settings "Test DarkSubs integration" entry.
#
#   2. run_full_check(): user-triggered self-test (default.py action
#      `darksubs_status`). Walks every link in the chain end-to-end
#      and shows a dialog summarising what works and what doesn't.
#
# Why both: the toast tells the user they need to look at SOMETHING;
# the dialog tells them exactly what's broken so they can either fix
# it themselves (e.g. re-enter the Gemini key) or report a specific
# failure mode to me. Silent fall-through to Google Translate has been
# the single most painful debugging scenario across CoreELEC, LibreELEC,
# stock Linux, and Windows installs alike -- no log, no signal,
# nothing for the user to look at.

import os

try:
    import xbmc
    import xbmcaddon
    import xbmcgui
    import xbmcvfs
except Exception:
    xbmc = xbmcaddon = xbmcgui = xbmcvfs = None

from . import kodi_utils
from . import darksubs_patcher


DARKSUBS_ADDON_ID = 'service.subtitles.All_Subs'
ENGINE_REL_PATH = 'resources/modules/engine.py'

# Bump when the surfaced-failure copy materially changes (so the
# nag toast pops once per upgrade where the text is now more useful).
NAG_VERSION = '1'


def _addon_path():
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/' + DARKSUBS_ADDON_ID + '/')
    except Exception:
        return ''


def _engine_path():
    base = _addon_path()
    if not base:
        return ''
    p = os.path.join(base, ENGINE_REL_PATH)
    return p if os.path.isfile(p) else ''


def _darksubs_installed():
    if xbmcaddon is None:
        return False
    try:
        xbmcaddon.Addon(DARKSUBS_ADDON_ID)
        return True
    except Exception:
        return False


def _read_engine_text():
    p = _engine_path()
    if not p:
        return ''
    try:
        with open(p, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return ''


def _diagnose():
    """Walk the integration end-to-end and return a structured
    result. Each entry is (label, ok_bool, detail_text).
    """
    out = []

    # 1. DarkSubs is installed.
    ds_installed = _darksubs_installed()
    out.append(('DarkSubs מותקן', ds_installed,
                'addon ID ' + DARKSUBS_ADDON_ID))

    # 2. engine.py is reachable on disk.
    engine = _engine_path()
    out.append(('engine.py נמצא על הדיסק', bool(engine),
                engine or 'לא נמצא -- '
                          'special://home/addons/' + DARKSUBS_ADDON_ID
                          + '/' + ENGINE_REL_PATH))

    # 3. engine.py is readable.
    content = _read_engine_text()
    out.append(('engine.py נקרא', bool(content),
                '{0} bytes'.format(len(content)) if content
                else 'open() נכשל -- הרשאות?'))

    # 4. Our hook marker is present in engine.py.
    marker_present = bool(content) and darksubs_patcher.MARKER in content
    out.append(('הוק AI מוזרק (marker {0})'.format(
                    darksubs_patcher.MARKER), marker_present,
                'marker נמצא בקובץ' if marker_present else
                'marker לא נמצא -- הפאצ\'ר לא תפס'))

    # 5. machine_translate_subs signature still matches our pattern.
    sig_matches = bool(content) and bool(
        darksubs_patcher._FUNC_DEF_RE.search(content))
    out.append(('machine_translate_subs בצורה מצופה', sig_matches,
                'regex תפס' if sig_matches else
                'DarkSubs upstream השתנה -- צריך לעדכן את ה-regex'))

    # 6. engine.py is writable (test by stat + open in append-then-truncate).
    writable = False
    if engine:
        try:
            with open(engine, 'r+', encoding='utf-8') as f:
                f.seek(0, 2)  # SEEK_END
            writable = True
        except OSError:
            writable = False
    out.append(('engine.py כתיב', writable,
                'יש הרשאת כתיבה' if writable else
                'read-only filesystem או הרשאה חסרה'))

    # 7. Gemini API key is configured in OUR addon.
    api_key = (kodi_utils.get_setting('api_key', '') or '').strip()
    has_key = bool(api_key)
    out.append(('Gemini API key מוגדר', has_key,
                '{0} תווים'.format(len(api_key)) if has_key
                else 'ריק -- הוק יחזור לגוגל תרגום'))

    # 8. DarkSubs auto_translate is on (otherwise machine_translate_subs
    #    is never called and the hook can't fire).
    auto_translate_on = False
    if ds_installed and xbmcaddon is not None:
        try:
            dark = xbmcaddon.Addon(DARKSUBS_ADDON_ID)
            v = (dark.getSetting('auto_translate') or '').lower()
            auto_translate_on = (v == 'true')
        except Exception:
            auto_translate_on = False
    out.append(('DarkSubs auto_translate מופעל', auto_translate_on,
                'מופעל' if auto_translate_on else
                'כבוי -- DarkSubs לא יקרא לתרגום מכונה בכלל'))

    return out


def _format_dialog_body(results):
    lines = []
    overall_ok = True
    for label, ok, detail in results:
        mark = '[COLOR lime]✓[/COLOR]' if ok else '[COLOR red]✗[/COLOR]'
        lines.append('{0} {1}'.format(mark, label))
        if not ok:
            overall_ok = False
            lines.append('   [COLOR grey]{0}[/COLOR]'.format(detail))
    if overall_ok:
        lines.append('')
        lines.append('[COLOR lime][B]הכל מחובר -- '
                     'תרגום ה-AI יפעל בלחיצה על כתובית '
                     'באנגלית מ-DarkSubs.[/B][/COLOR]')
    else:
        lines.append('')
        lines.append('[COLOR red][B]משהו לא מחובר. בלי לתקן את '
                     'הסעיפים האדומים, DarkSubs ימשיך לתרגם דרך '
                     'גוגל במקום AI.[/B][/COLOR]')
    return '\n'.join(lines)


def run_full_check():
    """User-triggered (default.py action=darksubs_status). Pops a
    big dialog with the diagnostic checklist."""
    if xbmcgui is None:
        return
    results = _diagnose()
    body = _format_dialog_body(results)
    try:
        xbmcgui.Dialog().textviewer('בדיקת חיבור DarkSubs', body)
    except Exception:
        try:
            xbmcgui.Dialog().ok('בדיקת חיבור DarkSubs', body)
        except Exception:
            pass


def _failure_class(results):
    """Compress the diagnostic into a single failure class identifier
    (or '' for "all good"). Used to gate the one-time toast."""
    by_label = {r[0]: r[1] for r in results}
    if not by_label.get('DarkSubs מותקן'):
        return ''  # not installed -- not a failure for the user
    if not by_label.get('engine.py נמצא על הדיסק'):
        return 'engine_missing'
    if not by_label.get('engine.py נקרא'):
        return 'engine_unreadable'
    if not by_label.get('machine_translate_subs בצורה מצופה'):
        return 'signature_changed'
    if not by_label.get('engine.py כתיב'):
        return 'engine_readonly'
    marker_label = next((k for k in by_label if k.startswith(
        'הוק AI מוזרק')), None)
    if marker_label and not by_label.get(marker_label):
        return 'hook_not_injected'
    if not by_label.get('Gemini API key מוגדר'):
        return 'no_api_key'
    if not by_label.get('DarkSubs auto_translate מופעל'):
        return 'auto_translate_off'
    return ''


_FAILURE_NAGS = {
    'engine_missing': 'DarkSubs לא נמצא בדיסק -- אם הוא מותקן, '
                      'נסה להפעיל את Kodi מחדש',
    'engine_unreadable': 'אין הרשאת קריאה ל-DarkSubs engine.py -- '
                        'בדוק הרשאות',
    'signature_changed': 'גרסת DarkSubs שלך השתנתה ולא תאמה לפאצ\'ר '
                         'שלי. דווח לי על הגרסה הזאת',
    'engine_readonly': 'מערכת הקבצים של DarkSubs לקריאה בלבד -- '
                       'הפאצ\'ר לא יכול לכתוב',
    'hook_not_injected': 'פאצ\'ר ה-AI לא תפס ב-DarkSubs. פתח את '
                         '"בדיקת חיבור DarkSubs" בתפריט',
    'no_api_key': 'אין מפתח Gemini -- DarkSubs ישתמש בגוגל תרגום '
                  'עד שתחבר',
    'auto_translate_off': 'DarkSubs auto_translate כבוי -- AI '
                          'לא יתורגם, הפעל בהגדרות DarkSubs',
}


def surface_status_if_problem():
    """Called once at Kodi startup from service.py. Pops a Hebrew
    toast if the integration has an actionable problem -- and only
    once per failure-class-version, so we don't spam on every boot.
    """
    if xbmc is None:
        return
    results = _diagnose()
    fclass = _failure_class(results)
    if not fclass:
        # Either everything's fine, or DarkSubs isn't installed.
        # Either way, no toast.
        kodi_utils.set_setting('_darksubs_nag_done',
                               'ok:' + NAG_VERSION)
        return
    nag_key = '{0}:{1}'.format(fclass, NAG_VERSION)
    if kodi_utils.get_setting('_darksubs_nag_done', '') == nag_key:
        return
    kodi_utils.set_setting('_darksubs_nag_done', nag_key)
    msg = _FAILURE_NAGS.get(fclass, 'יש בעיה בחיבור DarkSubs -- '
                                    'פתח "בדיקת חיבור DarkSubs"')
    try:
        kodi_utils.notify(msg, title='Kodi POV IL - AI Subtitles',
                          time_ms=8000)
    except Exception:
        pass
    kodi_utils.log(
        'DarkSubs integration nag: ' + fclass + ' -- ' + msg,
        level='WARNING')
