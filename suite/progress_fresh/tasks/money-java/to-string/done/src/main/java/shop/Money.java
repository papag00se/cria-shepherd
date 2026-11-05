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
        String sign = cents < 0 ? "-" : "";
        long abs = Math.abs(cents);
        return String.format("%s%d.%02d", sign, abs / 100, abs % 100);
    }
}
