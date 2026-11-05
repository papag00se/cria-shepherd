package shop;

public final class Money {
    private final long cents;

    public Money(long cents) {
        this.cents = cents;
    }

    public long cents() {
        return cents;
    }

    public Money plus(Money other) {
        return new Money(cents + other.cents);
    }

    @Override
    public boolean equals(Object o) {
        return o instanceof Money && ((Money) o).cents == cents;
    }

    @Override
    public int hashCode() {
        return Long.hashCode(cents);
    }

    @Override
    public String toString() {
        return (cents / 100) + "." + (cents % 100);
    }
}
