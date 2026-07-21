# Heal + harden Idan Plus (plugin.video.idanplus) channel loading.
#
# WHY: idanplus keeps its channel map in a per-profile file,
# displayChannels.json, as a JSON OBJECT {channelID: channelObj}. Every
# writer in the addon writes a dict. But its ReadList() helper swallows any
# read/parse error and returns [] -- a LIST -- as the "empty" sentinel. So a
# single corrupt/partial displayChannels.json (an interrupted write, bad
# JSON, a truncated file) turns every subsequent channel read into
# list.items() / list.get() and the whole addon dies with
# "AttributeError: 'list' object has no attribute 'items'":
#   * GetChannels(type)  -> items(displayChannels)      (common.py ~575)
#   * GetChannels rebuild -> displayChannels.get(...)   (common.py ~556)
# No channels load, nothing plays, and because the rebuild path crashes on
# the very same list the file can never repair itself -- exactly the "no
# channel works, nothing is even shown, and even when shown it didn't work"
# symptom. This is present in the latest upstream (3.9.9) too, so updating
# the addon does not help.
#
# WHAT (two independent, guarded, fail-open steps):
#   1) DATA HEAL (version-agnostic, the actual fix): if displayChannels.json
#      exists and does NOT parse to a JSON object, move it aside to
#      displayChannels.json.povil-bak and drop the original, so idanplus
#      rebuilds a clean dict from the remote channels.json on next entry.
#      A non-dict here is already-unreadable data, so no valid user
#      customisation (my_name / my_index / my_image ...) is lost -- and a
#      valid dict is left completely untouched.
#   2) CODE HARDEN (best-effort): make GetDisplayChannels() always hand back
#      a dict (dropping a corrupt file so GetChannels rebuilds) and make the
#      items() helper tolerate a non-dict, so any FUTURE corruption degrades
#      to "rebuild" instead of crashing mid-session. Exact-match on the
#      shipped source; silently skipped if the installed source differs.
#
# Everything no-ops when idanplus isn't installed. Idempotent + safe to run
# on every Kodi startup.

import json

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


IDAN_ADDON_ID = 'plugin.video.idanplus'
COMMON_PY = ('special://home/addons/' + IDAN_ADDON_ID +
             '/resources/lib/common.py')
DISPLAY_CHANNELS_JSON = ('special://profile/addon_data/' + IDAN_ADDON_ID +
                         '/displayChannels.json')
DISPLAY_CHANNELS_BAK = DISPLAY_CHANNELS_JSON + '.povil-bak'


# --- exact source anchors (LF, tab-indented) shipped by idanplus 3.9.x ------
# Built line-by-line so the tab/newline layout is unambiguous and matches the
# on-disk file byte-for-byte.
_ITEMS_OLD = '\n'.join([
    'def items(d):',
    '\tif py2:',
    '\t\treturn d.iteritems()',
    '\telse:',
    '\t\treturn d.items()',
])
_ITEMS_NEW = '\n'.join([
    'def items(d):',
    '\tif not isinstance(d, dict):',
    '\t\treturn d',
    '\tif py2:',
    '\t\treturn d.iteritems()',
    '\telse:',
    '\t\treturn d.items()',
])

_GDC_OLD = '\n'.join([
    'def GetDisplayChannels(displayChannelsFile):',
    '\tif not os.path.isfile(displayChannelsFile):',
    '\t\tWriteList(displayChannelsFile, {})',
    '\treturn ReadList(displayChannelsFile)',
])
_GDC_NEW = '\n'.join([
    'def GetDisplayChannels(displayChannelsFile):',
    '\tif not os.path.isfile(displayChannelsFile):',
    '\t\tWriteList(displayChannelsFile, {})',
    '\t_displayChannels = ReadList(displayChannelsFile)',
    '\tif not isinstance(_displayChannels, dict):',
    '\t\ttry:',
    '\t\t\tos.remove(displayChannelsFile)',
    '\t\texcept Exception:',
    '\t\t\tpass',
    '\t\t_displayChannels = {}',
    '\treturn _displayChannels',
])

# Distinctive substrings that only exist AFTER we patch -- used to make the
# code-harden idempotent (skip if already applied).
_ITEMS_MARK = '\tif not isinstance(d, dict):'
_GDC_MARK = '\tif not isinstance(_displayChannels, dict):'


def _log(msg, level='INFO'):
    if kodi_utils is not None:
        try:
            kodi_utils.log('idanplus_channels_patcher: ' + msg, level=level)
        except Exception:
            pass


def _translate(path):
    return xbmcvfs.translatePath(path) if xbmcvfs else path


def _exists(path):
    try:
        return bool(xbmcvfs.exists(_translate(path))) if xbmcvfs else False
    except Exception:
        return False


def _read(path):
    with xbmcvfs.File(_translate(path)) as f:
        return f.read()


def _write(path, content):
    f = xbmcvfs.File(_translate(path), 'w')
    try:
        return bool(f.write(content))
    finally:
        f.close()


