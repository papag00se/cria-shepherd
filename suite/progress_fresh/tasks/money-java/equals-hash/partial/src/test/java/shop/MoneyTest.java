package shop;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class MoneyTest {
    @Test
    void plusAdds() {
        assertEquals(350, new Money(100).plus(new Money(250)).cents());
    }

    @Test
    void equalAmountsAreEqual() {
        assertEquals(new Money(100), new Money(100));
    }
}
