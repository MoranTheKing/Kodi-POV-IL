"""Everything this build does to a skin, in one place, so a port can prove it kept it.

WHY THIS EXISTS. The question "how hard is it to move the build to another
video add-on / another Kodi" cannot be answered from the patcher list alone,
because most of what makes this build look like itself is not in a patcher at
all -- it is Hebrew menu XML, home-screen layouts, and several hundred
plugin:// paths that name the video add-on directly. Those do not announce
themselves, and anything not on a list does not get ported.

WHAT IT REPORTS, per skin:

  HOW IT ARRIVES   shipped in the build / an overlay we drop into somebody
                   else's skin / patched only if the user installs it.
                   These are three different porting costs and conflating them
                   is how "we support four skins" turns into a surprise.
  OUR FILES        the XML this build owns, with line counts, how much of it
                   is Hebrew, and how many plugin:// paths it hard-codes.
  OUR PATCHERS     every module that edits that skin, and the file it edits.
  REPOINTING       plugin:// references by target add-on. This is the number
                   that matters for a video-add-on swap: each one is a tile,
                   a widget or a menu entry that would point at nothing.

Run: python3 tools/skin_customisation_inventory.py [--build <zip>] [--json]
"""
import ast
import io
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
ADDON = os.path.join(ROOT, 'addons', 'service.subtitles.kodipovilai')
LIB = os.path.join(ADDON, 'resources', 'lib')

# The add-on a video-add-on swap would replace. Everything else named in a
# tile stays exactly where it is, and flagging that difference is the whole
# point of counting them separately.
SWAP_TARGET = 'plugin.video.pov'

HEB = re.compile('[֐-׿]')
PLUGIN = re.compile(r'plugin://(plugin\.[A-Za-z0-9._]+)')
SKIN_CONST = re.compile(
    r"(?m)^[A-Z][A-Z0-9_]*\s*=\s*'(skin\.[A-Za-z0-9._]+)'")
SKIN_ANY = re.compile(r"skin\.[a-z0-9]+(?:\.[a-z0-9]+)*")
# A path constant next to a skin constant is the file that skin gets edited in.
REL_CONST = re.compile(
    r"(?m)^[A-Z][A-Z0-9_]*\s*=\s*'([^']*\.(?:xml|py|po))'")


def skins_of(src):
    """Skins a module targets. Declared constants first; they are the truth.

    Falling back to any mention catches the modules that switch on the ACTIVE
    skin instead of declaring one -- search_provider, pov_seasons_view_seed --
    which really do customise several skins and would otherwise be invisible.
    """
    declared = set(SKIN_CONST.findall(src))
    if declared:
        return declared, True
    return {s for s in SKIN_ANY.findall(src) if s.count('.') >= 2}, False


def patcher_map():
    out = {}
    for name in sorted(os.listdir(LIB)):
        if not name.endswith('.py'):
            continue
        try:
            src = io.open(os.path.join(LIB, name), encoding='utf-8').read()
        except Exception:
            continue
        skins, declared = skins_of(src)
        if not skins:
            continue
        files = sorted(set(REL_CONST.findall(src)))
        for s in skins:
            out.setdefault(s, []).append(
                {'patcher': name[:-3], 'declared': declared, 'files': files})
    return out


def xml_facts(text):
    lines = text.split('\n')
    heb = [l for l in lines if HEB.search(l)]
    plugins = {}
    for p in PLUGIN.findall(text):
        plugins[p] = plugins.get(p, 0) + 1
    return {'lines': len(lines), 'hebrew_lines': len(heb),
            'plugins': plugins,
            'hebrew_samples': [l.strip()[:60] for l in heb[:5]]}


def build_files(build_zip):
    """Per-skin files the BUILD ships, and which of them this repo owns."""
    if not build_zip or not os.path.isfile(build_zip):
        return {}, set()
    zf = zipfile.ZipFile(build_zip)
    per = {}
    present = set()
    for n in zf.namelist():
        m = re.match(r'^addons/(skin\.[^/]+)/(.*)$', n)
        if not m or n.endswith('/'):
            continue
        skin, rel = m.group(1), m.group(2)
        present.add(skin)
        per.setdefault(skin, []).append((rel, zf.getinfo(n).file_size, n))
    return per, present


