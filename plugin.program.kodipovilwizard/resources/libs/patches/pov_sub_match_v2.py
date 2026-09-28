# File: plugin.program.kodipovilwizard/resources/libs/patches/pov_sub_match_v2.py

import sys
import xbmc
import xbmcvfs

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
        if not hasattr(self_obj, '_wizard_sub_cache'):
            self_obj._wizard_sub_cache = {'loaded': False, 'module': None}

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