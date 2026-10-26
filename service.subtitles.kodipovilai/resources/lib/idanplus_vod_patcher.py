# Idan Plus VOD: Kan stopped playing, the Kan archive and i24NEWS English came
# up empty.
#
# Found by browsing and PLAYING every Idan Plus VOD provider inside a real
# Kodi (21.3). Reshet 13, Now 14, Keshet 12, Channel 24, Channel 9, Sport 5,
# Sport 1 and i24NEWS Hebrew all played; these did not, each for a reason on
# the provider's side of the wire:
#
# 1. CLOUDFLARE TURNS KODI AWAY FROM www.kan.org.il. Every page fetch inside
#    Kodi answers 403 -- cloudscraper with a browser User-Agent, the plain
#    `requests` fallback, and Kodi's own libcurl alike -- while the same
#    request shapes from a desktop Python pass. So it is the client
#    fingerprint, not anything a header can fix. The SAME Umbraco site answers
#    on Kan's mobile-API host, mobapi.kan.org.il, which Kodi already reaches
#    for the JSON feeds: an episode page fetched there was byte-identical
#    (126060 bytes) to the www one. GetCF now asks that host first for
#    www.kan.org.il pages, and falls through to the stock path untouched when
#    it gets anything but a 200 that stayed on that host.
#
#    Kids pages (www.kankids.org.il) are NOT served there -- mobapi answers
#    them with a redirect to themselves -- so they keep the stock path, which
#    Kodi does get through. That path could not even send its request: the
#    Referer it builds for a season page carries the Hebrew word for "season"
#    verbatim, and `requests` refuses a non-latin-1 header ("'latin-1' codec
#    can't encode characters"). The Referer is percent-encoded now, exactly as
#    a browser sends it.
#
# 2. KAN MOVED ITS PLAYER. Episode pages no longer carry data-hls-url /
#    data-dash-url / data-entryId; the stream now sits in a JSON block,
#
#        <script type="application/json" data-redge-config="redge-player-ID">
#            {..., "file": {"dash": "//r.il.cdn-redge.media/.../Manifest.ism",
#                           "hls":  "//r.il.cdn-redge.media/.../playlist.m3u8?fmp4"}}
#
#    so even a page that did load resolved to nothing. The Kaltura links the
#    mobile API still lists are dead (404 on every one sampled), and kids
#    entries there have an empty src, so the page is the only source left.
#    The resolver reads that block right where it used to read the old
#    attributes -- but only the config whose id IS the episode's id (on all
#    21 sampled pages there was exactly one, and it was), so a teaser or a
#    promo player on the page can never stand in for the episode; without
#    a match the stock path, YouTube included, carries on as before.
#
# 3. THE KAN ARCHIVE LOBBY WAS REDESIGNED. The "vod-section" grid the archive
#    menu parsed is gone, so the menu died on an IndexError and showed
#    nothing. The lobby now lists programs as cards carrying
#    data-item-type="program"; those are listed as ordinary Kan programs,
#    whose episodes come from the mobile API like every other program's.
#
#    Two program lists came up empty on IndexError/AttributeError, so the
#    whole program looked missing: one mobile-API episode with a null title
#    (Idan Plus calls .strip() on it) takes every sibling down with it -- the
#    title falls back to the episode title Kan reports in the analytics
#    block -- and a program the mobile API lists NO episodes for falls back
#    to page parsers written for the old layout. Program pages now list
#    their episodes as "cr-item" cards (link, aria-label title, image); those
#    are read when, and only when, the API had nothing.
#
# 4. i24NEWS ENGLISH LOST ITS API HOST. api.i24news.wiztivi.io no longer
#    resolves. Hebrew had already been moved to the Univtec API that
#    video.i24news.tv uses; English lives there too, as region "all" with its
#    own "Shows" section. Series and episode pages there answer the same in
#    either region, so only the catalog needs the English section.
#
# Each injected line carries the marker; a later version reverts its own
# lines first and re-applies. The anchors are Idan Plus 4.0.2's text verbatim
# (the version the build installs from the Fishenzon repo). Every fix is safe
# without the others and is applied on its own; one whose function has
# changed stands down and is reported, and the rest still land.
#
# IDAN PLUS 4.0.3 (26 Oct 2026) READS KAN'S PLAYER ITSELF. Its PageStream reads
# the same settings block as fix 2, a few lines after the one that records
# where the credits start -- the time its new next-episode card waits for.
# Fix 2 sits right after the page fetch, above that line, and returned before
# it, so the card fell back to its default time. On an
# Idan Plus that has PageStream, fix 2 is left to Idan Plus; the others (the
# GetCF mirror its other Kan pages still use, the archive lobby, the null
# title, i24NEWS English) are not in 4.0.3 and still apply. v2 takes back a
# v1 fix 2 that already landed on 4.0.3.