def main():
    build = None
    as_json = '--json' in sys.argv
    if '--build' in sys.argv:
        build = sys.argv[sys.argv.index('--build') + 1]
    else:
        d = os.path.join(ROOT, 'dist')
        cands = sorted(
            (f for f in os.listdir(d) if re.match(
                r'Kodi-POV-IL-FENtastic-test-\d+\.\d+\.\d+\.zip$', f)),
            key=lambda f: [int(x) for x in re.findall(r'\d+', f)])
        build = os.path.join(d, cands[-1]) if cands else None

    pm = patcher_map()
    shipped, present = build_files(build)
    zf = zipfile.ZipFile(build) if build else None

    skins = sorted(set(pm) | set(shipped))
    report = {}
    for s in skins:
        files = shipped.get(s, [])
        has_addon_xml = any(rel == 'addon.xml' for rel, _sz, _n in files)
        if files and has_addon_xml:
            arrival = 'SHIPPED IN THE BUILD'
        elif files:
            arrival = 'OVERLAY -- our XML dropped into somebody else\'s skin'
        else:
            arrival = 'ON DEMAND -- patched only if the user installs it'
        entry = {'arrival': arrival, 'our_files': [], 'patchers': [],
                 'repoint': {}}
        # A SHIPPED SKIN IS NOT AN UNTOUCHED SKIN, and skipping those was the
        # first version's worst omission: skin.fentastic ships 1240 files, of
        # which 29 carry Hebrew -- a 220-line strings.po, 149 Hebrew lines in
        # Variables.xml, three VideoOsd includes -- plus ten files naming the
        # video add-on. All of that is ours and all of it has to survive a
        # port. Reporting only the two Nox overlays made the job look an order
        # of magnitude smaller than it is.
        for rel, sz, full in sorted(files):
            if not rel.endswith(('.xml', '.po')):
                continue
            try:
                text = zf.read(full).decode('utf-8', 'replace')
            except Exception:
                continue
            f = xml_facts(text)
            if not (f['hebrew_lines'] or f['plugins']
                    or 'KODI POV IL' in text or 'AI_SUBS' in text):
                continue
            f['file'] = rel
            f['bytes'] = sz
            f['marked'] = 'KODI POV IL' in text or 'AI_SUBS' in text
            entry['our_files'].append(f)
            for k, v in f['plugins'].items():
                entry['repoint'][k] = entry['repoint'].get(k, 0) + v
        for p in sorted(pm.get(s, []), key=lambda d: d['patcher']):
            entry['patchers'].append(p)
        report[s] = entry

    if as_json:
        print(json.dumps(report, indent=1, ensure_ascii=False))
        return

    print('Skin customisation inventory')
    print('build: %s' % (os.path.basename(build) if build else '(none found)'))
    print()
    for s in skins:
        e = report[s]
        print('=' * 74)
        print('%s' % s)
        print('  %s' % e['arrival'])
        if e['our_files']:
            hb = sum(f['hebrew_lines'] for f in e['our_files'])
            print('  FILES CARRYING OUR WORK: %d  (%d Hebrew lines in total)'
                  % (len(e['our_files']), hb))
            for f in sorted(e['our_files'],
                            key=lambda f: -f['hebrew_lines'])[:12]:
                pv = sum(f['plugins'].values())
                print('    %-44s %5d lines, %4d Hebrew%s%s'
                      % (f['file'], f['lines'], f['hebrew_lines'],
                         ', %d plugin paths' % pv if pv else '',
                         '  [marked ours]' if f.get('marked') else ''))
            if len(e['our_files']) > 12:
                print('    ... and %d more' % (len(e['our_files']) - 12))
        if e['repoint']:
            print('  PLUGIN TARGETS NAMED IN THOSE FILES:')
            for k, v in sorted(e['repoint'].items(), key=lambda kv: -kv[1]):
                # Only the video add-on being replaced has to move. Saying so
                # here stops the total reading as if every one were work.
                flag = '  <-- REPOINT on a video-add-on swap' if k == SWAP_TARGET else ''
                print('    %-38s %4d%s' % (k, v, flag))
        if e['patchers']:
            print('  OUR PATCHERS (%d):' % len(e['patchers']))
            for p in e['patchers']:
                tag = '' if p['declared'] else '   [by active skin, not declared]'
                print('    %-42s %s%s'
                      % (p['patcher'], ', '.join(p['files'][:2]) or '-', tag))
    print('=' * 74)
    tot_files = sum(len(e['our_files']) for e in report.values())
    tot_heb = sum(f['hebrew_lines'] for e in report.values()
                  for f in e['our_files'])
    tot_swap = sum(e['repoint'].get(SWAP_TARGET, 0) for e in report.values())
    print('%d skins, %d patcher bindings, %d files carrying our work, '
          '%d Hebrew lines' % (len(skins),
                               sum(len(e['patchers']) for e in report.values()),
                               tot_files, tot_heb))
    print('%d references to %s across those files would need repointing.'
          % (tot_swap, SWAP_TARGET))


if __name__ == '__main__':
    main()
