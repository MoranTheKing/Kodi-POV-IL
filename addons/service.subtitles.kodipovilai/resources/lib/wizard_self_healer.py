# One-shot self-healer for the bundled Kodi POV IL Wizard.
#
# v2 (bundled): the wizard zip travels INSIDE this addon at
# resources/staged_wizard.zip. No download, no SSL, no network --
# all of which were failing silently in v1 against an Android Kodi
# user (no toast appeared after quick_update + restart).
#
# Why this healer exists at all: the wizard's quick_update extracts
# the quickfix via extract.all (resources/libs/extract.py), which
# has a safety guard that skips any file whose path contains
# CONFIG.ADDON_ID -- the wizard's own id. The intent was "don't
# let the wizard trash itself mid-extract." The side effect was
# that every wizard-update shipped via quick_update was silently
# dropped: the addon DB record got bumped, but the .py files on
# disk stayed at the pre-update version. PR #161 (AF3 third skin)
# was the first time the bug was *visible* to users -- Switch Skin
# kept listing only Estuary + FENtastic after quick_update + restart.
#
# Wizard 0.1.10 patches extract.all to take ignore=True, so future
# quick_updates ship the wizard cleanly. But users currently stuck
# on the pre-fix wizard can't get the fix via the broken pipe.
# This healer rides the AI subs quickfix path (different addon id,
# not skipped), detects the stuck-wizard fingerprint via a sentinel
# byte string in the installed wizard.py, and extracts the bundled
# zip directly over the installed wizard's addon dir.
#
# Idempotent: a marker file inside the wizard's addon dir gates
# re-runs. Self-disarms once the installed wizard.py contains the
# 0.1.10 ignore-bypass fingerprint -- after that the regular
# quick_update path takes over and this healer becomes a no-op.
#
# UX: on successful heal a MODAL Dialog().ok pops -- user must
# tap OK before continuing, then must restart Kodi for Python to
# reload the new wizard module. A toast also fires on most
# failure modes so users have signal even when the heal can't
# complete.

import os
import shutil
import zipfile

try:
    import xbmcaddon
    import xbmcgui
    import xbmcvfs
except ImportError:
    xbmcaddon = None
    xbmcgui = None
    xbmcvfs = None

try:
    import xbmc
except ImportError:
    xbmc = None

from . import kodi_utils


AI_SUBS_ADDON_ID = 'service.subtitles.kodipovilai'
WIZARD_ADDON_ID = 'plugin.program.kodipovilwizard'

# Sentinel inside the installed wizard.py that proves the
# extract.all self-skip bug has been fixed (wizard >= 0.1.10).
# Once present, this healer is permanently a no-op for that
# install -- the wizard can self-update going forward.
HEALED_SENTINEL = b'ignore=True bypasses extract.all'

# Marker file written into the wizard's addon dir on success so
# repeated boots don't repeat the work on a healthy install.
# Versioned so we can re-trigger if a future bug requires it.
MARKER_NAME = '.ai_subs_wizard_healed_v2'

STAGED_ZIP_REL = os.path.join('resources', 'staged_wizard.zip')


def _log(msg, level='INFO'):
    try:
        kodi_utils.log(
            'wizard_self_healer: ' + msg, level=level)
    except Exception:
        if xbmc is not None:
            try:
                xbmc.log(
                    '[wizard_self_healer] ' + msg,
                    level=xbmc.LOGINFO if level == 'INFO'
                    else xbmc.LOGWARNING,
                )
            except Exception:
                pass


def _ai_subs_base():
    """Path to this addon's directory -- the staged zip lives
    inside it. translatePath handles Android's split-storage."""
    if xbmcaddon is None:
        return ''
    try:
        return xbmcvfs.translatePath(
            xbmcaddon.Addon(AI_SUBS_ADDON_ID).getAddonInfo('path'))
    except Exception:
        return ''


def _wizard_base():
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(
            'special://home/addons/' + WIZARD_ADDON_ID + '/')
    except Exception:
        return ''


def _wizard_needs_heal(base):
    """True iff the installed wizard.py lacks the post-fix
    sentinel. Read-only check; safe to call every startup."""
    p = os.path.join(base, 'resources', 'libs', 'wizard.py')
    if not os.path.isfile(p):
        # No wizard installed (AI-only-on-other-build users). Skip.
        return False
    try:
        with open(p, 'rb') as f:
            return HEALED_SENTINEL not in f.read()
    except OSError:
        return False


def _notify(msg, header='Kodi POV IL', timeout=8000, error=False):
    if xbmcgui is None:
        return
    try:
        xbmcgui.Dialog().notification(
            header,
            msg,
            (xbmcgui.NOTIFICATION_ERROR if error
             else xbmcgui.NOTIFICATION_INFO),
            timeout,
        )
    except Exception:
        pass