import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

try:
    from resources.lib import kodi_utils
except Exception:
    kodi_utils = None


IDANPLUS_ADDON_ID = 'plugin.video.idanplus'
COMMON_REL = 'resources/lib/common.py'
KAN_REL = 'resources/lib/kan.py'
I24_REL = 'resources/lib/i24news.py'

MARKER = '# AI_SUBS_IDAN_VOD_v2'
# Prefix, never an enumerated list of predecessors.
_MARKER_ANY = '# AI_SUBS_IDAN_VOD_v'

# --- common.py: mirror host first, ASCII Referer -------------------------
_GETCF_HEAD = ("def GetCF(url, ua=None, retries=8, responseMethod='text', "
               "referer=None):\n")
_REFERER = "\tbrowseReferer = referer or home\n"

# No blank lines inside any injection: _revert keeps a blank line that ends a
# block, so a blank here would survive every upgrade and pile up.
_COMMON_HELPER = (
    "def _aiKanAscii(u):  " + MARKER + "\n"
    "\ttry:\n"
    "\t\tfrom requests.utils import requote_uri\n"
    "\t\treturn requote_uri(u)\n"
    "\texcept Exception:\n"
    "\t\treturn u\n"
    "def _aiKanMirror(url, ua, responseMethod):  " + MARKER + "\n"
    "\tif responseMethod not in ('text', 'json'):\n"
    "\t\treturn None\n"
    "\tmatch = re.match(r'https?://www\\.kan\\.org\\.il(/[^#]*)?$', url or '')\n"
    "\tif not match:\n"
    "\t\treturn None\n"
    "\ttry:\n"
    "\t\timport requests\n"
    "\t\tsession = requests.Session()\n"
    "\t\tsession.max_redirects = 4\n"
    "\t\tresponse = session.get('https://mobapi.kan.org.il' + "
    "_aiKanAscii(match.group(1) or '/'), headers={'User-Agent': ua, "
    "'Accept-Encoding': 'gzip'}, timeout=(6, 20))\n"
    "\t\tif response.status_code != 200 or not response.text or not "
    "response.url.startswith('https://mobapi.kan.org.il/'):\n"
    "\t\t\treturn None\n"
    "\t\treturn response.json() if responseMethod == 'json' else "
    "response.text\n"
    "\texcept Exception:\n"
    "\t\treturn None\n"
)
_COMMON_CALL = (
    "\tbrowseReferer = _aiKanAscii(browseReferer)  " + MARKER + "\n"
    "\t_aiPage = _aiKanMirror(url, ua, responseMethod)  " + MARKER + "\n"
    "\tif _aiPage is not None: return _aiPage  " + MARKER + "\n"
)

# --- kan.py: read the Redge player config -------------------------------
_KAN_PAGE = "    text = _getKanPage(url, fresh=True)\n"
_KAN_FIX = (
    "    if text and 'data-redge-config' in text:  " + MARKER + "\n"
    "        _aiOwn = (re.findall(r'/(\\d+)/?(?:\\?|$)', url) or [''])[-1]\n"
    "        for _aiCfg in re.findall(r'<script[^>]*data-redge-config[^>]*>"
    "(.*?)</script>', text, re.S):\n"
    "            try:\n"
    "                _aiCfg = json.loads(_aiCfg)\n"
    "                _aiFile = _aiCfg.get('file') or {}\n"
    "                _aiLink = (_aiFile.get('hls') or _aiFile.get('dash') "
    "or '').strip()\n"
    "            except Exception:\n"
    "                continue\n"
    "            if _aiLink and (not _aiOwn or str(_aiCfg.get('id')) == "
    "_aiOwn):\n"
    "                return _pipe_headers(_aiLink, userAgent, url)\n"
)

