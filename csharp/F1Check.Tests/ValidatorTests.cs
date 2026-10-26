using F1Check;
using Microsoft.Data.Sqlite;
using Xunit;

namespace F1Check.Tests;

public class ValidatorTests
{
    // Four clean samples of one lap, 0.25 s apart, like the Python tests' fixture.
    static List<Sample> Lap(string driver = "HUL", double start = 0, params double[] times) =>
        (times.Length > 0 ? times : new[] { 0.0, 0.25, 0.5, 0.75 })
        .Select(t => new Sample(driver, 1, start + t, 300, 11000, 7, 100, 0)).ToList();

    static Dictionary<string, int> ByCheck(IEnumerable<Sample> samples) =>
        Validator.Run(samples.ToList()).GroupBy(kv => kv.Key.Check).ToDictionary(g => g.Key, g => g.Sum(kv => kv.Value));

    [Fact]
    public void CleanDataHasNoIssues() => Assert.Empty(Validator.Run(Lap()));

    [Fact]
    public void MissingAndOutOfRangeValuesAreFlagged()
    {
        var s = Lap();
        s[1] = s[1] with { Speed = 420, Throttle = 104 };  // 104 is OpenF1's invalid value
        s[2] = s[2] with { Speed = null };
        Assert.Equal(new Dictionary<string, int> { ["out_of_range_Speed"] = 1, ["out_of_range_Throttle"] = 1, ["missing_Speed"] = 1 },
                     ByCheck(s));
    }

    [Fact]
    public void LimitsAreInclusive()
    {
        var s = Lap();
        s[0] = s[0] with { Speed = 380, Rpm = 15500, Gear = 8, Throttle = 0, Brake = 100 };
        Assert.Empty(Validator.Run(s));
    }

    [Fact]
    public void RepeatedTimeAndALongGapAreFlaggedForASingleCar()
    {
        // One car alone cannot tell the feed from the car, so its gap counts as the car's.
        Assert.Equal(new Dictionary<string, int> { ["non_increasing_time"] = 1, ["gap_over_1s_car"] = 1 },
                     ByCheck(Lap(times: new[] { 0.0, 0.25, 0.25, 2.0 })));
    }

    [Fact]
    public void GapInBothCarsAtTheSameMomentIsTheFeeds()
    {
        var hul = Lap("HUL", times: new[] { 0.0, 0.25, 2.0, 2.25 });         // gap ends at 2.0 s
        var bor = Lap("BOR", times: new[] { 0.1, 0.35, 2.1, 5.0 });          // same gap, plus one of its own
        var found = Validator.Run(hul.Concat(bor).ToList());
        Assert.Equal(1, found[("HUL", 1, "gap_over_1s_feed")]);
        Assert.Equal(1, found[("BOR", 1, "gap_over_1s_feed")]);
        Assert.Equal(1, found[("BOR", 1, "gap_over_1s_car")]);
        Assert.Equal(3, found.Count);
    }

    [Fact]
    public void GapsMoreThanHalfASecondApartAreNotTheSameDropout()
    {
        var hul = Lap("HUL", times: new[] { 0.0, 0.25, 2.0 });
        var bor = Lap("BOR", times: new[] { 0.0, 0.25, 2.6 });  // 0.6 s later: a different dropout
        var found = ByCheck(hul.Concat(bor));
        Assert.Equal(new Dictionary<string, int> { ["gap_over_1s_car"] = 2 }, found);
    }

    [Fact]
    public void GapsAcrossLapsAreNotCounted()
    {
        // The time step is measured within a lap, as in the Python pipeline.
        var s = Lap().Concat(Lap(start: 10).Select(x => x with { Lap = 2 })).ToList();
        Assert.Empty(Validator.Run(s));
    }

    [Fact]
    public void CompareListsEveryDisagreement()
    {
        var python = new Dictionary<(string, int, string), int> { [("HUL", 3, "gap_over_1s_feed")] = 2, [("BOR", 3, "gap_over_1s_feed")] = 1 };
        var csharp = new Dictionary<(string, int, string), int> { [("HUL", 3, "gap_over_1s_feed")] = 2, [("BOR", 3, "gap_over_1s_car")] = 1 };
        Assert.Equal(new[] { "BOR lap 3 gap_over_1s_car: Python 0, C# 1", "BOR lap 3 gap_over_1s_feed: Python 1, C# 0" },
                     Validator.Compare(python, csharp));
        Assert.Empty(Validator.Compare(python, python));
    }

    [Fact]
    public void ReadsTheTablesThePythonPipelineWrites()
    {
        var path = Path.Combine(Path.GetTempPath(), $"f1check-{Guid.NewGuid()}.db");
        try
        {
            using (var con = new SqliteConnection($"Data Source={path}"))
            {
                con.Open();
                var cmd = con.CreateCommand();
                cmd.CommandText = """
                    CREATE TABLE samples (Driver TEXT, LapNumber INTEGER, SessionTimeS REAL, Speed INTEGER, RPM INTEGER,
                                          nGear INTEGER, Throttle INTEGER, Brake INTEGER);
                    INSERT INTO samples VALUES ('HUL', 2, 10.0, 300, 11000, 7, 100, 0), ('HUL', 2, 10.25, NULL, 11000, 7, 104, 0);
                    CREATE TABLE issues (Driver TEXT, LapNumber INTEGER, "Check" TEXT, Count INTEGER);
                    INSERT INTO issues VALUES ('HUL', 2, 'missing_Speed', 1), ('HUL', 2, 'out_of_range_Throttle', 1);
                    """;
                cmd.ExecuteNonQuery();
            }
            SqliteConnection.ClearAllPools();  // release the file so the checker can open it read-only
            var samples = Store.ReadSamples(path);
            Assert.Equal(2, samples.Count);
            Assert.Null(samples[1].Speed);
            Assert.Empty(Validator.Compare(Store.ReadIssues(path), Validator.Run(samples)));
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            File.Delete(path);
        }
    }

    [Fact]
    public void MissingDatabaseGivesAClearError() =>
        Assert.Throws<FileNotFoundException>(() => Store.ReadSamples("does-not-exist.db"));
}
