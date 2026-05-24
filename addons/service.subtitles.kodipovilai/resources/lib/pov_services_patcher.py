# Self-healing injection of two AI service entries (Gemini, Wyzie)
# into the POV plugin's "My Services" menu
# (plugin.video.pov/resources/lib/modules/myservices.py).
#
# The POV plugin owns its own "Connect Services" UI that's separate
# from the wizard's login_menu. It iterates a hardcoded tuple of
# (name, AuthClass) pairs in modules.myservices.authorize() -- there
# is no public registration API for adding new services. To get our
# entries in there we patch the file on disk and re-inject on every
# Kodi startup, same pattern as darksubs_patcher and wizard_patcher.
#
# The injected service classes are dead simple: they read the
# matching key (api_key for Gemini, wyzie_api_key for Wyzie) from
# *our* addon's settings (service.subtitles.kodipovilai), prompt for
# input when unset, and clear it when set. They write back through
# xbmcaddon directly because POV's get_setting/set_setting operate
# on the POV addon's own settings, not ours.

import hashlib
import os
import re
import shutil

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import kodi_utils

POV_ADDON_ID = 'plugin.video.pov'
MYSERVICES_REL_PATH = 'resources/lib/modules/myservices.py'
POV_MEDIA_REL_PATH = 'resources/skins/Default/media'

# Source paths for the two icons we ship.
ICON_SRC_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'icons')
ICON_FILENAMES = ('gemini.png', 'wyzie.png')

INJECT_VERSION = 5
MARKER = '# AI_SUBS_MYSERVICES_INJECT_v{0}'.format(INJECT_VERSION)
END_MARKER = '# END AI_SUBS_MYSERVICES_INJECT_v{0}'.format(INJECT_VERSION)
TUPLE_MARKER = "# AI_SUBS_MYSERVICES_TUPLE_v{0}".format(INJECT_VERSION)
# Version log:
#   v1 (addon v0.1.8): placeholder tmdb.png / mdblist.png icons.
#   v2 (addon v0.1.9-v0.2.1): custom gemini.png / wyzie.png icons.
#   v3 (addon v0.2.2): Wyzie first-time setup dialog mentions that
#     the All_Subs addon makes Wyzie redundant.
#   v4 (addon v0.2.3): same dialog, but uses "DarkSubs" (the
#     display name the user actually sees) instead of "All_Subs"
#     (the addon-id / folder-name) which was confusing.
#   v5 (addon v0.2.11): Gemini auth dialog gets a QR code for the
#     AI Studio URL (so users on a TV can scan with their phone)
#     and validates the entered key INLINE before saving -- if
#     Gemini rejects the key, we don't write it to settings and
#     instead loop with a retry prompt. Also gives users with an
#     already-set key a Test / Remove / Cancel chooser instead of
#     jumping straight to remove.
# Each bump triggers a one-time re-patch on the next Kodi startup;
# OLD_MARKERS lists every prior version's marker so the legacy
# blocks get stripped cleanly before the new one is injected.
OLD_MARKERS = [
    '# AI_SUBS_MYSERVICES_INJECT_v1',
    '# AI_SUBS_MYSERVICES_INJECT_v2',
    '# AI_SUBS_MYSERVICES_INJECT_v3',
    '# AI_SUBS_MYSERVICES_INJECT_v4',
]

