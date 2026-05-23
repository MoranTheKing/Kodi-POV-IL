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

import os
import re

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import kodi_utils

POV_ADDON_ID = 'plugin.video.pov'
MYSERVICES_REL_PATH = 'resources/lib/modules/myservices.py'

INJECT_VERSION = 1
MARKER = '# AI_SUBS_MYSERVICES_INJECT_v{0}'.format(INJECT_VERSION)
END_MARKER = '# END AI_SUBS_MYSERVICES_INJECT_v{0}'.format(INJECT_VERSION)
TUPLE_MARKER = "# AI_SUBS_MYSERVICES_TUPLE_v{0}".format(INJECT_VERSION)
OLD_MARKERS = []

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


class Gemini:
    icon = 'tmdb.png'  # reused; we don't ship a separate icon for now

    def __init__(self):
        self._ai = _ai_get_addon()
        try:
            v = self._ai.getSetting('api_key') if self._ai else ''
        except Exception:
            v = ''
        self.token = (v or '').strip()

    def set(self):
        cls_name = 'Gemini AI'
        if not self._ai:
            notification('Kodi POV IL AI subtitles addon not installed')
            return
        if self.token:
            if not confirm_dialog(): return
            try: self._ai.setSetting('api_key', '')
            except Exception: pass
            return notification('Removed %s Authorization' % cls_name)
        # First-time setup: explain where to get the key.
        kodi_utils.ok_dialog(
            heading='Gemini AI - איך משיגים API key',
            text=(
                'כדי שתרגום ה-AI יעבוד צריך API key חינמי של Gemini:\\n\\n'
                '1) פתח בדפדפן (במחשב/טלפון):\\n'
                '   https://aistudio.google.com/apikey\\n\\n'
                '2) התחבר עם חשבון Google רגיל. לחץ '
                '"Create API key" -> "Create API key in new project".\\n\\n'
                '3) העתק את המחרוזת שמתקבלת והדבק במסך הבא.\\n\\n'
                'התוכנית החינמית של Gemini מאפשרת ~500 בקשות ביום של '
                'מודל Flash Lite - מספיק לעשרות סרטים בלי לשלם.'
            ),
        )
        api_key = kodi_utils.dialog.input('Gemini API Key:').strip()
        if not api_key: return
        try: self._ai.setSetting('api_key', api_key)
        except Exception:
            return notification('Failed to write to AI subs addon')
        notification('Set %s Authorization' % cls_name)
        # Nudge the user about TMDB after setting up Gemini.
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


class Wyzie:
    icon = 'mdblist.png'  # reused placeholder

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
            item.setArt({{'icon': '%s%s' % (icon_path, api.icon)}})
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
'''.format(marker=MARKER, end_marker=END_MARKER)


def _myservices_path():
    if xbmcvfs is None:
        return None
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/{0}/{1}'.format(
                POV_ADDON_ID, MYSERVICES_REL_PATH))
    except Exception:
        return None


def ensure_patched():
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
