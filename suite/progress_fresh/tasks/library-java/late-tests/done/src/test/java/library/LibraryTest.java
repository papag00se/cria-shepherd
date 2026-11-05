package library;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.time.LocalDate;
import org.junit.jupiter.api.Test;

class LibraryTest {
    @Test
    void noFineWhenOnTime() {
        Library l = new Library();
        l.checkout("1", LocalDate.of(2024, 1, 1));
        assertEquals(0, l.fineCents("1", LocalDate.of(2024, 1, 15)));
    }

    @Test
    void oneDayLateIs25Cents() {
        Library l = new Library();
        l.checkout("1", LocalDate.of(2024, 1, 1));
        assertEquals(25, l.fineCents("1", LocalDate.of(2024, 1, 16)));
    }

    @Test
    void neverCheckedOutIsZero() {
        assertEquals(0, new Library().fineCents("9", LocalDate.of(2024, 6, 1)));
    }

    @Test
    void noFineAfterGiveBack() {
        Library l = new Library();
        l.checkout("1", LocalDate.of(2024, 1, 1));
        l.giveBack("1");
        assertEquals(0, l.fineCents("1", LocalDate.of(2024, 3, 1)));
    }
}
