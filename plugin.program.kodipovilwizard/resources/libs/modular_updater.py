import os
import xbmc
import xbmcgui
import json

from resources.libs.common.config import CONFIG
from resources.libs import youtube_platform
from resources.libs.common import logging
from resources.libs.common import tools
# Download/extraction and config modules are imported at their call sites.
# Loading them during startup delayed AF3's first modular check even when
# there was no addon ZIP to install.


class ModularUpdater:
    # NOX is required for fresh installs. Existing users install it only
    # through Switch Skin; OTA never changes their chosen skin.
    ON_DEMAND_SKINS = frozenset(('skin.povil.nox',))

    @staticmethod
    def _pending_addon_receipt(addon_id):
        from resources.libs import addon_install_receipt
        return addon_install_receipt.needs_retry(
            os.path.join(CONFIG.ADDON_DATA, CONFIG.ADDON_ID), addon_id)

    def __init__(self, background=False):
        self.background = background
        self.dialog = xbmcgui.Dialog()
        self.progress = xbmcgui.DialogProgressBG() if background else xbmcgui.DialogProgress()
        # MANIFEST_URL is mapped onto CONFIG in config.py -> init_uservars()
        # (and defined in uservar.py). getattr keeps us safe if it is missing.
        self.manifest_url = getattr(CONFIG, 'MANIFEST_URL', 'http://missing_manifest_url')

    def _version_tuple(self, ver):
        """Convert string versions (e.g. '5.12.04', '0.6.20a') into comparable
        numeric tuples.

        NOTE (fix #4): the original split-on-dot logic dropped trailing
        letters, so '0.6.20a' and '0.6.20b' compared equal and a letter-only
        bump (which our build actually uses for script.fentastic.helper) would
        never be detected. We now append the letter as an extra ordinal
        component: '0.6.20' -> (0,6,20), '0.6.20a' -> (0,6,20,1) < (0,6,20,2).
        """
        parts = []
        for chunk in str(ver).split('.'):
            num = ''.join(ch for ch in chunk if ch.isdigit())
            suffix = ''.join(ch for ch in chunk if ch.isalpha())
            parts.append(int(num) if num else 0)
            if suffix:
                parts.append(ord(suffix[0].lower()) - 96)  # a->1, b->2, ...
        return tuple(parts)

    @staticmethod
    def _on_disk(addon_id):
        """True when the addon's folder + addon.xml physically exist under
        special://home/addons -- i.e. it was extracted, regardless of whether
        Kodi currently considers it enabled."""
        try:
            return os.path.exists(os.path.join(CONFIG.ADDONS, addon_id, 'addon.xml'))
        except Exception:
            return False

    @staticmethod
    def _enable_addon(addon_id):
        """Enable an installed addon in the RUNNING Kodi via JSON-RPC.

        Writing enabled=1 straight into Addons??.db (db.addon_database) does NOT
        flip Kodi's in-memory state, so after a raw zip extract an addon can sit
        DISABLED -- System.HasAddon then returns false and heal_missing_addons
        would re-download it on every launch forever (the fishenzon loop). A
        JSON-RPC SetAddonEnabled makes the enable actually stick at runtime."""
        try:
            q = json.dumps({'jsonrpc': '2.0', 'id': 1,
                            'method': 'Addons.SetAddonEnabled',
                            'params': {'addonid': addon_id, 'enabled': True}})
            response = json.loads(xbmc.executeJSONRPC(q))
            return ('error' not in response and response.get('result') in ('OK', True))
        except Exception as e:
            logging.log("[ModularUpdater] enable {0} failed: {1}".format(addon_id, e),
                        level=xbmc.LOGWARNING)
            return False

    @staticmethod
    def _runtime_addon_enabled(addon_id):
        """Fail closed if Kodi cannot prove the old service is stopped."""
        try:
            request = json.dumps({
                'jsonrpc': '2.0', 'id': 1, 'method': 'Addons.GetAddonDetails',
                'params': {'addonid': addon_id, 'properties': ['enabled']}})
            response = json.loads(xbmc.executeJSONRPC(request))
            addon = response['result']['addon']
            if addon.get('addonid') != addon_id:
                return True
            enabled = addon.get('enabled')
            return enabled if isinstance(enabled, bool) else True
        except Exception:
            return True

    def get_local_version(self, addon_id):
        """Read the local addon.xml to find the currently installed version.

        Returns None when the addon is NOT installed on this device.
        """
        addon_xml = os.path.join(CONFIG.ADDONS, addon_id, 'addon.xml')
        if not os.path.exists(addon_xml):
            return None
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(addon_xml)
            return tree.getroot().get('version')
        except Exception as e:
            logging.log("[ModularUpdater] Failed to parse local {0} XML: {1}".format(addon_id, e), level=xbmc.LOGERROR)
            return None

    def _load_manifest(self):
        """Fetch the small manifest once with an explicit network timeout."""
        try:
            logging.log('[ModularUpdater] loading manifest HTTP client', level=xbmc.LOGINFO)
            from urllib.request import Request, ProxyHandler, build_opener
            logging.log('[ModularUpdater] HTTP client ready', level=xbmc.LOGINFO)
            request = Request(self.manifest_url,
                              headers={'User-Agent': CONFIG.USER_AGENT})
            # The process-wide opener may spend unbounded time discovering a
            # Windows proxy/PAC before socket timeout starts. Direct access
            # keeps the boot check bounded on devices without a proxy.
            opener = build_opener(ProxyHandler({}))
            logging.log('[ModularUpdater] requesting manifest', level=xbmc.LOGINFO)
            with opener.open(request, timeout=8) as response:
                payload = response.read(2 * 1024 * 1024 + 1)
            logging.log('[ModularUpdater] manifest downloaded', level=xbmc.LOGINFO)
            if len(payload) > 2 * 1024 * 1024:
                raise ValueError('manifest exceeds 2 MiB')
            manifest = json.loads(payload)
            if not isinstance(manifest, dict) or not isinstance(
                    manifest.get('addons'), dict):
                raise ValueError('manifest has no addons object')
            return manifest
        except Exception as exc:
            logging.log('[ModularUpdater] manifest fetch failed: {0}'.format(exc),
                        level=xbmc.LOGERROR)
            return None

    def run_update_check(self):
        """Fetch manifest, diff versions, and execute necessary updates."""
        logging.log("[ModularUpdater] Starting modular update check...", level=xbmc.LOGINFO)

        # A previously prepared clean POV tree can be completed offline. The
        # legacy subtitle service has had a full intervening Kodi process to
        # observe its POV-writers-off setting before this code moves the host.
        if (not getattr(self, 'fresh', False) and
                getattr(globals().get('CONFIG'), 'ADDONS', None) and
                getattr(CONFIG, 'USERDATA', None)):
            try:
                from resources.libs import pov_host_handoff
                pov_host = os.path.join(CONFIG.ADDONS, 'plugin.video.pov')
                if pov_host_handoff.complete(pov_host, CONFIG.USERDATA):
                    logging.log('[ModularUpdater] Clean POV host activated and '
                                'validated; previous code retained for rollback.',
                                level=xbmc.LOGINFO)
            except Exception as exc:
                logging.log('[ModularUpdater] Clean POV handoff deferred or '
                            'rolled back: {0}'.format(exc), level=xbmc.LOGERROR)

        # A power loss in the few milliseconds between directory renames may
        # leave the old service in the private backup location. Restore it
        # before reading versions, including when the manifest is offline.
        if (getattr(globals().get('CONFIG'), 'ADDON_DATA', None) and
                getattr(CONFIG, 'ADDONS', None)):
            try:
                from resources.libs import staged_addon_install
                service_zip = os.path.join(CONFIG.ADDON_DATA, CONFIG.ADDON_ID,
                                           'ota-packages',
                                           'service.subtitles.kodipovilai_update.zip')
                staged_addon_install.recover(CONFIG.ADDONS, service_zip,
                                             'service.subtitles.kodipovilai')
            except Exception as exc:
                logging.log('[ModularUpdater] service recovery failed: {0}'.format(exc),
                            level=xbmc.LOGERROR)
                return False
            try:
                from resources.libs import addon_install_receipt
                data_dir = os.path.join(CONFIG.ADDON_DATA, CONFIG.ADDON_ID)
                pending_addons = addon_install_receipt.pending_addons(data_dir)
                if pending_addons:
                    from resources.libs import staged_addon_install
                for addon_id in pending_addons:
                    if addon_id == 'service.subtitles.kodipovilai':
                        continue
                    staged_addon_install.recover(CONFIG.ADDONS, CONFIG.ADDONS,
                                                 addon_id)
            except Exception as exc:
                logging.log('[ModularUpdater] interrupted add-on recovery failed: {0}'
                            .format(exc), level=xbmc.LOGERROR)
                return False
        # Finish a package prepared on the previous boot before any network
        # request. The old service has already acknowledged and exited; a
        # manifest outage must not strand a complete local handoff.
        if not getattr(self, 'fresh', False):
            self._complete_pending_service_handoff()

        # 1. Fetch Remote Manifest
        self._manifest_checked = True
        manifest = self._load_manifest()
        if not manifest:
            if not self.background:
                self.dialog.ok(CONFIG.ADDONTITLE, "שגיאה בתקשורת מול שרת העדכונים.")
            return False

        addons = manifest.get('addons', {})

        if not getattr(self, 'fresh', False) and hasattr(self, '_prepare_clean_pov_host'):
            self._prepare_clean_pov_host(manifest)

        # Keep the parsed manifest so execute_updates can also apply the
        # build-config pack (skin/locale/favourites/sources/...) in the same
        # pass, at the value/id level -- without clobbering the user's keys.
        self._manifest = manifest

        # 2. Compare Versions
        #
        # FIX #2 (safety): only update addons that are ALREADY installed.
        # The manifest lists ALL build addons -- including the on-demand
        # skin.povil.nox (31MB) and the other skins. The original
        # "install if not local_ver" branch would silently force-install
        # every missing skin onto every device on the first check, which
        # fights the build's on-demand-skin design (startup.py only ever
        # refreshes the *active* skin pack). New addons are installed by
        # their own flows (Fresh Install / Switch Skin), never here.
        #
        # If you ever DO want this updater to also install missing addons,
        # set self.install_missing = True before calling run_update_check().
        install_missing = getattr(self, 'install_missing', False)

        update_queue = []
        for addon_id, mod in addons.items():
            remote_ver = mod.get('version')
            local_ver = self.get_local_version(addon_id)

            if not remote_ver:
                continue

            pending = False
            if getattr(self, 'fresh', False):
                pending = self._pending_addon_receipt(addon_id)
            elif addon_id != 'service.subtitles.kodipovilai':
                from resources.libs import addon_install_receipt
                pending = addon_install_receipt.needs_retry(
                    os.path.join(CONFIG.ADDON_DATA, CONFIG.ADDON_ID), addon_id)
            if not local_ver:
                if (addon_id in self.ON_DEMAND_SKINS and not pending
                        and not getattr(self, 'fresh', False)):
                    logging.log('[ModularUpdater] on-demand skin remains optional: {0}'
                                .format(addon_id), level=xbmc.LOGINFO)
                    continue
                if install_missing or pending:
                    update_queue.append(mod)
                else:
                    logging.log("[ModularUpdater] Skipping not-installed addon {0}".format(addon_id),
                                level=xbmc.LOGINFO)
                continue

            if pending or self._version_tuple(local_ver) < self._version_tuple(remote_ver):
                logging.log("[ModularUpdater] {0}: {1} -> {2}".format(addon_id, local_ver, remote_ver),
                            level=xbmc.LOGINFO)
                update_queue.append(mod)

        # On a pre-modular build the old MoranSubs service still owns the
        # self-healing edits inside POV. PatchEngine intentionally refuses to
        # mix its new hooks with that tree. Keep the old repair service until
        # POV has a clean host; replacing it now would leave neither owner
        # able to repair those files after the next POV update.
        # A clean installation has no old service to hand off. Kodi reports
        # an error for an unknown addon; the conservative live-service probe
        # deliberately treats that error as running. Do not mistake an absent
        # addon on a fresh profile for a legacy service. Existing trees still
        # require the full handoff protocol, even during manual provisioning.
        initial_service_install = (getattr(self, 'fresh', False) and
                                   not self._on_disk('service.subtitles.kodipovilai'))
        if (not initial_service_install and
                any(mod.get('id') == 'service.subtitles.kodipovilai'
                    for mod in update_queue)):
            service_mod = next(mod for mod in update_queue if
                               mod.get('id') == 'service.subtitles.kodipovilai')
            if self._runtime_addon_enabled('service.subtitles.kodipovilai'):
                if self._service_handoff_ready():
                    self._prepare_service_handoff(service_mod)
                else:
                    logging.log('[ModularUpdater] Keeping legacy MoranSubs until '
                                'POV patches and clean-host migration are verified.',
                                level=xbmc.LOGWARNING)
                update_queue = [mod for mod in update_queue
                                if mod.get('id') != 'service.subtitles.kodipovilai']
            elif not self._service_handoff_ready():
                update_queue = [mod for mod in update_queue
                                if mod.get('id') != 'service.subtitles.kodipovilai']
                logging.log('[ModularUpdater] Service disabled, but POV handoff '
                            'is not ready.', level=xbmc.LOGWARNING)

        # 3. Execute Updates if needed
        #
        # The build-config pack carries its own version, independent of the
        # addons. A user can be up to date on code but behind on config (e.g.
        # a new skin tweak / extra repo source), so we run the update pass when
        # EITHER an addon moved OR the config moved.
        config_pending = self._config_pending(manifest)
        fresh = getattr(self, 'fresh', False)
        logging.log('[ModularUpdater] update queue={0}, config_pending={1}, fresh={2}'
                    .format(len(update_queue), config_pending, fresh), level=xbmc.LOGINFO)
        if not update_queue and not config_pending and not fresh:
            self._record_build_identity(manifest)
            logging.log("[ModularUpdater] All modules and config are up to date.", level=xbmc.LOGINFO)
            if not self.background:
                self.dialog.ok(CONFIG.ADDONTITLE, "כל ההרחבות מעודכנות לגרסה האחרונה.")
            return True

        # Fresh install ALWAYS falls through to execute_updates even with an
        # empty queue, so provisioning + the .provisioned marker still run on a
        # device that already happens to have every addon (e.g. resuming an
        # interrupted setup whose addons all landed but whose config / marker
        # never did).
        logging.log('[ModularUpdater] entering execute_updates', level=xbmc.LOGINFO)
        success = self.execute_updates(update_queue)
        if success:
            self._record_build_identity(manifest)
        return success

    def _record_build_identity(self, manifest):
        """An OTA completion updates the build label too; never certify a failure."""
        if self._config_pending(manifest):
            return False
        for addon_id, mod in (manifest.get('addons') or {}).items():
            actual = self.get_local_version(addon_id)
            if not actual and addon_id in self.ON_DEMAND_SKINS:
                continue
            if (not actual or not mod.get('version') or
                    self._pending_addon_receipt(addon_id) or
                    self._version_tuple(actual) < self._version_tuple(mod['version'])):
                return False
        version = CONFIG.BUILDVERSION_DEFAULT
        for key in ('buildversion', 'latestversion'):
            if CONFIG.get_setting(key) != version:
                CONFIG.set_setting(key, version)
        CONFIG.BUILDVERSION = CONFIG.BUILDLATEST = version
        return True

    @staticmethod
    def _service_handoff_ready():
        """Retire the old repair service only after every active hook is sound."""
        try:
            from resources.libs.patch_engine import PatchEngine
            engine = PatchEngine()
            # run() already refuses a legacy-marked POV before writing any
            # patch. A separate legacy_pov_host_present() call normalized all
            # 80 Kodi settings a second time on x86 before the same decision.
            stats = engine.run()
            return (not any(stats.get(key) for key in (
                'legacy_host_deferred', 'anchor_missing', 'missing',
                'failed', 'malformed'))
                and sum(stats.get(key, 0) for key in (
                    'applied', 'upgraded', 'skipped_current', 'superseded')) > 0)
        except Exception as exc:
            logging.log('[ModularUpdater] Could not verify POV host: {0}'
                        .format(exc), level=xbmc.LOGWARNING)
            return False

    def _prepare_clean_pov_host(self, manifest):
        """Stage an official, hash-pinned POV while the old service remains live."""
        entry = manifest.get('pov_host_migration') or {}
        if not isinstance(entry, dict):
            return False
        version = str(entry.get('version') or '')
        sha256 = str(entry.get('sha256') or '').lower()
        if not version or len(sha256) != 64:
            return False
        try:
            from resources.libs.patch_engine import PatchEngine
            if not PatchEngine().legacy_pov_host_present():
                return False
            current = self.get_local_version('plugin.video.pov')
            if current and self._version_tuple(current) > self._version_tuple(version):
                logging.log('[ModularUpdater] Installed POV is newer than the '
                            'pinned clean host; refusing downgrade.',
                            level=xbmc.LOGWARNING)
                return False
            from resources.libs import pov_host_handoff
            host = os.path.join(CONFIG.ADDONS, 'plugin.video.pov')
            bridge = os.path.join(CONFIG.ADDONS, 'service.subtitles.kodipovilai',
                                  'resources', 'lib', 'modular_service_handoff.py')
            if not os.path.isfile(bridge):
                logging.log('[ModularUpdater] Legacy service has no migration '
                            'guard; keeping both existing addon trees.',
                            level=xbmc.LOGWARNING)
                return False
            plan = pov_host_handoff.read_plan(CONFIG.USERDATA, host)
            if (plan and plan['version'] == version and plan['sha256'] == sha256
                    and plan['stage'].is_dir() and
                    pov_host_handoff._digest_tree(plan['stage']) == plan['tree_digest']):
                return True
            ota = os.path.join(CONFIG.ADDON_DATA, CONFIG.ADDON_ID,
                               'ota-packages')
            os.makedirs(ota, exist_ok=True)
            package = os.path.join(ota, 'plugin.video.pov-clean.zip')
            self._download_background_zip(entry.get('zip'), package, entry)
            pov_host_handoff.prepare(
                package, host, CONFIG.USERDATA, version, sha256, bridge)
            tools.remove_file(package)
            xbmcgui.Dialog().notification(
                CONFIG.ADDONTITLE,
                'עדכון POV הוכן. יש לסגור את Kodi ולפתוח מחדש להשלמתו.',
                time=8000)
            logging.log('[ModularUpdater] Official clean POV staged; restart '
                        'required before activation.', level=xbmc.LOGINFO)
            return True
        except Exception as exc:
            logging.log('[ModularUpdater] Could not stage clean POV: {0}'
                        .format(exc), level=xbmc.LOGERROR)
            return False

    def _prepare_service_handoff(self, mod):
        """Stage MoranSubs while the currently running service remains intact."""
        from resources.libs import staged_addon_install
        addon_id = 'service.subtitles.kodipovilai'
        bridge = os.path.join(CONFIG.ADDONS, addon_id, 'resources', 'lib',
                              'modular_service_handoff.py')
        if not os.path.isfile(bridge):
            logging.log('[ModularUpdater] Legacy MoranSubs lacks the restart '
                        'handoff bridge; keeping its live service.',
                        level=xbmc.LOGWARNING)
            return False
        version = str(mod.get('version') or '')
        sha256 = str(mod.get('sha256') or '').lower()
        if not version or len(sha256) != 64:
            logging.log('[ModularUpdater] MoranSubs handoff lacks version/SHA',
                        level=xbmc.LOGERROR)
            return False
        try:
            already = staged_addon_install.prepared_matches(
                CONFIG.ADDONS, addon_id, version, sha256)
            if not already:
                ota_dir = os.path.join(CONFIG.ADDON_DATA, CONFIG.ADDON_ID,
                                       'ota-packages')
                os.makedirs(ota_dir, exist_ok=True)
                zip_path = os.path.join(ota_dir, addon_id + '_update.zip')
                self._download_background_zip(mod.get('zip'), zip_path, mod)
                staged_addon_install.install(
                    zip_path, CONFIG.ADDONS, addon_id, version, sha256,
                    defer_swap=True)
                tools.remove_file(zip_path)
            old_plan, _ack = staged_addon_install.read_handoff(CONFIG.USERDATA)
            staged_addon_install.request_handoff(CONFIG.USERDATA, version, sha256)
            notice = staged_addon_install.claim_restart_notice(
                CONFIG.ADDONS, addon_id, version, sha256)
            previous_notice = (old_plan and old_plan.get('version') == version and
                               old_plan.get('sha256') == sha256)
            if notice and not previous_notice:
                xbmcgui.Dialog().notification(
                    CONFIG.ADDONTITLE,
                    'עדכון התרגום מוכן. יש לסגור את Kodi ולפתוח מחדש להשלמתו.',
                    time=8000)
            logging.log('[ModularUpdater] MoranSubs prepared; current service '
                        'kept until next Kodi process.', level=xbmc.LOGINFO)
            return True
        except Exception as exc:
            logging.log('[ModularUpdater] MoranSubs staging failed: {0}'.format(exc),
                        level=xbmc.LOGERROR)
            return False

    def _complete_pending_service_handoff(self):
        """Swap only after the old service acknowledged a different boot."""
        from resources.libs import staged_addon_install
        plan, ack = staged_addon_install.read_handoff(CONFIG.USERDATA)
        if plan and not ack:
            monitor = xbmc.Monitor()
            for _attempt in range(40):
                if monitor.waitForAbort(0.25):
                    return False
                plan, ack = staged_addon_install.read_handoff(CONFIG.USERDATA)
                if not plan or ack:
                    break
        if not plan or not ack:
            return False
        addon_id = 'service.subtitles.kodipovilai'
        if xbmc.getCondVisibility('Player.HasMedia') or not self._service_handoff_ready():
            return False
        if not staged_addon_install.prepared_matches(
                CONFIG.ADDONS, addon_id, plan['version'], plan['sha256']):
            staged_addon_install.clear_handoff(CONFIG.USERDATA)
            logging.log('[ModularUpdater] Prepared MoranSubs package missing; '
                        'old service remains installed.', level=xbmc.LOGERROR)
            return False
        try:
            # The acknowledged service returned without starting listeners,
            # but Kodi still marks its addon enabled. Setting enabled=True
            # again is a no-op and does NOT start the replacement service.
            # Stop/disable it explicitly before swapping, then enable the new
            # package in this boot. Never do this to a live unacknowledged one.
            response = json.loads(xbmc.executeJSONRPC(json.dumps({
                'jsonrpc': '2.0', 'id': 1, 'method': 'Addons.SetAddonEnabled',
                'params': {'addonid': addon_id, 'enabled': False}})))
            if ('error' in response or response.get('result') not in ('OK', True)
                    or self._runtime_addon_enabled(addon_id)):
                raise RuntimeError('acknowledged subtitle service did not disable')
            count = staged_addon_install.activate_prepared(
                CONFIG.ADDONS, addon_id, plan['version'], plan['sha256'])
            from resources.libs import db
            db.addon_database([addon_id], 1, True)
            xbmc.executebuiltin('UpdateLocalAddons')
            staged_addon_install.clear_handoff(CONFIG.USERDATA)
            if not self._enable_addon(addon_id):
                xbmcgui.Dialog().notification(
                    CONFIG.ADDONTITLE,
                    'עדכון הכתוביות הותקן, אך השירות לא התחיל. יש לפתוח את Kodi מחדש.',
                    time=8000)
                raise RuntimeError('updated subtitle service could not enable')
            logging.log('[ModularUpdater] MoranSubs handoff complete: {0} files'
                        .format(count), level=xbmc.LOGINFO)
            xbmcgui.Dialog().notification(
                CONFIG.ADDONTITLE,
                'עדכון הכתוביות הושלם.', time=5000)
            return True
        except Exception as exc:
            staged_addon_install.clear_handoff(CONFIG.USERDATA)
            logging.log('[ModularUpdater] MoranSubs handoff failed; old service '
                        'will resume on restart: {0}'.format(exc),
                        level=xbmc.LOGERROR)
            return False

    def run_fresh_install(self):
        """Hydrate a clean device ENTIRELY from the manifest.

        Installs every addon listed in manifest.json and seeds the
        build-config pack in 'fresh' mode -- the modular replacement for the
        legacy monolithic build zip. The caller (startup) pins the build
        settings and performs the single force-close afterwards, so
        execute_updates must NOT restart/reload here (self.fresh guards it).
        """
        self.install_missing = True
        self.fresh = True
        return self.run_update_check()

    # ---- Provisioning state marker -------------------------------------------
    # A persistent file written to userdata ONLY when a fresh install has run all
    # the way to the end (every addon attempted + the config.zip applied).
    # startup.py uses it to tell a COMPLETED setup apart from one the user
    # force-closed mid-provisioning, so an interrupted setup is resumed instead
    # of being left half-built forever.
    @staticmethod
    def provision_marker_path():
        return os.path.join(CONFIG.USERDATA, 'kodipovil.provisioned')

    @classmethod
    def is_provisioned(cls):
        try:
            return os.path.exists(cls.provision_marker_path())
        except Exception:
            return False

    @classmethod
    def mark_provisioned(cls, version=''):
        try:
            with open(cls.provision_marker_path(), 'w') as fh:
                fh.write(str(version or ''))
            logging.log("[Provisioning] wrote .provisioned marker (v{0})".format(version),
                        level=xbmc.LOGINFO)
        except Exception as e:
            logging.log("[Provisioning] failed writing .provisioned marker: {0}".format(e),
                        level=xbmc.LOGERROR)

    @classmethod
    def clear_provisioned(cls):
        try:
            os.remove(cls.provision_marker_path())
        except Exception:
            pass

    def heal_missing_addons(self):
        """Strict OTA enforcement (beyond version bumps).

        Physically verify with System.HasAddon that every REQUIRED addon is
        actually installed, and silently (re)install any that are missing -- e.g.
        a content addon that timed out during a previous provisioning pass
        (YouTube), or a manifest addon that never landed. On-demand skins
        (type 'skin') are intentionally EXCLUDED: by design they are installed
        only via Switch Skin, never force-installed here.

        Reuses self._manifest if run_update_check already fetched it this run.
        """
        manifest = getattr(self, '_manifest', None)
        if not manifest:
            # run_update_check already attempted this URL on this boot. A
            # second identical request only adds another network timeout.
            if getattr(self, '_manifest_checked', False):
                return
            manifest = self._load_manifest()
            if not manifest:
                return
            self._manifest = manifest
        addons = manifest.get('addons', {})

        # 1. Manifest addons (our private addons + the third-party repos),
        #    excluding on-demand skins.
        #
        #    CRUCIAL: distinguish "absent from disk" (re-download) from "on disk
        #    but not enabled". System.HasAddon is false in BOTH cases, but an
        #    addon that is already extracted must NOT be re-downloaded -- doing so
        #    is exactly the fishenzon infinite loop (extract -> still disabled ->
        #    System.HasAddon false -> re-download -> ...). For on-disk-but-disabled
        #    we just (re)enable it via JSON-RPC; only genuinely absent addons are
        #    pulled through the modular pipeline.
        missing = []
        disabled_on_disk = []
        for addon_id, mod in addons.items():
            if mod.get('type') == 'skin':
                continue
            if xbmc.getCondVisibility('System.HasAddon({0})'.format(addon_id)):
                continue
            if self._on_disk(addon_id):
                disabled_on_disk.append(addon_id)
            else:
                missing.append(mod)
        if disabled_on_disk:
            logging.log("[OTA-Heal] On-disk but disabled -> enabling (NOT re-downloading): "
                        "{0}".format(disabled_on_disk), level=xbmc.LOGWARNING)
            for _aid in disabled_on_disk:
                self._enable_addon(_aid)
            try:
                xbmc.executebuiltin('UpdateLocalAddons')
            except Exception:
                pass
        if missing:
            logging.log("[OTA-Heal] Missing manifest addons -> installing: {0}".format(
                [m.get('id') for m in missing]), level=xbmc.LOGWARNING)
            try:
                self.execute_updates(missing)
            except Exception as e:
                logging.log("[OTA-Heal] manifest heal failed: {0}".format(e), level=xbmc.LOGERROR)

        # 2. Third-party CONTENT addons (provisioned via native InstallAddon).
        #    post_install_provisioning is idempotent -- present addons are
        #    skipped -- so this re-attempts ONLY what is genuinely missing.
        missing_provision = [a for a in youtube_platform.eligible(self.PROVISION_IDS)
                             if not xbmc.getCondVisibility('System.HasAddon({0})'.format(a))]
        if missing_provision:
            logging.log("[OTA-Heal] Missing content addons -> provisioning: {0}".format(
                missing_provision), level=xbmc.LOGWARNING)
            try:
                self.post_install_provisioning()
            except Exception as e:
                logging.log("[OTA-Heal] provisioning heal failed: {0}".format(e), level=xbmc.LOGERROR)

    # Hybrid provisioning: third-party content addons are NOT vendored in our
    # manifest. The manifest ships only our private addons + the third-party
    # repositories; the content addons themselves are installed here through
    # Kodi's native InstallAddon so that (a) Kodi resolves their dependencies
    # natively (script.module.*, context.otaku, inputstream.adaptive ...) and
    # (b) they keep receiving OTA updates straight from their own developers.
    # Order matters: install the lean, reliable core content addons FIRST so the
    # build is operational fast, and keep plugin.video.otaku DEAD LAST. Otaku
    # pulls a large dependency tree and is known to spike background syncs / stall
    # for up to ~60s on a fresh install; placing it last means a transient Otaku
    # timeout can never block the core addons (POV, IdanPlus, YouTube, language
    # pack) -- heal_missing_addons() simply (re)installs Otaku on the next launch.
    PROVISION_IDS = [
        'script.module.acctmgr',            # <- repository.709 (Account Manager)
        'plugin.video.pov',                 # <- repository.kodifitzwell (+ patched at runtime)
        'plugin.video.idanplus',            # <- repository.Fishenzon
        'plugin.video.youtube',             # <- Kodi official repo
        'resource.language.he_il',          # <- Kodi official repo (Hebrew language pack)
        'script.xbmc.unpausejumpback',      # <- Kodi official repo (unpause jumpback)
        'plugin.video.otaku',               # <- repository.otaku (+ context.otaku); LAST: heavy
                                            #    + timeout-prone, must not block core install.
    ]
    # These are installed through Kodi's repositories, not the manifest ZIPs.
    # A completed config pack must not certify a fresh build without them.
    # Otaku and unpause-jumpback are recoverable optional additions.
    CORE_PROVISION_IDS = (
        'script.module.acctmgr',
        'plugin.video.pov',
        'plugin.video.idanplus',
        'plugin.video.youtube',
        'resource.language.he_il',
    )

    def post_install_provisioning(self, per_addon_timeout=60, ids=None):
        """Installation Orchestrator (Phase 1 & Phase 2 Integration).

            This orchestrator manages the seamless transition between the Manifest installation (Phase 1)
            and the 3rd-party Headless installation (Phase 2), ensuring a single, continuous user experience.

            Workflow:
              1. Launches the custom `install_manager` GUI with the Manifest queue.
              2. Upon Phase 1 completion, keeps the GUI alive and triggers `UpdateLocalAddons` to load
                 the newly installed repository XMLs into Kodi's database.
              3. Triggers the Headless Installer to resolve 3rd-party dependencies, placing the GUI in a
                 visual "Calculating dependencies / מנתח מאגרים..." pause state.
              4. Injects the resolved Phase 2 queue dynamically into the active GUI window (resolving friendly
                 names and real addon types like `script.module`).
              5. Once the GUI successfully completes all tasks and closes, handles any unresolvable
                 binary dependencies (Native Fallback) using Kodi's non-intrusive `DialogProgressBG`,
                 coordinated with a micro-watchdog.

            Args:
                per_addon_timeout (int): Timeout per addon during native installation fallback.
                ids (list, optional): List of addon IDs to provision. Defaults to PROVISION_IDS.

            Note:
                Idempotent: Addons already present at the target version are skipped, making this safe
                to call both right after a fresh install AND as a startup self-heal.
            """
        import xbmc
        provision_ids = list(ids) if ids is not None else list(self.PROVISION_IDS)
        provision_ids = youtube_platform.eligible(provision_ids)

        logging.log("[Provisioning] HEADLESS provisioning of {0} addons".format(
            len(provision_ids)), level=xbmc.LOGINFO)

        # The repositories were just extracted to disk. Force Kodi to load them so
        # their addon.xml (datadir) is visible to the headless resolver.
        try:
            xbmc.executebuiltin('UpdateLocalAddons')
            if xbmc.Monitor().waitForAbort(2):
                return False
        except Exception:
            pass

        installed, missing = [], list(provision_ids)
        try:
            from resources.libs.headless_installer import HeadlessInstaller
            installed, missing = HeadlessInstaller().install(provision_ids)
            logging.log("[Provisioning] headless installed={0} missing={1}".format(
                installed, missing), level=xbmc.LOGINFO)
        except Exception as e:
            logging.log("[Provisioning] headless installer error: {0}".format(e),
                        level=xbmc.LOGERROR)
            missing = [a for a in provision_ids
                       if not xbmc.getCondVisibility('System.HasAddon({0})'.format(a))]

        # Native fallback ONLY for what headless could not provision.
        if missing and not xbmc.Monitor().abortRequested():
            logging.log("[Provisioning] native fallback for: {0}".format(missing),
                        level=xbmc.LOGWARNING)
            self._native_install_fallback(missing, per_addon_timeout)

        logging.log("[Provisioning] Provisioning finished", level=xbmc.LOGINFO)

        all_present = all(
            xbmc.getCondVisibility('System.HasAddon({0})'.format(a)) for a in provision_ids
        )
        return all_present

    @staticmethod
    def _confirm_native_install():
        """Only Kodi's InstallModal download question, in its actual dialog.

        Kodi 21 uses heading 24076 and body lines 24100/24101. A skin-change,
        security or unrelated Yes/No question must remain under user control.
        """
        if xbmcgui.getCurrentWindowDialogId() != 10100:
            return False
        try:
            if xbmc.getInfoLabel('Control.GetLabel(1)') != xbmc.getLocalizedString(24076):
                return False
            # Read through Kodi's GUI-info API; never wrap a control that the
            # GUI thread may still be constructing or unloading.
            body = xbmc.getInfoLabel('Control.GetLabel(9)')
            phrases = [xbmc.getLocalizedString(key) for key in (24100, 24101)]
            if not all(phrase and phrase in body for phrase in phrases):
                return False
            xbmc.executebuiltin('SendClick(10100,11)')
            return True
        except Exception:
            return False

    def _native_install_fallback(self, ids, per_addon_timeout=60):
        """Last-resort native install for addons the headless resolver could not
        place (e.g. a dependency only in a repo we don't ship). Uses Kodi's own
        InstallAddon so Kodi pulls the remaining deps, with a MINIMAL confirmer
        thread that auto-accepts ONLY the dependency Yes/No dialog (window 10100,
        control 11 = Yes -- fixed by Kodi core regardless of skin). Unlike the old
        watchdog it NEVER closes any other dialog, so it can't eat the user's
        menus or an in-flight download.
        """
        import threading
        import time
        import xbmc
        import xbmcgui
        monitor = xbmc.Monitor()
        ids = youtube_platform.eligible(ids)
        if not ids:
            return

        # Make sure repo indexes are fresh so InstallAddon can find the addons.
        try:
            xbmc.executebuiltin('UpdateAddonRepos', True)
        except Exception:
            pass
        if monitor.waitForAbort(2):
            return

        stop = threading.Event()

        def _confirmer():
            while not stop.is_set():
                try:
                    if self._confirm_native_install():
                        if monitor.waitForAbort(0.8):
                            return
                        continue
                except Exception:
                    pass
                if monitor.waitForAbort(0.3):
                    return

        watcher = threading.Thread(target=_confirmer)
        watcher.daemon = True
        watcher.start()
        try:
            for addon_id in ids:
                if monitor.abortRequested():
                    break
                if xbmc.getCondVisibility('System.HasAddon({0})'.format(addon_id)):
                    continue
                logging.log("[Provisioning] native install {0}".format(addon_id),
                            level=xbmc.LOGINFO)
                xbmc.executebuiltin('InstallAddon({0})'.format(addon_id))
                deadline = time.time() + int(per_addon_timeout)
                landed = False
                while time.time() < deadline:
                    if monitor.waitForAbort(1):
                        break
                    if xbmc.getCondVisibility('System.HasAddon({0})'.format(addon_id)):
                        landed = True
                        break
                if not landed:
                    logging.log("[Provisioning] native install did not confirm {0} "
                                "within {1}s (will self-heal next launch)".format(
                                    addon_id, per_addon_timeout), level=xbmc.LOGWARNING)
        finally:
            stop.set()
            watcher.join(5)

    def _config_pending(self, manifest):
        """True when the manifest's config version is ahead of what we last
        applied on this device."""
        cfg = (manifest or {}).get('config') or {}
        remote = cfg.get('config_version')
        if not remote:
            return False
        return CONFIG.get_setting('config_applied_version') != remote

    def _install_verified_module(self, zip_path, mod, sha256):
        """Fresh and OTA use the same complete extraction and atomic swap.

        Never replace a running subtitle service. Missing or proven-disabled
        services can be installed immediately; live ones use the handoff gate.
        A previous failed in-place extraction receipt is cleared only after
        the staged package has been fully verified and activated.
        """
        from resources.libs import staged_addon_install, addon_install_receipt
        addon_id = mod['id']
        if not sha256:
            raise ValueError('add-on installation requires SHA-256')
        if (addon_id == 'service.subtitles.kodipovilai' and self._on_disk(addon_id)
                and self._runtime_addon_enabled(addon_id)):
            raise RuntimeError('refusing live MoranSubs directory swap')
        data_dir = os.path.join(CONFIG.ADDON_DATA, CONFIG.ADDON_ID)
        addon_install_receipt.begin(data_dir, addon_id, mod.get('version'), sha256)
        count = staged_addon_install.install(
            zip_path, CONFIG.ADDONS, addon_id, str(mod.get('version')), sha256)
        addon_install_receipt.complete(data_dir, addon_id)
        return count

    def _fresh_install_complete(self, manifest):
        """Certify the installed files, not the installer dialog's completion.

        The dialog may finish after individual download/extract failures. A
        .provisioned marker in that state would prevent a later retry.
        """
        missing = []
        for addon_id, mod in (manifest.get('addons') or {}).items():
            expected = mod.get('version')
            actual = self.get_local_version(addon_id)
            if self._pending_addon_receipt(addon_id):
                missing.append('{0} (extraction not verified)'.format(addon_id))
            if (not expected or not actual or
                    self._version_tuple(actual) < self._version_tuple(expected)):
                missing.append('{0} ({1}, expected {2})'.format(
                    addon_id, actual or 'missing', expected or 'unspecified'))
        for addon_id in youtube_platform.eligible(self.CORE_PROVISION_IDS) + ['skin.povil.nox', 'script.fentastic.helper']:
            try:
                enabled = xbmc.getCondVisibility(
                    'System.HasAddon({0})'.format(addon_id))
            except Exception:
                enabled = False
            if not enabled:
                missing.append('{0} (native core addon unavailable)'.format(addon_id))
        config_version = (manifest.get('config') or {}).get('config_version')
        actual_config = CONFIG.get_setting('config_applied_version')
        if not config_version or actual_config != config_version:
            missing.append('config ({0}, expected {1})'.format(
                actual_config or 'missing', config_version or 'unspecified'))
        previous = getattr(self, 'last_install_issues', None)
        self.last_install_issues = missing
        if missing:
            if previous != missing:
                logging.log('[Provisioning] incomplete; retry required: {0}'
                            .format(', '.join(missing)), level=xbmc.LOGERROR)
            return False
        return True

    def _resolve_phase_two_bounded(self, timeout=15):
        """Keep a slow repository from holding the installation dialog forever.

        Repository resolution only reads indexes and prepares jobs. If it
        exceeds the deadline, its daemon worker cannot inject late jobs; the
        caller falls back to Kodi's native installer and the fresh completion
        gate still verifies the resulting addon state.
        """
        import threading

        result = {}

        def work():
            try:
                from resources.libs.headless_installer import HeadlessInstaller
                result['jobs'] = HeadlessInstaller().resolve_and_prepare(
                    tuple(youtube_platform.eligible(self.PROVISION_IDS)))
            except Exception as error:
                result['error'] = error

        worker = threading.Thread(target=work, name='KodiPOVILRepoResolver')
        worker.daemon = True
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            raise TimeoutError('repository lookup exceeded {0}s'.format(timeout))
        if 'error' in result:
            raise result['error']
        return result['jobs']

    @staticmethod
    def _download_background_zip(url, dest, entry):
        """Fetch an OTA ZIP without importing the old foreground downloader.

        The old downloader imports Requests before making a request. On some
        Kodi x86 starts that import can stall the entire background update.
        Keep partial downloads invisible to the installer and bound both the
        response size and network waits.
        """
        import urllib.request

        if not isinstance(url, str) or not (
                url.startswith('https://') or url.startswith('http://127.0.0.1:')):
            raise ValueError('unsupported OTA ZIP URL')
        expected_size = int(entry.get('size') or 0)
        limit = 256 * 1024 * 1024
        if expected_size < 0 or expected_size > limit:
            raise ValueError('invalid OTA ZIP size')
        part = dest + '.part'
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            request = urllib.request.Request(
                url, headers={'User-Agent': getattr(CONFIG, 'USER_AGENT', 'Kodi POV IL')})
            count = 0
            with opener.open(request, timeout=20) as response, open(part, 'wb') as target:
                if getattr(response, 'status', 200) != 200:
                    raise IOError('OTA ZIP HTTP status {}'.format(response.status))
                while True:
                    if xbmc.Monitor().abortRequested():
                        raise IOError('Kodi is shutting down')
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > limit or (expected_size and count > expected_size):
                        raise IOError('OTA ZIP exceeds manifest size')
                    target.write(chunk)
            if not count or (expected_size and count != expected_size):
                raise IOError('OTA ZIP size mismatch')
            os.replace(part, dest)
        finally:
            try:
                os.remove(part)
            except OSError:
                pass

    def execute_updates(self, queue):
        """Download, extract, and register the queued modules."""
        # Also protect callers that bypass run_update_check (including the
        # missing-addon healer and manual provisioning on an existing build).
        if (not getattr(self, 'fresh', False)
                and any(mod.get('id') == 'service.subtitles.kodipovilai'
                        for mod in queue)
                and (not self.background or
                     self._runtime_addon_enabled('service.subtitles.kodipovilai') or
                     not self._service_handoff_ready())):
            queue = [mod for mod in queue
                     if mod.get('id') != 'service.subtitles.kodipovilai']
            logging.log('[ModularUpdater] Refusing direct MoranSubs replacement '
                        'before clean POV handoff.', level=xbmc.LOGWARNING)
        logging.log('[ModularUpdater] ensuring package directory', level=xbmc.LOGINFO)
        tools.ensure_folders(CONFIG.PACKAGES)
        logging.log('[ModularUpdater] package directory ready', level=xbmc.LOGINFO)

        requires_restart = False
        extracted_addons = []
        failed_addons = []
        self._missing_native = []

        fresh = getattr(self, 'fresh', False)
        early_config_touched = [None]

        def _apply_config_pack():
            try:
                logging.log('[ModularUpdater] importing config_apply', level=xbmc.LOGINFO)
                from resources.libs import config_apply
                logging.log('[ModularUpdater] config_apply ready', level=xbmc.LOGINFO)
                manifest = getattr(self, '_manifest', None)
                if manifest:
                    res = config_apply.apply_config_pack(manifest, fresh=fresh, background=self.background)
                    return bool(res.get('skin_touched'))
            except Exception as e:
                logging.log("[ModularUpdater] config apply failed: {0}".format(e), level=xbmc.LOGERROR)
            return False

        class _OrchestratorProxy:
            def __init__(self, target_queue): self.target_queue = target_queue
            def append_to_queue(self, jobs):
                for j in jobs:
                    if not any(x.get('id') == j.get('id') for x in self.target_queue):
                        self.target_queue.append(j)
            def wait_for_queue_empty(self): pass
            def pause_for_resolution(self): pass
            def remove_resolution_pause(self): pass
            def mark_all_jobs_added(self): pass
            def get_installed(self): return []

        def _orchestrator(dialog):
            if queue:
                dialog.append_to_queue(queue)
                dialog.wait_for_queue_empty()

            if fresh:
                # Seed managed settings before UpdateLocalAddons can start
                # freshly extracted services with their upstream defaults.
                early_config_touched[0] = _apply_config_pack()
                # Bridge Phase 1 -> Phase 2 DB Registration so Phase 2 logic can "see" the extracted Phase 1 modules
                extracted_so_far = dialog.get_installed()
                if extracted_so_far:
                    try:
                        from resources.libs import db
                        logging.log("[ModularUpdater] Phase 1 queue complete. Synchronizing DB & VFS...", level=xbmc.LOGINFO)
                        db.addon_database(extracted_so_far, 1, True)
                        xbmc.executebuiltin('UpdateLocalAddons')

                        # CRITICAL FIX: Give Kodi 2.5 seconds to unlock the SQLite DB
                        # and process the VFS event queue so new Python modules (like certifi) load.
                        xbmc.Monitor().waitForAbort(2.5)

                        for _aid in extracted_so_far:
                            self._enable_addon(_aid)
                    except Exception as e:
                        logging.log("[ModularUpdater] Phase 1 DB sync error: {0}".format(e), level=xbmc.LOGERROR)

                dialog.pause_for_resolution()

                try:
                    logging.log("[ModularUpdater] Triggering Phase 2 Headless Resolution...", level=xbmc.LOGINFO)
                    phase2_jobs, missing_native = self._resolve_phase_two_bounded()

                    dialog.remove_resolution_pause()
                    if phase2_jobs:
                        logging.log("[ModularUpdater] Injecting {0} Phase 2 jobs to UI.".format(len(phase2_jobs)), level=xbmc.LOGINFO)
                        dialog.append_to_queue(phase2_jobs)
                    self._missing_native = missing_native
                except Exception as e:
                    logging.log("[ModularUpdater] Phase 2 resolution fatal error: {0}".format(e), level=xbmc.LOGERROR)
                    # A resolver error must not silently suppress native
                    # provisioning. The installed-state gate below will still
                    # refuse to certify an incomplete fresh install.
                    self._missing_native = [aid for aid in self.PROVISION_IDS
                                            if not xbmc.getCondVisibility(
                                                'System.HasAddon({0})'.format(aid))]
                    dialog.remove_resolution_pause()

            dialog.mark_all_jobs_added()

        if queue or fresh:
            if not self.background:
                try:
                    from resources.libs.gui.install_manager import run_install_manager
                    extracted_addons = run_install_manager(orchestrator_func=_orchestrator)
                    for _aid in extracted_addons:
                        if _aid == 'plugin.program.kodipovilwizard':
                            requires_restart = True
                    queue = []  # Consumed dynamically via UI thread.
                except Exception as _ui_err:
                    logging.log("[ModularUpdater] install-manager UI failed ({0}); "
                                "falling back to classic installer".format(_ui_err), level=xbmc.LOGWARNING)
                    proxy = _OrchestratorProxy(queue)
                    _orchestrator(proxy)

        # Fallback Classic GUI loop if UI failed (UI execution skips this because queue = [])
        if queue:
            logging.log('[ModularUpdater] classic installer: importing modules',
                        level=xbmc.LOGINFO)
            if not self.background:
                from resources.libs.downloader import Downloader
            from resources.libs import config_apply
            logging.log('[ModularUpdater] classic installer: modules ready',
                        level=xbmc.LOGINFO)
            if self.background:
                self.progress.create(CONFIG.ADDONTITLE, "מבצע עדכון רקע מודולרי...")
            else:
                self.progress.create(CONFIG.ADDONTITLE, "מבצע עדכון מודולרי...")
            logging.log('[ModularUpdater] classic installer: progress ready',
                        level=xbmc.LOGINFO)

            for i, mod in enumerate(queue, start=1):
                addon_id = mod.get('id')
                name = mod.get('name', addon_id)
                url = mod.get('zip')

                if addon_id == 'plugin.program.kodipovilwizard': requires_restart = True

                msg = "מוריד: {0}".format(tools.clean_text(name))
                percent = int((i - 1) / float(len(queue)) * 100)

                if self.background: self.progress.update(percent, message=msg)
                else: self.progress.update(percent, "[B]{0}[/B]".format(msg))

                if self.background:
                    # Keep active downloads outside the add-on tree while Kodi
                    # refreshes its database; this also isolates partial ZIPs.
                    ota_dir = os.path.join(CONFIG.ADDON_DATA, CONFIG.ADDON_ID,
                                           'ota-packages')
                    os.makedirs(ota_dir, exist_ok=True)
                else:
                    ota_dir = CONFIG.PACKAGES
                zip_path = os.path.join(ota_dir, "{0}_update.zip".format(addon_id))
                tools.remove_file(zip_path)

                try:
                    logging.log('[ModularUpdater] downloading {0}'.format(addon_id),
                                level=xbmc.LOGINFO)
                    if self.background:
                        self._download_background_zip(url, zip_path, mod)
                    else:
                        Downloader(progress_dialog_bg=False).download(url, zip_path)
                except Exception as e:
                    logging.log('[ModularUpdater] download failed for {0}: {1}'
                                .format(addon_id, e), level=xbmc.LOGERROR)
                    failed_addons.append(addon_id)
                    continue

                if not os.path.exists(zip_path) or os.path.getsize(zip_path) == 0:
                    failed_addons.append(addon_id)
                    continue

                want_sha = mod.get('sha256')
                if want_sha:
                    try: got_sha = config_apply.sha256_file(zip_path)
                    except Exception: got_sha = None
                    if not got_sha or got_sha.lower() != str(want_sha).lower():
                        tools.remove_file(zip_path)
                        failed_addons.append(addon_id)
                        continue

                try:
                    logging.log('[ModularUpdater] extracting {0}'.format(addon_id),
                                level=xbmc.LOGINFO)
                    count = self._install_verified_module(zip_path, mod, want_sha)
                    logging.log('[ModularUpdater] verified and swapped {0} files for {1}'
                                .format(count, addon_id), level=xbmc.LOGINFO)
                    extracted_addons.append(addon_id)
                    logging.log('[ModularUpdater] extracted {0}'.format(addon_id),
                                level=xbmc.LOGINFO)
                except Exception as e:
                    logging.log('[ModularUpdater] extraction failed for {0}: {1}'
                                .format(addon_id, e), level=xbmc.LOGERROR)
                    failed_addons.append(addon_id)
                tools.remove_file(zip_path)

            try: self.progress.close()
            except: pass

        # 4. Database Registration for all extracted addons
        if extracted_addons:
            from resources.libs import db
            logging.log("[ModularUpdater] Registering to Addons DB: {0}".format(extracted_addons), level=xbmc.LOGINFO)
            db.addon_database(extracted_addons, 1, True)
            xbmc.executebuiltin('UpdateLocalAddons')
            # The refresh is asynchronous. A fixed sleep here can hold the
            # startup interpreter for tens of seconds while a widget-heavy
            # skin rescans add-ons. The fresh-install gate below verifies the
            # actual addon state; an unfinished scan retries on next launch.
            for _aid in extracted_addons:
                self._enable_addon(_aid)

        # A resolved job can still fail during download/extraction. Such core
        # addons were previously omitted from native fallback because only
        # resolution failures populated this list.
        if fresh:
            for addon_id in youtube_platform.eligible(self.CORE_PROVISION_IDS):
                if (addon_id not in extracted_addons and
                        addon_id not in self._missing_native and
                        not xbmc.getCondVisibility('System.HasAddon({0})'.format(addon_id))):
                    self._missing_native.append(addon_id)

        # 4a. Native Binary/Fallback handling outside of custom window loops
        if getattr(self, '_missing_native', None) and not xbmc.Monitor().abortRequested():
            try:
                bg = xbmcgui.DialogProgressBG()
                bg.create(CONFIG.ADDONTITLE, "משלים התקנות מערכת (Native)...")
                self._native_install_fallback(self._missing_native, per_addon_timeout=60)
                bg.close()
            except Exception as e:
                logging.log("[ModularUpdater] Native fallback failed: {0}".format(e), level=xbmc.LOGERROR)

        # 4b/4c. Build-config pack Phase
        config_skin_touched = bool(early_config_touched[0])
        # A false early result can mean failure, not successful unchanged
        # settings. Retry after dependencies have been registered/enabled.
        if (early_config_touched[0] is None or
                self._config_pending(getattr(self, '_manifest', None))):
            config_skin_touched = _apply_config_pack() or config_skin_touched
        try:
            from resources.libs import fentastic_widgets
            # Preserve saved rows before the updater's own skin reload.
            config_skin_touched = bool(fentastic_widgets.repair(reload_skin=False)) or config_skin_touched
        except Exception as exc:
            logging.log('[FENtastic widgets] update repair deferred: {}'.format(exc),
                        level=xbmc.LOGWARNING)

        if fresh:
            manifest = getattr(self, '_manifest', None) or {}
            monitor = xbmc.Monitor()
            if failed_addons:
                return False
            if self._config_pending(manifest):
                # Waiting for addon scans cannot complete a failed config.
                # Return to bounded provisioning recovery immediately.
                self._fresh_install_complete(manifest)
                return False
            # UpdateLocalAddons and enabling dependencies are asynchronous.
            # Wait for their actual state in this launch rather than leaving a
            # complete download waiting for another manual restart.
            for _ in range(20):
                if self._fresh_install_complete(manifest):
                    break
                for addon_id in youtube_platform.eligible(self.CORE_PROVISION_IDS) + ['skin.povil.nox', 'script.fentastic.helper']:
                    if not xbmc.getCondVisibility('System.HasAddon({0})'.format(addon_id)):
                        self._enable_addon(addon_id)
                if monitor.waitForAbort(1):
                    return False
            else:
                return False
            if monitor.abortRequested():
                return False
            cfg = manifest.get('config') or {}
            self.mark_provisioned(cfg.get('config_version'))
            return self.is_provisioned()

        if requires_restart:
            if not self.background:
                choice = self.dialog.yesno(
                    CONFIG.ADDONTITLE,
                    "עדכון קריטי בוצע בהצלחה.\nיש להפעיל מחדש את קודי כדי להחיל את השינויים.",
                    yeslabel="יציאה",
                    nolabel="מאוחר יותר"
                )
                if choice:
                    from resources.libs.wizard import Wizard
                    Wizard().force_close_kodi_in_5_seconds("עדכון קריטי הסתיים.")
        elif extracted_addons or config_skin_touched:
            xbmc.executebuiltin('ReloadSkin()')
            if not self.background:
                self.dialog.ok(CONFIG.ADDONTITLE, "העדכון המודולרי הסתיים בהצלחה!")

        return not failed_addons
