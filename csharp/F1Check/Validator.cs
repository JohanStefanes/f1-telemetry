namespace F1Check;

/// <summary>One telemetry sample as the Python pipeline stores it in the `samples` table.</summary>
public sealed record Sample(string Driver, int Lap, double Time, double? Speed, double? Rpm, double? Gear,
                           double? Throttle, double? Brake);

/// <summary>
/// The validation rules of the Python pipeline (f1telemetry/pipeline.py), written again from scratch,
/// so the two implementations can check each other.
/// </summary>
public static class Validator
{
    public const double MaxGapS = 1.0;  // car data arrives at ~4 Hz; a longer gap is a dropout
    public const double MatchS = 0.5;   // gaps in different cars this close together are the same feed dropout

    // Physical limits for an F1 car (OpenF1 sends 104 for an invalid throttle or brake value).
    static readonly (string Name, Func<Sample, double?> Value, double Lo, double Hi)[] Channels =
    {
        ("Speed", s => s.Speed, 0, 380),
        ("RPM", s => s.Rpm, 0, 15500),
        ("nGear", s => s.Gear, 0, 8),
        ("Throttle", s => s.Throttle, 0, 100),
        ("Brake", s => s.Brake, 0, 100),
    };

    /// <summary>Flagged samples per (driver, lap, check), the same shape as the Python `issues` table.</summary>
    public static Dictionary<(string Driver, int Lap, string Check), int> Run(IReadOnlyList<Sample> samples)
    {
        var counts = new Dictionary<(string, int, string), int>();
        void Flag(Sample s, string check) =>
            counts[(s.Driver, s.Lap, check)] = counts.GetValueOrDefault((s.Driver, s.Lap, check)) + 1;

        foreach (var s in samples)
            foreach (var (name, value, lo, hi) in Channels)
            {
                var v = value(s);
                if (v is null) Flag(s, $"missing_{name}");
                else if (v < lo || v > hi) Flag(s, $"out_of_range_{name}");
            }

        // Time step to the previous sample of the same driver and lap, in stored order.
        var gaps = new List<Sample>();
        var previous = new Dictionary<(string, int), double>();
        foreach (var s in samples)
        {
            if (previous.TryGetValue((s.Driver, s.Lap), out var before))
            {
                var dt = s.Time - before;
                if (dt <= 0) Flag(s, "non_increasing_time");
                if (dt > MaxGapS) gaps.Add(s);
            }
            previous[(s.Driver, s.Lap)] = s.Time;
        }

        // A gap is the feed's when every other car has a gap at the same moment; one car alone cannot tell.
        var drivers = samples.Select(s => s.Driver).Distinct().ToList();
        var gapTimes = drivers.ToDictionary(d => d, d => gaps.Where(g => g.Driver == d).Select(g => g.Time).ToList());
        foreach (var g in gaps)
        {
            var feed = drivers.Count > 1 && drivers.Where(d => d != g.Driver)
                .All(d => gapTimes[d].Any(t => Math.Abs(t - g.Time) <= MatchS));
            Flag(g, feed ? "gap_over_1s_feed" : "gap_over_1s_car");
        }
        return counts;
    }

    /// <summary>Every (driver, lap, check) where the two sets of counts disagree, in readable form.</summary>
    public static List<string> Compare(IReadOnlyDictionary<(string Driver, int Lap, string Check), int> expected,
                                       IReadOnlyDictionary<(string Driver, int Lap, string Check), int> actual)
    {
        return expected.Keys.Union(actual.Keys)
            .Where(k => expected.GetValueOrDefault(k) != actual.GetValueOrDefault(k))
            .OrderBy(k => k.Driver).ThenBy(k => k.Lap).ThenBy(k => k.Check)
            .Select(k => $"{k.Driver} lap {k.Lap} {k.Check}: Python {expected.GetValueOrDefault(k)}, C# {actual.GetValueOrDefault(k)}")
            .ToList();
    }
}
