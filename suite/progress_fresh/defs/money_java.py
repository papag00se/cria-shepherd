from suite.progress_fresh.dsl import ed

SEED = {
"src/main/java/shop/Money.java": '''package shop;

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
        return (cents / 100) + "." + (cents % 100);
    }
}
''',
"src/test/java/shop/MoneyTest.java": '''package shop;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class MoneyTest {
    @Test
    void plusAdds() {
        assertEquals(350, new Money(100).plus(new Money(250)).cents());
    }
}
''',
}
M = SEED["src/main/java/shop/Money.java"]
T = SEED["src/test/java/shop/MoneyTest.java"]
TS_OLD = '        return (cents / 100) + "." + (cents % 100);'
TS_NEW = '''        String sign = cents < 0 ? "-" : "";
        long abs = Math.abs(cents);
        return String.format("%s%d.%02d", sign, abs / 100, abs % 100);'''
TASK = dict(extension=True, name="money-java", language="Java", seed=SEED,
unrelated={"src/main/java/shop/Money.java": M.replace("public final class", "/** Immutable amount in minor units. */\npublic final class")},
reqs=[
dict(id="to-string", text="Money.toString prints 5 cents as \"0.5\" and negative amounts wrongly. Format as two decimals with a leading minus for negatives (\"0.05\", \"-12.30\") and test those.",
 partial={"src/main/java/shop/Money.java": ed(M, (TS_OLD, '        return String.format("%d.%02d", cents / 100, cents % 100);')),
          "src/test/java/shop/MoneyTest.java": ed(T, ("    }\n}\n", '''    }

    @Test
    void formatsTwoDecimals() {
        assertEquals("0.05", new Money(5).toString());
        assertEquals("12.30", new Money(1230).toString());
    }
}
'''))},
 done={"src/main/java/shop/Money.java": ed(M, (TS_OLD, TS_NEW)),
       "src/test/java/shop/MoneyTest.java": ed(T, ("    }\n}\n", '''    }

    @Test
    void formatsTwoDecimals() {
        assertEquals("0.05", new Money(5).toString());
        assertEquals("12.30", new Money(1230).toString());
    }

    @Test
    void formatsNegatives() {
        assertEquals("-12.30", new Money(-1230).toString());
        assertEquals("-0.05", new Money(-5).toString());
    }
}
'''))}),
dict(id="equals-hash", text="Money values with the same cents should be equal and hash the same so they work in HashSet/HashMap; implement equals and hashCode and test equality and use as a map key.",
 partial={"src/main/java/shop/Money.java": ed(M, ("    @Override\n    public String toString", '''    @Override
    public boolean equals(Object o) {
        return o instanceof Money && ((Money) o).cents == cents;
    }

    @Override
    public String toString''')),
          "src/test/java/shop/MoneyTest.java": ed(T, ("    }\n}\n", '''    }

    @Test
    void equalAmountsAreEqual() {
        assertEquals(new Money(100), new Money(100));
    }
}
'''))},
 done={"src/main/java/shop/Money.java": ed(M, ("    @Override\n    public String toString", '''    @Override
    public boolean equals(Object o) {
        return o instanceof Money && ((Money) o).cents == cents;
    }

    @Override
    public int hashCode() {
        return Long.hashCode(cents);
    }

    @Override
    public String toString''')),
       "src/test/java/shop/MoneyTest.java": ed(T, ("import org.junit.jupiter.api.Test;", "import java.util.HashSet;\nimport java.util.Set;\nimport org.junit.jupiter.api.Test;"), ("    }\n}\n", '''    }

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
'''))}),
dict(id="overflow-guard", text="plus must not silently overflow: use Math.addExact so an overflow throws ArithmeticException, add minus(Money) with the same guarantee, and test the overflow.",
 partial={"src/main/java/shop/Money.java": ed(M, ("        return new Money(cents + other.cents);\n    }\n", "        return new Money(Math.addExact(cents, other.cents));\n    }\n\n    public Money minus(Money other) {\n        return new Money(cents - other.cents);\n    }\n")),
          "src/test/java/shop/MoneyTest.java": ed(T, ("import static org.junit.jupiter.api.Assertions.assertEquals;", "import static org.junit.jupiter.api.Assertions.assertEquals;\nimport static org.junit.jupiter.api.Assertions.assertThrows;"), ("    }\n}\n", '''    }

    @Test
    void overflowThrows() {
        assertThrows(ArithmeticException.class, () -> new Money(Long.MAX_VALUE).plus(new Money(1)));
    }

    @Test
    void minusSubtracts() {
        assertEquals(150, new Money(250).minus(new Money(100)).cents());
    }
}
'''))},
 done={"src/main/java/shop/Money.java": ed(M, ("        return new Money(cents + other.cents);\n    }\n", "        return new Money(Math.addExact(cents, other.cents));\n    }\n\n    public Money minus(Money other) {\n        return new Money(Math.subtractExact(cents, other.cents));\n    }\n")),
       "src/test/java/shop/MoneyTest.java": ed(T, ("import static org.junit.jupiter.api.Assertions.assertEquals;", "import static org.junit.jupiter.api.Assertions.assertEquals;\nimport static org.junit.jupiter.api.Assertions.assertThrows;"), ("    }\n}\n", '''    }

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
'''))}),
])
