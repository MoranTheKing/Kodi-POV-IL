"""Report upstream add-on releases the build's patches were not verified on.

Usage: python3 tools/check_upstream_addons.py [UPSTREAM_VERSIONS.txt]

The content add-ons below update themselves on users' devices straight from
their developers' repositories (the wizard registers each to its repository
so Kodi offers the update), and the build patches several of them at
startup. A new upstream version is therefore the moment to re-run the
patchers against it -- before devices find a moved anchor. This prints one
line per watched add-on whose newest published version differs from the
marker file:

    plugin.video.pov: 6.10.05 -> 6.10.06

and nothing when all match. A repository that cannot be read is reported
on stderr and skipped; it never fails the check.
"""
import re
import sys
import urllib.request

# (addon id, repository indexes that publish it -- the newest version wins,
# as it does in Kodi)
WATCH = (
    ('plugin.video.pov', (
        'https://kodifitzwell.github.io/repo/packages/addons.xml',
        'https://kodiyashimaru.github.io/repo/packages/addons.xml')),
    ('plugin.video.idanplus', (
        'https://raw.githubusercontent.com/fishenzon/repo/master/addons.xml',)),
    ('skin.arctic.fuse.3', (
        'https://raw.githubusercontent.com/jurialmunkey/repository.jurialmunkey'
        '/master/omega/zips/addons.xml',
        'https://raw.githubusercontent.com/jurialmunkey/repository.jurialmunkey'
        '/master/repo/zips/addons.xml')),
    ('plugin.video.umbrella', (
        'https://raw.githubusercontent.com/umbrellaplug/umbrellaplug.github.io'
        '/master/omega/zips/addons.xml',)),
    ('plugin.video.otaku', (
        'https://raw.githubusercontent.com/Goldenfreddy0703/repository.otaku'
        '/master/repo/zips/addons.xml',)),
    ('script.module.acctmgr', (
        'https://raw.githubusercontent.com/Zaxxon709/zaxxon/main/zips/addons.xml',)),
)

_ADDON = re.compile(r'<addon\b[^>]*>', re.S)
_ATTR = re.compile(r'\b(id|version)\s*=\s*"([^"]*)"')


def version_key(version):
    """Kodi-like ordering: numeric parts compared as numbers."""
    parts = re.split(r'[.\-+~]', version or '')
    return [(0, int(p)) if p.isdigit() else (1, p) for p in parts]


def versions_in(index_xml):
    """{addon id: newest version} from one repository addons.xml."""
    found = {}
    for tag in _ADDON.findall(index_xml or ''):
        attrs = dict(_ATTR.findall(tag))
        aid, ver = attrs.get('id'), attrs.get('version')
        if aid and ver and (aid not in found
                            or version_key(ver) > version_key(found[aid])):
            found[aid] = ver
    return found


def read_marker(text):
    marker = {}
    for line in (text or '').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or ':' not in line:
            continue
        aid, ver = line.split(':', 1)
        marker[aid.strip()] = ver.strip()
    return marker


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': 'kodi-povil-upstream-check'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', 'replace')


def upstream_versions(fetcher=fetch, warn=None):
    cache, newest = {}, {}
    for aid, urls in WATCH:
        for url in urls:
            if url not in cache:
                try:
                    cache[url] = versions_in(fetcher(url))
                except Exception as exc:
                    cache[url] = {}
                    if warn:
                        warn('could not read {0}: {1}'.format(url, exc))
            ver = cache[url].get(aid)
            if ver and (aid not in newest
                        or version_key(ver) > version_key(newest[aid])):
                newest[aid] = ver
    return newest


def changes(marker, newest):
    return ['{0}: {1} -> {2}'.format(aid, marker.get(aid, '?'), newest[aid])
            for aid, _urls in WATCH
            if aid in newest and newest[aid] != marker.get(aid)]


def main(argv):
    path = argv[1] if len(argv) > 1 else 'UPSTREAM_VERSIONS.txt'
    with open(path, encoding='utf-8') as handle:
        marker = read_marker(handle.read())
    for line in changes(marker, upstream_versions(
            warn=lambda m: sys.stderr.write(m + '\n'))):
        print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
