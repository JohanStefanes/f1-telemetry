"""CLI: python -m f1telemetry --year 2026 --location Austin --drivers HUL BOR"""
import argparse
import json

from .pipeline import compare, load, store, validate


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--location", required=True, help="OpenF1 location, e.g. Austin")
    p.add_argument("--session", default="Race")
    p.add_argument("--drivers", nargs=2, required=True, metavar=("A", "B"))
    p.add_argument("--db", default="telemetry.db")
    args = p.parse_args()

    samples, laps, excluded = load(args.year, args.location, args.session, list(args.drivers))
    issues = validate(samples)
    store(args.db, samples=samples, laps=laps, issues=issues, excluded=excluded)

    flagged = int(issues["Count"].sum()) if len(issues) else 0
    report = {
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
