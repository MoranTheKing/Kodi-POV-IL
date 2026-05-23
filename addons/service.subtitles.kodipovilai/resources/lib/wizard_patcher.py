# Self-healing injection of the AI subtitle entries into the
# wizard's "Connect Services" menu.
#
# The wizard has AUTOUPDATE='No' hardcoded -- it never updates
# itself from build.txt. That means our v0.1.5 wizard (with the
# Gemini + Wyzie LOGINID entries) is sitting on GitHub but no
# existing user installation pulls it. Even after multiple Kodi
# restarts, users stay on 0.1.4 forever unless they manually
# reinstall the wizard.
#
# Workaround: same pattern as darksubs_patcher.py -- patch the
# wizard's loginit.py on disk to add our entries at the end of
# the file. Idempotent (marker-gated). Self-healing on every
# Kodi startup. If the wizard updates legitimately later, our
# patch gets wiped and we re-inject; if our patch sticks but the
# user uninstalls our addon, the wizard's login_menu just doesn't
# render those rows because System.HasAddon() returns False.

import os
import re

try:
    import xbmcvfs
except ImportError:
    xbmcvfs = None

from . import kodi_utils

WIZARD_ADDON_ID = 'plugin.program.kodipovilwizard'
LOGINIT_REL_PATH = 'resources/libs/loginit.py'
SETTINGS_REL_PATH = 'resources/settings.xml'

# Bump when the injected block changes.
INJECT_VERSION = 1
MARKER = '# AI_SUBS_LOGINIT_INJECT_v{0}'.format(INJECT_VERSION)
END_MARKER = '# END AI_SUBS_LOGINIT_INJECT_v{0}'.format(INJECT_VERSION)
# Older versions we should overwrite. Add to this list when bumping.
OLD_MARKERS = []

# Block appended to the end of loginit.py. Uses ORDER.extend +
# LOGINID dict assignment so it doesn't care WHERE in the file the
# upstream ORDER/LOGINID definitions are -- only that they exist as
# module-level names by the time this block runs.
INJECT_BLOCK = '''\

{marker}
# Injected by service.subtitles.kodipovilai. See wizard_patcher.py.
# The wizard's AUTOUPDATE is 'No', so existing installs never pull
# the upstream loginit.py changes that add these two entries -- we
# add them at runtime instead. Idempotent: if the names are already
# in ORDER (e.g. from a future fresh wizard install) we skip.
try:
    if 'gemini-kodipovilai' not in ORDER:
        ORDER.append('gemini-kodipovilai')
    if 'wyzie-kodipovilai' not in ORDER:
        ORDER.append('wyzie-kodipovilai')
    if 'gemini-kodipovilai' not in LOGINID:
        LOGINID['gemini-kodipovilai'] = {{
            'name'     : 'Gemini AI - תרגום כתוביות',
            'saved'    : 'gemini-kodipovilai',
            'plugin'   : 'service.subtitles.kodipovilai',
            'path'     : os.path.join(CONFIG.ADDONS, 'service.subtitles.kodipovilai'),
            'icon'     : os.path.join(CONFIG.ADDONS, 'service.subtitles.kodipovilai', 'icon.png'),
            'fanart'   : os.path.join(CONFIG.ADDONS, 'service.subtitles.kodipovilai', 'icon.png'),
            'file'     : os.path.join(CONFIG.LOGINFOLD, 'kodipovilai_gemini'),
            'settings' : os.path.join(CONFIG.ADDON_DATA, 'service.subtitles.kodipovilai', 'settings.xml'),
            'default'  : 'api_key',
            'data'     : ['api_key'],
            'activate' : ''}}
    if 'wyzie-kodipovilai' not in LOGINID:
        LOGINID['wyzie-kodipovilai'] = {{
            'name'     : 'Wyzie - מקור כתוביות לתרגום AI',
            'saved'    : 'wyzie-kodipovilai',
            'plugin'   : 'service.subtitles.kodipovilai',
            'path'     : os.path.join(CONFIG.ADDONS, 'service.subtitles.kodipovilai'),
            'icon'     : os.path.join(CONFIG.ADDONS, 'service.subtitles.kodipovilai', 'icon.png'),
            'fanart'   : os.path.join(CONFIG.ADDONS, 'service.subtitles.kodipovilai', 'icon.png'),
            'file'     : os.path.join(CONFIG.LOGINFOLD, 'kodipovilai_wyzie'),
            'settings' : os.path.join(CONFIG.ADDON_DATA, 'service.subtitles.kodipovilai', 'settings.xml'),
            'default'  : 'wyzie_api_key',
            'data'     : ['wyzie_api_key'],
            'activate' : ''}}
except Exception:
    # Never let the inject crash the wizard. Worst case the rows
    # don't appear; the user can wait for a real wizard update.
    pass
{end_marker}
'''.format(marker=MARKER, end_marker=END_MARKER)


def _loginit_path():
    if xbmcvfs is None:
        return None
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/{0}/{1}'.format(
                WIZARD_ADDON_ID, LOGINIT_REL_PATH))
    except Exception:
        return None


