"""The user's own TV channels (Kodi's live TV: IPTV Simple and the like) as a
right-to-left home row (the Onyx skin).

Kodi lists its channels itself (pvr://channels/tv/*) with the first one on the
left; the Onyx home starts every row on the right. This route reads the same
channels through Kodi's JSON-RPC (PVR.GetChannels, the "all channels" group,
hidden ones left out, the first ROW_LIMIT -- a provider's list may hold
thousands) and lists them last first, each marked povil_rtl=1, so the skin
starts the row on the first channel, on the right. Each carries what is on
now as its plot, and the Onyx soft wash of its logo (povil_rtl.blur_art).

A tap plays the channel (mode=pvr_play: Player.Open by channel id), once Kodi
still knows it (PVR.GetChannelDetails): Kodi 21 crashes on Player.Open for a
channel id while it has no live TV (checked in the QA Kodi) -- a row shown
before the live TV went away. No live TV, or a kids profile: an empty row,
which Onyx hides.

default.py hands both modes here before the Wizard's router: a home row
should not pay for the Wizard's menus.
"""
import json
from urllib.parse import unquote

import xbmc
import xbmcgui
import xbmcplugin

BASE = 'plugin://plugin.program.kodipovilwizard/'
ROW_LIMIT = 200


def _rpc(method, params):
    try:
        reply = json.loads(xbmc.executeJSONRPC(json.dumps(
            {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})))
    except (TypeError, ValueError):
        return None
    return reply.get('result')


def _unwrap(url):
    """Kodi hands art back wrapped (image://<address>/); the row wants the address."""
    if url.startswith('image://') and url.endswith('/'):
        inner = url[len('image://'):-1]
        if '/' not in inner and '@' not in inner:
            return unquote(inner)
    return url


def channels():
    """[(channel id, name, logo, on now)] in Kodi's order; [] without live TV."""
    result = _rpc('PVR.GetChannels', {'channelgroupid': 'alltv',
                                      'properties': ['thumbnail', 'hidden', 'broadcastnow'],
                                      'limits': {'start': 0, 'end': ROW_LIMIT}})
    found = []
    for channel in (result or {}).get('channels') or []:
        if channel.get('hidden') or not isinstance(channel.get('channelid'), int):
            continue
        now = (channel.get('broadcastnow') or {}).get('title') or ''
        found.append((channel['channelid'], channel.get('label') or '', _unwrap(channel.get('thumbnail') or ''), now))
    return found


def _child():
    """A kids profile, or no way to tell: then nothing is listed or played."""
    try:
        from resources.libs.patches import profile_age_guard
        return profile_age_guard.active_policy() is not None
    except Exception:
        return True


def _blur(item):
    try:
        from resources.libs.patches import povil_rtl
        povil_rtl.blur_art(item)
    except Exception:
        pass


def row(handle):
    items = []
    if not _child():
        for channel_id, name, logo, now in reversed(channels()):
            item = xbmcgui.ListItem(name, offscreen=True)
            if logo:
                item.setArt({'thumb': logo, 'icon': logo})
                _blur(item)
            tag = item.getVideoInfoTag()
            tag.setTitle(name)
            if now:
                tag.setPlot(now)
            item.setProperty('povil_rtl', '1')
            item.setProperty('IsPlayable', 'false')
            items.append(('%s?mode=pvr_play&id=%d' % (BASE, channel_id), item, False))
    if items:
        xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.endOfDirectory(handle, cacheToDisc=False)


def play(handle, params):
    if handle >= 0:
        # Kodi may start a non-playable item as media: nothing to play here
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem(offscreen=True))
    if _child():
        return
    try:
        channel_id = int(params.get('id', ''))
    except ValueError:
        return
    if not _rpc('PVR.GetChannelDetails', {'channelid': channel_id}):
        return      # no live TV now: Player.Open would bring Kodi down (see above)
    _rpc('Player.Open', {'item': {'channelid': channel_id}})
