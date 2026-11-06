"""
Valkra Performance · NK iRacing 2026 · pace voor de komende race

Doel: per split een overzicht van wie welke tijd heeft gereden, een inschatting van de pace op racedag voor iedereen
(ook wie nog niet testte) en een target: de pace die nodig is om mee te doen om de top 3.

Opbouw
1. Komende race: de eerstvolgende geplande race uit de split-seizoenen (baan + datum).
2. Pace-index per rijder uit de geschiedenis: hoeveel procent hij sneller of trager is dan de mediaan van het veld.
   Bronnen: de VIR-prequal en elke eerder verreden race (testsessies + kwalificatie + race op die baan).
   Een race telt zwaarder naarmate de rijder er meer ronden reed (volle weging vanaf 20 ronden).
3. Lijn voor de komende baan: beste testronde = c + k × pace-index + h × ln(iRating), gefit op alle rijders met een
   testtijd (met lichte ridge). Het aantal ronden zit er niet meer in: na Suzuka bleek dat het geen voorspellende
   waarde had op racedag, terwijl iRating dat wel had.
4. Verwachting op racedag: de lijn plus de eigen afwijking van de rijder (die telt voor n / (n + 40) mee, n = testronden).
   Een testronde is geen ondergrens: de helft van de rijders was op racedag trager dan de beste testronde.
5. Zonder testtijden op de komende baan: geen absolute rondetijden (die hangen van de baan af). Wel een
   prior-forecast uit pace-index (prequal + eerdere races): relatieve seconden t.o.v. de veldmediaan, top-3-kansen
   en gat tot P3. Zodra er genoeg tests zijn, schakelt het model over op echte baantijden.
6. 20.000 simulaties per split geven de target (derde snelste tijd in de split), de winnaars- en top-10-pace en per
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
PRIOR_LAPS = 40          # eigen afwijking telt voor 50% bij 40 testronden (backtest Suzuka)
MIN_FIT_DRIVERS = 8
RIDGE = 2.0
SPLIT_SHOCK = 0.45      # gezamenlijke afwijking van een heel split op racedag (s), uit de Suzuka-backtest
IND_SD = 0.42           # eigen onzekerheid per rijder zonder testtijd (s)
MIN_FIT_LAPS = 3
SPLIT_SIZE = 30
SHOW_SPLITS = (1, 2)
QUALI_LAPS = 5           # ronden in de 10 minuten kwalificatie op racedag


def _norm(s):
    s = re.sub(r"\d+", "", (s or "").lower())
    s = re.sub(r"[^a-zà-ÿ ]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Drop single-letter middle initials ("Patrick A Hesterman" → "patrick hesterman").
    parts = [p for p in s.split() if len(p) > 1]
    return " ".join(parts) if parts else s


def _name_keys(s):
    n = _norm(s)
    if not n:
        return set()
    parts = n.split()
    keys = {n}
    if len(parts) >= 2:
        keys.add(" ".join(sorted(parts)))  # "jelmer berends" ↔ "berends jelmer"
    return keys


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower().split(" – ")[0]).strip("-")


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_teams(path):
    if not path.exists():
        return {}, {}
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    by_num = {r["car_number"]: r for r in rows if r["car_number"] not in ("", "0")}
    by_name = {}
    for r in rows:
        for key in _name_keys(r["name"]):
            by_name.setdefault(key, r)
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
        """Resolve team + entry car from teams.csv. Prefer number, then fuzzy name. Never invent empty strings."""
        t = by_num.get(str(r["num"])) if r.get("num") not in (None, "", "0") else None
        if not t:
            for key in _name_keys(r.get("name")):
                t = by_name.get(key)
                if t:
                    break
        team = ((t or {}).get("team") or "").strip() or None
        car = ((t or {}).get("car") or "").strip() or None
        return team, car

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

    # History on disk (re-written from the season data on every run)
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


    # 3. Line for the coming track: best test lap = c + k*index + h*ln(iRating), ridge on standardised features
    ir_of = lambda r: math.log(max(r.get("ir") or 1500, 300))
    idx_vals = [v[0] for v in prior.values()]
    m_idx, s_idx = (float(np.mean(idx_vals)), float(np.std(idx_vals)) or 1.0) if idx_vals else (0.0, 1.0)
    ir_vals = [ir_of(r) for r in rows]
    m_ir, s_ir = float(np.mean(ir_vals)), float(np.std(ir_vals)) or 1.0

    def feats(r):
        p = prior.get(r["id"], (None, 0))[0]
        return np.array([1.0, ((m_idx if p is None else p) - m_idx) / s_idx, (ir_of(r) - m_ir) / s_ir])

    fit_rows = [r for r in rows if r["id"] in cur_tests and cur_tests[r["id"]]["best"] and cur_tests[r["id"]]["laps"] >= MIN_FIT_LAPS]
    pending = len(fit_rows) < MIN_FIT_DRIVERS
    if not pending:
        A = np.array([feats(r) for r in fit_rows]); y = np.array([cur_tests[r["id"]]["best"] for r in fit_rows])
        pen = np.diag([0.0, RIDGE, RIDGE])
        beta = np.linalg.solve(A.T @ A + pen, A.T @ y)
        res = y - A @ beta; sd = float(res.std(ddof=3))
        r2 = float(1 - (res ** 2).sum() / ((y - y.mean()) ** 2).sum())
        c0 = float(beta[0] - beta[1] * m_idx / s_idx - beta[2] * m_ir / s_ir)
        k1 = float(beta[1] / s_idx / 100); h1 = float(beta[2] / s_ir)   # k per 1% of index
        line = lambda r: float(feats(r) @ beta)
    else:
        sd, r2, c0, k1, h1 = None, None, None, None, None
    days_left = max(0, (_dt(cur_start).date() - fetched.date()).days - (1 if fetched.hour >= 19 else 0))

    # Race pace offsets (average race lap minus best lap, top 10 finishers) from the latest earlier race, per split
    race_off = {}
    prev = [(s_, tr) for s_, tr in rounds if (s_, tr) != (cur_start, cur_track) and any(x["track"] == tr for x in race_rows)]
    if prev:
        ptr = prev[-1][1]
        for sp in (1, 2, 3, 4):
            rr = sorted((x for x in race_rows if x["track"] == ptr and x["split"] == sp and (x["race_laps"] or 0) >= 25
                         and x["race_avg"] and x["race_best"] and x["finish"]), key=lambda x: x["finish"])[:10]
            if len(rr) >= 5:
                race_off[sp] = round(float(st.median(x["race_avg"] - x["race_best"] for x in rr)), 2)

    # Results of finished races (shown in the round tab after the race)
    rows_by_id = {r["id"]: r for r in rows}
    results = []
    for i_, (s_, tr_) in enumerate(rounds, 1):
        rr_ = [x for x in race_rows if x["track"] == tr_ and x["cust_id"] in rows_by_id]
        ran = {x["cust_id"] for x in rr_ if (x["race_laps"] or 0) > 0}
        rr_ = [x for x in rr_ if (x["race_laps"] or 0) > 0 or x["cust_id"] not in ran]   # drop DNS ghosts in a second split
        if not rr_ or (s_, tr_) == (cur_start, cur_track):
            continue
        tt_ = {d["cust_id"]: d for d in T.get(tr_, {"drivers": []})["drivers"]}
        eid_ = f"{s_[:10]}-{_slug(tr_)}"
        idx_ = {cid: next((i for e, i, _ in h if e == eid_), None) for cid, h in hist.items()}
        sps = []
        for sp in sorted({x["split"] for x in rr_}):
            ds = []
            for x in sorted((x for x in rr_ if x["split"] == sp), key=lambda x: x["finish"] or 99):
                r = rows_by_id[x["cust_id"]]
                team, entry_car = team_of(r)
                ds.append(dict(name=r["name"], car_number=r["num"], irating=r["ir"], team=team, is_team=team == TEAM,
                               car=x.get("car") or entry_car, finish=x["finish"], quali_best=x["quali_best"], race_best=x["race_best"],
                               race_avg=x["race_avg"], laps=x["race_laps"], incidents=x["incidents"],
                               practice_best=(tt_.get(x["cust_id"]) or {}).get("best"), practice_laps=(tt_.get(x["cust_id"]) or {}).get("laps", 0),
                               pace_index=(round(idx_[x["cust_id"]] * 100, 2) if idx_.get(x["cust_id"]) is not None else None)))
            sps.append(dict(split=sp, shown=sp in SHOW_SPLITS, drivers=ds,
                            podium_best=[d["race_best"] for d in ds[:3]], podium_avg=[d["race_avg"] for d in ds[:3]],
                            p3_best=ds[2]["race_best"] if len(ds) >= 3 else None, p3_avg=ds[2]["race_avg"] if len(ds) >= 3 else None,
                            winner=ds[0]["name"] if ds else None))
        results.append(dict(round=i_, track=tr_, race_start=s_, splits=sps,
                            team_drivers=[dict(d, split=sp["split"]) for sp in sps for d in sp["drivers"] if d["is_team"]]))

    # 4. Splits: official split from race results, else the prequal rank
    official = {}
    for x in sorted(race_rows, key=lambda x: x["subsession_id"] or 0):
        if (x["race_laps"] or 0) > 0 or x["cust_id"] not in official:
            official[x["cust_id"]] = x["split"]

    # Seconds per 1% pace-index, from the latest finished race (absolute track times stay unknown without tests).
    sec_per_pct = 0.35
    if prev:
        ptr = prev[-1][1]
        rb = [x["race_best"] for x in race_rows if x["track"] == ptr and x["race_best"]]
        if len(rb) >= 10:
            med_rb = st.median(rb)
            xs, ys = [], []
            for x in race_rows:
                if x["track"] != ptr or not x["race_best"] or x["cust_id"] not in prior:
                    continue
                xs.append(prior[x["cust_id"]][0] * 100)
                ys.append(x["race_best"] - med_rb)
            if len(xs) >= 10 and (max(xs) - min(xs)) > 0.2:
                # slope only: delta_time ≈ sec_per_pct * index_%
                num = sum(a * b for a, b in zip(xs, ys))
                den = sum(a * a for a in xs) or 1.0
                sec_per_pct = float(np.clip(num / den, 0.15, 0.8))

    def build_people(use_track_line):
        out = []
        for r in rows:
            sp = official.get(r["id"]) or (math.ceil(r["now"] / SPLIT_SIZE) if r.get("now") else None)
            if not sp:
                continue
            team, entry_car = team_of(r)
            d = cur_tests.get(r["id"], {})
            best, n = d.get("best"), d.get("laps", 0) or 0
            p = prior.get(r["id"], (None, 0))[0]
            if use_track_line:
                base = line(r)
                w = n / (n + PRIOR_LAPS) if best else 0.0
                mu = base + w * (best - base) if best else base
                sig = IND_SD * (1 - 0.4 * w) if best else IND_SD
            else:
                # Relative seconds vs field median (0); no absolute Zandvoort lap times.
                mu = (0.0 if p is None else p * 100 * sec_per_pct)
                w = 0.0
                sig = IND_SD
                best, n = None, 0
            out.append(dict(r=r, split=sp, best=best, laps=n, mu=mu, sig=sig, w=w, prior=p,
                            n_events=prior.get(r["id"], (None, 0))[1],
                            car=d.get("car") or entry_car, team=team, days=d.get("best_per_day")))
        return out

    if pending and not any(prior.values()):
        return dict(
            round=round_no, track=cur_track, race_start=cur_start, team=TEAM, pending_tests=True, prior_forecast=False,
            test_days=[], test_sessions=0, test_drivers=0, test_laps=0, fastest=None,
            model=dict(description="Nog geen testtijden voor deze baan en nog geen eerdere race-index. Zodra er tests of uitslagen zijn, verschijnen schattingen.",
                       c=None, k=None, h=None, g=0.0, residual_sd=None, r2=None, fit_n=len(fit_rows), test_days_left=days_left,
                       expected_extra_laps=0, prior_laps=PRIOR_LAPS, pace_definition="snelste ronde (kwalificatie-niveau)"),
            history=history_events, splits=[], team_drivers=[], results=results)

    people = build_people(use_track_line=not pending)
    prior_forecast = bool(pending)

    rnd = np.random.default_rng(seed)
    splits = []
    for sp_no in sorted({p["split"] for p in people}):
        ms = [p for p in people if p["split"] == sp_no]
        if len(ms) < 5:
            continue
        fallback = st.median(p["mu"] for p in ms if p["mu"] is not None)
        mu = np.array([p["mu"] if p["mu"] is not None else fallback for p in ms]); sg = np.array([p["sig"] for p in ms])
        draw = rnd.normal(mu, sg, size=(N_SIM, len(ms))) + rnd.normal(0, SPLIT_SHOCK, size=(N_SIM, 1))
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
            exp_rank = round(float(rankpos[:, j].mean()), 1)
            out.append(dict(
                name=r["name"], car_number=r["num"], irating=r["ir"], team=p["team"], is_team=p["team"] == TEAM, car=p["car"],
                prequal_position=r.get("now"), prequal_best=r.get("qBest"), pace_index=(round(p["prior"] * 100, 2) if p["prior"] is not None else None),
                history_events=p["n_events"], best=p["best"], laps=p["laps"], best_per_day=p["days"],
                rank_now=(timed.index(p) + 1) if p["best"] else None,
                expected_rank=exp_rank,
                expected_pace=exp, estimated_only=prior_forecast or not p["best"],
                gap_to_target_now=(round(p["best"] - target["p50"], 3) if p["best"] else None),
                gap_to_target_expected=round(exp["mean"] - target["p50"], 3),
                chance_top3=round(float((rankpos[:, j] <= 3).mean() * 100), 1),
                chance_win=round(float((rankpos[:, j] == 1).mean() * 100), 1)))
        if prior_forecast:
            out.sort(key=lambda d: (d["expected_pace"]["mean"], -d["chance_top3"]))
        else:
            out.sort(key=lambda d: (d["best"] is None, d["best"] or 0, d["expected_pace"]["mean"]))
        lo = (sp_no - 1) * SPLIT_SIZE + 1
        splits.append(dict(split=sp_no, shown=sp_no in SHOW_SPLITS, prequal_from=lo, prequal_to=lo + len(ms) - 1, members=len(ms),
                           with_time=len(timed), now=dict(p1=timed[0]["best"] if timed else None,
                                                          p3=timed[2]["best"] if len(timed) >= 3 else None,
                                                          p10=timed[9]["best"] if len(timed) >= 10 else None),
                           target=target, race_pace_offset=race_off.get(sp_no),
                           race_pace_target=({k_: round(v_ + race_off[sp_no], 3) for k_, v_ in target.items()} if sp_no in race_off else None),
                           winner_pace=band(srt[:, 0]), top10_pace=band(srt[:, min(9, len(ms) - 1)]), drivers=out))

    team_rows = [dict(d, split=S["split"], target=S["target"]["p50"]) for S in splits for d in S["drivers"] if d["is_team"]]
    team_rows.sort(key=lambda d: (d["split"], d["expected_pace"]["mean"]))
    fast = min((p for p in people if p["best"]), key=lambda p: p["best"], default=None)

    if prior_forecast:
        return dict(
            round=round_no, track=cur_track, race_start=cur_start, team=TEAM,
            pending_tests=True, prior_forecast=True,
            test_days=[], test_sessions=0, test_drivers=0, test_laps=0, fastest=None,
            model=dict(
                description=("Nog geen Zandvoort-testtijden. Schatting op pace-index uit prequal + Suzuka: relatieve seconden "
                             f"t.o.v. de veldmediaan (~{sec_per_pct:.2f} s per 1% index), top-3-kansen uit "
                             + f"{N_SIM:,}".replace(",", ".") + " simulaties. Absolute rondetijden volgen zodra er getest is."),
                c=None, k=round(sec_per_pct, 4), h=None, g=0.0, residual_sd=IND_SD, r2=None, fit_n=0,
                test_days_left=days_left, expected_extra_laps=0, prior_laps=PRIOR_LAPS,
                sec_per_pct=round(sec_per_pct, 4), race_pace_offsets=race_off,
                pace_definition="relatieve pace t.o.v. veldmediaan (geen baantijd)"),
            history=history_events, splits=splits, team_drivers=team_rows, results=results)

    return dict(
        round=round_no, track=cur_track, race_start=cur_start, team=TEAM,
        pending_tests=False, prior_forecast=False,
        test_days=T.get(cur_track, {}).get("days", []), test_sessions=len(T.get(cur_track, {}).get("sessions_used", [])),
        test_drivers=sum(1 for d in cur_tests.values() if d["best"]), test_laps=sum(d["laps"] for d in cur_tests.values()),
        fastest=(dict(name=fast["r"]["name"], time=fast["best"], car=fast["car"], split=fast["split"], team=fast["team"]) if fast else None),
        model=dict(
            description=("Pace-index per rijder = procent sneller of trager dan de mediaan van het veld, uit de VIR-prequal en eerder verreden races. "
                         "Lijn voor deze baan: beste testronde = c + k × pace-index + h × ln(iRating), gefit op de testtijden. Verwachting op racedag: "
                         f"de lijn plus de eigen afwijking van de rijder (50% bij {PRIOR_LAPS} testronden). Een testronde is geen ondergrens. "
                         "Target = derde snelste tijd in de split, uit " + f"{N_SIM:,}".replace(",", ".") + " simulaties."),
            c=round(c0, 3), k=round(k1, 4), h=round(h1, 4), g=0.0, residual_sd=round(sd, 3), r2=round(r2, 3),
            fit_n=len(fit_rows), test_days_left=days_left, expected_extra_laps=0, prior_laps=PRIOR_LAPS,
            race_pace_offsets=race_off,
            pace_definition="snelste ronde op racedag (kwalificatie of race)"),
        history=history_events, splits=splits, team_drivers=team_rows, results=results)