# Two service classes plus a hook that monkey-patches authorize()
# to include them. We do NOT edit the authorize() function source --
# instead we wrap it after definition. Cleaner + survives most
# refactors of the inline tuple.
CLASS_BLOCK = '''\

{marker}
# Injected by service.subtitles.kodipovilai. See pov_services_patcher.py.

import xbmcaddon as _ai_xbmcaddon


def _ai_get_addon():
    try:
        return _ai_xbmcaddon.Addon('service.subtitles.kodipovilai')
    except Exception:
        return None


_AI_GEMINI_KEY_URL = 'https://aistudio.google.com/apikey'


def _ai_gemini_validate(api_key):
    """Inline test of a Gemini API key. Hits the public /models
    endpoint with the supplied key and returns (ok, message). Done
    here rather than via `from resources.lib import gemini` to avoid
    sys.path conflicts inside POV's own resources namespace.

    Status mapping mirrors gemini.test_key:
      200 + models present     -> ok
      400 / 403                -> key rejected
      429                      -> quota
      5xx                      -> service issue
      timeout / network        -> reachable error
    """
    try:
        import requests as _ai_req
        import urllib.parse as _ai_up
    except ImportError:
        return False, 'requests library not available'
    if not api_key:
        return False, 'אין key להזנה'
    url = ('https://generativelanguage.googleapis.com/v1/models'
           '?key=' + _ai_up.quote(api_key, safe=''))
    try:
        r = _ai_req.get(url, timeout=10)
    except _ai_req.Timeout:
        return False, ('Gemini לא הגיב תוך 10 שניות. נסה שוב או '
                       'בדוק שיש לך חיבור אינטרנט.')
    except _ai_req.RequestException as e:
        return False, 'שגיאת רשת: {0}'.format(str(e)[:80])
    s = r.status_code
    if s in (400, 403):
        return False, ('ה-key נדחה ע"י Gemini (HTTP {0}). '
                       'בדוק שהעתקת אותו במלואו ושהוא תקין.'.format(s))
    if s == 429:
        return False, ('חרגת מהמכסה היומית. נסה שוב מאוחר יותר.')
    if 500 <= s < 600:
        return False, ('Gemini במצב תקלה זמני (HTTP {0}). נסה שוב '
                       'בעוד מספר דקות.'.format(s))
    if s != 200:
        return False, 'תגובה בלתי צפויה (HTTP {0})'.format(s)
    try:
        data = r.json()
    except Exception:
        return False, 'תגובה לא תקינה מ-Gemini (לא JSON)'
    n = len(data.get('models', []))
    if not n:
        return False, ('Gemini החזיר 0 מודלים זמינים -- ה-key '
                       'כנראה מוגבל או לא מאופשר.')
    return True, '✓ ה-key תקין. {0} מודלים זמינים.'.format(n)


def _ai_gemini_show_qr_and_get_key():
    """Show a progress dialog with a QR code for the Gemini API
    Studio URL, count down 3 minutes, and let the user dismiss
    early. Then prompt for the API key string. Returns the
    typed key (stripped) or '' if the user cancelled."""
    try:
        from urllib.parse import quote as _ai_quote
    except ImportError:
        _ai_quote = lambda x: x
    qr_icon = qr_str % '&data=%s' % _ai_quote(_AI_GEMINI_KEY_URL)
    meta = {**dict.fromkeys(meta_keys.split(), ''), 'poster': qr_icon}
    detail = (
        'סרוק את ה-QR או פתח: %s' % _AI_GEMINI_KEY_URL,
        '1) Sign in -> "Create API key" -> בחר Project',
        '2) העתק את ה-key, חזור לכאן ולחץ סגור',
        '3) הדבק את ה-key במסך הבא',
    )
    expires_in = 180
    progress_dialog = _make_progress_dialog(meta=meta)
    for i in range(1, expires_in + 1):
        if progress_dialog.iscanceled():
            break
        remaining = expires_in - i
        lines = (await_str % divmod(remaining, 60),) + detail
        progress = 100 - int(100 * i / expires_in)
        try: progress_dialog.update('[CR]'.join(lines), progress)
        except Exception: pass
        sleep(1000)
    progress_dialog.close()
    try:
        return (kodi_utils.dialog.input('Gemini API Key:') or '').strip()
    except Exception:
        return ''


class Gemini:
    icon = 'gemini.png'  # copied into POV's media dir by pov_services_patcher

    def __init__(self):
        self._ai = _ai_get_addon()
        try:
            v = self._ai.getSetting('api_key') if self._ai else ''
        except Exception:
            v = ''
        self.token = (v or '').strip()

    def _save_and_nudge_tmdb(self, api_key):
        try:
            self._ai.setSetting('api_key', api_key)
        except Exception:
            notification('Failed to write to AI subs addon')
            return False
        notification('Set Gemini AI Authorization')
        kodi_utils.ok_dialog(
            heading='שלב הבא (אופציונלי): TMDB',
            text=(
                'כדי שהתרגום יבחין בזכר/נקבה לפי הדמויות בסרט, '
                'התוסף משתמש ב-API של TMDB דרך תוסף "TMDb Helper" '
                'שכבר מותקן בבילד.\\n\\n'
                'אם לא חיברת אותו עדיין, ב-"חיבור שירותים להרחבת POV" '
                'תמצא את "TMDB" - חבר אותו עם API key חינמי מ-'
                'themoviedb.org. בלי TMDB התרגום עובד אבל הזכר/נקבה '
                'הוא ניחוש מהקשר.'
            ),
        )
        return True

    def _input_validate_loop(self):
        """Show QR + URL, ask for key, validate, retry on failure.
        Returns True if a valid key was saved, False otherwise."""
        # First-time setup primer.
        kodi_utils.ok_dialog(
            heading='Gemini AI - איך משיגים API key',
            text=(
                'כדי שתרגום ה-AI יעבוד צריך API key חינמי של Gemini.\\n\\n'
                'במסך הבא יוצג QR code שמוביל ל-AI Studio של Google. '
                'סרוק עם הטלפון, או פתח את הקישור בדפדפן.\\n\\n'
                'התוכנית החינמית של Gemini מאפשרת ~500 בקשות ביום של '
                'מודל Flash Lite - מספיק לעשרות סרטים בלי לשלם.'
            ),
        )
        while True:
            api_key = _ai_gemini_show_qr_and_get_key()
            if not api_key:
                return False  # user cancelled the input dialog
            # Show a brief "checking..." notification so the user
            # knows we're doing something during the HTTP round-trip.
            notification('Gemini: בודק את ה-key...')
            ok, msg = _ai_gemini_validate(api_key)
            if ok:
                kodi_utils.ok_dialog(
                    heading='Gemini AI', text=msg)
                return self._save_and_nudge_tmdb(api_key)
            # Failure -- show the specific reason and offer retry.
            retry = confirm_dialog(
                heading='Gemini AI - הבדיקה נכשלה',
                text=msg + '\\n\\nלנסות שוב?')
            if not retry:
                return False  # user cancelled retry

    def _menu_for_existing_token(self):
        """Already-configured Gemini: let the user pick between
        testing the connection, replacing the key, or removing it.
        (Was just "remove?" yes/no in v4 and earlier.)"""
        choices = [
            '🔍 בדוק חיבור (Test connection)',
            '🔄 החלף key (Replace)',
            '❌ מחק key (Remove)',
        ]
        try:
            choice = kodi_utils.dialog.select(
                'Gemini AI - מה לעשות?', choices)
        except Exception:
            choice = -1
        if choice < 0:
            return  # user cancelled the chooser
        if choice == 0:
            notification('Gemini: בודק את ה-key...')
            ok, msg = _ai_gemini_validate(self.token)
            kodi_utils.ok_dialog(
                heading='Gemini AI', text=msg)
            return
        if choice == 1:
            # Replace: clear current token and run the input loop.
            self.token = ''
            try: self._ai.setSetting('api_key', '')
            except Exception: pass
            self._input_validate_loop()
            return
        if choice == 2:
            if not confirm_dialog():
                return
            try: self._ai.setSetting('api_key', '')
            except Exception: pass
            notification('Removed Gemini AI Authorization')
            return

    def set(self):
        if not self._ai:
            notification('Kodi POV IL AI subtitles addon not installed')
            return
        if self.token:
            self._menu_for_existing_token()
            return
        return self._input_validate_loop()


class Wyzie:
    icon = 'wyzie.png'  # copied into POV's media dir by pov_services_patcher

    def __init__(self):
        self._ai = _ai_get_addon()
        try:
            v = self._ai.getSetting('wyzie_api_key') if self._ai else ''
        except Exception:
            v = ''
        self.token = (v or '').strip()

    def set(self):
        cls_name = 'Wyzie'
        if not self._ai:
            notification('Kodi POV IL AI subtitles addon not installed')
            return
        if self.token:
            if not confirm_dialog(): return
            try: self._ai.setSetting('wyzie_api_key', '')
            except Exception: pass
            return notification('Removed %s Authorization' % cls_name)
        # First-time setup: nudge that Wyzie is optional. The build
        # ships DarkSubs (service.subtitles.All_Subs) which already
        # gives non-Hebrew sources -- clicking those triggers our AI
        # via the engine.py hook, no Wyzie needed. Users without
        # DarkSubs DO benefit from Wyzie, so we still offer it.
        try:
            _has_darksubs = False
            try:
                _ai_xbmcaddon.Addon('service.subtitles.All_Subs')
                _has_darksubs = True
            except Exception:
                pass
            if _has_darksubs:
                _msg = (
                    'שים לב: יש לך תוסף DarkSubs מותקן, אז Wyzie '
                    'בעצם לא נחוץ -- לחיצה על כתובית באנגלית (או כל '
                    'שפה לא-עברית) ב-DarkSubs כבר מפעילה את התרגום '
                    'AI שלי אוטומטית.\\n\\nאם בכל זאת אתה רוצה Wyzie '
                    'key (למשל למקור אונליין נוסף לתוך התוסף שלי, '
                    'בלי לעבור דרך DarkSubs):\\n'
                    'https://store.wyzie.io/redeem\\n'
                    '1000 בקשות ביום, חינם.'
                )
            else:
                _msg = (
                    'Wyzie נותן מקור כתוביות אונליין חינמי '
                    '(1000 בקשות ביום). הירשם ב-store.wyzie.io/'
                    'redeem, ואז הדבק את ה-key שתקבל במסך הבא.\\n\\n'
                    '(אופציונלי - אם תתקין בעתיד את התוסף '
                    'DarkSubs, תוכל לוותר על Wyzie לגמרי.)'
                )
            kodi_utils.ok_dialog(
                heading='Wyzie - איך משיגים API key', text=_msg)
        except Exception:
            pass
        api_key = kodi_utils.dialog.input('Wyzie API Key:').strip()
        if not api_key: return
        try: self._ai.setSetting('wyzie_api_key', api_key)
        except Exception:
            return notification('Failed to write to AI subs addon')
        notification('Set %s Authorization' % cls_name)
        return True


# Replace authorize() with a wrapper that adds our two services to
# the menu. We can't reliably regex-edit the inline tuple because
# the formatting might shift in upstream updates, so we wrap the
# function instead.
_ai_orig_authorize = authorize
def authorize():
    _ai_extra = (('gemini-ai', Gemini), ('wyzie', Wyzie))
    # Monkey-patch the module's `_builder` indirectly by replicating
    # authorize()'s logic exactly, but with our extras appended to
    # the services list. (We can't just call _orig_authorize and
    # then patch -- the dialog gets built INSIDE the function and
    # we'd have already shown the original.)
    def _builder():
        for name, api in services:
            item = kodi_utils.make_listitem()
            item.setLabel('[B]%s[/B]' % name.upper())
            item.setLabel2(auth_str if api().token else noauth_str)
            item.setArt({'icon': '%s%s' % (icon_path, api.icon)})
            yield(item)
    icon_path = kodi_utils.media_path()
    services = (
        ('trakt', Trakt), ('mdblist', MDBList), ('tmdblist', TMDBList),
        ('real-debrid', RealDebrid), ('premiumize.me', Premiumize),
        ('alldebrid', AllDebrid), ('torbox', TorBox),
        ('offcloud', Offcloud), ('easynews', EasyNews),
    ) + _ai_extra
    service = kodi_utils.dialog.select('My Services', list(_builder()), useDetails=True)
    if service < 0: return
    try: success = services[service][1]().set()
    except Exception as e: kodi_utils.logger('myservices error', str(e))
    else: return success
    return notification(32574)
{end_marker}
'''
# Replace the marker placeholders without using .format() -- the
# injected code body itself uses '{0}'-style placeholders inside
# its own .format() calls, and a single outer .format() would try
# to interpret those too and crash with IndexError.
CLASS_BLOCK = CLASS_BLOCK.replace('{marker}', MARKER) \
                         .replace('{end_marker}', END_MARKER)


