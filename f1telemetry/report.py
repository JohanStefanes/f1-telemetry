"""Write a self-contained HTML report from the SQLite store: python -m f1telemetry.report"""
import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

from .crosscheck import run as crosscheck
from .pipeline import compare, degradation
from .season import summary

TRACE_COLS = ["Distance", "TimeInLapS", "Speed", "Throttle", "Brake", "nGear"]


def records(df):
    """DataFrame -> list of dicts with None instead of NaN, so the JSON stays valid."""
    return df.astype(object).where(df.notna(), None).to_dict("records")


def build(samples, laps, issues, title, season=None, excluded=None, checks=None):
    drivers = list(samples["Driver"].unique())  # order as stored: deltas are second minus first
    traces = {
        d: {int(lap): {c: [r[c] for r in records(g[TRACE_COLS].round({**dict.fromkeys(TRACE_COLS, 1), "TimeInLapS": 3}))] for c in TRACE_COLS}
            for lap, g in samples[samples["Driver"] == d].sort_values("SessionTimeS").groupby("LapNumber")}
        for d in drivers
    }
    data = {
        "title": title,
        "drivers": drivers,
        "samples": len(samples),
        "comparison": compare(samples, laps, *drivers),
        "laps": records(laps),
        "issues": records(issues),
        "traces": traces,
        "stints": records(degradation(laps)) if "Compound" in laps else [],
        "excluded": records(excluded) if excluded is not None else [],
        "checks": records(checks) if checks is not None else [],
        "season": season,
        "built": date.today().isoformat(),
    }
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return (Path(__file__).with_name("report.html").read_text()
            .replace("__TITLE__", title).replace("__DATA__", payload))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="telemetry.db")
    p.add_argument("--out", default="report.html")
    p.add_argument("--title", default="F1 telemetry report")
    args = p.parse_args()
    with sqlite3.connect(args.db) as con:
        samples, laps, issues = (read(con, t) for t in ("samples", "laps", "issues"))
        tables = set(pd.read_sql("SELECT name FROM sqlite_master WHERE type = 'table'", con)["name"])
        excluded = read(con, "excluded") if "excluded" in tables else None
        season = checks = None
        # The season section and the cross-checks appear once `python -m f1telemetry.season` has run.
        if {"races", "season_laps", "results"} <= tables:
            season_laps, results = read(con, "season_laps"), read(con, "results")
            season = summary(read(con, "races"), season_laps)
            checks = crosscheck(samples, laps, season_laps, results)
    Path(args.out).write_text(build(samples, laps, issues, args.title, season, excluded, checks))
    print(f"Wrote {args.out}")


def read(con, table):
    df = pd.read_sql(f"SELECT * FROM {table}", con)
    for col in ("IsAccurate", "PitIn", "PitOut", "Finished"):
        if col in df:
            df[col] = df[col].astype(bool)  # SQLite stores booleans as 0/1
    return df


if __name__ == "__main__":
    main()
