"""
Valkra Performance · NK iRacing 2026 prequal forecast

Reads model/input/roster.json and model/input/laps.json, simulates the prequal and writes:
  data/valkra-nk-prequal.json           data file for the website
  data/valkra-nk-prequal-rijders.csv    one row per driver
  site/valkra-nk-prequal.html           the dashboard (loads the JSON, with a built-in copy as fallback)

Run from the repository root:  python3 model/build.py
Needs: Python 3.9+ and numpy.
"""
import bisect
import csv
import json
import math
import random
import statistics as st
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "model" / "input"
RAW_URL = "https://raw.githubusercontent.com/Diegoteun/nkiracing2026-valkra/main/data/valkra-nk-prequal.json"

# Model settings
MIN_LAPS_RELIABLE = 20        # a best time from 20+ laps counts as the driver's pace
KNEE_IRATING = 7000           # above this iRating the pace curve flattens
TARGET_10K = 102.30           # a 10.000 iRating driver sets a median prequal of 1:42.30 (team estimate)
ABSOLUTE_TOP = 102.25         # no attempt is faster than this (team estimate)
SAFE_SPLIT1 = 103.0
N_BASE, N_SCENARIO = 20000, 5000
SEED = 2026


def load_rows():
    roster = json.load(open(INPUT / "roster.json"))
    laps = json.load(open(INPUT / "laps.json"))
    by_id = {d["cust_id"]: d for d in laps["drivers"]}
    rows = []
    for m in roster["members"]:
        l = by_id.get(m["cust_id"], {})
        p_best, p_laps = l.get("practice_best"), l.get("practice_laps", 0) or 0
        q_best, q_laps = l.get("prequal_best"), l.get("prequal_laps", 0) or 0
        q_sess = l.get("prequal_sessions_used", 0) or 0
        best = min([t for t in (p_best, q_best) if t is not None], default=None)
        n = p_laps + q_laps
        status = "no_time" if best is None else ("reliable" if n >= MIN_LAPS_RELIABLE and best < 115 else "few_laps")
        rows.append(dict(id=m["cust_id"], name=m["name"], num=m.get("car_number"), ir=m["irating"],
                         lic=m["license"], sr=m["safety_rating"], pBest=p_best, pLaps=p_laps, qBest=q_best,
                         qLaps=q_laps, qSess=q_sess, best=best, laps=n, status=status))
    return roster, laps, rows


roster, laps_in, rows = load_rows()
rel = [r for r in rows if r["status"] == "reliable"]
x = np.log([r["ir"] for r in rel]); y = np.array([r["best"] for r in rel])
b, a = np.polyfit(x, y, 1)
r2 = float(1 - ((y - (a + b * x)) ** 2).sum() / ((y - y.mean()) ** 2).sum())

# Prequal attempt vs practice best, measured on drivers with 20+ practice laps
pairs = [(r["ir"], r["qBest"] - r["pBest"]) for r in rows
         if r["qBest"] and r["pBest"] and r["pLaps"] >= MIN_LAPS_RELIABLE and abs(r["qBest"] - r["pBest"]) < 1.5]
d_hi = [d for ir, d in pairs if ir >= 4000]; d_lo = [d for ir, d in pairs if ir < 4000]
ATT = dict(mu=st.mean(d for _, d in pairs), sd_hi=st.pstdev(d_hi), sd_lo=st.pstdev(d_lo), n=len(pairs))


def make_pace(top):
    pk = a + b * math.log(KNEE_IRATING); b2 = (top - pk) / math.log(10000 / KNEE_IRATING)
    def pace(ir):
        if ir <= KNEE_IRATING:
            return float(a + b * math.log(ir))
        return float(pk + b2 * (math.log(ir) - math.log(KNEE_IRATING)))
    return pace, b2


