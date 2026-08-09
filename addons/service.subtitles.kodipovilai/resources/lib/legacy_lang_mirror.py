# Give a third-party add-on the MODERN language layout so its labels render
# on a Kodi whose interface language is not English.
#
# THE TRAP. Kodi 19+ resolves an add-on's strings by locale FOLDER: it looks
# for resources/language/resource.language.<locale>/, then falls back to
# resource.language.en_gb/. An add-on that still ships only the legacy
# resources/language/English/ has NEITHER, so every numeric label lookup
# returns an empty string. On an English Kodi the legacy folder name happens
# to match the interface language and everything renders, which is why
# upstream never sees it -- and why it is invisible until the add-on lands on
# a Hebrew device.
#
# The fix is purely ADDITIVE: copy English/strings.po into a new
# resource.language.en_gb/ folder inside the installed add-on. No upstream
# byte is modified, so the add-on's own repo updates keep applying cleanly --
# and because an update REPLACES the add-on folder (removing our copy), this
# runs at every Kodi startup and re-heals, refreshing the copy whenever
# upstream's English strings change.
#
# Two add-ons in the build's orbit need it, both opt-in, both hit for the same
# reason: Umbrella (blank settings categories and labels) and Account Manager
# Lite (twenty blank labels -- and they are Authorize, Username, Password and
# API Key, i.e. exactly the controls a user has to press to connect an
# account). Instant no-op for anyone who installed neither.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


LEGACY_REL = 'resources/language/English/strings.po'
MODERN_REL = 'resources/language/resource.language.en_gb/strings.po'

# Written as the first line of every copy WE create, so a later run can tell
# our mirror apart from a real en_gb the add-on may start shipping itself.
# Migrating to the modern layout while the legacy folder is still there is
# the normal way an add-on does it -- and at that moment upstream's own file
# is sitting exactly where we want to write. Without this marker we would
# overwrite their translation with our copy of the English one, at every
# startup, forever. A leading '#' line is an ordinary gettext comment, so
# nothing downstream cares that it is there.
MARKER = '# mirrored from the legacy English folder by MoranSubs -- delete '\
         'this line and the file becomes untouchable\n'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('legacy_lang_mirror: ' + msg, level=level)
    except Exception:
        pass


def _addon_path(addon_id):
    if xbmcvfs is None:
        return ''
    # An add-on id is a dotted name, never a path. Refusing anything else
    # keeps a caller from steering this at some other part of the disk --
    # this module is deliberately generic now, so the next caller is one we
    # have not seen.
    if not addon_id or '/' in addon_id or '\\' in addon_id or addon_id == '..':
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/' + addon_id + '/')
    except Exception:
        return ''
    return base if os.path.isdir(base) else ''


def _inside(base, path):
    """True only when `path` really lands inside `base`. Guards the two
    relative paths as well as the id: they are constants at both call sites
    today, and constants are exactly what stops being constant later."""
    try:
        base_real = os.path.realpath(base)
        path_real = os.path.realpath(path)
    except Exception:
        return False
    return (path_real == base_real
            or path_real.startswith(base_real.rstrip(os.sep) + os.sep))


def mirror(addon_id, legacy_rel=LEGACY_REL, modern_rel=MODERN_REL):
    """Mirror an add-on's legacy English strings into the modern en_gb
    resource folder Kodi actually looks for. Idempotent, additive-only,
    never raises. Returns a short status string."""
    base = _addon_path(addon_id)
    if not base:
        return 'not_installed'
    src = os.path.join(base, *legacy_rel.split('/'))
    dst = os.path.join(base, *modern_rel.split('/'))
    if not (_inside(base, src) and _inside(base, dst)):
        _log('{0}: refusing to work outside the add-on folder'.format(
            addon_id), 'WARNING')
        return 'outside'
    if not os.path.isfile(src):
        # Upstream moved to the modern layout themselves, or a broken
        # install -- either way there is nothing safe to copy.
        _log('{0}: legacy English strings.po not found -- skipping'.format(
            addon_id), 'WARNING')
        return 'no_source'
    try:
        with open(src, 'rb') as f:
            payload = f.read()
    except OSError as e:
        _log('{0}: read failed: {1}'.format(addon_id, e), 'WARNING')
        return 'read_failed'
    if not payload:
        return 'no_source'
    marker = MARKER.encode('utf-8')
    try:
        if os.path.isfile(dst):
            with open(dst, 'rb') as f:
                existing = f.read()
            if existing.startswith(marker):
                # Ours. Refresh it if upstream's English strings moved.
                if existing == marker + payload:
                    return 'unchanged'
            elif existing == payload:
                # Ours too -- written before this file carried a marker.
                # Rewriting it once stamps the marker for good.
                pass
            else:
                # Somebody else's file. That is upstream finally shipping a
                # real en_gb, which is the outcome we wanted all along, so
                # the only correct move is to stop.
                return 'upstream'
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + '.aitmp'
        with open(tmp, 'wb') as f:
            f.write(marker + payload)
        os.replace(tmp, dst)
        _log('{0}: installed modern en_gb strings ({1} bytes) -- labels will '
             'render'.format(addon_id, len(payload)))
        return 'patched'
    except OSError as e:
        try:
            os.remove(dst + '.aitmp')
        except OSError:
            pass
        _log('{0}: write failed: {1}'.format(addon_id, e), 'WARNING')
        return 'write_failed'