def _settings_path():
    if xbmcvfs is None:
        return None
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/{0}/{1}'.format(
                WIZARD_ADDON_ID, SETTINGS_REL_PATH))
    except Exception:
        return None


def _ensure_loginit_patched():
    p = _loginit_path()
    if not p or not os.path.isfile(p):
        return 'no_wizard'
    try:
        with open(p, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        kodi_utils.log(
            'wizard_patcher: read failed {0}: {1}'.format(p, e),
            level='WARNING')
        return 'read_failed'
    if MARKER in content:
        return 'already_patched'
    # Sanity: confirm ORDER and LOGINID exist as module-level
    # names. If the wizard's been refactored beyond recognition,
    # bail without touching it.
    if not re.search(r'^\s*ORDER\s*=\s*\[', content, re.MULTILINE):
        kodi_utils.log(
            'wizard_patcher: ORDER definition not found, skipping',
            level='WARNING')
        return 'unmatched'
    if not re.search(r'^\s*LOGINID\s*=\s*\{', content, re.MULTILINE):
        kodi_utils.log(
            'wizard_patcher: LOGINID definition not found, skipping',
            level='WARNING')
        return 'unmatched'

    # Strip old markers if we ever bump INJECT_VERSION.
    for old in OLD_MARKERS:
        old_end = old.replace('AI_SUBS_LOGINIT_INJECT',
                              'END AI_SUBS_LOGINIT_INJECT', 1)
        pattern = re.compile(
            r'^[ \t]*' + re.escape(old) + r'\b.*?^[ \t]*'
            + re.escape(old_end) + r'\b[^\n]*\n',
            re.MULTILINE | re.DOTALL,
        )
        content = pattern.sub('', content)

    # Append our block at the very end of the file.
    if not content.endswith('\n'):
        content += '\n'
    new_content = content + INJECT_BLOCK

    tmp_path = p + '.aitmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp_path, p)
    except OSError as e:
        kodi_utils.log(
            'wizard_patcher: write failed {0}: {1}'.format(p, e),
            level='WARNING')
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return 'write_failed'

    kodi_utils.log(
        'wizard_patcher: injected loginit entries v{0}'.format(
            INJECT_VERSION),
        level='INFO')
    return 'patched'


# Settings declarations the wizard needs to persist saved key data.
# Without these, CONFIG.get_setting('gemini-kodipovilai') returns ''
# and the "Saved Data" row would always be "Not Saved" even after
# the user clicks save.
SETTINGS_INJECT_LINES = (
    '        <setting id="gemini-kodipovilai" type="text" default="" visible="false"/>\n'
    '        <setting id="wyzie-kodipovilai" type="text" default="" visible="false"/>\n'
)
# Marker on the line above the closing </category> so we can detect
# previous injection without parsing XML.
SETTINGS_MARKER = '<!-- ai-subs-injected-v{0} -->'.format(INJECT_VERSION)


def _ensure_settings_patched():
    """Add our two <setting id="..."> entries to the wizard's
    settings.xml inside the same <category> that holds the existing
    login-* settings. We look for the line that contains
    'ws-wonderfulsubs' (the LAST existing login id alphabetically
    and definitionally) and insert our two lines right after it.
    If the marker is already present we bail.

    Editing XML by string surgery is fragile but the wizard's
    settings.xml is hand-maintained and shape-stable. We sanity-
    check that the closing </category> still appears after our
    insertion point; if not, bail."""
    p = _settings_path()
    if not p or not os.path.isfile(p):
        return 'no_wizard'
    try:
        with open(p, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError:
        return 'read_failed'
    if SETTINGS_MARKER in content:
        return 'already_patched'

    # Use the existing ws-wonderfulsubs line as the anchor.
    anchor_re = re.compile(
        r'^(\s*<setting id="ws-wonderfulsubs"[^/>]*/>\s*\n)',
        re.MULTILINE,
    )
    m = anchor_re.search(content)
    if not m:
        kodi_utils.log(
            'wizard_patcher: settings.xml anchor not found, skipping',
            level='WARNING')
        return 'unmatched'
    insertion = (m.group(1)
                 + SETTINGS_INJECT_LINES
                 + '        ' + SETTINGS_MARKER + '\n')
    new_content = (content[:m.start()] + insertion
                   + content[m.end():])
    # Cheap sanity-check: still well-formed enough to have a
    # </category> following our insertion.
    if '</category>' not in new_content[m.end():]:
        return 'unmatched'

    tmp_path = p + '.aitmp'
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp_path, p)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return 'write_failed'
    kodi_utils.log(
        'wizard_patcher: injected settings entries v{0}'.format(
            INJECT_VERSION),
        level='INFO')
    return 'patched'


def ensure_patched():
    """Run both patches. Returns a dict of {step: status}."""
    return {
        'loginit':  _ensure_loginit_patched(),
        'settings': _ensure_settings_patched(),
    }
