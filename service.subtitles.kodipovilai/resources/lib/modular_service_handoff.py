"""Let a prepared MoranSubs replacement start only after a real Kodi restart.

The old service keeps running on the boot when the Wizard prepares the next
package. On the following boot it acknowledges the request and exits before
creating player listeners or writing patches. The Wizard may then replace its
code tree; a missing or invalid request always starts the old service.
"""

import json
import os
import re
import time


REQUEST = 'kodipovil.modular_service_handoff.json'
ACK = 'kodipovil.modular_service_handoff_ack.json'
ADDON_ID = 'service.subtitles.kodipovilai'
_TOKEN = re.compile(r'^[0-9a-f]{32}$')


def _addon_version(path):
    try:
        with open(path, 'r', encoding='utf-8-sig') as source:
            opening = source.read(4096).split('<addon', 1)[1].split('>', 1)[0]
        aid = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', opening)
        version = re.search(r'\bversion\s*=\s*["\']([^"\']+)["\']', opening)
        if aid and aid.group(1) == ADDON_ID and version:
            return version.group(1)
    except (OSError, IndexError):
        pass
    return None


def maybe_yield():
    """Return True only after writing an acknowledgement for a staged update."""
    try:
        import xbmcvfs
        userdata = xbmcvfs.translatePath('special://home/userdata')
        addons_parent = xbmcvfs.translatePath('special://home')
        request_path = os.path.join(userdata, REQUEST)
        with open(request_path, 'rb') as source:
            raw = source.read(2049)
        if len(raw) > 2048:
            return False
        plan = json.loads(raw)
        now = int(time.time())
        token = plan.get('token')
        created = plan.get('created')
        expires = plan.get('expires')
        if (plan.get('schema') != 1 or plan.get('addon_id') != ADDON_ID or
                not isinstance(token, str) or not _TOKEN.fullmatch(token) or
                not isinstance(created, int) or not isinstance(expires, int) or
                created > now + 300 or expires < now or
                expires > created + 7 * 86400 or
                plan.get('creator_pid') == os.getpid()):
            return False
        stage_xml = os.path.join(addons_parent, '.kodipovil-ms-new', 'addon.xml')
        if _addon_version(stage_xml) != plan.get('version'):
            return False
        ack_path = os.path.join(userdata, ACK)
        temp = ack_path + '.tmp-{}'.format(os.getpid())
        with open(temp, 'w', encoding='utf-8') as target:
            json.dump({'schema': 1, 'token': token, 'acked': now}, target)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temp, ack_path)
        return True
    except (OSError, ValueError, TypeError):
        return False
