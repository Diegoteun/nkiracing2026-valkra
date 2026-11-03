"""
Valkra Performance · NK iRacing 2026 · pace voor de komende race

Doel: per split een overzicht van wie welke tijd heeft gereden, een inschatting van de pace op racedag voor iedereen
(ook wie nog niet testte) en een target: de pace die nodig is om mee te doen om de top 3.

Opbouw
1. Komende race: de eerstvolgende geplande race uit de split-seizoenen (baan + datum).
2. Pace-index per rijder uit de geschiedenis: hoeveel procent hij sneller of trager is dan de mediaan van het veld.
   Bronnen: de VIR-prequal en elke eerder verreden race (testsessies + kwalificatie + race op die baan).
   Een race telt zwaarder naarmate de rijder er meer ronden reed (volle weging vanaf 20 ronden).
3. Lijn voor de komende baan: beste testronde = c + k × pace-index + g × ln(ronden), gefit op rijders met beide.
   Wie meer ronden rijdt, wordt sneller (g < 0).
4. Verwachting op racedag: lijn bij de ronden die een rijder dan naar verwachting heeft, plus zijn eigen afwijking
   van de lijn (die telt voor n / (n + 20) mee). Een al gereden ronde kan niet trager worden.
5. 20.000 simulaties per split geven de target (derde snelste tijd in de split), de winnaars- en top-10-pace en per
   rijder de kans op een top 3.
"""
import csv
import json
import math
import re
import statistics as st
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

TEAM = "Valkra Performance"
N_SIM = 20000
PRIOR_LAPS = 20          # eigen afwijking telt voor 50% bij 20 ronden
MIN_FIT_LAPS = 3
SPLIT_SIZE = 30
SHOW_SPLITS = (1, 2)
QUALI_LAPS = 5           # ronden in de 10 minuten kwalificatie op racedag


def _norm(s):
    s = re.sub(r"\d+", "", (s or "").lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-zà-ÿ ]", "", s)).strip()


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower().split(" – ")[0]).strip("-")


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_teams(path):
    if not path.exists():
        return {}, {}
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    by_num = {r["car_number"]: r for r in rows if r["car_number"] not in ("", "0")}
    by_name = {_norm(r["name"]): r for r in rows}
    return by_num, by_name


