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
RETRIES = 6  # waits 1, 2, 4, 8, 16 s: OpenF1 allows only a few requests per second
MAX_GAP_S = 1.0  # car data arrives at ~4 Hz; a longer gap is a dropout
MATCH_S = 0.5  # gaps in different cars this close together are the same feed dropout
SLOW_LAP = 1.07  # slower than 107 % of the driver's median lap: safety car, VSC or a problem
MIN_STINT = 5  # comparable laps a stint needs before a degradation slope means anything
POS_TOL = pd.Timedelta("500ms")  # a position sample further away in time than this is not used
CORNER_WINDOW_M = 150  # a corner's slowest point is the slowest within this many metres either side
CORNER_DROP = 0.85  # ... and at least 15 % slower than the fastest point 400 m around it


def get(endpoint, fresh=False, **params):
    """Fetch one OpenF1 endpoint. The raw JSON is kept in CACHE, so reruns do not download again.

    fresh=True downloads again, for answers that change over time such as the list of races so far.
    """
    query = urllib.parse.urlencode(sorted(params.items()))
    path = CACHE / f"{endpoint}_{query}.json"
    if fresh or not path.exists():
        raw = fetch(f"{API}/{endpoint}?{query}")
        if not json.loads(raw):
            return pd.DataFrame()  # empty usually means "not published yet": ask again next time
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
            wait = getattr(e, "headers", None) and e.headers.get("Retry-After")
            time.sleep(float(wait) if wait and wait.isdigit() else 2 ** attempt)


def find_session(year, location=None, session="Race"):
    """The session at `location`, or with no location the latest finished one that already has lap data."""
    if location:
        found = get("sessions", year=year, location=location, session_name=session)
        if found.empty:
            raise SystemExit(f"No {session} session for {location} {year} on OpenF1")
        return found.iloc[0]
    found = get("sessions", fresh=True, year=year, session_name=session)
    if not found.empty:
        finished = ~found["is_cancelled"].fillna(False).astype(bool) & (
            pd.to_datetime(found["date_end"], format="ISO8601") < pd.Timestamp.now(tz="UTC"))
        for _, s in found[finished].sort_values("date_start", ascending=False).iterrows():
            if not get("laps", session_key=s["session_key"], lap_number=2).empty:  # one small request per race
                return s
    raise SystemExit(f"No finished {session} session with lap data for {year} on OpenF1")


def race_title(s):
    """'2026 United States GP' for a session, from the meeting it belongs to."""
    meeting = get("meetings", meeting_key=s["meeting_key"])
    name = meeting["meeting_name"].iloc[0] if not meeting.empty else s["location"]
    return f"{s['year']} {name.replace(' Grand Prix', ' GP')}"


def load(year, location, session, drivers, s=None):
    """Return (samples, laps, excluded) for the given driver acronyms, e.g. ["HUL", "BOR"].

    excluded counts, per driver, the samples recorded outside the race laps (grid, garage, after the flag)
    and how many of those carried invalid values, so the report can say what was left out.
    """
    s = find_session(year, location, session) if s is None else s
    key = s["session_key"]
    roster = get("drivers", session_key=key).set_index("driver_number")["name_acronym"]
    all_laps = lap_table(get("laps", session_key=key), get("pit", session_key=key), roster,
                         get("stints", session_key=key))
    start = pd.Timestamp(s["date_start"])
    samples, excluded = [], []
    for acronym in drivers:
        number = int(roster[roster == acronym].index[0])
        car = get("car_data", session_key=key, driver_number=number)
        car["date"] = pd.to_datetime(car["date"], format="ISO8601")
        lap = all_laps[all_laps["Driver"] == acronym]
        # Assign each sample to the lap it falls in; samples outside any lap (grid, garage) are dropped.
        car = pd.merge_asof(car.sort_values("date"), lap[["DateStart", "DateEnd", "LapNumber"]],
                            left_on="date", right_on="DateStart")
        car = car.rename(columns={"speed": "Speed", "rpm": "RPM", "n_gear": "nGear",
                                  "throttle": "Throttle", "brake": "Brake", "drs": "DRS"})
        inside = car["date"] < car["DateEnd"]
        invalid = pd.concat([~car[c].between(*LIMITS[c]) for c in LIMITS], axis=1).any(axis=1)
        excluded.append({"Driver": acronym, "Samples": int((~inside).sum()), "Invalid": int((~inside & invalid).sum())})
        car = car[inside]
        car["Driver"] = acronym
        car["LapNumber"] = car["LapNumber"].astype(int)
        car["SessionTimeS"] = (car["date"] - start).dt.total_seconds()
        car["TimeInLapS"] = (car["date"] - car["DateStart"]).dt.total_seconds()
        car["Distance"] = add_distance(car)
        car = add_position(car, get("location", session_key=key, driver_number=number))
        samples.append(car[["Driver", "LapNumber", "SessionTimeS", "TimeInLapS", "Distance", *CHANNELS, "X", "Y"]])
    laps = all_laps[all_laps["Driver"].isin(drivers)].drop(columns=["DateStart", "DateEnd"])
    return pd.concat(samples, ignore_index=True), laps.reset_index(drop=True), pd.DataFrame(excluded)


