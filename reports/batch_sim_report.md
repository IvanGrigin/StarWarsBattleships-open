# Batch simulation report (ruleset v3, sprint 1)

RandomLegal vs RandomLegal, one bot instance per match with
`Rng(match_seed * 7919 + 13)`; match seed = `base_seed + i`.
Reproducible: no timestamps, fixed file names, same arguments give
byte-identical reports.

- Matches: 200
- Base seed: 1000
- Round limit: 60
- ruleset_hash: `A76A0C893AC2FB7D`

## Results

| Outcome | Count | Share |
|---|---:|---:|
| Team A win | 14 | 7.00% |
| Team B win | 14 | 7.00% |
| Draw | 172 | 86.00% |
| ended by elimination | 28 | 14.00% |
| ended by both_eliminated | 0 | 0.00% |
| ended by round_limit | 172 | 86.00% |

## rounds

| avg | min | P50 | P95 | max |
|---:|---:|---:|---:|---:|
| 58.20 | 29 | 60 | 60 | 60 |

## commands

| avg | min | P50 | P95 | max |
|---:|---:|---:|---:|---:|
| 1493.29 | 785 | 1502 | 1853 | 2129 |
