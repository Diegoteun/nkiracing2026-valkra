# CLAUDE.md — NK iRacing 2026 · Valkra Performance

Lees dit bestand **altijd** bij start van een sessie, bij elke **nieuwe run**, en vóór je `model/`, `data/`, `public/` of de dashboard-HTML wijzigt.

---

## 1. Project in één zin

Dashboard voor **Valkra Performance** over het **NK iRacing 2026** (league SRVN.nl iRacing, powered by KNAF). Eén JSON voedt de site. Prequal (VIR) is afgerond en gearchiveerd; de focus is de **komende race** (Suzuka = ronde 1 van 4).

**Repo (GitHub):** `Diegoteun/nkiracing2026-valkra`  
**Live JSON (raw):**  
`https://raw.githubusercontent.com/Diegoteun/nkiracing2026-valkra/main/data/valkra-nk-prequal.json`  
**Vercel:** serveert `public/` (`index.html` + `assets/`). Geen aparte upload-API.

---

## 2. Trigger: “nieuwe run”

Wanneer de gebruiker **nieuwe run** vraagt:

1. Data ophalen via ingelogde iRacing (`fetch_iracing.js`).
2. Model opnieuw rekenen (`ingest.py` → `build.py`).
3. Committen en pushen naar `main`.
4. Vercel is ~1 min live; raw JSON op GitHub cachet ~5 min.

**Stop** bij falende ingest/build. Geen force-push, geen `--no-verify`, geen secrets in commits.

### Stap-voor-stap

```text
1. Open https://members-ng.iracing.com (ingelogd).
2. Draai model/fetch_iracing.js (browserconsole of automatisering).
   → één JSON-string, versie 3, met check-object. Ook als window.__valkraInput.
3. Sla die tekst op als bestand (bijv. /tmp/valkra-fetch.json).
4. python3 model/ingest.py <bestand>
5. python3 model/build.py
6. git add … && git commit && git push origin main
```

### Dependencies

- Python **3.9+**, **numpy**
- iRacing-sessie met cookies (fetch moet `credentials: "include"` kunnen gebruiken op members-ng)

### IDs in fetch_iracing.js

| Constante | Waarde | Betekenis |
| :--- | :--- | :--- |
| `LEAGUE_ID` | `15445` | SRVN.nl iRacing (Powered by KNAF) |
| `TEST_SEASON` | `138636` | NK iRacing 2026 prequal + testsessies |

Fetch haalt op: ledenlijst (`m`), tests per baan behalve VIR (`t`), raceresultaten split-seizoenen (`r`), schema (`sched`). VIR-prequal wordt **niet** opnieuw opgehaald.

### Wat ingest schrijft / niet schrijft

| Bestand | Actie |
| :--- | :--- |
| `model/input/roster.json` | overschrijven |
| `model/input/tests.json` | overschrijven |
| `model/input/races.json` | overschrijven |
| `model/input/schedule.json` | overschrijven |
| `model/input/laps.json` | **niet aanraken** (definitieve VIR-prequal) |

Ingest weigert input als `v !== 3` of als een controlegetal (`check`) niet klopt.

### Wat build schrijft

| Output | Inhoud |
| :--- | :--- |
| `data/valkra-nk-prequal.json` | volledige payload (prequal-archief + `race`) |
| `data/valkra-nk-prequal-rijders.csv` | rijderslijst |
| `data/history/…` | archief per race + `prequal-vir.json` (via race_model) |
| `site/valkra-nk-prequal.html` | dashboard (embedded JSON + fetch raw URL) |
| `public/index.html` | zelfde dashboard voor Vercel |
| `site/assets/` ← kopie van `public/assets/` | Valkra-logo’s + **brand logos** |

Build **faalt** als `public/assets/brands/` ontbreekt of leeg is.

### Check na een run

- [ ] `meta.generated_at` is van deze run
- [ ] `meta.prequal_closed` is `true` (na 1 nov 2026)
- [ ] `race.round` / `race.track` kloppen met het schema
- [ ] Splits 1–2 hebben testdata / drivers als die er zijn
- [ ] `public/assets/brands/` heeft logo’s; nieuwe autonamen matchen `CAR_BRANDS`
- [ ] Geen em dashes in nieuwe UI-copy; geen `/upload` teruggezet

---

## 3. Data-model (JSON)

Bestandsnaam blijft `valkra-nk-prequal.json` om historische paden/raw-URL stabiel te houden. Racedata zit onder **`race`**.

### Top-level keys

`meta`, `forecast`, `position_curve`, `race`, `drivers`, `irating_bands`, `irating_histogram`, `irating_density`, `irating_summary`

### meta (selectie)

- `generated_at`, `league`, `season`, `track` (VIR voor prequal-archief)
- `prequal_closed`, `field_size`, `simulations`, `units` (tijden in **seconden**: `103.25` = 1:43.250)

### race (actuele race-view)

