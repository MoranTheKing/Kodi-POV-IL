"""Keep the current profile flag fresh and stop unapproved external playback."""
import hashlib
import json
import time

import xbmc
import xbmcgui
import xbmcvfs

from resources.libs.patches import profile_age_guard as guard


def permitted_receipt(receipt, profile, url, policy, now):
    digest = hashlib.sha256(str(url).split('|')[0].encode('utf-8')).hexdigest()
    return (receipt.get('profile') == profile and receipt.get('url_hash') == digest and
            receipt.get('host') in ('pov', 'umbrella') and 0 <= now - receipt.get('issued', 0) <= 300 and
            guard.allows(policy, receipt_meta(receipt)))


def receipt_meta(receipt):
    return {'mpaa': receipt.get('mpaa'),
            'mediatype': 'tv' if str(receipt.get('key')).startswith('tv:') else 'movie',
            'tmdb_id': str(receipt.get('key') or '').split(':')[-1]}


def run():
    window = xbmcgui.Window(10000)
    monitor = xbmc.Monitor()
    player = xbmc.Player()
    import uuid
    token = uuid.uuid4().hex
    window.setProperty('POVIL.ProfileGuardOwner', token)
    last = None
    while not monitor.waitForAbort(0.5):
        if window.getProperty('POVIL.ProfileGuardOwner') != token:
            return
        policy = guard.active_policy()
        profile = xbmcvfs.translatePath('special://profile/')
        window.setProperty('POVIL.ChildProfile', 'true' if policy is not None else 'false')
        if policy is None or not player.isPlayingVideo():
            last = None
            continue
        if policy.get('blocked'):
            player.stop()
            last = None
            continue
        try:
            url = player.getPlayingFile()
            receipt = json.loads(window.getProperty('POVIL.ChildPlay') or '{}')
            identity = (profile, url)
            if last and identity == last[:2] and guard.allows(policy, receipt_meta(last[2])):
                continue  # next-episode preparation must not stop this video
            if not permitted_receipt(receipt, profile, url, policy, time.time()):
                player.stop()
                window.clearProperty('POVIL.ChildPlay')
                xbmcgui.Dialog().notification('פרופיל ילדים', 'הניגון אינו מאושר לפרופיל הילדים.', time=3500)
            else:
                last = (profile, url, receipt)
        except Exception:
            # Unknown/missing receipt is never an implicit permission.
            player.stop()


if __name__ == '__main__':
    run()
