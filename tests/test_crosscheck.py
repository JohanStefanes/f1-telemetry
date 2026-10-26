import pandas as pd

from f1telemetry.crosscheck import run


def season(sector_error=0.0):
    rows = []
    for key, date in ((1, "2026-01-01"), (2, "2026-02-01")):
        for driver, base in (("HUL", 100.0), ("BOR", 101.0), ("OCO", 102.0)):
            for lap in range(1, 13):
                t = base + 0.01 * lap
                rows.append({"SessionKey": key, "Date": date, "Race": f"R{key}", "Team": "T", "Driver": driver,
                             "LapNumber": lap, "LapTimeS": t, "S1": 30.0, "S2": 30.0, "S3": t - 60 + sector_error,
                             "IsAccurate": lap > 1})
    return pd.DataFrame(rows)


RESULTS = pd.DataFrame([{"SessionKey": k, "Driver": d, "Position": p, "Laps": 12, "Finished": True}
                        for k in (1, 2) for p, d in enumerate(["HUL", "BOR", "OCO"], 1)])
SAMPLES = pd.DataFrame({"Driver": "HUL", "LapNumber": [2, 2], "Speed": [300.0, 320.0]})
LAPS = pd.DataFrame({"Driver": ["HUL"], "LapNumber": [2], "TrapKmh": [315.0]})


def test_consistent_data_passes_every_check():
    checks = run(SAMPLES, LAPS, season(), RESULTS)
    assert checks["Passed"].all(), checks.to_string()
    assert len(checks) == 5


def test_sector_times_that_do_not_add_up_fail():
    checks = run(SAMPLES, LAPS, season(sector_error=0.05), RESULTS).set_index("Check")["Passed"]
    assert not checks["Sector times add up to the lap time"]
    assert checks.drop("Sector times add up to the lap time").all()
