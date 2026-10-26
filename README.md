# f1-telemetry

A small data pipeline for Formula 1 car telemetry: ingest, validate, store and compare.

```
OpenF1 API ──► ingest ──► validate ──► SQLite ──► compare
 car data      assign      range,       samples,    fastest lap,
 + laps        samples     missing,     laps,       sectors,
               to laps,    time order,  issues      speed by
               distance    dropouts                 track segment
```

## Run

```bash
uv run python -m f1telemetry --year 2026 --location Austin --drivers HUL BOR
uv run python -m f1telemetry.report --title "2026 United States GP · Race"
uv run pytest
```

The second command writes `report.html`, a single-file report you open in the browser:
lap times over the race (dropout laps marked), speed, throttle, brake and gear by distance
for any two laps with the speed delta between them, sector times, and the data-quality
counts. Click a lap in the lap-time chart to load it.

## Result: 2026 United States GP, Hülkenberg vs Bortoleto (Audi)

| | |
|---|---|
| Telemetry samples processed | 42,898 (~4 Hz, median 0.24 s between samples) |
| Laps | 111 (106 comparable: no lap 1, no pit-out laps) |
| Flagged samples | 124 dropouts > 1 s, in 39 laps per driver |
| Runtime | ~7 s end to end |

Fastest comparable lap, lap 53 for both:

| | Lap time | S1 | S2 | S3 | Top speed | Full throttle |
|---|---|---|---|---|---|---|
| HUL | 100.323 s | 26.732 | 39.915 | 33.676 | 318 km/h | 48.1 % |
| BOR | 98.393 s | 26.364 | 39.010 | 33.019 | 321 km/h | 49.3 % |

Bortoleto was 1.93 s faster, most of it in sector 2 (−0.905 s).

The dropouts point to the data feed rather than either car's sensors: each car has 62
gaps over 1 s, and all 62 start at the same session time in both cars (0.0 s apart). They
fall in 39 laps per driver; four laps differ (10/11 and 50/51) only because the two cars
crossed the line at different moments.

## Validation checks

- Missing values: speed, RPM, gear, throttle, brake
- Out of physical range (OpenF1 reports `104` for invalid throttle/brake)
- Timestamps that do not increase
- Gaps over 1 s between samples (dropouts)

## Notes

- Data: [OpenF1](https://openf1.org), free historical API. FastF1 now needs an F1 account
  for live-timing data, so this pipeline reads OpenF1 directly.
- Distance is integrated from speed over time per lap; OpenF1 car data has no distance channel.
