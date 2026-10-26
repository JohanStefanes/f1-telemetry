// F1Check: re-runs the pipeline's validation in C# and fails if it disagrees with Python's `issues` table.
// Usage: dotnet run --project csharp/F1Check -- telemetry.db
using System.Globalization;
using F1Check;

CultureInfo.CurrentCulture = CultureInfo.InvariantCulture;  // same number format on every machine
var dbPath = args.Length > 0 ? args[0] : "telemetry.db";
try
{
    var samples = Store.ReadSamples(dbPath);
    var python = Store.ReadIssues(dbPath);
    var csharp = Validator.Run(samples);
    var mismatches = Validator.Compare(python, csharp);

    int Total(string prefix) => csharp.Where(kv => kv.Key.Check.StartsWith(prefix)).Sum(kv => kv.Value);
    Console.WriteLine($"Samples checked:        {samples.Count:N0} ({string.Join(", ", samples.Select(s => s.Driver).Distinct())})");
    Console.WriteLine($"Flagged by C#:          {csharp.Values.Sum():N0} in {csharp.Count} driver/lap/check groups");
    Console.WriteLine($"Flagged by Python:      {python.Values.Sum():N0} in {python.Count} driver/lap/check groups");
    Console.WriteLine($"Dropouts, feed / car:   {Total("gap_over_1s_feed")} / {Total("gap_over_1s_car")}");
    Console.WriteLine($"Missing / out of range: {Total("missing_")} / {Total("out_of_range_")}");

    if (mismatches.Count == 0)
    {
        Console.WriteLine("Result: C# and Python agree on every check.");
        return 0;
    }
    Console.WriteLine($"Result: {mismatches.Count} disagreement{(mismatches.Count == 1 ? "" : "s")}:");
    foreach (var m in mismatches.Take(20)) Console.WriteLine("  " + m);
    return 1;
}
catch (Exception e) when (e is FileNotFoundException or Microsoft.Data.Sqlite.SqliteException)
{
    Console.Error.WriteLine(e.Message);
    return 2;
}
