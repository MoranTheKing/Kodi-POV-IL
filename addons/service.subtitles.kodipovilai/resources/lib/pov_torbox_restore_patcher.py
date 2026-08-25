# Put back the TorBox client our own update package overwrote.
#
# WHAT WENT WRONG, IN OUR CODE, NOT POV'S:
#
# The build's quick-update package (Kodi-POV-IL-FENtastic-quickfix-*.zip)
# carried two files belonging to plugin.video.pov:
#
#     addons/plugin.video.pov/resources/lib/debrids/torbox_api.py
#     addons/plugin.video.pov/resources/lib/debrids/torbox.py
#
# They were copies from June, carried forward package after package. Kodi
# extracts a quickfix straight over the add-ons folder, so every quick update
# quietly replaced POV's own TorBox client with those older copies. For weeks
# that was invisible -- the old client still worked.
#
# POV 6.07.92 ended it. Its modules/debrid.py now reads a class attribute the
# June copy does not have:
#
#     file_url = api.unrestrict_link(file_key)
#     if not api.defaults_to_cloud:            # <- AttributeError
#
# Note WHERE that line sits: the source has already resolved successfully and
# the playable URL is in hand. The attribute lookup raises, the whole
# resolve_external_sources() falls into its except, the URL is thrown away, and
# POV moves on to the next source -- and the next, up to Limit Resolve Attempts,
# every one of them failing at the same line. What the user sees is a source
# they picked being skipped, POV running through the rest of the list, and
# "No Results" at the end. Nothing about it points at a file we replaced.
#
# THE REPAIR: restore POV's own 6.07.92 torbox_api.py, byte for byte, and delete
# the torbox.py we planted (POV 6.07.92 has no such file and imports it
# nowhere). The package itself stops carrying both from 0.1.493 on, so this only
# ever has to run on a device an earlier package already touched.
#
# It fires ONLY on the exact damage signature -- POV's debrid.py needs
# defaults_to_cloud and the installed torbox_api.py does not define it. POV
# always ships those two files together, so that combination cannot occur in
# any POV release; it can only be the result of something overwriting one of
# them, which was us. A device that was never damaged is untouched, and once
# POV publishes its next version its own file wins again.

import hashlib
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
DEBRID_REL = 'resources/lib/modules/debrid.py'
TORBOX_API_REL = 'resources/lib/debrids/torbox_api.py'
TORBOX_ORPHAN_REL = 'resources/lib/debrids/torbox.py'
# What debrid.py must actually DO for the damage to bite -- the attribute
# lookup itself, not the bare word, so a POV that merely mentions it somewhere
# else is not mistaken for one that depends on it.
DEBRID_USE = 'api.defaults_to_cloud'
# And what the client must actually DO to satisfy it -- an assignment, not the
# word appearing somewhere. A file that only mentions defaults_to_cloud in a
# comment still raises AttributeError, and reading it as "fine" would leave a
# genuinely broken device unrepaired and told it was healthy.
API_DEFINES_RE = re.compile(rb'^\s*defaults_to_cloud\s*=', re.M)

# POV 6.07.92's own file, kept verbatim beside this module.
GOOD_ASSET = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'pov_repair', 'torbox_api.py')

# The exact copies our packages shipped. Used only to say, in the log, whether
# what we found is precisely what we put there -- the repair itself does not
# depend on the match, because a device that has been through several packages
# may hold a different old copy and still needs the same fix.
STALE_API_MD5 = 'eff4f956224cb8f8ff50bb317337791c'
STALE_ORPHAN_MD5 = '7bc8d9df73b14172c111844f5bfbd07f'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('pov_torbox_restore_patcher: ' + msg, level=level)
    except Exception:
        pass


def _pov_path(rel):
    """POV's file, wherever THIS POV keeps it.

    6.08.14 moved the debrid API clients from debrids/ to indexers/, so a path
    recorded against one layout has to be tried against the other -- and the
    order is decided by POV's own import line, not by which file happens to
    exist. Both folders ship in 6.08.14, so "first one present" would have
    rewritten a stale debrids/torbox_api.py and reported a repair that fixed
    nothing while the live indexers/ copy went untouched.

    An earlier version of this docstring claimed the function had to return a
    path for a MISSING file because this patcher restores one. It does not:
    ensure_patched and _remove_orphan both re-check os.path.isfile and treat a
    missing file exactly as they treat '', so the extra branch was dead code
    that only served to pick the wrong folder.
    """
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath('special://home/addons/' + POV_ADDON_ID + '/')
    except Exception:
        return ''
    for candidate in _relocations(rel, base):
        p = os.path.join(base, *candidate.split('/'))
        if os.path.isfile(p):
            return p
    return ''


_MOVED = (('resources/lib/debrids/', 'resources/lib/indexers/'),
          ('resources/lib/indexers/', 'resources/lib/debrids/'))


