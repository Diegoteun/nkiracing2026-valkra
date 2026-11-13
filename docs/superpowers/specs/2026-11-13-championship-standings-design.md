# Championship standings (Stand-tab)

## Goal

Season leaderboard per split (1 and 2) from finished race results, using the official NK points scale.

## Points

| Finish | Points |
| ---: | ---: |
| 1 | 100 |
| 2 | 88 |
| 3 | 80 |
| 4–15 | 76, 72, 68, 64, 60, 56, 52, 48, 44, 40, 36, 32 |
| 16–30 | 30, 28, 26, 24, 22, 20, 18, 16, 14, 12, 10, 8, 6, 4, 2 |
| 31+ | 1 |

## UX

- New tab **Stand** (after Prequali).
- Two standings via existing split switch; cookie `valkra_split` is the default.
- Table: `#`, rijder (team/auto), points per finished round, **totaal**.
- Team/auto filters reused.
- Valkra rows keep yellow stripe; small Valkra block optional with their positions.

## Data

Computed client-side from `race.results[]` (finish per split). No separate upload path.

## Tie-break

Higher total → more wins → better average finish → name.
