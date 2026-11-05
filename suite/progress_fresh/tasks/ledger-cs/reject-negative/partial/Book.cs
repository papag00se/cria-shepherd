namespace Ledger;

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
