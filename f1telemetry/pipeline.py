"""Ingest, validate, store and compare F1 car telemetry."""
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

API = "https://api.openf1.org/v1"
CHANNELS = ["Speed", "RPM", "nGear", "Throttle", "Brake", "DRS"]
# Physical limits for an F1 car; anything outside is a sensor or transmission error
# (OpenF1 reports 104 for throttle/brake when the value is invalid).
LIMITS = {"Speed": (0, 380), "RPM": (0, 15500), "nGear": (0, 8), "Throttle": (0, 100), "Brake": (0, 100)}
CACHE = Path(".cache")  # raw API responses; delete it to download again
RETRIES = 4
MAX_GAP_S = 1.0  # car data arrives at ~4 Hz; a longer gap is a dropout
MATCH_S = 0.5  # gaps in different cars this close together are the same feed dropout


def get(endpoint, **params):
    """Fetch one OpenF1 endpoint. The raw JSON is kept in CACHE, so reruns do not download again."""
    query = urllib.parse.urlencode(sorted(params.items()))
    path = CACHE / f"{endpoint}_{query}.json"
    if not path.exists():
        raw = fetch(f"{API}/{endpoint}?{query}")
        CACHE.mkdir(exist_ok=True)
        path.with_suffix(".tmp").write_bytes(raw)
        path.with_suffix(".tmp").replace(path)  # never leave a half-written file in the cache
    return pd.DataFrame(json.loads(path.read_bytes()))


def fetch(url):
    """Download with retries: OpenF1 rate-limits (429) and occasionally times out."""
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as e:
            client_error = isinstance(e, urllib.error.HTTPError) and e.code < 500 and e.code != 429
            if client_error or attempt == RETRIES - 1:
                raise
            time.sleep(2 ** attempt)


def find_session(year, location, session="Race"):
    found = get("sessions", year=year, location=location, session_name=session)
    if found.empty:
        raise SystemExit(f"No {session} session for {location} {year} on OpenF1")
    return found.iloc[0]


def load(year, location, session, drivers):
    """Return (samples, laps) for the given driver acronyms, e.g. ["HUL", "BOR"]."""
    s = find_session(year, location, session)
    roster = get("drivers", session_key=s["session_key"]).set_index("name_acronym")["driver_number"]
    start = pd.Timestamp(s["date_start"])
    samples, laps = [], []
    for acronym in drivers:
        number = int(roster[acronym])
        car = get("car_data", session_key=s["session_key"], driver_number=number)
        lap = get("laps", session_key=s["session_key"], driver_number=number)
        car["date"] = pd.to_datetime(car["date"], format="ISO8601")
        lap["date_start"] = pd.to_datetime(lap["date_start"], format="ISO8601")
        lap = lap.dropna(subset=["date_start"]).sort_values("date_start")
        lap["date_end"] = lap["date_start"] + pd.to_timedelta(lap["lap_duration"], unit="s")
        # Assign each sample to the lap it falls in; samples outside any lap (grid, garage) are dropped.
        car = pd.merge_asof(car.sort_values("date"), lap[["date_start", "date_end", "lap_number"]],
                            left_on="date", right_on="date_start")
        car = car[car["date"] < car["date_end"]]
        car = car.rename(columns={"speed": "Speed", "rpm": "RPM", "n_gear": "nGear",
                                  "throttle": "Throttle", "brake": "Brake", "drs": "DRS",
                                  "lap_number": "LapNumber"})
        car["Driver"] = acronym
        car["LapNumber"] = car["LapNumber"].astype(int)
        car["SessionTimeS"] = (car["date"] - start).dt.total_seconds()
        car["TimeInLapS"] = (car["date"] - car["date_start"]).dt.total_seconds()
        car["Distance"] = add_distance(car)
        samples.append(car[["Driver", "LapNumber", "SessionTimeS", "TimeInLapS", "Distance", *CHANNELS]])
        laps.append(pd.DataFrame({
            "Driver": acronym,
            "LapNumber": lap["lap_number"].astype(int),
            "LapTimeS": lap["lap_duration"],
            "S1": lap["duration_sector_1"],
            "S2": lap["duration_sector_2"],
            "S3": lap["duration_sector_3"],
            # Lap 1 starts from the grid and out-laps leave the pits: not comparable.
            "IsAccurate": (lap["lap_number"] > 1) & ~lap["is_pit_out_lap"].fillna(False).astype(bool),
        }))
    return pd.concat(samples, ignore_index=True), pd.concat(laps, ignore_index=True)


