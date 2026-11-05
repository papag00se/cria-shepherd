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
        return new Money(Math.addExact(cents, other.cents));
    }

    public Money minus(Money other) {
        return new Money(Math.subtractExact(cents, other.cents));
    }

    @Override
    public String toString() {
        return (cents / 100) + "." + (cents % 100);
    }
}
