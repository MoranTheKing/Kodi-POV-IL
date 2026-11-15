"""The build's subtitles without the box behind them.

The owner (15 Nov 2026, a phone screenshot): "the default should be without
the black rectangle created for the subtitles -- only white text with a black
outline". The build shipped Kodi's "box" background (backgroundtype 2, 35 %
black) with a border size of 41; in that mode Kodi draws no outline at all,
the border setting only pads the box. Without the box the outline is drawn,
and 41 is so thick that it fills the letters (QA Kodi, on a white and on a
coloured picture); 25 -- Kodi's own default -- reads cleanly on both.

Three places carry the look:
- userdata/guisettings.xml (config pack 2.0.11): a fresh install;
- apply_to(): the Wizard's own, immutable copy of the pack still has the box,
  and "restore the build's Kodi settings" (gui_repair) reads that copy;
- migrate(): a device already installed, and a new profile (seeded from the
  Wizard's copy of the pack). Only when its background and border settings
  are exactly what the build shipped -- a device where any of the five was
  changed has a look someone chose, and keeps it (so does one moved from the
  old build, which has no box already). Font, size, colour, position are not
  looked at and not touched. Done once: after it, the box is the user's to
  switch back on.

Kodi's Settings API changes memory only (Kodi 21), so the change is saved
through build_skin.persist_live_settings(); the mark is 'pending' before the
first write, so a start that was cut between the two values finishes the
job instead of taking its own half-done state for a user's choice.
"""
import json

import xbmc

from resources.libs.common.config import CONFIG
from resources.libs.common import logging

MARK = 'subtitle_outline_v1'
BOX = {
    'subtitles.backgroundtype': 2,
    'subtitles.bgcolorpick': 'FF000000',
    'subtitles.bgopacity': 35,
    'subtitles.bordersize': 41,
    'subtitles.bordercolorpick': 'FF000000',
}
OUTLINE = {'subtitles.backgroundtype': 0, 'subtitles.bordersize': 25}


def _rpc(method, params):
    reply = json.loads(xbmc.executeJSONRPC(json.dumps(
        {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})))
    return reply.get('result')


def _get(key):
    try:
        return (_rpc('Settings.GetSettingValue', {'setting': key}) or {}).get('value')
    except Exception:
        return None


def _same(actual, wanted):
    if isinstance(wanted, int):
        try:
            return not isinstance(actual, bool) and int(actual) == wanted
        except (TypeError, ValueError):
            return False
    return str(actual or '').upper() == wanted


def apply_to(root):
    """The pack's guisettings <settings> `root` with the look the build ships
    now. Returns root."""
    for key, value in OUTLINE.items():
        for node in root.findall("setting[@id='{0}']".format(key)):
            node.text = str(value)
            node.attrib.pop('default', None)
    return root


def migrate():
    """At start-up, until it has been done once in this profile. Returns
    True when the look was changed now."""
    try:
        state = CONFIG.get_setting(MARK) or ''
        if state in ('applied', 'kept'):
            return False
        # Kodi hides the box's colour and opacity from its Settings API while
        # no box is on (they answer only with background type 2 or 3), so
        # "all five still as shipped" can be asked only before the first
        # change -- and what is asked afterwards is the two values set here.
        now = dict((key, _get(key)) for key in BOX)
        if now['subtitles.backgroundtype'] is None:
            return False                    # Kodi is not answering: next start
        target = dict(BOX, **OUTLINE)
        if state != 'pending':
            if not all(_same(now[key], BOX[key]) for key in BOX):
                # Not the shipped box: nothing to do, and nothing is marked --
                # a profile is first seen with Kodi's own defaults and gets
                # the build's settings (from the Wizard's copy of the pack,
                # the box) only later in its first start.
                return False
            CONFIG.set_setting(MARK, 'pending')
            if CONFIG.get_setting(MARK) != 'pending':
                return False                # the mark did not hold: change nothing
        elif not all(_same(now[key], BOX[key]) or _same(now[key], target[key])
                     or (now[key] is None and key not in OUTLINE
                         and _same(now['subtitles.backgroundtype'], 0)) for key in BOX):
            # changed by hand while the job was half done: theirs now
            CONFIG.set_setting(MARK, 'kept')
            return False
        # The background first: the border size is greyed out while the box is on.
        for key, value in OUTLINE.items():
            if not _same(now[key], value) and _rpc(
                    'Settings.SetSettingValue', {'setting': key, 'value': value}) is not True:
                logging.log('[Subtitle style] Kodi did not take {0}'.format(key), level=xbmc.LOGWARNING)
                return False                # still 'pending': tried again next start
        from resources.libs import build_skin
        saved = build_skin.persist_live_settings()
        if not all(_same(_get(key), value) for key, value in OUTLINE.items()):
            return False
        if saved:
            CONFIG.set_setting(MARK, 'applied')
        logging.log('[Subtitle style] the box behind the subtitles is off, outline 25 (saved: {0})'.format(saved),
                    level=xbmc.LOGINFO)
        return True
    except Exception as err:
        logging.log('[Subtitle style] skipped: {0}'.format(err), level=xbmc.LOGWARNING)
        return False
