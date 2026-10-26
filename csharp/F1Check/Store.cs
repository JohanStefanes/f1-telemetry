using Microsoft.Data.Sqlite;

namespace F1Check;

/// <summary>Reads the tables the Python pipeline writes to telemetry.db.</summary>
public static class Store
{
    public static List<Sample> ReadSamples(string dbPath)
    {
        using var con = Open(dbPath);
        using var cmd = con.CreateCommand();
        // rowid keeps the order the pipeline wrote, which is the order its time-step check uses
        cmd.CommandText = "SELECT Driver, LapNumber, SessionTimeS, Speed, RPM, nGear, Throttle, Brake FROM samples ORDER BY rowid";
        using var r = cmd.ExecuteReader();
        var samples = new List<Sample>();
        double? Num(int i) => r.IsDBNull(i) ? null : r.GetDouble(i);
        while (r.Read())
            samples.Add(new Sample(r.GetString(0), r.GetInt32(1), r.GetDouble(2), Num(3), Num(4), Num(5), Num(6), Num(7)));
        return samples;
    }

    public static Dictionary<(string Driver, int Lap, string Check), int> ReadIssues(string dbPath)
    {
        using var con = Open(dbPath);
        using var cmd = con.CreateCommand();
        cmd.CommandText = "SELECT Driver, LapNumber, \"Check\", Count FROM issues";
        using var r = cmd.ExecuteReader();
        var issues = new Dictionary<(string, int, string), int>();
        while (r.Read())
            issues[(r.GetString(0), r.GetInt32(1), r.GetString(2))] = r.GetInt32(3);
        return issues;
    }

    static SqliteConnection Open(string dbPath)
    {
        if (!File.Exists(dbPath))
            throw new FileNotFoundException($"No database at {dbPath}; run the Python pipeline first.");
        var con = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = dbPath, Mode = SqliteOpenMode.ReadOnly }.ToString());
        con.Open();
        return con;
    }
}
