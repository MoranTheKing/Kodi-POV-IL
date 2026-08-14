# Stop two add-ons offering an update the build will not let anybody take.
#
# Umbrella and Account Manager Lite each check their own upstream repo at
# Kodi start and pop a toast when it is ahead. Neither toast leads anywhere.
# The build pins both versions on purpose -- Umbrella carries a dozen of our
# patches (the Hebrew search fix, the subtitle-match badge, the picked-source
# publisher, the MDBList routing) and the upstream zip over the top of them
# removes every one silently. So the message offers the user something that
# would cost them half the build, and the add-on screen offers no button to
# take it either, which is exactly why it reads as a fault rather than an
# offer.
#
# Both add-ons gate the check behind a setting of their own, so this is a
# settings write and not a patch:
#
#   plugin.video.umbrella   general.checkAddonUpdates   service.py, before
#                                                       AddonCheckUpdate().run()
#   script.module.acctmgr   check_for_update            lib/startup.py, at the
#                                                       top of AddonCheckUpdate
#
# Both ship 'true'.
#
# ONCE, AND ONLY WHILE THE VALUE IS STILL WHAT THEY SHIPPED. Somebody who goes
# and turns the check back on has said something, and this must not argue with
# them every boot -- so the write is guarded on the shipped default, and the
# decision is recorded either way, including the decision to leave it alone.
# An add-on that is not installed is not recorded at all, so it is handled if
# it ever arrives.
#
# The write goes through addon_settings_safe.apply(), never straight through
# xbmcaddon: a plain setSetting on somebody else's add-on makes Kodi
# re-serialise that add-on's WHOLE settings.xml, which can hand a setting we
# never named back its default. See addon_settings_safe.py.

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None

try:
    from resources.lib import addon_settings_safe
except Exception:
    addon_settings_safe = None


# (add-on id, setting, the value they ship, what we want, guard property)
# The guard property is the home-window flag the add-on uses to mute its own
# settings monitor while it writes settings itself; Umbrella has one, Account
# Manager Lite does not.
TARGETS = (
    ('plugin.video.umbrella', 'general.checkAddonUpdates', 'true', 'false',
     'umbrella.updateSettings'),
    ('script.module.acctmgr', 'check_for_update', 'true', 'false', None),
)
DONE_SETTING = '_update_nag_quiet_v1'


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('update_nag_patcher: ' + msg, level=level)
    except Exception:
        pass


def _done():
    """The (add-on, setting) pairs we have already settled, once and for all."""
    try:
        raw = kodi_utils.get_setting(DONE_SETTING, '') or ''
    except Exception:
        return set()
    return set(p.strip() for p in raw.split(',') if p.strip())


def _record(tags):
    try:
        kodi_utils.set_setting(DONE_SETTING, ','.join(sorted(tags)))
    except Exception:
        pass


def ensure_quiet():
    """'not_installed' | 'unchanged' | 'patched' | 'write_failed'.
    Never raises."""
    if addon_settings_safe is None or kodi_utils is None:
        return 'write_failed'
    done = _done()
    settled = set(done)
    quieted = []
    failed_any = False
    saw_one = False
    for addon_id, key, shipped, wanted, guard in TARGETS:
        tag = addon_id + ':' + key
        if tag in done:
            # Settled on an earlier start. That still counts as having found
            # the add-on -- reporting "not installed" here would be a status
            # nobody could act on, for the ordinary case of a device where
            # this has already run once.
            saw_one = True
            continue
        try:
            import xbmcaddon
            target = xbmcaddon.Addon(addon_id)
        except Exception:
            # Not installed, or Kodi is still in the window where it says so.
            # Either way, record nothing: if it turns up later, so do we.
            continue
        saw_one = True
        try:
            current = (target.getSetting(key) or '').strip()
        except Exception:
            # Cannot read it -> cannot claim to know where it stands.
            failed_any = True
            continue
        if current != shipped:
            # They have moved it themselves. That is an answer, and it is
            # settled -- including if they later happen to move it back.
            settled.add(tag)
            continue
        _changed, _restored, failed = addon_settings_safe.apply(
            addon_id, ((key, wanted),), guard_property=guard)
        if key in failed:
            # Recording this would mean never trying again for a value we
            # never actually wrote.
            failed_any = True
            continue
        settled.add(tag)
        quieted.append(addon_id)
    if settled != done:
        _record(settled)
    if quieted:
        _log('update notification switched off for: ' + ', '.join(quieted))
        return 'patched'
    if failed_any:
        return 'write_failed'
    if not saw_one:
        return 'not_installed'
    return 'unchanged'
