using Ledger;
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
