# File: plugin.program.kodipovilwizard/resources/libs/patches/pov_source_quality_v2.py

import xbmc

def run(local_vars):
    """
    Mutates self.results in place before the enumeration loop begins.
    Upgrades incorrect 'SD' flags based on the actual release string.
    """
    try:
        self_obj = local_vars.get('self')
        if not self_obj or not hasattr(self_obj, 'results'):
            return

        from modules.source_utils import get_release_quality

        rank = {'4K': 0, '1080P': 1, '720P': 2, 'SD': 3}
        new_results = []

        for it in self_obj.results:
            if it.get('_pin_top'):
                new_results.append(it)
                continue

            qual = (it.get('quality') or 'SD').upper()
            if qual == 'SD':
                nm = it.get('URLName') or it.get('name') or ''
                real_q = get_release_quality(nm) if nm else ''

                # Upgrade logic
                if real_q.upper() in ('4K', '1080P', '720P'):
                    it['quality'] = real_q.upper()

            new_results.append(it)

        self_obj.results[:] = new_results
        # Sort keeping pinned items top, then quality, then size reversed
        self_obj.results.sort(key=lambda i: (
            0, 0, 0.0) if i.get('_pin_top') else (
            1, rank.get((i.get('quality') or 'SD').upper(), 3), -float(i.get('size') or 0)
        ))

    except Exception as e:
        xbmc.log(f"POV_WIZARD_PATCH [pov_source_quality_v2]: Failed - {str(e)}", xbmc.LOGWARNING)