// Haalt de invoer voor model/build.py op uit de iRacing Data API (versie 3: per race).
// Draai dit in een ingelogd tabblad op https://members-ng.iracing.com (browserconsole of automatisering).
// Het resultaat is één compacte JSON-tekst met controlegetallen. Sla die op als bestand en draai:
//   python3 model/ingest.py <bestand>
//
// Wat erin zit:
//   m      ledenlijst met iRating en licentie (Sports Car)
//   t      testsessies per baan uit het NK-seizoen (alles behalve VIR, dat was de prequal)
//   r      raceresultaten uit de split-seizoenen (kwalificatie, snelste en gemiddelde raceronde, uitslag)
//   sched  geplande races per split (baan en starttijd), om de komende race te bepalen
// De VIR-prequal wordt niet opnieuw opgehaald: die staat definitief in model/input/laps.json.

(async () => {
  const LEAGUE_ID = 15445;    // SRVN.nl iRacing (Powered by KNAF)
  const TEST_SEASON = 138636; // NK iRacing 2026: prequal en testsessies
  const get = async path => {
    const j = await (await fetch("/bff/pub/proxy/data/" + path, { credentials: "include" })).json();
    if (j.error) throw new Error(path + ": " + (j.message || j.error));
    return j.link ? await (await fetch(j.link)).json() : j;
  };
  const trackOf = s => s.track ? `${s.track.track_name} – ${s.track.config_name || ""}`.replace(/ – $/, "") : "?";

  const league = await get(`league/get?league_id=${LEAGUE_ID}&include_licenses=true`);
  const m = league.roster.map(x => {
    const sc = (x.licenses || []).find(l => l.category === "sports_car") || {};
    const group = sc.group_name || "";
    return [x.cust_id, x.display_name, x.car_number || null, sc.irating, group === "Rookie" ? "R" : group.replace("Class ", ""), sc.safety_rating];
  });

  // Test sessions per track
  const season = await get(`league/season_sessions?league_id=${LEAGUE_ID}&season_id=${TEST_SEASON}`);
  const tests = {};
  for (const s of (season.sessions || []).filter(s => s.subsession_id && s.has_results)) {
    const tr = trackOf(s);
    if (tr.startsWith("Virginia")) continue;
    const T = tests[tr] = tests[tr] || { days: [], sessions: [], per: {} };
    const day = s.launch_at.slice(0, 10);
    let di = T.days.indexOf(day); if (di < 0) { T.days.push(day); di = T.days.length - 1; }
    T.sessions.push(s.subsession_id);
    const r = await get("results/get?subsession_id=" + s.subsession_id);
    for (const sr of r.session_results || []) for (const x of sr.results || []) {
      const o = T.per[x.cust_id] = T.per[x.cust_id] || { id: x.cust_id, laps: 0, best: null, d: {}, car: x.car_name || null };
      const t = x.best_lap_time > 0 ? x.best_lap_time / 1e4 : null;
      o.laps += x.laps_complete || 0;
      if (t != null) { if (o.best == null || t < o.best) { o.best = t; o.car = x.car_name || o.car; } if (o.d[di] == null || t < o.d[di]) o.d[di] = t; }
    }
  }
  const t = Object.entries(tests).map(([track, T]) => ({ track, days: T.days, sessions: T.sessions,
    s: Object.values(T.per).map(o => [o.id, o.best, o.laps, T.days.map((_, i) => o.d[i] ?? null), o.car]) }));

  // Race results and schedule per split season ("NK Split N")
  const seasons = await get(`league/seasons?league_id=${LEAGUE_ID}&retired=true`);
  const splitSeasons = (seasons.seasons || []).map(x => ({ id: x.season_id, split: +((x.season_name || "").match(/Split\s*(\d+)/i) || [])[1] }))
    .filter(x => x.split);
  const r = [], sched = [];
  for (const ss of splitSeasons) {
    const S = await get(`league/season_sessions?league_id=${LEAGUE_ID}&season_id=${ss.id}`);
    for (const s of S.sessions || []) {
      sched.push([ss.split, s.launch_at, trackOf(s), s.subsession_id || null, s.has_results ? 1 : 0]);
      if (!s.subsession_id || !s.has_results) continue;
      const res = await get("results/get?subsession_id=" + s.subsession_id);
      const per = {};
      for (const sr of res.session_results || []) {
        const type = sr.simsession_type_name || "";
        const isQ = type.includes("Qual"), isR = type.includes("Race");
        if (!isQ && !isR) continue;
        for (const x of sr.results || []) {
          const o = per[x.cust_id] = per[x.cust_id] || [x.cust_id, ss.split, trackOf(s), null, null, null, 0, null, null, x.car_name || null, s.subsession_id];
          const bl = x.best_lap_time > 0 ? x.best_lap_time / 1e4 : null;
          if (isQ && bl != null) o[3] = o[3] == null ? bl : Math.min(o[3], bl);
          if (isR) {
            o[4] = bl;
            o[5] = x.average_lap > 0 ? x.average_lap / 1e4 : null;
            o[6] = x.laps_complete || 0;
            o[7] = x.finish_position_in_class != null ? x.finish_position_in_class + 1 : (x.finish_position != null ? x.finish_position + 1 : null);
            o[8] = x.incidents != null ? x.incidents : null;
          }
        }
      }
      r.push(...Object.values(per));
    }
  }

  const check = {
    members: m.length, irating_sum: m.reduce((a, x) => a + (x[3] || 0), 0),
    tracks: t.length, t_drivers: t.reduce((a, T) => a + T.s.length, 0),
    t_laps: t.reduce((a, T) => a + T.s.reduce((b, x) => b + x[2], 0), 0),
    t_time_sum: Math.round(t.reduce((a, T) => a + T.s.reduce((b, x) => b + (x[1] || 0), 0), 0) * 1e4),
    r_rows: r.length, r_laps: r.reduce((a, x) => a + (x[6] || 0), 0),
    r_time_sum: Math.round(r.reduce((a, x) => a + (x[3] || 0) + (x[4] || 0) + (x[5] || 0), 0) * 1e4),
    sched: sched.length
  };
  const out = { v: 3, fetched_at: new Date().toISOString(), league_id: LEAGUE_ID, league_name: league.league_name,
    season_name: "NK iRacing 2026", m, t, r, sched, check };
  window.__valkraInput = out;
  return JSON.stringify(out);
})();
