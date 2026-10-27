// Haalt de invoer voor model/build.py op uit de iRacing Data API.
// Draai dit in de browserconsole (of via een browser-automatisering) op een tabblad van
// https://members-ng.iracing.com terwijl je bent ingelogd. Het resultaat is een object met
// { roster, laps }: sla die op als model/input/roster.json en model/input/laps.json.

(async () => {
  const LEAGUE_ID = 15445;   // SRVN.nl iRacing (Powered by KNAF)
  const SEASON_ID = 138636;  // NK iRacing 2026
  const get = async path => {
    const j = await (await fetch("/bff/pub/proxy/data/" + path, { credentials: "include" })).json();
    return j.link ? await (await fetch(j.link)).json() : j;
  };

  const league = await get(`league/get?league_id=${LEAGUE_ID}&include_licenses=true`);
  const members = league.roster.map(m => {
    const sc = (m.licenses || []).find(l => l.category === "sports_car") || {};
    const group = sc.group_name || "";
    return {
      cust_id: m.cust_id,
      name: m.display_name,
      car_number: m.car_number || null,
      irating: sc.irating,
      license: group === "Rookie" ? "R" : group.replace("Class ", ""),
      safety_rating: sc.safety_rating
    };
  });

  const season = await get(`league/season_sessions?league_id=${LEAGUE_ID}&season_id=${SEASON_ID}`);
  const done = (season.sessions || []).filter(s => s.subsession_id && s.has_results);
  const per = {};
  let track = null;
  for (const s of done) {
    const r = await get("results/get?subsession_id=" + s.subsession_id);
    track = track || (r.track ? `${r.track.track_name} – ${r.track.config_name || ""}`.trim() : null);
    for (const sr of r.session_results || []) {
      const isQual = sr.simsession_type_name.includes("Qual");
      for (const x of sr.results || []) {
        const o = per[x.cust_id] = per[x.cust_id] || { cust_id: x.cust_id, practice_best: null, practice_laps: 0, prequal_best: null, prequal_laps: 0, prequal_sessions_used: 0 };
        const t = x.best_lap_time > 0 ? +(x.best_lap_time / 1e4).toFixed(3) : null;
        if (isQual) {
          o.prequal_sessions_used += 1;
          o.prequal_laps += x.laps_complete || 0;
          if (t != null && (o.prequal_best == null || t < o.prequal_best)) o.prequal_best = t;
        } else {
          o.practice_laps += x.laps_complete || 0;
          if (t != null && (o.practice_best == null || t < o.practice_best)) o.practice_best = t;
        }
      }
    }
  }

  const fetched_at = new Date().toISOString();
  const roster = { fetched_at, league_id: LEAGUE_ID, league_name: league.league_name, season_id: SEASON_ID, season_name: "NK iRacing 2026", category: "sports_car", members };
  const laps = { fetched_at, track, sessions_used: done.map(s => s.subsession_id), drivers: Object.values(per) };
  window.__valkraInput = { roster, laps };
  return JSON.stringify({ roster, laps });
})();
