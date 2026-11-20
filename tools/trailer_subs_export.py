"""Run by .github/workflows/trailer-subs.yml: the trailer subtitles translated since the last run, from the subtitle
pool's Worker into a folder of the trailer-subs branch, which deploy-pages.yml serves at tsubs/ on GitHub Pages.

    python3 tools/trailer_subs_export.py <the trailer-subs checkout> <MoranSubs' pool.py>

Hebrew subtitles for the home's trailers (the owner, Nov 2026): MoranSubs translates a trailer once, with the viewer's
own free Gemini quota, and uploads it to the Worker; every device then READS it here, from GitHub Pages, so trailer
views cost the Worker nothing (it stays far inside Cloudflare's free plan however many watch). The Worker hands the
export only to this repository's own workflow, by GitHub's OIDC token (audience povil-tsubs): no shared secret.

The branch holds one small file per trailer, written once and never changed (git keeps only what is new):
    <sha1(video id)[:2]>/<sha1(video id)[:16]>.json   {"c": [[start_ms, end_ms, text], ...], "s", "m", "n", "y", "ts"}
(the hash, not the id: YouTube ids differ by letter case, which a case-blind file system would merge) and
state.json, the last row exported. A trailer translated twice keeps its first file.

A translation the owner withdrew (the Worker's /tsub/ban page): the export lists every withdrawn trailer ("drop");
their files are deleted here and drop.json ({"drop": [video ids]}) tells the devices to delete their own copies and
never translate those trailers again.
"""
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request

AUDIENCE = 'povil-tsubs'
PAGES, PAGE = 40, 500        # at most 20,000 rows a run (the Worker accepts at most a few thousand a day)


def path_of(video):
    h = hashlib.sha1(video.encode('ascii')).hexdigest()
    return h[:2], h[:16] + '.json'


def worker_url(pool_py):
    """The pool Worker's address, as MoranSubs has it (not written a second time in the repository)."""
    m = re.search(r"^POOL_URL\s*=\s*'(https://[^']+)'", open(pool_py, encoding='utf-8').read(), re.M)
    if not m:
        sys.exit('pool.py: no POOL_URL')
    return m.group(1).rstrip('/')


def oidc_token(env=os.environ, opener=urllib.request.urlopen):
    url = env['ACTIONS_ID_TOKEN_REQUEST_URL'] + '&audience=' + urllib.parse.quote(AUDIENCE)
    req = urllib.request.Request(url, headers={'Authorization': 'bearer ' + env['ACTIONS_ID_TOKEN_REQUEST_TOKEN']})
    with opener(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))['value']


def fetch_page(base, token, after, opener=urllib.request.urlopen):
    req = urllib.request.Request('%s/tsub/export?after=%d&limit=%d' % (base, after, PAGE),
                                 headers={'Authorization': 'Bearer ' + token, 'User-Agent': 'povil-tsubs-export'})
    with opener(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))


def export(folder, fetch):
    """Writes the new rows from fetch(after) into folder and takes the withdrawn ones out;
    returns (files written, files removed + drop.json changed, last seq)."""
    state_path = os.path.join(folder, 'state.json')
    try:
        after = int(json.load(open(state_path, encoding='utf-8')).get('after') or 0)
    except (OSError, ValueError):
        after = 0
    written, drop = 0, None
    for _ in range(PAGES):
        page = fetch(after)
        if drop is None and isinstance(page.get('drop'), list):
            drop = {str(v) for v in page['drop'] if re.match(r'^[A-Za-z0-9_-]{11}$', str(v))}
        rows = page.get('rows') or []
        for row in rows:
            video = str(row.get('v') or '')
            # (past it either way: a row that is not a trailer's is never asked for again)
            after = max(after, int(row.get('seq') or 0))
            if not re.match(r'^[A-Za-z0-9_-]{11}$', video) or video in (drop or ()):
                continue
            sub, name = path_of(video)
            target = os.path.join(folder, sub, name)
            if not os.path.exists(target):
                os.makedirs(os.path.join(folder, sub), exist_ok=True)
                data = {k: row[k] for k in ('c', 's', 'm', 'n', 'y', 'ts') if k in row}
                with open(target, 'w', encoding='utf-8', newline='\n') as f:
                    json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
                written += 1
            after = max(after, int(row.get('seq') or 0))
        if not rows or not page.get('more'):
            break
    removed = 0 if drop is None else withdraw(folder, drop)
    with open(state_path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'after': after}, f)
    return written, removed, after


def withdraw(folder, drop):
    """Deletes the withdrawn trailers' files and writes drop.json; returns how much changed."""
    changed = 0
    for video in drop:
        sub, name = path_of(video)
        try:
            os.remove(os.path.join(folder, sub, name))
            changed += 1
        except OSError:
            pass
    path = os.path.join(folder, 'drop.json')
    data = {'drop': sorted(drop)}
    try:
        old = json.load(open(path, encoding='utf-8'))
    except (OSError, ValueError):
        old = None if drop else data         # (no file and nothing withdrawn: none is needed)
    if old != data:
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(data, f, separators=(',', ':'))
        changed += 1
    return changed


def main(folder, pool_py):
    base, token = worker_url(pool_py), oidc_token()
    written, removed, after = export(folder, lambda a: fetch_page(base, token, a))
    print('trailer subtitles: %d new, %d withdrawn, exported up to row %d' % (written, removed, after))
    # the workflow reads the count from here (anything changed: Pages is published again)
    with open(os.environ.get('GITHUB_OUTPUT', os.devnull), 'a', encoding='utf-8') as f:
        f.write('changed=%d\n' % (written + removed))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