# --- kan.py: list the redesigned archive lobby --------------------------
_ARCHIVE_HEAD = (
    "def GetArchiveCategoriesList(url, iconimage, catName):\n"
    "    text = common.GetCF(url, userAgent)\n"
    "    #text = common.OpenURL(url)\n"
    "    domain = baseKidsUrl if 'kankids' in url else baseUrl\n"
    "    links = []\n"
    "    matches = re.compile('<main id=\"main\"(.*)</main>', re.S)"
    ".findall(text)\n"
    "    if len(matches) < 1:\n"
    "        return\n"
)
_ARCHIVE_FIX = (
    "    if '<div class=\"vod-section' not in matches[0]:  " + MARKER + "\n"
    "        for _aiLink, _aiName, _aiImage in re.findall(r'<a [^>]*href=\""
    "([^\"]+)\"[^>]*data-item-type=\"program\"[^>]*aria-label=\"([^\"]*)"
    "\"[^>]*>(?:(?!</a>).)*?<img src=\"([^\"]+)\"', matches[0], re.S):\n"
    "            if not _aiLink.startswith('http'):\n"
    "                _aiLink = '{0}{1}'.format(domain, _aiLink)\n"
    "            if _aiLink in links:\n"
    "                continue\n"
    "            links += [_aiLink]\n"
    "            _aiName = common.UnEscapeXML(_aiName)\n"
    "            try:\n"
    "                _aiImage = GetImageLink(common.quoteNonASCII("
    "common.UnEscapeXML(_aiImage)), _aiName)\n"
    "            except Exception:\n"
    "                _aiImage = iconimage\n"
    "            _aiName = common.GetLabelColor(_aiName, keyColor=\"prColor\", "
    "bold=True)\n"
    "            common.addDir(_aiName, _aiLink, 2, _aiImage, infos={\"title\": "
    "_aiName, \"plot\": _aiName}, module=module, "
    "moreData='kan|||{0}'.format(catName), urlParamsData={'catName': "
    "catName})\n"
    "        return\n"
)

# --- kan.py: a mobile-API episode without a title -----------------------
_MOB_LOOP = (
    "    for entry in entries:\n"
    "        if season_filter and _mobEpisodeSeason(entry) != season_filter:\n"
)
_MOB_LOOP_FIX = (
    "    entries = [dict(e, title=e.get('title') or ((e.get('extensions') or "
    "{}).get('analyticsCustomProperties') or {}).get('episode_title') or '') "
    "for e in entries]  " + MARKER + "\n"
)

# --- kan.py: episode cards when the mobile API has none -----------------
_EPISODES_PAGE = (
    "    #text = common.GetCF(url)\n"
    "    text = cache.get(common.GetCF, 24, url, table='pages')\n"
    "    if text==[]:\n"
    "        text = cache.get(common.GetCF, 0, url, table='pages')\n"
    "    if not text:\n"
    "        return\n"
)
_EPISODES_PAGE_FIX = (
    "    if programId and 'cr-item' in text:  " + MARKER + "\n"
    "        _aiSeen = []\n"
    "        for _aiLink, _aiName, _aiImage in re.findall(r'<a class=\"cr-item"
    "[^\"]*\"\\s+href=\"([^\"]*/p-' + programId + r'/(?:[^\"/]+/)*\\d+/?)\""
    "\\s+aria-label=\"([^\"]*)\"(?:(?!</a>).)*?<img src=\"([^\"]+)\"', "
    "text, re.S):\n"
    "            if not _aiLink.startswith('http'):\n"
    "                _aiLink = (baseKidsUrl if 'kankids' in url else baseUrl) "
    "+ _aiLink\n"
    "            if _aiLink in _aiSeen or (seasonFilter and '/s{0}/'.format("
    "seasonFilter) not in _aiLink):\n"
    "                continue\n"
    "            _aiSeen.append(_aiLink)\n"
    "            _aiName = common.UnEscapeXML(_aiName.strip())\n"
    "            try:\n"
    "                _aiImage = GetImageLink(common.quoteNonASCII("
    "common.UnEscapeXML(_aiImage)), _aiName)\n"
    "            except Exception:\n"
    "                _aiImage = iconimage\n"
    "            _aiName = common.GetLabelColor(_aiName, keyColor=\"chColor\")\n"
    "            common.addDir(_aiName, _aiLink, 3, _aiImage, infos={\"title\": "
    "_aiName, \"plot\": _aiName}, module=module, moreData=bitrate, "
    "isFolder=False, isPlayable=True, urlParamsData={'catName': catName})\n"
    "        if _aiSeen:\n"
    "            return\n"
)