def _modal_ok(msg, header='Kodi POV IL'):
    """Blocking modal -- user MUST tap OK. Used for the success
    path so the restart prompt can't be missed (toast disappears
    in 8s; a lot of Android users boot Kodi, look at the home
    screen for 10s deciding what to do, and miss the toast)."""
    if xbmcgui is None:
        return
    try:
        xbmcgui.Dialog().ok(header, msg)
    except Exception:
        pass


def ensure_healed():
    """Self-heal the bundled wizard if it's still on the
    extract.all-skip-bug version. Returns one of:
    'no_wizard' | 'wizard_already_healthy' | 'already_healed'
    | 'no_staged_zip' | 'bad_zip' | 'write_failed' | 'healed'.
    """
    base = _wizard_base()
    if not base or not os.path.isdir(base):
        return 'no_wizard'
    marker = os.path.join(base, MARKER_NAME)
    if os.path.isfile(marker):
        return 'already_healed'
    if not _wizard_needs_heal(base):
        # Already healthy. Stamp the marker so we skip the
        # filesystem read on every subsequent boot.
        try:
            with open(marker, 'wb') as f:
                f.write(b'healthy at first check\n')
        except OSError:
            pass
        return 'wizard_already_healthy'

    ai_base = _ai_subs_base()
    if not ai_base:
        _log('cannot locate AI subs addon path', level='WARNING')
        return 'no_staged_zip'
    staged = os.path.join(ai_base, STAGED_ZIP_REL)
    if not os.path.isfile(staged):
        _log('staged zip missing at ' + staged, level='WARNING')
        _notify(
            'תיקון הוויזרד נכשל: קובץ התיקון חסר. '
            'התקן ידנית מ-Install from zip.',
            timeout=12000, error=True,
        )
        return 'no_staged_zip'

    _log('installed wizard lacks ignore-bypass sentinel; '
         'extracting bundled wizard zip to heal',
         level='INFO')
    try:
        zf = zipfile.ZipFile(staged, 'r')
    except Exception as e:
        _log('zip parse failed: {0}'.format(e), level='WARNING')
        _notify(
            'תיקון הוויזרד נכשל: קובץ התיקון פגום. '
            'התקן ידנית מ-Install from zip.',
            timeout=12000, error=True,
        )
        return 'bad_zip'

    # The staged zip wraps its tree in `plugin.program.kodipovilwizard/`.
    # Strip that prefix when writing so files land directly under the
    # installed wizard's addon dir.
    prefix = WIZARD_ADDON_ID + '/'
    members = zf.namelist()
    has_prefixed = any(m.startswith(prefix) for m in members)
    written = 0
    try:
        for m in members:
            if has_prefixed:
                if not m.startswith(prefix):
                    continue
                rel = m[len(prefix):]
            else:
                rel = m
            if not rel or rel.endswith('/'):
                continue
            # Path traversal guard -- defence in depth.
            parts = rel.replace('\\', '/').split('/')
            if '..' in parts or '' in parts:
                continue
            if os.path.isabs(rel):
                continue
            dest = os.path.join(base, *parts)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(m) as src, open(dest, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            written += 1
    except OSError as e:
        _log('write failed: {0}'.format(e), level='WARNING')
        _notify(
            'תיקון הוויזרד נכשל: בעיית כתיבה לדיסק. '
            'בדוק הרשאות אחסון של Kodi.',
            timeout=12000, error=True,
        )
        return 'write_failed'
    finally:
        try:
            zf.close()
        except Exception:
            pass

    # Best-effort cleanup of stale bytecode so Python picks up
    # the new .py files cleanly on next boot. Not critical -- .pyc
    # mtime checks will recompile anyway -- but on Android Kodi
    # we've seen stale cached imports.
    try:
        pycache_root = os.path.join(base, 'resources', 'libs',
                                    '__pycache__')
        if os.path.isdir(pycache_root):
            shutil.rmtree(pycache_root, ignore_errors=True)
    except Exception:
        pass

    try:
        with open(marker, 'wb') as f:
            f.write(b'healed by AI subs wizard_self_healer v2\n')
    except OSError:
        # Marker write failure is non-fatal; the sentinel check
        # next boot will see the new wizard.py and short-circuit.
        pass

    _log('healed wizard -- wrote {0} files. User must restart '
         'Kodi for the new wizard module to load (Python caches '
         'the old import for the lifetime of this process).'
         .format(written), level='INFO')

    # Modal dialog so the user CANNOT miss the restart instruction.
    # The v1 toast (8s) was getting missed -- user reported "no
    # notification appeared at all" after quick_update + restart.
    _modal_ok(
        'הוויזרד עודכן בהצלחה ל-0.1.10.\n\n'
        'כדי להפעיל את המצב החדש (כולל Arctic Fuse 3 ברשימת '
        'החלפת סקין):\n\n'
        '[B]סגור את Kodi לחלוטין ופתח מחדש[/B]\n\n'
        '(אנדרואיד: לחיצה ארוכה על Home → Force Stop → פתח שוב)'
    )
    return 'healed'
