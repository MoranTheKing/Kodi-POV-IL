# One-shot self-healer for the bundled Kodi POV IL Wizard.
#
# v3 (APK-override): the wizard's actual location matters. On the
# Android build the wizard ships *inside the APK* at
# /data/.../cache/apk/assets/addons/plugin.program.kodipovilwizard/
# which is read-only. The writable mirror at
# special://home/addons/plugin.program.kodipovilwizard/ may not
# exist at all -- which is what bit v2: the healer bailed silently
# with 'no_wizard' on every Android-APK user we tried to recover.
# A real-world user log proved it (no toast, no modal, no log
# line, wizard staying at 0.1.4 from APK after multiple
# quick_updates).
#
# v3 fix: don't require the writable wizard dir to pre-exist.
# If xbmcaddon.Addon('plugin.program.kodipovilwizard') resolves at
# all (which it does for APK-bundled installs), we know the user
# intends to have the wizard. We then extract the bundled staged
# zip into the WRITABLE addons path -- creating the directory if
# necessary -- and let Kodi's normal addon-resolution pick the
# higher-versioned writable copy over the APK's 0.1.4. (We've
# verified this works in practice via skin.fentastic, which the
# same user's log shows being loaded from writable v1.0.25 even
# though the APK ships its own older copy.)
#
# v2 lineage (still applies):
# - Wizard zip bundled INSIDE this addon at resources/staged_wizard.zip;
#   no network, no SSL, no CDN.
# - Modal Dialog().ok the user must acknowledge (not a transient
#   toast that boots-up activity hides).
# - Hebrew error toasts on every failure path (v1 was completely
#   silent on failure, which is how we ended up here in the first
#   place).
# - __pycache__ cleanup so Python recompiles cleanly on next boot.
#
# Marker bumped to v3 so v2 installs that bailed 'no_wizard'
# silently get a fresh attempt with v3's path.
#
# Steady-state logging at INFO level for every return code now
# (v2 was 'pass'-on-no-op which made remote diagnosis a nightmare).

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
# When present in the *writable* wizard.py, we're done.
HEALED_SENTINEL = b'ignore=True bypasses extract.all'

# Marker file written into the writable wizard addon dir once a
# heal has been attempted. Bumped per healer version so previous
# attempts that may have left a stale marker get a fresh try.
MARKER_NAME = '.ai_subs_wizard_healed_v3'

STAGED_ZIP_REL = os.path.join('resources', 'staged_wizard.zip')

# Writable-side wizard path expressed as a special:// URI. On
# Android Kodi this translates to
#   /storage/emulated/0/Android/data/org.xbmc.kodi/files/.kodi/addons/...
# On Linux/macOS Kodi it's the standard ~/.kodi/addons/...
WRITABLE_WIZARD_SPECIAL = (
    'special://home/addons/' + WIZARD_ADDON_ID + '/'
)


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


def _writable_wizard_path():
    """Path where the writable copy of the wizard lives (or will
    live after we extract). Always returned -- we do NOT check
    existence here, because the whole point of v3 is to create
    this directory on APK-only users."""
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath(WRITABLE_WIZARD_SPECIAL)
    except Exception:
        return ''


def _wizard_known_to_kodi():
    """True iff Kodi's addon manager has *any* record of the
    wizard (APK-bundled, writable, or both). This is the v3
    pre-condition for healing: we only want to install a wizard
    where one was already intended. AI-subs-on-someone-else's-build
    users without the wizard get no surprise install."""
    if xbmcaddon is None:
        return False
    try:
        xbmcaddon.Addon(WIZARD_ADDON_ID)
        return True
    except Exception:
        return False


def _writable_wizard_is_healthy(writable_dir):
    """True iff the writable copy of wizard.py contains the
    post-fix sentinel. Used to short-circuit further heals once
    a newer wizard has landed in the writable mirror."""
    p = os.path.join(writable_dir, 'resources', 'libs', 'wizard.py')
    if not os.path.isfile(p):
        return False
    try:
        with open(p, 'rb') as f:
            return HEALED_SENTINEL in f.read()
    except OSError:
        return False


def _ai_subs_base():
    """Path to this addon's directory -- the staged zip lives
    inside it. Uses Kodi's addon API rather than guessing the
    install location, which differs APK / OS / portable-mode."""
    if xbmcaddon is None:
        return ''
    try:
        return xbmcvfs.translatePath(
            xbmcaddon.Addon(AI_SUBS_ADDON_ID).getAddonInfo('path'))
    except Exception:
        return ''


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
    """Blocking modal -- user MUST tap OK. Used on the success
    path so the restart prompt can't be missed (a transient toast
    disappears in 8s; Android boot-up activity often hides it)."""
    if xbmcgui is None:
        return
    try:
        xbmcgui.Dialog().ok(header, msg)
    except Exception:
        pass


