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
    public String toString() {
        return String.format("%d.%02d", cents / 100, cents % 100);
    }
}