# --- i24news.py: the English catalog on the Univtec API -----------------
_I24_UNIVTEC_HEAD = (
    "def ShowCatalogUnivtec(language='he'):\n"
    "    \"\"\"Display Hebrew TV shows from the current i24NEWS website "
    "API.\"\"\"\n"
)
_I24_UNIVTEC_FIX = (
    "    if language == 'en':  " + MARKER + "\n"
    "        _aiData = GetUnivtecData('pages/section/6a15800ed7dd65c210d2d0c1', "
    "{'page': 1, 'limit': 100}, region='all')\n"
    "        _aiShows = [s for s in ((_aiData or {}).get('items') or []) "
    "if s.get('id')]\n"
    "        for _aiShow in _aiShows:\n"
    "            _aiTitle = _aiShow.get('title') or _aiShow.get('name') or "
    "'Unknown'\n"
    "            common.addDir(name=common.GetLabelColor(_aiTitle, "
    "keyColor=\"prColor\", bold=True), url='action=seasons_univtec&series_id="
    "{0}&show_name={1}'.format(_aiShow['id'], common.quote_plus(_aiTitle)), "
    "mode=-1, iconimage=GetUnivtecImage(_aiShow, moduleIcon), "
    "infos={'Title': _aiTitle, 'Plot': _aiShow.get('description') or ''}, "
    "module=module, isFolder=True)\n"
    "        return bool(_aiShows)\n"
)
_I24_CATALOG = "    if language == 'he' and ShowCatalogUnivtec(language):\n"
_I24_CATALOG_FIX = (
    "    if language == 'en' and ShowCatalogUnivtec(language): return  "
    + MARKER + "\n"
)


def _log(msg, level='INFO'):
    if kodi_utils is None:
        return
    try:
        kodi_utils.log('idanplus_vod_patcher: ' + msg, level=level)
    except Exception:
        pass


def _fitter(content):
    eol = '\r\n' if '\r\n' in content else '\n'
    return (lambda t: t.replace('\n', eol)) if eol != '\n' else (lambda t: t), eol


def _revert(content, eol='\n'):
    """Delete a previous version's injected lines.

    A marked line plus everything indented strictly deeper below it: a helper
    function's body, a block's body, or nothing for a single marked line.
    """
    lines = content.split(eol)
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if _MARKER_ANY not in line:
            out.append(line)
            i += 1
            continue
        base = len(line) - len(line.lstrip())
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if nxt.strip():
                if (len(nxt) - len(nxt.lstrip())) <= base:
                    break
                i += 1
                continue
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            if (j >= len(lines)
                    or (len(lines[j]) - len(lines[j].lstrip())) <= base):
                break
            i = j
    return eol.join(out)


def _idan_path(rel):
    if xbmcvfs is None:
        return ''
    try:
        base = xbmcvfs.translatePath(
            'special://home/addons/' + IDANPLUS_ADDON_ID + '/')
    except Exception:
        return ''
    p = os.path.join(base, *rel.split('/'))
    return p if os.path.isfile(p) else ''


def _insert(content, fit, groups):
    """Apply groups of (anchor, text, before) edits.

    A group is all-or-nothing -- its edits depend on each other -- but groups
    are independent: if Idan Plus rewrites one function (say, fixes its own
    null-title crash), that group stands down and the others still land, so
    the fix that makes Kan play at all is never lost to an unrelated change.
    Returns (content or None when no group applied, groups skipped).
    """
    applied, skipped = 0, 0
    for group in groups:
        edits = [(fit(a), fit(t), before) for a, t, before in group]
        if any(content.count(a) != 1 for a, _t, _b in edits):
            skipped += 1
            continue
        for anchor, text, before in edits:
            content = content.replace(
                anchor, (text + anchor) if before else (anchor + text), 1)
        applied += 1
    return (content if applied else None), skipped


def _patch_common(content, fit):
    # The call lines use the helpers, so the two edits are one group -- and
    # only valid with the Referer line inside GetCF, i.e. after its head.
    head, referer = fit(_GETCF_HEAD), fit(_REFERER)
    if content.find(referer) < content.find(head):
        return None, 1
    return _insert(content, fit, (((_GETCF_HEAD, _COMMON_HELPER, True),
                                   (_REFERER, _COMMON_CALL, False)),))


