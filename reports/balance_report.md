# Balance report — ruleset v3, sprint 1

- Generated: 2026-09-14 15:41:04
- Matches: 10000 requested, 10000 played, match seeds 6000..15999
- Round limit: 60
- Bots: RandomLegal vs RandomLegal (per-seat Rng, seed = match_seed*1000003 + seat_index)
- Scope: sprint 1: heroes and special abilities disabled (ADR-011)
- ruleset_hash: 289FEA29F1BB029E

## Outcomes

| Outcome | Count | Share |
|---|---:|---:|
| Team A win | 4643 | 46.4% |
| Team B win | 4631 | 46.3% |
| Draw | 726 | 7.3% |
| — ended by elimination | 9274 | 92.7% |
| — ended by both_eliminated | 0 | 0.0% |
| — ended by round_limit | 726 | 7.3% |
| Average rounds | 28.9 | |

## Ships

| Type | Picks | Kills | Deaths | Damage dealt | Damage taken | Dmg/death | Avg death round | Survived |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| death_star_1 | 3639 | 4473 | 3325 | 54384 | 45490 | 16.4 | 6.5 | 314 |
| eta2_actis | 7654 | 4497 | 5302 | 28034 | 29794 | 5.3 | 15.5 | 2352 |
| ghost | 3652 | 3463 | 1684 | 20773 | 22358 | 12.3 | 23.2 | 1425 |
| millennium_falcon | 2996 | 2704 | 1372 | 15859 | 17327 | 11.6 | 21.3 | 1624 |
| phantom | 0 | 0 | 0 | 0 | 0 | - | - | 543 |
| slave_1 | 3426 | 2598 | 2054 | 16059 | 17579 | 7.8 | 18.5 | 1372 |
| star_destroyer | 276 | 281 | 124 | 1667 | 1569 | 13.4 | 20.9 | 152 |
| tie_advanced_x1 | 3368 | 2575 | 2001 | 15932 | 17284 | 8.0 | 18.3 | 1367 |
| tie_fighter | 14227 | 8998 | 9260 | 54941 | 56395 | 5.9 | 16.2 | 4967 |
| vulture_droid | 10384 | 5570 | 7547 | 33681 | 32756 | 4.5 | 13.8 | 2837 |
| xwing_t65 | 10378 | 5329 | 7819 | 32842 | 33620 | 4.2 | 13.9 | 2559 |

## Seats (team A = A1+A2, team B = B1+B2)

| Seat | Wins | Winrate |
|---|---:|---:|
| A1 | 4643 | 46.4% |
| B1 | 4631 | 46.3% |
| A2 | 4643 | 46.4% |
| B2 | 4631 | 46.3% |

## Observations

- Draft: most picked type is 'tie_fighter' (14227 picks of 120000 slots, pick_rate 11.9%).
- Survivability: 'star_destroyer' survives most often (55.1% of its picks alive at the end); 'death_star_1' survives least (8.6%).
- Damage efficiency: 'death_star_1' deals the most damage per death (16.4). Total damage dealt by all types: 274172.
- Team A vs team B win skew is 0.1 pp — within 2 sigma (2.0 pp) of a fair coin, placement looks symmetric.
- Draws: 726 (7.3%), of which round_limit 726 and both_eliminated 0.