def _myservices_path():
    if xbmcvfs is None:
        return None
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/{0}/{1}'.format(
                POV_ADDON_ID, MYSERVICES_REL_PATH))
    except Exception:
        return None


def _pov_media_dir():
    if xbmcvfs is None:
        return None
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/{0}/{1}'.format(
                POV_ADDON_ID, POV_MEDIA_REL_PATH))
    except Exception:
        return None


def _sha1(path):
    try:
        h = hashlib.sha1()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _ensure_icons_copied():
    """Copy gemini.png + wyzie.png from our addon's icons dir into
    POV's media folder if missing or different. Idempotent.

    Returns the number of icons newly written (0 = no change needed).
    """
    media_dir = _pov_media_dir()
    if not media_dir or not os.path.isdir(media_dir):
        return 0
    written = 0
    for name in ICON_FILENAMES:
        src = os.path.join(ICON_SRC_DIR, name)
        if not os.path.isfile(src):
            kodi_utils.log(
                'pov_services_patcher: icon source missing: {0}'.format(
                    src), level='WARNING')
            continue
        dst = os.path.join(media_dir, name)
        if os.path.isfile(dst) and _sha1(src) == _sha1(dst):
            continue  # already up to date
        try:
            tmp = dst + '.aitmp'
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
            written += 1
            kodi_utils.log(
                'pov_services_patcher: installed icon {0}'.format(name),
                level='INFO')
        except OSError as e:
            kodi_utils.log(
                'pov_services_patcher: icon copy failed {0}: {1}'
                .format(name, e), level='WARNING')
    return written


