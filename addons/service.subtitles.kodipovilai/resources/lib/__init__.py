# Package-level compatibility wiring.
#
# Keep this tiny: service.py imports resources.lib modules from many entry
# points. We use that import point to wrap the DarkSubs integration so the
# None-path guard runs immediately after the regular AI translation hook is
# installed or verified.


def _wrap_darksubs_none_guard():
    try:
        from . import dark_subs_integration
        from . import darksubs_none_guard_patcher
        from . import kodi_utils
    except Exception:
        return

    if getattr(dark_subs_integration, '_none_guard_wrapped', False):
        return

    original = dark_subs_integration.maybe_patch_darksubs

    def wrapped_maybe_patch_darksubs(*args, **kwargs):
        status = original(*args, **kwargs)
        try:
            guard_status = darksubs_none_guard_patcher.ensure_patched()
            if guard_status == 'patched':
                kodi_utils.log('DarkSubs AI hook None guard applied',
                               level='INFO')
            elif guard_status in ('unmatched', 'write_failed', 'read_failed'):
                kodi_utils.log('DarkSubs AI hook None guard skipped: '
                               + guard_status, level='WARNING')
        except Exception as e:
            try:
                kodi_utils.log(
                    'DarkSubs AI hook None guard crashed: {0}'.format(e),
                    level='WARNING')
            except Exception:
                pass
        return status

    dark_subs_integration.maybe_patch_darksubs = wrapped_maybe_patch_darksubs
    dark_subs_integration._none_guard_wrapped = True


_wrap_darksubs_none_guard()
