# nkiracing2026-valkra

Prequal-data en voorspelling voor het NK iRacing 2026 (SRVN.nl, powered by KNAF), voor de website van Valkra Performance.

## Voor de website

| Bestand | Wat |
| :--- | :--- |
| `site/valkra-nk-prequal.html` | Het dashboard. Eén bestand, zonder build-stap. |
| `data/valkra-nk-prequal.json` | Alle data. Dit bestand wordt bijgewerkt. |
| `data/valkra-nk-prequal-rijders.csv` | Dezelfde rijderslijst als spreadsheet. |

De pagina haalt bij het openen de laatste JSON op via:

```
https://raw.githubusercontent.com/Diegoteun/nkiracing2026-valkra/main/data/valkra-nk-prequal.json
```

Een update in deze repo is dus zonder nieuwe deploy zichtbaar op de site. GitHub cachet raw-bestanden tot ongeveer 5 minuten. Kan de JSON niet geladen worden, dan toont de pagina de ingebouwde kopie van de laatste build.

Ergens anders vandaan laden kan met een regel vóór de pagina:

```html
<script>window.VALKRA_PREQUAL_CONFIG = { dataUrl: "/pad/naar/valkra-nk-prequal.json" };</script>
```

Met `#beheer` achter de URL verschijnt de knop **JSON importeren**. Die laat een ander JSON-bestand zien in de eigen browser. Met `uploadUrl` in de config stuurt de knop het bestand ook naar een endpoint (POST multipart, veld `file`, met `X-CSRF-TOKEN` uit `<meta name="csrf-token">` als die er is).

### Belangrijkste velden in de JSON

- `meta.generated_at`: stand van de data.
- `forecast.split1_range` en `forecast.split2_range`: verwachte grens voor split 1 (P30) en split 2 (P60), als `low`, `likely` en `high`, in seconden.
- `forecast.fastest_so_far`: snelste tijd tot nu.
- `drivers[]`: per rijder iRating, licentie, beste tijd, ronden, `time_status`, `expected_prequal` en `expected_position` (p10/p50/p90), en `chance_split1`/`chance_split2` in procenten.
- `position_curve`: verwachte positie per prequal-tijd.
- `irating_bands`, `irating_histogram`, `irating_density`, `irating_summary`: voor de tabellen en de verdeling.

Alle tijden zijn seconden: `103.25` is 1:43.25.

## Data bijwerken

1. Open een ingelogd tabblad op members-ng.iracing.com en draai `model/fetch_iracing.js`.
2. Sla `roster` en `laps` uit het resultaat op als `model/input/roster.json` en `model/input/laps.json`.
3. Draai `python3 model/build.py` (Python 3.9+ met numpy). Dat schrijft `data/` en `site/` opnieuw.
4. Commit en push naar `main`.

Tijdens de prequal-week gebeurt dit elke ochtend om 10:00 automatisch.

## Model in het kort

- Tempo per iRating, gefit op rijders met 20 of meer ronden. Boven 7.000 iRating loopt de curve vlakker, zodat een rijder van 10.000 in de prequal mediaan 1:42.30 rijdt.
- Wie minder dan 20 ronden of nog geen tijd heeft, krijgt dat tempo plus de spreiding van zijn iRating-groep, nooit trager dan wat hij al reed.
- Iedereen rijdt zijn resterende prequal-sessies (maximaal twee). Een poging is de beste tijd of het modeltempo plus een afwijking. Die afwijking komt uit het gemeten verschil tussen prequal en training: ±0,28 s boven 4.000 iRating, ±0,45 s daaronder.
- Geen poging is sneller dan 1:42.25. Die ondergrens en de 1:42.30 voor een 10k-rijder zijn inschattingen van het team.
- 20.000 simulaties. De bandbreedte van de grenzen komt uit extra scenario's: een deel rijdt één sessie, pogingen tot 0,2 s trager, ongeveer 100 deelnemers.

Bron: iRacing Data API. Ledenlijst en Sports Car-licenties van league 15445 en de resultaten van de league-sessies op VIR.
