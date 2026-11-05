package shop;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class MoneyTest {
    @Test
    void plusAdds() {
        assertEquals(350, new Money(100).plus(new Money(250)).cents());
    }

    @Test
    void formatsTwoDecimals() {
        assertEquals("0.05", new Money(5).toString());
        assertEquals("12.30", new Money(1230).toString());
    }
}