def simulate(top, n, seed, att_shift=0.0, p_second=1.0, drop=0, collect=False):
    pace, b2 = make_pace(top)
    rh = [r["best"] - pace(r["ir"]) for r in rel if r["ir"] >= 4000]
    rl = [r["best"] - pace(r["ir"]) for r in rel if r["ir"] < 4000]
    nonrun = [r["id"] for r in rows if r["best"] is None]
    rnd = random.Random(seed)
    grid = [round(102.0 + i * 0.02, 2) for i in range(161)]
    out = dict(c30=[], c60=[], pace=pace, b2=b2, rh=rh, rl=rl, grid=grid)
    if collect:
        out.update(fin={r["id"]: [] for r in rows}, rank={r["id"]: [] for r in rows}, posg=[[] for _ in grid])
    for _ in range(n):
        dropped = set(rnd.sample(nonrun, min(drop, len(nonrun)))) if drop else set()
        f = []
        for r in rows:
            if r["id"] in dropped:
                continue
            if r["status"] == "reliable":
                mu = r["best"]
            elif r["qBest"] is not None:
                mu = r["qBest"]                    # a prequal lap is a measurement, however few laps before it
            else:
                mu = pace(r["ir"]) + rnd.choice(rh if r["ir"] >= 4000 else rl)
                if r["best"] is not None:
                    mu = min(mu, r["best"])
            sd = ATT["sd_hi"] if r["ir"] >= 4000 else ATT["sd_lo"]
            left = max(0, 2 - r["qSess"])
            if left == 2 and rnd.random() > p_second:
                left = 1
            elif left == 1 and r["qSess"] == 1 and rnd.random() > p_second:
                left = 0
            fin = r["qBest"] if r["qBest"] is not None else math.inf
            for _ in range(left):
                fin = min(fin, max(ABSOLUTE_TOP, mu + rnd.gauss(ATT["mu"] + att_shift, sd)))
            if fin == math.inf:
                fin = max(ABSOLUTE_TOP, mu + rnd.gauss(ATT["mu"] + att_shift, sd))
            f.append((fin, r["id"]))
        f.sort()
        out["c30"].append(f[29][0]); out["c60"].append(f[59][0])
        if collect:
            for k, (t, i) in enumerate(f):
                out["fin"][i].append(t); out["rank"][i].append(k + 1)
            ts = [t for t, _ in f]
            for gi, g in enumerate(grid):
                out["posg"][gi].append(bisect.bisect_left(ts, g) + 1)
    return out


def med_10k(top, n=30000, seed=3):
    pace, _ = make_pace(top); rnd = random.Random(seed)
    rh = [r["best"] - pace(r["ir"]) for r in rel if r["ir"] >= 4000]
    return st.median(min(max(ABSOLUTE_TOP, pace(10000) + rnd.choice(rh) + rnd.gauss(ATT["mu"], ATT["sd_hi"]))
                         for _ in range(2)) for _ in range(n))


lo, hi = 102.2, 102.9
for _ in range(22):
    mid = (lo + hi) / 2
    if med_10k(mid) < TARGET_10K:
        lo = mid
    else:
        hi = mid
TOP = round((lo + hi) / 2, 3)
q = lambda L, p: sorted(L)[int(p * (len(L) - 1))]
pct = lambda L: {k: round(q(L, p), 3) for k, p in (("p10", .1), ("p50", .5), ("p90", .9))}

R = simulate(TOP, N_BASE, SEED, collect=True)
pace = R["pace"]
for r in rows:
    rk = R["rank"][r["id"]]
    r["exp"] = pct(R["fin"][r["id"]])
    r["rng"] = (q(rk, .1), q(rk, .9))
    r["s1"] = round(sum(v <= 30 for v in rk) / N_BASE * 100, 1)
    r["s2"] = round(sum(v <= 60 for v in rk) / N_BASE * 100, 1)
for k, r in enumerate(sorted(rows, key=lambda r: (r["exp"]["p50"], -r["ir"])), 1):
    r["pos"] = {"p10": min(r["rng"][0], k), "p50": k, "p90": max(r["rng"][1], k)}
# current prequal standings (ties: higher iRating first)
for k, r in enumerate(sorted((r for r in rows if r["qBest"] is not None), key=lambda r: (r["qBest"], -r["ir"])), 1):
    r["now"] = k
for r in rows:
    r["p1"] = round(sum(v == 1 for v in R["rank"][r["id"]]) / N_BASE * 100, 1)

