# -*- coding: utf-8 -*-
"""Headless resolver and installer for third-party CONTENT addons.

WHY THIS EXISTS
---------------
Traditionally, installing 3rd-party addons (POV, YouTube, Otaku) relied on Kodi's native
`InstallAddon(id)`. That triggers intrusive Kodi dialogs (dependency confirmations, progress
bars, first-run popups) which required aggressive, buggy watchdogs to suppress.

This module bypasses native Kodi dialogs entirely by resolving the dependency tree from
locally installed repositories (kodifitzwell, xbmc.org, etc.), downloading the zips directly,
and extracting them into special://home/addons.

NEW UNIFIED ARCHITECTURE (PHASE 2)
----------------------------------
While the extraction remains "headless" (bypassing Kodi's native engine), it is NO LONGER
silent to the user. This module now calculates the total download queue—dynamically resolving
addon types (e.g., `script.module`, `resource.language`) and friendly names—and injects it
directly into the ALREADY RUNNING `install_manager` UI queue.

Any binary/platform-specific dependencies (e.g., inputstream.adaptive) that cannot be resolved
headlessly are returned to the Orchestrator, which safely handles them via a minimal native
Kodi fallback AFTER the custom UI gracefully closes.
"""
import gzip
import os
import re

try:
    import xbmc
except Exception:
    xbmc = None

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

from resources.libs.common import logging
from resources.libs.common import tools
from resources.libs.common.config import CONFIG

try:
    from resources.libs import db
except Exception:
    db = None

try:
    from resources.libs import extract
except Exception:
    extract = None

try:
    from resources.libs.downloader import Downloader
except Exception:
    Downloader = None


# Dependencies Kodi provides itself (the python runtime, gui bindings, resources
# virtual packages...). Never something we download.
VIRTUAL_PREFIXES = ('xbmc.', 'kodi.')

# Binary / platform-specific addons. A repo's addons.xml lists one version per
# Kodi codename, but the actual binary must match the device's OS+arch+ABI, so we
# must NEVER blindly extract a zip for these -- we'd risk planting a binary built
# for the wrong platform. They are almost always bundled with Kodi already; if one
# is genuinely missing, we leave its dependent to the native fallback so Kodi
# installs the platform-correct build itself.
BINARY_PREFIXES = ('inputstream.', 'peripheral.', 'vfs.', 'audioencoder.',
                   'audiodecoder.', 'imagedecoder.', 'pvr.', 'game.',
                   'screensaver.', 'visualization.')

_ADDON_RE = re.compile(r'<addon\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</addon>', re.DOTALL)
_VER_RE = re.compile(r'\bversion="([^"]+)"')
_IMPORT_RE = re.compile(r'<import\b[^>]*\baddon="([^"]+)"')
_INFO_RE = re.compile(r'<info\b[^>]*>([^<]+)</info>')
_DATADIR_RE = re.compile(r'<datadir\b[^>]*>([^<]+)</datadir>')


def _log(msg, level=None):
    try:
        logging.log('[HeadlessInstaller] ' + msg,
                    level=level if level is not None else (xbmc.LOGINFO if xbmc else 0))
    except Exception:
        pass


def _version_tuple(v):
    """Loose, never-throwing version compare key (digits only, dotted)."""
    parts = []
    for chunk in re.split(r'[._-]', str(v or '')):
        m = re.match(r'\d+', chunk)
        parts.append(int(m.group(0)) if m else 0)
    return tuple(parts)


# --------------------------------------------------------------------------- #
#  Pure parsing helpers (no Kodi calls -- unit-testable).                      #
# --------------------------------------------------------------------------- #
def _parse_repo_extension(addon_xml_text):
    """From a repository addon's addon.xml, return [(info_url, datadir), ...].

    A repo can declare several <dir> blocks (one per Kodi codename); we pair the
    Nth <info> with the Nth <datadir> positionally, falling back to the last
    datadir when counts differ."""
    infos = [s.strip() for s in _INFO_RE.findall(addon_xml_text)]
    datadirs = [s.strip() for s in _DATADIR_RE.findall(addon_xml_text)]
    out = []
    for i, info in enumerate(infos):
        if i < len(datadirs):
            dd = datadirs[i]
        elif datadirs:
            dd = datadirs[-1]
        else:
            dd = ''
        out.append((info, dd))
    return out


