# Self-healing patch: give Umbrella the MODERN addon-language layout so its
# settings labels render on a Hebrew-interface Kodi.
#
# Symptom (field report, first day of the Umbrella pilot): Umbrella's
# settings dialog shows blank category names and blank setting labels --
# only the toggles/values render.
#
# Root cause: Umbrella ships its strings ONLY in the legacy folder layout
# (resources/language/English/strings.po, German/, Polish/ ...). Kodi 21
# resolves addon strings by locale folder: it looks for
# resource.language.he_il, then falls back to resource.language.en_gb --
# and Umbrella has NEITHER, so every label lookup returns an empty string.
# English-interface users are saved by the legacy folder name happening to
# match their language, which is why upstream never notices. POV and
# CocoScrapers both ship the modern layout, which is why they render fine
# on the same devices.
#
# The fix is purely ADDITIVE: copy English/strings.po into a new
# resource.language.en_gb/ folder inside the installed addon. No upstream
# byte is modified, so Umbrella's own repo updates keep applying cleanly --
# and because an update REPLACES the addon folder (removing our copy), this
# runs every Kodi startup and re-heals, refreshing the copy whenever
# upstream's English strings change. No-op in the common case and for the
# vast majority of users who never installed the pilot.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


UMBRELLA_ADDON_ID = 'plugin.video.umbrella'
LEGACY_REL = 'resources/language/English/strings.po'
MODERN_REL = 'resources/language/resource.language.en_gb/strings.po'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('umbrella_language_patcher: ' + msg, level=level)
    except Exception:
        pass


def _addon_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + UMBRELLA_ADDON_ID + '/')
    except Exception:
        return ''
    return base if os.path.isdir(base) else ''


def ensure_patched():
    """Mirror Umbrella's legacy English strings into the modern en_gb
    resource folder Kodi actually looks for. Idempotent, additive-only,
    never raises. Returns a short status string."""
    base = _addon_path()
    if not base:
        return 'not_installed'
    src = os.path.join(base, *LEGACY_REL.split('/'))
    dst = os.path.join(base, *MODERN_REL.split('/'))
    if not os.path.isfile(src):
        # upstream moved to the modern layout themselves, or a broken
        # install -- either way there is nothing safe to copy
        _log('legacy English strings.po not found -- skipping', 'WARNING')
        return 'no_source'
    try:
        with open(src, 'rb') as f:
            payload = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), 'WARNING')
        return 'read_failed'
    if not payload:
        return 'no_source'
    try:
        if os.path.isfile(dst):
            with open(dst, 'rb') as f:
                if f.read() == payload:
                    return 'unchanged'
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + '.aitmp'
        with open(tmp, 'wb') as f:
            f.write(payload)
        os.replace(tmp, dst)
        _log('installed modern en_gb strings for Umbrella '
             '({0} bytes) -- settings labels will render'.format(len(payload)))
        return 'patched'
    except OSError as e:
        try:
            os.remove(dst + '.aitmp')
        except OSError:
            pass
        _log('write failed: {0}'.format(e), 'WARNING')
        return 'write_failed'
