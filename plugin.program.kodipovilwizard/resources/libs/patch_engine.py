# -*- coding: utf-8 -*-
################################################################################
#  KODI-POV-IL - Engine v2 Runtime Patching Architecture
#
#  A metadata-driven source patcher. Every entry in
#  resources.libs.patches.patches_config.PATCH_CONFIG describes a single
#  surgical edit to apply to an installed addon's source file: WHERE to make
#  it (addon_id + target_file + anchor), WHAT to inject (hook), and HOW to
#  version/roll it forward (id + marker).
#
#  This lets us ship, upgrade, and roll back in-place code patches to
#  third-party/downstream addons (plugin.video.pov and friends) purely by
#  publishing an updated patches_config.py -- no wizard redeploy, no addon
#  redeploy, no user action.
#
#  DESIGN GOALS (all enforced below):
#    1. NEVER raise. A malformed patch entry, a missing addon, a missing
#       file, a missing anchor, or a corrupt existing patch block must only
#       ever be logged and skipped -- boot must always continue.
#    2. Idempotent. Running this 50 times in a row on an already-patched
#       device is a silent, instant no-op.
#    3. Self-healing / upgradeable. Bumping a patch's `marker` (e.g. _v1 ->
#       _v2) automatically scrubs the stale block and re-injects the new one
#       on the next run, with the file's `id` tag staying constant across
#       every version so the block is always findable.
#    4. Active Scrubbing. Disabling a patch (either in config or via Kodi UI
#       settings) actively removes the injected code on the next run.
#    5. Cheap on flash. Each physical target file is read once and written
#       once per run, no matter how many patches target it.
################################################################################

import os
import re
import textwrap

import xbmc
import xbmcaddon
import xbmcvfs

from resources.libs.common import logging

# Addons that predate the "addon_id" field in patches_config.py were all
# written against the main build addon -- default to it for backward compat.
DEFAULT_ADDON_ID = 'plugin.video.pov'

# The id (NOT the marker) is the stable handle for a patch across every
# version of it that will ever ship. The marker is what actually changes
# between versions and is what tells us whether an already-applied block is
# current or stale.
BEGIN_TAG = '# --- BEGIN PATCH ID: {id} ---'
END_TAG = '# --- END PATCH ID: {id} ---'

# Fields every patch entry must supply (addon_id/description are optional --
# see _normalize_entry).
_REQUIRED_FIELDS = ('id', 'name', 'target_file', 'marker', 'anchor', 'action', 'hook')
_VALID_ACTIONS = ('prepend_before', 'append_after')


