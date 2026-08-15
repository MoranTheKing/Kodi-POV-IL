# Stop POV asking TorBox to append the filename to the download URL.
#
# THE OUTAGE (field log, 2026-08-15 11:22, and POV published the cause the same
# morning at 08:31). Nothing plays. Pick any source, get "הניגון נכשל"
# instantly -- so fast that it is clearly not a network failure, because it
# never becomes one:
#
#   CCurlFile::Stat - <https://store-079.wnam.tb-cdn.io/dld/<id>?token=<tok>
#   &filename=Spider-Man- Homecoming (2017) 2160p 4K UHD HDR10 DV Blu-ray
#   REMUX Dual Audio [Hindi + English] ESub ~ RemuxDoc.mkv>
#   Failed: URL using bad/illegal format or missing URL(3)
#
# That `filename=` value carries RAW SPACES, brackets and parentheses. libcurl
# rejects the URL as malformed (CURLE_URL_MALFORMAT) and never sends a byte.
# Kodi then reports a failed item and POV moves on. Every release name has
# spaces in it, so this is not "some files" -- it is all of them.
#
# WHERE IT COMES FROM. POV 6.08.12's debrids/torbox_api.py, in
# unrestrict_link(), added one request parameter:
#
#     params = {key: ids[0], 'file_id': ids[1], 'token': self.token,
#               'append_name': 'true'}          # <- new in 6.08.12
#
# `append_name=true` asks TorBox to put the file's name into the link it hands
# back, and TorBox returns it unencoded. 6.08.06 does not send it and its links
# play. POV's changelog does not mention the change at all.
#
# WHY REMOVING IT IS THE RIGHT FIX AND NOT A WORKAROUND. Checked, not assumed:
# `append_name` appears exactly ONCE in the whole of POV 6.08.12, and nothing
# reads a filename back out of the URL. modules/downloader.py -- the one place
# that might -- derives its name from `params_get('name')` and, failing that,
# from `urlparse(url).path`, which for a TorBox link is `/dld/<uuid>`: the
# appended name lives in the QUERY and never reaches it. That file is
# byte-identical in 6.08.06 and 6.08.12, so removing the parameter restores
# exactly the behaviour that worked until this morning and costs nothing.
#
# The alternative -- percent-encoding the returned URL -- treats the symptom,
# needs us to rewrite a URL we did not build, and would keep working against us
# every time TorBox changes what it puts in there.
#
# Self-healing: POV replacing its own file re-adds the parameter, and this runs
# every startup and puts it back out. Exact-string, idempotent, compile-checked,
# atomic, .pyc dropped. A device whose POV never had the parameter is a no-op.
# Never raises.

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

# The exact fragment POV 6.08.12 added, with the comma that joins it to the
# dict before it, so removing it leaves a valid literal either way round.
_FRAGMENT = ", 'append_name': 'true'"
# Deliberately NOT marker-based. The presence of the parameter IS the state:
# absent means correct, whether we removed it or POV never sent it. A marker
# would only add a second thing that can drift out of step with the first.
_SENTINEL = 'append_name'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_torbox_append_name_fix: ' + msg, level=level)
    except Exception:
        pass


def _pov_path(rel):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    try:
        p = os.path.join(base, *rel.split('/'))
    except Exception:
        return ''
    try:
        return p if os.path.isfile(p) else ''
    except Exception:
        return ''


def _drop_pyc(path):
    """Remove the cached bytecode so POV re-imports the edited source."""
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
    """Remove `append_name` from POV's TorBox unrestrict call. Returns
    'no_file' | 'clean' | 'patched' | 'read_failed' | 'compile_failed' |
    'write_failed' | 'unexpected_shape'. Never raises."""
    path = _pov_path(TORBOX_REL)
    if not path:
        return 'no_file'

    try:
        with open(path, 'r', encoding='utf-8') as fh:
            content = fh.read()
    except Exception as exc:
        _log('read failed: {0}'.format(exc), level='WARNING')
        return 'read_failed'

    if _SENTINEL not in content:
        return 'clean'

    if content.count(_FRAGMENT) != 1:
        # The parameter is in there but not in the shape we know how to remove.
        # Say so and change nothing -- a half-understood edit to the file that
        # resolves every playable link is not worth the risk.
        _log('found {0!r} but not the exact fragment (count={1}) -- POV changed '
             'shape again; NOT editing'.format(
                 _SENTINEL, content.count(_FRAGMENT)), level='WARNING')
        return 'unexpected_shape'

    new_content = content.replace(_FRAGMENT, '', 1)

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