def _delete(path):
    try:
        return bool(xbmcvfs.delete(_translate(path)))
    except Exception:
        return False


def _rename(src, dst):
    try:
        return bool(xbmcvfs.rename(_translate(src), _translate(dst)))
    except Exception:
        return False


def _atomic_write(path, content):
    """Write `content` to a temp sibling then rename it over `path`, so a
    crash/power-loss mid-write can never leave a half-written (truncated)
    file. rename(2) is atomic on the POSIX backends Kodi runs on; on a VFS
    that won't overwrite we fall back to delete+rename. Returns True on
    success. The temp file lives beside the target so the rename stays on
    one filesystem."""
    tmp = path + '.povil-tmp'
    if not _write(tmp, content):
        _delete(tmp)
        return False
    if _rename(tmp, path):
        return True
    # backend refused to overwrite an existing dst -> remove then rename
    _delete(path)
    if _rename(tmp, path):
        return True
    _delete(tmp)
    return False


def _installed():
    """idanplus is present iff its common.py is on disk."""
    return _exists(COMMON_PY)


def heal_display_channels():
    """Step 1 -- the version-agnostic fix. If displayChannels.json exists but
    is not a JSON object, back it up and remove it so idanplus rebuilds a
    fresh dict. Returns 'healed' / 'ok' / 'missing' / 'failed'.

    Note: special://profile resolves to the ACTIVE Kodi profile, so at
    startup this heals the profile in use (typically master). A corrupt file
    under a different, inactive profile is only healed once that profile is
    active -- but the code-harden step is profile-independent and protects
    those too, and deleting is exactly what idanplus's own mode-22 reset does
    (main.py: DelFile(displayChannelsFile))."""
    if xbmcvfs is None:
        return 'failed'
    if not _exists(DISPLAY_CHANNELS_JSON):
        return 'missing'
    # Read + parse. Any failure (unreadable / invalid JSON) is itself a
    # corruption signal -> heal.
    raw = None
    try:
        raw = _read(DISPLAY_CHANNELS_JSON)
    except Exception as e:
        _log('read displayChannels.json failed: {0}'.format(e),
             level='WARNING')
    corrupt = False
    if raw is None:
        corrupt = True
    else:
        try:
            data = json.loads(raw)
            corrupt = not isinstance(data, dict)
        except Exception:
            corrupt = True
    if not corrupt:
        return 'ok'
    # Back the bad file up (best-effort) then drop it. Deleting is what
    # actually matters: with the file gone, idanplus's isFileOld() check is
    # true and GetChannels() rebuilds the map from the remote channels.json.
    if raw is not None:
        try:
            _delete(DISPLAY_CHANNELS_BAK)
            _write(DISPLAY_CHANNELS_BAK, raw)
        except Exception:
            pass
    if _delete(DISPLAY_CHANNELS_JSON) or not _exists(DISPLAY_CHANNELS_JSON):
        _log('healed corrupt displayChannels.json (non-object) -> idanplus '
             'will rebuild channels from the remote list')
        return 'healed'
    _log('could not remove corrupt displayChannels.json', level='WARNING')
    return 'failed'


def harden_common_py():
    """Step 2 -- best-effort source hardening so a future corruption can't
    crash. Returns 'patched' / 'already' / 'no_match' / 'no_target' /
    'failed'."""
    if xbmcvfs is None:
        return 'failed'
    if not _exists(COMMON_PY):
        return 'no_target'
    try:
        src = _read(COMMON_PY)
    except Exception as e:
        _log('read common.py failed: {0}'.format(e), level='WARNING')
        return 'failed'

    already = (_ITEMS_MARK in src) and (_GDC_MARK in src)
    new_src = src
    if _GDC_MARK not in new_src and _GDC_OLD in new_src:
        new_src = new_src.replace(_GDC_OLD, _GDC_NEW, 1)
    if _ITEMS_MARK not in new_src and _ITEMS_OLD in new_src:
        new_src = new_src.replace(_ITEMS_OLD, _ITEMS_NEW, 1)

    if new_src == src:
        return 'already' if already else 'no_match'
    # Keep one pristine copy the first time we touch common.py, so the
    # original is always recoverable even in the worst case.
    if not _exists(COMMON_PY + '.povil-orig'):
        try:
            _write(COMMON_PY + '.povil-orig', src)
        except Exception:
            pass
    if not _atomic_write(COMMON_PY, new_src):
        _log('write common.py failed', level='WARNING')
        return 'failed'
    _log('hardened common.py (GetDisplayChannels/items dict-safe)')
    return 'patched'


def ensure_patched():
    """Heal the data file, then harden the source. No-op when idanplus isn't
    installed. Returns an aggregate status string."""
    if not _installed():
        return 'no_target'
    heal = heal_display_channels()
    harden = harden_common_py()
    return 'heal={0} harden={1}'.format(heal, harden)
