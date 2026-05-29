# One-shot self-healer for the bundled Kodi POV IL Wizard.
#
# Why this lives in the AI subs addon: the wizard's quick_update
# extracts the quickfix via extract.all (resources/libs/extract.py),
# which has a safety guard that skips any file whose path contains
# CONFIG.ADDON_ID -- the wizard's own id. The intent is "don't let
# the wizard trash itself mid-extract." The side effect is that
# every wizard-update shipped via quick_update is silently dropped:
# the addon DB record is bumped, but the .py files on disk stay at
# the pre-update version. PR #161 (Arctic Fuse 3 third-skin support)
# was the first time users could *see* this breakage -- Switch Skin
# kept listing only Estuary + FENtastic after quick_update + restart.
#
# Wizard 0.1.10 patches extract.all to take ignore=True so future
# quick_updates ship the wizard cleanly. But users currently stuck
# on 0.1.9-or-older can't get the fix via the broken pipe. This
# healer rides the AI subs quickfix path (different addon id, not
# skipped), detects the stuck-wizard fingerprint, downloads the
# latest wizard zip from GitHub, and force-extracts it over the
# installed wizard's addon dir. Toasts the user to restart so the
# new Python files get re-imported.
#
# Idempotent: a marker file inside the wizard's addon dir gates
# re-runs. Self-disarms once the installed wizard.py contains the
# 0.1.10 ignore-bypass fingerprint -- after that the regular
# quick_update path takes over and this healer becomes a no-op.

import io
import os
import shutil
import zipfile

try:
    import urllib.request as urllib_req
except ImportError:
    urllib_req = None

try:
    import xbmcgui
    import xbmcvfs
except ImportError:
    xbmcgui = None
    xbmcvfs = None

from . import kodi_utils


WIZARD_ADDON_ID = 'plugin.program.kodipovilwizard'
WIZARD_ZIP_URL = (
    'https://github.com/MoranTheKing/Kodi-POV-IL/raw/main/'
    'wizard/plugin.program.kodipovilwizard-latest.zip'
)

# Sentinel inside the installed wizard.py that proves the
# extract.all self-skip bug has been fixed (wizard >= 0.1.10).
# Once present, this healer is permanently a no-op for that
# install -- the wizard can self-update going forward.
HEALED_SENTINEL = b'ignore=True bypasses extract.all'

# Marker file written into the wizard's addon dir on success so
# repeated boots don't re-download a healthy wizard. Versioned so
# we can re-trigger the healer if a future bug requires it.
MARKER_NAME = '.ai_subs_wizard_healed_v1'

REQUEST_TIMEOUT = 30
USER_AGENT = 'Kodi-POV-IL-AISubs-WizardHealer/1'


def _log(msg, level='INFO'):
    try:
        kodi_utils.log(
            'wizard_self_healer: ' + msg, level=level)
    except Exception:
        pass


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


def _notify(msg):
    if xbmcgui is None:
        return
    try:
        xbmcgui.Dialog().notification(
            'Kodi POV IL',
            msg,
            xbmcgui.NOTIFICATION_INFO,
            8000,
        )
    except Exception:
        pass


def ensure_healed():
    """Self-heal the bundled wizard if it's still on the
    extract.all-skip-bug version. Returns one of:
    'no_wizard' | 'wizard_already_healthy' | 'already_healed'
    | 'no_urllib' | 'download_failed' | 'bad_zip'
    | 'write_failed' | 'healed'.
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
    if urllib_req is None:
        return 'no_urllib'

    _log('installed wizard lacks ignore-bypass sentinel; '
         'downloading latest from GitHub to heal',
         level='INFO')
    try:
        req = urllib_req.Request(
            WIZARD_ZIP_URL,
            headers={'User-Agent': USER_AGENT},
        )
        with urllib_req.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = resp.read()
    except Exception as e:
        _log('download failed: {0}'.format(e), level='WARNING')
        return 'download_failed'

    try:
        zf = zipfile.ZipFile(io.BytesIO(data), 'r')
    except Exception as e:
        _log('zip parse failed: {0}'.format(e), level='WARNING')
        return 'bad_zip'

    # The published zip wraps its tree in `plugin.program.kodipovilwizard/`.
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
            # Path traversal guard -- the zip is ours, but defence
            # in depth never hurts when we're shelling out file writes.
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
        return 'write_failed'
    finally:
        try:
            zf.close()
        except Exception:
            pass

    try:
        with open(marker, 'wb') as f:
            f.write(b'healed by AI subs wizard_self_healer\n')
    except OSError:
        # Marker write failure is non-fatal; the sentinel check
        # next boot will see the new wizard.py and short-circuit.
        pass

    _log('healed wizard -- wrote {0} files. User must restart '
         'Kodi for the new wizard module to load (Python caches '
         'the old import for the lifetime of this process).'
         .format(written), level='INFO')

    # Hebrew toast so the user knows to restart -- otherwise the
    # next quick_update + Switch Skin path stays on the cached
    # old wizard module and nothing visibly changes.
    _notify('הוויזרד עודכן. אנא הפעל מחדש את Kodi כדי לראות Arctic Fuse 3.')

    return 'healed'
