package shop;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.HashSet;
import java.util.Set;
import org.junit.jupiter.api.Test;

class MoneyTest {
    @Test
    void plusAdds() {
        assertEquals(350, new Money(100).plus(new Money(250)).cents());
    }

    @Test
    void equalAmountsAreEqualAndHashAlike() {
        assertEquals(new Money(100), new Money(100));
        assertEquals(new Money(100).hashCode(), new Money(100).hashCode());
        Set<Money> s = new HashSet<>();
        s.add(new Money(100));
        s.add(new Money(100));
        assertEquals(1, s.size());
    }
}
