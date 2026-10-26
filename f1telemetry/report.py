"""Write a self-contained HTML report from the SQLite store: python -m f1telemetry.report"""
import argparse
import json
import sqlite3
from pathlib import Path

import pandas as pd

from .pipeline import compare

TRACE_COLS = ["Distance", "Speed", "Throttle", "Brake", "nGear"]


def records(df):
    """DataFrame -> list of dicts with None instead of NaN, so the JSON stays valid."""
    return df.astype(object).where(df.notna(), None).to_dict("records")


def build(samples, laps, issues, title):
    drivers = list(samples["Driver"].unique())  # order as stored: deltas are second minus first
    traces = {
        d: {int(lap): {c: [r[c] for r in records(g[TRACE_COLS].round(1))] for c in TRACE_COLS}
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
    Path(args.out).write_text(build(samples, laps, issues, args.title))
    print(f"Wrote {args.out}")


def read(con, table):
    df = pd.read_sql(f"SELECT * FROM {table}", con)
    if "IsAccurate" in df:
        df["IsAccurate"] = df["IsAccurate"].astype(bool)  # SQLite stores booleans as 0/1
    return df


if __name__ == "__main__":
    main()
