import pandas as pd

from f1telemetry.pipeline import add_distance, compare, validate


def samples(**override):
    df = pd.DataFrame({
        "Driver": ["HUL"] * 4,
        "LapNumber": [1] * 4,
        "SessionTimeS": [0.0, 0.25, 0.5, 0.75],
        "Distance": [0.0, 20.0, 40.0, 60.0],
        "Speed": [280.0, 290.0, 300.0, 310.0],
        "RPM": [11000.0] * 4,
        "nGear": [7] * 4,
        "Throttle": [100.0] * 4,
        "Brake": [0.0] * 4,
        "DRS": [0] * 4,
    })
    for col, values in override.items():
        df[col] = values
    return df


def checks(df):
    return dict(zip(validate(df)["Check"], validate(df)["Count"]))


def test_clean_data_has_no_issues():
    assert validate(samples()).empty


def test_out_of_range_and_missing_values_are_flagged():
    found = checks(samples(Speed=[280.0, 420.0, None, 310.0], Throttle=[100.0, 104.0, 100.0, 100.0]))
    assert found == {"missing_Speed": 1, "out_of_range_Speed": 1, "out_of_range_Throttle": 1}


def test_time_errors_and_dropouts_are_flagged():
    found = checks(samples(SessionTimeS=[0.0, 0.25, 0.25, 2.0]))
    assert found == {"non_increasing_time": 1, "gap_over_1s": 1}


def test_compare_uses_fastest_accurate_lap():
    s = pd.concat([
        samples(),
        samples(Driver=["BOR"] * 4, Speed=[270.0, 280.0, 290.0, 300.0]),
        samples(LapNumber=[2] * 4, Speed=[100.0] * 4),
    ], ignore_index=True)
    laps = pd.DataFrame({
        "Driver": ["HUL", "BOR", "HUL"],
        "LapNumber": [1, 1, 2],
        "LapTimeS": [98.0, 98.5, 97.0],
        "S1": [30.0, 30.2, 29.0], "S2": [38.0, 38.1, 38.0], "S3": [30.0, 30.2, 30.0],
        "IsAccurate": [True, True, False],  # lap 2 is faster but not accurate
    })
    out = compare(s, laps, "HUL", "BOR")
    assert out["HUL"]["lap"] == 1
    assert out["delta_s"] == 0.5
    assert out["sector_delta_s"] == [0.2, 0.1, 0.2]
    assert all(d == -10.0 for d in out["speed_delta_by_segment"])


def test_distance_is_integrated_per_lap():
    car = pd.DataFrame({"LapNumber": [1, 1, 1, 2, 2], "SessionTimeS": [0.0, 1.0, 2.0, 2.0, 3.0],
                        "Speed": [360.0, 360.0, 180.0, 360.0, 360.0]})
    # 360 km/h = 100 m/s; distance restarts at 0 on each new lap
    assert add_distance(car).tolist() == [0.0, 100.0, 150.0, 0.0, 100.0]


def test_report_embeds_traces_and_comparison():
    import json
    from f1telemetry.report import build
    s = pd.concat([samples(), samples(Driver=["BOR"] * 4, Speed=[270.0, None, 290.0, 300.0])], ignore_index=True)
    laps = pd.DataFrame({"Driver": ["HUL", "BOR"], "LapNumber": [1, 1], "LapTimeS": [98.0, 98.5],
                         "S1": [30.0, 30.2], "S2": [38.0, 38.1], "S3": [30.0, 30.2], "IsAccurate": [True, True]})
    html = build(s, laps, validate(s), "Test GP")
    data = json.loads(html.split('id="data">')[1].split("</script>")[0])
    assert data["drivers"] == ["HUL", "BOR"]
    assert data["traces"]["BOR"]["1"]["Speed"] == [270.0, None, 290.0, 300.0]  # NaN becomes null
    assert data["comparison"]["delta_s"] == 0.5
    assert "<title>Test GP</title>" in html
