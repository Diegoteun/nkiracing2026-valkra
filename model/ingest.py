"""
Controleert de compacte uitvoer van model/fetch_iracing.js (versie 3) en schrijft de invoer voor build.py:
  model/input/roster.json     ledenlijst met iRating en licentie
  model/input/tests.json      testsessies per baan (beste ronde, ronden, beste per dag, auto)
  model/input/races.json      raceresultaten per split (kwalificatie, snelste en gemiddelde raceronde, uitslag)
  model/input/schedule.json   geplande races per split
De VIR-prequal (model/input/laps.json) blijft ongemoeid: die is definitief.

Gebruik: python3 model/ingest.py <bestand-met-uitvoer.json>
Stopt met een foutmelding als een controlegetal niet klopt, zodat een beschadigde kopie nooit wordt gebruikt.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "model" / "input"

src = json.loads(Path(sys.argv[1]).read_text())
if src.get("v") != 3:
    sys.exit("Invoer afgekeurd: verwacht versie 3 van fetch_iracing.js")
m, t, r, sched, c = src["m"], src["t"], src["r"], src["sched"], src["check"]
problems = []
chk = lambda ok, msg: ok or problems.append(msg)
chk(len(m) == c["members"], f"leden {len(m)} ≠ {c['members']}")
chk(sum(x[3] or 0 for x in m) == c["irating_sum"], "som iRating klopt niet")
chk(len({x[0] for x in m}) == len(m), "dubbele leden")
chk(len(t) == c["tracks"], "aantal banen klopt niet")
chk(sum(len(T["s"]) for T in t) == c["t_drivers"], "aantal rijders in testsessies klopt niet")
chk(sum(x[2] for T in t for x in T["s"]) == c["t_laps"], "som testronden klopt niet")
chk(round(sum((x[1] or 0) for T in t for x in T["s"]) * 1e4) == c["t_time_sum"], "som testtijden klopt niet")
chk(len(r) == c["r_rows"], "aantal raceregels klopt niet")
chk(sum(x[6] or 0 for x in r) == c["r_laps"], "som raceronden klopt niet")
chk(round(sum((x[3] or 0) + (x[4] or 0) + (x[5] or 0) for x in r) * 1e4) == c["r_time_sum"], "som racetijden klopt niet")
chk(len(sched) == c["sched"], "aantal geplande races klopt niet")
if problems:
    sys.exit("Invoer afgekeurd: " + "; ".join(problems))

meta = dict(fetched_at=src["fetched_at"], league_id=src["league_id"], league_name=src["league_name"], season_name=src["season_name"])
roster = dict(meta, category="sports_car",
              members=[dict(cust_id=x[0], name=x[1], car_number=x[2], irating=x[3], license=x[4], safety_rating=x[5]) for x in m])
tests = dict(meta, tracks=[dict(track=T["track"], days=T["days"], sessions_used=T["sessions"],
                                drivers=[dict(cust_id=x[0], best=x[1], laps=x[2], best_per_day=x[3], car=x[4]) for x in T["s"]]) for T in t])
races = dict(meta, rows=[dict(cust_id=x[0], split=x[1], track=x[2], quali_best=x[3], race_best=x[4], race_avg=x[5], race_laps=x[6],
                              finish=x[7], incidents=x[8], car=x[9], subsession_id=x[10]) for x in r])
schedule = dict(meta, races=[dict(split=x[0], start=x[1], track=x[2], subsession_id=x[3], has_results=bool(x[4])) for x in sched])
INPUT.mkdir(parents=True, exist_ok=True)
for name, obj in (("roster", roster), ("tests", tests), ("races", races), ("schedule", schedule)):
    (INPUT / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=1))
old = INPUT / "suzuka.json"
if old.exists():
    old.unlink()
print(f"OK: {len(m)} leden, testsessies op {len(t)} baan/banen ({c['t_drivers']} rijders, {c['t_laps']} ronden), "
      f"{len(r)} raceregels, {len(sched)} geplande races, stand {src['fetched_at']}")
