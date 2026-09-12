"""Blind evaluation counts regressions and refuses incomplete ratings."""
import tempfile
import csv
import json
from pathlib import Path
from evaluate_translation_quality import prepare, score

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    rows = [dict(id=str(i), scene='Original synthetic scene', source='Source',
                 baseline='Old ' + str(i), candidate='New ' + str(i)) for i in range(3)]
    assert prepare(rows, root, 627) == 3
    key = json.loads((root / 'review_key.json').read_text())
    with (root / 'blind_review.csv').open(encoding='utf-8-sig', newline='') as f:
        blind = list(csv.DictReader(f))
    assert all(row[key[row['id']]] == 'New ' + row['id'] for row in blind)
    for row in blind:
        c, b = {'0': (0, 5), '1': (5, 0), '2': (1, 1)}[row['id']]
        row['errors_A'], row['errors_B'] = (c, b) if key[row['id']] == 'A' else (b, c)
    result = score(blind, key)
    assert result['net_error_points_removed'] == 0
    assert result['improved_cases'] == result['harmed_cases'] == result['tied_cases'] == 1
    for bad in (blind[:-1], blind + [blind[0]]):
        try:
            score(bad, key)
        except ValueError:
            pass
        else:
            raise AssertionError('Incomplete/duplicate review accepted')
    blind[0]['errors_A'] = ''
    try:
        score(blind, key)
    except ValueError:
        pass
    else:
        raise AssertionError('Unrated case became zero errors')
print('PASS: blind identity, gains AND harms, missing and duplicate rating rejection')
