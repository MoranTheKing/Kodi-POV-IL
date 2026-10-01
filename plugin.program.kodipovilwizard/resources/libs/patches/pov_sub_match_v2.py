# File: plugin.program.kodipovilwizard/resources/libs/patches/pov_sub_match_v2.py

import sys
import xbmc
import xbmcvfs
import time

def _refresh_cached(cache, meta):
    """A late availability answer is a local cache read, never another request."""
    sm = cache.get('module')
    params = sm._media_params(meta)
    entry = sm._cache_entry(sm._media_key(params)) if params else None
    if not entry or not entry.get('warm'):
        return False
    cache.update(names=list(entry.get('names') or []),
                 emb=list(entry.get('embedded') or []),
                 syncrel=set(entry.get('sync_rel') or []))
    return True

def refresh_when_ready(window):
    """Fill late badges in the existing list without reloading or moving focus."""
    cache = getattr(window, '_wizard_sub_cache', {})
    if not cache.get('loaded') or cache.get('names') or cache.get('polling'):
        return
    cache['polling'] = True
    def refresh():
        try:
            monitor = xbmc.Monitor()
            for _ in range(15):
                if monitor.waitForAbort(1):
                    return
                if not _refresh_cached(cache, window.meta):
                    continue
                control = window.win
                for index in range(control.size()):
                    row = control.getListItem(index)
                    source = window._results.get(row.getProperty('source'))
                    if not source:
                        continue
                    prefix = cache['module'].label_prefix(
                        source.get('URLName') or source.get('name') or '',
                        cache['names'], cache['emb'], source.get('name') or '', cache['syncrel'])
                    if prefix:
                        row.setProperty('tikiskins.size_label', prefix + source.get('size_label', 'N/A'))
                return
        except Exception:
            # Closing/filtering the dialog must never affect playback.
            pass
        finally:
            cache['polling'] = False
    from threading import Thread
    Thread(target=refresh, name='POV subtitle badges', daemon=True).start()

def run(local_vars):
    """
    Hooks directly after POV sets the size_label property on the listitem.
    We fetch the sub prefix and sequential-override the property.
    """
    try:
        self_obj = local_vars.get('self')
        get_fn = local_vars.get('get')
        set_property = local_vars.get('set_property')

        if not self_obj or not get_fn or not set_property:
            return

        meta = getattr(self_obj, 'meta', None)
        if not meta:
            return

        # Initialize memoized cache exclusively on the window object lifecycle
        if getattr(self_obj, '_wizard_sub_cache', {}).get('meta') != meta:
            self_obj._wizard_sub_cache = {'loaded': False, 'module': None}

        cache = self_obj._wizard_sub_cache
        now = time.monotonic()
        if not cache.get('loaded') and now >= cache.get('retry_at', 0):
            cache.update(meta=dict(meta), retry_at=now + 1)

            # Subtitle module path injection
            sub_path = xbmcvfs.translatePath('special://home/addons/service.subtitles.kodipovilai/resources/lib')
            if sub_path not in sys.path:
                sys.path.append(sub_path)

            try:
                import he_sub_match as sm_m
                self_obj._wizard_sub_cache.update({
                    'loaded': True,
                    'module': sm_m,
                    'names': sm_m.release_names(meta),
                    'emb': sm_m.embedded_names(meta),
                    'syncrel': sm_m.confirmed_releases(meta)
                })
            except ImportError:
                xbmc.log("POV_WIZARD_PATCH [pov_sub_match_v2]: he_sub_match module not found.", xbmc.LOGINFO)
            except Exception as e:
                xbmc.log(f"POV_WIZARD_PATCH [pov_sub_match_v2]: Setup error - {str(e)}", xbmc.LOGWARNING)

        cache = self_obj._wizard_sub_cache
        if not cache.get('loaded'):
            return
        if not cache.get('names') and now >= cache.get('peek_at', 0):
            cache['peek_at'] = now + 1
            _refresh_cached(cache, meta)

        nm = get_fn('URLName') or get_fn('name') or ''
        rl = get_fn('name') or ''

        prefix = ''
        try:
            sm_m = cache['module']
            prefix = sm_m.label_prefix(nm, cache['names'], cache['emb'], rl, cache['syncrel'])
        except Exception as e:
            xbmc.log(f"POV_WIZARD_PATCH [pov_sub_match_v2]: Row processing error - {str(e)}", xbmc.LOGDEBUG)

        if prefix:
            orig_size = get_fn('size_label', 'N/A')
            # Sequential Override Action: safely overwrite the upstream value dynamically
            set_property('tikiskins.size_label', f"{prefix}{orig_size}")

    except Exception as e:
        xbmc.log(f"POV_WIZARD_PATCH [pov_sub_match_v2]: Global hook execution error - {str(e)}", xbmc.LOGWARNING)