def _parse_addons_xml(text):
    """Parse an addons.xml document into {id: {'version':, 'requires':[...]}}.

    Keeps the highest version when an id appears more than once."""
    index = {}
    for m in _ADDON_RE.finditer(text or ''):
        aid, body = m.group(1), m.group(2)
        head = text[m.start():m.start(2)]
        vm = _VER_RE.search(head)
        version = vm.group(1) if vm else '0'
        requires = [d for d in _IMPORT_RE.findall(body)
                    if not d.startswith(VIRTUAL_PREFIXES)]
        prev = index.get(aid)
        if prev and _version_tuple(prev['version']) >= _version_tuple(version):
            continue
        index[aid] = {'version': version, 'requires': requires}
    return index


def _zip_url(datadir, addon_id, version):
    """Standard Kodi repo layout: <datadir>/<id>/<id>-<version>.zip."""
    base = (datadir or '').rstrip('/')
    return '{0}/{1}/{1}-{2}.zip'.format(base, addon_id, version)


# --------------------------------------------------------------------------- #
#  Installer (Kodi-side).                                                       #
# --------------------------------------------------------------------------- #
class HeadlessInstaller:
    def __init__(self):
        self.index = {}        # id -> {'version', 'requires', 'datadir'}
        self.unresolved = set()
        self._loaded = False

    # ---- repo discovery + index -------------------------------------------- #
    def _addon_roots(self):
        roots = []
        for sp in ('special://home/addons', 'special://xbmc/addons'):
            try:
                p = xbmcvfs.translatePath(sp) if xbmcvfs else sp
            except Exception:
                p = None
            if p and os.path.isdir(p) and p not in roots:
                roots.append(p)
        return roots

    def _iter_installed_repos(self):
        """Yield (repo_name, [(info_url, datadir), ...]) for every repository
        addon on disk. The pair list preserves the order declared in addon.xml
        (Kodi lists newest codename first), so callers can stop after the first
        pair that yields a usable index instead of fetching every codename."""
        seen = set()
        for root in self._addon_roots():
            try:
                names = os.listdir(root)
            except Exception:
                continue
            for name in names:
                if not name.startswith('repository.') or name in seen:
                    continue
                axml = os.path.join(root, name, 'addon.xml')
                if not os.path.isfile(axml):
                    continue
                try:
                    with open(axml, 'r', encoding='utf-8', errors='replace') as fh:
                        txt = fh.read()
                except Exception:
                    continue
                if 'xbmc.addon.repository' not in txt:
                    continue
                pairs = [(i, d) for i, d in _parse_repo_extension(txt) if i and d]
                if pairs:
                    seen.add(name)
                    yield name, pairs

    def _fetch_text(self, url):
        """Fetch a repository index without a separate, slow HEAD probe."""
        import time
        data = None

        # Kodi's C++ VFS has its own TLS stack. On some 32-bit Windows Kodi
        # builds Python can spend tens of seconds creating an SSL context, so
        # use VFS for HTTPS before entering Python's certificate path.
        if url.startswith('https://') and xbmcvfs is not None:
            try:
                source = xbmcvfs.File(url)
                try:
                    data = bytes(source.readBytes())
                finally:
                    source.close()
            except Exception as e:
                _log('Kodi VFS repository fetch failed for {0}: {1}'.format(url, e),
                     level=xbmc.LOGWARNING)
        if data and len(data) > 8 * 1024 * 1024:
            _log('repository index exceeds 8 MiB: {0}'.format(url),
                 level=xbmc.LOGWARNING)
            return None

        # tools.open_url performs HEAD before GET. On Kodi's embedded Python,
        # the HEAD TLS handshake can occupy the first-install dialog for an
        # entire timeout even when the repository is otherwise reachable.
        # Try one bounded GET if VFS had no data; retain the old proxy-aware
        # route for users whose network needs it.
        if not data:
            try:
                from urllib.request import Request, ProxyHandler, build_opener
                request = Request(url, headers={'User-Agent': CONFIG.USER_AGENT,
                                                'Accept-Encoding': 'identity'})
                with build_opener(ProxyHandler({})).open(request, timeout=8) as response:
                    data = response.read(8 * 1024 * 1024 + 1)
                if len(data) > 8 * 1024 * 1024:
                    _log('repository index exceeds 8 MiB: {0}'.format(url),
                         level=xbmc.LOGWARNING)
                    return None
            except Exception as e:
                _log('direct repository fetch failed for {0}: {1}'.format(url, e),
                     level=xbmc.LOGWARNING)

        for attempt in range(2 if not data else 0):
            try:
                r = tools.open_url(url)
                if r and r.content:
                    data = r.content
                    break
            except Exception as e:
                _log('Python fetch error {0} on {1}: {2}'.format(attempt+1, url, e), level=xbmc.LOGWARNING)

            # SSL/VFS Race Condition Fix: Fallback to Kodi's native C++ VFS engine
            try:
                _log('Falling back to xbmcvfs.File C++ engine for {0}'.format(url), level=xbmc.LOGINFO)
                f = xbmcvfs.File(url)
                read_bytes = f.readBytes()
                f.close()
                if read_bytes:
                    data = bytearray(read_bytes)
                    break
            except Exception as e:
                _log('xbmcvfs fetch failed: {0}'.format(e), level=xbmc.LOGWARNING)

            time.sleep(1)

        if not data:
            _log('Completely failed to fetch: {0}'.format(url), level=xbmc.LOGERROR)
            return None

        if data[:2] == b'\x1f\x8b' or url.endswith('.gz'):
            try:
                data = gzip.decompress(data)
            except Exception as e:
                _log('gunzip failed {0}: {1}'.format(url, e), level=xbmc.LOGERROR)
                return None
        try:
            return data.decode('utf-8', 'replace')
        except Exception:
            return None

    def load_index(self, wanted_ids=None):
        """Load only enough repository metadata to resolve requested addons.

        The old all-repository scan delayed even a single missing addon behind
        unrelated repositories. Keep scanning when a dependency is unknown.
        """
        if self._loaded:
            return
        wanted = tuple(wanted_ids or ())
        hints = {
            'script.module.acctmgr': 'repository.709',
            'plugin.video.pov': 'repository.kodifitzwell',
            'plugin.video.idanplus': 'repository.Fishenzon',
            'plugin.video.youtube': 'repository.xbmc.org',
            'resource.language.he_il': 'repository.xbmc.org',
            'script.xbmc.unpausejumpback': 'repository.xbmc.org',
            'plugin.video.otaku': 'repository.otaku',
        }
        preferred = {hints[aid] for aid in wanted if aid in hints}
        repos = list(self._iter_installed_repos())
        repos.sort(key=lambda entry: entry[0] not in preferred)
        for repo_name, pairs in repos:
            # Stop at the first pair (codename) that yields a usable index, so the
            # big official repo costs ONE addons.xml(.gz) fetch, not one per
            # codename.
            for info_url, datadir in pairs:
                text = self._fetch_text(info_url)
                if not text:
                    _log('repo {0}: could not load {1}'.format(repo_name, info_url), level=xbmc.LOGERROR)
                    continue
                sub = _parse_addons_xml(text)
                if not sub:
                    continue
                added = 0
                for aid, meta in sub.items():
                    prev = self.index.get(aid)
                    if prev and _version_tuple(prev['version']) >= _version_tuple(meta['version']):
                        continue
                    self.index[aid] = {'version': meta['version'],
                                       'requires': meta['requires'],
                                       'datadir': datadir}
                    added += 1
                _log('repo {0}: indexed {1} addons from {2}'.format(repo_name, added, info_url))
                break
            if wanted and self._targets_indexed(wanted):
                break
        self._loaded = True
        _log('union index built: {0} addons across all repos'.format(len(self.index)))

    def _targets_indexed(self, wanted):
        """True when requested addons and non-native dependencies are known."""
        def known(aid, visiting):
            if (aid.startswith(VIRTUAL_PREFIXES) or self._installed(aid) or
                    aid.startswith(BINARY_PREFIXES)):
                return True
            if aid in visiting:
                return True
            meta = self.index.get(aid)
            if not meta:
                return False
            return all(known(dep, visiting | {aid}) for dep in meta['requires'])

        return all(known(aid, set()) for aid in wanted)

    # ---- resolution -------------------------------------------------------- #
    def _installed(self, addon_id):
        if xbmc is None:
            return False
        try:
            return bool(xbmc.getCondVisibility('System.HasAddon({0})'.format(addon_id)))
        except Exception:
            return False

    def _resolve(self, wanted):
        """Return a deps-first install order containing only fully-resolvable,
        not-yet-installed addons. Records anything missing in self.unresolved."""
        order, order_set = [], set()
        cache, visiting = {}, set()

        def visit(aid):
            if aid.startswith(VIRTUAL_PREFIXES):
                return True
            if self._installed(aid):
                return True
            if aid.startswith(BINARY_PREFIXES):
                # Not installed + binary -> we won't extract it. Treat as
                # unresolved so any dependent drops to the native fallback (Kodi
                # installs the platform-correct binary).
                self.unresolved.add(aid)
                return False
            if aid in cache:
                return cache[aid]
            if aid in visiting:          # dependency cycle -> assume satisfiable
                return True
            meta = self.index.get(aid)
            if not meta:
                self.unresolved.add(aid)
                cache[aid] = False
                return False
            visiting.add(aid)
            ok = all(visit(dep) for dep in meta['requires'])
            visiting.discard(aid)
            cache[aid] = ok
            if ok and aid not in order_set:
                order.append(aid)
                order_set.add(aid)
            elif not ok:
                # LOGIC BUG FIX: The addon was found in index, but a dependency failed.
                # It MUST be added to unresolved so Native Fallback can rescue it.
                _log('Dependency resolution failed for {0}, sending to Native Fallback'.format(aid), level=xbmc.LOGWARNING)
                self.unresolved.add(aid)

            return ok

        for w in wanted:
            visit(w)
        return order

    # ---- download + extract ------------------------------------------------ #
    def _download_extract(self, addon_id, meta):
        if Downloader is None or extract is None:
            return False
        url = _zip_url(meta['datadir'], addon_id, meta['version'])
        zp = os.path.join(CONFIG.PACKAGES, '{0}_provision.zip'.format(addon_id))
        tools.remove_file(zp)
        try:
            Downloader(progress_dialog_bg=True).download(url, zp)
        except Exception as e:
            _log('download failed {0}: {1}'.format(addon_id, e),
                 level=xbmc.LOGERROR if xbmc else 0)
            return False
        if not os.path.exists(zp) or os.path.getsize(zp) == 0:
            _log('download produced no file: {0}'.format(addon_id))
            return False
        try:
            extract.all(zp, CONFIG.ADDONS, ignore=True, progress_dialog_bg=True)
        except Exception as e:
            _log('extract failed {0}: {1}'.format(addon_id, e),
                 level=xbmc.LOGERROR if xbmc else 0)
            tools.remove_file(zp)
            return False
        tools.remove_file(zp)
        return True

    def install(self, wanted_ids):
        """Headlessly install wanted_ids + their resolvable deps.

        Returns (installed_ids, missing_ids) where missing_ids are the REQUESTED
        ids that could not be fully provisioned headlessly (caller may fall back
        to native InstallAddon for those)."""
        try:
            tools.ensure_folders(CONFIG.PACKAGES)
        except Exception:
            pass
        self.load_index(a for a in wanted_ids if not self._installed(a))

        already = [a for a in wanted_ids if self._installed(a)]
        for a in already:
            _log('{0} already present -- skipping'.format(a))

        order = self._resolve(wanted_ids)
        _log('resolved install order ({0}): {1}'.format(len(order), order))
        if self.unresolved:
            _log('unresolved (will need native fallback): {0}'.format(sorted(self.unresolved)),
                 level=xbmc.LOGWARNING if xbmc else 0)

        installed_ok = set()
        for aid in order:
            meta = self.index[aid]
            deps_ready = all(
                d.startswith(VIRTUAL_PREFIXES) or self._installed(d) or d in installed_ok
                for d in meta['requires']
            )
            if not deps_ready:
                _log('deferring {0} -- a dependency is not in place'.format(aid),
                     level=xbmc.LOGWARNING if xbmc else 0)
                continue
            _log('installing {0} {1} (headless)'.format(aid, meta['version']))
            if self._download_extract(aid, meta):
                installed_ok.add(aid)

        # Register + load everything we extracted, in one pass.
        if installed_ok and db is not None:
            try:
                db.addon_database(sorted(installed_ok), 1, True)
            except Exception as e:
                _log('addon DB register failed: {0}'.format(e),
                     level=xbmc.LOGERROR if xbmc else 0)
        if installed_ok and xbmc is not None:
            try:
                xbmc.executebuiltin('UpdateLocalAddons')
                xbmc.sleep(1500)
            except Exception:
                pass
            # The sqlite write does not flip Kodi's in-memory state, so enable
            # each extracted addon explicitly -- otherwise it stays DISABLED,
            # System.HasAddon returns false, and the heal/provision pass would
            # re-extract it forever.
            for _aid in sorted(installed_ok):
                try:
                    q = ('{"jsonrpc":"2.0","id":1,"method":"Addons.SetAddonEnabled",'
                         '"params":{"addonid":"%s","enabled":true}}' % _aid)
                    xbmc.executeJSONRPC(q)
                except Exception:
                    pass

        # A requested id is "missing" if it is still not visible to Kodi.
        missing = [a for a in wanted_ids if not self._installed(a)]
        _log('headless install done. installed={0} missing={1}'.format(
            sorted(installed_ok), missing))
        return sorted(installed_ok), missing

    def _get_type(self, aid):
        if aid.startswith('script.module.'): return 'module'
        if aid.startswith('resource.language.'): return 'language'
        if aid.startswith('plugin.video.'): return 'plugin'
        if aid.startswith('plugin.audio.'): return 'plugin'
        if aid.startswith('plugin.program.'): return 'plugin'
        if aid.startswith('skin.'): return 'skin'
        if aid.startswith('repository.'): return 'repository'
        return 'addon'

    def resolve_and_prepare(self, wanted_ids):
        """Phase 2 Preparer: Headlessly resolve missing dependencies and return jobs
        for dynamic UI injection, avoiding native popups. Unresolvable/Binary items are
        returned as a fallback tuple list for Kodi to handle natively."""
        missing = [aid for aid in wanted_ids if not self._installed(aid)]
        if not missing:
            _log('all requested addons already present; no repo fetch needed')
            return [], []
        self.load_index(missing)
        order = self._resolve(missing)
        _log('resolve_and_prepare calculated install order: {0}'.format(order))

        phase2_jobs = []
        for aid in order:
            if aid in self.unresolved:
                continue
            meta = self.index.get(aid)
            if not meta:
                continue

            phase2_jobs.append({
                'id': aid,
                'name': aid,
                'version': meta['version'],
                'zip': _zip_url(meta['datadir'], aid, meta['version']),
                'type': self._get_type(aid)
            })

        native_missing = [aid for aid in self.unresolved]
        return phase2_jobs, native_missing
