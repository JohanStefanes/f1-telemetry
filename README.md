# f1-telemetry

[![tests](https://github.com/JohanStefanes/f1-telemetry/actions/workflows/tests.yml/badge.svg)](https://github.com/JohanStefanes/f1-telemetry/actions/workflows/tests.yml)

A small Python pipeline for Formula 1 data. It downloads car telemetry for two drivers and
lap times for every 2026 race, checks the data for errors, stores it in SQLite, compares
the two drivers' fastest laps and makes a simple, backtested pace prediction for the rest of the season.

**[Open the live report](https://johanstefanes.github.io/f1-telemetry/report.html)**: it updates itself after
every race (see [Automatic updates](#automatic-updates)).

![Report: lap times and telemetry for Hülkenberg vs Bortoleto, 2026 US GP](docs/report.png)

## How it works

```
OpenF1 API  →  load  →  validate  →  SQLite  →  compare / predict  →  HTML report
```

1. **Load:** car data (speed, RPM, gear, throttle, brake, DRS, ~4 samples per second) and track position for one race,
   and laps, pit stops, tyres, results and weather for every completed race, from the free [OpenF1](https://openf1.org) API.
2. **Prepare:** assign every sample to its lap and work out distance from the start line using speed over time.
3. **Validate:** flag bad samples (see below).
4. **Store:** everything goes into `telemetry.db` (see [Data schema](#data-schema)).
5. **Compare:** fastest comparable lap of each driver: time gap along the track, sectors, speed, throttle, brake,
   gear, a track map coloured by the faster driver, and what happened in each braking zone.
6. **Predict:** expected race pace for every remaining race, tested on the races already run.

## Run it

You need [uv](https://docs.astral.sh/uv/).

```bash
uv run python -m f1telemetry --year 2026 --drivers HUL BOR
uv run python -m f1telemetry.season --year 2026
uv run python -m f1telemetry.report
uv run pytest
```

1. The first command downloads the telemetry of the latest race that OpenF1 has published
   (add `--location Austin` for a specific one).
2. The second downloads the laps of every completed 2026 race.
3. The third writes `report.html`, which you open in a browser.

Raw API responses are kept in `.cache/`, so reruns take about a second, and failed downloads and rate limits are retried.
Empty answers are not cached, because they usually mean OpenF1 has not published that data yet.

## Second check in C#

[`csharp/F1Check`](csharp/F1Check) is a small .NET 8 tool that reads `telemetry.db` and runs the sample
validation again, written from scratch in C#: missing values, physical ranges, time order, and dropouts
split into feed and car. It then compares its counts with the `issues` table the Python pipeline wrote,
check by check and lap by lap, and exits with an error if anything differs. Two independent
implementations that agree are much harder to get wrong than one.

```bash
dotnet run --project csharp/F1Check -- telemetry.db
dotnet test csharp/F1Check.Tests
```

On the 2026 US GP it checks all 42,898 samples and agrees with Python on every check: 124 feed dropouts,
no car dropouts, nothing missing or out of range. The automatic update runs it before publishing, so a
report is only published when both implementations agree. Ten xUnit tests cover the rules and the
comparison, and a test on a deliberately changed database confirms the tool fails when the results differ.

## Automatic updates

A scheduled GitHub Action ([`update.yml`](.github/workflows/update.yml)) runs the three commands every
Monday, Tuesday and Wednesday morning, after the Sunday race. It picks the latest race that already has
data, reloads the season, rebuilds the report and checks the validation again in C#. Only if both agree
and the report changed does it commit and publish
it, so weeks without a race leave the repository untouched. It can also be started by hand from the
Actions tab.

## Snapshot: 2026 US GP, Hülkenberg vs Bortoleto (Audi)

The live report always shows the latest race. The numbers in this README are from the United States GP
on 25 October 2026, the latest race when it was written.

Bortoleto's best lap was **1.93 s faster** (both on lap 53), most of it in sector 2.

| | Lap time | S1 | S2 | S3 | Top speed |
|---|---|---|---|---|---|
| HUL | 100.323 s | 26.732 | 39.915 | 33.676 | 318 km/h |
| BOR | 98.393 s | 26.364 | 39.010 | 33.019 | 321 km/h |

**Where on the track:** Bortoleto was faster in all seven main braking zones. Hülkenberg often braked
later (up to 24 m) but carried less speed through the corner, which cost him more than it gained. The seven
zones account for 1.70 s of the 1.93 s; the rest came on the straights.

**Tyres:** both started on softs and switched to hards; Bortoleto stopped again for softs on lap 50.
The report shows each stint and its wear (lap time lost per lap on the same set). Wear comes out
slightly negative, between −0.06 and +0.01 s per lap, because the car gains more from burning fuel
than it loses from the tyres.

## Season and prediction

18 completed 2026 races (Bahrain and Saudi Arabia were cancelled), 20,693 timed laps of all drivers,
17,431 of them comparable. Zandvoort and Kuala Lumpur were wet (rain in at least 10 % of the weather readings
during the race); the report marks them, because rain explains some of the outliers. Over the season, Bortoleto and Hülkenberg are level on race pace: each was
the faster of the two in 7 of the 14 races both finished with enough clean laps.

**Race pace** is a driver's median comparable lap, as % slower than the fastest driver in that race.
**The prediction** for the five remaining races (Mexico City, São Paulo, Las Vegas, Lusail, Yas Marina)
is a simple statistical model: the average of each driver's last 5 races. It ignores track type,
weather, upgrades, grid position and strategy, so it gives the same expected pace for every remaining
race, and it predicts pace, not finishing order. It puts both Audis at about +2.0 %, 11th and 12th on pace.

**Backtest:** each past race was predicted only from races before it, then compared with what happened.
For races further ahead, the races in between were hidden from the model too.

| Predicting | Races tested | Gap error | Order error |
|---|---|---|---|
| 1 race ahead (Mexico City) | 15 | 0.65 pp | 2.0 places |
| 2 races ahead (São Paulo) | 14 | 0.69 pp | 2.1 places |
| 3 races ahead (Las Vegas) | 13 | 0.70 pp | 2.0 places |
| 4 races ahead (Lusail) | 12 | 0.70 pp | 1.9 places |
| 5 races ahead (Yas Marina) | 11 | 0.65 pp | 1.9 places |

pp = percentage points. Simply repeating each driver's last race is off by 0.74 pp one race ahead, so
the model helps, but only a little: it is a starting point, not a forecast to bet on. The error hardly
grows further ahead, because form in 2026 has been fairly stable.

**Why the last 5 races:** the same backtest with other form windows gives 0.70 pp (last 3), 0.67 pp
(last 8) and 0.67 pp (whole season). The differences are small, so the simple choice stays.

## Validation

42,898 telemetry samples over 111 laps were checked:

| Check | Rule | Flagged |
|---|---|---|
| Missing value | speed, RPM, gear, throttle or brake is empty | 0 |
| Out of range | speed 0–380 km/h, RPM 0–15,500, gear 0–8, throttle and brake 0–100 (OpenF1 sends `104` for invalid values) | 0 |
| Time order | timestamp not later than the one before | 0 |
| Dropout, feed | gap over 1 s, and every other car has a gap at the same moment (±0.5 s) | 124 |
| Dropout, car | gap over 1 s that only this car has | 0 |

All 124 dropouts (62 per car) are feed dropouts: both cars lose data at exactly the same
time, so the cause is the data feed, not a sensor on either car.

Before validation, samples recorded outside the race laps (grid, garage, after the flag) are set
aside: 13,312 for Hülkenberg and 13,618 for Bortoleto. 1,904 and 244 of them carry invalid values,
mostly OpenF1's `104`, which never appears during the race laps.

**Cross-checks against official data** compare whole datasets with independent sources, which
catches errors in the pipeline itself:

| Check | Compared with | Result |
|---|---|---|
| Sector times add up to the lap time | OpenF1 timing | 20,520 of 20,520 laps within 10 ms |
| Lap count matches the official classification | OpenF1 session results | 313 of 315 classified finishers |
| Every lap has a time | OpenF1 timing | 114 of 20,807 laps have none, 40 of them in Melbourne, where OpenF1 has no time for anyone's final lap |
| Telemetry top speed reaches the speed trap | OpenF1 speed trap | 100 % of 111 laps, median +8 km/h |
| Race pace order matches the finishing order | OpenF1 session results | rank correlation 0.88 over 18 races |

**Comparable laps** leave out lap 1, laps into and out of the pits, and laps slower than 107 % of
the driver's median lap (safety car, VSC). In Austin that keeps 98 of 111 laps.

**Distance check:** distance is not in the data, so it is calculated from speed. The
calculated lap is on average 5,437 m long, against the official 5,513 m for Austin
(−1.4 %). About 12 m of that is the last ~0.2 s of each lap after the final sample;
the rest is likely the 4 Hz sample rate and the racing line being shorter than the
measured centre line.

## Data schema

`telemetry.db` (SQLite):

| Table | One row per | Columns |
|---|---|---|
| `samples` | telemetry sample | Driver, LapNumber, SessionTimeS, TimeInLapS, Distance, Speed, RPM, nGear, Throttle, Brake, DRS, X, Y (track position) |
| `laps` | lap of the two compared drivers | Driver, LapNumber, LapTimeS, S1, S2, S3, PitIn, PitOut, TrapKmh, Stint, Compound, TyreAge, IsAccurate |
| `issues` | driver, lap and failed check | Driver, LapNumber, Check, Count |
| `excluded` | driver | Driver, Samples (outside the race laps), Invalid (of those) |
| `meta` | the compared race | Title, Race, Date |
| `races` | 2026 race | SessionKey, Race, Date, Status (done / upcoming), Wet (rain in at least 10 % of the race), TrackTempC |
| `season_laps` | lap of any driver in any completed race | the `laps` columns plus SessionKey, Race, Date, Team |
| `results` | driver in a completed race | SessionKey, Race, Driver, Position, Laps, Finished |

`IsAccurate` marks a comparable lap. Times are in seconds, distance in metres, speed in km/h.

## Project structure

```
f1telemetry/
  pipeline.py    load, validate, store and compare one race; tyre wear
  season.py      all races, race pace, prediction and backtest
  crosscheck.py  checks against the official classification, timing and speed trap
  report.py      writes report.html from telemetry.db
  report.html    page template for the report
  __main__.py    command line for one race
csharp/
  F1Check/       .NET 8 tool that checks the validation again in C#
  F1Check.Tests/ 10 xUnit tests
tests/           22 offline Python tests
docs/            screenshot for this README
report.html      the generated report, published on GitHub Pages
```

## Design decisions

- **OpenF1, not FastF1:** FastF1 now needs an F1 account for live-timing data. OpenF1 is free and open.
- **Telemetry for one race, laps for all:** car data for every driver in every race would be millions of rows and heavy on OpenF1's rate limit. Laps are enough for race pace.
- **SQLite:** one file, no server, and every tool can read it.
- **1 s dropout limit:** samples arrive every ~0.25 s, so 1 s means at least three missing samples.
- **Median, not fastest lap, for race pace:** a single lap can be a low-fuel or fresh-tyre outlier; the median shows the whole race.

## Limits

- About 4 samples per second: OpenF1's rate, far below the car's real sensor rate.
- Distance is estimated from speed, not measured. The report scales both laps to the same length so corners line up, but small bumps in the time gap at braking points remain.
- Two drivers per telemetry run.
- Braking zones are found from the speed trace (the speed drops at least 15 % below the speed around it), so fast
  kinks are not counted and the numbers are not the official turn numbers.
- The prediction knows nothing about the next track, the weather or car upgrades.

## Next steps

- Use track type (street, high-speed, high-downforce) in the prediction, once there is enough data to learn it.
  With 18 races, each type has too few to learn from without guessing.
- Alert when a feed dropout happens during a live session. OpenF1 serves live data only with a paid account.

## Built with

Python 3.12, pandas, numpy, SQLite, Plotly; C# with .NET 8 and Microsoft.Data.Sqlite. 22 pytest tests run without internet and cover loading,
retries and caching, validation, dropout classification, comparable laps, distance, tyre wear, lap
comparison, braking zones, track position, race pace, prediction, backtest, cross-checks, weather, picking the
latest race and the report.
Every push runs ruff, the Python tests and the 10 xUnit tests.

---

Not affiliated with Formula 1, the FIA or Audi. Data from [OpenF1](https://openf1.org), an unofficial API.
MIT licence · [Johan Stefanes](https://johanstefanes.ch)