| Veld | Betekenis |
| :--- | :--- |
| `round` | Rondenummer (1–4) |
| `track` | Volledige baannaam (bijv. `Suzuka International Racing Course – Grand Prix`) |
| `race_start` | Starttijd |
| `team` | `"Valkra Performance"` |
| `splits[]` | Per split: `split`, `shown`, `drivers[]`, targets, pace-stats |
| `team_drivers[]` | Valkra-rijders over splits heen |
| `fastest`, `model`, `history`, `test_*` | Samenvatting tests / model |

**Splits:** P1–P30 = split 1, P31–P60 = split 2 (uit prequal; na race 1 volgens officiële uitslag). UI toont standaard splits **1 en 2** (`SHOW_SPLITS`).

### drivers[] (prequal-archief)

Per rijder o.a. iRating, licentie, beste tijd, ronden, `time_status`, `prequal_position_now`, `expected_prequal` / `expected_position`, `chance_split1` / `chance_split2`.

### Lokale preview

```bash
python3 -m http.server 8765 --directory public
# → http://127.0.0.1:8765/
```

Optioneel vóór de pagina:  
`window.VALKRA_PREQUAL_CONFIG = { dataUrl: "…" }`  
`#beheer` toont alleen lokale JSON-import (geen server-upload).

---

## 4. Seizoen & tabs

| Datum (Europe/Amsterdam) | Default-tab bij page load |
| :--- | :--- |
| tot en met 5 nov 2026 | **Ronde 1** |
| vanaf **6** nov 2026 | Ronde 2 |
| vanaf **13** nov 2026 | Ronde 3 |
| vanaf **20** nov 2026 | Ronde 4 |

Code: `ROUND_SWITCH` / `defaultViewId()` in `model/template.html`.  
Tabs: Prequali | Ronde 1…4. Prequali is archief, **niet** de starttab. Handmatige tabkeuze blijft alleen in die browsersessie (geen localStorage voor view).

Huidige schema-voorbeeld (kan wijzigen na fetch):

- Ronde 1: Suzuka GP — race start ~`2026-11-05T18:30:00Z` (alle 4 splits)
- Ronde 2: **Zandvoort**. Zonder tests: `prior_forecast` (index uit prequal + Suzuka → top-3-kansen + relatief gat, geen absolute rondetijden). Met tests: normale racepace.
- Ronden 3–4: placeholder tot league ze plant (`kind: "soon"` in UI)

---

## 5. Model (kort)

### Prequal (`build.py`, archief)

- Tempo vs iRating; boven 7000 iRating vlakker; 10k-mediaan ~1:42.30; floor 1:42.25
- Poging = practice + gemeten prequal-offset (±0,28 s ≥4k, ±0,45 s daaronder)
- 20k + scenario-simulaties; na `PREQUAL_END` (`2026-11-01`) geen imputatie meer — tijden zijn final

### Race (`race_model.py`)

1. Komende race = eerstvolgende geplande start na `fetched_at`, anders laatste. Is de laatste race al gereden en staat er niets nieuws in het schema, dan is die race een uitslag (`race.track = null`, `pending_tests = true`, ronde = volgende nummer) en voedt hij de pace-index. `PLANNED_ROUNDS` in `race_model.py` vult een bekende ronde aan (nu Road America op 19 nov, datum is een aanname) zolang het league-schema daar rond die datum niets heeft; `race.planned = true` toont dat in de hero
2. **Pace-index** vs veldmediaan uit VIR-prequal + eerdere races (zwaarder bij meer ronden; vol bij 20)
3. Fit op huidige baan: beste test ≈ `c + k×index + h×ln(iRating)` (geen ronden-term meer; backtest Suzuka: RMSE per rijder 0,79 → 0,56 s). Zonder testtijden voor de komende baan: `race.pending_tests = true`, geen splits
4. Verwachting racedag (eigen afwijking telt n/(n+40) mee, testronde is geen ondergrens) + 20 000 sims per split met gezamenlijke split-afwijking (±0,45 s) → target (P3), winnaar-/top-10-pace, `chance_top3`
5. Teams uit `model/teams.csv` (koppeling startnummer, anders genormaliseerde naam)

Constanten o.a.: `TEAM = "Valkra Performance"`, `N_SIM = 20000`, `SPLIT_SIZE = 30`, `SHOW_SPLITS = (1, 2)`, `QUALI_LAPS = 5`.

---

## 6. UI / design (niet stukmaken)

**Enige bron:** `model/template.html`. Nooit alleen `public/index.html` of `site/valkra-nk-prequal.html` editen — die zijn build-output.

Tokens: `design/tokens.json` (Poppins, `#feea27`, light/dark tokens; **UI is light-only**).

### Visuele regels

