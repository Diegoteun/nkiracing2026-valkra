"""
Controleert de compacte uitvoer van model/fetch_iracing.js en schrijft model/input/roster.json en laps.json.

Gebruik: python3 model/ingest.py <bestand-met-uitvoer.json>
Stopt met een foutmelding als het controlegetal niet klopt, zodat een beschadigde kopie nooit wordt gebruikt.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "model" / "input"

src = json.loads(Path(sys.argv[1]).read_text())
m, l, c = src["m"], src["l"], src["check"]
problems = []
if len(m) != c["members"]:
    problems.append(f"leden {len(m)} ≠ {c['members']}")
if len(l) != c["drivers"]:
    problems.append(f"rijders met resultaten {len(l)} ≠ {c['drivers']}")
if sum(x[3] or 0 for x in m) != c["irating_sum"]:
    problems.append("som iRating klopt niet")
if sum(x[2] + x[4] for x in l) != c["laps_sum"]:
    problems.append("som ronden klopt niet")
if round(sum((x[1] or 0) + (x[3] or 0) for x in l) * 1e4) != c["time_sum"]:
    problems.append("som tijden klopt niet")
if len({x[0] for x in m}) != len(m):
    problems.append("dubbele leden")
if problems:
    sys.exit("Invoer afgekeurd: " + "; ".join(problems))

roster = dict(fetched_at=src["fetched_at"], league_id=src["league_id"], league_name=src["league_name"],
              season_id=src["season_id"], season_name=src["season_name"], category="sports_car",
              members=[dict(cust_id=x[0], name=x[1], car_number=x[2], irating=x[3], license=x[4], safety_rating=x[5]) for x in m])
laps = dict(fetched_at=src["fetched_at"], track=src["track"], sessions_used=src["sessions"],
            drivers=[dict(cust_id=x[0], practice_best=x[1], practice_laps=x[2], prequal_best=x[3], prequal_laps=x[4],
                          prequal_sessions_used=x[5]) for x in l])
INPUT.mkdir(parents=True, exist_ok=True)
(INPUT / "roster.json").write_text(json.dumps(roster, ensure_ascii=False, indent=1))
(INPUT / "laps.json").write_text(json.dumps(laps, ensure_ascii=False, indent=1))
print(f"OK: {len(m)} leden, {len(l)} rijders met resultaten, {len(src['sessions'])} sessies, stand {src['fetched_at']}")
