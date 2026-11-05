TASK = dict(name="ledger-cs", language="C#", seed={
"Ledger.csproj": '<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n    <TargetFramework>net8.0</TargetFramework>\n    <Nullable>enable</Nullable>\n  </PropertyGroup>\n</Project>\n',
"Ledger.Tests/Ledger.Tests.csproj": '<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n    <TargetFramework>net8.0</TargetFramework>\n  </PropertyGroup>\n  <ItemGroup>\n    <PackageReference Include="xunit" Version="2.8.0" />\n    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.10.0" />\n    <ProjectReference Include="../Ledger.csproj" />\n  </ItemGroup>\n</Project>\n',
"Expense.cs": '''namespace Ledger;

public record Expense(string Category, decimal Amount, DateOnly Date);
''',
"Book.cs": '''namespace Ledger;

public class Book
{
    private readonly List<Expense> _items = new();

    public void Add(Expense e) => _items.Add(e);

    public decimal Total() => _items.Sum(e => e.Amount);

    public Dictionary<string, decimal> ByCategory() =>
        _items.GroupBy(e => e.Category).ToDictionary(g => g.Key, g => g.Sum(e => e.Amount));
}
''',
"Ledger.Tests/BookTests.cs": '''using Ledger;
using Xunit;

public class BookTests
{
    [Fact]
    public void TotalSumsAmounts()
    {
        var b = new Book();
        b.Add(new Expense("food", 3m, new DateOnly(2024, 1, 1)));
        b.Add(new Expense("food", 4m, new DateOnly(2024, 1, 2)));
        Assert.Equal(7m, b.Total());
    }
}
''',
}, unrelated={"Expense.cs": '''namespace Ledger;

/// <summary>One spend.</summary>
public record Expense(string Category, decimal Amount, DateOnly Date);
'''},
reqs=[
dict(id="reject-negative", text="Book.Add must reject an expense with a negative or zero amount by throwing ArgumentOutOfRangeException, without adding it.",
 partial={"Book.cs": '''namespace Ledger;

public class Book
{
    private readonly List<Expense> _items = new();

    public void Add(Expense e)
    {
        if (e.Amount < 0) throw new ArgumentOutOfRangeException(nameof(e));
        _items.Add(e);
    }

    public decimal Total() => _items.Sum(e => e.Amount);

    public Dictionary<string, decimal> ByCategory() =>
        _items.GroupBy(e => e.Category).ToDictionary(g => g.Key, g => g.Sum(e => e.Amount));
}
'''},
 done={"Book.cs": '''namespace Ledger;

public class Book
{
    private readonly List<Expense> _items = new();

    public void Add(Expense e)
    {
        if (e.Amount <= 0) throw new ArgumentOutOfRangeException(nameof(e), "amount must be positive");
        _items.Add(e);
    }

    public decimal Total() => _items.Sum(e => e.Amount);

    public Dictionary<string, decimal> ByCategory() =>
        _items.GroupBy(e => e.Category).ToDictionary(g => g.Key, g => g.Sum(e => e.Amount));
}
'''}),
dict(id="month-filter", text="Add Book.TotalForMonth(int year, int month) returning the sum of expenses dated in that calendar month, plus a test that checks an expense on the last day of the month is included and one on the first day of the next month is not.",
 partial={"Book.cs": '''namespace Ledger;

public class Book
{
    private readonly List<Expense> _items = new();

    public void Add(Expense e) => _items.Add(e);

    public decimal Total() => _items.Sum(e => e.Amount);

    public decimal TotalForMonth(int year, int month) =>
        _items.Where(e => e.Date.Year == year && e.Date.Month == month).Sum(e => e.Amount);

    public Dictionary<string, decimal> ByCategory() =>
        _items.GroupBy(e => e.Category).ToDictionary(g => g.Key, g => g.Sum(e => e.Amount));
}
'''},
 done={"Book.cs": '''namespace Ledger;

public class Book
{
    private readonly List<Expense> _items = new();

    public void Add(Expense e) => _items.Add(e);

    public decimal Total() => _items.Sum(e => e.Amount);

    public decimal TotalForMonth(int year, int month) =>
        _items.Where(e => e.Date.Year == year && e.Date.Month == month).Sum(e => e.Amount);

    public Dictionary<string, decimal> ByCategory() =>
        _items.GroupBy(e => e.Category).ToDictionary(g => g.Key, g => g.Sum(e => e.Amount));
}
''', "Ledger.Tests/BookTests.cs": '''using Ledger;
using Xunit;

public class BookTests
{
    [Fact]
    public void TotalSumsAmounts()
    {
        var b = new Book();
        b.Add(new Expense("food", 3m, new DateOnly(2024, 1, 1)));
        b.Add(new Expense("food", 4m, new DateOnly(2024, 1, 2)));
        Assert.Equal(7m, b.Total());
    }

    [Fact]
    public void MonthBoundariesAreInclusiveAndExclusive()
    {
        var b = new Book();
        b.Add(new Expense("a", 1m, new DateOnly(2024, 1, 31)));
        b.Add(new Expense("a", 10m, new DateOnly(2024, 2, 1)));
        Assert.Equal(1m, b.TotalForMonth(2024, 1));
        Assert.Equal(10m, b.TotalForMonth(2024, 2));
    }
}
'''}),
dict(id="csv-export", text="Add Book.ToCsv() that returns a header line `category,amount,date` followed by one line per expense in insertion order, with the date in ISO yyyy-MM-dd and the amount using the invariant culture; categories containing commas must be quoted.",
 partial={"Book.cs": '''namespace Ledger;

public class Book
{
    private readonly List<Expense> _items = new();

    public void Add(Expense e) => _items.Add(e);

    public decimal Total() => _items.Sum(e => e.Amount);

    public Dictionary<string, decimal> ByCategory() =>
        _items.GroupBy(e => e.Category).ToDictionary(g => g.Key, g => g.Sum(e => e.Amount));

    public string ToCsv()
    {
        var lines = new List<string> { "category,amount,date" };
        foreach (var e in _items) lines.Add($"{e.Category},{e.Amount},{e.Date}");
        return string.Join("\\n", lines);
    }
}
'''},
 done={"Book.cs": '''using System.Globalization;

namespace Ledger;

public class Book
{
    private readonly List<Expense> _items = new();

    public void Add(Expense e) => _items.Add(e);

    public decimal Total() => _items.Sum(e => e.Amount);

    public Dictionary<string, decimal> ByCategory() =>
        _items.GroupBy(e => e.Category).ToDictionary(g => g.Key, g => g.Sum(e => e.Amount));

    public string ToCsv()
    {
        var lines = new List<string> { "category,amount,date" };
        foreach (var e in _items)
        {
            var cat = e.Category.Contains(',') ? $"\\"{e.Category.Replace("\\"", "\\"\\"")}\\"" : e.Category;
            lines.Add(string.Join(",", cat, e.Amount.ToString(CultureInfo.InvariantCulture),
                e.Date.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)));
        }
        return string.Join("\\n", lines);
    }
}
'''}),
])