- Light Apple-achtige **glass** UI, gele gloed (`#feea27`) spaarzaam: ambient glow, Valkra-rij streep links, active tab wash
- Geen dark mode forceren; geen paarse AI-defaults; geen em dashes (`—`) in copy (gebruik ASCII `-` of herformuleer)
- Geen FULL-CAPS eyebrows; “NK iRacing 2026” subtiel naast logo
- **Eén** `.shell.glass`-blok: hero + rondetabs + “Wat betekenen deze cijfers?”
- Active tab: gele achtergrondwash, **geen** `border-bottom`
- Tabellen: duidelijke kolommen; split-switch 1/2; verborgen scrollbars op table boxes
- Auto-iconen compact (`object-fit: contain`, max ~40×22)
- Valkra-logo: `public/assets/valkra-logo.png` (zwart op transparant), geen gele pill achter logo

### Views

| View | Inhoud |
| :--- | :--- |
| Race (`#view-race`) | Tiles, Valkra-blok, veld-tabel, target/winnaar/top10 |
| Prequal (`#view-prequal`) | Eindstand VIR, split-kansen |
| Soon (`#view-soon`) | Placeholder ronde zonder baan/data |

### Help-teksten (kern)

- **Target** — pace voor top 3 in die split op racedag  
- **Beste** — snelste testronde  
- **Verwacht** — model-inschatting racedag  
- **Gat** — verwacht − target (≤0 = binnen target)  
- **Top 3** — gesimuleerde podiumkans  

### Merklogo’s (kritisch bij nieuwe data)

- Bestanden: `public/assets/brands/` (bron); build kopieert naar `site/assets/brands/`
- Match in JS: array `CAR_BRANDS` (merk + model-aliassen: 296, 911/992, M4, 720S, Huracán, NSX, Z06, R8, Vantage, Mustang, …)
- URL via `brandSrc()` + `document.baseURI` zodat relatieve paden blijven werken
- **Nieuw merk** zonder bestand: logo toevoegen + `CAR_BRANDS`-regel + rebuild
- Bekende merken met nieuwe modelnaam moeten blijven matchen op de bestaande regex

Huidige logo-bestanden o.a.: Ferrari, Porsche, Mercedes, BMW, McLaren, Lamborghini, Acura, Honda, Chevrolet, Audi, Aston Martin, Lexus, Ford.

---

## 7. Bestandskaart

```text
CLAUDE.md                 ← dit runbook (altijd lezen)
README.md                 ← menselijke documentatie
design/tokens.json        ← design tokens
model/
  fetch_iracing.js        ← iRacing BFF fetch (v3)
  ingest.py               ← validatie → model/input/
  build.py                ← prequal-sim + HTML + assets
  race_model.py           ← racepace / targets / history
  teams.csv               ← inschrijvingen (team, auto, nummer)
  template.html           ← dashboard-bron
  input/
    roster.json
    laps.json             ← VIR prequal (IMMUTABLE na close)
    tests.json
    races.json
    schedule.json
data/
  valkra-nk-prequal.json  ← gepubliceerde payload
  valkra-nk-prequal-rijders.csv
  history/                ← prequal-vir + per-race JSON
public/                   ← Vercel root
  index.html
  assets/
    valkra-logo.png
    valkra-logo-white.png
    valkra-logo-black.png
    valkra-mark.svg
    brands/*              ← GT3 merklogo’s (verplicht)
site/
  valkra-nk-prequal.html
  assets/                 ← kopie na build
```

---

## 8. Git / deploy

- Branch: `main`
- Na push: Vercel deploy van `public/` + site leest raw JSON
- Commitberichten: kort, waarom (NL of EN consistent met recente history)
- **Niet** terugzetten: `/upload`, `api/upload.js`, `vercel.json` upload-rewrite, `UPLOAD_PASSWORD` / upload-env

---

## 9. Harde “doe niet”

1. `model/input/laps.json` overschrijven of prequal opnieuw “open” rekenen alsof die nog loopt.
2. Alleen generated HTML editen i.p.v. `model/template.html`.
3. Brand-logos map leegmaken of copy-stap in `build.py` verwijderen.
4. Upload-flow of wachtwoord-API herintroduceren.
5. Em dashes, full-caps eyebrows, of layout die hero/tabs/help uit elkaar trekt.
6. Force-push / hooks skippen zonder expliciete gebruikersvraag.

---

## 10. Snelle diagnose

| Symptoom | Check |
| :--- | :--- |
| Oude stand op site | raw URL + GitHub-cache; hard refresh; `generated_at` |
| Lege ronde 2–4 | normaal tot schema/tests bestaan; tab = `soon` |
| Kapotte auto-iconen | `public/assets/brands` + `CAR_BRANDS` + rebuild |
| Ingest faalt | `v: 3` en `check.*` vs payload |
| Build faalt op brands | vul `public/assets/brands/` |
| Verkeerde default-tab | datum Amsterdam vs `ROUND_SWITCH` |
| Logo Valkra vies/geel vlak | gebruik `valkra-logo.png` (zwart/transparant), geen achtergrondpill |