scenarios = [{}, dict(att_shift=0.1), dict(att_shift=0.2), dict(p_second=0.5), dict(drop=11),
             dict(drop=11, p_second=0.5, att_shift=0.1)]
m30, m60 = [], []
for kw in scenarios:
    s = simulate(TOP, N_SCENARIO, 11, **kw)
    m30.append(st.median(s["c30"])); m60.append(st.median(s["c60"]))
rng = lambda L: dict(low=round(min(L), 2), likely=round(st.median(L), 2), high=round(max(L), 2))

# Summaries
edges = [0, 1500, 2000, 2500, 3000, 4000, 5000, 6000, 8000, 10 ** 6]
def band_label(i):
    if i == 0:
        return "< 1.500"
    if i == len(edges) - 2:
        return "8.000+"
    return f"{edges[i]:,}–{edges[i + 1]:,}".replace(",", ".")
bands = []
for i in range(len(edges) - 1):
    members = [r for r in rows if edges[i] <= r["ir"] < edges[i + 1]]
    measured = sorted(r["best"] for r in members if r["status"] == "reliable")
    bands.append(dict(label=band_label(i), irating_from=edges[i], irating_to=(None if i == len(edges) - 2 else edges[i + 1]),
                      members=len(members), measured_n=len(measured),
                      measured_median=(round(st.median(measured), 3) if measured else None),
                      expected_prequal_median=(round(st.median(r["exp"]["p50"] for r in members), 3) if members else None)))
irs = sorted(r["ir"] for r in rows)
hist = [dict(irating_from=lo_, irating_to=lo_ + 500, count=sum(lo_ <= v < lo_ + 500 for v in irs)) for lo_ in range(500, 10500, 500)]
lx = np.log(irs); h = 1.06 * np.std(lx) * len(lx) ** (-1 / 5); xs = list(range(500, 10600, 100))
dens = [round(float(np.exp(-0.5 * ((math.log(v) - lx) / h) ** 2).sum() / (len(lx) * h * math.sqrt(2 * math.pi)) / v * len(irs) * 500), 3) for v in xs]
fastest = min((r for r in rows if r["best"] is not None), key=lambda r: r["best"])

drivers = [dict(name=r["name"], car_number=r["num"], irating=r["ir"], license=r["lic"], safety_rating=r["sr"],
                practice_best=r["pBest"], practice_laps=r["pLaps"], prequal_best=r["qBest"], prequal_laps=r["qLaps"],
                prequal_sessions_used=r["qSess"], best_time=r["best"], laps_total=r["laps"], time_status=r["status"],
                model_time=round(pace(r["ir"]), 3), prequal_position_now=r.get("now"),
                expected_prequal=r["exp"], expected_position=r["pos"],
                chance_p1=r["p1"], chance_split1=r["s1"], chance_split2=r["s2"])
           for r in sorted(rows, key=lambda r: r["pos"]["p50"])]

