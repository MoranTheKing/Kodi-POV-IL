# Make POV's TorBox links legal URLs, instead of taking away the feature POV
# just added.
#
# THE OUTAGE (field log, 2026-08-15 11:22; POV published the cause the same
# morning at 08:31). Nothing plays. Any source, instantly:
#
#   CCurlFile::Stat - <https://store-079.wnam.tb-cdn.io/dld/<id>?token=<tok>
#   &filename=Spider-Man- Homecoming (2017) 2160p ... [Hindi + English]
#   ESub ~ RemuxDoc.mkv>   Failed: URL using bad/illegal format or missing URL(3)
#
# POV 6.08.12's debrids/torbox_api.py unrestrict_link() started sending
# `append_name=true`, which asks TorBox to put the file's name into the link it
# returns -- and TorBox returns that name RAW. The link arrives with spaces and
# square brackets in it, libcurl refuses to parse it (CURLE_URL_MALFORMAT) and
# never sends a request. Every release name has spaces, so nothing plays at all.
#
# WHY WE ENCODE INSTEAD OF DELETING THE PARAMETER. The first version of this
# fix removed `append_name`. It worked, and it was the wrong shape: POV added
# that parameter deliberately and will keep it, so every future POV release
# would re-add it and we would be taking it out again forever -- and each time,
# playback would break for one boot until our patcher caught up. Encoding the
# link keeps POV's feature working AND makes it valid, so a POV release that
# keeps `append_name` needs nothing from us at all.
#
# WHAT EXACTLY GETS ENCODED, MEASURED RATHER THAN GUESSED. Feeding candidate
# characters to curl one at a time, only TWO are actually rejected in a query:
# the space, and the square brackets. Parentheses, +, ~, &, ' , ; = : @ # % and
# even <>"{}|\^` all parse fine. So the encoder covers the characters that
# cannot legally appear in a URI at all -- that measured pair plus the rest of
# the excluded set, and anything outside printable ASCII so a Hebrew or
# accented filename cannot break it either -- and touches nothing else. The
# token is hex and passes through byte-for-byte.
#
# IT IS IDEMPOTENT ON THE URL, which matters more than it looks: `%` is left
# alone, so a link TorBox already encoded, or one that passes through twice, is
# unchanged rather than double-encoded into a different file name.
#
# Self-healing: a POV update replaces the file and this puts the helper back on
# the next start. Marker-gated, compile-checked, atomic, .pyc dropped, and a
# no-op on any POV that does not have the anchor. Never raises.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


POV_ADDON_ID = 'plugin.video.pov'
TORBOX_REL = 'resources/lib/debrids/torbox_api.py'
MARKER = '# AI_SUBS_TORBOX_URL_v1'

# POV's file is tab-indented; these must match it byte for byte.
_RETURN_OLD = '\t\treturn self._get(path, params=params)\n'
_RETURN_NEW = ('\t\treturn _ai_safe_url(self._get(path, params=params))  '
               + MARKER + '\n')

# Injected at module level, right after POV's own imports. Deliberately uses no
# imports of its own -- str methods and .encode() only -- so it cannot be
# broken by POV rearranging what that module imports.
_HELPER = '''

def _ai_safe_url(_u):  ''' + MARKER + '''
\t"""Percent-encode only what cannot legally appear in a URI.

\tPOV asks TorBox for append_name=true and TorBox returns the file name
\traw, so the link arrives with spaces and brackets and libcurl rejects it
\t(error 3) before sending anything. Encoding here keeps POV's feature and
\tmakes the link valid.

\tLeaves '%' alone, so an already-encoded link is returned unchanged
\trather than double-encoded. Anything that is not a string is passed
\tstraight through -- this wraps a call that also returns errors.
\t"""
\tif not isinstance(_u, str) or '://' not in _u: return _u
\t_bad = '<>"{}|\\\\^`[] '
\t_out = []
\tfor _c in _u:
\t\tif _c in _bad or _c < '!' or _c > '~':
\t\t\t_out.append(''.join('%%%02X' % _b for _b in _c.encode('utf-8')))
\t\telse: _out.append(_c)
\treturn ''.join(_out)

'''

# Injected after the last of POV's own module-level imports.
_IMPORT_ANCHOR = "session.mount('https://api.torbox.app'"


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_torbox_url_fix: ' + msg, level=level)
    except Exception:
        pass


def _pov_path(rel):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
        p = os.path.join(base, *rel.split('/'))
        return p if os.path.isfile(p) else ''
    except Exception:
        return ''


def _drop_pyc(path):
    try:
        d = os.path.join(os.path.dirname(path), '__pycache__')
        base = os.path.splitext(os.path.basename(path))[0] + '.'
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.startswith(base):
                    try:
                        os.remove(os.path.join(d, fn))
                    except OSError:
                        pass
    except Exception:
        pass


def ensure_patched():
    """Wrap POV's TorBox unrestrict_link result in a URL encoder. Returns
    'no_file' | 'unchanged' | 'patched' | 'read_failed' | 'no_anchor' |
    'compile_failed' | 'write_failed'. Never raises."""
    path = _pov_path(TORBOX_REL)
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            content = fh.read()
    except Exception as exc:
        _log('read failed: {0}'.format(exc), level='WARNING')
        return 'read_failed'

    if MARKER in content:
        return 'unchanged'

    # Both edits or neither: a helper with nothing calling it is dead weight,
    # and a call with no helper is an AttributeError on every resolve.
    if content.count(_RETURN_OLD) != 1 or content.count(_IMPORT_ANCHOR) != 1:
        _log('anchors not found as expected (return={0}, import={1}) -- POV '
             'changed shape; not editing'.format(
                 content.count(_RETURN_OLD), content.count(_IMPORT_ANCHOR)),
             level='WARNING')
        return 'no_anchor'

    line_end = content.index(_IMPORT_ANCHOR)
    line_end = content.index('\n', line_end) + 1
    new_content = (content[:line_end] + _HELPER + content[line_end:])
    new_content = new_content.replace(_RETURN_OLD, _RETURN_NEW, 1)

    try:
        compile(new_content, path, 'exec')
    except SyntaxError as exc:
        _log('patched content would not compile -- skipping ({0})'.format(exc),
             level='WARNING')
        return 'compile_failed'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(new_content)
        os.replace(tmp, path)
    except Exception as exc:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass
        except Exception as cleanup_exc:
            _log('and its temp file could not be removed either: {0}'.format(
                cleanup_exc), level='WARNING')
        _log('write failed: {0}'.format(exc), level='WARNING')
        return 'write_failed'

    _drop_pyc(path)
    return 'patched'
