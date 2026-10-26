"""All races of a season and a simple pace prediction for the next one: python -m f1telemetry.season --year 2026

Only laps and pit stops are loaded for every race (a few thousand rows each); car telemetry stays
limited to the race being compared, which keeps the load on OpenF1 small.
"""
import argparse
import json

import pandas as pd

from .pipeline import get, lap_table, store

RECENT = 5  # races of form the prediction averages
MIN_LAPS = 10  # fewer comparable laps (retired, early crash) gives no pace for that race
FIRST_TEST = 4  # the backtest starts at race 4, so every prediction has at least three races behind it
WET_SHARE = 0.1  # rain in at least 10 % of the weather readings makes a wet race; a passing shower does not
MODELS = (3, 5, 8, 99)  # form windows compared in the backtest; 99 means the whole season


def races(year):
    """(completed races, next race or None). Cancelled races are left out."""
    s = get("sessions", fresh=True, year=year, session_name="Race")
    s = s[~s["is_cancelled"].fillna(False).astype(bool)].sort_values("date_start")
    done = pd.to_datetime(s["date_end"], format="ISO8601") < pd.Timestamp.now(tz="UTC")
    table = pd.DataFrame({
        "SessionKey": s["session_key"],
        "Race": s["location"],
        "Date": s["date_start"].str[:10],
        "Status": done.map({True: "done", False: "upcoming"}),
    }).reset_index(drop=True)
    upcoming = table[table["Status"] == "upcoming"]
    return table, (upcoming.iloc[0] if len(upcoming) else None)


def load_season(year):
    """Return (races table, laps of every driver in every completed race, official results)."""
    table, _ = races(year)
    table["Wet"], table["TrackTempC"] = None, None
    laps, results = [], []
    for r in table[table["Status"] == "done"].itertuples():
        raw = get("laps", session_key=r.SessionKey)
        if raw.empty:  # finished, but OpenF1 has not published the laps yet: still to come for us
            table.loc[table["SessionKey"] == r.SessionKey, "Status"] = "upcoming"
            continue
        drivers = get("drivers", session_key=r.SessionKey)
        roster = drivers.set_index("driver_number")["name_acronym"]
        team = drivers.set_index("name_acronym")["team_name"]
        t = lap_table(raw, get("pit", session_key=r.SessionKey), roster,
                      get("stints", session_key=r.SessionKey))
        laps.append(t.drop(columns=["DateStart", "DateEnd"])
                     .assign(SessionKey=r.SessionKey, Race=r.Race, Date=r.Date, Team=t["Driver"].map(team)))
        weather = get("weather", session_key=r.SessionKey)
        if not weather.empty:
            table.loc[table["SessionKey"] == r.SessionKey, ["Wet", "TrackTempC"]] = [
                bool((weather["rainfall"].fillna(0) > 0).mean() >= WET_SHARE),
                round(float(weather["track_temperature"].mean()), 1)]
        res = get("session_result", session_key=r.SessionKey)
        results.append(pd.DataFrame({
            "SessionKey": r.SessionKey, "Race": r.Race, "Driver": res["driver_number"].map(roster),
            "Position": res["position"], "Laps": res["number_of_laps"],
            "Finished": ~(res["dnf"].fillna(False) | res["dns"].fillna(False) | res["dsq"].fillna(False)).astype(bool),
        }))
    return table, pd.concat(laps, ignore_index=True), pd.concat(results, ignore_index=True)


def pace(laps):
    """Race pace per driver and race: median comparable lap, as % slower than the fastest driver that race."""
    ok = laps[laps["IsAccurate"].astype(bool)]
    p = (ok.groupby(["Date", "Race", "Driver", "Team"])["LapTimeS"]
         .agg(MedianS="median", Laps="count").reset_index())
    p = p[p["Laps"] >= MIN_LAPS].copy()
    p["GapPct"] = 100 * (p["MedianS"] / p.groupby("Date")["MedianS"].transform("min") - 1)
    return p.sort_values(["Date", "GapPct"]).reset_index(drop=True)


def predict(p, drivers, recent=RECENT):
    """Expected gap for each driver: the mean of their last `recent` races. Drivers without history are left out."""
    recent = p.sort_values("Date").groupby("Driver").tail(recent)
    g = recent.groupby("Driver")["GapPct"].agg(GapPct="mean", Races="count")
    g = g.reindex(list(drivers)).dropna().sort_values("GapPct")
    g["Rank"] = range(1, len(g) + 1)
    return g.reset_index()


