package library;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;

public class Library {
    private static final long MAX_FINE_CENTS = 1000;
    private final Map<String, LocalDate> dueDates = new HashMap<>();

    public void checkout(String isbn, LocalDate today) {
        dueDates.put(isbn, today.plusDays(14));
    }

    public void giveBack(String isbn) {
        dueDates.remove(isbn);
    }

    public long fineCents(String isbn, LocalDate today) {
        LocalDate due = dueDates.get(isbn);
        if (due == null || !today.isAfter(due)) return 0;
        return (today.toEpochDay() - due.toEpochDay()) * 25;
    }
}
