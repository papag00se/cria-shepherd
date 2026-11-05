namespace Ledger;

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