def ensure_patched():
    # Always make sure the icons are in place, even when myservices.py
    # is already patched -- handles the case where the icons got
    # blown away by a POV update but the marker block in the .py is
    # still there.
    _ensure_icons_copied()

    p = _myservices_path()
    if not p or not os.path.isfile(p):
        return 'no_pov'
    try:
        with open(p, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        kodi_utils.log(
            'pov_services_patcher: read failed: {0}'.format(e),
            level='WARNING')
        return 'read_failed'
    if MARKER in content:
        return 'already_patched'

    # Sanity: confirm authorize() and the expected service classes
    # are present in the file. If POV refactored the menu away from
    # this pattern, bail without touching it.
    if 'def authorize():' not in content:
        return 'unmatched'
    for cls in ('class Trakt', 'class RealDebrid', 'class Premiumize'):
        if cls not in content:
            kodi_utils.log(
                'pov_services_patcher: {0} not found, skipping'.format(
                    cls), level='WARNING')
            return 'unmatched'

    # Strip old-version markers if we ever bump.
    for old in OLD_MARKERS:
        old_end = old.replace('AI_SUBS_MYSERVICES_INJECT',
                              'END AI_SUBS_MYSERVICES_INJECT', 1)
        pattern = re.compile(
            r'^[ \t]*' + re.escape(old) + r'\b.*?^[ \t]*'
            + re.escape(old_end) + r'\b[^\n]*\n',
            re.MULTILINE | re.DOTALL,
        )
        content = pattern.sub('', content)

    if not content.endswith('\n'):
        content += '\n'
    new_content = content + CLASS_BLOCK

    tmp_path = p + '.aitmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp_path, p)
    except OSError as e:
        kodi_utils.log(
            'pov_services_patcher: write failed: {0}'.format(e),
            level='WARNING')
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return 'write_failed'
    kodi_utils.log(
        'pov_services_patcher: injected v{0} into POV myservices'.format(
            INJECT_VERSION),
        level='INFO')
    return 'patched'