def lap_table(lap, pit, roster, stints=None):
    """One row per lap from OpenF1 laps, pit stops and tyre stints; roster maps driver number to acronym."""
    if lap.empty:
        lap = pd.DataFrame(columns=["driver_number", "lap_number", "lap_duration", "date_start", "is_pit_out_lap",
                                    "duration_sector_1", "duration_sector_2", "duration_sector_3"])
    lap = lap.dropna(subset=["date_start"])
    start = pd.to_datetime(lap["date_start"], format="ISO8601")
    # OpenF1 gives the lap a car entered the pits on; the lap after it is flagged as the out-lap.
    pit_in = set(zip(pit["driver_number"], pit["lap_number"].astype(int))) if len(pit) else set()
    out = pd.DataFrame({
        "Driver": lap["driver_number"].map(roster),
        "LapNumber": lap["lap_number"].astype(int),
        "LapTimeS": lap["lap_duration"],
        "S1": lap["duration_sector_1"],
        "S2": lap["duration_sector_2"],
        "S3": lap["duration_sector_3"],
        "PitIn": [(d, n) in pit_in for d, n in zip(lap["driver_number"], lap["lap_number"])],
        "PitOut": lap["is_pit_out_lap"].fillna(False).astype(bool),
        "TrapKmh": lap.get("st_speed"),
        "Stint": None, "Compound": None, "TyreAge": None,
        "DateStart": start,
        "DateEnd": start + pd.to_timedelta(lap["lap_duration"], unit="s"),
    })
    if stints is not None and len(stints):
        m = (lap[["driver_number", "lap_number"]].reset_index().merge(stints, on="driver_number")
             .query("lap_start <= lap_number and (lap_number <= lap_end or lap_end != lap_end)")  # NaN end: still running
             .drop_duplicates("index").set_index("index"))
        out["Stint"], out["Compound"] = m["stint_number"], m["compound"]
        out["TyreAge"] = m["tyre_age_at_start"] + m["lap_number"] - m["lap_start"]
    out = out.dropna(subset=["Driver"]).sort_values(["Driver", "DateStart"])
    out["IsAccurate"] = comparable(out)
    return out.reset_index(drop=True)


def degradation(laps):
    """Seconds lost per lap of tyre age in each stint: the slope of a straight line through its comparable laps.

    The car also gets lighter as fuel burns, which makes it faster, so the real tyre wear is somewhat larger.
    """
    rows = []
    ok = laps[laps["IsAccurate"].astype(bool) & laps["Compound"].notna()]
    for (driver, stint), g in ok.groupby(["Driver", "Stint"]):
        if len(g) < MIN_STINT:
            continue
        rows.append({"Driver": driver, "Stint": int(stint), "Compound": g["Compound"].iloc[0],
                     "FirstLap": int(g["LapNumber"].min()), "LastLap": int(g["LapNumber"].max()), "Laps": len(g),
                     "DegS": round(float(np.polyfit(g["TyreAge"].astype(float), g["LapTimeS"], 1)[0]), 3),
                     "MedianS": round(float(g["LapTimeS"].median()), 3)})
    return pd.DataFrame(rows, columns=["Driver", "Stint", "Compound", "FirstLap", "LastLap", "Laps", "DegS", "MedianS"])


def comparable(laps):
    """Laps that show race pace: not lap 1 (grid start), not into or out of the pits,
    and not slower than SLOW_LAP times the driver's median (safety car, VSC, a problem)."""
    median = laps.groupby("Driver")["LapTimeS"].transform("median")
    return ((laps["LapNumber"] > 1) & ~laps["PitIn"] & ~laps["PitOut"]
            & (laps["LapTimeS"] <= SLOW_LAP * median))


def add_position(car, pos):
    """Add the car's track position (OpenF1 x/y, arbitrary units) from the nearest location sample in time."""
    if pos.empty:
        return car.assign(X=np.nan, Y=np.nan)
    pos = pos.assign(date=pd.to_datetime(pos["date"], format="ISO8601"))
    pos = pos[(pos["x"] != 0) | (pos["y"] != 0)].sort_values("date")  # 0/0 is sent while the car is in the garage
    out = pd.merge_asof(car.sort_values("date"), pos[["date", "x", "y"]].rename(columns={"x": "X", "y": "Y"}),
                        on="date", direction="nearest", tolerance=POS_TOL)
    return out.set_index(car.sort_values("date").index).loc[car.index]


def corners(samples, driver, lap):
    """The main braking zones of one lap: where speed bottoms out at least 15 % below the speed around it.

    Fast kinks that barely slow the car are not counted, so the numbers are not the official turn numbers.
    Returns each zone's position as a fraction of the lap (so it fits any lap of the same track)
    and its minimum speed.
    """
    t = samples[(samples["Driver"] == driver) & (samples["LapNumber"] == lap)].dropna(subset=["Distance", "Speed"])
    t = t.sort_values("Distance")
    x, raw = t["Distance"].to_numpy(), t["Speed"].to_numpy()
    v = t["Speed"].rolling(3, center=True, min_periods=1).mean().to_numpy()  # smoothed only to find the corners
    if len(x) < 10:
        return []
    out = []
    for i in range(len(x)):
        if not 50 < x[i] < x[-1] - 50:
            continue  # the first and last samples sit at the line, where the lap is cut, not in a corner
        near, around = abs(x - x[i]) <= CORNER_WINDOW_M, abs(x - x[i]) <= 400
        if v[i] == v[near].min() and v[i] <= CORNER_DROP * v[around].max():
            if not out or x[i] - out[-1][0] > 2 * CORNER_WINDOW_M:
                out.append((x[i], raw[near].min()))
    return [{"Corner": n, "Fraction": round(float(d / x[-1]), 4), "MinKmh": round(float(s), 1)}
            for n, (d, s) in enumerate(out, 1)]


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
        rows += [(d, int(lap), name, int(n)) for (d, lap), n in hit.items()]
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


def store(db_path, **tables):
    """Write each DataFrame to the SQLite table of the same name, replacing what was there."""
    with sqlite3.connect(db_path) as con:
        for name, df in tables.items():
            df.to_sql(name, con, if_exists="replace", index=False)


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
