namespace Ledger;

/// <summary>One spend.</summary>
public record Expense(string Category, decimal Amount, DateOnly Date);