def add_distance(car):
    """Distance in metres from the start line, integrated from speed (km/h) over time in the lap.

    Trapezoid rule between samples; the first sample of a lap counts from the line at its own speed.
    """
    lap = car.groupby("LapNumber")
    dt = lap["TimeInLapS"].diff().fillna(car["TimeInLapS"])
    v = (car["Speed"] + lap["Speed"].shift().fillna(car["Speed"])) / 2 / 3.6
    return (v * dt).groupby(car["LapNumber"]).cumsum()


def validate(samples):
    """Flag bad samples. Returns one row per (Driver, LapNumber, Check) with a count."""
    checks = {}
    for col in ["Speed", "RPM", "nGear", "Throttle", "Brake"]:
        checks[f"missing_{col}"] = samples[col].isna()
        lo, hi = LIMITS[col]
        checks[f"out_of_range_{col}"] = samples[col].notna() & ~samples[col].between(lo, hi)
    dt = samples.groupby(["Driver", "LapNumber"])["SessionTimeS"].diff()
    checks["non_increasing_time"] = dt <= 0
    gap = dt > MAX_GAP_S
    shared = feed_gaps(samples, gap)
    checks["gap_over_1s_feed"] = gap & shared
    checks["gap_over_1s_car"] = gap & ~shared
    rows = []
    for name, mask in checks.items():
        hit = samples.loc[mask, ["Driver", "LapNumber"]].value_counts()
        rows += [(d, int(l), name, int(n)) for (d, l), n in hit.items()]
    return pd.DataFrame(rows, columns=["Driver", "LapNumber", "Check", "Count"])


def feed_gaps(samples, gap):
    """True where a gap appears at the same moment in every other car: the feed dropped out, not this car."""
    t = samples["SessionTimeS"]
    drivers = samples["Driver"].unique()
    shared = pd.Series(False, index=samples.index)
    if len(drivers) < 2:
        return shared  # one car alone cannot tell feed from car
    at = {d: t[gap & (samples["Driver"] == d)].to_numpy() for d in drivers}
    for i in samples.index[gap]:
        shared[i] = all(np.abs(at[o] - t[i]).min(initial=np.inf) <= MATCH_S
                        for o in drivers if o != samples.at[i, "Driver"])
    return shared


def store(db_path, samples, laps, issues):
    with sqlite3.connect(db_path) as con:
        samples.to_sql("samples", con, if_exists="replace", index=False)
        laps.to_sql("laps", con, if_exists="replace", index=False)
        issues.to_sql("issues", con, if_exists="replace", index=False)


def compare(samples, laps, a, b):
    """Compare the fastest accurate lap of drivers a and b; deltas are b minus a."""
    best = (laps[laps["IsAccurate"] & laps["LapTimeS"].notna()]
            .sort_values("LapTimeS").groupby("Driver").head(1).set_index("Driver"))
    out = {}
    for d in (a, b):
        lap = samples[(samples["Driver"] == d) & (samples["LapNumber"] == best.loc[d, "LapNumber"])]
        out[d] = {
            "lap": int(best.loc[d, "LapNumber"]),
            "lap_time_s": round(best.loc[d, "LapTimeS"], 3),
            "sectors_s": [round(best.loc[d, s], 3) for s in ("S1", "S2", "S3")],
            "top_speed_kmh": int(lap["Speed"].max()),
            "full_throttle_pct": round(100 * (lap["Throttle"] >= 99).mean(), 1),
        }
    out["delta_s"] = round(out[b]["lap_time_s"] - out[a]["lap_time_s"], 3)
    out["sector_delta_s"] = [round(y - x, 3) for x, y in zip(out[a]["sectors_s"], out[b]["sectors_s"])]
    out["speed_delta_by_segment"] = speed_delta(samples, best, a, b)
    return out


def speed_delta(samples, best, a, b, segments=10):
    """Mean speed difference (b - a) in equal track segments, on a shared distance grid."""
    traces = {}
    for d in (a, b):
        lap = samples[(samples["Driver"] == d) & (samples["LapNumber"] == best.loc[d, "LapNumber"])]
        traces[d] = lap.sort_values("Distance")
    length = min(t["Distance"].max() for t in traces.values())
    grid = np.linspace(0, length, 500)
    va, vb = (np.interp(grid, traces[d]["Distance"], traces[d]["Speed"]) for d in (a, b))
    return [round(float(part.mean()), 1) for part in np.array_split(vb - va, segments)]