class PatchEngine(object):
    """Applies every patch in PATCH_CONFIG to its target addon file.

    Usage:
        from resources.libs.patch_engine import PatchEngine
        PatchEngine().run()

    `run()` is fully fault-tolerant: it will never raise, regardless of what
    is (or isn't) on disk, or how malformed a config entry is.
    """

    def __init__(self, config=None):
        """`config` is normally omitted -- it's exposed mainly so unit tests
        can hand in a synthetic PATCH_CONFIG list without touching disk."""
        self._raw_config = config if config is not None else self._load_default_config()
        self._stats = {
            'applied': 0,        # fresh block injected for the first time
            'upgraded': 0,       # stale block (older marker) replaced
            'skipped_current': 0,  # already up to date, nothing to do
            'anchor_missing': 0,  # target file present, but anchor not found
            'missing': 0,         # addon or target file not present on disk
            'failed': 0,           # unexpected per-patch error
            'malformed': 0,        # patch entry itself failed schema validation
            'removed': 0,          # disabled patch actively scrubbed from disk
            'skipped_disabled': 0, # disabled patch already not present
        }

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def run(self):
        """Apply every configured patch. Returns the internal stats dict.
        Guaranteed not to raise."""
        try:
            patches = self._normalize_patches(self._raw_config)
            if not patches:
                logging.log('[PatchEngine] No valid patches configured; nothing to do.',
                            level=xbmc.LOGDEBUG)
                return self._stats

            # The previous public build edited POV files in place using
            # AI_SUBS_/KODI_POV_IL markers. The new anchors target an upstream
            # clean tree; applying only the anchors that still happen to match
            # would leave a mixed and potentially broken host. Preserve that
            # installed tree until a separate verified clean-host migration
            # can stage, validate and atomically replace it.
            if self._has_legacy_pov_edits(patches):
                self._stats['legacy_host_deferred'] = 1
                logging.log('[PatchEngine] Legacy POV edits detected; deferring '
                            'new patches until clean-host migration.',
                            level=xbmc.LOGWARNING)
                return self._stats

            grouped = self._group_patches(patches)

            for (addon_id, target_file), patch_list in grouped.items():
                try:
                    self._process_target(addon_id, target_file, patch_list)
                except Exception as err:
                    self._stats['failed'] += len(patch_list)
                    logging.log(
                        "[PatchEngine] Unhandled error processing {0}/{1}: {2}".format(
                            addon_id, target_file, err),
                        level=xbmc.LOGERROR)

        except Exception as err:
            # Belt-and-suspenders: absolutely nothing in here is allowed to
            # bubble up into the caller's boot/update flow.
            logging.log('[PatchEngine] Fatal error during run(): {0}'.format(err),
                        level=xbmc.LOGERROR)
            return self._stats

        applied = self._stats['applied']
        upgraded = self._stats['upgraded']
        removed = self._stats['removed']
        failed = self._stats['failed']
        level = xbmc.LOGWARNING if failed else (xbmc.LOGINFO if (applied or upgraded or removed) else xbmc.LOGDEBUG)
        logging.log('[PatchEngine] Run complete: {0}'.format(self._stats), level=level)
        return self._stats

    @classmethod
    def _has_legacy_pov_edits(cls, patches):
        """Fail closed before any write when the old public patcher is present."""
        targets = {p['target_file'] for p in patches
                   if p['addon_id'] == DEFAULT_ADDON_ID and p.get('enabled', True)}
        for target in targets:
            _, path = cls._resolve_paths(DEFAULT_ADDON_ID, target)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, 'rb') as source:
                    content = source.read()
            except OSError:
                # _process_target will report unreadable files as failures.
                continue
            if b'AI_SUBS_' in content or b'KODI_POV_IL' in content:
                return True
        return False

    def legacy_pov_host_present(self):
        """True when replacing the old repair service would strand POV edits."""
        patches = self._normalize_patches(self._raw_config)
        return self._has_legacy_pov_edits(patches)

    # ------------------------------------------------------------------
    # Schema parsing / normalization
    # ------------------------------------------------------------------
    @staticmethod
    def _load_default_config():
        """Lazily imports patches_config so a syntax error / missing module
        in that file can never prevent patch_engine.py itself from being
        imported (and thus never breaks the caller's own try/except-wrapped
        import of PatchEngine).

        PATH VERIFICATION (repo convention audit): every first-party import
        in this codebase -- startup.py, wizard.py, modular_updater.py, etc.
        -- resolves through the plural package `resources.libs` (there is
        no `resources.lib`, singular, anywhere in this addon's own Python
        package tree). This import below is therefore correct as written.
        The *hook strings* inside patches_config.py, however, previously
        pointed their runtime sys.path.append() at the singular
        'special://.../resources/lib/patches/' -- a directory that does not
        exist -- which would have raised ImportError inside the *target*
        addon (plugin.video.pov) the instant an injected hook actually ran,
        rather than inside PatchEngine's own try/except. That has been
        corrected to 'resources/libs/patches/' in patches_config.py so it
        matches this same package and actually resolves."""
        try:
            from resources.libs.patches import patches_config
            return list(getattr(patches_config, 'PATCH_CONFIG', None) or [])
        except Exception as err:
            logging.log('[PatchEngine] Could not import patches_config: {0}'.format(err),
                        level=xbmc.LOGERROR)
            return []

    def _normalize_patches(self, raw_list):
        normalized = []
        for idx, entry in enumerate(raw_list or []):
            patch = self._normalize_entry(entry, idx)
            if patch is not None:
                normalized.append(patch)
        return normalized

    def _normalize_entry(self, entry, idx):
        try:
            if not isinstance(entry, dict):
                logging.log('[PatchEngine] Patch entry #{0} is not a dict; skipped.'.format(idx),
                            level=xbmc.LOGWARNING)
                self._stats['malformed'] += 1
                return None

            missing = [f for f in _REQUIRED_FIELDS if not entry.get(f)]
            if missing:
                logging.log(
                    "[PatchEngine] Patch entry #{0} ('{1}') missing required field(s) {2}; skipped.".format(
                        idx, entry.get('id', '?'), missing),
                    level=xbmc.LOGWARNING)
                self._stats['malformed'] += 1
                return None

            action = entry['action']
            if action not in _VALID_ACTIONS:
                logging.log(
                    "[PatchEngine] Patch '{0}' has unknown action '{1}' (expected one of {2}); skipped.".format(
                        entry['id'], action, _VALID_ACTIONS),
                    level=xbmc.LOGWARNING)
                self._stats['malformed'] += 1
                return None

            # User Kodi setting overrides the JSON/config 'enabled' property.
            patch_id = entry['id']
            try:
                override = xbmcaddon.Addon().getSetting('patch_enabled_' + patch_id)
                if override == 'true':
                    is_enabled = True
                elif override == 'false':
                    is_enabled = False
                else:
                    is_enabled = entry.get('enabled', True)
            except Exception:
                is_enabled = entry.get('enabled', True)

            return {
                'id': patch_id,
                'name': entry.get('name', patch_id),
                'description': entry.get('description', ''),
                # Backward compat: pre-addon_id entries all targeted the main build addon.
                'addon_id': entry.get('addon_id') or DEFAULT_ADDON_ID,
                'target_file': entry['target_file'],
                'marker': entry['marker'],
                'anchor': entry['anchor'],
                'action': action,
                'hook': entry['hook'],
                'enabled': is_enabled,
                'alternatives': entry.get('alternatives', []),
            }
        except Exception as err:
            logging.log('[PatchEngine] Error normalizing patch entry #{0}: {1}'.format(idx, err),
                        level=xbmc.LOGWARNING)
            self._stats['malformed'] += 1
            return None

    @staticmethod
    def _group_patches(patches):
        """Groups by (addon_id, target_file) so each physical file is opened
        and saved exactly once, however many patches target it."""
        groups = {}
        for patch in patches:
            key = (patch['addon_id'], patch['target_file'])
            groups.setdefault(key, []).append(patch)
        return groups

    # ------------------------------------------------------------------
    # Per-file processing
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_paths(addon_id, target_file):
        addon_dir = xbmcvfs.translatePath('special://home/addons/{0}/'.format(addon_id))
        target_path = xbmcvfs.translatePath(
            'special://home/addons/{0}/{1}'.format(addon_id, target_file))
        return addon_dir, target_path

    def _process_target(self, addon_id, target_file, patch_list):
        addon_dir, target_path = self._resolve_paths(addon_id, target_file)

        # SAFETY FIRST: verify the addon is actually installed before ever
        # touching the filesystem for it. A patch targeting an addon that
        # isn't present (not yet installed, optional addon the user never
        # added, etc.) is a completely normal, expected situation -- warn
        # once and move on, never raise.
        if not os.path.isdir(addon_dir):
            logging.log(
                "[PatchEngine] Addon '{0}' not found on disk; skipping {1} patch(es) for {2}.".format(
                    addon_id, len(patch_list), target_file),
                level=xbmc.LOGWARNING)
            self._stats['missing'] += len(patch_list)
            return

        if not os.path.isfile(target_path):
            logging.log(
                "[PatchEngine] Target file not found: {0} (addon={1}); skipping {2} patch(es).".format(
                    target_file, addon_id, len(patch_list)),
                level=xbmc.LOGWARNING)
            self._stats['missing'] += len(patch_list)
            return

        try:
            content = self._read_file(target_path)
        except Exception as err:
            logging.log(
                "[PatchEngine] Could not read {0}: {1}; skipping {2} patch(es).".format(
                    target_path, err, len(patch_list)),
                level=xbmc.LOGWARNING)
            self._stats['failed'] += len(patch_list)
            return

        original_content = content
        # Preserve whatever line-ending convention the target file already
        # uses (Windows-built addons are frequently CRLF) so injected blocks
        # don't turn into a full-file line-ending diff.
        newline = '\r\n' if '\r\n' in content else '\n'

        for patch in patch_list:
            try:
                content, changed, status = self._apply_single_patch(content, patch, newline)
                self._stats[status] = self._stats.get(status, 0) + 1

                if status in ('applied', 'upgraded', 'removed'):
                    logging.log(
                        "[PatchEngine] [{0}] '{1}' ({2}) -> {3}/{4}".format(
                            status.upper(), patch['id'], patch['name'], addon_id, target_file),
                        level=xbmc.LOGINFO)
                elif status == 'anchor_missing':
                    logging.log(
                        "[PatchEngine] Anchor not found for patch '{0}' in {1}/{2}; "
                        "leaving file untouched for this patch.".format(
                            patch['id'], addon_id, target_file),
                        level=xbmc.LOGWARNING)
                elif status == 'skipped_disabled':
                    logging.log(
                        "[PatchEngine] '{0}' is disabled and not present in {1}/{2}.".format(
                            patch['id'], addon_id, target_file),
                        level=xbmc.LOGDEBUG)
                else:  # skipped_current
                    logging.log(
                        "[PatchEngine] '{0}' already up to date in {1}/{2}.".format(
                            patch['id'], addon_id, target_file),
                        level=xbmc.LOGDEBUG)
            except Exception as err:
                self._stats['failed'] += 1
                logging.log(
                    "[PatchEngine] Failed applying patch '{0}' to {1}/{2}: {3}".format(
                        patch['id'], addon_id, target_file, err),
                    level=xbmc.LOGERROR)

        if content != original_content:
            try:
                if target_path.endswith('.py'):
                    compile(content, target_path, 'exec')
                self._write_file(target_path, content)
                logging.log(
                    "[PatchEngine] Saved patched {0}/{1}.".format(addon_id, target_file),
                    level=xbmc.LOGINFO)
            except Exception as err:
                self._stats['failed'] += len(patch_list)
                logging.log(
                    "[PatchEngine] Failed writing {0}: {1}".format(target_path, err),
                    level=xbmc.LOGERROR)

    # ------------------------------------------------------------------
    # Single-patch application
    # ------------------------------------------------------------------
    @staticmethod
    def _existing_block_regex(patch_id):
        begin = re.escape(BEGIN_TAG.format(id=patch_id))
        end = re.escape(END_TAG.format(id=patch_id))
        # Non-greedy DOTALL span, plus any leading indentation before BEGIN
        # and the single trailing newline after END -- mirrors exactly what
        # _build_block() produces, so removal is a clean, complete no-trace
        # deletion (no stray blank lines left behind).
        pattern = r'[ \t]*' + begin + r'.*?' + end + r'[ \t]*\r?\n?'
        return re.compile(pattern, re.DOTALL)

    def _apply_single_patch(self, content, patch, newline):
        """Returns (new_content, changed, status). `status` is one of:
        'skipped_current', 'applied', 'upgraded', 'anchor_missing'."""
        block_regex = self._existing_block_regex(patch['id'])
        existing_match = block_regex.search(content)

        # ACTIVE SCRUBBING: If disabled, ensure it is completely removed.
        if not patch['enabled']:
            if existing_match:
                working = block_regex.sub('', content, count=1)
                return working, True, 'removed'
            else:
                return content, False, 'skipped_disabled'

        # UP TO DATE: exact marker already present in the existing block.
        if existing_match and patch['marker'] in existing_match.group(0):
            return content, False, 'skipped_current'

        # Compare host shapes outside our previous block. Otherwise an old
        # hook can supply its own anchor and manufacture a healthy result.
        clean = block_regex.sub('', content, count=1) if existing_match else content
        choices = [patch] + list(patch.get('alternatives') or [])
        selected = next((choice for choice in choices
                         if choice.get('anchor') and choice['anchor'] in clean), None)
        if selected is None:
            return content, False, 'anchor_missing'
        if selected.get('superseded'):
            return clean, clean != content, 'superseded'
        patch = dict(patch, **{key: selected.get(key, patch[key])
                              for key in ('anchor', 'hook', 'action')})

        # Locate the anchor BEFORE mutating anything, so a missing anchor
        # (upstream addon changed that line, typo in config, etc.) is a
        # pure no-op -- we never destroy a working stale block just because
        # we can no longer find where to put its replacement.
        if patch['anchor'] not in content:
            return content, False, 'anchor_missing'

        working = content
        status = 'applied'

        if existing_match:
            # ROLLBACK/UPGRADE: an older-marker block exists -> scrub it
            # completely before injecting the current version.
            working = block_regex.sub('', working, count=1)
            status = 'upgraded'
            if patch['anchor'] not in working:
                # Pathological edge case: the anchor text lived inside the
                # stale block we just removed. Bail out without writing
                # anything so the file is never left with neither the old
                # nor the new patch applied.
                logging.log(
                    "[PatchEngine] Anchor for '{0}' vanished after removing its "
                    "stale block; leaving the file untouched.".format(patch['id']),
                    level=xbmc.LOGWARNING)
                return content, False, 'anchor_missing'

        anchor_pos = working.find(patch['anchor'])
        line_start = working.rfind('\n', 0, anchor_pos) + 1
        line_end = working.find('\n', anchor_pos)
        line_end = len(working) if line_end == -1 else line_end + 1  # keep the newline

        # Indentation is read from the REAL anchor line on disk, never
        # assumed from the config -- this is what lets a single hook string
        # slot correctly into whatever depth the anchor actually sits at,
        # even if it drifts between addon versions.
        indent = re.match(r'[ \t]*', working[line_start:line_end]).group(0)

        block = self._build_block(patch, indent, newline)

        if patch['action'] == 'prepend_before':
            working = working[:line_start] + block + working[line_start:]
        else:  # append_after
            working = working[:line_end] + block + working[line_end:]

        return working, True, status

    @staticmethod
    def _reindent_hook(hook, indent):
        """Normalizes a hook string to `indent` regardless of how it was
        authored in patches_config.py.

        Some hooks are written with absolute indentation already baked in
        (assuming a specific anchor depth); others are written flush-left
        assuming the engine will indent them. textwrap.dedent() strips
        whatever *common* leading whitespace every non-blank line shares
        (a no-op for flush-left hooks, and a full strip for pre-indented
        ones), and re-indenting from there produces identical, correct
        output for both authoring styles.
        """
        dedented = textwrap.dedent(hook)
        lines = dedented.splitlines()
        # Drop trailing blank lines the hook's own trailing "\n" produces.
        while lines and lines[-1].strip() == '':
            lines.pop()
        return [(indent + ln) if ln.strip() else '' for ln in lines]

    def _build_block(self, patch, indent, newline):
        lines = [indent + BEGIN_TAG.format(id=patch['id']), indent + patch['marker']]
        lines.extend(self._reindent_hook(patch['hook'], indent))
        lines.append(indent + END_TAG.format(id=patch['id']))
        return newline.join(lines) + newline

    # ------------------------------------------------------------------
    # File I/O (read-once / write-once per target, atomic write)
    # ------------------------------------------------------------------
    @staticmethod
    def _read_file(path):
        # newline='' preserves the file's exact original line endings
        # (no universal-newline translation) so CRLF-authored addon source
        # round-trips byte-for-byte outside of our own inserted blocks.
        with open(path, 'r', encoding='utf-8', errors='replace', newline='') as fh:
            return fh.read()

    @staticmethod
    def _write_file(path, content):
        # Write to a temp file and swap it in with os.replace(), which is
        # atomic on both POSIX and Windows. This means a mid-write crash
        # (force-close, Android low-battery kill, power loss on a box) can
        # never leave a half-written / truncated addon source file behind --
        # worst case the temp file is orphaned and the original is untouched.
        tmp_path = path + '.pwtmp'
        try:
            with open(tmp_path, 'w', encoding='utf-8', newline='') as fh:
                fh.write(content)
                fh.flush()
                # Best-effort durability: survive a hard power cut between
                # the write and the rename, not just a process kill. Some
                # Android/embedded filesystems don't support fsync on every
                # path, so this is deliberately non-fatal.
                try:
                    os.fsync(fh.fileno())
                except Exception:
                    pass
            os.replace(tmp_path, path)
        except Exception:
            # Never leave a stray .pwtmp behind if the write or the atomic
            # swap itself failed -- the caller already logs the exception,
            # this just keeps the addon directory clean for the next run.
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            raise