def _extract_staged_into(staged_zip_path, writable_dir):
    """Extract the bundled wizard zip into the writable addon dir.
    Returns (written_count, error_or_None)."""
    try:
        zf = zipfile.ZipFile(staged_zip_path, 'r')
    except Exception as e:
        return 0, 'bad_zip: ' + str(e)

    # The staged zip wraps its tree in `plugin.program.kodipovilwizard/`.
    # Strip that prefix so files land directly under writable_dir.
    prefix = WIZARD_ADDON_ID + '/'
    members = zf.namelist()
    has_prefixed = any(m.startswith(prefix) for m in members)
    written = 0
    try:
        os.makedirs(writable_dir, exist_ok=True)
        for m in members:
            if has_prefixed:
                if not m.startswith(prefix):
                    continue
                rel = m[len(prefix):]
            else:
                rel = m
            if not rel or rel.endswith('/'):
                continue
            # Path traversal guard -- the zip is ours, but defence
            # in depth never hurts when we're shelling file writes.
            parts = rel.replace('\\', '/').split('/')
            if '..' in parts or '' in parts:
                continue
            if os.path.isabs(rel):
                continue
            dest = os.path.join(writable_dir, *parts)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(m) as src, open(dest, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            written += 1
    except OSError as e:
        return written, 'write_failed: ' + str(e)
    finally:
        try:
            zf.close()
        except Exception:
            pass
    return written, None


def ensure_healed():
    """Self-heal the bundled wizard if the writable copy is stuck
    (or missing entirely, the APK-only case). Returns:
    'no_kodi' | 'wizard_not_installed' | 'already_healed'
    | 'wizard_already_healthy' | 'no_staged_zip' | 'bad_zip'
    | 'write_failed' | 'healed'.
    """
    if xbmcaddon is None or xbmcvfs is None:
        _log('not in a Kodi process; nothing to do', level='INFO')
        return 'no_kodi'

    if not _wizard_known_to_kodi():
        # User doesn't have the POV wizard installed anywhere
        # (APK or writable). Don't auto-install one -- they might
        # be running AI subs standalone on a different build.
        _log('wizard addon not registered with Kodi; '
             'AI-subs-on-other-build install, no-op',
             level='INFO')
        return 'wizard_not_installed'

    writable = _writable_wizard_path()
    if not writable:
        _log('could not translate writable wizard path', level='WARNING')
        return 'no_kodi'

    marker = os.path.join(writable, MARKER_NAME)
    if os.path.isfile(marker):
        _log('marker present at {0}; healed previously, skipping'
             .format(marker), level='INFO')
        return 'already_healed'

    if (os.path.isdir(writable)
            and _writable_wizard_is_healthy(writable)):
        # Writable wizard exists AND already contains the fix.
        # Stamp the marker so we skip the read on every boot.
        try:
            with open(marker, 'wb') as f:
                f.write(b'healthy at first check\n')
        except OSError:
            pass
        _log('writable wizard at {0} already has the fix; marker stamped'
             .format(writable), level='INFO')
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

    _log('healing wizard: extracting {0} -> {1}'
         .format(staged, writable), level='INFO')

    written, err = _extract_staged_into(staged, writable)
    if err is not None:
        _log(err, level='WARNING')
        if err.startswith('bad_zip'):
            _notify(
                'תיקון הוויזרד נכשל: קובץ התיקון פגום. '
                'התקן ידנית מ-Install from zip.',
                timeout=12000, error=True,
            )
            return 'bad_zip'
        else:
            _notify(
                'תיקון הוויזרד נכשל: בעיית כתיבה לדיסק. '
                'בדוק הרשאות אחסון של Kodi.',
                timeout=12000, error=True,
            )
            return 'write_failed'

    # Best-effort cleanup of stale bytecode so Python picks up
    # the new .py files cleanly on next boot. Not critical -- .pyc
    # mtime checks will recompile anyway -- but on Android Kodi
    # we've seen stale cached imports.
    try:
        pycache_root = os.path.join(writable, 'resources', 'libs',
                                    '__pycache__')
        if os.path.isdir(pycache_root):
            shutil.rmtree(pycache_root, ignore_errors=True)
    except Exception:
        pass

    try:
        with open(marker, 'wb') as f:
            f.write(b'healed by AI subs wizard_self_healer v3\n')
    except OSError:
        # Marker write failure is non-fatal; sentinel check next
        # boot will short-circuit if files landed correctly.
        pass

    _log('healed wizard ({0} files written to {1}). User must '
         'restart Kodi for the new wizard module to load.'
         .format(written, writable), level='INFO')

    # Modal dialog -- user CANNOT miss the restart instruction.
    _modal_ok(
        'הוויזרד עודכן בהצלחה ל-0.1.10.\n\n'
        'כדי להפעיל את המצב החדש (כולל Arctic Fuse 3 ברשימת '
        'החלפת סקין):\n\n'
        '[B]סגור את Kodi לחלוטין ופתח מחדש[/B]\n\n'
        '(אנדרואיד: לחיצה ארוכה על Home → Force Stop → פתח שוב)'
    )
    return 'healed'
