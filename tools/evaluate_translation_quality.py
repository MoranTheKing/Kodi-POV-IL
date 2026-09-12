"""Prepare and score a blind paired translation review (no network/API keys).

prepare: JSONL rows need id, scene, source, baseline, candidate. Outputs a
shuffled review CSV and a separate answer key. Do not give the key to reviewers.
score: reviewers fill errors_A/errors_B with total severity-weighted errors
(minor=1, major=5, critical=10). Lower is better. Counts newly harmed cases,
not just gains. Never use model/rule agreement as human accuracy.
"""
import argparse
import csv
import json
from pathlib import Path
import random


def prepare(rows, output, seed):
    if not rows or len({row['id'] for row in rows}) != len(rows):
        raise ValueError('Need nonempty, uniquely identified paired outputs')
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    rows = list(rows)
    rng.shuffle(rows)
    key = {}
    sheet = []
    for row in rows:
        if not all(isinstance(row.get(k), str) and row[k].strip()
                   for k in ('id', 'scene', 'source', 'baseline', 'candidate')):
            raise ValueError('Missing actual paired output: ' + str(row.get('id')))
        candidate_a = bool(rng.getrandbits(1))
        key[row['id']] = 'A' if candidate_a else 'B'
        sheet.append(dict(id=row['id'], scene=row['scene'], source=row['source'],
                          A=row['candidate'] if candidate_a else row['baseline'],
                          B=row['baseline'] if candidate_a else row['candidate'],
                          errors_A='', errors_B='', notes=''))
    with (output / 'blind_review.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(sheet[0]))
        writer.writeheader()
        writer.writerows(sheet)
    (output / 'review_key.json').write_text(json.dumps(key, indent=2), encoding='utf-8')
    return len(sheet)


def score(rows, key):
    if {row['id'] for row in rows} != set(key) or len(rows) != len(key):
        raise ValueError('Incomplete/duplicate review; missing ratings are not zero errors')
    baseline = candidate = improved = harmed = tied = 0
    for row in rows:
        a, b = float(row['errors_A']), float(row['errors_B'])
        import math
        if not all(math.isfinite(v) and v >= 0 for v in (a, b)):
            raise ValueError('Ratings must be finite nonnegative error counts')
        if key[row['id']] not in ('A', 'B'):
            raise ValueError('Invalid blind key')
        c, old = (a, b) if key[row['id']] == 'A' else (b, a)
        candidate += c
        baseline += old
        improved += c < old
        harmed += c > old
        tied += c == old
    return dict(cases=len(rows), baseline_error_points=baseline,
                candidate_error_points=candidate, net_error_points_removed=baseline-candidate,
                improved_cases=improved, harmed_cases=harmed, tied_cases=tied,
                scope='Human paired ratings supplied by caller; not overall subtitle accuracy')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='mode', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--pairs', type=Path, required=True)
    prep.add_argument('--output', type=Path, required=True)
    prep.add_argument('--seed', type=int, default=627)
    scoring = sub.add_parser('score')
    scoring.add_argument('--ratings', type=Path, required=True)
    scoring.add_argument('--key', type=Path, required=True)
    args = p.parse_args()
    if args.mode == 'prepare':
        rows = [json.loads(line) for line in args.pairs.read_text(encoding='utf-8').splitlines() if line.strip()]
        print('Prepared', prepare(rows, args.output, args.seed), 'paired cases')
    else:
        with args.ratings.open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
        print(json.dumps(score(rows, json.loads(args.key.read_text(encoding='utf-8'))), indent=2))


if __name__ == '__main__':
    main()