generated = laps_in.get("fetched_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")
out = dict(
    meta=dict(
        generated_at=generated,
        league=dict(id=roster.get("league_id"), name=roster.get("league_name")),
        season=roster.get("season_name"), track=laps_in.get("track"),
        prequal_window=dict(start="2026-10-26", end="2026-11-01"),
        sessions_used=laps_in.get("sessions_used", []), field_size=len(rows), simulations=N_BASE,
        units="Alle tijden in seconden (103.25 = 1:43.25). Posities: 1 = snelste. p10/p50/p90 = 10e, 50e en 90e percentiel van de simulaties.",
        time_status=dict(reliable="tijd gezet in 20 of meer ronden", few_laps="tijd gezet in minder dan 20 ronden", no_time="nog geen tijd"),
        model=dict(
            description="Tempo per iRating: lap = a + b*ln(iRating), gefit op rijders met 20+ ronden; boven 7.000 iRating vlakker, zodat een rijder van 10.000 in de prequal mediaan 1:42.30 rijdt. Rijders met minder dan 20 ronden of zonder tijd krijgen het modeltempo plus de spreiding van hun iRating-groep, nooit trager dan hun gereden tijd. Iedereen rijdt zijn resterende prequal-sessies (max 2); een poging = beste tijd of modeltempo + afwijking uit het gemeten verschil tussen prequal en training. Geen poging sneller dan de absolute toptijd.",
            a=round(float(a), 4), b=round(float(b), 4), knee_irating=KNEE_IRATING, slope_above_knee=round(R["b2"], 4),
            pace_at_10000=TOP, expected_prequal_at_10000=TARGET_10K, absolute_top_time=ABSOLUTE_TOP,
            r2=round(r2, 3), fit_n=len(rel),
            spread_irating_4000_plus=round(st.pstdev(R["rh"]), 3), spread_irating_below_4000=round(st.pstdev(R["rl"]), 3),
            attempt_mean=round(ATT["mu"], 3), attempt_sd=round(ATT["sd_lo"], 3), attempt_sd_irating_4000_plus=round(ATT["sd_hi"], 3),
            attempt_n=ATT["n"], expected_position="Volgorde van de verwachte prequal-tijd (p50); p10/p90 uit de simulaties.")),
    forecast=dict(
        split1_cutoff=pct(R["c30"]), split2_cutoff=pct(R["c60"]), safe_split1=SAFE_SPLIT1, absolute_top_time=ABSOLUTE_TOP,
        split1_range=rng(m30), split2_range=rng(m60),
        range_note="split1_cutoff/split2_cutoff = strengste scenario (alle leden, allemaal twee sessies). split1_range/split2_range = bandbreedte over scenario's: een deel rijdt één sessie, pogingen tot 0,2 s trager, ~100 deelnemers.",
        fastest_so_far=dict(name=fastest["name"], irating=fastest["ir"], time=fastest["best"],
                            session=("prequal" if fastest["best"] == fastest["qBest"] else "training"))),
    position_curve=dict(description="Verwachte prequal-positie bij deze tijd, tegen het hele veld", times=R["grid"],
                        p10=[q(L, .1) for L in R["posg"]], p50=[q(L, .5) for L in R["posg"]], p90=[q(L, .9) for L in R["posg"]]),
    drivers=drivers, irating_bands=bands, irating_histogram=hist,
    irating_density=dict(irating=xs, expected_count_per_500=dens),
    irating_summary=dict(median=st.median(irs), mean=round(st.mean(irs)), min=irs[0], max=irs[-1]))

(ROOT / "data").mkdir(exist_ok=True); (ROOT / "site").mkdir(exist_ok=True)
json.dump(out, open(ROOT / "data" / "valkra-nk-prequal.json", "w"), ensure_ascii=False, indent=1)
with open(ROOT / "data" / "valkra-nk-prequal-rijders.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["verwachte_plek", "verwachte_plek_p10", "verwachte_plek_p90", "naam", "nummer", "irating", "licentie", "sr",
                "beste_tijd", "ronden", "status", "verwachte_prequal", "verwachte_prequal_p10", "verwachte_prequal_p90",
                "kans_split1_pct", "kans_split2_pct", "prequal_sessies_gebruikt"])
    for d in drivers:
        w.writerow([d["expected_position"]["p50"], d["expected_position"]["p10"], d["expected_position"]["p90"], d["name"],
                    d["car_number"] or "", d["irating"], d["license"], d["safety_rating"],
                    "" if d["best_time"] is None else d["best_time"], d["laps_total"], d["time_status"],
                    d["expected_prequal"]["p50"], d["expected_prequal"]["p10"], d["expected_prequal"]["p90"],
                    d["chance_split1"], d["chance_split2"], d["prequal_sessions_used"]])
template = open(ROOT / "model" / "template.html").read()
assert template.count("/*__DATA__*/null") == 1 and template.count("/*__DATA_URL__*/") == 1
page = (template.replace("/*__DATA__*/null", json.dumps(out, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
                .replace("/*__DATA_URL__*/", json.dumps(RAW_URL)))
open(ROOT / "site" / "valkra-nk-prequal.html", "w").write(page)

print(f"Stand {generated}: grens split 1 ≈{out['forecast']['split1_range']['likely']} "
      f"({out['forecast']['split1_range']['low']}–{out['forecast']['split1_range']['high']}), "
      f"split 2 ≈{out['forecast']['split2_range']['likely']}, snelste {fastest['name']} {fastest['best']}")
