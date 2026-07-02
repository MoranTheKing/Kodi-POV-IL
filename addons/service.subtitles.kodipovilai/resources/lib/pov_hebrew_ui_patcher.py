# Hebrew-ise POV's own in-app UI strings (all skins).
#
# POV ships ONLY resource.language.en_gb, so every string POV shows via
# ls(<id>) is English -- including the resume dialog ("Resume Point" / "Resume"
# / "Start Over") and the search hub (Search / Movies / TV Shows / People /
# Collection / New / History). The build's menus look Hebrew because they come
# from navigator.db / favourites seeds, but POV's own windows fall back to the
# English source strings.
#
# Fix: set the Hebrew text on BOTH the msgid and msgstr of the relevant ids in
# POV's en_gb strings.po. (For its own source language, Kodi shows the msgid,
# not the msgstr -- so a Hebrew msgstr alone was ignored; the msgid must be
# Hebrew too.) Only the msgid/msgstr lines that immediately follow each
# targeted msgctxt are touched; format tokens like [B]%s[/B] are preserved. The
# lookup is by numeric id, so translating the text changes nothing else.
#
# Idempotent (re-run leaves an already-Hebrew msgstr unchanged), atomic, and
# self-healing (a POV self-update that resets strings.po is re-applied on the
# next boot). Safe no-op if POV isn't installed or an id is absent.

import os
import re

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
STRINGS_REL = 'resources/language/resource.language.en_gb/strings.po'

# POV string id -> Hebrew. Format tokens ([B], %s) are kept verbatim.
HE = {
    # Resume / playback-point dialog
    '32790': 'נקודת המשך: [B]%s[/B]',
    '32832': 'המשך צפייה',
    '32833': 'התחל מהתחלה',
    # Search hub (magnifying glass) + search-history flow
    '32450': 'חיפוש',
    '32028': 'סרטים',
    '32029': 'סדרות',
    '32507': 'אנשים',
    '32499': 'קולקציה',
    '32857': 'חדש',
    '32486': 'היסטוריה',
    '32698': 'הסרה מההיסטוריה',
    '32699': 'ניקוי כל ההיסטוריה',
}


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_hebrew_ui_patcher: ' + msg, level=level)
    except Exception:
        pass


def _strings_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *STRINGS_REL.split('/'))
    return p if os.path.isfile(p) else ''


def ensure_patched():
    """Returns 'patched' | 'already_patched' | 'no_pov' | 'no_file'
    | 'unmatched' | 'read_failed' | 'write_failed'."""
    path = _strings_path()
    if not path:
        return 'no_pov' if xbmcvfs is None else 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'

    new_content = content
    applied = 0
    for sid, he in HE.items():
        # msgctxt "#<id>" \n msgid "<english>" \n msgstr "<current>"
        # -> set BOTH msgid and msgstr to Hebrew. Tolerates LF or CRLF.
        pat = re.compile(
            r'(msgctxt "#' + sid + r'"\r?\nmsgid )"[^"]*"(\r?\nmsgstr )"[^"]*"')
        he_q = '"' + he + '"'
        new_content, n = pat.subn(
            lambda m: m.group(1) + he_q + m.group(2) + he_q,
            new_content, count=1)
        applied += n

    if applied == 0:
        _log('no target string ids matched -- POV strings.po shape changed; '
             'leaving it alone', level='WARNING')
        return 'unmatched'

    if new_content == content:
        return 'already_patched'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'

    _log('set {0} POV UI string(s) to Hebrew (resume dialog + search)'.format(
        applied), level='INFO')
    return 'patched'
