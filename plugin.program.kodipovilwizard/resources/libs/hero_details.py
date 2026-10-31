"""What the Onyx home's hero lacks for Israeli shows, fetched for the item it
shows (mode=hero_details) and kept for the rows themselves.

Idan Plus lists Keshet 12's programmes with the name as the plot and the
poster as the backdrop, and Kan 11's with the poster as the backdrop
(field report: no summary on Keshet, no backdrop like Reshet's). The sites
have the rest:

* Keshet 12: the programme's page on mako (its __NEXT_DATA__ block, as
  Idan's keshet.py reads it) -- data.hero: the summary (description), a
  1920x1080 picture (pics) and the title logo (logo, a transparent PNG).
* Kan 11: Kan's programme list (api/mobile/subClass, the list Idan's kan.py
  reads; 200 a page, about 880 KB each) -- image_base, the 1920x1080 picture
  of every programme (asked 1280 wide). The summary Idan already gives; Kan
  has no title logos.

The skin names the item in Window(home).Property(povil.details.key) (its
folder path) once the screen has been still for a second, and its neighbours
in povil.details.near (two on each side), and runs this mode. The item's
answer goes to povil.details.plot / .fanart / .logo, then povil.details.for
names the item they belong to (set last, so the skin never pairs an item with
another one's details); the neighbours' go to povil.details.1. ... .4.: a step
to one of them shows its details at once. Nothing is written once the skin
has moved on to another item meanwhile: a slow answer for it must not wipe
what the newer item already shows (its own run answers for it).

What was fetched is also kept for the rows: Keshet's in index.json (folder
path -> details), Kan's list in kan_wide.json, which povil_rtl reads when
Idan Plus lists a home row -- an item fetched once shows its details at once
from then on, and every Kan item once the list was read. mode=hero_warm reads
Kan's list when the Israeli tab opens (once a Kodi session), before the user
reaches Kan's row; one read at a time (kan_wide.lock).

Each programme is fetched once a week (a failure, or a page without its
data, again after an hour), Kan's list once a day (a failure after an hour);
all of it is kept in the Wizard's addon_data (hero_details/), and a show's
file not written for 30 days goes. Keshet's pages are fetched from mako only.
"""
import hashlib
import json
import os
import re
import time
import uuid
from urllib.parse import parse_qs, unquote_plus, urlparse

import xbmcgui
import xbmcvfs

STORE = 'special://profile/addon_data/plugin.program.kodipovilwizard/hero_details/'
INDEX = 'index.json'
KAN_FILE = 'kan_wide.json'
KAN_LOCK = 'kan_wide.lock'
KEEP = 7 * 24 * 3600
RETRY = 3600
PRUNE = 30 * 24 * 3600
KAN_KEEP = 24 * 3600
KAN_LIST = 'https://mobapi.kan.org.il/api/mobile/subClass?from={0}&id=4444'
KAN_PAGE = 200
KAN_MAX_PAGES = 5
KAN_TIMEOUT = 25            # a page is ~880 KB: a phone on a slow line needs it
LOCK_STALE = 150
NEAR = 4
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
    """Whole or not at all: each write has a temporary file of its own (two runs
    may write index.json at once)."""
    path = os.path.join(_store(), name)
    temp = '%s.%s.tmp' % (path, uuid.uuid4().hex)
    try:
        with open(temp, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(temp, path)
    except OSError:
        try:
            os.remove(temp)
        except OSError:
            pass


def _prune():
    """A show's file not written for PRUNE seconds goes (shows that left the lists)."""
    limit = time.time() - PRUNE
    try:
        for entry in os.scandir(_store()):
            if (entry.name.endswith('.json') and entry.name not in (INDEX, KAN_FILE)
                    and entry.stat().st_mtime < limit):
                os.remove(entry.path)
    except OSError:
        pass


def _get(url, as_json=False, timeout=8):
    import requests
    reply = requests.get(url, headers=HEADERS, timeout=timeout)
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


def _fresh(kept):
    return kept and time.time() - kept.get('ts', 0) < (KAN_KEEP if kept.get('ok', True) else RETRY)


def _locked(path):
    try:
        return time.time() - os.path.getmtime(path) < LOCK_STALE
    except OSError:
        return False


def _kan_wide():
    """({programme id: its wide picture}, the list was read) from Kan 11's programme
    list, kept a day; while it cannot be read, the last one read (if any). One read
    at a time: another run reading it is waited for."""
    kept = _read(KAN_FILE)
    if _fresh(kept):
        return kept.get('wide') or {}, kept.get('ok', True)
    lock = os.path.join(_store(), KAN_LOCK)
    waited = 0
    while _locked(lock) and waited < LOCK_STALE:
        time.sleep(0.5)
        waited += 0.5
        kept = _read(KAN_FILE)
        if _fresh(kept):
            return kept.get('wide') or {}, kept.get('ok', True)
    kept = _read(KAN_FILE)
    if _fresh(kept):            # written just as the other run let go
        return kept.get('wide') or {}, kept.get('ok', True)
    try:
        with open(lock, 'w') as fh:
            fh.write(str(time.time()))
    except OSError:
        pass
    try:
        try:
            wide = _kan_list()
        except Exception:
            stale = (kept or {}).get('wide') or {}
            _write(KAN_FILE, {'ts': time.time(), 'ok': False, 'wide': stale})
            return stale, False
        _write(KAN_FILE, {'ts': time.time(), 'ok': True, 'wide': wide})
        return wide, True
    finally:
        try:                    # only once the file is written: a waiter finds it
            os.remove(lock)
        except OSError:
            pass


def _kan_list():
    wide = {}
    start = 1
    for _ in range(KAN_MAX_PAGES):
        entries = _get(KAN_LIST.format(start), as_json=True, timeout=KAN_TIMEOUT).get('entry') or []
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


_index = None


def _remember(key, details):
    """Keshet's details for the rows (povil_rtl reads index.json): read once a run,
    and again just before a change is written (another run may have added to it)."""
    global _index
    if _index is None:
        _index = _read(INDEX) or {}
    if _index.get(key) != details:
        _index = _read(INDEX) or {}
        _index[key] = details
        _write(INDEX, _index)


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
        details = kept.get('details') or {}
        if kept.get('ok') and module == 'keshet' and any(details.values()):
            _remember(key, details)     # an entry another run's write lost comes back
        return details
    try:
        details, ok = fetch(url), True
    except Exception:
        details, ok = {}, False
    _prune()
    _write(name, {'ts': time.time(), 'ok': ok, 'details': details})
    if ok and module == 'keshet' and any(details.values()):
        _remember(key, details)
    return details


def _answer(home, slot, key, details):
    for field in ('plot', 'fanart', 'logo'):
        home.setProperty('povil.details.%s%s' % (slot, field), details.get(field) or '')
    home.setProperty('povil.details.%sfor' % slot, key)


def run():
    home = xbmcgui.Window(10000)
    key = home.getProperty('povil.details.key')
    if not key:
        return
    near = [k for k in home.getProperty('povil.details.near').split() if k != key][:NEAR]
    details = lookup(key)
    if home.getProperty('povil.details.key') != key:
        return      # the skin moved on: kept for a revisit, the newer item's own run answers
    _answer(home, '', key, details)
    for slot, other in enumerate(near, 1):
        details = lookup(other)
        if home.getProperty('povil.details.key') != key:
            return
        _answer(home, '%d.' % slot, other, details)


def warm():
    """Kan's list before the user reaches its row (mode=hero_warm)."""
    _kan_wide()
