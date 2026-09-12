"""Thirty synthetic controls: abstention is intentional, not a missed test."""
import importlib.util
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / 'addons/service.subtitles.kodipovilai/resources/lib/arabic_gender.py'
spec = importlib.util.spec_from_file_location('gender_controls', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
rows = json.loads((root / 'tools/fixtures/gender_quality_controls.json').read_text(encoding='utf-8'))
assert len(rows) == 30 and len({r['id'] for r in rows}) == 30
failures = []
for row in rows:
    actual = module.reference_addressee_gender(row['reference'], row['language'])
    if actual != row['expected_candidate']:
        failures.append((row['id'], actual, row['expected_candidate']))
assert not failures, failures
print('PASS: 30 synthetic detector controls; not a live translation-accuracy score')
