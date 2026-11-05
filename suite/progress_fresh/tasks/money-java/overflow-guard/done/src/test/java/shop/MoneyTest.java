package shop;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;

class MoneyTest {
    @Test
    void plusAdds() {
        assertEquals(350, new Money(100).plus(new Money(250)).cents());
    }

    @Test
    void overflowThrows() {
        assertThrows(ArithmeticException.class, () -> new Money(Long.MAX_VALUE).plus(new Money(1)));
        assertThrows(ArithmeticException.class, () -> new Money(Long.MIN_VALUE).minus(new Money(1)));
    }

    @Test
    void minusSubtracts() {
        assertEquals(150, new Money(250).minus(new Money(100)).cents());
    }
}