def backtest(p, ahead=1, recent=RECENT):
    """Predict each race from the races at least `ahead` races before it, and measure the error against
    what happened. ahead=1 is the next race; ahead=3 is three races later, with the two in between unknown.

    Also scores a naive baseline (each driver repeats their last known race), so the model has something to beat.
    """
    dates = sorted(p["Date"].unique())
    rows = []
    for i in range(FIRST_TEST - 1 + ahead - 1, len(dates)):
        known = dates[:i - ahead + 1]
        before, actual = p[p["Date"].isin(known)], p[p["Date"] == dates[i]].set_index("Driver")
        model = predict(before, actual.index, recent).set_index("Driver")["GapPct"]
        naive = before[before["Date"] == known[-1]].set_index("Driver")["GapPct"]
        both = actual.index.intersection(model.index).intersection(naive.index)
        real = actual.loc[both, "GapPct"]
        rows.append({
            "Date": dates[i],
            "Race": actual["Race"].iloc[0],
            "Drivers": len(both),
            "ModelErrPct": (model[both] - real).abs().mean(),
            "NaiveErrPct": (naive[both] - real).abs().mean(),
            "RankErr": (model[both].rank() - real.rank()).abs().mean(),
        })
    return pd.DataFrame(rows)


def summary(table, laps):
    """Everything the report and the CLI show about the season, as plain Python values."""
    p = pace(laps)
    remaining = table[table["Status"] == "upcoming"]
    nxt = remaining.head(1)
    latest = p[p["Date"] == p["Date"].max()]
    team = latest.set_index("Driver")["Team"]
    pred = predict(p, latest["Driver"])  # the entry list of the latest race
    pred["Team"] = pred["Driver"].map(team)
    bt = backtest(p)
    ahead = [backtest(p, h) for h in range(1, len(remaining) + 1)]
    done = table[table["Status"] == "done"]
    return {
        "races": len(done),
        "as_of": done.iloc[-1][["Race", "Date"]].to_dict() if len(done) else None,
        "laps": int(laps["LapTimeS"].notna().sum()),  # laps with a time; retirements leave one without
        "untimed_laps": int(laps["LapTimeS"].isna().sum()),
        "comparable_laps": int(laps["IsAccurate"].astype(bool).sum()),
        "next_race": nxt.iloc[0][["Race", "Date"]].to_dict() if len(nxt) else None,
        "prediction": pred.round(3).to_dict("records"),
        "pace": p.round(3).to_dict("records"),
        "backtest": bt.round(3).to_dict("records"),
        "backtest_mean": {k: round(float(bt[k].mean()), 3) for k in ("ModelErrPct", "NaiveErrPct", "RankErr")},
        # Every remaining race with the backtest error for predicting that many races ahead.
        "remaining": [{"Race": r.Race, "Date": r.Date, "Ahead": h,
                       "ErrPct": round(float(b["ModelErrPct"].mean()), 3) if len(b) else None,
                       "RankErr": round(float(b["RankErr"].mean()), 3) if len(b) else None,
                       "Tested": len(b)}
                      for h, (r, b) in enumerate(zip(remaining.itertuples(), ahead), 1)],
        # Same backtest for other form windows, to show the 5-race choice is not cherry-picked.
        "models": [{"Recent": n, "ErrPct": round(float(backtest(p, recent=n)["ModelErrPct"].mean()), 3)} for n in MODELS],
        "weather": [{"Race": r.Race, "Wet": bool(r.Wet), "TrackTempC": r.TrackTempC}
                    for r in done.itertuples() if "Wet" in done and r.Wet is not None and r.Wet == r.Wet],
    }


def main():
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--year", type=int, required=True)
    a.add_argument("--db", default="telemetry.db")
    args = a.parse_args()
    table, laps, results = load_season(args.year)
    store(args.db, races=table, season_laps=laps, results=results)
    s = summary(table, laps)
    print(json.dumps({k: s[k] for k in ("races", "laps", "untimed_laps", "comparable_laps", "backtest_mean", "models")}, indent=2))
    print(pd.DataFrame(s["prediction"]).to_string(index=False))


if __name__ == "__main__":
    main()
