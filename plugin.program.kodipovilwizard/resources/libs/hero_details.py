"""What the Onyx home's hero lacks for Israeli shows, fetched for the item it
shows (mode=hero_details).

Idan Plus lists Keshet 12's programmes with the name as the plot and the
poster as the backdrop, and Kan 11's with the poster as the backdrop
(field report: no summary on Keshet, no backdrop like Reshet's). The sites
have the rest:

* Keshet 12: the programme's page on mako (its __NEXT_DATA__ block, as
  Idan's keshet.py reads it) -- data.hero: the summary (description), a
  1920x1080 picture (pics) and the title logo (logo, a transparent PNG).
* Kan 11: Kan's programme list (api/mobile/subClass, the list Idan's kan.py
  reads; 200 a page) -- image_base, the wide picture of every programme. The
  summary Idan already gives.

The skin names the item in Window(home).Property(povil.details.key) (its
folder path) once the screen has been still for a second, and runs this
mode; the answer goes to povil.details.plot / .fanart / .logo, and
povil.details.for names the item they belong to (set last, so the skin never
pairs an item with another one's details) -- unless the skin has moved on to
another item meanwhile: a slow answer for it must not wipe what the newer
item already shows (its own run answers for it). Each programme is fetched
once a week (a failure, or a page without its data, again after an hour),
Kan's list once a day (a failure after an hour); all of it is kept in the
Wizard's addon_data (hero_details/), and a file not written for 30 days goes.
Keshet's pages are fetched from mako only.
"""
import hashlib
import json
import os
import re
import time
from urllib.parse import parse_qs, unquote_plus, urlparse

import xbmcgui
import xbmcvfs

STORE = 'special://profile/addon_data/plugin.program.kodipovilwizard/hero_details/'
KEEP = 7 * 24 * 3600
RETRY = 3600
PRUNE = 30 * 24 * 3600
KAN_KEEP = 24 * 3600
KAN_LIST = 'https://mobapi.kan.org.il/api/mobile/subClass?from={0}&id=4444'
KAN_PAGE = 200
KAN_MAX_PAGES = 5
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36'
HEADERS = {'User-Agent': UA, 'Accept-Language': 'he-IL,he;q=0.9,en;q=0.8'}
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
KAN_ID = re.compile(r'/p-(\d+)/?')


def _store():
    path = xbmcvfs.translatePath(STORE)
    os.makedirs(path, exist_ok=True)
    return path


def _read(name):
    try:
        with open(os.path.join(_store(), name), encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write(name, data):
    path = os.path.join(_store(), name)
    try:
        with open(path + '.tmp', 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(path + '.tmp', path)
    except OSError:
        pass


def _prune():
    """Files not written for PRUNE seconds go (shows that left the lists)."""
    limit = time.time() - PRUNE
    try:
        for entry in os.scandir(_store()):
            if entry.name.endswith('.json') and entry.stat().st_mtime < limit:
                os.remove(entry.path)
    except OSError:
        pass


def _get(url, as_json=False):
    import requests
    reply = requests.get(url, headers=HEADERS, timeout=8)
    reply.raise_for_status()
    return reply.json() if as_json else reply.text


def keshet(url):
    """{plot, fanart, logo} from the programme's page on mako."""
    host = (urlparse(url).hostname or '').lower()
    if host != 'mako.co.il' and not host.endswith('.mako.co.il'):
        return {}
    match = NEXT_DATA.search(_get(url))
    if not match:
        raise ValueError('no __NEXT_DATA__')    # a check or consent page: again in an hour
    data = json.loads(match.group(1))['props']['pageProps']['data']
    hero = data.get('hero') or {}
    seo = data.get('seo') or {}
    pics = [p.get('picUrl') for p in hero.get('pics') or [] if isinstance(p, dict) and p.get('picUrl')]
    return {'plot': (hero.get('description') or seo.get('description') or '').strip(),
            'fanart': pics[0] if pics else '',
            'logo': hero.get('logo') or ''}


def _kan_wide():
    """({programme id: its wide picture}, the list was read) from Kan 11's programme
    list, kept a day; while it cannot be read, the last one read (if any)."""
    kept = _read('kan_wide.json')
    if kept and time.time() - kept.get('ts', 0) < (KAN_KEEP if kept.get('ok', True) else RETRY):
        return kept.get('wide') or {}, kept.get('ok', True)
    try:
        wide = _kan_list()
    except Exception:
        stale = (kept or {}).get('wide') or {}
        _write('kan_wide.json', {'ts': time.time(), 'ok': False, 'wide': stale})
        return stale, False
    _write('kan_wide.json', {'ts': time.time(), 'ok': True, 'wide': wide})
    return wide, True


def _kan_list():
    wide = {}
    start = 1
    for _ in range(KAN_MAX_PAGES):
        entries = _get(KAN_LIST.format(start), as_json=True).get('entry') or []
        for entry in entries:
            items = ((entry.get('media_group') or [{}])[0] or {}).get('media_item') or []
            src = next((i.get('src') for i in items if i.get('key') == 'image_base' and i.get('src')), '')
            if entry.get('id') is not None and src:
                wide[str(entry['id'])] = src.split('?')[0] + '?width=1280'
        if len(entries) < KAN_PAGE:
            break
        start += KAN_PAGE
    return wide


def kan(url):
    match = KAN_ID.search(url)
    if not match:
        return {}
    wide, read = _kan_wide()
    if match.group(1) not in wide and not read:
        raise ValueError("Kan's list could not be read")   # this show: again in an hour, not a week
    return {'plot': '', 'fanart': wide.get(match.group(1), ''), 'logo': ''}


def lookup(key):
    """The details for an Idan Plus item (its folder path); {} for anything else."""
    query = parse_qs(urlparse(key).query)
    module = (query.get('module') or [''])[0]
    url = (query.get('url') or [''])[0]
    if '://' not in url:
        url = unquote_plus(url)     # Idan Plus quotes its url= twice (quote_plus, then urlencode)
    fetch = {'keshet': keshet, 'kan': kan}.get(module)
    if not fetch or not url.startswith('https://'):
        return {}
    name = hashlib.md5(key.encode('utf-8')).hexdigest() + '.json'
    kept = _read(name)
    if kept and time.time() - kept.get('ts', 0) < (KEEP if kept.get('ok') else RETRY):
        return kept.get('details') or {}
    try:
        details, ok = fetch(url), True
    except Exception:
        details, ok = {}, False
    _prune()
    _write(name, {'ts': time.time(), 'ok': ok, 'details': details})
    return details


def run():
    home = xbmcgui.Window(10000)
    key = home.getProperty('povil.details.key')
    if not key:
        return
    details = lookup(key)
    if home.getProperty('povil.details.key') != key:
        return      # the skin moved on: kept for a revisit, the newer item's own run answers
    for field in ('plot', 'fanart', 'logo'):
        home.setProperty('povil.details.%s' % field, details.get(field) or '')
    home.setProperty('povil.details.for', key)
