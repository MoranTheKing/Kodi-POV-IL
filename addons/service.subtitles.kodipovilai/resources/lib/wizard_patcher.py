# Cleanup utility for the (incorrect) wizard "Connect Services"
# injection that v0.1.5-v0.1.7 of this addon shipped.
#
# Background: we originally added Gemini AI + Wyzie entries to
# plugin.program.kodipovilwizard's loginit.py / settings.xml, on
# the assumption that the wizard's login_menu was the "Connect
# Services" UI the user was looking at. It wasn't -- the right
# UI is plugin.video.pov's own My Services menu (handled by the
# new pov_services_patcher). So this module now just REMOVES the
# leftover injection from the wizard files if it's still there,
# so the rows don't show up in the wrong place after upgrade.
#
# This file used to do the additive patching; the additive code
# was deleted entirely in v0.1.8. Idempotent: if the marker
# isn't found, no file write happens.

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

# Markers we previously wrote. If any are present, strip them.
LOGINIT_MARKER = '# AI_SUBS_LOGINIT_INJECT_v1'
LOGINIT_END_MARKER = '# END AI_SUBS_LOGINIT_INJECT_v1'
SETTINGS_MARKER = '<!-- ai-subs-injected-v1 -->'


def _path(rel):
    if xbmcvfs is None:
        return None
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/{0}/{1}'.format(
                WIZARD_ADDON_ID, rel))
    except Exception:
        return None


def _strip_loginit_injection(content):
    """Remove the AI_SUBS_LOGINIT_INJECT_v1 block (and any leading
    whitespace line we may have left when appending). Returns
    (new_content, changed_bool)."""
    if LOGINIT_MARKER not in content:
        return content, False
    # The injection was appended at end of file as a multi-line
    # try/except wrapped in MARKER ... END_MARKER. Match from the
    # marker line through the end marker line inclusive.
    pattern = re.compile(
        r'[ \t]*' + re.escape(LOGINIT_MARKER) + r'\b.*?'
        + re.escape(LOGINIT_END_MARKER) + r'\b[^\n]*\n?',
        re.DOTALL,
    )
    new = pattern.sub('', content)
    # Strip the trailing blank line(s) left by the appended block.
    new = new.rstrip('\n') + '\n'
    return new, True


def _strip_settings_injection(content):
    """Remove the two <setting id="gemini-kodipovilai"> /
    <setting id="wyzie-kodipovilai"> lines + the marker comment
    we inserted right after the existing ws-wonderfulsubs line."""
    if SETTINGS_MARKER not in content:
        return content, False
    # We inserted: two <setting .../> lines + a <!-- marker -->
    # line right after the ws-wonderfulsubs line. Match those
    # three lines together.
    pattern = re.compile(
        r'^[ \t]*<setting id="gemini-kodipovilai"[^/>]*/>\s*\n'
        r'[ \t]*<setting id="wyzie-kodipovilai"[^/>]*/>\s*\n'
        r'[ \t]*' + re.escape(SETTINGS_MARKER) + r'\s*\n',
        re.MULTILINE,
    )
    new, n = pattern.subn('', content)
    return new, n > 0


def _atomic_write(path, content):
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(content)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def ensure_unpatched():
    """If the loginit / settings files still carry our v1
    injection markers, strip them. Idempotent + safe on every
    Kodi startup."""
    result = {'loginit': 'no_change', 'settings': 'no_change'}

    li = _path(LOGINIT_REL_PATH)
    if li and os.path.isfile(li):
        try:
            with open(li, 'r', encoding='utf-8') as f:
                content = f.read()
        except OSError:
            content = None
        if content is not None:
            new, changed = _strip_loginit_injection(content)
            if changed and _atomic_write(li, new):
                result['loginit'] = 'cleaned'
                kodi_utils.log(
                    'wizard_patcher: removed stale loginit injection',
                    level='INFO')
            elif changed:
                result['loginit'] = 'write_failed'

    sx = _path(SETTINGS_REL_PATH)
    if sx and os.path.isfile(sx):
        try:
            with open(sx, 'r', encoding='utf-8') as f:
                content = f.read()
        except OSError:
            content = None
        if content is not None:
            new, changed = _strip_settings_injection(content)
            if changed and _atomic_write(sx, new):
                result['settings'] = 'cleaned'
                kodi_utils.log(
                    'wizard_patcher: removed stale settings injection',
                    level='INFO')
            elif changed:
                result['settings'] = 'write_failed'

    return result
