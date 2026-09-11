"""Portable scraper tests: current stock when supplied, verbatim method fixtures otherwise.
Fixtures contain real upstream methods; provider modules are explicit inert test doubles.
"""
from pathlib import Path
import os, tempfile, atexit, shutil

def pov_tree(version):
    if version == '6903':
        stock = Path(os.environ.get('POV_STOCK', '__not_supplied__'))
        if (stock / 'resources/lib/modules/sources.py').is_file():
            print('Using POV_STOCK:', stock)
            return str(stock)
        if os.environ.get('PATCHER_REQUIRE_STOCK') == '1':
            raise AssertionError('POV_STOCK is required for current-host integration')
    root = Path(tempfile.mkdtemp(prefix='pov-method-fixture-'))
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    target = root / 'resources/lib/modules/sources.py'
    target.parent.mkdir(parents=True)
    target.write_bytes((Path(__file__).parent / 'fixtures' / ('pov_scrapers_' + version + '.py')).read_bytes())
    providers = root / 'resources/lib' / ('scrapers' if version == '6813' else 'debrids')
    providers.mkdir()
    for name in ('rd_cloud', 'tb_cloud', 'aiostreams', 'easynews'):
        (providers / (name + '.py')).write_text('source = None\n', encoding='utf-8')
    print('Using verbatim POV', version, 'method fixture with synthetic provider modules')
    return str(root)


def historical_pov_source(relative):
    """Read the shipped 6.08.13 baseline for historical byte-slice assertions."""
    import zipfile
    archive = Path(__file__).resolve().parents[1] / 'dist/Kodi-POV-IL-FENtastic-test-0.1.134.zip'
    with zipfile.ZipFile(archive) as z:
        candidates = [relative, relative.replace('/indexers/', '/debrids/'),
                      relative.replace('realdebrid_api.py', 'real_debrid_api.py')]
        candidates += [c.replace('realdebrid_api.py', 'real_debrid_api.py') for c in candidates]
        for rel in candidates:
            hits = [n for n in z.namelist() if n.endswith('plugin.video.pov/' + rel)]
            if len(hits) == 1:
                return z.read(hits[0]).decode('utf-8-sig')
    raise AssertionError('Historical source missing: ' + relative)
