# File: plugin.program.kodipovilwizard/resources/libs/patches/pov_torbox_usage.py

import xbmc
import xbmcgui
from datetime import datetime, timezone

def _format_bytes(value):
    if value in (None, ''):
        return ''
    try:
        value = float(value)
    except Exception:
        return str(value)

    if value >= 1024 ** 3:
        return '%.2f GB' % (value / (1024 ** 3))
    if value >= 1024 ** 2:
        return '%.2f MB' % (value / (1024 ** 2))
    return '%d Bytes' % int(value)

def _torbox_usage_30(stats):
    if not isinstance(stats, dict):
        return None
    bandwidth = stats.get('bandwidth') or stats.get('bandwidths')
    if isinstance(bandwidth, list):
        total = 0
        found = False
        for item in bandwidth:
            if not isinstance(item, dict):
                continue
            value = item.get('bytes_downloaded')
            if value is not None:
                try:
                    total += int(value)
                    found = True
                except Exception:
                    pass
        if found:
            return total

    general = stats.get('general')
    if isinstance(general, dict):
        for key in ('bytes_downloaded', 'total_downloaded', 'total_data_downloaded'):
            if key in general:
                return general.get(key)
    return None

def show_textviewer_and_exit(api_instance, account_info):
    """
    Displays the textviewer dialog and terminates function flow to prevent
    the smaller ok_dialog from executing.
    """
    try:
        email = account_info.get('email', 'N/A')
        username = account_info.get('customer', 'N/A')

        plans = {0: 'Free', 1: 'Essential', 2: 'Pro', 3: 'Standard'}
        plan_code = account_info.get('plan')
        status = plans.get(plan_code, str(plan_code) if plan_code is not None else 'N/A')

        expires_label = 'N/A'
        days_remaining = 'N/A'
        expires_raw = account_info.get('premium_expires_at')
        if expires_raw:
            try:
                expires = datetime.fromisoformat(expires_raw.replace('Z', '+00:00'))
                expires_label = str(expires.date() if hasattr(expires, 'date') else expires)
                days_remaining = str((expires - datetime.now(timezone.utc)).days)
            except Exception:
                pass

        total_downloaded_raw = account_info.get('total_downloaded', '')
        downloaded = _format_bytes(total_downloaded_raw) if total_downloaded_raw not in ('', None) else 'N/A'

        usage_30 = None
        try:
            if hasattr(api_instance, 'user_stats'):
                stats_data = api_instance.user_stats()
                usage_30 = _torbox_usage_30(stats_data)
        except Exception as e:
            xbmc.log(f"[WIZARD PATCH] TorBox API user_stats fetch failed: {e}", level=xbmc.LOGWARNING)

        usage_30_str = _format_bytes(usage_30) if usage_30 is not None else 'N/A'

        body = [
            'Days Remaining: {0}'.format(days_remaining),
            'Expires: {0}'.format(expires_label),
            'Account: {0}'.format(email),
            'Username: {0}'.format(username),
            'Status: {0}'.format(status),
            'Downloaded: {0}'.format(downloaded),
            # The API may return an unbounded history or a lifetime fallback.
            # Do not label that value as a verified 30-day total.
            'Reported Usage: {0}'.format(usage_30_str),
        ]

        text = '\n\n'.join(body)

        kodi_utils_hide = getattr(api_instance, 'hide_busy_dialog', None)
        dialog = xbmcgui.Dialog()
        try:
            dialog.textviewer('TORBOX', text)
        except Exception:
            dialog.ok('TORBOX', text)

    except Exception as e:
        xbmc.log(f"[WIZARD PATCH] Custom dialog error: {e}", level=xbmc.LOGERROR)