# Idan Plus's own reader of the player settings (4.0.3+): fix 2 stays out.
_KAN_OWN_PLAYER = 'def PageStream('


def _patch_kan(content, fit):
    groups = (((_ARCHIVE_HEAD, _ARCHIVE_FIX, False),),
              ((_MOB_LOOP, _MOB_LOOP_FIX, True),),
              ((_EPISODES_PAGE, _EPISODES_PAGE_FIX, False),))
    if _KAN_OWN_PLAYER not in content:
        groups = (((_KAN_PAGE, _KAN_FIX, False),),) + groups
    return _insert(content, fit, groups)


def _patch_i24(content, fit):
    return _insert(content, fit, (((_I24_UNIVTEC_HEAD, _I24_UNIVTEC_FIX, False),
                                   (_I24_CATALOG, _I24_CATALOG_FIX, True)),))


_FILES = ((COMMON_REL, _patch_common), (KAN_REL, _patch_kan),
          (I24_REL, _patch_i24))


def _ensure_file(rel, patch):
    path = _idan_path(rel)
    if not path:
        return 'no_file'
    try:
        with open(path, encoding='utf-8', newline='') as f:
            content = f.read()
    except Exception as e:
        _log('{0}: read failed: {1}'.format(rel, e), level='WARNING')
        return 'read_failed'

    fit, eol = _fitter(content)
    if MARKER in content:
        return 'unchanged'

    repatch = False
    if _MARKER_ANY in content:
        content = _revert(content, eol)
        repatch = True
        if _MARKER_ANY in content:
            _log('{0}: could not remove an older injection'.format(rel),
                 level='WARNING')
            return 'revert_failed'

    new_content, skipped = patch(content, fit)
    if new_content is None:
        _log('{0} no longer has the shape this fix was written for; nothing '
             'was changed there.'.format(rel), level='WARNING')
        return 'unmatched'
    if skipped:
        _log('{0}: {1} fix(es) found a changed function and stood down; the '
             'rest were applied.'.format(rel, skipped), level='WARNING')

    try:
        # A leading U+FEFF is fine for import and fatal for compile().
        compile(new_content.lstrip('\ufeff'), path, 'exec')
    except SyntaxError as e:
        _log('{0}: compile check failed, not writing: {1}'.format(rel, e),
             level='WARNING')
        return 'compile_failed'

    tmp = path + '.aitmp'
    try:
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            f.write(new_content)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        _log('{0}: write failed: {1}'.format(rel, e), level='WARNING')
        return 'write_failed'

    stem = os.path.basename(path).split('.')[0] + '.'
    pycache = os.path.join(os.path.dirname(path), '__pycache__')
    if os.path.isdir(pycache):
        for fn in os.listdir(pycache):
            if fn.startswith(stem) and fn.endswith('.pyc'):
                try:
                    os.remove(os.path.join(pycache, fn))
                except OSError:
                    pass
    return 'repatched' if repatch else 'patched'


_FAILURES = ('read_failed', 'revert_failed', 'unmatched', 'compile_failed',
             'write_failed')


def ensure_patched():
    """Idempotent. Never raises. Returns 'no_idanplus' | 'no_file' |
    'unchanged' | 'patched' | 'repatched' | 'unmatched' | 'read_failed' |
    'write_failed' | 'compile_failed' | 'revert_failed' -- the worst outcome
    across the three files."""
    if xbmcvfs is None:
        return 'no_idanplus'
    results = []
    for rel, patch in _FILES:
        try:
            results.append(_ensure_file(rel, patch))
        except Exception as e:
            _log('{0}: failed: {1}'.format(rel, e), level='WARNING')
            results.append('write_failed')
    for status in _FAILURES:
        if status in results:
            return status
    if 'no_file' in results:
        return 'no_file'
    if 'repatched' in results:
        status = 'repatched'
    elif 'patched' in results:
        status = 'patched'
    else:
        return 'unchanged'
    _log('Kan pages load through the mobile-API host, Kan\'s archive lobby '
         'is read (and its new player, where Idan Plus does not read it '
         'itself), and i24NEWS English has its catalog')
    return status
