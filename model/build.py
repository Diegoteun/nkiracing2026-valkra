"""
Valkra Performance · NK iRacing 2026 prequal forecast

Reads model/input/roster.json and model/input/laps.json, simulates the prequal and writes:
  data/valkra-nk-prequal.json           data file for the website
  data/valkra-nk-prequal-rijders.csv    one row per driver
  site/valkra-nk-prequal.html           the dashboard (loads the JSON, with a built-in copy as fallback)
  public/index.html                     same dashboard for Vercel

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
PREQUAL_END = "2026-11-01"    # last prequal day; after this the VIR times are final and the splits are fixed
N_SUZUKA = 20000              # simulations for the Suzuka top-3 pace
SUZUKA_RACE = "2026-11-05"
SUZ_PRIOR_LAPS = 20           # a Suzuka best from this many laps counts for half in the driver-specific offset


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
CLOSED = (laps_in.get("fetched_at") or "9999")[:10] > PREQUAL_END
# Pace curve = practice pace: fitted on practice bests of drivers with 20+ practice laps.
# A prequal attempt is then practice pace + an attempt offset (measured below), so prequal gains are counted once.
rel = [r for r in rows if r["pBest"] is not None and r["pLaps"] >= MIN_LAPS_RELIABLE and r["pBest"] < 115]
x = np.log([r["ir"] for r in rel]); y = np.array([r["pBest"] for r in rel])
b, a = np.polyfit(x, y, 1)
r2 = float(1 - ((y - (a + b * x)) ** 2).sum() / ((y - y.mean()) ** 2).sum())

# Prequal attempt vs practice best: drivers with 20+ practice laps and exactly one prequal session (one attempt)
pairs = [(r["ir"], r["qBest"] - r["pBest"]) for r in rows
         if r["qBest"] and r["pBest"] and r["pLaps"] >= MIN_LAPS_RELIABLE and r["qSess"] == 1 and abs(r["qBest"] - r["pBest"]) < 1.5]
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
    rh = [r["pBest"] - pace(r["ir"]) for r in rel if r["ir"] >= 4000]
    rl = [r["pBest"] - pace(r["ir"]) for r in rel if r["ir"] < 4000]
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
            if CLOSED:                      # prequal is over: the best prequal time is final, nothing is imputed
                f.append((r["qBest"] if r["qBest"] is not None else math.inf, r["id"]))
                continue
            # mu = practice-level pace; a prequal lap counts as one attempt (pace + ATT["mu"])
            if r["pBest"] is not None and r["pLaps"] >= MIN_LAPS_RELIABLE:
                mu = r["pBest"]
                if r["qBest"] is not None:
                    mu = min(mu, r["qBest"] - ATT["mu"])
            elif r["qBest"] is not None:
                mu = r["qBest"] - ATT["mu"]
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
    rh = [r["pBest"] - pace(r["ir"]) for r in rel if r["ir"] >= 4000]
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

N_RUN = 1 if CLOSED else N_BASE
R = simulate(TOP, N_RUN, SEED, collect=True)
pace = R["pace"]
# current prequal standings (ties: higher iRating first)
for k, r in enumerate(sorted((r for r in rows if r["qBest"] is not None), key=lambda r: (r["qBest"], -r["ir"])), 1):
    r["now"] = k
if CLOSED:
    for r in rows:
        k = r.get("now")
        if k is None:   # no prequal time: placed after everyone with a time (model pace only as a placeholder for older dashboards)
            n_t = sum(1 for x in rows if x["qBest"] is not None)
            k2 = n_t + 1 + sorted((x["ir"] * -1, x["id"]) for x in rows if x["qBest"] is None).index((-r["ir"], r["id"]))
            pc = round(pace(r["ir"]), 3)
            r.update(exp=dict(p10=pc, p50=pc, p90=pc), pos=dict(p10=k2, p50=k2, p90=k2), s1=0.0, s2=0.0, p1=0.0)
        else:
            r.update(exp=dict(p10=r["qBest"], p50=r["qBest"], p90=r["qBest"]), pos=dict(p10=k, p50=k, p90=k),
                     s1=100.0 if k <= 30 else 0.0, s2=100.0 if 30 < k <= 60 else 0.0, p1=100.0 if k == 1 else 0.0)
else:
    for r in rows:
        rk = R["rank"][r["id"]]
        r["exp"] = pct(R["fin"][r["id"]])
        r["rng"] = (q(rk, .1), q(rk, .9))
        r["s1"] = round(sum(v <= 30 for v in rk) / N_BASE * 100, 1)
        r["s2"] = round(sum(v <= 60 for v in rk) / N_BASE * 100, 1)
    for k, r in enumerate(sorted(rows, key=lambda r: (r["exp"]["p50"], -r["ir"])), 1):
        r["pos"] = {"p10": min(r["rng"][0], k), "p50": k, "p90": max(r["rng"][1], k)}
    for r in rows:
        r["p1"] = round(sum(v == 1 for v in R["rank"][r["id"]]) / N_BASE * 100, 1)

scenarios = [{}] if CLOSED else [{}, dict(att_shift=0.1), dict(att_shift=0.2), dict(p_second=0.5), dict(drop=11),
                                 dict(drop=11, p_second=0.5, att_shift=0.1)]
m30, m60 = [], []
for kw in scenarios:
    s = simulate(TOP, 1 if CLOSED else N_SCENARIO, 11, **kw)
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
                      expected_prequal_median=(round(st.median(r["exp"]["p50"] for r in members if r["exp"]), 3) if any(r["exp"] for r in members) else None)))
irs = sorted(r["ir"] for r in rows)
hist = [dict(irating_from=lo_, irating_to=lo_ + 500, count=sum(lo_ <= v < lo_ + 500 for v in irs)) for lo_ in range(500, 10500, 500)]
lx = np.log(irs); h = 1.06 * np.std(lx) * len(lx) ** (-1 / 5); xs = list(range(500, 10600, 100))
dens = [round(float(np.exp(-0.5 * ((math.log(v) - lx) / h) ** 2).sum() / (len(lx) * h * math.sqrt(2 * math.pi)) / v * len(irs) * 500), 3) for v in xs]
fastest = min((r for r in rows if r["best"] is not None), key=lambda r: r["best"])

# ---------------------------------------------------------------------------------------------
# Suzuka test sessions: expected pace for a top-3 place in split 1 and split 2
# Split = final VIR prequal rank (P1-30 split 1, P31-60 split 2). Pace = fastest lap (qualifying-level).
# Model: Suzuka best = c + k * VIR prequal best + g * ln(laps)  (more laps -> faster), fitted on drivers with both.
# A driver's own offset from that line counts partly (weight n / (n + SUZ_PRIOR_LAPS)); the pace on race day is
# projected at the laps a driver is expected to have by then. 20.000 simulations give the top-3 threshold per split.
def build_suzuka():
    sp = INPUT / "suzuka.json"
    if not sp.exists():
        return None
    sz = json.load(open(sp))
    S = {d["cust_id"]: d for d in sz["drivers"]}
    cars = {}
    byrow = {r["id"]: r for r in rows}
    fit = [(r["qBest"], S[r["id"]]["best"], S[r["id"]]["laps"]) for r in rows
           if r["qBest"] is not None and r["id"] in S and S[r["id"]]["best"] and S[r["id"]]["laps"] >= 3]
    xq = np.array([f[0] for f in fit]); ys = np.array([f[1] for f in fit]); ln_ = np.log([f[2] for f in fit])
    A = np.vstack([np.ones_like(xq), xq, ln_]).T
    (c0, k1, g1), *_ = np.linalg.lstsq(A, ys, rcond=None)
    resid = ys - A @ np.array([c0, k1, g1])
    sd = float(resid.std(ddof=3))
    r2s = float(1 - (resid ** 2).sum() / ((ys - ys.mean()) ** 2).sum())
    # laps a driver is expected to add before the race: two more test days + the race qualifying
    day_laps = []
    for d in sz["drivers"]:
        pass
    n_days = len(sz.get("days", [])) or 1
    active = sum(1 for d in sz["drivers"] if d["laps"])
    per_day = max(8.0, sum(d["laps"] for d in sz["drivers"]) / max(1, sum(1 for d in sz["drivers"] for v in d["best_per_day"] if v is not None)))
    test_days_left = max(0, (datetime.fromisoformat(SUZUKA_RACE) - datetime.fromisoformat((laps_in.get("fetched_at") or "")[:10])).days - 1)
    extra = test_days_left * per_day + 5
    ranked = sorted((r for r in rows if r.get("now")), key=lambda r: r["now"])
    members = []
    for r in ranked:
        if r["now"] > 60:
            break
        s = S.get(r["id"], {})
        best, n = s.get("best"), s.get("laps", 0) or 0
        base_now = c0 + k1 * r["qBest"] + g1 * math.log(max(n, 1))
        n_ref = max(n, 0) + extra
        mu0 = c0 + k1 * r["qBest"] + g1 * math.log(max(n_ref, 1))
        w = n / (n + SUZ_PRIOR_LAPS) if best else 0.0
        delta = (best - base_now) if best else 0.0
        mu = mu0 + w * delta
        sig = sd * (1 - 0.5 * w)
        members.append(dict(r=r, split=1 if r["now"] <= 30 else 2, best=best, laps=n, mu=mu, sig=sig, car=s.get("car"),
                            days=s.get("best_per_day")))
    rnd = np.random.default_rng(SEED)
    out_s = {}
    for sp_no in (1, 2):
        ms = [m for m in members if m["split"] == sp_no]
        mu = np.array([m["mu"] for m in ms]); sg = np.array([m["sig"] for m in ms])
        draw = rnd.normal(mu, sg, size=(N_SUZUKA, len(ms)))
        for j, m in enumerate(ms):
            if m["best"]:
                draw[:, j] = np.minimum(draw[:, j], m["best"])        # a lap already set cannot be undone
        srt = np.sort(draw, axis=1)
        order = np.argsort(draw, axis=1)
        rankpos = np.empty_like(order); rows_i = np.arange(order.shape[0])[:, None]
        rankpos[rows_i, order] = np.arange(1, len(ms) + 1)[None, :]
        qs = lambda a, p: float(np.quantile(a, p))
        timed_now = sorted((m for m in ms if m["best"]), key=lambda m: m["best"])
        drivers_s = []
        for j, m in enumerate(ms):
            r = m["r"]
            now_rank = (timed_now.index(m) + 1) if m["best"] else None
            drivers_s.append(dict(
                name=r["name"], car_number=r["num"], irating=r["ir"], prequal_position=r["now"], prequal_best=r["qBest"],
                suzuka_best=m["best"], suzuka_laps=m["laps"], suzuka_car=m["car"], suzuka_best_per_day=m["days"],
                suzuka_rank_now=now_rank,
                expected_pace=dict(p10=round(qs(draw[:, j], .1), 3), p50=round(qs(draw[:, j], .5), 3), p90=round(qs(draw[:, j], .9), 3)),
                expected_rank=dict(p10=int(qs(rankpos[:, j], .1)), p50=int(round(qs(rankpos[:, j], .5))), p90=int(qs(rankpos[:, j], .9))),
                chance_top3=round(float((rankpos[:, j] <= 3).mean() * 100), 1),
                chance_win=round(float((rankpos[:, j] == 1).mean() * 100), 1)))
        drivers_s.sort(key=lambda d: (d["expected_pace"]["p50"], d["expected_rank"]["p50"]))
        for i_, d_ in enumerate(drivers_s, 1):
            d_["expected_order"] = i_
        p3 = srt[:, 2]; p1 = srt[:, 0]; p10 = srt[:, 9]
        now_p = lambda k: timed_now[k - 1]["best"] if len(timed_now) >= k else None
        out_s[sp_no] = dict(
            split=sp_no, prequal_from=1 if sp_no == 1 else 31, prequal_to=30 if sp_no == 1 else 60, members=len(ms),
            with_time=len(timed_now),
            now=dict(p1=now_p(1), p3=now_p(3), p10=now_p(10)),
            top3_pace=dict(p10=round(qs(p3, .1), 3), p50=round(qs(p3, .5), 3), p90=round(qs(p3, .9), 3)),
            winner_pace=dict(p10=round(qs(p1, .1), 3), p50=round(qs(p1, .5), 3), p90=round(qs(p1, .9), 3)),
            top10_pace=dict(p10=round(qs(p10, .1), 3), p50=round(qs(p10, .5), 3), p90=round(qs(p10, .9), 3)),
            drivers=drivers_s)
    fast = [(d["best"], r_["name"]) for r_ in rows for d in [S.get(r_["id"])] if d and d["best"]]
    fast.sort()
    all_fastest = None
    if fast:
        fr = next(r_ for r_ in rows if S.get(r_["id"]) and S[r_["id"]]["best"] == fast[0][0])
        all_fastest = dict(name=fr["name"], time=fast[0][0], car=S[fr["id"]]["car"], split=(1 if (fr.get("now") or 99) <= 30 else 2 if (fr.get("now") or 99) <= 60 else None))
    return dict(
        track="Suzuka International Racing Course – Grand Prix", race_date=SUZUKA_RACE, days=sz.get("days", []),
        sessions_used=sz.get("sessions_used", []), drivers_with_time=sum(1 for d in sz["drivers"] if d["best"]),
        laps_total=sum(d["laps"] for d in sz["drivers"]), fastest=all_fastest,
        model=dict(
            description="Suzuka-tempo = c + k × VIR-prequaltijd + g × ln(ronden): wie meer rondes reed is sneller. De eigen afwijking van een rijder weegt mee naarmate hij meer ronden heeft (50% bij " + str(SUZ_PRIOR_LAPS) + " ronden). De verwachte pace is de snelste ronde die een rijder op racedag naar verwachting heeft gereden, met de ronden die hij tot dan nog bij rijdt. Een al gereden ronde kan niet trager worden. De drempel voor een top-3 is de derde snelste verwachte pace binnen de split, uit " + f"{N_SUZUKA:,}".replace(",", ".") + " simulaties.",
            c=round(float(c0), 3), k=round(float(k1), 4), g=round(float(g1), 4), residual_sd=round(sd, 3), r2=round(r2s, 3), fit_n=len(fit),
            expected_extra_laps=round(extra, 1), test_days_left=test_days_left, prior_laps=SUZ_PRIOR_LAPS,
            pace_definition="snelste ronde (kwalificatie-niveau), geen gemiddelde racepace"),
        splits=[out_s[1], out_s[2]])

SUZUKA = build_suzuka()

drivers = [dict(name=r["name"], car_number=r["num"], irating=r["ir"], license=r["lic"], safety_rating=r["sr"],
                practice_best=r["pBest"], practice_laps=r["pLaps"], prequal_best=r["qBest"], prequal_laps=r["qLaps"],
                prequal_sessions_used=r["qSess"], best_time=r["best"], laps_total=r["laps"], time_status=r["status"],
                model_time=round(pace(r["ir"]), 3), prequal_position_now=r.get("now"),
                expected_prequal=r["exp"], expected_position=r["pos"],
                chance_p1=r["p1"], chance_split1=r["s1"], chance_split2=r["s2"])
           for r in sorted(rows, key=lambda r: (r["pos"]["p50"] if r["pos"] else 10 ** 6, -r["ir"]))]

generated = laps_in.get("fetched_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")
out = dict(
    meta=dict(
        generated_at=generated,
        league=dict(id=roster.get("league_id"), name=roster.get("league_name")),
        season=roster.get("season_name"), track=laps_in.get("track"),
        prequal_window=dict(start="2026-10-26", end="2026-11-01"),
        sessions_used=laps_in.get("sessions_used", []), field_size=len(rows), simulations=N_RUN, prequal_closed=CLOSED,
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
    suzuka=SUZUKA,
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
        ep = d["expected_position"] or {}
        xp = d["expected_prequal"] or {}
        w.writerow([ep.get("p50", ""), ep.get("p10", ""), ep.get("p90", ""), d["name"],
                    d["car_number"] or "", d["irating"], d["license"], d["safety_rating"],
                    "" if d["best_time"] is None else d["best_time"], d["laps_total"], d["time_status"],
                    xp.get("p50", ""), xp.get("p10", ""), xp.get("p90", ""),
                    d["chance_split1"], d["chance_split2"], d["prequal_sessions_used"]])
template = open(ROOT / "model" / "template.html").read()
assert template.count("/*__DATA__*/null") == 1 and template.count("/*__DATA_URL__*/") == 1
page = (template.replace("/*__DATA__*/null", json.dumps(out, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
                .replace("/*__DATA_URL__*/", json.dumps(RAW_URL)))
open(ROOT / "site" / "valkra-nk-prequal.html", "w").write(page)
(ROOT / "public").mkdir(exist_ok=True)
open(ROOT / "public" / "index.html", "w").write(page)

print(f"Stand {generated}: grens split 1 ≈{out['forecast']['split1_range']['likely']} "
      f"({out['forecast']['split1_range']['low']}–{out['forecast']['split1_range']['high']}), "
      f"split 2 ≈{out['forecast']['split2_range']['likely']}, snelste {fastest['name']} {fastest['best']}")
