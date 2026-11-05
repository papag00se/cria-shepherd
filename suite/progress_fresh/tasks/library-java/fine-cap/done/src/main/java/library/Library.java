package library;

import java.time.LocalDate;
import java.util.HashMap;
import java.util.Map;

public class Library {
    static final long MAX_FINE_CENTS = 1000;
    private static final long DAILY_FINE_CENTS = 25;
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
        long days = today.toEpochDay() - due.toEpochDay();
        return Math.min(days * DAILY_FINE_CENTS, MAX_FINE_CENTS);
    }
}
