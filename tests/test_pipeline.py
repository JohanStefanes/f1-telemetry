import io
import urllib.error

import pandas as pd
import pytest

from f1telemetry import pipeline
from f1telemetry.pipeline import add_distance, comparable, compare, degradation, load, validate


def samples(**override):
    df = pd.DataFrame({
        "Driver": ["HUL"] * 4,
        "LapNumber": [1] * 4,
        "SessionTimeS": [0.0, 0.25, 0.5, 0.75],
        "TimeInLapS": [0.0, 0.25, 0.5, 0.75],
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
    assert found == {"non_increasing_time": 1, "gap_over_1s_car": 1}


def test_gap_in_both_cars_at_same_time_is_a_feed_dropout():
    s = pd.concat([
        samples(SessionTimeS=[0.0, 0.25, 2.0, 2.25]),                         # gap ends at 2.0 s
        samples(Driver=["BOR"] * 4, SessionTimeS=[0.1, 0.35, 2.1, 5.0]),      # same gap, plus its own
    ], ignore_index=True)
    found = {(d, c): n for d, c, n in validate(s)[["Driver", "Check", "Count"]].itertuples(index=False)}
    assert found == {("HUL", "gap_over_1s_feed"): 1, ("BOR", "gap_over_1s_feed"): 1, ("BOR", "gap_over_1s_car"): 1}


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
    car = pd.DataFrame({"LapNumber": [1, 1, 1, 2, 2], "TimeInLapS": [0.5, 1.5, 2.5, 0.0, 1.0],
                        "Speed": [360.0, 360.0, 180.0, 360.0, 360.0]})
    # 360 km/h = 100 m/s. Lap 1's first sample is 0.5 s past the line (50 m); 360 -> 180 km/h averages 75 m/s.
    # Distance restarts on each new lap.
    assert add_distance(car).tolist() == [50.0, 150.0, 225.0, 0.0, 100.0]


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


def test_load_assigns_samples_to_laps_and_drops_the_rest(monkeypatch):
    def t(s):
        return (pd.Timestamp("2026-10-25T19:00:00Z") + pd.Timedelta(seconds=s)).isoformat()

    api = {
        "sessions": [{"session_key": 1, "date_start": t(0)}],
        "drivers": [{"name_acronym": "HUL", "driver_number": 27}],
        "pit": [],
        "stints": [{"driver_number": 27, "stint_number": 1, "lap_start": 1, "lap_end": 2, "compound": "SOFT", "tyre_age_at_start": 3},
                   {"driver_number": 27, "stint_number": 2, "lap_start": 3, "lap_end": None, "compound": "HARD", "tyre_age_at_start": 0}],
        "laps": [  # lap 1 from the grid, lap 2 a normal lap, lap 3 out of the pits
            {"driver_number": 27, "lap_number": n, "date_start": t(start), "lap_duration": dur, "is_pit_out_lap": pit,
             "duration_sector_1": 30.0, "duration_sector_2": 30.0, "duration_sector_3": 30.0}
            for n, start, dur, pit in [(1, 10, 100, None), (2, 110, 90, False), (3, 200, 95, True)]],
        "car_data": [{"date": t(s), "speed": 200, "rpm": 11000, "n_gear": 6, "throttle": thr, "brake": 0, "drs": 0}
                     # 5 s is on the grid (with OpenF1's invalid 104), 400 s after the last lap
                     for s, thr in ((5, 104), (10.5, 100), (109.9, 100), (110.2, 100), (400, 100))],
    }
    monkeypatch.setattr(pipeline, "get", lambda endpoint, **_: pd.DataFrame(api[endpoint]))
    samples, laps, excluded = load(2026, "Austin", "Race", ["HUL"])
    assert samples["LapNumber"].tolist() == [1, 1, 2]
    assert samples["TimeInLapS"].round(3).tolist() == [0.5, 99.9, 0.2]
    assert samples["SessionTimeS"].tolist()[0] == 10.5
    assert laps["IsAccurate"].tolist() == [False, True, False]
    assert excluded.to_dict("records") == [{"Driver": "HUL", "Samples": 2, "Invalid": 1}]
    assert laps["Compound"].tolist() == ["SOFT", "SOFT", "HARD"]
    assert laps["TyreAge"].tolist() == [3, 4, 0]  # stint 1 started on tyres 3 laps old


def test_get_retries_rate_limits_and_caches_raw_data(monkeypatch, tmp_path):
    calls = []

    def urlopen(url, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None)
        return io.BytesIO(b'[{"lap_number": 1}]')

    monkeypatch.setattr(pipeline, "CACHE", tmp_path)
    monkeypatch.setattr(pipeline.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    assert pipeline.get("laps", session_key=1).to_dict("records") == [{"lap_number": 1}]
    assert pipeline.get("laps", session_key=1).to_dict("records") == [{"lap_number": 1}]  # from the cache
    assert len(calls) == 2  # one rate-limited attempt, one success, nothing for the second call


def test_get_does_not_retry_a_bad_request(monkeypatch, tmp_path):
    def urlopen(url, timeout):
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr(pipeline, "CACHE", tmp_path)
    monkeypatch.setattr(pipeline.urllib.request, "urlopen", urlopen)
    with pytest.raises(urllib.error.HTTPError):
        pipeline.get("laps", session_key=1)
    assert not list(tmp_path.iterdir())


def test_comparable_laps_skip_start_pits_and_safety_car():
    laps = pd.DataFrame({
        "Driver": ["HUL"] * 6,
        "LapNumber": [1, 2, 3, 4, 5, 6],
        # median 106.5 s, so 107 % is 113.96 s: lap 6 (137 s, safety car) is too slow
        "LapTimeS": [110.0, 100.0, 103.0, 125.0, 101.0, 137.0],
        "PitIn": [False, False, True, False, False, False],
        "PitOut": [False, False, False, True, False, False],
    })
    assert comparable(laps).tolist() == [False, True, False, False, True, False]


def test_degradation_is_the_lap_time_slope_per_stint():
    age = list(range(8))
    laps = pd.DataFrame({
        "Driver": "HUL", "Stint": [1] * 8 + [2] * 4, "Compound": ["SOFT"] * 8 + ["HARD"] * 4,
        "LapNumber": range(2, 14), "TyreAge": age + [0, 1, 2, 3],
        "LapTimeS": [100 + 0.1 * a for a in age] + [101.0] * 4,  # soft loses 0.1 s per lap
        "IsAccurate": True,
    })
    deg = degradation(laps)
    assert deg[["Stint", "Compound", "Laps"]].values.tolist() == [[1, "SOFT", 8]]  # 4 hard laps are too few
    assert deg.loc[0, "DegS"] == pytest.approx(0.1)
