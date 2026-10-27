// Haalt de invoer voor model/build.py op uit de iRacing Data API.
// Draai dit in een ingelogd tabblad op https://members-ng.iracing.com (browserconsole of automatisering).
// Het resultaat is één compacte JSON-tekst met een controlegetal. Sla die op als bestand en draai:
//   python3 model/ingest.py <bestand>
// Dat controleert de tekst en schrijft model/input/roster.json en model/input/laps.json.

(async () => {
  const LEAGUE_ID = 15445;   // SRVN.nl iRacing (Powered by KNAF)
  const SEASON_ID = 138636;  // NK iRacing 2026
  const get = async path => {
    const j = await (await fetch("/bff/pub/proxy/data/" + path, { credentials: "include" })).json();
    if (j.error) throw new Error(path + ": " + (j.message || j.error));
    return j.link ? await (await fetch(j.link)).json() : j;
  };

  const league = await get(`league/get?league_id=${LEAGUE_ID}&include_licenses=true`);
  const m = league.roster.map(x => {
    const sc = (x.licenses || []).find(l => l.category === "sports_car") || {};
    const group = sc.group_name || "";
    return [x.cust_id, x.display_name, x.car_number || null, sc.irating, group === "Rookie" ? "R" : group.replace("Class ", ""), sc.safety_rating];
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
        const o = per[x.cust_id] = per[x.cust_id] || [x.cust_id, null, 0, null, 0, 0];
        const t = x.best_lap_time > 0 ? x.best_lap_time / 1e4 : null;
        if (isQual) {
          o[5] += 1; o[4] += x.laps_complete || 0;
          if (t != null && (o[3] == null || t < o[3])) o[3] = t;
        } else {
          o[2] += x.laps_complete || 0;
          if (t != null && (o[1] == null || t < o[1])) o[1] = t;
        }
      }
    }
  }
  const l = Object.values(per);
  const check = {
    members: m.length,
    drivers: l.length,
    irating_sum: m.reduce((s, x) => s + (x[3] || 0), 0),
    laps_sum: l.reduce((s, x) => s + x[2] + x[4], 0),
    time_sum: Math.round(l.reduce((s, x) => s + (x[1] || 0) + (x[3] || 0), 0) * 1e4)
  };
  const out = { v: 1, fetched_at: new Date().toISOString(), league_id: LEAGUE_ID, league_name: league.league_name,
    season_id: SEASON_ID, season_name: "NK iRacing 2026", track, sessions: done.map(s => s.subsession_id), m, l, check };
  window.__valkraInput = out;
  return JSON.stringify(out);
})();
