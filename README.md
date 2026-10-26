# f1-telemetry

[![tests](https://github.com/JohanStefanes/f1-telemetry/actions/workflows/tests.yml/badge.svg)](https://github.com/JohanStefanes/f1-telemetry/actions/workflows/tests.yml)

A small Python pipeline for Formula 1 car telemetry. It downloads data for two drivers,
checks it for errors, stores it in SQLite and compares their fastest laps.

**[Open the live report](https://johanstefanes.github.io/f1-telemetry/report.html)**

![Report: lap times and telemetry for Hülkenberg vs Bortoleto, 2026 US GP](docs/report.png)

## How it works

```
OpenF1 API  →  load  →  validate  →  SQLite  →  compare  →  HTML report
```

1. **Load:** car data (speed, RPM, gear, throttle, brake, DRS, ~4 samples per second) and lap times from the free [OpenF1](https://openf1.org) API.
2. **Prepare:** assign every sample to its lap and work out distance from the start line using speed over time.
3. **Validate:** flag bad samples (see below).
4. **Store:** samples, laps and found issues go into `telemetry.db`.
5. **Compare:** fastest comparable lap of each driver: time gap along the track, sectors, speed, throttle, brake, gear.

## Run it

You need [uv](https://docs.astral.sh/uv/).

```bash
uv run python -m f1telemetry --year 2026 --location Austin --drivers HUL BOR
uv run python -m f1telemetry.report --title "2026 United States GP · Race"
uv run pytest
```

The first command downloads and stores the data. The second writes `report.html`, which you open in a browser.

## Result: 2026 US GP, Hülkenberg vs Bortoleto (Audi)

Bortoleto's best lap was **1.93 s faster** (both on lap 53), most of it in sector 2.

| | Lap time | S1 | S2 | S3 | Top speed |
|---|---|---|---|---|---|
| HUL | 100.323 s | 26.732 | 39.915 | 33.676 | 318 km/h |
| BOR | 98.393 s | 26.364 | 39.010 | 33.019 | 321 km/h |

## Validation

42,898 samples over 111 laps were checked:

| Check | Rule | Flagged |
|---|---|---|
| Missing value | speed, RPM, gear, throttle or brake is empty | 0 |
| Out of range | speed 0–380 km/h, RPM 0–15,500, gear 0–8, throttle and brake 0–100 (OpenF1 sends `104` for invalid values) | 0 |
| Time order | timestamp not later than the one before | 0 |
| Dropout, feed | gap over 1 s, and every other car has a gap at the same moment (±0.5 s) | 124 |
| Dropout, car | gap over 1 s that only this car has | 0 |

All 124 dropouts (62 per car) are feed dropouts: both cars lose data at exactly the same
time, so the cause is the data feed, not a sensor on either car.

**Distance check:** distance is not in the data, so it is calculated from speed. The
calculated lap is on average 5,437 m long, against the official 5,513 m for Austin
(−1.4 %). About 12 m of that is the last ~0.2 s of each lap after the final sample;
the rest is likely the 4 Hz sample rate and the racing line being shorter than the
measured centre line.

## Design decisions

- **OpenF1, not FastF1:** FastF1 now needs an F1 account for live-timing data. OpenF1 is free and open.
- **SQLite:** one file, no server, and every tool can read it.
- **1 s dropout limit:** samples arrive every ~0.25 s, so 1 s means at least three missing samples.
- **Lap 1 and pit-out laps excluded from comparison:** they start from the grid or the pit lane, so their times say nothing about pace.

## Limits

- About 4 samples per second: OpenF1's rate, far below the car's real sensor rate.
- Distance is estimated from speed, not measured, so small offsets show up as spikes in the time gap at braking points.
- Two drivers per run.

## Next steps

- Compare several sessions or races.
- Alert when a feed dropout happens during a live session.
- Use OpenF1's car position data for a track map.

## Built with

Python 3.12, pandas, numpy, SQLite, Plotly. Seven pytest tests cover validation, dropout classification, distance, lap comparison and the report.

---

Not affiliated with Formula 1, the FIA or Audi. Data from [OpenF1](https://openf1.org), an unofficial API.
MIT licence · [Johan Stefanes](https://johanstefanes.ch)
