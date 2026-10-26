"""Check the stored data against independent sources: the official classification, timing and physics.

Validation (pipeline.validate) looks at each sample on its own; these checks compare whole datasets
with something they should agree with, which catches errors in the pipeline itself.
"""
import pandas as pd

SECTOR_TOL_S = 0.01  # sector times are rounded to the millisecond
TRAP_TOL_KMH = 5  # the speed trap sits at one point; the car's top speed can be slightly elsewhere
MIN_MATCH = 0.95  # share of laps or races that must agree


def run(samples, laps, season_laps, results):
    """One row per check: what was compared, against what, the result and whether it passed."""
    rows = []

    def add(check, source, passed, result):
        rows.append({"Check": check, "Source": source, "Passed": bool(passed), "Result": result})

    timed = season_laps.dropna(subset=["LapTimeS", "S1", "S2", "S3"])
    off = (timed["S1"] + timed["S2"] + timed["S3"] - timed["LapTimeS"]).abs() > SECTOR_TOL_S
    add("Sector times add up to the lap time", "OpenF1 timing", not off.any(),
        f"{len(timed) - off.sum():,} of {len(timed):,} laps within {SECTOR_TOL_S * 1000:.0f} ms")

    finishers = results[results["Finished"]].set_index(["SessionKey", "Driver"])["Laps"]
    last = season_laps.groupby(["SessionKey", "Driver"])["LapNumber"].max()
    both = finishers.index.intersection(last.index)
    same = (last[both] == finishers[both]).mean()
    add("Lap count matches the official classification", "OpenF1 session results", same >= MIN_MATCH,
        f"{(last[both] == finishers[both]).sum()} of {len(both)} classified finishers")

    untimed = season_laps[season_laps["LapTimeS"].isna()]
    worst = untimed["Race"].value_counts()
    add("Every lap has a time", "OpenF1 timing", len(untimed) <= (1 - MIN_MATCH) * len(season_laps),
        f"{len(untimed)} of {len(season_laps):,} laps have none"
        + (f"; most in {worst.index[0]} ({worst.iloc[0]})" if len(worst) else ""))

    top = samples.groupby(["Driver", "LapNumber"])["Speed"].max()
    trap = laps.dropna(subset=["TrapKmh"]).set_index(["Driver", "LapNumber"])["TrapKmh"]
    pair = top.to_frame("top").join(trap, how="inner")
    ok = (pair["top"] >= pair["TrapKmh"] - TRAP_TOL_KMH).mean() if len(pair) else 0
    add("Telemetry top speed reaches the speed trap", "OpenF1 speed trap", ok >= MIN_MATCH,
        f"{ok:.0%} of {len(pair)} laps, median {(pair['top'] - pair['TrapKmh']).median():+.0f} km/h")

    corr = rank_corr(season_laps, results)
    add("Race pace order matches the finishing order", "OpenF1 session results", corr >= 0.7,
        f"rank correlation {corr:.2f} on average over {season_laps['SessionKey'].nunique()} races")
    return pd.DataFrame(rows)


def rank_corr(season_laps, results):
    """Mean Spearman correlation between race pace rank and finishing position, over all races."""
    from .season import pace  # season imports pipeline; importing here keeps this module light

    p = pace(season_laps).merge(season_laps[["Date", "SessionKey"]].drop_duplicates(), on="Date")
    out = []
    for key, g in p.groupby("SessionKey"):
        pos = results[results["SessionKey"] == key].set_index("Driver")["Position"].reindex(g["Driver"])
        x, y = g["GapPct"].rank().to_numpy(), pos.rank().to_numpy()
        if pd.notna(y).sum() > 2:
            out.append(pd.Series(x).corr(pd.Series(y)))
    return float(pd.Series(out).mean()) if out else float("nan")