def _live_pkg(base):
    """Which package POV ITSELF imports these clients from, or ''."""
    p = os.path.join(base, 'resources', 'lib', 'modules', 'debrid.py')
    try:
        with open(p, encoding='utf-8', errors='replace') as fh:
            text = fh.read()
    except Exception:
        return ''
    for line in text.splitlines():
        s = line.strip()
        for pkg in ('indexers', 'debrids'):
            if s.startswith('from %s import ' % pkg) and '_api' in s:
                return pkg
    return ''


def _relocations(rel, base=''):
    out = [rel]
    for a, b in _MOVED:
        if rel.startswith(a):
            alt = b + rel[len(a):]
            if alt not in out:
                out.append(alt)
    pkg = _live_pkg(base) if base else ''
    if pkg:
        out.sort(key=lambda c: 0 if '/%s/' % pkg in c else 1)
    return out


def _relocations(rel):
    out = [rel]
    for a, b in _MOVED:
        if rel.startswith(a):
            alt = b + rel[len(a):]
            if alt not in out:
                out.append(alt)
    return out


def _read_bytes(path):
    try:
        with open(path, 'rb') as f:
            return f.read()
    except Exception:
        return None


def _drop_pyc(path, stem):
    pycache = os.path.join(os.path.dirname(path), '__pycache__')
    if not os.path.isdir(pycache):
        return
    for fn in os.listdir(pycache):
        if fn.startswith(stem + '.') and fn.endswith('.pyc'):
            try:
                os.remove(os.path.join(pycache, fn))
            except OSError:
                pass


def _remove_orphan():
    """Delete the torbox.py our packages planted -- but only if it is byte for
    byte the file we shipped. Anything else is not ours to remove."""
    path = _pov_path(TORBOX_ORPHAN_REL)
    if not path or not os.path.isfile(path):
        return 'absent'
    body = _read_bytes(path)
    if body is None:
        return 'unreadable'
    if hashlib.md5(body).hexdigest() != STALE_ORPHAN_MD5:
        return 'not_ours'
    try:
        os.remove(path)
    except OSError as e:
        _log('could not remove the orphan torbox.py: {0}'.format(e),
             level='WARNING')
        return 'remove_failed'
    try:
        _drop_pyc(path, 'torbox')
    except Exception:
        pass
    return 'removed'


def ensure_patched():
    """Returns 'no_pov' | 'not_damaged' | 'no_asset' | 'bad_asset'
    | 'restored' | 'read_failed' | 'write_failed'."""
    api_path = _pov_path(TORBOX_API_REL)
    debrid_path = _pov_path(DEBRID_REL)
    if not api_path or not os.path.isfile(api_path) \
            or not os.path.isfile(debrid_path):
        return 'no_pov'

    debrid_src = _read_bytes(debrid_path)
    api_src = _read_bytes(api_path)
    if debrid_src is None or api_src is None:
        return 'read_failed'

    # The torbox.py we planted is ours to clear up whether or not the client
    # still needs restoring -- POV's own next update fixes torbox_api.py
    # without deleting a file it no longer ships, and the orphan would
    # otherwise sit there for good.
    try:
        orphan = _remove_orphan()
    except Exception:
        orphan = 'error'

    if DEBRID_USE.encode('ascii') not in debrid_src:
        # This POV does not read the attribute, so whatever TorBox client is on
        # disk is not causing this failure. Leave it alone.
        return 'not_damaged'
    if API_DEFINES_RE.search(api_src):
        return 'not_damaged'

    good = _read_bytes(GOOD_ASSET)
    if not good:
        _log('POV needs a TorBox client we do not have a copy of -- skipping',
             level='WARNING')
        return 'no_asset'
    try:
        # Never hand POV a file that will not import. modules/debrid.py imports
        # debrids.torbox_api at module scope, so a truncated or corrupted asset
        # would not merely leave TorBox broken -- it would take down every
        # debrid path that reaches modules.debrid, which is worse than the bug
        # being fixed here.
        compile(good, api_path, 'exec')
    except (SyntaxError, ValueError) as e:
        _log('our copy of POV\'s TorBox client will not compile -- refusing '
             'to install it ({0})'.format(e), level='WARNING')
        return 'bad_asset'

    tmp = api_path + '.aitmp'
    try:
        with open(tmp, 'wb') as f:
            f.write(good)
        os.replace(tmp, api_path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('could not restore torbox_api.py: {0}'.format(e), level='WARNING')
        return 'write_failed'

    # The repair is on disk from here on. Nothing below may turn a completed
    # restore into a reported failure, so the tidying is guarded on its own.
    try:
        _drop_pyc(api_path, 'torbox_api')
    except Exception:
        pass
    was_ours = hashlib.md5(api_src).hexdigest() == STALE_API_MD5
    _log('POV\'s TorBox client was an old copy that our own update package '
         'had written over it{0}; every TorBox source resolved and was then '
         'thrown away on api.defaults_to_cloud, which is why picking a source '
         'ran through the whole list and ended in "No Results". Restored POV '
         '6.07.92\'s own file (orphan torbox.py: {1}).'.format(
             '' if was_ours else ' (a variant, not the exact copy we shipped)',
             orphan), level='INFO')
    return 'restored'
