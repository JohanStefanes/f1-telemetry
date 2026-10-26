import pandas as pd
import pytest

from f1telemetry.season import backtest, pace, predict


def test_pace_is_gap_to_fastest_median_and_skips_short_races():
    laps = pd.DataFrame({
        "Date": "2026-10-25", "Race": "Austin", "Team": "Audi",
        "Driver": ["HUL"] * 10 + ["BOR"] * 10 + ["OCO"] * 3,  # OCO retired after 3 laps
        "LapTimeS": [100.0] * 10 + [102.0] * 10 + [99.0] * 3,
        "IsAccurate": True,
    })
    p = pace(laps).set_index("Driver")["GapPct"]
    assert p.to_dict() == pytest.approx({"HUL": 0.0, "BOR": 2.0})


def test_prediction_averages_the_last_five_races():
    p = pd.DataFrame({"Date": [f"2026-0{i}-01" for i in range(1, 7)], "Driver": "HUL",
                      "GapPct": [9.0, 1.0, 1.0, 2.0, 2.0, 1.0]})  # the 9 % in race 1 is too old to count
    pred = predict(p, ["HUL", "NEW"]).set_index("Driver")  # NEW has no races yet
    assert pred.loc["HUL", "GapPct"] == pytest.approx(1.4)
    assert pred.loc["HUL", "Races"] == 5
    assert "NEW" not in pred.index


def test_backtest_predicts_each_race_only_from_earlier_races():
    gaps = {"A": [0, 0, 0, 0], "B": [1, 1, 1, 4], "C": [2, 2, 3, 2]}
    p = pd.DataFrame([{"Date": f"2026-0{i + 1}-01", "Race": f"R{i + 1}", "Driver": d, "GapPct": float(g[i])}
                      for d, g in gaps.items() for i in range(4)])
    bt = backtest(p)
    assert bt["Race"].tolist() == ["R4"]  # races 1-3 only build up history
    # Race 4 predicted from races 1-3 (A 0, B 1, C 7/3) against what happened (A 0, B 4, C 2)
    assert bt.loc[0, "ModelErrPct"] == pytest.approx((0 + 3 + 1 / 3) / 3)
    assert bt.loc[0, "NaiveErrPct"] == pytest.approx((0 + 3 + 1) / 3)  # naive: repeat race 3
    assert bt.loc[0, "RankErr"] == pytest.approx(2 / 3)  # predicted A, B, C; actual A, C, B


def test_backtest_further_ahead_ignores_the_races_in_between():
    gaps = {"A": [0, 0, 0, 9, 0], "B": [1, 1, 1, 9, 1]}  # race 4 is odd, but two races ahead it is unknown
    p = pd.DataFrame([{"Date": f"2026-0{i + 1}-01", "Race": f"R{i + 1}", "Driver": d, "GapPct": float(g[i])}
                      for d, g in gaps.items() for i in range(5)])
    bt = backtest(p, ahead=2)
    assert bt["Race"].tolist() == ["R5"]  # predicted from races 1-3 only
    assert bt.loc[0, "ModelErrPct"] == pytest.approx(0.0)
    assert bt.loc[0, "NaiveErrPct"] == pytest.approx(0.0)  # naive repeats race 3, the last one known