def build_race(rows, INPUT, ROOT, seed=2026):
    tests_p, races_p, sched_p = INPUT / "tests.json", INPUT / "races.json", INPUT / "schedule.json"
    if not (tests_p.exists() and sched_p.exists()):
        return None
    tests = json.load(open(tests_p)); races = json.load(open(races_p)) if races_p.exists() else {"rows": []}
    sched = json.load(open(sched_p))
    fetched = _dt(tests["fetched_at"])
    by_num, by_name = load_teams(ROOT / "model" / "teams.csv")

    def team_of(r):
        t = by_num.get(str(r["num"])) if r.get("num") else None
        t = t or by_name.get(_norm(r["name"]))
        return (t or {}).get("team") or None, (t or {}).get("car") or None

    # 1. Coming race: earliest scheduled start after the fetch, else the last one
    starts = sorted({(x["start"], x["track"]) for x in sched["races"]})
    upcoming = [s for s in starts if _dt(s[0]) > fetched]
    cur_start, cur_track = (upcoming[0] if upcoming else starts[-1])
    rounds = []
    for s, tr in starts:
        if not rounds or rounds[-1][1] != tr or (_dt(s) - _dt(rounds[-1][0])).days > 2:
            rounds.append((s, tr))
    round_no = next(i for i, (s, tr) in enumerate(rounds, 1) if tr == cur_track and abs((_dt(s) - _dt(cur_start)).days) <= 2)

    T = {x["track"]: x for x in tests["tracks"]}
    cur_tests = {d["cust_id"]: d for d in T.get(cur_track, {"drivers": []})["drivers"]}
    race_rows = races["rows"]

    # 2. Pace index from history (prequal + earlier races; the current track's tests are used directly)
    hist = {r["id"]: [] for r in rows}
    ranked = [r for r in rows if r.get("now")]
    q_med = st.median(r["qBest"] for r in ranked)
    for r in ranked:
        hist[r["id"]].append(("prequal-vir", r["qBest"] / q_med - 1, 1.0))
    history_events = [dict(id="prequal-vir", kind="prequal", track="Virginia International Raceway – Full Course",
                           date="2026-11-01", drivers=len(ranked), reference=round(q_med, 3))]
    for s, tr in rounds:
        if tr == cur_track and abs((_dt(s) - _dt(cur_start)).days) <= 2:
            continue
        rr = [x for x in race_rows if x["track"] == tr]
        if not rr:
            continue
        best = {}
        for d in T.get(tr, {"drivers": []})["drivers"]:
            if d["best"]:
                best[d["cust_id"]] = [d["best"], d["laps"]]
        for x in rr:
            b = [v for v in (x["quali_best"], x["race_best"]) if v]
            if not b:
                continue
            o = best.setdefault(x["cust_id"], [min(b), 0])
            o[0] = min(o[0], min(b)); o[1] += (x["race_laps"] or 0) + 3
        ref = st.median(v[0] for v in best.values() if v[1] >= 10) if any(v[1] >= 10 for v in best.values()) else None
        if not ref:
            continue
        eid = f"{s[:10]}-{_slug(tr)}"
        for cid, (b, n) in best.items():
            if cid in hist:
                hist[cid].append((eid, b / ref - 1, min(1.0, n / 20)))
        history_events.append(dict(id=eid, kind="race", track=tr, date=s[:10], drivers=len(best), reference=round(ref, 3)))
    prior = {cid: (sum(i * w for _, i, w in h) / sum(w for *_, w in h), len(h)) for cid, h in hist.items() if h and sum(w for *_, w in h) > 0}

    # 3. Line for the coming track
    fit = [(prior[r["id"]][0], cur_tests[r["id"]]["best"], cur_tests[r["id"]]["laps"]) for r in rows
           if r["id"] in prior and r["id"] in cur_tests and cur_tests[r["id"]]["best"] and cur_tests[r["id"]]["laps"] >= MIN_FIT_LAPS]
    if len(fit) >= 8:
        A = np.array([[1.0, p, math.log(n)] for p, _, n in fit]); y = np.array([b for _, b, _ in fit])
        (c0, k1, g1), *_ = np.linalg.lstsq(A, y, rcond=None)
        res = y - A @ np.array([c0, k1, g1]); sd = float(res.std(ddof=3))
        r2 = float(1 - (res ** 2).sum() / ((y - y.mean()) ** 2).sum())
    else:  # too few test times yet: scale the index to the track, average learning effect
        y = [b for _, b, _ in fit]
        base = st.median(y) if y else 110.0
        c0, k1, g1, sd, r2 = base, base, -0.3, 0.8, None
    line = lambda p, n: c0 + k1 * p + g1 * math.log(max(n, 1))

    # laps still to come before the race: remaining evening test sessions + race qualifying
    days_left = max(0, (_dt(cur_start).date() - fetched.date()).days - (1 if fetched.hour >= 19 else 0))
    pairs = [(d, v) for d in T.get(cur_track, {"drivers": []})["drivers"] for v in d["best_per_day"] if v is not None]
    per_day = max(8.0, sum(d["laps"] for d in cur_tests.values()) / max(1, len(pairs)))
    extra = days_left * per_day + QUALI_LAPS

    # 4. Splits: official split from race results, else the prequal rank
    official = {}
    for x in sorted(race_rows, key=lambda x: x["subsession_id"] or 0):
        official[x["cust_id"]] = x["split"]
    people = []
    for r in rows:
        sp = official.get(r["id"]) or (math.ceil(r["now"] / SPLIT_SIZE) if r.get("now") else None)
        if not sp:
            continue
        team, entry_car = team_of(r)
        d = cur_tests.get(r["id"], {})
        best, n = d.get("best"), d.get("laps", 0) or 0
        p = prior.get(r["id"], (None, 0))[0]
        if p is None:
            mu, sig, w = None, sd * 1.5, 0.0
        else:
            w = n / (n + PRIOR_LAPS) if best else 0.0
            mu = line(p, n + extra) + (w * (best - line(p, n)) if best else 0.0)
            sig = sd * (1 - 0.5 * w)
        people.append(dict(r=r, split=sp, best=best, laps=n, mu=mu, sig=sig, w=w, prior=p, n_events=prior.get(r["id"], (None, 0))[1],
                           car=d.get("car") or entry_car, team=team, days=d.get("best_per_day")))

    rnd = np.random.default_rng(seed)
    splits = []
    for sp_no in sorted({p["split"] for p in people}):
        ms = [p for p in people if p["split"] == sp_no]
        if len(ms) < 5:
            continue
        fallback = st.median(p["mu"] for p in ms if p["mu"] is not None)
        mu = np.array([p["mu"] if p["mu"] is not None else fallback for p in ms]); sg = np.array([p["sig"] for p in ms])
        draw = rnd.normal(mu, sg, size=(N_SIM, len(ms)))
        for j, p in enumerate(ms):
            if p["best"]:
                draw[:, j] = np.minimum(draw[:, j], p["best"])
        srt = np.sort(draw, axis=1)
        order = np.argsort(draw, axis=1)
        rankpos = np.empty_like(order); rankpos[np.arange(N_SIM)[:, None], order] = np.arange(1, len(ms) + 1)[None, :]
        qs = lambda a, q: round(float(np.quantile(a, q)), 3)
        band = lambda a: dict(p10=qs(a, .1), p50=qs(a, .5), p90=qs(a, .9))
        timed = sorted((p for p in ms if p["best"]), key=lambda p: p["best"])
        target = band(srt[:, 2])
        out = []
        for j, p in enumerate(ms):
            r = p["r"]
            exp = dict(band(draw[:, j]), mean=round(float(draw[:, j].mean()), 3))
            out.append(dict(
                name=r["name"], car_number=r["num"], irating=r["ir"], team=p["team"], is_team=p["team"] == TEAM, car=p["car"],
                prequal_position=r.get("now"), prequal_best=r.get("qBest"), pace_index=(round(p["prior"] * 100, 2) if p["prior"] is not None else None),
                history_events=p["n_events"], best=p["best"], laps=p["laps"], best_per_day=p["days"],
                rank_now=(timed.index(p) + 1) if p["best"] else None,
                expected_pace=exp, estimated_only=not p["best"],
                gap_to_target_now=(round(p["best"] - target["p50"], 3) if p["best"] else None),
                gap_to_target_expected=round(exp["mean"] - target["p50"], 3),
                chance_top3=round(float((rankpos[:, j] <= 3).mean() * 100), 1),
                chance_win=round(float((rankpos[:, j] == 1).mean() * 100), 1)))
        out.sort(key=lambda d: (d["best"] is None, d["best"] or 0, d["expected_pace"]["mean"]))
        lo = (sp_no - 1) * SPLIT_SIZE + 1
        splits.append(dict(split=sp_no, shown=sp_no in SHOW_SPLITS, prequal_from=lo, prequal_to=lo + len(ms) - 1, members=len(ms),
                           with_time=len(timed), now=dict(p1=timed[0]["best"] if timed else None,
                                                          p3=timed[2]["best"] if len(timed) >= 3 else None,
                                                          p10=timed[9]["best"] if len(timed) >= 10 else None),
                           target=target, winner_pace=band(srt[:, 0]), top10_pace=band(srt[:, min(9, len(ms) - 1)]), drivers=out))

    team_rows = [dict(d, split=S["split"], target=S["target"]["p50"]) for S in splits for d in S["drivers"] if d["is_team"]]
    team_rows.sort(key=lambda d: (d["split"], d["expected_pace"]["mean"]))
    fast = min((p for p in people if p["best"]), key=lambda p: p["best"], default=None)

    # Keep a record of every event in data/history (re-written from the season data on every run)
    hdir = ROOT / "data" / "history"; hdir.mkdir(parents=True, exist_ok=True)
    pv = [dict(cust_id=r["id"], name=r["name"], prequal_best=r["qBest"], position=r["now"], split=math.ceil(r["now"] / SPLIT_SIZE),
               pace_index=round((r["qBest"] / q_med - 1) * 100, 3)) for r in sorted(ranked, key=lambda r: r["now"])]
    json.dump(dict(id="prequal-vir", kind="prequal", track="Virginia International Raceway – Full Course", reference=q_med, drivers=pv),
              open(hdir / "prequal-vir.json", "w"), ensure_ascii=False, indent=1)
    names = {r["id"]: r["name"] for r in rows}
    for s, tr in rounds:
        tt = T.get(tr); rr = [x for x in race_rows if x["track"] == tr]
        if not tt and not rr:
            continue
        rec = dict(id=f"{s[:10]}-{_slug(tr)}", track=tr, race_start=s, fetched_at=tests["fetched_at"],
                   tests=dict(days=tt["days"], sessions_used=tt["sessions_used"],
                              drivers=[dict(d, name=names.get(d["cust_id"])) for d in tt["drivers"]]) if tt else None,
                   race=[dict(x, name=names.get(x["cust_id"])) for x in rr])
        json.dump(rec, open(hdir / f"{rec['id']}.json", "w"), ensure_ascii=False, indent=1)

    return dict(
        round=round_no, track=cur_track, race_start=cur_start, team=TEAM,
        test_days=T.get(cur_track, {}).get("days", []), test_sessions=len(T.get(cur_track, {}).get("sessions_used", [])),
        test_drivers=sum(1 for d in cur_tests.values() if d["best"]), test_laps=sum(d["laps"] for d in cur_tests.values()),
        fastest=(dict(name=fast["r"]["name"], time=fast["best"], car=fast["car"], split=fast["split"], team=fast["team"]) if fast else None),
        model=dict(
            description=("Pace-index per rijder = procent sneller of trager dan de mediaan van het veld, uit de VIR-prequal en eerder verreden races. "
                         "Lijn voor deze baan: beste testronde = c + k × pace-index + g × ln(ronden). Verwachting op racedag: de lijn bij de ronden die een rijder "
                         f"dan heeft, plus zijn eigen afwijking (50% bij {PRIOR_LAPS} ronden). Een gereden ronde kan niet trager worden. "
                         "Target = derde snelste tijd in de split, uit " + f"{N_SIM:,}".replace(",", ".") + " simulaties."),
            c=round(float(c0), 3), k=round(float(k1), 3), g=round(float(g1), 4), residual_sd=round(sd, 3), r2=(round(r2, 3) if r2 is not None else None),
            fit_n=len(fit), test_days_left=days_left, expected_extra_laps=round(extra, 1), prior_laps=PRIOR_LAPS,
            pace_definition="snelste ronde (kwalificatie-niveau); racepace volgt zodra er raceresultaten zijn"),
        history=history_events, splits=splits, team_drivers=team_rows)
