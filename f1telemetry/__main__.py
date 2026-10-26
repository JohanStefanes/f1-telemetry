"""CLI: python -m f1telemetry --year 2026 --drivers HUL BOR  (latest race; or pick one with --location Austin)"""
import argparse
import json

import pandas as pd

from .pipeline import compare, find_session, load, race_title, store, validate


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--location", help="OpenF1 location, e.g. Austin; default: the latest finished race")
    p.add_argument("--session", default="Race")
    p.add_argument("--drivers", nargs=2, required=True, metavar=("A", "B"))
    p.add_argument("--db", default="telemetry.db")
    args = p.parse_args()

    s = find_session(args.year, args.location, args.session)
    samples, laps, excluded = load(args.year, s["location"], args.session, list(args.drivers), s)
    issues = validate(samples)
    meta = pd.DataFrame([{"Title": race_title(s), "Race": s["location"], "Date": s["date_start"][:10]}])
    store(args.db, samples=samples, laps=laps, issues=issues, excluded=excluded, meta=meta)

    flagged = int(issues["Count"].sum()) if len(issues) else 0
    report = {
        "race": meta["Title"].iloc[0],
        "samples": len(samples),
        "laps": len(laps),
        "flagged_samples": flagged,
        "excluded_outside_race": excluded.set_index("Driver").to_dict("index"),
        "issues_by_check": issues.groupby("Check")["Count"].sum().to_dict() if len(issues) else {},
        "comparison": compare(samples, laps, *args.drivers),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
