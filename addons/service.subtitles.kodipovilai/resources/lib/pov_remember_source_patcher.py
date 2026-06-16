# PHASE 1 (capture only) of "remember the source the user picked".
#
# Injects a small, GATED block into plugin.video.pov's
# sources.py::play_file()._process(), right where POV yields the resolved
# link of the source the user picked. The block records that source's
# identifying attributes (name/hash/quality/provider/debrid) plus the media
# ids, one JSON file per media, under our addon_data/source_memory/. A later
# phase will read those to auto-pick the same/similar source.
#
# SAFETY:
#   * Gated at runtime by our `remember_source` setting (OFF by default), so
#     when off the injected code is a no-op.
#   * Idempotent (marker) and defensive (only patches the exact anchor line).
#   * The resulting file is compiled with compile() BEFORE it's written -- if
#     the injected block were ever malformed we skip and leave POV untouched,
#     so this can never break playback.
#   * Wrapped so any failure just logs and leaves POV as-is.

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
SOURCES_REL_PATH = 'resources/lib/modules/sources.py'
MARKER = '# AI_SUBS_REMEMBER_SOURCE_v1'

# Anchor: the single-line yield of the resolved link in _process(). 4 tabs.
OLD_LINE = '\t\t\t\tif not link is None: yield link\n'

# Replacement: same guard, but expanded so we can stash the chosen source
# first. 5-tab body. Self-contained (imports its own modules); writes one
# JSON per media key (no read-modify-write race).
NEW_BLOCK = (
    '\t\t\t\tif not link is None:\n'
    '\t\t\t\t\t' + MARKER + '\n'
    '\t\t\t\t\ttry:\n'
    '\t\t\t\t\t\timport xbmcaddon as _rs_a, xbmcvfs as _rs_v, json as _rs_j, os as _rs_o\n'
    "\t\t\t\t\t\tif (_rs_a.Addon('service.subtitles.kodipovilai').getSetting('remember_source') or '').lower() == 'true':\n"
    "\t\t\t\t\t\t\t_rs_id = str(self.tmdb_id or self.meta.get('imdb_id') or '')\n"
    '\t\t\t\t\t\t\tif _rs_id:\n'
    "\t\t\t\t\t\t\t\t_rs_key = '%s_%s_s%s_e%s' % (self.media_type, _rs_id, self.season or 0, self.episode or 0)\n"
    "\t\t\t\t\t\t\t\t_rs_rec = {'name': item.get('name', ''), 'hash': item.get('hash', ''), 'quality': item.get('quality', ''), 'provider': item.get('scrape_provider') or item.get('provider', ''), 'debrid': item.get('debrid', ''), 'release_title': item.get('release_title', '')}\n"
    "\t\t\t\t\t\t\t\t_rs_dir = _rs_v.translatePath('special://profile/addon_data/service.subtitles.kodipovilai/source_memory/')\n"
    '\t\t\t\t\t\t\t\tif not _rs_o.path.isdir(_rs_dir): _rs_o.makedirs(_rs_dir)\n'
    "\t\t\t\t\t\t\t\t_rs_tmp = _rs_o.path.join(_rs_dir, _rs_key + '.json.tmp')\n"
    "\t\t\t\t\t\t\t\twith open(_rs_tmp, 'w', encoding='utf-8') as _rs_f: _rs_f.write(_rs_j.dumps(_rs_rec))\n"
    "\t\t\t\t\t\t\t\t_rs_o.replace(_rs_tmp, _rs_o.path.join(_rs_dir, _rs_key + '.json'))\n"
    '\t\t\t\t\texcept Exception: pass\n'
    '\t\t\t\t\tyield link\n'
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_remember_source_patcher: ' + msg, level=level)
    except Exception:
        pass


def _sources_path():
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, SOURCES_REL_PATH)
    return p if os.path.isfile(p) else ''


def ensure_patched():
    path = _sources_path()
    if not path:
        return 'no_file'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        _log('read failed: {0}'.format(e), level='WARNING')
        return 'read_failed'
    if MARKER in content:
        return 'unchanged'
    # Handle either LF or CRLF source.
    old_line = OLD_LINE
    new_block = NEW_BLOCK
    if '\r\n' in content[:4096]:
        old_line = old_line.replace('\n', '\r\n')
        new_block = new_block.replace('\n', '\r\n')
    if old_line not in content:
        _log('play_file yield shape changed upstream -- skipping', level='WARNING')
        return 'unmatched'
    new_content = content.replace(old_line, new_block, 1)
    # SAFETY: never write a file that doesn't compile.
    try:
        compile(new_content, path, 'exec')
    except SyntaxError as e:
        _log('patched content would not compile -- skipping ({0})'.format(e),
             level='WARNING')
        return 'compile_failed'
    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(new_content)
        os.replace(tmp, path)
        _log('injected remember-source capture into sources.py::play_file()',
             level='INFO')
        return 'patched'
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('write failed: {0}'.format(e), level='WARNING')
        return 'write_failed'
