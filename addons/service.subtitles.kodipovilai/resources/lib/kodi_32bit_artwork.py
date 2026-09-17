"""Stop the build's original-size artwork policy on 32-bit Kodi only.

The full build historically ships ``<imageres>9999</imageres>``. That tells
Kodi to cache source artwork at its original dimensions. It is especially
expensive on 32-bit boxes where every initial widget wave decodes several rows
of posters and fanart into a much smaller skin control.

This migration is deliberately narrow:

* only a 32-bit Python/Kodi process is eligible;
* only the exact build-owned value 9999 is changed to Kodi's normal 720;
* a missing value or any user-selected value is left alone;
* no thumbnail is deleted, so an update cannot trigger a redownload storm.

Kodi reads advancedsettings.xml at process start, so an existing install gains
the policy on its next ordinary Kodi restart. Existing cached images age out in
the normal way; newly seen artwork is bounded immediately after that restart.
"""

import os
import re
import sys
import xml.etree.ElementTree as ET

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


_BUILD_VALUE = '9999'
_KODI_DEFAULT = '720'
_IMAGE_RE = re.compile(
    r'(<imageres\b[^>]*>)(?P<space>\s*)9999(?P=space)(</imageres>)',
    re.IGNORECASE,
)


def _log(message, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('kodi_32bit_artwork: ' + message, level=level)
    except Exception:
        pass


def _profile_path():
    if xbmcvfs is None:
        return ''
    try:
        return xbmcvfs.translatePath('special://profile/advancedsettings.xml')
    except Exception:
        return ''


def _atomic_write(path, body):
    temp = path + '.kpov32tmp'
    try:
        with open(temp, 'w', encoding='utf-8', newline='') as handle:
            handle.write(body)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        os.replace(temp, path)
        return True
    except OSError:
        try:
            os.remove(temp)
        except OSError:
            pass
        return False


def ensure_optimized(path='', is_32bit=None):
    """Return a status string and never discard a valid custom file."""
    try:
        if is_32bit is None:
            is_32bit = sys.maxsize <= 2 ** 32
        if not is_32bit:
            return 'not_32bit'
        path = path or _profile_path()
        if not path or not os.path.isfile(path):
            return 'no_file'
        with open(path, 'r', encoding='utf-8', newline='') as handle:
            original = handle.read()
        try:
            root = ET.fromstring(original.encode('utf-8'))
        except ET.ParseError:
            return 'invalid_xml'
        if root.tag != 'advancedsettings':
            return 'wrong_root'
        image = root.find('imageres')
        if image is None:
            return 'no_setting'
        value = (image.text or '').strip()
        if value == _KODI_DEFAULT:
            return 'already_optimized'
        if value != _BUILD_VALUE:
            return 'custom_preserved'
        updated, count = _IMAGE_RE.subn(
            lambda match: (match.group(1) + match.group('space')
                           + _KODI_DEFAULT + match.group('space')
                           + match.group(3)),
            original,
            count=1,
        )
        if count != 1:
            return 'unmatched'
        try:
            ET.fromstring(updated.encode('utf-8'))
        except ET.ParseError:
            return 'invalid_result'
        if not _atomic_write(path, updated):
            return 'write_failed'
        _log('bounded future artwork cache entries to 720 on 32-bit; existing '
             'thumbnails were kept and the setting takes effect next restart')
        return 'patched'
    except Exception as exc:
        _log('failed safely: {0}'.format(exc), level='WARNING')
        return 'failed'
