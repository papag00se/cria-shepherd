using System.Globalization;

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
            var cat = e.Category.Contains(',') ? $"\"{e.Category.Replace("\"", "\"\"")}\"" : e.Category;
            lines.Add(string.Join(",", cat, e.Amount.ToString(CultureInfo.InvariantCulture),
                e.Date.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)));
        }
        return string.Join("\n", lines);
    }
}
